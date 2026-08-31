from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from agno.run.agent import ModelRequestCompletedEvent, RunContinuedEvent

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.checkpoint import reporting_phase_task_key
from smart_reporting.reporting.workflow.execution import (
    ReportTaskRunner,
    _TaskModelMetricsSettlement,
    _worker_session_id,
)
from smart_reporting.task_execution import TaskScope, TaskState


class _RecordedErrors:
    def __init__(self, errors: list[Exception | None]):
        self._errors = iter(errors)

    def report_run_error(self) -> Exception | None:
        return next(self._errors)


def test_worker_finish_receipt_sums_every_model_request_event() -> None:
    settlement = _TaskModelMetricsSettlement(
        task_id="analysis-task-1",
        phase_attempt=1,
        agno_run_id="agno-run-1",
    )
    settlement.record(
        ModelRequestCompletedEvent(
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            reasoning_tokens=5,
            cache_read_tokens=40,
        )
    )
    settlement.record(
        ModelRequestCompletedEvent(
            input_tokens=200,
            output_tokens=30,
            total_tokens=230,
            reasoning_tokens=7,
            cache_write_tokens=9,
        )
    )

    receipt = ReportTaskRunner._finish_receipt(
        SimpleNamespace(finish_receipt={"ok": True}),
        model_metrics=settlement.snapshot(),
    )

    assert receipt["modelMetrics"] == {
        "requestCount": 2,
        "inputTokens": 300,
        "outputTokens": 50,
        "totalTokens": 350,
        "reasoningTokens": 12,
        "cacheReadTokens": 40,
        "cacheWriteTokens": 9,
    }


def test_task_model_metrics_settles_failed_requests_once(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict[str, int | float]] = []
    monkeypatch.setattr(
        "smart_reporting.reporting.workflow.execution.record_step_model_metrics",
        lambda value: recorded.append(value),
    )
    settlement = _TaskModelMetricsSettlement(
        task_id="analysis-task-1",
        phase_attempt=2,
        agno_run_id="agno-run-1",
    )
    settlement.record(
        ModelRequestCompletedEvent(
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            reasoning_tokens=5,
            cache_read_tokens=40,
            cache_write_tokens=3,
            time_to_first_token=1.25,
        )
    )

    settlement.settle(outcome="failed")
    settlement.settle(outcome="failed")

    assert recorded == [
        {
            "requestCount": 1,
            "inputTokens": 100,
            "outputTokens": 20,
            "totalTokens": 120,
            "reasoningTokens": 5,
            "cacheReadTokens": 40,
            "cacheWriteTokens": 3,
            "timeToFirstTokenSeconds": 1.25,
        }
    ]


def test_task_model_metrics_settles_cancelled_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict[str, int | float]] = []
    monkeypatch.setattr(
        "smart_reporting.reporting.workflow.execution.record_step_model_metrics",
        lambda value: recorded.append(value),
    )
    settlement = _TaskModelMetricsSettlement(
        task_id="section-task-1",
        phase_attempt=1,
        agno_run_id="agno-run-2",
    )
    settlement.record(ModelRequestCompletedEvent(total_tokens=42))
    settlement.settle(outcome="cancelled")

    assert recorded == [
        {
            "requestCount": 1,
            "inputTokens": 0,
            "outputTokens": 0,
            "totalTokens": 42,
            "reasoningTokens": 0,
            "cacheReadTokens": 0,
            "cacheWriteTokens": 0,
        }
    ]


def test_task_model_metrics_deduplicates_replayed_continuation_response() -> None:
    settlement = _TaskModelMetricsSettlement(
        task_id="visualization-task-1",
        phase_attempt=3,
        agno_run_id="agno-run-3",
    )
    first = ModelRequestCompletedEvent(total_tokens=230, reasoning_tokens=7)
    second = ModelRequestCompletedEvent(total_tokens=310, reasoning_tokens=11)

    settlement.record(first, model_response_index=0)
    settlement.record(second, model_response_index=1)
    settlement.record(first, model_response_index=0)
    settlement.record(second, model_response_index=1)
    settlement.record(
        ModelRequestCompletedEvent(total_tokens=400, reasoning_tokens=13),
        model_response_index=2,
    )

    assert settlement.snapshot()["requestCount"] == 3
    assert settlement.snapshot()["totalTokens"] == 940
    assert settlement.snapshot()["reasoningTokens"] == 31


