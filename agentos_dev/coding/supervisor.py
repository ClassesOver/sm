from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol

from .executor import AgnoCodingExecutor, AgnoRunState, provider_error_suspend_code
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

MAX_TOOL_EVENT_ARGUMENT_CHARS = 600
MAX_TOOL_ARGUMENT_VALUE_CHARS = 240
_SENSITIVE_ARGUMENT_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "passwd",
    "password",
    "secret",
    "token",
)
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization)"
    r"(\s*[=:]\s*|\s+)([^\s,;&]+)"
)
_URL_CREDENTIAL_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^:/\s]+:)[^@\s]+(@)")


class ExecutionCleanup(Protocol):
    async def cleanup_old_epoch(self, scope: CodingScope, current_epoch: int) -> None: ...

    async def cleanup_disconnect(self, scope: CodingScope, current_epoch: int) -> None: ...


class AcceptanceValidatorRegistry(Protocol):
    def validate_contract(self, contract: Any) -> dict[str, Any]: ...


class _TaskSuspended(Exception):
    def __init__(self, code: str):
        self.code = code


class CodingTaskSupervisor:
    def __init__(
        self,
        repository: CodingTaskRepository,
        executor: AgnoCodingExecutor,
        *,
        policy: ContinuationPolicy | None = None,
        run_manager: InternalRunManager | None = None,
        execution_cleanup: ExecutionCleanup | None = None,
        validator_registry: AcceptanceValidatorRegistry | None = None,
        session_factory: Callable[[CodingTaskRepository, CodingScope], TaskSession] = TaskSession,
    ):
        self.repository = repository
        self.executor = executor
        self.policy = policy or ContinuationPolicy()
        self.run_manager = run_manager or InternalRunManager(repository)
        self.execution_cleanup = execution_cleanup
        self.validator_registry = validator_registry
        self.session_factory = session_factory

    async def start_task(
        self,
        scope: CodingScope,
        initial_instruction: str,
        predecessor_task_id: str | None = None,
        *,
        acceptance_contract: dict[str, Any] | None = None,
    ) -> TaskSnapshot:
        normalized_contract = None
        if acceptance_contract is not None:
            if self.validator_registry is None:
                raise CodingRepositoryError(
                    "acceptance_validator_unavailable",
                    "编码任务验收契约没有可用的服务端 validator registry。",
                )
            try:
                normalized_contract = self.validator_registry.validate_contract(acceptance_contract)
            except ValueError as error:
                raise CodingRepositoryError("acceptance_contract_invalid", str(error)) from error
        return await self.repository.create_task_with_initial_attempt(
            scope,
            initial_instruction,
            predecessor_task_id,
            acceptance_contract=normalized_contract,
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

    async def revise_task(
        self,
        scope: CodingScope,
        instruction_id: str,
        content: str,
        *,
        acceptance_contract: dict[str, Any] | None = None,
    ) -> TaskSnapshot:
        normalized_contract = None
        if acceptance_contract is not None:
            if self.validator_registry is None:
                raise CodingRepositoryError(
                    "acceptance_validator_unavailable",
                    "编码任务验收契约没有可用的服务端 validator registry。",
                )
            try:
                normalized_contract = self.validator_registry.validate_contract(acceptance_contract)
            except ValueError as error:
                raise CodingRepositoryError("acceptance_contract_invalid", str(error)) from error
        return await self.repository.revise_completed_task(
            scope,
            instruction_id,
            content,
            acceptance_contract=normalized_contract,
        )

    async def cancel_task(self, scope: CodingScope) -> TaskSnapshot:
        task = await self.repository.cancel_and_reject(scope)
        if self.execution_cleanup is not None:
            await self.execution_cleanup.cleanup_disconnect(scope, task.lease_epoch)
            await self._cleanup_task_outputs(scope)
        return task

    async def _drive(self, scope: CodingScope) -> AsyncGenerator[CodingEvent, None]:
        task = await self._task_for_scope(scope)
        if task.state is TaskState.COMPLETED:
            async for event in self._completion_events(task):
                yield event
            return
        if task.state in {TaskState.FAILED, TaskState.CANCELLED}:
            await self._cleanup_task_outputs(scope)
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
                    reasoning_open = False
                    try:
                        async for raw_event in source:
                            session.assert_alive()
                            sequence += 1
                            event_type = self._event_type(raw_event)
                            event_id = f"{scope.external_run_id}:{attempt.attempt_no}:{sequence}"
                            native_reasoning = self._native_reasoning_content(raw_event, event_type)
                            if native_reasoning is not None:
                                if not reasoning_open:
                                    yield CodingEvent(
                                        event_id=f"{event_id}:reasoning-started",
                                        type="agno_event",
                                        data={"event": "ReasoningStarted"},
                                    )
                                    reasoning_open = True
                                yield CodingEvent(
                                    event_id=f"{event_id}:reasoning-delta",
                                    type="agno_event",
                                    data={
                                        "event": "ReasoningContentDelta",
                                        "reasoning_content": native_reasoning,
                                    },
                                )
                                continue
                            if reasoning_open and not self._reasoning_event(event_type):
                                yield CodingEvent(
                                    event_id=f"{event_id}:reasoning-completed",
                                    type="agno_event",
                                    data={"event": "ReasoningCompleted"},
                                )
                                reasoning_open = False
                            if self._candidate_text_event(event_type) and not self._reasoning_event(
                                event_type
                            ):
                                continue
                            data = self._agno_event_data(
                                raw_event,
                                event_type,
                                call_id_prefix=(
                                    f"{scope.external_run_id}:{attempt.attempt_no}:internal"
                                ),
                            )
                            if data is None:
                                continue
                            normalized_event_type = event_type.lower()
                            if normalized_event_type == "reasoningstarted":
                                reasoning_open = True
                            elif normalized_event_type == "reasoningcompleted":
                                reasoning_open = False
                            yield CodingEvent(
                                event_id=event_id,
                                type="agno_event",
                                data=data,
                            )
                        if reasoning_open:
                            yield CodingEvent(
                                event_id=(
                                    f"{scope.external_run_id}:{attempt.attempt_no}:"
                                    f"{sequence + 1}:reasoning-completed"
                                ),
                                type="agno_event",
                                data={"event": "ReasoningCompleted"},
                            )
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        run_state = AgnoRunState(
                            exists=True,
                            status="ERROR",
                            terminal=True,
                            output=str(error),
                            suspend_code=provider_error_suspend_code(error),
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
                        suspend_code=run_state.suspend_code,
                    )
                    if decision.action is ContinuationAction.SUSPEND:
                        task = await self._pause_task(task, session, run_state.status)
                        yield self._suspended_event(task, decision.code)
                        return
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
        except _TaskSuspended as suspended:
            task = await self._task_for_scope(scope)
            yield self._suspended_event(task, suspended.code)
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
                "threadId": task.scope.thread_id,
                "sandboxId": task.scope.sandbox_id,
                "leaseOwner": session.lease.owner,
                "leaseEpoch": session.lease.epoch,
                "attemptNo": attempt.attempt_no,
            }
        }
        if attempt.state is AttemptState.CREATED and not run_state.exists:
            task, attempt = await self.run_manager.open_initial(task, session.lease)
            instruction = await self._attempt_instruction(task, attempt)
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
                    suspend_code=run_state.suspend_code,
                )
                if decision.action is ContinuationAction.SUSPEND:
                    await self._pause_task(task, session, run_state.status)
                    raise _TaskSuspended(decision.code)
                if decision.action is ContinuationAction.RESUME:
                    task, attempt = await self.run_manager.resume_current(task, session.lease)
                    instruction = await self._attempt_instruction(task, attempt)
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
            instruction = await self._attempt_instruction(task, attempt)
            return (
                self.executor.acontinue_run(
                    task.scope, attempt, instruction or None, dependencies=dependencies
                ),
                task,
                attempt,
            )
        raise CodingRepositoryError("attempt_not_runnable", "当前 Attempt 不可运行。")

    async def _attempt_instruction(self, task: TaskSnapshot, attempt: AttemptSnapshot) -> str:
        instruction = await self.repository.attempt_instruction(
            task.scope.external_run_id, attempt.attempt_no
        )
        if attempt.attempt_no == 0:
            return instruction
        previous_run_id = self.repository.internal_run_id(
            task.scope.external_run_id, attempt.attempt_no - 1
        )
        source_attempt = await self.repository.get_attempt(previous_run_id)
        if source_attempt is None or source_attempt.outcome is not AttemptOutcome.NO_FINISH:
            return instruction
        source_run_state = await self.executor.state(task.scope, source_attempt)
        feedback = await self._runtime_feedback(task, source_attempt, source_run_state)
        return f"{instruction}\n\n{feedback}" if feedback else instruction

    async def _runtime_feedback(
        self,
        task: TaskSnapshot,
        source_attempt: AttemptSnapshot,
        source_run_state: AgnoRunState,
    ) -> str:
        executions = await self.repository.list_executions(task.scope.external_run_id)
        current_verifications = [
            execution
            for execution in executions
            if execution.is_verification and execution.mutation_sequence == task.mutation_sequence
        ]
        latest_verification = current_verifications[-1] if current_verifications else None
        latest_succeeded = bool(
            latest_verification is not None
            and latest_verification.status == "completed"
            and latest_verification.exit_code == 0
            and (latest_verification.operation_receipt or {}).get("valid", True) is not False
        )
        successful = latest_verification if latest_succeeded else None
        failed = (
            latest_verification
            if latest_verification is not None and not latest_succeeded
            else None
        )
        finish_failure = source_run_state.finish_failure
        finish_failure_details = (
            finish_failure.get("details") if isinstance(finish_failure, dict) else None
        )
        current_finish_failure = bool(
            isinstance(finish_failure_details, dict)
            and finish_failure_details.get("mutationSequence") == task.mutation_sequence
        )
        if current_finish_failure and isinstance(finish_failure, dict):
            code = str(finish_failure.get("code") or "finish_rejected")
            required_actions = list(finish_failure.get("requiredActions") or [])[:10]
            failed_items = [{"code": code, "details": finish_failure_details}]
        elif failed is not None:
            receipt = failed.operation_receipt or {}
            code = str(receipt.get("failure_code") or "coding_verification_failed")
            required_actions = ["仅修复失败验证项，并在当前 mutation 上重新运行验证。"]
            failed_items = [{"executionId": failed.execution_id, "code": code}]
        elif successful is not None:
            code = "coding_finish_required"
            required_actions = ["当前 mutation 已验证；调用 finish_task 提交完成回执。"]
            failed_items = []
        elif task.mutation_sequence > 0:
            code = "coding_verification_required"
            required_actions = ["在当前 mutation 上执行与改动范围匹配的验证。"]
            failed_items = []
        else:
            code = "coding_runtime_action_required"
            required_actions = ["继续完成初始任务；完成后验证并调用 finish_task。"]
            failed_items = []
        failed_items_fingerprint = hashlib.sha256(
            json.dumps(
                failed_items, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode()
        ).hexdigest()
        fingerprint_source = (
            f"{source_attempt.internal_run_id}:{code}:{task.mutation_sequence}:"
            f"{failed_items_fingerprint}"
        )
        payload = {
            "marker": "CODING_RUNTIME_FEEDBACK",
            "version": 1,
            "code": code,
            "sourceAttempt": source_attempt.attempt_no,
            "fingerprint": hashlib.sha256(fingerprint_source.encode()).hexdigest(),
            "mutation": task.mutation_sequence,
            "failedItems": failed_items,
            "passedItems": (
                [{"executionId": successful.execution_id}] if successful is not None else []
            ),
            "requiredActions": required_actions,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    async def _coordinate_finish(
        self, task: TaskSnapshot, attempt: AttemptSnapshot, session: TaskSession
    ) -> TaskSnapshot:
        run_state = await self.executor.state(task.scope, attempt)
        if run_state.exists and not run_state.terminal and run_state.checkpoint_recoverable:
            raise CodingRepositoryError(
                "finish_waiting_for_agno", "完成回执已保存，正在等待 Agno run 终态。"
            )
        completed = await self.repository.finalize_finish(
            task.scope.external_run_id,
            session.lease,
            task.state_version,
            agno_status=run_state.status or "lost",
        )
        await self._cleanup_task_outputs(task.scope)
        return completed

    async def _disconnect(self, scope: CodingScope, session: TaskSession) -> None:
        task = await self.repository.get_task_snapshot(scope.external_run_id)
        if task is None or task.state in {
            TaskState.SUSPENDED,
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

    async def _pause_task(
        self, task: TaskSnapshot, session: TaskSession, agno_status: str | None
    ) -> TaskSnapshot:
        if self.execution_cleanup is not None:
            await self.execution_cleanup.cleanup_disconnect(task.scope, session.lease.epoch)
        return await self.repository.pause_and_release(
            task.scope.external_run_id,
            session.lease,
            task.state_version,
            agno_status=agno_status,
        )

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
        failed = await self.repository.fail_closed_task(
            task.scope.external_run_id, task.state_version, code
        )
        await self._cleanup_task_outputs(task.scope)
        return failed

    async def _cleanup_task_outputs(self, scope: CodingScope) -> None:
        cleanup = getattr(self.execution_cleanup, "cleanup_task_outputs", None)
        if callable(cleanup):
            await cleanup(scope)

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
    def _suspended_event(task: TaskSnapshot, code: str) -> CodingEvent:
        return CodingEvent(
            event_id=f"{task.scope.external_run_id}:suspended:{task.state_version}",
            type="suspended",
            data={"state": TaskState.SUSPENDED.value, "code": code},
        )

    @staticmethod
    def _event_type(event: Any) -> str:
        value = getattr(event, "event", None) or getattr(event, "type", None)
        return str(getattr(value, "value", value) or type(event).__name__)

    @classmethod
    def _agno_event_data(
        cls, event: Any, event_type: str, *, call_id_prefix: str
    ) -> dict[str, Any] | None:
        data: dict[str, Any] = {"event": event_type}
        if event_type.lower() == "reasoningcontentdelta":
            reasoning_content = getattr(event, "reasoning_content", None)
            if not isinstance(reasoning_content, str) or not reasoning_content:
                return None
            data["reasoning_content"] = reasoning_content
            return data
        if cls._reasoning_event(event_type):
            return data
        phase = {
            "toolcallstarted": "started",
            "toolcallcompleted": "completed",
            "toolcallerror": "error",
        }.get(event_type.lower())
        tool = getattr(event, "tool", None)
        tool_name = getattr(tool, "tool_name", None)
        if phase is None or not isinstance(tool_name, str) or not tool_name:
            return data
        if phase == "completed" and bool(getattr(tool, "tool_call_error", False)):
            phase = "error"
        raw_call_id = str(getattr(tool, "tool_call_id", "") or tool_name)
        data.update(
            {
                "phase": phase,
                "tool": tool_name,
                "call_id": f"{call_id_prefix}:{raw_call_id}",
            }
        )
        if phase == "started":
            arguments = cls._safe_tool_arguments(getattr(tool, "tool_args", None))
            if arguments:
                data["arguments"] = arguments
        duration = getattr(getattr(tool, "metrics", None), "duration", None)
        if isinstance(duration, int | float) and duration >= 0:
            data["duration_seconds"] = round(float(duration), 2)
        return data

    @classmethod
    def _safe_tool_arguments(cls, arguments: Any) -> str:
        if not isinstance(arguments, dict) or not arguments:
            return ""
        safe = {
            str(key): cls._safe_argument_value(str(key), value) for key, value in arguments.items()
        }
        rendered = json.dumps(safe, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(rendered) <= MAX_TOOL_EVENT_ARGUMENT_CHARS:
            return rendered
        return rendered[: MAX_TOOL_EVENT_ARGUMENT_CHARS - 3] + "..."

    @classmethod
    def _safe_argument_value(cls, key: str, value: Any) -> Any:
        normalized_key = key.lower().replace("-", "_")
        if any(marker in normalized_key for marker in _SENSITIVE_ARGUMENT_MARKERS):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {
                str(child_key): cls._safe_argument_value(str(child_key), child_value)
                for child_key, child_value in list(value.items())[:20]
            }
        if isinstance(value, list | tuple):
            return [cls._safe_argument_value(key, item) for item in value[:20]]
        if isinstance(value, str):
            redacted = _SENSITIVE_VALUE_RE.sub(r"\1\2[REDACTED]", value)
            redacted = _URL_CREDENTIAL_RE.sub(r"\1[REDACTED]\2", redacted)
            if len(redacted) > MAX_TOOL_ARGUMENT_VALUE_CHARS:
                return redacted[: MAX_TOOL_ARGUMENT_VALUE_CHARS - 3] + "..."
            return redacted
        if value is None or isinstance(value, bool | int | float):
            return value
        return str(value)[:MAX_TOOL_ARGUMENT_VALUE_CHARS]

    @staticmethod
    def _candidate_text_event(event_type: str) -> bool:
        normalized = event_type.lower()
        return "content" in normalized or "message" in normalized or "response" in normalized

    @staticmethod
    def _native_reasoning_content(event: Any, event_type: str) -> str | None:
        if event_type.lower() != "runcontent":
            return None
        reasoning_content = getattr(event, "reasoning_content", None)
        if isinstance(reasoning_content, str) and reasoning_content:
            return reasoning_content
        return None

    @staticmethod
    def _reasoning_event(event_type: str) -> bool:
        return event_type.lower() in {
            "reasoningstarted",
            "reasoningcontentdelta",
            "reasoningcompleted",
        }

    @staticmethod
    def _project_error(task: TaskSnapshot, error: str | None) -> TaskSnapshot:
        if error is None:
            return task
        from dataclasses import replace

        from .repository import error_fingerprint

        fingerprint = error_fingerprint(error)
        count = task.same_error_count + 1 if task.error_fingerprint == fingerprint else 1
        return replace(task, same_error_count=count, error_fingerprint=fingerprint)
