"""用独立原始行oracle检验可加性，不把去重计数或比率当作可加指标。"""

from decimal import Decimal

import duckdb
from hypothesis import given, settings
from hypothesis import strategies as st

from smart_reporting.reporting.semantics.compiler import compile_metric
from smart_reporting.reporting.semantics.models import MetricDefinition
from smart_reporting.reporting.tests.test_metric_compilation import (
    catalog,
    execute,
    policy,
    request,
)
from smart_reporting.reporting.tests.test_semantic_models import metric_payload


@settings(max_examples=16, deadline=None)
@given(rows=st.lists(st.tuples(st.sampled_from(("A", "B", "C")), st.integers(-100000, 100000)), min_size=1, max_size=20))
def test_sum_partition_and_total_match_independent_original_rows(rows):
    metric = MetricDefinition.model_validate(metric_payload())
    with duckdb.connect() as connection:
        connection.execute("CREATE SCHEMA test")
        connection.execute("CREATE TABLE test.budget(project_id VARCHAR, amount DECIMAL(18,2), period DATE)")
        connection.executemany("INSERT INTO test.budget VALUES (?, ?, '2026-01-15')", rows)
        total = execute(connection, compile_metric(request(), policy(), (metric,), catalog()).queries[0])[0]["value"]
        groups = execute(connection, compile_metric(request(dimensions=["project"]), policy(), (metric,), catalog()).queries[0])
    oracle = {}
    for group, amount in rows:
        oracle[group] = oracle.get(group, Decimal(0)) + Decimal(amount)
    assert {item["dimension_0"]: item["value"] for item in groups} == oracle
    assert total == sum(oracle.values(), Decimal(0))


def test_distinct_count_is_recomputed_instead_of_summing_group_counts():
    metric = MetricDefinition.model_validate(metric_payload(kind="count_distinct", unit="个"))
    with duckdb.connect() as connection:
        connection.execute("CREATE SCHEMA test")
        connection.execute("CREATE TABLE test.budget(project_id VARCHAR, amount DECIMAL(18,2), period DATE)")
        connection.execute("INSERT INTO test.budget VALUES ('A',100,'2026-01-01'),('B',100,'2026-01-01')")
        total = execute(connection, compile_metric(request(), policy(), (metric,), catalog()).queries[0])[0]["value"]
        groups = execute(connection, compile_metric(request(dimensions=["project"]), policy(), (metric,), catalog()).queries[0])
    assert total == 1 and sum(item["value"] for item in groups) == 2
