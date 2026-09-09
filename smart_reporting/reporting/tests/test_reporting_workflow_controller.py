import asyncio
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.db.in_memory import InMemoryDb
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.workflow import HumanReview, OnError, Step, Workflow
from agno.workflow.types import StepOutput

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
        self.external_requests: dict[str, dict[str, str]] = {}
        self.run_registrations: list[dict[str, object]] = []
        self.request_attachments: list[tuple[str, str]] = []
        self.owner_attachments: list[dict[str, str]] = []
        self.status_updates: list[tuple[str, str, bool | None]] = []
        self.parent_runs: dict[str, dict[str, object]] = {}
        self.lock = asyncio.Lock()
        self.execution_locks: dict[str, asyncio.Lock] = {}

    async def register_run(self, **values: object) -> dict[str, object]:
        self.run_registrations.append(dict(values))
        stored = {"status": "running", "finalization_pending": False, **values}
        self.parent_runs[str(values["external_run_id"])] = stored
        return stored

    async def get_run_by_external(self, external_run_id: str) -> dict[str, object] | None:
        return self.parent_runs.get(external_run_id)

    async def attach_request_run(self, external_run_id: str, report_run_id: str) -> None:
        self.request_attachments.append((external_run_id, report_run_id))

    async def attach_workflow_owner_run(self, **values: str) -> None:
        assert self.owners.get(values["thread_id"]) == (
            values["external_run_id"],
            values["owner_user_id"],
        )
        self.owner_attachments.append(dict(values))

    async def update_run_status(
        self,
        report_run_id: str,
        *,
        status: str,
        finalization_pending: bool | None = None,
    ) -> None:
        self.status_updates.append((report_run_id, status, finalization_pending))
        for parent in self.parent_runs.values():
            if parent.get("report_run_id") == report_run_id:
                parent["status"] = status
                if finalization_pending is not None:
                    parent["finalization_pending"] = finalization_pending

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

    async def register_external_request(self, **values: str) -> dict[str, str]:
        external_run_id = values["external_run_id"]
        async with self.lock:
            return self.external_requests.setdefault(external_run_id, dict(values))

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
async def test_external_background_start_returns_before_workflow_completes() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        def __init__(self) -> None:
            self.output = None

        async def arun(self, *_args, **kwargs):
            started.set()
            await release.wait()
            self.output = SimpleNamespace(
                status=RunStatus.completed,
                user_id=kwargs["user_id"],
                metadata=kwargs["metadata"],
                content=None,
            )
            return self.output

        async def aget_run(self, *_args, **_kwargs):
            return self.output

    workflow = Workflow()
    controller = ReportWorkflowController(
        lambda: workflow,
        thread_ownership=_ThreadOwnership(),
    )

    accepted = await controller.start_external_background(
        ReportingWorkflowInput(prompt="生成报表"),
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
        request_fingerprint="a" * 64,
    )
    await asyncio.wait_for(started.wait(), timeout=0.1)

    assert accepted == {"ok": True, "status": "running"}
    assert await controller.get_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    ) == {"ok": True, "status": "running"}

    release.set()
    await controller._background_tasks["external-run"]
    completed = await controller.get_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )
    assert completed == {"ok": True, "status": "completed"}


@pytest.mark.anyio
async def test_external_background_keeps_preclaimed_owner_without_early_cleanup() -> None:
    started = asyncio.Event()
    cleanup_calls: list[str] = []

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            started.set()
            await asyncio.Future()

        async def aget_run(self, *_args, **_kwargs):
            return None

    async def cleanup(scope, *_args) -> None:
        cleanup_calls.append(scope["external_run_id"])

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
        terminal_cleanup=cleanup,
    )
    await controller.start_external_background(
        ReportingWorkflowInput(prompt="生成报表"),
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
        request_fingerprint="a" * 64,
        prepare=lambda: asyncio.sleep(0, result=ReportingWorkflowInput(prompt="已物化请求")),
    )
    await asyncio.wait_for(started.wait(), timeout=0.1)
    cleanup_before_cancel = len(cleanup_calls)

    await controller.cancel_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )

    assert cleanup_before_cancel == 0
    _, report_run_id = reporting_workflow_ids(
        user_id="user", thread_id="thread", external_run_id="external-run"
    )
    assert ownership.status_updates == [
        (report_run_id, "cancelled", True),
        (report_run_id, "cancelled", False),
    ]


