"""可视化章节的固定执行链。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from agno.run import RunContext

from ...models import ReportingError
from ...phase import reporting_python_script_failed
from ..checkpoint import ChartVisualInspectionReceipt, FileIdentity
from .phase_models import ChartDraft, VisualizationScriptDraft

GenerateVisualization = Callable[
    [Mapping[str, Any], RunContext], Awaitable[VisualizationScriptDraft]
]
RecoverVisualization = Callable[
    [Mapping[str, Any], RunContext], Awaitable[VisualizationScriptDraft]
]
WriteScript = Callable[[str, str, RunContext], Awaitable[FileIdentity]]
ExecuteScript = Callable[[str, RunContext], Awaitable[Mapping[str, Any]]]
InspectChart = Callable[[ChartDraft, RunContext], Awaitable[ChartVisualInspectionReceipt]]
SubmitVisualization = Callable[
    [VisualizationScriptDraft, tuple[ChartVisualInspectionReceipt, ...], RunContext],
    Awaitable[Mapping[str, Any]],
]

_NON_RECOVERABLE_CODES = frozenset(
    {
        "report_phase_artifact_changed",
        "report_capability_invalid",
        "report_task_lease_conflict",
        "report_task_cancelled",
        "report_task_timeout",
        "report_workspace_unavailable",
    }
)


def _recovery_diagnostic(error: Exception) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {"message": str(error)[:2000]}
    if isinstance(error, ReportingError):
        diagnostic["code"] = error.code
        if isinstance(error.details, Mapping):
            diagnostic["details"] = dict(error.details)
    return diagnostic


@dataclass(frozen=True, slots=True)
class VisualizationWorkflowResult:
    status: str
    draft: VisualizationScriptDraft
    script_file: FileIdentity
    inspections: tuple[ChartVisualInspectionReceipt, ...]
    recovery_used: bool = False


class VisualizationSectionWorkflow:
    """生成、执行、审查、提交的单向流程；内容错误最多恢复一次。"""

    def __init__(
        self,
        *,
        generate: GenerateVisualization,
        recover: RecoverVisualization | None,
        write_script: WriteScript,
        execute_script: ExecuteScript,
        inspect_chart: InspectChart | None,
        submit: SubmitVisualization,
    ) -> None:
        self.generate = generate
        self.recover = recover
        self.write_script = write_script
        self.execute_script = execute_script
        self.inspect_chart = inspect_chart
        self.submit = submit

    async def run(
        self, payload: Mapping[str, Any], run_context: RunContext
    ) -> VisualizationWorkflowResult:
        draft: VisualizationScriptDraft | None = None
        script_file: FileIdentity | None = None
        written_script: tuple[str, str] | None = None
        recovery_used = False
        for attempt in range(2):
            try:
                if draft is None:
                    draft = await self.generate(payload, run_context)
                normalized_source = (
                    draft.python_source
                    if draft.python_source.endswith("\n")
                    else f"{draft.python_source}\n"
                )
                current_script = (draft.script_path, normalized_source)
                if current_script != written_script:
                    script_file = await self.write_script(
                        draft.script_path, normalized_source, run_context
                    )
                    if script_file.path != draft.script_path:
                        raise ReportingError(
                            "report_phase_artifact_changed",
                            "脚本写入回执路径与签发路径不一致。",
                        )
                    written_script = current_script
                # 恢复模型可能确认原脚本无需修改。相同源码再次生成 unified diff 会得到
                # 空字符串并被写入 schema 拒绝；已提交身份仍受后续执行和图表审查约束，
                # 因此复用该身份继续执行，而不是伪造一次无变化 mutation。
                if script_file is None:
                    raise ReportingError(
                        "report_visualization_write_failed", "章节图表脚本尚未成功写入。"
                    )
                execution = await self.execute_script(draft.script_path, run_context)
                if reporting_python_script_failed(execution):
                    raise ReportingError(
                        "report_visualization_script_failed",
                        "可视化脚本执行失败。",
                        details=dict(execution),
                    )
                inspections: tuple[ChartVisualInspectionReceipt, ...] = ()
                if self.inspect_chart is not None:
                    inspections = tuple(
                        [await self.inspect_chart(chart, run_context) for chart in draft.charts]
                    )
                    if any(
                        receipt.source_path != chart.source_path
                        for chart, receipt in zip(draft.charts, inspections, strict=True)
                    ):
                        raise ReportingError(
                            "report_phase_artifact_changed",
                            "图表审查回执与签发图表路径不一致。",
                        )
                    if any(
                        item.requires_revision or item.visual_review_status != "passed"
                        for item in inspections
                    ):
                        raise ReportingError(
                            "report_visualization_review_failed",
                            "图表正式审查未通过。",
                            details={
                                "inspections": [
                                    item.model_dump(mode="json", by_alias=True)
                                    for item in inspections
                                ]
                            },
                        )
                receipt = await self.submit(draft, inspections, run_context)
                if receipt.get("status") not in {"accepted", "committed", "already_committed"}:
                    raise ReportingError(
                        "report_visualization_submit_rejected",
                        "图表提交未被服务端接受。",
                        details=dict(receipt),
                    )
                return VisualizationWorkflowResult(
                    "accepted", draft, script_file, inspections, recovery_used
                )
            except Exception as error:
                if isinstance(error, ReportingError) and error.code in _NON_RECOVERABLE_CODES:
                    raise
                if attempt == 1 or self.recover is None:
                    raise
                recovery_used = True
                repair: dict[str, Any] = {"diagnostic": _recovery_diagnostic(error)}
                if draft is not None:
                    repair["draft"] = draft.model_dump(mode="json", by_alias=True)
                draft = await self.recover(
                    repair,
                    run_context,
                )
        raise RuntimeError("可视化固定 Workflow 状态不可达")


__all__ = ["VisualizationSectionWorkflow", "VisualizationWorkflowResult"]
