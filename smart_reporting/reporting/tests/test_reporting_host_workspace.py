import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from smart_reporting.reporting.host_workspace import (
    HostReportingWorkspace,
    ReportingPathMapper,
    ReportingWorkspaceRegistry,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope
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
