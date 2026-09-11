from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

import pytest
from daytona.common.errors import DaytonaError, DaytonaNotFoundError

from smart_reporting.sandbox import (
    CodeRunRequest,
    DaytonaProvider,
    ExecRequest,
    ExecutionStatus,
    ProviderKind,
    RunPythonScriptRequest,
    SandboxCapabilityUnsupported,
    SandboxNotFound,
    SandboxPolicyDenied,
    SandboxProviderError,
    SessionCommandRequest,
    WorkspaceBinding,
)
from smart_reporting.task_execution.execution import TaskExecutionKernel, TaskExecutionRuntime
from smart_reporting.workspace import WorkspaceService


class MemoryRegistryTransaction:
    def __init__(self, values: dict[str, str], bindings: dict[str, Any]) -> None:
        self.values = values
        self.bindings = bindings

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, resource_id: str) -> None:
        self.values[key] = resource_id

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def set_binding(self, record: Any) -> None:
        self.bindings[record.binding_digest] = record
        self.values[record.binding_digest] = record.resource_id


class MemoryRegistry:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.bindings: dict[str, Any] = {}
        self.generations: dict[str, str] = {}
        self.cleanup_bindings: dict[str, Any] = {}

    @asynccontextmanager
    async def locked(self, key: str):
        yield MemoryRegistryTransaction(self.values, self.bindings)

    async def workspace_label(self, base_label: str) -> str:
        generation = self.generations.get(base_label)
        if generation is None:
            return base_label
        return hashlib.sha256(f"{base_label}:{generation}".encode()).hexdigest()

    async def quarantine_workspace(self, base_label: str, binding_digest: str) -> str:
        record = self.bindings.pop(binding_digest, None)
        self.values.pop(binding_digest, None)
        if record is not None:
            self.cleanup_bindings[binding_digest] = record
        self.generations[base_label] = uuid.uuid4().hex
        return binding_digest

    async def pending_cleanup_bindings(self, limit: int = 20) -> tuple[Any, ...]:
        return tuple(self.cleanup_bindings.values())[:limit]

    async def complete_cleanup(self, binding_digest: str) -> None:
        self.cleanup_bindings.pop(binding_digest, None)


class FakeFileSystem:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def get_file_info(self, path: str) -> Any:
        if path not in self.files:
            raise DaytonaNotFoundError("missing")
        return SimpleNamespace(
            name=path.rsplit("/", 1)[-1], is_dir=False, size=len(self.files[path]), mode="-644"
        )

    async def list_files(self, path: str) -> list[Any]:
        prefix = path.rstrip("/") + "/"
        return [
            SimpleNamespace(
                name=name.removeprefix(prefix), is_dir=False, size=len(content), mode="-644"
            )
            for name, content in self.files.items()
            if name.startswith(prefix) and "/" not in name.removeprefix(prefix)
        ]

    async def create_folder(self, path: str, mode: str) -> None:
        return None

    async def upload_file(self, content: bytes, path: str) -> None:
        self.files[path] = content

    async def download_file(self, path: str) -> bytes:
        return self.files[path]

    async def download_file_stream(self, path: str, timeout: int = 1800):
        yield self.files[path]

    async def delete_file(self, path: str, recursive: bool = False) -> None:
        self.files.pop(path, None)

    async def move_files(self, source: str, destination: str) -> None:
        self.files[destination] = self.files.pop(source)


class FakeProcess:
    def __init__(self) -> None:
        self.sessions: dict[str, SimpleNamespace] = {}
        self.inputs: list[tuple[str, str, str]] = []
        self.code_runs: list[str] = []

    async def exec(self, command: str, cwd: str | None = None, timeout: int | None = None) -> Any:
        return SimpleNamespace(exit_code=0, result=f"exec:{command}")

    async def code_run(self, code: str, params: Any = None, timeout: int | None = None) -> Any:
        self.code_runs.append(code)
        return SimpleNamespace(exit_code=0, result=f"code:{code}")

    async def create_session(self, session_id: str) -> None:
        self.sessions[session_id] = SimpleNamespace(session_id=session_id, commands=[])

    async def list_sessions(self) -> list[Any]:
        return list(self.sessions.values())

    async def get_session(self, session_id: str) -> Any:
        return self.sessions[session_id]

    async def delete_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    async def execute_session_command(
        self, session_id: str, request: Any, timeout: int | None = None
    ) -> Any:
        command = SimpleNamespace(id="command-1", command=request.command, exit_code=None)
        self.sessions[session_id].commands.append(command)
        return SimpleNamespace(cmd_id=command.id, exit_code=None, stdout="started", stderr="")

    async def get_session_command(self, session_id: str, command_id: str) -> Any:
        return next(item for item in self.sessions[session_id].commands if item.id == command_id)

    async def get_session_command_logs(self, session_id: str, command_id: str) -> Any:
        return SimpleNamespace(stdout="out", stderr="err", output=None)

    async def send_session_command_input(self, session_id: str, command_id: str, data: str) -> None:
        self.inputs.append((session_id, command_id, data))


