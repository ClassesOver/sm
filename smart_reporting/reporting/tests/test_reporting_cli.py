from __future__ import annotations

import asyncio
import subprocess
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.db.in_memory import InMemoryDb
from agno.models.message import Message
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.workflow import OnError
from agno.workflow.step import Step
from agno.workflow.types import StepOutput
from loguru import logger

from smart_reporting.reporting import cli as reporting_cli
from smart_reporting.reporting.cli import (
    _cli_settings,
    _CliProgressSink,
    drive_workflow,
    parse_report_input,
    resume_workflow,
)
from smart_reporting.reporting.delivery.publishing import cli_result
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.controller import ReportWorkflowToolkit
from smart_reporting.reporting.workflow.orchestration import (
    _timed_step_executor,
    create_reporting_workflow,
    record_step_model_metrics,
)
from smart_reporting.runtime.settings import AgentSettings


class ErrorRequirement:
    def __init__(self, step_id: str = "validate-report") -> None:
        self.step_id = step_id
        self.step_name = "PDF/Word 双格式验收"
        self.decision = None

    @property
    def is_resolved(self) -> bool:
        return self.decision is not None

    def retry(self) -> None:
        self.decision = "retry"


class UncontendedStateRepository:
    def __init__(self) -> None:
        self.status_updates: list[tuple[str, str, bool | None]] = []

    @asynccontextmanager
    async def workflow_execution_lock(self, _run_id: str):
        yield

    async def update_run_status(
        self,
        report_run_id: str,
        *,
        status: str,
        finalization_pending: bool | None = None,
    ) -> None:
        self.status_updates.append((report_run_id, status, finalization_pending))


def runtime(**values: object) -> SimpleNamespace:
    return SimpleNamespace(state_repository=UncontendedStateRepository(), **values)


@pytest.mark.anyio
async def test_timed_workflow_step_logs_safe_success_and_failure() -> None:
    async def succeed() -> StepOutput:
        return StepOutput(content={"private": "workflow-output"})

    async def fail() -> StepOutput:
        raise RuntimeError("private-workflow-error")

    debug_records: list[str] = []
    info_records: list[str] = []
    debug_sink_id = logger.add(debug_records.append, level="DEBUG", format="{message}")
    info_sink_id = logger.add(info_records.append, level="INFO", format="{message}")

    try:
        output = await _timed_step_executor(succeed, step_id="confirm-source")()
        with pytest.raises(RuntimeError, match="private-workflow-error"):
            await _timed_step_executor(fail, step_id="prepare-data-profile")()
    finally:
        logger.remove(debug_sink_id)
        logger.remove(info_sink_id)

    log_text = "".join(debug_records)
    info_text = "".join(info_records)
    assert output.content == {"private": "workflow-output"}
    assert "report_workflow_step_started step_id=confirm-source" in log_text
    assert "report_workflow_step_completed step_id=confirm-source" in log_text
    assert "report_workflow_step_failed step_id=prepare-data-profile" in log_text
    assert info_text.count("report_workflow_step_started step_id=confirm-source") == 1
    assert info_text.count("report_workflow_step_completed step_id=confirm-source") == 1
    assert "report_workflow_step_failed step_id=prepare-data-profile" in info_text
    assert "error_type=RuntimeError" in log_text
    assert "workflow-output" not in log_text
    assert "private-workflow-error" not in log_text


@pytest.mark.anyio
async def test_timed_workflow_step_cancellation_does_not_log_failure() -> None:
    async def cancelled() -> StepOutput:
        raise asyncio.CancelledError

    records: list[str] = []
    sink_id = logger.add(records.append, level="WARNING", format="{message}")
    try:
        with pytest.raises(asyncio.CancelledError):
            await _timed_step_executor(cancelled, step_id="cancelled-step")()
    finally:
        logger.remove(sink_id)

    assert "report_workflow_step_failed" not in "".join(records)


