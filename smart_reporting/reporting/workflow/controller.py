from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from agno.run import RunContext
from agno.run.base import RunStatus
from agno.tools import Toolkit, tool
from agno.workflow import OnReject
from loguru import logger
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
REPORT_MCP_REQUEST_FINGERPRINT_DEPENDENCY = "Reporting MCP 请求指纹"
REPORT_MCP_THREAD_PRECLAIMED_DEPENDENCY = "Reporting MCP 已占用 thread"
_WORKFLOW_ID = "enterprise-reporting-workflow-v1"
_ACTIVE_STATUSES = frozenset({"running", "paused"})
_THREAD_CLAIM_WAIT_SECONDS = 2.0
_THREAD_CLAIM_RETRY_DELAY_SECONDS = 0.1
_MAX_RETAINED_BACKGROUND_TASKS = 1024
# 每个活跃后台 run 会持有一条 PostgreSQL session advisory lock 连接；硬上限
# 必须显著低于默认 async pool 容量，为 Agno 持久化和状态查询保留连接余量。
_MAX_ACTIVE_BACKGROUND_TASKS = 4
ReportWorkflowStatus = Literal["running", "paused", "completed", "cancelled", "failed"]
ReviewStage = Literal["request", "outline", "recovery"]
_RECOVERY_STEP_IDS = frozenset({"assemble-report", "validate-report"})


def reporting_workflow_ids(
    *, user_id: str, thread_id: str, external_run_id: str
) -> tuple[str, str]:
    session_digest = hashlib.sha256(f"{user_id}:{thread_id}".encode()).hexdigest()[:32]
    run_digest = hashlib.sha256(f"{user_id}:{thread_id}:{external_run_id}".encode()).hexdigest()[
        :32
    ]
    return f"report-session-{session_digest}", f"report-run-{run_digest}"


def reporting_external_operation_id(
    *,
    database: str,
    company_id: str,
    user_id: str,
    thread_id: str,
    client_request_id: str,
) -> str:
    """生成同时绑定租户作用域与客户端幂等键的不透明 MCP operation ID。"""

    scope = _external_operation_scope_digest(
        database=database,
        company_id=company_id,
        user_id=user_id,
        thread_id=thread_id,
    )
    request = hashlib.sha256(client_request_id.encode()).hexdigest()
    return f"{scope}{request}"


