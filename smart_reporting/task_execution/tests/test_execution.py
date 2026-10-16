import asyncio
import hashlib
import os
from copy import copy
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools import Function
from agno.tools.function import FunctionCall
from sqlalchemy import text

import smart_reporting.task_execution.execution as execution_module
from smart_reporting.agent_control import AGENT_PLAN_STATE_KEY
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope
from smart_reporting.runtime.database import create_agent_database
from smart_reporting.skills import (
    TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY,
    skill_script_receipt_hook,
)
from smart_reporting.task_execution.execution import (
    MAX_PARALLEL_READ_TOOLS,
    TASK_EXECUTION_DEPENDENCY,
    TASK_EXECUTION_TOOL_OUTPUT_STATE_KEY,
    TaskExecutionKernel,
    TaskExecutionRuntime,
    _task_tool_parallel_safe,
    absolute_paths,
    create_task_tool_scheduler_hook,
    normalize_task_function_call_arguments,
)
from smart_reporting.task_execution.models import Lease, TaskExecutionScope
from smart_reporting.task_execution.repository import (
    TaskExecutionRepository,
    TaskExecutionRepositoryError,
)
from smart_reporting.workspace import WorkspaceError, WorkspacePathConflict

pytestmark = pytest.mark.integration

SECRET = "0123456789abcdef0123456789abcdef"


def local_workspace(tmp_path, thread_id: str = "thread") -> ReportingWorkspaceRouter:
    registry = ReportingWorkspaceRegistry(tmp_path / "workspaces", secret=SECRET)
    registry.resolve(
        ReportingWorkflowScope(
            run_id="run",
            external_run_id="external-run",
            session_id="report-session",
            caller_thread_id=thread_id,
            user_id="user",
            database="database",
            company_id="company",
            thread_lease_key="lease",
            workspace_key=thread_id,
        )
    )
    return ReportingWorkspaceRouter(registry)


def runtime_scope(thread_id: str = "thread", mutation_sequence: int = 0) -> TaskExecutionRuntime:
    return TaskExecutionRuntime(
        task=SimpleNamespace(mutation_sequence=mutation_sequence),
        external_run_id="external-run",
        internal_run_id="internal-run",
        owner_user_id="user",
        thread_id=thread_id,
        sandbox_id=thread_id,
        lease_owner="lease",
        lease_epoch=1,
        attempt_no=0,
    )


@pytest.fixture
async def execution_runtime(tmp_path):
    database_url = os.getenv("REPORTING_TEST_DB_URL", "").strip()
    if not database_url:
        pytest.skip("未设置 REPORTING_TEST_DB_URL，跳过 PostgreSQL 任务执行集成测试。")
    database = create_agent_database(database_url)
    repository = TaskExecutionRepository(database.async_db)
    await repository.initialize()
    async with database.async_engine.begin() as connection:
        await connection.execute(text("TRUNCATE agentos_coding.agentos_coding_tasks CASCADE"))
    workspace = local_workspace(tmp_path)
    task = await repository.create_task_with_initial_attempt(
        TaskExecutionScope("external-run", "user", "thread", "thread", "coding-agent"),
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
            TASK_EXECUTION_DEPENDENCY: {
                "externalRunId": "external-run",
                "leaseOwner": "request-a",
                "leaseEpoch": lease.epoch,
                "sandboxId": "thread",
            }
        },
    )
    yield SimpleNamespace(
        database=database,
        repository=repository,
        workspace=workspace,
        kernel=TaskExecutionKernel(workspace, repository),
        context=context,
    )
    async with database.async_engine.begin() as connection:
        await connection.execute(text("TRUNCATE agentos_coding.agentos_coding_tasks CASCADE"))
    await database.async_engine.dispose()
    database.sync_engine.dispose()


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
        TASK_EXECUTION_DEPENDENCY: dict(runtime.context.dependencies[TASK_EXECUTION_DEPENDENCY])
    }
    snapshot = await runtime.repository.get_task_snapshot("external-run")
    assert snapshot is not None
    if invalid == "owner":
        context.dependencies[TASK_EXECUTION_DEPENDENCY]["leaseOwner"] = "other-owner"
    elif invalid == "epoch":
        context.dependencies[TASK_EXECUTION_DEPENDENCY]["leaseEpoch"] += 1
    elif invalid == "epoch_type":
        context.dependencies[TASK_EXECUTION_DEPENDENCY]["leaseEpoch"] = True
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
        context.dependencies[TASK_EXECUTION_DEPENDENCY]["sandboxId"] = "other-sandbox"

    async def unexpected_claim(*_args, **_kwargs):
        raise AssertionError("v2 scope 不应重新领取租约")

    monkeypatch.setattr(runtime.repository, "claim_lease", unexpected_claim)
    with pytest.raises(TaskExecutionRepositoryError) as rejected:
        await runtime.kernel.scope(context)
    assert rejected.value.code == expected_code