@pytest.mark.anyio
async def test_mcp_preclaim_attaches_request_and_owner_to_reporting_run() -> None:
    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            return SimpleNamespace(status=RunStatus.completed)

        async def aget_run(self, *_args, **_kwargs):
            return None

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)
    await controller.reserve_external_request(
        external_run_id="external-run",
        request_fingerprint="a" * 64,
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )

    await controller.start_external(
        ReportingWorkflowInput(prompt="生成报表"),
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
        request_fingerprint="a" * 64,
        thread_preclaimed=True,
    )

    registration = ownership.run_registrations[-1]
    report_run_id = str(registration["report_run_id"])
    assert registration["entrypoint"] == "mcp"
    assert registration["caller_session_id"] == "thread"
    assert registration["caller_run_id"] == "external-run"
    assert ownership.request_attachments == [("external-run", report_run_id)]
    assert ownership.owner_attachments == [
        {
            "thread_id": "thread",
            "external_run_id": "external-run",
            "owner_user_id": "user",
            "report_run_id": report_run_id,
        }
    ]


@pytest.mark.anyio
async def test_external_background_active_run_rejects_changed_fingerprint() -> None:
    started = asyncio.Event()

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            started.set()
            await asyncio.Future()

        async def aget_run(self, *_args, **_kwargs):
            return None

    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=_ThreadOwnership(),
    )
    await controller.start_external_background(
        ReportingWorkflowInput(prompt="第一个请求"),
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
        request_fingerprint="a" * 64,
    )
    await asyncio.wait_for(started.wait(), timeout=0.1)
    conflict: ReportingError | None = None
    try:
        await controller.start_external_background(
            ReportingWorkflowInput(prompt="被改写的请求"),
            external_run_id="external-run",
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="11",
            request_fingerprint="b" * 64,
        )
    except ReportingError as error:
        conflict = error
    finally:
        await controller.cancel_external(
            external_run_id="external-run",
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="11",
        )

    assert conflict is not None
    assert conflict.code == "report_mcp_idempotency_conflict"


@pytest.mark.anyio
async def test_external_reserved_request_is_queryable_while_attachments_download() -> None:
    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def aget_run(self, *_args, **_kwargs):
            return None

    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=_ThreadOwnership(),
    )
    created = await controller.reserve_external_request(
        external_run_id="external-run",
        request_fingerprint="a" * 64,
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )

    result = await controller.get_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )

    assert created is False
    assert result == {"ok": True, "status": "running"}


@pytest.mark.anyio
async def test_external_reservation_blocks_cross_controller_owner_reclaim() -> None:
    prepare_started = asyncio.Event()
    release_prepare = asyncio.Event()

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            await asyncio.Future()

        async def aget_run(self, *_args, **_kwargs):
            return None

    async def prepare() -> ReportingWorkflowInput:
        prepare_started.set()
        await release_prepare.wait()
        return ReportingWorkflowInput(prompt="物化后的请求")

    ownership = _ThreadOwnership()
    first = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)
    second = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)

    first_start = asyncio.create_task(
        first.start_external_background(
            ReportingWorkflowInput(prompt="第一个请求"),
            external_run_id="external-run-1",
            request_fingerprint="a" * 64,
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="11",
            prepare=prepare,
        )
    )
    await prepare_started.wait()

    with pytest.raises(ReportingError) as error:
        await second.start_external_background(
            ReportingWorkflowInput(prompt="第二个请求"),
            external_run_id="external-run-2",
            request_fingerprint="b" * 64,
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="11",
        )

    assert error.value.code == "report_workflow_active"
    assert ownership.owners == {"thread": ("external-run-1", "user")}
    release_prepare.set()
    await first_start
    await first.cancel_external(
        external_run_id="external-run-1",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )


