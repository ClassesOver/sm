"""可视化章节的固定执行链。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from agno.run import RunContext
from loguru import logger

from ...models import ReportingError
from ...phase import reporting_python_script_failed
from ..checkpoint import ChartVisualInspectionReceipt, FileIdentity
from .code_generation import CodeGenerationResult
from .phase_models import ChartDraft, VisualizationPlanDraft

GenerateVisualizationPlan = Callable[
    [Mapping[str, Any], RunContext], Awaitable[VisualizationPlanDraft]
]
GenerateVisualizationScript = Callable[
    [VisualizationPlanDraft, RunContext], Awaitable[CodeGenerationResult]
]
RepairVisualizationScript = Callable[
    [
        FileIdentity,
        Mapping[str, Any],
        Mapping[str, Any],
        RunContext,
    ],
    Awaitable[CodeGenerationResult],
]
ExecuteScript = Callable[[str, RunContext], Awaitable[Mapping[str, Any]]]
InspectChart = Callable[[ChartDraft, RunContext], Awaitable[ChartVisualInspectionReceipt]]
SubmitVisualization = Callable[
    [VisualizationPlanDraft, tuple[ChartVisualInspectionReceipt, ...], RunContext],
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
_MAX_GENERATE_ATTEMPTS = 3


def _signed_script_path(payload: Mapping[str, Any]) -> str:
    workspace = payload.get("visualizationWorkspace")
    script_path = workspace.get("scriptPath") if isinstance(workspace, Mapping) else None
    if not isinstance(script_path, str) or not script_path:
        raise ReportingError("report_phase_contract_invalid", "缺少可视化脚本签发路径。")
    return script_path


def _repair_diagnostic(
    plan: VisualizationPlanDraft, error: Exception, script_path: str
) -> dict[str, Any]:
    code = error.code if isinstance(error, ReportingError) else "report_visualization_failed"
    path = script_path
    if isinstance(error, ReportingError) and isinstance(error.details, Mapping):
        nested = error.details.get("details")
        details = nested if isinstance(nested, Mapping) else error.details
        candidate = details.get("sourcePath", details.get("path"))
        if isinstance(candidate, str) and candidate:
            path = candidate

    message = error.message if isinstance(error, ReportingError) else "可视化固定 Workflow 执行失败。"
    return {"code": code, "message": message, "details": {"path": path}}


def _repair_task_facts(
    plan: VisualizationPlanDraft, error: Exception, script_path: str
) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    code = error.code if isinstance(error, ReportingError) else "report_visualization_failed"
    path = script_path
    details = error.details if isinstance(error, ReportingError) and isinstance(error.details, Mapping) else {}
    nested = details.get("details") if isinstance(details.get("details"), Mapping) else details
    candidate = nested.get("sourcePath", nested.get("path"))
    if isinstance(candidate, str) and candidate:
        path = candidate

    if code == "report_chart_file_missing":
        facts["missingCharts"] = [
            {
                "chartId": chart.chart_id,
                "sourcePath": chart.source_path,
                "title": chart.title,
            }
            for chart in plan.charts
            if chart.source_path == path
        ]
    elif code == "report_visualization_review_failed":
        inspections = details.get("inspections")
        if isinstance(inspections, list):
            facts["inspections"] = [
                {
                    "sourcePath": inspection["sourcePath"],
                    "visualReviewStatus": inspection.get("visualReviewStatus"),
                    "requiresRevision": inspection.get("requiresRevision"),
                    "issues": inspection.get("issues", []),
                    "summary": inspection.get("summary"),
                    "warnings": inspection.get("warnings", []),
                    "suggestions": inspection.get("suggestions", []),
                }
                for inspection in inspections
                if isinstance(inspection, Mapping)
                and isinstance(inspection.get("sourcePath"), str)
                and (
                    inspection.get("requiresRevision") is True
                    or inspection.get("visualReviewStatus") != "passed"
                )
            ]
    return facts


def _is_nonrecoverable(error: Exception) -> bool:
    return isinstance(error, ReportingError) and (
        error.code in _NON_RECOVERABLE_CODES
        or (isinstance(error.details, Mapping) and error.details.get("retryable") is False)
    )


def _ensure_script_identity(result: CodeGenerationResult, script_path: str) -> FileIdentity:
    script_file = result.script_file
    if script_file.path != script_path:
        raise ReportingError(
            "report_phase_artifact_changed", "脚本回执路径与 Workflow 签发路径不一致。"
        )
    return script_file


def _raise_rejected_submission(receipt: Mapping[str, Any]) -> None:
    if receipt.get("status") in {"accepted", "committed", "already_committed"}:
        return
    rejection_code = receipt.get("code")
    code = (
        rejection_code
        if isinstance(rejection_code, str)
        else "report_visualization_submit_rejected"
    )
    message = receipt.get("message")
    logger.bind(rejection_code=code).warning("report_visualization_submission_rejected")
    raise ReportingError(
        code,
        message if isinstance(message, str) else "图表提交未被服务端接受。",
        details=dict(receipt),
    )


@dataclass(frozen=True, slots=True)
class VisualizationWorkflowResult:
    status: str
    plan: VisualizationPlanDraft
    script_file: FileIdentity | None
    inspections: tuple[ChartVisualInspectionReceipt, ...]
    recovery_used: bool = False


class VisualizationSectionWorkflow:
    """计划只生成一次；固定 Workflow 执行、审查并在必要时修复脚本一次。"""

    def __init__(
        self,
        *,
        generate_plan: GenerateVisualizationPlan,
        generate_script: GenerateVisualizationScript,
        repair_script: RepairVisualizationScript | None,
        execute_script: ExecuteScript,
        inspect_chart: InspectChart | None,
        submit: SubmitVisualization,
    ) -> None:
        self.generate_plan = generate_plan
        self.generate_script = generate_script
        self.repair_script = repair_script
        self.execute_script = execute_script
        self.inspect_chart = inspect_chart
        self.submit = submit

    async def run(
        self, payload: Mapping[str, Any], run_context: RunContext
    ) -> VisualizationWorkflowResult:
        plan = await self.generate_plan(payload, run_context)
        if not plan.charts:
            receipt = await self.submit(plan, (), run_context)
            _raise_rejected_submission(receipt)
            return VisualizationWorkflowResult("accepted", plan, None, ())

        script_path = _signed_script_path(payload)
        script_file: FileIdentity | None = None
        for generate_attempt in range(_MAX_GENERATE_ATTEMPTS):
            try:
                generated = await self.generate_script(plan, run_context)
                script_file = _ensure_script_identity(generated, script_path)
                break
            except Exception as error:
                if _is_nonrecoverable(error) or generate_attempt == _MAX_GENERATE_ATTEMPTS - 1:
                    raise
        if script_file is None:
            raise RuntimeError("可视化脚本生成状态不可达")
        recovery_used = False

        for attempt in range(2):
            try:
                execution = await self.execute_script(script_path, run_context)
                if reporting_python_script_failed(execution):
                    raise ReportingError(
                        "report_visualization_script_failed",
                        "可视化脚本执行失败。",
                        details=dict(execution),
                    )

                inspections: tuple[ChartVisualInspectionReceipt, ...] = ()
                if self.inspect_chart is not None:
                    inspections = tuple(
                        [await self.inspect_chart(chart, run_context) for chart in plan.charts]
                    )
                    if any(
                        receipt.source_path != chart.source_path
                        for chart, receipt in zip(plan.charts, inspections, strict=True)
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

                receipt = await self.submit(plan, inspections, run_context)
                _raise_rejected_submission(receipt)
                return VisualizationWorkflowResult(
                    "accepted", plan, script_file, inspections, recovery_used
                )
            except Exception as error:
                if _is_nonrecoverable(error):
                    raise
                if attempt == 1 or self.repair_script is None:
                    raise
                recovery_used = True
                repaired = await self.repair_script(
                    script_file,
                    _repair_diagnostic(plan, error, script_path),
                    _repair_task_facts(plan, error, script_path),
                    run_context,
                )
                script_file = _ensure_script_identity(repaired, script_path)

        raise RuntimeError("可视化固定 Workflow 状态不可达")


__all__ = ["VisualizationSectionWorkflow", "VisualizationWorkflowResult"]
