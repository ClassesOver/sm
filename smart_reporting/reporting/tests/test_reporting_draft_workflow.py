from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext
from agno.workflow import Workflow
from agno.workflow.types import StepOutput
from loguru import logger

from smart_reporting.reporting.workflow.runtime.reporting_draft_workflow import (
    ReportingAnalysisAndDraftWorkflow,
    ReportingDraftWorkflow,
    build_reporting_draft_steps,
)


def _ok(value: str) -> StepOutput:
    return StepOutput(content=value)


@pytest.mark.anyio
async def test_section_execution_logs_started_base_info_and_completed_once() -> None:
    callback = AsyncMock(return_value=_ok("ok"))
    workflow = ReportingDraftWorkflow(
        report_goal="目标",
        section_goal={
            "sectionNumber": "2",
            "sectionCode": "section_002",
            "title": "经营趋势",
        },
        analysis_ids=["analysis_001", "analysis_002"],
        run_analysis=callback,
        submit_visualization=callback,
        draft_section=callback,
    )
    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO", format="{message}")
    try:
        await workflow.execute_section(RunContext(run_id="run-1", session_id="session-1"))
    finally:
        logger.remove(sink_id)

    events = [line for line in "".join(records).splitlines() if line.startswith("report_section_")]
    assert events[:2] == [
        "report_section_started section_code=section_002",
        (
            'report_section_base_info section={"sectionNumber":"2",'
            '"sectionCode":"section_002","title":"经营趋势","analysisCount":2}'
        ),
    ]
    assert len(events) == 3
    duration = events[2].removeprefix(
        "report_section_completed section_code=section_002 duration_ms="
    )
    assert duration.isdigit()