class FakeSandbox:
    def __init__(self, resource_id: str, *, state: str = "started") -> None:
        self.id = resource_id
        self.state = state
        self.fs = FakeFileSystem()
        self.process = FakeProcess()


class FakeDaytonaClient:
    def __init__(self) -> None:
        self.sandboxes: dict[str, FakeSandbox] = {}
        self.created = 0
        self.closed = False
        self.failure_operation: str | None = None
        self.failure: DaytonaError | None = None

    def _raise_failure(self, operation: str) -> None:
        if self.failure_operation == operation and self.failure is not None:
            raise self.failure

    async def get(self, resource_id: str) -> FakeSandbox:
        self._raise_failure("get")
        try:
            return self.sandboxes[resource_id]
        except KeyError as error:
            raise DaytonaNotFoundError("missing") from error

    async def list(self, query: Any = None):
        self._raise_failure("list")
        labels = getattr(query, "labels", None) or {}
        expected = labels.get("agent-thread")
        for sandbox in self.sandboxes.values():
            if expected is None or getattr(sandbox, "binding_label", None) == expected:
                yield sandbox

    async def create(self, params: Any) -> FakeSandbox:
        self.created += 1
        sandbox = FakeSandbox(f"sandbox-{self.created}")
        sandbox.binding_label = params.labels["agent-thread"]
        self.sandboxes[sandbox.id] = sandbox
        return sandbox

    async def start(self, sandbox: FakeSandbox) -> None:
        self._raise_failure("start")
        sandbox.state = "started"

    async def stop(self, sandbox: FakeSandbox) -> None:
        self._raise_failure("stop")
        sandbox.state = "stopped"

    async def delete(self, sandbox: FakeSandbox) -> None:
        self._raise_failure("delete")
        self.sandboxes.pop(sandbox.id, None)

    async def close(self) -> None:
        self.closed = True


def binding(thread_id: str = "thread-1") -> WorkspaceBinding:
    return WorkspaceBinding(
        tenant_id="database-a",
        user_id="user-1",
        company_id="company-1",
        thread_id=thread_id,
        idempotency_key="request-00000001",
    )


@pytest.mark.anyio
async def test_daytona_provider_ensures_one_workspace_per_binding() -> None:
    client = FakeDaytonaClient()
    registry = MemoryRegistry()
    provider = DaytonaProvider(
        client=client,
        registry=registry,
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )

    first = await provider.ensure_workspace(binding())
    second = await provider.ensure_workspace(binding())

    assert first.ref == second.ref
    assert first.ref.provider == ProviderKind.DAYTONA
    assert first.ref.binding_digest != binding().thread_id
    assert client.created == 1
    assert registry.bindings[first.ref.binding_digest].provider == ProviderKind.DAYTONA


