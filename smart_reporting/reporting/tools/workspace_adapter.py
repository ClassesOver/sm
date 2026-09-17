"""现有任务执行内核到 Reporting 工具端口的生产适配。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

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
    WorkspaceService,
)
from .context import ReportingFileRef, ReportingOutputPolicy, ReportingToolContext
from .workspace_port import ReportingWorkspaceError

_DAYTONA_WORKSPACE_PREFIX = "/home/daytona/workspace/"
_DAYTONA_HOME_PREFIX = "/home/daytona/"


class _HostSandboxProcess:
    async def exec(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _HostSandboxFS:
    def __init__(self, service: Any, thread_id: str) -> None:
        self._service = service
        self._thread_id = thread_id

    @staticmethod
    def _relative(path: str) -> str:
        if path.startswith(_DAYTONA_WORKSPACE_PREFIX):
            return path[len(_DAYTONA_WORKSPACE_PREFIX) :]
        if path.startswith(_DAYTONA_HOME_PREFIX):
            return path[len(_DAYTONA_HOME_PREFIX) :]
        return WorkspaceService.normalize_path(path, allow_root=False)[0]

    async def create_folder(self, directory: str, _mode: str | None = None) -> None:
        relative = self._relative(directory)
        if relative:
            await self._service.aensure_directory(self._thread_id, relative)

    async def upload_file(self, content: bytes, path: str) -> None:
        await self._service.awrite_bytes(
            self._thread_id,
            self._relative(path),
            content,
            overwrite=True,
        )

    async def download_file(self, path: str) -> bytes:
        content, _mime = await self._service.afile_bytes(
            self._thread_id, self._relative(path)
        )
        return content

    async def delete_file(self, path: str, recursive: bool = False) -> None:
        await self._service.adelete_file(
            self._thread_id, self._relative(path), recursive=recursive
        )

    async def move_files(self, source: str, destination: str) -> None:
        await self._service.amove_files(
            self._thread_id,
            self._relative(source),
            self._relative(destination),
        )


class _HostSandbox:
    def __init__(self, service: Any, thread_id: str) -> None:
        self.fs = _HostSandboxFS(service, thread_id)
        self.process = _HostSandboxProcess()
        self.id = thread_id
        self.ref = None


def _validate_reporting_content(content: bytes) -> None:
    if not isinstance(content, bytes):
        raise WorkspaceError("文件内容格式无效，请使用二进制内容后重试。")
    if len(content) > MAX_UPLOAD_BYTES:
        raise WorkspaceError("文件内容超过 200 MiB，请缩小文件后重试。")


class WorkspaceServiceReportingPort:
    """按单个已解析 Task scope 绑定的最小工作区端口。"""

    def __init__(
        self,
        service: WorkspaceService,
        kernel: TaskExecutionKernel,
        context: ReportingToolContext,
        scope: Any,
    ) -> None:
        self._service = service
        self._kernel = kernel
        self.context = context
        self._scope = scope

    @staticmethod
    def _normalize(path: str) -> str:
        try:
            return WorkspaceService.normalize_path(path, allow_root=False)[0]
        except WorkspaceError as error:
            raise ReportingWorkspaceError("Reporting 路径无效。") from error

    def _require_output(self, path: str) -> str:
        normalized = self._normalize(path)
        if any(item.path == normalized for item in (*self.context.inputs, *self.context.data)):
            raise ReportingWorkspaceError("Reporting 输入和数据只读。")
        if not self.context.output_policy.allows(normalized):
            raise ReportingWorkspaceError("Reporting 写入目标不在输出目录。")
        return normalized

    async def read_bytes(self, path: str) -> bytes:
        normalized = self._normalize(path)
        content, _mime = await self._service.afile_bytes(self.context.thread_id, normalized)
        return content

    async def read_text(self, path: str) -> str:
        return (await self.read_bytes(path)).decode("utf-8")

    async def hash_files(self, paths: Sequence[str]) -> tuple[ReportingFileRef, ...]:
        values = await self._service.abatch_hash_files(
            self.context.thread_id, [self._normalize(path) for path in paths]
        )
        missing = [item["path"] for item in values if item.get("missing") is True]
        if missing:
            raise ReportingWorkspaceError(f"Reporting 文件不存在：{', '.join(missing)}")
        return tuple(
            ReportingFileRef(path=item["path"], size=item["size"], sha256=item["sha256"])
            for item in values
        )

    async def write_text(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool = False,
        expected_sha256: str | None = None,
    ) -> ReportingFileRef:
        normalized = self._require_output(path)
        raw = content.encode("utf-8")
        _validate_reporting_content(raw)
        result = await self._kernel.patch(
            "overwrite" if overwrite else "create",
            normalized,
            None,
            None,
            False,
            None,
            None,
            content=content,
            expected_sha256=expected_sha256,
            _scope=self._scope,
        )
        if result.get("ok") is not True:
            raise ReportingWorkspaceError("Reporting 文件写入失败。")
        identity = await self._service.ahash_file(self.context.thread_id, normalized)
        return ReportingFileRef(
            path=identity["path"], size=identity["size"], sha256=identity["sha256"]
        )

    async def execute_script(
        self,
        script_path: str,
        *,
        timeout: int,
    ) -> Mapping[str, Any]:
        return await self._kernel.run_python_script(
            script_path, timeout=timeout, _scope=self._scope
        )


class ReportingWorkspaceAdapter:
    """封装 Reporting 已有读写原语，不向领域工具暴露 Daytona client。"""

    def __init__(self, service: WorkspaceService) -> None:
        self._service = service

    normalize_path = staticmethod(WorkspaceService.normalize_path)

    def file_bytes(self, thread_id: str, path: str) -> tuple[bytes, str]:
        return self._service.file_bytes(thread_id, path)

    async def afile_bytes(self, thread_id: str, path: str) -> tuple[bytes, str]:
        return await self._service.afile_bytes(thread_id, path)

    async def aread_text(self, thread_id: str, path: str) -> str:
        return await self._service.aread_text(thread_id, path)

    def read_text(self, thread_id: str, path: str) -> str:
        return self._service.read_text(thread_id, path)

    def validate_content(self, content: bytes) -> None:
        _validate_reporting_content(content)

    async def hash_file(self, thread_id: str, path: str) -> dict[str, Any]:
        return await self._service.ahash_file(thread_id, path)

    async def batch_hash_files(self, thread_id: str, paths: Sequence[str]) -> list[dict[str, Any]]:
        return await self._service.abatch_hash_files(thread_id, list(paths))

    async def probe_python_modules(self, thread_id: str, names: set[str]) -> set[str]:
        if (
            not names
            or len(names) > 100
            or any(re.fullmatch(r"[A-Za-z_]\w*", name) is None for name in names)
        ):
            raise WorkspaceError("Python 依赖探测参数无效。")
        del thread_id
        return {name for name in names if importlib.util.find_spec(name) is not None}

    async def read_limited_regular_file(
        self,
        thread_id: str,
        path: str,
        *,
        max_bytes: int,
    ) -> bytes:
        return await self._service.read_limited_regular_file(
            thread_id, path, max_bytes=max_bytes
        )

    async def inspect_chart_file(self, thread_id: str, path: str) -> dict[str, Any]:
        from ..workspace import inspect_report_chart_file

        return await inspect_report_chart_file(self._service, thread_id=thread_id, path=path)


class WorkspaceServiceReportingRuntime:
    """Reporting 工具的运行时边界；RunContext 只在此处解析。"""

    def __init__(
        self,
        service: WorkspaceService,
        repository: Any,
        *,
        validator_registry: Any = None,
    ) -> None:
        self._kernel = TaskExecutionKernel(
            service,
            repository,
            validator_registry=validator_registry,
        )
        self._kernel.require_finish_verification = False
        self._kernel.evaluate_finish_acceptance = False
        self.workspace = ReportingWorkspaceAdapter(service)
        self._service = service
        self.repository = repository
        if not hasattr(service, "_async_client"):

            async def host_sandbox(scope: Any):
                yield _HostSandbox(service, scope.thread_id)

            self._kernel._sandbox = host_sandbox

    def __getattr__(self, name: str) -> Any:
        """迁移期间只转发 TaskExecutionKernel 公共执行原语。"""

        return getattr(self._kernel, name)

    async def execute_script(
        self,
        script_path: str,
        *,
        timeout: int,
        _scope: TaskExecutionRuntime,
    ) -> dict[str, Any]:
        """将 Reporting 脚本端口映射到执行内核的受限 Python runner。"""

        return await self._kernel.run_python_script(
            script_path,
            timeout=timeout,
            _scope=_scope,
        )

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

    async def context(
        self,
        run_context: RunContext | None,
        *,
        input_snapshot: Mapping[str, Any],
        inputs: Sequence[ReportingFileRef] = (),
        data: Sequence[ReportingFileRef] = (),
        output_policy: ReportingOutputPolicy,
    ) -> ReportingToolContext:
        scope = await self.scope(run_context)
        return ReportingToolContext(
            external_run_id=scope.external_run_id,
            thread_id=scope.thread_id,
            attempt_no=scope.attempt_no,
            output_policy=output_policy,
            input_snapshot=input_snapshot,
            inputs=tuple(inputs),
            data=tuple(data),
        )

    async def workspace_port(
        self,
        run_context: RunContext | None,
        *,
        input_snapshot: Mapping[str, Any],
        inputs: Sequence[ReportingFileRef] = (),
        data: Sequence[ReportingFileRef] = (),
        output_policy: ReportingOutputPolicy,
    ) -> WorkspaceServiceReportingPort:
        scope = await self.scope(run_context)
        context = ReportingToolContext(
            external_run_id=scope.external_run_id,
            thread_id=scope.thread_id,
            attempt_no=scope.attempt_no,
            output_policy=output_policy,
            input_snapshot=input_snapshot,
            inputs=tuple(inputs),
            data=tuple(data),
        )
        return WorkspaceServiceReportingPort(self._service, self._kernel, context, scope)