@pytest.mark.anyio
async def test_timed_workflow_step_aggregates_metrics_from_concurrent_child_tasks() -> None:
    async def succeed() -> StepOutput:
        async def record(input_tokens: int) -> None:
            await asyncio.sleep(0)
            record_step_model_metrics(
                {
                    "requestCount": 1,
                    "inputTokens": input_tokens,
                    "outputTokens": 10,
                    "totalTokens": input_tokens + 10,
                    "timeToFirstTokenSeconds": 0.5,
                }
            )

        async with asyncio.TaskGroup() as task_group:
            task_group.create_task(record(100))
            task_group.create_task(record(200))
        return StepOutput(content="done")

    output = await _timed_step_executor(succeed, step_id="run-coding-analysis")()

    assert output.metrics is not None
    assert output.metrics.input_tokens == 300
    assert output.metrics.output_tokens == 20
    assert output.metrics.total_tokens == 320
    assert output.metrics.additional_metrics == {
        "request_count": 2,
        "time_to_first_token_seconds": 1.0,
    }


def test_report_input_parsing_is_shared_with_agentos() -> None:
    assert parse_report_input("生成 2025 年运营报告") == {
        "version": "1",
        "prompt": "生成 2025 年运营报告",
    }


def test_cli_publication_result_includes_html_artifact() -> None:
    result = cli_result(
        path="reports/report.pdf",
        size=1,
        sha256="a" * 64,
        word_path="reports/report.docx",
        word_size=2,
        word_sha256="b" * 64,
        html_path="reports/report.html",
        html_size=3,
        html_sha256="c" * 64,
    )

    assert result["html"] == {
        "path": "reports/report.html",
        "size": 3,
        "sha256": "c" * 64,
    }


@pytest.mark.anyio
async def test_agentos_report_start_accepts_cli_envelope_json() -> None:
    controller = SimpleNamespace(start=AsyncMock(return_value={"status": "running"}))
    toolkit = ReportWorkflowToolkit(controller)
    run_context = RunContext(
        run_id="run-1",
        session_id="thread-1",
        messages=[
            Message(
                role="user",
                content=(
                    '{"version":"1","reportGoal":"生成运营报告",'
                    '"reportType":"comprehensive","period":'
                    '{"start":"2025-01-01","end":"2025-12-31"}}'
                ),
            )
        ],
    )

    assert await toolkit.report_workflow_start(run_context) == {"status": "running"}
    workflow_input, captured_context = controller.start.await_args.args
    assert workflow_input.prompt is None
    assert workflow_input.report_goal == "生成运营报告"
    assert workflow_input.report_type == "comprehensive"
    assert workflow_input.period.model_dump(mode="json") == {
        "start": "2025-01-01",
        "end": "2025-12-31",
    }
    assert captured_context is run_context
    assert parse_report_input(
        '{"version":"1","reportGoal":"生成运营报告",'
        '"reportType":"comprehensive","period":{"start":"2025-01-01",'
        '"end":"2025-12-31"}}'
    ) == {
        "version": "1",
        "reportGoal": "生成运营报告",
        "reportType": "comprehensive",
        "period": {"start": "2025-01-01", "end": "2025-12-31"},
    }


@pytest.mark.anyio
async def test_resume_workflow_retries_only_failed_delivery_step() -> None:
    requirement = ErrorRequirement()
    paused = SimpleNamespace(
        status="paused",
        run_id="run-1",
        session_id="session-1",
        content=None,
        step_requirements=[],
        error_requirements=[requirement],
    )
    completed = SimpleNamespace(status="completed", content={"path": "report.pdf"})
    workflow = SimpleNamespace(
        arun=AsyncMock(),
        aget_run_output=AsyncMock(return_value=paused),
        acontinue_run=AsyncMock(return_value=completed),
    )

    result = await resume_workflow(
        workflow,
        runtime=runtime(),
        run_id="run-1",
        session_id="session-1",
        user_id="cli",
        database="odoo",
        company_id="3",
    )

    assert requirement.decision == "retry"
    assert result == {
        "status": "completed",
        "runId": "run-1",
        "sessionId": "session-1",
        "content": {"path": "report.pdf"},
    }
    workflow.arun.assert_not_awaited()
    workflow.aget_run_output.assert_awaited_once_with(
        run_id="run-1", session_id="session-1", user_id="cli"
    )
    workflow.acontinue_run.assert_awaited_once()