@pytest.mark.anyio
async def test_reporting_draft_workflow_is_agno_workflow_and_injects_goals() -> None:
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

    workflow = ReportingAnalysisAndDraftWorkflow(
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
    workflow = ReportingDraftWorkflow(
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


def test_reporting_draft_workflow_rejects_analysis_id_assigned_to_two_sections() -> None:
    callback = AsyncMock(return_value=_ok("ok"))
    with pytest.raises(ValueError, match="不能归属于多个章节"):
        ReportingAnalysisAndDraftWorkflow(
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

    workflow = ReportingAnalysisAndDraftWorkflow(
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

    workflow = ReportingAnalysisAndDraftWorkflow(
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

    # 上抛章节的原始异常而不是 Agno 批次包装消息；失败批次后的章节不再启动。
    with pytest.raises(RuntimeError, match="section failed"):
        await workflow._run_sections(RunContext(run_id="run-1", session_id="session-1"))
    assert started == ["section_001"]


@pytest.mark.anyio
async def test_reporting_draft_workflow_arun_uses_agno_public_entrypoint() -> None:
    workflow = ReportingAnalysisAndDraftWorkflow(
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


@pytest.mark.anyio
async def test_rework_output_reruns_analysis_visualization_and_draft_in_same_workflow() -> None:
    events: list[str] = []

    async def analysis(_instruction, _context):
        events.append("analysis")
        return _ok("analysis")

    async def visualization(_instruction, _context):
        events.append("visualization")
        return _ok("visualization")

    async def rework(instruction, _context):
        events.append("rework")
        assert instruction["rework"] == {
            "analysisIds": ["a1"],
            "missingEvidence": ["同比"],
        }
        return _ok("rework")

    async def draft(_instruction, _context):
        events.append("draft")
        if events.count("draft") == 1:
            return StepOutput(
                content={
                    "sectionCode": "section_001",
                    "status": "rework",
                    "rework": {"analysisIds": ["a1"], "missingEvidence": ["同比"]},
                }
            )
        return StepOutput(content={"sectionCode": "section_001", "status": "completed"})

    workflow = ReportingAnalysisAndDraftWorkflow(
        report_goal="目标",
        sections=[{"sectionCode": "section_001", "analysisIds": ["a1"]}],
        run_analysis=analysis,
        submit_visualization=visualization,
        draft_section=draft,
        rework_analysis=rework,
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
        ],
    }
    assert events == [
        "analysis",
        "visualization",
        "draft",
        "rework",
        "visualization",
        "draft",
    ]


@pytest.mark.anyio
async def test_rework_exhaustion_forces_degraded_draft_without_stopping_workflow() -> None:
    rework_output = StepOutput(
        content={
            "sectionCode": "section_001",
            "status": "rework",
            "rework": {"analysisIds": ["a1"], "missingEvidence": ["同比"]},
        }
    )

    draft_attempts = 0

    async def draft(instruction, _context):
        nonlocal draft_attempts
        draft_attempts += 1
        if instruction.get("forceDegradedDraft") is True:
            assert instruction["rework"] == rework_output.content["rework"]
            return StepOutput(content={"sectionCode": "section_001", "status": "completed"})
        return rework_output

    workflow = ReportingDraftWorkflow(
        report_goal="目标",
        section_goal={"sectionCode": "section_001"},
        analysis_ids=["a1"],
        run_analysis=AsyncMock(return_value=_ok("analysis")),
        submit_visualization=AsyncMock(return_value=_ok("visualization")),
        draft_section=draft,
        rework_analysis=AsyncMock(return_value=_ok("rework")),
    )

    result = await workflow.execute_section(RunContext(run_id="run-1", session_id="session-1"))

    assert result.draft_output.content == {
        "sectionCode": "section_001",
        "status": "completed",
    }
    assert draft_attempts == 3


@pytest.mark.anyio
async def test_forced_degraded_draft_rework_is_not_reported_completed() -> None:
    rework_output = StepOutput(
        content={
            "sectionCode": "section_001",
            "status": "rework",
            "rework": {"analysisIds": ["a1"], "missingEvidence": ["同比"]},
        }
    )
    workflow = ReportingDraftWorkflow(
        report_goal="目标",
        section_goal={"sectionCode": "section_001"},
        analysis_ids=["a1"],
        run_analysis=AsyncMock(return_value=_ok("analysis")),
        submit_visualization=AsyncMock(return_value=_ok("visualization")),
        draft_section=AsyncMock(return_value=rework_output),
        rework_analysis=AsyncMock(return_value=_ok("rework")),
    )

    with pytest.raises(RuntimeError, match="章节强制降级成稿未完成"):
        await workflow.execute_section(RunContext(run_id="run-1", session_id="session-1"))


@pytest.mark.anyio
async def test_parallel_rework_analysis_uses_shared_analysis_limiter() -> None:
    active = 0
    maximum = 0
    draft_attempts: dict[str, int] = {}

    async def rework(_instruction, _context):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        return _ok("rework")

    async def draft(instruction, _context):
        section_code = instruction["sectionCode"]
        draft_attempts[section_code] = draft_attempts.get(section_code, 0) + 1
        if draft_attempts[section_code] == 1:
            return StepOutput(
                content={
                    "status": "rework",
                    "rework": {"analysisIds": instruction["analysisIds"]},
                }
            )
        return StepOutput(content={"sectionCode": section_code, "status": "completed"})

    workflow = ReportingAnalysisAndDraftWorkflow(
        report_goal="目标",
        sections=[
            {"sectionCode": "section_001", "analysisIds": ["a1"]},
            {"sectionCode": "section_002", "analysisIds": ["a2"]},
        ],
        run_analysis=AsyncMock(return_value=_ok("analysis")),
        submit_visualization=AsyncMock(return_value=_ok("visualization")),
        draft_section=draft,
        rework_analysis=rework,
        execution_mode="parallel",
        section_concurrency=2,
        analysis_concurrency=1,
    )

    await workflow._run_sections(RunContext(run_id="run-1", session_id="session-1"))

    assert maximum == 1


def test_parallel_plan_uses_agno_parallel_container() -> None:
    workflow = ReportingDraftWorkflow(
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
        build_reporting_draft_steps(workflow, RunContext(run_id="run-1", session_id="session-1")),
        Parallel,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["sequential", "parallel"])
async def test_section_failures_keep_original_reporting_error(mode: str) -> None:
    from smart_reporting.reporting.models import ReportingError

    async def failing_analysis(_instruction, _context):
        raise ReportingError("report_semantic_contract_upgrade_required", "请重新分析")

    workflow = ReportingAnalysisAndDraftWorkflow(
        report_goal="目标",
        sections=[
            {"sectionCode": "section_001", "analysisIds": ["analysis_001"]},
            {"sectionCode": "section_002", "analysisIds": ["analysis_002"]},
        ],
        run_analysis=failing_analysis,
        submit_visualization=AsyncMock(return_value=_ok("ok")),
        draft_section=AsyncMock(return_value=_ok("ok")),
        execution_mode=mode,
        section_concurrency=2,
    )

    # Agno Steps/Parallel 会把子步骤异常转成 success=False；稳定错误码必须原样上抛。
    with pytest.raises(ReportingError) as caught:
        await workflow._run_sections(RunContext(run_id="run-1", session_id="session-1"))
    assert caught.value.code == "report_semantic_contract_upgrade_required"

    # Agno 默认 on_error=skip 会返回 completed；章节 Step 必须失败关闭并原样上抛。
    with pytest.raises(ReportingError) as caught_run:
        await workflow.arun(input={"reportGoal": "目标"}, run_id="run-2", session_id="session-2")
    assert caught_run.value.code == "report_semantic_contract_upgrade_required"
    assert workflow.execution_error is caught_run.value
