import asyncio
import hashlib
import re
import shlex
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import tree_sitter_bash
from agno.run import RunContext
from agno.tools import Function, Toolkit
from agno.tools.daytona import DaytonaTools
from daytona.common.errors import DaytonaNotFoundError
from tree_sitter import Language, Node, Parser

from .agent_control import AgentControlToolkit
from .async_utils import complete_cleanup
from .workspace import (
    MAX_BACKGROUND_EXECUTION_TIMEOUT,
    MAX_MANAGED_PROCESSES,
    MAX_PATCH_FILES,
    MAX_PROCESS_INPUT_BYTES,
    MAX_TOOL_OUTPUT_BYTES,
    WorkspaceError,
    WorkspaceProcessNotFound,
    WorkspaceService,
    WorkspaceToolkit,
    _thread,
)

CODEX_EXEC_SESSIONS_STATE_KEY = "agentos_codex_exec_sessions"
CODEX_EXEC_NEXT_SESSION_STATE_KEY = "agentos_codex_exec_next_session"
CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY = "agentos_codex_exec_closed_sessions"
MAX_CODEX_SESSION_HANDLES = MAX_MANAGED_PROCESSES * 4
MAX_CLOSED_SESSION_HANDLES = MAX_CODEX_SESSION_HANDLES * 2
CODEX_EXEC_SESSION_TTL_SECONDS = 3600
DEFAULT_EXEC_TIMEOUT_SECONDS = 900
DEFAULT_YIELD_TIME_MS = 10_000
DEFAULT_MAX_OUTPUT_TOKENS = MAX_TOOL_OUTPUT_BYTES // 4
MAX_OUTPUT_TOKENS = MAX_TOOL_OUTPUT_BYTES // 4
MUTATING_INLINE_EDIT_COMMAND = re.compile(
    r"(?:^|[;&|]\s*)(?:sed\s+(?:-[^;&|\s]*i\b|[^;&|]*\s-i(?:\s|$))|perl\s+-p?i(?:\s|$))"
)
PIP_INSTALL_WITH_OUTPUT_FILTER = re.compile(
    r"(?:^|[;&|]\s*)(?:python3?\s+-m\s+pip|pip3?|uv\s+pip)\s+install\b[^|]*\|"
    r"\s*(?:tail|head|grep|sed)\b"
)
DETACHED_PROCESS_COMMAND = re.compile(r"(?:^|[;&|]\s*)(?:nohup|disown)\b")
_BASH_LANGUAGE = Language(tree_sitter_bash.language())
APPLY_PATCH_COMMAND_PREFIX = re.compile(r"apply_patch(?=$|[\s;&|<>])")
APPLY_PATCH_HEREDOC_HEADER = re.compile(
    r"apply_patch[ \t]*<<[ \t]*(?:"
    r"(?P<quote>['\"])(?P<quoted>[A-Za-z_][A-Za-z0-9_]{0,31})(?P=quote)|"
    r"(?P<bare>[A-Za-z_][A-Za-z0-9_]{0,31})"
    r")[ \t]*"
)
_PATCH_OPERATION_PREFIXES = (
    "*** Add File: ",
    "*** Delete File: ",
    "*** Update File: ",
)
_PATCH_HEREDOC_OPENERS = {"<<EOF", "<<'EOF'", '<<"EOF"'}
_PATCH_MATCH_TRANSLATION = str.maketrans(
    {
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "−": "-",
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        " ": " ",
        "　": " ",
    }
)

CODING_TOOLKIT_INSTRUCTIONS = """
Coding Agent 工具规则：
- 所有命令和文件都位于当前 thread 隔离的 Daytona 工作区；workdir 和文件路径只能使用工作区相对路径。
- 搜索和读取优先通过 exec_command 使用 rg、sed、git 等现有命令；不得访问 AgentOS 宿主文件系统。
- 已有文件的小范围精确修改优先使用 patch 的 replace 模式；新增、删除、移动或多文件变更使用 apply_patch，或使用 patch 的 patch 模式提交完整“*** Begin Patch / *** End Patch”补丁。原生补丁支持 Add/Update/Delete/Move、多文件和多个 hunk，并兼容完整单层 Markdown 围栏、apply_patch heredoc，以及 Add File 正文中漏写 + 的纯空行；禁止使用 ---/+++、/dev/null 或普通 unified diff。
- 如果模型无法稳定生成补丁函数参数，可改用独立 exec_command heredoc：apply_patch <<'PATCH'，随后是完整补丁和单独一行 PATCH。服务端会拦截并复用同一原子补丁实现，不会在 Daytona 中查找或执行 apply_patch 命令；不得附加其他 Shell 命令、workdir 或 PTY。
- CodingToolkit 的全部工具直接执行，不会请求确认；这不扩大当前 thread、Daytona 工作区、路径、进程、网络、超时或输出限制。
- exec_command、poll_process 和 write_stdin 的 yield_time_ms 必须在 0 至 30000 之间；不得提交 60000 等越界值。
- exec_command 默认最多运行 900 秒；明确需要更长时间的构建、测试或服务才设置 timeout_seconds，最长 86400 秒。短命令完成后检查 exit_code；普通长任务返回 session_id 时用 poll_process 读取增量日志，直到 status 为 completed。
- write_stdin 只用于向仍在运行的命令写入非空字符或发送 Ctrl-C；不要用它执行纯轮询。
- stop_process 用于终止仍在运行的受管命令，包括默认非 PTY 长任务；终止后句柄不可继续使用。
- 对服务器等预期长驻进程，status 为 running 且用独立 exec_command 健康检查成功后即可报告启动成功并保留 session_id；后续按需或定时用 poll_process 读取增量日志和状态，但不要在同一轮中紧密轮询等待服务退出。
- 禁止使用 shell 后台符号 &、nohup 或 disown 绕过受管进程；长驻服务直接以前台命令启动，让 exec_command 返回受管 session_id，再用独立健康检查验证。
- 修改文件只能使用 apply_patch 或 patch，不得使用 sed -i、perl -pi 或类似命令绕过补丁校验。
- 默认 shell 是 /bin/sh；需要 bash 语法时显式设置 shell="/bin/bash"，否则不要使用 source。
- 工作区镜像预装常用 Linux、文档、数据、测试和数据库能力；任务需要外部命令或 Python 模块时先用有界命令探测直接依赖，已存在则复用，确认缺失后才安装；不要无目的枚举完整环境。
- 任务确需安装依赖时允许使用包管理器，但应设置明确 timeout、保留完整错误输出并检查 exit_code；不要把 pip 输出管道到 tail，否则网络受限时无法获得实时错误反馈。
- 如果用户明确要求某框架或库（例如 FastAPI），依赖无法安装时必须报告阻塞，不能改用标准库或其他框架冒充完成。
- 非长驻命令连续两次轮询均为 running 且没有新输出时，不得继续盲目轮询；应检查进程状态、使用有界替代命令，或报告当前阻塞与 session_id。
- Python 任务优先创建 .py 脚本，再用 python3 <工作区相对脚本> 执行、检查错误、修改并重跑测试。
- 复杂任务用 update_plan 维护可验证步骤；只有命令成功、文件已复查且测试通过后才能声称完成。
""".strip()

