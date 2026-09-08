from types import SimpleNamespace

import pytest
from daytona import SessionExecuteRequest

from smart_reporting.sandbox import (
    CommandResult,
    ExecutionStatus,
    IsolationKind,
    ProviderKind,
    SandboxNotFound,
    SandboxRef,
    SessionCommandRequest,
    SessionRef,
    SessionSummary,
)
from smart_reporting.task_execution.process_runtime import ManagedProcessRuntime
from smart_reporting.tests.workspace_fakes import (
    AsyncFakeClient,
    AsyncFakeProcess,
    AsyncMemoryRegistry,
    service,
)
from smart_reporting.workspace import WorkspaceError, WorkspaceProcessNotFound, WorkspaceService


class ProviderProcess:
    def __init__(self, *, running_sessions: int = 0) -> None:
        self.ref = SandboxRef(
            provider=ProviderKind.DAYTONA,
            isolation=IsolationKind.PROVIDER_MANAGED,
            resource_id="sandbox-1",
            generation=1,
            binding_digest="a" * 64,
        )
        self.sessions = {
            f"agent-exec-{index:032x}": ExecutionStatus.RUNNING for index in range(running_sessions)
        }
        self.commands: dict[tuple[str, str], CommandResult] = {}
        self.request: SessionCommandRequest | None = None

    async def list_sessions(self) -> list[SessionSummary]:
        return [
            SessionSummary(session_id=session_id, status=status)
            for session_id, status in self.sessions.items()
        ]

    async def create_session(self, session_id: str) -> SessionRef:
        self.sessions[session_id] = ExecutionStatus.SUCCEEDED
        return SessionRef(sandbox_ref=self.ref, provider_session_id=session_id)

    async def execute_session_command(
        self, session_id: str, request: SessionCommandRequest
    ) -> CommandResult:
        assert isinstance(request, SessionCommandRequest)
        self.request = request
        self.sessions[session_id] = ExecutionStatus.RUNNING
        result = CommandResult(command_id="command-1", status=ExecutionStatus.RUNNING)
        self.commands[(session_id, result.command_id)] = result
        return result

    async def get_session(self, session_id: str) -> SessionSummary:
        try:
            status = self.sessions[session_id]
        except KeyError as error:
            raise SandboxNotFound("sandbox 执行会话不存在。") from error
        return SessionSummary(session_id=session_id, status=status)

    async def get_session_command(self, session_id: str, command_id: str) -> CommandResult:
        return self.commands[(session_id, command_id)]

    async def delete_session(self, session_id: str) -> None:
        self.sessions.pop(session_id)


def _runtime(tmp_path):
    current = service(tmp_path)
    runtime_service = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    process = AsyncFakeProcess(current.sandbox_for("thread").process)
    return ManagedProcessRuntime(runtime_service), process


@pytest.mark.anyio
async def test_managed_process_runtime_starts_bound_session(tmp_path):
    runtime, process = _runtime(tmp_path)

    session_id, command_id, result = await runtime.start_session(
        process,
        "thread",
        SessionExecuteRequest(command="pytest", run_async=True),
    )

    assert session_id.startswith("agent-exec-")
    assert command_id == "command-1"
    assert result.cmd_id == command_id
    assert await runtime.get_command(process, session_id, command_id)


@pytest.mark.anyio
async def test_managed_process_runtime_uses_provider_session_contract(tmp_path):
    runtime, _process = _runtime(tmp_path)
    process = ProviderProcess()

    session_id, command_id, result = await runtime.start_session(
        process,
        "thread",
        SessionExecuteRequest(command="pytest", run_async=True, suppress_input_echo=True),
    )

    assert command_id == "command-1"
    assert result.command_id == command_id
    assert process.request == SessionCommandRequest(
        command="pytest", run_async=True, suppress_input_echo=True
    )
    assert await runtime.get_command(process, session_id, command_id) == result


@pytest.mark.anyio
async def test_managed_process_runtime_counts_running_provider_sessions(tmp_path):
    runtime, _process = _runtime(tmp_path)
    process = ProviderProcess(running_sessions=4)

    with pytest.raises(WorkspaceError, match="已有 4 个后台进程"):
        await runtime.start_session(
            process,
            "thread",
            SessionExecuteRequest(command="pytest", run_async=True),
        )


@pytest.mark.anyio
async def test_managed_process_runtime_normalizes_missing_provider_session(tmp_path):
    runtime, _process = _runtime(tmp_path)
    process = ProviderProcess()

    with pytest.raises(WorkspaceProcessNotFound, match="不属于当前会话"):
        await runtime.get_command(
            process,
            "agent-exec-" + "a" * 32,
            "command-1",
        )


@pytest.mark.anyio
async def test_managed_process_runtime_rejects_unbound_process_ids(tmp_path):
    runtime, process = _runtime(tmp_path)

    with pytest.raises(WorkspaceError, match="会话标识无效"):
        await runtime.get_command(process, "other-session", "command-1")
    with pytest.raises(WorkspaceProcessNotFound, match="不属于当前会话"):
        await runtime.get_command(process, "agent-exec-" + "a" * 32, "command-1")


def test_managed_process_runtime_preserves_utf8_output_boundaries():
    value = SimpleNamespace(stdout="甲乙\n", stderr="")

    with pytest.raises(WorkspaceError, match="UTF-8 字符"):
        ManagedProcessRuntime.format_output(
            value,
            session_id="session",
            command_id="command",
            status="completed",
            exit_code=0,
            max_bytes=1,
        )

    result = ManagedProcessRuntime.format_output(
        value,
        session_id="session",
        command_id="command",
        status="completed",
        exit_code=0,
        max_bytes=4,
    )

    assert result["output"] == "甲"
    assert result["nextOffset"] == 3
    assert result["hasMore"] is True
