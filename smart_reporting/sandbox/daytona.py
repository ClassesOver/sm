from __future__ import annotations

import hashlib
import hmac
import inspect
import math
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, cast

from daytona import (
    AsyncDaytona,
    CodeRunParams,
    CreateSandboxFromSnapshotParams,
    ListSandboxesQuery,
    SessionExecuteRequest,
)
from daytona.common.errors import DaytonaError, DaytonaNotFoundError

from .contracts import (
    CodeRunRequest,
    CommandLogs,
    CommandResult,
    DestroyResult,
    ExecRequest,
    ExecResult,
    ExecutionStatus,
    FileInfo,
    IsolationKind,
    ProviderCapabilities,
    ProviderHealth,
    ProviderKind,
    RunPythonScriptRequest,
    RunPythonScriptResult,
    SandboxRef,
    SandboxState,
    SandboxSummary,
    SessionCommandRequest,
    SessionRef,
    SessionSummary,
    WorkspaceBinding,
    binding_digest,
)
from .errors import (
    SandboxCapabilityUnsupported,
    SandboxNotFound,
    SandboxPolicyDenied,
    SandboxProviderError,
)
from .matplotlib_defaults import matplotlib_bootstrap
from .python_runner import bounded_python_output
from .registry import SandboxBindingRecord

DAYTONA_WORKSPACE_ROOT = "/home/daytona/workspace"
_STARTING_STATES = {
    "creating",
    "restoring",
    "starting",
    "pending_build",
    "building_snapshot",
    "pulling_snapshot",
    "resuming",
}


def _target_code_execution(source: str) -> str:
    """执行动态源码，并确保 traceback 使用目标源码而非外层包装。"""

    return (
        "import linecache as _reporting_linecache\n"
        "import traceback as _reporting_traceback\n"
        f"_reporting_source = {source!r}\n"
        "_reporting_filename = '<target_code>'\n"
        "_reporting_linecache.cache[_reporting_filename] = (\n"
        "    len(_reporting_source),\n"
        "    None,\n"
        "    _reporting_source.splitlines(keepends=True),\n"
        "    _reporting_filename,\n"
        ")\n"
        "try:\n"
        "    exec(compile(_reporting_source, _reporting_filename, 'exec'), globals(), globals())\n"
        "except Exception as _reporting_error:\n"
        "    _reporting_traceback.print_exception(_reporting_error)\n"
        "    raise SystemExit(1) from None\n"
    )


async def _daytona_call[T](
    operation: Awaitable[T],
    *,
    action: str,
    missing_message: str | None = None,
) -> T:
    try:
        return await operation
    except DaytonaNotFoundError as error:
        raise SandboxNotFound(missing_message or "Daytona 资源不存在。") from error
    except DaytonaError as error:
        raise SandboxProviderError(
            f"Daytona {action}失败。",
            retryable=True,
            details={"backend": "daytona", "error_type": type(error).__name__},
        ) from error


async def _daytona_list[T](
    operation: AsyncIterator[T],
    *,
    action: str,
    missing_message: str | None = None,
) -> list[T]:
    async def collect() -> list[T]:
        return [value async for value in operation]

    return await _daytona_call(
        collect(),
        action=action,
        missing_message=missing_message,
    )


def _state(value: Any) -> SandboxState:
    raw = str(getattr(value, "value", value) or "").lower()
    if raw == "started":
        return SandboxState.STARTED
    if raw in {"stopped", "archived"}:
        return SandboxState.STOPPED
    if raw in _STARTING_STATES:
        return SandboxState.STARTING
    return SandboxState.FAILED


def _execution_status(exit_code: int | None) -> ExecutionStatus:
    if exit_code is None:
        return ExecutionStatus.RUNNING
    return ExecutionStatus.SUCCEEDED if exit_code == 0 else ExecutionStatus.FAILED


def _workspace_cwd(value: str) -> str:
    return DAYTONA_WORKSPACE_ROOT + (f"/{value}" if value else "")


