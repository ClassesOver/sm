import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from agno.run import RunContext
from agno.run.base import RunStatus

import smart_reporting.reporting.workflow.controller as controller_module
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
        self.execution_locks: dict[str, asyncio.Lock] = {}

    def workflow_execution_lock(self, external_run_id: str):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def locked():
            lock = self.execution_locks.setdefault(external_run_id, asyncio.Lock())
            if lock.locked():
                raise ReportingError(
                    "report_workflow_run_conflict", "Reporting run 正由其他进程执行。"
                )
            await lock.acquire()
            try:
                yield
            finally:
                lock.release()

        return locked()

    async def is_workflow_run_active(self, external_run_id: str) -> bool:
        lock = self.execution_locks.get(external_run_id)
        return bool(lock and lock.locked())

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

    async def get_workflow_thread_owner(self, thread_id: str):
        owner = self.owners.get(thread_id)
        if owner is None:
            return None
        external_run_id, owner_user_id = owner
        return {
            "thread_id": thread_id,
            "external_run_id": external_run_id,
            "owner_user_id": owner_user_id,
            "created_at": datetime.now(UTC),
        }


class _ThreadOwnershipWithoutExecutionLock:
    async def claim_workflow_thread(
        self, *, thread_id: str, external_run_id: str, owner_user_id: str
    ) -> bool:
        return True

    async def ensure_workflow_thread_owner(
        self, *, thread_id: str, external_run_id: str, owner_user_id: str
    ) -> bool:
        return True

    async def release_workflow_thread(
        self, *, thread_id: str, external_run_id: str, owner_user_id: str
    ) -> bool:
        return True

    async def get_workflow_thread_owner(self, thread_id: str):
        return None

    async def is_workflow_run_active(self, external_run_id: str) -> bool:
        return False


@pytest.mark.anyio
async def test_controller_fails_closed_when_execution_lock_is_missing() -> None:
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            return SimpleNamespace(status=RunStatus.completed)

    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=_ThreadOwnershipWithoutExecutionLock(),  # type: ignore[arg-type]
    )

    with pytest.raises(
        ReportingError,
        match="Reporting runtime 缺少 workflow 执行锁",
    ) as error:
        await controller.start(ReportingWorkflowInput(prompt="生成报表"), _context())

    assert error.value.code == "report_workflow_runtime_invalid"
    assert run_calls == 0


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
        known_runs: set[str] = set()

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            self.known_runs.add(_kwargs["run_id"])
            return SimpleNamespace(status=RunStatus.completed)

        async def aget_run(self, *_args, **_kwargs):
            if _args and _args[0] in self.known_runs:
                return SimpleNamespace(status=RunStatus.completed, user_id="user")
            return None

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
async def test_controller_releases_thread_when_sandbox_cleanup_fails() -> None:
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            return SimpleNamespace(status=RunStatus.cancelled)

    async def cleanup(*_args, **_kwargs) -> None:
        raise ReportingError(
            "report_sandbox_cleanup_failed",
            "报表工作流已结束，但运行环境删除失败。",
        )

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
        terminal_cleanup=cleanup,
    )
    first = await controller.start(ReportingWorkflowInput(prompt="生成第一份报表"), _context())

    assert first["status"] == "cancelled"
    assert ownership.owners == {}

    second_context = RunContext(
        run_id="external-run-2",
        session_id="thread",
        user_id="user",
        session_state={},
    )
    second = await controller.start(ReportingWorkflowInput(prompt="生成第二份报表"), second_context)

    assert second["status"] == "cancelled"
    assert run_calls == 2
    assert ownership.owners == {}


