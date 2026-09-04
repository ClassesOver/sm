"""执行 Kernel 与受管工具共享的命令策略和会话状态原语。"""

from __future__ import annotations

import re

import tree_sitter_bash
from tree_sitter import Language, Node, Parser

from ..workspace import WorkspaceError

CODEX_EXEC_SESSIONS_STATE_KEY = "agentos_codex_exec_sessions"
CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY = "agentos_codex_exec_closed_sessions"

_BASH_LANGUAGE = Language(tree_sitter_bash.language())
APPLY_PATCH_COMMAND_PREFIX = re.compile(r"apply_patch(?=$|[\s;&|<>])")
APPLY_PATCH_HEREDOC_HEADER = re.compile(
    r"apply_patch[ \t]*<<[ \t]*(?:"
    r"(?P<quote>['\"])(?P<quoted>[A-Za-z_][A-Za-z0-9_]{0,31})(?P=quote)|"
    r"(?P<bare>[A-Za-z_][A-Za-z0-9_]{0,31})"
    r")[ \t]*"
)
MUTATING_INLINE_EDIT_COMMAND = re.compile(
    r"(?:^|[;&|]\s*)(?:sed\s+(?:-[^;&|\s]*i\b|[^;&|]*\s-i(?:\s|$))|perl\s+-p?i(?:\s|$))"
)
PIP_INSTALL_WITH_OUTPUT_FILTER = re.compile(
    r"(?:^|[;&|]\s*)(?:python3?\s+-m\s+pip|pip3?|uv\s+pip)\s+install\b[^|]*\|"
    r"\s*(?:tail|head|grep|sed)\b"
)
DETACHED_PROCESS_COMMAND = re.compile(r"(?:^|[;&|]\s*)(?:nohup|disown)\b")


def extract_apply_patch_command(cmd: str) -> str | None:
    """解析 exec_command 中允许的独立 apply_patch 调用。"""
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
        return "\n".join(lines[1:closing_index]) + "\n"
    if re.match(r"apply_patch[ \t]+['\"]", first_line) is None:
        raise WorkspaceError(
            "exec_command 中的 apply_patch 只能接收同一行开始的单个引号参数，建议改用独立 heredoc。"
        )
    import shlex

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


def _contains_shell_background_operator(root: Node) -> bool:
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "&" and node.parent is not None and node.parent.type != "binary_expression":
            return True
        stack.extend(node.children)
    return False


def validate_command_policy(cmd: str, selected_shell: str) -> None:
    """执行 TaskExecution Kernel 的 Shell 安全策略。"""
    if not isinstance(cmd, str) or not cmd.strip():
        raise WorkspaceError("Shell 命令不能为空。")
    source = cmd.encode("utf-8")
    root = Parser(_BASH_LANGUAGE).parse(source).root_node
    if root.has_error:
        raise WorkspaceError(
            "Shell 命令语法无法可靠解析；请检查引号、heredoc 闭合标记和 Shell 语法。"
        )
    policy_source = _shell_policy_source(root, source)
    if PIP_INSTALL_WITH_OUTPUT_FILTER.search(policy_source):
        raise WorkspaceError(
            "安装依赖时不能把 pip 输出管道到 tail/head/grep/sed；"
            "请保留完整输出，以便报告网络、索引、解析或构建错误。"
        )
    if MUTATING_INLINE_EDIT_COMMAND.search(policy_source):
        raise WorkspaceError("修改文件必须使用 apply_patch；不得使用 sed -i 或 perl -pi。")
    if DETACHED_PROCESS_COMMAND.search(policy_source):
        raise WorkspaceError("禁止使用 nohup 或 disown；长驻服务必须保持为受管前台命令。")
    if _contains_shell_background_operator(root):
        raise WorkspaceError(
            "禁止使用 shell 后台符号 & 绕过受管进程；"
            "请直接以前台命令启动服务，让 exec_command 返回 session_id。"
        )
    if selected_shell == "/bin/sh" and re.search(r"(?:^|[;&|]\s*)source\s+", policy_source):
        raise WorkspaceError('默认 shell 是 /bin/sh，不支持 source；需要时设置 shell="/bin/bash"。')
