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
    execute_analysis_items,
)


def _ok(value: str) -> StepOutput:
    return StepOutput(content=value)


@pytest.mark.anyio
@pytest.mark.parametrize("status,code,visual_calls", [
    ("budget_exhausted", "report_quality_budget_exhausted", 1),
    ("degraded", "report_quality_supplement_failed", 2),
])
async def test_quality_budget_exhaustion_preserves_visuals_and_drafts_with_gap(status, code, visual_calls):
    visualization = AsyncMock(return_value=_ok("existing visuals"))
    analysis = AsyncMock(return_value=_ok("analysis"))
    calls = []

    async def draft(instruction, _context):
        calls.append(dict(instruction))
        if len(calls) == 1:
            return StepOutput(content={"status": "rework", "rework": {
                "analysisIds": ["a1"], "missingEvidence": ["baseline"],
            }})
        assert instruction["analysisReworkAllowed"] is False
        assert instruction["rework"]["budgetCode"] == code
        return StepOutput(content={"status": "completed"})

    workflow = ReportingDraftWorkflow(
        report_goal="目标", section_goal={"sectionCode": "s1"}, analysis_ids=["a1"],
        run_analysis=analysis, submit_visualization=visualization, draft_section=draft,
        rework_analysis=AsyncMock(return_value=StepOutput(content={
            "status": status, "budgetCode": code,
        })),
    )
    result = await workflow.execute_section(RunContext(run_id="run", session_id="session"))
    assert result.draft_output.content["status"] == "completed"
    assert visualization.await_count == visual_calls
    assert analysis.await_count == 1


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
@pytest.mark.parametrize(
    "analysis_groups",
    [(["a1", "a7"], ["a7"], ["a8"]),
     (["a1"], ["a2"], ["a1", "a2"])],
)
async def test_shared_frozen_evidence_is_not_read_during_section_rework(analysis_groups):
    evidence = {analysis_id: 1 for group in analysis_groups for analysis_id in group}
    drafted = set()
    seen = {}

    async def visualization(instruction, _context):
        assert all(analysis_id in evidence for analysis_id in instruction["analysisIds"])
        return _ok("visualization")

    async def draft(instruction, _context):
        code = instruction["sectionCode"]
        if code not in drafted:
            drafted.add(code)
            return StepOutput(content={"status": "rework", "rework": {
                "analysisIds": instruction["analysisIds"],
            }})
        seen[code] = [evidence[item] for item in instruction["analysisIds"]]
        return StepOutput(content={"status": "completed"})

    async def rework(instruction, _context):
        ids = instruction["rework"]["analysisIds"]
        previous = {item: evidence.pop(item) for item in ids}
        # 重现 reducer 先撤销证据、补证完成后重新登记的可见时间窗口。
        await asyncio.sleep(0)
        evidence.update({item: value + 1 for item, value in previous.items()})
        return _ok("rework")

    workflow = ReportingAnalysisAndDraftWorkflow(
        report_goal="目标",
        sections=[{"sectionCode": f"s{index}", "analysisIds": group}
                  for index, group in enumerate(analysis_groups, 1)],
        run_analysis=AsyncMock(side_effect=AssertionError("冻结证据不可重复初次分析")),
        submit_visualization=visualization, draft_section=draft, rework_analysis=rework,
        execution_mode="parallel", section_concurrency=3, evidence_frozen=True,
    )
    results = await workflow._run_sections(RunContext(run_id="run", session_id="session"))
    assert [result.section_code for result in results] == ["s1", "s2", "s3"]
    if analysis_groups[0] == ["a1", "a7"]:
        assert seen == {"s1": [2, 2], "s2": [3], "s3": [2]}
    else:
        assert seen == {"s1": [2], "s2": [2], "s3": [3, 3]}


@pytest.mark.anyio
async def test_disjoint_frozen_sections_still_run_concurrently():
    both_started = asyncio.Event()
    active = 0

    async def visualization(_instruction, _context):
        nonlocal active
        active += 1
        if active == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=2)
        return _ok("visualization")

    workflow = ReportingAnalysisAndDraftWorkflow(
        report_goal="目标",
        sections=[{"sectionCode": "s1", "analysisIds": ["a1"]},
                  {"sectionCode": "s2", "analysisIds": ["a2"]}],
        run_analysis=AsyncMock(side_effect=AssertionError("冻结证据不可重复初次分析")),
        submit_visualization=visualization,
        draft_section=AsyncMock(return_value=StepOutput(content={"status": "completed"})),
        execution_mode="parallel", section_concurrency=2, evidence_frozen=True,
    )
    results = await workflow._run_sections(RunContext(run_id="run", session_id="session"))
    assert [result.section_code for result in results] == ["s1", "s2"]


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


