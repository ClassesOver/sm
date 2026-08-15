import asyncio
import hashlib
import json
import subprocess
import sys
from copy import copy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools import Function
from agno.tools.function import FunctionCall
from daytona.common.errors import DaytonaNotFoundError

import agentos_dev.task_execution.execution as execution_module
from agentos_dev.agent_control import AGENT_PLAN_STATE_KEY
from agentos_dev.coding import CodingScope, Lease
from agentos_dev.coding.reporting.tools import ReportWorkspaceTaskToolkit
from agentos_dev.coding.executor import CODING_FINISH_FAILURE_STATE_KEY
from agentos_dev.coding.tests.workspace_fakes import (
    AsyncFakeClient,
    AsyncFakeFs,
    AsyncFakeProcess,
    AsyncMemoryRegistry,
    service,
)
from agentos_dev.database import create_agent_database
from agentos_dev.skills import (
    CODING_SKILL_SCRIPT_RECEIPTS_STATE_KEY,
    SkillValidatorRegistry,
    load_builtin_coding_skills,
    skill_script_receipt_hook,
)
from agentos_dev.task_execution.execution import (
    CODING_EXECUTION_MIGRATION_STATE_KEY,
    CODING_TASK_DEPENDENCY,
    CODING_TOOL_ARGUMENT_AUTOFIX_STATE_KEY,
    CODING_TOOL_FAILURE_STATE_KEY,
    CODING_TOOL_OUTPUT_STATE_KEY,
    CODING_TOOL_PROGRESS_STATE_KEY,
    MAX_PARALLEL_READ_TOOLS,
    MAX_TERMINAL_COMMAND_BYTES,
    CodingExecutionKernel,
    CodingTaskScope,
    WorkspaceCodingToolkit,
    _absolute_paths,
    _task_tool_parallel_safe,
    create_coding_tool_scheduler_hook,
    normalize_coding_function_call_arguments,
)
from agentos_dev.task_execution.repository import CodingRepositoryError, CodingTaskRepository
from agentos_dev.task_execution.tools import (
    CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY,
    CODEX_EXEC_SESSIONS_STATE_KEY,
)
from agentos_dev.workspace import (
    MANAGED_PROCESS_PREFIX,
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceService,
    WorkspaceToolkit,
)


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


@pytest.mark.anyio
async def test_hot_read_resolves_one_snapshot_without_lease_or_cleanup_queries(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    snapshot_calls = 0
    original_snapshot = runtime.repository.get_task_snapshot

    async def counted_snapshot(external_run_id):
        nonlocal snapshot_calls
        snapshot_calls += 1
        return await original_snapshot(external_run_id)

    async def unexpected(*_args, **_kwargs):
        raise AssertionError("热态只读工具不应领取租约或清理历史任务")

    monkeypatch.setattr(runtime.repository, "get_task_snapshot", counted_snapshot)
    monkeypatch.setattr(runtime.repository, "claim_lease", unexpected)
    monkeypatch.setattr(runtime.repository, "cleanup_expired", unexpected)
    monkeypatch.setattr(runtime.repository, "get_task", unexpected)

    result = await toolkit.coding_list_files(run_context=runtime.context)

    assert isinstance(result, list)
    assert snapshot_calls == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("invalid", "expected_code"),
    [
        ("owner", "task_lease_binding_invalid"),
        ("epoch", "task_lease_binding_invalid"),
        ("epoch_type", "task_binding_invalid"),
        ("expiry", "task_lease_binding_invalid"),
        ("internal_run", "task_run_mismatch"),
        ("sandbox", "task_scope_mismatch"),
    ],
)
async def test_v2_scope_rejects_stale_or_mismatched_snapshot_bindings(
    execution_runtime,
    monkeypatch,
    invalid,
    expected_code,
):
    runtime = execution_runtime
    context = copy(runtime.context)
    context.dependencies = {
        CODING_TASK_DEPENDENCY: dict(runtime.context.dependencies[CODING_TASK_DEPENDENCY])
    }
    snapshot = await runtime.repository.get_task_snapshot("external-run")
    assert snapshot is not None
    if invalid == "owner":
        context.dependencies[CODING_TASK_DEPENDENCY]["leaseOwner"] = "other-owner"
    elif invalid == "epoch":
        context.dependencies[CODING_TASK_DEPENDENCY]["leaseEpoch"] += 1
    elif invalid == "epoch_type":
        context.dependencies[CODING_TASK_DEPENDENCY]["leaseEpoch"] = True
    elif invalid == "expiry":
        expired = replace(
            snapshot, lease_expires_at=execution_module.utcnow() - timedelta(seconds=1)
        )

        async def expired_snapshot(_external_run_id):
            return expired

        monkeypatch.setattr(runtime.repository, "get_task_snapshot", expired_snapshot)
    elif invalid == "internal_run":
        context.run_id = "other-internal-run"
    else:
        context.dependencies[CODING_TASK_DEPENDENCY]["sandboxId"] = "other-sandbox"

    async def unexpected_claim(*_args, **_kwargs):
        raise AssertionError("v2 scope 不应重新领取租约")

    monkeypatch.setattr(runtime.repository, "claim_lease", unexpected_claim)
    with pytest.raises(CodingRepositoryError) as rejected:
        await runtime.kernel.scope(context)
    assert rejected.value.code == expected_code


@pytest.mark.anyio
async def test_legacy_scope_keeps_query_bind_and_claim_path(execution_runtime, monkeypatch):
    runtime = execution_runtime
    sandbox_id = str(runtime.synchronous.sandbox_for("thread").id)
    await runtime.repository.create_task(
        external_run_id="legacy-run",
        owner_user_id="user",
        thread_id="thread",
        agent_id="coding-agent",
        sandbox_id=sandbox_id,
        deadline_at=execution_module.utcnow() + timedelta(minutes=5),
    )
    context = RunContext(
        run_id="legacy-internal-run",
        session_id="thread",
        user_id="user",
        session_state={},
        dependencies={
            CODING_TASK_DEPENDENCY: {
                "externalRunId": "legacy-run",
                "leaseOwner": "legacy-owner",
                "sandboxId": sandbox_id,
            }
        },
    )
    claim_calls = 0
    original_claim = runtime.repository.claim_lease

    async def counted_claim(*args, **kwargs):
        nonlocal claim_calls
        claim_calls += 1
        return await original_claim(*args, **kwargs)

    async def unexpected_cleanup(*_args, **_kwargs):
        raise AssertionError("工具 scope 不应执行历史任务清理")

    monkeypatch.setattr(runtime.repository, "claim_lease", counted_claim)
    monkeypatch.setattr(runtime.repository, "cleanup_expired", unexpected_cleanup)

    scope = await runtime.kernel.scope(context)

    assert scope.internal_run_id == "legacy-internal-run"
    assert scope.lease is None
    assert claim_calls == 1