HERMES_CODING_TOOLKIT_INSTRUCTIONS = """
生产工作区工具规则：
- 只使用 terminal、process、patch、view_image、update_plan 和 finish_task；它们共享当前 thread 唯一的 Daytona 工作区、受管进程和原子文件提交层。
- 短命令使用 terminal 前台模式；长任务或服务使用 background=true，并用 process 的 poll 或 wait 查看增量输出，不能使用 shell 后台符号绕过受管进程。
- process 支持 list、poll、wait、kill、write 和 submit；write 原样写入，submit 会在数据后追加换行。未暴露的日志回溯、关闭 stdin 和异步通知能力不可假定存在。
- patch 的 replace 模式用于精确字符串替换，默认要求原文唯一；需要替换全部匹配时显式设置 replace_all=true。
- patch 的 patch 模式使用完整的“*** Begin Patch / *** End Patch”补丁，支持 Add/Update/Delete/Move、多文件和多个 hunk；terminal 中独立的 apply_patch heredoc 进入同一原子补丁内核。
- 文件路径和 workdir 必须是工作区相对路径；所有工具直接执行，但不会扩大当前 thread、路径、网络、进程、超时或输出限制。
- 多步骤任务用 update_plan 维护计划；完成前确保全部步骤为 completed，且交付产物仍存在。
- 最后一次潜在修改后必须用 terminal 得到成功验证回执；存在活动进程时必须终止，或在 finish_task 的 service_sessions 中声明并提供当前 mutation 的成功健康检查回执。
- 只有 finish_task 返回 accepted 才表示任务完成；门禁拒绝时按稳定 code 修复后再次调用，不得把候选总结当作最终交付。
""".strip()


@dataclass(frozen=True)
class _PatchChunk:
    context: str | None
    old_lines: tuple[str, ...]
    new_lines: tuple[str, ...]
    end_of_file: bool


@dataclass(frozen=True)
class _PatchOperation:
    operation: str
    path: str
    destination: str | None = None
    content: str | None = None
    chunks: tuple[_PatchChunk, ...] = ()


def _extract_apply_patch_command(cmd: str) -> str | None:
    command = cmd.strip()
    if APPLY_PATCH_COMMAND_PREFIX.match(command) is None:
        return None

    lines = command.splitlines()
    first_line = lines[0]
    if re.match(r"apply_patch[ \t]*<<", first_line):
        header = APPLY_PATCH_HEREDOC_HEADER.fullmatch(first_line)
        if header is None:
            raise WorkspaceError(
                "exec_command 中的 apply_patch heredoc 起始行无效；"
                "只能使用独立的 apply_patch <<'PATCH' 命令。"
            )
        delimiter = header.group("quoted") or header.group("bare")
        try:
            closing_index = lines.index(delimiter, 1)
        except ValueError as error:
            raise WorkspaceError("exec_command 中的 apply_patch heredoc 缺少闭合标记。") from error
        if closing_index != len(lines) - 1:
            raise WorkspaceError(
                "exec_command 中的 apply_patch heredoc 闭合标记必须是最后一行，不能附加其他命令。"
            )
        return "\n".join(lines[1:closing_index])

    if re.match(r"apply_patch[ \t]+['\"]", first_line) is None:
        raise WorkspaceError(
            "exec_command 中的 apply_patch 只能接收同一行开始的单个引号参数，建议改用独立 heredoc。"
        )
    try:
        arguments = shlex.split(command, posix=True)
    except ValueError as error:
        raise WorkspaceError(
            "exec_command 中的 apply_patch 参数引号无效；请使用独立 heredoc。"
        ) from error
    if len(arguments) != 2 or arguments[0] != "apply_patch":
        raise WorkspaceError(
            "exec_command 中的 apply_patch 只能接收一个完整补丁参数，不能附加其他命令。"
        )
    return arguments[1]


def _parse_update_chunks(lines: list[str], path: str) -> tuple[_PatchChunk, ...]:
    chunks: list[_PatchChunk] = []
    index = 0
    while index < len(lines):
        while index < len(lines) and chunks and chunks[-1].end_of_file and not lines[index].strip():
            index += 1
        if index >= len(lines):
            break

        header = lines[index].rstrip()
        if header == "@@" or header.startswith("@@ "):
            context = header[3:] if header.startswith("@@ ") else None
            index += 1
        elif not chunks:
            context = None
        else:
            raise WorkspaceError(f"文件“{path}”的后续更新 hunk 必须以 @@ 开头。")

        old_lines: list[str] = []
        new_lines: list[str] = []
        end_of_file = False
        saw_line = False
        while index < len(lines):
            line = lines[index]
            update_line = line.rstrip()
            if update_line == "@@" or update_line.startswith("@@ "):
                break
            if update_line == "*** End of File":
                if not saw_line:
                    raise WorkspaceError(f"文件“{path}”的 End of File 前必须包含 hunk 行。")
                end_of_file = True
                index += 1
                break
            if line == "":
                marker, value = " ", ""
            elif line[0] in {" ", "+", "-"}:
                marker, value = line[0], line[1:]
            else:
                raise WorkspaceError(f"文件“{path}”的 hunk 行必须以空格、+ 或 - 开头。")
            saw_line = True
            if marker in {" ", "-"}:
                old_lines.append(value)
            if marker in {" ", "+"}:
                new_lines.append(value)
            index += 1
        if not saw_line:
            raise WorkspaceError(f"文件“{path}”的更新 hunk 不能为空。")
        chunks.append(
            _PatchChunk(
                context=context,
                old_lines=tuple(old_lines),
                new_lines=tuple(new_lines),
                end_of_file=end_of_file,
            )
        )
    return tuple(chunks)


def _normalized_patch_lines(patch: str) -> list[str]:
    normalized = patch.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = normalized.split("\n")
    if len(lines) >= 3 and lines[0].strip() in {"```", "```patch"}:
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
    elif len(lines) >= 4 and lines[0].strip() in _PATCH_HEREDOC_OPENERS:
        if lines[-1].strip() == "EOF":
            lines = lines[1:-1]
    return "\n".join(lines).strip().split("\n")


def parse_codex_patch(patch: str) -> tuple[_PatchOperation, ...]:
    if not isinstance(patch, str) or not patch.strip():
        raise WorkspaceError("补丁不能为空。")
    lines = _normalized_patch_lines(patch)
    if not lines or lines[0].strip() != "*** Begin Patch":
        raise WorkspaceError(
            "补丁首行必须是 *** Begin Patch，且 patch 参数只能包含纯补丁文本；"
            "仅兼容完整单层 Markdown 代码围栏或 apply_patch heredoc 外壳。"
        )
    if len(lines) < 3 or lines[-1].strip() != "*** End Patch":
        raise WorkspaceError("补丁末行必须是 *** End Patch。")

    operations: list[_PatchOperation] = []
    index = 1
    while index < len(lines) - 1:
        header = lines[index].strip()
        if header.startswith("*** Add File: "):
            path = header.removeprefix("*** Add File: ").strip()
            index += 1
            content: list[str] = []
            while index < len(lines) - 1 and not lines[index].strip().startswith(
                _PATCH_OPERATION_PREFIXES
            ):
                if lines[index] == "":
                    content.append("")
                elif lines[index].startswith("+"):
                    content.append(lines[index][1:])
                else:
                    raise WorkspaceError(f"新增文件“{path}”每一行的非空内容都必须以 + 开头。")
                index += 1
            if not content:
                raise WorkspaceError(f"新增文件“{path}”至少需要一行内容。")
            operations.append(
                _PatchOperation(operation="create", path=path, content="\n".join(content) + "\n")
            )
            continue
        if header.startswith("*** Delete File: "):
            path = header.removeprefix("*** Delete File: ").strip()
            operations.append(_PatchOperation(operation="delete", path=path))
            index += 1
            continue
        if header.startswith("*** Update File: "):
            path = header.removeprefix("*** Update File: ").strip()
            index += 1
            destination = None
            if index < len(lines) - 1 and lines[index].strip().startswith("*** Move to: "):
                destination = lines[index].strip().removeprefix("*** Move to: ").strip()
                index += 1
            update_lines: list[str] = []
            while index < len(lines) - 1 and not lines[index].strip().startswith(
                _PATCH_OPERATION_PREFIXES
            ):
                update_lines.append(lines[index])
                index += 1
            if not update_lines and destination is None:
                raise WorkspaceError(f"更新文件“{path}”必须包含 hunk 或 Move to。")
            operations.append(
                _PatchOperation(
                    operation="update",
                    path=path,
                    destination=destination,
                    chunks=_parse_update_chunks(update_lines, path) if update_lines else (),
                )
            )
            continue
        raise WorkspaceError(f"无效的补丁文件操作：{header}")

    if not 1 <= len(operations) <= MAX_PATCH_FILES:
        raise WorkspaceError(f"补丁必须包含 1 至 {MAX_PATCH_FILES} 个文件操作。")
    return tuple(operations)


