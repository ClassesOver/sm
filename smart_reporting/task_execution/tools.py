import asyncio
import hashlib
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from unidiff import PatchSet, UnidiffParseError

from ..workspace import (
    MAX_PATCH_FILES,
    WorkspaceError,
    WorkspaceService,
)


@dataclass(frozen=True)
class _PatchOperation:
    operation: str
    path: str


def _unified_diff_path(value: str) -> str:
    if value == "/dev/null":
        return value
    if not value.startswith(("a/", "b/")):
        raise WorkspaceError("unified diff 路径必须使用 a/path 或 b/path 前缀。")
    return value[2:]


_HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$"
)


def _canonicalize_patch_lines(patch: str) -> list[str]:
    lines = patch.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    canonical: list[str] = []
    for line in lines:
        match = _HUNK_HEADER_RE.match(line.rstrip("\n"))
        if match:
            source_start, source_length, target_start, target_length, section = match.groups()
            source_length = source_length or "1"
            target_length = target_length or "1"
            newline = "\n" if line.endswith("\n") else ""
            line = (
                f"@@ -{source_start},{source_length} +{target_start},{target_length} @@"
                f"{section}{newline}"
            )
        canonical.append(line)
    return canonical


def parse_unified_diff(patch: str) -> tuple[_PatchOperation, ...]:
    if not isinstance(patch, str) or not patch.strip():
        raise WorkspaceError("补丁不能为空。")
    normalized = patch.replace("\r\n", "\n").replace("\r", "\n")
    if "*** Begin Patch" in normalized or "*** Add File:" in normalized:
        raise WorkspaceError("仅接受标准 unified diff，不接受 Codex patch 方言。")
    try:
        parsed = PatchSet(normalized)
    except (UnidiffParseError, ValueError) as error:
        raise WorkspaceError("标准 unified diff 语法无效。") from error
    if _canonicalize_patch_lines(normalized) != _canonicalize_patch_lines(str(parsed)):
        raise WorkspaceError("unified diff hunk 存在未被计数消费的尾部内容。")
    if not 1 <= len(parsed) <= MAX_PATCH_FILES:
        raise WorkspaceError(f"补丁必须包含 1 至 {MAX_PATCH_FILES} 个文件操作。")
    operations: list[_PatchOperation] = []
    for patched_file in parsed:
        if not patched_file:
            raise WorkspaceError("每个 unified diff 文件必须包含至少一个 @@ hunk。")
        source = _unified_diff_path(patched_file.source_file)
        target = _unified_diff_path(patched_file.target_file)
        if patched_file.is_added_file:
            if source != "/dev/null" or target == "/dev/null":
                raise WorkspaceError("新增文件必须使用 --- /dev/null 与 +++ b/path。")
            operations.append(_PatchOperation(operation="create", path=target))
        elif patched_file.is_removed_file:
            if source == "/dev/null" or target != "/dev/null":
                raise WorkspaceError("删除文件必须使用 --- a/path 与 +++ /dev/null。")
            operations.append(_PatchOperation(operation="delete", path=source))
        else:
            if source == "/dev/null" or target == "/dev/null":
                raise WorkspaceError("更新文件必须同时声明 a/path 与 b/path。")
            if source != target:
                raise WorkspaceError("重命名必须使用删除旧文件和新建新文件两个标准 diff。")
            operations.append(_PatchOperation(operation="update", path=source))
    return tuple(operations)


def _apply_unified_hunks(content: str, patched_file: Any) -> str:
    """保留历史 hunk 应用器以便审计；生产 patch 路径已统一由 Git 执行。"""

    original = content.splitlines(keepends=True)
    updated: list[str] = []
    source_index = 0
    for hunk in patched_file:
        hunk_start = max(0, hunk.source_start - 1)
        if hunk_start < source_index:
            raise WorkspaceError("unified diff hunk 范围重叠或顺序无效。")
        updated.extend(original[source_index:hunk_start])
        cursor = hunk_start
        hunk_lines = list(hunk)
        for index, line in enumerate(hunk_lines):
            if line.line_type == "\\":
                continue
            value = line.value
            if index + 1 < len(hunk_lines) and hunk_lines[index + 1].line_type == "\\":
                value = value.removesuffix("\n")
            if line.is_context or line.is_removed:
                if cursor >= len(original) or original[cursor] != value:
                    raise WorkspaceError("unified diff hunk 与当前文件内容不匹配。")
                if line.is_context:
                    updated.append(original[cursor])
                cursor += 1
            elif line.is_added:
                updated.append(value)
        source_index = cursor
    updated.extend(original[source_index:])
    return "".join(updated)