@pytest.mark.anyio
async def test_consume_run_deduplicates_replayed_continuation_model_events() -> None:
    first = ModelRequestCompletedEvent(
        created_at=1_700_000_001,
        run_id="agno-run-3",
        total_tokens=230,
        reasoning_tokens=7,
    )
    second = ModelRequestCompletedEvent(
        created_at=1_700_000_002,
        run_id="agno-run-3",
        total_tokens=310,
        reasoning_tokens=11,
    )
    third = ModelRequestCompletedEvent(
        created_at=1_700_000_003,
        run_id="agno-run-3",
        total_tokens=400,
        reasoning_tokens=13,
    )

    async def events(*values: Any):
        for value in values:
            yield value

    settlement = _TaskModelMetricsSettlement(
        task_id="visualization-task-1",
        phase_attempt=3,
        agno_run_id="agno-run-3",
    )
    runner = cast(Any, object.__new__(ReportTaskRunner))
    runner.idle_timeout_seconds = 1
    runner.event_sink = None
    scope = SimpleNamespace()

    await runner._consume_run(
        events(first, second),
        scope,
        "workflow-run-1",
        model_metrics_settlement=settlement,
    )
    await runner._consume_run(
        events(first, second, RunContinuedEvent(run_id="agno-run-3"), third),
        scope,
        "workflow-run-1",
        continuation=True,
        model_metrics_settlement=settlement,
    )

    assert settlement.snapshot()["requestCount"] == 3
    assert settlement.snapshot()["totalTokens"] == 940
    assert settlement.snapshot()["reasoningTokens"] == 31


@pytest.mark.anyio
async def test_consume_run_counts_distinct_model_events_with_equal_token_metrics() -> None:
    first = ModelRequestCompletedEvent(
        created_at=1_700_000_001,
        run_id="agno-run-equal",
        total_tokens=230,
    )
    same_second_continuation = ModelRequestCompletedEvent(
        created_at=1_700_000_001,
        run_id="agno-run-equal",
        total_tokens=230,
    )

    async def events(*values: Any):
        for value in values:
            yield value

    settlement = _TaskModelMetricsSettlement(
        task_id="analysis-task-equal",
        phase_attempt=1,
        agno_run_id="agno-run-equal",
    )
    runner = cast(Any, object.__new__(ReportTaskRunner))
    runner.idle_timeout_seconds = 1
    runner.event_sink = None

    await runner._consume_run(
        events(first),
        SimpleNamespace(),
        "workflow-run-1",
        model_metrics_settlement=settlement,
    )
    await runner._consume_run(
        events(
            RunContinuedEvent(run_id="agno-run-equal"),
            same_second_continuation,
        ),
        SimpleNamespace(),
        "workflow-run-1",
        continuation=True,
        model_metrics_settlement=settlement,
    )

    assert settlement.snapshot()["requestCount"] == 2
    assert settlement.snapshot()["totalTokens"] == 460


@pytest.mark.anyio
async def test_consume_run_ignores_replayed_prefix_when_continuation_breaks_before_boundary() -> (
    None
):
    historical = ModelRequestCompletedEvent(
        created_at=1_700_000_001,
        run_id="agno-run-broken-continuation",
        total_tokens=230,
    )

    async def broken_replay():
        yield historical
        raise RuntimeError("stream disconnected before RunContinued")

    settlement = _TaskModelMetricsSettlement(
        task_id="analysis-task-broken-continuation",
        phase_attempt=1,
        agno_run_id="agno-run-broken-continuation",
    )
    settlement.record(historical, model_response_index=0)
    runner = cast(Any, object.__new__(ReportTaskRunner))
    runner.idle_timeout_seconds = 1
    runner.event_sink = None

    with pytest.raises(RuntimeError, match="stream disconnected"):
        await runner._consume_run(
            broken_replay(),
            SimpleNamespace(),
            "workflow-run-1",
            continuation=True,
            model_metrics_settlement=settlement,
        )

    assert settlement.snapshot()["requestCount"] == 1
    assert settlement.snapshot()["totalTokens"] == 230


