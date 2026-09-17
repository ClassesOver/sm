import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from agno.run import RunContext
from PIL import Image

from smart_reporting.reporting.agent import create_reporting_phase_agent
from smart_reporting.reporting.contract import REPORT_WORKFLOW_SCOPE_STATE_KEY
from smart_reporting.reporting.host_workspace import (
    HostReportingWorkspace,
    ReportingPathMapper,
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tools.factory import build_reporting_tools
from smart_reporting.reporting.tools.workspace_adapter import WorkspaceServiceReportingRuntime
from smart_reporting.reporting.workflow.runtime.base import _ReportWorkflowRuntimeBase
from smart_reporting.reporting.workflow.scope import (
    REPORT_WORKFLOW_SCOPE_DEPENDENCY,
    ReportingWorkflowScope,
)
from smart_reporting.runtime.execution import create_execution_context
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.task_execution.execution import TASK_EXECUTION_TOOL_OUTPUT_STATE_KEY
from smart_reporting.workspace import WorkspaceError, WorkspacePathConflict

SECRET = "0123456789abcdef0123456789abcdef"


def _scope(*, run_id: str, workspace_key: str) -> ReportingWorkflowScope:
    return ReportingWorkflowScope(
        run_id=run_id,
        external_run_id=f"external-{run_id}",
        session_id="report-session-1",
        caller_thread_id="thread-1",
        user_id="user-1",
        database="database-1",
        company_id="company-1",
        thread_lease_key="lease-1",
        workspace_key=workspace_key,
    )


def test_registry_reuses_workspace_for_same_reporting_run(tmp_path: Path) -> None:
    registry = ReportingWorkspaceRegistry(tmp_path, secret=SECRET)

    first = registry.resolve(_scope(run_id="run-1", workspace_key="workspace-1"))
    resumed = registry.resolve(_scope(run_id="run-1", workspace_key="workspace-1"))

    assert first is resumed
    assert first.workspace is resumed.workspace
    assert first.root == resumed.root
    assert first.workspace.root == first.root
    assert set(first.workspace.functions) == {
        "read_file",
        "list_files",
        "search_content",
        "write_file",
        "edit_file",
        "move_file",
        "delete_file",
        "run_command",
    }
    assert first.workspace.requires_confirmation_tools == []


def test_registry_isolates_different_reporting_runs(tmp_path: Path) -> None:
    registry = ReportingWorkspaceRegistry(tmp_path, secret=SECRET)

    first = registry.resolve(_scope(run_id="run-1", workspace_key="workspace-1"))
    second = registry.resolve(_scope(run_id="run-2", workspace_key="workspace-2"))

    assert first is not second
    assert first.workspace is not second.workspace
    assert first.root != second.root
    assert first.root.parent == tmp_path / "sessions"
    assert second.root.parent == tmp_path / "sessions"


def test_registry_rejects_workspace_key_rebound_to_another_scope(tmp_path: Path) -> None:
    registry = ReportingWorkspaceRegistry(tmp_path, secret=SECRET)
    registry.resolve(_scope(run_id="run-1", workspace_key="workspace-1"))
    rebound = _scope(run_id="run-2", workspace_key="workspace-1")

    with pytest.raises(ValueError, match="作用域不一致"):
        registry.resolve(rebound)


def test_registry_restores_same_directory_after_process_restart(tmp_path: Path) -> None:
    scope = _scope(run_id="run-1", workspace_key="workspace-1")
    first = ReportingWorkspaceRegistry(tmp_path, secret=SECRET).resolve(scope)
    restored = ReportingWorkspaceRegistry(tmp_path, secret=SECRET).resolve(scope)

    assert first.workspace is not restored.workspace
    assert first.root == restored.root


def test_registry_release_drops_instance_without_deleting_directory(tmp_path: Path) -> None:
    registry = ReportingWorkspaceRegistry(tmp_path, secret=SECRET)
    identity = registry.resolve(_scope(run_id="run-1", workspace_key="workspace-1"))

    assert registry.release("workspace-1") is True
    assert registry.get("workspace-1") is None
    assert identity.root.is_dir()


def test_reporting_agent_tools_are_session_scoped_without_duplicate_names(
    tmp_path: Path,
) -> None:
    registry = ReportingWorkspaceRegistry(tmp_path, secret=SECRET)
    first = registry.resolve(_scope(run_id="run-1", workspace_key="workspace-1"))
    second = registry.resolve(_scope(run_id="run-2", workspace_key="workspace-2"))
    router = ReportingWorkspaceRouter(registry)
    settings = AgentSettings.from_environment(
        {"REPORTING_HOST_WORKSPACE_ROOT": str(tmp_path)},
        load_env_file=False,
    )
    agent = create_reporting_phase_agent(
        settings,
        object(),
        router,
        object(),
        state_repository=object(),
        workspace_registry=registry,
    )

    def tools_for(workspace_key: str):
        context = RunContext(
            run_id=f"task-{workspace_key}",
            session_id=f"task-{workspace_key}",
            user_id="user-1",
            session_state={},
            dependencies={
                "AgentOS 任务执行": {
                    "externalRunId": f"task-{workspace_key}",
                    "threadId": workspace_key,
                    "reportingPhase": "analysis",
                    "reportingTaskKind": "analysis_item",
                }
            },
        )
        return agent.tools(context)

    first_tools = tools_for(first.workspace_key)
    second_tools = tools_for(second.workspace_key)
    expected_native_names = {
        "read_file",
        "write_file",
        "edit_file",
        "list_files",
        "search_content",
        "move_file",
        "delete_file",
        "run_command",
    }
    for tools, expected_workspace in (
        (first_tools, first.workspace),
        (second_tools, second.workspace),
    ):
        assert tools[0] is expected_workspace
        names = {
            name
            for toolkit in tools
            for name in (*toolkit.functions, *toolkit.async_functions)
        }
        assert expected_native_names <= names
        assert "inspect_chart" not in names
        assert "run_python_script" not in names
    assert agent.cache_callables is False

    visualization_context = RunContext(
        run_id="task-visualization",
        session_id="task-visualization",
        user_id="user-1",
        session_state={},
        dependencies={
            "AgentOS 任务执行": {
                "externalRunId": "task-visualization",
                "threadId": "workspace-1",
                "reportingPhase": "analysis",
                "reportingTaskKind": "visualization_section",
            }
        },
    )
    visualization_tools = build_reporting_tools(
        router,
        object(),
        state_repository=object(),
        run_context=visualization_context,
        vision_reviewer=object(),
    )
    visualization_names = {
        name
        for toolkit in visualization_tools
        for name in (*toolkit.functions, *toolkit.async_functions)
    }
    assert "inspect_chart" not in visualization_names


def _host_workspace(tmp_path: Path) -> HostReportingWorkspace:
    identity = ReportingWorkspaceRegistry(tmp_path, secret=SECRET).resolve(
        _scope(run_id="run-1", workspace_key="workspace-1")
    )
    return HostReportingWorkspace(identity)


def test_path_mapper_preserves_normalized_relative_paths(tmp_path: Path) -> None:
    mapper = ReportingPathMapper(tmp_path)

    assert mapper.normalize("facts/a.json") == "facts/a.json"
    assert mapper.normalize("facts\\a.json") == "facts/a.json"
    assert mapper.to_host_path("facts/a.json") == tmp_path / "facts" / "a.json"


@pytest.mark.parametrize(
    "path",
    ["../outside", "facts/../../outside", "/etc/passwd", "C:\\Windows\\system.ini", "a\x00b"],
)
def test_path_mapper_rejects_paths_outside_workspace(tmp_path: Path, path: str) -> None:
    with pytest.raises(WorkspaceError):
        ReportingPathMapper(tmp_path).to_host_path(path)


def test_path_mapper_rejects_symlink_parent(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceError, match="符号链接"):
        ReportingPathMapper(tmp_path).to_host_path("linked/result.json")




@pytest.mark.anyio
async def test_host_workspace_writes_reads_and_hashes_regular_file(tmp_path: Path) -> None:
    workspace = _host_workspace(tmp_path)
    content = b'{"value":1}'

    created = await workspace.awrite_bytes("workspace-1", "facts/a.json", content)
    loaded, mime_type = await workspace.afile_bytes("workspace-1", "facts/a.json")
    identity = await workspace.ahash_file("workspace-1", "facts/a.json")

    assert created == {"path": "facts/a.json", "size": len(content), "status": "synced"}
    assert loaded == content
    assert mime_type == "application/json"
    assert identity == {
        "path": "facts/a.json",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


@pytest.mark.anyio
async def test_host_workspace_create_and_cas_detect_file_changes(tmp_path: Path) -> None:
    workspace = _host_workspace(tmp_path)
    await workspace.awrite_bytes("workspace-1", "facts/a.json", b"first")

    with pytest.raises(WorkspacePathConflict):
        await workspace.awrite_bytes(
            "workspace-1", "facts/a.json", b"duplicate", overwrite=False
        )
    with pytest.raises(WorkspacePathConflict):
        await workspace.awrite_bytes(
            "workspace-1",
            "facts/a.json",
            b"second",
            overwrite=True,
            expected_sha256="0" * 64,
        )

    replaced = await workspace.awrite_bytes(
        "workspace-1",
        "facts/a.json",
        b"second",
        overwrite=True,
        expected_sha256=hashlib.sha256(b"first").hexdigest(),
    )
    assert replaced["size"] == len(b"second")


@pytest.mark.anyio
async def test_host_workspace_batch_hash_marks_missing_files(tmp_path: Path) -> None:
    workspace = _host_workspace(tmp_path)
    await workspace.awrite_bytes("workspace-1", "facts/a.json", b"value")

    identities = await workspace.abatch_hash_files(
        "workspace-1", ["facts/a.json", "facts/missing.json"]
    )

    assert identities[0]["sha256"] == hashlib.sha256(b"value").hexdigest()
    assert identities[1] == {"path": "facts/missing.json", "missing": True}


@pytest.mark.anyio
async def test_workspace_router_keeps_reporting_runs_isolated(tmp_path: Path) -> None:
    registry = ReportingWorkspaceRegistry(tmp_path, secret=SECRET)
    first = registry.resolve(_scope(run_id="run-1", workspace_key="workspace-1"))
    second = registry.resolve(_scope(run_id="run-2", workspace_key="workspace-2"))
    router = ReportingWorkspaceRouter(registry)

    await router.awrite_bytes("workspace-1", "facts/value.txt", b"first")
    await router.awrite_bytes("workspace-2", "facts/value.txt", b"second")

    assert await router.aread_text("workspace-1", "facts/value.txt") == "first"
    assert await router.aread_text("workspace-2", "facts/value.txt") == "second"
    assert (first.root / "facts/value.txt").read_bytes() == b"first"
    assert (second.root / "facts/value.txt").read_bytes() == b"second"


@pytest.mark.anyio
async def test_workspace_router_rejects_unregistered_run(tmp_path: Path) -> None:
    router = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(tmp_path, secret=SECRET))

    with pytest.raises(ReportingError) as raised:
        await router.aread_text("missing-workspace", "facts/value.txt")

    assert raised.value.code == "report_host_workspace_missing"


@pytest.mark.anyio
async def test_host_workspace_moves_and_deletes_directories(tmp_path: Path) -> None:
    workspace = _host_workspace(tmp_path)
    await workspace.awrite_text("workspace-1", "staging/report.md", "report")

    await workspace.amove_files("workspace-1", "staging", "reports/revision-1")
    assert await workspace.aread_text(
        "workspace-1", "reports/revision-1/report.md"
    ) == "report"

    await workspace.adelete_file("workspace-1", "reports/revision-1", recursive=True)
    assert not (workspace.identity.root / "reports/revision-1").exists()


@pytest.mark.anyio
async def test_host_workspace_rejects_symlink_file(tmp_path: Path) -> None:
    workspace = _host_workspace(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("outside", encoding="utf-8")
    target = workspace.identity.root / "facts" / "linked.json"
    target.parent.mkdir()
    target.symlink_to(outside)

    with pytest.raises(WorkspaceError, match="符号链接"):
        await workspace.afile_bytes("workspace-1", "facts/linked.json")


@pytest.mark.anyio
async def test_host_workspace_inspects_valid_nonblank_png(tmp_path: Path) -> None:
    workspace = _host_workspace(tmp_path)
    buffer = io.BytesIO()
    image = Image.new("RGB", (20, 10), "white")
    image.putpixel((5, 5), (0, 0, 0))
    image.save(buffer, format="PNG")
    await workspace.awrite_bytes("workspace-1", "charts/chart.png", buffer.getvalue())

    inspection = await workspace.inspect_chart_file("workspace-1", "charts/chart.png")

    assert inspection["sourcePath"] == "charts/chart.png"
    assert inspection["format"] == "PNG"
    assert inspection["width"] == 20
    assert inspection["height"] == 10


@pytest.mark.anyio
async def test_host_workspace_rejects_blank_png(tmp_path: Path) -> None:
    workspace = _host_workspace(tmp_path)
    buffer = io.BytesIO()
    Image.new("RGB", (20, 10), "white").save(buffer, format="PNG")
    await workspace.awrite_bytes("workspace-1", "charts/chart.png", buffer.getvalue())

    with pytest.raises(ReportingError) as raised:
        await workspace.inspect_chart_file("workspace-1", "charts/chart.png")

    assert raised.value.code == "report_chart_blank"


def test_execution_context_builds_reporting_workspace_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = AgentSettings.from_environment(
        {
            "REPORTING_HOST_WORKSPACE_ROOT": str(tmp_path),
            "AGENT_WORKSPACE_HMAC_SECRET": SECRET,
        },
        load_env_file=False,
    )
    database = type(
        "Database",
        (),
        {"async_db": object(), "sync_db": object()},
    )()
    monkeypatch.setattr(
        "smart_reporting.runtime.execution.AsyncSandboxRegistry",
        lambda _database: object(),
    )
    monkeypatch.setattr(
        "smart_reporting.runtime.execution.create_sandbox_provider",
        lambda *_args, **_kwargs: object(),
    )

    context = create_execution_context(
        settings,
        database_factory=lambda _url: database,
        tracing_configurer=lambda *_args, **_kwargs: None,
        workspace_factory=lambda **_kwargs: object(),
    )

    assert isinstance(context.reporting_workspace_registry, ReportingWorkspaceRegistry)
    assert context.reporting_workspace_registry.root == tmp_path


def test_runtime_prepare_run_binds_host_workspace(tmp_path: Path) -> None:
    runtime = object.__new__(_ReportWorkflowRuntimeBase)
    runtime.workspace_registry = ReportingWorkspaceRegistry(tmp_path, secret=SECRET)
    dependencies = {
        REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
            "externalRunId": "external-run-1",
            "threadId": "caller-thread-1",
            "userId": "user-1",
            "database": "database-1",
            "companyId": "company-1",
        }
    }

    state = runtime.prepare_run(
        run_id="report-run-1",
        session_id="report-session-1",
        user_id="user-1",
        dependencies=dependencies,
    )

    workspace_key = state[REPORT_WORKFLOW_SCOPE_STATE_KEY]["threadId"]
    assert runtime.workspace_registry.get(workspace_key) is not None


def test_runtime_resolves_same_host_workspace_after_prepare_run(tmp_path: Path) -> None:
    runtime = object.__new__(_ReportWorkflowRuntimeBase)
    runtime.workspace_registry = ReportingWorkspaceRegistry(tmp_path, secret=SECRET)
    dependencies = {
        REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
            "externalRunId": "external-run-1",
            "threadId": "caller-thread-1",
            "userId": "user-1",
            "database": "database-1",
            "companyId": "company-1",
        }
    }
    runtime.prepare_run(
        run_id="report-run-1",
        session_id="report-session-1",
        user_id="user-1",
        dependencies=dependencies,
    )

    first = runtime.workspace_for(
        run_id="report-run-1",
        session_id="report-session-1",
        user_id="user-1",
        dependencies=dependencies,
    )
    second = runtime.workspace_for(
        run_id="report-run-1",
        session_id="report-session-1",
        user_id="user-1",
        dependencies=dependencies,
    )

    assert first is second


