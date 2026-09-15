"""可视化章节的固定执行链。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from agno.run import RunContext
from loguru import logger

from ....model_routing import TaskComplexity
from ...model_policy import ThinkingRequest, bind_reporting_thinking, select_reporting_thinking
from ...models import ReportingError
from ...phase import bounded_python_script_diagnostic
from ..checkpoint import ChartVisualInspectionReceipt, FileIdentity
from .code_generation import (
    CodeGenerationResult,
    _bounded_forbidden_path_operations,
    _bounded_unsigned_paths,
    _code_failure_kind,
)
from .phase_models import ChartDraft, VisualizationPlanDraft

GenerateVisualizationPlan = Callable[
    [Mapping[str, Any], RunContext], Awaitable[VisualizationPlanDraft]
]


class RunVisualizationCode(Protocol):
    def __call__(
        self,
        plan: VisualizationPlanDraft,
        run_context: RunContext,
        /,
        *,
        diagnostic: Mapping[str, Any] | None,
        task_facts: Mapping[str, Any] | None = None,
    ) -> Awaitable[CodeGenerationResult]: ...


InspectChart = Callable[[ChartDraft, RunContext], Awaitable[ChartVisualInspectionReceipt]]
SubmitVisualization = Callable[
    [VisualizationPlanDraft, tuple[ChartVisualInspectionReceipt, ...], RunContext],
    Awaitable[Mapping[str, Any]],
]
DegradeVisualization = Callable[[Exception, RunContext], Awaitable[Mapping[str, Any]]]

_NON_RECOVERABLE_CODES = frozenset(
    {
        "report_phase_artifact_changed",
        "report_capability_invalid",
        "report_task_lease_conflict",
        "report_task_cancelled",
        "report_task_timeout",
        "report_workspace_unavailable",
        "report_coding_task_conflict",
        "report_code_mode_runtime_missing",
    }
)
_MAX_GENERATE_ATTEMPTS = 3
MAX_VISUALIZATION_EXECUTION_REPAIRS = 3
MAX_VISUALIZATION_REVIEW_REPAIRS = 3
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
    unsigned_paths = _bounded_unsigned_paths(raw_details.get("unsignedPaths"))
    if unsigned_paths:
        details["unsignedPaths"] = unsigned_paths
    forbidden_operations = _bounded_forbidden_path_operations(
        raw_details.get("forbiddenPathOperations")
    )
    if forbidden_operations:
        details["forbiddenPathOperations"] = forbidden_operations
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
    if raw_details.get("repairUnchanged") is True:
        details["repairUnchanged"] = True
    sha256 = raw_details.get("sha256")
    if isinstance(sha256, str) and sha256:
        details["sha256"] = sha256[:64]
    return {"code": code, "message": message[:512], "details": details}


def _visualization_data_contract(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    projected_metrics: list[dict[str, Any]] = []
    visualization_facts = payload.get("visualizationFacts")
    if not isinstance(visualization_facts, (list, tuple)):
        return None
    for analysis in visualization_facts:
        if not isinstance(analysis, Mapping):
            continue
        analysis_id = analysis.get("analysisId")
        metrics = analysis.get("metrics")
        if not isinstance(analysis_id, str) or not analysis_id or not isinstance(metrics, list):
            continue
        for metric in metrics:
            if not isinstance(metric, Mapping):
                continue
            data_paths = metric.get("dataPaths")
            required_values = (
                metric.get("metricIndex"),
                metric.get("field"),
                metric.get("periodValueCount"),
                metric.get("topGroupCount"),
                metric.get("bottomGroupCount"),
            )
            if not isinstance(data_paths, Mapping) or any(value is None for value in required_values):
                continue
            projected_metrics.append(
                {
                    "analysisId": analysis_id,
                    "metricIndex": metric.get("metricIndex"),
                    "field": metric.get("field"),
                    "periodValueCount": metric.get("periodValueCount"),
                    "topGroupCount": metric.get("topGroupCount"),
                    "bottomGroupCount": metric.get("bottomGroupCount"),
                    "dataPaths": dict(data_paths),
                }
            )
    if not projected_metrics:
        return None
    return {
        "groupAlignmentPolicy": "metric_local_only",
        "metrics": projected_metrics,
    }


def _repair_task_facts(
    plan: VisualizationPlanDraft,
    error: Exception,
    script_path: str,
    *,
    payload: Mapping[str, Any],
    repair_attempt: int,
) -> dict[str, Any]:
    facts: dict[str, Any] = {"repairAttempt": repair_attempt}
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
    elif code in {"execution_output_error", "report_visualization_script_failed"}:
        data_contract = _visualization_data_contract(payload)
        if data_contract is not None:
            facts["visualizationDataContract"] = data_contract
    return facts


def _is_nonrecoverable(error: Exception) -> bool:
    return isinstance(error, ReportingError) and (
        error.code in _NON_RECOVERABLE_CODES
        or (isinstance(error.details, Mapping) and error.details.get("retryable") is False)
    )


def _is_degradable(error: Exception) -> bool:
    return isinstance(error, ReportingError) and error.code in _DEGRADABLE_CODES


def _with_repair_counts(
    error: Exception, *, execution_repairs: int, visual_review_repairs: int
) -> Exception:
    if not isinstance(error, ReportingError):
        return error
    details = dict(error.details) if isinstance(error.details, Mapping) else {}
    details.update(
        {
            "executionRepairCount": execution_repairs,
            "visualReviewRepairCount": visual_review_repairs,
        }
    )
    return ReportingError(error.code, error.message, details=details)


def _with_unchanged_repair(error: Exception, *, script_file: FileIdentity) -> ReportingError:
    """保留原始失败分类，只追加本次修复没有改变源码的诊断。"""

    code = error.code if isinstance(error, ReportingError) else "report_visualization_failed"
    message = error.message if isinstance(error, ReportingError) else str(error)
    details = dict(error.details) if isinstance(error, ReportingError) and isinstance(
        error.details, Mapping
    ) else {}
    details.update(
        {
            "path": script_file.path,
            "repairUnchanged": True,
            "sha256": script_file.sha256,
        }
    )
    return ReportingError(code, message, details=details)


def _visual_review_issue_summary(
    inspections: tuple[ChartVisualInspectionReceipt, ...],
) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for inspection in inspections:
        if not inspection.requires_revision and inspection.visual_review_status == "passed":
            continue
        if not inspection.issues:
            summary.append(
                {
                    "sourcePath": inspection.source_path,
                    "category": "unknown",
                    "severity": "critical",
                    "description": (inspection.summary or "视觉审查状态未通过。")[:500],
                }
            )
        for issue in inspection.issues:
            summary.append(
                {
                    "sourcePath": inspection.source_path,
                    "category": issue.category,
                    "severity": issue.severity,
                    "description": issue.description[:500],
                }
            )
            if len(summary) >= 20:
                return summary
    return summary


def _ensure_script_identity(result: CodeGenerationResult, script_path: str) -> FileIdentity:
    script_file = result.script_file
    if script_file.path != script_path or script_file != result.execution_receipt.source_file:
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
    """计划只生成一次；固定 Workflow 独立限制执行修复与视觉审查修复。"""

    def __init__(
        self,
        *,
        generate_plan: GenerateVisualizationPlan,
        run_code: RunVisualizationCode,
        inspect_chart: InspectChart | None,
        submit: SubmitVisualization,
        degrade: DegradeVisualization | None = None,
        thinking_enabled: bool = True,
        thinking_budget_cap: int = 8192,
    ) -> None:
        self.generate_plan = generate_plan
        self.run_code = run_code
        self.inspect_chart = inspect_chart
        self.submit = submit
        self.degrade = degrade
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
        script_file: FileIdentity | None = None
        generation_failure: Exception | None = None
        generated_result: CodeGenerationResult | None = None
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
                    generated_result = await self.run_code(
                        plan,
                        run_context,
                        diagnostic=diagnostic,
                    )
                script_file = _ensure_script_identity(generated_result, script_path)
                break
            except Exception as error:
                generation_failure = error
                if _is_nonrecoverable(error) or generate_attempt == _MAX_GENERATE_ATTEMPTS - 1:
                    raise
        if script_file is None:
            raise RuntimeError("可视化脚本生成状态不可达")
        if generated_result is None:
            raise RuntimeError("可视化执行回执状态不可达")
        output_paths = {item.path for item in generated_result.execution_receipt.output_files}
        if any(chart.source_path not in output_paths for chart in plan.charts):
            raise ReportingError(
                "report_phase_artifact_changed",
                "图表路径不在 Coding Agent 签发输出中。",
            )
        recovery_used = False
        execution_repairs = 0
        visual_review_repairs = 0
        pending_repair_error: Exception | None = None

        while True:
            try:
                if pending_repair_error is not None:
                    error = pending_repair_error
                    pending_repair_error = None
                    raise error
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
                    signed_outputs = {
                        item.path: item for item in generated_result.execution_receipt.output_files
                    }
                    if any(
                        signed_outputs.get(item.source_path) is None
                        or signed_outputs[item.source_path].sha256 != item.sha256
                        for item in inspections
                    ):
                        raise ReportingError(
                            "report_phase_artifact_changed",
                            "图表当前身份与 Coding Agent 签发回执不一致。",
                        )
                    if any(
                        item.requires_revision or item.visual_review_status != "passed"
                        for item in inspections
                    ):
                        logger.warning(
                            "report_visualization_review_failed issues={}",
                            json.dumps(
                                _visual_review_issue_summary(inspections),
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        )
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
                if not _is_degradable(error):
                    raise
                is_visual_review_failure = (
                    isinstance(error, ReportingError)
                    and error.code == "report_visualization_review_failed"
                )
                repair_count = (
                    visual_review_repairs if is_visual_review_failure else execution_repairs
                )
                repair_limit = (
                    MAX_VISUALIZATION_REVIEW_REPAIRS
                    if is_visual_review_failure
                    else MAX_VISUALIZATION_EXECUTION_REPAIRS
                )
                if repair_count >= repair_limit:
                    exhausted_error = _with_repair_counts(
                        error,
                        execution_repairs=execution_repairs,
                        visual_review_repairs=visual_review_repairs,
                    )
                    if self.degrade is not None and _is_degradable(error):
                        receipt = await self.degrade(exhausted_error, run_context)
                        _raise_rejected_submission(receipt)
                        return VisualizationWorkflowResult(
                            "degraded", plan, script_file, (), recovery_used
                        )
                    raise exhausted_error
                if is_visual_review_failure:
                    visual_review_repairs += 1
                else:
                    execution_repairs += 1
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
                    repaired = await self.run_code(
                        plan,
                        run_context,
                        diagnostic=diagnostic,
                        task_facts=_repair_task_facts(
                            plan,
                            error,
                            script_path,
                            payload=payload,
                            repair_attempt=(
                                visual_review_repairs
                                if is_visual_review_failure
                                else execution_repairs
                            ),
                        ),
                    )
                repaired_file = _ensure_script_identity(repaired, script_path)
                generated_result = repaired
                repaired_outputs = {
                    item.path for item in repaired.execution_receipt.output_files
                }
                if any(chart.source_path not in repaired_outputs for chart in plan.charts):
                    raise ReportingError(
                        "report_phase_artifact_changed",
                        "图表路径不在 Coding Agent 签发输出中。",
                    )
                if repaired_file.sha256 == script_file.sha256:
                    pending_repair_error = _with_unchanged_repair(
                        error, script_file=script_file
                    )
                    logger.warning(
                        "report_visualization_script_repair_unchanged path={} sha256={} "
                        "execution_repairs={} visual_review_repairs={}",
                        script_path,
                        script_file.sha256,
                        execution_repairs,
                        visual_review_repairs,
                    )
                else:
                    script_file = repaired_file

        raise RuntimeError("可视化固定 Workflow 状态不可达")


__all__ = [
    "MAX_VISUALIZATION_EXECUTION_REPAIRS",
    "MAX_VISUALIZATION_REVIEW_REPAIRS",
    "VisualizationSectionWorkflow",
    "VisualizationWorkflowResult",
]
