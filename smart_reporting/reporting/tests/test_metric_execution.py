"""真实SQL与宿主机工作区核对计算/数据集身份；不代替StarRocks验收。"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from agno.run import RunContext
from sqlglot import parse_one

from smart_reporting.reporting.data_source.materialization import CsvMaterializer
from smart_reporting.reporting.data_sources import ReportDatasetStore
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.tests.test_metric_compilation import (
    catalog,
    definitions,
    policy,
    request,
)
from smart_reporting.reporting.tests.test_metric_compilation import warehouse as warehouse
from smart_reporting.reporting.tests.test_reporting_host_workspace import SECRET, _scope

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def execution_context(tmp_path, warehouse):
    class SqlSource:
        config = SimpleNamespace(id="warehouse", database="test", limits=SimpleNamespace(query_concurrency=1, max_bytes=1000000))
        async def materialize_bound(self, sql, parameters, *, max_bytes=None):
            cursor = warehouse.execute(parse_one(sql, read="mysql").sql(dialect="duckdb"), parameters)
            writer = CsvMaterializer(tuple(column[0] for column in cursor.description), max_bytes=max_bytes)
            writer.append(tuple(cursor.fetchall()))
            return writer.finish()
    registry = ReportingWorkspaceRegistry(tmp_path, secret=SECRET)
    registry.resolve(_scope(run_id="run-1", workspace_key="workspace-1"))
    router = ReportingWorkspaceRouter(registry)
    return {"warehouse": SqlSource()}, ReportDatasetStore(router), RunContext(run_id="run-1", session_id="workspace-1", session_state={})


async def test_execute_ratio_registers_actual_csv_and_precise_dependency_results(execution_context):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    adapters, datasets, context = execution_context
    plan = compile_metric(request("rate"), policy("rate"), definitions(), catalog())
    receipt = await execute_metric(plan, adapters, datasets=datasets, run_context=context, calculation_id="calculation-1")
    by_metric = {result.metric_version.metric_id: result for result in receipt.results}
    assert by_metric["budget"].value == Decimal(300)
    assert by_metric["actual"].value == Decimal(190)
    assert by_metric["rate"].value == Decimal(190) / Decimal(300) * 100
    assert by_metric["rate"].status == "computed"
    assert len(receipt.datasets) == 2
    paths = await datasets.resolve_dataset_paths(by_metric["rate"].dataset_ids, run_context=context)
    assert len(paths) == 2
    content = [await datasets.service.afile_bytes(context.session_id, path) for path in paths]
    assert any(b"300.00" in body for body, _ in content)
    assert all(result.basis_id == "basis-1" and result.calculation_id == "calculation-1" for result in receipt.results)


@pytest.mark.parametrize("mutation,issue", [("UPDATE test.budget SET amount=0", "zero_denominator"),
    ("DELETE FROM test.actual", "missing_data"), ("UPDATE test.actual SET amount=NULL", "null_observations")])
async def test_invalid_inputs_never_become_zero_rate(execution_context, warehouse, mutation, issue):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    warehouse.execute(mutation)
    adapters, datasets, context = execution_context
    receipt = await execute_metric(compile_metric(request("rate"), policy("rate"), definitions(), catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calculation-1")
    rate = next(result for result in receipt.results if result.metric_version.metric_id == "rate")
    assert rate.value is None and rate.status == "unavailable"
    assert issue in rate.issue_codes


async def test_unmatched_ratio_groups_are_retained_with_specific_reason(execution_context, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    warehouse.execute("DELETE FROM test.actual WHERE project_id='B'")
    warehouse.execute("INSERT INTO test.actual VALUES ('C',50,'2026-01-10')")
    adapters, datasets, context = execution_context
    plan = compile_metric(request("rate", dimensions=["project"]), policy("rate"), definitions(), catalog())
    receipt = await execute_metric(plan, adapters, datasets=datasets, run_context=context, calculation_id="calculation-1")
    rates = {result.dimensions[0].value: result for result in receipt.results if result.metric_version.metric_id == "rate"}
    assert set(rates) == {"A", "B", "C"}
    assert rates["A"].value == Decimal(90)
    for group in ("B", "C"):
        assert rates[group].value is None and "unmatched_groups" in rates[group].issue_codes
    readiness = next(item for item in receipt.readiness if item.metric_version.metric_id == "rate")
    unmatched = {(item.side, item.dimensions[0].value): item.value for item in readiness.unmatched_groups}
    assert unmatched == {("denominator", "B"): Decimal(200), ("numerator", "C"): Decimal(50)}
    assert "unmatched_groups" in readiness.issue_codes
    assert all(set(item.fact_refs).issubset({result.fact_id for result in receipt.results}) for item in readiness.unmatched_groups)


async def test_unavailable_grouped_plan_retains_reason_without_querying(execution_context):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    adapters, datasets, context = execution_context
    plan = compile_metric(request(dimensions=["department"]), policy(), definitions(), catalog())
    receipt = await execute_metric(plan, adapters, datasets=datasets, run_context=context, calculation_id="calculation-1")
    assert receipt.datasets == ()
    assert len(receipt.results) == 1 and receipt.results[0].value is None
    assert receipt.results[0].issue_codes == ("grain_not_supported",)


async def test_grouped_database_failure_returns_unavailable_and_no_staged_files(execution_context, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    warehouse.execute("DROP TABLE test.actual")
    adapters, datasets, context = execution_context
    plan = compile_metric(request("rate", dimensions=["project"]), policy("rate"), definitions(), catalog())
    receipt = await execute_metric(plan, adapters, datasets=datasets, run_context=context, calculation_id="calculation-1")
    assert receipt.datasets == () and receipt.results[0].value is None
    assert "metric_query_failed" in receipt.results[0].issue_codes
    root = datasets.service.registry.get("workspace-1").root
    assert list(root.rglob("*.csv")) == []


async def test_empty_grouped_ratio_retains_missing_data_without_inventing_groups(execution_context, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    warehouse.execute("DELETE FROM test.actual")
    warehouse.execute("DELETE FROM test.budget")
    adapters, datasets, context = execution_context
    receipt = await execute_metric(compile_metric(request("rate", dimensions=["project"]), policy("rate"), definitions(), catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calculation-1")
    rate = next(result for result in receipt.results if result.metric_version.metric_id == "rate")
    assert rate.value is None and rate.dimensions == () and rate.status == "unavailable"
    assert "missing_data" in rate.issue_codes and len(rate.dataset_ids) == 2


async def test_null_and_empty_dimension_values_do_not_merge(execution_context, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    warehouse.execute("INSERT INTO test.actual VALUES (NULL,10,'2026-01-03'),('',20,'2026-01-03')")
    adapters, datasets, context = execution_context
    receipt = await execute_metric(compile_metric(request("actual", dimensions=["project"]), policy("actual"), definitions(), catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calculation-1")
    values = {result.dimensions[0].value: result.value for result in receipt.results}
    assert values == {"A": Decimal(90), "B": Decimal(100), None: Decimal(10), "": Decimal(20)}


async def test_real_sql_readiness_detects_missing_month_and_expected_group(execution_context, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    warehouse.execute("INSERT INTO test.actual VALUES ('C',10,'2026-03-01')")
    periods = [{"start": "2026-01-01", "end": "2026-02-01"}, {"start": "2026-02-01", "end": "2026-03-01"}, {"start": "2026-03-01", "end": "2026-04-01"}]
    selected = policy("actual", readinessPolicy={"expectedPeriods": periods,
        "expectedGroups": [[{"dimensionId": "project", "value": value}] for value in ("A", "B", "D")]})
    adapters, datasets, context = execution_context
    receipt = await execute_metric(compile_metric(request("actual", period={"start": "2026-01-01", "end": "2026-04-01"}), selected, definitions(), catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calculation-1")
    assert len(receipt.readiness) == 1
    readiness = receipt.readiness[0]
    assert {"missing_period_observations", "missing_group_observations"}.issubset(readiness.issue_codes)
    assert receipt.results[0].value == Decimal(200)
    assert "missing_period_observations" in receipt.results[0].issue_codes
    assert all(check.fact_refs for check in readiness.checks)
    assert set(readiness.checks[0].fact_refs).issubset({item.fact_id for item in receipt.results})


async def test_real_sql_readiness_keeps_covered_zero_distinct_from_empty(execution_context, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    warehouse.execute("UPDATE test.actual SET amount=0")
    selected = policy("actual", readinessPolicy={"expectedPeriods": [{"start": "2026-01-01", "end": "2026-02-01"}],
        "expectedGroups": [[{"dimensionId": "project", "value": value}] for value in ("A", "B")]})
    adapters, datasets, context = execution_context
    receipt = await execute_metric(compile_metric(request("actual"), selected, definitions(), catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calculation-1")
    checks = {item.name: item.status for item in receipt.readiness[0].checks}
    assert checks["period_coverage"] == checks["group_coverage"] == "pass"
    assert receipt.results[0].value == Decimal(0) and receipt.results[0].status == "computed"


async def test_incomplete_input_coverage_does_not_produce_verified_ratio(execution_context, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    selected = policy("rate", readinessPolicy={"expectedPeriods": [
        {"start": "2026-01-01", "end": "2026-02-01"},
        {"start": "2026-02-01", "end": "2026-03-01"}]})
    adapters, datasets, context = execution_context
    receipt = await execute_metric(compile_metric(request("rate", period={"start": "2026-01-01", "end": "2026-03-01"}), selected, definitions(), catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calculation-1")
    rate = next(item for item in receipt.results if item.metric_version.metric_id == "rate")
    assert rate.value is None and rate.status == "unavailable"
    assert "missing_period_observations" in rate.issue_codes
    assert any(item.value is not None for item in receipt.results if item.metric_version.metric_id != "rate")


async def test_missing_readiness_rules_are_explicit_in_execution_receipt(execution_context):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    adapters, datasets, context = execution_context
    receipt = await execute_metric(compile_metric(request(), policy(), definitions(), catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calculation-1")
    assert len(receipt.readiness) == 1
    assert receipt.readiness[0].issue_codes == ("data_readiness_unknown",)


async def test_invalid_calculation_identity_is_rejected_before_materialization(execution_context):
    from pydantic import ValidationError

    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    adapters, datasets, context = execution_context
    with pytest.raises(ValidationError):
        await execute_metric(compile_metric(request(), policy(), definitions(), catalog()),
            adapters, datasets=datasets, run_context=context, calculation_id="invalid identity")
    assert list(datasets.service.registry.get("workspace-1").root.rglob("*.csv")) == []


async def test_numeric_dimensions_retain_registered_type_through_csv(execution_context, warehouse):
    from smart_reporting.reporting.contract import ModelColumn
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    warehouse.execute("DROP TABLE test.actual")
    warehouse.execute("CREATE TABLE test.actual(project_id INTEGER, amount DECIMAL(18,2), period DATE)")
    warehouse.execute("INSERT INTO test.actual VALUES (1,10,'2026-01-01'),(2,20,'2026-01-01')")
    tables = tuple(table.model_copy(update={"columns": tuple(ModelColumn(name=column.name, dataType="INTEGER", nullable=True)
        if column.name == "project_id" else column for column in table.columns)}) for table in catalog())
    adapters, datasets, context = execution_context
    receipt = await execute_metric(compile_metric(request("actual", dimensions=["project"]), policy("actual"), definitions(), tables),
        adapters, datasets=datasets, run_context=context, calculation_id="calc-numeric")
    assert {item.dimensions[0].value: item.value for item in receipt.results} == {1: Decimal(10), 2: Decimal(20)}
    assert all(type(item.dimensions[0].value) is int for item in receipt.results)


async def test_equal_numbers_do_not_merge_different_basis_or_filter_identities(execution_context):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    adapters, datasets, context = execution_context
    results = []
    for selected in (request(), request(basisId="basis-other"), request(filterValues=[
        {"fieldRef": "warehouse.test.budget.project_id", "operator": "in", "values": ["A", "B"]}])):
        receipt = await execute_metric(compile_metric(selected, policy(), definitions(), catalog()),
            adapters, datasets=datasets, run_context=context, calculation_id="calc-identity")
        results.append(receipt.results[0])
    assert all(item.value == Decimal(300) for item in results)
    assert len({item.fact_id for item in results}) == 3
    assert len({item.dataset_ids for item in results}) == 3


async def test_cancelled_metric_query_preserves_cancellation_and_cleans_staging(execution_context, monkeypatch):
    import asyncio

    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    adapters, datasets, context = execution_context
    started = asyncio.Event()
    async def pending_query(sql, parameters, *, max_bytes=None):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(adapters["warehouse"], "materialize_bound", pending_query)
    task = asyncio.create_task(execute_metric(compile_metric(request(), policy(), definitions(), catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calc-cancel"))
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)
    root = datasets.service.registry.get("workspace-1").root
    assert list(root.rglob("*.csv")) == []
    assert not any(path.name.startswith(".staging-") for path in root.rglob("*"))
