"""Reporting 工具使用的不可变运行上下文。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ...workspace import WorkspaceError, WorkspaceService


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ReportingFileRef:
    """由服务端签发并在读取时复核的文件身份。"""

    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        try:
            normalized = WorkspaceService.normalize_path(self.path, allow_root=False)[0]
        except WorkspaceError as error:
            raise ValueError("Reporting 文件路径无效。") from error
        if normalized != self.path:
            raise ValueError("Reporting 文件路径必须是规范化相对路径。")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ValueError("Reporting 文件大小无效。")
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("Reporting 文件 SHA-256 无效。")


@dataclass(frozen=True, slots=True)
class ReportingOutputPolicy:
    """限定 Reporting 工具唯一允许写入的相对目录。"""

    roots: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized: list[str] = []
        for root in self.roots:
            value = WorkspaceService.normalize_path(root, allow_root=False)[0].rstrip("/")
            if value not in normalized:
                normalized.append(value)
        if not normalized:
            raise ValueError("Reporting 输出目录不能为空。")
        object.__setattr__(self, "roots", tuple(normalized))

    def allows(self, path: str) -> bool:
        normalized = WorkspaceService.normalize_path(path, allow_root=False)[0]
        return any(normalized == root or normalized.startswith(f"{root}/") for root in self.roots)


@dataclass(frozen=True, slots=True)
class ReportingToolContext:
    """工具核心可消费的已校验快照，不持有可变 session 或 I/O 客户端。"""

    external_run_id: str
    thread_id: str
    attempt_no: int
    output_policy: ReportingOutputPolicy
    input_snapshot: Mapping[str, Any]
    inputs: tuple[ReportingFileRef, ...] = ()
    data: tuple[ReportingFileRef, ...] = ()

    def __post_init__(self) -> None:
        if not self.external_run_id or not self.thread_id:
            raise ValueError("Reporting 运行绑定不能为空。")
        if isinstance(self.attempt_no, bool) or self.attempt_no < 1:
            raise ValueError("Reporting attempt_no 无效。")
        object.__setattr__(self, "input_snapshot", _freeze(self.input_snapshot))