class DaytonaFileSystemApi:
    def __init__(self, filesystem: Any) -> None:
        self._filesystem = filesystem

    @staticmethod
    def _info(value: Any, path: str) -> FileInfo:
        return FileInfo(
            name=str(getattr(value, "name", "") or path.rsplit("/", 1)[-1]),
            path=path,
            is_dir=bool(getattr(value, "is_dir", False)),
            size=max(0, int(getattr(value, "size", 0) or 0)),
            mode=str(getattr(value, "mode", "") or "") or None,
        )

    async def get_file_info(self, path: str) -> FileInfo:
        value = await _daytona_call(
            self._filesystem.get_file_info(path),
            action="文件查询",
            missing_message="sandbox 文件不存在。",
        )
        return self._info(value, path)

    async def list_files(self, path: str) -> list[FileInfo]:
        values = await _daytona_call(
            self._filesystem.list_files(path),
            action="目录查询",
            missing_message="sandbox 目录不存在。",
        )
        prefix = path.rstrip("/")
        return [self._info(value, f"{prefix}/{getattr(value, 'name', '')}") for value in values]

    async def create_folder(self, path: str, mode: str) -> None:
        await _daytona_call(self._filesystem.create_folder(path, mode), action="目录创建")

    async def upload_file(self, content: bytes, path: str, *, timeout: int | None = None) -> None:
        kwargs = {} if timeout is None else {"timeout": timeout}
        await _daytona_call(
            self._filesystem.upload_file(content, path, **kwargs), action="文件上传"
        )

    async def download_file(self, path: str) -> bytes:
        content = await _daytona_call(
            self._filesystem.download_file(path),
            action="文件下载",
            missing_message="sandbox 文件不存在。",
        )
        if not isinstance(content, bytes):
            raise SandboxNotFound("sandbox 文件不存在。")
        return content

    async def download_file_stream(self, path: str, timeout: int) -> AsyncIterator[bytes]:
        async def stream() -> AsyncIterator[bytes]:
            try:
                source = self._filesystem.download_file_stream(path, timeout=timeout)
                if inspect.isawaitable(source):
                    source = await source
                async for chunk in source:
                    yield chunk
            except DaytonaNotFoundError as error:
                raise SandboxNotFound("sandbox 文件不存在。") from error
            except DaytonaError as error:
                raise SandboxProviderError(
                    "Daytona 文件流下载失败。",
                    retryable=True,
                    details={"backend": "daytona", "error_type": type(error).__name__},
                ) from error

        return stream()

    async def delete_file(self, path: str, recursive: bool = False) -> None:
        await _daytona_call(
            self._filesystem.delete_file(path, recursive=recursive),
            action="文件删除",
            missing_message="sandbox 文件不存在。",
        )

    async def move_files(self, source: str, destination: str) -> None:
        await _daytona_call(
            self._filesystem.move_files(source, destination),
            action="文件移动",
            missing_message="sandbox 文件不存在。",
        )


