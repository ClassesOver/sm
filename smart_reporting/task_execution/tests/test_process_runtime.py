from types import SimpleNamespace

import pytest
from daytona import SessionExecuteRequest

from smart_reporting.task_execution.process_runtime import ManagedProcessRuntime
from smart_reporting.tests.workspace_fakes import (
    AsyncFakeClient,
    AsyncFakeProcess,
    AsyncMemoryRegistry,
    service,
)
from smart_reporting.workspace import WorkspaceError, WorkspaceProcessNotFound, WorkspaceService


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
