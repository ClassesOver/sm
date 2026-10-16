"""Reporting 工具访问工作区的最小端口。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .context import ReportingFileRef


class ReportingWorkspaceError(ValueError):
    """Reporting 工作区边界拒绝。"""


class ReportingWorkspacePort(Protocol):
    async def read_bytes(self, path: str) -> bytes: ...

    async def read_text(self, path: str) -> str: ...

    async def hash_files(self, paths: Sequence[str]) -> tuple[ReportingFileRef, ...]: ...

    async def write_text(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool = False,
        expected_sha256: str | None = None,
    ) -> ReportingFileRef: ...
