import hashlib
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agno.tools import Function, Toolkit
from agno.tools.daytona import DaytonaTools
from unidiff import PatchSet, UnidiffParseError

from ..workspace import (
    MAX_PATCH_FILES,
    WorkspaceError,
    WorkspaceService,
)

PURE_CODING_TOOLKIT_INSTRUCTIONS = """
生产工作区工具规则：
- 只使用当前生产 Toolkit 声明的 terminal、process、read_file、read_tool_output、view_image 和 finish_task；它们共享当前 thread 唯一的 Daytona 工作区与受管进程。
- 文件读取优先使用 read_file；结果被截断时使用 read_tool_output 按需重读，不要用 terminal 代替受控只读工具。
- 短命令使用 terminal 前台模式；长任务或服务使用 background=true，并用 process 的 poll 或 wait 查看增量输出，不能使用 shell 后台符号绕过受管进程。terminal 的 command 最多 1 MiB UTF-8 字节。
- process 支持 list、poll、wait、kill、write 和 submit；write 原样写入，submit 会在数据后追加换行。未暴露的日志回溯、关闭 stdin 和异步通知能力不可假定存在。
- 文本工具结果被截断且返回 outputHandle 时，使用 read_tool_output(handle, offset, max_bytes) 按需重读；句柄是当前 Task/Attempt 的不透明标识，不得当作路径或跨任务使用。
- 文件路径和 workdir 必须是工作区相对路径；所有工具直接执行，但不会扩大当前 thread、路径、网络、进程、超时或输出限制。
- terminal 默认从工作区根目录执行；设置 workdir 后，命令中的每个相对路径都以该 workdir 为基准。命令引用工作区根目录相对路径时保持 workdir 为空，不得同时设置子目录 workdir 后重复拼接根目录相对路径。
- 只有 finish_task 返回 accepted 才表示任务完成；门禁拒绝时按稳定 code 修复后再次调用，不得把候选总结当作最终交付。
""".strip()


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


def build_workspace_changes(
    service: WorkspaceService,
    thread: str,
    patch: str,
    expected_sha256: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    normalized = patch.replace("\r\n", "\n").replace("\r", "\n")
    operations = parse_unified_diff(normalized)
    originals: dict[str, str] = {}
    paths: list[tuple[_PatchOperation, str]] = []
    for operation in operations:
        path = service.normalize_path(operation.path, allow_root=False)[0]
        paths.append((operation, path))
        if operation.operation == "create":
            if expected_sha256 and path in expected_sha256:
                raise WorkspaceError("新增文件不能提供已有文件的基线 SHA-256。")
            continue
        current = service.read_text(thread, path)
        digest = hashlib.sha256(current.encode("utf-8")).hexdigest()
        if expected_sha256 and expected_sha256.get(path) != digest:
            raise WorkspaceError("文件内容已变化，请重新读取文件和哈希后再应用补丁。")
        originals[path] = current

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


class _ManagedDaytonaTools(DaytonaTools):
    """复用 DaytonaTools 类型契约，但由 WorkspaceService 作为唯一 sandbox 入口。"""

    def __init__(
        self,
        *,
        name: str,
        tools: list[Function],
        instructions: str,
    ):
        # 上游构造器会创建第二个 sandbox；这里只初始化显式注册的受管工具。
        Toolkit.__init__(
            self,
            name=name,
            tools=tools,
            instructions=instructions,
            add_instructions=True,
        )
        for function in {**self.functions, **self.async_functions}.values():
            function.process_entrypoint()
            function.skip_entrypoint_processing = True
            function.requires_confirmation = False
