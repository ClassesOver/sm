from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.models.message import Message
from agno.run import RunContext
from agno.workflow import OnError

from smart_reporting.reporting import cli as reporting_cli
from smart_reporting.reporting.cli import (
    _cli_settings,
    _CliProgressSink,
    parse_report_input,
    resume_workflow,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.controller import ReportWorkflowToolkit
from smart_reporting.reporting.workflow.orchestration import create_reporting_workflow
from smart_reporting.settings import AgentSettings


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


def test_report_input_parsing_is_shared_with_agentos() -> None:
    assert parse_report_input("生成 2025 年运营报告") == {
        "version": "1",
        "prompt": "生成 2025 年运营报告",
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
        runtime=SimpleNamespace(),
        run_id="run-1",
        session_id="session-1",
        user_id="cli",
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
            runtime=SimpleNamespace(),
            run_id="run-1",
            session_id="session-1",
            user_id="cli",
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
        runtime=SimpleNamespace(),
        run_id="run-1",
        session_id="session-1",
        user_id="cli",
    )

    assert result["status"] == "completed"
    assert running.status.value == "PAUSED"
    workflow.acontinue_run.assert_awaited_once()
    assert workflow.acontinue_run.await_args.kwargs["run_response"] is running


@pytest.mark.anyio
async def test_resume_workflow_rejects_cancelled_run() -> None:
    workflow = SimpleNamespace(
        aget_run_output=AsyncMock(return_value=SimpleNamespace(status="cancelled"))
    )

    with pytest.raises(ReportingError) as raised:
        await resume_workflow(
            workflow,
            runtime=SimpleNamespace(),
            run_id="run-1",
            session_id="session-1",
            user_id="cli",
        )

    assert raised.value.code == "report_workflow_resume_invalid"


def test_only_delivery_validation_step_pauses_for_error_recovery() -> None:
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
        run_coding_analysis=executor,
        validate_report=executor,
        finalize_publication=executor,
    )

    steps = {step.step_id: step for step in workflow.steps}
    assert steps["validate-report"].on_error is OnError.pause
    assert steps["run-coding-analysis"].on_error is OnError.fail


def test_reporting_cli_applies_requested_debug_setting() -> None:
    enabled = AgentSettings.from_environment({"AGENT_DEBUG": "true"}, load_env_file=False)
    disabled = AgentSettings.from_environment({"AGENT_DEBUG": "false"}, load_env_file=False)

    assert _cli_settings(enabled, debug=False).debug is False
    assert _cli_settings(disabled, debug=True).debug is True


@pytest.mark.parametrize(("arguments", "expected"), [([], True), (["--no-debug"], False)])
def test_reporting_cli_debug_argument_defaults_enabled(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    expected: bool,
) -> None:
    calls: list[bool] = []

    async def fake_run_cli(**kwargs: object) -> None:
        calls.append(bool(kwargs["debug"]))

    monkeypatch.setattr(reporting_cli, "run_cli", fake_run_cli)

    reporting_cli.main(arguments)

    assert calls == [expected]


@pytest.mark.anyio
async def test_cli_progress_sink_reports_safe_high_signal_and_throttled_progress() -> None:
    writes: list[str] = []
    clock_values = iter((0.0, 1.0, 31.0, 32.0))
    sink = _CliProgressSink(writes.append, clock=lambda: next(clock_values))

    await sink.emit_worker(
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
    await sink.emit_worker(
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
    await sink.emit_worker(
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
        "Coding 进度: tool=query_profile status=accepted events=2",
        "Coding 进度: tool=complete_analysis_item status=rejected events=3 "
        "analysisId=analysis_003 code=report_analysis_evidence_identity_mismatch",
    ]
    assert "不得输出" not in "".join(writes)