@pytest.mark.anyio
async def test_resume_workflow_retries_failed_assembly_with_same_run_identity() -> None:
    requirement = ErrorRequirement("assemble-report")
    paused = SimpleNamespace(
        status="paused",
        run_id="run-1",
        session_id="session-1",
        content=None,
        step_requirements=[],
        error_requirements=[requirement],
    )
    completed = SimpleNamespace(status="completed", content={"path": "report.pdf"})
    cleanup = AsyncMock()
    workflow = SimpleNamespace(
        arun=AsyncMock(),
        aget_run_output=AsyncMock(return_value=paused),
        acontinue_run=AsyncMock(return_value=completed),
    )

    result = await resume_workflow(
        workflow,
        runtime=runtime(cleanup_terminal=cleanup),
        run_id="run-1",
        session_id="session-1",
        user_id="cli",
        database="odoo",
        company_id="3",
    )

    assert requirement.decision == "retry"
    assert result["runId"] == "run-1"
    assert result["sessionId"] == "session-1"
    workflow.arun.assert_not_awaited()
    assert workflow.acontinue_run.await_args.kwargs["run_response"] is paused
    cleanup.assert_not_awaited()


@pytest.mark.anyio
async def test_resume_workflow_rejects_non_delivery_error() -> None:
    paused = SimpleNamespace(
        status="paused",
        run_id="run-1",
        session_id="session-1",
        content=None,
        step_requirements=[],
        error_requirements=[ErrorRequirement("run-coding-analysis")],
    )
    workflow = SimpleNamespace(aget_run_output=AsyncMock(return_value=paused))

    with pytest.raises(ReportingError) as raised:
        await resume_workflow(
            workflow,
            runtime=runtime(),
            run_id="run-1",
            session_id="session-1",
            user_id="cli",
            database="odoo",
            company_id="3",
        )

    assert raised.value.code == "report_workflow_resume_unsupported"


@pytest.mark.anyio
async def test_resume_workflow_continues_interrupted_running_checkpoint() -> None:
    running = SimpleNamespace(
        status="running",
        run_id="run-1",
        session_id="session-1",
        content=None,
        step_requirements=[],
        error_requirements=[],
    )
    completed = SimpleNamespace(status="completed", content={"path": "report.pdf"})
    workflow = SimpleNamespace(
        aget_run_output=AsyncMock(return_value=running),
        acontinue_run=AsyncMock(return_value=completed),
    )

    result = await resume_workflow(
        workflow,
        runtime=runtime(),
        run_id="run-1",
        session_id="session-1",
        user_id="cli",
        database="odoo",
        company_id="3",
    )

    assert result["status"] == "completed"
    assert running.status.value == "PAUSED"
    workflow.acontinue_run.assert_awaited_once()
    assert workflow.acontinue_run.await_args.kwargs["run_response"] is running


@pytest.mark.anyio
async def test_resume_workflow_cleans_up_failed_terminal_sandbox() -> None:
    running = SimpleNamespace(
        status="running",
        run_id="run-1",
        session_id="session-1",
        content=None,
        step_requirements=[],
        error_requirements=[],
    )
    workflow = SimpleNamespace(
        aget_run_output=AsyncMock(return_value=running),
        acontinue_run=AsyncMock(return_value=SimpleNamespace(status="failed", content=None)),
    )
    cleanup = AsyncMock()

    result = await resume_workflow(
        workflow,
        runtime=runtime(cleanup_terminal=cleanup),
        run_id="run-1",
        session_id="session-1",
        user_id="cli",
        database="odoo",
        company_id="3",
    )

    assert result["status"] == "failed"
    cleanup.assert_awaited_once_with(
        {
            "external_run_id": "run-1",
            "thread_id": "session-1",
            "user_id": "cli",
        },
        "session-1",
        "run-1",
    )


@pytest.mark.anyio
async def test_resume_workflow_rejects_concurrent_resume_of_same_run() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class StateRepository:
        def __init__(self) -> None:
            self.locked = False

        @asynccontextmanager
        async def workflow_execution_lock(self, _run_id: str):
            if self.locked:
                raise ReportingError("report_workflow_run_conflict", "run 正在执行。")
            self.locked = True
            try:
                yield
            finally:
                self.locked = False

    async def get_run_output(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            status="running",
            run_id="run-1",
            session_id="session-1",
            content=None,
            step_requirements=[],
            error_requirements=[],
        )

    async def continue_run(**_kwargs: object) -> SimpleNamespace:
        entered.set()
        await release.wait()
        return SimpleNamespace(status="completed", content={"path": "report.pdf"})

    workflow = SimpleNamespace(
        aget_run_output=get_run_output,
        acontinue_run=AsyncMock(side_effect=continue_run),
    )
    runtime = SimpleNamespace(state_repository=StateRepository())
    arguments = {
        "workflow": workflow,
        "runtime": runtime,
        "run_id": "run-1",
        "session_id": "session-1",
        "user_id": "cli",
        "database": "odoo",
        "company_id": "3",
    }
    first = asyncio.create_task(resume_workflow(**arguments))
    await entered.wait()
    try:
        with pytest.raises(ReportingError) as conflict:
            await resume_workflow(**arguments)
    finally:
        release.set()
        await first

    assert conflict.value.code == "report_workflow_run_conflict"
    assert workflow.acontinue_run.await_count == 1


