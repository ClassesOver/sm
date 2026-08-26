from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from agno.run import RunContext
from agno.run.base import RunStatus
from agno.tools import Toolkit, tool
from agno.workflow import OnReject
from pydantic import BaseModel

from ..contract import (
    REPORT_WORKFLOW_SCOPE_STATE_KEY,
    ReportingWorkflowInput,
    ReportRequestEnvelope,
    parse_reporting_workflow_input,
)
from ..models import (
    ReportingError,
    ReportReviewSnapshot,
    ReportWorkflowControl,
)
from .state import ReportingStateError

REPORT_WORKFLOW_CONTROL_STATE_KEY = "report_workflow_control"
REPORT_WORKFLOW_SCOPE_DEPENDENCY = "AgentOS 报表工作流"
_WORKFLOW_ID = "enterprise-reporting-workflow-v1"
_ACTIVE_STATUSES = frozenset({"running", "paused"})
_THREAD_CLAIM_WAIT_SECONDS = 2.0
_THREAD_CLAIM_RETRY_DELAY_SECONDS = 0.1
ReportWorkflowStatus = Literal["running", "paused", "completed", "cancelled", "failed"]
ReviewStage = Literal["request", "outline"]


def reporting_workflow_ids(
    *, user_id: str, thread_id: str, external_run_id: str
) -> tuple[str, str]:
    session_digest = hashlib.sha256(f"{user_id}:{thread_id}".encode()).hexdigest()[:32]
    run_digest = hashlib.sha256(f"{user_id}:{thread_id}:{external_run_id}".encode()).hexdigest()[
        :32
    ]
    return f"report-session-{session_digest}", f"report-run-{run_digest}"


class ReviewableWorkflow(Protocol):
    id: str | None

    async def arun(self, *args: Any, **kwargs: Any) -> Any: ...

    async def aget_run(self, run_id: str, session_id: str | None = None) -> Any: ...

    async def acontinue_run(self, *args: Any, **kwargs: Any) -> Any: ...

    async def acancel_run(self, run_id: str) -> bool: ...


class WorkflowThreadOwnership(Protocol):
    async def claim_workflow_thread(
        self, *, thread_id: str, external_run_id: str, owner_user_id: str
    ) -> bool: ...

    async def ensure_workflow_thread_owner(
        self, *, thread_id: str, external_run_id: str, owner_user_id: str
    ) -> bool: ...

    async def release_workflow_thread(
        self, *, thread_id: str, external_run_id: str, owner_user_id: str
    ) -> bool: ...

    def workflow_execution_lock(self, external_run_id: str) -> Any: ...

    async def get_workflow_thread_owner(self, thread_id: str) -> dict[str, Any] | None: ...

    async def is_workflow_run_active(self, external_run_id: str) -> bool: ...


WorkflowFactory = Callable[[], ReviewableWorkflow]
TerminalCleanup = Callable[[dict[str, str], str, str], Awaitable[None]]


