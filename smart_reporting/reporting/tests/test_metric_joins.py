"""维度关联必须先证明多对一；真实SQL核对金额不被重复维度放大。"""

from decimal import Decimal

import pytest

from smart_reporting.reporting.contract import ModelColumn, ModelTable
from smart_reporting.reporting.semantics.models import MetricDefinition
from smart_reporting.reporting.tests.test_metric_compilation import (
    catalog,
    definitions,
    policy,
    request,
)
from smart_reporting.reporting.tests.test_metric_compilation import warehouse as warehouse
from smart_reporting.reporting.tests.test_metric_execution import anyio_backend as anyio_backend
from smart_reporting.reporting.tests.test_metric_execution import (
    execution_context as execution_context,
)

pytestmark = pytest.mark.anyio


def joined_definitions():
    return tuple(MetricDefinition.model_validate({**metric.model_dump(by_alias=True),
        "dimensions": [*metric.model_dump(by_alias=True)["dimensions"], {"id": "department", "fieldRef": "warehouse.test.projects.department"}]})
        for metric in definitions())


def joined_policy():
    return policy("rate", joins=[{"leftKeys": [f"warehouse.test.{table}.project_id"],
        "rightKeys": ["warehouse.test.projects.project_id"], "outputGrain": ["project"]}
        for table in ("budget", "actual")])


def joined_catalog():
    return (*catalog(), ModelTable(sourceId="warehouse", database="test", name="projects", columns=(
        ModelColumn(name="project_id", dataType="VARCHAR", nullable=False),
        ModelColumn(name="department", dataType="VARCHAR", nullable=False))))


def create_dimension(warehouse):
    warehouse.execute("CREATE TABLE test.projects(project_id VARCHAR, department VARCHAR)")
    warehouse.execute("INSERT INTO test.projects VALUES ('A','X'),('B','Y'),('UNUSED','Z')")


async def test_registered_dimension_join_aggregates_independent_facts(execution_context, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    create_dimension(warehouse)
    adapters, datasets, context = execution_context
    plan = compile_metric(request("rate", dimensions=["department"]), joined_policy(), joined_definitions(), joined_catalog())
    assert plan.issues == ()
    receipt = await execute_metric(plan, adapters, datasets=datasets, run_context=context, calculation_id="calc-join")
    rates = {item.dimensions[0].value: item.value for item in receipt.results if item.metric_version.metric_id == "rate"}
    assert rates == {"X": Decimal(90), "Y": Decimal(50)}
    assert sum(item.value for item in receipt.results if item.metric_version.metric_id == "budget") == Decimal(300)


async def test_duplicate_dimension_keys_are_unavailable_before_fact_query(execution_context, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    create_dimension(warehouse)
    warehouse.execute("INSERT INTO test.projects VALUES ('B','OTHER')")
    adapters, datasets, context = execution_context
    receipt = await execute_metric(compile_metric(request("rate", dimensions=["department"]), joined_policy(), joined_definitions(), joined_catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calc-join")
    assert len(receipt.results) == 1 and receipt.results[0].value is None
    assert "join_fanout" in receipt.results[0].issue_codes
    assert receipt.datasets
    assert all("SUM(" not in handle.query_sql.upper() for handle in receipt.datasets)


async def test_missing_dimension_row_keeps_fact_amount_and_discloses_unmatched_key(execution_context, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    create_dimension(warehouse)
    warehouse.execute("DELETE FROM test.projects WHERE project_id='B'")
    adapters, datasets, context = execution_context
    receipt = await execute_metric(compile_metric(request("rate", dimensions=["department"]), joined_policy(), joined_definitions(), joined_catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calc-join")
    budget = [item for item in receipt.results if item.metric_version.metric_id == "budget"]
    assert sum(item.value for item in budget) == Decimal(300)
    missing = next(item for item in budget if item.dimensions[0].value is None)
    assert missing.value == Decimal(200) and "unmatched_dimension_keys" in missing.issue_codes


async def test_dimension_duplicates_after_preflight_cannot_inflate_results(execution_context, warehouse, monkeypatch):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    create_dimension(warehouse)
    adapters, datasets, context = execution_context
    original = adapters["warehouse"].materialize_bound
    changed = False
    async def concurrent_write(sql, parameters, *, max_bytes=None):
        nonlocal changed
        if "SUM(" in sql.upper() and not changed:
            warehouse.execute("INSERT INTO test.projects VALUES ('B','OTHER')")
            changed = True
        return await original(sql, parameters, max_bytes=max_bytes)
    monkeypatch.setattr(adapters["warehouse"], "materialize_bound", concurrent_write)
    receipt = await execute_metric(compile_metric(request("rate", dimensions=["department"]), joined_policy(), joined_definitions(), joined_catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calc-race")
    affected = [item for item in receipt.results if "join_fanout" in item.issue_codes]
    assert changed and affected
    assert all(item.value is None for item in affected)
    assert all(item.value is None or item.value <= Decimal(300) for item in receipt.results)


async def test_dimension_filter_is_parameterized_and_applies_to_both_facts(execution_context, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    create_dimension(warehouse)
    selected = request("rate", filterValues=[{"fieldRef": "warehouse.test.projects.department", "operator": "eq", "values": ["X"]}])
    adapters, datasets, context = execution_context
    receipt = await execute_metric(compile_metric(selected, joined_policy(), joined_definitions(), joined_catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calc-filter")
    rate = next(item for item in receipt.results if item.metric_version.metric_id == "rate")
    assert rate.value == Decimal(90)


def test_dimension_join_cannot_read_an_unexposed_table():
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.semantics.compiler import compile_metric
    with pytest.raises(ReportingError) as denied:
        compile_metric(request("rate", dimensions=["department"]), joined_policy(), joined_definitions(), catalog())
    assert denied.value.code == "metric_field_denied"


def test_dimension_join_reads_only_registered_dependency_columns():
    from smart_reporting.reporting.semantics.compiler import compile_metric
    tables = joined_catalog()
    dimension = tables[-1].model_copy(update={"columns": (*tables[-1].columns, ModelColumn(name="unrelated_payload", dataType="JSON", nullable=True))})
    plan = compile_metric(request("rate", dimensions=["department"]), joined_policy(), joined_definitions(), (*tables[:-1], dimension))
    assert plan.issues == ()
    assert all("unrelated_payload" not in query.sql for query in (*plan.queries, *plan.checks))