def _external_operation_scope_digest(
    *, database: str, company_id: str, user_id: str, thread_id: str
) -> str:
    payload = json.dumps(
        [database, company_id, user_id, thread_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class ReviewableWorkflow(Protocol):
    id: str | None

    async def arun(self, *args: Any, **kwargs: Any) -> Any: ...

    async def aget_run(self, run_id: str, session_id: str | None = None) -> Any: ...

    async def acontinue_run(self, *args: Any, **kwargs: Any) -> Any: ...

    async def acancel_run(self, run_id: str) -> bool: ...


class WorkflowThreadOwnership(Protocol):
    async def register_run(self, **values: Any) -> dict[str, Any]: ...

    async def attach_request_run(self, external_run_id: str, report_run_id: str) -> None: ...

    async def attach_workflow_owner_run(self, **values: str) -> None: ...

    async def update_run_status(
        self,
        report_run_id: str,
        *,
        status: str,
        finalization_pending: bool | None = None,
    ) -> None: ...

    async def get_run_by_external(self, external_run_id: str) -> dict[str, Any] | None: ...

    async def register_external_request(self, **values: str) -> dict[str, Any]: ...

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

    def workflow_thread_lifecycle_lock(self, thread_id: str) -> Any: ...

    async def get_workflow_thread_owner(self, thread_id: str) -> dict[str, Any] | None: ...

    async def is_workflow_run_active(self, external_run_id: str) -> bool: ...


WorkflowFactory = Callable[[], ReviewableWorkflow]
TerminalCleanup = Callable[[dict[str, str], str, str], Awaitable[None]]
PreparedInputCleanup = Callable[[], Awaitable[None]]


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
        self._external_request_lock = asyncio.Lock()
        self._external_request_fingerprints: dict[str, str] = {}
        self._background_tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self._background_scopes: dict[str, tuple[str, str, str, str]] = {}
        self._background_request_fingerprints: dict[str, str] = {}
        self._background_cleanup_deferred: set[str] = set()

    async def start_external(
        self,
        workflow_input: ReportingWorkflowInput | ReportRequestEnvelope | dict[str, Any],
        *,
        external_run_id: str,
        thread_id: str,
        user_id: str,
        database: str = "default",
        company_id: str = "default",
        request_fingerprint: str | None = None,
        thread_preclaimed: bool = False,
    ) -> dict[str, Any]:
        context = self._external_run_context(
            external_run_id=external_run_id,
            thread_id=thread_id,
            user_id=user_id,
            database=database,
            company_id=company_id,
            request_fingerprint=request_fingerprint,
            thread_preclaimed=thread_preclaimed,
        )
        return await self.start(workflow_input, context)

    async def reserve_external_request(
        self,
        *,
        external_run_id: str,
        request_fingerprint: str,
        thread_id: str,
        user_id: str,
        database: str,
        company_id: str,
        run_lock_held: bool = False,
    ) -> bool:
        """在附件下载前固定幂等请求；返回 True 表示同参数请求已存在。"""

        async with self._external_request_lock:
            self._prune_background_tasks()
            current = self._external_request_fingerprints.get(external_run_id)
            if current is not None:
                if current != request_fingerprint:
                    raise ReportingError(
                        "report_mcp_idempotency_conflict",
                        "同一 clientRequestId 不得提交不同的报表请求。",
                    )
                self._assert_background_scope(
                    external_run_id,
                    thread_id=thread_id,
                    user_id=user_id,
                    database=database,
                    company_id=company_id,
                )
                return True
            for reserved_run_id, reserved_scope in self._background_scopes.items():
                reserved_task = self._background_tasks.get(reserved_run_id)
                if (
                    reserved_run_id != external_run_id
                    and reserved_scope[0] == thread_id
                    and (reserved_task is None or not reserved_task.done())
                ):
                    raise ReportingError(
                        "report_workflow_active", "当前 thread 已有未完成的报表工作流。"
                    )
            scope = {
                "external_run_id": external_run_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "database": database,
                "company_id": company_id,
            }
            await self._register_external_request(scope, request_fingerprint)
            session_id, run_id = self._workflow_ids(scope)
            output = await self._load_run_output(self._workflow(), run_id, session_id)
            if output is not None:
                stored_user = getattr(output, "user_id", None)
                metadata = getattr(output, "metadata", None)
                stored_fingerprint = (
                    metadata.get("mcpRequestFingerprint") if isinstance(metadata, dict) else None
                )
                if stored_user is not None and str(stored_user) != user_id:
                    raise ReportingError(
                        "report_workflow_scope_mismatch", "报表工作流不属于当前用户。"
                    )
                self._assert_mcp_metadata_scope(metadata, scope)
                if stored_fingerprint != request_fingerprint:
                    raise ReportingError(
                        "report_mcp_idempotency_conflict",
                        "同一 clientRequestId 不得提交不同的报表请求。",
                    )
                self._external_request_fingerprints[external_run_id] = request_fingerprint
                return True
            async with self._thread_lifecycle_lock(thread_id):
                claimed = await self._thread_ownership.claim_workflow_thread(
                    thread_id=thread_id,
                    external_run_id=external_run_id,
                    owner_user_id=user_id,
                )
                if not claimed:
                    owner = await self._get_thread_owner(thread_id)
                    if owner is None:
                        raise ReportingError(
                            "report_workflow_active", "当前 thread 已有未完成的报表工作流。"
                        )
                    same_run = (
                        str(owner.get("external_run_id")),
                        str(owner.get("owner_user_id")),
                    ) == (external_run_id, user_id)
                    owner_active = (
                        False
                        if same_run and run_lock_held
                        else await self._owner_run_active(str(owner.get("external_run_id") or ""))
                    )
                    if owner_active:
                        raise ReportingError(
                            "report_workflow_active", "当前 thread 已有未完成的报表工作流。"
                        )
                    owner_output = await self._load_owner_output(owner)
                    if not await self._reclaim_inactive_owner(
                        owner, owner_output, same_run=same_run
                    ) or not await self._thread_ownership.claim_workflow_thread(
                        thread_id=thread_id,
                        external_run_id=external_run_id,
                        owner_user_id=user_id,
                    ):
                        raise ReportingError(
                            "report_workflow_active", "当前 thread 已有未完成的报表工作流。"
                        )
            self._external_request_fingerprints[external_run_id] = request_fingerprint
            self._background_scopes[external_run_id] = (
                thread_id,
                user_id,
                database,
                company_id,
            )
            return False

    async def release_external_request(
        self, *, external_run_id: str, request_fingerprint: str
    ) -> None:
        scope: tuple[str, str, str, str] | None = None
        async with self._external_request_lock:
            if self._external_request_fingerprints.get(external_run_id) == request_fingerprint:
                self._external_request_fingerprints.pop(external_run_id, None)
                scope = self._background_scopes.get(external_run_id)
                if external_run_id not in self._background_tasks:
                    self._background_scopes.pop(external_run_id, None)
        if scope is not None:
            thread_id, user_id, _database, _company_id = scope
            await self._release_thread(
                {
                    "thread_id": thread_id,
                    "external_run_id": external_run_id,
                    "user_id": user_id,
                }
            )

    async def start_external_background(
        self,
        workflow_input: ReportingWorkflowInput | ReportRequestEnvelope | dict[str, Any],
        *,
        external_run_id: str,
        thread_id: str,
        user_id: str,
        database: str,
        company_id: str,
        request_fingerprint: str,
        thread_preclaimed: bool = False,
        prepare: Callable[
            [], Awaitable[ReportingWorkflowInput | ReportRequestEnvelope | dict[str, Any]]
        ]
        | None = None,
        prepared_input_cleanup: PreparedInputCleanup | None = None,
    ) -> dict[str, Any]:
        """使用现有确定性 run ID 在后台执行，避免 MCP tools/call 长时间占用。"""

        # 入队前完成强 schema 校验，不能把无效请求伪装成已接受的后台任务。
        self._prune_background_tasks()
        validated = (
            workflow_input
            if isinstance(workflow_input, (ReportingWorkflowInput, ReportRequestEnvelope))
            else ReportingWorkflowInput.model_validate(workflow_input)
        )
        current = self._background_tasks.get(external_run_id)
        if current is not None and not current.done():
            self._assert_background_scope(
                external_run_id,
                thread_id=thread_id,
                user_id=user_id,
                database=database,
                company_id=company_id,
            )
            if self._background_request_fingerprints.get(external_run_id) != request_fingerprint:
                raise ReportingError(
                    "report_mcp_idempotency_conflict",
                    "同一 clientRequestId 不得提交不同的报表请求。",
                )
            return {"ok": True, "status": "running"}
        ready: asyncio.Future[dict[str, Any]] | None = None
        active_count = sum(not task.done() for task in self._background_tasks.values())
        if active_count >= _MAX_ACTIVE_BACKGROUND_TASKS:
            raise ReportingError(
                "report_workflow_capacity_exceeded",
                "Reporting 后台任务容量已满，请稍后重试。",
            )
        context = self._external_run_context(
            external_run_id=external_run_id,
            thread_id=thread_id,
            user_id=user_id,
            database=database,
            company_id=company_id,
            request_fingerprint=request_fingerprint,
            thread_preclaimed=thread_preclaimed,
        )
        ready = asyncio.get_running_loop().create_future()
        run = self._run_external_background(
            validated,
            context,
            request_fingerprint=request_fingerprint,
            thread_preclaimed=thread_preclaimed,
            prepare=prepare,
            prepared_input_cleanup=prepared_input_cleanup,
            ready=ready,
        )
        task = asyncio.create_task(
            run,
            name=f"reporting-mcp-{external_run_id[:16]}",
        )
        self._background_tasks[external_run_id] = task
        self._background_scopes[external_run_id] = (
            thread_id,
            user_id,
            database,
            company_id,
        )
        self._background_request_fingerprints[external_run_id] = request_fingerprint
        task.add_done_callback(
            lambda completed: self._log_background_result(external_run_id, completed)
        )
        try:
            return await asyncio.shield(ready)
        except BaseException:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def _run_external_background(
        self,
        workflow_input: ReportingWorkflowInput | ReportRequestEnvelope,
        context: RunContext,
        *,
        request_fingerprint: str,
        thread_preclaimed: bool,
        prepare: Callable[
            [], Awaitable[ReportingWorkflowInput | ReportRequestEnvelope | dict[str, Any]]
        ]
        | None,
        prepared_input_cleanup: PreparedInputCleanup | None,
        ready: asyncio.Future[dict[str, Any]],
    ) -> dict[str, Any]:
        scope = self._scope(context)
        inputs_prepared = False
        workflow_started = False

        def mark_workflow_started() -> None:
            nonlocal workflow_started
            workflow_started = True

        try:
            async with self._execution_lock(scope["external_run_id"]):
                if thread_preclaimed:
                    await self._ensure_thread_owner(scope)
                    existing = False
                else:
                    existing = await self.reserve_external_request(
                        external_run_id=scope["external_run_id"],
                        request_fingerprint=request_fingerprint,
                        thread_id=scope["thread_id"],
                        user_id=scope["user_id"],
                        database=scope["database"],
                        company_id=scope["company_id"],
                        run_lock_held=True,
                    )
                    if not existing:
                        # reservation 已在同一执行锁内持久化并占用 thread。必须把该
                        # 事实传给 _start_unlocked；再次 claim 会把自身误判为孤儿，
                        # 在 Workflow 读取物化附件前触发终态 workspace 清理。
                        assert context.dependencies is not None
                        context.dependencies[REPORT_MCP_THREAD_PRECLAIMED_DEPENDENCY] = True
                if existing:
                    result = await self._start_unlocked(workflow_input, context)
                    if not ready.done():
                        ready.set_result(result)
                    return result
                prepared_input = await prepare() if prepare is not None else workflow_input
                validated = (
                    prepared_input
                    if isinstance(prepared_input, (ReportingWorkflowInput, ReportRequestEnvelope))
                    else ReportingWorkflowInput.model_validate(prepared_input)
                )
                inputs_prepared = True
                if not ready.done():
                    ready.set_result({"ok": True, "status": "running"})
                return await self._start_unlocked(
                    validated,
                    context,
                    on_workflow_start=mark_workflow_started,
                )
        except BaseException as error:
            cleanup_error: BaseException | None = None
            cleanup_deferred = False
            cleanup_prepared_input = (
                inputs_prepared and not workflow_started and prepared_input_cleanup is not None
            )
            attachment_cleanup_failed = self._contains_error_code(
                error, "report_attachment_cleanup_failed"
            )
            if cleanup_prepared_input or attachment_cleanup_failed:
                async with self._thread_lifecycle_lock(self._thread_scope_key(scope)):
                    owner = await self._get_thread_owner(self._thread_scope_key(scope))
                    owner_matches = owner is None or (
                        str(owner.get("external_run_id") or "") == scope["external_run_id"]
                        and str(owner.get("owner_user_id") or "") == scope["user_id"]
                    )
                    if owner_matches and cleanup_prepared_input:
                        assert prepared_input_cleanup is not None
                        try:
                            await prepared_input_cleanup()
                        except BaseException as failure:
                            cleanup_error = failure
                    needs_workspace_recovery = (
                        cleanup_error is not None or attachment_cleanup_failed
                    )
                    if owner_matches and needs_workspace_recovery:
                        if self._terminal_cleanup is None:
                            if not ready.done():
                                ready.set_exception(error)
                            raise error from cleanup_error
                        workflow_session_id, workflow_run_id = self._workflow_ids(scope)
                        try:
                            # operation 目录删除失败后，只有完整 workspace 已销毁或成功隔离，
                            # 才能释放 thread owner；否则下一次运行会重新接触残留附件。
                            cleaned = await self._cleanup_terminal_allowing_deferred(
                                scope, workflow_session_id, workflow_run_id
                            )
                            cleanup_deferred = not cleaned
                        except BaseException as finalization_error:
                            if not ready.done():
                                ready.set_exception(error)
                            raise error from finalization_error
            parent_pending = await self._parent_pending_control(scope)
            if cleanup_deferred or parent_pending is not None:
                self._background_cleanup_deferred.add(scope["external_run_id"])
            if (
                not cleanup_deferred
                and parent_pending is None
                and not self._contains_quarantine_failure(error)
            ):
                await self.release_external_request(
                    external_run_id=scope["external_run_id"],
                    request_fingerprint=request_fingerprint,
                )
            if not ready.done():
                ready.set_exception(error)
            raise

    @staticmethod
    def _contains_quarantine_failure(error: BaseException) -> bool:
        return ReportWorkflowController._contains_error_code(
            error, "report_sandbox_quarantine_failed"
        )

    @staticmethod
    def _contains_error_code(error: BaseException, code: str) -> bool:
        current: BaseException | None = error
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, ReportingError) and current.code == code:
                return True
            current = current.__cause__ or current.__context__
        return False

    @staticmethod
    def _external_run_context(
        *,
        external_run_id: str,
        thread_id: str,
        user_id: str,
        database: str,
        company_id: str,
        request_fingerprint: str | None,
        thread_preclaimed: bool,
    ) -> RunContext:
        dependencies: dict[str, Any] = {
            REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                "database": database,
                "companyId": company_id,
            }
        }
        if request_fingerprint is not None:
            dependencies[REPORT_MCP_REQUEST_FINGERPRINT_DEPENDENCY] = request_fingerprint
        if thread_preclaimed:
            dependencies[REPORT_MCP_THREAD_PRECLAIMED_DEPENDENCY] = True
        return RunContext(
            run_id=external_run_id,
            session_id=thread_id,
            user_id=user_id,
            dependencies=dependencies,
            session_state={},
        )

    async def get_external(
        self,
        *,
        external_run_id: str,
        thread_id: str,
        user_id: str,
        database: str,
        company_id: str,
    ) -> dict[str, Any]:
        scope = {
            "external_run_id": external_run_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "database": database,
            "company_id": company_id,
        }
        task = self._background_tasks.get(external_run_id)
        if task is not None and not task.done():
            self._assert_background_scope(
                external_run_id,
                thread_id=thread_id,
                user_id=user_id,
                database=database,
                company_id=company_id,
            )
            return {"ok": True, "status": "running"}
        session_id, run_id = self._workflow_ids(scope)
        output = await self._load_run_output(self._workflow(), run_id, session_id)
        if output is None:
            task = self._background_tasks.get(external_run_id)
            if task is None and external_run_id not in self._external_request_fingerprints:
                inflight = await self._external_inflight_result(scope)
                if inflight is not None:
                    return inflight
                # owner/执行锁可能恰好在首次读取后完成交接；二次读取持久化
                # output，避免把刚完成或刚暂停的 run 短暂误报为不存在。
                output = await self._load_run_output(self._workflow(), run_id, session_id)
                if output is None:
                    raise ReportingError(
                        "report_workflow_not_found", "报表工作流不存在或已经失效。"
                    )
            if output is None:
                if task is None:
                    self._assert_background_scope(
                        external_run_id,
                        thread_id=thread_id,
                        user_id=user_id,
                        database=database,
                        company_id=company_id,
                    )
                    return {"ok": True, "status": "running"}
                self._assert_background_scope(
                    external_run_id,
                    thread_id=thread_id,
                    user_id=user_id,
                    database=database,
                    company_id=company_id,
                )
                if not task.done():
                    return {"ok": True, "status": "running"}
                if task.cancelled():
                    return {"ok": True, "status": "cancelled"}
                try:
                    return task.result()
                except BaseException:
                    return {"ok": False, "status": "failed"}
        stored_user = getattr(output, "user_id", None)
        if stored_user is not None and str(stored_user) != user_id:
            raise ReportingError("report_workflow_scope_mismatch", "报表工作流不属于当前用户。")
        self._assert_mcp_metadata_scope(getattr(output, "metadata", None), scope)
        control = self._control_from_output(output, scope, session_id, run_id)
        lock_acquired = False
        try:
            async with self._execution_lock(external_run_id):
                lock_acquired = True
                await self._finalize_control(control, scope)
        except ReportingError as error:
            if lock_acquired or error.code != "report_workflow_run_conflict":
                raise
        return self._result(control, output)

    async def _register_external_request(
        self, scope: dict[str, str], request_fingerprint: str
    ) -> None:
        register = getattr(self._thread_ownership, "register_external_request", None)
        if not callable(register):
            raise ReportingError(
                "report_workflow_runtime_invalid",
                "Reporting runtime 缺少 MCP 请求幂等仓储。",
            )
        try:
            stored = await register(
                external_run_id=scope["external_run_id"],
                request_fingerprint=request_fingerprint,
                thread_id=scope["thread_id"],
                owner_user_id=scope["user_id"],
                database=scope["database"],
                company_id=scope["company_id"],
            )
        except Exception as error:
            raise ReportingError(
                "report_workflow_reservation_failed",
                "无法持久化 Reporting MCP 请求，请稍后重试。",
            ) from error
        if not isinstance(stored, dict):
            raise ReportingError(
                "report_workflow_reservation_failed", "Reporting MCP 请求幂等记录无效。"
            )
        stored_scope = (
            str(stored.get("thread_id") or ""),
            str(stored.get("owner_user_id") or ""),
            str(stored.get("database") or ""),
            str(stored.get("company_id") or ""),
        )
        expected_scope = (
            scope["thread_id"],
            scope["user_id"],
            scope["database"],
            scope["company_id"],
        )
        if stored_scope != expected_scope:
            raise ReportingError(
                "report_workflow_scope_mismatch", "报表工作流不属于当前租户或 thread。"
            )
        if str(stored.get("request_fingerprint") or "") != request_fingerprint:
            raise ReportingError(
                "report_mcp_idempotency_conflict",
                "同一 clientRequestId 不得提交不同的报表请求。",
            )

    async def _external_inflight_result(self, scope: dict[str, str]) -> dict[str, Any] | None:
        expected_scope = _external_operation_scope_digest(
            database=scope["database"],
            company_id=scope["company_id"],
            user_id=scope["user_id"],
            thread_id=scope["thread_id"],
        )
        operation_id = scope["external_run_id"]
        if len(operation_id) != 128 or not hmac.compare_digest(operation_id[:64], expected_scope):
            raise ReportingError(
                "report_workflow_scope_mismatch", "报表工作流不属于当前租户或 thread。"
            )
        owner = await self._get_thread_owner(scope["thread_id"])
        if owner is None or (
            str(owner.get("external_run_id")),
            str(owner.get("owner_user_id")),
        ) != (operation_id, scope["user_id"]):
            return None
        if await self._owner_run_active(operation_id):
            return {"ok": True, "status": "running"}
        return None

    async def cancel_external(
        self,
        *,
        external_run_id: str,
        thread_id: str,
        user_id: str,
        database: str,
        company_id: str,
    ) -> dict[str, Any]:
        task = self._background_tasks.get(external_run_id)
        if task is not None and not task.done():
            self._assert_background_scope(
                external_run_id,
                thread_id=thread_id,
                user_id=user_id,
                database=database,
                company_id=company_id,
            )
            task.cancel()
            try:
                await task
            except asyncio.CancelledError as error:
                if error.__cause__ is not None:
                    raise error.__cause__
            scope = {
                "external_run_id": external_run_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "database": database,
                "company_id": company_id,
            }
            if await self._parent_pending_control(scope) is None:
                await self._thread_ownership.release_workflow_thread(
                    thread_id=thread_id,
                    external_run_id=external_run_id,
                    owner_user_id=user_id,
                )
            return {"ok": True, "status": "cancelled"}
        context = await self.external_context(
            external_run_id=external_run_id,
            thread_id=thread_id,
            user_id=user_id,
            database=database,
            company_id=company_id,
        )
        return await self.cancel(context)

    def _assert_background_scope(
        self,
        external_run_id: str,
        *,
        thread_id: str,
        user_id: str,
        database: str,
        company_id: str,
    ) -> None:
        if self._background_scopes.get(external_run_id) != (
            thread_id,
            user_id,
            database,
            company_id,
        ):
            raise ReportingError(
                "report_workflow_scope_mismatch", "报表工作流不属于当前租户或 thread。"
            )

    def _prune_background_tasks(self) -> None:
        overflow = len(self._background_tasks) - _MAX_RETAINED_BACKGROUND_TASKS
        if overflow < 0:
            return
        for external_run_id, task in tuple(self._background_tasks.items()):
            if not task.done():
                continue
            self._background_tasks.pop(external_run_id, None)
            self._background_scopes.pop(external_run_id, None)
            self._background_request_fingerprints.pop(external_run_id, None)
            self._external_request_fingerprints.pop(external_run_id, None)
            self._background_cleanup_deferred.discard(external_run_id)
            overflow -= 1
            if overflow < 0:
                break

    async def aclose(self) -> None:
        active = tuple(
            (external_run_id, task)
            for external_run_id, task in self._background_tasks.items()
            if not task.done()
        )
        for _external_run_id, task in active:
            task.cancel()
        results = (
            await asyncio.gather(
                *(task for _, task in active),
                return_exceptions=True,
            )
            if active
            else ()
        )
        for (external_run_id, _task), result in zip(active, results, strict=True):
            if isinstance(result, BaseException) and result.__cause__ is not None:
                continue
            scope = self._background_scopes.get(external_run_id)
            if scope is None:
                continue
            thread_id, user_id, _database, _company_id = scope
            pending = await self._parent_pending_control(
                {
                    "external_run_id": external_run_id,
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "database": _database,
                    "company_id": _company_id,
                }
            )
            if pending is not None or external_run_id in self._background_cleanup_deferred:
                continue
            await self._thread_ownership.release_workflow_thread(
                thread_id=thread_id,
                external_run_id=external_run_id,
                owner_user_id=user_id,
            )

    @staticmethod
    def _log_background_result(external_run_id: str, task: asyncio.Task[dict[str, Any]]) -> None:
        if task.cancelled():
            logger.debug("report_mcp_background_cancelled external_run_id={}", external_run_id)
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "report_mcp_background_failed external_run_id={} error_type={}",
                external_run_id,
                type(error).__name__,
            )

    async def external_context(
        self,
        *,
        external_run_id: str,
        thread_id: str,
        user_id: str,
        database: str = "default",
        company_id: str = "default",
    ) -> RunContext:
        scope = {
            "external_run_id": external_run_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "database": database,
            "company_id": company_id,
        }
        session_id, run_id = self._workflow_ids(scope)
        output = await self._load_run_output(self._workflow(), run_id, session_id)
        if output is None:
            raise ReportingError("report_workflow_not_found", "报表工作流不存在或已经失效。")
        stored_user = getattr(output, "user_id", None)
        if stored_user is not None and str(stored_user) != user_id:
            raise ReportingError("report_workflow_scope_mismatch", "报表工作流不属于当前用户。")
        self._assert_mcp_metadata_scope(getattr(output, "metadata", None), scope)
        control = self._control_from_output(output, scope, session_id, run_id)
        return RunContext(
            run_id=external_run_id,
            session_id=thread_id,
            user_id=user_id,
            dependencies={
                REPORT_WORKFLOW_SCOPE_DEPENDENCY: {"database": database, "companyId": company_id}
            },
            session_state={REPORT_WORKFLOW_CONTROL_STATE_KEY: control.public_dict()},
        )

    async def start(
        self,
        workflow_input: ReportingWorkflowInput | ReportRequestEnvelope | dict[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        scope = self._scope(run_context)
        logger.info(
            "report_workflow_start_requested external_run_id={} thread_id={} user_id_present={}",
            scope["external_run_id"],
            scope["thread_id"],
            bool(scope["user_id"]),
        )
        try:
            async with self._execution_lock(scope["external_run_id"]):
                return await self._start_unlocked(workflow_input, run_context)
        except ReportingError as error:
            if error.code != "report_workflow_run_conflict":
                raise
            logger.warning(
                "report_workflow_duplicate_wait_started external_run_id={} thread_id={}",
                scope["external_run_id"],
                scope["thread_id"],
            )
            return await self._wait_for_duplicate_start(workflow_input, run_context, scope)

    async def _wait_for_duplicate_start(
        self,
        workflow_input: ReportingWorkflowInput | ReportRequestEnvelope | dict[str, Any],
        run_context: RunContext | None,
        scope: dict[str, str],
        *,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        """有限等待同一 run 的首个请求，避免重复调用立即失败或无限等待。"""

        if deadline is None:
            deadline = asyncio.get_running_loop().time() + _THREAD_CLAIM_WAIT_SECONDS
        workflow = self._workflow()
        workflow_session_id, workflow_run_id = self._workflow_ids(scope)
        while True:
            run_active = await self._owner_run_active(scope["external_run_id"])
            output = (
                None
                if run_active
                else await self._load_run_output(workflow, workflow_run_id, workflow_session_id)
            )
            if output is not None:
                status = self._status(getattr(output, "status", None))
                if status != "running":
                    control = self._control_from_output(
                        output, scope, workflow_session_id, workflow_run_id
                    )
                    return self._result(control, output)
                if not run_active:
                    # 持久化的 running 记录但执行锁已释放，说明首个进程已崩溃或
                    # 重启遗留；交给正常 start 路径清理并按确定性 run_id 重跑。
                    return await self._retry_duplicate_within_deadline(
                        workflow_input, run_context, scope, deadline
                    )
            elif not run_active:
                # 首个请求已经释放执行锁但没有留下可读结果，交给正常恢复路径
                # 重新校验 owner、清理现场并按相同身份启动，保持幂等键语义。
                return await self._retry_duplicate_within_deadline(
                    workflow_input, run_context, scope, deadline
                )
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                logger.warning(
                    "report_workflow_duplicate_wait_timeout external_run_id={} thread_id={}",
                    scope["external_run_id"],
                    scope["thread_id"],
                )
                raise ReportingError(
                    "report_workflow_run_conflict", "同一报表请求正在执行，请稍后重试。"
                )
            await asyncio.sleep(min(_THREAD_CLAIM_RETRY_DELAY_SECONDS, remaining))

    async def _retry_duplicate_within_deadline(
        self,
        workflow_input: ReportingWorkflowInput | ReportRequestEnvelope | dict[str, Any],
        run_context: RunContext | None,
        scope: dict[str, str],
        deadline: float,
    ) -> dict[str, Any]:
        try:
            async with self._execution_lock(scope["external_run_id"]):
                return await self._start_unlocked(workflow_input, run_context)
        except ReportingError as error:
            if error.code != "report_workflow_run_conflict":
                raise
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise ReportingError(
                    "report_workflow_run_conflict", "同一报表请求正在执行，请稍后重试。"
                ) from error
            await asyncio.sleep(min(_THREAD_CLAIM_RETRY_DELAY_SECONDS, remaining))
            return await self._wait_for_duplicate_start(
                workflow_input,
                run_context,
                scope,
                deadline=deadline,
            )

    async def _start_unlocked(
        self,
        workflow_input: ReportingWorkflowInput | ReportRequestEnvelope | dict[str, Any],
        run_context: RunContext | None,
        *,
        on_workflow_start: Callable[[], None] | None = None,
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
            await self._finalize_control(existing, existing_scope, state=state)
            return self._result(existing, None)
        if existing is None:
            parent_pending = await self._parent_pending_control(scope)
            if parent_pending is not None:
                state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = parent_pending.public_dict()
                await self._finalize_control(parent_pending, scope, state=state)
                return self._result(parent_pending, None)
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
            return self._result(current, output)

        workflow = self._workflow()
        workflow_session_id, workflow_run_id = self._workflow_ids(scope)
        await self._register_reporting_run(
            scope,
            workflow_session_id=workflow_session_id,
            workflow_run_id=workflow_run_id,
            run_context=run_context,
        )
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
                async with self._thread_lifecycle_lock(self._thread_scope_key(scope)):
                    owner = await self._get_thread_owner(scope["thread_id"])
                    owner_matches = owner is None or (
                        str(owner.get("external_run_id")) == scope["external_run_id"]
                        and str(owner.get("owner_user_id")) == scope["user_id"]
                    )
                    if owner_matches:
                        await self._cleanup_terminal_allowing_deferred(
                            scope, workflow_session_id, workflow_run_id
                        )
                        await self._release_thread_locked(scope)
                        persisted_output = None
                    else:
                        # 另一个 run 占用同一 thread 时，不能清理其 sandbox；交给下面的
                        # thread claim 路径返回明确冲突。
                        persisted_output = None
            if persisted_output is not None:
                state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = control.public_dict()
                if control.status in _ACTIVE_STATUSES:
                    await self._ensure_thread_owner(scope)
                await self._finalize_control(control, scope, state=state)
                return self._result(control, persisted_output)
        thread_preclaimed = bool(
            (run_context.dependencies or {}).get(REPORT_MCP_THREAD_PRECLAIMED_DEPENDENCY)
        )
        if thread_preclaimed:
            await self._ensure_thread_owner(scope)
            owned_output = None
        else:
            owned_output = await self._claim_thread_with_recovery(scope)
        if owned_output is not None:
            control = self._control_from_output(
                owned_output, scope, workflow_session_id, workflow_run_id
            )
            state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = control.public_dict()
            await self._finalize_control(control, scope, state=state)
            return self._result(control, owned_output)
        if on_workflow_start is not None:
            on_workflow_start()
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
                metadata=self._workflow_metadata(run_context, scope),
                stream=False,
            )
            control = self._control_from_output(output, scope, workflow_session_id, workflow_run_id)
        except BaseException as run_error:
            await self._finalize_run_error(
                run_error,
                scope,
                workflow_session_id,
                workflow_run_id,
                state,
            )
            raise
        state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = control.public_dict()
        await self._finalize_control(control, scope, state=state)
        return self._result(control, output)

    async def _register_reporting_run(
        self,
        scope: dict[str, str],
        *,
        workflow_session_id: str,
        workflow_run_id: str,
        run_context: RunContext | None,
    ) -> None:
        register = getattr(self._thread_ownership, "register_run", None)
        if not callable(register):
            return
        dependencies = run_context.dependencies if run_context is not None else {}
        is_mcp = isinstance(dependencies, dict) and bool(
            dependencies.get(REPORT_MCP_REQUEST_FINGERPRINT_DEPENDENCY)
        )
        await register(
            report_run_id=workflow_run_id,
            external_run_id=scope["external_run_id"],
            entrypoint="mcp" if is_mcp else "agentos",
            workflow_id=_WORKFLOW_ID,
            agno_session_id=workflow_session_id,
            agno_run_id=workflow_run_id,
            caller_session_id=scope["thread_id"],
            caller_run_id=scope["external_run_id"],
            thread_id=scope["thread_id"],
            owner_user_id=scope["user_id"],
            database=scope["database"],
            company_id=scope["company_id"],
        )
        if is_mcp:
            attach = getattr(self._thread_ownership, "attach_request_run", None)
            if callable(attach):
                await attach(scope["external_run_id"], workflow_run_id)
            attach_owner = getattr(
                self._thread_ownership, "attach_workflow_owner_run", None
            )
            if callable(attach_owner):
                await attach_owner(
                    thread_id=self._thread_scope_key(scope),
                    external_run_id=scope["external_run_id"],
                    owner_user_id=scope["user_id"],
                    report_run_id=workflow_run_id,
                )

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
                error_requirement = self._active_error_requirement(output)
                if error_requirement is not None:
                    error_requirement.skip()
                    await workflow.acancel_run(control.workflow_run_id)
                    try:
                        output = await workflow.acontinue_run(
                            run_response=output,
                            step_requirements=list(
                                getattr(output, "step_requirements", None) or []
                            ),
                            dependencies=self._workflow_dependencies(scope),
                            stream=False,
                        )
                    except BaseException as run_error:
                        await self._finalize_run_error(
                            run_error,
                            scope,
                            control.workflow_session_id,
                            control.workflow_run_id,
                            state,
                        )
                        raise
                else:
                    requirement = self._active_requirement(output)
                    requirement.on_reject = OnReject.cancel
                    requirement.reject(feedback="用户取消报表工作流。")
                    try:
                        output = await workflow.acontinue_run(
                            run_response=output,
                            step_requirements=list(
                                getattr(output, "step_requirements", None) or []
                            ),
                            dependencies=self._workflow_dependencies(scope),
                            stream=False,
                        )
                    except BaseException as run_error:
                        await self._finalize_run_error(
                            run_error,
                            scope,
                            control.workflow_session_id,
                            control.workflow_run_id,
                            state,
                        )
                        raise
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
            state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = updated.public_dict()
            await self._finalize_control(updated, scope, state=state)
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
            error_requirement = self._active_error_requirement(output)
            requirement = (
                error_requirement
                if error_requirement is not None
                else self._active_requirement(output)
            )
            if error_requirement is not None and not approve:
                raise ReportingError(
                    "report_workflow_recovery_retry_required",
                    "末端恢复项只能重试或取消。",
                )
            if error_requirement is not None:
                requirement.retry()
            elif approve:
                requirement.confirm()
            else:
                requirement.reject(feedback=feedback)
            workflow = self._workflow()
            try:
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
            except BaseException as run_error:
                await self._finalize_run_error(
                    run_error,
                    scope,
                    control.workflow_session_id,
                    control.workflow_run_id,
                    state,
                )
                raise
            state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = updated.public_dict()
            await self._finalize_control(updated, scope, state=state)
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
            await self._update_reporting_run_status(
                control.workflow_run_id,
                status=control.status,
                finalization_pending=None,
            )
            return
        # completed 的发布步骤已经在产物持久化后删除 sandbox；这里只覆盖没有发布
        # 收尾机会的取消和失败终态，避免成功路径二次清理反而遮蔽下载回执。
        if control.status in {"cancelled", "failed"}:
            async with self._thread_lifecycle_lock(self._thread_scope_key(scope)):
                parent = await self._terminal_cleanup_parent(control, scope)
                if parent is None:
                    return
                parent_status = str(parent.get("status") or "")
                if parent_status == control.status and not bool(parent.get("finalization_pending")):
                    await self._release_thread_locked(scope)
                    return
                if parent_status not in {*_ACTIVE_STATUSES, control.status}:
                    return
                if parent_status in _ACTIVE_STATUSES:
                    await self._update_reporting_run_status(
                        control.workflow_run_id,
                        status=control.status,
                        finalization_pending=True,
                    )
                    parent = await self._terminal_cleanup_parent(control, scope)
                    if parent is None:
                        return
                if str(parent.get("status") or "") != control.status or not bool(
                    parent.get("finalization_pending")
                ):
                    return
                pending = control.model_copy(update={"finalization_pending": True})
                if state is not None:
                    state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = pending.public_dict()
                cleaned = await self._cleanup_terminal_allowing_deferred(
                    scope, control.workflow_session_id, control.workflow_run_id
                )
                if not cleaned:
                    return
                await self._update_reporting_run_status(
                    control.workflow_run_id,
                    status=control.status,
                    finalization_pending=False,
                )
                if state is not None:
                    state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = control.model_copy(
                        update={"finalization_pending": None}
                    ).public_dict()
                await self._release_thread_locked(scope)
            return
        else:
            await self._update_reporting_run_status(
                control.workflow_run_id,
                status=control.status,
                finalization_pending=False,
            )
        await self._release_thread(scope)

    async def _terminal_cleanup_parent(
        self, control: ReportWorkflowControl, scope: dict[str, str]
    ) -> dict[str, Any] | None:
        getter = getattr(self._thread_ownership, "get_run_by_external", None)
        if not callable(getter):
            return None
        parent = await getter(control.external_run_id)
        owner = await self._get_thread_owner(self._thread_scope_key(scope))
        if not isinstance(parent, dict) or owner is None:
            return None
        parent_identity = (
            str(parent.get("report_run_id") or ""),
            str(parent.get("external_run_id") or ""),
            str(parent.get("thread_id") or ""),
            str(parent.get("owner_user_id") or ""),
        )
        owner_identity = (
            str(owner.get("report_run_id") or ""),
            str(owner.get("external_run_id") or ""),
            str(owner.get("thread_id") or ""),
            str(owner.get("owner_user_id") or ""),
        )
        expected = (
            control.workflow_run_id,
            scope["external_run_id"],
            self._thread_scope_key(scope),
            scope["user_id"],
        )
        if parent_identity != expected or owner_identity != expected:
            return None
        return parent

    async def _finalize_run_error(
        self,
        run_error: BaseException,
        scope: dict[str, str],
        workflow_session_id: str,
        workflow_run_id: str,
        state: dict[str, Any],
    ) -> None:
        terminal_status: ReportWorkflowStatus = (
            "cancelled" if isinstance(run_error, asyncio.CancelledError) else "failed"
        )
        terminal = ReportWorkflowControl(
            workflowId=_WORKFLOW_ID,
            workflowRunId=workflow_run_id,
            workflowSessionId=workflow_session_id,
            externalRunId=scope["external_run_id"],
            threadId=scope["thread_id"],
            userId=scope["user_id"],
            status=terminal_status,
        )
        state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = terminal.public_dict()
        async with self._thread_lifecycle_lock(self._thread_scope_key(scope)):
            if await self._terminal_cleanup_parent(terminal, scope) is None:
                return
            pending = terminal.model_copy(update={"finalization_pending": True})
            state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = pending.public_dict()
            await self._update_reporting_run_status(
                workflow_run_id,
                status=terminal_status,
                finalization_pending=True,
            )
            parent = await self._terminal_cleanup_parent(terminal, scope)
            if (
                parent is None
                or str(parent.get("status") or "") != terminal_status
                or not bool(parent.get("finalization_pending"))
            ):
                state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = terminal.public_dict()
                return
            try:
                cleaned = await self._cleanup_terminal_allowing_deferred(
                    scope, workflow_session_id, workflow_run_id
                )
                if cleaned:
                    await self._update_reporting_run_status(
                        workflow_run_id,
                        status=terminal_status,
                        finalization_pending=False,
                    )
                    state[REPORT_WORKFLOW_CONTROL_STATE_KEY] = pending.model_copy(
                        update={"finalization_pending": None}
                    ).public_dict()
                    await self._release_thread_locked(scope)
            except BaseException as finalization_error:
                # Agno 尚未返回可投影的 RunResponse，但持久化 owner 已占用成功。补偿失败
                # 必须保留最小终态控制面，同时继续抛出原始运行异常，避免遮蔽主失败。
                raise run_error from finalization_error

    async def _update_reporting_run_status(
        self,
        report_run_id: str,
        *,
        status: str,
        finalization_pending: bool | None,
    ) -> None:
        update_status = getattr(self._thread_ownership, "update_run_status", None)
        if callable(update_status):
            await update_status(
                report_run_id,
                status=status,
                finalization_pending=finalization_pending,
            )

    async def _parent_pending_control(
        self, scope: dict[str, str]
    ) -> ReportWorkflowControl | None:
        getter = getattr(self._thread_ownership, "get_run_by_external", None)
        if not callable(getter):
            return None
        stored = await getter(scope["external_run_id"])
        if stored is None or not bool(stored.get("finalization_pending")):
            return None
        stored_scope = (
            str(stored.get("external_run_id") or ""),
            str(stored.get("thread_id") or ""),
            str(stored.get("owner_user_id") or ""),
            str(stored.get("database") or ""),
            str(stored.get("company_id") or ""),
        )
        expected_scope = (
            scope["external_run_id"],
            scope["thread_id"],
            scope["user_id"],
            scope["database"],
            scope["company_id"],
        )
        status = str(stored.get("status") or "")
        workflow_session_id, workflow_run_id = self._workflow_ids(scope)
        stored_identity = (
            str(stored.get("workflow_id") or ""),
            str(stored.get("report_run_id") or ""),
            str(stored.get("agno_session_id") or ""),
            str(stored.get("agno_run_id") or ""),
            str(stored.get("caller_session_id") or ""),
            str(stored.get("caller_run_id") or ""),
        )
        expected_identity = (
            _WORKFLOW_ID,
            workflow_run_id,
            workflow_session_id,
            workflow_run_id,
            scope["thread_id"],
            scope["external_run_id"],
        )
        if (
            stored_scope != expected_scope
            or stored_identity != expected_identity
            or status not in {"cancelled", "failed"}
        ):
            raise ReportingError(
                "report_workflow_scope_mismatch",
                "Reporting 父运行不属于当前租户或不是待清理终态。",
            )
        return ReportWorkflowControl(
            workflowId=_WORKFLOW_ID,
            workflowRunId=workflow_run_id,
            workflowSessionId=workflow_session_id,
            externalRunId=scope["external_run_id"],
            threadId=scope["thread_id"],
            userId=scope["user_id"],
            status=status,
            finalizationPending=True,
        )

    async def _cleanup_terminal(
        self, scope: dict[str, str], workflow_session_id: str, workflow_run_id: str
    ) -> None:
        if self._terminal_cleanup is not None:
            await self._terminal_cleanup(scope, workflow_session_id, workflow_run_id)

    async def _cleanup_terminal_allowing_deferred(
        self, scope: dict[str, str], workflow_session_id: str, workflow_run_id: str
    ) -> bool:
        try:
            await self._cleanup_terminal(scope, workflow_session_id, workflow_run_id)
        except BaseException as error:
            if not self._sandbox_cleanup_failed(error):
                raise
            self._log_deferred_sandbox_cleanup(scope, error)
            return False
        self._background_cleanup_deferred.discard(scope["external_run_id"])
        return True

    @staticmethod
    def _sandbox_cleanup_failed(error: BaseException) -> bool:
        return isinstance(error, ReportingError) and error.code == "report_sandbox_cleanup_failed"

    @staticmethod
    def _log_deferred_sandbox_cleanup(scope: dict[str, str], error: BaseException) -> None:
        logger.warning(
            "report_sandbox_cleanup_deferred external_run_id={} thread_id={} error_type={}",
            scope["external_run_id"],
            scope["thread_id"],
            type(error).__name__,
        )

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
        resolved_external_run_id = external_run_id or run_context.run_id
        values = {
            "external_run_id": str(resolved_external_run_id or ""),
            "thread_id": str(run_context.session_id or ""),
            "user_id": str(run_context.user_id or ""),
        }
        if isinstance(dependency, dict):
            values["database"] = str(dependency.get("database") or "")
            values["company_id"] = str(dependency.get("companyId") or "")
        else:
            values["database"] = ""
            values["company_id"] = ""
        if not values["database"] and not values["company_id"]:
            values["database"] = "default"
            values["company_id"] = "default"
        elif not values["database"] or not values["company_id"]:
            raise ReportingError("report_workflow_context_missing", "报表工作流作用域不完整。")
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
                **(
                    {"database": scope["database"], "companyId": scope["company_id"]}
                    if "database" in scope
                    else {}
                ),
            }
        }

    @staticmethod
    def _workflow_metadata(
        run_context: RunContext | None, scope: dict[str, str]
    ) -> dict[str, str] | None:
        value = (
            (run_context.dependencies or {}).get(REPORT_MCP_REQUEST_FINGERPRINT_DEPENDENCY)
            if run_context is not None
            else None
        )
        if not isinstance(value, str) or not value:
            return None
        return {
            "mcpRequestFingerprint": value,
            "mcpDatabase": scope["database"],
            "mcpCompanyId": scope["company_id"],
            "mcpThreadId": scope["thread_id"],
        }

    @staticmethod
    def _assert_mcp_metadata_scope(metadata: Any, scope: dict[str, str]) -> None:
        if not isinstance(metadata, dict) or "mcpRequestFingerprint" not in metadata:
            raise ReportingError(
                "report_workflow_scope_mismatch", "报表工作流不属于 Reporting MCP。"
            )
        if (
            str(metadata.get("mcpDatabase") or ""),
            str(metadata.get("mcpCompanyId") or ""),
            str(metadata.get("mcpThreadId") or ""),
        ) != (
            scope["database"],
            scope["company_id"],
            scope["thread_id"],
        ):
            raise ReportingError(
                "report_workflow_scope_mismatch", "报表工作流不属于当前租户或 thread。"
            )

    @staticmethod
    def _thread_scope_key(scope: dict[str, str]) -> str:
        return scope["thread_id"]

    async def _claim_thread_with_recovery(self, scope: dict[str, str]) -> Any:
        """占用 thread；冲突时恢复同 run、回收终态 owner，或短暂等待前序 run。"""

        deadline = asyncio.get_running_loop().time() + _THREAD_CLAIM_WAIT_SECONDS
        while True:
            owner: dict[str, Any] | None = None
            async with self._thread_lifecycle_lock(self._thread_scope_key(scope)):
                if await self._thread_ownership.claim_workflow_thread(
                    thread_id=self._thread_scope_key(scope),
                    external_run_id=scope["external_run_id"],
                    owner_user_id=scope["user_id"],
                ):
                    logger.debug(
                        "report_workflow_owner_claimed external_run_id={} thread_id={}",
                        scope["external_run_id"],
                        scope["thread_id"],
                    )
                    return None
                owner = await self._get_thread_owner(scope["thread_id"])
                if owner is not None:
                    same_run = (
                        owner["external_run_id"],
                        owner["owner_user_id"],
                    ) == (scope["external_run_id"], scope["user_id"])
                    if not same_run and await self._owner_run_active(owner["external_run_id"]):
                        logger.debug(
                            "report_workflow_owner_active old_external_run_id={} "
                            "new_external_run_id={} thread_id={}",
                            owner.get("external_run_id"),
                            scope["external_run_id"],
                            scope["thread_id"],
                        )
                        output = None
                    else:
                        output = await self._load_owner_output(owner)
                    if same_run and output is not None:
                        return output
                    if await self._reclaim_inactive_owner(owner, output, same_run=same_run):
                        logger.warning(
                            "report_workflow_owner_reclaimed old_external_run_id={} "
                            "new_external_run_id={} thread_id={} same_run={}",
                            owner.get("external_run_id"),
                            scope["external_run_id"],
                            scope["thread_id"],
                            same_run,
                        )
                        if await self._thread_ownership.claim_workflow_thread(
                            thread_id=self._thread_scope_key(scope),
                            external_run_id=scope["external_run_id"],
                            owner_user_id=scope["user_id"],
                        ):
                            return None
                    if same_run:
                        logger.warning(
                            "report_workflow_same_run_conflict external_run_id={} thread_id={}",
                            scope["external_run_id"],
                            scope["thread_id"],
                        )
                        raise ReportingError(
                            "report_workflow_run_conflict", "同一报表请求正在启动，请稍后重试。"
                        )
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                logger.warning(
                    "report_workflow_thread_active external_run_id={} thread_id={} "
                    "owner_external_run_id={}",
                    scope["external_run_id"],
                    scope["thread_id"],
                    owner.get("external_run_id") if owner is not None else "-",
                )
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
                cleaned = await self._cleanup_terminal_allowing_deferred(
                    owner_scope, session_id, run_id
                )
                if not cleaned:
                    return False
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
        async with self._thread_lifecycle_lock(self._thread_scope_key(scope)):
            owned = await self._thread_ownership.ensure_workflow_thread_owner(
                thread_id=self._thread_scope_key(scope),
                external_run_id=scope["external_run_id"],
                owner_user_id=scope["user_id"],
            )
        if not owned:
            raise ReportingError("report_workflow_active", "当前 thread 已有未完成的报表工作流。")

    async def _release_thread(self, scope: dict[str, str]) -> None:
        async with self._thread_lifecycle_lock(self._thread_scope_key(scope)):
            await self._release_thread_locked(scope)

    async def _release_thread_locked(self, scope: dict[str, str]) -> None:
        await self._thread_ownership.release_workflow_thread(
            thread_id=self._thread_scope_key(scope),
            external_run_id=scope["external_run_id"],
            owner_user_id=scope["user_id"],
        )

    @asynccontextmanager
    async def _thread_lifecycle_lock(self, thread_id: str) -> Any:
        lock = getattr(self._thread_ownership, "workflow_thread_lifecycle_lock", None)
        if not callable(lock):
            raise ReportingError(
                "report_workflow_runtime_invalid",
                "Reporting runtime 缺少 workflow thread 生命周期锁。",
            )
        try:
            async with lock(thread_id):
                yield
        except ReportingStateError as error:
            raise ReportingError(error.code, error.message) from error

    @asynccontextmanager
    async def _execution_lock(self, external_run_id: str) -> Any:
        """串行化同一 paused run 的审批/取消，避免重复调用 Agno continue。"""

        lock = getattr(self._thread_ownership, "workflow_execution_lock", None)
        if not callable(lock):
            raise ReportingError(
                "report_workflow_runtime_invalid", "Reporting runtime 缺少 workflow 执行锁。"
            )
        try:
            async with lock(external_run_id):
                yield
        except ReportingStateError as error:
            raise ReportingError(error.code, error.message) from error

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

    @staticmethod
    def _active_error_requirement(output: Any) -> Any | None:
        errors = [
            item
            for item in list(getattr(output, "error_requirements", None) or [])
            if not bool(getattr(item, "is_resolved", False))
        ]
        if not errors:
            return None
        if len(errors) != 1 or str(getattr(errors[0], "step_id", "")) not in _RECOVERY_STEP_IDS:
            raise ReportingError("report_workflow_review_invalid", "报表工作流恢复状态无效。")
        return errors[0]

    def _review(self, output: Any) -> ReportReviewSnapshot:
        error_requirement = self._active_error_requirement(output)
        if error_requirement is not None:
            step_id = str(getattr(error_requirement, "step_id", ""))
            title = "重试最终报告汇编" if step_id == "assemble-report" else "重试报告格式验收"
            return ReportReviewSnapshot(
                stage="recovery",
                title=title,
                message=f"{title}；将沿用当前运行与工作区，仅重试失败的末端步骤。",
                preview={"stepId": step_id},
            )
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
                "Reporting 分析。"
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