def _normalized_patch_match_line(value: str) -> str:
    return value.strip().translate(_PATCH_MATCH_TRANSLATION)


def _seek_patch_sequence(
    lines: list[str], pattern: tuple[str, ...], start: int, end_of_file: bool
) -> int | None:
    if not pattern:
        return start
    if len(pattern) > len(lines):
        return None

    last_start = len(lines) - len(pattern)
    search_start = last_start if end_of_file else start

    def find(normalize: Callable[[str], str]) -> int | None:
        for candidate in range(search_start, last_start + 1):
            if all(
                normalize(lines[candidate + offset]) == normalize(expected)
                for offset, expected in enumerate(pattern)
            ):
                return candidate
        return None

    for normalize in (
        lambda value: value,
        str.rstrip,
        str.strip,
        _normalized_patch_match_line,
    ):
        found = find(normalize)
        if found is not None:
            return found
    return None


def _apply_update_chunks(content: str, operation: _PatchOperation) -> str:
    if not operation.chunks:
        return content

    original_lines = content.split("\n")
    if original_lines and original_lines[-1] == "":
        original_lines.pop()
    replacements: list[tuple[int, int, tuple[str, ...]]] = []
    line_index = 0

    for chunk in operation.chunks:
        if chunk.context is not None:
            context_index = _seek_patch_sequence(
                original_lines, (chunk.context,), line_index, False
            )
            if context_index is None:
                raise WorkspaceError(
                    f"文件“{operation.path}”中未找到 hunk 上下文“{chunk.context}”。"
                )
            line_index = context_index + 1

        if not chunk.old_lines:
            replacements.append((len(original_lines), 0, chunk.new_lines))
            continue

        old_lines = chunk.old_lines
        new_lines = chunk.new_lines
        match = _seek_patch_sequence(original_lines, old_lines, line_index, chunk.end_of_file)
        if match is None and old_lines[-1] == "":
            old_lines = old_lines[:-1]
            if new_lines and new_lines[-1] == "":
                new_lines = new_lines[:-1]
            match = _seek_patch_sequence(original_lines, old_lines, line_index, chunk.end_of_file)
        if match is None:
            raise WorkspaceError(
                f"文件“{operation.path}”中未找到 hunk 原文，请重新读取文件后重试。"
            )
        replacements.append((match, len(old_lines), new_lines))
        line_index = match + len(old_lines)

    updated_lines = list(original_lines)
    for start, old_length, new_lines in reversed(sorted(replacements, key=lambda item: item[0])):
        updated_lines[start : start + old_length] = new_lines
    if not updated_lines or updated_lines[-1] != "":
        updated_lines.append("")
    return "\n".join(updated_lines)


