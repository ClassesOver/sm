from __future__ import annotations

import asyncio
import hashlib
import json
import shlex
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agno.run import RunContext
from agno.tools import Function
from daytona import SessionExecuteRequest
from daytona.common.errors import DaytonaNotFoundError

from ..agent_control import AGENT_PLAN_STATE_KEY, AgentControlToolkit
from ..coding_tools import (
    CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY,
    CODEX_EXEC_SESSIONS_STATE_KEY,
    HERMES_CODING_TOOLKIT_INSTRUCTIONS,
    CodingToolkit,
    _extract_apply_patch_command,
    _ManagedDaytonaTools,
    build_workspace_changes,
)
from ..workspace import (
    MANAGED_PROCESS_PREFIX,
    MAX_BACKGROUND_EXECUTION_TIMEOUT,
    MAX_PROCESS_INPUT_BYTES,
    MAX_TOOL_OUTPUT_BYTES,
    WORKSPACE_ROOT,
    WorkspaceError,
    WorkspaceProcessNotFound,
    WorkspaceService,
    WorkspaceToolkit,
    _thread,
)
from .models import CodingScope, Lease, TaskSnapshot
from .repository_impl import (
    TERMINAL_EXECUTION_STATUSES,
    CodingExecution,
    CodingRepositoryError,
    CodingTask,
    CodingTaskRepository,
    utcnow,
)

CODING_TASK_DEPENDENCY = "AgentOS 编码任务"
CODING_FINISH_STATE_KEY = "agentos_coding_finish"
CODING_EXECUTION_MIGRATION_STATE_KEY = "agentos_coding_execution_migrated"
DEFAULT_TERMINAL_TIMEOUT = 900
MAX_FINISH_ARTIFACTS = 50
MAX_VERIFICATION_IDS = 20


@dataclass(frozen=True)
class CodingTaskScope:
    task: CodingTask | TaskSnapshot
    external_run_id: str
    internal_run_id: str
    owner_user_id: str
    thread_id: str
    sandbox_id: str
    lease_owner: str
    lease_epoch: int
    attempt_no: int
    lease: Lease | None = None


