import asyncio
from types import SimpleNamespace

import pytest
from agno.run import RunContext
from agno.tools import Function
from daytona.common.errors import DaytonaNotFoundError

from agentos_dev.agent_control import AGENT_PLAN_STATE_KEY
from agentos_dev.coding import CodingScope, Lease
from agentos_dev.coding.execution import (
    CODING_EXECUTION_MIGRATION_STATE_KEY,
    CODING_TASK_DEPENDENCY,
    CodingExecutionKernel,
    WorkspaceCodingToolkit,
)
from agentos_dev.coding.repository import CodingRepositoryError, CodingTaskRepository
from agentos_dev.coding_tools import (
    CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY,
    CODEX_EXEC_SESSIONS_STATE_KEY,
)
from agentos_dev.database import create_agent_database
from agentos_dev.tests.workspace_fakes import (
    AsyncFakeClient,
    AsyncFakeProcess,
    AsyncMemoryRegistry,
    service,
)
from agentos_dev.workspace import MANAGED_PROCESS_PREFIX, WorkspaceService


@pytest.fixture
async def execution_runtime(tmp_path):
    database = create_agent_database(f"sqlite:///{tmp_path / 'agent.db'}")
    repository = CodingTaskRepository(database.async_db)
    synchronous = service(tmp_path)
    workspace = WorkspaceService(
        synchronous.secret,
        client=synchronous.client,
        registry=synchronous.registry,
        async_client=AsyncFakeClient(synchronous.client),
        async_registry=AsyncMemoryRegistry(synchronous.registry.values),
    )
    sandbox_id = str(synchronous.sandbox_for("thread").id)
    task = await repository.create_task_with_initial_attempt(
        CodingScope("external-run", "user", "thread", sandbox_id, "coding-agent"),
        "执行测试任务",
    )
    lease = await repository.claim_lease("external-run", "request-a")
    assert isinstance(lease, Lease)
    task, attempt = await repository.open_initial("external-run", lease, task.state_version)
    context = RunContext(
        run_id=attempt.internal_run_id,
        session_id="thread",
        user_id="user",
        session_state={},
        dependencies={
            CODING_TASK_DEPENDENCY: {
                "externalRunId": "external-run",
                "leaseOwner": "request-a",
                "leaseEpoch": lease.epoch,
                "sandboxId": sandbox_id,
            }
        },
    )
    yield SimpleNamespace(
        database=database,
        repository=repository,
        synchronous=synchronous,
        workspace=workspace,
        kernel=CodingExecutionKernel(workspace, repository),
        context=context,
    )
    await database.async_engine.dispose()
    database.sync_engine.dispose()


def remote_process(runtime):
    return runtime.synchronous.sandbox_for("thread").process


def finish_remote_execution(runtime, execution_id: str, output: str = "ok\n", exit_code: int = 0):
    process = remote_process(runtime)
    session = process.sessions[f"{MANAGED_PROCESS_PREFIX}{execution_id}"]
    command = session.commands[0]
    command.output = f"started{output}"
    command.exit_code = exit_code