@pytest.mark.anyio
async def test_controller_keeps_thread_owned_when_sandbox_quarantine_fails() -> None:
    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            return SimpleNamespace(status=RunStatus.cancelled)

    async def cleanup(*_args, **_kwargs) -> None:
        raise ReportingError(
            "report_sandbox_quarantine_failed",
            "报表工作流已结束，但失败运行环境无法隔离。",
        )

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
        terminal_cleanup=cleanup,
    )

    with pytest.raises(ReportingError) as raised:
        await controller.start(ReportingWorkflowInput(prompt="生成报表"), _context())

    assert raised.value.code == "report_sandbox_quarantine_failed"
    assert ownership.owners == {"thread": ("external-run", "user")}


@pytest.mark.anyio
async def test_controller_preserves_run_error_and_releases_thread_after_sandbox_cleanup_failure() -> (
    None
):
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            if run_calls == 1:
                raise RuntimeError("materialize failed")
            return SimpleNamespace(status=RunStatus.completed)

    async def cleanup(*_args, **_kwargs) -> None:
        raise ReportingError(
            "report_sandbox_cleanup_failed",
            "报表工作流已结束，但运行环境删除失败。",
        )

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
        terminal_cleanup=cleanup,
    )

    with pytest.raises(RuntimeError, match="materialize failed"):
        await controller.start(ReportingWorkflowInput(prompt="生成第一份报表"), _context())

    assert ownership.owners == {}
    second = await controller.start(
        ReportingWorkflowInput(prompt="生成第二份报表"),
        RunContext(
            run_id="external-run-2",
            session_id="thread",
            user_id="user",
            session_state={},
        ),
    )
    assert second["status"] == "completed"
    assert run_calls == 2


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


@pytest.mark.anyio
async def test_controller_serializes_concurrent_approvals_for_same_run() -> None:
    continue_calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    class Requirement:
        step_name = "提纲审核"
        confirmation_message = "确认提纲"
        step_output = SimpleNamespace(content={"title": "报告", "sections": [], "assumptions": []})
        is_resolved = False

        def confirm(self) -> None:
            self.is_resolved = True

    class Workflow:
        id = "enterprise-reporting-workflow-v1"
        status = RunStatus.paused

        async def arun(self, *_args, **_kwargs):
            return SimpleNamespace(
                status=RunStatus.paused, active_step_requirements=[Requirement()]
            )

        async def aget_run(self, *_args, **_kwargs):
            if self.status != RunStatus.paused:
                return SimpleNamespace(status=self.status)
            return SimpleNamespace(
                status=RunStatus.paused, active_step_requirements=[Requirement()]
            )

        async def acontinue_run(self, *_args, **_kwargs):
            nonlocal continue_calls
            continue_calls += 1
            started.set()
            await release.wait()
            self.status = RunStatus.completed
            return SimpleNamespace(status=RunStatus.completed)

    ownership = _ThreadOwnership()
    workflow = Workflow()
    controller = ReportWorkflowController(lambda: workflow, thread_ownership=ownership)
    initial = _context()
    await controller.start(ReportingWorkflowInput(prompt="生成报表"), initial)
    first = asyncio.create_task(
        controller.approve(
            RunContext(
                run_id="request-1",
                session_id="thread",
                user_id="user",
                session_state=dict(initial.session_state),
            )
        )
    )
    await started.wait()
    second = asyncio.create_task(
        controller.approve(
            RunContext(
                run_id="request-2",
                session_id="thread",
                user_id="user",
                session_state=dict(initial.session_state),
            )
        )
    )
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(first, second, return_exceptions=True)

    assert continue_calls == 1
    assert any(
        isinstance(result, ReportingError) and result.code == "report_workflow_run_conflict"
        for result in results
    )


