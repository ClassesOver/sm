"""累计快照按登记月末及重置规则差分；不把快照相加或当成业务流量。"""

from decimal import Decimal

import pytest

from smart_reporting.reporting.semantics.models import MetricDefinition
from smart_reporting.reporting.tests.test_metric_compilation import catalog, policy, request
from smart_reporting.reporting.tests.test_metric_compilation import warehouse as warehouse
from smart_reporting.reporting.tests.test_metric_execution import anyio_backend as anyio_backend
from smart_reporting.reporting.tests.test_metric_execution import (
    execution_context as execution_context,
)
from smart_reporting.reporting.tests.test_semantic_models import metric_payload

pytestmark = pytest.mark.anyio


def snapshot_metric(reset="calendar_year_zero"):
    return MetricDefinition.model_validate(metric_payload(aggregationPolicy={"observationKind": "cumulative_snapshot",
        "timeAggregation": "difference", "reset": reset}))


async def calculate(execution_context, *, start="2026-02-01", end="2026-03-01", reset="calendar_year_zero"):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    adapters, datasets, context = execution_context
    plan = compile_metric(request(period={"start": start, "end": end}), policy(), (snapshot_metric(reset),), catalog())
    return await execute_metric(plan, adapters, datasets=datasets, run_context=context, calculation_id="calc-snapshot")


def snapshots(warehouse, rows):
    warehouse.execute("DELETE FROM test.budget")
    warehouse.executemany("INSERT INTO test.budget VALUES (?, ?, ?)", rows)


async def test_monthly_difference_uses_each_registered_grain_baseline(execution_context, warehouse):
    snapshots(warehouse, [("A", 100, "2026-01-31"), ("B", 200, "2026-01-31"),
        ("A", 130, "2026-02-28"), ("B", 180, "2026-02-28")])
    receipt = await calculate(execution_context)
    assert len(receipt.results) == 1 and receipt.results[0].value == Decimal(10)
    assert "cumulative_snapshot_change_not_flow" in receipt.results[0].issue_codes


async def test_january_reset_uses_declared_zero_instead_of_december(execution_context, warehouse):
    snapshots(warehouse, [("A", 1000, "2025-12-31"), ("A", 20, "2026-01-31")])
    receipt = await calculate(execution_context, start="2026-01-01", end="2026-02-01")
    assert receipt.results[0].value == Decimal(20)


@pytest.mark.parametrize("rows,reset,issue", [
    ([("A", 20, "2026-02-28")], "calendar_year_zero", "cumulative_baseline_missing"),
    ([("A", 1000, "2025-12-31"), ("A", 20, "2026-01-31")], None, "cumulative_reset_unresolved"),
    ([("A", 10, "2026-01-31"), ("A", 20, "2026-02-28"), ("A", 20, "2026-02-28")], "calendar_year_zero", "cumulative_duplicate_snapshot"),
])
async def test_missing_or_ambiguous_snapshot_never_produces_value(execution_context, warehouse, rows, reset, issue):
    snapshots(warehouse, rows)
    start, end = ("2026-01-01", "2026-02-01") if reset is None else ("2026-02-01", "2026-03-01")
    receipt = await calculate(execution_context, start=start, end=end, reset=reset)
    assert receipt.results[0].value is None and issue in receipt.results[0].issue_codes


async def test_multiple_months_difference_preserves_negative_adjustment(execution_context, warehouse):
    snapshots(warehouse, [("A", 100, "2026-01-31"), ("A", 80, "2026-02-28"), ("A", 130, "2026-03-31")])
    receipt = await calculate(execution_context, end="2026-04-01")
    assert receipt.results[0].value == Decimal(30)


async def test_missing_intermediate_month_does_not_use_endpoint_difference(execution_context, warehouse):
    snapshots(warehouse, [("A", 100, "2026-01-31"), ("A", 130, "2026-03-31")])
    receipt = await calculate(execution_context, end="2026-04-01")
    assert receipt.results[0].value is None
    assert "cumulative_snapshot_missing" in receipt.results[0].issue_codes


async def test_midmonth_observation_is_not_accepted_as_month_end(execution_context, warehouse):
    snapshots(warehouse, [("A", 100, "2026-01-31"), ("A", 130, "2026-02-20")])
    receipt = await calculate(execution_context)
    assert receipt.results[0].value is None
    assert "cumulative_month_end_required" in receipt.results[0].issue_codes


async def test_disappearing_grain_is_retained_as_incomplete_total(execution_context, warehouse):
    snapshots(warehouse, [("A", 100, "2026-01-31"), ("B", 200, "2026-01-31"), ("A", 130, "2026-02-28")])
    receipt = await calculate(execution_context)
    assert receipt.results[0].value is None
    assert "cumulative_snapshot_missing" in receipt.results[0].issue_codes


async def test_high_precision_snapshot_changes_do_not_round_before_display(execution_context, warehouse):
    warehouse.execute("DROP TABLE test.budget")
    warehouse.execute("CREATE TABLE test.budget(project_id VARCHAR, amount DECIMAL(38,2), period DATE)")
    snapshots(warehouse, [("A", "0.00", "2026-01-31"), ("B", "0.00", "2026-01-31"),
        ("A", "10000000000000000000000000000.01", "2026-02-28"), ("B", "0.02", "2026-02-28")])
    receipt = await calculate(execution_context)
    assert receipt.results[0].value == Decimal("10000000000000000000000000000.03")


async def test_snapshot_baseline_does_not_prove_current_group_coverage(execution_context, warehouse):
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    snapshots(warehouse, [("A", 100, "2026-01-31"), ("B", 200, "2026-01-31"), ("A", 130, "2026-02-28")])
    selected = policy(readinessPolicy={"expectedPeriods": [{"start": "2026-02-01", "end": "2026-03-01"}],
        "expectedGroups": [[{"dimensionId": "project", "value": group}] for group in ("A", "B")]})
    adapters, datasets, context = execution_context
    receipt = await execute_metric(compile_metric(request(period={"start": "2026-02-01", "end": "2026-03-01"}), selected, (snapshot_metric(),), catalog()),
        adapters, datasets=datasets, run_context=context, calculation_id="calc-coverage")
    readiness = receipt.readiness[0]
    assert "missing_group_observations" in readiness.issue_codes
    assert readiness.observed_period.start.isoformat() == "2026-02-28"