class DaytonaProcessApi:
    def __init__(self, process: Any, sandbox_ref: SandboxRef) -> None:
        self._process = process
        self._sandbox_ref = sandbox_ref

    async def exec(self, request: ExecRequest) -> ExecResult:
        if request.run_async:
            raise SandboxCapabilityUnsupported("exec_run_async")
        value = await _daytona_call(
            self._process.exec(
                request.command,
                cwd=_workspace_cwd(request.cwd),
                timeout=request.timeout,
            ),
            action="进程执行",
        )
        exit_code = int(value.exit_code)
        return ExecResult(
            status=_execution_status(exit_code),
            exit_code=exit_code,
            stdout=str(getattr(value, "result", "") or ""),
        )

    async def code_run(self, request: CodeRunRequest) -> ExecResult:
        if request.cwd:
            raise SandboxCapabilityUnsupported("code_run_cwd")
        return await self._run_code(request.code, timeout=request.timeout)

    async def _run_code(self, code: str, *, timeout: int) -> ExecResult:
        # 这里只接收本模块两个已校验公开入口产生的源码：code_run 保持 1 MiB
        # 上限，run_python_script 的包装则由同样受限的 script 和 cwd 确定性生成。
        # 不用 CodeRunRequest 二次校验包装结果，否则固定 cwd 前缀会错误拒绝
        # 恰好达到公开 script 上限的合法请求。
        value = await _daytona_call(
            self._process.code_run(
                code,
                params=CodeRunParams(),
                timeout=timeout,
            ),
            action="Python 执行",
        )
        exit_code = int(value.exit_code)
        return ExecResult(
            status=_execution_status(exit_code),
            exit_code=exit_code,
            stdout=str(getattr(value, "result", "") or ""),
        )

    async def create_session(self, session_id: str) -> SessionRef:
        await _daytona_call(self._process.create_session(session_id), action="会话创建")
        return SessionRef(sandbox_ref=self._sandbox_ref, provider_session_id=session_id)

    async def list_sessions(self) -> list[SessionSummary]:
        values = await _daytona_call(self._process.list_sessions(), action="会话列表查询")
        return [self._session(value) for value in values]

    async def get_session(self, session_id: str) -> SessionSummary:
        value = await _daytona_call(
            self._process.get_session(session_id),
            action="会话查询",
            missing_message="sandbox 执行会话不存在。",
        )
        return self._session(value)

    async def delete_session(self, session_id: str) -> None:
        await _daytona_call(
            self._process.delete_session(session_id),
            action="会话删除",
            missing_message="sandbox 执行会话不存在。",
        )

    async def execute_session_command(
        self, session_id: str, request: SessionCommandRequest
    ) -> CommandResult:
        value = await _daytona_call(
            self._process.execute_session_command(
                session_id,
                SessionExecuteRequest(
                    command=request.command,
                    run_async=request.run_async,
                    suppress_input_echo=request.suppress_input_echo,
                ),
            ),
            action="会话命令执行",
            missing_message="sandbox 执行会话不存在。",
        )
        return CommandResult(
            command_id=str(value.cmd_id),
            status=_execution_status(value.exit_code),
            exit_code=value.exit_code,
            stdout=str(getattr(value, "stdout", "") or getattr(value, "output", "") or ""),
            stderr=str(getattr(value, "stderr", "") or ""),
        )

    async def get_session_command(self, session_id: str, command_id: str) -> CommandResult:
        value = await _daytona_call(
            self._process.get_session_command(session_id, command_id),
            action="会话命令查询",
            missing_message="sandbox 执行命令不存在。",
        )
        return CommandResult(
            command_id=str(value.id),
            status=_execution_status(value.exit_code),
            exit_code=value.exit_code,
        )

    async def get_session_command_logs(self, session_id: str, command_id: str) -> CommandLogs:
        value = await _daytona_call(
            self._process.get_session_command_logs(session_id, command_id),
            action="会话日志查询",
            missing_message="sandbox 执行命令不存在。",
        )
        stdout = str(getattr(value, "stdout", "") or getattr(value, "output", "") or "")
        stderr = str(getattr(value, "stderr", "") or "")
        size = len(stdout.encode()) + len(stderr.encode())
        return CommandLogs(stdout=stdout, stderr=stderr, next_offset=size)

    async def send_session_command_input(self, session_id: str, command_id: str, data: str) -> None:
        await _daytona_call(
            self._process.send_session_command_input(session_id, command_id, data),
            action="会话输入",
            missing_message="sandbox 执行命令不存在。",
        )

    @staticmethod
    def _session(value: Any) -> SessionSummary:
        commands = list(getattr(value, "commands", ()) or ())
        exit_codes = [getattr(command, "exit_code", None) for command in commands]
        status = (
            ExecutionStatus.RUNNING
            if any(exit_code is None for exit_code in exit_codes)
            else ExecutionStatus.FAILED
            if any(exit_code != 0 for exit_code in exit_codes)
            else ExecutionStatus.SUCCEEDED
        )
        return SessionSummary(session_id=str(value.session_id), status=status)


class DaytonaExecutionApi:
    def __init__(self, process: DaytonaProcessApi) -> None:
        self._process = process

    async def run_python_script(self, request: RunPythonScriptRequest) -> RunPythonScriptResult:
        workspace_cwd = (
            f"{DAYTONA_WORKSPACE_ROOT}/{request.cwd}" if request.cwd else DAYTONA_WORKSPACE_ROOT
        )
        # Daytona code_run 没有 cwd 参数，而 provider-neutral 契约把空 cwd 定义为
        # workspace 根。工作目录必须由服务端固定后再执行原始源码，否则模型获得的
        # 工作区相对路径会相对于 Daytona 默认目录解析，合法输入文件也无法读取。
        script = (
            matplotlib_bootstrap("/tmp/reporting-matplotlib")
            + f"_reporting_os.chdir({workspace_cwd!r})\n"
            + _target_code_execution(request.script)
        )
        result = await self._process._run_code(
            script,
            timeout=max(1, math.ceil(request.timeout_ms / 1000)),
        )
        stdout, stdout_truncated = bounded_python_output(
            result.stdout, request.output_limit_bytes
        )
        stderr, stderr_truncated = bounded_python_output(
            result.stderr, request.output_limit_bytes
        )
        return RunPythonScriptResult(
            status=result.status,
            exit_code=result.exit_code,
            stdout=stdout,
            stderr=stderr,
            output_truncated=stdout_truncated or stderr_truncated,
            script_hash=hashlib.sha256(request.script.encode()).hexdigest(),
        )


