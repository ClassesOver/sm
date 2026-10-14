"""章节 WorkItem 的发现边界契约。"""

import pytest

from smart_reporting.reporting.workflow.checkpoint import SectionWorkItem


def _item(**changes):
    payload = {
        "sectionCode": "section_001",
        "sectionNumber": "1",
        "title": "收入变化",
        "objective": "解释收入变化",
        "completionConditions": ["保留证据"],
        "analysisIds": ["analysis_001"],
        "findingIds": ["finding_0000000000000001"],
        "findingSummaries": [{"findingId": "finding_0000000000000001", "summary": "收入变化"}],
        "markdownRequirements": ["使用事实"],
        **changes,
    }
    return SectionWorkItem.model_validate(payload)


def test_section_work_item_keeps_assigned_finding_ids():
    item = _item()
    assert item.finding_ids == ("finding_0000000000000001",)


def test_section_work_item_rejects_summary_from_another_section():
    with pytest.raises(ValueError, match="当前章节"):
        _item(findingSummaries=[{"findingId": "finding_0000000000000002", "summary": "其他"}])


def _claim(finding_ids):
    return {
        "claimId": "claim_001", "metricCode": "income", "value": 10,
        "managementQuestionRef": "analysis_001", "currentPeriod": "2025",
        "citationIds": ["citation_001"], "findingIds": finding_ids,
    }


@pytest.mark.parametrize("finding_ids, expected_code", [
    (["finding_0000000000000001"], None),
    (["finding_0000000000000002"], "report_section_claim_finding_unknown"),
    ([], "report_section_claim_finding_missing"),
])
def test_claim_binds_only_assigned_findings_without_blocking_text(finding_ids, expected_code):
    from smart_reporting.reporting.tools.sections import RuntimeSectionsMixin

    item = _item(citations=[{
        "citationId": "citation_001", "datasetId": "dataset_001",
        "requirementId": "requirement_001", "snapshotHash": "a" * 64,
    }])
    claims, warnings = RuntimeSectionsMixin._normalize_section_claims(
        section_code=item.section_code, claims=[_claim(finding_ids)], work_item=item,
    )
    assert len(claims) == 1
    assert claims[0].finding_ids == ((item.finding_ids[0],) if expected_code is None else ())
    if expected_code:
        assert any(warning["code"] == expected_code for warning in warnings)


def test_plan_correction_identifies_finding_outside_section():
    from smart_reporting.reporting.workflow.runtime.phase_models import RenderSectionPlan
    from smart_reporting.reporting.workflow.runtime.sections import _section_plan_reference_issues

    plan = RenderSectionPlan(
        sectionCode="section_001",
        blocks=[{"blockId": "block_001", "objective": "解释发现", "claimIds": ["claim_001"]}],
        claims=[_claim(["finding_0000000000000002"])],
    )
    issues = _section_plan_reference_issues(plan, _item())
    finding_issue = next(issue for issue in issues if issue["type"] == "unknown_finding_id")
    assert finding_issue["path"] == "$.claims[0].findingIds"
    assert finding_issue["allowedValues"] == list(_item().finding_ids)


def test_claim_authoring_contract_exposes_assigned_findings():
    from smart_reporting.reporting.workflow.runtime.sections import (
        _section_claim_authoring_contract,
    )

    contract = _section_claim_authoring_contract(_item())
    assert contract["allowedFindingIds"] == list(_item().finding_ids)
    assert contract["findingRule"]


def test_dynamic_work_item_requests_assigned_findings_instead_of_entire_analysis():
    from types import SimpleNamespace

    from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin

    item = _item()
    result = RuntimeSectionsMixin._build_section_work_item(
        SimpleNamespace(code=item.section_code, section_number="1", title=item.title,
                        focus=(), analysis_ids=item.analysis_ids),
        detailed_plan=SimpleNamespace(analyses=[SimpleNamespace(
            analysis_id="analysis_001", metrics=(), management_question="解释收入变化",
        )]),
        analysis_artifact=SimpleNamespace(
            evidence_manifest=SimpleNamespace(evidence=(), charts=(), metric_definitions=()),
            profile_read_receipts=(),
        ),
        citation_bindings=(), finding_ids=item.finding_ids, finding_summaries=item.finding_summaries,
    )
    assert result.completion_conditions[0] == "仅呈现当前章节分配的管理发现及其证据、经营影响和管理动作"
