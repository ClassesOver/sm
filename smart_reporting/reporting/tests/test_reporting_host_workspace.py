from pathlib import Path

import pytest

from smart_reporting.reporting.host_workspace import ReportingWorkspaceRegistry
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope

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