@pytest.mark.anyio
async def test_parallel_analysis_items_run_concurrently_up_to_the_shared_limit() -> None:
    # 补证阶段与章节共用同一执行函数：parallel 模式按 limiter 并发，输出保持计划顺序。
    active = maximum = 0
    release = asyncio.Event()

    async def analysis(analysis_id):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if maximum == 2:
            release.set()
        await release.wait()
        active -= 1
        return _ok(analysis_id)

    outputs = await execute_analysis_items(
        ["a1", "a2", "a3", "a4"], analysis, execution_mode="parallel",
        limiter=asyncio.Semaphore(2), run_context=RunContext(run_id="run-1", session_id="session-1"),
    )
    assert maximum == 2
    assert [output.content for output in outputs] == ["a1", "a2", "a3", "a4"]


@pytest.mark.anyio
async def test_parallel_analysis_default_runs_five_items_and_preserves_plan_order() -> None:
    active = maximum = 0
    release = asyncio.Event()
    completed_sections = []

    async def analysis(instruction, _context):
        nonlocal active, maximum
        if instruction['sectionCode'] == 's2':
            assert completed_sections == ['s1']
        active += 1
        maximum = max(maximum, active)
        if maximum == 5:
            release.set()
        await release.wait()
        active -= 1
        return _ok(instruction['analysisId'])

    async def draft(instruction, _context):
        completed_sections.append(instruction['sectionCode'])
        return _ok('draft')

    workflow = ReportingAnalysisAndDraftWorkflow(
        report_goal='验证默认五并发',
        sections=[
            {'sectionCode': 's1', 'analysisIds': ['a1', 'a2', 'a3', 'a4', 'a5', 'a6']},
            {'sectionCode': 's2', 'analysisIds': ['a7']},
        ],
        run_analysis=analysis, submit_visualization=AsyncMock(return_value=_ok('visual')),
        draft_section=draft,
    )
    result = await asyncio.wait_for(
        workflow._run_sections(RunContext(run_id='run-1', session_id='session-1')),
        timeout=2,
    )
    assert maximum == 5
    assert [output.content for output in result[0].analysis_outputs] == ['a1', 'a2', 'a3', 'a4', 'a5', 'a6']
    assert [output.content for output in result[1].analysis_outputs] == ['a7']
    assert completed_sections == ['s1', 's2']


@pytest.mark.anyio
@pytest.mark.parametrize(("mode", "expected_started"), [
    ("sequential", ["a1", "a2"]),
    ("parallel", ["a1", "a2", "a3"]),
])
async def test_analysis_item_failure_keeps_the_original_error(mode, expected_started) -> None:
    from smart_reporting.reporting.models import ReportingError

    started: list[str] = []

    async def analysis(analysis_id):
        started.append(analysis_id)
        if analysis_id == "a2":
            raise ReportingError("report_analysis_task_terminal", "分析项 a2 Task 未完成收尾即终止。")
        return _ok(analysis_id)

    # 顺序模式首个失败即停，不再为后续分析项调用模型；两种模式都按计划顺序上抛原始错误。
    with pytest.raises(ReportingError) as caught:
        await execute_analysis_items(
            ["a1", "a2", "a3"], analysis, execution_mode=mode,
            limiter=asyncio.Semaphore(3), run_context=RunContext(run_id="run-1", session_id="session-1"),
        )
    assert caught.value.code == "report_analysis_task_terminal"
    assert sorted(started) == expected_started


@pytest.mark.anyio
@pytest.mark.parametrize(('concurrency', 'valid'), [
    (6, False), (True, False), (1.5, False), (0, False),
    (1, True), (3, True), (5, True),
])
async def test_analysis_workflow_requires_bounded_integer_concurrency(concurrency, valid) -> None:
    active = maximum = 0

    async def analysis(instruction, _context):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        return _ok(instruction['analysisId'])

    async def complete(_instruction, _context):
        return _ok('completed')

    def build():
        return ReportingAnalysisAndDraftWorkflow(
            report_goal='验证分析并发参数边界',
            sections=[{'sectionCode': 's1', 'analysisIds': ['a1', 'a2', 'a3', 'a4', 'a5', 'a6']}],
            run_analysis=analysis, submit_visualization=complete, draft_section=complete,
            execution_mode='parallel', analysis_concurrency=concurrency,
        )

    if not valid:
        with pytest.raises(ValueError):
            build()
        return

    workflow = build()
    result = await workflow.sections[0].execute_section(RunContext(run_id='run', session_id='session'))
    assert maximum == concurrency
    assert [output.content for output in result.analysis_outputs] == ['a1', 'a2', 'a3', 'a4', 'a5', 'a6']