@pytest.mark.anyio
async def test_legacy_scope_keeps_query_bind_and_claim_path(execution_runtime, monkeypatch):
    runtime = execution_runtime
    sandbox_id = "thread"
    await runtime.repository.create_task(
        external_run_id="legacy-run",
        owner_user_id="user",
        thread_id="thread",
        executor_id="coding-agent",
        sandbox_id=sandbox_id,
        deadline_at=execution_module.utcnow() + timedelta(minutes=5),
    )
    context = RunContext(
        run_id="legacy-internal-run",
        session_id="thread",
        user_id="user",
        session_state={},
        dependencies={
            TASK_EXECUTION_DEPENDENCY: {
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
async def test_skill_script_receipt_rejects_writable_copy(execution_runtime):
    runtime = execution_runtime
    body = "print('trusted')\n"

    async def read_script(**_kwargs):
        return {"skill_name": "report", "script_path": "validate.py", "content": body}

    await skill_script_receipt_hook(
        runtime.context,
        "get_skill_script",
        read_script,
        {"skill_name": "report", "script_path": "validate.py", "execute": False},
    )

    receipt = runtime.context.session_state[TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY][
        "report:validate.py"
    ]
    assert receipt["sha256"] == hashlib.sha256(body.encode()).hexdigest()

    with pytest.raises(WorkspaceError, match="get_skill_script"):
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


@pytest.mark.anyio
async def test_finish_task_enforces_plan_and_artifacts(execution_runtime):
    runtime = execution_runtime
    finish_function = Function(name="finish_task")
    runtime.context.session_state[AGENT_PLAN_STATE_KEY] = {
        "plan": [{"step": "生成产物", "status": "in_progress"}]
    }

    incomplete = await runtime.kernel.finish_task(
        "done", [], [], [], runtime.context, finish_function
    )
    assert incomplete["code"] == "finish_plan_incomplete"
    assert finish_function.stop_after_tool_call is False

    runtime.context.session_state[AGENT_PLAN_STATE_KEY]["plan"][0]["status"] = "completed"
    missing = await runtime.kernel.finish_task(
        "done", ["missing.txt"], [], [], runtime.context, finish_function
    )
    assert missing["code"] == "finish_artifact_missing"
    assert missing["details"]["missingPaths"] == ["missing.txt"]
    assert missing["details"]["mutationSequence"] == 0
    assert missing["requiredActions"]
    assert missing["retryable"] is True

    await runtime.kernel.patch(
        "create", "missing.txt", None, None, False, None, runtime.context, content="ready"
    )
    accepted = await runtime.kernel.finish_task(
        "done", ["missing.txt"], [], [], runtime.context, finish_function
    )
    assert accepted["status"] == "accepted", accepted
    assert accepted["verificationIds"] == []
    assert accepted["artifacts"][0]["sha256"] == hashlib.sha256(b"ready").hexdigest()
    assert finish_function.stop_after_tool_call is True


@pytest.mark.anyio
async def test_finish_task_rejects_identical_failed_gate_until_workspace_progress(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    runtime.context.session_state[AGENT_PLAN_STATE_KEY] = {"plan": []}
    hash_calls = 0
    original = runtime.workspace.abatch_hash_files

    async def count_hash(thread_id, paths):
        nonlocal hash_calls
        hash_calls += 1
        return await original(thread_id, paths)

    monkeypatch.setattr(runtime.workspace, "abatch_hash_files", count_hash)
    arguments = ("done", ["missing.txt"], [], [])

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

    await runtime.kernel.patch(
        "create", "unrelated.txt", None, None, False, None, runtime.context, content="x"
    )
    progressed = await runtime.kernel.finish_task(
        *arguments, runtime.context, Function(name="finish_task")
    )

    assert progressed["code"] == "finish_no_progress"
    assert hash_calls == 2

    await runtime.kernel.patch(
        "create", "missing.txt", None, None, False, None, runtime.context, content="ready"
    )
    accepted = await runtime.kernel.finish_task(
        *arguments, runtime.context, Function(name="finish_task")
    )

    assert accepted["status"] == "accepted"


@pytest.mark.anyio
async def test_finish_task_rejects_absolute_artifact_paths_without_hashing_or_fake_progress(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    runtime.context.session_state[AGENT_PLAN_STATE_KEY] = {"plan": []}
    hash_calls = 0
    original = runtime.workspace.abatch_hash_files

    async def count_hash(thread_id, paths):
        nonlocal hash_calls
        hash_calls += 1
        return await original(thread_id, paths)

    monkeypatch.setattr(runtime.workspace, "abatch_hash_files", count_hash)
    absolute = "/srv/workspace/report.html"
    first = await runtime.kernel.finish_task(
        "done",
        [absolute],
        [],
        [],
        runtime.context,
        Function(name="finish_task"),
    )

    assert first["code"] == "finish_artifact_path_invalid"
    assert first["details"]["invalidPaths"] == [absolute]
    assert first["requiredActions"] == ["把 details.invalidPaths 改为工作区相对路径。"]
    assert hash_calls == 0

    repeated = await runtime.kernel.finish_task(
        "changed summary",
        [absolute],
        [],
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
        [],
        [],
        runtime.context,
        Function(name="finish_task"),
    )
    assert relative["code"] == "finish_artifact_missing"
    assert hash_calls == 1


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

    metadata = runtime.context.session_state[TASK_EXECUTION_TOOL_OUTPUT_STATE_KEY]["handles"][
        bounded["outputHandle"]
    ]
    metadata["attempt"] += 1
    with pytest.raises(WorkspaceError, match="不属于当前"):
        await runtime.kernel.read_tool_output(bounded["outputHandle"], 0, 1024, runtime.context)


@pytest.mark.anyio
async def test_report_tool_output_honors_explicit_preview_window():
    kernel = object.__new__(TaskExecutionKernel)
    scope = SimpleNamespace(external_run_id="report-coding-visualization")
    output = "x" * (40 * 1024)

    bounded = await kernel.bound_tool_result(
        scope,
        {"output": output},
        None,
        preview_bytes=64 * 1024,
    )

    assert bounded["output"] == output
    assert "TOOL_OUTPUT_TRUNCATED" not in bounded["output"]


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
    page = await runtime.kernel.read_tool_output(retained["outputHandle"], 0, 1024, runtime.context)

    assert ordinary == result
    assert "outputHandle" not in ordinary
    assert retained["output"] == result["output"]
    assert retained["outputTruncated"] is False
    assert retained["outputDiscarded"] is False
    assert page["content"] == result["output"]
    assert page["hasMore"] is False


@pytest.mark.anyio
async def test_reporting_tool_output_uses_smaller_preview_and_exact_handle_reads(
    execution_runtime,
):
    runtime = execution_runtime
    external_run_id = "report-coding-preview-test"
    sandbox_id = "thread"
    task = await runtime.repository.create_task_with_initial_attempt(
        TaskExecutionScope(external_run_id, "user", "thread", sandbox_id, "coding-agent"),
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
            TASK_EXECUTION_DEPENDENCY: {
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
    assert len(bounded["output"].encode("utf-8")) <= execution_module.MAX_REPORT_TOOL_PREVIEW_BYTES
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
        for metadata in runtime.context.session_state[TASK_EXECUTION_TOOL_OUTPUT_STATE_KEY][
            "handles"
        ].values()
    }
    root = runtime.workspace.workspace("thread").identity.root
    assert any((root / path).exists() for path in internal_paths)

    await runtime.kernel.cleanup_tool_outputs(scope, runtime.context)

    assert not any((root / path).exists() for path in internal_paths)


@pytest.mark.anyio
async def test_batch_hash_preserves_order_and_reports_each_missing_path(execution_runtime):
    runtime = execution_runtime
    await runtime.workspace.awrite_bytes("thread", "a.txt", b"a")
    await runtime.workspace.awrite_bytes("thread", "b.txt", b"bb")

    results = await runtime.workspace.abatch_hash_files("thread", ["b.txt", "missing.txt", "a.txt"])

    assert [item["path"] for item in results] == ["b.txt", "missing.txt", "a.txt"]
    assert results[1] == {"path": "missing.txt", "missing": True}
    assert results[0]["sha256"] == hashlib.sha256(b"bb").hexdigest()


@pytest.mark.anyio
async def test_agno_tool_batch_caps_reads_and_prioritizes_skill_script_execution(
    execution_runtime,
):
    runtime = execution_runtime
    assert MAX_PARALLEL_READ_TOOLS == 10
    hook = create_task_tool_scheduler_hook(runtime.repository)
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
    hook = create_task_tool_scheduler_hook(runtime.repository)

    async def fail(reference_path: str):
        raise RuntimeError(reference_path)

    with pytest.raises(RuntimeError, match="broken.md"):
        await hook(runtime.context, "get_skill_reference", fail, {"reference_path": "broken.md"})

    assert (id(runtime.repository), "external-run") not in execution_module._TASK_TOOL_SCHEDULERS


@pytest.mark.anyio
async def test_reporting_wrapper委托通用工具时同一任务写锁可重入(execution_runtime):
    runtime = execution_runtime
    hook = create_task_tool_scheduler_hook(runtime.repository)

    async def verify_report_draft():
        # Reporting 专用工具由 Agno hook 持有外层任务写锁；正式验收随后委托
        # Reporting 验收会再次进入同一任务调度器。两层调用在
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
    hook = create_task_tool_scheduler_hook(repository)  # type: ignore[arg-type]
    context = RunContext(run_id="run", session_id="thread", user_id="user")
    scheduler_key = (id(repository), "external-run")

    async def create_files(files):
        assert scheduler_key not in execution_module._TASK_TOOL_SCHEDULERS
        return files

    files = [{"path": "one.py", "content": "value = 1\n"}]

    assert await hook(context, "create_files", create_files, {"files": files}) == files


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
async def test_replace_text内容不变时不记录mutation(tmp_path):
    workspace = local_workspace(tmp_path)
    await workspace.awrite_bytes("thread", "result.txt", b"done")
    kernel = TaskExecutionKernel(workspace, SimpleNamespace())

    result = await kernel.patch(
        "replace",
        "result.txt",
        "done",
        "done",
        False,
        None,
        None,
        _scope=runtime_scope(mutation_sequence=7),
    )

    assert result["code"] == "tool_no_progress"
    assert result["details"]["mutationSequence"] == 7
    assert (await workspace.afile_bytes("thread", "result.txt"))[0] == b"done"


@pytest.mark.anyio
async def test_patch_overwrites_local_workspace_file(tmp_path):
    workspace = local_workspace(tmp_path)
    await workspace.awrite_bytes("thread", "result.txt", b"before")
    repository = SimpleNamespace()
    stored = {}

    async def increment_mutation(*_args, **_kwargs):
        return 1

    async def reserve_execution(**kwargs):
        stored.update(kwargs)
        return SimpleNamespace(status="reserved")

    async def update_execution(_execution_id, **kwargs):
        return SimpleNamespace(status=kwargs["status"])

    repository.increment_mutation = increment_mutation
    repository.reserve_execution = reserve_execution
    repository.update_execution = update_execution
    kernel = TaskExecutionKernel(workspace, repository)

    result = await kernel.patch(
        "overwrite",
        "result.txt",
        None,
        None,
        False,
        None,
        None,
        content="after",
        expected_sha256=hashlib.sha256(b"before").hexdigest(),
        _scope=runtime_scope(),
    )

    assert result["ok"] is True
    assert (await workspace.afile_bytes("thread", "result.txt"))[0] == b"after"


@pytest.mark.anyio
def test_absolute_paths_distinguishes_unicode_relative_and_absolute_paths():
    relative = "python3 \u62a5\u8868/\u667a\u80fd\u5206\u6790/report-run-1/analysis.py"
    absolute = (
        'File "/srv/workspace/\u62a5\u8868/\u667a\u80fd\u5206\u6790/'
        'report-run-1/analysis.py", line 1'
    )

    assert absolute_paths(relative) == set()
    assert absolute_paths(absolute) == {
        "/srv/workspace/\u62a5\u8868/\u667a\u80fd\u5206\u6790/report-run-1/analysis.py"
    }


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

    normalize_task_function_call_arguments(call)

    assert call.arguments == expected


@pytest.mark.anyio
async def test_finish_task_returns_stable_errors_for_invalid_services_and_state_race(
    execution_runtime,
    monkeypatch,
):
    runtime = execution_runtime
    runtime.context.session_state[AGENT_PLAN_STATE_KEY] = {"plan": []}
    finish_function = Function(name="finish_task")

    invalid = await runtime.kernel.finish_task(
        "done",
        [],
        [],
        [{"session_id": 7, "healthcheck_execution_id": "health"}],  # type: ignore[list-item]
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
        "done", [], [], [], runtime.context, finish_function
    )

    assert raced["code"] == "finish_state_changed"
    assert finish_function.stop_after_tool_call is False
    task = await runtime.repository.get_task("external-run")
    assert task is not None and task.status != "completed"


@pytest.mark.anyio
async def test_finish_task_rejects_changed_workspace_with_stable_code(
    execution_runtime, monkeypatch
):
    runtime = execution_runtime
    runtime.context.session_state[AGENT_PLAN_STATE_KEY] = {"plan": []}
    original = runtime.workspace.abatch_hash_files
    calls = 0

    async def changed_on_recheck(thread_id, paths):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise WorkspaceError("工作区已替换")
        return await original(thread_id, paths)

    monkeypatch.setattr(runtime.workspace, "abatch_hash_files", changed_on_recheck)

    result = await runtime.kernel.finish_task(
        "done",
        [],
        [],
        [],
        runtime.context,
        Function(name="finish_task"),
    )

    assert result["code"] == "finish_workspace_changed"
    task = await runtime.repository.get_task("external-run")
    assert task is not None and task.status != "completed"


@pytest.mark.anyio
async def test_patch_settles_completed_when_bookkeeping_fails_after_apply() -> None:
    content = "done\n"
    after = hashlib.sha256(content.encode()).hexdigest()
    updates: list[str] = []
    stored: dict[str, object] = {}

    class Repository:
        async def increment_mutation(self, *_args, **_kwargs):
            return 1

        async def reserve_execution(self, **kwargs):
            stored["receipt"] = kwargs["operation_receipt"]
            stored["id"] = kwargs["execution_id"]
            return SimpleNamespace(status="reserved")

        async def get_execution(self, execution_id):
            return SimpleNamespace(
                execution_id=execution_id,
                thread_id="thread",
                operation_receipt=stored["receipt"],
                status="reserved",
            )

        async def update_execution(self, _execution_id, **kwargs):
            if not updates:
                updates.append("failed-attempt")
                raise RuntimeError("db blip")
            updates.append(kwargs["status"])
            return SimpleNamespace(status=kwargs["status"])

    class Service:
        async def aapply_changes(self, _thread_id, _changes):
            return {"changed": True}

        async def ahash_file(self, _thread_id, _path):
            return {"sha256": after}

    kernel = TaskExecutionKernel(Service(), Repository())  # type: ignore[arg-type]
    scope = TaskExecutionRuntime(
        task=SimpleNamespace(mutation_sequence=0),
        external_run_id="external-run",
        internal_run_id="internal-run",
        owner_user_id="user",
        thread_id="thread",
        sandbox_id="thread",
        lease_owner="lease",
        lease_epoch=1,
        attempt_no=0,
    )

    result = await kernel.patch(
        "patch",
        None,
        None,
        None,
        False,
        "diff",
        None,
        _changes=[{"operation": "update", "path": "result.txt", "content": content}],
        _scope=scope,
    )

    assert result["ok"] is True
    assert updates == ["failed-attempt", "completed"]