@pytest.mark.anyio
async def test_terminal_runtime_install_is_concurrent_once_and_revalidates_after_lru_eviction(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    scope = await runtime.kernel.scope(runtime.context)
    uploads = []
    original_upload = AsyncFakeFs.upload_file

    async def counted_upload(fs, content, path):
        if path.endswith("/readonly_script_runtime.py"):
            uploads.append(path)
        return await original_upload(fs, content, path)

    monkeypatch.setattr(AsyncFakeFs, "upload_file", counted_upload)
    first, concurrent = await asyncio.gather(
        runtime.kernel._install_terminal_runtime(scope),
        runtime.kernel._install_terminal_runtime(scope),
    )
    cached = await runtime.kernel._install_terminal_runtime(scope)
    first_sandbox = runtime.synchronous.sandbox_for("thread")
    assert first == concurrent == cached
    assert first_sandbox.fs.download_calls.count(first) == 1
    assert len(uploads) == 1
    assert (
        sum("sudo chown root:root" in call["command"] for call in first_sandbox.process.calls) == 1
    )

    monkeypatch.setattr(execution_module, "MAX_TERMINAL_RUNTIME_CACHE_ENTRIES", 1)
    other_sandbox = runtime.synchronous.sandbox_for("other-thread")
    other_scope = CodingTaskScope(
        task=scope.task,
        external_run_id=scope.external_run_id,
        internal_run_id=scope.internal_run_id,
        owner_user_id=scope.owner_user_id,
        thread_id="other-thread",
        sandbox_id=str(other_sandbox.id),
        lease_owner=scope.lease_owner,
        lease_epoch=scope.lease_epoch,
        attempt_no=scope.attempt_no,
        lease=scope.lease,
    )
    other_path = await runtime.kernel._install_terminal_runtime(other_scope)
    revisited = await runtime.kernel._install_terminal_runtime(scope)

    assert other_path == first == revisited
    assert first_sandbox.fs.download_calls.count(first) == 2
    assert other_sandbox.fs.download_calls.count(other_path) == 1
    assert len(uploads) == 2
    assert (
        sum("sudo chown root:root" in call["command"] for call in first_sandbox.process.calls) == 2
    )


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


async def completed_verification(
    runtime,
    command: str = "verify",
    *,
    kernel=None,
    run_context=None,
) -> str:
    current_kernel = kernel or runtime.kernel
    current_context = run_context or runtime.context
    task = asyncio.create_task(current_kernel.verify(command, [], current_context))
    execution_id = None
    for _attempt in range(100):
        await asyncio.sleep(0)
        executions = await runtime.repository.list_executions(
            current_context.dependencies[CODING_TASK_DEPENDENCY]["externalRunId"]
        )
        execution_id = next(
            (
                execution.execution_id
                for execution in reversed(executions)
                if execution.is_verification
                and execution.command_id is not None
                and execution.status not in {"completed", "failed", "terminated", "lost"}
            ),
            None,
        )
        if execution_id is not None:
            break
    assert execution_id is not None
    finish_remote_execution(runtime, execution_id)
    result = await task
    assert result["status"] == "completed"
    return execution_id


def create_acceptance_registry(tmp_path):
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "analysis"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    script = scripts_dir / "validate.py"
    script.write_text("print('server validator')\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: analysis\n"
        "description: Validate analysis artifacts\n"
        "metadata:\n"
        "  agentos:\n"
        "    acceptance:\n"
        "      validators:\n"
        "        report:\n"
        "          script: validate.py\n"
        "          timeout: 17\n"
        "          artifactPatterns:\n"
        "            - reports/*.json\n"
        "---\n"
        "Validate analysis artifacts.\n",
        encoding="utf-8",
    )
    registry = SkillValidatorRegistry.from_skills(load_builtin_coding_skills(str(skill_root)))
    return registry, script


async def acceptance_runtime(runtime, tmp_path, *, requirements=None):
    registry, script = create_acceptance_registry(tmp_path)
    contract = {
        "version": 1,
        "requirements": requirements
        or [
            {
                "id": "report",
                "validatorId": "analysis:report",
                "parameters": {"minimumRows": 3},
                "artifactPatterns": ["reports/*.json"],
            }
        ],
    }
    scope = CodingScope(
        "acceptance-run",
        "user",
        "thread",
        str(runtime.synchronous.sandbox_for("thread").id),
        "coding-agent",
    )
    task = await runtime.repository.create_task_with_initial_attempt(
        scope,
        "生成分析产物",
        acceptance_contract=contract,
    )
    lease = await runtime.repository.claim_lease(scope.external_run_id, "acceptance-request")
    assert isinstance(lease, Lease)
    _task, attempt = await runtime.repository.open_initial(
        scope.external_run_id, lease, task.state_version
    )
    context = RunContext(
        run_id=attempt.internal_run_id,
        session_id="thread",
        user_id="user",
        session_state={AGENT_PLAN_STATE_KEY: {"plan": []}},
        dependencies={
            CODING_TASK_DEPENDENCY: {
                "externalRunId": scope.external_run_id,
                "leaseOwner": "acceptance-request",
                "leaseEpoch": lease.epoch,
                "sandboxId": scope.sandbox_id,
            }
        },
    )
    sandbox = runtime.synchronous.sandbox_for("thread")
    sandbox.fs.create_folder("/home/daytona/workspace/reports", "700")
    sandbox.fs.upload_file(b"{}", "/home/daytona/workspace/reports/result.json")
    return SimpleNamespace(
        context=context,
        contract=contract,
        kernel=CodingExecutionKernel(
            runtime.workspace,
            runtime.repository,
            validator_registry=registry,
        ),
        registry=registry,
        scope=scope,
        script=script,
    )


async def completed_validator(runtime, acceptance, *, passed=None, output=None, tamper=None):
    pending = asyncio.create_task(
        acceptance.kernel.verify(
            None,
            ["reports/result.json"],
            acceptance.context,
            validator_id="analysis:report",
        )
    )
    execution_id = None
    command_text = None
    for _attempt in range(100):
        await asyncio.sleep(0)
        executions = await runtime.repository.list_executions(acceptance.scope.external_run_id)
        execution = next(
            (
                item
                for item in reversed(executions)
                if item.is_verification
                and item.command_id is not None
                and item.status not in {"completed", "failed", "terminated", "lost"}
            ),
            None,
        )
        if execution is not None:
            execution_id = execution.execution_id
            process = remote_process(runtime)
            session = process.sessions[f"{MANAGED_PROCESS_PREFIX}{execution_id}"]
            command = session.commands[0]
            command_text = command.command
            if tamper is not None:
                tamper(command_text)
            if output is None:
                assert isinstance(passed, bool)
                output = json.dumps(
                    {
                        "version": 1,
                        "requirements": [
                            {
                                "id": "report",
                                "passed": passed,
                                "message": "ok" if passed else "数据不完整",
                                "details": {"rows": 3 if passed else 2},
                            }
                        ],
                    },
                    separators=(",", ":"),
                )
            command.output = output
            command.exit_code = 0
            break
    assert execution_id is not None
    result = await pending
    return execution_id, command_text, result


@pytest.mark.anyio
async def test_validator_verify_uses_pinned_script_fixed_timeout_and_strict_receipt(
    execution_runtime,
    tmp_path,
    monkeypatch,
):
    runtime = execution_runtime
    debug_messages = []
    monkeypatch.setattr(execution_module, "log_debug", debug_messages.append)
    acceptance = await acceptance_runtime(runtime, tmp_path)
    original_script = acceptance.script.read_bytes()

    execution_id, command, result = await completed_validator(
        runtime,
        acceptance,
        passed=True,
    )

    validator = acceptance.registry.require("analysis:report")
    execution = await runtime.repository.get_execution(execution_id)
    assert command is not None and "python3 -I -B" in command
    assert "readonly_script_runtime.py" in command
    assert f"validators/{validator.install_digest}/" in command
    assert "17s" in command
    assert result["status"] == "completed"
    assert result["acceptance"]["requirements"][0]["passed"] is True
    assert execution is not None and execution.mutation_sequence == 0
    assert execution.operation_receipt["validator_id"] == "analysis:report"
    assert execution.operation_receipt["validator_sha256"] == validator.script_sha256
    assert execution.operation_receipt["valid"] is True
    assert acceptance.script.read_bytes() == original_script
    sandbox_fs = runtime.synchronous.sandbox_for("thread").fs
    assert not any("/validators/" in path for path in sandbox_fs.download_calls)
    assert sum("/validators/" in path for path in sandbox_fs.stream_download_calls) == 4
    phases = [
        message.split("phase=", 1)[1].split()[0]
        for message in debug_messages
        if message.startswith("coding_validator_verify phase=")
    ]
    assert phases == [
        "artifact_hash_started",
        "artifact_hash_completed",
        "validator_install_started",
        "validator_install_completed",
        "validator_execution_started",
        "validator_execution_completed",
        "validator_integrity_started",
        "validator_integrity_completed",
        "validator_cleanup_started",
        "validator_cleanup_completed",
        "artifact_rehash_started",
        "artifact_rehash_completed",
        "completed",
    ]
    internal_files = sandbox_fs.entries
    assert not any(f"validators/{validator.install_digest}/" in path for path in internal_files)


@pytest.mark.anyio
async def test_validator_install流式下载无响应时按阶段超时失败关闭(
    execution_runtime,
    tmp_path,
    monkeypatch,
):
    runtime = execution_runtime
    acceptance = await acceptance_runtime(runtime, tmp_path)
    scope = await acceptance.kernel.scope(acceptance.context)
    validator = acceptance.registry.require("analysis:report")
    original_download = AsyncFakeFs.download_file_stream

    async def blocking_download(fs, path, timeout=30 * 60):
        if "/validators/" not in path:
            return await original_download(fs, path, timeout=timeout)

        async def stream():
            await asyncio.Event().wait()
            yield b"unreachable"

        return stream()

    monkeypatch.setattr(AsyncFakeFs, "download_file_stream", blocking_download)
    monkeypatch.setattr(execution_module, "MAX_VALIDATOR_STAGE_TIMEOUT", 0.01)

    with pytest.raises(WorkspaceError, match="validator 安装超时"):
        await acceptance.kernel._install_validator(scope, validator, b"{}")


@pytest.mark.anyio
async def test_validator_failure_returns_directional_bounded_requirements(
    execution_runtime,
    tmp_path,
):
    runtime = execution_runtime
    acceptance = await acceptance_runtime(
        runtime,
        tmp_path,
        requirements=[
            {
                "id": "graph",
                "validatorId": "analysis:report",
                "parameters": {},
                "artifactPatterns": ["reports/*.json"],
            },
            {
                "id": "events",
                "validatorId": "analysis:report",
                "parameters": {},
                "artifactPatterns": ["reports/*.json"],
            },
        ],
    )
    output = json.dumps(
        {
            "version": 1,
            "requirements": [
                {
                    "id": "graph",
                    "passed": True,
                    "message": "graph checks passed",
                    "details": {"failedTests": []},
                },
                {
                    "id": "events",
                    "passed": False,
                    "message": "events checks failed",
                    "details": {
                        "check": "invalid_event_keeps_state",
                        "observed": "event id consumed",
                    },
                },
            ],
        },
        separators=(",", ":"),
    )

    _execution_id, _command, result = await completed_validator(
        runtime,
        acceptance,
        output=output,
    )

    assert result["code"] == "verification_acceptance_failed"
    assert result["failedRequirements"] == [
        {
            "id": "events",
            "message": "events checks failed",
            "details": {
                "check": "invalid_event_keeps_state",
                "observed": "event id consumed",
            },
        }
    ]
    assert result["passedRequirements"] == [{"id": "graph"}]
    assert result["requiredActions"] == [
        "仅修复 failedRequirements 列出的失败能力；保持 passedRequirements 已通过行为不变。",
        "先运行与失败项对应的公开测试或局部验证，再重新运行 validator_id=analysis:report。",
    ]


@pytest.mark.anyio
async def test_validator_failure_preserves_bounded_schema_details(
    execution_runtime,
    tmp_path,
):
    runtime = execution_runtime
    acceptance = await acceptance_runtime(runtime, tmp_path)
    details = {
        "schemaErrors": [
            {
                "path": f"sections.{index}",
                "message": "对象不符合契约；期望 string，实际为 object。",
            }
            for index in range(12)
        ]
    }
    details_size = len(
        json.dumps(details, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    assert 512 < details_size < execution_module.MAX_VALIDATOR_DETAIL_BYTES
    output = json.dumps(
        {
            "version": 1,
            "requirements": [
                {
                    "id": "report",
                    "passed": False,
                    "message": "ReportArtifactManifest 不符合 JSON Schema。",
                    "details": details,
                }
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    _execution_id, _command, result = await completed_validator(
        runtime,
        acceptance,
        output=output,
    )

    assert result["code"] == "verification_acceptance_failed"
    assert result["failedRequirements"] == [
        {
            "id": "report",
            "message": "ReportArtifactManifest 不符合 JSON Schema。",
            "details": details,
        }
    ]


@pytest.mark.anyio
async def test_validator_acceptance_preserves_bounded_warnings(
    execution_runtime,
    tmp_path,
):
    runtime = execution_runtime
    acceptance = await acceptance_runtime(runtime, tmp_path)
    warnings = ["w" * 1000] * 60
    details = {"summary": "d" * 7900}
    output = json.dumps(
        {
            "version": 1,
            "requirements": [
                {
                    "id": "report",
                    "passed": True,
                    "message": "详细分析计划有效。",
                    "details": details,
                    "warnings": warnings,
                }
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert 64 * 1024 < len(output.encode("utf-8")) < execution_module.MAX_VALIDATOR_RESULT_BYTES

    execution_id, _command, result = await completed_validator(
        runtime,
        acceptance,
        output=output,
    )

    assert result["ok"] is True
    assert result["acceptance"]["requirements"][0]["warnings"] == warnings
    assert result["acceptance"]["requirements"][0]["details"] == details
    execution = await runtime.repository.get_execution(execution_id)
    assert execution is not None
    assert execution.operation_receipt["acceptance"]["requirements"][0]["warnings"] == warnings


@pytest.mark.parametrize(
    ("warnings", "expected_error"),
    [
        (["warning"] * (execution_module.MAX_VALIDATOR_WARNINGS + 1), "warnings"),
        (["x" * 1025], "warnings"),
        (["警" * 700] * execution_module.MAX_VALIDATOR_WARNINGS, "warnings_size"),
    ],
)
def test_validator_result_rejects_warnings_outside_bounds(warnings, expected_error):
    requirements = [
        {
            "id": "report",
            "validatorId": "analysis:report",
            "parameters": {},
            "artifactPatterns": ["reports/*.json"],
        }
    ]
    output = json.dumps(
        {
            "version": 1,
            "requirements": [
                {
                    "id": "report",
                    "passed": True,
                    "warnings": warnings,
                }
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    with pytest.raises(ValueError, match=rf"validator_result_{expected_error}$"):
        CodingExecutionKernel._parse_validator_result(output, requirements)


@pytest.mark.anyio
async def test_skill_script_is_installed_readonly_and_writable_copy_is_rejected(
    execution_runtime,
):
    runtime = execution_runtime
    body = "print('trusted')\n"

    async def read_script(**_kwargs):
        return json.dumps({"skill_name": "report", "script_path": "validate.py", "content": body})

    raw = await skill_script_receipt_hook(
        runtime.context,
        "get_skill_script",
        read_script,
        {"skill_name": "report", "script_path": "validate.py", "execute": False},
        workspace_service=runtime.workspace,
    )

    result = json.loads(raw)
    readonly_path = result["readonly_path"]
    sandbox = runtime.synchronous.sandbox_for("thread")
    info, installed = sandbox.fs.entries[readonly_path]
    assert installed == body.encode()
    assert info is not None
    receipt = runtime.context.session_state[CODING_SKILL_SCRIPT_RECEIPTS_STATE_KEY][
        "report:validate.py"
    ]
    assert receipt["readonlyPath"] == readonly_path

    with pytest.raises(WorkspaceError, match="readonly_path"):
        await runtime.kernel.patch(
            "create",
            "validate.py",
            None,
            None,
            False,
            None,
            runtime.context,
            content=body,
        )
    assert await runtime.repository.list_executions("external-run") == []


def test_readonly_script_runtime_blocks_self_mutation_but_allows_workspace_write(tmp_path):
    protected = tmp_path / "protected"
    workspace = tmp_path / "workspace"
    protected.mkdir()
    workspace.mkdir()
    script = protected / "validator.py"
    script.write_text(
        "from pathlib import Path\n"
        "target = Path(__file__)\n"
        "blocked = []\n"
        "for operation in (\n"
        "    lambda: target.write_text('changed'),\n"
        "    lambda: target.unlink(),\n"
        "    lambda: target.rename(target.with_suffix('.moved')),\n"
        "):\n"
        "    try:\n"
        "        operation()\n"
        "    except PermissionError:\n"
        "        blocked.append(True)\n"
        f"Path({str(workspace / 'result.txt')!r}).write_text('ok')\n"
        "Path('/dev/null').write_text('discarded')\n"
        "print(len(blocked))\n",
        encoding="utf-8",
    )
    original = script.read_bytes()
    runtime = Path(execution_module.__file__).with_name("readonly_script_runtime.py")

    completed = subprocess.run(
        [
            sys.executable,
            str(runtime),
            "--write-root",
            str(workspace),
            "--write-root",
            "/dev/null",
            str(script),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "3"
    assert script.read_bytes() == original
    assert (workspace / "result.txt").read_text(encoding="utf-8") == "ok"


@pytest.mark.anyio
async def test_validator_rejects_runtime_digest_change_and_cleans_install(
    execution_runtime,
    tmp_path,
):
    runtime = execution_runtime
    acceptance = await acceptance_runtime(runtime, tmp_path)
    sandbox = runtime.synchronous.sandbox_for("thread")

    def tamper(_command: str) -> None:
        runtime_path = next(
            path for path in sandbox.fs.entries if path.endswith("readonly_script_runtime.py")
        )
        info, _content = sandbox.fs.entries[runtime_path]
        sandbox.fs.entries[runtime_path] = (info, b"changed")

    execution_id, _command, result = await completed_validator(
        runtime,
        acceptance,
        passed=True,
        tamper=tamper,
    )

    execution = await runtime.repository.get_execution(execution_id)
    assert result["code"] == "verification_validator_script_modified"
    assert execution is not None
    assert execution.operation_receipt["failure_code"] == "validator_script_modified"
    validator = acceptance.registry.require("analysis:report")
    assert not any(f"validators/{validator.install_digest}/" in path for path in sandbox.fs.entries)


@pytest.mark.anyio
async def test_validator_verify_rejects_invalid_and_oversized_json_results(
    execution_runtime,
    tmp_path,
):
    runtime = execution_runtime
    acceptance = await acceptance_runtime(runtime, tmp_path)

    invalid_id, _command, invalid = await completed_validator(
        runtime,
        acceptance,
        output="{not-json",
    )
    oversized_id, _command, oversized = await completed_validator(
        runtime,
        acceptance,
        output="x" * (execution_module.MAX_VALIDATOR_RESULT_BYTES + 1),
    )

    assert invalid["code"] == "verification_validator_result_invalid"
    assert oversized["code"] == "verification_validator_result_invalid"
    for execution_id in (invalid_id, oversized_id):
        execution = await runtime.repository.get_execution(execution_id)
        assert execution is not None
        assert execution.operation_receipt["valid"] is False
        assert execution.operation_receipt["failure_code"] == "validator_result_invalid"


@pytest.mark.anyio
async def test_finish_acceptance_progresses_from_missing_and_failed_to_accepted(
    execution_runtime,
    tmp_path,
):
    runtime = execution_runtime
    acceptance = await acceptance_runtime(runtime, tmp_path)
    verification_id = await completed_verification(
        runtime,
        "true",
        kernel=acceptance.kernel,
        run_context=acceptance.context,
    )
    finish_function = Function(name="finish_task")

    missing = await acceptance.kernel.finish_task(
        "done",
        ["reports/result.json"],
        [verification_id],
        [],
        acceptance.context,
        finish_function,
    )
    repeated_missing = await acceptance.kernel.finish_task(
        "done",
        ["reports/result.json"],
        [verification_id],
        [],
        acceptance.context,
        finish_function,
    )
    await completed_validator(runtime, acceptance, passed=False)
    failed = await acceptance.kernel.finish_task(
        "done",
        ["reports/result.json"],
        [verification_id],
        [],
        acceptance.context,
        finish_function,
    )
    repeated_failed = await acceptance.kernel.finish_task(
        "done",
        ["reports/result.json"],
        [verification_id],
        [],
        acceptance.context,
        finish_function,
    )
    passed_id, _command, _result = await completed_validator(runtime, acceptance, passed=True)
    accepted = await acceptance.kernel.finish_task(
        "done",
        ["reports/result.json"],
        [verification_id],
        [],
        acceptance.context,
        finish_function,
    )

    assert missing["code"] == "finish_acceptance_missing"
    assert repeated_missing["code"] == "finish_no_progress"
    assert repeated_missing["details"]["failureCode"] == "finish_acceptance_missing"
    assert failed["code"] == "finish_acceptance_failed"
    assert repeated_failed["code"] == "finish_no_progress"
    assert accepted["status"] == "accepted"
    assert accepted["acceptance"] == {
        "version": 1,
        "requirements": [
            {
                "id": "report",
                "validatorId": "analysis:report",
                "status": "passed",
                "executionId": passed_id,
            }
        ],
    }


@pytest.mark.anyio
async def test_finish_rejects_validator_evidence_after_workspace_mutation(
    execution_runtime,
    tmp_path,
):
    runtime = execution_runtime
    acceptance = await acceptance_runtime(runtime, tmp_path)
    await completed_validator(runtime, acceptance, passed=True)

    await acceptance.kernel.patch(
        "overwrite",
        "reports/result.json",
        None,
        None,
        False,
        None,
        acceptance.context,
        content='{"changed":true}',
        expected_sha256=hashlib.sha256(b"{}").hexdigest(),
    )
    verification_id = await completed_verification(
        runtime,
        "true",
        kernel=acceptance.kernel,
        run_context=acceptance.context,
    )
    stale = await acceptance.kernel.finish_task(
        "done",
        ["reports/result.json"],
        [verification_id],
        [],
        acceptance.context,
        Function(name="finish_task"),
    )

    assert stale["code"] == "finish_acceptance_stale"
    assert stale["details"]["requirements"] == [
        {
            "id": "report",
            "validatorId": "analysis:report",
            "status": "stale",
        }
    ]


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
    assert missing["details"]["missingPaths"] == ["missing.txt"]
    assert missing["details"]["mutationSequence"] == 0
    assert missing["requiredActions"]
    assert missing["retryable"] is True

    service = await runtime.kernel.terminal("serve", background=True, run_context=runtime.context)
    health_id = await completed_verification(runtime, "healthcheck")
    stale = await runtime.kernel.finish_task(
        "done", [], [verification_id], [], runtime.context, finish_function
    )
    assert stale["code"] == "finish_verification_stale"
    assert stale["details"]["verification"][0]["current"] is False
    active = await runtime.kernel.finish_task(
        "done", [], [health_id], [], runtime.context, finish_function
    )
    assert active["code"] == "finish_process_active"
    assert active["details"]["activeProcesses"] == [
        {"sessionId": service["execution_id"], "status": "running"}
    ]

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
    assert accepted["status"] == "accepted", accepted
    assert finish_function.stop_after_tool_call is True
    retained = await runtime.repository.get_execution(service["execution_id"])
    assert retained is not None and retained.retained_service is True


@pytest.mark.anyio
async def test_finish_task_rejects_identical_failed_gate_until_execution_progress(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    verification_id = await completed_verification(runtime)
    runtime.context.session_state[AGENT_PLAN_STATE_KEY] = {"plan": []}
    hash_calls = 0
    original = runtime.workspace.abatch_hash_files

    async def count_hash(thread_id, paths):
        nonlocal hash_calls
        hash_calls += 1
        return await original(thread_id, paths)

    monkeypatch.setattr(runtime.workspace, "abatch_hash_files", count_hash)
    arguments = ("done", ["missing.txt"], [verification_id], [])

    first = await runtime.kernel.finish_task(
        *arguments, runtime.context, Function(name="finish_task")
    )
    repeated = await runtime.kernel.finish_task(
        *arguments, runtime.context, Function(name="finish_task")
    )

    assert first["code"] == "finish_artifact_missing"
    assert repeated["code"] == "finish_no_progress"
    assert repeated["details"]["failureCode"] == "finish_artifact_missing"
    assert repeated["details"]["missingPaths"] == ["missing.txt"]
    assert hash_calls == 1

    await completed_verification(runtime, "progress")
    progressed = await runtime.kernel.finish_task(
        *arguments, runtime.context, Function(name="finish_task")
    )

    assert progressed["code"] == "finish_no_progress"
    assert hash_calls == 2

    runtime.workspace.create_file("thread", "missing.txt", b"ready")
    current_verification_id = await completed_verification(runtime, "verify fixed artifact")
    accepted = await runtime.kernel.finish_task(
        "done",
        ["missing.txt"],
        [current_verification_id],
        [],
        runtime.context,
        Function(name="finish_task"),
    )

    assert accepted["status"] == "accepted"


@pytest.mark.anyio
async def test_finish_task_rejects_absolute_artifact_paths_without_hashing_or_fake_progress(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    verification_id = await completed_verification(runtime)
    runtime.context.session_state[AGENT_PLAN_STATE_KEY] = {"plan": []}
    hash_calls = 0
    original = runtime.workspace.abatch_hash_files

    async def count_hash(thread_id, paths):
        nonlocal hash_calls
        hash_calls += 1
        return await original(thread_id, paths)

    monkeypatch.setattr(runtime.workspace, "abatch_hash_files", count_hash)
    absolute = "/home/daytona/workspace/report.html"
    first = await runtime.kernel.finish_task(
        "done",
        [absolute],
        [verification_id],
        [],
        runtime.context,
        Function(name="finish_task"),
    )

    assert first["code"] == "finish_artifact_path_invalid"
    assert first["details"]["invalidPaths"] == [absolute]
    assert first["requiredActions"] == ["把 details.invalidPaths 改为工作区相对路径。"]
    assert hash_calls == 0

    next_verification_id = await completed_verification(runtime, "unrelated verification")
    repeated = await runtime.kernel.finish_task(
        "changed summary",
        [absolute],
        [next_verification_id],
        [],
        runtime.context,
        Function(name="finish_task"),
    )

    assert repeated["code"] == "finish_no_progress"
    assert repeated["details"]["failureCode"] == "finish_artifact_path_invalid"
    assert repeated["details"]["invalidPaths"] == [absolute]
    assert hash_calls == 0

    relative = await runtime.kernel.finish_task(
        "changed summary",
        ["report.html"],
        [next_verification_id],
        [],
        runtime.context,
        Function(name="finish_task"),
    )
    assert relative["code"] == "finish_artifact_missing"
    assert hash_calls == 1


@pytest.mark.anyio
async def test_terminal_rejects_oversized_inline_command_without_mutation(execution_runtime):
    runtime = execution_runtime
    before = await runtime.repository.get_task("external-run")
    assert before is not None

    with pytest.raises(WorkspaceError, match="terminal command 超过"):
        await runtime.kernel.terminal(
            "x" * (MAX_TERMINAL_COMMAND_BYTES + 1),
            run_context=runtime.context,
        )

    after = await runtime.repository.get_task("external-run")
    assert after is not None
    assert after.mutation_sequence == before.mutation_sequence


@pytest.mark.anyio
async def test_terminal_accepts_1_mib_utf8_boundary(execution_runtime):
    runtime = execution_runtime
    command = "x" * MAX_TERMINAL_COMMAND_BYTES

    result = await runtime.kernel.terminal(command, background=True, run_context=runtime.context)

    assert result["status"] == "running"


@pytest.mark.anyio
async def test_patch_create_and_overwrite_require_safe_preconditions(execution_runtime):
    runtime = execution_runtime

    created = await runtime.kernel.patch(
        "create", "notes.txt", None, None, False, None, runtime.context, content="first"
    )
    assert created["ok"] is True
    with pytest.raises(WorkspaceError, match="已经存在"):
        await runtime.kernel.patch(
            "create", "notes.txt", None, None, False, None, runtime.context, content="again"
        )
    executions = await runtime.repository.list_executions("external-run")
    assert executions[-1].status == "failed"

    with pytest.raises(WorkspaceError, match="expected_sha256"):
        await runtime.kernel.patch(
            "overwrite", "notes.txt", None, None, False, None, runtime.context, content="second"
        )
    with pytest.raises(WorkspacePathConflict):
        await runtime.kernel.patch(
            "overwrite",
            "notes.txt",
            None,
            None,
            False,
            None,
            runtime.context,
            content="second",
            expected_sha256="0" * 64,
        )
    overwritten = await runtime.kernel.patch(
        "overwrite",
        "notes.txt",
        None,
        None,
        False,
        None,
        runtime.context,
        content="second",
        expected_sha256=created["files"][0]["sha256"],
    )
    assert overwritten["files"][0]["sha256"] != created["files"][0]["sha256"]


@pytest.mark.anyio
async def test_split_mutation_tool_and_inclusive_read_lines(execution_runtime, monkeypatch):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    calls = []

    async def read_lines(thread_id, path, start_line, line_count):
        calls.append((thread_id, path, start_line, line_count))
        return {
            "path": path,
            "startLine": start_line,
            "endLine": start_line + line_count - 1,
            "content": "two\nthree\nfour\n",
        }

    monkeypatch.setattr(runtime.workspace, "aread_lines", read_lines)

    created = await toolkit.coding_create_file(
        "lines.txt",
        "one\ntwo\nthree\nfour\nfive\n",
        run_context=runtime.context,
    )
    selected = await toolkit.read_lines(
        "lines.txt",
        start_line=2,
        end_line=4,
        run_context=runtime.context,
    )

    assert created["ok"] is True
    assert created["mutation_sequence"] == 1
    assert selected["content"] == "two\nthree\nfour\n"
    assert selected["startLine"] == 2
    assert selected["endLine"] == 4
    assert calls == [("thread", "lines.txt", 2, 3)]

    with pytest.raises(WorkspaceError, match="end_line"):
        await toolkit.read_lines(
            "lines.txt",
            start_line=4,
            end_line=2,
            run_context=runtime.context,
        )


@pytest.mark.anyio
async def test_terminal_is_not_verification_and_finish_auto_selects_verify(execution_runtime):
    runtime = execution_runtime
    runtime.context.session_state[AGENT_PLAN_STATE_KEY] = {"plan": []}
    terminal = await runtime.kernel.terminal("true", background=True, run_context=runtime.context)
    assert not await runtime.repository.successful_verification(
        "external-run", terminal["execution_id"], terminal["mutation_sequence"]
    )
    finish_remote_execution(runtime, terminal["execution_id"])
    await runtime.kernel.poll(terminal["execution_id"], runtime.context)

    verification_id = await completed_verification(runtime, "true")
    accepted = await runtime.kernel.finish_task(
        "done", [], None, [], runtime.context, Function(name="finish_task")
    )

    assert accepted["verificationIds"] == [verification_id]


@pytest.mark.anyio
async def test_large_tool_output_has_stable_preview_and_exact_handle_reads(execution_runtime):
    runtime = execution_runtime
    scope = await runtime.kernel.scope(runtime.context)
    output = "开" * 20_000

    bounded = await runtime.kernel.bound_tool_result(scope, {"output": output}, runtime.context)
    page = await runtime.kernel.read_tool_output(
        bounded["outputHandle"], 0, 60_000, runtime.context
    )

    assert "TOOL_OUTPUT_TRUNCATED" in bounded["output"]
    assert len(bounded["output"].encode("utf-8")) <= 48 * 1024
    assert bounded["outputBytes"] == len(output.encode("utf-8"))
    assert page["content"] == output
    assert page["outputSha256"] == bounded["outputSha256"]

    metadata = runtime.context.session_state["agentos_coding_tool_outputs"]["handles"][
        bounded["outputHandle"]
    ]
    metadata["attempt"] += 1
    with pytest.raises(WorkspaceError, match="不属于当前"):
        await runtime.kernel.read_tool_output(bounded["outputHandle"], 0, 1024, runtime.context)


@pytest.mark.anyio
async def test_small_tool_output_only_gets_handle_when_explicitly_retained(execution_runtime):
    runtime = execution_runtime
    scope = await runtime.kernel.scope(runtime.context)
    result = {"status": "completed", "output": "收入同比增长 8.2%"}

    ordinary = await runtime.kernel.bound_tool_result(scope, result, runtime.context)
    retained = await runtime.kernel.bound_tool_result(
        scope,
        result,
        runtime.context,
        retain=True,
    )
    page = await runtime.kernel.read_tool_output(
        retained["outputHandle"], 0, 1024, runtime.context
    )

    assert ordinary == result
    assert "outputHandle" not in ordinary
    assert retained["output"] == result["output"]
    assert retained["outputTruncated"] is False
    assert retained["outputDiscarded"] is False
    assert page["content"] == result["output"]
    assert page["hasMore"] is False


@pytest.mark.anyio
async def test_reporting_analysis_terminal_retains_small_output(execution_runtime):
    runtime = execution_runtime
    external_run_id = "report-coding-retain-test"
    sandbox_id = str(runtime.synchronous.sandbox_for("thread").id)
    scope = CodingScope(external_run_id, "user", "thread", sandbox_id, "report-agent")
    task = await runtime.repository.create_task_with_initial_attempt(
        scope,
        "执行全局分析",
        acceptance_contract={
            "version": 1,
            "requirements": [
                {
                    "id": "report-artifact",
                    "validatorId": "report:artifact",
                    "parameters": {"phase": "analysis"},
                    "artifactPatterns": [],
                }
            ],
        },
    )
    lease = await runtime.repository.claim_lease(external_run_id, "report-request")
    assert isinstance(lease, Lease)
    _task, attempt = await runtime.repository.open_initial(
        external_run_id,
        lease,
        task.state_version,
    )
    context = RunContext(
        run_id=attempt.internal_run_id,
        session_id="thread",
        user_id="user",
        session_state={},
        dependencies={
            CODING_TASK_DEPENDENCY: {
                "externalRunId": external_run_id,
                "leaseOwner": "report-request",
                "leaseEpoch": lease.epoch,
                "sandboxId": sandbox_id,
            }
        },
    )
    toolkit = ReportWorkspaceTaskToolkit(runtime.workspace, runtime.repository)

    created = await toolkit.coding_create_file(
        "analysis/report_analysis.py",
        "print('收入同比增长 8.2%')\n",
        run_context=context,
    )
    started = await toolkit.terminal(
        "printf '收入同比增长 8.2%%'",
        background=True,
        run_context=context,
    )
    finish_remote_execution(
        runtime,
        started["execution_id"],
        output="收入同比增长 8.2%",
    )
    result = await toolkit.process(
        "poll",
        session_id=started["execution_id"],
        run_context=context,
    )
    if result["status"] == "draining":
        result = await toolkit.process(
            "poll",
            session_id=started["execution_id"],
            run_context=context,
        )
    page = await toolkit.read_tool_output(
        result["outputHandle"], _agno_run_context=context
    )

    assert created["mutation_sequence"] == 1
    assert "收入同比增长 8.2%" in result["output"]
    assert result["outputTruncated"] is False
    assert page["content"] == result["output"]


@pytest.mark.anyio
async def test_report_coding_tool_output_uses_smaller_preview_and_exact_handle_reads(
    execution_runtime,
):
    runtime = execution_runtime
    external_run_id = "report-coding-preview-test"
    sandbox_id = str(runtime.synchronous.sandbox_for("thread").id)
    task = await runtime.repository.create_task_with_initial_attempt(
        CodingScope(external_run_id, "user", "thread", sandbox_id, "coding-agent"),
        "生成报表章节",
    )
    lease = await runtime.repository.claim_lease(external_run_id, "report-request")
    assert isinstance(lease, Lease)
    _task, attempt = await runtime.repository.open_initial(
        external_run_id,
        lease,
        task.state_version,
    )
    context = RunContext(
        run_id=attempt.internal_run_id,
        session_id="thread",
        user_id="user",
        session_state={},
        dependencies={
            CODING_TASK_DEPENDENCY: {
                "externalRunId": external_run_id,
                "leaseOwner": "report-request",
                "leaseEpoch": lease.epoch,
                "sandboxId": sandbox_id,
            }
        },
    )
    scope = await runtime.kernel.scope(context)
    output = "画像统计" * 8_000

    bounded = await runtime.kernel.bound_tool_result(scope, {"output": output}, context)
    first_page = await runtime.kernel.read_tool_output(
        bounded["outputHandle"],
        0,
        execution_module.MAX_TOOL_OUTPUT_READ_BYTES,
        context,
    )
    second_page = await runtime.kernel.read_tool_output(
        bounded["outputHandle"],
        first_page["nextOffset"],
        execution_module.MAX_TOOL_OUTPUT_READ_BYTES,
        context,
    )

    assert "TOOL_OUTPUT_TRUNCATED" in bounded["output"]
    assert (
        len(bounded["output"].encode("utf-8"))
        <= execution_module.MAX_REPORT_TOOL_PREVIEW_BYTES
    )
    assert first_page["content"] + second_page["content"] == output
    assert first_page["hasMore"] is True
    assert second_page["hasMore"] is False
    assert second_page["outputSha256"] == bounded["outputSha256"]


@pytest.mark.anyio
async def test_tool_output_capacity_is_explicit_and_cleanup_removes_internal_files(
    execution_runtime, monkeypatch
):
    runtime = execution_runtime
    scope = await runtime.kernel.scope(runtime.context)
    monkeypatch.setattr(execution_module, "MAX_TOOL_OUTPUT_RESOURCE_BYTES", 100)
    monkeypatch.setattr(execution_module, "MAX_TASK_TOOL_OUTPUT_BYTES", 150)
    output = "x" * (49 * 1024)

    first = await runtime.kernel.bound_tool_result(scope, {"output": output}, runtime.context)
    second = await runtime.kernel.bound_tool_result(scope, {"output": output}, runtime.context)
    third = await runtime.kernel.bound_tool_result(scope, {"output": output}, runtime.context)

    assert [
        first["outputStoredBytes"],
        second["outputStoredBytes"],
        third["outputStoredBytes"],
    ] == [
        100,
        50,
        0,
    ]
    assert all(result["outputDiscarded"] for result in (first, second, third))
    internal_paths = {
        metadata["path"]
        for metadata in runtime.context.session_state["agentos_coding_tool_outputs"][
            "handles"
        ].values()
    }
    assert any(
        path in runtime.synchronous.sandbox_for("thread").fs.entries for path in internal_paths
    )

    await runtime.kernel.cleanup_tool_outputs(scope, runtime.context)

    assert not any(
        path in runtime.synchronous.sandbox_for("thread").fs.entries for path in internal_paths
    )


@pytest.mark.anyio
async def test_batch_hash_preserves_order_and_reports_each_missing_path(execution_runtime):
    runtime = execution_runtime
    runtime.workspace.create_file("thread", "a.txt", b"a")
    runtime.workspace.create_file("thread", "b.txt", b"bb")

    results = await runtime.workspace.abatch_hash_files("thread", ["b.txt", "missing.txt", "a.txt"])

    assert [item["path"] for item in results] == ["b.txt", "missing.txt", "a.txt"]
    assert results[1] == {"path": "missing.txt", "missing": True}
    assert results[0]["sha256"] == hashlib.sha256(b"bb").hexdigest()


@pytest.mark.anyio
async def test_third_identical_read_is_blocked_until_real_progress(execution_runtime):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)

    first = await toolkit.coding_list_files(run_context=runtime.context)
    second = await toolkit.coding_list_files(run_context=runtime.context)
    blocked = await toolkit.coding_list_files(run_context=runtime.context)

    assert first == second
    assert blocked["code"] == "tool_no_progress"
    assert blocked["requiredActions"]
    assert blocked["retryable"] is True

    await toolkit.patch("create", path="progress.txt", content="done", run_context=runtime.context)
    progressed = await toolkit.coding_list_files(run_context=runtime.context)
    assert any(item["path"] == "progress.txt" for item in progressed)


@pytest.mark.anyio
async def test_alternating_reads_are_blocked_when_they_repeat_without_progress(
    execution_runtime,
):
    runtime = execution_runtime
    runtime.workspace.create_file("thread", "input.txt", b"data")
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)

    await toolkit.coding_list_files(run_context=runtime.context)
    await toolkit.coding_read_file("input.txt", run_context=runtime.context)
    await toolkit.coding_list_files(run_context=runtime.context)
    await toolkit.coding_read_file("input.txt", run_context=runtime.context)
    blocked = await toolkit.coding_list_files(run_context=runtime.context)

    assert blocked["code"] == "tool_no_progress"


@pytest.mark.anyio
async def test_agno_tool_batch_caps_reads_and_prioritizes_skill_script_execution(
    execution_runtime,
):
    runtime = execution_runtime
    assert MAX_PARALLEL_READ_TOOLS == 10
    hook = create_coding_tool_scheduler_hook(runtime.repository)
    active_reads = 0
    started_reads = 0
    first_batch_started = asyncio.Event()
    release_reads = asyncio.Event()
    writer_started = asyncio.Event()
    release_writer = asyncio.Event()

    async def read_reference(reference_path: str):
        nonlocal active_reads, started_reads
        active_reads += 1
        started_reads += 1
        if active_reads == MAX_PARALLEL_READ_TOOLS:
            first_batch_started.set()
        await release_reads.wait()
        active_reads -= 1
        return {"reference": reference_path}

    async def execute_script(script_path: str, execute: bool):
        assert execute is True
        writer_started.set()
        await release_writer.wait()
        return {"script": script_path}

    read_function = Function(
        name="get_skill_reference",
        entrypoint=read_reference,
        tool_hooks=[hook],
    )
    write_function = Function(
        name="get_skill_script",
        entrypoint=execute_script,
        tool_hooks=[hook],
    )
    read_function._run_context = runtime.context
    write_function._run_context = runtime.context
    calls = [
        FunctionCall(
            function=read_function,
            arguments={"reference_path": f"reference-{index}.md"},
            call_id=f"read-{index}",
        )
        for index in range(MAX_PARALLEL_READ_TOOLS + 1)
    ]
    calls.append(
        FunctionCall(
            function=write_function,
            arguments={"script_path": "validate.py", "execute": True},
            call_id="write",
        )
    )
    results = []

    async def run_batch():
        async for _event in OpenAIChat(id="test").arun_function_calls(
            function_calls=calls,
            function_call_results=results,
        ):
            pass

    batch = asyncio.create_task(run_batch())
    await asyncio.wait_for(first_batch_started.wait(), timeout=1)
    scheduler_key = (id(runtime.repository), "external-run")
    assert scheduler_key in execution_module._TASK_TOOL_SCHEDULERS
    assert active_reads == MAX_PARALLEL_READ_TOOLS
    assert started_reads == MAX_PARALLEL_READ_TOOLS

    release_reads.set()
    await asyncio.wait_for(writer_started.wait(), timeout=1)
    assert started_reads == MAX_PARALLEL_READ_TOOLS

    release_writer.set()
    await asyncio.wait_for(batch, timeout=1)

    assert started_reads == MAX_PARALLEL_READ_TOOLS + 1
    assert len(results) == MAX_PARALLEL_READ_TOOLS + 2
    assert scheduler_key not in execution_module._TASK_TOOL_SCHEDULERS


@pytest.mark.anyio
async def test_tool_scheduler_is_released_after_hook_failure(execution_runtime):
    runtime = execution_runtime
    hook = create_coding_tool_scheduler_hook(runtime.repository)

    async def fail(reference_path: str):
        raise RuntimeError(reference_path)

    with pytest.raises(RuntimeError, match="broken.md"):
        await hook(runtime.context, "get_skill_reference", fail, {"reference_path": "broken.md"})

    assert (id(runtime.repository), "external-run") not in execution_module._TASK_TOOL_SCHEDULERS


@pytest.mark.anyio
async def test_reporting_wrapper委托通用工具时同一任务写锁可重入(execution_runtime):
    runtime = execution_runtime
    hook = create_coding_tool_scheduler_hook(runtime.repository)

    async def verify_report_draft():
        # Reporting 专用工具由 Agno hook 持有外层任务写锁；正式验收随后委托
        # WorkspaceTaskToolkit.verify，并会再次进入同一任务调度器。两层调用在
        # 同一个 asyncio Task 内，必须复用写锁，否则 validator 尚未启动就会死锁。
        async with runtime.kernel.task_scheduler("external-run") as scheduler:
            async with scheduler.write():
                return {"ok": True}

    result = await asyncio.wait_for(
        hook(runtime.context, "verify_report_draft", verify_report_draft, {}),
        timeout=0.2,
    )

    assert result == {"ok": True}
    assert (id(runtime.repository), "external-run") not in execution_module._TASK_TOOL_SCHEDULERS


@pytest.mark.anyio
async def test_create_files_defers_scheduling_to_atomic_patch_kernel():
    repository = object()
    hook = create_coding_tool_scheduler_hook(repository)  # type: ignore[arg-type]
    context = RunContext(run_id="run", session_id="thread", user_id="user")
    scheduler_key = (id(repository), "external-run")

    async def create_files(files):
        assert scheduler_key not in execution_module._TASK_TOOL_SCHEDULERS
        return files

    files = [{"path": "one.py", "content": "value = 1\n"}]

    assert await hook(context, "create_files", create_files, {"files": files}) == files


@pytest.mark.anyio
async def test_view_image_and_file_read_overlap(execution_runtime):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    active = 0
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def read(name: str):
        nonlocal active
        active += 1
        if active == 2:
            both_started.set()
        await release.wait()
        active -= 1
        return {"name": name}

    file_read = asyncio.create_task(
        toolkit._invoke(
            "read_file",
            {"path": "source.txt"},
            lambda _scope: read("file"),
            runtime.context,
        )
    )
    image_read = asyncio.create_task(
        toolkit._invoke(
            "view_image",
            {"path": "chart.png", "detail": "high"},
            lambda _scope: read("image"),
            runtime.context,
        )
    )

    await asyncio.wait_for(both_started.wait(), timeout=1)
    release.set()
    assert await asyncio.gather(file_read, image_read) == [
        {"name": "file"},
        {"name": "image"},
    ]


@pytest.mark.anyio
async def test_parallel_read_completion_merges_progress_failures_and_output_handles(
    execution_runtime,
):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    started = 0
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def failed_read(path: str):
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await release.wait()
        return {
            "ok": False,
            "exit_code": 1,
            "output": f"cannot read {path}\n" + (path[-1] * (60 * 1024)),
        }

    calls = [
        asyncio.create_task(
            toolkit._invoke(
                "terminal",
                {"command": f"cat {path}"},
                lambda _scope, path=path: failed_read(path),
                runtime.context,
            )
        )
        for path in ("/tmp/a", "/tmp/b")
    ]
    await asyncio.wait_for(both_started.wait(), timeout=1)
    release.set()
    results = await asyncio.gather(*calls)

    progress = runtime.context.session_state[CODING_TOOL_PROGRESS_STATE_KEY]
    failures = runtime.context.session_state[CODING_TOOL_FAILURE_STATE_KEY]
    outputs = runtime.context.session_state[CODING_TOOL_OUTPUT_STATE_KEY]
    assert len(progress["entries"]) == 2
    assert {entry["resource"] for entry in failures["entries"]} == {"/tmp/a", "/tmp/b"}
    assert len(outputs["handles"]) == 2
    assert len(outputs["tasks"]["external-run"]["handles"]) == 2
    assert len({result["outputHandle"] for result in results}) == 2


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected"),
    [
        ("get_skill_instructions", {}, True),
        ("get_skill_reference", {}, True),
        ("get_skill_script", {"execute": False}, True),
        ("get_skill_script", {"execute": True}, False),
        ("get_skill_script", {"execute": 0}, False),
        ("report_list_data_sources", {}, True),
        ("report_describe_data_source", {}, True),
        ("inspect_profile_index", {}, True),
        ("read_profile_pointer", {}, True),
        ("report_materialize_dataset", {}, False),
        ("report_prepare_dataset", {}, False),
        ("unknown_tool", {}, False),
    ],
)
def test_skill_and_report_tool_scheduler_classification(tool_name, arguments, expected):
    assert _task_tool_parallel_safe(tool_name, arguments) is expected


@pytest.mark.anyio
async def test_read_only_terminal_does_not_increment_mutation(execution_runtime):
    runtime = execution_runtime

    before = await runtime.repository.get_task("external-run")
    read = await runtime.kernel.terminal(
        "pwd && ls -la | head",
        background=True,
        run_context=runtime.context,
    )
    after_read = await runtime.repository.get_task("external-run")
    write = await runtime.kernel.terminal(
        "printf changed > result.txt",
        background=True,
        run_context=runtime.context,
    )
    after_write = await runtime.repository.get_task("external-run")

    assert before is not None and after_read is not None and after_write is not None
    assert read["mutation_sequence"] == before.mutation_sequence
    assert after_read.mutation_sequence == before.mutation_sequence
    assert write["mutation_sequence"] == before.mutation_sequence + 1
    assert after_write.mutation_sequence == before.mutation_sequence + 1


@pytest.mark.anyio
async def test_verify_reuses_current_mutation_and_allows_dev_null(execution_runtime, monkeypatch):
    runtime = execution_runtime
    commands = []
    original_managed_command = runtime.kernel._managed_command

    def managed_command(command, workdir, timeout, pty):
        commands.append(command)
        return original_managed_command(command, workdir, timeout, pty)

    monkeypatch.setattr(runtime.kernel, "_managed_command", managed_command)
    await runtime.kernel.patch(
        "create",
        "result.txt",
        None,
        None,
        False,
        None,
        runtime.context,
        content="done\n",
    )
    before = await runtime.repository.get_task("external-run")

    verification_id = await completed_verification(runtime, "python -m pytest -q")

    after = await runtime.repository.get_task("external-run")
    execution = await runtime.repository.get_execution(verification_id)
    assert before is not None and after is not None and execution is not None
    assert execution.mutation_sequence == before.mutation_sequence
    assert after.mutation_sequence == before.mutation_sequence
    assert any("--write-root /dev/null" in command for command in commands)


@pytest.mark.anyio
async def test_unknown_foreground_terminal_only_records_real_workspace_mutation(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    fingerprints = iter(["before-read", "before-read", "before-write", "after-write"])

    async def fingerprint(_thread_id):
        return next(fingerprints)

    async def wait_for_terminal_execution(previous_count):
        for _attempt in range(100):
            await asyncio.sleep(0)
            executions = await runtime.repository.list_executions("external-run")
            if len(executions) > previous_count and executions[-1].command_id is not None:
                return executions[-1]
        raise AssertionError("terminal execution 未启动")

    monkeypatch.setattr(runtime.workspace, "aworkspace_fingerprint", fingerprint)

    read_task = asyncio.create_task(
        runtime.kernel.terminal("python3 query.py", run_context=runtime.context)
    )
    read_execution = await wait_for_terminal_execution(0)
    finish_remote_execution(runtime, read_execution.execution_id)
    read = await read_task

    write_task = asyncio.create_task(
        runtime.kernel.terminal("python3 generate.py", run_context=runtime.context)
    )
    write_execution = await wait_for_terminal_execution(1)
    finish_remote_execution(runtime, write_execution.execution_id)
    write = await write_task
    task = await runtime.repository.get_task("external-run")

    assert task is not None
    assert read["mutation_sequence"] == 0
    assert write["mutation_sequence"] == 1
    assert task.mutation_sequence == 1


@pytest.mark.anyio
async def test_validation_state_rejects_terminal_without_side_effects(execution_runtime):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    created = await toolkit.coding_create_file("result.txt", "draft", runtime.context)
    executions_before = await runtime.repository.list_executions("external-run")
    process_calls_before = len(runtime.synchronous.sandbox_for("thread").process.sessions)

    blocked = await toolkit.terminal("python3 query.py", run_context=runtime.context)
    executions_after = await runtime.repository.list_executions("external-run")
    process_calls_after = len(runtime.synchronous.sandbox_for("thread").process.sessions)

    assert created["mutation_sequence"] == 1
    assert blocked["code"] == "coding_verification_required"
    assert blocked["details"]["mutationSequence"] == 1
    assert executions_after == executions_before
    assert process_calls_after == process_calls_before


@pytest.mark.anyio
async def test_validation_state_rejects_intermediate_plan_update(execution_runtime):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    await toolkit.coding_create_file("result.txt", "draft", runtime.context)

    blocked = await toolkit.update_plan(
        [{"step": "验证", "status": "in_progress"}],
        run_context=runtime.context,
    )

    assert blocked["code"] == "coding_verification_required"
    assert AGENT_PLAN_STATE_KEY not in runtime.context.session_state


@pytest.mark.anyio
async def test_incomplete_plan_keeps_iteration_open_until_plan_is_completed(
    execution_runtime,
):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    await toolkit.update_plan(
        [
            {"step": "生成中间产物", "status": "in_progress"},
            {"step": "验证最终产物", "status": "pending"},
        ],
        run_context=runtime.context,
    )
    await toolkit.coding_create_file("result.txt", "draft", runtime.context)
    scope = await runtime.kernel.scope(runtime.context)

    admission = await toolkit._state_admission_rejection(
        scope,
        "terminal",
        {"command": "python3 generate.py"},
        runtime.context.session_state,
    )
    advanced = await toolkit.update_plan(
        [
            {"step": "生成中间产物", "status": "completed"},
            {"step": "验证最终产物", "status": "in_progress"},
        ],
        run_context=runtime.context,
    )
    completed = await toolkit.update_plan(
        [
            {"step": "生成中间产物", "status": "completed"},
            {"step": "验证最终产物", "status": "completed"},
        ],
        run_context=runtime.context,
    )
    completed_scope = await runtime.kernel.scope(runtime.context)
    blocked = await toolkit._state_admission_rejection(
        completed_scope,
        "terminal",
        {"command": "python3 generate.py"},
        runtime.context.session_state,
    )

    assert admission is None
    assert advanced["ok"] is True
    assert completed["ok"] is True
    assert blocked is not None
    assert blocked["code"] == "coding_verification_required"


@pytest.mark.anyio
async def test_verified_state_rejects_reads_and_requires_finish_but_keeps_plan_available(
    execution_runtime,
):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    await toolkit.coding_create_file("result.txt", "done", runtime.context)
    verification_task = asyncio.create_task(toolkit.verify("verify", run_context=runtime.context))
    verification_id = None
    for _attempt in range(100):
        await asyncio.sleep(0)
        executions = await runtime.repository.list_executions("external-run")
        verification_id = next(
            (
                execution.execution_id
                for execution in reversed(executions)
                if execution.is_verification and execution.command_id is not None
            ),
            None,
        )
        if verification_id is not None:
            break
    assert verification_id is not None
    finish_remote_execution(runtime, verification_id)
    verification = await verification_task
    assert verification["status"] == "completed"

    blocked = await toolkit.terminal("python3 query.py", run_context=runtime.context)
    blocked_read = await toolkit.coding_list_files(run_context=runtime.context)
    plan = await toolkit.update_plan(
        [{"step": "完成", "status": "completed"}],
        run_context=runtime.context,
    )

    assert blocked["code"] == "coding_finish_required"
    assert blocked["details"]["verificationId"] == verification_id
    assert blocked_read["code"] == "coding_finish_required"
    assert blocked_read["details"]["allowedTools"] == ["finish_task", "update_plan"]
    assert plan["ok"] is True


@pytest.mark.anyio
async def test_verified_state_in_progress_plan_reopens_work_and_invalidates_old_verification(
    execution_runtime,
):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    await toolkit.coding_create_file("result.txt", "done", runtime.context)
    verification_id = await completed_verification(runtime)

    reopened = await toolkit.update_plan(
        [{"step": "修正异常结果", "status": "in_progress"}],
        run_context=runtime.context,
    )
    readable = await toolkit.coding_read_file("result.txt", run_context=runtime.context)
    changed = await toolkit.replace_text(
        "result.txt", "done", "corrected", run_context=runtime.context
    )
    blocked = await toolkit.terminal("python3 verify.py", run_context=runtime.context)

    assert reopened["ok"] is True
    assert readable["content"] == "done"
    assert changed["mutation_sequence"] == 2
    assert blocked["code"] == "coding_verification_required"
    assert blocked["details"]["mutationSequence"] == 2
    assert blocked["details"].get("failedVerificationId") != verification_id


@pytest.mark.anyio
async def test_replace_text内容不变时不记录mutation(tmp_path):
    workspace = service(tmp_path)
    workspace.create_file("thread", "result.txt", b"done")
    kernel = CodingExecutionKernel(workspace, SimpleNamespace())
    scope = CodingTaskScope(
        task=SimpleNamespace(mutation_sequence=7),
        external_run_id="external-run",
        internal_run_id="internal-run",
        owner_user_id="user",
        thread_id="thread",
        sandbox_id=str(workspace.sandbox_for("thread").id),
        lease_owner="lease",
        lease_epoch=1,
        attempt_no=0,
    )

    result = await kernel.patch(
        "replace",
        "result.txt",
        "done",
        "done",
        False,
        None,
        None,
        _scope=scope,
    )

    assert result["code"] == "tool_no_progress"
    assert result["details"]["mutationSequence"] == 7
    assert workspace.file_bytes("thread", "result.txt")[0] == b"done"


@pytest.mark.anyio
async def test_finish_artifact_failure_returns_complete_repair_gate(execution_runtime):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    await toolkit.coding_create_file("generate_report.py", "print('report')", runtime.context)
    verification_id = await completed_verification(runtime)
    runtime.context.session_state[AGENT_PLAN_STATE_KEY] = {
        "plan": [{"step": "生成报告", "status": "completed"}]
    }
    failure = await runtime.kernel.finish_task(
        "done",
        ["reports/ruijin-2025.pdf"],
        [verification_id],
        [],
        runtime.context,
        Function(name="finish_task"),
    )
    executions_before = await runtime.repository.list_executions("external-run")

    blocked_terminal = await toolkit.terminal(
        "python3 generate_report.py", run_context=runtime.context
    )
    reopened_plan = await toolkit.update_plan(
        [{"step": "修复缺失报告路径", "status": "in_progress"}],
        run_context=runtime.context,
    )
    repair_read = await toolkit.coding_read_file("generate_report.py", run_context=runtime.context)
    scope = await runtime.kernel.scope(runtime.context)
    verify_admission = await toolkit._state_admission_rejection(
        scope,
        "verify",
        {
            "command": "python3 generate_report.py",
            "artifact_paths": ["reports/ruijin-2025.pdf"],
        },
        runtime.context.session_state,
    )
    executions_after = await runtime.repository.list_executions("external-run")

    assert failure["code"] == "finish_artifact_missing"
    assert blocked_terminal["code"] == "coding_finish_repair_required"
    assert blocked_terminal["details"]["finishFailureCode"] == "finish_artifact_missing"
    assert blocked_terminal["details"]["missingPaths"] == ["reports/ruijin-2025.pdf"]
    assert "read_file" in blocked_terminal["details"]["allowedTools"]
    assert blocked_terminal["requiredActions"] == [
        "核对 details.missingPaths：若路径声明错误，下一次 finish_task 使用实际存在的 "
        "artifact_paths；若确为必需产物，生成后调用 verify，再用实际存在路径重新提交。"
    ]
    assert reopened_plan["ok"] is True
    assert "print('report')" in repair_read["content"]
    assert runtime.context.session_state[AGENT_PLAN_STATE_KEY]["plan"] == [
        {"step": "修复缺失报告路径", "status": "in_progress"}
    ]
    assert verify_admission is None
    assert executions_after == executions_before


@pytest.mark.anyio
async def test_mutation_zero_finish_failure_still_requires_verification(execution_runtime):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    runtime.context.session_state[CODING_FINISH_FAILURE_STATE_KEY] = {
        "code": "finish_artifact_missing",
        "details": {"mutationSequence": 0, "missingPaths": ["report.pdf"]},
        "requiredActions": ["生成缺失产物并验证。"],
    }

    blocked = await toolkit.terminal("python3 generate.py", run_context=runtime.context)

    assert blocked["code"] == "coding_verification_required"
    assert await runtime.repository.list_executions("external-run") == []


@pytest.mark.anyio
async def test_repeated_read_only_terminal_is_blocked_without_new_execution(execution_runtime):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)

    first = await toolkit.terminal("pwd && ls", background=True, run_context=runtime.context)
    second = await toolkit.terminal("pwd && ls", background=True, run_context=runtime.context)
    blocked = await toolkit.terminal("pwd && ls", background=True, run_context=runtime.context)

    assert first["status"] == second["status"] == "running"
    assert blocked["code"] == "tool_no_progress"
    assert len(await runtime.repository.list_executions("external-run")) == 2


@pytest.mark.anyio
async def test_failed_absolute_path_is_blocked_across_terminal_and_verify(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    original = AsyncFakeProcess.execute_session_command

    async def fail_invalid_workspace(process, session_id, request, timeout=None):
        result = await original(process, session_id, request, timeout=timeout)
        command = await process.get_session_command(session_id, result.cmd_id)
        if "cd /workspace" in request.command:
            command.output = "/bin/sh: 1: cd: can't cd to /workspace\n"
            command.exit_code = 2
        else:
            command.output = "verified\n"
            command.exit_code = 0
        return result

    monkeypatch.setattr(AsyncFakeProcess, "execute_session_command", fail_invalid_workspace)

    failed = await toolkit.terminal(
        "cd /workspace && python3 generate.py",
        run_context=runtime.context,
    )
    blocked = await toolkit.verify(
        "cd /workspace && python3 verify.py",
        timeout=30,
        run_context=runtime.context,
    )
    recovered = await toolkit.verify(
        "python3 verify.py",
        timeout=30,
        run_context=runtime.context,
    )

    assert failed["status"] == "failed"
    assert blocked["code"] == "tool_no_progress"
    assert blocked["details"]["failedResource"] == "/workspace"
    assert blocked["details"]["workspaceRoot"] == "/home/daytona/workspace"
    assert blocked["requiredActions"]
    assert blocked["retryable"] is True
    assert recovered["status"] == "completed"
    assert len(await runtime.repository.list_executions("external-run")) == 2


def test_absolute_paths_distinguishes_unicode_relative_and_absolute_paths():
    relative = "python3 \u62a5\u8868/\u667a\u80fd\u5206\u6790/report-run-1/analysis.py"
    absolute = (
        'File "/home/daytona/workspace/\u62a5\u8868/\u667a\u80fd\u5206\u6790/'
        'report-run-1/analysis.py", line 1'
    )

    assert _absolute_paths(relative) == set()
    assert _absolute_paths(absolute) == {
        "/home/daytona/workspace/\u62a5\u8868/\u667a\u80fd\u5206\u6790/report-run-1/analysis.py"
    }


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("pwd && ls -la | head", True),
        ("find . -maxdepth 2 -type f -print", True),
        ("find . -type f 2>/dev/null", True),
        ("git -C repo status --short", True),
        ("printf changed > result.txt", False),
        ("find . -exec touch {} +", False),
        ("rg --pre cat pattern", False),
        ("git diff --ext-diff", False),
        ("python inspect.py", False),
    ],
)
def test_read_only_terminal_classifier_is_conservative(command, expected):
    assert execution_module._is_read_only_terminal_command(command) is expected


def test_workspace_coding_tools_have_explicit_schemas_and_split_mutations():
    toolkit = WorkspaceCodingToolkit(None, None)  # type: ignore[arg-type]
    tools = {**toolkit.functions, **toolkit.async_functions}

    assert 'list_files(path="")' in toolkit.instructions
    assert "禁止传 /workspace" in toolkit.instructions
    assert "patch" not in tools
    assert "create_file" not in tools
    assert {
        "create_files",
        "overwrite_file",
        "replace_text",
        "apply_patch",
    }.issubset(tools)
    create_files = tools["create_files"]
    assert create_files.parameters["properties"]["files"]["minItems"] == 1
    for name in (
        "list_files",
        "read_file",
        "read_lines",
        "search_text",
        "tree",
        "git_status",
        "git_diff",
        "view_image",
    ):
        schema = tools[name].parameters
        assert schema["type"] == "object"
        assert schema["properties"]
        assert schema["additionalProperties"] is False

    list_files = tools["list_files"]
    assert "本次 assistant 工具批次中的唯一调用" in tools["terminal"].description
    assert 'path 传空字符串 ""' in list_files.description
    assert '根目录必须传空字符串 ""' in list_files.parameters["properties"]["path"]["description"]

    assert set(tools["read_lines"].parameters["properties"]) == {
        "path",
        "start_line",
        "end_line",
    }
    assert set(tools["search_text"].parameters["properties"]) == {
        "pattern",
        "path",
        "limit",
    }


@pytest.mark.anyio
async def test_finish_entrypoint_stops_registered_agno_function_after_acceptance(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    finish_function = toolkit.async_functions["finish_task"]
    parsed_clone = copy(finish_function)

    async def accepted(*_args, **_kwargs):
        return {"ok": True, "status": "accepted", "digest": "done"}

    async def no_cleanup(*_args, **_kwargs):
        return None

    monkeypatch.setattr(toolkit.kernel, "finish_task", accepted)
    monkeypatch.setattr(toolkit.kernel, "cleanup_tool_outputs", no_cleanup)

    parsed_clone._run_context = runtime.context
    function_call = FunctionCall(
        function=parsed_clone,
        arguments={"summary": "done", "artifact_paths": []},
        call_id="finish-call",
    )
    execution_result = await function_call.aexecute()

    assert execution_result.status == "success"
    assert execution_result.result["status"] == "accepted"
    assert finish_function.stop_after_tool_call is True
    assert parsed_clone.stop_after_tool_call is True


@pytest.mark.anyio
async def test_coding基础工具自动展开唯一一层arguments包装(execution_runtime):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    assert all(
        function.pre_hook is normalize_coding_function_call_arguments
        for function in (*toolkit.functions.values(), *toolkit.async_functions.values())
    )
    function = copy(toolkit.async_functions["create_files"])

    async def passthrough_tool_hook(run_context, function_name, function_call, arguments):
        assert run_context is runtime.context
        assert function_name == "create_files"
        return await function_call(**arguments)

    function.tool_hooks = [passthrough_tool_hook]
    function._run_context = runtime.context
    call = FunctionCall(
        function=function,
        arguments={"arguments": {"files": [{"path": "wrapped.py", "content": "print(1)\n"}]}},
        call_id="wrapped-create-files",
    )

    result = await call.aexecute()

    assert result.status == "success"
    assert result.result["ok"] is True
    assert (
        runtime.synchronous.sandbox_for("thread").fs.entries["/home/daytona/workspace/wrapped.py"][
            1
        ]
        == b"print(1)\n"
    )
    assert runtime.context.session_state[CODING_TOOL_ARGUMENT_AUTOFIX_STATE_KEY] == [
        {
            "code": "coding_tool_arguments_unwrapped",
            "toolName": "create_files",
            "mutationSequence": 0,
        }
    ]


@pytest.mark.anyio
async def test_coding基础工具按schema恢复json字符串数组(execution_runtime):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    function = copy(toolkit.async_functions["create_files"])

    async def passthrough_tool_hook(run_context, function_name, function_call, arguments):
        assert run_context is runtime.context
        assert function_name == "create_files"
        return await function_call(**arguments)

    function.tool_hooks = [passthrough_tool_hook]
    function._run_context = runtime.context
    call = FunctionCall(
        function=function,
        arguments={
            "files": json.dumps([{"path": "schema-array.py", "content": "print('schema')\n"}])
        },
        call_id="schema-array-create-files",
    )

    result = await call.aexecute()

    assert result.status == "success"
    assert result.result["ok"] is True
    assert (
        runtime.synchronous.sandbox_for("thread").fs.entries[
            "/home/daytona/workspace/schema-array.py"
        ][1]
        == b"print('schema')\n"
    )


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            {"arguments": {"files": []}, "timeout": 30},
            {"files": [], "timeout": 30},
        ),
        ({"arguments": '{"files":[]}'}, {"files": []}),
        (
            {"arguments": {"arguments": {"files": []}}},
            {"arguments": {"files": []}},
        ),
    ],
)
def test_coding基础工具arguments只做一层等价json规范化(arguments, expected):
    call = SimpleNamespace(
        arguments=arguments,
        function=SimpleNamespace(name="create_files"),
    )

    normalize_coding_function_call_arguments(call)

    assert call.arguments == expected


@pytest.mark.anyio
async def test_failed_parent_absolute_path_blocks_child_path(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    original = AsyncFakeProcess.execute_session_command

    async def fail_parent(process, session_id, request, timeout=None):
        result = await original(process, session_id, request, timeout=timeout)
        command = await process.get_session_command(session_id, result.cmd_id)
        command.output = "/bin/sh: 1: cd: can't cd to /workspace\n"
        command.exit_code = 2
        return result

    monkeypatch.setattr(AsyncFakeProcess, "execute_session_command", fail_parent)

    failed = await toolkit.terminal(
        "cd /workspace/report && python3 generate.py",
        run_context=runtime.context,
    )
    blocked = await toolkit.verify(
        "cd /workspace/report/output && python3 verify.py",
        timeout=30,
        run_context=runtime.context,
    )

    assert failed["status"] == "failed"
    assert blocked["code"] == "tool_no_progress"
    assert blocked["details"]["failedResource"] == "/workspace"


@pytest.mark.anyio
async def test_verify_rejects_command_not_found_even_with_zero_exit(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    original = AsyncFakeProcess.execute_session_command

    async def soft_failure(process, session_id, request, timeout=None):
        result = await original(process, session_id, request, timeout=timeout)
        command = await process.get_session_command(session_id, result.cmd_id)
        command.output = "/bin/sh: 29: bc: not found\nall checks passed\n"
        command.exit_code = 0
        return result

    monkeypatch.setattr(AsyncFakeProcess, "execute_session_command", soft_failure)

    result = await runtime.kernel.verify("verify artifacts", [], runtime.context, timeout=30)
    execution = await runtime.repository.get_execution(result["execution_id"])

    assert result["ok"] is False
    assert result["code"] == "verification_output_error"
    assert execution is not None
    assert execution.operation_receipt["valid"] is False
    assert not await runtime.repository.successful_verification(
        "external-run",
        result["execution_id"],
        result["mutation_sequence"],
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("output", "failure_code"),
    [
        ("/bin/sh: 29: xxd: not found\nwrapped command passed\n", "command_not_found"),
        (
            "Traceback (most recent call last):\n"
            '  File "verify.py", line 1, in <module>\n'
            "NameError: name 'pd' is not defined\n",
            "python_traceback",
        ),
    ],
)
async def test_terminal_rejects_deterministic_errors_hidden_by_zero_exit(
    execution_runtime,
    monkeypatch,
    output,
    failure_code,
):
    runtime = execution_runtime
    original = AsyncFakeProcess.execute_session_command

    async def soft_failure(process, session_id, request, timeout=None):
        result = await original(process, session_id, request, timeout=timeout)
        command = await process.get_session_command(session_id, result.cmd_id)
        command.output = output
        command.exit_code = 0
        return result

    monkeypatch.setattr(AsyncFakeProcess, "execute_session_command", soft_failure)

    result = await runtime.kernel.terminal("python verify.py", run_context=runtime.context)

    assert result["ok"] is False
    assert result["code"] == "execution_output_error"
    assert result["details"]["failureCode"] == failure_code


@pytest.mark.anyio
async def test_verify_rejects_python_traceback_hidden_by_zero_exit(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    original = AsyncFakeProcess.execute_session_command

    async def soft_failure(process, session_id, request, timeout=None):
        result = await original(process, session_id, request, timeout=timeout)
        command = await process.get_session_command(session_id, result.cmd_id)
        command.output = (
            "Traceback (most recent call last):\n"
            '  File "verify.py", line 4, in <module>\n'
            "AssertionError: metric-001 citation 不匹配: have={'citation_006'} want=['citation_009']\n"
        )
        command.exit_code = 0
        return result

    monkeypatch.setattr(AsyncFakeProcess, "execute_session_command", soft_failure)

    result = await runtime.kernel.verify("python verify.py", [], runtime.context, timeout=30)
    execution = await runtime.repository.get_execution(result["execution_id"])

    assert result["ok"] is False
    assert result["code"] == "verification_output_error"
    assert result["details"]["failureCode"] == "python_traceback"
    assert "事实卡" in result["requiredActions"][0]
    assert execution is not None
    assert execution.operation_receipt["valid"] is False


@pytest.mark.anyio
async def test_verify_allows_nonfatal_stderr_warning(execution_runtime, monkeypatch):
    runtime = execution_runtime
    original = AsyncFakeProcess.execute_session_command

    async def warning(process, session_id, request, timeout=None):
        result = await original(process, session_id, request, timeout=timeout)
        command = await process.get_session_command(session_id, result.cmd_id)
        command.output = "warning: optional font unavailable\nchecks passed\n"
        command.exit_code = 0
        return result

    monkeypatch.setattr(AsyncFakeProcess, "execute_session_command", warning)

    result = await runtime.kernel.verify("verify artifacts", [], runtime.context, timeout=30)

    assert result["status"] == "completed"
    assert result.get("ok", True) is True
    execution = await runtime.repository.get_execution(result["execution_id"])
    assert execution is not None
    assert execution.operation_receipt["valid"] is True


@pytest.mark.anyio
async def test_toolkit_returns_structured_workspace_errors(execution_runtime):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)

    async def invalid_path(_scope):
        raise WorkspaceError("工作区路径是绝对路径，请改用相对路径。")

    async def conflict(_scope):
        raise WorkspacePathConflict("文件内容已变化。")

    invalid = await toolkit._invoke(
        "list_files", {"path": "/workspace/report"}, invalid_path, runtime.context
    )
    conflicted = await toolkit._invoke(
        "overwrite_file",
        {"path": "/home/daytona/workspace/report.md"},
        conflict,
        runtime.context,
    )

    assert invalid == {
        "ok": False,
        "status": "rejected",
        "code": "workspace_error",
        "message": "工作区路径是绝对路径，请改用相对路径。",
        "details": {"tool": "list_files", "suggestedPath": "report"},
        "requiredActions": ["按错误说明修正参数后重试。"],
        "retryable": True,
    }
    assert conflicted["code"] == "workspace_path_conflict"
    assert conflicted["details"]["suggestedPath"] == "report.md"
    assert conflicted["retryable"] is True


def test_session_output_prefers_structured_streams_and_strips_fallback_framing():
    toolkit = WorkspaceToolkit.__new__(WorkspaceToolkit)

    structured = toolkit._session_output(
        SimpleNamespace(
            output="\x01\x01\x01polluted stdout\n\x02\x02\x02polluted stderr",
            stdout="clean stdout",
            stderr="clean stderr",
        ),
        session_id="session",
        command_id="command",
        status="completed",
        exit_code=0,
    )
    fallback = toolkit._session_output(
        SimpleNamespace(output="\x01\x01\x01first\n\x02\x02\x02second"),
        session_id="session",
        command_id="command",
        status="completed",
        exit_code=0,
    )

    assert structured["output"] == "clean stdout\nclean stderr"
    assert fallback["output"] == "first\nsecond"


@pytest.mark.anyio
async def test_verify_rejects_modified_loaded_skill_script(execution_runtime):
    runtime = execution_runtime
    original = b"print('trusted')\n"
    runtime.context.session_state["agentos_coding_skill_script_receipts"] = {
        "report:validate_report.py": {
            "skill": "report",
            "path": "validate_report.py",
            "sha256": hashlib.sha256(original).hexdigest(),
        }
    }
    runtime.workspace.create_file("thread", "validate_report.py", b"print('modified')\n")

    result = await runtime.kernel.verify(
        "python validate_report.py report.md",
        [],
        runtime.context,
    )

    assert result["ok"] is False
    assert result["code"] == "verification_skill_script_modified"
    assert await runtime.repository.list_executions("external-run") == []


@pytest.mark.anyio
async def test_skill_script_verification_uses_server_receipt_without_database(monkeypatch):
    original = b"print('trusted')\n"
    modified = b"print('modified')\n"
    kernel = CodingExecutionKernel.__new__(CodingExecutionKernel)
    kernel.service = SimpleNamespace(file_bytes=lambda _thread, _path: (modified, "text/plain"))

    async def scope(_run_context):
        return SimpleNamespace(thread_id="thread")

    async def inline_to_thread(function, *args):
        return function(*args)

    kernel.scope = scope
    monkeypatch.setattr(asyncio, "to_thread", inline_to_thread)
    context = RunContext(
        run_id="run",
        session_id="thread",
        user_id="user",
        session_state={
            "agentos_coding_skill_script_receipts": {
                "report:validate_report.py": {
                    "skill": "report",
                    "path": "validate_report.py",
                    "sha256": hashlib.sha256(original).hexdigest(),
                }
            }
        },
    )

    result = await kernel._skill_script_verification_error(
        "python validate_report.py report.md", context
    )

    assert result is not None
    assert result["code"] == "verification_skill_script_modified"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("writer_tool", "writer_arguments"),
    [
        ("patch", {"mode": "test"}),
        ("terminal", {"command": "touch generated.txt"}),
        ("verify", {"validator_id": "analysis:report"}),
    ],
)
async def test_tool_scheduler_allows_parallel_reads_and_serializes_write(
    execution_runtime,
    monkeypatch,
    writer_tool,
    writer_arguments,
):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    scope = SimpleNamespace(
        external_run_id="external-run",
        attempt_no=0,
        task=SimpleNamespace(mutation_sequence=0),
    )

    async def resolve_scope(_run_context):
        return scope

    monkeypatch.setattr(toolkit.kernel, "scope", resolve_scope)
    both_reads_entered = asyncio.Event()
    release_reads = asyncio.Event()
    active_reads = 0
    write_entered = False

    async def read_call(_scope):
        nonlocal active_reads
        active_reads += 1
        if active_reads == 2:
            both_reads_entered.set()
        await release_reads.wait()
        active_reads -= 1
        return {"status": "ok"}

    async def write_call(_scope):
        nonlocal write_entered
        write_entered = True
        assert active_reads == 0
        return {"status": "ok"}

    reads = [
        asyncio.create_task(
            toolkit._invoke("git_status", {"repo_path": str(index)}, read_call, runtime.context)
        )
        for index in range(2)
    ]
    await both_reads_entered.wait()
    writer = asyncio.create_task(
        toolkit._invoke(writer_tool, writer_arguments, write_call, runtime.context)
    )
    await asyncio.sleep(0)
    assert write_entered is False
    release_reads.set()
    await asyncio.gather(*reads, writer)
    assert write_entered is True
    assert (
        id(runtime.repository),
        "external-run",
    ) not in execution_module._TASK_TOOL_SCHEDULERS


@pytest.mark.anyio
async def test_workspace_tool_scheduler_caps_parallel_reads(execution_runtime, monkeypatch):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    scope = SimpleNamespace(
        external_run_id="external-run",
        attempt_no=0,
        task=SimpleNamespace(mutation_sequence=0),
    )

    async def resolve_scope(_run_context):
        return scope

    monkeypatch.setattr(toolkit.kernel, "scope", resolve_scope)
    active_reads = 0
    started_reads = 0
    first_batch_started = asyncio.Event()
    release_reads = asyncio.Event()

    async def read_call(_scope):
        nonlocal active_reads, started_reads
        active_reads += 1
        started_reads += 1
        if active_reads == MAX_PARALLEL_READ_TOOLS:
            first_batch_started.set()
        await release_reads.wait()
        active_reads -= 1
        return {"status": "ok"}

    reads = [
        asyncio.create_task(
            toolkit._invoke("read_file", {"path": f"{index}.txt"}, read_call, runtime.context)
        )
        for index in range(MAX_PARALLEL_READ_TOOLS + 1)
    ]

    await asyncio.wait_for(first_batch_started.wait(), timeout=1)
    await asyncio.sleep(0)
    assert active_reads == MAX_PARALLEL_READ_TOOLS
    assert started_reads == MAX_PARALLEL_READ_TOOLS

    release_reads.set()
    await asyncio.wait_for(asyncio.gather(*reads), timeout=1)
    assert started_reads == MAX_PARALLEL_READ_TOOLS + 1


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


@pytest.mark.anyio
async def test_finish_task_rejects_invalid_verification_receipt(execution_runtime):
    runtime = execution_runtime
    verification_id = await completed_verification(runtime)
    execution = await runtime.repository.get_execution(verification_id)
    assert execution is not None
    receipt = dict(execution.operation_receipt or {})
    receipt.update(
        valid=False,
        failure_code="verification_output_error",
        diagnostics=["command_not_found"],
    )
    await runtime.repository.update_execution(verification_id, operation_receipt=receipt)
    runtime.context.session_state[AGENT_PLAN_STATE_KEY] = {"plan": []}

    result = await runtime.kernel.finish_task(
        "done",
        [],
        [verification_id],
        [],
        runtime.context,
        Function(name="finish_task"),
    )

    assert result["code"] == "finish_verification_failed"
    details = result["details"]
    assert details["failureCode"] == "verification_output_error"
    assert details["diagnostics"] == ["command_not_found"]
    assert details["mutationSequence"] == execution.mutation_sequence
    assert details["verification"] == [
        {
            "executionId": verification_id,
            "status": "completed",
            "exitCode": 0,
            "mutationSequence": execution.mutation_sequence,
            "current": False,
            "valid": False,
        }
    ]
    assert details["activeProcesses"] == []
    assert result["requiredActions"] == ["修复验证错误，并在当前 mutation 上重新运行验证。"]


@pytest.mark.anyio
async def test_update_plan_declares_schema_and_returns_stable_missing_argument_error():
    toolkit = WorkspaceCodingToolkit(None, None)  # type: ignore[arg-type]
    function = toolkit.async_functions["update_plan"]

    assert function.parameters["required"] == ["plan"]
    assert function.parameters["properties"]["plan"]["items"]["required"] == [
        "step",
        "status",
    ]
    assert (await function.entrypoint())["code"] == "plan_required"


@pytest.mark.anyio
async def test_verify_declares_and_forwards_bounded_timeout(execution_runtime, monkeypatch):
    runtime = execution_runtime
    toolkit = WorkspaceCodingToolkit(runtime.workspace, runtime.repository)
    function = toolkit.async_functions["verify"]
    captured = []

    async def verify(command, artifact_paths, run_context, *, validator_id, timeout, _scope):
        captured.append((command, validator_id, artifact_paths, run_context, timeout, _scope))
        return {"ok": True, "status": "completed", "exit_code": 0}

    monkeypatch.setattr(toolkit.kernel, "verify", verify)

    result = await function.entrypoint(
        command="true",
        timeout=17,
        run_context=runtime.context,
    )

    timeout_schema = function.parameters["properties"]["timeout"]
    assert timeout_schema == {
        "type": "integer",
        "minimum": 1,
        "maximum": 86_400,
        "default": 900,
    }
    assert function.parameters["oneOf"] == [
        {"required": ["command"]},
        {"required": ["validator_id"]},
    ]
    assert result["ok"] is True
    assert len(captured) == 1
    assert captured[0][:5] == ("true", None, [], runtime.context, 17)
    assert isinstance(captured[0][5], CodingTaskScope)

    with pytest.raises(WorkspaceError, match="verify timeout"):
        await runtime.kernel.verify("true", [], runtime.context, timeout=0)


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