@pytest.mark.anyio
async def test_external_get_observes_cross_controller_attachment_reservation() -> None:
    prepare_started = asyncio.Event()
    release_prepare = asyncio.Event()

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            await asyncio.Future()

        async def aget_run(self, *_args, **_kwargs):
            return None

    async def prepare() -> ReportingWorkflowInput:
        prepare_started.set()
        await release_prepare.wait()
        return ReportingWorkflowInput(prompt="物化后的请求")

    scope_digest = hashlib.sha256(
        json.dumps(
            ["odoo", "11", "user", "thread"],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    operation_id = scope_digest + hashlib.sha256(b"request-1").hexdigest()
    ownership = _ThreadOwnership()
    first = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)
    second = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)

    first_start = asyncio.create_task(
        first.start_external_background(
            ReportingWorkflowInput(prompt="原始请求"),
            external_run_id=operation_id,
            request_fingerprint="a" * 64,
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="11",
            prepare=prepare,
        )
    )
    await prepare_started.wait()

    result = await second.get_external(
        external_run_id=operation_id,
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )

    assert result == {"ok": True, "status": "running"}
    release_prepare.set()
    await first_start
    await first.cancel_external(
        external_run_id=operation_id,
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )


@pytest.mark.anyio
async def test_external_get_rejects_cross_tenant_attachment_reservation() -> None:
    prepare_started = asyncio.Event()
    release_prepare = asyncio.Event()

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            await asyncio.Future()

        async def aget_run(self, *_args, **_kwargs):
            return None

    async def prepare() -> ReportingWorkflowInput:
        prepare_started.set()
        await release_prepare.wait()
        return ReportingWorkflowInput(prompt="物化后的请求")

    scope_digest = hashlib.sha256(
        json.dumps(
            ["odoo", "11", "user", "thread"],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    operation_id = scope_digest + hashlib.sha256(b"request-1").hexdigest()
    ownership = _ThreadOwnership()
    first = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)
    second = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)

    first_start = asyncio.create_task(
        first.start_external_background(
            ReportingWorkflowInput(prompt="原始请求"),
            external_run_id=operation_id,
            request_fingerprint="a" * 64,
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="11",
            prepare=prepare,
        )
    )
    await prepare_started.wait()

    with pytest.raises(ReportingError) as error:
        await second.get_external(
            external_run_id=operation_id,
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="12",
        )

    assert error.value.code == "report_workflow_scope_mismatch"
    release_prepare.set()
    await first_start
    await first.cancel_external(
        external_run_id=operation_id,
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )


@pytest.mark.anyio
async def test_external_reservation_rejects_second_run_for_same_thread() -> None:
    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def aget_run(self, *_args, **_kwargs):
            return None

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)
    await controller.reserve_external_request(
        external_run_id="external-run-1",
        request_fingerprint="a" * 64,
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )

    with pytest.raises(ReportingError) as error:
        await controller.reserve_external_request(
            external_run_id="external-run-2",
            request_fingerprint="b" * 64,
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="11",
        )

    assert error.value.code == "report_workflow_active"
    assert ownership.owners == {"thread": ("external-run-1", "user")}


@pytest.mark.anyio
async def test_external_request_fingerprint_survives_controller_restart() -> None:
    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def aget_run(self, *_args, **_kwargs):
            return None

    ownership = _ThreadOwnership()
    first = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)
    await first.reserve_external_request(
        external_run_id="external-run",
        request_fingerprint="a" * 64,
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )
    await first.release_external_request(
        external_run_id="external-run",
        request_fingerprint="a" * 64,
    )
    restarted = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)

    with pytest.raises(ReportingError) as error:
        await restarted.reserve_external_request(
            external_run_id="external-run",
            request_fingerprint="b" * 64,
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="11",
        )

    assert error.value.code == "report_mcp_idempotency_conflict"


@pytest.mark.anyio
async def test_external_get_rejects_run_without_mcp_metadata() -> None:
    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def aget_run(self, *_args, **_kwargs):
            return SimpleNamespace(
                status=RunStatus.completed,
                user_id="user",
                metadata=None,
                content=None,
            )

    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=_ThreadOwnership(),
    )

    with pytest.raises(ReportingError) as error:
        await controller.get_external(
            external_run_id="external-run",
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="11",
        )

    assert error.value.code == "report_workflow_scope_mismatch"


@pytest.mark.anyio
async def test_external_cancel_stops_active_background_task() -> None:
    started = asyncio.Event()

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            started.set()
            await asyncio.Future()

        async def aget_run(self, *_args, **_kwargs):
            return None

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
    )
    await controller.start_external_background(
        ReportingWorkflowInput(prompt="生成报表"),
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
        request_fingerprint="a" * 64,
    )
    await asyncio.wait_for(started.wait(), timeout=0.1)

    with pytest.raises(ReportingError) as scope_error:
        await controller.cancel_external(
            external_run_id="external-run",
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="12",
        )
    assert scope_error.value.code == "report_workflow_scope_mismatch"

    result = await controller.cancel_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )

    assert result == {"ok": True, "status": "cancelled"}
    assert ownership.owners == {}
    assert await controller.get_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    ) == {"ok": True, "status": "cancelled"}


