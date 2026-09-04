from __future__ import annotations

from collections.abc import AsyncIterator
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_HEX_DIGEST_PATTERN = r"^[0-9a-f]{64}$"


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderKind(StrEnum):
    DAYTONA = "daytona"
    LOCAL = "local"


class IsolationKind(StrEnum):
    PROVIDER_MANAGED = "provider_managed"
    LINUX_PROCESS = "linux_process"


class SandboxState(StrEnum):
    STARTING = "starting"
    STARTED = "started"
    STOPPED = "stopped"
    FAILED = "failed"


class ExecutionStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"


class WorkspaceBinding(_Contract):
    tenant_id: str = Field(min_length=1, max_length=256)
    user_id: str = Field(min_length=1, max_length=256)
    company_id: str = Field(min_length=1, max_length=256)
    thread_id: str = Field(min_length=1, max_length=256)
    idempotency_key: str = Field(min_length=16, max_length=256)
    profile: str | None = Field(default=None, min_length=1, max_length=64)


class SandboxRef(_Contract):
    provider: ProviderKind
    isolation: IsolationKind
    node: str | None = Field(default=None, min_length=1, max_length=256)
    resource_id: str = Field(min_length=1, max_length=256)
    generation: int = Field(ge=1)
    binding_digest: str = Field(pattern=_HEX_DIGEST_PATTERN)
    dependency_bundle_digest: str | None = Field(default=None, pattern=_SHA256_PATTERN)


class SessionRef(_Contract):
    sandbox_ref: SandboxRef
    provider_session_id: str = Field(min_length=1, max_length=256)


class ProviderCapabilities(_Contract):
    persistent_sessions: bool
    pty: bool
    network_policy: bool
    branch_copy: bool
    resource_limits: bool
    snapshots: bool


class ProviderHealth(_Contract):
    healthy: bool
    provider: ProviderKind
    message: str = Field(min_length=1, max_length=1000)
    node: str | None = Field(default=None, min_length=1, max_length=256)


class DestroyResult(_Contract):
    deleted: bool


class SandboxSummary(_Contract):
    ref: SandboxRef
    state: SandboxState


class FileInfo(_Contract):
    name: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=1024)
    is_dir: bool
    size: int = Field(default=0, ge=0)
    mode: str | None = Field(default=None, max_length=16)


def _relative_workspace_path(value: str) -> str:
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("工作目录包含控制字符")
    normalized = value.replace("\\", "/")
    if len(normalized) >= 2 and normalized[0].isalpha() and normalized[1] == ":":
        raise ValueError("工作目录必须是 workspace 相对路径")
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("工作目录必须是 workspace 相对路径")
    return "/".join(part for part in candidate.parts if part not in {"", "."})


class ExecRequest(_Contract):
    command: str = Field(min_length=1, max_length=1024 * 1024)
    cwd: str = Field(default="", max_length=1024)
    timeout: int = Field(default=60, ge=1, le=24 * 60 * 60)
    run_async: bool = False

    _validate_cwd = field_validator("cwd")(_relative_workspace_path)


class CodeRunRequest(_Contract):
    code: str = Field(min_length=1, max_length=1024 * 1024)
    cwd: str = Field(default="", max_length=1024)
    timeout: int = Field(default=60, ge=1, le=24 * 60 * 60)

    _validate_cwd = field_validator("cwd")(_relative_workspace_path)


class ExecResult(_Contract):
    status: ExecutionStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""


class SessionSummary(_Contract):
    session_id: str = Field(min_length=1, max_length=256)
    status: ExecutionStatus


class SessionCommandRequest(_Contract):
    command: str = Field(min_length=1, max_length=1024 * 1024)
    run_async: bool = False
    suppress_input_echo: bool = False


class CommandResult(_Contract):
    command_id: str = Field(min_length=1, max_length=256)
    status: ExecutionStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""


class CommandLogs(_Contract):
    stdout: str = ""
    stderr: str = ""
    offset: int = Field(default=0, ge=0)
    next_offset: int = Field(default=0, ge=0)
    has_more: bool = False


class RunPythonScriptRequest(_Contract):
    script: str = Field(min_length=1, max_length=1024 * 1024)
    cwd: str = Field(default="", max_length=1024)
    timeout_ms: int = Field(default=60_000, ge=1, le=24 * 60 * 60 * 1000)
    output_limit_bytes: int = Field(default=64 * 1024, ge=1, le=4 * 1024 * 1024)

    _validate_cwd = field_validator("cwd")(_relative_workspace_path)


class RunPythonScriptResult(_Contract):
    status: ExecutionStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    script_hash: str = Field(pattern=_HEX_DIGEST_PATTERN)
    dependency_bundle_digest: str | None = Field(default=None, pattern=_SHA256_PATTERN)


class FileSystemApi(Protocol):
    async def get_file_info(self, path: str) -> FileInfo: ...

    async def list_files(self, path: str) -> list[FileInfo]: ...

    async def create_folder(self, path: str, mode: str) -> None: ...

    async def upload_file(self, content: bytes, path: str) -> None: ...

    async def download_file(self, path: str) -> bytes: ...

    async def download_file_stream(self, path: str, timeout: int) -> AsyncIterator[bytes]: ...

    async def delete_file(self, path: str, recursive: bool = False) -> None: ...

    async def move_files(self, source: str, destination: str) -> None: ...


class ProcessApi(Protocol):
    async def exec(self, request: ExecRequest) -> ExecResult: ...

    async def code_run(self, request: CodeRunRequest) -> ExecResult: ...

    async def create_session(self, session_id: str) -> SessionRef: ...

    async def list_sessions(self) -> list[SessionSummary]: ...

    async def get_session(self, session_id: str) -> SessionSummary: ...

    async def delete_session(self, session_id: str) -> None: ...

    async def execute_session_command(
        self, session_id: str, request: SessionCommandRequest
    ) -> CommandResult: ...

    async def get_session_command(self, session_id: str, command_id: str) -> CommandResult: ...

    async def get_session_command_logs(self, session_id: str, command_id: str) -> CommandLogs: ...

    async def send_session_command_input(
        self, session_id: str, command_id: str, data: str
    ) -> None: ...


class ExecutionApi(Protocol):
    async def run_python_script(self, request: RunPythonScriptRequest) -> RunPythonScriptResult: ...


class SandboxHandle(Protocol):
    ref: SandboxRef
    fs: FileSystemApi
    process: ProcessApi
    execution: ExecutionApi


class SandboxProvider(Protocol):
    async def ensure_workspace(self, binding: WorkspaceBinding) -> SandboxHandle: ...

    async def get_workspace(self, ref: SandboxRef, binding: WorkspaceBinding) -> SandboxHandle: ...

    async def list_workspaces(self, binding: WorkspaceBinding) -> list[SandboxSummary]: ...

    async def start_workspace(
        self, ref: SandboxRef, binding: WorkspaceBinding
    ) -> SandboxHandle: ...

    async def stop_workspace(self, ref: SandboxRef, binding: WorkspaceBinding) -> SandboxHandle: ...

    async def destroy_workspace(
        self, ref: SandboxRef, binding: WorkspaceBinding
    ) -> DestroyResult: ...

    async def health_check(self) -> ProviderHealth: ...

    async def capabilities(self) -> ProviderCapabilities: ...

    async def aclose(self) -> None: ...
