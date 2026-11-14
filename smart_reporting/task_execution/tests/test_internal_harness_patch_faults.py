"""Offline patch fault corpus; repository/workspace doubles perform no external I/O.

These tests exercise the production kernel, not a proposed harness assembly.
A repository receipt alone is deliberately insufficient evidence of a write.
"""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.task_execution.execution import TaskExecutionKernel, TaskExecutionRuntime
from smart_reporting.task_execution.models import Lease, utcnow
from smart_reporting.task_execution.repository import TaskExecutionRepositoryError
from smart_reporting.workspace import WorkspaceError


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def patch_runtime():
    lease = Lease("worker", 7, utcnow() + timedelta(minutes=1))
    scope = TaskExecutionRuntime(
        task=SimpleNamespace(mutation_sequence=0), external_run_id="offline-task",
        internal_run_id="attempt", owner_user_id="user", thread_id="thread",
        sandbox_id="workspace", lease_owner=lease.owner, lease_epoch=lease.epoch,
        attempt_no=0, lease=lease,
    )
    repository = SimpleNamespace(
        increment_mutation=AsyncMock(return_value=1),
        reserve_execution=AsyncMock(), validate_execution_fence=AsyncMock(),
        update_execution=AsyncMock(), get_execution=AsyncMock(return_value=None),
    )
    workspace = SimpleNamespace(
        aapply_changes=AsyncMock(return_value={"paths": ["result.txt"]}),
        afile_bytes=AsyncMock(return_value=(b"same", "text/plain")),
        ahash_file=AsyncMock(),
    )
    return SimpleNamespace(
        kernel=TaskExecutionKernel(workspace, repository), repository=repository,
        workspace=workspace, scope=scope,
    )


async def create(runtime):
    return await runtime.kernel.patch(
        "create", "result.txt", None, None, False, None, None,
        content="new", _scope=runtime.scope,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("error", [PermissionError("synthetic deny"), WorkspaceError("write failed")])
async def test_write_failure_is_recorded_failed_and_propagated(patch_runtime, error):
    runtime = patch_runtime
    runtime.workspace.aapply_changes.side_effect = error
    with pytest.raises(type(error)) as captured:
        await create(runtime)
    assert captured.value is error
    update = runtime.repository.update_execution.await_args.kwargs
    assert update["status"] == "failed"
    assert update["exit_code"] == 1
    runtime.repository.get_execution.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["increment_mutation", "reserve_execution", "validate_execution_fence"])
async def test_prewrite_rejection_never_writes_or_records_completion(patch_runtime, stage):
    runtime = patch_runtime
    error = TaskExecutionRepositoryError("task_lease_lost", "synthetic stale lease")
    getattr(runtime.repository, stage).side_effect = error
    with pytest.raises(TaskExecutionRepositoryError) as captured:
        await create(runtime)
    assert captured.value is error
    runtime.workspace.aapply_changes.assert_not_awaited()
    runtime.repository.update_execution.assert_not_awaited()


@pytest.mark.anyio
async def test_cancel_during_write_preserves_unknown_receipt_without_success(patch_runtime):
    runtime = patch_runtime
    started, finalized = asyncio.Event(), asyncio.Event()

    async def blocked_write(*_args):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            finalized.set()

    runtime.workspace.aapply_changes.side_effect = blocked_write
    task = asyncio.create_task(create(runtime))
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert finalized.is_set()
    runtime.repository.reserve_execution.assert_awaited_once()
    # Cancellation cannot establish whether the external write took effect.
    runtime.repository.update_execution.assert_not_awaited()
    runtime.repository.get_execution.assert_not_awaited()


@pytest.mark.anyio
async def test_duplicate_noop_replace_never_reserves_mutation(patch_runtime):
    runtime = patch_runtime
    for _ in range(2):
        result = await runtime.kernel.patch(
            "replace", "result.txt", "same", "same", False, None, None,
            _scope=runtime.scope,
        )
        assert result["ok"] is False
        assert result["status"] == "rejected"
        assert result["code"] == "tool_no_progress"
    runtime.repository.increment_mutation.assert_not_awaited()
    runtime.repository.reserve_execution.assert_not_awaited()
    runtime.workspace.aapply_changes.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("readback", ["missing", "changed", "denied"])
async def test_postwrite_lost_fence_without_confirmed_artifact_never_succeeds(patch_runtime, readback):
    runtime = patch_runtime
    error = TaskExecutionRepositoryError("task_lease_lost", "synthetic postwrite takeover")
    runtime.repository.validate_execution_fence.side_effect = [None, error]

    async def execution(_execution_id):
        reservation = runtime.repository.reserve_execution.await_args.kwargs
        return SimpleNamespace(thread_id="thread", operation_receipt=reservation["operation_receipt"])

    runtime.repository.get_execution.side_effect = execution
    if readback == "missing":
        runtime.workspace.ahash_file.side_effect = WorkspaceError("synthetic missing")
    elif readback == "denied":
        runtime.workspace.ahash_file.side_effect = PermissionError("synthetic denied")
    else:
        runtime.workspace.ahash_file.return_value = {"sha256": "unexpected digest"}
    with pytest.raises(TaskExecutionRepositoryError) as captured:
        await create(runtime)
    assert captured.value is error
    assert all(
        call.kwargs.get("status") != "completed"
        for call in runtime.repository.update_execution.await_args_list
    )