@pytest.mark.anyio
async def test_external_cancel_releases_preclaimed_thread_before_task_runs() -> None:
    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            await asyncio.Future()

        async def aget_run(self, *_args, **_kwargs):
            return None

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)
    await controller.reserve_external_request(
        external_run_id="external-run",
        request_fingerprint="a" * 64,
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )
    await controller.start_external_background(
        ReportingWorkflowInput(prompt="生成报表"),
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
        request_fingerprint="a" * 64,
        thread_preclaimed=True,
    )

    result = await controller.cancel_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )

    assert result == {"ok": True, "status": "cancelled"}
    assert ownership.owners == {}


@pytest.mark.anyio
async def test_preclaimed_background_start_holds_execution_lock_before_accepting() -> None:
    started = asyncio.Event()

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            started.set()
            await asyncio.Future()

        async def aget_run(self, *_args, **_kwargs):
            return None

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)
    await controller.reserve_external_request(
        external_run_id="external-run",
        request_fingerprint="a" * 64,
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )

    await controller.start_external_background(
        ReportingWorkflowInput(prompt="生成报表"),
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
        request_fingerprint="a" * 64,
        thread_preclaimed=True,
    )

    assert await ownership.is_workflow_run_active("external-run") is True
    assert started.is_set()
    await controller.cancel_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )


@pytest.mark.anyio
async def test_external_background_prepares_request_under_single_execution_lock() -> None:
    from contextlib import asynccontextmanager

    class SingleSlotOwnership(_ThreadOwnership):
        def __init__(self) -> None:
            super().__init__()
            self.single_lock = asyncio.Lock()

        def workflow_execution_lock(self, _external_run_id: str):
            @asynccontextmanager
            async def locked():
                if self.single_lock.locked():
                    raise ReportingError(
                        "report_workflow_run_conflict", "Reporting run 正由其他进程执行。"
                    )
                await self.single_lock.acquire()
                try:
                    yield
                finally:
                    self.single_lock.release()

            return locked()

        async def is_workflow_run_active(self, _external_run_id: str) -> bool:
            return self.single_lock.locked()

    started = asyncio.Event()

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            started.set()
            await asyncio.Future()

        async def aget_run(self, *_args, **_kwargs):
            return None

    async def prepare() -> ReportingWorkflowInput:
        return ReportingWorkflowInput(prompt="物化后的报表请求")

    ownership = SingleSlotOwnership()
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)

    result = await controller.start_external_background(
        ReportingWorkflowInput(prompt="原始请求"),
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
        request_fingerprint="a" * 64,
        prepare=prepare,
    )

    assert result == {"ok": True, "status": "running"}
    assert started.is_set()
    await controller.cancel_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )


@pytest.mark.anyio
async def test_external_background_cleans_prepared_inputs_when_preflight_fails() -> None:
    reads = 0
    cleanup_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def aget_run(self, *_args, **_kwargs):
            nonlocal reads
            reads += 1
            if reads == 1:
                return None
            raise RuntimeError("postgres read failed")

    async def prepare() -> ReportingWorkflowInput:
        return ReportingWorkflowInput(prompt="物化后的报表请求")

    async def cleanup_prepared_inputs() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)

    accepted = await controller.start_external_background(
        ReportingWorkflowInput(prompt="原始请求"),
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
        request_fingerprint="a" * 64,
        prepare=prepare,
        prepared_input_cleanup=cleanup_prepared_inputs,
    )

    assert accepted == {"ok": True, "status": "running"}
    with pytest.raises(RuntimeError, match="postgres read failed"):
        await controller._background_tasks["external-run"]
    assert cleanup_calls == 1
    assert ownership.owners == {}