def _run_git_apply(root: Path, patch_path: Path, *, check: bool) -> None:
    command = [
        "git",
        "-c",
        "core.autocrlf=false",
        "-c",
        "core.safecrlf=false",
        "apply",
        "--no-index",
    ]
    if check:
        command.append("--check")
    command.append(str(patch_path))
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except FileNotFoundError as error:
        raise WorkspaceError("补丁应用内核不可用，请稍后重试。") from error
    except subprocess.TimeoutExpired as error:
        raise WorkspaceError("补丁应用内核超时，请稍后重试。") from error
    if completed.returncode != 0:
        raise WorkspaceError("标准 unified diff 无法应用到当前文件内容。")


def _initialize_git_tree(root: Path) -> None:
    try:
        subprocess.run(
            ["git", "init", "--quiet"],
            cwd=root,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as error:
        raise WorkspaceError("补丁应用内核不可用，请稍后重试。") from error


def _build_changes_from_originals(
    normalized: str,
    paths: list[tuple[_PatchOperation, str]],
    originals: dict[str, str],
) -> list[dict[str, Any]]:
    # Git 是唯一的 hunk 应用器；临时树不包含真实 workspace，也不会使用 index 或
    # 真实仓库状态。先完整校验再应用，保证任何非法 diff 都不会越过 Daytona 的原子提交。
    with tempfile.TemporaryDirectory(prefix="reporting-patch-") as temporary:
        root = Path(temporary, "tree")
        root.mkdir()
        _initialize_git_tree(root)
        for path, content in originals.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="")
        patch_path = Path(temporary, "change.diff")
        patch_path.write_text(normalized, encoding="utf-8", newline="")
        _run_git_apply(root, patch_path, check=True)
        _run_git_apply(root, patch_path, check=False)

        changes: list[dict[str, Any]] = []
        for operation, path in paths:
            if operation.operation == "delete":
                if (root / path).exists():
                    raise WorkspaceError("删除文件的 unified diff 未移除目标文件。")
                changes.append(
                    {
                        "operation": "delete",
                        "path": path,
                        "expected_sha256": hashlib.sha256(
                            originals[path].encode("utf-8")
                        ).hexdigest(),
                    }
                )
                continue
            target = root / path
            if not target.is_file():
                raise WorkspaceError("标准 unified diff 未生成预期目标文件。")
            try:
                content = target.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise WorkspaceError("标准 unified diff 产生了非 UTF-8 文本文件。") from error
            change: dict[str, Any] = {
                "operation": operation.operation,
                "path": path,
                "content": content,
            }
            if operation.operation == "update":
                change["expected_sha256"] = hashlib.sha256(
                    originals[path].encode("utf-8")
                ).hexdigest()
            changes.append(change)
    if len(changes) > MAX_PATCH_FILES:
        raise WorkspaceError(f"补丁转换后的文件操作不能超过 {MAX_PATCH_FILES} 个。")
    return changes


def _normalized_patch_inputs(
    service: WorkspaceService,
    patch: str,
) -> tuple[str, list[tuple[_PatchOperation, str]]]:
    normalized = patch.replace("\r\n", "\n").replace("\r", "\n")
    paths = [
        (operation, service.normalize_path(operation.path, allow_root=False)[0])
        for operation in parse_unified_diff(normalized)
    ]
    return normalized, paths


def build_workspace_changes(
    service: WorkspaceService,
    thread: str,
    patch: str,
) -> list[dict[str, Any]]:
    normalized, paths = _normalized_patch_inputs(service, patch)
    originals: dict[str, str] = {}
    for operation, path in paths:
        if operation.operation == "create":
            continue
        current = service.read_text(thread, path)
        originals[path] = current
    return _build_changes_from_originals(normalized, paths, originals)


async def abuild_workspace_changes(
    service: WorkspaceService,
    thread: str,
    patch: str,
) -> list[dict[str, Any]]:
    normalized, paths = _normalized_patch_inputs(service, patch)
    originals: dict[str, str] = {}
    for operation, path in paths:
        if operation.operation == "create":
            continue
        current = await service.aread_text(thread, path)
        originals[path] = current
    return await asyncio.to_thread(_build_changes_from_originals, normalized, paths, originals)
