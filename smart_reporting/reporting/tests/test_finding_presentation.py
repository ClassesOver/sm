"""Professional review: priority and resolvable pointers cannot upgrade evidence."""

import pytest

from smart_reporting.reporting.hospital_operation.finding_presentation import (
    finding_presentation_policy,
)
from smart_reporting.reporting.hospital_operation.narrative_planner import (
    build_fallback_narrative_candidate,
    build_narrative_planning_context,
)
from smart_reporting.reporting.tests.narrative_helpers import finding, graph
from smart_reporting.reporting.tests.test_dynamic_section_rendering import _item
from smart_reporting.reporting.workflow.runtime.sections import _section_model_work_item_payload


@pytest.mark.parametrize("level, mode", [
    ("verified_fact", "bounded_fact"), ("rule_based", "bounded_fact"),
    ("direct_decomposition", "bounded_fact"), ("statistical_relation", "association"),
    ("business_hypothesis", "hypothesis"), ("evidence_missing", "gap"),
])
def test_high_priority_preserves_evidence_boundary_through_planning_and_writing(level, mode):
    card = finding(evidenceLevel=level, priority="high", actionability="high",
                   limitations=("收入归属尚未确认",))
    source = graph(card)
    frozen = source.model_dump(mode="json", by_alias=True)
    context = build_narrative_planning_context(source, "识别经营问题")
    candidate = build_fallback_narrative_candidate(source, "经营报告")
    item = _item(findingSummaries=[card.model_dump(mode="json", by_alias=True)])
    view = _section_model_work_item_payload(item)["findingSummaries"][0]

    assert candidate.sections[0].finding_ids == (card.finding_id,)
    assert "已核验发现" not in candidate.sections[0].objective
    assert context["findings"][0]["presentationPolicy"] == view["presentationPolicy"]
    assert view["presentationPolicy"]["statementMode"] == mode
    assert view["limitations"] == ["收入归属尚未确认"]
    assert source.model_dump(mode="json", by_alias=True) == frozen


@pytest.mark.parametrize("level", [None, "legacy_unknown", "evidence_missing"])
def test_unknown_levels_never_grant_verified_conclusions(level):
    assert finding_presentation_policy(level)["statementMode"] == "gap"


def test_missing_one_source_downgrades_only_affected_finding_and_preserves_frozen_summary():
    first, second = finding(1), finding(2)
    item = _item(
        analysisIds=["analysis_001", "analysis_002"],
        findingIds=[first.finding_id, second.finding_id],
        findingSummaries=[card.model_dump(mode="json", by_alias=True) for card in (first, second)],
    )
    frozen = item.model_dump(mode="json", by_alias=True)
    view = _section_model_work_item_payload(item, unavailable_finding_ids={first.finding_id})
    invalid, valid = view["findingSummaries"]
    assert invalid["presentationPolicy"]["statementMode"] == "gap"
    assert invalid["summary"] != first.summary
    assert "来源未完整核实" in invalid["summary"]
    assert valid["presentationPolicy"]["statementMode"] == "bounded_fact"
    assert valid["summary"] == second.summary
    assert item.model_dump(mode="json", by_alias=True) == frozen


def test_writer_recomputes_policy_instead_of_trusting_supplied_verification():
    card = finding(evidenceLevel="business_hypothesis").model_dump(mode="json", by_alias=True)
    card["presentationPolicy"] = {"statementMode": "verified", "actionBoundary": "立即整改"}
    item = _item(findingSummaries=[card])
    view = _section_model_work_item_payload(item)["findingSummaries"][0]
    assert view["presentationPolicy"]["statementMode"] == "hypothesis"
    assert "立即整改" not in str(view["presentationPolicy"])


@pytest.mark.anyio
@pytest.mark.parametrize("whole_section", [False, True])
@pytest.mark.parametrize("source_state", ["valid", "missing", "partial"])
async def test_runtime_carries_boundaries_and_source_failures_to_every_generation_path(
    monkeypatch, whole_section, source_state,
):
    import hashlib
    import json

    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
        _context,
        _plan_claim,
        _revenue_work_item,
    )
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity
    from smart_reporting.reporting.workflow.runtime import sections
    from smart_reporting.reporting.workflow.runtime.phase_models import (
        SectionBlockContent,
        SectionContent,
        SectionEvidenceBundle,
        SectionEvidenceFile,
        SectionPlanOutput,
    )
    from smart_reporting.task_execution import TaskExecutionScope

    missing_source = source_state != "valid"
    content = json.dumps({"analysisId": "analysis_001", "metrics": [{
        "factId": "fact-aaaaaaaaaaaaaaaa", "total": 100, "field": "revenue",
    }]})
    identity = FileIdentity(path="facts.json", size=len(content.encode()),
                            sha256=hashlib.sha256(content.encode()).hexdigest())
    card = finding(evidenceLevel="statistical_relation").model_dump(mode="json", by_alias=True)
    card["sourceRefs"] = [{"analysisId": "analysis_001", "path": identity.path,
                           "fileSha256": identity.sha256,
                           "pointer": "/metrics/9" if missing_source else "/metrics/0"}]
    if source_state == "partial":
        card["sourceRefs"].append({**card["sourceRefs"][0], "pointer": "/metrics/0"})
    work_item = _revenue_work_item().model_copy(update={
        "finding_ids": (card["findingId"],), "finding_summaries": (card,),
        "evidence": (_revenue_work_item().evidence[0].model_copy(update={
            "summary": "不得泄漏的分析结论", "evidence_files": (identity,),
        }),),
    })
    frozen = work_item.model_dump(mode="json", by_alias=True)
    evidence = SectionEvidenceBundle(
        sectionCode="section_001", files=(SectionEvidenceFile(identity=identity, content=content),),
        factSummaries=("不得泄漏的分析结论",),
    )
    seen = []

    async def run_stage(_agent, _schema, stage, payload, **_kwargs):
        seen.append(stage)
        boundary = payload["sectionGoal"]["findingPresentation"][0]["presentationPolicy"]
        assert boundary["statementMode"] == ("gap" if missing_source else "association")
        assert "不得泄漏的分析结论" not in json.dumps(payload, ensure_ascii=False)
        if stage == "plan":
            summary = payload["sectionWorkItem"]["findingSummaries"][0]["summary"]
            assert (summary != card["summary"]) == missing_source
            return SectionPlanOutput.model_validate({
                "kind": "render", "sectionCode": "section_001",
                "blocks": [{"blockId": "block_001", "objective": "披露证据边界", "claimIds": ["claim_001"]}],
                "claims": [_plan_claim("claim_001", factIds=[], findingIds=[card["findingId"]])],
            })
        markdown = "### 证据边界\n\n现有证据不足以认定经营原因，需进一步核查。"
        if whole_section:
            return SectionContent(blocks=[{"blockId": "block_001", "markdown": markdown}])
        return SectionBlockContent(markdown=markdown)

    monkeypatch.setattr(sections, "_run_section_stage", run_stage)
    notices = {}
    result = await sections._generate_section_in_blocks(
        object(), {"reportGoal": "分析收入", "sectionGoal": {}}, evidence, work_item,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
        run_context=_context(), thinking_request=ThinkingRequest(
            operation="section_generation", complexity="standard",
        ), whole_section=whole_section, review_notices=notices,
    )
    assert seen[0] == "plan" and len(seen) >= 2
    assert result.blocks
    codes = {notice["code"] for values in notices.values() for notice in values}
    assert ("report_section_finding_source_unavailable" in codes) == missing_source
    assert work_item.model_dump(mode="json", by_alias=True) == frozen
