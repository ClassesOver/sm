"""只依据固定事实的分析项：服务端写出引用式摘要，数字全部可核对，不再请求模型转述。"""

import re
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.trace.numeric_text import (
    frozen_number_catalog,
    render_frozen_numbers,
)
from smart_reporting.reporting.trace.semantic_bindings import resolve_number_references
from smart_reporting.reporting.trace.statement_review import statement_review_warnings
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
    AnalysisItemWorkflow,
    AnalysisSummaryDraft,
    _AnalysisItemState,
)
from smart_reporting.reporting.workflow.runtime.fact_summary import deterministic_fact_summary

from .test_dimension_breakdowns import _bundle
from .test_evidence_coverage import THREE_MONTHS

_TOKEN = re.compile(r"\{\{value:[^{}]+\}\}")


def test_summary_cites_registered_values_for_totals_months_and_composition():
    bundle = _bundle(THREE_MONTHS)
    content = bundle.model_dump_json(by_alias=True)
    summary = deterministic_fact_summary(bundle)
    tokens = _TOKEN.findall(summary)
    # 摘要中的数字全部是登记引用；没有手写数字。
    assert tokens and not re.search(r"\d", re.sub(r"\d{4}年[\d—]+月", "", _TOKEN.sub("", summary)))
    assert all(resolve_number_references(tokens, [content]).values())
    rendered = render_frozen_numbers(summary, frozen_number_catalog([content]))
    assert rendered.startswith("2025年1—3月amount合计370元；月均123.33元，最高为2025年2月160元，最低为2025年1月100元")
    assert "按收入业务类型：住院230元（占62.16%）、门诊140元（占37.84%）" in rendered
    # 写作时的引用句核对对摘要同样成立：期间、范围与口径一致。
    assert statement_review_warnings(summary, [content]) == []


def test_constant_months_and_missing_values_are_not_written_as_extremes():
    csv = "month,department,income_type,amount\n2025-01,A,住院,50\n2025-02,A,住院,50\n2025-03,A,住院,50\n"
    content = _bundle(csv)
    rendered = render_frozen_numbers(deterministic_fact_summary(content),
                                     frozen_number_catalog([content.model_dump_json(by_alias=True)]))
    assert "各月登记值相同，均为50元" in rendered and "最高" not in rendered
    assert deterministic_fact_summary(_bundle(dimensions=()).model_copy(update={"metrics": ()})) == ""


def _completion_workflow(summarize):
    complete = AsyncMock(return_value={"status": "accepted", "taskFinished": True})
    workflow = AnalysisItemWorkflow(decide_evidence=AsyncMock(), run_code=AsyncMock(), summarize=summarize,
                                    read_file=AsyncMock(), complete=complete)
    return workflow, complete


_SUFFICIENT = AnalysisEvidenceDecision(requiresSupplementalEvidence=False, reason="固定事实足够",
                                       missingFacts=(), codingRequirements=())


@pytest.mark.anyio
async def test_facts_only_analysis_completes_with_a_server_summary():
    summarize = AsyncMock(side_effect=AssertionError("只用固定事实时不应请求摘要模型"))
    workflow, complete = _completion_workflow(summarize)
    state = _AnalysisItemState(instruction={"currentAnalysisId": "analysis_001",
                                            "currentAnalysis": {"datasetIds": ["current"]}})
    state.facts = _bundle(THREE_MONTHS)
    state.decision = _SUFFICIENT
    await workflow._complete_analysis(state, None)
    summarize.assert_not_awaited()
    assert _TOKEN.search(complete.await_args.kwargs["summary"])
    assert complete.await_args.kwargs["evidencePaths"] == []


@pytest.mark.anyio
@pytest.mark.parametrize("instruction", [{"reviewFeedback": "补充说明"}, {"analysisReworkRequest": {"x": 1}}])
async def test_feedback_or_rework_still_uses_the_model_summary(instruction):
    summarize = AsyncMock(return_value=AnalysisSummaryDraft(summary="按修订意见说明。", warnings=()))
    workflow, complete = _completion_workflow(summarize)
    state = _AnalysisItemState(instruction={"currentAnalysisId": "analysis_001",
                                            "currentAnalysis": {"datasetIds": ["current"]},
                                            "deterministicFacts": {"analysisId": "analysis_001"}, **instruction})
    state.facts = _bundle(THREE_MONTHS)
    await workflow._complete_analysis(state, None)
    summarize.assert_awaited_once()
    assert complete.await_args.kwargs["summary"] == "按修订意见说明。"


@pytest.mark.anyio
async def test_abandoned_supplement_keeps_the_model_summary_that_states_the_gap():
    # 判定需要补证、补证又被放弃时，服务端摘要会把未回答的问题写成已回答；仍由模型说明缺口。
    summarize = AsyncMock(return_value=AnalysisSummaryDraft(summary="缺少科室构成，仅列示合计。", warnings=()))
    workflow, complete = _completion_workflow(summarize)
    state = _AnalysisItemState(instruction={"currentAnalysisId": "analysis_001",
                                            "currentAnalysis": {"datasetIds": ["current"]},
                                            "deterministicFacts": {"analysisId": "analysis_001"}})
    state.facts = _bundle(THREE_MONTHS)
    state.decision = AnalysisEvidenceDecision.model_validate({
        "requiresSupplementalEvidence": True, "reason": "缺科室构成", "missingFacts": ["科室构成"],
        "codingRequirements": [{"datasetId": "current", "fields": ["department", "amount"],
                                "calculation": "按科室汇总", "outputName": "department_total"}],
    })
    state.supplement_abandoned = True
    await workflow._complete_analysis(state, None)
    summarize.assert_awaited_once()


def test_year_over_year_sentence_is_not_rewritten_as_incomparable():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        build_deterministic_analysis_bundle,
    )
    from smart_reporting.reporting.tools.analysis_item import (
        _normalize_analysis_summary_comparability,
    )

    # 全期、单月极值与同比同句时，完成校验会把“同比”改成“参考对比”；同比须单独成句。
    from .test_deterministic_analysis import analysis, context, semantic

    def dataset(name):
        return context(name, semantics=(semantic("amount", unit="元"),)).model_copy(
            update={"period_granularities": {"month": "month"}})

    bundle = build_deterministic_analysis_bundle(analysis(), (
        ("current", b"month,department,amount\n2025-01,A,120\n2025-02,A,150\n2025-03,A,90\n",
         dataset("current"), ("current",)),
        ("baseline", b"month,department,amount\n2024-01,A,100\n2024-02,A,100\n2024-03,A,100\n",
         dataset("baseline"), ("yoy",)),
    ))
    summary = deterministic_fact_summary(bundle)
    assert "较上年同期变化" in summary
    normalized, warnings = _normalize_analysis_summary_comparability(summary)
    assert normalized == summary and warnings == ()
