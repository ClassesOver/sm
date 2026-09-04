from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from agno.run import RunContext
from agno.workflow.types import StepOutput

from smart_reporting.reporting.cli import drive_workflow, parse_report_input
from smart_reporting.reporting.tools.context import ReportingOutputPolicy
from smart_reporting.reporting.tools.mock_workspace import MockReportingToolRuntime
from smart_reporting.reporting.workflow.runtime.reporting_draft_workflow import (
    ReportingDraftWorkflow,
)


class _Runtime:
    def __init__(self) -> None:
        self.state_repository = self
        self.cleaned = False

    @asynccontextmanager
    async def workflow_execution_lock(self, _run_id: str):
        yield

    async def cleanup_terminal(self, *_args: Any) -> None:
        self.cleaned = True


class _CliDraftAdapter:
    def __init__(self) -> None:
        self.received_input: dict[str, Any] | None = None
        self.received_scope: dict[str, Any] | None = None
        self.contexts: list[RunContext] = []
        self.production_draft_workflow_called = False

    async def arun(self, report_input: dict[str, Any], **kwargs: Any) -> Any:
        self.received_input = report_input
        self.received_scope = kwargs["dependencies"]["AgentOS 报表工作流"]
        context = RunContext(
            run_id=kwargs["run_id"],
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            session_state=kwargs["session_state"],
            dependencies=kwargs["dependencies"],
        )

        async def stage(_payload: dict[str, Any], run_context: RunContext) -> StepOutput:
            self.contexts.append(run_context)
            return StepOutput(content={"ok": True})

        workflow = ReportingDraftWorkflow(
            report_goal=report_input["prompt"],
            section_goal={"sectionCode": "section-1"},
            analysis_ids=("analysis-1",),
            run_analysis=stage,
            submit_visualization=stage,
            draft_section=stage,
        )
        self.production_draft_workflow_called = True
        await workflow.execute_section(context)
        return SimpleNamespace(status="completed", content={"sectionCode": "section-1"})

    async def acontinue_run(self, **_kwargs: Any) -> Any:
        raise AssertionError("正常 CLI mock 闭环不应调用 continuation")


def _mock_tool_runtime() -> MockReportingToolRuntime:
    return MockReportingToolRuntime(
        input_snapshot={"version": "1"},
        inputs={"inputs/report.json": b"{}"},
        output_policy=ReportingOutputPolicy(("reports",)),
    )


@pytest.mark.anyio
async def test_cli_input_reaches_production_draft_workflow() -> None:
    raw = "生成 2025 年运营报告，重点分析收入同比和区域贡献"
    parsed = parse_report_input(raw)
    adapter = _CliDraftAdapter()

    result = await drive_workflow(
        adapter,
        _Runtime(),
        parsed,
        run_id="cli-run-1",
        session_id="cli-session-1",
        user_id="cli-user-1",
        database="odoo",
        company_id="company-1",
    )

    assert adapter.received_input == parsed
    assert adapter.received_scope == {
        "externalRunId": "cli-run-1",
        "threadId": "cli-session-1",
        "userId": "cli-user-1",
        "database": "odoo",
        "companyId": "company-1",
    }
    assert result["status"] == "completed"
    assert adapter.production_draft_workflow_called is True
    assert len(adapter.contexts) == 3
    assert all(context.run_id == "cli-run-1" for context in adapter.contexts)
    assert all(context.session_id == "cli-session-1" for context in adapter.contexts)


@pytest.mark.anyio
async def test_cli_mock_repeated_ten_times_is_deterministic() -> None:
    observations: list[tuple[dict[str, Any], tuple[tuple[str, Any], ...]]] = []
    for index in range(10):
        adapter = _CliDraftAdapter()
        runtime = _Runtime()
        parsed = parse_report_input("生成 2025 年运营报告")
        result = await drive_workflow(
            adapter,
            runtime,
            parsed,
            run_id=f"cli-run-{index}",
            session_id=f"cli-session-{index}",
            user_id="cli-user-1",
        )
        observations.append(
            (
                result,
                tuple(("run", "session") for _context in adapter.contexts),
            )
        )
        assert runtime.cleaned is False
    assert all(item[0]["status"] == "completed" for item in observations)
    assert all(item[1] == observations[0][1] for item in observations)


def test_mock_runtime_isolated_for_each_cli_case() -> None:
    first = _mock_tool_runtime()
    second = _mock_tool_runtime()
    assert first is not second
    assert first.workspace is not second.workspace
    assert first.calls == second.calls == []


@pytest.mark.anyio
async def test_mock_workspace_background_session_and_sha_recovery_boundaries() -> None:
    runtime = _mock_tool_runtime()
    started = await runtime.workspace.execute_script(
        "python3 reports/script.py", timeout=30, background=True
    )
    session_id = str(started["session_id"])
    assert started["status"] == "running"
    await runtime.workspace.send_process_input(session_id, "", submit=True, timeout=30)
    with pytest.raises(Exception, match="已提交"):
        await runtime.workspace.send_process_input(session_id, "", submit=True, timeout=30)

    identity = await runtime.workspace.write_text("reports/script.py", "print('v1')")
    runtime.workspace._outputs["reports/script.py"] = b"print('v2')"
    with pytest.raises(Exception, match="哈希已变化"):
        await runtime.workspace.write_text(
            "reports/script.py", "print('repair')", overwrite=True, expected_sha256=identity.sha256
        )