def test_task_model_metrics_matches_historical_sample() -> None:
    settlement = _TaskModelMetricsSettlement(
        task_id="historical-task",
        phase_attempt=1,
        agno_run_id="historical-agno-run",
    )
    for index in range(97):
        settlement.record(
            ModelRequestCompletedEvent(total_tokens=30_000, reasoning_tokens=1_000),
            model_response_index=index,
        )
    settlement.record(
        ModelRequestCompletedEvent(total_tokens=263_436, reasoning_tokens=12_509),
        model_response_index=97,
    )

    metrics = settlement.snapshot()
    assert metrics["requestCount"] == 98
    assert metrics["totalTokens"] == 3_173_436
    assert metrics["reasoningTokens"] == 109_509


@pytest.mark.anyio
async def test_worker_error_continues_same_agno_run_without_replaying_instruction() -> None:
    transient = RuntimeError("transient tool failure")
    worker = SimpleNamespace(
        model=_RecordedErrors([transient, None]),
        arun=MagicMock(return_value="initial-run"),
        acontinue_run=MagicMock(return_value="continued-run"),
    )
    runner = cast(Any, object.__new__(ReportTaskRunner))
    runner.worker = worker
    runner._consume_run = AsyncMock(side_effect=["failed-output", "completed-output"])

    output = await runner._run_worker(
        continuing=False,
        instruction="original analysis_001 instruction",
        internal_run_id="worker-run-1",
        worker_session_id="worker-session-1",
        owner_user_id="user-1",
        dependencies={"scope": "analysis"},
        run_context=SimpleNamespace(),
        scope=SimpleNamespace(),
        parent_run_id="workflow-run-1",
    )

    assert output == "completed-output"
    worker.arun.assert_called_once()
    assert worker.arun.call_args.args == ("original analysis_001 instruction",)
    worker.acontinue_run.assert_called_once()
    assert worker.acontinue_run.call_args.kwargs["run_id"] == "worker-run-1"
    assert "不得重放原始任务" in worker.acontinue_run.call_args.kwargs["input"]
    assert "additional_instructions" not in worker.acontinue_run.call_args.kwargs


@pytest.mark.anyio
async def test_worker_reporting_error_is_raised_without_continuation() -> None:
    terminal = ReportingError(
        "report_tool_arguments_invalid",
        "Reporting 工具参数不符合严格调用 schema。",
        details={"terminalReason": "tool_no_progress"},
    )
    worker = SimpleNamespace(
        model=_RecordedErrors([terminal]),
        arun=MagicMock(return_value="initial-run"),
        acontinue_run=MagicMock(return_value="unexpected-continuation"),
    )
    runner = cast(Any, object.__new__(ReportTaskRunner))
    runner.worker = worker
    runner._consume_run = AsyncMock(return_value="failed-output")

    with pytest.raises(ReportingError) as raised:
        await runner._run_worker(
            continuing=False,
            instruction="original instruction",
            internal_run_id="worker-run-1",
            worker_session_id="worker-session-1",
            owner_user_id="user-1",
            dependencies={},
            run_context=SimpleNamespace(),
            scope=SimpleNamespace(),
            parent_run_id="workflow-run-1",
        )

    assert raised.value is terminal
    worker.arun.assert_called_once()
    worker.acontinue_run.assert_not_called()


