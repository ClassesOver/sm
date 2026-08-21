from types import SimpleNamespace

import pytest
from agno.run import RunContext
from agno.run.base import RunStatus

from smart_reporting.reporting.contract import ReportingWorkflowInput
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