@pytest.mark.anyio
async def test_runtime_resolves_parent_workspace_from_stored_scope_in_child_context(
    tmp_path: Path,
) -> None:
    runtime = object.__new__(_ReportWorkflowRuntimeBase)
    runtime.workspace_registry = ReportingWorkspaceRegistry(tmp_path, secret=SECRET)
    dependencies = {
        REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
            "externalRunId": "external-run-1",
            "threadId": "caller-thread-1",
            "userId": "user-1",
            "database": "database-1",
            "companyId": "company-1",
        }
    }
    state = runtime.prepare_run(
        run_id="report-run-1",
        session_id="report-session-1",
        user_id="user-1",
        dependencies=dependencies,
    )
    stored_scope = state[REPORT_WORKFLOW_SCOPE_STATE_KEY]
    parent = runtime.workspace_for(
        run_id="report-run-1",
        session_id="report-session-1",
        user_id="user-1",
        dependencies=dependencies,
        stored_scope=stored_scope,
    )
    await parent.awrite_text(
        parent.identity.workspace_key,
        "datasets/input.csv",
        "value\n1\n",
    )

    child = runtime.workspace_for(
        run_id="report-run-1",
        session_id="report-session-1",
        user_id="user-1",
        dependencies={"AgentOS 任务执行": {"externalRunId": "child-task"}},
        stored_scope=stored_scope,
    )

    assert child is parent
    assert await child.aread_text(
        child.identity.workspace_key, "datasets/input.csv"
    ) == "value\n1\n"