class ReportWorkflowController:
    """在 Agent 工具边界内启动和恢复 Agno Workflow。"""

    def __init__(
        self,
        workflow_factory: WorkflowFactory,
        *,
        thread_ownership: WorkflowThreadOwnership,
        terminal_cleanup: TerminalCleanup | None = None,
    ):
        self._workflow_factory = workflow_factory
        self._thread_ownership = thread_ownership
        self._terminal_cleanup = terminal_cleanup

    async def start(
        self,
        workflow_input: ReportingWorkflowInput | ReportRequestEnvelope | dict[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        scope = self._scope(run_context)
        async with self._execution_lock(scope["external_run_id"]):
            return await self._start_unlocked(workflow_input, run_context)

    async def _start_unlocked(
        self,
        workflow_input: ReportingWorkflowInput | ReportRequestEnvelope | dict[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        request = (
            workflow_input
            if isinstance(workflow_input, ReportingWorkflowInput)
            else ReportingWorkflowInput.model_validate(
                workflow_input.model_dump(mode="json", by_alias=True, exclude_none=True)
                if isinstance(workflow_input, ReportRequestEnvelope)
                else workflow_input
            )
        )
        scope = self._scope(run_context)
        state = self._state(run_context)
        assert run_context is not None
        existing = self._control(state, required=False)
        if existing is not None and existing.finalization_pending:
            existing_scope = self._scope(run_context, external_run_id=existing.external_run_id)
            self._assert_scope(existing, existing_scope)
            await self._ensure_thread_owner(existing_scope)
            await self._cleanup_terminal(
                existing_scope, existing.workflow_session_id, existing.workflow_run_id
            )
            finalized = existing.model_copy(update={"finalization_pending": None})
            await self._release_thread(existing_scope)
            state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = finalized.public_dict()
            return self._result(finalized, None)
        if existing is not None and existing.status in _ACTIVE_STATUSES:
            existing_scope = self._scope(run_context, external_run_id=existing.external_run_id)
            self._assert_scope(existing, existing_scope)
            await self._ensure_thread_owner(existing_scope)
            output = await self._load(existing)
            current = self._control_from_output(
                output,
                existing_scope,
                existing.workflow_session_id,
                existing.workflow_run_id,
            )
            state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = current.public_dict()
            if current.status in _ACTIVE_STATUSES:
                return self._result(current, output)
            await self._finalize_control(current, existing_scope, state=state)

        workflow = self._workflow()
        workflow_session_id, workflow_run_id = self._workflow_ids(scope)
        payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
        persisted_output = await self._load_run_output(
            workflow, workflow_run_id, workflow_session_id
        )
        if persisted_output is not None:
            control = self._control_from_output(
                persisted_output, scope, workflow_session_id, workflow_run_id
            )
            if control.status == "running":
                # arun 是同步等待的；拿到执行锁后仍读到 running，只能是进程崩溃或
                # 旧版本留下的半成品。继续返回 running 会让同一个请求永久卡住，必须
                # 在当前 owner 身份一致时清理后按确定性 run_id 重新执行。
                owner = await self._get_thread_owner(scope["thread_id"])
                owner_matches = owner is None or (
                    str(owner.get("external_run_id")) == scope["external_run_id"]
                    and str(owner.get("owner_user_id")) == scope["user_id"]
                )
                if owner_matches:
                    await self._cleanup_terminal(scope, workflow_session_id, workflow_run_id)
                    await self._release_thread(scope)
                    persisted_output = None
                else:
                    # 另一个 run 占用同一 thread 时，不能清理其 sandbox；交给下面的
                    # thread claim 路径返回明确冲突。
                    persisted_output = None
            if persisted_output is not None:
                if control.status in _ACTIVE_STATUSES:
                    await self._ensure_thread_owner(scope)
                else:
                    await self._finalize_control(control, scope, state=state)
                state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = control.public_dict()
                return self._result(control, persisted_output)
        owned_output = await self._claim_thread_with_recovery(scope)
        if owned_output is not None:
            control = self._control_from_output(
                owned_output, scope, workflow_session_id, workflow_run_id
            )
            state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = control.public_dict()
            if control.status not in _ACTIVE_STATUSES:
                await self._finalize_control(control, scope, state=state)
                state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = control.public_dict()
            return self._result(control, owned_output)
        try:
            output = await workflow.arun(
                payload,
                run_id=workflow_run_id,
                session_id=workflow_session_id,
                user_id=scope["user_id"],
                session_state={
                    REPORT_WORKFLOW_SCOPE_STATE_KEY: self._workflow_dependencies(scope)[
                        REPORT_WORKFLOW_SCOPE_DEPENDENCY
                    ]
                },
                dependencies=self._workflow_dependencies(scope),
                stream=False,
            )
            control = self._control_from_output(output, scope, workflow_session_id, workflow_run_id)
        except BaseException as run_error:
            try:
                await self._cleanup_terminal(scope, workflow_session_id, workflow_run_id)
                await self._release_thread(scope)
            except BaseException as finalization_error:
                # arun 尚未返回时 Agno 没有可投影的 RunResponse，但持久化 owner 已经
                # 占用成功。补偿失败必须写入最小失败控制面，后续调用才能重试清理并
                # 释放同一 owner；同时继续抛出原始运行异常，避免清理故障遮蔽主失败。
                state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = ReportWorkflowControl(
                    workflowId=_WORKFLOW_ID,
                    workflowRunId=workflow_run_id,
                    workflowSessionId=workflow_session_id,
                    externalRunId=scope["external_run_id"],
                    threadId=scope["thread_id"],
                    userId=scope["user_id"],
                    status="failed",
                    finalizationPending=True,
                ).public_dict()
                raise run_error from finalization_error
            raise
        await self._finalize_control(control, scope, state=state)
        state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = control.public_dict()
        return self._result(control, output)

    async def approve(self, run_context: RunContext | None) -> dict[str, Any]:
        return await self._continue(run_context, approve=True)

    async def reject(self, feedback: str, run_context: RunContext | None) -> dict[str, Any]:
        normalized = str(feedback or "").strip()
        if not normalized or len(normalized) > 4000:
            raise ReportingError(
                "review_feedback_invalid", "拒绝时必须提供 1 至 4000 个字符的意见。"
            )
        return await self._continue(run_context, approve=False, feedback=normalized)

    async def cancel(self, run_context: RunContext | None) -> dict[str, Any]:
        state = self._state(run_context)
        control = self._control(state)
        assert control is not None
        scope = self._scope(run_context, external_run_id=control.external_run_id)
        self._assert_scope(control, scope)
        async with self._execution_lock(control.external_run_id):
            await self._ensure_thread_owner(scope)
            output = await self._load(control)
            status = self._status(getattr(output, "status", None))
            workflow = self._workflow()
            if status == "paused":
                requirement = self._active_requirement(output)
                requirement.on_reject = OnReject.cancel
                requirement.reject(feedback="用户取消报表工作流。")
                output = await workflow.acontinue_run(
                    run_response=output,
                    step_requirements=list(getattr(output, "step_requirements", None) or []),
                    dependencies=self._workflow_dependencies(scope),
                    stream=False,
                )
            elif status == "running":
                await workflow.acancel_run(control.workflow_run_id)
                output = await workflow.aget_run(
                    control.workflow_run_id, session_id=control.workflow_session_id
                )
            updated = self._control_from_output(
                output,
                scope,
                control.workflow_session_id,
                control.workflow_run_id,
            )
            if updated.status in _ACTIVE_STATUSES:
                raise ReportingError("report_workflow_cancel_failed", "报表工作流未进入取消终态。")
            await self._finalize_control(updated, scope, state=state)
            state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = updated.public_dict()
            return self._result(updated, output)

    async def _continue(
        self,
        run_context: RunContext | None,
        *,
        approve: bool,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        state = self._state(run_context)
        control = self._control(state)
        assert control is not None
        scope = self._scope(run_context, external_run_id=control.external_run_id)
        self._assert_scope(control, scope)
        if approve and control.review is not None and control.review.stage == "request":
            raise ReportingError(
                "report_request_clarification_required",
                "当前审核项必须补充报表分析期间。",
            )
        async with self._execution_lock(control.external_run_id):
            output = await self._load(control)
            if self._status(getattr(output, "status", None)) != "paused":
                raise ReportingError("report_workflow_not_paused", "报表工作流当前不等待审核。")
            # ensure 会在服务重启后补写持久化所有权，必须先以 Agno 存储的真实状态确认
            # Workflow 仍在暂停；否则终态 run 的重复审批会重新占用 thread 且没有释放路径。
            await self._ensure_thread_owner(scope)
            requirement = self._active_requirement(output)
            if approve:
                requirement.confirm()
            else:
                requirement.reject(feedback=feedback)
            workflow = self._workflow()
            output = await workflow.acontinue_run(
                run_response=output,
                step_requirements=list(getattr(output, "step_requirements", None) or []),
                dependencies=self._workflow_dependencies(scope),
                stream=False,
            )
            updated = self._control_from_output(
                output,
                scope,
                control.workflow_session_id,
                control.workflow_run_id,
            )
            await self._finalize_control(updated, scope, state=state)
            state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = updated.public_dict()
            return self._result(updated, output)

    async def _load(self, control: ReportWorkflowControl) -> Any:
        output = await self._load_run_output(
            self._workflow(), control.workflow_run_id, control.workflow_session_id
        )
        if output is None:
            raise ReportingError("report_workflow_not_found", "报表工作流不存在或已经失效。")
        stored_user = getattr(output, "user_id", None)
        if stored_user is not None and str(stored_user) != control.user_id:
            raise ReportingError("report_workflow_scope_mismatch", "报表工作流不属于当前用户。")
        return output

    @staticmethod
    async def _load_run_output(workflow: Any, run_id: str, session_id: str) -> Any:
        getter = getattr(workflow, "aget_run", None)
        if not callable(getter):
            return None
        return await getter(run_id, session_id=session_id)

    async def _finalize_control(
        self,
        control: ReportWorkflowControl,
        scope: dict[str, str],
        *,
        state: dict[str, Any] | None = None,
    ) -> None:
        if control.status in _ACTIVE_STATUSES:
            return
        # completed 的发布步骤已经在产物持久化后删除 sandbox；这里只覆盖没有发布
        # 收尾机会的取消和失败终态，避免成功路径二次清理反而遮蔽下载回执。
        if control.status in {"cancelled", "failed"}:
            pending = control.model_copy(update={"finalization_pending": True})
            if state is not None:
                state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = pending.public_dict()
            try:
                await self._cleanup_terminal(
                    scope, control.workflow_session_id, control.workflow_run_id
                )
            except BaseException:
                raise
        await self._release_thread(scope)

    async def _cleanup_terminal(
        self, scope: dict[str, str], workflow_session_id: str, workflow_run_id: str
    ) -> None:
        if self._terminal_cleanup is not None:
            await self._terminal_cleanup(scope, workflow_session_id, workflow_run_id)

    def _workflow(self) -> ReviewableWorkflow:
        workflow = self._workflow_factory()
        if workflow is None or str(getattr(workflow, "id", "") or "") != _WORKFLOW_ID:
            raise ReportingError("report_workflow_unavailable", "报表工作流配置不可用。")
        return workflow

    @staticmethod
    def _state(run_context: RunContext | None) -> dict[str, Any]:
        if run_context is None:
            raise ReportingError("report_workflow_context_missing", "报表工作流缺少运行上下文。")
        if run_context.session_state is None:
            run_context.session_state = {}
        if not isinstance(run_context.session_state, dict):
            raise ReportingError("report_workflow_state_invalid", "报表工作流状态无效。")
        return run_context.session_state

    @staticmethod
    def _scope(
        run_context: RunContext | None, *, external_run_id: str | None = None
    ) -> dict[str, str]:
        if run_context is None:
            raise ReportingError("report_workflow_context_missing", "报表工作流缺少运行上下文。")
        dependency = (run_context.dependencies or {}).get(REPORT_WORKFLOW_SCOPE_DEPENDENCY)
        resolved_external_run_id = (
            external_run_id
            or (dependency.get("externalRunId") if isinstance(dependency, dict) else None)
            or run_context.run_id
        )
        values = {
            "external_run_id": str(resolved_external_run_id or ""),
            "thread_id": str(run_context.session_id or ""),
            "user_id": str(run_context.user_id or ""),
        }
        if any(not value or len(value) > 256 for value in values.values()):
            raise ReportingError("report_workflow_context_missing", "报表工作流作用域不完整。")
        return values

    @staticmethod
    def _workflow_ids(scope: dict[str, str]) -> tuple[str, str]:
        return reporting_workflow_ids(
            user_id=scope["user_id"],
            thread_id=scope["thread_id"],
            external_run_id=scope["external_run_id"],
        )

    @staticmethod
    def _workflow_dependencies(scope: dict[str, str]) -> dict[str, dict[str, str]]:
        return {
            REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                "externalRunId": scope["external_run_id"],
                "threadId": scope["thread_id"],
                "userId": scope["user_id"],
            }
        }

    @staticmethod
    def _thread_scope_key(scope: dict[str, str]) -> str:
        return scope["thread_id"]

    async def _claim_thread_with_recovery(self, scope: dict[str, str]) -> Any:
        """占用 thread；冲突时恢复同 run、回收终态 owner，或短暂等待前序 run。"""

        deadline = asyncio.get_running_loop().time() + _THREAD_CLAIM_WAIT_SECONDS
        while True:
            if await self._thread_ownership.claim_workflow_thread(
                thread_id=self._thread_scope_key(scope),
                external_run_id=scope["external_run_id"],
                owner_user_id=scope["user_id"],
            ):
                return None
            owner = await self._get_thread_owner(scope["thread_id"])
            if owner is not None:
                output = await self._load_owner_output(owner)
                same_run = (
                    owner["external_run_id"],
                    owner["owner_user_id"],
                ) == (scope["external_run_id"], scope["user_id"])
                if same_run and output is not None:
                    return output
                if await self._reclaim_inactive_owner(owner, output, same_run=same_run):
                    continue
                if same_run:
                    raise ReportingError(
                        "report_workflow_run_conflict", "同一报表请求正在启动，请稍后重试。"
                    )
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise ReportingError(
                    "report_workflow_active", "当前 thread 已有未完成的报表工作流。"
                )
            await asyncio.sleep(min(_THREAD_CLAIM_RETRY_DELAY_SECONDS, remaining))

    async def _get_thread_owner(self, thread_id: str) -> dict[str, Any] | None:
        getter = getattr(self._thread_ownership, "get_workflow_thread_owner", None)
        if not callable(getter):
            return None
        owner = await getter(thread_id)
        return owner if isinstance(owner, dict) else None

    async def _load_owner_output(self, owner: dict[str, Any]) -> Any:
        session_id, run_id = reporting_workflow_ids(
            user_id=str(owner["owner_user_id"]),
            thread_id=str(owner["thread_id"]),
            external_run_id=str(owner["external_run_id"]),
        )
        getter = getattr(self._workflow(), "aget_run", None)
        if not callable(getter):
            return None
        try:
            return await getter(run_id, session_id=session_id)
        except Exception as error:
            raise ReportingError(
                "report_workflow_owner_lookup_failed",
                "无法确认 thread 当前报表工作流状态，请稍后重试。",
            ) from error

    async def _reclaim_inactive_owner(
        self, owner: dict[str, Any], output: Any, *, same_run: bool
    ) -> bool:
        raw_status = getattr(output, "status", None) if output is not None else None
        status = self._status(raw_status) if raw_status is not None else None
        # paused 是正常的人审等待，必须跨重启保留；running 则只有在对应执行锁
        # 已释放后才可认定为进程遗留。缺失的 run 同样用执行锁排除仍在运行的进程。
        if status == "paused":
            return False
        if status in _ACTIVE_STATUSES or output is None:
            if not same_run and await self._owner_run_active(owner["external_run_id"]):
                return False
            # 当前 start 已持有自己的 external_run_id 执行锁，因此同 run 的探测
            # 不会误判自身；旧 run 的锁释放后即可安全回收。durable 非终态不再
            # 阻塞新请求，旧 workflow 的 workspace 会由 cleanup 统一销毁。
        elif status not in {"completed", "cancelled", "failed"}:
            return False
        owner_scope = {
            "thread_id": str(owner["thread_id"]),
            "external_run_id": str(owner["external_run_id"]),
            "user_id": str(owner["owner_user_id"]),
        }
        session_id, run_id = self._workflow_ids(owner_scope)
        if output is None or status in {"running", "cancelled", "failed"}:
            try:
                await self._cleanup_terminal(owner_scope, session_id, run_id)
            except BaseException:
                # 清理失败时保留 owner，避免新 run 与旧 sandbox 并发；调用方会在
                # 有界等待后收到明确的 active，而不是把底层异常误当成已回收。
                if same_run:
                    raise
                return False
        return await self._thread_ownership.release_workflow_thread(
            thread_id=owner_scope["thread_id"],
            external_run_id=owner_scope["external_run_id"],
            owner_user_id=owner_scope["user_id"],
        )

    async def _owner_run_active(self, external_run_id: str) -> bool:
        getter = getattr(self._thread_ownership, "is_workflow_run_active", None)
        if not callable(getter):
            # 生产仓储始终提供锁探测；缺失时宁可保持旧行为，避免测试替身或
            # 其他实现误删真实运行中的 owner。
            return True
        try:
            return bool(await getter(str(external_run_id)))
        except Exception as error:
            raise ReportingError(
                "report_workflow_owner_lookup_failed",
                "无法确认 thread 当前报表工作流状态，请稍后重试。",
            ) from error

    async def _ensure_thread_owner(self, scope: dict[str, str]) -> None:
        if not await self._thread_ownership.ensure_workflow_thread_owner(
            thread_id=self._thread_scope_key(scope),
            external_run_id=scope["external_run_id"],
            owner_user_id=scope["user_id"],
        ):
            raise ReportingError("report_workflow_active", "当前 thread 已有未完成的报表工作流。")

    async def _release_thread(self, scope: dict[str, str]) -> None:
        await self._thread_ownership.release_workflow_thread(
            thread_id=self._thread_scope_key(scope),
            external_run_id=scope["external_run_id"],
            owner_user_id=scope["user_id"],
        )

    @asynccontextmanager
    async def _execution_lock(self, external_run_id: str) -> Any:
        """串行化同一 paused run 的审批/取消，避免重复调用 Agno continue。"""

        lock_factory = getattr(self._thread_ownership, "workflow_execution_lock", None)
        if callable(lock_factory):
            try:
                async with lock_factory(external_run_id):
                    yield
            except ReportingStateError as error:
                raise ReportingError(error.code, error.message) from error
            return
        # 仅兼容不提供执行锁的单元测试替身；生产仓储始终实现该接口。
        yield

    @staticmethod
    def _control(state: dict[str, Any], *, required: bool = True) -> ReportWorkflowControl | None:
        raw = state.get(REPORT_WORKFLOW_CONTROL_STATE_KEY)
        if raw is None and not required:
            return None
        try:
            return ReportWorkflowControl.model_validate(raw)
        except Exception as error:
            raise ReportingError(
                "report_workflow_control_invalid", "报表工作流控制状态无效。"
            ) from error

    @staticmethod
    def _assert_scope(control: ReportWorkflowControl, scope: dict[str, str]) -> None:
        if (
            control.external_run_id,
            control.thread_id,
            control.user_id,
        ) != (
            scope["external_run_id"],
            scope["thread_id"],
            scope["user_id"],
        ):
            raise ReportingError("report_workflow_scope_mismatch", "报表工作流不属于当前运行。")

    def _control_from_output(
        self,
        output: Any,
        scope: dict[str, str],
        workflow_session_id: str,
        workflow_run_id: str,
    ) -> ReportWorkflowControl:
        status = self._status(getattr(output, "status", None))
        review = self._review(output) if status == "paused" else None
        return ReportWorkflowControl(
            workflowId=_WORKFLOW_ID,
            workflowRunId=workflow_run_id,
            workflowSessionId=workflow_session_id,
            externalRunId=scope["external_run_id"],
            threadId=scope["thread_id"],
            userId=scope["user_id"],
            status=status,
            review=review,
            updatedAt=datetime.now(UTC),
        )

    @staticmethod
    def _status(value: Any) -> ReportWorkflowStatus:
        normalized = value.value if isinstance(value, RunStatus) else str(value or "").upper()
        statuses: dict[str, ReportWorkflowStatus] = {
            "PENDING": "running",
            "RUNNING": "running",
            "PAUSED": "paused",
            "COMPLETED": "completed",
            "CANCELLED": "cancelled",
            "ERROR": "failed",
            "FAILED": "failed",
        }
        status = statuses.get(normalized)
        if status is None:
            raise ReportingError("report_workflow_status_invalid", "报表工作流状态无效。")
        return status

    @staticmethod
    def _active_requirement(output: Any) -> Any:
        active = list(getattr(output, "active_step_requirements", None) or [])
        if not active:
            requirements = list(getattr(output, "step_requirements", None) or [])
            active = [
                item for item in requirements if not bool(getattr(item, "is_resolved", False))
            ]
        if len(active) != 1:
            raise ReportingError("report_workflow_review_invalid", "报表工作流审核状态无效。")
        return active[0]

    def _review(self, output: Any) -> ReportReviewSnapshot:
        requirement = self._active_requirement(output)
        name = str(getattr(requirement, "step_name", "") or "")
        stage: ReviewStage
        content = getattr(getattr(requirement, "step_output", None), "content", None)
        if isinstance(content, BaseModel):
            content = content.model_dump(mode="json", by_alias=True)
        if "规范化报表请求" in name:
            stage = "request"
            title = "补充分析期间"
            allowed = {"clarificationQuestion"}
        elif "提纲" in name:
            stage = "outline"
            title = "审核报告提纲"
            allowed = {"title", "sections", "assumptions"}
        else:
            raise ReportingError("report_workflow_review_invalid", "报表工作流出现未知审核阶段。")
        preview = (
            {key: content[key] for key in allowed if key in content}
            if isinstance(content, dict)
            else {}
        )
        message = str(
            getattr(requirement, "confirmation_message", None)
            or getattr(requirement, "output_review_message", None)
            or title
        )[:1000]
        return ReportReviewSnapshot(stage=stage, title=title, message=message, preview=preview)

    @staticmethod
    def _result(control: ReportWorkflowControl, output: Any) -> dict[str, Any]:
        result: dict[str, Any] = {"ok": control.status != "failed", "status": control.status}
        if control.review is not None:
            result["review"] = control.review.model_dump(mode="json", by_alias=True)
        if control.status == "completed":
            content = getattr(output, "content", None)
            if isinstance(content, BaseModel):
                content = content.model_dump(mode="json", by_alias=True)
            if isinstance(content, dict):
                allowed = {
                    "reportId",
                    "revision",
                    "pdf",
                    "word",
                }
                report = {key: content[key] for key in allowed if key in content}
                if report:
                    result["report"] = report
        return result


class ReportWorkflowToolkit(Toolkit):
    def __init__(self, controller: ReportWorkflowController):
        self.controller = controller
        super().__init__(
            name="report_workflow",
            tools=[
                self.report_workflow_start,
                self.report_workflow_review,
                self.report_workflow_approve,
                self.report_workflow_reject,
            ],
            instructions=(
                "启动新报表只调用无参数的 report_workflow_start；该工具读取当前最后一条"
                "用户消息并交给 Workflow 首步归一化。"
                "任一工具返回普通审核 paused 时，准确展示 review 后必须立即调用 "
                "report_workflow_approve，由 AgentOS 原生确认收集批准或拒绝；request "
                "阶段使用 report_workflow_review 收集补充输入。"
                "不得在文本回答中代替用户审批，不得绕过 Workflow 审核或自行执行取数和 "
                "Coding 分析。"
            ),
            add_instructions=True,
        )
        review = self.async_functions["report_workflow_review"]
        for field in review.user_input_schema or []:
            field.value = "" if field.name == "feedback" else None

    async def report_workflow_start(
        self,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """将当前用户原文交给报表 Workflow 首步。"""
        prompt = self._current_user_prompt(run_context)
        workflow_input = parse_reporting_workflow_input(prompt)
        return await self.controller.start(workflow_input, run_context)

    @staticmethod
    def _current_user_prompt(run_context: RunContext | None) -> str:
        for message in reversed((run_context.messages if run_context else None) or []):
            if getattr(message, "role", None) != "user":
                continue
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                return content
            break
        raise ReportingError("report_request_invalid", "当前消息缺少自然语言报表需求。")

    @tool(
        requires_user_input=True,
        user_input_fields=["action", "feedback"],
    )
    async def report_workflow_review(
        self,
        action: Literal["approve", "reject", "cancel"],
        feedback: str = "",
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """审核当前暂停的报表 Workflow。

        Args:
            action: 审核动作：approve 批准，reject 拒绝，cancel 取消。
            feedback: 拒绝或补充信息时必填的完整意见。
        """
        if action == "approve":
            return await self.controller.approve(run_context)
        if action == "reject":
            return await self.controller.reject(feedback, run_context)
        return await self.controller.cancel(run_context)

    @tool(requires_confirmation=True)
    async def report_workflow_approve(
        self,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """批准当前展示的报表审核项并继续 Workflow。"""
        return await self.controller.approve(run_context)

    @tool()
    async def report_workflow_reject(
        self,
        feedback: str,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """将 AgentOS 原生确认的拒绝备注提交给报表 Workflow。"""
        return await self.controller.reject(feedback, run_context)