@pytest.mark.anyio
async def test_external_background_recovers_workspace_after_attachment_cleanup_failure() -> None:
    terminal_cleanup_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def aget_run(self, *_args, **_kwargs):
            return None

    async def prepare() -> ReportingWorkflowInput:
        raise ReportingError(
            "report_attachment_cleanup_failed",
            "报表附件清理失败。",
        )

    async def terminal_cleanup(*_args, **_kwargs) -> None:
        nonlocal terminal_cleanup_calls
        terminal_cleanup_calls += 1

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
        terminal_cleanup=terminal_cleanup,
    )

    with pytest.raises(ReportingError) as error:
        await controller.start_external_background(
            ReportingWorkflowInput(prompt="原始请求"),
            external_run_id="external-run",
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="11",
            request_fingerprint="a" * 64,
            prepare=prepare,
        )

    assert error.value.code == "report_attachment_cleanup_failed"
    assert terminal_cleanup_calls == 1
    assert ownership.owners == {}


@pytest.mark.anyio
async def test_external_background_keeps_owner_when_attachment_quarantine_fails() -> None:
    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def aget_run(self, *_args, **_kwargs):
            return None

    async def prepare() -> ReportingWorkflowInput:
        raise ReportingError(
            "report_attachment_cleanup_failed",
            "报表附件清理失败。",
        )

    async def terminal_cleanup(*_args, **_kwargs) -> None:
        raise ReportingError(
            "report_sandbox_quarantine_failed",
            "报表运行环境无法隔离。",
        )

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
        terminal_cleanup=terminal_cleanup,
    )

    with pytest.raises(ReportingError) as error:
        await controller.start_external_background(
            ReportingWorkflowInput(prompt="原始请求"),
            external_run_id="external-run",
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="11",
            request_fingerprint="a" * 64,
            prepare=prepare,
        )

    assert error.value.code == "report_attachment_cleanup_failed"
    assert isinstance(error.value.__cause__, ReportingError)
    assert error.value.__cause__.code == "report_sandbox_quarantine_failed"
    assert ownership.owners == {"thread": ("external-run", "user")}


@pytest.mark.anyio
async def test_external_background_rejects_when_capacity_is_exhausted(monkeypatch) -> None:
    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            await asyncio.Future()

        async def aget_run(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(controller_module, "_MAX_ACTIVE_BACKGROUND_TASKS", 1)
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=_ThreadOwnership())
    await controller.start_external_background(
        ReportingWorkflowInput(prompt="第一个请求"),
        external_run_id="external-run-1",
        thread_id="thread-1",
        user_id="user",
        database="odoo",
        company_id="11",
        request_fingerprint="a" * 64,
    )

    with pytest.raises(ReportingError) as error:
        await controller.start_external_background(
            ReportingWorkflowInput(prompt="第二个请求"),
            external_run_id="external-run-2",
            thread_id="thread-2",
            user_id="user",
            database="odoo",
            company_id="11",
            request_fingerprint="b" * 64,
        )

    assert error.value.code == "report_workflow_capacity_exceeded"
    await controller.cancel_external(
        external_run_id="external-run-1",
        thread_id="thread-1",
        user_id="user",
        database="odoo",
        company_id="11",
    )


@pytest.mark.anyio
async def test_external_cancel_keeps_owner_when_workspace_quarantine_fails() -> None:
    started = asyncio.Event()

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            started.set()
            await asyncio.Future()

        async def aget_run(self, *_args, **_kwargs):
            return None

    async def cleanup(*_args, **_kwargs) -> None:
        raise ReportingError(
            "report_sandbox_quarantine_failed",
            "报表工作流已结束，但失败运行环境无法隔离，请稍后重试。",
        )

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
        terminal_cleanup=cleanup,
    )
    await controller.reserve_external_request(
        external_run_id="external-run",
        request_fingerprint="a" * 64,
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )
    await controller.start_external_background(
        ReportingWorkflowInput(prompt="生成报表"),
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
        request_fingerprint="a" * 64,
        thread_preclaimed=True,
    )
    await asyncio.wait_for(started.wait(), timeout=0.1)

    with pytest.raises(ReportingError) as error:
        await controller.cancel_external(
            external_run_id="external-run",
            thread_id="thread",
            user_id="user",
            database="odoo",
            company_id="11",
        )

    assert error.value.code == "report_sandbox_quarantine_failed"
    assert ownership.owners == {"thread": ("external-run", "user")}