@pytest.mark.anyio
async def test_drive_workflow_holds_execution_lock_during_initial_run() -> None:
    events: list[str] = []

    class StateRepository:
        @asynccontextmanager
        async def workflow_execution_lock(self, run_id: str):
            events.append(f"lock:{run_id}")
            try:
                yield
            finally:
                events.append(f"unlock:{run_id}")

    async def run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        events.append("run")
        return SimpleNamespace(status="completed", content={"path": "report.pdf"})

    result = await drive_workflow(
        SimpleNamespace(arun=run),
        SimpleNamespace(state_repository=StateRepository()),
        {"version": "1", "prompt": "生成运营报告"},
        run_id="run-1",
        session_id="session-1",
        user_id="cli",
        database="odoo",
        company_id="3",
    )

    assert result["status"] == "completed"
    assert events == ["lock:run-1", "run", "unlock:run-1"]


@pytest.mark.anyio
@pytest.mark.parametrize("terminal_status", ["cancelled", "failed"])
async def test_drive_workflow_cleans_up_terminal_sandbox(terminal_status: str) -> None:
    cleanup = AsyncMock()
    current_runtime = runtime(cleanup_terminal=cleanup)

    async def run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(status=terminal_status, content=None)

    result = await drive_workflow(
        SimpleNamespace(arun=run),
        current_runtime,
        {"version": "1", "prompt": "生成运营报告"},
        run_id="run-1",
        session_id="session-1",
        user_id="cli",
        database="odoo",
        company_id="3",
    )

    assert result["status"] == terminal_status
    assert current_runtime.state_repository.status_updates == [
        ("run-1", terminal_status, True),
        ("run-1", terminal_status, False),
    ]
    cleanup.assert_awaited_once_with(
        {
            "external_run_id": "run-1",
            "thread_id": "session-1",
            "user_id": "cli",
        },
        "session-1",
        "run-1",
    )


@pytest.mark.anyio
async def test_drive_workflow_marks_completed_without_cleanup_pending() -> None:
    cleanup = AsyncMock()
    current_runtime = runtime(cleanup_terminal=cleanup)

    async def run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(status=RunStatus.completed, content=None)

    result = await drive_workflow(
        SimpleNamespace(arun=run),
        current_runtime,
        {"version": "1", "prompt": "生成运营报告"},
        run_id="run-1",
        session_id="session-1",
        user_id="cli",
        database="odoo",
        company_id="3",
    )

    assert result["status"] == "completed"
    assert current_runtime.state_repository.status_updates == [
        ("run-1", "completed", False)
    ]
    cleanup.assert_not_awaited()


@pytest.mark.anyio
async def test_drive_workflow_cleans_up_sandbox_when_initial_run_raises() -> None:
    cleanup = AsyncMock()
    current_runtime = runtime(cleanup_terminal=cleanup)

    async def run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        raise RuntimeError("workflow failed")

    with pytest.raises(RuntimeError, match="workflow failed"):
        await drive_workflow(
            SimpleNamespace(arun=run),
            current_runtime,
            {"version": "1", "prompt": "生成运营报告"},
            run_id="run-1",
            session_id="session-1",
            user_id="cli",
            database="odoo",
            company_id="3",
        )

    assert current_runtime.state_repository.status_updates == [
        ("run-1", "failed", True),
        ("run-1", "failed", False),
    ]
    cleanup.assert_awaited_once_with(
        {
            "external_run_id": "run-1",
            "thread_id": "session-1",
            "user_id": "cli",
        },
        "session-1",
        "run-1",
    )


