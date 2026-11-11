"""声明的数据就绪条件必须由取数回执证明，不能把无记录当作零。"""

import pytest

from smart_reporting.reporting.tests.test_metric_compilation import policy, request


def observations(**changes):
    from smart_reporting.reporting.semantics.readiness import ReadinessObservations
    return ReadinessObservations.model_validate({
        "metricVersion": {"metricId": "budget", "revision": 1}, "basisId": "basis-1",
        "requestedPeriod": {"start": "2026-01-01", "end": "2026-02-01"},
        "extractedAt": "2026-02-02T00:00:00Z",
        "observedPeriod": {"start": "2026-01-01", "end": "2026-02-01"},
        "factRefs": ["observation-fact"],
        "periodCounts": [{"period": {"start": "2026-01-01", "end": "2026-02-01"}, "observedCount": 2}],
        "groupCounts": [{"dimensions": [{"dimensionId": "project", "value": group}], "observedCount": 1} for group in ("A", "B")],
        "sourceWatermark": "2026-02-01T23:30:00Z", **changes,
    })


def ready_policy(**changes):
    return policy(readinessPolicy={
        "expectedPeriods": [{"start": "2026-01-01", "end": "2026-02-01"}],
        "expectedGroups": [[{"dimensionId": "project", "value": group}] for group in ("A", "B")],
        "watermarkField": "warehouse.test.budget.updated_at", "maximumDelaySeconds": 3600, **changes,
    })


def test_declared_checks_require_observed_facts_and_fresh_watermark():
    from smart_reporting.reporting.semantics.readiness import evaluate_data_readiness
    receipt = evaluate_data_readiness(request(), ready_policy(), observations())
    assert {check.name: check.status for check in receipt.checks} == {"period_coverage": "pass", "group_coverage": "pass", "source_freshness": "pass"}
    assert receipt.issue_codes == ()
    assert all(check.fact_refs == ("observation-fact",) for check in receipt.checks)


def test_missing_rules_remain_unknown_despite_plausible_observed_range():
    from smart_reporting.reporting.semantics.readiness import evaluate_data_readiness
    receipt = evaluate_data_readiness(request(), policy(), observations())
    assert receipt.issue_codes == ("data_readiness_unknown",)
    assert all(check.status == "unknown" for check in receipt.checks)


def test_missing_month_is_not_hidden_by_minimum_and_maximum_dates():
    from smart_reporting.reporting.semantics.readiness import evaluate_data_readiness
    periods = [{"start": "2026-01-01", "end": "2026-02-01"}, {"start": "2026-02-01", "end": "2026-03-01"}, {"start": "2026-03-01", "end": "2026-04-01"}]
    counts = [{"period": period, "observedCount": count} for period, count in zip(periods, (1, 0, 1), strict=True)]
    period = {"start": "2026-01-01", "end": "2026-04-01"}
    receipt = evaluate_data_readiness(request(period=period), ready_policy(expectedPeriods=periods),
        observations(requestedPeriod=period, observedPeriod=period, periodCounts=counts))
    assert "missing_period_observations" in receipt.issue_codes
    assert next(check for check in receipt.checks if check.name == "period_coverage").status == "fail"


def test_missing_groups_and_stale_watermark_have_separate_reasons():
    from smart_reporting.reporting.semantics.readiness import evaluate_data_readiness
    receipt = evaluate_data_readiness(request(), ready_policy(), observations(
        groupCounts=[{"dimensions": [{"dimensionId": "project", "value": "A"}], "observedCount": 2}],
        sourceWatermark="2026-02-01T00:00:00Z"))
    assert set(receipt.issue_codes) == {"missing_group_observations", "source_watermark_stale"}


@pytest.mark.parametrize("watermark,code", [(None, "source_watermark_unknown"), ("2026-02-02T01:00:00Z", "source_watermark_in_future")])
def test_missing_or_future_watermark_never_proves_freshness(watermark, code):
    from smart_reporting.reporting.semantics.readiness import evaluate_data_readiness
    receipt = evaluate_data_readiness(request(), ready_policy(), observations(sourceWatermark=watermark))
    assert code in receipt.issue_codes


def test_zero_when_complete_does_not_turn_unobserved_period_into_zero():
    from smart_reporting.reporting.semantics.readiness import evaluate_data_readiness
    receipt = evaluate_data_readiness(request(), ready_policy(emptyObservation="zero_when_complete"),
        observations(periodCounts=[{"period": {"start": "2026-01-01", "end": "2026-02-01"}, "observedCount": 0}]))
    assert "missing_period_observations" in receipt.issue_codes


def test_foreign_calculation_observations_are_rejected():
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.semantics.readiness import evaluate_data_readiness
    with pytest.raises(ReportingError) as denied:
        evaluate_data_readiness(request(), ready_policy(), observations(basisId="another-basis"))
    assert denied.value.code == "metric_observation_mismatch"


@pytest.mark.parametrize("changes", [
    {"expectedGroups": [[]]},
    {"expectedGroups": [[{"dimensionId": "project", "value": "A"}, {"dimensionId": "project", "value": "B"}]]},
    {"expectedPeriods": [{"start": "2026-01-01", "end": "2026-03-01"}, {"start": "2026-02-01", "end": "2026-04-01"}]},
    {"maximumDelaySeconds": 300},
])
def test_ambiguous_readiness_rules_are_rejected_before_compilation(changes):
    from pydantic import ValidationError

    from smart_reporting.reporting.semantics.models import DataReadinessPolicy
    with pytest.raises(ValidationError):
        DataReadinessPolicy.model_validate(changes)
