"""工作区共用的路径规范化、内容与哈希校验、错误类型和容量常量。

Reporting 只使用宿主机上的本地工作区（见 ``reporting.host_workspace``）；本模块不绑定任何具体
工作区实现，只提供各实现与工具共同遵守的路径和内容契约。
"""

from __future__ import annotations

import unicodedata
from pathlib import PurePosixPath
from typing import Any

from agno.run import RunContext

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
MAX_TOOL_OUTPUT_BYTES = 64 * 1024
MAX_PATCH_FILES = 20
MAX_PATH_BYTES = 1024
MAX_PATH_COMPONENT_BYTES = 255
MAX_PATH_DEPTH = 32


class WorkspaceError(ValueError):
    pass


class WorkspaceHashResultError(WorkspaceError):
    """哈希计算成功但返回的身份字段不符合协议。"""


class WorkspacePathConflict(WorkspaceError):
    pass


def normalize_workspace_path(path: str | None, allow_root: bool = True) -> str:
    """把用户或模型给出的路径规范为工作区内的相对 POSIX 路径；越界、控制字符和超限一律拒绝。"""

    raw = str(path or "")
    if any(unicodedata.category(character).startswith("C") for character in raw):
        raise WorkspaceError("工作区路径包含控制字符，请删除不可见字符后重试。")
    raw = raw.replace("\\", "/")
    if len(raw.encode("utf-8")) > MAX_PATH_BYTES:
        raise WorkspaceError(f"工作区路径超过 {MAX_PATH_BYTES} 字节，请缩短路径后重试。")
    candidate = PurePosixPath(raw)
    windows_absolute = len(raw) >= 2 and raw[0].isalpha() and raw[1] == ":"
    if candidate.is_absolute() or windows_absolute:
        raise WorkspaceError("工作区路径是绝对路径，请改用当前工作区内的相对路径。")
    parts = [part for part in candidate.parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise WorkspaceError("工作区路径包含目录穿越“..”，请改用当前工作区内的路径。")
    if len(parts) > MAX_PATH_DEPTH:
        raise WorkspaceError(f"工作区路径目录层级超过 {MAX_PATH_DEPTH} 层，请减少目录层级后重试。")
    if any(len(part.encode("utf-8")) > MAX_PATH_COMPONENT_BYTES for part in parts):
        raise WorkspaceError(
            f"工作区路径中的名称超过 {MAX_PATH_COMPONENT_BYTES} 字节，请缩短名称后重试。"
        )
    relative = "/".join(parts)
    if not relative and not allow_root:
        raise WorkspaceError("没有提供工作区路径，请指定文件或目录后重试。")
    return relative


def validate_workspace_content(content: bytes) -> None:
    if not isinstance(content, bytes):
        raise WorkspaceError("文件内容格式无效，请使用二进制内容后重试。")
    if len(content) > MAX_UPLOAD_BYTES:
        raise WorkspaceError("文件内容超过 200 MiB，请缩小文件后重试。")


def validate_patch_hash(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in value)
    ):
        raise WorkspaceError("补丁文件哈希格式无效，请先重新读取文件哈希。")
    return value.lower()


def _thread(run_context: RunContext | None) -> str:
    if not run_context or not run_context.session_id:
        raise WorkspaceError("当前操作没有绑定对话，请刷新页面后重试。")
    return run_context.session_id
