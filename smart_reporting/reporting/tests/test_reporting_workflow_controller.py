import asyncio
from types import SimpleNamespace

import pytest
from agno.run import RunContext
from agno.run.base import RunStatus

from smart_reporting.reporting.contract import ReportingWorkflowInput
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.controller import (
    ReportWorkflowController,
    reporting_workflow_ids,
)


def _context() -> RunContext:
    return RunContext(
        run_id="external-run",
        session_id="thread",
        user_id="user",
        session_state={},
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("workflow_status", "expected_status"),
    [(RunStatus.cancelled, "cancelled"), (RunStatus.error, "failed")],
)
async def test_controller_reclaims_sandbox_after_terminal_start(
    workflow_status: RunStatus, expected_status: str
) -> None:
    cleanup_calls: list[tuple[dict[str, str], str, str]] = []

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            return SimpleNamespace(status=workflow_status)

    async def cleanup(scope: dict[str, str], session_id: str, run_id: str) -> None:
        cleanup_calls.append((scope, session_id, run_id))

    controller = ReportWorkflowController(lambda: Workflow(), terminal_cleanup=cleanup)
    result = await controller.start(ReportingWorkflowInput(prompt="生成报表"), _context())
    session_id, run_id = reporting_workflow_ids(
        user_id="user", thread_id="thread", external_run_id="external-run"
    )

    assert result["status"] == expected_status
    assert cleanup_calls == [
        (
            {
                "external_run_id": "external-run",
                "thread_id": "thread",
                "user_id": "user",
            },
            session_id,
            run_id,
        )
    ]


@pytest.mark.anyio
async def test_controller_reclaims_sandbox_when_workflow_raises() -> None:
    cleanup_calls: list[tuple[dict[str, str], str, str]] = []

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            raise RuntimeError("workflow failed")

    async def cleanup(scope: dict[str, str], session_id: str, run_id: str) -> None:
        cleanup_calls.append((scope, session_id, run_id))

    controller = ReportWorkflowController(lambda: Workflow(), terminal_cleanup=cleanup)

    with pytest.raises(RuntimeError, match="workflow failed"):
        await controller.start(ReportingWorkflowInput(prompt="生成报表"), _context())

    assert len(cleanup_calls) == 1
    assert cleanup_calls[0][0]["thread_id"] == "thread"


@pytest.mark.anyio
async def test_controller_rejects_concurrent_runs_for_same_thread() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            started.set()
            await release.wait()
            return SimpleNamespace(status=RunStatus.cancelled)

    controller = ReportWorkflowController(lambda: Workflow())
    first = asyncio.create_task(
        controller.start(ReportingWorkflowInput(prompt="生成第一份报表"), _context())
    )
    await started.wait()
    second_context = RunContext(
        run_id="external-run-2",
        session_id="thread",
        user_id="user",
        session_state={},
    )

    try:
        with pytest.raises(ReportingError) as raised:
            await controller.start(ReportingWorkflowInput(prompt="生成第二份报表"), second_context)
    finally:
        release.set()
        await first

    assert raised.value.code == "report_workflow_active"
    third_context = RunContext(
        run_id="external-run-3",
        session_id="thread",
        user_id="user",
        session_state={},
    )
    await controller.start(ReportingWorkflowInput(prompt="生成第三份报表"), third_context)
    assert run_calls == 2


@pytest.mark.anyio
async def test_controller_keeps_thread_owned_when_terminal_cleanup_fails() -> None:
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            return SimpleNamespace(status=RunStatus.cancelled)

    async def cleanup(*_args, **_kwargs) -> None:
        raise RuntimeError("cleanup failed")

    controller = ReportWorkflowController(lambda: Workflow(), terminal_cleanup=cleanup)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        await controller.start(ReportingWorkflowInput(prompt="生成第一份报表"), _context())

    second_context = RunContext(
        run_id="external-run-2",
        session_id="thread",
        user_id="user",
        session_state={},
    )
    with pytest.raises(ReportingError) as raised:
        await controller.start(ReportingWorkflowInput(prompt="生成第二份报表"), second_context)

    assert raised.value.code == "report_workflow_active"
    assert run_calls == 1
