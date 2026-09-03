from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from smart_reporting.task_execution.tools import build_workspace_changes
from smart_reporting.workspace import WorkspaceError


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


def test_git_patch_kernel_rejects_stale_expected_sha256_before_apply() -> None:
    service = _Workspace({"report.py": "actual = 1\n"})
    patch = """\
--- a/report.py
+++ b/report.py
@@ -1 +1 @@
-actual = 1
+updated = 1
"""

    with pytest.raises(WorkspaceError, match="哈希"):
        build_workspace_changes(
            service,
            "thread",
            patch,
            expected_sha256={"report.py": "0" * 64},
        )