@pytest.mark.anyio
async def test_worker_continuation_exhaustion_raises_original_error() -> None:
    terminal = RuntimeError("terminal tool failure")
    worker = SimpleNamespace(
        model=_RecordedErrors([terminal, terminal, terminal]),
        arun=MagicMock(return_value="initial-run"),
        acontinue_run=MagicMock(return_value="continued-1"),
    )
    runner = cast(Any, object.__new__(ReportTaskRunner))
    runner.worker = worker
    runner._consume_run = AsyncMock(side_effect=["failed-output-1", "failed-output-2"])

    with pytest.raises(RuntimeError) as raised:
        await runner._run_worker(
            continuing=False,
            instruction="original instruction",
            internal_run_id="worker-run-1",
            worker_session_id="worker-session-1",
            owner_user_id="user-1",
            dependencies={},
            run_context=SimpleNamespace(),
            scope=SimpleNamespace(),
            parent_run_id="workflow-run-1",
        )

    assert raised.value is terminal
    worker.arun.assert_called_once()
    worker.acontinue_run.assert_called_once()


@pytest.mark.anyio
async def test_section_worker_plain_text_reports_missing_terminal_tool_without_continuation() -> (
    None
):
    worker = SimpleNamespace(
        model=_RecordedErrors([None, None]),
        arun=MagicMock(return_value="initial-run"),
        acontinue_run=MagicMock(return_value="continued-run"),
    )
    runner = cast(Any, object.__new__(ReportTaskRunner))
    runner.worker = worker
    runner.repository = SimpleNamespace(
        get_task_snapshot=AsyncMock(return_value=SimpleNamespace(state=TaskState.ACTIVE))
    )
    runner._consume_run = AsyncMock(side_effect=["plain-text", "plain-text-again"])

    with pytest.raises(ReportingError) as raised:
        await runner._run_worker(
            continuing=False,
            instruction="render section_001",
            internal_run_id="worker-run-1",
            worker_session_id="worker-session-1",
            owner_user_id="user-1",
            dependencies={"AgentOS 编码任务": {"reportingTaskKind": "section"}},
            run_context=SimpleNamespace(),
            scope=SimpleNamespace(external_run_id="section-task-1"),
            parent_run_id="workflow-run-1",
        )

    assert raised.value.code == "report_worker_terminal_tool_missing"
    assert raised.value.details == {
        "taskKind": "section",
        "requiredTerminalTools": ["render_report_section", "request_analysis_rework"],
    }
    worker.arun.assert_called_once()
    worker.acontinue_run.assert_not_called()