@pytest.mark.anyio
async def test_host_workspace_applies_create_update_and_delete_changes(tmp_path: Path) -> None:
    workspace = _host_workspace(tmp_path)

    created = await workspace.aapply_changes(
        "workspace-1",
        [{"operation": "create", "path": "analysis/script.py", "content": "value = 1\n"}],
    )
    assert created["operations"] == 1
    assert await workspace.aread_text("workspace-1", "analysis/script.py") == "value = 1\n"

    current = created["files"][0]["sha256"]
    updated = await workspace.aapply_changes(
        "workspace-1",
        [
            {
                "operation": "update",
                "path": "analysis/script.py",
                "content": "value = 2\n",
                "expected_sha256": current,
            }
        ],
    )
    assert await workspace.aread_text("workspace-1", "analysis/script.py") == "value = 2\n"

    await workspace.aapply_changes(
        "workspace-1",
        [
            {
                "operation": "delete",
                "path": "analysis/script.py",
                "expected_sha256": updated["files"][0]["sha256"],
            }
        ],
    )
    assert await workspace.apath_exists("workspace-1", "analysis/script.py") is False


@pytest.mark.anyio
async def test_reporting_runtime_retains_tool_output_on_host_workspace(tmp_path: Path) -> None:
    registry = ReportingWorkspaceRegistry(tmp_path, secret=SECRET)
    registry.resolve(_scope(run_id="run-1", workspace_key="workspace-1"))
    router = ReportingWorkspaceRouter(registry)
    runtime = WorkspaceServiceReportingRuntime(router, object())
    scope = SimpleNamespace(
        external_run_id="report-coding-analysis-1",
        attempt_no=1,
        thread_id="workspace-1",
    )
    context = RunContext(run_id="run-1", session_id="session-1", session_state={})

    retained = await runtime.bound_tool_result(
        scope,
        {"path": "facts/analysis_001.json", "content": "医疗收入"},
        context,
        retain=True,
        preview_bytes=8,
    )

    assert retained["outputHandle"]
    assert retained["outputTruncated"] is True
    handles = context.session_state[TASK_EXECUTION_TOOL_OUTPUT_STATE_KEY]["handles"]
    stored_path = handles[retained["outputHandle"]]["path"]
    relative = stored_path.removeprefix("/home/daytona/")
    assert (registry.get("workspace-1").root / relative).is_file()
    raw, metadata = await runtime.read_tool_output_resource(
        retained["outputHandle"],
        context,
        _scope=scope,
    )
    assert raw.decode("utf-8") == "医疗收入"
    assert metadata["bytes"] == len("医疗收入".encode())