@pytest.mark.anyio
async def test_workspace_quarantine_rotates_provider_binding_and_cleans_old_workspace() -> None:
    client = FakeDaytonaClient()
    registry = MemoryRegistry()
    provider = DaytonaProvider(
        client=client,
        registry=registry,
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    workspace = WorkspaceService(
        "0123456789abcdef0123456789abcdef",
        async_registry=registry,
        provider=provider,
    )

    first = await workspace._asandbox_for(None, "thread-1")
    await workspace.aquarantine("thread-1")
    second = await workspace._asandbox_for(None, "thread-1")

    assert second.ref.resource_id != first.ref.resource_id
    assert set(client.sandboxes) == {first.ref.resource_id, second.ref.resource_id}
    assert await workspace.acleanup_quarantined() == 1
    assert set(client.sandboxes) == {second.ref.resource_id}
    assert registry.cleanup_bindings == {}


@pytest.mark.anyio
async def test_workspace_quarantine_cleanup_retries_provider_failure() -> None:
    client = FakeDaytonaClient()
    registry = MemoryRegistry()
    provider = DaytonaProvider(
        client=client,
        registry=registry,
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    workspace = WorkspaceService(
        "0123456789abcdef0123456789abcdef",
        async_registry=registry,
        provider=provider,
    )

    first = await workspace._asandbox_for(None, "thread-1")
    await workspace.aquarantine("thread-1")
    client.failure_operation = "delete"
    client.failure = DaytonaError("temporary backend failure")

    assert await workspace.acleanup_quarantined() == 0
    assert first.ref.resource_id in client.sandboxes
    assert tuple(registry.cleanup_bindings) == (first.ref.binding_digest,)

    client.failure_operation = None
    assert await workspace.acleanup_quarantined() == 1
    assert first.ref.resource_id not in client.sandboxes
    assert registry.cleanup_bindings == {}


@pytest.mark.anyio
async def test_daytona_provider_starts_and_stops_workspace() -> None:
    provider = DaytonaProvider(
        client=FakeDaytonaClient(),
        registry=MemoryRegistry(),
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    handle = await provider.ensure_workspace(binding())

    stopped = await provider.stop_workspace(handle.ref, binding())
    assert stopped.state.value == "stopped"

    started = await provider.start_workspace(handle.ref, binding())
    assert started.state.value == "started"


@pytest.mark.anyio
async def test_daytona_handle_normalizes_files_and_process_results() -> None:
    provider = DaytonaProvider(
        client=FakeDaytonaClient(),
        registry=MemoryRegistry(),
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    handle = await provider.ensure_workspace(binding())

    await handle.fs.upload_file(b"data", "/home/daytona/workspace/data.txt")
    info = await handle.fs.get_file_info("/home/daytona/workspace/data.txt")
    executed = await handle.process.exec(ExecRequest(command="fixed-runner"))
    code = await handle.process.code_run(CodeRunRequest(code="print('ok')"))

    assert info.path == "/home/daytona/workspace/data.txt"
    assert info.size == 4
    assert executed.stdout == "exec:fixed-runner"
    assert executed.status == ExecutionStatus.SUCCEEDED
    assert code.stdout == "code:print('ok')"


@pytest.mark.anyio
async def test_daytona_public_code_run_rejects_cwd() -> None:
    provider = DaytonaProvider(
        client=FakeDaytonaClient(),
        registry=MemoryRegistry(),
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    handle = await provider.ensure_workspace(binding())

    with pytest.raises(SandboxCapabilityUnsupported):
        await handle.process.code_run(CodeRunRequest(code="print('ok')", cwd="analysis"))


@pytest.mark.anyio
async def test_daytona_python_runner_executes_from_workspace_root() -> None:
    client = FakeDaytonaClient()
    provider = DaytonaProvider(
        client=client,
        registry=MemoryRegistry(),
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    handle = await provider.ensure_workspace(binding())
    script = "from pathlib import Path\nprint(Path('data.csv').read_text())\n"

    result = await handle.execution.run_python_script(RunPythonScriptRequest(script=script))

    executed = client.sandboxes[handle.ref.resource_id].process.code_runs[-1]
    assert "chdir('/home/daytona/workspace')" in executed
    assert "Noto Sans CJK SC" in executed
    assert "setdefault('MATPLOTLIBRC'" in executed
    assert "TTCollection" in executed
    assert "fontManager.addfont" in executed
    assert "replace(_reporting_matplotlibrc_temporary, _reporting_matplotlibrc)" in executed
    assert executed.index("setdefault('MATPLOTLIBRC'") < executed.index("exec(compile(")
    assert repr(script) in executed
    assert result.script_hash == hashlib.sha256(script.encode()).hexdigest()


@pytest.mark.anyio
async def test_daytona_python_runner_accepts_public_script_size_boundary() -> None:
    client = FakeDaytonaClient()
    provider = DaytonaProvider(
        client=client,
        registry=MemoryRegistry(),
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    handle = await provider.ensure_workspace(binding())
    script = "#" * (1024 * 1024)

    result = await handle.execution.run_python_script(RunPythonScriptRequest(script=script))

    executed = client.sandboxes[handle.ref.resource_id].process.code_runs[-1]
    assert "chdir('/home/daytona/workspace')" in executed
    assert repr(script) in executed
    assert result.script_hash == hashlib.sha256(script.encode()).hexdigest()


@pytest.mark.anyio
async def test_task_execution_accepts_provider_resource_id() -> None:
    registry = MemoryRegistry()
    provider = DaytonaProvider(
        client=FakeDaytonaClient(),
        registry=registry,
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    workspace = WorkspaceService(
        "0123456789abcdef0123456789abcdef",
        async_registry=registry,
        provider=provider,
    )
    handle = await provider.ensure_workspace(await workspace._provider_binding("thread-1"))
    scope = TaskExecutionRuntime(
        task=cast(Any, SimpleNamespace()),
        external_run_id="external-run",
        internal_run_id="internal-run",
        owner_user_id="user-1",
        thread_id="thread-1",
        sandbox_id=handle.ref.resource_id,
        lease_owner="lease-owner",
        lease_epoch=1,
        attempt_no=0,
    )
    kernel = TaskExecutionKernel(workspace, cast(Any, SimpleNamespace()))

    resolved = [sandbox async for sandbox in kernel._sandbox(scope)]

    assert len(resolved) == 1
    assert resolved[0].ref.resource_id == scope.sandbox_id


@pytest.mark.anyio
async def test_task_execution_stores_retained_output_with_provider_process_contract() -> None:
    client = FakeDaytonaClient()
    registry = MemoryRegistry()
    provider = DaytonaProvider(
        client=client,
        registry=registry,
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    workspace = WorkspaceService(
        "0123456789abcdef0123456789abcdef",
        async_registry=registry,
        provider=provider,
    )
    handle = await provider.ensure_workspace(await workspace._provider_binding("thread-1"))
    scope = TaskExecutionRuntime(
        task=cast(Any, SimpleNamespace()),
        external_run_id="report-coding-analysis-1",
        internal_run_id="internal-run",
        owner_user_id="user-1",
        thread_id="thread-1",
        sandbox_id=handle.ref.resource_id,
        lease_owner="lease-owner",
        lease_epoch=1,
        attempt_no=0,
    )
    kernel = TaskExecutionKernel(workspace, cast(Any, SimpleNamespace()))
    run_context = cast(Any, SimpleNamespace(session_state={}))

    result = await kernel.bound_tool_result(
        scope,
        {"output": "analysis-result"},
        run_context,
        retain=True,
    )

    assert result["outputStoredBytes"] == len(b"analysis-result")
    assert b"analysis-result" in client.sandboxes[handle.ref.resource_id].fs.files.values()


@pytest.mark.anyio
async def test_daytona_handle_normalizes_session_commands_and_logs() -> None:
    provider = DaytonaProvider(
        client=FakeDaytonaClient(),
        registry=MemoryRegistry(),
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    handle = await provider.ensure_workspace(binding())

    session_ref = await handle.process.create_session("session-1")
    command = await handle.process.execute_session_command(
        "session-1", SessionCommandRequest(command="fixed-runner", run_async=True)
    )
    logs = await handle.process.get_session_command_logs("session-1", command.command_id)
    await handle.process.send_session_command_input("session-1", command.command_id, "input")

    assert session_ref.provider_session_id == "session-1"
    assert command.status == ExecutionStatus.RUNNING
    assert logs.stdout == "out"
    assert logs.stderr == "err"
    assert logs.next_offset == len(b"outerr")


@pytest.mark.anyio
async def test_daytona_provider_rejects_binding_mismatch_before_backend_access() -> None:
    client = FakeDaytonaClient()
    provider = DaytonaProvider(
        client=client,
        registry=MemoryRegistry(),
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    handle = await provider.ensure_workspace(binding())

    with pytest.raises(SandboxPolicyDenied):
        await provider.get_workspace(handle.ref, binding("other-thread"))


@pytest.mark.anyio
async def test_daytona_provider_normalizes_missing_workspace() -> None:
    provider = DaytonaProvider(
        client=FakeDaytonaClient(),
        registry=MemoryRegistry(),
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    handle = await provider.ensure_workspace(binding())
    await provider.destroy_workspace(handle.ref, binding())

    with pytest.raises(SandboxNotFound):
        await provider.get_workspace(handle.ref, binding())


@pytest.mark.anyio
async def test_daytona_provider_does_not_close_injected_client() -> None:
    client = FakeDaytonaClient()
    provider = DaytonaProvider(
        client=client,
        registry=MemoryRegistry(),
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )

    await provider.aclose()

    assert client.closed is False


@pytest.mark.anyio
async def test_daytona_process_error_is_normalized() -> None:
    client = FakeDaytonaClient()
    provider = DaytonaProvider(
        client=client,
        registry=MemoryRegistry(),
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    handle = await provider.ensure_workspace(binding())

    async def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise DaytonaError("secret backend detail")

    client.sandboxes[handle.ref.resource_id].process.exec = fail

    with pytest.raises(SandboxProviderError) as raised:
        await handle.process.exec(ExecRequest(command="fixed-runner"))

    assert raised.value.details == {"backend": "daytona", "error_type": "DaytonaError"}
    assert "secret backend detail" not in str(raised.value)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("provider_operation", "sdk_operation"),
    [
        ("ensure_list", "list"),
        ("list_workspaces", "list"),
        ("ensure_get", "get"),
        ("ensure_start", "start"),
        ("start_workspace", "start"),
        ("stop_workspace", "stop"),
        ("destroy_get", "get"),
        ("destroy_delete", "delete"),
    ],
)
async def test_daytona_provider_normalizes_lifecycle_errors(
    provider_operation: str, sdk_operation: str
) -> None:
    client = FakeDaytonaClient()
    provider = DaytonaProvider(
        client=client,
        registry=MemoryRegistry(),
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    handle = None
    if provider_operation != "ensure_list":
        handle = await provider.ensure_workspace(binding())
    if provider_operation == "ensure_start":
        assert handle is not None
        client.sandboxes[handle.ref.resource_id].state = "stopped"
    client.failure_operation = sdk_operation
    client.failure = DaytonaError("secret backend detail")

    with pytest.raises(SandboxProviderError) as raised:
        if provider_operation in {"ensure_list", "ensure_get", "ensure_start"}:
            await provider.ensure_workspace(binding())
        elif provider_operation == "list_workspaces":
            await provider.list_workspaces(binding())
        elif provider_operation == "start_workspace":
            assert handle is not None
            await provider.start_workspace(handle.ref, binding())
        elif provider_operation == "stop_workspace":
            assert handle is not None
            await provider.stop_workspace(handle.ref, binding())
        else:
            assert handle is not None
            await provider.destroy_workspace(handle.ref, binding())

    assert raised.value.details == {"backend": "daytona", "error_type": "DaytonaError"}
    assert "secret backend detail" not in str(raised.value)


@pytest.mark.anyio
@pytest.mark.parametrize("sdk_operation", ["start", "stop", "delete"])
async def test_daytona_provider_normalizes_lifecycle_not_found(
    sdk_operation: str,
) -> None:
    client = FakeDaytonaClient()
    provider = DaytonaProvider(
        client=client,
        registry=MemoryRegistry(),
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    handle = await provider.ensure_workspace(binding())
    client.failure_operation = sdk_operation
    client.failure = DaytonaNotFoundError("missing")

    with pytest.raises(SandboxNotFound):
        if sdk_operation == "start":
            await provider.start_workspace(handle.ref, binding())
        elif sdk_operation == "stop":
            await provider.stop_workspace(handle.ref, binding())
        else:
            await provider.destroy_workspace(handle.ref, binding())


@pytest.mark.anyio
async def test_daytona_provider_destroy_missing_workspace_remains_idempotent() -> None:
    client = FakeDaytonaClient()
    provider = DaytonaProvider(
        client=client,
        registry=MemoryRegistry(),
        snapshot="sandbox-tools",
        binding_secret=b"0123456789abcdef0123456789abcdef",
    )
    handle = await provider.ensure_workspace(binding())
    client.sandboxes.pop(handle.ref.resource_id)

    result = await provider.destroy_workspace(handle.ref, binding())

    assert result.deleted is False