@pytest.mark.anyio
async def test_visualization_worker_plain_text_reports_missing_terminal_tool_without_continuation() -> (
    None
):
    worker = SimpleNamespace(
        model=_RecordedErrors([None, None]),
        arun=MagicMock(return_value="initial-run"),
        acontinue_run=MagicMock(return_value="continued-run"),
    )
    runner = cast(Any, object.__new__(ReportTaskRunner))
    runner.worker = worker
    runner.repository = SimpleNamespace(
        get_task_snapshot=AsyncMock(return_value=SimpleNamespace(state=TaskState.ACTIVE))
    )
    runner._consume_run = AsyncMock(side_effect=["plain-text", "plain-text-again"])

    with pytest.raises(ReportingError) as raised:
        await runner._run_worker(
            continuing=False,
            instruction="render visualization",
            internal_run_id="worker-run-visualization-1",
            worker_session_id="worker-session-visualization-1",
            owner_user_id="user-1",
            dependencies={"AgentOS 编码任务": {"reportingTaskKind": "visualization_finalize"}},
            run_context=SimpleNamespace(),
            scope=SimpleNamespace(external_run_id="visualization-task-1"),
            parent_run_id="workflow-run-1",
        )

    assert raised.value.code == "report_worker_terminal_tool_missing"
    assert raised.value.details == {
        "taskKind": "visualization_finalize",
        "requiredTerminalTools": ["finalize_report_analysis"],
    }
    worker.arun.assert_called_once()
    worker.acontinue_run.assert_called_once()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("task_kind", "required_terminal_tools"),
    [
        ("visualization_section", ["submit_visualization_charts"]),
        ("visualization_finalize", ["finalize_report_analysis"]),
    ],
)
async def test_terminal_tools_for_new_visualization_task_kinds(
    task_kind: str, required_terminal_tools: list[str]
) -> None:
    worker = SimpleNamespace(
        model=_RecordedErrors([None, None]),
        arun=MagicMock(return_value="initial-run"),
        acontinue_run=MagicMock(return_value="continued-run"),
    )
    runner = cast(Any, object.__new__(ReportTaskRunner))
    runner.worker = worker
    runner.repository = SimpleNamespace(
        get_task_snapshot=AsyncMock(return_value=SimpleNamespace(state=TaskState.ACTIVE))
    )
    runner._consume_run = AsyncMock(side_effect=["plain-text", "plain-text-again"])

    with pytest.raises(ReportingError) as raised:
        await runner._run_worker(
            continuing=False,
            instruction="run visualization task",
            internal_run_id="worker-run-visualization-new-1",
            worker_session_id="worker-session-visualization-new-1",
            owner_user_id="user-1",
            dependencies={"AgentOS 编码任务": {"reportingTaskKind": task_kind}},
            run_context=SimpleNamespace(),
            scope=SimpleNamespace(external_run_id="visualization-new-task-1"),
            parent_run_id="workflow-run-1",
        )

    assert raised.value.details["requiredTerminalTools"] == required_terminal_tools


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("task_kind", "expected_instruction"),
    [
        (
            "visualization_section",
            "服务端已保留本 run 已生成的该章图表文件。立即停止重新探索;"
            "脚本尚未执行时先且只执行一次签发的本章脚本;"
            "随后只调用一次 submit_visualization_charts 提交该章全部图表草案,"
            "缺失的图表不要提交。不得调用 read_file,不得输出解释性文本。",
        ),
        (
            "visualization_finalize",
            "服务端已保留全部章节图表草案。立即停止重新探索;"
            "只调用一次 register_report_charts 整批登记,随后立即调用 "
            "finalize_report_analysis。不得调用 read_file/query_analysis_facts,"
            "不得输出解释性文本。",
        ),
    ],
)
async def test_recovery_instruction_for_new_visualization_task_kinds(
    task_kind: str, expected_instruction: str
) -> None:
    worker = SimpleNamespace(
        model=_RecordedErrors([None, None]),
        arun=MagicMock(return_value="initial-run"),
        acontinue_run=MagicMock(return_value="continued-run"),
    )
    runner = cast(Any, object.__new__(ReportTaskRunner))
    runner.worker = worker
    runner.repository = SimpleNamespace(
        get_task_snapshot=AsyncMock(
            side_effect=[
                SimpleNamespace(state=TaskState.ACTIVE),
                SimpleNamespace(state=TaskState.FINISHING),
            ]
        )
    )
    runner._consume_run = AsyncMock(side_effect=["plain-text", "completed-output"])

    output = await runner._run_worker(
        continuing=False,
        instruction="run visualization task",
        internal_run_id="worker-run-visualization-recovery-1",
        worker_session_id="worker-session-visualization-recovery-1",
        owner_user_id="user-1",
        dependencies={"AgentOS 编码任务": {"reportingTaskKind": task_kind}},
        run_context=SimpleNamespace(),
        scope=SimpleNamespace(external_run_id="visualization-recovery-task-1"),
        parent_run_id="workflow-run-1",
    )

    assert output == "completed-output"
    recovery_input = worker.acontinue_run.call_args.kwargs["input"]
    assert recovery_input == expected_instruction