class CodingExecutionKernel:
    def __init__(
        self,
        service: WorkspaceService,
        repository: CodingTaskRepository,
        *,
        completion_evidence: Callable[[RunContext], Awaitable[dict[str, Any] | None]] | None = None,
    ):
        self.service = service
        self.repository = repository
        self.completion_evidence = completion_evidence
        self.workspace = WorkspaceToolkit(service)
        self.plan = AgentControlToolkit(service)
        self._migration_lock = asyncio.Lock()

    async def cleanup_old_epoch(self, scope: CodingScope, current_epoch: int) -> None:
        await self._cleanup_executions(scope, current_epoch, old_only=True)

    async def cleanup_disconnect(self, scope: CodingScope, current_epoch: int) -> None:
        await self._cleanup_executions(scope, current_epoch, old_only=False)

    async def _cleanup_executions(
        self, scope: CodingScope, current_epoch: int, *, old_only: bool
    ) -> None:
        executions = await self.repository.list_executions(scope.external_run_id)
        for execution in executions:
            if execution.status in TERMINAL_EXECUTION_STATUSES or execution.retained_service:
                continue
            if old_only and execution.lease_epoch >= current_epoch:
                continue
            if not old_only and execution.lease_epoch != current_epoch:
                continue
            if execution.kind == "patch" and execution.operation_receipt:
                coordinated = await self._coordinate_patch(execution)
                if coordinated == "indeterminate":
                    await self.repository.fail_indeterminate_mutation(scope, current_epoch)
                    return
                await self.repository.update_execution(
                    execution.execution_id,
                    status="completed" if coordinated == "applied" else "cancelled",
                    exit_code=0 if coordinated == "applied" else None,
                )
                continue
            try:
                async with self.service._async_client() as client:
                    sandbox = await self.service._asandbox_for(client, scope.thread_id)
                    await sandbox.process.delete_session(execution.daytona_session_id)
                status = "terminated"
            except DaytonaNotFoundError:
                status = "lost"
            await self.repository.update_execution(execution.execution_id, status=status)

    async def _coordinate_patch(self, execution: CodingExecution) -> str:
        receipt = execution.operation_receipt or {}
        files = receipt.get("files")
        if not isinstance(files, list) or not files:
            return "indeterminate"
        states: list[str] = []
        for item in files:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                return "indeterminate"
            try:
                current = await self.service.ahash_file(execution.thread_id, item["path"])
                digest = current["sha256"]
            except (WorkspaceError, DaytonaNotFoundError):
                digest = None
            if digest == item.get("after_sha256"):
                states.append("after")
            elif digest == item.get("before_sha256"):
                states.append("before")
            else:
                states.append("other")
        if all(state == "after" for state in states):
            return "applied"
        if all(state == "before" for state in states):
            return "not_applied"
        return "indeterminate"

    async def scope(self, run_context: RunContext | None) -> CodingTaskScope:
        if run_context is None or not run_context.run_id or not run_context.user_id:
            raise CodingRepositoryError("task_context_missing", "缺少编码任务运行上下文。")
        dependencies = (
            run_context.dependencies if isinstance(run_context.dependencies, dict) else {}
        )
        binding = dependencies.get(CODING_TASK_DEPENDENCY)
        if not isinstance(binding, dict):
            raise CodingRepositoryError("task_binding_missing", "当前运行没有绑定编码任务。")
        external_run_id = binding.get("externalRunId")
        lease_owner = binding.get("leaseOwner")
        lease_epoch = binding.get("leaseEpoch")
        bound_sandbox_id = binding.get("sandboxId")
        if (
            not isinstance(external_run_id, str)
            or not isinstance(lease_owner, str)
            or (lease_epoch is not None and not isinstance(lease_epoch, int))
            or (bound_sandbox_id is not None and not isinstance(bound_sandbox_id, str))
        ):
            raise CodingRepositoryError("task_binding_invalid", "当前编码任务绑定无效。")
        snapshot = await self.repository.get_task_snapshot(external_run_id)
        task: CodingTask | TaskSnapshot | None = snapshot
        if task is None:
            task = await self.repository.get_task(external_run_id)
        if task is None:
            raise CodingRepositoryError("task_not_found", "编码任务必须由 Supervisor 创建。")
        sandbox_id = task.scope.sandbox_id if isinstance(task, TaskSnapshot) else task.sandbox_id
        thread_id = _thread(run_context)
        if isinstance(task, TaskSnapshot):
            if (
                task.scope.owner_user_id != str(run_context.user_id)
                or task.scope.thread_id != thread_id
                or task.scope.sandbox_id != sandbox_id
            ):
                raise CodingRepositoryError("task_scope_mismatch", "编码任务范围不匹配。")
        else:
            self.repository._assert_scope(task, str(run_context.user_id), thread_id, sandbox_id)
        internal_run_id = str(run_context.run_id)
        if not isinstance(task, TaskSnapshot) and task.current_internal_run_id is None:
            task = await self.repository.bind_initial_run(external_run_id, internal_run_id)
        elif internal_run_id != task.current_internal_run_id:
            raise CodingRepositoryError(
                "task_run_mismatch", "当前内部运行不是编码任务的活动 checkpoint。"
            )
        claimed = await self.repository.claim_lease(external_run_id, lease_owner)
        if not claimed:
            raise CodingRepositoryError("task_lease_conflict", "编码任务正在由另一连接处理。")
        active_lease = claimed if isinstance(claimed, Lease) else None
        if isinstance(task, TaskSnapshot) and (
            active_lease is None or lease_epoch != active_lease.epoch
        ):
            raise CodingRepositoryError("task_lease_binding_invalid", "编码任务 epoch 绑定无效。")
        await self.repository.cleanup_expired(lease_owner=lease_owner)
        scope = CodingTaskScope(
            task=task,
            external_run_id=external_run_id,
            internal_run_id=internal_run_id,
            owner_user_id=str(run_context.user_id),
            thread_id=thread_id,
            sandbox_id=sandbox_id,
            lease_owner=lease_owner,
            lease_epoch=active_lease.epoch if active_lease is not None else 0,
            attempt_no=(
                task.current_attempt_no
                if isinstance(task, TaskSnapshot)
                else task.continuation_count
            ),
            lease=active_lease,
        )
        await self._migrate_legacy_executions(scope, run_context)
        return scope

    async def _migrate_legacy_executions(
        self,
        scope: CodingTaskScope,
        run_context: RunContext,
    ) -> None:
        async with self._migration_lock:
            await self._migrate_legacy_executions_locked(scope, run_context)

    async def _migrate_legacy_executions_locked(
        self,
        scope: CodingTaskScope,
        run_context: RunContext,
    ) -> None:
        state = run_context.session_state if isinstance(run_context.session_state, dict) else None
        if state is None or state.get(CODING_EXECUTION_MIGRATION_STATE_KEY) is True:
            return
        active = state.get(CODEX_EXEC_SESSIONS_STATE_KEY)
        closed = state.get(CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY)
        for kind, entries in (("active", active), ("closed", closed)):
            if not isinstance(entries, dict):
                continue
            for legacy_handle, raw_entry in entries.items():
                if not isinstance(raw_entry, dict):
                    continue
                if (
                    str(raw_entry.get("thread") or "") != scope.thread_id
                    or str(raw_entry.get("user_id") or "") != scope.owner_user_id
                ):
                    raise CodingRepositoryError(
                        "legacy_execution_scope_mismatch",
                        "旧执行句柄不属于当前用户或对话。",
                    )
                remote_session_id = raw_entry.get("session_id")
                command_id = raw_entry.get("command_id")
                if kind == "active" and (
                    not isinstance(remote_session_id, str)
                    or not remote_session_id.startswith(MANAGED_PROCESS_PREFIX)
                    or not isinstance(command_id, str)
                    or not command_id
                ):
                    continue
                execution_id = hashlib.sha256(
                    f"{scope.external_run_id}:{kind}:{legacy_handle}".encode()
                ).hexdigest()[:32]
                if await self.repository.get_execution(execution_id) is not None:
                    continue
                synthetic_session_id = (
                    remote_session_id
                    if isinstance(remote_session_id, str)
                    else f"legacy-{execution_id}"
                )
                execution = await self.repository.reserve_execution(
                    execution_id=execution_id,
                    external_run_id=scope.external_run_id,
                    internal_run_id=scope.internal_run_id,
                    owner_user_id=scope.owner_user_id,
                    thread_id=scope.thread_id,
                    sandbox_id=scope.sandbox_id,
                    daytona_session_id=synthetic_session_id,
                    mutation_sequence=scope.task.mutation_sequence,
                )
                if kind == "active":
                    offset = raw_entry.get("offset", 0)
                    await self.repository.update_execution(
                        execution.execution_id,
                        status="running",
                        command_id=command_id,
                        output_cursor=(
                            offset
                            if isinstance(offset, int)
                            and not isinstance(offset, bool)
                            and offset >= 0
                            else 0
                        ),
                    )
                    continue
                reason = str(raw_entry.get("reason") or "lost")
                terminal_status = {
                    "completed": "completed",
                    "terminated": "terminated",
                    "timed_out": "failed",
                }.get(reason, "lost")
                await self.repository.update_execution(
                    execution.execution_id,
                    status=terminal_status,
                    exit_code=(
                        0
                        if terminal_status == "completed"
                        else 124
                        if reason == "timed_out"
                        else None
                    ),
                )
        state[CODING_EXECUTION_MIGRATION_STATE_KEY] = True

    async def _sandbox(self, scope: CodingTaskScope):
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, scope.thread_id)
            if str(getattr(sandbox, "id", "") or "") != scope.sandbox_id:
                raise CodingRepositoryError(
                    "task_sandbox_mismatch", "当前 Daytona 工作区与编码任务绑定不一致。"
                )
            yield sandbox

    async def _check_fence(self, scope: CodingTaskScope, execution_id: str) -> None:
        if scope.lease is not None:
            await self.repository.validate_execution_fence(execution_id, scope.lease)

    @staticmethod
    def _public_execution(execution: CodingExecution, *, cached: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "execution_id": execution.execution_id,
            "status": execution.status,
            "output": execution.terminal_output,
            "exit_code": execution.exit_code,
            "output_cursor": execution.output_cursor,
        }
        if execution.status not in TERMINAL_EXECUTION_STATUSES:
            result["session_id"] = execution.execution_id
        if cached:
            result["status_is_cached"] = True
        return result

    async def _scoped_execution(
        self,
        execution_id: str,
        run_context: RunContext | None,
    ) -> tuple[CodingTaskScope, CodingExecution]:
        scope = await self.scope(run_context)
        execution = await self.repository.scoped_execution(
            execution_id,
            owner_user_id=scope.owner_user_id,
            thread_id=scope.thread_id,
            sandbox_id=scope.sandbox_id,
        )
        if execution.external_run_id != scope.external_run_id:
            raise CodingRepositoryError("execution_scope_mismatch", "执行句柄不属于当前编码任务。")
        return scope, execution

    @staticmethod
    def _validate_terminal_arguments(
        command: str,
        background: bool,
        timeout: int,
        pty: bool,
    ) -> None:
        if not isinstance(background, bool) or not isinstance(pty, bool):
            raise WorkspaceError("terminal 的 background 和 pty 必须是布尔值。")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86_400:
            raise WorkspaceError("terminal timeout 必须是 1 至 86400 之间的整数秒。")
        CodingToolkit._validate_command_policy(command, "/bin/sh")

    @staticmethod
    def _managed_command(command: str, workdir: str | None, timeout: int, pty: bool) -> str:
        remote_cwd = WORKSPACE_ROOT
        if workdir is not None:
            _relative, remote_cwd = WorkspaceService.normalize_path(workdir)
        executed = f"exec {shlex.join(['/bin/sh', '-l', '-c', command])}"
        if pty:
            pty_command = f"export TERM=xterm-256color; stty rows 24 cols 80 -echo; {executed}"
            executed = shlex.join(
                ["script", "--quiet", "--return", "--command", pty_command, "/dev/null"]
            )
        timed = (
            f"timeout --signal=TERM --kill-after=5s {timeout}s /bin/sh -lc {shlex.quote(executed)}"
        )
        return f"cd -- {shlex.quote(remote_cwd)} && {timed}"

    async def _read_remote(
        self,
        process: Any,
        execution: CodingExecution,
        *,
        wait_ms: int = 0,
    ) -> dict[str, Any]:
        assert execution.command_id is not None
        deadline = asyncio.get_running_loop().time() + wait_ms / 1000
        while True:
            command = await self.workspace._managed_command(
                process,
                execution.daytona_session_id,
                execution.command_id,
            )
            exit_code = getattr(command, "exit_code", None)
            if exit_code is not None or asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(min(0.1, max(0.0, deadline - asyncio.get_running_loop().time())))
        logs = await process.get_session_command_logs(
            execution.daytona_session_id,
            execution.command_id,
        )
        return self.workspace._session_output(
            logs,
            session_id=execution.daytona_session_id,
            command_id=execution.command_id,
            status="completed" if exit_code is not None else "running",
            exit_code=exit_code,
            offset=execution.output_cursor,
            max_bytes=MAX_TOOL_OUTPUT_BYTES,
            timeout_marker=self.workspace._managed_timeout_marker(command),
        )

    async def _persist_result(
        self,
        process: Any,
        execution: CodingExecution,
        result: dict[str, Any],
    ) -> CodingExecution:
        remote_status = result.get("status")
        has_more = bool(result.get("hasMore"))
        exit_code = result.get("exitCode")
        status = (
            "running"
            if remote_status == "running"
            else "draining"
            if has_more
            else "completed"
            if exit_code == 0
            else "failed"
        )
        try:
            updated = await self.repository.update_execution(
                execution.execution_id,
                status=status,
                output_cursor=int(result.get("nextOffset", execution.output_cursor)),
                output=str(result.get("output", "") or ""),
                exit_code=exit_code if isinstance(exit_code, int) else None,
                expected_output_cursor=execution.output_cursor,
            )
        except CodingRepositoryError as error:
            if error.code != "execution_cas_conflict":
                raise
            latest = await self.repository.get_execution(execution.execution_id)
            assert latest is not None
            return latest
        if status in TERMINAL_EXECUTION_STATUSES:
            try:
                await process.delete_session(execution.daytona_session_id)
            except DaytonaNotFoundError:
                pass
        return updated

    async def terminal(
        self,
        command: str,
        *,
        background: bool = False,
        timeout: int = DEFAULT_TERMINAL_TIMEOUT,
        workdir: str | None = None,
        pty: bool = False,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        patch = _extract_apply_patch_command(command) if isinstance(command, str) else None
        if patch is None:
            self._validate_terminal_arguments(command, background, timeout, pty)
        elif workdir not in (None, "") or pty:
            raise WorkspaceError("apply_patch heredoc 不支持 workdir 或 PTY。")
        scope = await self.scope(run_context)
        patch_changes = (
            await asyncio.to_thread(build_workspace_changes, self.service, scope.thread_id, patch)
            if patch is not None
            else None
        )
        patch_receipt = self._patch_receipt(patch_changes) if patch_changes is not None else None
        mutation_sequence = await self.repository.increment_mutation(
            scope.external_run_id,
            lease=scope.lease,
            internal_run_id=scope.internal_run_id,
        )
        execution_id = uuid.uuid4().hex
        daytona_session_id = (
            "patch-"
            + hashlib.sha256(
                f"{scope.external_run_id}:{scope.attempt_no}:{mutation_sequence}".encode()
            ).hexdigest()[:32]
            if patch is not None
            else f"{MANAGED_PROCESS_PREFIX}{execution_id}"
        )
        execution = await self.repository.reserve_execution(
            execution_id=execution_id,
            external_run_id=scope.external_run_id,
            internal_run_id=scope.internal_run_id,
            owner_user_id=scope.owner_user_id,
            thread_id=scope.thread_id,
            sandbox_id=scope.sandbox_id,
            daytona_session_id=daytona_session_id,
            mutation_sequence=mutation_sequence,
            is_verification=patch is None,
            kind="patch" if patch is not None else "terminal",
            attempt_no=scope.attempt_no,
            lease_epoch=scope.lease_epoch,
            operation_receipt=patch_receipt,
            lease=scope.lease,
        )
        await self._check_fence(scope, execution_id)
        if patch is not None:
            try:
                assert patch_changes is not None
                applied = await asyncio.to_thread(
                    self.service.apply_changes, scope.thread_id, patch_changes
                )
                result = {**applied, "ok": True, "message": "补丁已应用。"}
                await self._check_fence(scope, execution_id)
                execution = await self.repository.update_execution(
                    execution_id,
                    status="completed",
                    output=str(result["message"]),
                    exit_code=0,
                )
                return {**self._public_execution(execution), **result, "intercepted_tool": "patch"}
            except Exception as error:
                message = (
                    str(error)
                    if isinstance(error, (CodingRepositoryError, WorkspaceError))
                    else "补丁执行失败。"
                )
                execution = await self.repository.update_execution(
                    execution_id,
                    status="failed",
                    output=message,
                    exit_code=1,
                )
                return {
                    **self._public_execution(execution),
                    "ok": False,
                    "code": "execution_failed",
                    "message": message,
                    "intercepted_tool": "patch",
                }

        managed_command = self._managed_command(command, workdir, timeout, pty)
        try:
            async for sandbox in self._sandbox(scope):
                session_id, command_id, _value = await self.workspace._start_managed_session(
                    sandbox.process,
                    scope.thread_id,
                    SessionExecuteRequest(
                        command=managed_command,
                        run_async=True,
                        suppress_input_echo=pty,
                    ),
                    session_id=daytona_session_id,
                )
                assert session_id == daytona_session_id
                await self._check_fence(scope, execution_id)
                execution = await self.repository.update_execution(
                    execution_id,
                    status="running",
                    command_id=command_id,
                )
                result = await self._read_remote(
                    sandbox.process,
                    execution,
                    wait_ms=0 if background else 30_000,
                )
                execution = await self._persist_result(sandbox.process, execution, result)
                await self._check_fence(scope, execution_id)
                return self._public_execution(execution)
        except Exception as error:
            current = await self.repository.get_execution(execution_id)
            if current is not None and current.status not in TERMINAL_EXECUTION_STATUSES:
                status = (
                    "lost"
                    if isinstance(error, (DaytonaNotFoundError, WorkspaceProcessNotFound))
                    else "failed"
                )
                try:
                    message = (
                        "Daytona 执行会话已丢失。"
                        if status == "lost"
                        else "命令启动或输出读取失败。"
                    )
                    current = await self.repository.update_execution(
                        execution_id,
                        status=status,
                        output=message,
                        exit_code=1 if status == "failed" else None,
                        expected_status=current.status,
                    )
                except CodingRepositoryError as conflict:
                    if conflict.code != "execution_cas_conflict":
                        raise
                    current = await self.repository.get_execution(execution_id)
                    assert current is not None
                if current.command_id is not None:
                    try:
                        async for sandbox in self._sandbox(scope):
                            await sandbox.process.delete_session(current.daytona_session_id)
                    except (CodingRepositoryError, DaytonaNotFoundError, WorkspaceError):
                        pass
            assert current is not None
            if current.status not in {"failed", "lost"}:
                return self._public_execution(current, cached=True)
            code = "execution_lost" if current.status == "lost" else "execution_failed"
            message = (
                "Daytona 执行会话已丢失。"
                if current.status == "lost"
                else "命令启动或输出读取失败。"
            )
            return {
                **self._public_execution(current),
                "ok": False,
                "code": code,
                "message": message,
            }
        raise AssertionError("Daytona 客户端上下文未返回 sandbox。")

    async def poll(
        self,
        execution_id: str,
        run_context: RunContext | None,
        *,
        wait_ms: int = 0,
    ) -> dict[str, Any]:
        scope, execution = await self._scoped_execution(execution_id, run_context)
        if execution.status in TERMINAL_EXECUTION_STATUSES:
            return self._public_execution(execution, cached=True)
        if execution.command_id is None:
            return self._public_execution(execution)
        try:
            async for sandbox in self._sandbox(scope):
                result = await self._read_remote(sandbox.process, execution, wait_ms=wait_ms)
                updated = await self._persist_result(sandbox.process, execution, result)
                return self._public_execution(updated)
        except (DaytonaNotFoundError, WorkspaceProcessNotFound):
            latest = await self.repository.get_execution(execution_id)
            if latest is not None and latest.status in TERMINAL_EXECUTION_STATUSES:
                return self._public_execution(latest, cached=True)
            try:
                lost = await self.repository.update_execution(
                    execution_id,
                    status="lost",
                    expected_status=execution.status,
                )
            except CodingRepositoryError as error:
                if error.code != "execution_cas_conflict":
                    raise
                latest_execution = await self.repository.get_execution(execution_id)
                assert latest_execution is not None
                lost = latest_execution
            return {**self._public_execution(lost), "code": "execution_lost"}
        raise AssertionError("Daytona 客户端上下文未返回 sandbox。")

    async def process(
        self,
        action: str,
        execution_id: str | None,
        data: str,
        timeout: int,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        scope = await self.scope(run_context)
        if action == "list":
            executions = await self.repository.list_executions(scope.external_run_id)
            return {
                "processes": [
                    self._public_execution(execution)
                    for execution in executions
                    if execution.kind == "terminal"
                    if execution.owner_user_id == scope.owner_user_id
                    and execution.thread_id == scope.thread_id
                    and execution.sandbox_id == scope.sandbox_id
                ]
            }
        if action not in {"poll", "wait", "kill", "write", "submit"}:
            raise WorkspaceError("process action 只支持 list、poll、wait、kill、write 或 submit。")
        if not isinstance(execution_id, str) or not execution_id:
            raise WorkspaceError("process 操作必须提供 terminal 返回的 session_id。")
        if action == "poll":
            return await self.poll(execution_id, run_context)
        if action == "wait":
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, int)
                or not 1 <= timeout <= 86_400
            ):
                raise WorkspaceError("process wait timeout 必须是 1 至 86400 之间的整数秒。")
            deadline = asyncio.get_running_loop().time() + timeout
            while True:
                remaining = max(0.0, deadline - asyncio.get_running_loop().time())
                result = await self.poll(
                    execution_id,
                    run_context,
                    wait_ms=min(30_000, int(remaining * 1000)),
                )
                if result["status"] in TERMINAL_EXECUTION_STATUSES or remaining <= 0:
                    return result
        scope, execution = await self._scoped_execution(execution_id, run_context)
        if action == "kill":
            if execution.status in TERMINAL_EXECUTION_STATUSES:
                return self._public_execution(execution, cached=True)
            remote_process = None
            async for sandbox in self._sandbox(scope):
                remote_process = sandbox.process
            try:
                terminated = await self.repository.update_execution(
                    execution_id,
                    status="terminated",
                    expected_status=execution.status,
                )
            except CodingRepositoryError as error:
                if error.code != "execution_cas_conflict":
                    raise
                latest_execution = await self.repository.get_execution(execution_id)
                assert latest_execution is not None
                terminated = latest_execution
            try:
                assert remote_process is not None
                await remote_process.delete_session(execution.daytona_session_id)
            except DaytonaNotFoundError:
                pass
            return self._public_execution(terminated)

        if execution.status in TERMINAL_EXECUTION_STATUSES:
            return {
                **self._public_execution(execution, cached=True),
                "code": "execution_terminal",
                "message": "执行已结束，不能继续写入。",
            }
        if not isinstance(data, str) or len(data.encode("utf-8")) > MAX_PROCESS_INPUT_BYTES:
            raise WorkspaceError("process 输入必须是不超过 8 KiB 的字符串。")
        if execution.command_id is None:
            raise WorkspaceError("执行尚未创建远端命令，不能写入。")
        payload = data if action == "write" else f"{data}\n"
        mutation_sequence = await self.repository.increment_mutation(
            scope.external_run_id,
            lease=scope.lease,
            internal_run_id=scope.internal_run_id,
        )
        operation_id = uuid.uuid4().hex
        await self.repository.reserve_execution(
            execution_id=operation_id,
            external_run_id=scope.external_run_id,
            internal_run_id=scope.internal_run_id,
            owner_user_id=scope.owner_user_id,
            thread_id=scope.thread_id,
            sandbox_id=scope.sandbox_id,
            daytona_session_id=f"process-input-{operation_id}",
            mutation_sequence=mutation_sequence,
            kind=f"process_{action}",
            attempt_no=scope.attempt_no,
            lease_epoch=scope.lease_epoch,
            operation_receipt={
                "target_execution_id": execution_id,
                "input_sha256": hashlib.sha256(payload.encode()).hexdigest(),
                "input_bytes": len(payload.encode()),
            },
            lease=scope.lease,
        )
        await self._check_fence(scope, operation_id)
        try:
            async for sandbox in self._sandbox(scope):
                await self.workspace._managed_command(
                    sandbox.process,
                    execution.daytona_session_id,
                    execution.command_id,
                )
                await sandbox.process.send_session_command_input(
                    execution.daytona_session_id,
                    execution.command_id,
                    payload,
                )
                await self._check_fence(scope, operation_id)
                await self.repository.update_execution(
                    operation_id,
                    status="completed",
                    exit_code=0,
                )
                return await self.poll(execution_id, run_context)
        except (DaytonaNotFoundError, WorkspaceProcessNotFound):
            await self.repository.update_execution(operation_id, status="lost")
            latest = await self.repository.get_execution(execution_id)
            if latest is not None and latest.status in TERMINAL_EXECUTION_STATUSES:
                return self._public_execution(latest, cached=True)
            try:
                lost = await self.repository.update_execution(
                    execution_id,
                    status="lost",
                    expected_status=execution.status,
                )
            except CodingRepositoryError as error:
                if error.code != "execution_cas_conflict":
                    raise
                latest_execution = await self.repository.get_execution(execution_id)
                assert latest_execution is not None
                lost = latest_execution
            return {**self._public_execution(lost), "code": "execution_lost"}
        raise AssertionError("Daytona 客户端上下文未返回 sandbox。")

    def apply_patch_sync(self, scope: CodingTaskScope, patch: str) -> dict[str, Any]:
        changes = build_workspace_changes(self.service, scope.thread_id, patch)
        result = self.service.apply_changes(scope.thread_id, changes)
        return {**result, "ok": True, "message": "补丁已应用。"}

    @staticmethod
    def _patch_receipt(changes: list[dict[str, Any]]) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        for change in changes:
            operation = change["operation"]
            content = change.get("content")
            after_sha = (
                hashlib.sha256(content.encode("utf-8")).hexdigest()
                if isinstance(content, str)
                else None
            )
            files.append(
                {
                    "path": change["path"],
                    "before_sha256": change.get("expected_sha256"),
                    "after_sha256": None if operation in {"delete", "move"} else after_sha,
                }
            )
            if operation == "move":
                files.append(
                    {
                        "path": change["destination"],
                        "before_sha256": None,
                        "after_sha256": change.get("expected_sha256"),
                    }
                )
        return {"files": files}

    async def patch(
        self,
        mode: str,
        path: str | None,
        old_string: str | None,
        new_string: str | None,
        replace_all: bool,
        patch: str | None,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        scope = await self.scope(run_context)
        if mode == "patch":
            if not isinstance(patch, str) or not patch.strip():
                raise WorkspaceError("patch 模式必须提供完整补丁。")
            changes = await asyncio.to_thread(
                build_workspace_changes, self.service, scope.thread_id, patch
            )
        elif mode == "replace":
            if not isinstance(path, str) or not isinstance(old_string, str) or not old_string:
                raise WorkspaceError("replace 模式必须提供 path 和非空 old_string。")
            if not isinstance(new_string, str) or not isinstance(replace_all, bool):
                raise WorkspaceError("replace 模式参数无效。")

            def replacement() -> tuple[list[dict[str, Any]], int]:
                content, _mime = self.service.file_bytes(scope.thread_id, path)
                try:
                    original = content.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise WorkspaceError("replace 模式只支持 UTF-8 文本文件。") from error
                count = original.count(old_string)
                if count == 0:
                    raise WorkspaceError("old_string 在目标文件中不存在。")
                if count != 1 and not replace_all:
                    raise WorkspaceError(
                        "old_string 在目标文件中不唯一；请扩大上下文或启用 replace_all。"
                    )
                updated = original.replace(old_string, new_string, -1 if replace_all else 1)
                return (
                    [
                        {
                            "operation": "update",
                            "path": path,
                            "content": updated,
                            "expected_sha256": hashlib.sha256(content).hexdigest(),
                        }
                    ],
                    count if replace_all else 1,
                )

            changes, replacements = await asyncio.to_thread(replacement)
        else:
            raise WorkspaceError("patch mode 只支持 replace 或 patch。")
        mutation_sequence = await self.repository.increment_mutation(
            scope.external_run_id,
            lease=scope.lease,
            internal_run_id=scope.internal_run_id,
        )
        execution_id = uuid.uuid4().hex
        receipt = self._patch_receipt(changes)
        patch_session_id = (
            "patch-"
            + hashlib.sha256(
                f"{scope.external_run_id}:{scope.attempt_no}:{mutation_sequence}".encode()
            ).hexdigest()[:32]
        )
        await self.repository.reserve_execution(
            execution_id=execution_id,
            external_run_id=scope.external_run_id,
            internal_run_id=scope.internal_run_id,
            owner_user_id=scope.owner_user_id,
            thread_id=scope.thread_id,
            sandbox_id=scope.sandbox_id,
            daytona_session_id=patch_session_id,
            mutation_sequence=mutation_sequence,
            kind="patch",
            attempt_no=scope.attempt_no,
            lease_epoch=scope.lease_epoch,
            operation_receipt=receipt,
            lease=scope.lease,
        )
        await self._check_fence(scope, execution_id)
        result = await asyncio.to_thread(self.service.apply_changes, scope.thread_id, changes)
        await self._check_fence(scope, execution_id)
        await self.repository.update_execution(
            execution_id,
            status="completed",
            exit_code=0,
            operation_receipt=receipt,
        )
        return {
            **result,
            "ok": True,
            "execution_id": execution_id,
            "mutation_sequence": mutation_sequence,
            **({"replacements": replacements} if mode == "replace" else {}),
        }

    async def finish_task(
        self,
        summary: str | None,
        artifact_paths: list[str] | None,
        verification_ids: list[str] | None,
        service_sessions: list[dict[str, str]],
        run_context: RunContext | None,
        finish_function: Function,
    ) -> dict[str, Any]:
        scope = await self.scope(run_context)
        if isinstance(scope.task, TaskSnapshot) and scope.task.finish_receipt is not None:
            finish_function.stop_after_tool_call = True
            return {"ok": True, "status": "accepted", **scope.task.finish_receipt}
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 4000:
            return self._finish_error("finish_summary_invalid", "summary 必须是 1 至 4000 个字符。")
        state = (
            run_context.session_state
            if run_context and isinstance(run_context.session_state, dict)
            else {}
        )
        plan = state.get(AGENT_PLAN_STATE_KEY)
        steps = plan.get("plan") if isinstance(plan, dict) else []
        if isinstance(steps, list) and any(
            not isinstance(step, dict) or step.get("status") != "completed" for step in steps
        ):
            return self._finish_error("finish_plan_incomplete", "仍有计划步骤未完成。")
        if (
            not isinstance(artifact_paths, list)
            or len(artifact_paths) > MAX_FINISH_ARTIFACTS
            or any(not isinstance(path, str) or not path for path in artifact_paths)
        ):
            return self._finish_error("finish_artifacts_invalid", "artifact_paths 无效。")
        if not isinstance(service_sessions, list):
            return self._finish_error("finish_services_invalid", "service_sessions 无效。")
        declared_services: dict[str, str] = {}
        for item in service_sessions:
            if (
                not isinstance(item, dict)
                or set(item) != {"session_id", "healthcheck_execution_id"}
                or not isinstance(item.get("session_id"), str)
                or not item["session_id"]
                or not isinstance(item.get("healthcheck_execution_id"), str)
                or not item["healthcheck_execution_id"]
                or item["session_id"] in declared_services
            ):
                return self._finish_error("finish_services_invalid", "service_sessions 无效。")
            declared_services[item["session_id"]] = item["healthcheck_execution_id"]
        artifacts: list[dict[str, Any]] = []
        try:
            async for _sandbox in self._sandbox(scope):
                pass
        except (CodingRepositoryError, WorkspaceError, DaytonaNotFoundError):
            return self._finish_error(
                "finish_sandbox_changed", "当前 Daytona 工作区与任务绑定不一致。"
            )
        try:
            for path in artifact_paths:
                artifacts.append(await self.service.ahash_file(scope.thread_id, path))
        except (WorkspaceError, DaytonaNotFoundError):
            return self._finish_error("finish_artifact_missing", "交付产物不存在或已发生变化。")

        if (
            not isinstance(verification_ids, list)
            or not verification_ids
            or len(verification_ids) > MAX_VERIFICATION_IDS
        ):
            return self._finish_error("finish_verification_missing", "至少需要一个验证执行回执。")
        task = await self.repository.get_task(scope.external_run_id)
        assert task is not None
        for execution_id in verification_ids:
            if not isinstance(
                execution_id, str
            ) or not await self.repository.successful_verification(
                scope.external_run_id,
                execution_id,
                task.mutation_sequence,
            ):
                return self._finish_error(
                    "finish_verification_stale", "验证未成功，或早于最后一次潜在修改。"
                )

        executions = await self.repository.list_executions(scope.external_run_id)
        active = [
            execution
            for execution in executions
            if execution.status not in TERMINAL_EXECUTION_STATUSES
        ]
        active_ids = {execution.execution_id for execution in active}
        if active_ids != set(declared_services):
            return self._finish_error("finish_process_active", "存在未声明的活动进程。")
        for execution in active:
            healthcheck_id = declared_services[execution.execution_id]
            if not await self.repository.successful_verification(
                scope.external_run_id,
                healthcheck_id,
                task.mutation_sequence,
            ):
                return self._finish_error(
                    "finish_service_unhealthy", "保留服务缺少当前 mutation 的成功健康检查。"
                )

        extra_evidence = None
        if self.completion_evidence is not None:
            try:
                assert run_context is not None
                extra_evidence = await self.completion_evidence(run_context)
            except (WorkspaceError, DaytonaNotFoundError):
                extra_evidence = None
            if extra_evidence is None:
                return self._finish_error(
                    "finish_report_unverified", "报表 PDF 或交付证据未通过验收。"
                )

        payload: dict[str, Any] = {
            "summary": summary.strip(),
            "artifacts": artifacts,
            "verificationIds": verification_ids,
            "serviceSessions": service_sessions,
            **({"evidence": extra_evidence} if extra_evidence is not None else {}),
        }
        try:
            current_artifacts = [
                await self.service.ahash_file(scope.thread_id, path) for path in artifact_paths
            ]
            async for _sandbox in self._sandbox(scope):
                pass
        except (CodingRepositoryError, WorkspaceError, DaytonaNotFoundError):
            return self._finish_error(
                "finish_sandbox_changed", "当前工作区或交付产物在验收期间发生变化。"
            )
        if current_artifacts != artifacts:
            return self._finish_error("finish_artifact_changed", "交付产物在验收期间发生变化。")
        try:
            if isinstance(scope.task, TaskSnapshot):
                receipt = {
                    "taskId": scope.external_run_id,
                    "attemptNo": scope.attempt_no,
                    "internalRunId": scope.internal_run_id,
                    "sandboxId": scope.sandbox_id,
                    "mutationSequence": task.mutation_sequence,
                    **payload,
                    "acceptedAt": utcnow().isoformat(),
                }
                receipt["digest"] = hashlib.sha256(
                    json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                assert scope.lease is not None
                await self.repository.request_finish(
                    scope.external_run_id,
                    scope.lease,
                    scope.task.state_version,
                    receipt,
                    result_text=summary.strip(),
                    retained_execution_ids=list(declared_services),
                )
                payload = receipt
            else:
                await self.repository.complete_task(
                    scope.external_run_id,
                    expected_mutation_sequence=task.mutation_sequence,
                    expected_lease_owner=scope.lease_owner,
                    result_text=summary.strip(),
                    finish_payload=payload,
                    retained_execution_ids=list(declared_services),
                )
        except CodingRepositoryError as error:
            if error.code == "finish_instruction_pending":
                finish_function.stop_after_tool_call = True
                return self._finish_error(error.code, str(error))
            if error.code not in {"task_cas_conflict", "attempt_cas_conflict"}:
                raise
            return self._finish_error(
                "finish_state_changed", "任务状态在验收期间发生变化，请重新验证。"
            )
        state[CODING_FINISH_STATE_KEY] = payload
        finish_function.stop_after_tool_call = True
        return {"ok": True, "status": "accepted", **payload}

    @staticmethod
    def _finish_error(code: str, message: str) -> dict[str, Any]:
        return {"ok": False, "status": "rejected", "code": code, "message": message}


class WorkspaceCodingToolkit(_ManagedDaytonaTools):
    def __init__(
        self,
        service: WorkspaceService,
        repository: CodingTaskRepository,
        *,
        completion_evidence: Callable[[RunContext], Awaitable[dict[str, Any] | None]] | None = None,
    ):
        self.kernel = CodingExecutionKernel(
            service, repository, completion_evidence=completion_evidence
        )
        finish_function = Function(
            name="finish_task",
            description="提交最终任务验收；验收失败时按稳定错误码修复后再次调用。",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "minLength": 1, "maxLength": 4000},
                    "artifact_paths": {
                        "type": "array",
                        "maxItems": MAX_FINISH_ARTIFACTS,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "verification_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_VERIFICATION_IDS,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "service_sessions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["session_id", "healthcheck_execution_id"],
                            "properties": {
                                "session_id": {"type": "string", "minLength": 1},
                                "healthcheck_execution_id": {"type": "string", "minLength": 1},
                            },
                        },
                        "default": [],
                    },
                },
                "required": ["summary", "artifact_paths", "verification_ids"],
                "additionalProperties": False,
            },
        )

        async def finish_entrypoint(
            summary: str | None = None,
            artifact_paths: list[str] | None = None,
            verification_ids: list[str] | None = None,
            service_sessions: list[dict[str, str]] | None = None,
            run_context: RunContext | None = None,
        ) -> dict[str, Any]:
            return await self.kernel.finish_task(
                summary,
                artifact_paths,
                verification_ids,
                service_sessions or [],
                run_context,
                finish_function,
            )

        finish_function.entrypoint = finish_entrypoint
        super().__init__(
            name="workspace_coding",
            tools=[
                Function(
                    name="terminal",
                    parameters={
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "minLength": 1},
                            "background": {"type": "boolean", "default": False},
                            "timeout": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_BACKGROUND_EXECUTION_TIMEOUT,
                                "default": DEFAULT_TERMINAL_TIMEOUT,
                            },
                            "workdir": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "pty": {"type": "boolean", "default": False},
                        },
                        "required": ["command"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.terminal,
                ),
                Function(
                    name="process",
                    parameters={
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["list", "poll", "wait", "kill", "write", "submit"],
                            },
                            "session_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "data": {"type": "string", "maxLength": MAX_PROCESS_INPUT_BYTES},
                            "timeout": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_BACKGROUND_EXECUTION_TIMEOUT,
                                "default": 30,
                            },
                        },
                        "required": ["action"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.process,
                ),
                Function(
                    name="patch",
                    parameters={
                        "type": "object",
                        "properties": {
                            "mode": {"type": "string", "enum": ["replace", "patch"]},
                            "path": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "old_string": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "new_string": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                            "replace_all": {"type": "boolean", "default": False},
                            "patch": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        },
                        "required": ["mode"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.patch,
                ),
                Function(name="view_image", entrypoint=self.view_image),
                Function(
                    name="update_plan",
                    description="更新编码任务计划；最多 20 步且最多一个步骤处于 in_progress。",
                    parameters={
                        "type": "object",
                        "properties": {
                            "plan": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 20,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["step", "status"],
                                    "properties": {
                                        "step": {
                                            "type": "string",
                                            "minLength": 1,
                                            "maxLength": 300,
                                        },
                                        "status": {
                                            "type": "string",
                                            "enum": ["pending", "in_progress", "completed"],
                                        },
                                    },
                                },
                            },
                            "explanation": {
                                "anyOf": [{"type": "string", "maxLength": 1000}, {"type": "null"}]
                            },
                        },
                        "required": ["plan"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.update_plan,
                ),
                finish_function,
            ],
            instructions=HERMES_CODING_TOOLKIT_INSTRUCTIONS,
        )

    async def terminal(
        self,
        command: str,
        background: bool = False,
        timeout: int = DEFAULT_TERMINAL_TIMEOUT,
        workdir: str | None = None,
        pty: bool = False,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return await self.kernel.terminal(
            command,
            background=background,
            timeout=timeout,
            workdir=workdir,
            pty=pty,
            run_context=run_context,
        )

    async def process(
        self,
        action: str,
        session_id: str | None = None,
        data: str = "",
        timeout: int = 30,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return await self.kernel.process(action, session_id, data, timeout, run_context)

    async def patch(
        self,
        mode: str,
        path: str | None = None,
        old_string: str | None = None,
        new_string: str | None = None,
        replace_all: bool = False,
        patch: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return await self.kernel.patch(
            mode,
            path,
            old_string,
            new_string,
            replace_all,
            patch,
            run_context,
        )

    async def view_image(
        self,
        path: str,
        detail: str = "high",
        run_context: RunContext | None = None,
    ):
        if detail not in {"high", "original"}:
            raise WorkspaceError("图片 detail 必须是 high 或 original。")
        scope = await self.kernel.scope(run_context)
        return await asyncio.to_thread(self.kernel.service.view_image, scope.thread_id, path)

    def update_plan(
        self,
        plan: list[dict[str, str]] | None = None,
        explanation: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        if plan is None:
            return {
                "ok": False,
                "code": "plan_required",
                "message": "plan 必须包含 1 至 20 个步骤。",
            }
        return self.kernel.plan.agent_update_plan(plan, explanation, run_context)