@pytest.mark.anyio
async def test_terminal_reserves_before_remote_session_and_poll_survives_kernel_restart(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    observed = []
    original = AsyncFakeProcess.create_session

    async def assert_reserved(process, session_id):
        execution_id = session_id.removeprefix(MANAGED_PROCESS_PREFIX)
        execution = await runtime.repository.get_execution(execution_id)
        observed.append((session_id, execution.status if execution else None))
        return await original(process, session_id)

    monkeypatch.setattr(AsyncFakeProcess, "create_session", assert_reserved)
    started = await runtime.kernel.terminal(
        "pytest -q",
        background=True,
        run_context=runtime.context,
    )

    execution_id = started["execution_id"]
    assert started["session_id"] == execution_id
    assert observed == [(f"{MANAGED_PROCESS_PREFIX}{execution_id}", "reserved")]
    finish_remote_execution(runtime, execution_id)

    restarted = CodingExecutionKernel(runtime.workspace, runtime.repository)
    completed = await restarted.poll(execution_id, runtime.context)
    cached = await restarted.poll(execution_id, runtime.context)

    assert completed["status"] == "completed"
    assert completed["exit_code"] == 0
    assert cached["status_is_cached"] is True
    assert f"{MANAGED_PROCESS_PREFIX}{execution_id}" not in remote_process(runtime).sessions


@pytest.mark.anyio
async def test_terminal_returns_persistent_lost_receipt_when_remote_creation_fails(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime

    async def missing_session(_process, _session_id):
        raise DaytonaNotFoundError("missing")

    monkeypatch.setattr(AsyncFakeProcess, "create_session", missing_session)

    result = await runtime.kernel.terminal(
        "pytest -q",
        background=True,
        run_context=runtime.context,
    )

    assert result["execution_id"]
    assert "session_id" not in result
    assert result["status"] == "lost"
    assert result["code"] == "execution_lost"
    persisted = await runtime.repository.get_execution(result["execution_id"])
    assert persisted is not None and persisted.status == "lost"


@pytest.mark.anyio
async def test_terminal_drains_logs_before_deleting_remote_session(execution_runtime):
    runtime = execution_runtime
    started = await runtime.kernel.terminal("build", background=True, run_context=runtime.context)
    execution_id = started["execution_id"]
    output = "x" * (64 * 1024 + 37)
    finish_remote_execution(runtime, execution_id, output=output)

    first = await runtime.kernel.poll(execution_id, runtime.context)
    assert first["status"] == "draining"
    assert f"{MANAGED_PROCESS_PREFIX}{execution_id}" in remote_process(runtime).sessions

    second = await runtime.kernel.poll(execution_id, runtime.context)
    assert second["status"] == "completed"
    assert second["output_cursor"] == len("started") + len(output)
    assert f"{MANAGED_PROCESS_PREFIX}{execution_id}" not in remote_process(runtime).sessions


@pytest.mark.anyio
async def test_process_terminal_operations_are_idempotent_and_lost_is_persistent(execution_runtime):
    runtime = execution_runtime
    started = await runtime.kernel.terminal("serve", background=True, run_context=runtime.context)
    execution_id = started["execution_id"]

    killed = await runtime.kernel.process("kill", execution_id, "", 30, runtime.context)
    killed_again = await runtime.kernel.process("kill", execution_id, "", 30, runtime.context)
    write = await runtime.kernel.process("write", execution_id, "input", 30, runtime.context)

    assert killed["status"] == "terminated"
    assert killed_again["status_is_cached"] is True
    assert write["code"] == "execution_terminal"

    other = await runtime.kernel.terminal("watch", background=True, run_context=runtime.context)
    other_id = other["execution_id"]
    remote_process(runtime).sessions.pop(f"{MANAGED_PROCESS_PREFIX}{other_id}")
    lost = await runtime.kernel.poll(other_id, runtime.context)
    lost_again = await runtime.kernel.poll(other_id, runtime.context)

    assert lost["status"] == "lost"
    assert lost["code"] == "execution_lost"
    assert lost_again["status_is_cached"] is True


@pytest.mark.anyio
async def test_concurrent_poll_persists_terminal_output_once(execution_runtime):
    runtime = execution_runtime
    started = await runtime.kernel.terminal("test", background=True, run_context=runtime.context)
    execution_id = started["execution_id"]
    finish_remote_execution(runtime, execution_id, output="one result\n")

    results = await asyncio.gather(
        runtime.kernel.poll(execution_id, runtime.context),
        runtime.kernel.poll(execution_id, runtime.context),
    )
    stored = await runtime.repository.get_execution(execution_id)

    assert all(result["status"] == "completed" for result in results)
    assert stored is not None
    assert stored.terminal_output == "startedone result\n"


@pytest.mark.anyio
async def test_execution_rejects_cross_user_and_imports_legacy_handles_once(execution_runtime):
    runtime = execution_runtime
    runtime.context.session_state = {
        CODEX_EXEC_SESSIONS_STATE_KEY: {
            "1": {
                "thread": "thread",
                "user_id": "user",
                "session_id": f"{MANAGED_PROCESS_PREFIX}{'a' * 32}",
                "command_id": "command-1",
                "offset": 17,
            }
        },
        CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY: {
            "2": {
                "thread": "thread",
                "user_id": "user",
                "reason": "completed",
            }
        },
    }

    first = await runtime.kernel.process("list", None, "", 30, runtime.context)
    second = await CodingExecutionKernel(runtime.workspace, runtime.repository).process(
        "list", None, "", 30, runtime.context
    )

    assert runtime.context.session_state[CODING_EXECUTION_MIGRATION_STATE_KEY] is True
    assert len(first["processes"]) == len(second["processes"]) == 2
    assert {item["status"] for item in first["processes"]} == {"running", "completed"}
    assert {item["output_cursor"] for item in first["processes"]} == {0, 17}

    other_context = RunContext(
        run_id="internal-0",
        session_id="thread",
        user_id="other-user",
        session_state={},
        dependencies=runtime.context.dependencies,
    )
    with pytest.raises(CodingRepositoryError) as rejected:
        await runtime.kernel.process("list", None, "", 30, other_context)
    assert rejected.value.code == "task_scope_mismatch"


async def completed_verification(runtime, command: str = "verify") -> str:
    started = await runtime.kernel.terminal(command, background=True, run_context=runtime.context)
    execution_id = started["execution_id"]
    finish_remote_execution(runtime, execution_id)
    await runtime.kernel.poll(execution_id, runtime.context)
    return execution_id


@pytest.mark.anyio
async def test_finish_task_enforces_plan_artifacts_verification_and_active_processes(
    execution_runtime,
):
    runtime = execution_runtime
    verification_id = await completed_verification(runtime)
    finish_function = Function(name="finish_task")
    runtime.context.session_state[AGENT_PLAN_STATE_KEY] = {
        "plan": [{"step": "验证", "status": "in_progress"}]
    }

    incomplete = await runtime.kernel.finish_task(
        "done", [], [verification_id], [], runtime.context, finish_function
    )
    assert incomplete["code"] == "finish_plan_incomplete"
    assert finish_function.stop_after_tool_call is False

    runtime.context.session_state[AGENT_PLAN_STATE_KEY]["plan"][0]["status"] = "completed"
    missing = await runtime.kernel.finish_task(
        "done", ["missing.txt"], [verification_id], [], runtime.context, finish_function
    )
    assert missing["code"] == "finish_artifact_missing"

    service = await runtime.kernel.terminal("serve", background=True, run_context=runtime.context)
    health_id = await completed_verification(runtime, "healthcheck")
    stale = await runtime.kernel.finish_task(
        "done", [], [verification_id], [], runtime.context, finish_function
    )
    assert stale["code"] == "finish_verification_stale"
    active = await runtime.kernel.finish_task(
        "done", [], [health_id], [], runtime.context, finish_function
    )
    assert active["code"] == "finish_process_active"

    accepted = await runtime.kernel.finish_task(
        "done",
        [],
        [health_id],
        [
            {
                "session_id": service["execution_id"],
                "healthcheck_execution_id": health_id,
            }
        ],
        runtime.context,
        finish_function,
    )
    assert accepted["status"] == "accepted"
    assert finish_function.stop_after_tool_call is True
    retained = await runtime.repository.get_execution(service["execution_id"])
    assert retained is not None and retained.retained_service is True


@pytest.mark.anyio
async def test_finish_entrypoint_returns_stable_error_when_required_argument_is_missing(
    execution_runtime,
):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    finish_function = toolkit.async_functions["finish_task"]

    result = await finish_function.entrypoint(
        summary="done",
        artifact_paths=[],
        run_context=runtime.context,
    )

    assert result["code"] == "finish_verification_missing"


def test_update_plan_declares_schema_and_returns_stable_missing_argument_error():
    toolkit = WorkspaceCodingToolkit(None, None)  # type: ignore[arg-type]
    function = toolkit.functions["update_plan"]

    assert function.parameters["required"] == ["plan"]
    assert function.parameters["properties"]["plan"]["items"]["required"] == [
        "step",
        "status",
    ]
    assert function.entrypoint()["code"] == "plan_required"


@pytest.mark.anyio
async def test_finish_task_returns_stable_errors_for_invalid_services_and_state_race(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    verification_id = await completed_verification(runtime)
    runtime.context.session_state[AGENT_PLAN_STATE_KEY] = {"plan": []}
    finish_function = Function(name="finish_task")

    invalid = await runtime.kernel.finish_task(
        "done",
        [],
        [verification_id],
        [{"session_id": 7, "healthcheck_execution_id": verification_id}],  # type: ignore[list-item]
        runtime.context,
        finish_function,
    )
    assert invalid["code"] == "finish_services_invalid"

    original = runtime.repository.request_finish

    async def mutate_before_finish(*args, **kwargs):
        task = await runtime.repository.get_task_snapshot("external-run")
        assert task is not None
        await runtime.repository.submit_instruction(task.scope, "raced", "补充竞态指令")
        return await original(*args, **kwargs)

    monkeypatch.setattr(runtime.repository, "request_finish", mutate_before_finish)
    raced = await runtime.kernel.finish_task(
        "done", [], [verification_id], [], runtime.context, finish_function
    )

    assert raced["code"] == "finish_state_changed"
    assert finish_function.stop_after_tool_call is False
    task = await runtime.repository.get_task("external-run")
    assert task is not None and task.status != "completed"


@pytest.mark.anyio
async def test_finish_task_rejects_changed_sandbox_with_stable_code(execution_runtime):
    runtime = execution_runtime
    verification_id = await completed_verification(runtime)
    runtime.context.session_state[AGENT_PLAN_STATE_KEY] = {"plan": []}
    remote_process(runtime)
    sandbox = runtime.synchronous.sandbox_for("thread")
    sandbox.id = "replacement-sandbox"

    result = await runtime.kernel.finish_task(
        "done",
        [],
        [verification_id],
        [],
        runtime.context,
        Function(name="finish_task"),
    )

    assert result["code"] == "finish_sandbox_changed"
    task = await runtime.repository.get_task("external-run")
    assert task is not None and task.status != "completed"


@pytest.mark.anyio
async def test_report_finish_requires_validated_delivery_evidence(execution_runtime):
    runtime = execution_runtime
    report_scope = CodingScope(
        "report-run",
        "user",
        "thread",
        str(runtime.synchronous.sandbox_for("thread").id),
        "report-agent",
    )
    report_task = await runtime.repository.create_task_with_initial_attempt(
        report_scope, "生成报表"
    )
    report_lease = await runtime.repository.claim_lease("report-run", "report-request")
    assert isinstance(report_lease, Lease)
    _report_task, report_attempt = await runtime.repository.open_initial(
        "report-run", report_lease, report_task.state_version
    )
    report_context = RunContext(
        run_id=report_attempt.internal_run_id,
        session_id="thread",
        user_id="user",
        session_state={AGENT_PLAN_STATE_KEY: {"plan": []}},
        dependencies={
            CODING_TASK_DEPENDENCY: {
                "externalRunId": "report-run",
                "leaseOwner": "report-request",
                "leaseEpoch": report_lease.epoch,
                "sandboxId": report_scope.sandbox_id,
            }
        },
    )

    async def missing_evidence(_run_context):
        return None

    report_kernel = CodingExecutionKernel(
        runtime.workspace,
        runtime.repository,
        completion_evidence=missing_evidence,
    )
    started = await report_kernel.terminal(
        "verify report", background=True, run_context=report_context
    )
    execution_id = started["execution_id"]
    finish_remote_execution(runtime, execution_id)
    await report_kernel.poll(execution_id, report_context)

    result = await report_kernel.finish_task(
        "report done",
        [],
        [execution_id],
        [],
        report_context,
        Function(name="finish_task"),
    )

    assert result["code"] == "finish_report_unverified"
