"""交互式 Coding Agent 的任务绑定与执行回执。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from ...workspace import WorkspaceService
from ..contract import StrictModel
from ..host_workspace import HostReportingWorkspace
from ..models import ReportingError
from ..workflow.checkpoint import ChartVisualInspectionReceipt, FileIdentity


def _normalized_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        sorted({WorkspaceService.normalize_path(path, allow_root=False)[0] for path in paths})
    )


@dataclass(frozen=True, slots=True)
class ReportingCodingTaskContext:
    task_id: str
    task_kind: Literal["analysis", "visualization"]
    code_mode_session_id: str
    workspace_key: str
    workspace_root: Path
    script_path: str
    authorized_read_paths: tuple[str, ...]
    authorized_write_paths: tuple[str, ...]
    declared_output_paths: tuple[str, ...]
    max_source_bytes: int

    def __post_init__(self) -> None:
        script_path = WorkspaceService.normalize_path(self.script_path, allow_root=False)[0]
        read_paths = _normalized_paths(self.authorized_read_paths)
        write_paths = _normalized_paths(self.authorized_write_paths)
        output_paths = _normalized_paths(self.declared_output_paths)
        if script_path not in write_paths:
            raise ValueError("script_path 必须属于 authorized_write_paths")
        if not set(output_paths).issubset(write_paths):
            raise ValueError("declared_output_paths 必须属于 authorized_write_paths")
        object.__setattr__(self, "workspace_root", Path(self.workspace_root).resolve())
        object.__setattr__(self, "script_path", script_path)
        object.__setattr__(self, "authorized_read_paths", read_paths)
        object.__setattr__(self, "authorized_write_paths", write_paths)
        object.__setattr__(self, "declared_output_paths", output_paths)


class ExecutionReceipt(StrictModel):
    run_id: str = Field(alias="runId", min_length=1, max_length=128)
    source_file: FileIdentity = Field(alias="sourceFile")
    output_files: tuple[FileIdentity, ...] = Field(alias="outputFiles", max_length=100)


@dataclass(slots=True)
class ReportingCodingTaskBinding:
    context: ReportingCodingTaskContext
    workspace: HostReportingWorkspace
    execution_receipt: ExecutionReceipt | None = None
    visual_inspection_receipts: dict[str, ChartVisualInspectionReceipt] = field(
        default_factory=dict
    )
    visual_repair_diagnostic: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.context.workspace_key != self.workspace.identity.workspace_key:
            raise ReportingError(
                "report_coding_task_workspace_mismatch",
                "Coding task 与 Reporting Workspace 身份不一致。",
            )
        if self.context.workspace_root != self.workspace.identity.root.resolve():
            raise ReportingError(
                "report_coding_task_workspace_mismatch",
                "Coding task 与 Reporting Workspace 根目录不一致。",
            )

    def clear_execution_state(self) -> None:
        self.execution_receipt = None
        self.visual_inspection_receipts.clear()


class ReportingCodingTaskRegistry:
    """限制同一 task 或正式脚本同时只能存在一个活动绑定。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_task: dict[str, ReportingCodingTaskBinding] = {}
        self._by_script: dict[tuple[str, str], str] = {}

    @asynccontextmanager
    async def bind(
        self,
        context: ReportingCodingTaskContext,
        workspace: HostReportingWorkspace,
    ) -> AsyncIterator[ReportingCodingTaskBinding]:
        script_key = (context.workspace_key, context.script_path)
        async with self._lock:
            if context.task_id in self._by_task or script_key in self._by_script:
                raise ReportingError(
                    "report_coding_task_conflict",
                    "Coding task 与活动脚本冲突。",
                )
            binding = ReportingCodingTaskBinding(context, workspace)
            self._by_task[context.task_id] = binding
            self._by_script[script_key] = context.task_id
        try:
            yield binding
        finally:
            async with self._lock:
                self._by_task.pop(context.task_id, None)
                self._by_script.pop(script_key, None)

    @property
    def active_count(self) -> int:
        return len(self._by_task)


__all__ = [
    "ExecutionReceipt",
    "ReportingCodingTaskBinding",
    "ReportingCodingTaskContext",
    "ReportingCodingTaskRegistry",
]
