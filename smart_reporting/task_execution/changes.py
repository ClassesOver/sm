"""工作区文件变更原语的中立公共入口。"""

from .tools import abuild_workspace_changes, build_workspace_changes, parse_unified_diff

__all__ = [
    "abuild_workspace_changes",
    "build_workspace_changes",
    "parse_unified_diff",
]
