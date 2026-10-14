"""动态章节生产步骤顺序契约。"""

import pytest
from agno.run import RunContext
from agno.workflow.types import StepOutput

from smart_reporting.reporting.workflow.orchestration import create_reporting_analysis_step
from smart_reporting.reporting.workflow.runtime.reporting_draft_workflow import (
    ReportingAnalysisAndDraftWorkflow,
)


def test_analysis_step_factory_supports_evidence_and_draft_ids():
    evidence = create_reporting_analysis_step(
        lambda *_: None, step_id="run-analysis-evidence", name="完成原子分析与证据冻结"
    )
    draft = create_reporting_analysis_step(
        lambda *_: None, step_id="run-report-draft", name="按动态章节生成报告正文"
    )
    assert evidence.step_id == "run-analysis-evidence"
    assert draft.step_id == "run-report-draft"
    assert evidence.name != draft.name


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_frozen_evidence_can_support_two_sections_without_reanalysis(anyio_backend):
    calls = []

    async def analysis(instruction, context):
        raise AssertionError("冻结后的成稿不得重新分析")

    async def visualize(instruction, context):
        calls.append(("chart", instruction["sectionCode"]))
        return StepOutput(content={"status": "completed"})

    async def draft(instruction, context):
        calls.append(("draft", instruction["sectionCode"]))
        return StepOutput(content={"status": "completed"})

    workflow = ReportingAnalysisAndDraftWorkflow(
        report_goal="解释经营变化",
        sections=[
            {"sectionCode": "section_001", "title": "收入趋势", "analysisIds": ["analysis_001"]},
            {"sectionCode": "section_002", "title": "结构异常", "analysisIds": ["analysis_001"]},
        ],
        run_analysis=analysis, submit_visualization=visualize, draft_section=draft,
        evidence_frozen=True,
    )
    for section in workflow.sections:
        await section.execute_section(RunContext(run_id="run-1", session_id="session-1"))
    assert calls == [
        ("chart", "section_001"), ("draft", "section_001"),
        ("chart", "section_002"), ("draft", "section_002"),
    ]