@pytest.mark.anyio
async def test_external_reservation_recovers_stale_preclaim_after_restart() -> None:
    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def aget_run(self, *_args, **_kwargs):
            return None

    ownership = _ThreadOwnership()
    assert await ownership.claim_workflow_thread(
        thread_id="thread",
        external_run_id="external-run",
        owner_user_id="user",
    )
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=ownership)

    existing = await controller.reserve_external_request(
        external_run_id="external-run",
        request_fingerprint="a" * 64,
        thread_id="thread",
        user_id="user",
        database="odoo",
        company_id="11",
    )

    assert existing is False
    assert ownership.owners == {"thread": ("external-run", "user")}


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
                "database": "default",
                "company_id": "default",
            },
            session_id,
            run_id,
        )
    ]


@pytest.mark.anyio
async def test_controller_reclaims_sandbox_when_workflow_raises() -> None:
    cleanup_calls: list[tuple[dict[str, str], str, str]] = []
    events: list[str] = []

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            raise RuntimeError("workflow failed")

    async def cleanup(scope: dict[str, str], session_id: str, run_id: str) -> None:
        events.append("cleanup")
        cleanup_calls.append((scope, session_id, run_id))

    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=ownership,
        terminal_cleanup=cleanup,
    )
    original_update = ownership.update_run_status

    async def record_status(*args, **kwargs) -> None:
        events.append(f"status:{kwargs['status']}:{kwargs['finalization_pending']}")
        await original_update(*args, **kwargs)

    ownership.update_run_status = record_status  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="workflow failed"):
        await controller.start(ReportingWorkflowInput(prompt="生成报表"), _context())

    assert len(cleanup_calls) == 1
    assert cleanup_calls[0][0]["thread_id"] == "thread"
    report_run_id = str(ownership.run_registrations[-1]["report_run_id"])
    assert ownership.status_updates == [
        (report_run_id, "failed", True),
        (report_run_id, "failed", False),
    ]
    assert events == ["status:failed:True", "cleanup", "status:failed:False"]


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
    report_run_id = str(ownership.run_registrations[-1]["report_run_id"])
    assert ownership.status_updates == [(report_run_id, "failed", True)]

    recovered = await controller.start(ReportingWorkflowInput(prompt="重试清理"), context)

    assert recovered["status"] == "failed"
    assert cleanup_calls == 2
    assert ownership.owners == {}
    assert ownership.status_updates[-1] == (report_run_id, "failed", False)

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
async def test_controller_retries_parent_pending_cleanup_without_agno_failed_row() -> None:
    run_calls = 0
    cleanup = AsyncMock()
    ownership = _ThreadOwnership()
    session_id, run_id = reporting_workflow_ids(
        user_id="user", thread_id="thread", external_run_id="external-run"
    )
    ownership.owners["thread"] = ("external-run", "user")
    ownership.parent_runs["external-run"] = {
        "report_run_id": run_id,
        "external_run_id": "external-run",
        "workflow_id": "enterprise-reporting-workflow-v1",
        "agno_session_id": session_id,
        "agno_run_id": run_id,
        "caller_session_id": "thread",
        "caller_run_id": "external-run",
        "thread_id": "thread",
        "owner_user_id": "user",
        "database": "default",
        "company_id": "default",
        "status": "failed",
        "finalization_pending": True,
    }

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1

        async def aget_run(self, *_args, **_kwargs):
            return None

    context = _context()
    controller = ReportWorkflowController(
        lambda: Workflow(), thread_ownership=ownership, terminal_cleanup=cleanup
    )

    result = await controller.start(ReportingWorkflowInput(prompt="重试清理"), context)

    assert result["status"] == "failed"
    assert run_calls == 0
    cleanup.assert_awaited_once()
    assert ownership.status_updates == [(run_id, "failed", False)]
    assert ownership.owners == {}


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
@pytest.mark.parametrize("step_id", ["assemble-report", "validate-report"])
async def test_controller_recovery_pause_retries_error_without_cleanup(step_id: str) -> None:
    class Requirement:
        step_name = "报告末端恢复"
        step_output = None
        is_resolved = False

        def __init__(self) -> None:
            self.step_id = step_id
            self.retry_calls = 0

        def retry(self) -> None:
            self.retry_calls += 1
            self.is_resolved = True

        def confirm(self) -> None:
            raise AssertionError("ErrorRequirement 不得走普通 confirm")

    requirement = Requirement()

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            return SimpleNamespace(
                status=RunStatus.paused,
                active_step_requirements=[],
                step_requirements=[],
                error_requirements=[requirement],
            )

        async def aget_run(self, *_args, **_kwargs):
            return SimpleNamespace(
                status=RunStatus.paused,
                active_step_requirements=[],
                step_requirements=[],
                error_requirements=[requirement],
            )

        async def acontinue_run(self, *_args, **_kwargs):
            return SimpleNamespace(status=RunStatus.completed)

    cleanup = AsyncMock()
    ownership = _ThreadOwnership()
    workflow = Workflow()
    controller = ReportWorkflowController(
        lambda: workflow,
        thread_ownership=ownership,
        terminal_cleanup=cleanup,
    )
    context = _context()

    paused = await controller.start(ReportingWorkflowInput(prompt="生成报表"), context)

    assert paused["status"] == "paused"
    assert paused["review"]["stage"] == "recovery"
    assert paused["review"]["preview"]["stepId"] == step_id
    assert ownership.owners == {"thread": ("external-run", "user")}
    report_run_id = str(ownership.run_registrations[-1]["report_run_id"])
    assert ownership.status_updates == [(report_run_id, "paused", None)]
    cleanup.assert_not_awaited()

    completed = await controller.approve(context)

    assert completed["status"] == "completed"
    assert requirement.retry_calls == 1
    assert ownership.status_updates[-1] == (report_run_id, "completed", False)
    cleanup.assert_not_awaited()


