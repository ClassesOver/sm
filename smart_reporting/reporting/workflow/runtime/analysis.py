# mypy: disable-error-code="attr-defined"
# 运行时由 facade 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。
from __future__ import annotations

from collections.abc import Callable
from copy import copy
from typing import Literal

from agno.models.message import Message
from agno.session.agent import AgentSession

from ....task_execution import (
    TASK_EXECUTION_CONTEXT_TOKEN_LIMIT,
    TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
)
from ...code_agent.context import ExecutionReceipt, ReportingCodingTaskContext
from ...knowledge import ReportingKnowledgeIndex
from ...model_policy import (
    ThinkingFailureKind,
    ThinkingRequest,
    bind_reporting_thinking,
    resolve_reporting_input_token_hard_cap,
    select_reporting_thinking,
)
from ...phase import (
    REPORTING_ANALYSIS_INPUT_TOKEN_HARD_CAP,
    _nonnegative_int,
    reporting_model_route_from_run_context,
)
from ...structured_output import ReportingStructuredOutputExecutor
from ...tools import build_reporting_tools
from ..benchmark_variants import (
    BenchmarkProjection,
    BenchmarkVariant,
    LegacyAnalysisEvidenceDecision,
    LegacyVisualizationPlanDraft,
)
from ..checkpoint import ChartVisualInspectionReceipt, CheckpointRetryUsage
from ..execution import ReportingTaskInvocation
from .analysis_item_workflow import (
    MAX_SUPPLEMENTAL_EVIDENCE_BYTES,
    AnalysisEvidenceDecision,
    AnalysisItemWorkflow,
    AnalysisSummaryDraft,
    EvidenceDecision,
    SupplementalEvidence,
    _project_analysis_summary_payload,
    supplemental_evidence_schema_error,
    validate_supplemental_evidence,
)
from .base import (
    _VISUALIZATION_RECOVERY_ERROR_CODES,
    MAX_REPORT_ANALYSIS_REWORKS_PER_SECTION,
    MAX_REPORT_INSTRUCTION_BYTES,
    MAX_REPORT_SECTION_PHASE_ATTEMPTS,
    REPORT_ANALYSIS_CONTEXT_FILE_STATE_KEY,
    REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY,
    REPORT_ARTIFACTS_STATE_KEY,
    REPORT_DATA_REQUIREMENTS_STATE_KEY,
    REPORT_DATASET_LINEAGE_STATE_KEY,
    REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
    REPORT_DOCUMENT_GENERATED_DATE_STATE_KEY,
    REPORT_EFFECTIVE_PROFILE_STATE_KEY,
    REPORT_OUTLINE_HASH_STATE_KEY,
    REPORT_OUTLINE_STATE_KEY,
    REPORT_PROFILE_COVERAGE_STATE_KEY,
    REPORT_VISUAL_THEME,
    REPORT_WORKFLOW_RESULT_STATE_KEY,
    REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR,
    REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
    AnalysisReworkRequest,
    Any,
    BaseModel,
    Citation,
    ContextTrace,
    DatasetAnalysisContext,
    DatasetHandle,
    DatasetLineage,
    DetailedAnalysisPlan,
    DeterministicAnalysisBundle,
    DurableReportingPhase,
    FileIdentity,
    Mapping,
    ProfileCoverageManifest,
    QueryRequirement,
    ReportArtifactManifest,
    ReportingCheckpoint,
    ReportingCommand,
    ReportingError,
    ReportingStateError,
    ReportOutline,
    RunContext,
    Sequence,
    StepInput,
    StepOutput,
    TaskExecutionScope,
    TaskState,
    ValidationError,
    WorkspaceService,
    ZoneInfo,
    _frozen_outline,
    _payload_sha256,
    _report_machine_terms,
    _reporting_observed_data_facts,
    _source_warnings_from_state,
    anyio,
    authoritative_citations,
    build_deterministic_analysis_bundle,
    build_report_artifact_validation_context,
    build_report_phase_acceptance_contract,
    cast,
    date,
    datetime,
    hashlib,
    json,
    loguru_logger,
    partial,
    payload_sha256,
    re,
    reporting_phase_task_key,
    time,
    validate_metric_code_bindings,
)
from .code_generation import (
    CodeGenerationResult,
    ReportingCodeGenerationRunner,
    _code_failure_kind,
)
from .datasets import _profile_coverage_instruction_projection
from .phase_models import ChartDraft, VisualizationPlanDraft
from .reporting_draft_workflow import ReportingAnalysisAndDraftWorkflow
from .visualization_section_workflow import (
    VisualizationSectionWorkflow,
    _visualization_thinking_complexity,
)

__all__ = ["RuntimeAnalysisMixin"]


_ANALYSIS_THINKING_BUDGETS = {"simple": 1024, "standard": 2048, "complex": 4096}
_CODING_SCRIPT_MAX_BYTES = 4 * 1024 * 1024
_ANALYSIS_SCRIPT_MAX_BYTES = _CODING_SCRIPT_MAX_BYTES
_VISUALIZATION_SCRIPT_MAX_BYTES = _CODING_SCRIPT_MAX_BYTES
_ANALYSIS_EVIDENCE_RETRY_REASONS = frozenset(
    {"evidence_incomplete", "fact_incomplete", "evidence_binding"}
)


async def _record_successful_repair(
    knowledge_index: ReportingKnowledgeIndex | None,
    *,
    workspace_key: str | None,
    task_kind: str,
    diagnostic: Mapping[str, Any],
    script_file: FileIdentity,
) -> None:
    """知识写入失败只降级为日志，不能回滚已经 accepted 的领域结果。"""

    error_code = diagnostic.get("code")
    if (
        knowledge_index is None
        or not isinstance(workspace_key, str)
        or not workspace_key
        or not isinstance(error_code, str)
        or not error_code
    ):
        return
    summary = f"修复 {error_code} 后，正式领域验收已通过。"
    try:
        await knowledge_index.record_successful_repair(
            workspace_key=workspace_key,
            task_kind=task_kind,
            error_code=error_code,
            source_sha256=script_file.sha256,
            summary=summary,
        )
    except Exception as error:
        loguru_logger.bind(
            task_kind=task_kind,
            error_code=error_code,
            error_type=type(error).__name__,
        ).warning("report_knowledge_repair_record_failed")