@dataclass(frozen=True)
class DaytonaSandboxHandle:
    ref: SandboxRef
    state: SandboxState
    fs: DaytonaFileSystemApi
    process: DaytonaProcessApi
    execution: DaytonaExecutionApi

    @classmethod
    def from_sandbox(cls, sandbox: Any, ref: SandboxRef) -> DaytonaSandboxHandle:
        process = DaytonaProcessApi(sandbox.process, ref)
        return cls(
            ref=ref,
            state=_state(getattr(sandbox, "state", None)),
            fs=DaytonaFileSystemApi(sandbox.fs),
            process=process,
            execution=DaytonaExecutionApi(process),
        )


class DaytonaProvider:
    def __init__(
        self,
        *,
        registry: Any,
        snapshot: str,
        binding_secret: bytes,
        client: Any | None = None,
        network_allow_list: str | None = None,
    ) -> None:
        self._registry = registry
        self._snapshot = snapshot
        self._binding_secret = binding_secret
        self._client_value = client
        self._owns_client = client is None
        self._network_allow_list = network_allow_list

    @property
    def _client(self) -> Any:
        # Daytona SDK 构造时立即读取凭据。延迟到首次真实操作，避免仅导入
        # AgentOS 应用或执行纯配置检查时产生外部依赖副作用。
        if self._client_value is None:
            self._client_value = AsyncDaytona()
        return self._client_value

    def _digest(self, binding: WorkspaceBinding) -> str:
        if len(self._binding_secret) < 32:
            raise SandboxPolicyDenied(
                "sandbox binding secret 未安全配置。", reason="invalid_binding_secret"
            )
        return binding_digest(binding, self._binding_secret)

    def _ref(self, sandbox: Any, binding: WorkspaceBinding) -> SandboxRef:
        return SandboxRef(
            provider=ProviderKind.DAYTONA,
            isolation=IsolationKind.PROVIDER_MANAGED,
            resource_id=str(sandbox.id),
            generation=1,
            binding_digest=self._digest(binding),
        )

    def _require_binding(self, ref: SandboxRef, binding: WorkspaceBinding) -> None:
        if ref.provider != ProviderKind.DAYTONA or not hmac.compare_digest(
            ref.binding_digest, self._digest(binding)
        ):
            raise SandboxPolicyDenied("sandbox 资源不属于当前请求范围。", reason="binding_mismatch")

    async def _get_raw(self, resource_id: str) -> Any:
        try:
            return await self._client.get(resource_id)
        except DaytonaNotFoundError as error:
            raise SandboxNotFound("Daytona workspace 不存在。") from error
        except DaytonaError as error:
            raise SandboxProviderError(
                "Daytona workspace 查询失败。",
                retryable=True,
                details={"backend": "daytona", "error_type": type(error).__name__},
            ) from error

    async def ensure_workspace(self, binding: WorkspaceBinding) -> DaytonaSandboxHandle:
        digest = self._digest(binding)
        async with self._registry.locked(digest) as registry:
            resource_id = await registry.get(digest)
            sandbox = None
            if resource_id is not None:
                try:
                    sandbox = await _daytona_call(
                        self._client.get(resource_id),
                        action="workspace 查询",
                        missing_message="Daytona workspace 不存在。",
                    )
                except SandboxNotFound:
                    await registry.delete(digest)
            if sandbox is None:
                matches = await _daytona_list(
                    self._client.list(ListSandboxesQuery(labels={"agent-thread": digest}, limit=2)),
                    action="workspace 列表查询",
                )
                if len(matches) > 1:
                    raise SandboxProviderError("当前绑定关联了多个 Daytona workspace。")
                sandbox = matches[0] if matches else await self._create(digest)
                ref = self._ref(sandbox, binding)
                await registry.set_binding(
                    SandboxBindingRecord(
                        binding_digest=ref.binding_digest,
                        provider=ref.provider,
                        isolation=ref.isolation,
                        node=ref.node,
                        resource_id=ref.resource_id,
                        generation=ref.generation,
                        dependency_bundle_digest=ref.dependency_bundle_digest,
                    )
                )
        if _state(sandbox.state) == SandboxState.STOPPED:
            await _daytona_call(
                self._client.start(sandbox),
                action="workspace 启动",
                missing_message="Daytona workspace 不存在。",
            )
        if _state(sandbox.state) != SandboxState.STARTED:
            raise SandboxProviderError("Daytona workspace 尚未就绪。", retryable=True)
        return DaytonaSandboxHandle.from_sandbox(sandbox, self._ref(sandbox, binding))

    async def _create(self, digest: str) -> Any:
        network = (
            {"network_allow_list": self._network_allow_list}
            if self._network_allow_list
            else {"network_block_all": True}
        )
        try:
            return await self._client.create(
                CreateSandboxFromSnapshotParams(
                    snapshot=self._snapshot,
                    name=f"agent-{digest[:20]}",
                    language="python",
                    labels={"agent-thread": digest},
                    public=False,
                    ephemeral=False,
                    auto_stop_interval=60,
                    auto_archive_interval=0,
                    auto_delete_interval=-1,
                    **network,
                )
            )
        except DaytonaError as error:
            raise SandboxProviderError(
                "Daytona workspace 创建失败。",
                retryable=True,
                details={"backend": "daytona", "error_type": type(error).__name__},
            ) from error

    async def get_workspace(
        self, ref: SandboxRef, binding: WorkspaceBinding
    ) -> DaytonaSandboxHandle:
        self._require_binding(ref, binding)
        sandbox = await self._get_raw(ref.resource_id)
        return DaytonaSandboxHandle.from_sandbox(sandbox, ref)

    async def list_workspaces(self, binding: WorkspaceBinding) -> list[SandboxSummary]:
        digest = self._digest(binding)
        return [
            SandboxSummary(ref=self._ref(sandbox, binding), state=_state(sandbox.state))
            for sandbox in await _daytona_list(
                self._client.list(ListSandboxesQuery(labels={"agent-thread": digest})),
                action="workspace 列表查询",
            )
        ]

    async def start_workspace(
        self, ref: SandboxRef, binding: WorkspaceBinding
    ) -> DaytonaSandboxHandle:
        self._require_binding(ref, binding)
        sandbox = await self._get_raw(ref.resource_id)
        await _daytona_call(
            self._client.start(sandbox),
            action="workspace 启动",
            missing_message="Daytona workspace 不存在。",
        )
        return DaytonaSandboxHandle.from_sandbox(sandbox, ref)

    async def stop_workspace(
        self, ref: SandboxRef, binding: WorkspaceBinding
    ) -> DaytonaSandboxHandle:
        self._require_binding(ref, binding)
        sandbox = await self._get_raw(ref.resource_id)
        await _daytona_call(
            self._client.stop(sandbox),
            action="workspace 停止",
            missing_message="Daytona workspace 不存在。",
        )
        return DaytonaSandboxHandle.from_sandbox(sandbox, ref)

    async def destroy_workspace(self, ref: SandboxRef, binding: WorkspaceBinding) -> DestroyResult:
        self._require_binding(ref, binding)
        result = await self.destroy_workspace_ref(ref)
        digest = self._digest(binding)
        async with self._registry.locked(digest) as registry:
            if await registry.get(digest) == ref.resource_id:
                await registry.delete(digest)
        return result

    async def destroy_workspace_ref(self, ref: SandboxRef) -> DestroyResult:
        if ref.provider != ProviderKind.DAYTONA:
            raise SandboxPolicyDenied("sandbox provider 不匹配。", reason="provider_mismatch")
        try:
            sandbox = await _daytona_call(
                self._client.get(ref.resource_id),
                action="workspace 查询",
                missing_message="Daytona workspace 不存在。",
            )
        except SandboxNotFound:
            return DestroyResult(deleted=False)
        await _daytona_call(
            self._client.delete(sandbox),
            action="workspace 删除",
            missing_message="Daytona workspace 不存在。",
        )
        return DestroyResult(deleted=True)

    async def health_check(self) -> ProviderHealth:
        try:
            stream = cast(AsyncGenerator[Any, None], self._client.list(ListSandboxesQuery(limit=1)))
            async with aclosing(stream) as sandboxes:
                async for _sandbox in sandboxes:
                    break
        except DaytonaError as error:
            raise SandboxProviderError(
                "Daytona 健康检查失败。",
                retryable=True,
                details={"backend": "daytona", "error_type": type(error).__name__},
            ) from error
        return ProviderHealth(
            healthy=True,
            provider=ProviderKind.DAYTONA,
            message="Daytona provider 可用。",
        )

    async def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            persistent_sessions=True,
            pty=True,
            network_policy=True,
            branch_copy=True,
            resource_limits=True,
            snapshots=True,
        )

    async def aclose(self) -> None:
        if self._owns_client and self._client_value is not None:
            await self._client_value.close()