@pytest.mark.anyio
async def test_controller_can_cancel_recovery_pause_and_then_cleanup() -> None:
    after_assembly_calls = 0

    async def fail_assembly(*_args, **_kwargs) -> StepOutput:
        raise RuntimeError("assembly failed")

    async def after_assembly(*_args, **_kwargs) -> StepOutput:
        nonlocal after_assembly_calls
        after_assembly_calls += 1
        return StepOutput(content="must not run")

    cleanup = AsyncMock()
    ownership = _ThreadOwnership()
    workflow = Workflow(
        id="enterprise-reporting-workflow-v1",
        db=InMemoryDb(),
        steps=[
            Step(
                step_id="assemble-report",
                name="汇编最终报告",
                executor=fail_assembly,
                max_retries=0,
                human_review=HumanReview(on_error=OnError.pause),
            ),
            Step(step_id="after-assembly", name="后续步骤", executor=after_assembly),
        ],
        telemetry=False,
    )
    controller = ReportWorkflowController(
        lambda: workflow,
        thread_ownership=ownership,
        terminal_cleanup=cleanup,
    )
    context = _context()
    await controller.start(ReportingWorkflowInput(prompt="生成报表"), context)

    cancelled = await controller.cancel(context)

    assert cancelled["status"] == "cancelled"
    session_id, run_id = reporting_workflow_ids(
        user_id="user", thread_id="thread", external_run_id="external-run"
    )
    persisted = await workflow.aget_run(run_id, session_id=session_id)
    assert persisted is not None
    assert controller._status(persisted.status) == "cancelled"
    assert after_assembly_calls == 0
    cleanup.assert_awaited_once()
    assert ownership.owners == {}


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
async def test_controller_keeps_pending_when_sandbox_cleanup_is_deferred() -> None:
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
    context = _context()
    first = await controller.start(ReportingWorkflowInput(prompt="生成第一份报表"), context)

    assert first["status"] == "cancelled"
    assert ownership.owners == {"thread": ("external-run", "user")}
    assert ownership.status_updates[-1][1:] == ("cancelled", True)
    assert context.session_state[REPORT_WORKFLOW_CONTROL_STATE_KEY]["finalizationPending"] is True
    assert run_calls == 1


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
async def test_controller_preserves_run_error_and_owner_after_sandbox_cleanup_failure() -> (
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

    context = _context()
    with pytest.raises(RuntimeError, match="materialize failed"):
        await controller.start(ReportingWorkflowInput(prompt="生成第一份报表"), context)

    assert ownership.owners == {"thread": ("external-run", "user")}
    assert ownership.status_updates[-1][1:] == ("failed", True)
    retried = await controller.start(ReportingWorkflowInput(prompt="重试清理"), context)
    assert retried["status"] == "failed"
    assert run_calls == 1


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
