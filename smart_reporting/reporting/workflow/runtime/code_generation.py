"""Reporting Coding Agent V1 的交互式运行器。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from time import perf_counter
from types import SimpleNamespace
from typing import Any

from agno.agent import Agent
from agno.exceptions import ModelRateLimitError
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.tools.function import Function, FunctionCall
from loguru import logger
from openinference.instrumentation import using_metadata

from ....context_management import (
    CODING_COMPACTION_INPUT_TOKEN_GATE,
    CODING_CUSTOM_HISTORY_TOKEN_THRESHOLD,
    TASK_EXECUTION_CONTEXT_TOKEN_LIMIT,
    TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
)
from ...code_agent.context import (
    ExecutionReceipt,
    ReportingCodingTaskContext,
    ReportingCodingTaskRegistry,
)
from ...code_agent.delivery import SOURCE_EXCERPT_MAX_BYTES, bounded_edit_region
from ...code_agent.failure_policy import failure_kind as _code_failure_kind
from ...code_agent.lsp_process import ReportingLspProcessManager
from ...code_agent.metrics import build_coding_metric_sample, measure_input_components
from ...code_agent.toolkit import ReportingCodeModeToolkit
from ...code_mode import ReportingCodeModeRuntime
from ...host_workspace import HostReportingWorkspace
from ...knowledge import ReportingKnowledgeIndex
from ...models import ReportingError
from ...phase import bounded_python_script_diagnostic
from ...vision import ReportVisionReviewer
from ..checkpoint import ChartVisualInspectionReceipt, FileIdentity

MAX_DIAGNOSTIC_MESSAGE_LENGTH = 512
MAX_DIAGNOSTIC_OUTPUT_LENGTH = 2000
MAX_DIAGNOSTIC_PATH_LENGTH = 1024
MAX_DIAGNOSTIC_UNSIGNED_PATHS = 20
MAX_DIAGNOSTIC_POSITION = 1_000_000_000
ANALYSIS_TOOL_CALL_LIMIT = 30
VISUALIZATION_TOOL_CALL_BASE = 29
MAX_TOOL_CALL_LIMIT = 140
VISUALIZATION_BUDGET_GATE_SAFETY_MARGIN = 2
REPORTING_CODING_TASK_CONTEXT_METADATA_KEY = "reportingCodingTaskContext"
# V4 无进展快停：超过该请求序号仍无一次成功 run_script，或连续同签名
# run_script 失败达到上限时，提前以 report_code_no_progress 交给 fresh attempt。
# 请求阈值应按冻结回放中通过样本 firstSuccessfulRunRequest 最大值加余量标定。
VISUALIZATION_NO_PROGRESS_REQUEST_LIMIT = 24
VISUALIZATION_REPEATED_RUN_FAILURE_LIMIT = 3

# 同一 run 内压缩重连的上限；请求数同时受模型预算 request_limit 约束。
MAX_RUN_COMPACTION_CONTINUATIONS = 2
# 与投影层请求前门禁对齐：窗口内任一请求输入达到该阈值即视为历史增长越界。
RUN_COMPACTION_INPUT_TOKEN_THRESHOLD = min(
    int(
        (TASK_EXECUTION_CONTEXT_TOKEN_LIMIT - TASK_EXECUTION_OUTPUT_TOKEN_RESERVE)
        * CODING_CUSTOM_HISTORY_TOKEN_THRESHOLD
    ),
    CODING_COMPACTION_INPUT_TOKEN_GATE,
)


def _request_metric_tokens(entry: Any) -> int | None:
    if not isinstance(entry, Mapping):
        return None
    value = entry.get("inputTokens")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _run_compaction_signal(request_metrics: list[Any]) -> tuple[bool, int | str]:
    """窗口内压缩依据：投影层压缩标记或任一请求输入超过 Coding 专用阈值。"""

    triggered = False
    tokens: int | str = "unknown"
    for entry in request_metrics:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("compactionTriggered") is True or entry.get("compaction_triggered") is True:
            triggered = True
        value = _request_metric_tokens(entry)
        if value is not None and value >= RUN_COMPACTION_INPUT_TOKEN_THRESHOLD:
            triggered = True
            tokens = value if tokens == "unknown" else max(tokens, value)
    return triggered, tokens


def _observed_truncated_calls(request_metrics: list[Any]) -> int:
    """消费投影层暴露的截断计数；协议层未暴露时保持 0，不凭空捏造。"""

    total = 0
    for entry in request_metrics:
        if not isinstance(entry, Mapping):
            continue
        for key in ("truncatedCallCount", "truncated_calls"):
            value = entry.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                total += value
    return total


def _metric_failure_code(
    terminal_failure_code: str | None,
    last_failure: Mapping[str, Any] | None,
) -> str | None:
    """只返回导致任务终止或尚未解决的失败码。"""

    if terminal_failure_code:
        return terminal_failure_code
    if not isinstance(last_failure, Mapping) or last_failure.get("resolved") is True:
        return None
    code = last_failure.get("code")
    return code if isinstance(code, str) and code else None


def _bounded_unsigned_paths(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, str) and 0 < len(item) <= MAX_DIAGNOSTIC_PATH_LENGTH
    ][:MAX_DIAGNOSTIC_UNSIGNED_PATHS]


def _bounded_forbidden_path_operations(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str)})[:MAX_DIAGNOSTIC_UNSIGNED_PATHS]


@dataclass(frozen=True, slots=True)
class CodeGenerationResult:
    script_file: FileIdentity
    execution_receipt: ExecutionReceipt
    visual_inspection_receipts: tuple[ChartVisualInspectionReceipt, ...] = ()
    visual_repair_diagnostic: Mapping[str, Any] | None = None


class ReportingCodeGenerationRunner:
    """为单个 Coding task 创建 Agent 并签发一次交互式执行回执。"""

    @staticmethod
    def _model_task_payload(task_context: ReportingCodingTaskContext) -> dict[str, Any]:
        """只向模型公开实现脚本所需的任务边界。"""

        return {
            "task_kind": task_context.task_kind,
            "script_path": task_context.script_path,
            "authorized_read_paths": list(task_context.authorized_read_paths),
            "authorized_write_paths": list(task_context.authorized_write_paths),
            "declared_output_paths": list(task_context.declared_output_paths),
            "max_source_bytes": task_context.max_source_bytes,
        }

    @staticmethod
    def _repair_task_facts(task_facts: Mapping[str, Any]) -> dict[str, Any]:
        """保留修复所需契约，避免重复注入首轮规划和完整事实。"""

        if not isinstance(task_facts, Mapping):
            return {}
        projected: dict[str, Any] = {}
        for key in (
            "scriptPath",
            "evidencePath",
            "analysisOutputRoot",
            "repairAttempt",
            "existingFacts",
            "codingRequirements",
            "evidenceDecision",
            "outputContract",
            "visualizationDataContract",
            "missingCharts",
            "chartInputs",
        ):
            if key in task_facts:
                projected[key] = task_facts[key]
        current_analysis = task_facts.get("currentAnalysis")
        if isinstance(current_analysis, Mapping):
            projected["currentAnalysis"] = {
                key: current_analysis[key]
                for key in (
                    "analysisId",
                    "title",
                    "managementQuestion",
                    "primaryMetricFamily",
                    "datasetIds",
                )
                if key in current_analysis
            }
        datasets = task_facts.get("datasets")
        if isinstance(datasets, list):
            projected_datasets = []
            for item in datasets:
                if not isinstance(item, Mapping):
                    continue
                projected_item = {
                    key: item[key]
                    for key in ("datasetId", "path", "columns")
                    if key in item
                }
                provenance = item.get("provenance")
                if isinstance(provenance, Mapping):
                    period_roles = provenance.get("periodRoles")
                    if isinstance(period_roles, list):
                        projected_item["provenance"] = {
                            "periodRoles": [
                                role
                                for role in period_roles
                                if isinstance(role, str)
                            ]
                        }
                projected_datasets.append(projected_item)
            projected["datasets"] = projected_datasets
        return projected

    @staticmethod
    def _host_task_payload(task_context: ReportingCodingTaskContext) -> dict[str, Any]:
        """保留 trace/replay 所需身份，不进入模型输入。"""

        return {
            "task_id": task_context.task_id,
            "task_kind": task_context.task_kind,
            "code_mode_session_id": task_context.code_mode_session_id,
            "workspace_key": task_context.workspace_key,
            "workspace_root": str(task_context.workspace_root),
            "script_path": task_context.script_path,
            "authorized_read_paths": list(task_context.authorized_read_paths),
            "authorized_write_paths": list(task_context.authorized_write_paths),
            "declared_output_paths": list(task_context.declared_output_paths),
            "max_source_bytes": task_context.max_source_bytes,
        }

    @classmethod
    def _trace_task_context(cls, task_context: ReportingCodingTaskContext) -> Any:
        return using_metadata(
            {
                REPORTING_CODING_TASK_CONTEXT_METADATA_KEY: cls._host_task_payload(
                    task_context
                )
            }
        )

    def __init__(
        self,
        agent_factory: Callable[[tuple[Function, ...]], Agent],
        code_mode_runtime: ReportingCodeModeRuntime,
        lsp_manager: ReportingLspProcessManager,
        registry: ReportingCodingTaskRegistry | None = None,
        knowledge_index: ReportingKnowledgeIndex | None = None,
        vision_reviewer: ReportVisionReviewer | None = None,
        model_metrics_recorder: Callable[[Any, int], None] | None = None,
        coding_metrics_recorder: Callable[[Mapping[str, Any]], None] | None = None,
        failure_artifact_recorder: Callable[[Mapping[str, Any]], None] | None = None,
        compact_continuation: bool = False,
    ) -> None:
        self.agent_factory = agent_factory
        self.code_mode_runtime = code_mode_runtime
        self.registry = registry or ReportingCodingTaskRegistry()
        self.knowledge_index = knowledge_index
        self.lsp_manager = lsp_manager
        self.vision_reviewer = vision_reviewer
        self.model_metrics_recorder = model_metrics_recorder
        self.coding_metrics_recorder = coding_metrics_recorder
        self.failure_artifact_recorder = failure_artifact_recorder
        self.compact_continuation = compact_continuation

    async def run(
        self,
        task_context: ReportingCodingTaskContext,
        workspace: HostReportingWorkspace,
        task_facts: Mapping[str, Any],
        *,
        run_context: RunContext,
        diagnostic: Mapping[str, Any] | None = None,
        output_preflight: Callable[[ExecutionReceipt], Awaitable[Mapping[str, Any] | None]] | None = None,
    ) -> CodeGenerationResult:
        if task_context.task_kind == "visualization" and self.vision_reviewer is None:
            raise ReportingError(
                "report_code_visual_reviewer_missing",
                "章节图表 Coding Agent 未配置独立视觉审查模型。",
            )
        missing_inputs = [
            path
            for path in task_context.authorized_read_paths
            if not await workspace.apath_exists(task_context.task_id, path)
        ]
        if missing_inputs:
            raise ReportingError(
                "report_code_authorized_input_missing",
                "Coding Agent 的授权输入文件不在当前正式 Workspace。",
                details={"missingPaths": missing_inputs[:20]},
            )
        requested_tool_call_limit = (
            VISUALIZATION_TOOL_CALL_BASE + len(task_context.declared_output_paths)
            if task_context.task_kind == "visualization"
            else ANALYSIS_TOOL_CALL_LIMIT
        )
        if requested_tool_call_limit > MAX_TOOL_CALL_LIMIT:
            raise ReportingError(
                "report_code_tool_call_limit_exceeded",
                "章节图表数量超过 Coding Agent 工具调用硬上限。",
                details={
                    "declaredOutputCount": len(task_context.declared_output_paths),
                    "requestedToolCallLimit": requested_tool_call_limit,
                    "maxToolCallLimit": MAX_TOOL_CALL_LIMIT,
                },
            )
        async with self.registry.bind(task_context, workspace) as binding:
            toolkit = ReportingCodeModeToolkit(
                binding,
                self.code_mode_runtime,
                knowledge_index=self.knowledge_index,
                lsp_manager=self.lsp_manager,
                vision_reviewer=self.vision_reviewer,
                output_preflight=output_preflight,
                failure_artifact_recorder=self.failure_artifact_recorder,
            )
            await toolkit.refresh_delivery_state()
            task_payload = self._model_task_payload(task_context)
            payload = {
                "task": task_payload,
                "facts": (
                    self._repair_task_facts(task_facts)
                    if diagnostic is not None
                    else dict(task_facts)
                ),
                "diagnostic": self._short_diagnostic(diagnostic) if diagnostic else None,
            }
            started_at = perf_counter()
            metric_outputs: list[Any] = []
            metric_request_count = 0
            metric_recorded = False
            receipt: ExecutionReceipt | None = None
            agent: Any = None
            input_components: dict[str, dict[str, int | str]] = {}
            terminal_failure_code: str | None = None
            host_tool_results = 0
            compact_continuation_applied = False
            run_compaction: dict[str, Any] = {
                "windowId": 0,
                "triggered": False,
                "beforeTokens": "unknown",
                "afterTokens": "unknown",
                "retainedCallCount": 0,
                "truncatedCallCount": 0,
            }

            def record_coding_metrics() -> None:
                nonlocal metric_recorded
                if metric_recorded:
                    return
                metric_recorded = True

                def summed_usage(field: str) -> int | float | None:
                    total: int | float = 0
                    observed = False
                    for output in metric_outputs:
                        usage = getattr(output, "metrics", None)
                        if usage is None:
                            return None
                        value = getattr(usage, field, None)
                        if (
                            isinstance(value, int | float)
                            and not isinstance(value, bool)
                            and value >= 0
                        ):
                            total += value
                            observed = True
                    return total if observed else None

                visual_defect: bool | str = "unknown"
                if task_context.task_kind == "visualization":
                    visual_defect = any(
                        issue.severity == "critical"
                        for review in binding.visual_inspection_receipts.values()
                        for issue in review.issues
                    )
                model = getattr(agent, "model", None)
                raw_protocol_reader = getattr(model, "code_run_raw_protocol_correct", None)
                request_metrics_reader = getattr(model, "code_run_request_metrics", None)
                sample = build_coding_metric_sample(
                    duration_ms=max(0, round((perf_counter() - started_at) * 1000)),
                    task_id=task_context.task_id,
                    task_kind=task_context.task_kind,
                    model=getattr(model, "id", None),
                    provider=getattr(model, "provider", None),
                    reasoning_effort=getattr(model, "reasoning_effort", None),
                    request_count=metric_request_count,
                    input_tokens=summed_usage("input_tokens"),
                    output_tokens=summed_usage("output_tokens"),
                    reasoning_tokens=summed_usage("reasoning_tokens"),
                    cache_read_tokens=summed_usage("cache_read_tokens"),
                    model_cost=summed_usage("cost"),
                    tool_counts=(
                        toolkit.tool_call_metrics()
                        if callable(getattr(toolkit, "tool_call_metrics", None))
                        else {}
                    ),
                    completed_tool_calls=getattr(toolkit, "completed_tool_calls", None),
                    visual_review_duration_ms=getattr(
                        toolkit, "visual_review_duration_ms", None
                    ),
                    request_metrics=(
                        request_metrics_reader()
                        if callable(request_metrics_reader)
                        else None
                    ),
                    input_components=input_components,
                    raw_protocol_correct=(
                        raw_protocol_reader()
                        if callable(raw_protocol_reader)
                        else "unknown"
                    ),
                    envelope_normalized_inputs=(
                        envelope_reader()
                        if callable(envelope_reader := getattr(model, "code_run_envelope_normalized_inputs", None))
                        else "unknown"
                    ),
                    wire_shape_recoveries=(
                        wire_reader()
                        if callable(wire_reader := getattr(model, "code_run_wire_shape_recoveries", None))
                        else "unknown"
                    ),
                    first_script_success=getattr(
                        toolkit, "first_script_success", "unknown"
                    ),
                    first_script_failure_code=getattr(
                        toolkit, "first_script_failure_code", None
                    ),
                    first_run_success=getattr(toolkit, "first_run_success", "unknown"),
                    first_run_failure_code=getattr(
                        toolkit, "first_run_failure_code", None
                    ),
                    first_run_failure=getattr(toolkit, "first_run_failure", None),
                    first_patch_applied=getattr(toolkit, "first_patch_applied", "unknown"),
                    first_repair_success=getattr(
                        toolkit, "first_repair_success", "unknown"
                    ),
                    critical_visual_defect=visual_defect,
                    failure_code=_metric_failure_code(
                        terminal_failure_code,
                        getattr(toolkit, "last_failure", None),
                    ),
                    execution_spans=(
                        self.code_mode_runtime.drain_execution_spans(
                            task_context.code_mode_session_id
                        )
                        if callable(getattr(self.code_mode_runtime, "drain_execution_spans", None))
                        else "unknown"
                    ),
                )
                if task_context.task_kind == "visualization":
                    # V5：闸门降级提交单独计量，不并入干净通过；类别来自完整回执。
                    gate_tripped = getattr(toolkit, "visual_review_gate_tripped", None)
                    sample["visualReviewGateTripped"] = (
                        gate_tripped if isinstance(gate_tripped, bool) else "unknown"
                    )
                    receipts = getattr(
                        getattr(toolkit, "binding", None), "visual_inspection_receipts", None
                    )
                    categories: list[str] = []
                    if gate_tripped is True and isinstance(receipts, Mapping):
                        for receipt in receipts.values():
                            if not getattr(receipt, "requires_revision", False):
                                continue
                            categories.extend(
                                str(getattr(issue, "category", "unknown"))[:64]
                                for issue in getattr(receipt, "issues", ())
                                if getattr(issue, "severity", None) == "critical"
                            )
                    sample["gateCriticalCategories"] = sorted(categories)[:20]
                sample["compactContinuationEnabled"] = self.compact_continuation
                sample["compactContinuationApplied"] = compact_continuation_applied
                sample["compactionTriggered"] = run_compaction["triggered"]
                sample["compactionBeforeTokens"] = run_compaction["beforeTokens"]
                sample["compactionAfterTokens"] = run_compaction["afterTokens"]
                sample["compactionWindowId"] = run_compaction["windowId"]
                sample["retainedCallCount"] = run_compaction["retainedCallCount"]
                sample["truncatedCallCount"] = run_compaction["truncatedCallCount"]
                logger.info(
                    "report_code_coding_metrics task_id={} sample={}",
                    task_context.task_id,
                    json.dumps(sample, ensure_ascii=False, separators=(",", ":")),
                )
                if self.coding_metrics_recorder is None:
                    return
                try:
                    self.coding_metrics_recorder(sample)
                except Exception as error:
                    logger.warning(
                        "report_code_coding_metrics_record_failed task_id={} error_type={}",
                        task_context.task_id,
                        type(error).__name__,
                    )
            try:
                model_tool_limit = min(MAX_TOOL_CALL_LIMIT, requested_tool_call_limit)
                delivery_state_reader = getattr(toolkit, "delivery_state", None)
                state = (
                    delivery_state_reader()
                    if callable(delivery_state_reader)
                    else {}
                )
                if (
                    diagnostic is None
                    and state.get("nextTools") == ["run_script"]
                    and state.get("execution") is None
                    and state.get("lastFailure") is None
                    and state.get("validationFailure") is None
                    and state.get("script", {}).get("sha256")
                ):
                    # 宿主预执行不是 provider 调用；复用 Agno hooks，不生成工具回放消息。
                    call = FunctionCall(
                        function=next(tool for tool in toolkit.tool_functions if tool.name == "run_script"),
                        arguments={},
                        call_id=f"host-initial-run-{task_context.task_id}",
                    )
                    logger.info("report_code_host_execution_started task_id={} tool_name=run_script", task_context.task_id)
                    with self._trace_task_context(task_context):
                        await call.aexecute()
                    host_tool_results += 1
                    model_tool_limit -= 1
                    if toolkit.last_failure is not None:
                        # hook 已完成白名单与大小裁剪，保留 SHA、片段及函数修复范围。
                        payload["diagnostic"] = {
                            key: toolkit.last_failure[key]
                            for key in ("code", "message", "details")
                        }
                    logger.info(
                        "report_code_host_execution_completed task_id={} tool_name=run_script success={}",
                        task_context.task_id, toolkit.first_run_success,
                    )
                agent = self.agent_factory(toolkit.tool_functions)
                instruction_components = agent.__dict__.get(
                    "_reporting_instruction_components", {}
                )
                input_components = measure_input_components(
                    {
                        "commonInstructions": instruction_components.get("common", ()),
                        "stageInstructions": instruction_components.get("stage", ()),
                        "task": task_payload,
                        "facts": payload["facts"],
                        "diagnostic": payload["diagnostic"],
                        "tools": [
                            {
                                "name": tool.name,
                                "description": tool.description or "",
                            }
                            for tool in toolkit.tool_functions
                        ],
                    }
                )
                agent.tool_call_limit = model_tool_limit
                configure_code_run = getattr(getattr(agent, "model", None), "configure_code_run", None)
                if isinstance(agent, Agent) and not callable(configure_code_run):
                    raise ReportingError(
                        "report_code_model_protocol_missing",
                        "Coding Agent 模型未配置 Responses free-form 工具协议。",
                        details={"retryable": False},
                    )
                if callable(configure_code_run):
                    configure_code_run(
                        toolkit.tool_functions,
                        max_model_requests=max(4, agent.tool_call_limit + 1),
                        redundant_call_check=toolkit.has_current_visual_review,
                        delivery_state_reader=toolkit.delivery_state,
                        delivery_reserve=(
                            3 + len(task_context.declared_output_paths)
                            if task_context.task_kind == "visualization"
                            else 3
                        ),
                        tool_call_limit=model_tool_limit,
                        visual_budget_gate_safety_margin=VISUALIZATION_BUDGET_GATE_SAFETY_MARGIN,
                        **(
                            {
                                "no_progress_request_limit": (
                                    VISUALIZATION_NO_PROGRESS_REQUEST_LIMIT
                                ),
                                "repeated_run_failure_limit": (
                                    VISUALIZATION_REPEATED_RUN_FAILURE_LIMIT
                                ),
                            }
                            if task_context.task_kind == "visualization"
                            else {}
                        ),
                    )
                model = getattr(agent, "model", None)
                request_count_reader = getattr(model, "code_run_request_count", None)
                tool_count_reader = getattr(model, "code_run_tool_count", None)
                request_count = 0
                run_output = None
                attempt = 0
                compact_reconnect_summary: dict[str, Any] | None = None
                while True:
                    previous_requests = request_count
                    previous_output = run_output
                    run_output = None
                    window_request_metrics: list[Any] = []
                    try:
                        if attempt == 0:
                            with self._trace_task_context(task_context):
                                run_output = await agent.arun(
                                    self._prompt(payload), run_context=run_context
                                )
                        elif self.compact_continuation:
                            # 新 run 不载入历史；复用模型以保留任务预算和逐请求指标。
                            compact_continuation_applied = True
                            delivery = toolkit.delivery_state()
                            continuation_payload: dict[str, Any] = {
                                "instruction": "继续当前交付阶段，只处理尚未完成的动作并调用 submit_script。",
                                "task": task_payload,
                                "facts": self._repair_task_facts(task_facts),
                                "diagnostic": payload["diagnostic"],
                                "delivery": delivery,
                            }
                            if compact_reconnect_summary is not None:
                                continuation_payload["instruction"] = (
                                    "旧工具历史已压缩为摘要；只依据任务边界、最新 diagnostic、"
                                    "当前源码 SHA、压缩摘要与交付状态继续未完成的动作，"
                                    "不要重复已完成的调用，完成后调用 submit_script。"
                                )
                                continuation_payload["compaction"] = compact_reconnect_summary
                            compact_reconnect_summary = None
                            with self._trace_task_context(task_context):
                                run_output = await agent.arun(
                                    self._prompt(continuation_payload),
                                    run_context=run_context,
                                    add_history_to_context=False,
                                )
                        else:
                            with self._trace_task_context(task_context):
                                run_output = await agent.acontinue_run(
                                    run_response=previous_output,
                                    input=self._prompt({
                                        "instruction": "任务尚未提交，请根据当前交付状态完成剩余步骤并调用 submit_script。",
                                        "delivery": toolkit.delivery_state(),
                                    }),
                                    run_context=run_context,
                                )
                    finally:
                        request_count = (
                            request_count_reader() if callable(request_count_reader) else 0
                        )
                        recordable_output = run_output
                        request_metrics_reader = getattr(
                            model, "code_run_request_metrics", None
                        )
                        if callable(request_metrics_reader):
                            all_request_metrics = request_metrics_reader()
                            request_metrics = (
                                all_request_metrics[previous_requests:]
                                if isinstance(all_request_metrics, list)
                                else []
                            )
                            window_request_metrics = list(request_metrics)
                            if run_output is None:
                                recordable_output = SimpleNamespace(metrics=None)
                            try:
                                setattr(
                                    recordable_output,
                                    "_reporting_request_metrics",
                                    request_metrics,
                                )
                            except (AttributeError, TypeError, ValueError):
                                recordable_output = SimpleNamespace(
                                    metrics=getattr(run_output, "metrics", None),
                                    _reporting_request_metrics=request_metrics,
                                )
                        if run_compaction["triggered"] and run_compaction["afterTokens"] == "unknown":
                            for entry in window_request_metrics:
                                observed = _request_metric_tokens(entry)
                                if observed is not None:
                                    run_compaction["afterTokens"] = observed
                                    break
                        if self.model_metrics_recorder is not None:
                            self.model_metrics_recorder(
                                recordable_output, request_count - previous_requests
                            )
                        error_reader = getattr(model, "report_run_error", None)
                        model_error = error_reader() if callable(error_reader) else None
                        usage = getattr(run_output, "metrics", None)
                        # Agno 在协议失败时可能返回默认全零 RunMetrics，不能当成免费请求。
                        empty_failed_usage = isinstance(model_error, Exception) and not (
                            getattr(usage, "total_tokens", 0)
                            or getattr(usage, "input_tokens", 0)
                            or getattr(usage, "output_tokens", 0)
                            or getattr(usage, "details", None)
                        )
                        metric_outputs.append(None if empty_failed_usage else run_output)
                        metric_request_count += request_count - previous_requests
                    report_run_error = getattr(model, "report_run_error", None)
                    if callable(report_run_error):
                        recorded_error = report_run_error()
                        if isinstance(recorded_error, Exception):
                            raise recorded_error
                    if isinstance(toolkit.terminal_failure, Exception):
                        raise toolkit.terminal_failure
                    if (
                        toolkit.submitted_receipt is not None
                        or not isinstance(agent, Agent)
                        or getattr(run_output, "status", None) != RunStatus.completed
                        or getattr(run_output, "active_requirements", ())
                    ):
                        break
                    compaction_signal = False
                    compaction_tokens: int | str = "unknown"
                    if self.compact_continuation:
                        compaction_signal, compaction_tokens = _run_compaction_signal(
                            window_request_metrics
                        )
                    if attempt > 0 and not compaction_signal:
                        # 与既有契约一致：无压缩信号时交付补提交只续一次。
                        break
                    if (
                        compaction_signal
                        and run_compaction["windowId"] >= MAX_RUN_COMPACTION_CONTINUATIONS
                    ):
                        break
                    if attempt == 0:
                        remaining = agent.model.claim_delivery_continuation(model_tool_limit)
                        if remaining is None:
                            break
                    else:
                        # 一次性交付额度已消费；压缩重连只复用同一预算的剩余工具数。
                        # 请求预算同样要在重连前检查：余额不足时干净收尾，不能等到
                        # arun 内部才抛出 report_code_model_request_limit。
                        used_tools = (
                            tool_count_reader() if callable(tool_count_reader) else model_tool_limit
                        )
                        remaining = model_tool_limit - used_tools
                        if remaining <= 0:
                            break
                        current_request = getattr(model, "_current_code_request", None)
                        if callable(current_request):
                            _, request_limit = current_request()
                            used_requests = (
                                request_count_reader() if callable(request_count_reader) else 0
                            )
                            if used_requests >= request_limit:
                                break
                    agent.tool_call_limit = remaining
                    await toolkit.refresh_delivery_state()
                    if compaction_signal:
                        run_compaction["windowId"] += 1
                        run_compaction["triggered"] = True
                        if compaction_tokens != "unknown":
                            run_compaction["beforeTokens"] = compaction_tokens
                        run_compaction["afterTokens"] = "unknown"
                        retained = toolkit.tool_call_metrics()
                        run_compaction["retainedCallCount"] = sum(
                            value
                            for value in retained.values()
                            if isinstance(value, int) and not isinstance(value, bool)
                        )
                        run_compaction["truncatedCallCount"] += _observed_truncated_calls(
                            window_request_metrics
                        )
                        delivery = toolkit.delivery_state()
                        script = delivery.get("script")
                        compact_reconnect_summary = {
                            "windowId": run_compaction["windowId"],
                            "reason": "custom_history_input_token_threshold",
                            "beforeTokens": run_compaction["beforeTokens"],
                            "sourceSha256": (
                                script.get("sha256") if isinstance(script, Mapping) else None
                            ),
                            "summarizedToolCalls": retained,
                            "completedToolCalls": getattr(toolkit, "completed_tool_calls", None),
                            "nextTools": delivery.get("nextTools"),
                        }
                        logger.info(
                            "report_code_run_compaction_reconnect task_id={} window_id={} "
                            "before_tokens={} retained_calls={} remaining_tools={}",
                            task_context.task_id,
                            run_compaction["windowId"],
                            run_compaction["beforeTokens"],
                            run_compaction["retainedCallCount"],
                            remaining,
                        )
                    else:
                        logger.info(
                            "report_code_delivery_continuation task_id={} remaining_tools={} model_requests={}",
                            task_context.task_id, remaining, request_count,
                        )
                    attempt += 1
                receipt = toolkit.submitted_receipt
                if receipt is None:
                    details = await toolkit.submission_diagnostic()
                    tool_results = tool_count_reader() if callable(tool_count_reader) else sum(
                        message.role == "tool" for message in (getattr(run_output, "messages", None) or ())
                    )
                    details.update({
                        "retryable": False,
                        "recovery": "retry_then_degrade",
                        "toolCallLimit": requested_tool_call_limit,
                        "toolResultCount": tool_results + host_tool_results,
                        "providerToolResultCount": tool_results,
                        "hostToolResultCount": host_tool_results,
                        "modelRequests": request_count,
                        "compactionTriggered": run_compaction["triggered"],
                        "compactionBeforeTokens": run_compaction["beforeTokens"],
                        "compactionAfterTokens": run_compaction["afterTokens"],
                        "compactionWindowId": run_compaction["windowId"],
                        "retainedCallCount": run_compaction["retainedCallCount"],
                        "truncatedCallCount": run_compaction["truncatedCallCount"],
                        "terminationReason": (
                            "tool_call_limit_reached"
                            if tool_results >= model_tool_limit
                            else "model_ended_without_submission"
                        ),
                    })
                    raise ReportingError(
                        "report_code_generation_no_submission",
                        "Coding Agent 未签发成功执行的 Python 脚本。",
                        details=details,
                    )
            except ReportingError as error:
                terminal_failure_code = error.code
                raise
            except Exception as error:
                failure = self._agent_failure(error)
                terminal_failure_code = failure.code
                raise failure from error
            finally:
                try:
                    await self.code_mode_runtime.shutdown(task_context.code_mode_session_id)
                except Exception as shutdown_error:
                    logger.warning(
                        "report_code_mode_shutdown_failed session_id={} error_type={}",
                        task_context.code_mode_session_id,
                        type(shutdown_error).__name__,
                    )
                record_coding_metrics()
            await toolkit.require_current_receipt(receipt)
            visual_receipts = tuple(
                binding.visual_inspection_receipts[path]
                for path in sorted(binding.visual_inspection_receipts)
            )
            logger.info(
                "report_code_generation_completed task_id={} path={} duration_ms={}",
                task_context.task_id,
                receipt.source_file.path,
                max(0, round((perf_counter() - started_at) * 1000)),
            )
            return CodeGenerationResult(
                script_file=receipt.source_file,
                execution_receipt=receipt,
                visual_inspection_receipts=visual_receipts,
                visual_repair_diagnostic=(
                    binding.visual_repair_diagnostic
                    if task_context.task_kind == "visualization"
                    else None
                ),
            )

    @staticmethod
    def _prompt(payload: Mapping[str, Any]) -> str:
        return json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _agent_failure(error: Exception) -> ReportingError:
        if isinstance(error, ModelRateLimitError):
            return ReportingError(
                "report_code_generation_rate_limited",
                "Coding Agent 模型调用受限，请稍后重试。",
                details={"statusCode": error.status_code, "recovery": "retry_then_degrade"},
            )
        return ReportingError("report_code_generation_agent_failed", "Coding Agent 调用失败。")

    @classmethod
    def _short_diagnostic(cls, diagnostic: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        code = diagnostic.get("code")
        if isinstance(code, str) and code:
            result["code"] = code[:128]
        message = diagnostic.get("message")
        if isinstance(message, str) and message:
            result["message"] = message[:MAX_DIAGNOSTIC_MESSAGE_LENGTH]
        details = diagnostic.get("details")
        if not isinstance(details, Mapping):
            return result
        last_failure = details.get("lastFailure")
        if isinstance(last_failure, Mapping):
            nested = last_failure.get("details")
            details = {
                **details,
                **(nested if isinstance(nested, Mapping) else {}),
                "toolCode": last_failure.get("code"),
                "toolMessage": last_failure.get("message"),
            }
        # pendingOutputValidation 反映当前仍在阻塞提交的真实原因；lastFailure 可能已
        # 被之后一次无关的探索失败覆盖，所以这里优先于（覆盖）lastFailure 的推断。
        pending_validation = details.get("pendingOutputValidation")
        if isinstance(pending_validation, Mapping):
            nested = pending_validation.get("details")
            details = {
                **details,
                **(nested if isinstance(nested, Mapping) else {}),
                "toolCode": pending_validation.get("code"),
                "toolMessage": pending_validation.get("message"),
            }
        safe: dict[str, Any] = {}
        issue_summary = details.get("issueSummary")
        if isinstance(issue_summary, str) and issue_summary:
            safe["issueSummary"] = issue_summary[:MAX_DIAGNOSTIC_OUTPUT_LENGTH]
        path = details.get("path")
        if isinstance(path, str) and 0 < len(path) <= MAX_DIAGNOSTIC_PATH_LENGTH:
            safe["path"] = path
        unsigned = _bounded_unsigned_paths(details.get("unsignedPaths"))
        if unsigned:
            safe["unsignedPaths"] = unsigned
        forbidden = _bounded_forbidden_path_operations(details.get("forbiddenPathOperations"))
        if forbidden:
            safe["forbiddenPathOperations"] = forbidden
        for field in ("line", "offset", "size", "lineCount", "maxLineLength", "exitCode",
                      "sourceStartLine", "sourceEndLine", "errorLine"):
            value = details.get(field)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and abs(value) <= MAX_DIAGNOSTIC_POSITION
            ):
                safe[field] = value
        # 编辑锚点上下文与 delivery 投影使用同一边界，跨压缩重连时保持可修复性。
        source_excerpt = details.get("sourceExcerpt")
        if isinstance(source_excerpt, str) and source_excerpt:
            raw = source_excerpt.encode("utf-8")
            safe["sourceExcerpt"] = (
                source_excerpt
                if len(raw) <= SOURCE_EXCERPT_MAX_BYTES
                else raw[-SOURCE_EXCERPT_MAX_BYTES:].decode("utf-8", errors="ignore")
            )
        for field in ("readRange", "allowedEditRegion"):
            region = bounded_edit_region(details.get(field))
            if region is not None:
                safe[field] = region
        output = details.get("output")
        if isinstance(output, str) and output:
            safe["output"], truncated = bounded_python_script_diagnostic(
                output, MAX_DIAGNOSTIC_OUTPUT_LENGTH
            )
            safe["outputTruncated"] = truncated
        for field in ("traceback", "stderr", "stdout"):
            value = details.get(field)
            if isinstance(value, str) and value:
                safe[field], truncated = bounded_python_script_diagnostic(
                    value, MAX_DIAGNOSTIC_OUTPUT_LENGTH // 2
                )
                if truncated or details.get(f"{field}Truncated") is True:
                    safe[f"{field}Truncated"] = True
        for field in ("toolCode", "toolMessage"):
            value = details.get(field)
            if isinstance(value, str) and value:
                safe[field] = value[:MAX_DIAGNOSTIC_MESSAGE_LENGTH]
        if safe:
            result["details"] = safe
        return result


__all__ = ["CodeGenerationResult", "ReportingCodeGenerationRunner", "_code_failure_kind"]