@pytest.mark.anyio
async def test_visualization_worker_with_persisted_progress_continues_same_run() -> None:
    worker = SimpleNamespace(
        model=_RecordedErrors([None, None]),
        arun=MagicMock(return_value="initial-run"),
        acontinue_run=MagicMock(return_value="continued-run"),
    )
    runner = cast(Any, object.__new__(ReportTaskRunner))
    runner.worker = worker
    runner.repository = SimpleNamespace(
        get_task_snapshot=AsyncMock(
            side_effect=[
                SimpleNamespace(state=TaskState.ACTIVE),
                SimpleNamespace(state=TaskState.FINISHING),
            ]
        )
    )
    runner._consume_run = AsyncMock(side_effect=["plain-text", "completed-output"])
    run_context = SimpleNamespace(
        run_id="worker-run-visualization-progress",
        session_state={
            "agentos_reporting_visualization_script_written": True,
        },
    )

    output = await runner._run_worker(
        continuing=False,
        instruction="render visualization",
        internal_run_id="worker-run-visualization-progress",
        worker_session_id="worker-session-visualization-progress",
        owner_user_id="user-1",
        dependencies={
            "AgentOS 编码任务": {
                "reportingTaskKind": "visualization_section",
                "externalRunId": "visualization-task-1",
            }
        },
        run_context=run_context,
        scope=SimpleNamespace(external_run_id="visualization-task-1"),
        parent_run_id="workflow-run-1",
    )

    assert output == "completed-output"
    worker.arun.assert_called_once()
    worker.acontinue_run.assert_called_once()
    recovery_input = worker.acontinue_run.call_args.kwargs["input"]
    assert "submit_visualization_charts" in recovery_input
    assert "不得输出解释性文本" in recovery_input


@pytest.mark.anyio
async def test_visualization_worker_with_only_successful_exploration_does_not_continue() -> None:
    worker = SimpleNamespace(
        model=_RecordedErrors([None, None]),
        arun=MagicMock(return_value="initial-run"),
        acontinue_run=MagicMock(return_value="continued-run"),
    )
    runner = cast(Any, object.__new__(ReportTaskRunner))
    runner.worker = worker
    runner.repository = SimpleNamespace(
        get_task_snapshot=AsyncMock(return_value=SimpleNamespace(state=TaskState.ACTIVE))
    )
    runner._consume_run = AsyncMock(return_value="plain-text")
    run_context = SimpleNamespace(
        run_id="worker-run-visualization-exploration",
        session_state={
            "agentos_reporting_visualization_tool_budget": {
                "visualization-task-1:worker-run-visualization-exploration": {
                    "attemptedCount": 1,
                    "successfulCount": 1,
                }
            }
        },
    )

    with pytest.raises(ReportingError, match="report_worker_terminal_tool_missing"):
        await runner._run_worker(
            continuing=False,
            instruction="render visualization",
            internal_run_id="worker-run-visualization-exploration",
            worker_session_id="worker-session-visualization-exploration",
            owner_user_id="user-1",
            dependencies={
                "AgentOS 编码任务": {
                    "reportingTaskKind": "visualization_section",
                    "externalRunId": "visualization-task-1",
                }
            },
            run_context=run_context,
            scope=SimpleNamespace(external_run_id="visualization-task-1"),
            parent_run_id="workflow-run-1",
        )

    worker.acontinue_run.assert_called_once()


def test_each_analysis_and_visualization_use_distinct_task_and_session_identities() -> None:
    analysis_001 = reporting_phase_task_key(
        "workflow-run-1", 1, "analysis", analysis_id="analysis_001"
    )
    analysis_002 = reporting_phase_task_key(
        "workflow-run-1", 1, "analysis", analysis_id="analysis_002"
    )
    visualization = reporting_phase_task_key(
        "workflow-run-1", 1, "analysis", task_key="viz-finalize", task_kind="visualization_finalize"
    )
    task_ids = {analysis_001, analysis_002, visualization}

    assert len(task_ids) == 3
    session_ids = {
        _worker_session_id(TaskScope(task_id, "user-1", "thread-1", "sandbox-1", "worker-1"))
        for task_id in task_ids
    }
    assert len(session_ids) == 3