@pytest.mark.anyio
async def test_controller_does_not_reclaim_owner_when_run_lookup_fails() -> None:
    _, old_workflow_run_id = reporting_workflow_ids(
        user_id="user", thread_id="thread", external_run_id="external-run"
    )

    class Workflow:
        id = "enterprise-reporting-workflow-v1"
        started = False

        async def arun(self, *_args, **_kwargs):
            self.started = True
            return SimpleNamespace(status=RunStatus.running)

        async def aget_run(self, *_args, **_kwargs):
            if self.started and _args and _args[0] == old_workflow_run_id:
                raise RuntimeError("storage unavailable")
            return None

    ownership = _ThreadOwnership()
    workflow = Workflow()
    controller = ReportWorkflowController(lambda: workflow, thread_ownership=ownership)
    await controller.start(ReportingWorkflowInput(prompt="生成报表"), _context())

    second_context = RunContext(
        run_id="external-run-2",
        session_id="thread",
        user_id="user",
        session_state={},
    )
    with pytest.raises(ReportingError) as raised:
        await controller.start(ReportingWorkflowInput(prompt="生成第二份报表"), second_context)

    assert raised.value.code == "report_workflow_owner_lookup_failed"
    assert ownership.owners == {"thread": ("external-run", "user")}


@pytest.mark.anyio
async def test_controller_rejects_unknown_workflow_status() -> None:
    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            return SimpleNamespace(status="UNKNOWN")

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)

    with pytest.raises(ReportingError) as raised:
        await controller.start(ReportingWorkflowInput(prompt="生成报表"), _context())

    assert raised.value.code == "report_workflow_status_invalid"
    assert ownership.owners == {}


@pytest.mark.anyio
async def test_controller_retries_different_run_after_previous_run_releases_thread() -> None:
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            if run_calls == 1:
                first_started.set()
                await release_first.wait()
                return SimpleNamespace(status=RunStatus.cancelled)
            return SimpleNamespace(status=RunStatus.completed)

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)
    first = asyncio.create_task(
        controller.start(ReportingWorkflowInput(prompt="第一份报表"), _context())
    )
    await first_started.wait()
    second = asyncio.create_task(
        controller.start(
            ReportingWorkflowInput(prompt="第二份报表"),
            RunContext(
                run_id="external-run-2",
                session_id="thread",
                user_id="user",
                session_state={},
            ),
        )
    )
    await asyncio.sleep(0.15)
    release_first.set()

    first_result, second_result = await asyncio.gather(first, second)
    assert first_result["status"] == "cancelled"
    assert second_result["status"] == "completed"
    assert run_calls == 2


@pytest.mark.anyio
async def test_controller_restarts_same_run_when_persisted_running_owner_is_orphaned() -> None:
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            return SimpleNamespace(
                status=RunStatus.running if run_calls == 1 else RunStatus.completed
            )

        async def aget_run(self, *_args, **_kwargs):
            return None

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)
    await controller.start(ReportingWorkflowInput(prompt="第一次运行"), _context())

    restarted = await controller.start(
        ReportingWorkflowInput(prompt="重启后重试"),
        RunContext(
            run_id="external-run",
            session_id="thread",
            user_id="user",
            session_state={},
        ),
    )

    assert restarted["status"] == "completed"
    assert run_calls == 2
    assert ownership.owners == {}


@pytest.mark.anyio
async def test_controller_reclaims_orphan_after_sandbox_cleanup_is_deferred() -> None:
    cleanup_calls = 0
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            return SimpleNamespace(status=RunStatus.completed)

        async def aget_run(self, *_args, **_kwargs):
            return None

    async def cleanup(*_args, **_kwargs) -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        raise ReportingError(
            "report_sandbox_cleanup_failed",
            "报表工作流已结束，但运行环境删除失败，请重试清理。",
        )

    ownership = _ThreadOwnership()
    ownership.owners["thread"] = ("external-run", "user")
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
        terminal_cleanup=cleanup,
    )

    result = await asyncio.wait_for(
        controller.start(ReportingWorkflowInput(prompt="恢复遗留运行"), _context()),
        timeout=0.2,
    )

    assert result["status"] == "completed"
    assert cleanup_calls == 1
    assert run_calls == 1
    assert ownership.owners == {}


