"""编辑器会话能力：把持久化的能力字典一次性解析为显式类型。

持久化格式保持不变：``None``（数据库 NULL）表示完整 editor 会话（向后兼容旧会话结构），
分享会话在签发时写入受限能力字典。检查点只读取本类型的属性，不再各自解释 ``None``。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EditorCapabilities:
    full: bool
    blocked_columns: frozenset[str] = frozenset()
    download_original: bool = False
    download_derived: bool = False
    drilldown: bool = False

    @property
    def restricted(self) -> bool:
        return not self.full

    @classmethod
    def of(cls, value: EditorCapabilities | Mapping[str, Any] | None) -> EditorCapabilities:
        if isinstance(value, cls):
            return value
        if value is None:
            return FULL_EDITOR_CAPABILITIES
        return cls(
            full=False,
            blocked_columns=frozenset(str(item) for item in value.get("blocked_columns") or ()),
            download_original=bool(value.get("download_original", False)),
            download_derived=bool(value.get("download_derived", False)),
            drilldown=bool(value.get("drilldown", False)),
        )


FULL_EDITOR_CAPABILITIES = EditorCapabilities(
    full=True, download_original=True, download_derived=True, drilldown=True
)
