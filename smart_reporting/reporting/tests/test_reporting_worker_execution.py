from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from smart_reporting.reporting.workflow.checkpoint import reporting_phase_task_key
from smart_reporting.reporting.workflow.execution import ReportTaskRunner, _worker_session_id
from smart_reporting.task_execution import TaskScope


class _RecordedErrors:
    def __init__(self, errors: list[Exception | None]):
        self._errors = iter(errors)

    def report_run_error(self) -> Exception | None:
        return next(self._errors)


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
    assert "不得重放原始任务" in worker.acontinue_run.call_args.kwargs["additional_instructions"]


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


def test_each_analysis_and_visualization_use_distinct_task_and_session_identities() -> None:
    analysis_001 = reporting_phase_task_key(
        "workflow-run-1", 1, "analysis", analysis_id="analysis_001"
    )
    analysis_002 = reporting_phase_task_key(
        "workflow-run-1", 1, "analysis", analysis_id="analysis_002"
    )
    visualization = reporting_phase_task_key(
        "workflow-run-1", 1, "analysis", analysis_id="visualization"
    )
    task_ids = {analysis_001, analysis_002, visualization}

    assert len(task_ids) == 3
    session_ids = {
        _worker_session_id(TaskScope(task_id, "user-1", "thread-1", "sandbox-1", "worker-1"))
        for task_id in task_ids
    }
    assert len(session_ids) == 3
