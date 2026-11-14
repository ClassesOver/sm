from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.model_routing import DEFAULT_MODEL_PROFILES
from smart_reporting.reporting import phase
from smart_reporting.reporting.tests.test_reporting_task_coordinator import _Repository, _utcnow
from smart_reporting.reporting.workflow import execution
from smart_reporting.task_execution import (
    TaskExecutionRepositoryError,
    TaskExecutionScope,
    TaskState,
)
from smart_reporting.task_execution.session import TaskSession


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def runtime(monkeypatch):
    scope = TaskExecutionScope("guard-task", "user", "thread", "workspace", "reporting")
    repository = _Repository(scope)
    async def cancel_owned(scope, *, lease):
        assert scope == repository.task.scope
        if repository.task.lease_epoch != lease.epoch:
            raise TaskExecutionRepositoryError("task_lease_lost", "旧 worker 不得取消新 owner。")
        repository.task = replace(repository.task, state=TaskState.CANCELLED)

    repository.cancel_and_reject = AsyncMock(side_effect=cancel_owned)
    kernel = SimpleNamespace(cleanup_old_epoch=AsyncMock(), cleanup_disconnect=AsyncMock())
    sessions = []

    def create_session(repository, scope):
        session = TaskSession(repository, scope, heartbeat_interval=0.01)
        sessions.append(session)
        return session

    async def heartbeat(_run_id, lease, *, ttl):
        return replace(lease, expires_at=_utcnow() + ttl)

    repository.heartbeat_lease = heartbeat
    monkeypatch.setattr(execution, "TaskSession", create_session)
    monkeypatch.setattr(execution, "TASK_RUNTIME_POLL_SECONDS", 0.005, raising=False)
    return scope, repository, kernel, sessions


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("fault", "code"),
    [
        ("lost", "task_lease_lost"),
        ("expiry", "task_lease_lost"),
        ("heartbeat", "task_lease_lost"),
        ("cancelled", "task_cancelled"),
        ("deadline", "task_deadline_exceeded"),
        ("takeover", "task_lease_lost"),
        ("failed", "task_not_active"),
        ("completed", "task_not_active"),
        ("snapshot_error", "repository_unavailable"),
    ],
)
async def test_coordinator_stops_running_executor_and_awaits_finally(
    runtime, monkeypatch, fault, code
):
    scope, repository, kernel, sessions = runtime
    started = asyncio.Event()
    finalized = asyncio.Event()
    settled = []
    monkeypatch.setattr(execution, "record_step_model_metrics", settled.append)
    coordinator = execution.ReportingTaskCoordinator(
        repository, kernel, model_profiles=DEFAULT_MODEL_PROFILES
    )

    async def executor(invocation):
        assert phase.current_reporting_run_context() is invocation.run_context
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.01)
            invocation.model_metrics_settlement.record_run_output(
                SimpleNamespace(metrics=SimpleNamespace(total_tokens=13)), 1
            )
            finalized.set()

    # 在真正运行的 executor 启动后注入故障，避免只覆盖入口前置检查。
    task = asyncio.create_task(coordinator.run(scope, executor=executor))
    await asyncio.wait_for(started.wait(), 1)
    session = sessions[0]
    if fault == "lost":
        session._lost.set()
    elif fault == "expiry":
        session._lease = replace(session.lease, expires_at=_utcnow())
    elif fault == "heartbeat":
        repository.heartbeat_lease = AsyncMock(side_effect=RuntimeError("heartbeat unavailable"))
    elif fault == "cancelled":
        repository.task = replace(repository.task, state=TaskState.CANCELLED, lease_epoch=2)
    elif fault in {"failed", "completed"}:
        repository.task = replace(repository.task, state=TaskState(fault))
    elif fault == "deadline":
        repository.task = replace(repository.task, deadline_at=_utcnow() - timedelta(seconds=1))
    elif fault == "takeover":
        repository.task = replace(repository.task, lease_epoch=2, lease_owner="new-owner")
    elif fault == "snapshot_error":
        repository.get_task_snapshot = AsyncMock(side_effect=RuntimeError(code))
    try:
        with pytest.raises(Exception) as captured:
            await asyncio.wait_for(task, 0.4)
        assert getattr(captured.value, "code", str(captured.value)) == code
    finally:
        # 红例超时也须回收本测试的任务。
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert finalized.is_set()
    kernel.cleanup_disconnect.assert_awaited_once_with(scope, 1)
    repository.cancel_and_reject.assert_awaited_once_with(scope, lease=session.lease)
    assert len(settled) == 1
    assert settled[0]["totalTokens"] == 13
    if fault == "takeover":
        assert repository.task.lease_epoch == 2
        assert repository.task.lease_owner == "new-owner"
        assert repository.task.state is TaskState.ACTIVE