@pytest.mark.anyio
async def test_controller_allows_parallel_runs_for_different_sessions() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            if run_calls == 2:
                started.set()
            await release.wait()
            return SimpleNamespace(status=RunStatus.completed)

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)
    first = asyncio.create_task(
        controller.start(ReportingWorkflowInput(prompt="第一份"), _context())
    )
    await asyncio.sleep(0)
    second = asyncio.create_task(
        controller.start(
            ReportingWorkflowInput(prompt="第二份"),
            RunContext(
                run_id="external-run-2",
                session_id="thread-2",
                user_id="user",
                session_state={},
            ),
        )
    )
    await started.wait()
    release.set()

    first_result, second_result = await asyncio.gather(first, second)
    assert first_result["status"] == "completed"
    assert second_result["status"] == "completed"
    assert run_calls == 2
    assert ownership.owners == {}


@pytest.mark.anyio
async def test_controller_reuses_result_for_duplicate_start_same_external_run() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"
        completed = False

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            started.set()
            await release.wait()
            self.completed = True
            return SimpleNamespace(status=RunStatus.completed)

        async def aget_run(self, *_args, **_kwargs):
            return SimpleNamespace(status=RunStatus.completed) if self.completed else None

    ownership = _ThreadOwnership()
    workflow = Workflow()
    controller = ReportWorkflowController(lambda: workflow, thread_ownership=ownership)
    first = asyncio.create_task(
        controller.start(ReportingWorkflowInput(prompt="重复请求"), _context())
    )
    await started.wait()

    duplicate = asyncio.create_task(
        controller.start(
            ReportingWorkflowInput(prompt="重复请求"),
            RunContext(
                run_id="external-run",
                session_id="thread",
                user_id="user",
                session_state={},
            ),
        )
    )
    await asyncio.sleep(0)
    release.set()
    first_result, duplicate_result = await asyncio.gather(first, duplicate)
    assert first_result["status"] == "completed"
    assert duplicate_result["status"] == "completed"
    assert run_calls == 1


@pytest.mark.anyio
async def test_controller_duplicate_retry_keeps_original_wait_deadline(monkeypatch) -> None:
    class AlwaysConflictingOwnership(_ThreadOwnership):
        def workflow_execution_lock(self, external_run_id: str):
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def conflicting():
                raise ReportingError(
                    "report_workflow_run_conflict", "Reporting run 正由其他进程执行。"
                )
                yield

            return conflicting()

        async def is_workflow_run_active(self, external_run_id: str) -> bool:
            return False

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def aget_run(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(controller_module, "_THREAD_CLAIM_WAIT_SECONDS", 0.03)
    monkeypatch.setattr(controller_module, "_THREAD_CLAIM_RETRY_DELAY_SECONDS", 0.01)
    controller = ReportWorkflowController(
        lambda: Workflow(), thread_ownership=AlwaysConflictingOwnership()
    )

    with pytest.raises(ReportingError, match="同一报表请求正在执行") as error:
        await asyncio.wait_for(
            controller.start(ReportingWorkflowInput(prompt="重复请求"), _context()),
            timeout=0.2,
        )

    assert error.value.code == "report_workflow_run_conflict"


@pytest.mark.anyio
async def test_controller_reclaims_running_owner_after_execution_lock_is_released() -> None:
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            return SimpleNamespace(
                status=RunStatus.running if run_calls == 1 else RunStatus.completed
            )

        async def aget_run(self, *_args, **_kwargs):
            return SimpleNamespace(status=RunStatus.running)

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)
    await controller.start(ReportingWorkflowInput(prompt="遗留运行"), _context())

    result = await controller.start(
        ReportingWorkflowInput(prompt="接管后重跑"),
        RunContext(
            run_id="external-run-2",
            session_id="thread",
            user_id="user",
            session_state={},
        ),
    )

    assert result["status"] == "completed"
    assert run_calls == 2
    assert ownership.owners == {}
