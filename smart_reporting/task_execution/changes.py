"""工作区文件变更原语的中立公共入口。"""

from .execution import create_files_patch
from .tools import abuild_workspace_changes, build_workspace_changes, parse_unified_diff

__all__ = [
    "abuild_workspace_changes",
    "build_workspace_changes",
    "create_files_patch",
    "parse_unified_diff",
]