@pytest.mark.anyio
@pytest.mark.parametrize("repeat_cancel", [False, True])
async def test_outer_cancel_keeps_cancelled_error_and_waits_for_executor(runtime, repeat_cancel):
    scope, repository, kernel, _sessions = runtime
    started, finalizing, finalized = asyncio.Event(), asyncio.Event(), asyncio.Event()
    coordinator = execution.ReportingTaskCoordinator(
        repository, kernel, model_profiles=DEFAULT_MODEL_PROFILES
    )

    async def executor(_invocation):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            finalizing.set()
            await asyncio.sleep(0.01)
            finalized.set()

    task = asyncio.create_task(coordinator.run(scope, executor=executor))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    if repeat_cancel:
        await asyncio.wait_for(finalizing.wait(), 1)
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finalized.is_set()
    kernel.cleanup_disconnect.assert_awaited_once_with(scope, 1)


@pytest.mark.anyio
async def test_normal_finish_preserves_context_metrics_and_finishing_finally(runtime, monkeypatch):
    scope, repository, kernel, _sessions = runtime
    settled = []
    monkeypatch.setattr(execution, "record_step_model_metrics", settled.append)
    coordinator = execution.ReportingTaskCoordinator(
        repository, kernel, model_profiles=DEFAULT_MODEL_PROFILES
    )
    prior_context = phase.current_reporting_run_context()

    async def executor(invocation):
        assert phase.current_reporting_run_context() is invocation.run_context
        invocation.run_context.session_state["executorMutation"] = True
        phase.record_reporting_projection_metrics({"canonical_estimated_tokens": 11}, input_token_hard_cap=100)
        invocation.model_metrics_settlement.record_run_output(
            SimpleNamespace(metrics=SimpleNamespace(total_tokens=7)), 1
        )
        repository.task = replace(
            repository.task, state=TaskState.FINISHING,
            finish_receipt={"summary": "完成"},
        )
        # FINISHING 时 executor 仍可做异步收尾，监视器不得误取消。
        await asyncio.sleep(0.02)
        assert phase.current_reporting_run_context().session_state["executorMutation"]
        return SimpleNamespace(status="completed")

    result = await coordinator.run(scope, executor=executor)
    assert result["summary"] == "完成"
    assert result["modelMetrics"]["totalTokens"] == 7
    assert result["projectionMetrics"]["modelRequestCount"] == 1
    assert result["projectionMetrics"]["maxCanonicalTokens"] == 11
    assert phase.current_reporting_run_context() is prior_context
    assert len(settled) == 1
    kernel.cleanup_disconnect.assert_not_awaited()
    repository.cancel_and_reject.assert_not_awaited()


@pytest.mark.anyio
async def test_finishing_task_restores_without_executing_again(runtime):
    scope, repository, kernel, _sessions = runtime
    repository.task = replace(
        repository.task, state=TaskState.FINISHING, finish_receipt={"summary": "恢复完成"}
    )
    executor = AsyncMock(side_effect=AssertionError("不得重新执行 FINISHING 任务"))
    coordinator = execution.ReportingTaskCoordinator(
        repository, kernel, model_profiles=DEFAULT_MODEL_PROFILES
    )
    assert await coordinator.run(scope, executor=executor) == {"summary": "恢复完成"}
    executor.assert_not_awaited()
    kernel.cleanup_disconnect.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("fault", "code"),
    [("deadline", "task_deadline_exceeded"), ("cancelled", "task_cancelled"),
     ("failed", "task_not_active"), ("completed", "task_not_active")],
)
async def test_preflight_does_not_start_executor_after_task_becomes_invalid(runtime, fault, code):
    scope, repository, kernel, _sessions = runtime
    original_instruction = repository.attempt_instruction

    async def instruction(*args):
        result = await original_instruction(*args)
        if fault == "deadline":
            repository.task = replace(repository.task, deadline_at=_utcnow() - timedelta(seconds=1))
        else:
            repository.task = replace(repository.task, state=TaskState(fault))
        return result

    repository.attempt_instruction = instruction
    executor = AsyncMock(return_value=SimpleNamespace(status="completed"))
    coordinator = execution.ReportingTaskCoordinator(
        repository, kernel, model_profiles=DEFAULT_MODEL_PROFILES
    )
    with pytest.raises(TaskExecutionRepositoryError) as captured:
        await coordinator.run(scope, executor=executor)
    assert captured.value.code == code
    executor.assert_not_awaited()