def build_workspace_changes(
    service: WorkspaceService,
    thread: str,
    patch: str,
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for operation in parse_codex_patch(patch):
        path = service.normalize_path(operation.path, allow_root=False)[0]
        if operation.operation == "create":
            changes.append({"operation": "create", "path": path, "content": operation.content})
            continue

        current = service.read_text(thread, path)
        digest = hashlib.sha256(current.encode("utf-8")).hexdigest()
        if operation.operation == "delete":
            changes.append({"operation": "delete", "path": path, "expected_sha256": digest})
            continue

        updated = _apply_update_chunks(current, operation)
        if operation.destination is None:
            changes.append(
                {
                    "operation": "update",
                    "path": path,
                    "content": updated,
                    "expected_sha256": digest,
                }
            )
            continue

        destination = service.normalize_path(operation.destination, allow_root=False)[0]
        if updated == current:
            changes.append(
                {
                    "operation": "move",
                    "path": path,
                    "destination": destination,
                    "expected_sha256": digest,
                }
            )
        else:
            changes.extend(
                [
                    {"operation": "delete", "path": path, "expected_sha256": digest},
                    {"operation": "create", "path": destination, "content": updated},
                ]
            )
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


class CodingToolkit(_ManagedDaytonaTools):
    def __init__(self, service: WorkspaceService):
        self.service = service
        self._workspace = WorkspaceToolkit(service)
        self._plan = AgentControlToolkit(service)
        self._session_locks: weakref.WeakValueDictionary[tuple[str, int], asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        super().__init__(
            name="coding",
            tools=[
                Function(
                    name="exec_command",
                    description=(
                        "在当前 thread 的 Daytona 工作区执行完整 Shell 命令；"
                        "返回受管 session_id 时它不是 OS PID。也可作为 apply_patch 的兼容兜底："
                        "仅接受独立的 apply_patch heredoc，并在服务端按相同原子 Patch 语义执行。"
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "cmd": {
                                "type": "string",
                                "minLength": 1,
                                "description": (
                                    "完整 Shell 命令。apply_patch fallback 必须使用独立的 "
                                    "apply_patch <<'PATCH' heredoc，不能附加其他命令。"
                                ),
                            },
                            "workdir": {
                                "anyOf": [{"type": "string"}, {"type": "null"}],
                                "description": "可选工作区相对目录。",
                            },
                            "tty": {
                                "type": "boolean",
                                "default": False,
                                "description": "是否分配 PTY。",
                            },
                            "timeout_seconds": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_BACKGROUND_EXECUTION_TIMEOUT,
                                "default": DEFAULT_EXEC_TIMEOUT_SECONDS,
                                "description": (
                                    "受管命令的最长运行秒数；默认 900，"
                                    "明确的长构建、测试或服务可提高至 86400。"
                                ),
                            },
                            "yield_time_ms": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 30000,
                                "default": DEFAULT_YIELD_TIME_MS,
                                "description": "返回前等待输出或完成的毫秒数，必须在 0 至 30000 之间。",
                            },
                            "max_output_tokens": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_OUTPUT_TOKENS,
                                "default": DEFAULT_MAX_OUTPUT_TOKENS,
                                "description": "返回输出的近似 token 上限。",
                            },
                            "shell": {
                                "anyOf": [
                                    {"type": "string", "enum": ["/bin/sh", "/bin/bash"]},
                                    {"type": "null"},
                                ],
                                "description": "可选的受支持 Shell。",
                            },
                            "login": {
                                "type": "boolean",
                                "default": True,
                                "description": "指定 Shell 是否使用登录模式。",
                            },
                        },
                        "required": ["cmd"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.exec_command,
                ),
                Function(
                    name="poll_process",
                    description="轮询受管命令，并返回增量日志和当前状态。",
                    parameters={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "exec_command 返回的当前 thread 受管整数句柄，不是 OS PID。",
                            },
                            "yield_time_ms": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 30000,
                                "default": DEFAULT_YIELD_TIME_MS,
                                "description": "轮询时等待新输出或完成的毫秒数，必须在 0 至 30000 之间。",
                            },
                            "max_output_tokens": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_OUTPUT_TOKENS,
                                "default": DEFAULT_MAX_OUTPUT_TOKENS,
                                "description": "返回输出的近似 token 上限。",
                            },
                        },
                        "required": ["session_id"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.poll_process,
                ),
                Function(
                    name="write_stdin",
                    description="向仍在运行的受管命令写入字符或发送 Ctrl-C。",
                    parameters={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "exec_command 返回的当前 thread 受管整数句柄，不是 OS PID。",
                            },
                            "chars": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": MAX_PROCESS_INPUT_BYTES,
                                "description": "要写入的非空字符；使用 \\u0003 发送 Ctrl-C。",
                            },
                            "yield_time_ms": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 30000,
                                "default": DEFAULT_YIELD_TIME_MS,
                                "description": "写入后的等待毫秒数，必须在 0 至 30000 之间。",
                            },
                            "max_output_tokens": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_OUTPUT_TOKENS,
                                "default": DEFAULT_MAX_OUTPUT_TOKENS,
                                "description": "返回输出的近似 token 上限。",
                            },
                        },
                        "required": ["session_id", "chars"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.write_stdin,
                ),
                Function(
                    name="stop_process",
                    description=(
                        "终止仍在运行的受管命令并清理远端会话；支持非 PTY 命令，"
                        "重复终止返回缓存状态。"
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "exec_command 返回的当前 thread 受管整数句柄。",
                            }
                        },
                        "required": ["session_id"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.stop_process,
                ),
                Function(
                    name="apply_patch",
                    description="使用原生补丁语法原子地修改当前 Daytona 工作区文件。",
                    parameters={
                        "type": "object",
                        "properties": {
                            "patch": {
                                "type": "string",
                                "minLength": 1,
                                "description": (
                                    "优先直接传入完整原生补丁。例如：\n"
                                    "*** Begin Patch\n*** Add File: path\n+first line\n+\n"
                                    "+last line\n*** End Patch\n"
                                    "原生格式中 Add File 的每一行（包括空行）都以 + 开头；"
                                    "工具也兼容完整单层 Markdown 围栏、apply_patch heredoc 和"
                                    "漏写 + 的纯空行。Update 的首个 hunk 可省略 @@。"
                                    "禁止 ---/+++、/dev/null 和普通 unified diff。"
                                ),
                            }
                        },
                        "required": ["patch"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.apply_patch,
                ),
                Function(
                    name="view_image",
                    description="加载当前 Daytona 工作区中的图片供模型检查。",
                    parameters={
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "minLength": 1,
                                "description": "工作区相对图片路径。",
                            },
                            "detail": {
                                "type": "string",
                                "enum": ["high", "original"],
                                "default": "high",
                                "description": "图片细节级别。",
                            },
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.view_image,
                ),
                Function(
                    name="update_plan",
                    description="更新当前 Coding Agent 会话的任务计划。",
                    parameters={
                        "type": "object",
                        "properties": {
                            "plan": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 20,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["step", "status"],
                                    "properties": {
                                        "step": {
                                            "type": "string",
                                            "minLength": 1,
                                            "maxLength": 300,
                                        },
                                        "status": {
                                            "type": "string",
                                            "enum": ["pending", "in_progress", "completed"],
                                        },
                                    },
                                },
                                "description": "按顺序排列的计划步骤。",
                            },
                            "explanation": {
                                "anyOf": [{"type": "string", "maxLength": 1000}, {"type": "null"}],
                                "description": "可选计划变更说明。",
                            },
                        },
                        "required": ["plan"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.update_plan,
                ),
            ],
            instructions=CODING_TOOLKIT_INSTRUCTIONS,
        )

    @staticmethod
    def _validate_output_tokens(value: int) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= MAX_OUTPUT_TOKENS
        ):
            raise WorkspaceError(f"输出 token 上限必须是 1 至 {MAX_OUTPUT_TOKENS} 之间的整数。")
        return value

    @staticmethod
    def _bounded_output(value: Any, max_output_tokens: int) -> tuple[str, bool]:
        raw = str(value or "")
        maximum = max_output_tokens * 4
        encoded = raw.encode("utf-8", errors="replace")
        if len(encoded) <= maximum:
            return raw, False
        return encoded[:maximum].decode("utf-8", errors="ignore"), True

    @staticmethod
    def _closed_session_store(run_context: RunContext | None) -> dict[str, dict[str, Any]]:
        if run_context is None:
            raise WorkspaceError("缺少当前运行上下文。")
        if run_context.session_state is None:
            run_context.session_state = {}
        state = run_context.session_state
        if not isinstance(state, dict):
            raise WorkspaceError("当前会话状态无效。")
        closed = state.setdefault(CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY, {})
        if not isinstance(closed, dict):
            raise WorkspaceError("Coding Agent 已结束进程状态无效，请开始新的运行。")
        for key, entry in list(closed.items()):
            if not isinstance(entry, dict):
                closed.pop(key, None)
                continue
            closed_at = entry.get("closed_at")
            if (
                isinstance(closed_at, (int, float))
                and not isinstance(closed_at, bool)
                and time.time() - closed_at > CODEX_EXEC_SESSION_TTL_SECONDS
            ):
                closed.pop(key, None)
        return closed

    @staticmethod
    def _remember_closed_session(
        run_context: RunContext | None,
        key: str,
        entry: dict[str, Any] | None,
        reason: str,
    ) -> None:
        if not isinstance(entry, dict):
            return
        try:
            closed = CodingToolkit._closed_session_store(run_context)
        except WorkspaceError:
            return
        closed[key] = {
            "thread": entry.get("thread"),
            "user_id": entry.get("user_id"),
            "reason": reason,
            "closed_at": time.time(),
            **(
                {"timeout_seconds": entry["timeout_seconds"]}
                if isinstance(entry.get("timeout_seconds"), int)
                and not isinstance(entry.get("timeout_seconds"), bool)
                else {}
            ),
        }
        while len(closed) > MAX_CLOSED_SESSION_HANDLES:
            oldest = min(
                closed,
                key=lambda item: (
                    closed[item].get("closed_at", 0) if isinstance(closed.get(item), dict) else 0
                ),
            )
            closed.pop(oldest, None)

    @staticmethod
    def _closed_session_entry(
        session_id: int, run_context: RunContext | None
    ) -> dict[str, Any] | None:
        closed = CodingToolkit._closed_session_store(run_context)
        entry = closed.get(str(session_id))
        if not isinstance(entry, dict):
            return None
        if entry.get("thread") != _thread(run_context) or entry.get("user_id") != getattr(
            run_context, "user_id", None
        ):
            return None
        return entry

    @staticmethod
    def _closed_session_error(session_id: int, run_context: RunContext | None) -> None:
        entry = CodingToolkit._closed_session_entry(session_id, run_context)
        if entry is None:
            return
        reason = entry.get("reason")
        if reason == "completed":
            raise WorkspaceError(
                "进程 session_id 对应的受管命令已经完成；请依据最后一次结果判断状态，"
                "不要继续轮询或写入。"
            )
        if reason == "timed_out":
            raise WorkspaceError("进程 session_id 对应的受管命令已经超时终止，请重新执行必要命令。")
        if reason == "expired":
            raise WorkspaceError("进程 session_id 已过期，不能跨过期会话继续监控。")
        if reason == "lost":
            raise WorkspaceError("进程 session_id 对应的后台命令已经结束或丢失。")
        if reason == "terminated":
            raise WorkspaceError("进程 session_id 对应的受管命令已经终止，不能继续使用。")
        raise WorkspaceError("进程 session_id 已关闭，不能继续轮询或写入。")

    @staticmethod
    def _session_expired(entry: dict[str, Any], now: float) -> bool:
        started_at = entry.get("started_at")
        expires_at = entry.get("expires_at")
        valid_expiry = isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool)
        return bool(
            (
                isinstance(expires_at, (int, float))
                and not isinstance(expires_at, bool)
                and now > expires_at
            )
            or (
                not valid_expiry
                and isinstance(started_at, (int, float))
                and not isinstance(started_at, bool)
                and now - started_at > CODEX_EXEC_SESSION_TTL_SECONDS
            )
        )

    @staticmethod
    def _session_store(run_context: RunContext | None) -> dict[str, dict[str, Any]]:
        if run_context is None:
            raise WorkspaceError("缺少当前运行上下文。")
        if run_context.session_state is None:
            run_context.session_state = {}
        state = run_context.session_state
        if not isinstance(state, dict):
            raise WorkspaceError("当前会话状态无效。")
        sessions = state.setdefault(CODEX_EXEC_SESSIONS_STATE_KEY, {})
        if not isinstance(sessions, dict):
            raise WorkspaceError("Coding Agent 进程状态无效，请开始新的运行。")
        for key, entry in list(sessions.items()):
            if not isinstance(entry, dict):
                sessions.pop(key, None)
        return sessions

    async def _stop_remote_session(
        self,
        entry: dict[str, Any],
        run_context: RunContext | None,
        *,
        missing_ok: bool,
    ) -> None:
        try:
            await self._workspace.sandbox_process_stop(
                entry["session_id"],
                entry["command_id"],
                run_context=run_context,
            )
        except (DaytonaNotFoundError, WorkspaceProcessNotFound):
            if not missing_ok:
                raise

    async def _prune_expired_sessions(self, run_context: RunContext | None) -> None:
        sessions = self._session_store(run_context)
        thread = _thread(run_context)
        for key in list(sessions):
            try:
                handle = int(key)
            except (TypeError, ValueError):
                sessions.pop(key, None)
                continue
            async with self._session_lock(thread, handle):
                entry = sessions.get(key)
                if not isinstance(entry, dict) or not self._session_expired(entry, time.time()):
                    continue
                if entry.get("thread") != thread or entry.get("user_id") != getattr(
                    run_context, "user_id", None
                ):
                    raise WorkspaceError("Coding Agent 过期进程状态不属于当前 thread 和用户。")
                try:
                    await self._stop_remote_session(entry, run_context, missing_ok=True)
                except Exception as error:
                    raise WorkspaceError("清理过期进程失败，请稍后重试。") from error
                self._remember_closed_session(run_context, key, entry, "expired")
                sessions.pop(key, None)

    def _session_lock(self, thread: str, session_id: int) -> asyncio.Lock:
        key = (thread, session_id)
        lock = self._session_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[key] = lock
        return lock

    @staticmethod
    def _validate_session_id(session_id: int) -> int:
        if isinstance(session_id, bool) or not isinstance(session_id, int) or session_id < 1:
            raise WorkspaceError("进程 session_id 必须是 exec_command 返回的正整数。")
        return session_id

    @staticmethod
    def _next_offset(result: dict[str, Any], current_offset: int) -> int:
        raw_output = str(result.get("output", "") or "")
        maximum = current_offset + len(raw_output.encode("utf-8", errors="replace"))
        next_offset = result.get("nextOffset", maximum)
        if (
            isinstance(next_offset, bool)
            or not isinstance(next_offset, int)
            or not current_offset <= next_offset <= maximum
        ):
            raise WorkspaceError("Coding Agent 进程输出偏移无效，请开始新的运行。")
        total_bytes = result.get("totalBytes")
        if total_bytes is not None and (
            isinstance(total_bytes, bool)
            or not isinstance(total_bytes, int)
            or total_bytes < next_offset
        ):
            raise WorkspaceError("Coding Agent 进程输出总字节数无效，请开始新的运行。")
        return next_offset

    def _reserve_session(
        self,
        run_context: RunContext | None,
        *,
        started_at: float,
    ) -> tuple[dict[str, dict[str, Any]], str, int, dict[str, Any]]:
        sessions = self._session_store(run_context)
        if len(sessions) >= MAX_CODEX_SESSION_HANDLES:
            raise WorkspaceError("Coding Agent 进程句柄过多，请完成现有命令后重试。")
        assert run_context is not None and isinstance(run_context.session_state, dict)
        raw_next = run_context.session_state.get(CODEX_EXEC_NEXT_SESSION_STATE_KEY, 1)
        next_id = raw_next if isinstance(raw_next, int) and not isinstance(raw_next, bool) else 1
        while str(next_id) in sessions:
            next_id += 1
        entry = {
            "thread": _thread(run_context),
            "user_id": run_context.user_id,
            "started_at": started_at,
        }
        key = str(next_id)
        sessions[key] = entry
        run_context.session_state[CODEX_EXEC_NEXT_SESSION_STATE_KEY] = next_id + 1
        return sessions, key, next_id, entry

    def _session_entry(
        self,
        session_id: int,
        run_context: RunContext | None,
    ) -> tuple[dict[str, dict[str, Any]], str, dict[str, Any]]:
        self._validate_session_id(session_id)
        sessions = self._session_store(run_context)
        key = str(session_id)
        entry = sessions.get(key)
        if not isinstance(entry, dict):
            self._closed_session_error(session_id, run_context)
            raise WorkspaceError(
                "进程 session_id 不存在或已经结束；请使用 exec_command 返回的最新句柄。"
            )
        if entry.get("thread") != _thread(run_context) or entry.get("user_id") != getattr(
            run_context, "user_id", None
        ):
            raise WorkspaceError("进程 session_id 不属于当前 thread 和用户，或已经结束。")
        if not isinstance(entry.get("session_id"), str) or not isinstance(
            entry.get("command_id"), str
        ):
            raise WorkspaceError("Coding Agent 进程状态无效，请开始新的运行。")
        return sessions, key, entry

    def _format_process_result(
        self,
        result: dict[str, Any],
        max_output_tokens: int,
        session_id: int | None = None,
    ) -> dict[str, Any]:
        output, clipped = self._bounded_output(result.get("output", ""), max_output_tokens)
        status = result.get("status", "completed")
        exit_code = result.get("exitCode")
        outcome = (
            "running"
            if status == "running"
            else "success"
            if exit_code == 0
            else "timed_out"
            if result.get("timedOut") is True
            else "failed"
        )
        value = {
            "status": status,
            "output": output,
            "exit_code": exit_code,
            "outcome": outcome,
            "wall_time_seconds": result.get("wallTimeSeconds", 0.0),
            "truncated": bool(result.get("truncated")) or clipped,
        }
        if value["status"] == "running":
            value["guidance"] = (
                "普通长任务使用 poll_process 继续读取；预期长驻服务应保留 session_id，"
                "改用独立 exec_command 执行健康检查；成功后结束当前任务，后续按需或定时"
                "使用 poll_process 读取增量日志和状态，不要在同一轮中紧密轮询等待退出。"
                "非长驻命令连续两次轮询没有新输出时，应停止盲目轮询并报告阻塞。"
            )
        elif outcome == "timed_out":
            value["guidance"] = (
                "命令已达到 timeout_seconds 并被受管执行器终止。请报告超时，"
                "检查已有输出后决定是修正任务，还是仅在确有需要时使用更长时限重新执行。"
            )
        elif outcome == "failed":
            value["guidance"] = (
                "命令已结束但 exit_code 非零。请依据 output 报告实际失败原因；"
                "依赖安装场景需如实说明网络、索引、解析或构建错误，不要把该结果报告为成功。"
            )
        if session_id is not None:
            value["session_id"] = session_id
        return value

    @staticmethod
    def _shell_policy_source(root: Node, source: bytes) -> str:
        masked = bytearray(source)
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type in {
                "comment",
                "heredoc_body",
                "heredoc_end",
                "heredoc_start",
                "simple_heredoc_body",
            }:
                for index in range(node.start_byte, node.end_byte):
                    if masked[index] not in {10, 13}:
                        masked[index] = 32
                continue
            stack.extend(node.children)
        return masked.decode("utf-8")

    @staticmethod
    def _contains_shell_background_operator(root: Node) -> bool:
        stack = [root]
        while stack:
            node = stack.pop()
            if (
                node.type == "&"
                and node.parent is not None
                and node.parent.type != "binary_expression"
            ):
                return True
            stack.extend(node.children)
        return False

    @classmethod
    def _validate_command_policy(cls, cmd: str, selected_shell: str) -> None:
        if not isinstance(cmd, str) or not cmd.strip():
            raise WorkspaceError("Shell 命令不能为空。")
        source = cmd.encode("utf-8")
        tree = Parser(_BASH_LANGUAGE).parse(source)
        root = tree.root_node
        if root.has_error:
            raise WorkspaceError(
                "Shell 命令语法无法可靠解析；请检查引号、heredoc 闭合标记和 Shell 语法。"
            )
        policy_source = cls._shell_policy_source(root, source)
        if PIP_INSTALL_WITH_OUTPUT_FILTER.search(policy_source):
            raise WorkspaceError(
                "安装依赖时不能把 pip 输出管道到 tail/head/grep/sed；"
                "请保留完整输出，以便报告网络、索引、解析或构建错误。"
            )
        if MUTATING_INLINE_EDIT_COMMAND.search(policy_source):
            raise WorkspaceError("修改文件必须使用 apply_patch；不得使用 sed -i 或 perl -pi。")
        if DETACHED_PROCESS_COMMAND.search(policy_source):
            raise WorkspaceError("禁止使用 nohup 或 disown；长驻服务必须保持为受管前台命令。")
        if cls._contains_shell_background_operator(root):
            raise WorkspaceError(
                "禁止使用 shell 后台符号 & 绕过受管进程；"
                "请直接以前台命令启动服务，让 exec_command 返回 session_id。"
            )
        if selected_shell == "/bin/sh" and re.search(r"(?:^|[;&|]\s*)source\s+", policy_source):
            raise WorkspaceError(
                '默认 shell 是 /bin/sh，不支持 source；需要时设置 shell="/bin/bash"。'
            )

    async def _poll_process(
        self,
        entry: dict[str, Any],
        *,
        offset: int,
        max_bytes: int,
        yield_time_ms: int,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        started_at = asyncio.get_running_loop().time()
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, _thread(run_context))
            return await self._workspace._wait_managed_output(
                sandbox.process,
                entry["session_id"],
                entry["command_id"],
                offset=offset,
                max_bytes=max_bytes,
                yield_time_ms=yield_time_ms,
                started_at=started_at,
            )

    async def exec_command(
        self,
        cmd: str,
        workdir: str | None = None,
        tty: bool = False,
        timeout_seconds: int = DEFAULT_EXEC_TIMEOUT_SECONDS,
        yield_time_ms: int = DEFAULT_YIELD_TIME_MS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        shell: str | None = None,
        login: bool = True,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        if not isinstance(login, bool):
            raise WorkspaceError("Shell 登录模式必须是布尔值。")
        selected_shell = shell or "/bin/sh"
        if selected_shell not in {"/bin/sh", "/bin/bash"}:
            raise WorkspaceError("shell 只支持 /bin/sh 或 /bin/bash。")
        if not isinstance(tty, bool):
            raise WorkspaceError("伪终端标志必须是布尔值。")
        execution_timeout = self.service._validate_timeout(
            timeout_seconds,
            MAX_BACKGROUND_EXECUTION_TIMEOUT,
        )
        validated_yield_time = self._workspace._validate_yield_time(yield_time_ms)
        assert validated_yield_time is not None
        maximum = self._validate_output_tokens(max_output_tokens)
        if not isinstance(cmd, str) or not cmd.strip():
            raise WorkspaceError("Shell 命令不能为空。")

        patch = _extract_apply_patch_command(cmd)
        if patch is not None:
            if workdir not in (None, ""):
                raise WorkspaceError(
                    "apply_patch fallback 不支持 workdir；补丁路径必须相对工作区根目录。"
                )
            if tty:
                raise WorkspaceError("apply_patch fallback 不支持 PTY。")
            patch_result = await asyncio.to_thread(self.apply_patch, patch, run_context)
            return {
                "status": "completed",
                "output": f"{patch_result['message']}\n",
                "exit_code": 0,
                "outcome": "success",
                "wall_time_seconds": 0.0,
                "truncated": False,
                "timeout_seconds": execution_timeout,
                **patch_result,
                "intercepted_tool": "apply_patch",
            }

        self._validate_command_policy(cmd, selected_shell)
        arguments = [selected_shell]
        if login:
            arguments.append("-l")
        arguments.extend(["-c", cmd])
        command = f"exec {shlex.join(arguments)}"
        started_at = time.time()
        await self._prune_expired_sessions(run_context)
        sessions, key, handle, entry = self._reserve_session(
            run_context,
            started_at=started_at,
        )
        entry["expires_at"] = started_at + execution_timeout + 300
        entry["timeout_seconds"] = execution_timeout
        result: dict[str, Any] | None = None
        try:
            result = await self._workspace.sandbox_exec(
                command,
                cwd=workdir,
                timeout=execution_timeout,
                background=True,
                pty=tty,
                yield_time_ms=validated_yield_time,
                run_context=run_context,
            )
            formatted = self._format_process_result(result, maximum)
            formatted["timeout_seconds"] = execution_timeout
            needs_session = result.get("status") == "running" or bool(result.get("hasMore"))
            if not needs_session:
                reason = "timed_out" if formatted["outcome"] == "timed_out" else "completed"
                self._remember_closed_session(run_context, key, entry, reason)
                sessions.pop(key, None)
                return formatted
            raw_offset = result.get("offset", 0)
            if isinstance(raw_offset, bool) or not isinstance(raw_offset, int) or raw_offset < 0:
                raise WorkspaceError("Coding Agent 进程输出偏移无效，请开始新的运行。")
            consumed = len(formatted["output"].encode("utf-8"))
            next_offset = self._next_offset(result, raw_offset)
            entry.update(
                {
                    "session_id": result["sessionId"],
                    "command_id": result["commandId"],
                    "offset": min(next_offset, raw_offset + consumed),
                }
            )
            formatted["session_id"] = handle
            return formatted
        except BaseException:
            sessions.pop(key, None)
            if result is not None:
                remote_session_id = result.get("sessionId")
                remote_command_id = result.get("commandId")
                if isinstance(remote_session_id, str) and isinstance(remote_command_id, str):
                    try:
                        await complete_cleanup(
                            self._workspace.sandbox_process_stop(
                                remote_session_id,
                                remote_command_id,
                                run_context=run_context,
                            )
                        )
                    except Exception:
                        pass
            raise

    async def poll_process(
        self,
        session_id: int,
        yield_time_ms: int = DEFAULT_YIELD_TIME_MS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return await self._continue_process(
            session_id,
            chars="",
            yield_time_ms=yield_time_ms,
            max_output_tokens=max_output_tokens,
            run_context=run_context,
        )

    async def write_stdin(
        self,
        session_id: int,
        # 兼容升级前已持久化的待确认轮询；新工具 schema 仍要求 chars。
        chars: str = "",
        yield_time_ms: int = DEFAULT_YIELD_TIME_MS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        if not isinstance(chars, str):
            raise WorkspaceError("进程输入必须是字符串。")
        return await self._continue_process(
            session_id,
            chars=chars,
            yield_time_ms=yield_time_ms,
            max_output_tokens=max_output_tokens,
            run_context=run_context,
        )

    async def stop_process(
        self,
        session_id: int,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        handle = self._validate_session_id(session_id)
        thread = _thread(run_context)
        async with self._session_lock(thread, handle):
            closed_entry = self._closed_session_entry(handle, run_context)
            if closed_entry is not None and closed_entry.get("reason") == "terminated":
                return {
                    "status": "terminated",
                    "outcome": "terminated",
                    "session_id": handle,
                    "status_is_cached": True,
                }
            sessions, key, entry = self._session_entry(handle, run_context)
            try:
                await self._stop_remote_session(entry, run_context, missing_ok=False)
            except (DaytonaNotFoundError, WorkspaceProcessNotFound) as error:
                self._remember_closed_session(run_context, key, entry, "lost")
                sessions.pop(key, None)
                raise WorkspaceError("进程 session_id 对应的后台命令已经结束或丢失。") from error
            self._remember_closed_session(run_context, key, entry, "terminated")
            sessions.pop(key, None)
            return {"status": "terminated", "outcome": "terminated", "session_id": handle}

    async def _continue_process(
        self,
        session_id: int,
        *,
        chars: str,
        yield_time_ms: int,
        max_output_tokens: int,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        maximum = self._validate_output_tokens(max_output_tokens)
        validated_yield_time = self._workspace._validate_yield_time(yield_time_ms)
        assert validated_yield_time is not None
        handle = self._validate_session_id(session_id)
        thread = _thread(run_context)
        async with self._session_lock(thread, handle):
            sessions = self._session_store(run_context)
            current = sessions.get(str(handle))
            if isinstance(current, dict) and self._session_expired(current, time.time()):
                try:
                    await self._stop_remote_session(current, run_context, missing_ok=True)
                except Exception as error:
                    raise WorkspaceError("清理过期进程失败，请稍后重试。") from error
                self._remember_closed_session(run_context, str(handle), current, "expired")
                sessions.pop(str(handle), None)
            sessions, key, entry = self._session_entry(handle, run_context)
            offset = entry.get("offset", 0)
            max_bytes = min(MAX_TOOL_OUTPUT_BYTES, maximum * 4)
            try:
                if chars == "\x03":
                    await self._workspace.sandbox_process_interrupt(
                        entry["session_id"],
                        entry["command_id"],
                        run_context=run_context,
                    )
                    result = await self._poll_process(
                        entry,
                        offset=offset,
                        max_bytes=max_bytes,
                        yield_time_ms=validated_yield_time,
                        run_context=run_context,
                    )
                elif chars:
                    if len(chars.encode("utf-8")) > MAX_PROCESS_INPUT_BYTES:
                        raise WorkspaceError("进程单次输入超过 8 KiB，请拆分后重试。")
                    result = await self._workspace.sandbox_process_write(
                        entry["session_id"],
                        entry["command_id"],
                        chars,
                        offset=offset,
                        max_bytes=max_bytes,
                        yield_time_ms=validated_yield_time,
                        run_context=run_context,
                    )
                else:
                    result = await self._poll_process(
                        entry,
                        offset=offset,
                        max_bytes=max_bytes,
                        yield_time_ms=validated_yield_time,
                        run_context=run_context,
                    )
            except (DaytonaNotFoundError, WorkspaceProcessNotFound) as error:
                self._remember_closed_session(run_context, key, entry, "lost")
                sessions.pop(key, None)
                raise WorkspaceError("进程 session_id 对应的后台命令已经结束或丢失。") from error
            entry["offset"] = self._next_offset(result, offset)
            completed = result.get("status") == "completed" and not result.get("hasMore")
            if completed:
                outcome = self._format_process_result(result, maximum).get("outcome")
                reason = "timed_out" if outcome == "timed_out" else "completed"
                self._remember_closed_session(run_context, key, entry, reason)
                sessions.pop(key, None)
            formatted = self._format_process_result(
                result, maximum, None if completed else session_id
            )
            timeout_seconds = entry.get("timeout_seconds")
            if isinstance(timeout_seconds, int) and not isinstance(timeout_seconds, bool):
                formatted["timeout_seconds"] = timeout_seconds
            started_at = entry.get("started_at")
            if isinstance(started_at, (int, float)) and not isinstance(started_at, bool):
                formatted["wall_time_seconds"] = round(max(0.0, time.time() - started_at), 3)
            return formatted

    def apply_patch(
        self,
        patch: str,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        thread = _thread(run_context)
        changes = build_workspace_changes(self.service, thread, patch)
        result = self.service.apply_changes(thread, changes)
        return {**result, "ok": True, "message": "补丁已应用。"}

    def view_image(
        self,
        path: str,
        detail: str = "high",
        run_context: RunContext | None = None,
    ):
        if detail not in {"high", "original"}:
            raise WorkspaceError("图片 detail 必须是 high 或 original。")
        return self.service.view_image(_thread(run_context), path)

    def update_plan(
        self,
        plan: list[dict[str, str]],
        explanation: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        return self._plan.agent_update_plan(plan, explanation, run_context)


class HermesCodingToolkit(_ManagedDaytonaTools):
    """提供 terminal/process/patch 调用形状，并复用现有安全执行内核。"""

    def __init__(self, coding: CodingToolkit):
        self.coding = coding
        super().__init__(
            name="hermes_coding",
            tools=[
                Function(
                    name="terminal",
                    description=(
                        "在当前 thread 的 Daytona 工作区执行受管 Shell 命令；"
                        "前台模式最多等待 30 秒，后台模式立即返回 session_id。"
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "minLength": 1,
                                "description": "要执行的完整 Shell 命令。",
                            },
                            "background": {
                                "type": "boolean",
                                "default": False,
                                "description": "是否立即返回受管进程句柄。",
                            },
                            "timeout": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_BACKGROUND_EXECUTION_TIMEOUT,
                                "default": DEFAULT_EXEC_TIMEOUT_SECONDS,
                                "description": "命令最长运行秒数，默认 900，最大 86400。",
                            },
                            "workdir": {
                                "anyOf": [{"type": "string"}, {"type": "null"}],
                                "description": "可选工作区相对目录。",
                            },
                            "pty": {
                                "type": "boolean",
                                "default": False,
                                "description": "是否分配 PTY。",
                            },
                        },
                        "required": ["command"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.terminal,
                ),
                Function(
                    name="process",
                    description=(
                        "管理 terminal 返回的受管进程；支持列出、轮询、等待、终止、"
                        "原样写入和提交带换行的输入。"
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["list", "poll", "wait", "kill", "write", "submit"],
                                "description": "要执行的进程操作。",
                            },
                            "session_id": {
                                "anyOf": [
                                    {"type": "string", "pattern": "^[1-9][0-9]*$"},
                                    {"type": "integer", "minimum": 1},
                                ],
                                "description": "terminal 返回的受管句柄；接受数字字符串或正整数。",
                            },
                            "data": {
                                "type": "string",
                                "maxLength": MAX_PROCESS_INPUT_BYTES,
                                "description": "write 或 submit 要发送的文本。",
                            },
                            "timeout": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": MAX_BACKGROUND_EXECUTION_TIMEOUT,
                                "default": 30,
                                "description": "wait 最长等待秒数。",
                            },
                        },
                        "required": ["action"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.process,
                ),
                Function(
                    name="patch",
                    description=(
                        "修改当前 Daytona 工作区文件；replace 模式做精确字符串替换，"
                        "patch 模式应用完整的原生多文件补丁。"
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "mode": {
                                "type": "string",
                                "enum": ["replace", "patch"],
                                "default": "replace",
                                "description": "replace 为精确替换，patch 为原生补丁。",
                            },
                            "path": {
                                "type": "string",
                                "description": "replace 模式必填的工作区相对文件路径。",
                            },
                            "old_string": {
                                "type": "string",
                                "description": "replace 模式必填的非空原文。",
                            },
                            "new_string": {
                                "type": "string",
                                "description": "replace 模式必填的替换文本；可为空字符串。",
                            },
                            "replace_all": {
                                "type": "boolean",
                                "default": False,
                                "description": "是否替换所有匹配；否则原文必须唯一。",
                            },
                            "patch": {
                                "type": "string",
                                "description": (
                                    "patch 模式必填的完整补丁，必须包含 "
                                    "*** Begin Patch 和 *** End Patch。"
                                ),
                            },
                        },
                        "required": ["mode"],
                        "additionalProperties": False,
                    },
                    entrypoint=self.patch,
                ),
            ],
            instructions=HERMES_CODING_TOOLKIT_INSTRUCTIONS,
        )

    @staticmethod
    def _session_handle(session_id: str | int | None) -> int:
        if isinstance(session_id, bool):
            raise WorkspaceError("进程 session_id 必须是 terminal 返回的数字字符串或正整数。")
        if isinstance(session_id, int) and session_id > 0:
            return session_id
        if isinstance(session_id, str) and session_id.isdigit() and int(session_id) > 0:
            return int(session_id)
        raise WorkspaceError("进程 session_id 必须是 terminal 返回的数字字符串或正整数。")

    @staticmethod
    def _public_process_result(result: dict[str, Any]) -> dict[str, Any]:
        value = dict(result)
        if "session_id" in value:
            value["session_id"] = str(value["session_id"])
        return value

    async def terminal(
        self,
        command: str,
        background: bool = False,
        timeout: int | None = None,
        workdir: str | None = None,
        pty: bool = False,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        if not isinstance(background, bool):
            raise WorkspaceError("terminal 的 background 必须是布尔值。")
        execution_timeout = DEFAULT_EXEC_TIMEOUT_SECONDS if timeout is None else timeout
        result = await self.coding.exec_command(
            command,
            workdir=workdir,
            tty=pty,
            timeout_seconds=execution_timeout,
            yield_time_ms=0 if background else 30000,
            run_context=run_context,
        )
        return self._public_process_result(result)

    async def process(
        self,
        action: str,
        session_id: str | int | None = None,
        data: str = "",
        timeout: int | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        if action == "list":
            await self.coding._prune_expired_sessions(run_context)
            thread = _thread(run_context)
            sessions = self.coding._session_store(run_context)
            processes = []
            for key, entry in sessions.items():
                if entry.get("thread") != thread or entry.get("user_id") != getattr(
                    run_context, "user_id", None
                ):
                    continue
                process = {
                    "session_id": key,
                    "status": "running",
                    "started_at": entry.get("started_at"),
                }
                if isinstance(entry.get("timeout_seconds"), int) and not isinstance(
                    entry.get("timeout_seconds"), bool
                ):
                    process["timeout_seconds"] = entry["timeout_seconds"]
                processes.append(process)
            return {"processes": processes}

        if action not in {"poll", "wait", "kill", "write", "submit"}:
            raise WorkspaceError("process action 只支持 list、poll、wait、kill、write 或 submit。")
        handle = self._session_handle(session_id)
        if action == "poll":
            result = await self.coding.poll_process(
                handle,
                yield_time_ms=0,
                run_context=run_context,
            )
        elif action == "wait":
            result = await self._wait_process(handle, timeout, run_context)
        elif action == "kill":
            result = await self.coding.stop_process(handle, run_context=run_context)
        else:
            if not isinstance(data, str):
                raise WorkspaceError("进程输入必须是字符串。")
            chars = data if action == "write" else f"{data}\n"
            result = await self.coding.write_stdin(
                handle,
                chars,
                yield_time_ms=0,
                run_context=run_context,
            )
        return self._public_process_result(result)

    async def _wait_process(
        self,
        session_id: int,
        timeout: int | None,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        wait_seconds = self.coding.service._validate_timeout(
            30 if timeout is None else timeout,
            MAX_BACKGROUND_EXECUTION_TIMEOUT,
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        output_parts: list[str] = []
        result: dict[str, Any] = {"status": "running", "session_id": session_id}
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            result = await self.coding.poll_process(
                session_id,
                yield_time_ms=min(30000, max(0, int(remaining * 1000))),
                max_output_tokens=MAX_OUTPUT_TOKENS,
                run_context=run_context,
            )
            output = result.get("output")
            if isinstance(output, str) and output:
                output_parts.append(output)
            if result.get("status") != "running":
                break
            if not output:
                await asyncio.sleep(min(0.05, max(0, deadline - loop.time())))

        output, clipped = self.coding._bounded_output(
            "".join(output_parts),
            MAX_OUTPUT_TOKENS,
        )
        result = dict(result)
        result["output"] = output
        result["truncated"] = bool(result.get("truncated")) or clipped
        if result.get("status") == "running":
            result["wait_timed_out"] = True
        return result

    def patch(
        self,
        mode: str = "replace",
        path: str | None = None,
        old_string: str | None = None,
        new_string: str | None = None,
        replace_all: bool = False,
        patch: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        if mode == "patch":
            if any(value is not None for value in (path, old_string, new_string)) or replace_all:
                raise WorkspaceError("patch 模式只能传入 mode 和 patch。")
            if not isinstance(patch, str) or not patch.strip():
                raise WorkspaceError("patch 模式必须提供非空补丁文本。")
            return self.coding.apply_patch(patch, run_context=run_context)
        if mode != "replace":
            raise WorkspaceError("patch mode 只支持 replace 或 patch。")
        if patch is not None:
            raise WorkspaceError("replace 模式不能同时传入 patch。")
        if (
            not isinstance(path, str)
            or not path
            or not isinstance(old_string, str)
            or not old_string
            or not isinstance(new_string, str)
        ):
            raise WorkspaceError("replace 模式必须提供 path、非空 old_string 和字符串 new_string。")
        if not isinstance(replace_all, bool):
            raise WorkspaceError("replace_all 必须是布尔值。")
        thread = _thread(run_context)
        current = self.coding.service.read_text(thread, path)
        digest = hashlib.sha256(current.encode("utf-8")).hexdigest()
        result = self.coding.service.apply_patch(
            thread,
            path,
            old_string,
            new_string,
            digest,
            replace_all,
        )
        return {**result, "ok": True, "message": "文件替换已应用。"}
