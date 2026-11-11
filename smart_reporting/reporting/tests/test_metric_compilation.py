"""有限指标SQL在内存数据库执行核对；不能代替真实StarRocks验收。"""

from decimal import Decimal

import duckdb
import pytest
from sqlglot import parse_one

from smart_reporting.reporting.contract import ModelColumn, ModelTable
from smart_reporting.reporting.semantics.models import (
    MetricDefinition,
    MetricRequest,
    StatisticalPolicy,
)
from smart_reporting.reporting.tests.test_semantic_models import (
    metric_payload,
    policy_payload,
    ratio_payload,
)


def catalog():
    columns = (ModelColumn(name="project_id", dataType="VARCHAR", nullable=False),
        ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=True),
        ModelColumn(name="period", dataType="DATE", nullable=False))
    return tuple(ModelTable(sourceId="warehouse", database="test", name=name, columns=columns) for name in ("budget", "actual"))


def definitions():
    return (MetricDefinition.model_validate(metric_payload()),
        MetricDefinition.model_validate(metric_payload("actual", fieldRef="warehouse.test.actual.amount",
            timeField="warehouse.test.actual.period", dimensions=[{"id": "project", "fieldRef": "warehouse.test.actual.project_id"}])),
        MetricDefinition.model_validate(ratio_payload()))


def request(identity="budget", **changes):
    return MetricRequest.model_validate({"metricVersion": {"metricId": identity, "revision": 1},
        "basisId": "basis-1", "period": {"start": "2026-01-01", "end": "2026-02-01"}, **changes})


def policy(identity="budget", **changes):
    return StatisticalPolicy.model_validate(policy_payload(metricVersions=[{"metricId": identity, "revision": 1}], **changes))


@pytest.fixture
def warehouse():
    with duckdb.connect() as connection:
        connection.execute("CREATE SCHEMA test")
        for table in ("budget", "actual"):
            connection.execute(f"CREATE TABLE test.{table}(project_id VARCHAR, amount DECIMAL(18,2), period DATE)")
        connection.execute("INSERT INTO test.budget VALUES ('A',100,'2026-01-01'),('B',200,'2026-01-31'),('A',999,'2026-02-01')")
        connection.execute("INSERT INTO test.actual VALUES ('A',60,'2026-01-01'),('A',30,'2026-01-02'),('B',100,'2026-01-31')")
        yield connection


def execute(connection, query):
    sql = parse_one(query.sql, read="mysql").sql(dialect="duckdb")
    cursor = connection.execute(sql, {item.name: item.value for item in query.parameters})
    return [dict(zip([column[0] for column in cursor.description], row, strict=True)) for row in cursor.fetchall()]


def test_sum_query_uses_half_open_period_and_preserves_original_precision(warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    plan = compile_metric(request(), policy(), definitions(), catalog())
    assert plan.issues == () and len(plan.queries) == 1
    result = execute(warehouse, plan.queries[0])
    assert result == [{"value": Decimal("300.00"), "observed_count": 2, "nonnull_count": 2}]


def test_ratio_compiles_independent_fact_aggregates_without_detail_join(warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    plan = compile_metric(request("rate"), policy("rate"), definitions(), catalog())
    assert plan.issues == () and len(plan.queries) == 2
    actual = {query.metric_version.metric_id: execute(warehouse, query)[0]["value"] for query in plan.queries}
    assert actual == {"budget": Decimal("300.00"), "actual": Decimal("190.00")}
    assert (actual["actual"] / actual["budget"] * 100).quantize(Decimal("0.01")) == Decimal("63.33")


@pytest.mark.parametrize("kind,expected", [("count", 2), ("count_distinct", 2)])
def test_registered_count_aggregation_runs_against_real_sql(kind, expected, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    metric = MetricDefinition.model_validate(metric_payload(kind=kind, fieldRef="warehouse.test.budget.project_id", unit="个"))
    plan = compile_metric(request(), policy(), (metric,), catalog())
    assert execute(warehouse, plan.queries[0])[0]["value"] == expected


def test_filter_values_are_parameters_and_cannot_change_sql_structure(warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    malicious = "A' OR 1=1 --"
    selected = request(filterValues=[{"fieldRef": "warehouse.test.budget.project_id", "operator": "eq", "values": [malicious]}])
    plan = compile_metric(selected, policy(), definitions(), catalog())
    assert malicious not in plan.queries[0].sql
    assert execute(warehouse, plan.queries[0])[0]["observed_count"] == 0


def test_unexposed_table_and_foreign_scope_are_rejected_before_execution():
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.semantics.compiler import compile_metric
    with pytest.raises(ReportingError) as denied:
        compile_metric(request(), policy(), definitions(), tuple(table for table in catalog() if table.name != "budget"))
    assert denied.value.code == "metric_field_denied"
    foreign = MetricDefinition.model_validate(metric_payload(scopeId="org-b"))
    with pytest.raises(ReportingError) as scope:
        compile_metric(request(), policy(), (foreign,), catalog())
    assert scope.value.code == "metric_scope_mismatch"


def test_unsupported_grain_is_unavailable_without_partial_queries():
    from smart_reporting.reporting.semantics.compiler import compile_metric
    plan = compile_metric(request(dimensions=["department"]), policy(), definitions(), catalog())
    assert plan.queries == ()
    assert [issue.code for issue in plan.issues] == ["grain_not_supported"]


def test_policy_period_cannot_silently_expand_beyond_approved_validity():
    from smart_reporting.reporting.semantics.compiler import compile_metric
    plan = compile_metric(request(period={"start": "2025-12-01", "end": "2026-02-01"}), policy(), definitions(), catalog())
    assert plan.queries == ()
    assert [issue.code for issue in plan.issues] == ["policy_period_not_applicable"]


def test_duplicate_requested_dimensions_are_rejected_before_queries():
    from smart_reporting.reporting.semantics.compiler import compile_metric
    plan = compile_metric(request(dimensions=["project", "project"]), policy(), definitions(), catalog())
    assert plan.queries == ()
    assert [issue.code for issue in plan.issues] == ["grain_not_supported"]


def test_grouped_query_preserves_refunds_and_does_not_fill_missing_groups(warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    warehouse.execute("INSERT INTO test.actual VALUES ('A',-10,'2026-01-03')")
    plan = compile_metric(request("actual", dimensions=["project"]), policy("actual"), definitions(), catalog())
    result = sorted(execute(warehouse, plan.queries[0]), key=lambda row: row["dimension_0"])
    assert result == [{"dimension_0": "A", "dimension_0_is_null": 0, "value": Decimal("80.00"), "observed_count": 3, "nonnull_count": 3},
        {"dimension_0": "B", "dimension_0_is_null": 0, "value": Decimal("100.00"), "observed_count": 1, "nonnull_count": 1}]
