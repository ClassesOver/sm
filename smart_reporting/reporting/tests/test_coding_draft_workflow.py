from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext
from agno.workflow import Workflow
from agno.workflow.types import StepOutput

from smart_reporting.reporting.workflow.runtime.coding_draft_workflow import (
    CodingAnalysisAndDraftWorkflow,
    CodingDraftWorkflow,
    build_coding_draft_steps,
)


def _ok(value: str) -> StepOutput:
    return StepOutput(content=value)


@pytest.mark.anyio
async def test_coding_workflow_is_agno_workflow_and_injects_goals() -> None:
    seen: list[tuple[str, dict]] = []

    async def analysis(instruction, _context):
        seen.append(("analysis", instruction))
        return _ok("analysis")

    async def visualization(instruction, _context):
        seen.append(("visualization", instruction))
        return _ok("visualization")

    async def draft(instruction, _context):
        seen.append(("draft", instruction))
        return _ok("draft")

    workflow = CodingAnalysisAndDraftWorkflow(
        report_goal="分析收入变化原因",
        sections=[
            {
                "sectionCode": "section_001",
                "title": "规模",
                "focus": ["总额"],
                "analysisIds": ["a1"],
            },
            {
                "sectionCode": "section_002",
                "title": "趋势",
                "focus": ["同比"],
                "analysisIds": ["a2"],
            },
        ],
        run_analysis=analysis,
        submit_visualization=visualization,
        draft_section=draft,
    )

    assert isinstance(workflow, Workflow)
    await workflow.sections[0].execute_section(RunContext(run_id="run-1", session_id="session-1"))
    assert [kind for kind, _ in seen] == ["analysis", "visualization", "draft"]
    assert all(item[1]["reportGoal"] == "分析收入变化原因" for item in seen)
    assert all(item[1]["sectionGoal"]["sectionCode"] == "section_001" for item in seen)
    assert all(item[1]["sectionGoal"]["title"] == "规模" for item in seen)
    assert seen[0][1]["analysisId"] == "a1"
    assert seen[-1][1]["visualizationSubmitted"] is True


@pytest.mark.anyio
async def test_failed_analysis_blocks_visualization_and_draft() -> None:
    visualization = AsyncMock(return_value=_ok("visualization"))
    draft = AsyncMock(return_value=_ok("draft"))
    workflow = CodingDraftWorkflow(
        report_goal="目标",
        section_goal={"sectionCode": "section_001"},
        analysis_ids=["a1"],
        run_analysis=AsyncMock(return_value=StepOutput(content="bad", success=False)),
        submit_visualization=visualization,
        draft_section=draft,
    )

    with pytest.raises(RuntimeError, match="分析项 a1 执行失败"):
        await workflow.execute_section(RunContext(run_id="run-1", session_id="session-1"))
    visualization.assert_not_awaited()
    draft.assert_not_awaited()


def test_coding_workflow_rejects_analysis_id_assigned_to_two_sections() -> None:
    callback = AsyncMock(return_value=_ok("ok"))
    with pytest.raises(ValueError, match="不能归属于多个章节"):
        CodingAnalysisAndDraftWorkflow(
            report_goal="目标",
            sections=[
                {"sectionCode": "section_001", "analysisIds": ["a1"]},
                {"sectionCode": "section_002", "analysisIds": ["a1"]},
            ],
            run_analysis=callback,
            submit_visualization=callback,
            draft_section=callback,
        )


@pytest.mark.anyio
async def test_parallel_sections_share_analysis_limiter() -> None:
    active = 0
    maximum = 0

    async def analysis(_instruction, _context):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        return _ok("analysis")

    workflow = CodingAnalysisAndDraftWorkflow(
        report_goal="目标",
        sections=[
            {"sectionCode": "section_001", "analysisIds": ["a1"]},
            {"sectionCode": "section_002", "analysisIds": ["a2"]},
        ],
        run_analysis=analysis,
        submit_visualization=AsyncMock(return_value=_ok("visualization")),
        draft_section=AsyncMock(return_value=_ok("draft")),
        execution_mode="parallel",
        section_concurrency=2,
        analysis_concurrency=1,
    )

    await workflow._run_sections(RunContext(run_id="run-1", session_id="session-1"))
    assert maximum == 1


@pytest.mark.anyio
async def test_parallel_section_failure_stops_following_batches() -> None:
    started: list[str] = []

    async def analysis(instruction, _context):
        started.append(instruction["sectionCode"])
        if instruction["sectionCode"] == "section_001":
            raise RuntimeError("section failed")
        return _ok("analysis")

    workflow = CodingAnalysisAndDraftWorkflow(
        report_goal="目标",
        sections=[
            {"sectionCode": "section_001", "analysisIds": ["a1"]},
            {"sectionCode": "section_002", "analysisIds": ["a2"]},
        ],
        run_analysis=analysis,
        submit_visualization=AsyncMock(return_value=_ok("visualization")),
        draft_section=AsyncMock(return_value=_ok("draft")),
        execution_mode="parallel",
        section_concurrency=1,
    )

    with pytest.raises(RuntimeError, match="Agno 章节步骤执行失败"):
        await workflow._run_sections(RunContext(run_id="run-1", session_id="session-1"))
    assert started == ["section_001"]


@pytest.mark.anyio
async def test_coding_workflow_arun_uses_agno_public_entrypoint() -> None:
    workflow = CodingAnalysisAndDraftWorkflow(
        report_goal="目标",
        sections=[{"sectionCode": "section_001", "analysisIds": ["a1"]}],
        run_analysis=AsyncMock(return_value=_ok("analysis")),
        submit_visualization=AsyncMock(return_value=_ok("visualization")),
        draft_section=AsyncMock(return_value=_ok("draft")),
    )

    output = await workflow.arun(
        input={"reportGoal": "目标"}, run_id="run-1", session_id="session-1"
    )

    assert output.content == {
        "sections": [
            {
                "sectionCode": "section_001",
                "analysisCount": 1,
                "visualizationSubmitted": True,
                "draftCompleted": True,
            }
        ]
    }


def test_parallel_plan_uses_agno_parallel_container() -> None:
    workflow = CodingDraftWorkflow(
        report_goal="目标",
        section_goal={"sectionCode": "section_001"},
        analysis_ids=["a1"],
        run_analysis=AsyncMock(return_value=_ok("analysis")),
        submit_visualization=AsyncMock(return_value=_ok("visualization")),
        draft_section=AsyncMock(return_value=_ok("draft")),
        execution_mode="parallel",
    )
    from agno.workflow import Parallel

    assert isinstance(
        build_coding_draft_steps(workflow, RunContext(run_id="run-1", session_id="session-1")),
        Parallel,
    )
