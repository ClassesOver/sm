"""Reporting 工作区端口的确定性内存实现，仅供测试。"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from ...workspace import WorkspaceError, WorkspaceService
from .context import ReportingFileRef, ReportingOutputPolicy, ReportingToolContext
from .workspace_port import ReportingWorkspaceError


class MockReportingWorkspace:
    def __init__(
        self,
        *,
        inputs: Mapping[str, bytes] | None = None,
        data: Mapping[str, bytes] | None = None,
        output_policy: ReportingOutputPolicy,
    ) -> None:
        self._readonly = {
            self._normalize(path): bytes(content)
            for source in (inputs or {}, data or {})
            for path, content in source.items()
        }
        self._outputs: dict[str, bytes] = {}
        self.output_policy = output_policy
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _normalize(path: str) -> str:
        try:
            return WorkspaceService.normalize_path(path, allow_root=False)[0]
        except WorkspaceError as error:
            raise ReportingWorkspaceError("Reporting 路径无效。") from error

    @staticmethod
    def _identity(path: str, content: bytes) -> ReportingFileRef:
        return ReportingFileRef(
            path=path,
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )

    async def read_bytes(self, path: str) -> bytes:
        normalized = self._normalize(path)
        self.calls.append({"operation": "read_bytes", "path": normalized})
        if normalized in self._outputs:
            return self._outputs[normalized]
        try:
            return self._readonly[normalized]
        except KeyError as error:
            raise ReportingWorkspaceError("Reporting 文件不存在。") from error

    async def read_text(self, path: str) -> str:
        return (await self.read_bytes(path)).decode("utf-8")

    async def hash_files(self, paths: Sequence[str]) -> tuple[ReportingFileRef, ...]:
        identities: list[ReportingFileRef] = []
        for path in paths:
            normalized = self._normalize(path)
            content = await self.read_bytes(normalized)
            identities.append(self._identity(normalized, content))
        return tuple(identities)

    async def write_text(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool = False,
        expected_sha256: str | None = None,
    ) -> ReportingFileRef:
        normalized = self._normalize(path)
        if normalized in self._readonly:
            raise ReportingWorkspaceError("Reporting 输入和数据只读。")
        if not self.output_policy.allows(normalized):
            raise ReportingWorkspaceError("Reporting 写入目标不在输出目录。")
        current = self._outputs.get(normalized)
        if current is not None and not overwrite:
            raise ReportingWorkspaceError("Reporting 输出文件已存在。")
        if overwrite and current is None:
            raise ReportingWorkspaceError("Reporting 覆盖目标不存在。")
        if current is not None and expected_sha256 != hashlib.sha256(current).hexdigest():
            raise ReportingWorkspaceError("Reporting 输出文件哈希已变化。")
        raw = content.encode("utf-8")
        self._outputs[normalized] = raw
        self.calls.append({"operation": "write_text", "path": normalized, "overwrite": overwrite})
        return self._identity(normalized, raw)

    async def execute_script(
        self,
        script_path: str,
        *,
        timeout: int,
    ) -> Mapping[str, Any]:
        if timeout < 1:
            raise ReportingWorkspaceError("Reporting 脚本执行超时。")
        self.calls.append(
            {"operation": "execute_script", "script_path": script_path, "timeout": timeout}
        )
        return {"ok": True, "status": "completed", "exitCode": 0, "exit_code": 0}


class MockReportingToolRuntime:
    """为单个测试 case 绑定不可变 context 与独立内存工作区。"""

    def __init__(
        self,
        *,
        input_snapshot: Mapping[str, Any],
        inputs: Mapping[str, bytes] | None = None,
        data: Mapping[str, bytes] | None = None,
        output_policy: ReportingOutputPolicy,
        external_run_id: str = "report-run-1",
        thread_id: str = "thread-1",
        attempt_no: int = 1,
    ) -> None:
        input_files = dict(inputs or {})
        data_files = dict(data or {})
        self.context = ReportingToolContext(
            external_run_id=external_run_id,
            thread_id=thread_id,
            attempt_no=attempt_no,
            output_policy=output_policy,
            input_snapshot=input_snapshot,
            inputs=tuple(
                MockReportingWorkspace._identity(MockReportingWorkspace._normalize(path), content)
                for path, content in input_files.items()
            ),
            data=tuple(
                MockReportingWorkspace._identity(MockReportingWorkspace._normalize(path), content)
                for path, content in data_files.items()
            ),
        )
        self.workspace = MockReportingWorkspace(
            inputs=input_files,
            data=data_files,
            output_policy=output_policy,
        )

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.workspace.calls
