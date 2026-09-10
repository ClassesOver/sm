from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.task_execution.execution import TaskExecutionKernel, TaskExecutionRuntime
from smart_reporting.task_execution.tools import abuild_workspace_changes, build_workspace_changes
from smart_reporting.workspace import WorkspaceError, WorkspacePathConflict


class _Workspace:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    @staticmethod
    def normalize_path(path: str, *, allow_root: bool) -> tuple[str, str]:
        assert allow_root is False
        if not path or path.startswith("/") or ".." in Path(path).parts:
            raise WorkspaceError("路径无效。")
        return path, path

    def read_text(self, thread: str, path: str) -> str:
        assert thread == "thread"
        try:
            return self.files[path]
        except KeyError as error:
            raise WorkspaceError("目标文件不存在。") from error

    async def aread_text(self, thread: str, path: str) -> str:
        return self.read_text(thread, path)

    async def aapply_changes(self, thread: str, changes: list[dict]) -> None:
        self.applied_changes = changes
        for change in changes:
            current = self.files[change["path"]]
            if hashlib.sha256(current.encode()).hexdigest() != change["expected_sha256"]:
                raise WorkspacePathConflict("文件内容已变化")
        for change in changes:
            self.files[change["path"]] = change["content"]
        return {"operations": len(changes), "files": []}


def test_git_patch_kernel_builds_changes_for_update_create_and_delete() -> None:
    service = _Workspace({"update.txt": "before\n", "delete.txt": "remove\n"})
    patch = """\
--- a/update.txt
+++ b/update.txt
@@ -1 +1 @@
-before
+after
--- /dev/null
+++ b/create.txt
@@ -0,0 +1 @@
+created
--- a/delete.txt
+++ /dev/null
@@ -1 +0,0 @@
-remove
"""

    changes = build_workspace_changes(service, "thread", patch)

    assert changes == [
        {
            "operation": "update",
            "path": "update.txt",
            "content": "after\n",
            "expected_sha256": hashlib.sha256(b"before\n").hexdigest(),
        },
        {"operation": "create", "path": "create.txt", "content": "created\n"},
        {
            "operation": "delete",
            "path": "delete.txt",
            "expected_sha256": hashlib.sha256(b"remove\n").hexdigest(),
        },
    ]


def test_git_patch_kernel_rejects_hunk_that_does_not_match_current_content() -> None:
    service = _Workspace({"report.py": "actual = 1\n"})
    patch = """\
--- a/report.py
+++ b/report.py
@@ -1 +1 @@
-expected = 1
+updated = 1
"""

    with pytest.raises(WorkspaceError, match="无法应用"):
        build_workspace_changes(service, "thread", patch)


@pytest.mark.parametrize(("declared_lines", "provided_lines"), [(3, 5), (120, 125)])
def test_git_patch_kernel_rejects_unconsumed_hunk_tail(
    declared_lines: int,
    provided_lines: int,
) -> None:
    service = _Workspace({})
    patch_lines = "".join(f"+line-{index}\n" for index in range(provided_lines))
    patch = f"--- /dev/null\n+++ b/create.txt\n@@ -0,0 +1,{declared_lines} @@\n{patch_lines}"

    with pytest.raises(WorkspaceError, match="hunk"):
        build_workspace_changes(service, "thread", patch)


@pytest.mark.anyio
async def test_internal_baseline_cas_rejects_change_between_build_and_apply() -> None:
    service = _Workspace({"report.py": "actual = 1\n"})
    patch = """--- a/report.py
+++ b/report.py
@@ -1 +1 @@
-actual = 1
+updated = 1
"""
    changes = await abuild_workspace_changes(service, "thread", patch)
    service.files["report.py"] = "concurrent = 1\n"

    with pytest.raises(WorkspacePathConflict):
        await service.aapply_changes("thread", changes)
    assert service.files["report.py"] == "concurrent = 1\n"


@pytest.mark.anyio
async def test_patch_reuses_prebuilt_changes_for_workspace_apply() -> None:
    service = _Workspace({"report.py": "actual = 1\n"})
    changes = [
        {
            "operation": "update",
            "path": "report.py",
            "content": "updated = 1\n",
            "expected_sha256": hashlib.sha256(b"actual = 1\n").hexdigest(),
        }
    ]
    repository = SimpleNamespace(
        increment_mutation=AsyncMock(return_value=1),
        reserve_execution=AsyncMock(),
        update_execution=AsyncMock(),
    )
    kernel = TaskExecutionKernel(service, repository)  # type: ignore[arg-type]
    scope = TaskExecutionRuntime(
        task=SimpleNamespace(mutation_sequence=0),
        external_run_id="external-run",
        internal_run_id="internal-run",
        owner_user_id="user",
        thread_id="thread",
        sandbox_id="sandbox",
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
        "--- a/report.py\n+++ b/report.py\n@@ -1 +1 @@\n-actual = 1\n+updated = 1\n",
        None,
        _changes=changes,
        _scope=scope,
    )

    assert result["ok"] is True
    assert service.applied_changes is changes


@pytest.mark.anyio
async def test_async_git_patch_kernel_does_not_use_sync_workspace_reads() -> None:
    service = _Workspace({"analysis/model.py": "value = 1\n"})

    async def aread_text(thread: str, path: str) -> str:
        assert thread == "thread"
        return service.files[path]

    service.aread_text = aread_text  # type: ignore[attr-defined]
    service.read_text = lambda *_args: pytest.fail("不得调用同步 workspace 读取路径")  # type: ignore[method-assign]
    patch = """\
--- a/analysis/model.py
+++ b/analysis/model.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

    changes = await abuild_workspace_changes(service, "thread", patch)

    assert changes == [
        {
            "operation": "update",
            "path": "analysis/model.py",
            "content": "value = 2\n",
            "expected_sha256": hashlib.sha256(b"value = 1\n").hexdigest(),
        }
    ]
