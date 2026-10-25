"""只依据固定事实的分析项：服务端写出引用式摘要，数字全部可核对，不再请求模型转述。"""

import re
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.trace.numeric_text import frozen_number_catalog, render_frozen_numbers
from smart_reporting.reporting.trace.semantic_bindings import resolve_number_references
from smart_reporting.reporting.trace.statement_review import statement_review_warnings
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
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


@pytest.mark.anyio
async def test_facts_only_analysis_completes_with_a_server_summary():
    summarize = AsyncMock(side_effect=AssertionError("只用固定事实时不应请求摘要模型"))
    workflow, complete = _completion_workflow(summarize)
    state = _AnalysisItemState(instruction={"currentAnalysisId": "analysis_001",
                                            "currentAnalysis": {"datasetIds": ["current"]}})
    state.facts = _bundle(THREE_MONTHS)
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
