"""可视化章节的固定执行链。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from agno.run import RunContext
from loguru import logger

from ....model_routing import TaskComplexity
from ...model_policy import ThinkingRequest, bind_reporting_thinking, select_reporting_thinking
from ...models import ReportingError
from ...phase import bounded_python_script_diagnostic, reporting_python_script_failed
from ..checkpoint import ChartVisualInspectionReceipt, FileIdentity
from .code_generation import CodeGenerationResult, _code_failure_kind
from .phase_models import ChartDraft, VisualizationPlanDraft

GenerateVisualizationPlan = Callable[
    [Mapping[str, Any], RunContext], Awaitable[VisualizationPlanDraft]
]


class GenerateVisualizationScript(Protocol):
    def __call__(
        self,
        plan: VisualizationPlanDraft,
        run_context: RunContext,
        /,
        *,
        diagnostic: Mapping[str, Any] | None,
    ) -> Awaitable[CodeGenerationResult]: ...


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
DegradeVisualization = Callable[[Exception, RunContext], Awaitable[Mapping[str, Any]]]
LoadScript = Callable[[str, RunContext], Awaitable[FileIdentity | None]]

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
_DEGRADABLE_CODES = frozenset(
    {
        "execution_output_error",
        "report_visualization_script_failed",
        "report_visualization_review_failed",
        "report_chart_file_missing",
    }
)


def _visualization_thinking_complexity(payload: Mapping[str, Any]) -> TaskComplexity:
    analysis_ids = payload.get("analysisIds")
    count = len(analysis_ids) if isinstance(analysis_ids, (list, tuple)) else 0
    if count <= 1:
        return "simple"
    if count <= 3:
        return "standard"
    return "complex"


def _signed_script_path(payload: Mapping[str, Any]) -> str:
    workspace = payload.get("visualizationWorkspace")
    script_path = workspace.get("scriptPath") if isinstance(workspace, Mapping) else None
    if not isinstance(script_path, str) or not script_path:
        raise ReportingError("report_phase_contract_invalid", "缺少可视化脚本签发路径。")
    return script_path


def _repair_diagnostic(
    plan: VisualizationPlanDraft, error: Exception, script_path: str
) -> dict[str, Any]:
    _ = plan
    code = error.code if isinstance(error, ReportingError) else "report_visualization_failed"
    path = script_path
    raw_details: Mapping[str, Any] = {}
    if isinstance(error, ReportingError) and isinstance(error.details, Mapping):
        nested = error.details.get("details")
        raw_details = {**error.details, **nested} if isinstance(nested, Mapping) else error.details
        candidate = raw_details.get("sourcePath", raw_details.get("path"))
        if isinstance(candidate, str) and candidate:
            path = candidate

    message = (
        error.message if isinstance(error, ReportingError) else "可视化固定 Workflow 执行失败。"
    )
    details: dict[str, Any] = {"path": path}
    for field in ("size", "lineCount", "maxLineLength", "exitCode"):
        value = raw_details.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            details[field] = value
    output = raw_details.get("output")
    if isinstance(output, str) and output:
        details["output"], diagnostic_output_truncated = bounded_python_script_diagnostic(
            output, 2000
        )
    else:
        diagnostic_output_truncated = False
    output_truncated = raw_details.get("outputTruncated")
    if isinstance(output_truncated, bool) or diagnostic_output_truncated:
        details["outputTruncated"] = bool(output_truncated is True or diagnostic_output_truncated)
    for field in ("toolCode", "toolMessage"):
        value = raw_details.get(field)
        if isinstance(value, str) and value:
            details[field] = value[:512]
    return {"code": code, "message": message[:512], "details": details}


def _repair_task_facts(
    plan: VisualizationPlanDraft, error: Exception, script_path: str
) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    code = error.code if isinstance(error, ReportingError) else "report_visualization_failed"
    path = script_path
    details = (
        error.details
        if isinstance(error, ReportingError) and isinstance(error.details, Mapping)
        else {}
    )
    nested_details = details.get("details")
    nested = nested_details if isinstance(nested_details, Mapping) else details
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


def _is_degradable(error: Exception) -> bool:
    return isinstance(error, ReportingError) and error.code in _DEGRADABLE_CODES


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
        degrade: DegradeVisualization | None = None,
        load_script: LoadScript | None = None,
        thinking_enabled: bool = True,
        thinking_budget_cap: int = 8192,
    ) -> None:
        self.generate_plan = generate_plan
        self.generate_script = generate_script
        self.repair_script = repair_script
        self.execute_script = execute_script
        self.inspect_chart = inspect_chart
        self.submit = submit
        self.degrade = degrade
        self.load_script = load_script
        self.thinking_enabled = thinking_enabled
        self.thinking_budget_cap = thinking_budget_cap

    async def run(
        self, payload: Mapping[str, Any], run_context: RunContext
    ) -> VisualizationWorkflowResult:
        plan = await self.generate_plan(payload, run_context)
        thinking_complexity = _visualization_thinking_complexity(payload)
        if not plan.charts:
            receipt = await self.submit(plan, (), run_context)
            _raise_rejected_submission(receipt)
            return VisualizationWorkflowResult("accepted", plan, None, ())

        script_path = _signed_script_path(payload)
        script_file = (
            await self.load_script(script_path, run_context)
            if self.load_script is not None
            else None
        )
        generation_failure: Exception | None = None
        if script_file is None:
            for generate_attempt in range(_MAX_GENERATE_ATTEMPTS):
                try:
                    diagnostic = (
                        _repair_diagnostic(plan, generation_failure, script_path)
                        if generation_failure is not None
                        else None
                    )
                    failure_kind = _code_failure_kind(diagnostic)
                    decision = select_reporting_thinking(
                        ThinkingRequest(
                            operation="visualization_script",
                            complexity=thinking_complexity,
                            attempt=1 if failure_kind is not None else 0,
                            failure_kind=failure_kind,
                            configured_budget_cap=self.thinking_budget_cap,
                            thinking_enabled=self.thinking_enabled,
                        )
                    )
                    with bind_reporting_thinking(decision):
                        generated = await self.generate_script(
                            plan,
                            run_context,
                            diagnostic=diagnostic,
                        )
                    script_file = _ensure_script_identity(generated, script_path)
                    break
                except Exception as error:
                    generation_failure = error
                    if _is_nonrecoverable(error) or generate_attempt == _MAX_GENERATE_ATTEMPTS - 1:
                        raise
        else:
            script_file = _ensure_script_identity(CodeGenerationResult(script_file), script_path)
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
                if attempt == 1:
                    if self.degrade is not None and _is_degradable(error):
                        receipt = await self.degrade(error, run_context)
                        _raise_rejected_submission(receipt)
                        return VisualizationWorkflowResult(
                            "degraded", plan, script_file, (), recovery_used
                        )
                    raise
                if self.repair_script is None:
                    raise
                recovery_used = True
                diagnostic = _repair_diagnostic(plan, error, script_path)
                failure_kind = _code_failure_kind(diagnostic)
                repair_decision = select_reporting_thinking(
                    ThinkingRequest(
                        operation="visualization_script",
                        complexity=thinking_complexity,
                        attempt=1 if failure_kind is not None else 0,
                        failure_kind=failure_kind,
                        configured_budget_cap=self.thinking_budget_cap,
                        thinking_enabled=self.thinking_enabled,
                    )
                )
                with bind_reporting_thinking(repair_decision):
                    repaired = await self.repair_script(
                        script_file,
                        diagnostic,
                        _repair_task_facts(plan, error, script_path),
                        run_context,
                    )
                script_file = _ensure_script_identity(repaired, script_path)

        raise RuntimeError("可视化固定 Workflow 状态不可达")


__all__ = ["VisualizationSectionWorkflow", "VisualizationWorkflowResult"]
