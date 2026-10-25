"""现有任务执行内核到 Reporting 工具端口的生产适配。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

from agno.run import RunContext

from ...task_execution import (
    MAX_TOOL_FAILURE_ENTRIES,
    MAX_TOOL_PROGRESS_ENTRIES,
    NO_PROGRESS_EXEMPT_TOOLS,
    TASK_EXECUTION_TOOL_FAILURE_STATE_KEY,
    TASK_EXECUTION_TOOL_PROGRESS_STATE_KEY,
    TOOL_SPECS,
    TaskExecutionKernel,
    TaskExecutionRuntime,
    failed_result_resources,
    stable_progress_result,
    suggested_workspace_path,
)
from ...workspace import (
    MAX_UPLOAD_BYTES,
    WorkspaceError,
    WorkspacePathConflict,
    normalize_workspace_path,
)

if TYPE_CHECKING:
    from ..host_workspace import ReportingWorkspaceRouter

def _validate_reporting_content(content: bytes) -> None:
    if not isinstance(content, bytes):
        raise WorkspaceError("文件内容格式无效，请使用二进制内容后重试。")
    if len(content) > MAX_UPLOAD_BYTES:
        raise WorkspaceError("文件内容超过 200 MiB，请缩小文件后重试。")


class ReportingWorkspaceAdapter:
    """封装 Reporting 宿主机工作区已有的读写原语。"""

    def __init__(self, service: ReportingWorkspaceRouter) -> None:
        self._service = service

    normalize_path = staticmethod(normalize_workspace_path)

    async def afile_bytes(self, thread_id: str, path: str) -> tuple[bytes, str]:
        return await self._service.afile_bytes(thread_id, path)

    async def aread_text(self, thread_id: str, path: str) -> str:
        return await self._service.aread_text(thread_id, path)

    def validate_content(self, content: bytes) -> None:
        _validate_reporting_content(content)

    async def hash_file(self, thread_id: str, path: str) -> dict[str, Any]:
        return await self._service.ahash_file(thread_id, path)

    async def ahash_file(self, thread_id: str, path: str) -> dict[str, Any]:
        """提供 Reporting 可视化提交阶段使用的异步文件哈希能力。"""
        return await self.hash_file(thread_id, path)

    async def batch_hash_files(self, thread_id: str, paths: Sequence[str]) -> list[dict[str, Any]]:
        return await self._service.abatch_hash_files(thread_id, list(paths))

    async def read_limited_regular_file(
        self,
        thread_id: str,
        path: str,
        *,
        max_bytes: int,
    ) -> bytes:
        # 有界读取由 Reporting 宿主机工作区提供。
        reader = getattr(self._service, "read_limited_regular_file", None)
        if not callable(reader):
            raise WorkspaceError("当前工作区不支持有界文件读取。")
        return await reader(thread_id, path, max_bytes=max_bytes)

    async def inspect_chart_file(self, thread_id: str, path: str) -> dict[str, Any]:
        from ..workspace import inspect_report_chart_file

        return await inspect_report_chart_file(self._service, thread_id=thread_id, path=path)

    async def inspect_plotly_file(self, thread_id: str, path: str) -> dict[str, Any]:
        from ..workspace import inspect_report_plotly_file

        return await inspect_report_plotly_file(self._service, thread_id=thread_id, path=path)


class ReportingTaskRuntime:
    """Reporting 工具的运行时边界；RunContext 只在此处解析。"""

    def __init__(self, service: ReportingWorkspaceRouter, repository: Any) -> None:
        self._kernel = TaskExecutionKernel(service, repository)
        self.workspace = ReportingWorkspaceAdapter(service)
        self._service = service
        self.repository = repository

    def __getattr__(self, name: str) -> Any:
        """迁移期间只转发 TaskExecutionKernel 公共执行原语。"""

        return getattr(self._kernel, name)


    async def invoke(
        self,
        owner: Any,
        tool_name: str,
        arguments: dict[str, Any],
        call: Callable[[TaskExecutionRuntime], Awaitable[Any]],
        run_context: RunContext | None,
    ) -> Any:
        external_run_id = self.bound_external_run_id(run_context)
        progress_name = tool_name
        spec = TOOL_SPECS[tool_name]
        async with (
            self.task_scheduler(external_run_id) as lock,
            lock.read() if spec.parallel_safe else lock.write(),
        ):
            scope = await self.scope(run_context)
            state = (
                run_context.session_state
                if run_context is not None and isinstance(run_context.session_state, dict)
                else None
            )
            mutation_before = scope.task.mutation_sequence
            admission_rejection = await owner._state_admission_rejection(
                scope,
                tool_name,
                arguments,
                state,
            )
            if admission_rejection is not None:
                return admission_rejection
            args_hash = hashlib.sha256(
                json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str).encode()
            ).hexdigest()
            exempt = (
                progress_name in NO_PROGRESS_EXEMPT_TOOLS
                or tool_name == "finish_task"
                or owner._no_progress_exempt(
                    scope=scope,
                    tool_name=tool_name,
                    arguments=arguments,
                    run_context=run_context,
                )
            )
            async with lock.state():
                progress = (
                    state.get(TASK_EXECUTION_TOOL_PROGRESS_STATE_KEY) if state is not None else None
                )
                entries = (
                    list(progress["entries"])
                    if isinstance(progress, dict)
                    and progress.get("attempt") == scope.attempt_no
                    and progress.get("mutation") == mutation_before
                    and isinstance(progress.get("entries"), list)
                    else []
                )
                previous = next(
                    (
                        entry
                        for entry in reversed(entries)
                        if isinstance(entry, dict)
                        and entry.get("tool") == progress_name
                        and entry.get("argsHash") == args_hash
                    ),
                    None,
                )
                if not exempt and isinstance(previous, dict) and int(previous.get("count", 0)) >= 2:
                    return {
                        "ok": False,
                        "code": "tool_no_progress",
                        "message": "相同工具和参数已连续两次返回相同结果，本次未执行。",
                        "requiredActions": [
                            "修改参数或使用其他只读工具收集新证据。",
                            "先完成真实工作区修改，再重试该调用。",
                        ],
                        "retryable": True,
                    }
            try:
                result = await call(scope)
            except WorkspacePathConflict as error:
                details: dict[str, Any] = {"tool": tool_name}
                suggested_path = suggested_workspace_path(arguments)
                if suggested_path is not None:
                    details["suggestedPath"] = suggested_path
                return {
                    "ok": False,
                    "status": "rejected",
                    "code": "workspace_path_conflict",
                    "message": str(error)[:1000],
                    "details": details,
                    "requiredActions": ["重新读取目标路径及最新哈希后再重试。"],
                    "retryable": True,
                }
            except WorkspaceError as error:
                details = {"tool": tool_name}
                suggested_path = suggested_workspace_path(arguments)
                if suggested_path is not None:
                    details["suggestedPath"] = suggested_path
                return {
                    "ok": False,
                    "status": "rejected",
                    "code": "workspace_error",
                    "message": str(error)[:1000],
                    "details": details,
                    "requiredActions": ["按错误说明修正参数后重试。"],
                    "retryable": True,
                }
            failed_resources = failed_result_resources(arguments, result)
            if state is not None and failed_resources:
                fingerprint = hashlib.sha256(
                    json.dumps(
                        {
                            "exitCode": result.get("exit_code")
                            if isinstance(result, dict)
                            else None,
                            "output": result.get("output") if isinstance(result, dict) else None,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode()
                ).hexdigest()
                async with lock.state():
                    failure_state = state.get(TASK_EXECUTION_TOOL_FAILURE_STATE_KEY)
                    failure_entries = (
                        list(failure_state["entries"])
                        if isinstance(failure_state, dict)
                        and failure_state.get("attempt") == scope.attempt_no
                        and isinstance(failure_state.get("entries"), list)
                        else []
                    )
                    for resource in failed_resources:
                        failure_entries = [
                            entry
                            for entry in failure_entries
                            if not isinstance(entry, dict) or entry.get("resource") != resource
                        ]
                        failure_entries.append({"resource": resource, "fingerprint": fingerprint})
                    state[TASK_EXECUTION_TOOL_FAILURE_STATE_KEY] = {
                        "attempt": scope.attempt_no,
                        "entries": failure_entries[-MAX_TOOL_FAILURE_ENTRIES:],
                    }
            result_hash = hashlib.sha256(
                json.dumps(
                    stable_progress_result(result),
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode()
            ).hexdigest()
            if spec.output_policy == "bounded_text":
                result = await self.bound_tool_result(
                    scope,
                    result,
                    run_context,
                    retain=owner._retain_bounded_tool_result(scope, tool_name),
                    preview_bytes=owner._tool_preview_bytes(scope, tool_name, arguments, result),
                )
            if not exempt and state is not None:
                if spec.effect == "read":
                    mutation_after = mutation_before
                else:
                    latest_snapshot = await self.repository.get_task_snapshot(scope.external_run_id)
                    latest_task = latest_snapshot
                    if latest_task is None:
                        latest_task = await self.repository.get_task(scope.external_run_id)
                    mutation_after = (
                        latest_task.mutation_sequence if latest_task is not None else -1
                    )
                async with lock.state():
                    progress = state.get(TASK_EXECUTION_TOOL_PROGRESS_STATE_KEY)
                    entries = (
                        list(progress["entries"])
                        if isinstance(progress, dict)
                        and progress.get("attempt") == scope.attempt_no
                        and progress.get("mutation") == mutation_after
                        and isinstance(progress.get("entries"), list)
                        else []
                    )
                    previous = next(
                        (
                            entry
                            for entry in reversed(entries)
                            if isinstance(entry, dict)
                            and entry.get("tool") == progress_name
                            and entry.get("argsHash") == args_hash
                        ),
                        None,
                    )
                    same = bool(
                        isinstance(previous, dict)
                        and previous.get("resultHash") == result_hash
                        and mutation_before == mutation_after
                    )
                    entry = {
                        "attempt": scope.attempt_no,
                        "tool": progress_name,
                        "argsHash": args_hash,
                        "resultHash": result_hash,
                        "mutation": mutation_after,
                        "count": int((previous or {}).get("count", 0)) + 1 if same else 1,
                    }
                    if previous in entries:
                        entries.remove(previous)
                    entries.append(entry)
                    state[TASK_EXECUTION_TOOL_PROGRESS_STATE_KEY] = {
                        "attempt": scope.attempt_no,
                        "mutation": mutation_after,
                        "entries": entries[-MAX_TOOL_PROGRESS_ENTRIES:],
                    }
            if tool_name == "finish_task" and isinstance(result, dict) and result.get("ok"):
                await self.cleanup_tool_outputs(scope, run_context)
            return result

