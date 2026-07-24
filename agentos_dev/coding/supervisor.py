from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol

from .executor import AgnoCodingExecutor, AgnoRunState
from .models import (
    AttemptOutcome,
    AttemptSnapshot,
    AttemptState,
    CodingEvent,
    CodingScope,
    InstructionReceipt,
    TaskSnapshot,
    TaskState,
)
from .policy import ContinuationAction, ContinuationPolicy
from .repository import CodingRepositoryError, CodingTaskRepository
from .run_manager import InternalRunManager
from .session import TaskSession


class ExecutionCleanup(Protocol):
    async def cleanup_old_epoch(self, scope: CodingScope, current_epoch: int) -> None: ...

    async def cleanup_disconnect(self, scope: CodingScope, current_epoch: int) -> None: ...


class CodingTaskSupervisor:
    def __init__(
        self,
        repository: CodingTaskRepository,
        executor: AgnoCodingExecutor,
        *,
        policy: ContinuationPolicy | None = None,
        run_manager: InternalRunManager | None = None,
        execution_cleanup: ExecutionCleanup | None = None,
        session_factory: Callable[[CodingTaskRepository, CodingScope], TaskSession] = TaskSession,
    ):
        self.repository = repository
        self.executor = executor
        self.policy = policy or ContinuationPolicy()
        self.run_manager = run_manager or InternalRunManager(repository)
        self.execution_cleanup = execution_cleanup
        self.session_factory = session_factory

    async def start_task(
        self,
        scope: CodingScope,
        initial_instruction: str,
        predecessor_task_id: str | None = None,
    ) -> TaskSnapshot:
        return await self.repository.create_task_with_initial_attempt(
            scope, initial_instruction, predecessor_task_id
        )

    async def run_task(self, scope: CodingScope) -> AsyncIterator[CodingEvent]:
        stream = self._drive(scope)
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()

    async def resume_task(self, scope: CodingScope) -> AsyncIterator[CodingEvent]:
        stream = self._drive(scope)
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()

    async def submit_instruction(
        self,
        scope: CodingScope,
        instruction_id: str,
        content: str,
    ) -> InstructionReceipt:
        return await self.repository.submit_instruction(scope, instruction_id, content)

    async def cancel_task(self, scope: CodingScope) -> TaskSnapshot:
        task = await self.repository.cancel_and_reject(scope)
        if self.execution_cleanup is not None:
            await self.execution_cleanup.cleanup_disconnect(scope, task.lease_epoch)
        return task

    async def _drive(self, scope: CodingScope) -> AsyncGenerator[CodingEvent, None]:
        task = await self._task_for_scope(scope)
        if task.state is TaskState.COMPLETED:
            async for event in self._completion_events(task):
                yield event
            return
        if task.state in {TaskState.FAILED, TaskState.CANCELLED}:
            yield self._terminal_event(task)
            return

        session = self.session_factory(self.repository, scope)
        try:
            async with session, self._disconnect_on_exit(scope, session):
                if self.execution_cleanup is not None:
                    await self.execution_cleanup.cleanup_old_epoch(scope, session.lease.epoch)
                while True:
                    session.assert_alive()
                    task = await self._task_for_scope(scope)
                    attempt = await self._current_attempt(task)
                    if task.state is TaskState.FINISHING:
                        completed = await self._coordinate_finish(task, attempt, session)
                        async for event in self._completion_events(completed):
                            yield event
                        return

                    source, task, attempt = await self._source(task, attempt, session)
                    sequence = 0
                    try:
                        async for raw_event in source:
                            session.assert_alive()
                            sequence += 1
                            event_type = self._event_type(raw_event)
                            if not self._candidate_text_event(event_type):
                                yield CodingEvent(
                                    event_id=(
                                        f"{scope.external_run_id}:{attempt.attempt_no}:{sequence}"
                                    ),
                                    type="agno_event",
                                    data={"event": event_type},
                                )
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        run_state = AgnoRunState(
                            exists=True,
                            status="ERROR",
                            terminal=True,
                            output=str(error),
                        )
                    else:
                        run_state = await self.executor.state(scope, attempt)

                    task = await self._task_for_scope(scope)
                    if task.state is TaskState.FINISHING:
                        completed = await self._coordinate_finish(task, attempt, session)
                        async for event in self._completion_events(completed):
                            yield event
                        return
                    if task.state in {TaskState.CANCELLED, TaskState.FAILED}:
                        yield self._terminal_event(task)
                        return

                    pending = await self.repository.pending_instructions(scope.external_run_id)
                    outcome = (
                        AttemptOutcome.ERROR
                        if run_state.status == "ERROR"
                        else AttemptOutcome.LOST
                        if not run_state.exists
                        else AttemptOutcome.CANCELLED
                        if run_state.status == "CANCELLED"
                        else AttemptOutcome.NO_FINISH
                    )
                    fingerprint_error = (
                        run_state.output
                        if outcome in {AttemptOutcome.ERROR, AttemptOutcome.LOST}
                        else None
                    )
                    projected = self._project_error(task, fingerprint_error)
                    decision = self.policy.decide(
                        projected,
                        attempt,
                        pending_instruction_count=len(pending),
                        checkpoint_recoverable=run_state.checkpoint_recoverable,
                    )
                    if decision.action is ContinuationAction.RESUME:
                        task, attempt = await self.run_manager.resume_current(task, session.lease)
                        continue
                    create_next = decision.action in {
                        ContinuationAction.CONTINUE,
                        ContinuationAction.APPLY_INSTRUCTIONS,
                    }
                    task = await self.run_manager.close_and_advance(
                        task,
                        session.lease,
                        outcome=outcome,
                        agno_status=run_state.status,
                        terminal_output=run_state.output,
                        error=fingerprint_error,
                        create_next=create_next,
                    )
                    if create_next:
                        continue
                    task = await self._fail_task(task, decision.code)
                    yield self._terminal_event(task, decision.code)
                    return
        except asyncio.CancelledError:
            raise
        except CodingRepositoryError as error:
            yield CodingEvent(
                event_id=f"{scope.external_run_id}:terminal",
                type="terminal",
                data={"state": "failed", "code": error.code, "message": str(error)},
            )

    @asynccontextmanager
    async def _disconnect_on_exit(self, scope: CodingScope, session: TaskSession):
        try:
            yield
        finally:
            await self._disconnect(scope, session)

    async def _source(
        self,
        task: TaskSnapshot,
        attempt: AttemptSnapshot,
        session: TaskSession,
    ) -> tuple[AsyncIterator[Any], TaskSnapshot, AttemptSnapshot]:
        run_state = await self.executor.state(task.scope, attempt)
        dependencies = {
            "AgentOS 编码任务": {
                "externalRunId": task.scope.external_run_id,
                "sandboxId": task.scope.sandbox_id,
                "leaseOwner": session.lease.owner,
                "leaseEpoch": session.lease.epoch,
                "attemptNo": attempt.attempt_no,
            }
        }
        if attempt.state is AttemptState.CREATED and not run_state.exists:
            task, attempt = await self.run_manager.open_initial(task, session.lease)
            instruction = await self.repository.attempt_instruction(
                task.scope.external_run_id, attempt.attempt_no
            )
            return (
                self.executor.arun(task.scope, attempt, instruction, dependencies=dependencies),
                task,
                attempt,
            )
        if attempt.state in {AttemptState.RUNNING, AttemptState.PAUSED}:
            if run_state.terminal:
                outcome = (
                    AttemptOutcome.ERROR
                    if run_state.status == "ERROR"
                    else AttemptOutcome.CANCELLED
                    if run_state.status == "CANCELLED"
                    else AttemptOutcome.NO_FINISH
                )
                pending = await self.repository.pending_instructions(task.scope.external_run_id)
                projected = self._project_error(
                    task, run_state.output if outcome is AttemptOutcome.ERROR else None
                )
                decision = self.policy.decide(
                    projected,
                    attempt,
                    pending_instruction_count=len(pending),
                    checkpoint_recoverable=run_state.checkpoint_recoverable,
                )
                if decision.action is ContinuationAction.RESUME:
                    task, attempt = await self.run_manager.resume_current(task, session.lease)
                    instruction = await self.repository.attempt_instruction(
                        task.scope.external_run_id, attempt.attempt_no
                    )
                    return (
                        self.executor.acontinue_run(
                            task.scope,
                            attempt,
                            instruction or None,
                            dependencies=dependencies,
                        ),
                        task,
                        attempt,
                    )
                create_next = decision.action in {
                    ContinuationAction.CONTINUE,
                    ContinuationAction.APPLY_INSTRUCTIONS,
                }
                task = await self.run_manager.close_and_advance(
                    task,
                    session.lease,
                    outcome=outcome,
                    agno_status=run_state.status,
                    terminal_output=run_state.output,
                    error=run_state.output if outcome is AttemptOutcome.ERROR else None,
                    create_next=create_next,
                )
                if not create_next:
                    task = await self._fail_task(task, decision.code)
                    raise CodingRepositoryError(decision.code, "编码任务无法继续。")
                return await self._source(task, await self._current_attempt(task), session)
            if not run_state.exists:
                pending = await self.repository.pending_instructions(task.scope.external_run_id)
                projected = self._project_error(task, "agno_run_lost")
                decision = self.policy.decide(
                    projected,
                    attempt,
                    pending_instruction_count=len(pending),
                )
                create_next = decision.action in {
                    ContinuationAction.CONTINUE,
                    ContinuationAction.APPLY_INSTRUCTIONS,
                }
                task = await self.run_manager.close_and_advance(
                    task,
                    session.lease,
                    outcome=AttemptOutcome.LOST,
                    agno_status="lost",
                    error="agno_run_lost",
                    create_next=create_next,
                )
                if not create_next:
                    task = await self._fail_task(task, decision.code)
                    raise CodingRepositoryError(decision.code, "编码任务无法继续。")
                return await self._source(task, await self._current_attempt(task), session)
            task, attempt = await self.run_manager.resume_current(task, session.lease)
            instruction = await self.repository.attempt_instruction(
                task.scope.external_run_id, attempt.attempt_no
            )
            return (
                self.executor.acontinue_run(
                    task.scope, attempt, instruction or None, dependencies=dependencies
                ),
                task,
                attempt,
            )
        raise CodingRepositoryError("attempt_not_runnable", "当前 Attempt 不可运行。")

    async def _coordinate_finish(
        self, task: TaskSnapshot, attempt: AttemptSnapshot, session: TaskSession
    ) -> TaskSnapshot:
        run_state = await self.executor.state(task.scope, attempt)
        if run_state.exists and not run_state.terminal and run_state.checkpoint_recoverable:
            raise CodingRepositoryError(
                "finish_waiting_for_agno", "完成回执已保存，正在等待 Agno run 终态。"
            )
        return await self.repository.finalize_finish(
            task.scope.external_run_id,
            session.lease,
            task.state_version,
            agno_status=run_state.status or "lost",
        )

    async def _disconnect(self, scope: CodingScope, session: TaskSession) -> None:
        task = await self.repository.get_task_snapshot(scope.external_run_id)
        if task is None or task.state in {
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }:
            return
        if self.execution_cleanup is not None:
            await self.execution_cleanup.cleanup_disconnect(scope, session.lease.epoch)
        try:
            await self.repository.pause_and_release(
                scope.external_run_id, session.lease, task.state_version
            )
        except CodingRepositoryError:
            pass

    async def _task_for_scope(self, scope: CodingScope) -> TaskSnapshot:
        task = await self.repository.get_task_snapshot(scope.external_run_id)
        if task is None:
            raise CodingRepositoryError("task_not_found", "编码任务不存在。")
        if task.scope != scope:
            raise CodingRepositoryError("task_scope_mismatch", "编码任务范围不匹配。")
        return task

    async def _current_attempt(self, task: TaskSnapshot) -> AttemptSnapshot:
        attempt = await self.repository.get_attempt(task.current_internal_run_id)
        if attempt is None or attempt.attempt_no != task.current_attempt_no:
            raise CodingRepositoryError("attempt_not_found", "当前 Attempt 不存在。")
        return attempt

    async def _fail_task(self, task: TaskSnapshot, code: str) -> TaskSnapshot:
        return await self.repository.fail_closed_task(
            task.scope.external_run_id, task.state_version, code
        )

    async def _completion_events(self, task: TaskSnapshot) -> AsyncIterator[CodingEvent]:
        receipt = task.finish_receipt or {}
        yield CodingEvent(
            event_id=f"{task.scope.external_run_id}:final",
            type="final_message",
            data={"content": str(receipt.get("summary") or task.result_text or "任务已完成。")},
        )
        yield self._terminal_event(task)

    @staticmethod
    def _terminal_event(task: TaskSnapshot, code: str | None = None) -> CodingEvent:
        return CodingEvent(
            event_id=f"{task.scope.external_run_id}:terminal",
            type="terminal",
            data={"state": task.state.value, **({"code": code} if code else {})},
        )

    @staticmethod
    def _event_type(event: Any) -> str:
        value = getattr(event, "event", None) or getattr(event, "type", None)
        return str(getattr(value, "value", value) or type(event).__name__)

    @staticmethod
    def _candidate_text_event(event_type: str) -> bool:
        normalized = event_type.lower()
        return "content" in normalized or "message" in normalized or "response" in normalized

    @staticmethod
    def _project_error(task: TaskSnapshot, error: str | None) -> TaskSnapshot:
        if error is None:
            return task
        from dataclasses import replace

        from .repository import error_fingerprint

        fingerprint = error_fingerprint(error)
        count = task.same_error_count + 1 if task.error_fingerprint == fingerprint else 1
        return replace(task, same_error_count=count, error_fingerprint=fingerprint)
