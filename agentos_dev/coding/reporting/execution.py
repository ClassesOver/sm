"""Reporting 专属的单次 Agno worker 执行边界。"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Any

from agno.agent import Agent

from ...async_utils import complete_cleanup
from ...task_execution import TaskExecutionRepository, TaskScope, TaskState
from ...task_execution.execution import TASK_EXECUTION_DEPENDENCY, TaskExecutionKernel
from ...task_execution.session import TaskSession
from .models import ReportingError

WorkerEventSink = Callable[[TaskScope, str, Any], Awaitable[None]]


class ReportTaskRunner:
    """由 Reporting Workflow 驱动一次 worker run，不复用 Coding Supervisor 状态机。"""

    def __init__(
        self,
        repository: TaskExecutionRepository,
        worker: Agent,
        execution_cleanup: TaskExecutionKernel,
        *,
        event_sink: WorkerEventSink | None = None,
    ):
        self.repository = repository
        self.worker = worker
        self.execution_cleanup = execution_cleanup
        self.event_sink = event_sink

    async def start(
        self,
        scope: TaskScope,
        instruction: str,
        *,
        acceptance_contract: dict[str, Any],
    ) -> None:
        await self.repository.create_task_with_initial_attempt(
            scope,
            instruction,
            acceptance_contract=acceptance_contract,
        )

    async def revise(
        self,
        scope: TaskScope,
        instruction_id: str,
        instruction: str,
        *,
        acceptance_contract: dict[str, Any],
    ) -> None:
        await self.repository.revise_completed_task(
            scope,
            instruction_id,
            instruction,
            acceptance_contract=acceptance_contract,
        )

    async def run(self, scope: TaskScope, *, parent_run_id: str = "") -> dict[str, Any]:
        async with TaskSession(self.repository, scope) as session:
            await self.execution_cleanup.cleanup_old_epoch(scope, session.lease.epoch)
            task = await self.repository.get_task_snapshot(scope.external_run_id)
            if task is None:
                raise ReportingError("report_worker_task_missing", "报表分析任务不存在。")
            if task.state is TaskState.COMPLETED:
                return self._finish_receipt(task)
            if task.state is TaskState.FINISHING:
                completed = await self.repository.finalize_finish(
                    scope.external_run_id,
                    session.lease,
                    task.state_version,
                    agno_status="completed",
                )
                return self._finish_receipt(completed)
            continuing = task.state in {TaskState.ACTIVE, TaskState.SUSPENDED}
            try:
                if continuing:
                    task, attempt = await self.repository.resume_current(
                        scope.external_run_id,
                        session.lease,
                        task.state_version,
                    )
                else:
                    task, attempt = await self.repository.open_initial(
                        scope.external_run_id,
                        session.lease,
                        task.state_version,
                    )
                instruction = await self.repository.attempt_instruction(
                    scope.external_run_id,
                    attempt.attempt_no,
                )
                dependencies = {
                    TASK_EXECUTION_DEPENDENCY: {
                        "externalRunId": scope.external_run_id,
                        "threadId": scope.thread_id,
                        "sandboxId": scope.sandbox_id,
                        "leaseOwner": session.lease.owner,
                        "leaseEpoch": session.lease.epoch,
                        "attemptNo": attempt.attempt_no,
                    }
                }
                if continuing:
                    run_result: Any = self.worker.acontinue_run(
                        run_id=attempt.internal_run_id,
                        stream=True,
                        session_id=_worker_session_id(scope),
                        user_id=scope.owner_user_id,
                        dependencies=dependencies,
                    )
                else:
                    run_result = self.worker.arun(
                        instruction,
                        stream=True,
                        run_id=attempt.internal_run_id,
                        session_id=_worker_session_id(scope),
                        user_id=scope.owner_user_id,
                        dependencies=dependencies,
                    )
                output = await self._consume_run(run_result, scope, parent_run_id)
                session.assert_alive()
                updated = await self.repository.get_task_snapshot(scope.external_run_id)
                if updated is None or updated.state is not TaskState.FINISHING:
                    raise ReportingError("report_worker_failed", "报表 Coding 分析未完成验收。")
                completed = await self.repository.finalize_finish(
                    scope.external_run_id,
                    session.lease,
                    updated.state_version,
                    agno_status=str(getattr(output, "status", "completed")),
                )
                return self._finish_receipt(completed)
            except BaseException:
                await complete_cleanup(self._cancel_and_cleanup(scope, session.lease.epoch))
                raise

    async def _consume_run(self, run_result: Any, scope: TaskScope, parent_run_id: str) -> Any:
        output = await run_result if isawaitable(run_result) else run_result
        if not hasattr(output, "__aiter__"):
            return output
        last_event: Any = None
        async for event in output:
            last_event = event
            if self.event_sink is not None and parent_run_id:
                try:
                    await self.event_sink(scope, parent_run_id, event)
                except Exception:
                    pass
        return last_event

    async def cancel(self, scope: TaskScope) -> None:
        task = await self.repository.get_task_snapshot(scope.external_run_id)
        if task is None or task.state in {
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }:
            return
        await self.repository.cancel_and_reject(scope)
        await self.execution_cleanup.cleanup_disconnect(scope, task.lease_epoch)

    async def _cancel_and_cleanup(self, scope: TaskScope, lease_epoch: int) -> None:
        try:
            await self.repository.cancel_and_reject(scope)
        finally:
            await self.execution_cleanup.cleanup_disconnect(scope, lease_epoch)

    @staticmethod
    def _finish_receipt(task: Any) -> dict[str, Any]:
        receipt = task.finish_receipt
        if not isinstance(receipt, dict):
            raise ReportingError(
                "report_artifact_acceptance_missing",
                "报表 Coding 任务缺少正式产物验收回执。",
            )
        return receipt


def _worker_session_id(scope: TaskScope) -> str:
    digest = hashlib.sha256(f"{scope.thread_id}:{scope.external_run_id}".encode()).hexdigest()[:32]
    return f"report-worker-{digest}"
