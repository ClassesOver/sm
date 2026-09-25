"""可视化章节的固定执行链。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from agno.run import RunContext
from loguru import logger

from ....model_routing import TaskComplexity
from ...code_agent.failure_policy import recovery_for
from ...model_policy import ThinkingRequest, bind_reporting_thinking, select_reporting_thinking
from ...models import ReportingError
from ...phase import bounded_python_script_diagnostic
from ..benchmark_variants import BenchmarkProjection
from ..checkpoint import ChartVisualInspectionReceipt, FileIdentity
from .code_generation import (
    CodeGenerationResult,
    _bounded_forbidden_path_operations,
    _bounded_unsigned_paths,
    _code_failure_kind,
)
from .phase_models import ChartDataBinding, ChartDraft, VisualizationPlanDraft

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
        benchmark_projection: BenchmarkProjection | None = None,
    ) -> Awaitable[CodeGenerationResult]: ...


SubmitVisualization = Callable[
    [VisualizationPlanDraft, tuple[ChartVisualInspectionReceipt, ...], RunContext],
    Awaitable[Mapping[str, Any]],
]
DegradeVisualization = Callable[[Exception, RunContext], Awaitable[Mapping[str, Any]]]

_MAX_GENERATE_ATTEMPTS = 3
MAX_VISUALIZATION_EXECUTION_REPAIRS = 3


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


def _visualization_binding_catalog(
    payload: Mapping[str, Any],
) -> dict[tuple[str, str, str], frozenset[str]]:
    facts = payload.get("visualizationFacts")
    if not isinstance(facts, (list, tuple)):
        return {}
    catalog: dict[tuple[str, str, str], frozenset[str]] = {}

    def register(
        analysis_id: object, source_file: object, descriptors: object
    ) -> None:
        path = source_file.get("path") if isinstance(source_file, Mapping) else None
        if (
            not isinstance(analysis_id, str)
            or not analysis_id
            or not isinstance(path, str)
            or not path
            or not isinstance(descriptors, (list, tuple))
        ):
            return
        for descriptor in descriptors:
            if not isinstance(descriptor, Mapping):
                continue
            data_path = descriptor.get("dataPath")
            fields = descriptor.get("fields")
            if (
                not isinstance(data_path, str)
                or not data_path
                or not isinstance(fields, (list, tuple))
                or not fields
                or any(not isinstance(field, str) or not field for field in fields)
            ):
                continue
            key = (analysis_id, path, data_path)
            declared_fields = frozenset(fields)
            if key in catalog and catalog[key] != declared_fields:
                raise ReportingError(
                    "report_phase_contract_invalid",
                    "可视化事实包含冲突的数据绑定描述。",
                )
            catalog[key] = declared_fields

    for analysis in facts:
        if not isinstance(analysis, Mapping):
            continue
        analysis_id = analysis.get("analysisId")
        register(analysis_id, analysis.get("factFile"), analysis.get("dataDescriptors"))
        sources = analysis.get("supplementalEvidenceSources")
        if not isinstance(sources, (list, tuple)):
            continue
        for source in sources:
            if isinstance(source, Mapping):
                register(
                    analysis_id,
                    source.get("sourceFile"),
                    source.get("dataDescriptors"),
                )
    return catalog


def _validate_visualization_plan_bindings(
    plan: VisualizationPlanDraft, payload: Mapping[str, Any]
) -> VisualizationPlanDraft:
    catalog = _visualization_binding_catalog(payload)
    by_analysis: dict[Any, list[tuple[str, str, frozenset[str]]]] = {}
    for (analysis_id, path, data_path), fields in catalog.items():
        by_analysis.setdefault(analysis_id, []).append((path, data_path, fields))
    corrected_charts: list[ChartDraft] = []
    plan_corrected = False
    for chart in plan.charts:
        corrected_bindings: list[ChartDataBinding] = []
        chart_corrected = False
        for binding in chart.data_bindings:
            key = (binding.analysis_id, binding.fact_path, binding.data_path)
            declared_fields = catalog.get(key)
            if declared_fields is not None and set(binding.fields).issubset(declared_fields):
                corrected_bindings.append(binding)
                continue
            # 生产实证（cli-report-e556f25b 复盘）：planner 可能把 supplement 形状的
            # dataPath（如 findings[1].rows）签到 facts 文件上，模型照计划执行必然
            # KeyError。字段集合在该 analysisId 的签发描述中唯一匹配时自动改指；
            # 否则按结构错误终止本 Task，由报告级 fresh attempt 携错误上下文重签。
            binding_fields = frozenset(binding.fields)
            candidates = [
                (path, data_path)
                for path, data_path, fields in by_analysis.get(binding.analysis_id, ())
                if binding_fields and binding_fields == set(fields)
            ]
            if len(candidates) == 1:
                corrected_path, corrected_data_path = candidates[0]
                logger.bind(
                    chart_id=chart.chart_id,
                    analysis_id=binding.analysis_id,
                    fact_path=binding.fact_path,
                    corrected_fact_path=corrected_path,
                    data_path=binding.data_path,
                    corrected_data_path=corrected_data_path,
                ).warning(
                    "report_visualization_binding_autocorrected chart_id={} "
                    "dataPath={} -> {} 字段唯一匹配，自动改指。",
                    chart.chart_id,
                    binding.data_path,
                    corrected_data_path,
                )
                corrected_bindings.append(
                    binding.model_copy(
                        update={"fact_path": corrected_path, "data_path": corrected_data_path}
                    )
                )
                chart_corrected = True
                continue
            mismatched = {
                "chartId": chart.chart_id,
                "analysisId": binding.analysis_id,
                "factPath": binding.fact_path,
                "dataPath": binding.data_path,
                "fields": list(binding.fields),
                "declaredFields": (
                    sorted(declared_fields) if declared_fields is not None else None
                ),
                "availableDescriptors": [
                    {"factPath": path, "dataPath": data_path, "fields": sorted(fields)}
                    for path, data_path, fields in by_analysis.get(
                        binding.analysis_id, ()
                    )[:20]
                ],
            }
            # 2026-09-25 生产三跑实证：不可唯一修正的错配按软告警继续（AGENTS.md
            # "语义业务校验只需要软告警"）。硬拒会把 planner 的同一形态错配放大成
            # fresh attempt 循环耗尽；执行层 AST/指令/修复回执已可兜底。
            logger.bind(details=mismatched).warning(
                "report_visualization_binding_mismatch details={} "
                "图表数据绑定未逐字引用本轮签发的事实描述，继续执行。",
                mismatched,
            )
            corrected_bindings.append(binding)
        if chart_corrected:
            plan_corrected = True
            corrected_charts.append(
                chart.model_copy(update={"data_bindings": tuple(corrected_bindings)})
            )
        else:
            corrected_charts.append(chart)
    if plan_corrected:
        return plan.model_copy(update={"charts": tuple(corrected_charts)})
    return plan


def _repair_diagnostic(
    plan: VisualizationPlanDraft, error: Exception, script_path: str
) -> dict[str, Any]:
    _ = plan
    code = error.code if isinstance(error, ReportingError) else "report_visualization_failed"
    path = script_path
    raw_details: Mapping[str, Any] = {}
    if isinstance(error, ReportingError) and isinstance(error.details, Mapping):
        nested = error.details.get("details")
        last_failure = error.details.get("lastFailure")
        failure_details = (
            last_failure.get("details") if isinstance(last_failure, Mapping) else None
        )
        raw_details = {
            **error.details,
            **(nested if isinstance(nested, Mapping) else {}),
            **(failure_details if isinstance(failure_details, Mapping) else {}),
        }
        if isinstance(last_failure, Mapping):
            raw_details = {
                **raw_details,
                "toolCode": last_failure.get("code"),
                "toolMessage": last_failure.get("message"),
            }
        # pendingOutputValidation 反映当前仍在阻塞提交的真实原因；lastFailure 可能
        # 已被之后一次无关的探索失败覆盖，所以这里优先于（覆盖）lastFailure 的推断。
        pending_validation = error.details.get("pendingOutputValidation")
        if isinstance(pending_validation, Mapping):
            pending_details = pending_validation.get("details")
            raw_details = {
                **raw_details,
                **(pending_details if isinstance(pending_details, Mapping) else {}),
                "toolCode": pending_validation.get("code"),
                "toolMessage": pending_validation.get("message"),
            }
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
    for field in ("traceback", "stderr", "stdout"):
        value = raw_details.get(field)
        if isinstance(value, str) and value:
            details[field], truncated = bounded_python_script_diagnostic(value, 1024)
            if truncated or raw_details.get(f"{field}Truncated") is True:
                details[f"{field}Truncated"] = True
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
    elif code in {"execution_output_error", "report_visualization_script_failed"}:
        data_contract = _visualization_data_contract(payload)
        if data_contract is not None:
            facts["visualizationDataContract"] = data_contract
    return facts


def _is_nonrecoverable(error: Exception) -> bool:
    return recovery_for(error, "visualization") == "fatal"


def _is_degradable(error: Exception) -> bool:
    return recovery_for(error, "visualization") == "retry_then_degrade"


def _with_repair_count(error: Exception, *, execution_repairs: int) -> Exception:
    if not isinstance(error, ReportingError):
        return error
    details = dict(error.details) if isinstance(error.details, Mapping) else {}
    details["executionRepairCount"] = execution_repairs
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


def _ensure_script_identity(result: CodeGenerationResult, script_path: str) -> FileIdentity:
    script_file = result.script_file
    if script_file.path != script_path or script_file != result.execution_receipt.source_file:
        raise ReportingError(
            "report_phase_artifact_changed", "脚本回执路径与 Workflow 签发路径不一致。"
        )
    return script_file


def _validated_visual_receipts(
    result: CodeGenerationResult, plan: VisualizationPlanDraft
) -> tuple[ChartVisualInspectionReceipt, ...]:
    if len({item.path for item in result.execution_receipt.output_files}) != len(
        result.execution_receipt.output_files
    ) or len({item.source_path for item in result.visual_inspection_receipts}) != len(
        result.visual_inspection_receipts
    ):
        raise ReportingError("report_phase_artifact_changed", "图表签发回执包含重复路径。")
    outputs = {item.path: item for item in result.execution_receipt.output_files}
    expected_paths = {chart.source_path for chart in plan.charts}
    expected_outputs = expected_paths | {
        chart.interactive_path for chart in plan.charts if chart.interactive_path is not None
    }
    receipts = {item.source_path: item for item in result.visual_inspection_receipts}
    if set(receipts) != expected_paths or set(outputs) != expected_outputs:
        raise ReportingError(
            "report_phase_artifact_changed", "图表视觉回执与签发输出不一致。"
        )
    for path in expected_paths:
        output = outputs[path]
        receipt = receipts[path]
        if (
            receipt.sha256 != output.sha256
            or not receipt.reviewed
            or receipt.visual_review_status != "passed"
        ):
            raise ReportingError(
                "report_phase_artifact_changed", "图表视觉回执未通过或与签发输出不一致。"
            )
        if receipt.requires_revision:
            # 生产实证（cli-report-48220a46）：收敛闸门按 AGENTS.md 软告警口径放行的
            # requires_revision 回执在此被硬拒，把 section 打入 fresh attempt 死循环。
            # 未降级路径的 requires_revision 已由 submit_script 拦截，到达这里的一定
            # 是降级提交；结构/身份校验（sha、reviewed、passed）保持硬性。
            logger.warning(
                "report_visualization_revision_soft_warning path={} section 按软告警接受带修订要求的图表回执。",
                path,
            )
    return tuple(receipts[path] for path in sorted(receipts))


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
    """计划只生成一次；固定 Workflow 独立限制执行修复。"""

    def __init__(
        self,
        *,
        generate_plan: GenerateVisualizationPlan,
        run_code: RunVisualizationCode,
        submit: SubmitVisualization,
        degrade: DegradeVisualization | None = None,
        record_successful_repair: Callable[[Mapping[str, Any], FileIdentity], Awaitable[None]]
        | None = None,
        thinking_enabled: bool = True,
        thinking_budget_cap: int = 8192,
        benchmark_projection: BenchmarkProjection | None = None,
    ) -> None:
        self.generate_plan = generate_plan
        self.run_code = run_code
        self.submit = submit
        self.degrade = degrade
        self.record_successful_repair = record_successful_repair
        self.thinking_enabled = thinking_enabled
        self.thinking_budget_cap = thinking_budget_cap
        self.benchmark_projection = benchmark_projection

    async def run(
        self, payload: Mapping[str, Any], run_context: RunContext
    ) -> VisualizationWorkflowResult:
        plan = await self.generate_plan(payload, run_context)
        plan = _validate_visualization_plan_bindings(plan, payload)
        benchmark_kwargs = (
            {"benchmark_projection": self.benchmark_projection}
            if self.benchmark_projection is not None
            else {}
        )
        thinking_complexity = _visualization_thinking_complexity(payload)
        if not plan.charts:
            receipt = await self.submit(plan, (), run_context)
            _raise_rejected_submission(receipt)
            return VisualizationWorkflowResult("accepted", plan, None, ())

        script_path = _signed_script_path(payload)
        script_file: FileIdentity | None = None
        generation_failure: Exception | None = None
        generated_result: CodeGenerationResult | None = None
        successful_repair: tuple[Mapping[str, Any], FileIdentity] | None = None
        initial_recovery_used = False
        max_attempts = max(
            _MAX_GENERATE_ATTEMPTS,
            MAX_VISUALIZATION_EXECUTION_REPAIRS + 1,
        )
        for generate_attempt in range(max_attempts):
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
                        task_facts=(
                            _repair_task_facts(
                                plan,
                                generation_failure,
                                script_path,
                                payload=payload,
                                repair_attempt=generate_attempt,
                            )
                            if generation_failure is not None
                            else None
                        ),
                        **benchmark_kwargs,
                    )
                script_file = _ensure_script_identity(generated_result, script_path)
                repair_candidate = generated_result.visual_repair_diagnostic or diagnostic
                if repair_candidate is not None:
                    successful_repair = (repair_candidate, script_file)
                    initial_recovery_used = True
                break
            except Exception as error:
                generation_failure = error
                if _is_nonrecoverable(error):
                    raise
                if _is_degradable(error):
                    if generate_attempt >= MAX_VISUALIZATION_EXECUTION_REPAIRS:
                        exhausted_error = _with_repair_count(
                            error,
                            execution_repairs=MAX_VISUALIZATION_EXECUTION_REPAIRS,
                        )
                        if self.degrade is not None:
                            receipt = await self.degrade(exhausted_error, run_context)
                            _raise_rejected_submission(receipt)
                            return VisualizationWorkflowResult(
                                "degraded", plan, None, (), True
                            )
                        raise exhausted_error
                    continue
                # 「可恢复但不可降级」类失败按 _MAX_GENERATE_ATTEMPTS 独立封顶，不能
                # 借用为可降级失败预留的 max_attempts（更大）——否则每次都多烧一次
                # 昂贵的模型调用才放弃。即使这里因为分支未命中而落到循环结束，
                # 下方的兜底也会原样重抛 generation_failure，不会丢失根因。
                if generate_attempt == _MAX_GENERATE_ATTEMPTS - 1:
                    raise
        if script_file is None or generated_result is None:
            raise generation_failure or ReportingError(
                "report_visualization_section_failed", "可视化脚本生成未产出回执。"
            )
        output_paths = {item.path for item in generated_result.execution_receipt.output_files}
        if any(chart.source_path not in output_paths for chart in plan.charts):
            raise ReportingError(
                "report_phase_artifact_changed",
                "图表路径不在 Coding Agent 签发输出中。",
            )
        recovery_used = initial_recovery_used
        execution_repairs = 0
        pending_repair_error: Exception | None = None
        # 修复未改变脚本时，先用新结果（新执行/审查回执）再提交一次；
        # 仍失败才标记 repairUnchanged，避免临时故障被当成确定性失败而白耗修复。
        unchanged_repair = False

        while True:
            try:
                if pending_repair_error is not None:
                    error = pending_repair_error
                    pending_repair_error = None
                    raise error
                inspections = _validated_visual_receipts(generated_result, plan)
                receipt = await self.submit(plan, inspections, run_context)
                _raise_rejected_submission(receipt)
                if successful_repair is not None and self.record_successful_repair is not None:
                    await self.record_successful_repair(*successful_repair)
                return VisualizationWorkflowResult(
                    "accepted", plan, script_file, inspections, recovery_used
                )
            except Exception as error:
                if unchanged_repair:
                    unchanged_repair = False
                    if not isinstance(error, ReportingError) or not (
                        isinstance(error.details, Mapping)
                        and error.details.get("repairUnchanged") is True
                    ):
                        error = _with_unchanged_repair(error, script_file=script_file)
                if _is_nonrecoverable(error):
                    raise
                if not _is_degradable(error):
                    raise
                repair_count = execution_repairs
                repair_limit = MAX_VISUALIZATION_EXECUTION_REPAIRS
                if repair_count >= repair_limit:
                    exhausted_error = _with_repair_count(
                        error, execution_repairs=execution_repairs
                    )
                    if self.degrade is not None and _is_degradable(error):
                        receipt = await self.degrade(exhausted_error, run_context)
                        _raise_rejected_submission(receipt)
                        return VisualizationWorkflowResult(
                            "degraded", plan, script_file, (), recovery_used
                        )
                    raise exhausted_error
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
                try:
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
                                repair_attempt=execution_repairs,
                            ),
                            **benchmark_kwargs,
                        )
                except Exception as repair_error:  # noqa: BLE001 - 回注统一恢复策略
                    # 修复调用本身也属于本轮执行修复。把它送回循环入口，由同一
                    # fatal/retry_then_degrade 策略、计数器和降级出口处理，不能从
                    # except 分支直接逃逸。
                    pending_repair_error = repair_error
                    continue
                repaired_file = _ensure_script_identity(repaired, script_path)
                successful_repair = (
                    repaired.visual_repair_diagnostic or diagnostic,
                    repaired_file,
                )
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
                    unchanged_repair = True
                    logger.warning(
                        "report_visualization_script_repair_unchanged path={} sha256={} "
                        "execution_repairs={}",
                        script_path,
                        script_file.sha256,
                        execution_repairs,
                    )
                else:
                    script_file = repaired_file

        raise RuntimeError("可视化固定 Workflow 状态不可达")


__all__ = [
    "MAX_VISUALIZATION_EXECUTION_REPAIRS",
    "VisualizationSectionWorkflow",
    "VisualizationWorkflowResult",
]