@pytest.mark.anyio
async def test_drive_workflow_finalizes_when_initial_run_raises_reporting_error() -> None:
    cleanup = AsyncMock()
    current_runtime = runtime(cleanup_terminal=cleanup)
    workflow = SimpleNamespace(
        arun=AsyncMock(
            side_effect=ReportingError("report_workflow_step_failed", "Agno step failed")
        )
    )

    with pytest.raises(ReportingError) as raised:
        await drive_workflow(
            workflow,
            current_runtime,
            {"version": "1", "prompt": "生成运营报告"},
            run_id="run-1",
            session_id="session-1",
            user_id="cli",
            database="odoo",
            company_id="3",
        )

    assert raised.value.code == "report_workflow_step_failed"
    assert current_runtime.state_repository.status_updates == [
        ("run-1", "failed", True),
        ("run-1", "failed", False),
    ]
    cleanup.assert_awaited_once()


@pytest.mark.anyio
async def test_drive_workflow_maps_agno_error_to_failed_and_keeps_pending_on_cleanup_error() -> None:
    async def cleanup(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("cleanup failed")

    current_runtime = runtime(cleanup_terminal=cleanup)

    async def run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(status=RunStatus.error, content=None)

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await drive_workflow(
            SimpleNamespace(arun=run),
            current_runtime,
            {"version": "1", "prompt": "生成运营报告"},
            run_id="run-1",
            session_id="session-1",
            user_id="cli",
            database="odoo",
            company_id="3",
        )

    assert current_runtime.state_repository.status_updates == [("run-1", "failed", True)]


@pytest.mark.anyio
async def test_drive_workflow_finalizes_when_review_continue_raises() -> None:
    cleanup = AsyncMock()
    current_runtime = runtime(cleanup_terminal=cleanup)
    requirement = ErrorRequirement("validate-report")
    workflow = SimpleNamespace(
        arun=AsyncMock(
            return_value=SimpleNamespace(
                status=RunStatus.paused,
                error_requirements=[requirement],
            )
        ),
        acontinue_run=AsyncMock(
            side_effect=ReportingError("report_workflow_step_failed", "continue failed")
        ),
    )

    with pytest.raises(ReportingError) as raised:
        await drive_workflow(
            workflow,
            current_runtime,
            {"version": "1", "prompt": "生成运营报告"},
            run_id="run-1",
            session_id="session-1",
            user_id="cli",
            database="odoo",
            company_id="3",
        )

    assert raised.value.code == "report_workflow_step_failed"
    assert current_runtime.state_repository.status_updates == [
        ("run-1", "failed", True),
        ("run-1", "failed", False),
    ]
    cleanup.assert_awaited_once()


@pytest.mark.anyio
async def test_resume_workflow_finalizes_when_continue_raises() -> None:
    cleanup = AsyncMock()
    current_runtime = runtime(cleanup_terminal=cleanup)
    workflow = SimpleNamespace(
        aget_run_output=AsyncMock(return_value=SimpleNamespace(status=RunStatus.running)),
        acontinue_run=AsyncMock(side_effect=RuntimeError("continue failed")),
    )

    with pytest.raises(RuntimeError, match="continue failed"):
        await resume_workflow(
            workflow,
            current_runtime,
            run_id="run-1",
            session_id="session-1",
            user_id="cli",
            database="odoo",
            company_id="3",
        )

    assert current_runtime.state_repository.status_updates == [
        ("run-1", "failed", True),
        ("run-1", "failed", False),
    ]
    cleanup.assert_awaited_once()


@pytest.mark.anyio
async def test_resume_workflow_finishes_parent_pending_before_rejecting_terminal_agno_output() -> (
    None
):
    class StateRepository(UncontendedStateRepository):
        async def get_run(self, report_run_id: str) -> dict[str, object]:
            assert report_run_id == "run-1"
            return {
                "report_run_id": "run-1",
                "external_run_id": "run-1",
                "entrypoint": "cli",
                "workflow_id": "enterprise-reporting-workflow-v1",
                "agno_session_id": "session-1",
                "agno_run_id": "run-1",
                "caller_session_id": "session-1",
                "caller_run_id": "run-1",
                "thread_id": "session-1",
                "owner_user_id": "cli",
                "database": "odoo",
                "company_id": "3",
                "status": "failed",
                "finalization_pending": True,
            }

    cleanup = AsyncMock()
    repository = StateRepository()
    current_runtime = SimpleNamespace(
        state_repository=repository,
        cleanup_terminal=cleanup,
    )
    workflow = SimpleNamespace(aget_run_output=AsyncMock(return_value=None))

    result = await resume_workflow(
        workflow,
        current_runtime,
        run_id="run-1",
        session_id="session-1",
        user_id="cli",
        database="odoo",
        company_id="3",
    )

    assert result["status"] == "failed"
    assert repository.status_updates[-1] == ("run-1", "failed", False)
    cleanup.assert_awaited_once()
    workflow.aget_run_output.assert_not_awaited()


@pytest.mark.anyio
async def test_resume_workflow_rejects_cancelled_run() -> None:
    workflow = SimpleNamespace(
        aget_run_output=AsyncMock(return_value=SimpleNamespace(status="cancelled"))
    )

    with pytest.raises(ReportingError) as raised:
        await resume_workflow(
            workflow,
            runtime=runtime(),
            run_id="run-1",
            session_id="session-1",
            user_id="cli",
            database="odoo",
            company_id="3",
        )

    assert raised.value.code == "report_workflow_resume_invalid"


def test_only_tail_steps_pause_for_error_recovery() -> None:
    async def executor(*_args: object, **_kwargs: object) -> None:
        return None

    workflow = create_reporting_workflow(
        db=object(),
        normalize_report_request=executor,
        confirm_source=executor,
        prepare_data_profile=executor,
        propose_measure_semantics=executor,
        commit_measure_semantics=executor,
        generate_outline=executor,
        generate_analysis_plan=executor,
        generate_query_candidates=executor,
        materialize_datasets=executor,
        prepare_analysis_context=executor,
        generate_detailed_analysis_plan=executor,
        run_reporting_analysis=executor,
        assemble_report=executor,
        validate_report=executor,
        finalize_publication=executor,
    )

    assert isinstance(workflow.steps, list)
    steps = {step.step_id: step for step in workflow.steps if isinstance(step, Step)}
    assert steps["normalize-report-request"].human_review is not None
    assert callable(steps["normalize-report-request"].human_review.requires_output_review)
    assert steps["generate-outline"].human_review is not None
    assert steps["generate-outline"].human_review.requires_output_review is False
    assert steps["validate-report"].human_review.on_error is OnError.pause
    assert steps["assemble-report"].human_review.on_error is OnError.pause
    assert steps["run-coding-analysis"].human_review.on_error is OnError.fail
    assert workflow.input_schema is None
    assert workflow.stream_executor_events is False
    assert workflow.telemetry is False


def test_reporting_workflow_retries_transient_safe_steps_only() -> None:
    async def executor(*_args: object, **_kwargs: object) -> None:
        return None

    workflow = create_reporting_workflow(
        db=object(),
        normalize_report_request=executor,
        confirm_source=executor,
        prepare_data_profile=executor,
        propose_measure_semantics=executor,
        commit_measure_semantics=executor,
        generate_outline=executor,
        generate_analysis_plan=executor,
        generate_query_candidates=executor,
        materialize_datasets=executor,
        prepare_analysis_context=executor,
        generate_detailed_analysis_plan=executor,
        run_reporting_analysis=executor,
        assemble_report=executor,
        validate_report=executor,
        finalize_publication=executor,
    )

    steps = {step.step_id: step for step in workflow.steps if isinstance(step, Step)}
    retryable = {
        "confirm-source",
        "prepare-data-profile",
        "propose-measure-semantics",
        "generate-analysis-plan",
        "generate-query-candidates",
        "prepare-analysis-context",
        "generate-detailed-analysis-plan",
        "generate-outline",
    }
    for step_id in retryable:
        assert steps[step_id].max_retries == 1
    for step_id in {
        "normalize-report-request",
        "commit-measure-semantics",
        "materialize-datasets",
        "run-coding-analysis",
        "assemble-report",
        "validate-report",
        "finalize-publication",
    }:
        assert steps[step_id].max_retries == 0


@pytest.mark.anyio
async def test_outline直接流向coding节点而不暂停() -> None:
    calls: list[str] = []

    def executor(name: str):
        async def execute(*_args: object, **_kwargs: object) -> StepOutput:
            calls.append(name)
            return StepOutput(content={"step": name})

        return execute

    workflow = create_reporting_workflow(
        db=InMemoryDb(),
        normalize_report_request=executor("normalize-report-request"),
        confirm_source=executor("confirm-source"),
        prepare_data_profile=executor("prepare-data-profile"),
        propose_measure_semantics=executor("propose-measure-semantics"),
        commit_measure_semantics=executor("commit-measure-semantics"),
        generate_outline=executor("generate-outline"),
        generate_analysis_plan=executor("generate-analysis-plan"),
        generate_query_candidates=executor("generate-query-candidates"),
        materialize_datasets=executor("materialize-datasets"),
        prepare_analysis_context=executor("prepare-analysis-context"),
        generate_detailed_analysis_plan=executor("generate-detailed-analysis-plan"),
        run_reporting_analysis=executor("run-coding-analysis"),
        assemble_report=executor("assemble-report"),
        validate_report=executor("validate-report"),
        finalize_publication=executor("finalize-publication"),
    )

    output = await workflow.arun(
        "生成 2025 年运营报告",
        run_id="run-outline-no-review",
        session_id="session-outline-no-review",
        user_id="user-outline-no-review",
    )

    assert output.status is RunStatus.completed
    outline_index = calls.index("generate-outline")
    assert calls[outline_index + 1] == "run-coding-analysis"
    analysis_index = calls.index("run-coding-analysis")
    assert calls[analysis_index : analysis_index + 3] == [
        "run-coding-analysis",
        "assemble-report",
        "validate-report",
    ]


@pytest.mark.anyio
async def test_assemble_error_pause_retries_only_assembly_step() -> None:
    calls: list[str] = []
    assembly_attempts = 0

    def executor(name: str):
        async def execute(*_args: object, **_kwargs: object) -> StepOutput:
            nonlocal assembly_attempts
            calls.append(name)
            if name == "assemble-report":
                assembly_attempts += 1
                if assembly_attempts == 1:
                    raise RuntimeError("assembly failed")
            return StepOutput(content={"step": name})

        return execute

    workflow = create_reporting_workflow(
        db=InMemoryDb(),
        normalize_report_request=executor("normalize-report-request"),
        confirm_source=executor("confirm-source"),
        prepare_data_profile=executor("prepare-data-profile"),
        propose_measure_semantics=executor("propose-measure-semantics"),
        commit_measure_semantics=executor("commit-measure-semantics"),
        generate_outline=executor("generate-outline"),
        generate_analysis_plan=executor("generate-analysis-plan"),
        generate_query_candidates=executor("generate-query-candidates"),
        materialize_datasets=executor("materialize-datasets"),
        prepare_analysis_context=executor("prepare-analysis-context"),
        generate_detailed_analysis_plan=executor("generate-detailed-analysis-plan"),
        run_reporting_analysis=executor("run-coding-analysis"),
        assemble_report=executor("assemble-report"),
        validate_report=executor("validate-report"),
        finalize_publication=executor("finalize-publication"),
    )

    paused = await workflow.arun(
        "生成 2025 年运营报告",
        run_id="run-assembly-recovery",
        session_id="session-assembly-recovery",
        user_id="user-assembly-recovery",
    )

    assert paused.status is RunStatus.paused
    assert paused.error_requirements is not None
    assert paused.error_requirements[0].step_id == "assemble-report"
    assert calls.count("run-coding-analysis") == 1
    assert calls.count("validate-report") == 0

    paused.error_requirements[0].retry()
    completed = await workflow.acontinue_run(run_response=paused, stream=False)

    assert completed.status is RunStatus.completed
    assert calls.count("run-coding-analysis") == 1
    assert calls.count("assemble-report") == 2
    assert calls.count("validate-report") == 1


def test_reporting_cli_applies_requested_debug_setting() -> None:
    enabled = AgentSettings.from_environment({"AGENT_DEBUG": "true"}, load_env_file=False)
    disabled = AgentSettings.from_environment({"AGENT_DEBUG": "false"}, load_env_file=False)

    assert _cli_settings(enabled, debug=False).debug is False
    assert _cli_settings(disabled, debug=True).debug is True


@pytest.mark.parametrize(
    ("argument", "debug_count"),
    [("--no-debug", 0), ("--debug", 1)],
)
def test_reporting_cli_configures_loguru_for_debug_argument(
    argument: str, debug_count: int
) -> None:
    script = f"""
from loguru import logger
from smart_reporting.reporting import cli

async def fake_run_cli(**_kwargs):
    logger.debug("REPORTING_CLI_DEBUG_MARKER")
    logger.info("REPORTING_CLI_INFO_MARKER")
    return {{"status": "completed"}}

cli.run_cli = fake_run_cli
cli.main([{argument!r}])
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr.count("REPORTING_CLI_DEBUG_MARKER") == debug_count
    assert completed.stderr.count("REPORTING_CLI_INFO_MARKER") == 1


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["--tenant-database", "odoo", "--tenant-company-id", "3"], True),
        (
            [
                "--tenant-database",
                "odoo",
                "--tenant-company-id",
                "3",
                "--no-debug",
            ],
            False,
        ),
    ],
)
def test_reporting_cli_debug_argument_defaults_enabled(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    expected: bool,
) -> None:
    calls: list[bool] = []

    async def fake_run_cli(**kwargs: object) -> dict[str, str]:
        calls.append(bool(kwargs["debug"]))
        return {"status": "completed"}

    monkeypatch.setattr(reporting_cli, "run_cli", fake_run_cli)

    reporting_cli.main(arguments)

    assert calls == [expected]


def test_reporting_cli_allows_omitted_tenant_and_lets_run_cli_default_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_run_cli(**kwargs: object) -> dict[str, str]:
        captured.update(kwargs)
        return {"status": "completed"}

    monkeypatch.setattr(reporting_cli, "run_cli", fake_run_cli)

    reporting_cli.main([])

    assert captured["database"] is None
    assert captured["company_id"] is None


@pytest.mark.anyio
async def test_run_cli_rejects_partial_tenant_before_runtime_setup() -> None:
    with pytest.raises(ReportingError) as raised:
        await reporting_cli.run_cli(database="odoo", company_id=None)

    assert raised.value.code == "report_workflow_context_missing"


def test_reporting_cli_returns_failure_exit_for_cancelled_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_cli(**_kwargs: object) -> dict[str, str]:
        return {"status": "cancelled"}

    monkeypatch.setattr(reporting_cli, "run_cli", fake_run_cli)

    with pytest.raises(SystemExit) as raised:
        reporting_cli.main(["--tenant-database", "odoo", "--tenant-company-id", "3"])

    assert raised.value.code == 1


def test_reporting_cli_returns_130_for_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    async def interrupted(**_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(reporting_cli, "run_cli", interrupted)

    with pytest.raises(SystemExit) as raised:
        reporting_cli.main(["--tenant-database", "odoo", "--tenant-company-id", "3"])

    assert raised.value.code == 130


@pytest.mark.anyio
async def test_cli_progress_sink_reports_safe_high_signal_and_throttled_progress() -> None:
    writes: list[str] = []
    clock_values = iter((0.0, 1.0, 31.0, 32.0))
    sink = _CliProgressSink(writes.append, clock=lambda: next(clock_values))

    await sink.emit_reporting_event(
        None,
        "run-1",
        SimpleNamespace(
            event="ToolCallCompleted",
            tool=SimpleNamespace(
                tool_name="read_file",
                result={"ok": True, "content": "不得输出的业务正文"},
                tool_call_error=False,
            ),
        ),
    )
    await sink.emit_reporting_event(
        None,
        "run-1",
        SimpleNamespace(
            event="ToolCallCompleted",
            tool=SimpleNamespace(
                tool_name="query_profile",
                result={"ok": True, "value": {"sensitive": "不得输出"}},
                tool_call_error=False,
            ),
        ),
    )
    await sink.emit_reporting_event(
        None,
        "run-1",
        SimpleNamespace(
            event="ToolCallCompleted",
            tool=SimpleNamespace(
                tool_name="complete_analysis_item",
                result={
                    "ok": False,
                    "code": "report_analysis_evidence_identity_mismatch",
                    "analysisId": "analysis_003",
                    "message": "不得输出的错误正文",
                },
                tool_call_error=False,
            ),
        ),
    )

    assert writes == [
        "Reporting 进度: tool=query_profile status=accepted events=2",
        "Reporting 进度: tool=complete_analysis_item status=rejected events=3 "
        "analysisId=analysis_003 code=report_analysis_evidence_identity_mismatch",
    ]
    assert "不得输出" not in "".join(writes)
