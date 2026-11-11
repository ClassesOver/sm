"""保护新业务契约：精确版本、无伪值、无伪证据和明确的问题状态。"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.semantics.models import (
    ClaimSupport,
    DataReadiness,
    MetricDefinition,
    MetricResult,
    MetricSelection,
    Period,
    QuestionCoverage,
    ReportBasis,
    ReportIssueReview,
    ReportRequestSummary,
    StatisticalPolicy,
)
from smart_reporting.reporting.semantics.validation import validate_policy


def metric_payload(identity="budget", **changes):
    return {
        "id": identity, "name": "预算额", "scopeId": "org-a", "revision": 1,
        "kind": "sum", "fieldRef": "warehouse.test.budget.amount", "unit": "CNY",
        "grain": ["project"], "timeField": "warehouse.test.budget.period",
        "dimensions": [{"id": "project", "fieldRef": "warehouse.test.budget.project_id"}],
        "aggregationPolicy": {"observationKind": "flow", "timeAggregation": "sum"},
        **changes,
    }


def policy_payload(**changes):
    return {
        "id": "monthly-budget", "name": "合成预算执行", "scopeId": "org-a",
        "revision": 1, "scenario": "budget_execution", "validFrom": "2026-01-01",
        "validTo": "2027-01-01", "metricVersions": [{"metricId": "budget", "revision": 1}],
        "evidenceReleaseId": "rules-v1", **changes,
    }


def ratio_payload(identity="rate", numerator="actual", denominator="budget", **changes):
    payload = metric_payload(identity, kind="ratio", unit="%")
    payload.pop("fieldRef")
    payload.pop("timeField")
    payload["numeratorVersion"] = {"metricId": numerator, "revision": 1}
    payload["denominatorVersion"] = {"metricId": denominator, "revision": 1}
    payload.update(changes)
    return payload


def test_rejects_old_profile_properties_and_ambiguous_formula_shape():
    with pytest.raises(ValidationError):
        MetricDefinition.model_validate(metric_payload(profileId="old"))
    with pytest.raises(ValidationError):
        MetricDefinition.model_validate(ratio_payload(fieldRef="warehouse.test.budget.amount"))
    with pytest.raises(ValidationError):
        MetricDefinition.model_validate(metric_payload(grain=[]))
    with pytest.raises(ValidationError):
        MetricDefinition.model_validate(metric_payload(fieldRef="warehouse.test.*.amount"))


def test_uses_exclusive_end_and_rejects_inverted_policy_validity():
    period = Period(start="2026-01-01", end="2026-02-01")
    assert period.contains(date(2026, 1, 31))
    assert not period.contains(date(2026, 2, 1))
    with pytest.raises(ValidationError):
        Period(start="2026-01-01", end="2026-01-01")
    with pytest.raises(ValidationError):
        StatisticalPolicy.model_validate(policy_payload(validTo="2025-01-01"))


def test_exact_reference_does_not_resolve_latest_version():
    policy = StatisticalPolicy.model_validate(policy_payload())
    newer = MetricDefinition.model_validate(metric_payload(revision=2))
    issues = validate_policy(policy, (newer,))
    assert [(item.code, item.impact) for item in issues] == [
        ("metric_version_missing", "unavailable"),
    ]


def test_scope_mismatch_is_not_treated_as_a_business_warning():
    policy = StatisticalPolicy.model_validate(policy_payload())
    foreign = MetricDefinition.model_validate(metric_payload(scopeId="org-b"))
    with pytest.raises(ValueError, match="scope"):
        validate_policy(policy, (foreign,))


def test_ratio_cycle_is_unavailable_and_unit_mismatch_is_reported():
    policy = StatisticalPolicy.model_validate(policy_payload(metricVersions=[{"metricId": "rate", "revision": 1}]))
    budget = MetricDefinition.model_validate(metric_payload())
    first = MetricDefinition.model_validate(ratio_payload(numerator="other"))
    second = MetricDefinition.model_validate(ratio_payload("other", numerator="rate"))
    assert "metric_dependency_cycle" in {x.code for x in validate_policy(policy, (budget, first, second))}
    actual = MetricDefinition.model_validate(metric_payload("actual", unit="人次"))
    rate = MetricDefinition.model_validate(ratio_payload())
    assert "ratio_unit_mismatch" in {x.code for x in validate_policy(policy, (budget, actual, rate))}


def test_numeric_result_requires_exact_version_and_unavailable_cannot_hide_value():
    payload = {
        "metricVersion": {"metricId": "budget", "revision": 1}, "basisId": "basis-1",
        "calculationId": "calc-1", "factId": "fact-1",
        "period": {"start": "2026-01-01", "end": "2026-02-01"},
        "value": "0", "unit": "CNY", "status": "computed", "datasetIds": ["dataset-1"],
    }
    result = MetricResult.model_validate(payload)
    assert result.value == Decimal("0")
    assert result.model_dump(mode="json", by_alias=True)["metricVersion"]["revision"] == 1
    with pytest.raises(ValidationError):
        MetricResult.model_validate({**payload, "status": "unavailable", "issueCodes": ["missing_data"]})
    with pytest.raises(ValidationError):
        MetricResult.model_validate({**payload, "value": None})
    with pytest.raises(ValidationError):
        MetricResult.model_validate({**payload, "value": "NaN"})
    with pytest.raises(ValidationError):
        MetricResult.model_validate({**payload, "metricVersion": {"metricId": "budget"}})


def test_answered_question_and_supported_claim_require_references():
    with pytest.raises(ValidationError):
        QuestionCoverage(questionId="q1", status="answered")
    with pytest.raises(ValidationError):
        QuestionCoverage(questionId="q1", status="unavailable")
    with pytest.raises(ValidationError):
        ClaimSupport(subjectId="s1", kind="fact", supportStatus="supported")
    with pytest.raises(ValidationError):
        ClaimSupport(subjectId="s1", kind="inference", supportStatus="supported", factRefs=["fact-1"])
    claim = ClaimSupport(subjectId="s1", kind="inference", supportStatus="unverified", factRefs=["fact-1"])
    assert claim.support_status == "unverified"


def test_ambiguous_selection_cannot_silently_choose_a_candidate():
    ref = {"metricId": "budget", "revision": 1}
    with pytest.raises(ValidationError):
        MetricSelection(questionId="q1", status="ambiguous", selected=ref, candidates=[
            {"metricVersion": ref, "reason": "同名候选"},
        ], issueCodes=["metric_ambiguous"])
    with pytest.raises(ValidationError):
        MetricSelection(questionId="q1", status="resolved", selected=ref, candidates=[])


def test_accepted_feedback_is_not_resolved_without_repair_and_regression():
    payload = {
        "issueId": "issue-1", "reportRevision": "revision-1", "objectRefs": ["fact-1"],
        "category": "calculation", "description": "总执行率不应平均", "status": "accepted",
        "decisionReason": "独立汇总为63.33%",
    }
    assert ReportIssueReview.model_validate(payload).status == "accepted"
    with pytest.raises(ValidationError):
        ReportIssueReview.model_validate({**payload, "status": "resolved"})


def test_questions_have_unique_identity_and_preserve_explicit_assumptions():
    payload = {
        "goal": "解释预算执行", "scenario": "budget_execution", "organization": "org-a",
        "period": {"start": "2026-01-01", "end": "2026-02-01"},
        "displayUnit": "CNY", "requestedOutputs": ["pdf", "docx"],
        "questions": [{"id": "q1", "text": "执行率是多少"}],
        "assumptions": [{"field": "comparisonPeriod", "value": "未要求比较", "source": "explicit"}],
    }
    summary = ReportRequestSummary.model_validate(payload)
    assert summary.assumptions[0].source == "explicit"
    with pytest.raises(ValidationError):
        ReportRequestSummary.model_validate({**payload, "questions": payload["questions"] * 2})


def test_unknown_readiness_is_not_silently_passed():
    payload = {
        "metricVersion": {"metricId": "budget", "revision": 1},
        "requestedPeriod": {"start": "2026-01-01", "end": "2026-02-01"},
        "observedPeriod": None, "extractedAt": "2026-02-02T10:00:00Z",
        "checks": [{"name": "period_coverage", "status": "unknown", "factRefs": []}],
    }
    with pytest.raises(ValidationError):
        DataReadiness.model_validate(payload)
    readiness = DataReadiness.model_validate({**payload, "issueCodes": ["coverage_unknown"]})
    assert readiness.checks[0].status == "unknown"
    with pytest.raises(ValidationError):
        DataReadiness.model_validate({**payload, "checks": [{"name": "period_coverage", "status": "pass"}]})


def test_basis_requires_matching_request_scope_and_exact_policy():
    summary = {
        "goal": "预算执行", "scenario": "budget_execution", "organization": "org-a",
        "period": {"start": "2026-01-01", "end": "2026-02-01"},
        "displayUnit": "CNY", "requestedOutputs": ["pdf"],
        "questions": [{"id": "q1", "text": "执行率"}],
    }
    payload = {
        "id": "basis-1", "runId": "run-1", "scopeId": "org-a",
        "policyVersion": {"policyId": "monthly-budget", "revision": 1},
        "metricVersions": [{"metricId": "budget", "revision": 1}],
        "sourceVersions": [{"sourceId": "warehouse", "revision": 1, "contentHash": "a" * 64}],
        "catalogRefs": [{"sourceId": "warehouse", "revision": 1, "contentHash": "b" * 64}],
        "evidenceReleaseId": "rules-1", "requestSummary": summary,
        "buildIdentity": {"commit": "c" * 40, "sourceHash": "e" * 64, "dependencyHash": "d" * 64, "compilerVersion": "1"},
        "knowledgeAsOf": "2026-02-02T10:00:00Z", "registeredAt": "2026-02-02T10:00:00Z",
    }
    assert ReportBasis.model_validate(payload).reproducible_until is None
    with pytest.raises(ValidationError):
        ReportBasis.model_validate({**payload, "requestSummary": {**summary, "organization": "org-b"}})
    with pytest.raises(ValidationError):
        ReportBasis.model_validate({**payload, "policyVersion": {"policyId": "monthly-budget"}})


def test_knowledge_correction_can_close_with_document_version_and_regression_evidence():
    review = ReportIssueReview.model_validate({
        "issueId": "issue-2", "reportRevision": "revision-1", "objectRefs": ["claim-1"],
        "category": "citation", "description": "引文指向错误的制度修订", "status": "resolved",
        "decisionReason": "已发布正确制度并验证定位",
        "correctedVersions": [{"assetType": "document", "assetId": "rules", "revision": 2}],
        "regressionCaseIds": ["C21"], "newReportRevision": "revision-2",
    })
    assert review.corrected_versions[0].asset_type == "document"
