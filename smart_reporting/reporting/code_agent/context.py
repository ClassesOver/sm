"""交互式 Coding Agent 的任务绑定与执行回执。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
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


OutputValidationStatus = Literal[
    "not_checked", "checking", "not_required", "passed", "failed", "unavailable"
]


@dataclass(frozen=True, slots=True)
class OutputValidationState:
    """预检结果只对指定执行回执有效；没有失败记录不等于已经通过。

    状态是唯一事实来源：``run_id`` 必须指向当前执行回执。旧结果本身不再作为
    当前诊断，但也不能充当当前执行的通过结论。
    """

    status: OutputValidationStatus = "not_checked"
    run_id: str | None = None
    diagnostic: dict[str, Any] | None = None

    @property
    def blocking(self) -> bool:
        """预检尚未给出可用结论时，提交必须被阻塞。"""

        return self.status in {"failed", "unavailable", "checking"}

    def current_diagnostic(self, run_id: str | None) -> dict[str, Any] | None:
        """返回仍然对 ``run_id`` 生效的阻塞诊断，否则返回 None。

        ``checking`` 之类没有携带诊断的中间态也必须返回可展示的阻塞原因，
        否则调用方按 ``None`` 判空就会把未完成的校验当成通过。
        """

        if run_id is None or self.run_id != run_id or not self.blocking:
            return None
        return self.diagnostic if self.diagnostic is not None else dict(OUTPUT_VALIDATION_UNAVAILABLE)

    @classmethod
    def for_run(
        cls,
        status: OutputValidationStatus,
        run_id: str | None,
        diagnostic: Mapping[str, Any] | None = None,
    ) -> OutputValidationState:
        return cls(
            status=status,
            run_id=run_id,
            diagnostic=dict(diagnostic) if diagnostic is not None else None,
        )


#: 预检未能给出结论（抛错）时的诊断；此时必须阻塞提交而不是放行。
OUTPUT_VALIDATION_UNAVAILABLE: dict[str, Any] = {
    "ok": False,
    "code": "report_code_output_validation_unavailable",
    "message": "输出结构预检不可用；请重新执行脚本后再提交。",
}


@dataclass(slots=True)
class ReportingCodingTaskBinding:
    context: ReportingCodingTaskContext
    workspace: HostReportingWorkspace
    execution_receipt: ExecutionReceipt | None = None
    output_validation: OutputValidationState = field(default_factory=OutputValidationState)
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
        self.clear_execution_receipt()
        self.visual_inspection_receipts.clear()

    def clear_execution_receipt(self) -> None:
        """源码变更只失效执行回执；视觉回执由下次执行按内容哈希过滤。"""
        self.execution_receipt = None
        self.output_validation = OutputValidationState()


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
    "OUTPUT_VALIDATION_UNAVAILABLE",
    "OutputValidationState",
    "OutputValidationStatus",
    "ReportingCodingTaskBinding",
    "ReportingCodingTaskContext",
    "ReportingCodingTaskRegistry",
]