@pytest.mark.anyio
async def test_hanging_repository_read_stops_executor_instead_of_blinding_guard(runtime, monkeypatch):
    scope, repository, kernel, _sessions = runtime
    started, finalized = asyncio.Event(), asyncio.Event()

    async def executor(_invocation):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.01)
            finalized.set()

    coordinator = execution.ReportingTaskCoordinator(
        repository, kernel, model_profiles=DEFAULT_MODEL_PROFILES
    )
    task = asyncio.create_task(coordinator.run(scope, executor=executor))
    await asyncio.wait_for(started.wait(), 1)
    async def hanging_snapshot(_run_id):
        await asyncio.Event().wait()

    monkeypatch.setattr(execution, "TASK_RUNTIME_SNAPSHOT_TIMEOUT_SECONDS", 0.02)
    repository.get_task_snapshot = AsyncMock(side_effect=hanging_snapshot)
    with pytest.raises(TaskExecutionRepositoryError) as captured:
        await asyncio.wait_for(task, 0.4)
    assert captured.value.code == "task_runtime_check_timeout"
    assert finalized.is_set()
    kernel.cleanup_disconnect.assert_awaited_once_with(scope, 1)


@pytest.mark.anyio
@pytest.mark.parametrize("executor_fails", [False, True])
@pytest.mark.parametrize("cancel_count", [0, 1, 2])
async def test_cleanup_window_preserves_outer_cancel_and_original_error(
    runtime, executor_fails, cancel_count
):
    scope, repository, kernel, _sessions = runtime
    watcher_started, finalizing, release, finalized = (
        asyncio.Event(), asyncio.Event(), asyncio.Event(), asyncio.Event()
    )
    executor_finalized = asyncio.Event()
    failure = ValueError("executor 原始失败")
    coordinator = execution.ReportingTaskCoordinator(
        repository, kernel, model_profiles=DEFAULT_MODEL_PROFILES
    )

    async def watcher(_session):
        try:
            watcher_started.set()
            await asyncio.Event().wait()
        finally:
            finalizing.set()
            await release.wait()
            finalized.set()

    async def executor(_invocation):
        try:
            await watcher_started.wait()
            if executor_fails:
                raise failure
            repository.task = replace(
                repository.task, state=TaskState.FINISHING,
                finish_receipt={"summary": "正常执行完成"},
            )
            return SimpleNamespace(status="completed")
        finally:
            await asyncio.sleep(0)
            executor_finalized.set()

    coordinator._watch_runtime = watcher
    outer = asyncio.create_task(coordinator.run(scope, executor=executor))
    try:
        await asyncio.wait_for(finalizing.wait(), 1)
        for _ in range(cancel_count):
            outer.cancel()
            await asyncio.sleep(0)
        assert not outer.done()
        release.set()
        if cancel_count:
            with pytest.raises(asyncio.CancelledError):
                await outer
        elif executor_fails:
            with pytest.raises(ValueError) as captured:
                await outer
            assert captured.value is failure
        else:
            assert (await outer)["summary"] == "正常执行完成"
    finally:
        # 红例也释放监视器，避免遗留子任务。
        release.set()
        await asyncio.gather(outer, return_exceptions=True)
    assert finalized.is_set()
    assert executor_finalized.is_set()
    if cancel_count or executor_fails:
        kernel.cleanup_disconnect.assert_awaited_once_with(scope, 1)
    else:
        kernel.cleanup_disconnect.assert_not_awaited()
