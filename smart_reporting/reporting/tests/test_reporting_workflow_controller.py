import asyncio
from types import SimpleNamespace

import pytest
from agno.run import RunContext
from agno.run.base import RunStatus

from smart_reporting.reporting.contract import ReportingWorkflowInput
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.controller import (
    REPORT_WORKFLOW_CONTROL_STATE_KEY,
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


class _ThreadOwnership:
    def __init__(self) -> None:
        self.owners: dict[str, tuple[str, str]] = {}
        self.lock = asyncio.Lock()

    async def claim_workflow_thread(
        self, *, thread_id: str, external_run_id: str, owner_user_id: str
    ) -> bool:
        async with self.lock:
            if thread_id in self.owners:
                return False
            self.owners[thread_id] = (external_run_id, owner_user_id)
            return True

    async def ensure_workflow_thread_owner(
        self, *, thread_id: str, external_run_id: str, owner_user_id: str
    ) -> bool:
        async with self.lock:
            owner = self.owners.setdefault(thread_id, (external_run_id, owner_user_id))
            return owner == (external_run_id, owner_user_id)

    async def release_workflow_thread(
        self, *, thread_id: str, external_run_id: str, owner_user_id: str
    ) -> bool:
        async with self.lock:
            if self.owners.get(thread_id) != (external_run_id, owner_user_id):
                return False
            self.owners.pop(thread_id)
            return True


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

    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=_ThreadOwnership(),
        terminal_cleanup=cleanup,
    )
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

    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=_ThreadOwnership(),
        terminal_cleanup=cleanup,
    )

    with pytest.raises(RuntimeError, match="workflow failed"):
        await controller.start(ReportingWorkflowInput(prompt="生成报表"), _context())

    assert len(cleanup_calls) == 1
    assert cleanup_calls[0][0]["thread_id"] == "thread"


@pytest.mark.anyio
async def test_controller_workflow_and_cleanup_failure_remains_recoverable() -> None:
    run_calls = 0
    cleanup_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            if run_calls == 1:
                raise RuntimeError("workflow failed")
            return SimpleNamespace(status=RunStatus.completed)

    async def cleanup(*_args, **_kwargs) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise RuntimeError("cleanup failed")

    context = _context()
    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
        terminal_cleanup=cleanup,
    )

    with pytest.raises(RuntimeError, match="workflow failed") as raised:
        await controller.start(ReportingWorkflowInput(prompt="生成报表"), context)

    assert isinstance(raised.value.__cause__, RuntimeError)
    assert str(raised.value.__cause__) == "cleanup failed"
    assert context.session_state[REPORT_WORKFLOW_CONTROL_STATE_KEY]["finalizationPending"] is True
    assert ownership.owners == {"thread": ("external-run", "user")}

    recovered = await controller.start(ReportingWorkflowInput(prompt="重试清理"), context)

    assert recovered["status"] == "failed"
    assert cleanup_calls == 2
    assert ownership.owners == {}

    next_context = RunContext(
        run_id="external-run-2",
        session_id="thread",
        user_id="user",
        session_state={},
    )
    completed = await controller.start(
        ReportingWorkflowInput(prompt="生成下一份报表"), next_context
    )
    assert completed["status"] == "completed"
    assert run_calls == 2


@pytest.mark.anyio
async def test_controller_terminal_duplicate_approval_does_not_reclaim_thread() -> None:
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            return SimpleNamespace(status=RunStatus.completed)

        async def aget_run(self, *_args, **_kwargs):
            return SimpleNamespace(status=RunStatus.completed, user_id="user")

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
    )
    context = _context()
    await controller.start(ReportingWorkflowInput(prompt="生成第一份报表"), context)

    with pytest.raises(ReportingError) as raised:
        await controller.approve(context)

    assert raised.value.code == "report_workflow_not_paused"
    assert ownership.owners == {}
    second_context = RunContext(
        run_id="external-run-2",
        session_id="thread",
        user_id="user",
        session_state={},
    )
    await controller.start(ReportingWorkflowInput(prompt="生成第二份报表"), second_context)
    assert run_calls == 2


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

    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=_ThreadOwnership())
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

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
        terminal_cleanup=cleanup,
    )
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
    assert ownership.owners == {"thread": ("external-run", "user")}


@pytest.mark.anyio
async def test_controller_retries_pending_terminal_cleanup_without_rerunning_workflow() -> None:
    run_calls = 0
    cleanup_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            return SimpleNamespace(status=RunStatus.cancelled)

    async def cleanup(*_args, **_kwargs) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise RuntimeError("cleanup failed")

    context = _context()
    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
        terminal_cleanup=cleanup,
    )

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await controller.start(ReportingWorkflowInput(prompt="生成报表"), context)

    pending = context.session_state[REPORT_WORKFLOW_CONTROL_STATE_KEY]
    assert pending["finalizationPending"] is True

    result = await controller.start(ReportingWorkflowInput(prompt="重试清理"), context)

    assert result["status"] == "cancelled"
    assert run_calls == 1
    assert cleanup_calls == 2
    assert ownership.owners == {}
    assert "finalizationPending" not in context.session_state[REPORT_WORKFLOW_CONTROL_STATE_KEY]