def _analysis_summary_input_token_budget(agent: Any, run_context: RunContext) -> int:
    """按最终路由模型的已验证窗口收敛摘要请求预算。"""

    model = getattr(agent, "model", None)
    configured_cap = REPORTING_ANALYSIS_INPUT_TOKEN_HARD_CAP
    for owner in (model, agent):
        value = getattr(owner, "_task_execution_input_token_budget", None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            configured_cap = min(configured_cap, value)
            break
    route = reporting_model_route_from_run_context(run_context)
    model_id = route[1] if route is not None else getattr(model, "id", None)
    model_output_reserve = getattr(model, "max_tokens", None)
    hard_cap = resolve_reporting_input_token_hard_cap(
        configured_input_token_cap=configured_cap,
        model_id=model_id if isinstance(model_id, str) else None,
        output_token_reserve=max(
            TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
            (
                model_output_reserve
                if isinstance(model_output_reserve, int)
                and not isinstance(model_output_reserve, bool)
                and model_output_reserve > 0
                else 0
            ),
        ),
        absolute_input_token_cap=(
            TASK_EXECUTION_CONTEXT_TOKEN_LIMIT - TASK_EXECUTION_OUTPUT_TOKEN_RESERVE
        ),
    )
    # 预留四分之一给 provider wire 方言、纠错指令与 tokenizer 版本差异。
    return hard_cap * 3 // 4


def _prepare_analysis_summary_request(
    payload: Mapping[str, Any],
    *,
    analysis_id: str,
    agent: Any,
    run_context: RunContext,
) -> dict[str, Any]:
    """在模型调用前把完整证据投影为受预算约束、可守恒审计的摘要视图。"""

    request = {
        **payload,
        "analysisBlock": {"blockId": f"{analysis_id}:summary"},
    }
    model = getattr(agent, "model", None)
    counting_model = copy(model) if model is not None else None
    route = reporting_model_route_from_run_context(run_context)
    if counting_model is not None and route is not None:
        counting_model.id = route[1]
    model_count_tokens = getattr(counting_model, "count_tokens", None)
    get_system_message = getattr(agent, "get_system_message", None)
    tokenizer_failed = False

    def count_tokens(candidate: Mapping[str, Any]) -> int:
        nonlocal tokenizer_failed
        serialized = json.dumps(
            candidate,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        if not tokenizer_failed:
            try:
                if not callable(model_count_tokens):
                    raise TypeError("model 缺少 count_tokens")
                messages: list[Message] = []
                if callable(get_system_message):
                    system_message = get_system_message(
                        session=AgentSession(
                            session_id=f"analysis-summary-budget:{analysis_id}",
                            agent_id=getattr(agent, "id", None),
                        ),
                        run_context=None,
                        tools=[],
                        add_session_state_to_context=False,
                        input=serialized,
                    )
                    if system_message is not None:
                        messages.append(system_message)
                messages.append(Message(role="user", content=serialized))
                token_count = model_count_tokens(
                    messages,
                    output_schema=AnalysisSummaryDraft,
                )
                if (
                    isinstance(token_count, bool)
                    or not isinstance(token_count, int)
                    or token_count < 1
                ):
                    raise TypeError("count_tokens 未返回正整数")
                return token_count
            except Exception as error:
                # tokenizer 是优化边界，不能成为绕过 hard cap 的降级开关；
                # UTF-8 字节数对中英文 JSON 均高估 token，作为确定性失败关闭后备。
                tokenizer_failed = True
                loguru_logger.bind(
                    analysis_id=analysis_id,
                    error_type=type(error).__name__,
                ).warning("report_analysis_summary_tokenizer_fallback")
        return len(serialized.encode("utf-8"))

    return _project_analysis_summary_payload(
        request,
        max_tokens=_analysis_summary_input_token_budget(agent, run_context),
        count_tokens=count_tokens,
    )


def visualization_read_paths(facts: list[dict[str, Any]]) -> tuple[str, ...]:
    """返回图表任务投影中冻结证据的读取路径。"""
    sources = [item["factFile"] for item in facts]
    sources.extend(
        source["sourceFile"]
        for item in facts
        for source in item.get("supplementalEvidenceSources", ())
    )
    return tuple(sorted({FileIdentity.model_validate(source).path for source in sources}))


def _bound_collection_items(
    values: object, data_paths: set[str], *, prefix: str, index_key: str
) -> list[Any]:
    if not isinstance(values, (list, tuple)):
        return []
    indices = {
        int(path[len(prefix) :].split("]", 1)[0])
        for path in data_paths
        if path.startswith(prefix)
        and path[len(prefix) :].split("]", 1)[0].isdigit()
    }
    return [
        value
        for value in values
        if isinstance(value, Mapping) and value.get(index_key) in indices
    ]


def visualization_coding_facts(
    facts: list[dict[str, Any]], *, plan: VisualizationPlanDraft | None = None
) -> list[dict[str, Any]]:
    """仅向 Coding 投影数据定位描述，排除规划阶段叙述与重复身份。"""

    keys = (
        "analysisId",
        "factFile",
        "dataPathBase",
        "dataDescriptors",
        "metrics",
        "derivedMetrics",
        "comparisons",
        "supplementalEvidenceSources",
    )
    projected = [
        {
            key: item[key]
            for key in keys
            if key in item and item[key] not in (None, [], {})
        }
        for item in facts
    ]
    if plan is None:
        return projected

    bindings: dict[tuple[str, str], set[str]] = {}
    for chart in plan.charts:
        for binding in chart.data_bindings:
            bindings.setdefault(
                (binding.analysis_id, binding.fact_path), set()
            ).add(binding.data_path)

    compact: list[dict[str, Any]] = []
    for item in projected:
        analysis_id = item.get("analysisId")
        fact_file = item.get("factFile")
        fact_path = fact_file.get("path") if isinstance(fact_file, Mapping) else None
        main_paths = bindings.get((analysis_id, fact_path), set())
        sources: list[dict[str, Any]] = []
        for source in item.get("supplementalEvidenceSources", ()):
            if not isinstance(source, Mapping):
                continue
            source_file = source.get("sourceFile")
            source_path = (
                source_file.get("path") if isinstance(source_file, Mapping) else None
            )
            source_paths = bindings.get((analysis_id, source_path), set())
            if not source_paths:
                continue
            filtered_source = {
                key: source[key]
                for key in ("sourceFile", "dataPathBase")
                if key in source
            }
            filtered_source["dataDescriptors"] = [
                descriptor
                for descriptor in source.get("dataDescriptors", ())
                if isinstance(descriptor, Mapping)
                and descriptor.get("dataPath") in source_paths
            ]
            findings = _bound_collection_items(
                source.get("findings"),
                source_paths,
                prefix="findings[",
                index_key="findingIndex",
            )
            if findings:
                filtered_source["findings"] = findings
            sources.append(filtered_source)
        if not main_paths and not sources:
            continue
        filtered = {
            key: item[key]
            for key in ("analysisId", "factFile", "dataPathBase")
            if key in item
        }
        if main_paths:
            filtered["dataDescriptors"] = [
                descriptor
                for descriptor in item.get("dataDescriptors", ())
                if isinstance(descriptor, Mapping)
                and descriptor.get("dataPath") in main_paths
            ]
            for key, prefix, index_key in (
                ("metrics", "metrics[", "metricIndex"),
                ("derivedMetrics", "derivedMetrics[", "derivedMetricIndex"),
                ("comparisons", "comparisons[", "comparisonIndex"),
            ):
                values = _bound_collection_items(
                    item.get(key), main_paths, prefix=prefix, index_key=index_key
                )
                if values:
                    filtered[key] = values
        if sources:
            filtered["supplementalEvidenceSources"] = sources
        compact.append(filtered)
    return compact


def visualization_coding_plan(
    plan: VisualizationPlanDraft,
    *,
    benchmark_projection: BenchmarkProjection | None = None,
) -> dict[str, Any]:
    """投影图表计划；legacy 只隐藏 R7 字段，生产默认保持完整计划。"""

    projection = benchmark_projection or BenchmarkProjection.for_variant(
        BenchmarkVariant.CANDIDATE
    )
    payload = plan.model_dump(mode="json", by_alias=True)
    if projection.include_visual_bindings:
        return payload
    for chart in payload.get("charts", ()):
        if isinstance(chart, dict):
            chart.pop("visualForm", None)
            chart.pop("dataBindings", None)
    return payload


def _validate_analysis_benchmark_planner(
    projection: BenchmarkProjection | None,
    planner: Any | None,
    output_type: type[BaseModel],
) -> None:
    if projection is None or projection.variant is not BenchmarkVariant.LEGACY:
        return
    if planner is None or output_type is not LegacyAnalysisEvidenceDecision:
        raise ReportingError(
            "report_phase_contract_invalid",
            "legacy 分析 benchmark 必须在 planner 请求前显式提供旧 planner 与旧 schema。",
        )


def _validate_visualization_benchmark_planner(
    projection: BenchmarkProjection | None,
    planner: Any | None,
    output_type: type[BaseModel],
    adapter: Callable[[BaseModel, Mapping[str, Any]], VisualizationPlanDraft] | None,
) -> None:
    if projection is None or projection.variant is not BenchmarkVariant.LEGACY:
        return
    if (
        planner is None
        or output_type is not LegacyVisualizationPlanDraft
        or adapter is None
    ):
        raise ReportingError(
            "report_phase_contract_invalid",
            "legacy 可视化 benchmark 必须在 planner 请求前显式提供旧 planner、旧 schema 和 adapter。",
        )


def adapt_legacy_visualization_plan(
    plan: LegacyVisualizationPlanDraft,
    decisions_by_chart_id: Mapping[str, Mapping[str, Any]],
) -> VisualizationPlanDraft:
    """用冻结验收决策映射 legacy 计划；这些 R7 字段不会投影给 legacy Coding。"""

    chart_ids = {chart.chart_id for chart in plan.charts}
    if set(decisions_by_chart_id) != chart_ids:
        raise ReportingError(
            "report_phase_contract_invalid",
            "legacy 可视化计划与冻结图表验收身份不一致。",
        )
    charts = []
    for chart in plan.charts:
        decision = decisions_by_chart_id[chart.chart_id]
        visual_form = decision.get("visualForm")
        data_bindings = decision.get("dataBindings")
        if (
            not isinstance(visual_form, str)
            or not visual_form.strip()
            or not isinstance(data_bindings, (list, tuple))
            or not data_bindings
        ):
            raise ReportingError(
                "report_phase_contract_invalid",
                "legacy 可视化图表缺少冻结验收绑定。",
            )
        charts.append(
            {
                **chart.model_dump(mode="json", by_alias=True),
                "visualForm": visual_form,
                "dataBindings": data_bindings,
            }
        )
    try:
        return VisualizationPlanDraft.model_validate(
            {
                "charts": charts,
                "warnings": list(plan.warnings),
            }
        )
    except ValidationError as error:
        raise ReportingError(
            "report_phase_contract_invalid",
            "legacy 可视化计划无法映射到冻结验收契约。",
        ) from error


def _visualization_instruction_theme() -> dict[str, Any]:
    return {
        **REPORT_VISUAL_THEME,
        "chartPalette": list(REPORT_VISUAL_THEME["chartPalette"]),
    }


def _visualization_output_paths(plan: VisualizationPlanDraft) -> tuple[str, ...]:
    return tuple(
        sorted(
            path
            for chart in plan.charts
            for path in (chart.source_path, chart.interactive_path)
            if path is not None
        )
    )


def _visualization_registration_payload(chart: ChartDraft) -> dict[str, Any]:
    """仅提交交付注册字段，规划到 Coding 的决策字段不进入归档契约。"""

    return chart.model_dump(
        mode="json",
        by_alias=True,
        exclude={"visual_form", "data_bindings"},
    )


def _analysis_item_dataset_inputs(
    handles: Sequence[DatasetHandle],
    contexts: Sequence[DatasetAnalysisContext],
) -> list[dict[str, Any]]:
    """把每个签发 CSV 与其权威 Profile 字段精确绑定后投影给模型。"""

    context_by_id = {item.dataset_id: item for item in contexts}
    if len(context_by_id) != len(contexts):
        raise ReportingError(
            "report_analysis_context_unavailable",
            "分析数据上下文包含重复 Dataset 身份。",
        )
    inputs: list[dict[str, Any]] = []
    for handle in handles:
        context = context_by_id.get(handle.dataset_id)
        # 路径、大小、哈希和行数共同构成 Profile 与不可变 CSV 的绑定；任何一项
        # 不一致都必须失败关闭，不能把其他 Dataset 的字段暴露给补证脚本规划器。
        if context is None or (
            context.path,
            context.size,
            context.sha256,
            context.row_count,
        ) != (
            handle.path,
            handle.size,
            handle.sha256,
            handle.row_count,
        ):
            raise ReportingError(
                "report_analysis_context_unavailable",
                "分析数据上下文没有精确绑定当前不可变 Dataset。",
            )
        field_types = {item.name: item.inferred_type for item in context.field_stats}
        dataset_input = {
            **handle.public_dict(),
            "format": "csv",
            "hasHeader": True,
            "columns": list(context.fields),
        }
        if set(field_types) == set(context.fields):
            dataset_input["columnTypes"] = {
                field: field_types[field] for field in context.fields
            }
        inputs.append(dataset_input)
    return inputs


def _analysis_item_output_root(report_run_id: str, analysis_id: str, attempt: int) -> str:
    """为 fresh attempt 签发独立目录，避免失败脚本污染后续重试。"""

    return f"报表/智能分析/{report_run_id}/evidence/{analysis_id}/attempt-{attempt + 1}"


def _analysis_item_complexity(
    plan: Mapping[str, Any],
) -> tuple[int, Literal["simple", "standard", "complex"]]:
    """仅根据已校验分析计划字段计算复杂度，避免从自然语言猜测预算。"""

    def _count(name: str) -> int:
        value = plan.get(name)
        return (
            len(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else 0
        )

    score = max(0, _count("datasetIds") - 1) * 3
    score += min(2, max(0, _count("metrics") - 1))
    score += 2 if _count("comparisonBasis") else 0
    organization_grain_count = _count("organizationGrain")
    score += 2 if organization_grain_count >= 2 else organization_grain_count
    score += max(0, _count("actions") - 2)
    tier: Literal["simple", "standard", "complex"] = (
        "simple" if score <= 2 else "standard" if score <= 5 else "complex"
    )
    return score, tier


def _analysis_item_thinking_policy(
    plan: Mapping[str, Any], *, retry: bool, retry_reason: str | None
) -> tuple[Literal["high", "max"], int, Literal["simple", "standard", "complex"]]:
    """返回 thinking 档位、预算和复杂度；固定五阶段不再按请求次数截断。"""

    _, tier = _analysis_item_complexity(plan)
    if retry and _analysis_evidence_failure_kind(retry_reason) is not None:
        return "max", 6144, tier
    return "high", _ANALYSIS_THINKING_BUDGETS[tier], tier


def _analysis_evidence_failure_kind(reason: str | None) -> ThinkingFailureKind | None:
    normalized = (reason or "").lower()
    if "fact_incomplete" in normalized:
        return "fact_incomplete"
    if normalized in _ANALYSIS_EVIDENCE_RETRY_REASONS or "evidence_incomplete" in normalized:
        return "evidence_incomplete"
    return None


_MODEL_FACT_IDENTITY_KEYS = frozenset(
    {
        "datasetSha256",
        "datasetSha256s",
        "profileHash",
        "currentDatasetSha256",
        "baselineDatasetSha256",
    }
)
_MODEL_FACT_WARNING_COLLECTIONS = (
    "metrics",
    "derivedMetrics",
    "comparisons",
    "reconciliations",
)


def _model_facing_deterministic_facts(
    bundle: DeterministicAnalysisBundle,
) -> dict[str, Any]:
    """投影模型所需事实，隐藏校验元数据并去重重复告警。

    哈希、文件大小和路径属于服务端身份校验边界，完整 bundle 仍写入不可变 facts
    文件；模型只需要业务事实和可读的告警文本。相同告警可能同时出现在多个指标、
    比较和汇总层，模型输入只保留首次出现的位置，避免重复消耗上下文预算。
    """

    projected = bundle.model_dump(mode="json", by_alias=True)
    seen_warnings: set[str] = set()
    for collection_key in _MODEL_FACT_WARNING_COLLECTIONS:
        collection = projected.get(collection_key)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            for key in _MODEL_FACT_IDENTITY_KEYS:
                item.pop(key, None)
            warnings = item.get("warnings")
            if not isinstance(warnings, list):
                continue
            unique = []
            for warning in warnings:
                if not isinstance(warning, str) or warning in seen_warnings:
                    continue
                seen_warnings.add(warning)
                unique.append(warning)
            item["warnings"] = unique

    warnings = projected.get("warnings")
    if isinstance(warnings, list):
        unique = []
        for warning in warnings:
            if not isinstance(warning, str) or warning in seen_warnings:
                continue
            seen_warnings.add(warning)
            unique.append(warning)
        projected["warnings"] = unique
    correlations = projected.get("correlations")
    if isinstance(correlations, dict) and correlations:
        # 相关性键包含完整 datasetId 和两个字段名；在数十个指标时会重复数百次。
        # 只压缩模型投影，原始 facts 文件仍保留旧的可直接寻址字典，避免破坏回放和引用。
        datasets: list[str] = []
        dataset_indexes: dict[str, int] = {}
        rows: list[list[Any]] = []
        for raw_key, value in correlations.items():
            if not isinstance(raw_key, str) or not isinstance(value, (int, float)):
                continue
            dataset_id, separator, fields = raw_key.partition(":")
            left, pair_separator, right = fields.partition("~")
            if not separator or not pair_separator or not dataset_id or not left or not right:
                rows.append([raw_key, value])
                continue
            dataset_index = dataset_indexes.get(dataset_id)
            if dataset_index is None:
                dataset_index = len(datasets)
                datasets.append(dataset_id)
                dataset_indexes[dataset_id] = dataset_index
            rows.append([dataset_index, left, right, value])
        if rows and all(len(row) == 4 for row in rows):
            projected["correlations"] = {
                "datasets": datasets,
                "columns": ["dataset", "left", "right", "value"],
                "rows": rows,
            }
    return projected


def _analysis_fact_query_limit_for_plan(analysis_plan: Mapping[str, Any]) -> int:
    """按当前分析项复杂度分配事实查询额度，并保留硬上限。"""

    metrics = analysis_plan.get("metrics") if isinstance(analysis_plan, Mapping) else None
    datasets = analysis_plan.get("datasetIds") if isinstance(analysis_plan, Mapping) else None
    periods = analysis_plan.get("periods") if isinstance(analysis_plan, Mapping) else None
    complexity = sum(
        len(value) for value in (metrics, datasets, periods) if isinstance(value, (list, tuple))
    )
    return min(8, max(4, 2 + (complexity + 2) // 3))


class RuntimeAnalysisMixin:
    async def _run_visualization_section_task(
        self,
        section_code: str,
        *,
        context: Mapping[str, Any] | None = None,
        benchmark_projection: BenchmarkProjection | None = None,
        visualization_planner: Any | None = None,
        visualization_output_type: type[BaseModel] = VisualizationPlanDraft,
        visualization_plan_adapter: Callable[
            [BaseModel, Mapping[str, Any]], VisualizationPlanDraft
        ]
        | None = None,
    ) -> None:
        """执行单章可视化 Agent；章节草案由 durable submit 工具作为唯一完成信号。

        失败按 sectionCode 记入 checkpoint 账本并驱动同章 fresh retry(上限
        MAX_REPORT_SECTION_PHASE_ATTEMPTS);重试章继承已消耗预算并关闭探索
        (visualizationRecovery),已完成章由入口 durable 判定直接跳过。
        """
        context = context or self._visualization_context
        _validate_visualization_benchmark_planner(
            benchmark_projection,
            visualization_planner,
            visualization_output_type,
            visualization_plan_adapter,
        )
        run_context = context["run_context"]
        checkpoint = await self._current_reporting_checkpoint(run_context, context["checkpoint"])
        outline = _frozen_outline(self._state(run_context))
        section = next((item for item in outline.sections if item.code == section_code), None)
        if section is None:
            raise ReportingError("report_visualization_section_invalid", "提纲中不存在当前章节。")
        durable = await self.state_repository.get(
            str(run_context.run_id or context["external_run_id"])
        )
        payload = durable.payload if durable is not None else {}
        completed = payload.get("completedVisualizationSections", ())
        if section_code in completed:
            return
        analysis_items = payload.get("analysisItems", {})
        facts = []
        section_analysis_items: dict[str, Mapping[str, Any]] = {}
        section_fact_files: dict[str, FileIdentity] = {}
        section_warnings: list[str] = []
        for analysis_id in section.analysis_ids:
            fact_file = context["fact_files"].get(analysis_id)
            durable_item = (
                analysis_items.get(analysis_id) if isinstance(analysis_items, Mapping) else None
            )
            if fact_file is None or not isinstance(durable_item, Mapping):
                section_warnings.append(
                    f"analysisId {analysis_id} 缺少冻结 facts 或 durable 分析项"
                )
                continue
            facts.append(
                await self._visualization_section_fact_projection(
                    analysis_id, fact_file, durable_item, thread_id=context["thread_id"]
                )
            )
            section_analysis_items[analysis_id] = durable_item
            section_fact_files[analysis_id] = fact_file
        if not section_fact_files:
            loguru_logger.warning(
                f"report_visualization_section_warning section_code={section_code} "
                f"warnings={section_warnings}"
            )
            if section_warnings:
                await self._apply_durable_command(
                    run_context,
                    ReportingCommand(
                        name="record_warnings",
                        commandId=(
                            f"visualization-warning:{context['revision']}:{section_code}:"
                            f"{payload_sha256(section_warnings)}"
                        ),
                        payload={
                            "warnings": [
                                {
                                    "code": "visualization_section_warning",
                                    "message": warning,
                                    "sectionCode": section_code,
                                }
                                for warning in section_warnings
                            ]
                        },
                    ),
                )
            return
        # 按章动态预算以该章 analysisIds 的 evidence/fact 文件为基数,与全局汇总预算
        # 同构但互不共享;TaskRunner 解析(visualizationBudgetVersion 等 10 个标量)
        # 缺一即拒绝,因此必须整组注入 acceptance contract。
        section_budget = _visualization_dynamic_budget(section_analysis_items, section_fact_files)
        allowed_dataset_ids = tuple(
            dict.fromkeys(
                dataset_id
                for item in section_analysis_items.values()
                for dataset_id in item.get("datasetIds", ())
                if isinstance(dataset_id, str) and dataset_id
            )
        )
        last_error: Exception | None = _visualization_section_retry_error(
            checkpoint, section_code=section_code
        )
        matching = [
            item
            for item in checkpoint.trace
            if item.phase == "analysis"
            and item.work_kind == "visualization_section"
            and item.section_code == section_code
        ]
        next_attempt = max((item.attempt for item in matching), default=-1) + 1
        max_attempts = MAX_REPORT_SECTION_PHASE_ATTEMPTS * (
            MAX_REPORT_ANALYSIS_REWORKS_PER_SECTION + 1
        )
        if next_attempt >= max_attempts:
            raise ReportingError(
                "report_visualization_section_attempts_exhausted",
                "章节图表 fresh attempt 已达到上限，拒绝创建新的 Task。",
            )
        scope = self._scope(run_context)
        for attempt in range(next_attempt, max_attempts):
            root = f"报表/智能分析/{run_context.run_id}/analysis/charts/{section_code}/attempt-{attempt + 1}"
            task_id = reporting_phase_task_key(
                str(run_context.run_id or "report"),
                context["revision"],
                "analysis",
                section_code=section_code,
                task_kind="visualization_section",
                attempt=attempt,
            )
            script_path = f"{root}/charts.py"
            try:
                envelope = self._envelope(run_context)
                report_goal = envelope.report_goal
                visualization_mode = envelope.visualization_mode
            except ReportingError:
                report_goal = ""
                visualization_mode = "auto"
            instruction_payload = {
                "phase": "analysis",
                "taskKind": "visualization_section",
                "reportGoal": report_goal,
                "visualizationMode": visualization_mode,
                "sectionCode": section_code,
                "section": section.model_dump(mode="json", by_alias=True),
                "sectionGoal": {
                    "sectionCode": section.code,
                    "title": section.title,
                    "focus": list(section.focus),
                    "analysisIds": list(section.analysis_ids),
                },
                "analysisIds": list(section.analysis_ids),
                "allowedDatasetIds": list(allowed_dataset_ids),
                "warnings": section_warnings,
                "visualInspectionMode": context["visual_inspection_mode"],
                "reportVisualTheme": _visualization_instruction_theme(),
                "visualizationFacts": facts,
                "visualizationWorkspace": {
                    "scriptPath": script_path,
                    "chartOutputRoot": root,
                },
                "completionConditions": _visualization_section_completion_conditions(last_error),
            }
            instruction = json.dumps(instruction_payload, ensure_ascii=False, separators=(",", ":"))
            if len(instruction.encode("utf-8")) > MAX_REPORT_INSTRUCTION_BYTES:
                raise ReportingError(
                    "report_analysis_context_too_large", "单章可视化投影超过输入边界。"
                )
            contract = build_report_phase_acceptance_contract(
                phase="analysis",
                validation_context_file=context["validation_context_file"].model_dump(
                    mode="json", by_alias=True
                ),
                phase_contract={
                    "reportRunId": str(run_context.run_id or context["external_run_id"]),
                    "taskKind": "visualization_section",
                    "sectionCode": section_code,
                    "analysisIds": list(section.analysis_ids),
                    "allowedDatasetIds": list(allowed_dataset_ids),
                    "visualInspectionMode": context["visual_inspection_mode"],
                    "visualizationMode": visualization_mode,
                    "visualizationRecovery": _visualization_recovery_required(last_error),
                    **section_budget,
                    **_visualization_retry_usage(last_error),
                    "visualizationWorkspace": {
                        "scriptPath": script_path,
                        "chartOutputRoot": root,
                    },
                },
                analysis_output_path=f"{root}/section.json",
            )
            task_scope = TaskExecutionScope(
                task_id,
                scope["userId"],
                scope["threadId"],
                context["sandbox_id"],
                "reporting-visualization-agent",
            )
            checkpoint = self._update_reporting_checkpoint(
                checkpoint,
                trace=(
                    *checkpoint.trace,
                    ContextTrace(
                        phase="analysis",
                        taskId=task_id,
                        workKind="visualization_section",
                        sectionCode=section_code,
                        attempt=attempt,
                        instructionBytes=len(instruction.encode("utf-8")),
                        projectedContextBytes=len(instruction.encode("utf-8")),
                        visualInspectionMode=context["visual_inspection_mode"],
                    ),
                ),
            )
            await self._persist_reporting_checkpoint(run_context, checkpoint)
            try:
                existing = await self.task_runner.repository.get_task_snapshot(task_id)
                if existing is None:
                    await self.task_runner.start(
                        task_scope, instruction, acceptance_contract=contract
                    )
                elif existing.state in {TaskState.FAILED, TaskState.CANCELLED}:
                    raise ReportingError(
                        "report_visualization_section_task_terminal",
                        "章节图表 Task 未完成收尾即终止。",
                    )
                if self.visualization_generator is None:
                    raise ReportingError(
                        "report_visualization_executor_missing",
                        "章节图表结构化生成器未配置。",
                    )

                async def execute_fixed_visualization(
                    invocation: ReportingTaskInvocation,
                ) -> VisualizationPlanDraft:
                    toolkits = build_reporting_tools(
                        self.workspace_service,
                        self.task_runner.repository,
                        state_repository=self.state_repository,
                        run_context=invocation.run_context,
                        vision_reviewer=self.vision_reviewer,
                    )
                    if len(toolkits) != 1:
                        raise ReportingError(
                            "report_phase_contract_invalid", "章节图表 Toolkit 装配结果无效。"
                        )
                    toolkit = toolkits[0]
                    repair_workspace_key: str | None = None
                    knowledge_index = getattr(self, "knowledge_index", None)
                    code_runner_instance: ReportingCodeGenerationRunner | None = None
                    planner_metrics_recorder = (
                        invocation.model_metrics_settlement.stage_recorder(
                            "planner", agent_role="visualization-planner"
                        )
                    )
                    coding_metrics_recorder = (
                        invocation.model_metrics_settlement.stage_recorder(
                            "coding", agent_role="visualization-coding"
                        )
                    )

                    async def generate_plan(
                        request: Mapping[str, Any], task_context: RunContext
                    ) -> VisualizationPlanDraft:
                        payload = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
                        thinking_request = ThinkingRequest(
                            operation="visualization_plan",
                            complexity=_visualization_thinking_complexity(request),
                            configured_budget_cap=self._analysis_thinking_budget_cap,
                            thinking_enabled=self._analysis_thinking_enabled,
                        )
                        output = await ReportingStructuredOutputExecutor(
                            visualization_planner or self.visualization_generator
                        ).run(
                            payload,
                            scope=invocation.scope,
                            run_context=task_context,
                            thinking_request=thinking_request,
                            model_metrics_recorder=planner_metrics_recorder,
                        )
                        if not isinstance(output, visualization_output_type):
                            raise ReportingError(
                                "report_structured_output_invalid",
                                "可视化 planner 返回了错误的 benchmark 输出类型。",
                            )
                        if visualization_plan_adapter is not None:
                            return visualization_plan_adapter(output, request)
                        if not isinstance(output, VisualizationPlanDraft):
                            raise ReportingError(
                                "report_structured_output_invalid",
                                "可视化 planner 返回了错误的结构化结果类型。",
                            )
                        return output

                    def code_runner() -> ReportingCodeGenerationRunner:
                        nonlocal code_runner_instance
                        if self.visualization_code_agent_factory is None:
                            raise ReportingError(
                                "report_visualization_code_agent_missing",
                                "章节图表代码 Agent 未配置。",
                            )
                        if self.code_mode_runtime is None:
                            raise ReportingError(
                                "report_code_mode_runtime_missing",
                                "章节图表 CodeMode runtime 未配置。",
                            )
                        if code_runner_instance is None:
                            code_runner_instance = ReportingCodeGenerationRunner(
                                self.visualization_code_agent_factory,
                                self.code_mode_runtime,
                                registry=self.coding_task_registry,
                                knowledge_index=knowledge_index,
                                lsp_manager=getattr(self, "lsp_manager", None),
                                vision_reviewer=self.vision_reviewer,
                                model_metrics_recorder=coding_metrics_recorder,
                                compact_continuation=True,
                            )
                        return code_runner_instance

                    async def run_code(
                        plan: VisualizationPlanDraft,
                        task_context: RunContext,
                        *,
                        diagnostic: Mapping[str, Any] | None,
                        task_facts: Mapping[str, Any] | None = None,
                        benchmark_projection: BenchmarkProjection | None = None,
                    ) -> CodeGenerationResult:
                        nonlocal repair_workspace_key
                        binding = (
                            task_context.dependencies.get("AgentOS 任务执行")
                            if isinstance(task_context.dependencies, Mapping)
                            else None
                        )
                        coding_task_id = (
                            binding.get("externalRunId")
                            if isinstance(binding, Mapping)
                            else None
                        ) or task_id
                        parent_scope = self._scope(run_context)
                        task_workspace = self.workspace_for(
                            run_id=str(run_context.run_id or ""),
                            session_id=str(run_context.session_id or ""),
                            user_id=str(run_context.user_id or "") or None,
                            dependencies=(
                                dict(run_context.dependencies)
                                if isinstance(run_context.dependencies, Mapping)
                                else None
                            ),
                            stored_scope=parent_scope,
                        )
                        declared_outputs = _visualization_output_paths(plan)
                        coding_context = ReportingCodingTaskContext(
                            task_id=str(coding_task_id),
                            task_kind="visualization",
                            code_mode_session_id=f"visualization:{coding_task_id}",
                            workspace_key=task_workspace.identity.workspace_key,
                            workspace_root=task_workspace.identity.root,
                            script_path=script_path,
                            authorized_read_paths=visualization_read_paths(facts),
                            authorized_write_paths=(script_path, *declared_outputs),
                            declared_output_paths=declared_outputs,
                            max_source_bytes=_VISUALIZATION_SCRIPT_MAX_BYTES,
                        )
                        repair_workspace_key = coding_context.workspace_key
                        if benchmark_projection is not None and not isinstance(
                            benchmark_projection, BenchmarkProjection
                        ):
                            raise ReportingError(
                                "report_phase_contract_invalid",
                                "可视化 benchmark projection 类型无效。",
                            )
                        facts_payload = {
                            "visualizationMode": visualization_mode,
                            "visualizationFacts": visualization_coding_facts(
                                facts,
                                plan=(
                                    plan
                                    if benchmark_projection is None
                                    or benchmark_projection.include_visual_bindings
                                    else None
                                ),
                            ),
                            "visualizationWorkspace": instruction_payload[
                                "visualizationWorkspace"
                            ],
                            "visualizationPlan": visualization_coding_plan(
                                plan, benchmark_projection=benchmark_projection
                            ),
                            **dict(task_facts or {}),
                        }
                        return await code_runner().run(
                            coding_context,
                            task_workspace,
                            facts_payload,
                            run_context=task_context,
                            diagnostic=diagnostic,
                        )

                    async def record_successful_repair(
                        diagnostic: Mapping[str, Any], script_file: FileIdentity
                    ) -> None:
                        await _record_successful_repair(
                            knowledge_index,
                            workspace_key=repair_workspace_key,
                            task_kind="visualization",
                            diagnostic=diagnostic,
                            script_file=script_file,
                        )

                    async def submit(
                        plan: VisualizationPlanDraft,
                        _inspections: tuple[ChartVisualInspectionReceipt, ...],
                        task_context: RunContext,
                    ) -> Mapping[str, Any]:
                        return await toolkit.submit_visualization_charts(
                            section_code,
                            [_visualization_registration_payload(item) for item in plan.charts],
                            run_context=task_context,
                            visual_receipts=tuple(
                                item.model_dump(mode="json", by_alias=True)
                                for item in _inspections
                            ),
                        )

                    async def degrade(
                        error: Exception, task_context: RunContext
                    ) -> Mapping[str, Any]:
                        error_code = str(
                            getattr(error, "code", "report_visualization_section_failed")
                        )
                        error_details = getattr(error, "details", None)
                        details = error_details if isinstance(error_details, Mapping) else {}
                        nested_details = details.get("details")
                        if isinstance(nested_details, Mapping):
                            details = {**details, **nested_details}
                        execution_id = details.get("execution_id", details.get("executionId"))
                        warning_details: dict[str, Any] = {"failureCode": error_code}
                        if isinstance(execution_id, str) and execution_id:
                            warning_details["executionId"] = execution_id
                        for field in ("executionRepairCount", "visualReviewRepairCount"):
                            count = details.get(field)
                            if (
                                isinstance(count, int)
                                and not isinstance(count, bool)
                                and count >= 0
                            ):
                                warning_details[field] = count
                        warning = {
                            "code": "report_visualization_degraded",
                            "message": "章节图表修复后仍失败，已按零图继续成稿。",
                            "sectionCode": section_code,
                            "details": warning_details,
                        }
                        loguru_logger.bind(
                            section_code=section_code,
                            failure_code=error_code,
                            execution_id=execution_id,
                        ).warning("report_visualization_section_degraded")
                        await self._apply_durable_command(
                            run_context,
                            ReportingCommand(
                                name="record_warnings",
                                commandId=(
                                    f"visualization-degraded:{context['revision']}:"
                                    f"{section_code}:{payload_sha256(warning)}"
                                ),
                                payload={"warnings": [warning]},
                            ),
                        )
                        return await toolkit.submit_visualization_charts(
                            section_code, [], run_context=task_context
                        )

                    workflow_kwargs: dict[str, Any] = {
                        "generate_plan": generate_plan,
                        "run_code": run_code,
                        "submit": submit,
                        "degrade": degrade,
                        "thinking_enabled": self._analysis_thinking_enabled,
                        "thinking_budget_cap": self._analysis_thinking_budget_cap,
                        "benchmark_projection": benchmark_projection,
                    }
                    if knowledge_index is not None:
                        workflow_kwargs["record_successful_repair"] = record_successful_repair
                    result = await VisualizationSectionWorkflow(
                        **workflow_kwargs
                    ).run(instruction_payload, invocation.run_context)
                    return result.plan

                await self.task_runner.run(
                    task_scope,
                    parent_run_id=str(run_context.run_id or ""),
                    executor=execute_fixed_visualization,
                )
                latest = await self.state_repository.get(
                    str(run_context.run_id or context["external_run_id"])
                )
                latest_payload = latest.payload if latest is not None else {}
                if section_code not in latest_payload.get("completedVisualizationSections", ()):
                    raise ReportingError(
                        "report_visualization_section_incomplete", "章节图表 durable 收口缺失。"
                    )
                checkpoint = self._replace_trace(checkpoint, task_id, status="completed")
                checkpoint = self._update_reporting_checkpoint(
                    checkpoint,
                    visualization_section_errors={
                        key: value
                        for key, value in checkpoint.visualization_section_errors.items()
                        if key != section_code
                    },
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
                return
            except Exception as error:
                last_error = error
                checkpoint = self._replace_trace(checkpoint, task_id, status="failed")
                checkpoint = self._update_reporting_checkpoint(
                    checkpoint,
                    visualization_section_errors={
                        **checkpoint.visualization_section_errors,
                        section_code: {
                            "phase": "analysis",
                            "code": getattr(error, "code", "report_visualization_section_failed"),
                            "message": str(getattr(error, "message", error))[:2000],
                            "sectionCode": section_code,
                            "taskId": task_id,
                            "workKind": "visualization_section",
                            "attempt": attempt,
                            "retryUsage": _checkpoint_retry_usage(
                                error, work_kind="visualization_section"
                            ).model_dump(mode="json", by_alias=True),
                        },
                    },
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
        assert last_error is not None
        raise last_error

    async def _visualization_section_fact_projection(
        self,
        analysis_id: str,
        fact_file: FileIdentity,
        durable_item: Any,
        *,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        fact_model = await self._read_identity_model(
            thread_id or self._visualization_context["thread_id"],
            fact_file,
            DeterministicAnalysisBundle,
        )
        payload = fact_model.model_dump(mode="json", by_alias=True)
        data_descriptors: list[dict[str, Any]] = []
        for index, metric in enumerate(payload.get("metrics", ())):
            if not isinstance(metric, Mapping):
                continue
            data_descriptors.append(
                {"dataPath": f"metrics[{index}]", "fields": sorted(metric)}
            )
            data_descriptors.extend(
                {
                    "dataPath": f"metrics[{index}].{collection}",
                    "fields": fields,
                }
                for collection, fields in (
                    ("periodValues", ["period", "value"]),
                    ("topGroups", ["group", "value"]),
                    ("bottomGroups", ["group", "value"]),
                )
            )
        data_descriptors.extend(
            {"dataPath": f"derivedMetrics[{index}]", "fields": sorted(metric)}
            for index, metric in enumerate(payload.get("derivedMetrics", ()))
            if isinstance(metric, Mapping)
        )
        data_descriptors.extend(
            {"dataPath": f"comparisons[{index}]", "fields": sorted(item)}
            for index, item in enumerate(payload.get("comparisons", ()))
            if isinstance(item, Mapping)
        )
        supplemental_sources: list[dict[str, Any]] = []
        if isinstance(durable_item, Mapping):
            for raw_identity in durable_item.get("evidenceFiles", ()):
                try:
                    identity = FileIdentity.model_validate(raw_identity)
                except ValidationError as error:
                    raise ReportingError(
                        "report_phase_artifact_invalid", "补充 evidence 文件身份无效。"
                    ) from error
                if identity.path == fact_file.path or not identity.path.endswith(
                    "/supplement.json"
                ):
                    continue
                content = await self._read_identity_bytes(
                    thread_id or self._visualization_context["thread_id"], identity
                )
                try:
                    raw_evidence = json.loads(content)
                    if not isinstance(raw_evidence, dict):
                        raise TypeError("supplement root must be an object")
                    raw_evidence.pop("analysisId", None)
                    raw_evidence.pop("analysis_id", None)
                    raw_evidence.pop("datasetIds", None)
                    raw_evidence.pop("dataset_ids", None)
                    evidence = SupplementalEvidence.model_validate(
                        {
                            **raw_evidence,
                            "analysisId": analysis_id,
                            "datasetIds": durable_item.get("datasetIds"),
                        }
                    )
                except (TypeError, ValueError, ValidationError) as error:
                    raise ReportingError(
                        "report_phase_artifact_invalid", "补充 evidence 结构无效。"
                    ) from error
                findings: list[dict[str, Any]] = []
                supplemental_descriptors: list[dict[str, Any]] = []
                for index, finding in enumerate(evidence.findings):
                    descriptor: dict[str, Any] = {
                        "findingIndex": index,
                        "name": finding.get("name"),
                        "dataPath": f"findings[{index}]",
                        "fields": sorted(finding),
                    }
                    columns = finding.get("columns")
                    rows = finding.get("rows")
                    if isinstance(columns, list) and isinstance(rows, list):
                        nullable_fields = [
                            str(column)
                            for column_index, column in enumerate(columns)
                            if any(
                                isinstance(row, list)
                                and column_index < len(row)
                                and row[column_index] is None
                                for row in rows
                            )
                        ]
                        descriptor.update(
                            {
                                "columns": columns,
                                "rowsDataPath": f"findings[{index}].rows",
                                "rowEncoding": "columns_rows",
                                "rowCount": len(rows),
                                **({"nullableFields": nullable_fields} if nullable_fields else {}),
                            }
                        )
                    findings.append(descriptor)
                    supplemental_descriptors.append(
                        {
                            "dataPath": f"findings[{index}]",
                            "fields": sorted(finding),
                        }
                    )
                    if isinstance(columns, list) and isinstance(rows, list):
                        supplemental_descriptors.append(
                            {
                                "dataPath": f"findings[{index}].rows",
                                "fields": columns,
                            }
                        )
                supplemental_sources.append(
                    {
                        "sourceFile": identity.model_dump(mode="json", by_alias=True),
                        "dataPathBase": "fileRoot",
                        "findings": findings,
                        "dataDescriptors": supplemental_descriptors,
                    }
                )
        return {
            "analysisId": analysis_id,
            "factFile": fact_file.model_dump(mode="json", by_alias=True),
            "dataPathBase": "fileRoot",
            "dataDescriptors": data_descriptors,
            "summary": durable_item.get("summary") if isinstance(durable_item, Mapping) else None,
            "metrics": [
                {
                    "metricIndex": index,
                    **{
                        key: metric.get(key)
                        for key in (
                            "datasetId",
                            "field",
                            "metricCodes",
                            "aggregation",
                            "unit",
                            "scope",
                            "periodRoles",
                            "periodStart",
                            "periodEnd",
                            "total",
                        )
                    },
                    "periodValueCount": len(metric.get("periodValues", ())),
                    "periodValueFields": ["period", "value"],
                    "topGroupCount": len(metric.get("topGroups", ())),
                    "bottomGroupCount": len(metric.get("bottomGroups", ())),
                    "dataPaths": {
                        "metric": f"metrics[{index}]",
                        "periodValues": f"metrics[{index}].periodValues",
                        "topGroups": f"metrics[{index}].topGroups",
                        "bottomGroups": f"metrics[{index}].bottomGroups",
                    },
                }
                for index, metric in enumerate(payload.get("metrics", ()))
                if isinstance(metric, Mapping)
            ],
            "derivedMetrics": [
                {
                    "derivedMetricIndex": index,
                    **{
                        key: metric.get(key)
                        for key in (
                            "code",
                            "kind",
                            "unit",
                            "periodRole",
                            "periodStart",
                            "periodEnd",
                            "datasetIds",
                            "value",
                            "percentage",
                        )
                    },
                    "dataPath": f"derivedMetrics[{index}]",
                }
                for index, metric in enumerate(payload.get("derivedMetrics", ()))
                if isinstance(metric, Mapping)
            ],
            "comparisons": [
                {
                    "comparisonIndex": index,
                    **{
                        key: item.get(key)
                        for key in (
                            "comparisonType",
                            "field",
                            "unit",
                            "periodStart",
                            "periodEnd",
                            "currentDatasetId",
                            "baselineDatasetId",
                            "currentTotal",
                            "baselineTotal",
                            "change",
                            "changeRate",
                        )
                    },
                    "dataPath": f"comparisons[{index}]",
                }
                for index, item in enumerate(payload.get("comparisons", ()))
                if isinstance(item, Mapping)
            ],
            "evidenceFiles": durable_item.get("evidenceFiles", [])
            if isinstance(durable_item, Mapping)
            else [],
            "citationIds": durable_item.get("citationIds", [])
            if isinstance(durable_item, Mapping)
            else [],
            "supplementalEvidenceSources": supplemental_sources,
        }

    async def run_reporting_analysis(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        feedback = self._feedback(_step_input)
        state = self._state(run_context)
        scope = self._scope(run_context)
        durable = await self.state_repository.get_or_create(
            report_run_id=str(run_context.run_id or scope["externalRunId"]),
            external_run_id=scope["externalRunId"],
            thread_id=scope["callerThreadId"],
            owner_user_id=scope["userId"],
            revision=int(state.get(REPORT_OUTLINE_STATE_KEY, {}).get("revision", 1))
            if isinstance(state.get(REPORT_OUTLINE_STATE_KEY), Mapping)
            else 1,
        )
        if durable.phase is DurableReportingPhase.FINALIZE:
            stored_checkpoint = durable.payload.get("workflowCheckpoint")
            try:
                checkpoint = ReportingCheckpoint.model_validate(stored_checkpoint)
            except (TypeError, ValueError, ValidationError) as error:
                raise ReportingError(
                    "report_checkpoint_invalid", "Reporting checkpoint 状态无效。"
                ) from error
            if checkpoint.phase != "finalize":
                raise ReportingError(
                    "report_checkpoint_conflict", "Finalize 状态与 Workflow checkpoint 不一致。"
                )
            result = self._workflow_result(state)
            return StepOutput(content={"status": "ready", "jobId": result["jobId"]})
        if durable.phase not in {
            DurableReportingPhase.ANALYSIS_COVERAGE,
            DurableReportingPhase.ANALYSIS_RUNNING,
            DurableReportingPhase.VISUALIZATION,
            DurableReportingPhase.ANALYSIS_FREEZING,
            DurableReportingPhase.SECTIONS,
            DurableReportingPhase.ANALYSIS_REWORK,
        }:
            raise ReportingError(
                "report_state_version_unsupported",
                "当前 Reporting 运行状态不可继续执行。",
            )
        if durable.phase is DurableReportingPhase.ANALYSIS_COVERAGE:
            try:
                await self.state_repository.apply(
                    durable.report_run_id,
                    ReportingCommand(
                        name="start_analysis",
                        commandId=f"analysis-start:{durable.revision}",
                    ),
                    expected_version=durable.state_version,
                )
            except ReportingStateError as error:
                raise ReportingError(error.code, error.message) from error
        result = self._workflow_result(state)
        profile = self._profile(run_context)
        outline = _frozen_outline(state)
        period = self._envelope(run_context).period
        generated_date = state.get(REPORT_DOCUMENT_GENERATED_DATE_STATE_KEY)
        if generated_date is None:
            generated_date = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
            state[REPORT_DOCUMENT_GENERATED_DATE_STATE_KEY] = generated_date
        try:
            if (
                not isinstance(generated_date, str)
                or date.fromisoformat(generated_date).isoformat() != generated_date
            ):
                raise ValueError
        except ValueError as error:
            raise ReportingError(
                "report_document_context_invalid", "报告服务端生成日期状态无效。"
            ) from error
        # 文档事实只能在提纲审核通过后的下一步骤绑定；提前绑定会读取不存在的提纲，
        # 或把用户已拒绝的提纲固化进封面、目录和双格式 manifest。生成日期首次绑定后
        # 写入 Workflow state，跨午夜恢复也必须复用，不能让重入改变同一报告事实。
        await self.report_tools.bind_document_context(
            str(result["jobId"]),
            {
                "title": outline.title,
                "periodLabel": f"{period.start.isoformat()} 至 {period.end.isoformat()}",
                "organizationName": profile.document_branding.organization_name,
                "generatedByLabel": profile.document_branding.generated_by_label,
                "watermarkText": profile.document_branding.watermark_text,
                "generatedDate": generated_date,
                "sectionNumbers": [section.section_number for section in outline.sections],
                "sections": [
                    {
                        "code": section.code,
                        "sectionNumber": section.section_number,
                        "title": section.title,
                    }
                    for section in outline.sections
                ],
            },
            run_context=self._tool_context(run_context),
        )
        revision = int(result.get("revision", 0)) + 1
        # TaskExecutionScope 暂时保留 sandbox_id 字段名；宿主机模式写入稳定 workspace key。
        sandbox_id = scope["threadId"]
        lineage = tuple(
            DatasetLineage.model_validate(item) for item in state[REPORT_DATASET_LINEAGE_STATE_KEY]
        )
        requirements = tuple(
            QueryRequirement.model_validate(item)
            for item in state[REPORT_DATA_REQUIREMENTS_STATE_KEY]
        )
        detailed_plan = DetailedAnalysisPlan.model_validate(
            state[REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY]
        )
        analysis_context_file = FileIdentity.model_validate(
            state.get(REPORT_ANALYSIS_CONTEXT_FILE_STATE_KEY)
        )
        profile_coverage = ProfileCoverageManifest.model_validate(
            state.get(REPORT_PROFILE_COVERAGE_STATE_KEY)
        )
        dataset_handles = tuple(
            DatasetHandle.from_state(item) for item in result.get("datasets", ())
        )
        if not dataset_handles:
            raise ReportingError("report_analysis_context_unavailable", "授权 Dataset 缺失。")
        citation_bindings = authoritative_citations(lineage)
        render_sections = [
            {
                "code": section.code,
                "title": section.title,
                "protocolMarker": True,
                "analysisIds": list(section.analysis_ids),
            }
            for section in outline.sections
        ]
        validation_context = build_report_artifact_validation_context(
            forbidden_visible_terms=_report_machine_terms(
                state[REPORT_DATA_REQUIREMENTS_STATE_KEY],
                state[REPORT_DATASET_LINEAGE_STATE_KEY],
                state[REPORT_EFFECTIVE_PROFILE_STATE_KEY],
            ),
            observed_data_facts=_reporting_observed_data_facts(
                self._data_shapes(run_context), requirements, lineage
            ),
            expected_sections=tuple(str(item["code"]) for item in render_sections),
            expected_citation_bindings=tuple(
                (item.dataset_id, item.requirement_id) for item in citation_bindings
            ),
            expected_citations=tuple(
                (item.citation_id, item.dataset_id, item.requirement_id, item.snapshot_hash)
                for item in citation_bindings
            ),
            analysis_context_file=analysis_context_file.model_dump(mode="json", by_alias=True),
        )
        validation_context["renderContract"] = {
            "title": state[REPORT_OUTLINE_STATE_KEY]["title"],
            "sections": render_sections,
            "citationIds": [item.citation_id for item in citation_bindings],
            "requireTable": False,
        }
        validation_context_file = FileIdentity.model_validate(
            await self._write_artifact_validation_context(
                scope["threadId"],
                f"报表/智能分析/{run_context.run_id}/report-revision-{revision}.validation-context.json",
                validation_context,
            )
        )
        checkpoint = await self._load_or_create_reporting_checkpoint(
            run_context,
            revision=revision,
            profile_coverage=profile_coverage,
            analysis_context_file=analysis_context_file,
            outline=outline,
        )
        checkpoint, fact_files = await self._restore_or_create_deterministic_analysis_facts(
            run_context=run_context,
            checkpoint=checkpoint,
            thread_id=scope["threadId"],
            report_run_id=str(run_context.run_id or scope["externalRunId"]),
            revision=revision,
            detailed_plan=detailed_plan,
            dataset_handles=dataset_handles,
        )
        checkpoint = self._update_reporting_checkpoint(
            checkpoint,
            phase="analysis",
            files=self._merge_checkpoint_files(checkpoint.files, validation_context_file),
        )
        await self._persist_reporting_checkpoint(run_context, checkpoint)
        checkpoint_state: dict[str, Any] = checkpoint.model_dump(mode="python")
        # Reporting 阶段统一由 Agno Workflow 驱动。checkpoint 持久化层自身提供 CAS 锁，
        # 回调不持有跨模型调用的外层锁，从而允许 Parallel 模式真正并发执行分析项和章节。

        async def run_analysis_item(
            instruction: Mapping[str, Any], context: RunContext
        ) -> StepOutput:
            analysis_id = instruction.get("analysisId")
            if not isinstance(analysis_id, str):
                raise ReportingError("report_analysis_item_unknown", "章节缺少有效 analysisId。")
            section_goal = instruction.get("sectionGoal")
            if not isinstance(section_goal, Mapping):
                raise ReportingError("report_analysis_item_unknown", "章节缺少有效 sectionGoal。")
            checkpoint = await self._current_reporting_checkpoint(
                run_context, ReportingCheckpoint.model_validate(checkpoint_state)
            )
            updated = await self._run_analysis_item_task(
                run_context,
                checkpoint=checkpoint,
                revision=revision,
                sandbox_id=sandbox_id,
                validation_context_file=validation_context_file,
                detailed_plan=detailed_plan,
                dataset_handles=dataset_handles,
                lineage=lineage,
                citation_bindings=citation_bindings,
                analysis_context_file=analysis_context_file,
                fact_files=fact_files,
                analysis_id=analysis_id,
                section_goal=section_goal,
                retry_reason=("report_revision_feedback" if feedback else None),
                feedback=feedback,
                rework_request=None,
            )
            checkpoint_state.clear()
            checkpoint_state.update(updated.model_dump(mode="python"))
            return StepOutput(content={"analysisId": analysis_id, "status": "completed"})

        async def submit_visualization(
            instruction: Mapping[str, Any], _context: RunContext
        ) -> StepOutput:
            section_code = instruction.get("sectionCode")
            if not isinstance(section_code, str):
                raise ReportingError(
                    "report_visualization_section_invalid", "章节缺少有效 sectionCode。"
                )
            checkpoint = await self._current_reporting_checkpoint(
                run_context, ReportingCheckpoint.model_validate(checkpoint_state)
            )
            visual_inspection_mode = "vision" if self._vision_enabled else "deterministic"
            visualization_context = {
                "run_context": run_context,
                "checkpoint": checkpoint,
                "revision": revision,
                "sandbox_id": sandbox_id,
                "external_run_id": str(run_context.run_id or scope["externalRunId"]),
                "thread_id": scope["threadId"],
                "validation_context_file": validation_context_file,
                "fact_files": fact_files,
                "visual_inspection_mode": visual_inspection_mode,
            }
            await self._run_visualization_section_task(section_code, context=visualization_context)
            updated = await self._current_reporting_checkpoint(run_context, checkpoint)
            checkpoint_state.clear()
            checkpoint_state.update(updated.model_dump(mode="python"))
            return StepOutput(content={"sectionCode": section_code, "status": "completed"})

        async def rework_analysis(
            instruction: Mapping[str, Any], _context: RunContext
        ) -> StepOutput:
            section_code = instruction.get("sectionCode")
            section_goal = instruction.get("sectionGoal")
            raw_rework = instruction.get("rework")
            if (
                not isinstance(section_code, str)
                or not isinstance(section_goal, Mapping)
                or not isinstance(raw_rework, Mapping)
            ):
                raise ReportingError(
                    "report_analysis_rework_invalid", "章节补证请求缺少有效上下文。"
                )
            try:
                rework = AnalysisReworkRequest.model_validate(
                    {"sectionCode": section_code, **dict(raw_rework)}
                )
            except ValidationError as error:
                raise ReportingError(
                    "report_analysis_rework_invalid", "章节补证请求结构无效。"
                ) from error
            rework_payload = rework.model_dump(mode="json", by_alias=True)
            rework_digest = payload_sha256(rework_payload)
            # request_analysis_rework 是补证失效边界：先由 reducer 原子撤销目标
            # analysis、当前章节及其图表，再启动定向补证。否则后续可视化会误复用
            # 补证前的 durable 完成标记，形成新分析配旧图表的混合产物。
            await self._apply_durable_command(
                run_context,
                ReportingCommand(
                    name="request_analysis_rework",
                    commandId=f"analysis-rework-request:{revision}:{rework_digest}",
                    payload=rework_payload,
                ),
            )
            await self._apply_durable_command(
                run_context,
                ReportingCommand(
                    name="start_analysis",
                    commandId=f"analysis-rework-start:{revision}:{rework_digest}",
                ),
            )
            checkpoint = await self._current_reporting_checkpoint(
                run_context, ReportingCheckpoint.model_validate(checkpoint_state)
            )
            retry_reason = f"analysis_rework:{rework_digest}"
            for analysis_id in rework.analysis_ids:
                checkpoint = await self._run_analysis_item_task(
                    run_context,
                    checkpoint=checkpoint,
                    revision=revision,
                    sandbox_id=sandbox_id,
                    validation_context_file=validation_context_file,
                    detailed_plan=detailed_plan,
                    dataset_handles=dataset_handles,
                    lineage=lineage,
                    citation_bindings=citation_bindings,
                    analysis_context_file=analysis_context_file,
                    fact_files=fact_files,
                    analysis_id=analysis_id,
                    section_goal=section_goal,
                    retry_reason=retry_reason,
                    feedback=feedback,
                    rework_request=rework,
                )
            checkpoint_state.clear()
            checkpoint_state.update(checkpoint.model_dump(mode="python"))
            return StepOutput(
                content={
                    "sectionCode": section_code,
                    "status": "completed",
                    "analysisIds": list(rework.analysis_ids),
                }
            )

        async def draft_section(instruction: Mapping[str, Any], _context: RunContext) -> StepOutput:
            section_code = instruction.get("sectionCode")
            if not isinstance(section_code, str):
                raise ReportingError("report_section_invalid", "章节缺少有效 sectionCode。")
            analysis_rework_allowed = instruction.get("analysisReworkAllowed") is not False
            raw_rework = instruction.get("rework")
            degraded_rework = dict(raw_rework) if isinstance(raw_rework, Mapping) else None
            if not analysis_rework_allowed and degraded_rework is not None:
                warning = {
                    "code": "report_analysis_rework_exhausted",
                    "message": "章节补证次数已达到上限，已基于现有冻结证据降级成稿。",
                    "sectionCode": section_code,
                    "details": degraded_rework,
                }
                try:
                    await self._apply_durable_command(
                        run_context,
                        ReportingCommand(
                            name="record_warnings",
                            commandId=(
                                f"section-rework-exhausted:{revision}:{section_code}:"
                                f"{payload_sha256(warning)}"
                            ),
                            payload={"warnings": [warning]},
                        ),
                    )
                except ReportingError as error:
                    loguru_logger.bind(
                        section_code=section_code,
                        error_code=error.code,
                    ).warning("report_analysis_rework_warning_persist_failed")
            section = next(item for item in outline.sections if item.code == section_code)
            checkpoint = await self._current_reporting_checkpoint(
                run_context, ReportingCheckpoint.model_validate(checkpoint_state)
            )
            artifact = await self._build_reporting_artifact(
                run_context,
                analysis_ids=section.analysis_ids,
                detailed_plan=detailed_plan,
                fact_files=fact_files,
                citation_bindings=citation_bindings,
                section_codes=(section_code,),
            )
            work_item = self._build_section_work_item(
                section,
                detailed_plan=detailed_plan,
                analysis_artifact=artifact,
                citation_bindings=citation_bindings,
            )
            updated, _section_artifact, rework = await self._run_section_phase(
                run_context,
                checkpoint=checkpoint,
                revision=revision,
                sandbox_id=sandbox_id,
                validation_context_file=validation_context_file,
                work_item=work_item,
                analysis_rework_constraints=self._analysis_rework_constraints(
                    detailed_plan=detailed_plan,
                    profile_coverage=profile_coverage,
                    analysis_ids=work_item.analysis_ids,
                ),
                analysis_rework_allowed=analysis_rework_allowed,
                degraded_rework=degraded_rework,
            )
            checkpoint_state.clear()
            checkpoint_state.update(updated.model_dump(mode="python"))
            if rework is not None:
                return StepOutput(
                    content={
                        "sectionCode": section_code,
                        "status": "rework",
                        "rework": rework.model_dump(mode="json", by_alias=True),
                    }
                )
            return StepOutput(content={"sectionCode": section_code, "status": "completed"})

        reporting_workflow = ReportingAnalysisAndDraftWorkflow(
            report_goal=self._envelope(run_context).report_goal,
            sections=[
                {
                    "sectionCode": section.code,
                    "title": section.title,
                    "focus": section.focus,
                    "analysisIds": list(section.analysis_ids),
                }
                for section in outline.sections
            ],
            run_analysis=run_analysis_item,
            submit_visualization=submit_visualization,
            draft_section=draft_section,
            rework_analysis=rework_analysis,
            execution_mode=getattr(self, "reporting_execution_mode", "sequential"),
            section_concurrency=getattr(self, "section_concurrency", 1),
            analysis_concurrency=getattr(self, "analysis_concurrency", 1),
        )
        output = await reporting_workflow.arun(
            input={"reportGoal": self._envelope(run_context).report_goal},
            run_id=str(run_context.run_id or scope["externalRunId"]),
            session_id=scope["threadId"],
        )
        content = getattr(output, "content", None)
        if not isinstance(content, dict):
            raise ReportingError(
                "report_coding_workflow_output_invalid",
                "ReportingAnalysisAndDraftWorkflow 未返回有效结果。",
            )
        final_checkpoint = ReportingCheckpoint.model_validate(checkpoint_state)
        final_artifact = await self._build_reporting_artifact(
            run_context,
            analysis_ids=tuple(item.analysis_id for item in detailed_plan.analyses),
            detailed_plan=detailed_plan,
            fact_files=fact_files,
            citation_bindings=citation_bindings,
        )
        artifact_path = (
            f"报表/智能分析/{run_context.run_id}/phases/revision-{revision}/analysis-artifact.json"
        )
        artifact_file = await self._write_immutable_artifact(
            scope["threadId"],
            artifact_path,
            json.dumps(
                final_artifact.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        final_checkpoint = self._update_reporting_checkpoint(
            final_checkpoint,
            phase="finalize",
            report_brief=final_artifact.report_brief,
            evidence_manifest=final_artifact.evidence_manifest,
            analysis_manifest_file=artifact_file,
            profile_read_receipts=final_artifact.profile_read_receipts,
        )
        await self._persist_reporting_checkpoint(run_context, final_checkpoint)
        return StepOutput(content={**content, "jobId": result["jobId"]})

    async def assemble_report(self, _step_input: StepInput, run_context: RunContext) -> StepOutput:
        state = self._state(run_context)
        scope = self._scope(run_context)
        durable = await self.state_repository.get(str(run_context.run_id or scope["externalRunId"]))
        if durable is None or durable.phase not in {
            DurableReportingPhase.FINALIZE,
            DurableReportingPhase.COMPLETED,
        }:
            raise ReportingError(
                "report_state_version_unsupported", "当前 Reporting 运行状态不可执行汇编。"
            )
        stored_checkpoint = durable.payload.get("workflowCheckpoint")
        try:
            checkpoint = ReportingCheckpoint.model_validate(stored_checkpoint)
            lineage = tuple(
                DatasetLineage.model_validate(item)
                for item in state[REPORT_DATASET_LINEAGE_STATE_KEY]
            )
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise ReportingError(
                "report_checkpoint_invalid", "Finalize checkpoint 或冻结输入状态无效。"
            ) from error
        if checkpoint.phase not in {"finalize", "completed"}:
            raise ReportingError(
                "report_checkpoint_conflict", "当前 Workflow checkpoint 尚未进入 Finalize。"
            )
        if durable.phase is DurableReportingPhase.FINALIZE and checkpoint.phase != "finalize":
            raise ReportingError(
                "report_checkpoint_conflict", "Finalize durable 状态与 checkpoint 不一致。"
            )

        revision = checkpoint.revision
        markdown_path = f"报表/智能分析/{run_context.run_id}/report-revision-{revision}.md"
        manifest_path = (
            f"报表/智能分析/{run_context.run_id}/report-revision-{revision}.manifest.json"
        )
        if checkpoint.phase == "completed":
            manifest_file = next(
                (item for item in checkpoint.files if item.path == manifest_path), None
            )
            if manifest_file is None:
                raise ReportingError(
                    "report_checkpoint_invalid", "Completed checkpoint 缺少报告 manifest。"
                )
            manifest = cast(
                ReportArtifactManifest,
                await self._read_identity_model(
                    scope["threadId"], manifest_file, ReportArtifactManifest
                ),
            )
        else:
            _final_checkpoint, manifest = await self._finalize_reporting_sections(
                run_context,
                checkpoint=checkpoint,
                revision=revision,
                markdown_path=markdown_path,
                manifest_path=manifest_path,
                lineage=lineage,
                citation_bindings=authoritative_citations(lineage),
                source_warnings=_source_warnings_from_state(state),
            )
        result = self._workflow_result(state)
        result.update(
            {
                "markdownPath": markdown_path,
                "artifactManifestPath": manifest_path,
                "revision": revision,
            }
        )
        state[REPORT_WORKFLOW_RESULT_STATE_KEY] = result
        state[REPORT_ARTIFACTS_STATE_KEY] = {
            "draft": manifest.model_dump(mode="json", by_alias=True)
        }
        return StepOutput(content={"jobId": result["jobId"], "markdownPath": markdown_path})

    async def _write_artifact_validation_context(
        self,
        thread_id: str,
        path: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        content = json.dumps(
            context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        self.workspace_service.validate_content(content)
        relative, _host_path = self.workspace_service.normalize_path(path, allow_root=False)
        await self.workspace_service.awrite_bytes(thread_id, relative, content, overwrite=True)
        stored = await self.workspace_service.read_limited_regular_file(
            thread_id, relative, max_bytes=len(content)
        )
        if stored != content:
            raise ReportingError(
                "report_artifact_validation_context_changed",
                "报告验收上下文写入后发生变化。",
            )
        return {
            "path": relative,
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    @staticmethod
    def _update_reporting_checkpoint(
        checkpoint: ReportingCheckpoint,
        **updates: Any,
    ) -> ReportingCheckpoint:
        payload = checkpoint.model_dump(mode="python")
        payload.update(updates)
        return ReportingCheckpoint.model_validate(payload)

    @staticmethod
    def _merge_checkpoint_files(
        current: tuple[FileIdentity, ...],
        *files: FileIdentity,
    ) -> tuple[FileIdentity, ...]:
        by_path = {item.path: item for item in current}
        for item in files:
            by_path[item.path] = item
        return tuple(by_path.values())

    async def _persist_reporting_checkpoint(
        self,
        run_context: RunContext,
        checkpoint: ReportingCheckpoint,
    ) -> ReportingCheckpoint:
        # 并发分析项和章节都会携带各自启动时的 checkpoint 副本。读取最新 durable、
        # 合并和写回必须串行完成，否则后到的旧副本会覆盖先完成任务并触发重复执行。
        async with self._checkpoint_persist_lock:
            return await self._persist_reporting_checkpoint_unlocked(run_context, checkpoint)

    async def _persist_reporting_checkpoint_unlocked(
        self,
        run_context: RunContext,
        checkpoint: ReportingCheckpoint,
    ) -> ReportingCheckpoint:
        durable = await self.state_repository.get(
            str(run_context.run_id or self._scope(run_context)["externalRunId"])
        )
        stored = durable.payload.get("workflowCheckpoint") if durable is not None else None
        if isinstance(stored, dict):
            checkpoint = self._merge_reporting_checkpoints(
                ReportingCheckpoint.model_validate(stored), checkpoint
            )
        serialized = json.dumps(
            checkpoint.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(serialized).hexdigest()
        path = (
            f"报表/智能分析/{run_context.run_id}/audit/"
            f"reporting-checkpoint-{checkpoint.revision}-{digest}.json"
        )
        identity = await self._write_immutable_artifact(
            self._scope(run_context)["threadId"], path, serialized
        )
        await self._apply_durable_command(
            run_context,
            ReportingCommand(
                name="set_workflow_checkpoint",
                commandId=(f"workflow-checkpoint-v2:{checkpoint.revision}:{digest}"),
                payload={
                    "checkpoint": checkpoint.model_dump(mode="json", by_alias=True),
                    "mirrorFile": identity.model_dump(mode="json", by_alias=True),
                },
            ),
        )
        return checkpoint

    @staticmethod
    def _merge_reporting_checkpoints(
        current: ReportingCheckpoint,
        incoming: ReportingCheckpoint,
    ) -> ReportingCheckpoint:
        """合并并发任务回执；提纲和冻结 manifest 必须保持同一身份。"""

        current_frozen = (
            current.analysis_manifest_file,
            current.evidence_manifest,
            current.report_brief,
        )
        incoming_frozen = (
            incoming.analysis_manifest_file,
            incoming.evidence_manifest,
            incoming.report_brief,
        )
        freezes_analysis = (
            current.phase == "analysis"
            and current_frozen == (None, None, None)
            and all(item is not None for item in incoming_frozen)
        )
        if (
            current.revision != incoming.revision
            or current.outline_hash != incoming.outline_hash
            or current.profile_coverage != incoming.profile_coverage
            or (current_frozen != incoming_frozen and not freezes_analysis)
        ):
            raise ReportingError(
                "report_checkpoint_conflict",
                "并发任务 checkpoint 与当前冻结分析身份不一致。",
            )
        current_fact_files = current.deterministic_fact_files
        incoming_fact_files = incoming.deterministic_fact_files
        if current_fact_files and incoming_fact_files and current_fact_files != incoming_fact_files:
            raise ReportingError(
                "report_checkpoint_conflict",
                "并发任务 checkpoint 与当前确定性 facts 身份不一致。",
            )
        deterministic_fact_files = current_fact_files or incoming_fact_files
        merged_files = RuntimeAnalysisMixin._merge_checkpoint_files(current.files, *incoming.files)
        merged_files_by_path = {item.path: item for item in merged_files}
        if any(
            identity.path in merged_files_by_path
            and merged_files_by_path[identity.path] != identity
            for identity in deterministic_fact_files.values()
        ):
            raise ReportingError(
                "report_checkpoint_conflict",
                "并发任务 files 账本试图覆盖已冻结的确定性 facts 身份。",
            )
        completed_by_code = {item.section_code: item for item in current.completed_sections}
        for item in incoming.completed_sections:
            existing = completed_by_code.get(item.section_code)
            if existing is not None and existing != item:
                raise ReportingError(
                    "report_section_completion_conflict",
                    f"章节 {item.section_code} 已绑定其他完成产物。",
                )
            completed_by_code[item.section_code] = item
        completed_codes = set(completed_by_code)
        pending = tuple(
            code
            for code in dict.fromkeys((*current.pending_sections, *incoming.pending_sections))
            if code not in completed_codes
        )
        trace_by_task = {item.task_id: item for item in current.trace if item.task_id}
        anonymous_trace = [item for item in current.trace if not item.task_id]
        for trace_item in incoming.trace:
            if trace_item.task_id:
                trace_by_task[trace_item.task_id] = trace_item
            elif trace_item not in anonymous_trace:
                anonymous_trace.append(trace_item)
        section_errors = dict(current.visualization_section_errors)
        for section_code, error in incoming.visualization_section_errors.items():
            existing_error = section_errors.get(section_code)
            # checkpoint 持久化可乱序回放；同章账本只能由更高 attempt，或同 attempt
            # 的确定性 taskId 覆盖。否则旧执行器的失败写回会抹掉新执行器的恢复预算。
            if existing_error is None or (
                error.attempt if error.attempt is not None else -1,
                error.task_id or "",
            ) >= (
                existing_error.attempt if existing_error.attempt is not None else -1,
                existing_error.task_id or "",
            ):
                section_errors[section_code] = error
        for section_code, error in tuple(section_errors.items()):
            completed_attempts = (
                (item.attempt, item.task_id or "")
                for item in (*current.trace, *incoming.trace)
                if item.work_kind == "visualization_section"
                and item.status == "completed"
                and item.section_code == section_code
            )
            if any(
                completed_identity
                >= (error.attempt if error.attempt is not None else -1, error.task_id or "")
                for completed_identity in completed_attempts
            ):
                section_errors.pop(section_code)
        merged_phase = incoming.phase
        if current.phase == "completed" or incoming.phase == "completed":
            merged_phase = "completed"
        elif current.phase == "finalize" or incoming.phase == "finalize":
            merged_phase = "finalize"
        elif not freezes_analysis and (current.phase == "analysis" or incoming.phase == "analysis"):
            merged_phase = "analysis"
        return RuntimeAnalysisMixin._update_reporting_checkpoint(
            incoming,
            phase=merged_phase,
            completed_sections=tuple(completed_by_code.values()),
            pending_sections=pending,
            warnings=tuple((*current.warnings, *incoming.warnings)[-500:]),
            last_error=incoming.last_error or current.last_error,
            deterministic_fact_files=dict(deterministic_fact_files),
            visualization_section_errors=section_errors,
            files=merged_files,
            trace=tuple((*anonymous_trace, *trace_by_task.values())),
        )

    async def _current_reporting_checkpoint(
        self,
        run_context: RunContext,
        fallback: ReportingCheckpoint,
    ) -> ReportingCheckpoint:
        durable = await self.state_repository.get(
            str(run_context.run_id or self._scope(run_context)["externalRunId"])
        )
        stored = durable.payload.get("workflowCheckpoint") if durable is not None else None
        if not isinstance(stored, dict):
            return fallback
        return ReportingCheckpoint.model_validate(stored)

    async def _read_identity_bytes(
        self,
        thread_id: str,
        identity: FileIdentity,
        *,
        max_bytes: int = 10 * 1024 * 1024,
    ) -> bytes:
        if identity.size > max_bytes:
            raise ReportingError("report_phase_artifact_too_large", "阶段产物超过读取边界。")
        content = await self.workspace_service.read_limited_regular_file(
            thread_id,
            identity.path,
            max_bytes=identity.size,
        )
        if len(content) != identity.size or hashlib.sha256(content).hexdigest() != identity.sha256:
            raise ReportingError("report_phase_artifact_changed", "阶段产物身份校验失败。")
        return content

    async def _read_identity_model(
        self,
        thread_id: str,
        identity: FileIdentity,
        model: type[BaseModel],
    ) -> BaseModel:
        content = await self._read_identity_bytes(thread_id, identity)
        try:
            return model.model_validate_json(content)
        except ValidationError as error:
            raise ReportingError("report_phase_artifact_invalid", "阶段产物结构无效。") from error

    async def _write_immutable_artifact(
        self,
        thread_id: str,
        path: str,
        content: bytes,
    ) -> FileIdentity:
        self.workspace_service.validate_content(content)
        digest = hashlib.sha256(content).hexdigest()
        current = (await self.workspace_service.abatch_hash_files(thread_id, [path]))[0]
        if current.get("missing") is not True:
            if current.get("size") == len(content) and current.get("sha256") == digest:
                return FileIdentity.model_validate(current)
            raise ReportingError(
                "report_artifact_file_changed", "当前 revision 的服务端产物已存在但身份不同。"
            )
        relative, _host_path = self.workspace_service.normalize_path(path, allow_root=False)
        await self.workspace_service.awrite_bytes(thread_id, relative, content)
        stored = await self.workspace_service.read_limited_regular_file(
            thread_id, relative, max_bytes=len(content)
        )
        if stored != content:
            raise ReportingError("report_artifact_file_changed", "服务端产物写入后发生变化。")
        return FileIdentity(path=relative, size=len(content), sha256=digest)

    async def _load_or_create_reporting_checkpoint(
        self,
        run_context: RunContext,
        *,
        revision: int,
        profile_coverage: ProfileCoverageManifest,
        analysis_context_file: FileIdentity,
        outline: ReportOutline,
    ) -> ReportingCheckpoint:
        state = self._state(run_context)
        outline_hash = str(
            state.get(REPORT_OUTLINE_HASH_STATE_KEY)
            or _payload_sha256(outline.model_dump(mode="json", by_alias=True))
        )
        # 用户反馈会推进 revision，但同一 revision 的进程中断不能再次清空 analysis 和已完成章节。
        # 只有旧 checkpoint revision 落后时才创建新状态；同 revision 必须同时核验 state、落盘文件、
        # 冻结提纲和 Profile coverage，任一身份漂移都失败关闭。
        if any(key.startswith("report_reporting_checkpoint") for key in state):
            raise ReportingError(
                "report_state_version_unsupported",
                "旧 Reporting session checkpoint 不受支持。",
            )
        durable = await self.state_repository.get(
            str(run_context.run_id or self._scope(run_context)["externalRunId"])
        )
        stored_checkpoint = (
            durable.payload.get("workflowCheckpoint") if durable is not None else None
        )
        if isinstance(stored_checkpoint, dict):
            try:
                checkpoint = ReportingCheckpoint.model_validate(stored_checkpoint)
            except (TypeError, ValueError, ValidationError) as error:
                raise ReportingError(
                    "report_checkpoint_invalid", "Reporting checkpoint 状态无效。"
                ) from error
            if checkpoint.revision == revision:
                if (
                    checkpoint.outline_hash != outline_hash
                    or checkpoint.profile_coverage != profile_coverage
                ):
                    raise ReportingError(
                        "report_checkpoint_conflict",
                        "Reporting checkpoint 与当前提纲或 Profile coverage 不一致。",
                    )
                return checkpoint
            if checkpoint.revision > revision:
                raise ReportingError(
                    "report_checkpoint_conflict",
                    "Reporting checkpoint revision 超前于当前 Workflow 状态。",
                )

        profile_files = tuple(item.profile_file for item in profile_coverage.datasets)
        checkpoint = ReportingCheckpoint(
            revision=revision,
            phase="analysis",
            outlineHash=outline_hash,
            profileCoverage=profile_coverage,
            pendingSections=tuple(section.code for section in outline.sections),
            files=self._merge_checkpoint_files((), analysis_context_file, *profile_files),
        )
        return await self._persist_reporting_checkpoint(run_context, checkpoint)

    @staticmethod
    def _replace_trace(
        checkpoint: ReportingCheckpoint,
        task_id: str,
        **updates: Any,
    ) -> ReportingCheckpoint:
        traces: list[ContextTrace] = []
        replaced = False
        for item in checkpoint.trace:
            if item.task_id == task_id:
                payload = item.model_dump(mode="python")
                payload.update(updates)
                traces.append(ContextTrace.model_validate(payload))
                replaced = True
            else:
                traces.append(item)
        if not replaced:
            raise ReportingError("report_checkpoint_invalid", "Checkpoint 缺少当前 phase trace。")
        return RuntimeAnalysisMixin._update_reporting_checkpoint(checkpoint, trace=tuple(traces))

    @staticmethod
    def _trace_metrics_from_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        model_metrics = receipt.get("modelMetrics")
        model_input_tokens = (
            model_metrics.get("inputTokens") if isinstance(model_metrics, Mapping) else None
        )
        if (
            not isinstance(model_input_tokens, bool)
            and isinstance(model_input_tokens, int)
            and model_input_tokens >= 0
        ):
            updates["model_input_tokens"] = model_input_tokens
        projection_metrics = receipt.get("projectionMetrics")
        if not isinstance(projection_metrics, Mapping):
            return updates
        for alias, field_name in (
            ("modelRequestCount", "model_request_count"),
            ("maxCanonicalTokens", "max_canonical_tokens"),
            ("maxProjectedTokens", "max_projected_tokens"),
            ("rebaseCount", "rebase_count"),
            ("inputTokenHardCap", "input_token_hard_cap"),
            ("completedAnalysisCount", "completed_analysis_count"),
            ("toolEventCount", "tool_event_count"),
        ):
            value = projection_metrics.get(alias)
            if not isinstance(value, bool) and isinstance(value, int) and value >= 0:
                updates[field_name] = value
        return updates

    @staticmethod
    def _instruction_component_bytes(payload: Mapping[str, Any]) -> dict[str, int]:
        """按主要上下文字段统计 UTF-8 字节数，不记录字段内容。"""
        components = (
            ("current_analysis", "currentAnalysis"),
            ("deterministic_facts", "deterministicFacts"),
            ("profile_coverage", "profileCoverage"),
            ("analysis_context_file", "analysisContextFile"),
            ("datasets", "datasets"),
            ("dataset_lineage", "datasetLineage"),
            ("citation_registry", "citationRegistry"),
            ("completion_conditions", "completionConditions"),
            ("durable_analysis_item", "durableAnalysisItem"),
            ("outline", "outline"),
            ("registered_charts", "registeredCharts"),
            ("analysis_plans", "analysisPlans"),
            ("analysis_citation_ids", "analysisCitationIds"),
            ("citation_dataset_ids", "citationDatasetIds"),
            ("deterministic_fact_files", "deterministicFactFiles"),
            ("visualization_facts", "visualizationFacts"),
            ("dataset_semantics", "datasetSemantics"),
            ("metric_definitions", "metricDefinitions"),
            ("section_evidence_catalog", "sectionEvidenceCatalog"),
            ("chart_registration_rules", "chartRegistrationRules"),
            ("visualization_workspace", "visualizationWorkspace"),
            ("source_warnings", "sourceWarnings"),
            ("review_feedback", "reviewFeedback"),
        )
        return {
            name: len(
                json.dumps(payload[field], ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            for name, field in components
            if field in payload
        }

    async def _phase_artifact_from_receipt(
        self,
        thread_id: str,
        receipt: dict[str, Any],
        expected_paths: tuple[str, ...],
    ) -> FileIdentity:
        artifacts = receipt.get("artifacts") if isinstance(receipt, dict) else None
        if not isinstance(artifacts, list) or len(artifacts) != 1:
            raise ReportingError(
                "report_phase_artifact_missing", "Reporting phase 必须签发且只签发一个阶段产物。"
            )
        raw_identity = artifacts[0]
        if not isinstance(raw_identity, Mapping):
            raise ReportingError("report_phase_artifact_missing", "Reporting phase 产物身份无效。")
        identity = FileIdentity.model_validate(dict(raw_identity))
        if identity.path not in expected_paths:
            raise ReportingError(
                "report_phase_artifact_unexpected", "Reporting phase 返回了未授权产物路径。"
            )
        current = await self.workspace_service.ahash_file(thread_id, identity.path)
        if FileIdentity.model_validate(current) != identity:
            raise ReportingError("report_phase_artifact_changed", "阶段产物在签发后发生变化。")
        return identity

    def _analysis_thinking_effort(self) -> Literal["off", "high"]:
        return "high" if self._analysis_thinking_enabled else "off"

    async def _analysis_item_artifacts_from_receipt(
        self,
        thread_id: str,
        receipt: Mapping[str, Any],
        expected: tuple[FileIdentity, ...],
    ) -> tuple[FileIdentity, ...]:
        raw_artifacts = receipt.get("artifacts")
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise ReportingError(
                "report_phase_artifact_missing",
                "analysis item Task 没有签发 evidence 产物。",
            )
        try:
            received = tuple(FileIdentity.model_validate(item) for item in raw_artifacts)
        except ValidationError as error:
            raise ReportingError(
                "report_phase_artifact_missing",
                "analysis item Task 返回了无效 evidence 身份。",
            ) from error
        received_by_path = {item.path: item for item in received}
        expected_by_path = {item.path: item for item in expected}
        if len(received_by_path) != len(received) or received_by_path != expected_by_path:
            raise ReportingError(
                "report_analysis_evidence_identity_mismatch",
                "analysis item Task 签发的 evidence 与 durable 身份不一致。",
            )
        for identity in expected:
            current = FileIdentity.model_validate(
                await self.workspace_service.ahash_file(thread_id, identity.path)
            )
            if current != identity:
                raise ReportingError(
                    "report_analysis_evidence_identity_mismatch",
                    "analysis item evidence 在签发后发生变化。",
                )
        return expected

    async def _execute_analysis_item_workflow(
        self,
        instruction: str,
        task_run_context: RunContext,
        *,
        parent_run_context: RunContext,
        model_metrics_recorder: Callable[[Any, int], None],
        planner_model_metrics_recorder: Callable[[Any, int], None] | None = None,
        coding_model_metrics_recorder: Callable[[Any, int], None] | None = None,
        summary_model_metrics_recorder: Callable[[Any, int], None] | None = None,
        benchmark_projection: BenchmarkProjection | None = None,
        evidence_planner: Any | None = None,
        evidence_output_type: type[BaseModel] = AnalysisEvidenceDecision,
    ) -> StepOutput:
        """在当前 Task lease 内执行五阶段子流程，工具继续复用现有强契约。"""

        try:
            payload = json.loads(instruction)
        except (TypeError, json.JSONDecodeError) as error:
            raise ReportingError(
                "report_analysis_context_invalid", "单项分析任务输入不是有效 JSON。"
            ) from error
        if not isinstance(payload, dict):
            raise ReportingError(
                "report_analysis_context_invalid", "单项分析任务输入必须是 JSON 对象。"
            )
        _validate_analysis_benchmark_planner(
            benchmark_projection, evidence_planner, evidence_output_type
        )
        toolkits = build_reporting_tools(
            self.workspace_service,
            self.task_runner.repository,
            state_repository=self.state_repository,
            run_context=task_run_context,
        )
        if len(toolkits) != 1:
            raise ReportingError("report_phase_contract_invalid", "单项分析 Toolkit 装配结果无效。")
        toolkit = toolkits[0]
        analysis_id = str(payload.get("currentAnalysisId") or "")
        current_analysis = payload.get("currentAnalysis")
        _, thinking_complexity = _analysis_item_complexity(
            current_analysis if isinstance(current_analysis, Mapping) else {}
        )
        thinking_failure_kind = payload.get("thinkingFailureKind")
        evidence_failure_kind: ThinkingFailureKind | None = (
            thinking_failure_kind
            if thinking_failure_kind in {"evidence_incomplete", "fact_incomplete"}
            else None
        )
        thinking_enabled = self._analysis_thinking_enabled
        thinking_budget_cap = self._analysis_thinking_budget_cap
        planner_metrics_recorder = (
            planner_model_metrics_recorder or model_metrics_recorder
        )
        coding_metrics_recorder = coding_model_metrics_recorder or model_metrics_recorder
        summary_metrics_recorder = summary_model_metrics_recorder or model_metrics_recorder
        if self.code_mode_runtime is None:
            raise ReportingError(
                "report_code_mode_runtime_missing",
                "分析脚本 CodeMode runtime 未配置。",
            )
        code_runner = ReportingCodeGenerationRunner(
            self._analysis_script_agent_factory,
            self.code_mode_runtime,
            knowledge_index=getattr(self, "knowledge_index", None),
            lsp_manager=getattr(self, "lsp_manager", None),
            registry=self.coding_task_registry,
            model_metrics_recorder=coding_metrics_recorder,
            compact_continuation=True,
        )
        repair_workspace_key: str | None = None
        knowledge_index = getattr(self, "knowledge_index", None)

        async def run_structured_agent(
            agent: Any,
            request: dict[str, Any],
            expected_type: type[BaseModel],
        ) -> BaseModel:
            """调用统一结构化执行器；其内部负责最多五次带反馈纠错。"""

            output = await self._run_planner(
                agent,
                request,
                parent_run_context,
                thinking_complexity=thinking_complexity,
                attempt=1 if evidence_failure_kind is not None else 0,
                failure_kind=evidence_failure_kind,
                model_metrics_recorder=planner_metrics_recorder,
            )
            if not isinstance(output, expected_type):
                raise ReportingError(
                    "report_structured_output_invalid",
                    f"分析项 {analysis_id} 返回了错误的结构化结果类型。",
                )
            return output

        async def decide_evidence(
            planner_payload: Mapping[str, Any],
        ) -> EvidenceDecision:
            decision_request = {
                "currentAnalysis": planner_payload.get("currentAnalysis"),
                "deterministicFacts": planner_payload.get("deterministicFacts"),
                "datasets": planner_payload.get("datasets"),
                "analysisBlock": {"blockId": f"{analysis_id}:evidence:decision"},
            }
            return cast(
                EvidenceDecision,
                await run_structured_agent(
                    evidence_planner or self._analysis_evidence_agent,
                    decision_request,
                    evidence_output_type,
                ),
            )

        async def run_code(
            *,
            script_path: str,
            task_facts: Mapping[str, Any],
            diagnostic: Mapping[str, Any] | None,
            run_context: RunContext,
        ) -> CodeGenerationResult:
            nonlocal repair_workspace_key
            failure_kind = _code_failure_kind(diagnostic)
            decision = select_reporting_thinking(
                ThinkingRequest(
                    operation="analysis_script",
                    complexity=thinking_complexity,
                    attempt=1 if failure_kind is not None else 0,
                    failure_kind=failure_kind,
                    configured_budget_cap=thinking_budget_cap,
                    thinking_enabled=thinking_enabled,
                )
            )
            binding = (
                run_context.dependencies.get("AgentOS 任务执行")
                if isinstance(run_context.dependencies, Mapping)
                else None
            )
            task_id = (
                binding.get("externalRunId") if isinstance(binding, Mapping) else None
            ) or analysis_id
            parent_scope = self._scope(parent_run_context)
            task_workspace = self.workspace_for(
                run_id=str(parent_run_context.run_id or ""),
                session_id=str(parent_run_context.session_id or ""),
                user_id=str(parent_run_context.user_id or "") or None,
                dependencies=(
                    dict(parent_run_context.dependencies)
                    if isinstance(parent_run_context.dependencies, Mapping)
                    else None
                ),
                stored_scope=parent_scope,
            )
            datasets = task_facts.get("datasets")
            dataset_paths = tuple(
                sorted(
                    str(item["path"])
                    for item in datasets
                    if isinstance(item, Mapping) and isinstance(item.get("path"), str)
                )
            ) if isinstance(datasets, (list, tuple)) else ()
            evidence_path = str(task_facts.get("evidencePath") or "")
            if not evidence_path:
                raise ReportingError(
                    "report_phase_contract_invalid", "补充分析缺少 evidencePath。"
                )
            coding_context = ReportingCodingTaskContext(
                task_id=str(task_id),
                task_kind="analysis",
                code_mode_session_id=f"analysis:{task_id}",
                workspace_key=task_workspace.identity.workspace_key,
                workspace_root=task_workspace.identity.root,
                script_path=script_path,
                authorized_read_paths=dataset_paths,
                authorized_write_paths=(script_path, evidence_path),
                declared_output_paths=(evidence_path,),
                max_source_bytes=_ANALYSIS_SCRIPT_MAX_BYTES,
            )
            repair_workspace_key = coding_context.workspace_key

            async def preflight_evidence(receipt: ExecutionReceipt) -> Mapping[str, Any] | None:
                output = receipt.output_files[0]
                if not 0 < output.size <= MAX_SUPPLEMENTAL_EVIDENCE_BYTES:
                    return {
                        "code": "report_analysis_evidence_too_large",
                        "message": "补充 evidence 超过 10 MiB 安全上限或大小无效。",
                    }
                content = await task_workspace.read_limited_regular_file(
                    coding_context.task_id, output.path,
                    max_bytes=MAX_SUPPLEMENTAL_EVIDENCE_BYTES,
                )
                current = task_facts.get("currentAnalysis")
                try:
                    validate_supplemental_evidence(
                        content, current if isinstance(current, Mapping) else {},
                    )
                except ValidationError as error:
                    rejection = supplemental_evidence_schema_error(error)
                    return {"code": rejection.code, "message": rejection.message,
                            "details": rejection.details}
                return None

            with bind_reporting_thinking(decision):
                return await code_runner.run(
                    coding_context,
                    task_workspace,
                    task_facts,
                    run_context=run_context,
                    diagnostic=diagnostic,
                    output_preflight=preflight_evidence,
                )

        async def record_successful_repair(
            diagnostic: Mapping[str, Any], script_file: FileIdentity
        ) -> None:
            await _record_successful_repair(
                knowledge_index,
                workspace_key=repair_workspace_key,
                task_kind="analysis",
                diagnostic=diagnostic,
                script_file=script_file,
            )

        async def summarize(summary_payload: Mapping[str, Any]) -> AnalysisSummaryDraft:
            summary_request = _prepare_analysis_summary_request(
                summary_payload,
                analysis_id=analysis_id,
                agent=self._analysis_summary_agent,
                run_context=parent_run_context,
            )
            output = await self._run_planner(
                self._analysis_summary_agent,
                summary_request,
                parent_run_context,
                thinking_complexity=thinking_complexity,
                model_metrics_recorder=summary_metrics_recorder,
            )
            return cast(AnalysisSummaryDraft, output)

        workflow_kwargs: dict[str, Any] = {
            "decide_evidence": decide_evidence,
            "run_code": run_code,
            "summarize": summarize,
            "read_file": toolkit.read_file,
            "complete": toolkit.complete_analysis_item,
        }
        if knowledge_index is not None:
            workflow_kwargs["record_successful_repair"] = record_successful_repair
        workflow = AnalysisItemWorkflow(
            **workflow_kwargs,
            benchmark_projection=benchmark_projection,
        )
        result = await workflow.run(payload, task_run_context)
        return result.output

    async def _run_analysis_item_task(
        self,
        run_context: RunContext,
        *,
        checkpoint: ReportingCheckpoint,
        revision: int,
        sandbox_id: str,
        validation_context_file: FileIdentity,
        detailed_plan: DetailedAnalysisPlan,
        dataset_handles: tuple[DatasetHandle, ...],
        lineage: tuple[DatasetLineage, ...],
        citation_bindings: tuple[Citation, ...],
        analysis_context_file: FileIdentity,
        fact_files: Mapping[str, FileIdentity],
        analysis_id: str,
        section_goal: Mapping[str, Any],
        retry_reason: str | None,
        feedback: str | None,
        rework_request: AnalysisReworkRequest | None,
    ) -> ReportingCheckpoint:
        scope = self._scope(run_context)
        report_run_id = str(run_context.run_id or scope["externalRunId"])
        analysis = next(
            (item for item in detailed_plan.analyses if item.analysis_id == analysis_id),
            None,
        )
        if analysis is None or analysis_id not in fact_files:
            raise ReportingError(
                "report_analysis_item_unknown",
                "analysisId 不在冻结分析计划或固定事实文件中。",
            )
        selected_dataset_ids = set(analysis.dataset_ids)
        selected_handles = tuple(
            item for item in dataset_handles if item.dataset_id in selected_dataset_ids
        )
        if {item.dataset_id for item in selected_handles} != selected_dataset_ids:
            raise ReportingError(
                "report_analysis_context_unavailable",
                "当前分析项没有精确绑定全部不可变 Dataset。",
            )
        selected_lineage = tuple(
            item for item in lineage if item.dataset_id in selected_dataset_ids
        )
        selected_citations = tuple(
            item for item in citation_bindings if item.dataset_id in selected_dataset_ids
        )
        raw_contexts = self._state(run_context).get(REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY, ())
        try:
            dataset_contexts = tuple(
                DatasetAnalysisContext.model_validate(item) for item in raw_contexts
            )
            dataset_inputs = _analysis_item_dataset_inputs(selected_handles, dataset_contexts)
        except (TypeError, ValueError, ValidationError) as error:
            if isinstance(error, ReportingError):
                raise
            raise ReportingError(
                "report_analysis_context_unavailable",
                "分析数据上下文缺失或无效。",
            ) from error
        reporting_analysis_plan = _reporting_detailed_analysis_plan(
            detailed_plan,
            analysis_ids=(analysis_id,),
        )
        analysis_plan = reporting_analysis_plan["analyses"][0]
        deterministic_facts = cast(
            DeterministicAnalysisBundle,
            await self._read_identity_model(
                scope["threadId"], fact_files[analysis_id], DeterministicAnalysisBundle
            ),
        )
        if deterministic_facts.analysis_id != analysis_id:
            raise ReportingError(
                "report_analysis_facts_invalid",
                "固定 facts 文件与当前分析项身份不一致。",
            )
        last_error: Exception | None = _checkpoint_retry_error(
            checkpoint,
            work_kind="analysis_item",
            analysis_id=analysis_id,
            retry_reason=retry_reason,
        )

        for _ in range(MAX_REPORT_SECTION_PHASE_ATTEMPTS):
            matching_traces = [
                item
                for item in checkpoint.trace
                if item.phase == "analysis"
                and item.work_kind == "analysis_item"
                and item.analysis_id == analysis_id
                and item.retry_reason == retry_reason
            ]
            started_trace = next(
                (item for item in reversed(matching_traces) if item.status == "started"),
                None,
            )
            attempt = (
                started_trace.attempt
                if started_trace is not None
                else max(
                    (
                        item.attempt
                        for item in checkpoint.trace
                        if item.phase == "analysis"
                        and item.work_kind == "analysis_item"
                        and item.analysis_id == analysis_id
                    ),
                    default=-1,
                )
                + 1
            )
            task_id = reporting_phase_task_key(
                report_run_id,
                revision,
                "analysis",
                analysis_id=analysis_id,
                attempt=attempt,
            )
            retry = any(item.status == "failed" for item in matching_traces)
            effective_retry_reason = retry_reason or (
                last_error.code if isinstance(last_error, ReportingError) else None
            )
            thinking_failure_kind = (
                _analysis_evidence_failure_kind(effective_retry_reason) if retry else None
            )
            durable_before = await self.state_repository.get(report_run_id)
            durable_payload = durable_before.payload if durable_before is not None else {}
            durable_items = durable_payload.get("analysisItems")
            durable_item = (
                durable_items.get(analysis_id) if isinstance(durable_items, dict) else None
            )
            recovery_payload = None
            if isinstance(durable_item, dict):
                recovery_payload = {
                    key: value
                    for key, value in durable_item.items()
                    if key
                    in {
                        "analysisId",
                        "summary",
                        "datasetIds",
                        "evidencePaths",
                        "citationIds",
                        "metrics",
                        "chartIds",
                        "profileReadReceiptIds",
                        "warnings",
                    }
                }
            analysis_output_root = _analysis_item_output_root(report_run_id, analysis_id, attempt)
            instruction_payload = {
                "phase": "analysis",
                "taskKind": "analysis_item",
                "reportGoal": self._envelope(run_context).report_goal,
                "sectionGoal": dict(section_goal),
                "currentAnalysisId": analysis_id,
                "currentAnalysis": analysis_plan,
                "thinkingFailureKind": thinking_failure_kind,
                "analysisOutputRoot": analysis_output_root,
                "completionConditions": _analysis_item_completion_conditions(
                    recovery_payload,
                    last_error,
                ),
                "deterministicFactFile": fact_files[analysis_id].model_dump(
                    mode="json", by_alias=True
                ),
                "deterministicFacts": _model_facing_deterministic_facts(deterministic_facts),
                "profileCoverage": _profile_coverage_instruction_projection(
                    checkpoint.profile_coverage,
                    analysis_context_file,
                    dataset_ids=selected_dataset_ids,
                ),
                "analysisContextFile": analysis_context_file.model_dump(mode="json", by_alias=True),
                "datasets": dataset_inputs,
                "datasetLineage": [
                    item.model_dump(mode="json", by_alias=True) for item in selected_lineage
                ],
                "citationRegistry": [
                    item.model_dump(mode="json", by_alias=True) for item in selected_citations
                ],
                "sourceWarnings": [
                    item.model_dump(mode="json", by_alias=True)
                    for item in _source_warnings_from_state(self._state(run_context))
                    if set(item.dataset_ids) & selected_dataset_ids
                ],
                "reviewFeedback": feedback,
                "analysisReworkRequest": (
                    rework_request.model_dump(mode="json", by_alias=True)
                    if rework_request is not None and analysis_id in rework_request.analysis_ids
                    else None
                ),
                "durableAnalysisItem": recovery_payload,
            }
            instruction = json.dumps(instruction_payload, ensure_ascii=False, separators=(",", ":"))
            instruction_bytes = len(instruction.encode("utf-8"))
            if instruction_bytes > MAX_REPORT_INSTRUCTION_BYTES:
                raise ReportingError(
                    "report_analysis_context_too_large",
                    "单项分析投影超过模型输入边界；证据未被静默截断。",
                )
            (
                policy_effort,
                thinking_budget,
                complexity_tier,
            ) = _analysis_item_thinking_policy(
                analysis_plan, retry=retry, retry_reason=effective_retry_reason
            )
            complexity_score, _ = _analysis_item_complexity(analysis_plan)
            analysis_effort = self._analysis_thinking_effort()
            thinking_effort = "off" if analysis_effort == "off" else policy_effort
            analysis_fact_queries_used = _analysis_fact_retry_usage(last_error)
            analysis_recovery = _analysis_fact_recovery_required(last_error)
            contract = build_report_phase_acceptance_contract(
                phase="analysis",
                validation_context_file=validation_context_file.model_dump(
                    mode="json", by_alias=True
                ),
                phase_contract={
                    "reportRunId": report_run_id,
                    "taskKind": "analysis_item",
                    "thinkingEffort": thinking_effort,
                    "thinkingBudget": thinking_budget,
                    "thinkingComplexityTier": complexity_tier,
                    "thinkingComplexityScore": complexity_score,
                    "thinkingEscalationReason": (
                        effective_retry_reason if thinking_effort == "max" else None
                    ),
                    "analysisIds": [analysis_id],
                    "currentAnalysisId": analysis_id,
                    "analysisFactBudgetVersion": 1,
                    "analysisFactQueryLimit": _analysis_fact_query_limit_for_plan(analysis_plan),
                    "analysisFactQueriesUsed": analysis_fact_queries_used,
                    "analysisRecovery": analysis_recovery,
                    "analysisOutputRoot": analysis_output_root,
                    "analysisPlans": {analysis_id: analysis_plan},
                    "analysisDatasetIds": {analysis_id: list(analysis.dataset_ids)},
                    "deterministicFactFiles": {
                        analysis_id: fact_files[analysis_id].model_dump(mode="json", by_alias=True)
                    },
                    "datasetIds": [item.dataset_id for item in selected_handles],
                    "citationIds": [item.citation_id for item in selected_citations],
                    "citationRegistry": [
                        item.model_dump(mode="json", by_alias=True) for item in selected_citations
                    ],
                },
            )
            task_scope = TaskExecutionScope(
                task_id,
                scope["userId"],
                scope["threadId"],
                sandbox_id,
                "reporting-analysis-workflow",
            )
            if started_trace is None:
                checkpoint = self._update_reporting_checkpoint(
                    checkpoint,
                    phase="analysis",
                    trace=(
                        *checkpoint.trace,
                        ContextTrace(
                            phase="analysis",
                            taskId=task_id,
                            workKind="analysis_item",
                            analysisId=analysis_id,
                            attempt=attempt,
                            instructionBytes=instruction_bytes,
                            projectedContextBytes=instruction_bytes,
                            retryReason=retry_reason,
                        ),
                    ),
                    last_error=None,
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
            trace_metrics: dict[str, Any] = {}
            started_at = time.monotonic()
            try:
                existing = await self.task_runner.repository.get_task_snapshot(task_id)
                if existing is None:
                    await self.task_runner.start(
                        task_scope, instruction, acceptance_contract=contract
                    )
                elif existing.state in {TaskState.FAILED, TaskState.CANCELLED}:
                    raise ReportingError(
                        "report_analysis_task_terminal",
                        f"分析项 {analysis_id} Task 未完成收尾即终止。",
                    )

                async def execute_analysis_item(invocation):
                    settlement = invocation.model_metrics_settlement
                    return await self._execute_analysis_item_workflow(
                        invocation.instruction,
                        invocation.run_context,
                        parent_run_context=run_context,
                        model_metrics_recorder=settlement.record_run_output,
                        planner_model_metrics_recorder=settlement.stage_recorder(
                            "planner", agent_role="analysis-evidence-planner"
                        ),
                        coding_model_metrics_recorder=settlement.stage_recorder(
                            "coding", agent_role="analysis-coding"
                        ),
                        summary_model_metrics_recorder=settlement.stage_recorder(
                            "summary", agent_role="analysis-summary"
                        ),
                    )

                receipt = await self.task_runner.run(
                    task_scope,
                    parent_run_id=str(run_context.run_id or ""),
                    executor=execute_analysis_item,
                )
                trace_metrics = self._trace_metrics_from_receipt(receipt)
                trace_metrics["duration_seconds"] = time.monotonic() - started_at
                durable_after = await self.state_repository.get(report_run_id)
                durable_items_after = (
                    durable_after.payload.get("analysisItems")
                    if durable_after is not None
                    else None
                )
                completed_item = (
                    durable_items_after.get(analysis_id)
                    if isinstance(durable_items_after, dict)
                    else None
                )
                if not isinstance(completed_item, dict):
                    raise ReportingError(
                        "report_analysis_evidence_incomplete",
                        "analysis item Task 完成后 durable evidence 缺失。",
                    )
                expected_files = tuple(
                    FileIdentity.model_validate(item)
                    for item in completed_item.get("evidenceFiles", ())
                )
                identities = await self._analysis_item_artifacts_from_receipt(
                    scope["threadId"], receipt, expected_files
                )
                checkpoint = self._replace_trace(
                    checkpoint,
                    task_id,
                    status="completed",
                    pointer_receipt_ids=tuple(
                        item
                        for item in completed_item.get("profileReadReceiptIds", ())
                        if isinstance(item, str)
                    ),
                    **trace_metrics,
                )
                checkpoint = self._update_reporting_checkpoint(
                    checkpoint,
                    files=self._merge_checkpoint_files(checkpoint.files, *identities),
                    last_error=None,
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
                return checkpoint
            except Exception as error:
                last_error = error
                trace_metrics.setdefault("duration_seconds", time.monotonic() - started_at)
                code = (
                    error.code
                    if isinstance(error, ReportingError)
                    else "report_analysis_phase_failed"
                )
                message = (error.message if isinstance(error, ReportingError) else str(error))[
                    :2000
                ]
                checkpoint = self._replace_trace(
                    checkpoint,
                    task_id,
                    status="failed",
                    **trace_metrics,
                )
                checkpoint = self._update_reporting_checkpoint(
                    checkpoint,
                    phase="analysis",
                    last_error={
                        "phase": "analysis",
                        "code": code,
                        "message": message or "独立分析项失败。",
                        "retryReason": retry_reason or code,
                        "taskId": task_id,
                        "workKind": "analysis_item",
                        "analysisId": analysis_id,
                        "attempt": attempt,
                        "retryUsage": _checkpoint_retry_usage(
                            error, work_kind="analysis_item"
                        ).model_dump(mode="json", by_alias=True),
                    },
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
        assert last_error is not None
        raise last_error

    async def _restore_or_create_deterministic_analysis_facts(
        self,
        *,
        run_context: RunContext,
        checkpoint: ReportingCheckpoint,
        thread_id: str,
        report_run_id: str,
        revision: int,
        detailed_plan: DetailedAnalysisPlan,
        dataset_handles: tuple[DatasetHandle, ...],
    ) -> tuple[ReportingCheckpoint, dict[str, FileIdentity]]:
        """恢复同 revision 的 facts 权威身份；只有无分析进度的新 checkpoint 可生成。"""

        analysis_ids = tuple(item.analysis_id for item in detailed_plan.analyses)
        facts_root = f"报表/智能分析/{report_run_id}/facts/revision-{revision}"
        expected_paths = {
            analysis_id: f"{facts_root}/{analysis_id}.json" for analysis_id in analysis_ids
        }
        fact_files = dict(checkpoint.deterministic_fact_files)
        recovered_legacy_mapping = False

        if not fact_files:
            # 旧 v2 没有 analysisId 映射，只允许从通用账本中精确恢复当前 run/revision
            # 的规范文件集；部分匹配或额外 facts 都无法证明计划绑定，必须失败关闭。
            candidates_by_path: dict[str, list[FileIdentity]] = {}
            for identity in checkpoint.files:
                if identity.path.startswith(f"{facts_root}/"):
                    candidates_by_path.setdefault(identity.path, []).append(identity)
            if candidates_by_path:
                if set(candidates_by_path) != set(expected_paths.values()) or any(
                    len(candidates) != 1 for candidates in candidates_by_path.values()
                ):
                    raise ReportingError(
                        "report_semantic_contract_upgrade_required",
                        "运行中的 Reporting checkpoint 缺少完整的确定性 facts 身份映射。",
                    )
                fact_files = {
                    analysis_id: candidates_by_path[path][0]
                    for analysis_id, path in expected_paths.items()
                }
                recovered_legacy_mapping = True
            else:
                has_unmapped_fact_identity = any(
                    "/facts/revision-" in identity.path for identity in checkpoint.files
                )
                has_analysis_progress = (
                    checkpoint.phase != "analysis"
                    or checkpoint.report_brief is not None
                    or checkpoint.evidence_manifest is not None
                    or checkpoint.analysis_manifest_file is not None
                    or has_unmapped_fact_identity
                    or (
                        checkpoint.last_error is not None
                        and checkpoint.last_error.phase == "analysis"
                    )
                    or any(item.phase == "analysis" for item in checkpoint.trace)
                )
                if has_analysis_progress:
                    raise ReportingError(
                        "report_semantic_contract_upgrade_required",
                        "运行中的 Reporting checkpoint 缺少确定性 facts 身份映射。",
                    )
                fact_files = await self._prepare_deterministic_analysis_facts(
                    run_context=run_context,
                    thread_id=thread_id,
                    report_run_id=report_run_id,
                    revision=revision,
                    detailed_plan=detailed_plan,
                    dataset_handles=dataset_handles,
                )
                if set(fact_files) != set(analysis_ids) or any(
                    fact_files[analysis_id].path != expected_paths[analysis_id]
                    for analysis_id in analysis_ids
                ):
                    raise ReportingError(
                        "report_analysis_facts_invalid",
                        "确定性 facts 没有精确覆盖冻结分析计划。",
                    )
                checkpoint = self._update_reporting_checkpoint(
                    checkpoint,
                    deterministic_fact_files=fact_files,
                    files=self._merge_checkpoint_files(checkpoint.files, *fact_files.values()),
                )
                checkpoint = await self._persist_reporting_checkpoint(run_context, checkpoint)
                return checkpoint, fact_files

        # 映射是后续 Reporting Agent 的唯一 facts 来源。每次恢复均先核验计划、规范路径和普通
        # 文件的 size/SHA-256；不允许重新读取 Dataset 重算后覆盖已签发的事实身份。
        if set(fact_files) != set(analysis_ids) or any(
            fact_files[analysis_id].path != expected_paths[analysis_id]
            for analysis_id in analysis_ids
        ):
            raise ReportingError(
                "report_semantic_contract_upgrade_required",
                "运行中的 Reporting checkpoint 缺少完整的确定性 facts 身份映射。",
            )

        for analysis_id in analysis_ids:
            expected = fact_files[analysis_id]
            actual_value: Any = None
            try:
                actual_value = await self.workspace_service.ahash_file(thread_id, expected.path)
                actual = FileIdentity.model_validate(actual_value)
            except Exception as error:
                actual_size = (
                    actual_value.get("size") if isinstance(actual_value, Mapping) else None
                )
                actual_sha256 = (
                    actual_value.get("sha256") if isinstance(actual_value, Mapping) else None
                )
                loguru_logger.warning(
                    "report_analysis_facts_changed path={} expected_size={} actual_size={} "
                    "expected_sha256={} actual_sha256={}",
                    expected.path,
                    expected.size,
                    actual_size,
                    expected.sha256,
                    actual_sha256,
                )
                raise ReportingError(
                    "report_analysis_facts_changed",
                    "确定性 facts 文件缺失、类型无效或身份已变化。",
                ) from error
            if actual != expected:
                loguru_logger.warning(
                    "report_analysis_facts_changed path={} expected_size={} actual_size={} "
                    "expected_sha256={} actual_sha256={}",
                    expected.path,
                    expected.size,
                    actual.size,
                    expected.sha256,
                    actual.sha256,
                )
                raise ReportingError(
                    "report_analysis_facts_changed",
                    "确定性 facts 文件身份已变化。",
                )

        if recovered_legacy_mapping:
            checkpoint = self._update_reporting_checkpoint(
                checkpoint,
                deterministic_fact_files=fact_files,
            )
            checkpoint = await self._persist_reporting_checkpoint(run_context, checkpoint)
        return checkpoint, fact_files

    async def _prepare_deterministic_analysis_facts(
        self,
        *,
        run_context: RunContext,
        thread_id: str,
        report_run_id: str,
        revision: int,
        detailed_plan: DetailedAnalysisPlan,
        dataset_handles: tuple[DatasetHandle, ...],
    ) -> dict[str, FileIdentity]:
        raw_contexts = self._state(run_context).get(REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY, ())
        context_values = tuple(
            DatasetAnalysisContext.model_validate(item)
            for item in raw_contexts
            if isinstance(item, Mapping)
        )
        context_by_id = {item.dataset_id: item for item in context_values}
        handle_by_id = {item.dataset_id: item for item in dataset_handles}
        profile = self._profile(run_context)
        profile_metrics = tuple(
            item.model_dump(mode="json", by_alias=True) for item in profile.metrics
        )
        profile_reconciliations = tuple(
            item.model_dump(mode="json", by_alias=True) for item in profile.reconciliations
        )
        profile_dimensions = tuple(
            item.model_dump(mode="json", by_alias=True) for item in profile.dimensions
        )
        contents: dict[str, bytes] = {}
        for handle in dataset_handles:
            content = await self.workspace_service.read_limited_regular_file(
                thread_id,
                handle.path,
                max_bytes=handle.size,
            )
            if len(content) != handle.size or hashlib.sha256(content).hexdigest() != handle.sha256:
                raise ReportingError("stale_dataset", "确定性事实计算前 Dataset 身份已变化。")
            contents[handle.dataset_id] = content
        identities: dict[str, FileIdentity] = {}
        for analysis in detailed_plan.analyses:
            datasets = tuple(
                (
                    dataset_id,
                    contents[dataset_id],
                    context_by_id[dataset_id],
                    handle_by_id[dataset_id].period_roles,
                )
                for dataset_id in analysis.dataset_ids
            )
            bundle = await anyio.to_thread.run_sync(
                partial(
                    build_deterministic_analysis_bundle,
                    analysis,
                    datasets,
                    profile_metrics=profile_metrics,
                    profile_reconciliations=profile_reconciliations,
                    profile_dimensions=profile_dimensions,
                    profile_hash=profile.effective_profile_hash,
                )
            )
            try:
                validate_metric_code_bindings(bundle)
            except ValueError as error:
                raise ReportingError(
                    "report_analysis_metric_definition_incomplete",
                    "确定性数值事实缺少 Effective Profile 提供的权威指标定义，已拒绝冻结。",
                    details={"analysisId": analysis.analysis_id, "reason": str(error)},
                ) from error
            content = json.dumps(
                bundle.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            path = (
                f"报表/智能分析/{report_run_id}/facts/revision-{revision}/"
                f"{analysis.analysis_id}.json"
            )
            identity = await self._write_immutable_artifact(thread_id, path, content)
            identities[analysis.analysis_id] = identity
            await self._apply_durable_command(
                run_context,
                ReportingCommand(
                    name="record_artifact",
                    commandId=f"deterministic-fact:{analysis.analysis_id}:{identity.sha256}",
                    payload={"artifact": identity.model_dump(mode="json", by_alias=True)},
                ),
            )
        return identities


def _visualization_section_retry_error(
    checkpoint: ReportingCheckpoint,
    *,
    section_code: str,
) -> ReportingError | None:
    """按 sectionCode 从失败账本恢复该章的稳定错误与预算,驱动章节 fresh retry。

    账本条目必须与 trace 中该章最近一次失败记录的 taskId/attempt 完全一致,
    且携带完整 retryUsage;否则说明 checkpoint 状态不可信(例如账本与 trace
    来自不同写入轮次),必须失败关闭而不是静默重置预算。
    """

    stored = checkpoint.visualization_section_errors.get(section_code)
    if stored is None:
        return None
    matching_failure = next(
        (
            item
            for item in reversed(checkpoint.trace)
            if item.phase == "analysis"
            and item.work_kind == "visualization_section"
            and item.section_code == section_code
            and item.status == "failed"
        ),
        None,
    )
    if (
        stored.phase != "analysis"
        or stored.work_kind != "visualization_section"
        or stored.section_code != section_code
        or stored.retry_usage is None
        or matching_failure is None
        or stored.task_id != matching_failure.task_id
        or stored.attempt != matching_failure.attempt
    ):
        raise ReportingError(
            "report_semantic_contract_upgrade_required",
            "运行中的 Reporting checkpoint 缺少可信章节恢复身份或预算，请重新分析。",
        )
    error = ReportingError(stored.code, stored.message)
    setattr(
        error,
        REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
        stored.retry_usage.model_dump(mode="python", by_alias=True),
    )
    return error


def _visualization_section_completion_conditions(last_error: Exception | None) -> list[str]:
    conditions = [
        "只处理当前 sectionCode 及其 outline.analysisIds；跨域章节不得扩大事实范围",
        "返回完整 VisualizationPlanDraft；只包含 charts 和 warnings，不得返回脚本路径或源码",
        "固定 Workflow 负责脚本生成、执行、审查和图表提交",
    ]
    if _visualization_recovery_required(last_error):
        conditions.insert(
            0,
            "上一轮工具或脚本失败；仅生成满足冻结事实的图表计划，不重新探索工作区",
        )
    return conditions


def _checkpoint_retry_error(
    checkpoint: ReportingCheckpoint,
    *,
    work_kind: Literal["analysis_item", "visualization_section"],
    analysis_id: str | None,
    retry_reason: str | None,
) -> ReportingError | None:
    """仅将当前失败工作对应的稳定错误恢复为 fresh attempt 状态。"""

    matching_failure = next(
        (
            item
            for item in reversed(checkpoint.trace)
            if item.phase == "analysis"
            and item.work_kind == work_kind
            and item.analysis_id == analysis_id
            and item.retry_reason == retry_reason
            and item.status == "failed"
        ),
        None,
    )
    if matching_failure is None:
        return None
    stored = checkpoint.last_error
    if (
        stored is None
        or stored.phase != "analysis"
        or stored.task_id != matching_failure.task_id
        or stored.work_kind != matching_failure.work_kind
        or stored.analysis_id != matching_failure.analysis_id
        or stored.attempt != matching_failure.attempt
        or stored.retry_usage is None
    ):
        raise ReportingError(
            "report_semantic_contract_upgrade_required",
            "运行中的 Reporting checkpoint 缺少可信恢复身份或预算，请重新分析。",
        )
    error = ReportingError(stored.code, stored.message)
    usage = stored.retry_usage
    if work_kind == "analysis_item":
        setattr(
            error,
            REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR,
            {"queryCount": usage.analysis_fact_queries_used},
        )
    else:
        setattr(
            error,
            REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
            usage.model_dump(mode="python", by_alias=True),
        )
    return error


def _checkpoint_retry_usage(
    error: Exception,
    *,
    work_kind: Literal["analysis_item", "visualization_section"],
) -> CheckpointRetryUsage:
    if work_kind == "analysis_item":
        return CheckpointRetryUsage(analysisFactQueriesUsed=_analysis_fact_retry_usage(error))
    source = getattr(error, REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR, None)
    attempt_successes = (
        source.get("visualizationAttemptSuccessfulToolCalls", 0)
        if isinstance(source, Mapping)
        else 0
    )
    attempt_rejections = (
        source.get("visualizationAttemptRejectedToolCalls", 0) if isinstance(source, Mapping) else 0
    )
    return CheckpointRetryUsage(
        **_visualization_retry_usage(error),
        visualizationAttemptSuccessfulToolCalls=attempt_successes,
        visualizationAttemptRejectedToolCalls=attempt_rejections,
    )


def _reporting_detailed_analysis_plan(
    plan: DetailedAnalysisPlan,
    *,
    analysis_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """向成稿 Agent 投影 Codex 风格步骤，完整事实继续由受信上下文承载。"""
    allowed = set(analysis_ids) if analysis_ids is not None else None
    return {
        "version": plan.version,
        "analyses": [
            {
                "analysisId": item.analysis_id,
                "domain": item.domain,
                "step": item.management_question,
                "primaryMetricFamily": item.primary_metric_family,
                "datasetIds": list(item.dataset_ids),
                "fields": list(item.fields),
                "metrics": list(item.metrics),
                "organizationGrain": list(item.organization_grain),
                "actions": list(item.actions),
                "limitations": list(item.limitations),
            }
            for item in plan.analyses
            if allowed is None or item.analysis_id in allowed
        ],
    }


def _finalize_semantic_catalog(
    *,
    analysis_plans: Mapping[str, Mapping[str, Any]],
    fact_bundles: Mapping[str, Mapping[str, Any]],
    dataset_ids: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """从冻结计划与 facts 投影目录；可修复语义缺陷以 finding 返回。"""

    _require_dataset_id_sequence(
        dataset_ids,
        error_message="evidence Dataset 集合不能为空。",
        error_code="report_analysis_semantic_invalid",
    )
    if not analysis_plans:
        raise ReportingError("report_analysis_semantic_invalid", "分析计划不能为空。")

    grains_by_dataset: dict[str, set[str]] = {dataset_id: set() for dataset_id in dataset_ids}
    planned_dataset_ids: set[str] = set()
    for plan in analysis_plans.values():
        raw_dataset_ids = plan.get("datasetIds")
        raw_grain = plan.get("organizationGrain")
        if not isinstance(raw_dataset_ids, Sequence) or isinstance(raw_dataset_ids, (str, bytes)):
            raise ReportingError("report_analysis_dataset_inconsistent", "分析计划 Dataset 无效。")
        grains = (
            {item for item in raw_grain if isinstance(item, str) and item}
            if isinstance(raw_grain, Sequence) and not isinstance(raw_grain, (str, bytes))
            else set()
        )
        for dataset_id in raw_dataset_ids:
            if not isinstance(dataset_id, str) or not dataset_id:
                raise ReportingError(
                    "report_analysis_dataset_inconsistent", "分析计划包含无效 Dataset。"
                )
            planned_dataset_ids.add(dataset_id)
            if dataset_id not in grains_by_dataset:
                raise ReportingError(
                    "report_analysis_semantic_invalid",
                    "分析计划 Dataset 与 evidence-derived Dataset 不一致。",
                )
            grains_by_dataset[dataset_id].update(grains)
    if planned_dataset_ids != set(dataset_ids):
        raise ReportingError(
            "report_analysis_dataset_inconsistent",
            "分析计划 Dataset 必须精确覆盖 evidence-derived Dataset。",
        )
    findings: list[dict[str, Any]] = []
    for dataset_id, grains in grains_by_dataset.items():
        if not grains:
            findings.append(
                {
                    "ruleCode": "report_dataset_grain_missing",
                    "subjectType": "dataset_semantics",
                    "subjectId": dataset_id,
                    "message": "Dataset 缺少 organization grain，需后续修复。",
                    "details": {"reasonCode": "organization_grain_missing"},
                }
            )

    dataset_semantics = []
    for dataset_id in dataset_ids:
        grains = grains_by_dataset[dataset_id]
        row_grain = "+".join(sorted(grains)) or "unknown"
        if len(row_grain) > 128:
            row_grain = "unknown"
        dataset_semantics.append(
            {
                "datasetId": dataset_id,
                "rowGrain": row_grain,
                "duplicateResolution": "not_applicable",
            }
        )

    facts_by_code: dict[str, list[Mapping[str, Any]]] = {}
    for bundle in fact_bundles.values():
        raw_metrics = bundle.get("metrics", ())
        if isinstance(raw_metrics, Sequence) and not isinstance(raw_metrics, (str, bytes)):
            for metric in raw_metrics:
                if not isinstance(metric, Mapping):
                    continue
                metric_codes: set[str] = set()
                raw_codes = metric.get("metricCodes", ())
                if isinstance(raw_codes, Sequence) and not isinstance(raw_codes, (str, bytes)):
                    for code in raw_codes:
                        if isinstance(code, str) and code:
                            metric_codes.add(code)
                # facts 的 field 是数据集物理指标名，metricCodes 是规范业务指标名。
                # 图表与章节都可能引用前者，因此二者必须共享同一条受信事实定义；
                # 这里只登记既有事实别名，不推断公式，也不放宽后续引用校验。
                field = metric.get("field")
                if isinstance(field, str) and field:
                    metric_codes.add(field)
                for code in metric_codes:
                    facts_by_code.setdefault(code, []).append(metric)
        raw_derived = bundle.get("derivedMetrics", ())
        if isinstance(raw_derived, Sequence) and not isinstance(raw_derived, (str, bytes)):
            for metric in raw_derived:
                if isinstance(metric, Mapping) and isinstance(metric.get("code"), str):
                    facts_by_code.setdefault(metric["code"], []).append(metric)

    metric_definitions = []
    for code in sorted(facts_by_code):
        facts = facts_by_code[code]
        name = code
        formulas = sorted(
            {
                formula
                for fact in facts
                if isinstance((formula := fact.get("formula")), str) and formula
            }
        )
        unit_values = {fact.get("unit") for fact in facts}
        units_valid = len(unit_values) == 1 and all(
            unit is None or (isinstance(unit, str) and bool(unit)) for unit in unit_values
        )
        periods = sorted(
            {
                (period_start, period_end)
                for fact in facts
                if isinstance((period_start := fact.get("periodStart")), str)
                and period_start
                and isinstance((period_end := fact.get("periodEnd")), str)
                and period_end
            }
        )
        # 同一指标可在当前期、同比期等多个冻结事实中重复出现。目录只表达其
        # 唯一计算定义和覆盖期间，不能把多个完整期间误判为定义冲突；但每条事实
        # 仍必须具备完整 formula、unit 和期间边界，避免用部分证据补全语义目录。
        if (
            any(
                not isinstance(fact.get("formula"), str)
                or not fact["formula"]
                or not isinstance(fact.get("periodStart"), str)
                or not fact["periodStart"]
                or not isinstance(fact.get("periodEnd"), str)
                or not fact["periodEnd"]
                for fact in facts
            )
            or len(formulas) != 1
            or not units_valid
        ):
            missing_fields = []
            if len(formulas) != 1:
                missing_fields.append("formula")
            if not units_valid:
                missing_fields.append("unit")
            if not periods or any(
                not fact.get("periodStart") or not fact.get("periodEnd") for fact in facts
            ):
                missing_fields.append("period")
            findings.append(
                {
                    "ruleCode": "report_metric_semantic_incomplete",
                    "subjectType": "metric_definition",
                    "subjectId": code,
                    "message": f"指标 {code} 的语义定义缺失或冲突，需后续修复。",
                    "details": {"metricCode": code, "missingFields": sorted(set(missing_fields))},
                }
            )
            continue
        period_basis = "；".join(
            period_start if period_start == period_end else f"{period_start} 至 {period_end}"
            for period_start, period_end in periods
        )
        metric_definitions.append(
            {
                "code": code,
                "name": name,
                "definition": "；".join((name, *formulas))[:2000],
                "unit": next(iter(unit_values)),
                "periodBasis": period_basis,
            }
        )
    return dataset_semantics, metric_definitions, findings


def _require_dataset_id_sequence(
    value: object,
    *,
    error_message: str,
    error_code: str = "report_analysis_dataset_inconsistent",
) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ReportingError(error_code, error_message)
    return tuple(value)


def _analysis_item_completion_conditions(
    recovery_payload: dict[str, Any] | None,
    last_error: Exception | None,
) -> list[str]:
    if recovery_payload is not None:
        return [
            "durable 单项事实已冻结；不要重算或改写 evidence",
            "使用 durableAnalysisItem 的相同字段重新调用 complete_analysis_item 完成 Task 收尾",
        ]
    if _analysis_fact_recovery_required(last_error):
        return [
            "上一轮已耗尽 facts 查询额度；不得重新查询、读取、写入或执行任何工具",
            "直接使用 deterministicFacts 中已内联的受信事实，立即且只调用一次 complete_analysis_item",
        ]
    if (
        isinstance(last_error, ReportingError)
        and last_error.code == "report_analysis_tool_budget_exhausted"
    ):
        return [
            "上一轮因成功工具调用达到上限而终止；禁止继续探索 Profile、创建脚本或生成补充 evidence",
            "只调用一次 query_analysis_facts 读取 deterministicFactFile 中当前管理问题所需的最小事实",
            "随后立即调用 complete_analysis_item；evidencePaths 传空数组，不得调用其他工具",
        ]
    return [
        "只回答 currentAnalysis 的原子管理问题和 primaryMetricFamily",
        "deterministicFacts 已内联当前分析项的受信固定事实；"
        "先根据 currentAnalysis 判断其是否覆盖当前管理问题的必需事实；"
        "不得为探索 facts 结构、重复验证任务 JSON 已投影的元数据或空命中调用 query_analysis_facts",
        "固定事实足够时立即调用 complete_analysis_item；不得查询、读取 Profile、读取 CSV、"
        "创建脚本或 evidence，evidencePaths 传空数组，且只调用一次",
        "仅当前管理问题确实缺少必需事实时，才按缺口精确调用 query_analysis_facts 或读取实际使用的 Profile；"
        "不得猜测、补齐或替代缺失事实",
        "仅当 deterministicFactFile 仍未覆盖该事实缺口时，才从已绑定 CSV 创建最小补充 evidence",
        "本阶段禁止生成或登记图表",
        "最后且只调用一次 complete_analysis_item",
    ]


def _visualization_recovery_required(last_error: Exception | None) -> bool:
    """预算耗尽或 no-progress 终止后只允许复用既有可视化产物。"""

    return isinstance(last_error, ReportingError) and (
        last_error.code in _VISUALIZATION_RECOVERY_ERROR_CODES
        or (
            isinstance(last_error.details, dict)
            and last_error.details.get("terminalReason") == "tool_no_progress"
        )
    )


def _analysis_fact_recovery_required(last_error: Exception | None) -> bool:
    return (
        isinstance(last_error, ReportingError)
        and last_error.code == "report_analysis_fact_query_budget_exhausted"
    )


def _analysis_fact_retry_usage(last_error: Exception | None) -> int:
    source: Any = getattr(last_error, REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR, None)
    details = last_error.details if isinstance(last_error, ReportingError) else None

    if isinstance(source, Mapping):
        return _nonnegative_int(source.get("queryCount"))
    if isinstance(details, Mapping):
        return _nonnegative_int(details.get("queryCount"))
    return 0


def _visualization_retry_usage(last_error: Exception | None) -> dict[str, int]:
    source: Any = getattr(last_error, REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR, None)
    details = last_error.details if isinstance(last_error, ReportingError) else None

    if isinstance(source, Mapping):
        usage = {
            "visualizationReadUnitsUsed": _nonnegative_int(
                source.get("visualizationReadUnitsUsed")
            ),
            "visualizationFactQueriesUsed": _nonnegative_int(
                source.get("visualizationFactQueriesUsed")
            ),
            "visualizationToolCalls": _nonnegative_int(
                source.get("visualizationToolCalls", source.get("totalToolCalls"))
            ),
            "visualizationScriptFailures": _nonnegative_int(
                source.get("visualizationScriptFailures", source.get("scriptFailureCount"))
            ),
        }
        # 预算终态错误在动态预留点生成，details 对总调用和脚本失败的计数最及时；
        # read/fact 则只能来自执行器退出时附加的完整累计快照，两者必须合并。
        if isinstance(details, Mapping):
            if "totalToolCalls" in details:
                usage["visualizationToolCalls"] = _nonnegative_int(details.get("totalToolCalls"))
            if "scriptFailureCount" in details:
                usage["visualizationScriptFailures"] = _nonnegative_int(
                    details.get("scriptFailureCount")
                )
        return usage
    if isinstance(source, Sequence) and not isinstance(source, (str, bytes)) and len(source) == 2:
        return {
            "visualizationReadUnitsUsed": 0,
            "visualizationFactQueriesUsed": 0,
            "visualizationToolCalls": _nonnegative_int(source[0]),
            "visualizationScriptFailures": _nonnegative_int(source[1]),
        }
    if isinstance(details, Mapping):
        return {
            "visualizationReadUnitsUsed": 0,
            "visualizationFactQueriesUsed": 0,
            "visualizationToolCalls": _nonnegative_int(details.get("totalToolCalls")),
            "visualizationScriptFailures": _nonnegative_int(details.get("scriptFailureCount")),
        }
    return {
        "visualizationReadUnitsUsed": 0,
        "visualizationFactQueriesUsed": 0,
        "visualizationToolCalls": 0,
        "visualizationScriptFailures": 0,
    }


def _visualization_dynamic_budget(
    analysis_items: Any,
    fact_files: Mapping[str, FileIdentity],
) -> dict[str, int]:
    """从冻结文件身份计算预算，同一路径出现不同身份时失败关闭。"""

    identities: dict[str, tuple[int, str]] = {}
    evidence_paths: set[str] = set()
    fact_paths: set[str] = set()

    def register(raw: Any, *, category: str) -> None:
        value: Mapping[str, Any]
        if isinstance(raw, FileIdentity):
            value = raw.model_dump(mode="python", by_alias=True)
        elif isinstance(raw, Mapping):
            value = raw
        else:
            raise ReportingError(
                "report_visualization_evidence_identity_invalid",
                "visualization 文件身份缺失或无效。",
            )
        path = value.get("path")
        size = value.get("size")
        sha256 = value.get("sha256")
        if (
            not isinstance(path, str)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
        ):
            raise ReportingError(
                "report_visualization_evidence_identity_invalid",
                "visualization 文件身份缺失或无效。",
            )
        try:
            normalized = WorkspaceService.normalize_path(path, allow_root=False)[0]
        except Exception as error:
            raise ReportingError(
                "report_visualization_evidence_identity_invalid",
                "visualization 文件路径无效。",
            ) from error
        identity = (size, sha256)
        if normalized in identities and identities[normalized] != identity:
            raise ReportingError(
                "report_visualization_evidence_identity_conflict",
                "同一 visualization 文件路径绑定了不同身份。",
                details={"path": normalized},
            )
        identities[normalized] = identity
        (evidence_paths if category == "evidence" else fact_paths).add(normalized)

    if isinstance(analysis_items, Mapping):
        for item in analysis_items.values():
            evidence_files = item.get("evidenceFiles") if isinstance(item, Mapping) else None
            if isinstance(evidence_files, Sequence) and not isinstance(
                evidence_files, (str, bytes)
            ):
                for identity in evidence_files:
                    register(identity, category="evidence")
    for identity in fact_files.values():
        register(identity, category="fact")

    evidence_read_units = sum((identities[path][0] + 65535) // 65536 for path in evidence_paths)
    if evidence_read_units > 512:
        raise ReportingError(
            "report_visualization_evidence_budget_exceeded",
            "visualization 受信 evidence 超过读取预算上限。",
            details={"evidenceReadUnits": evidence_read_units, "limit": 512},
        )
    total_fact_bytes = sum(identities[path][0] for path in fact_paths)
    read_limit = 12
    fact_query_limit = min(max((total_fact_bytes + 16383) // 16384, 4), 16)
    attempt_limit = max(48, read_limit + fact_query_limit + 16)
    total_limit = max(64, attempt_limit + 16)
    return {
        "visualizationBudgetVersion": 1,
        "visualizationEvidenceReadUnits": evidence_read_units,
        "visualizationReadLimit": read_limit,
        "visualizationFactQueryLimit": fact_query_limit,
        "visualizationAttemptToolLimit": attempt_limit,
        "visualizationTotalToolLimit": total_limit,
    }
