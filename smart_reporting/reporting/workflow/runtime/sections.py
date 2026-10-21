# mypy: disable-error-code="attr-defined"
# 运行时由 facade 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from copy import copy

from agno.exceptions import ModelProviderError
from agno.models.message import Message
from agno.session.agent import AgentSession
from loguru import logger as loguru_logger

from ....context_management import TaskExecutionContextHardLimitError
from ....task_execution import (
    TASK_EXECUTION_CONTEXT_TOKEN_LIMIT,
    TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
)
from ...code_agent.failure_policy import fresh_attempt_futile
from ...contract import interactive_spec_path
from ...delivery.draft_v1 import (
    ReportDraftBlock,
    ReportServerTable,
    promote_orphan_h4_headings,
)
from ...delivery.report_runtime.markdown import normalize_number_notation
from ...hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
from ...hospital_operation.findings import FindingGraph
from ...hospital_operation.narrative_outline import NarrativeOutline, NarrativeSection
from ...hospital_operation.outline import ReportOutlineSection
from ...model_policy import (
    ThinkingFailureKind,
    ThinkingRequest,
    resolve_reporting_input_token_hard_cap,
)
from ...phase import reporting_model_route_from_run_context
from ...structured_output import ReportingStructuredOutputExecutor
from ...tools import build_reporting_tools
from ...trace.computation_service import detect_computation_cycles
from ...trace.content_review import (
    readability_warnings,
    repeated_sentence_warnings,
    review_content_result,
)
from ...trace.contracts_v1 import (
    ChartTraceV1,
    ComputationRecordV1,
    TableTraceV1,
    derive_resource_id,
)
from ...trace.fact_service import fact_display_unit, fact_display_value
from ...trace.index_builder import trace_index_path_for
from ...trace.number_selection import align_number_selections
from ...trace.numeric_text import (
    frozen_number_catalog,
    frozen_number_guide,
    prompt_number_catalog,
    render_frozen_numbers,
    replace_unregistered_numbers,
)
from ...trace.subject_builder import bind_local_claim_values, build_claim_subject_bindings
from ...trace.table_builder import build_analysis_tables
from ..checkpoint import (
    ChartVisualInspectionReceipt,
    CheckpointError,
    ProfileReadReceipt,
    SectionClaimSubmission,
)
from ..execution import ReportingTaskInvocation
from ..state import normalize_analysis_warnings
from .analysis import (
    _finalize_semantic_catalog,
    _reporting_detailed_analysis_plan,
)
from .base import (
    MAX_REPORT_ANALYSIS_REWORKS_PER_SECTION,
    MAX_REPORT_INSTRUCTION_BYTES,
    MAX_REPORT_SECTION_PHASE_ATTEMPTS,
    MAX_SECTION_WORK_ITEM_BYTES,
    AnalysisArtifact,
    AnalysisChart,
    AnalysisDatasetSemantics,
    AnalysisEvidence,
    AnalysisEvidenceManifest,
    AnalysisReworkRequest,
    Any,
    ArtifactFile,
    Citation,
    CompletedSection,
    ContextTrace,
    DatasetHandle,
    DatasetLineage,
    DetailedAnalysisPlan,
    FileIdentity,
    Mapping,
    MetricDefinition,
    ProfileCoverageManifest,
    PurePosixPath,
    ReportArtifactManifest,
    ReportBrief,
    ReportChartInput,
    ReportDraft,
    ReportDraftSection,
    ReportingCheckpoint,
    ReportingCommand,
    ReportingError,
    ReportSectionDefinition,
    RunContext,
    SectionArtifact,
    SectionCitation,
    SectionManagementQuestion,
    SectionWorkItem,
    Sequence,
    SourceWarning,
    TaskExecutionScope,
    TaskState,
    ValidationError,
    _frozen_outline,
    _planner_candidate,
    assemble_report_markdown,
    build_report_phase_acceptance_contract,
    cast,
    json,
    payload_sha256,
    reporting_phase_task_key,
    validate_report_draft_blocks,
)
from .finding_evidence import finding_evidence_view
from .phase_models import (
    AnalysisReworkDecision,
    RenderSectionDecision,
    RenderSectionPlan,
    SectionBlockContent,
    SectionContent,
    SectionDecision,
    SectionEvidenceBundle,
    SectionEvidenceFile,
    SectionPlanOutput,
)
from .publication import _accepted_artifacts_match_manifest
from .section_workflow import SectionWorkflow


def _archived_interactive_path(image_path: str) -> str:
    return interactive_spec_path(image_path)


def _frozen_visual_receipt(
    receipt: Any, source_file: Mapping[str, Any]
) -> ChartVisualInspectionReceipt | None:
    """沿用可视化阶段针对同一文件身份签发的审查回执；不匹配或无效时返回 None。"""

    if not isinstance(receipt, Mapping):
        return None
    try:
        parsed = ChartVisualInspectionReceipt.model_validate(receipt)
    except ValidationError:
        return None
    if parsed.source_path != source_file.get("path") or parsed.sha256 != source_file.get("sha256"):
        return None
    return parsed


def _analysis_chart_from_registration(
    raw_chart: Mapping[str, Any],
    source_file: Mapping[str, Any],
    interactive_file: Mapping[str, Any] | None,
    visual_receipt: Mapping[str, Any] | None = None,
    plot_data: Mapping[str, Any] | None = None,
) -> AnalysisChart:
    interactive_path = raw_chart.get("interactivePath")
    if interactive_path is not None and (
        interactive_file is None or interactive_file.get("path") != interactive_path
    ):
        raise ReportingError("report_phase_artifact_changed", "Plotly 图表缺少匹配的交互文件身份。")
    payload = {
        key: value
        for key, value in raw_chart.items()
        if key not in {"sourcePath", "interactivePath"}
    }
    payload["sourceFile"] = dict(source_file)
    if interactive_file is not None:
        payload["interactiveFile"] = dict(interactive_file)
    # B3：服务端重验过的 chart-input 文件身份随图表冻结，形成图片↔作图
    # 数据证据链；缺失时保持旧形态（plotDataFiles 空 = 来源不足，读取层降级）。
    if isinstance(plot_data, Mapping) and plot_data.get("files"):
        payload["plotDataFiles"] = [
            dict(item) for item in plot_data["files"] if isinstance(item, Mapping)
        ]
        payload["plotDataKind"] = "chart_input"
    # 可视化阶段已为同一文件签发的真实审查回执必须随冻结图表保留；否则通过视觉
    # 审查的图表会在证据中被记录为“未运行审查”。没有匹配回执时才退回确定性检查。
    receipt = _frozen_visual_receipt(visual_receipt, source_file) or ChartVisualInspectionReceipt(
        sourcePath=str(source_file["path"]),
        sha256=str(source_file["sha256"]),
        inspectionMode="deterministic",
        visualReviewStatus="not_run",
        inspectorId="deterministic-raster-inspector-v1",
        reviewed=True,
        requiresRevision=False,
    )
    payload["visualInspectionReceipt"] = receipt.model_dump(mode="json", by_alias=True)
    return AnalysisChart.model_validate(payload)


# 写作模型只需图表的主题、口径与期间；视觉审查回执、文件身份等用于服务端门禁与溯源，
# 交给模型会被写进正文（“视觉回执提示纵轴比例失真”“柱形顶部被截断”）。
_WRITER_CHART_EXCLUDE = frozenset({
    "visual_inspection_receipt", "source_file", "interactive_file", "plot_data_files", "plot_data_kind", "renderer",
})


def _writer_chart(chart: AnalysisChart) -> dict[str, Any]:
    return chart.model_dump(mode="json", by_alias=True, exclude=set(_WRITER_CHART_EXCLUDE))


_SECTION_BLOCK_DEFAULT_INPUT_TOKEN_BUDGET = 64 * 1024
_SECTION_BLOCK_PAYLOAD_TOKEN_NUMERATOR = 3
_SECTION_BLOCK_PAYLOAD_TOKEN_DENOMINATOR = 4
_SECTION_BLOCK_EVIDENCE_TOKEN_DIVISOR = 2
_SECTION_BLOCK_TEXT_CONTEXT_LINES = 2
_SECTION_BLOCK_MAX_RELEVANCE_TERMS = 128
_SECTION_BLOCK_MIN_FILE_TOKENS = 128
_SECTION_BLOCK_MAX_PROJECTION_ATTEMPTS = 16
_SECTION_BLOCK_OMISSION_MARKER = "[...已省略与当前正文块无关的证据内容...]"
# 纠错指令中与复核告警一一对应的处理方式（同比/环比、月均与分组排名口径，图表编号，
# 小标题），两种生成路径共用。
_LATER_CORRECTION_ACTIONS = (
    "同比/环比、月均值与分组排名按登记结果改正；数值归属与点名的指标或科室不符时改用该对象的数值引用或改写主语；"
    "referenceIssues 列出当前引用的真实期间、范围和选择器，逐项核对当前分句；多月合计不能充当单月值，"
    "科室名称须与引用范围一致，找不到对应来源时保留待核实，不得删除告警文字来冒充已核实；"
    "历史新高、首次突破等表述改为与对比期的比较；图表编号改用图表标题主题词指代；"
    "小标题压缩为不超过 24 字的主题短语；过长段落按结论、证据、建议拆分；倍数改用已登记的变化率。"
)
_MAX_EXECUTIVE_SUMMARY_CHARS = 8_000
_EXECUTIVE_SUMMARY_SEPARATOR = "；"
_EXECUTIVE_SUMMARY_ELLIPSIS = "…"


_MAX_BLOCK_REVIEW_NOTICES = 20


def _block_review_notices(
    section_code: str, block_id: str, warnings: Sequence[str], generated: str, published: str,
    *, number_notices: Sequence[Any] | None = None,
) -> list[dict[str, Any]]:
    """纠错后仍残留的复核告警与“待核实”替换，作为不阻断发布的块级质量告警返回用户。"""

    details = {"sectionCode": section_code, "blockId": block_id}
    notices: list[dict[str, Any]] = [
        {"code": "report_section_block_content_review", "message": warning[:300], "details": details}
        for warning in list(dict.fromkeys(warnings))[:_MAX_BLOCK_REVIEW_NOTICES]
    ]
    # 新流程使用实际替换事件；旧章节保留文本差值兼容。
    replaced = (sum(item.kind == "numeric_unverified" for item in number_notices)
                if number_notices is not None else published.count("待核实") - generated.count("待核实"))
    if replaced > 0:
        notices.append({
            "code": "report_section_block_unverified_numbers",
            "message": f"{replaced} 处缺少登记依据的数值已替换为“待核实”。",
            "details": {**details, "count": replaced},
        })
    return notices


def _bounded_executive_summary(summaries: Sequence[str]) -> str:
    """在 ReportBrief 上限内公平保留每个分析项的管理摘要。"""

    values = [summary.strip() for summary in summaries if summary.strip()]
    if not values:
        return "已完成冻结分析。"
    joined = _EXECUTIVE_SUMMARY_SEPARATOR.join(values)
    if len(joined) <= _MAX_EXECUTIVE_SUMMARY_CHARS:
        return joined

    # evidenceManifest 仍保存完整 summary；这里只为派生的管理摘要分配字符预算。
    # 使用统一水位可避免前序长项独占空间，并让短项释放的额度自动让给其他项。
    content_budget = _MAX_EXECUTIVE_SUMMARY_CHARS - len(_EXECUTIVE_SUMMARY_SEPARATOR) * (
        len(values) - 1
    )
    low, high = 1, max(len(value) for value in values)
    while low < high:
        candidate = (low + high + 1) // 2
        if sum(min(len(value), candidate) for value in values) <= content_budget:
            low = candidate
        else:
            high = candidate - 1
    budgets = [min(len(value), low) for value in values]
    remaining = content_budget - sum(budgets)
    for index, value in enumerate(values):
        if remaining <= 0:
            break
        if budgets[index] < len(value):
            budgets[index] += 1
            remaining -= 1

    projected: list[str] = []
    for value, budget in zip(values, budgets, strict=True):
        if len(value) <= budget:
            projected.append(value)
            continue
        if budget <= len(_EXECUTIVE_SUMMARY_ELLIPSIS):
            projected.append(_EXECUTIVE_SUMMARY_ELLIPSIS[:budget])
            continue
        prefix = value[: budget - len(_EXECUTIVE_SUMMARY_ELLIPSIS)].rstrip()
        sentence_end = max(prefix.rfind(mark) for mark in "。！？")
        if sentence_end >= len(prefix) // 2:
            prefix = prefix[: sentence_end + 1]
        projected.append(prefix + _EXECUTIVE_SUMMARY_ELLIPSIS)
    return _EXECUTIVE_SUMMARY_SEPARATOR.join(projected)


def _estimated_section_tokens(value: str) -> int:
    """对中英文混合 JSON 做保守估算，避免切片本身依赖供应商 tokenizer。"""

    ascii_characters = sum(1 for character in value if ord(character) < 128)
    return (ascii_characters + 3) // 4 + len(value) - ascii_characters


def _section_block_input_token_budget(agent: Any, run_context: RunContext) -> int:
    configured_cap = _SECTION_BLOCK_DEFAULT_INPUT_TOKEN_BUDGET
    for owner in (getattr(agent, "model", None), agent):
        value = getattr(owner, "_task_execution_input_token_budget", None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            configured_cap = value
            break
    route = reporting_model_route_from_run_context(run_context)
    model_id = route[1] if route is not None else getattr(getattr(agent, "model", None), "id", None)
    output_reserve = getattr(getattr(agent, "model", None), "max_tokens", None)
    return resolve_reporting_input_token_hard_cap(
        configured_input_token_cap=configured_cap,
        model_id=model_id if isinstance(model_id, str) else None,
        output_token_reserve=max(
            TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
            output_reserve if isinstance(output_reserve, int) and not isinstance(output_reserve, bool) else 0,
        ),
        absolute_input_token_cap=(
            TASK_EXECUTION_CONTEXT_TOKEN_LIMIT - TASK_EXECUTION_OUTPUT_TOKEN_RESERVE
        ),
    )


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _section_request_tokens(agent: Any, payload: Mapping[str, Any], run_context: RunContext) -> int:
    """按最终路由计入系统约束和输出 schema；tokenizer 不可用时保守估算。"""

    stage_agent = _section_stage_agent(agent, SectionContent, "content") if callable(getattr(agent, "deep_copy", None)) else agent
    model = getattr(stage_agent, "model", None)
    counting_model = copy(model) if model is not None else None
    route = reporting_model_route_from_run_context(run_context)
    if counting_model is not None and route is not None:
        counting_model.id = route[1]
    serialized = _json_text(payload)
    messages = []
    get_system_message = getattr(stage_agent, "get_system_message", None)
    if callable(get_system_message):
        system_message = get_system_message(
            session=AgentSession(session_id="section-content-budget", agent_id=getattr(stage_agent, "id", None)),
            run_context=None, tools=[], add_session_state_to_context=False, input=serialized,
        )
        if system_message is not None:
            messages.append(system_message)
    messages.append(Message(role="user", content=serialized))
    try:
        count = counting_model.count_tokens(messages, output_schema=SectionContent)
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            return count
    except Exception:
        pass
    return sum(len(str(message.content).encode("utf-8")) for message in messages) + len(
        _json_text(SectionContent.model_json_schema()).encode("utf-8")
    )


def _section_number_context(
    contents: Sequence[str],
    field_definitions: dict[str, str],
    *,
    claims: Sequence[Any] | None = None,
    allowed_fact_ids: set[str] | None = None,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """模型只消费当前结论的数值视图，完整目录仍用于服务端校验。"""

    catalog = frozen_number_catalog(contents)
    guide = frozen_number_guide(contents, catalog, field_definitions=field_definitions)
    dependencies = {
        item["factId"]: {entry["budgetFactId"] for key in ("budgetComparisons", "projectRatios")
                         for entry in item.get(key, ())}
                       | {entry["totalFactId"] for entry in item.get("metricShares", ())}
        for item in guide
    }

    def with_dependencies(ids: set[str]) -> set[str]:
        return ids | {dependency for fact_id in ids for dependency in dependencies.get(fact_id, ())}

    if allowed_fact_ids is not None:
        allowed_fact_ids = with_dependencies(allowed_fact_ids)
        guide = [item for item in guide if item.get("factId") in allowed_fact_ids]
        catalog = {token: value for token, value in catalog.items()
                   if token.split(":", 2)[1] in allowed_fact_ids}
    if claims is None:
        # 规划不生成数值占位符；直接展示已格式化数值，避免每个期间/分组反复携带
        # 长引用。factId 仍保留，用于下一阶段绑定结论。
        planning_guide = []
        for item in guide:
            projected = {
                key: value for key, value in item.items()
                if key not in {"groups", "rowStatistics"}
            }
            if "monthlyStatistics" in projected:
                projected["monthlyStatistics"] = {
                    key: value for key, value in projected["monthlyStatistics"].items()
                    if key not in {"prefixTotals", "monthOverMonth"}
                }
            planning_guide.append(projected)
        return prompt_number_catalog(catalog), json.loads(render_frozen_numbers(_json_text(planning_guide), catalog))
    fact_ids = with_dependencies({fact_id for claim in claims for fact_id in claim.fact_ids})
    unbound_metrics = {claim.metric_code for claim in claims if not claim.fact_ids}
    selected_ids = with_dependencies(fact_ids | {
        item["factId"] for item in guide
        if item["factId"] in fact_ids
        or set(item.get("metricCodes", ())).intersection(unbound_metrics)
        or item.get("metric") in unbound_metrics
    })
    guide = [item for item in guide if item["factId"] in selected_ids]
    if not guide and not fact_ids:
        # 旧证据可能没有 factId/metricCodes，沿用完整目录，不能猜测绑定。
        return prompt_number_catalog(catalog), frozen_number_guide(contents, catalog, field_definitions=field_definitions)
    # 同比/对账事实也有数值目录，但不在 metric 的 numberGuide 中；显式绑定
    # 的 factId 必须仍保留，不能因此回退到整份无关目录。
    catalog = {
        token: value for token, value in prompt_number_catalog(catalog).items()
        if token.split(":", 2)[1] in selected_ids
    }
    return catalog, guide


def _controlled_assertions(contents: Sequence[str], payload: dict[str, Any], policy: Any) -> dict:
    """Only an explicitly enabled, run-pinned policy changes generation prompts."""
    if not isinstance(policy, Mapping) or policy.get("mode") != "enabled":
        return {}
    from ...trace.assertions import assertion_catalog

    if policy.get("version", "1") != "1" or policy.get("ruleVersion", "assertions/1") != "assertions/1":
        payload["assertionUnavailable"] = "historical_rule_unavailable"
        return {}

    trusted_hashes = policy.get("trustedFactSha256")
    if not isinstance(trusted_hashes, (list, tuple)) or not trusted_hashes:
        payload["assertionUnavailable"] = "trusted_facts_unavailable"
        return {}
    trusted_contents = tuple(content for content in contents
                             if hashlib.sha256(content.encode("utf-8")).hexdigest() in trusted_hashes)
    if not trusted_contents:
        payload["assertionUnavailable"] = "trusted_facts_unavailable"
        return {}
    from ...trace.top_sets import requested_top_set_limits

    selection_context = _json_text({key: payload.get(key) for key in (
        "reportGoal", "sectionGoal", "managementQuestions", "block", "claims", "sectionPlan",
    )})
    top_set_limits = requested_top_set_limits(selection_context)
    if not top_set_limits:
        payload["topSetUnavailable"] = "requested_cutoff_outside_supported_policy"
    records = assertion_catalog(
        trusted_contents, profile_hash=policy["profileHash"],
        authorization_scope_hash=policy["authorizationScopeHash"],
        allowed_tokens=tuple(payload.get("frozenNumbers", ())),
        include_month_changes=True, include_group_shares=True, include_month_trends=True, include_top_sets=True, include_group_contributions=True, include_registered_ratios=True, include_cumulative_changes=True,
        top_set_limits=top_set_limits,
    )
    payload["assertionCatalog"] = [
        {"id": item.assertion_id, "placeholder": "{{assert:" + item.assertion_id + "}}",
         "status": item.status, "operation": item.request.operation, "unit": item.unit,
         "comparison": item.request.comparison, "text": item.factual_fragment()}
        for item in records.values()
    ]
    payload["assertionWritingRules"] = (
        "单值、月均、已登记同比/环比、分组占比及分组排名优先使用受支持的 assertion placeholder，服务端会展开完整主体、期间、范围和值。"
        "不得改写其限定或扩大到全院/全年；占比分母沿用片段中的总体范围，不得更换总体或解释为因果贡献；证据不足的问题明确说明缺口。"
        "数字重算通过不证明经营因果，假设与建议必须明确标注。"
        "排名保留升降序及同值同名次的竞赛规则；Top-K 展示不证明唯一名次或全部分组均已列出。"
        "连续趋势使用服务端月度趋势断言，保留全部登记窗口；首尾增加不等于逐月增长，不由登记月值推断未来或因果。"
    )
    return records


def _section_block_evidence_token_budget(
    agent: Any,
    base_payload: Mapping[str, Any],
    *,
    file_count: int,
    run_context: RunContext,
) -> int:
    input_budget = _section_block_input_token_budget(agent, run_context)
    base_tokens = (
        _section_request_tokens(agent, base_payload, run_context)
        if base_payload.get("generationStage") == "content"
        else _estimated_section_tokens(_json_text(base_payload))
    )
    payload_budget = (
        input_budget
        * _SECTION_BLOCK_PAYLOAD_TOKEN_NUMERATOR
        // _SECTION_BLOCK_PAYLOAD_TOKEN_DENOMINATOR
    )
    evidence_budget = min(
        input_budget // _SECTION_BLOCK_EVIDENCE_TOKEN_DIVISOR,
        payload_budget - base_tokens,
    )
    minimum = max(1, file_count) * _SECTION_BLOCK_MIN_FILE_TOKENS
    if evidence_budget < minimum:
        raise ReportingError(
            "report_section_context_too_large",
            "章节固定上下文已占满当前模型输入预算，无法安全附加 block 证据视图。",
            details={
                "inputTokenBudget": input_budget,
                "baseEstimatedTokens": base_tokens,
                "requiredEvidenceTokens": minimum,
            },
        )
    return evidence_budget


def _iter_section_relevance_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, Mapping):
        for nested in value.values():
            values.extend(_iter_section_relevance_values(nested))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            values.extend(_iter_section_relevance_values(nested))
    elif value is not None and not isinstance(value, bool):
        values.append(str(value))
    return values


def _section_block_relevance_terms(*values: Any) -> tuple[str, ...]:
    terms: dict[str, None] = {}
    for raw in _iter_section_relevance_values(values):
        normalized = raw.strip().casefold()
        if not normalized:
            continue
        candidates = [normalized]
        candidates.extend(
            item for item in re.split(r"[^0-9a-zA-Z_.%+\-\u4e00-\u9fff]+", normalized) if item
        )
        for candidate in candidates:
            if len(candidate) > 128:
                continue
            if len(candidate) < 2 and not candidate.isdigit():
                continue
            terms.setdefault(candidate, None)
            if len(terms) >= _SECTION_BLOCK_MAX_RELEVANCE_TERMS:
                return tuple(terms)
    return tuple(terms)


def _compile_section_relevance_matcher(terms: Sequence[str]) -> re.Pattern[str]:
    patterns: list[str] = []
    for term in sorted(terms, key=lambda item: (-len(item), item)):
        escaped = re.escape(term)
        if re.fullmatch(r"[0-9a-zA-Z_.%+\-]+", term):
            patterns.append(rf"(?<![0-9a-zA-Z_.]){escaped}(?![0-9a-zA-Z_.])")
        else:
            patterns.append(escaped)
    if not patterns:
        return re.compile(r"(?!)")
    return re.compile("|".join(patterns), re.IGNORECASE)


def _section_relevance_score(matcher: re.Pattern[str], value: str) -> tuple[int, int]:
    total_length = 0
    count = 0
    for match in matcher.finditer(value.casefold()):
        total_length += len(match.group(0))
        count += 1
    return total_length, count


def _json_scalar(value: Any) -> bool:
    return not isinstance(value, Mapping | list | tuple)


def _json_path_child(path: str, key: Any) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    key_text = str(key)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_text):
        return f"{path}.{key_text}"
    return f"{path}[{_json_text(key_text)}]"


def _collect_json_evidence_candidates(
    value: Any,
    matcher: re.Pattern[str],
    *,
    path: str = "$",
    forced: bool = False,
    record: bool = False,
) -> tuple[bool, list[tuple[str, Any]]]:
    if isinstance(value, Mapping):
        if isinstance(value.get("columns"), list) and isinstance(value.get("rows"), list):
            # 文件已按章节分析绑定；业务表名不一定逐字出现在 claims 中。
            # 保留表候选，不能因关键词未命中就把已签发的数值整表丢弃。
            return True, [(path, value)]
        matched = forced
        direct_values: dict[str, Any] = {}
        nested_candidates: list[tuple[str, Any]] = []
        for key, nested_value in value.items():
            child_path = _json_path_child(path, key)
            key_matched = forced or matcher.search(str(key).casefold()) is not None
            if _json_scalar(nested_value):
                value_matched = matcher.search(str(nested_value).casefold()) is not None
                if key_matched or value_matched:
                    matched = True
                    direct_values[str(key)] = nested_value
                continue
            child_matched, child_candidates = _collect_json_evidence_candidates(
                nested_value,
                matcher,
                path=child_path,
                forced=key_matched,
            )
            matched = matched or child_matched
            nested_candidates.extend(child_candidates)
        if record and matched:
            return True, [(path, value)]
        mapping_candidates = ([(path, direct_values)] if direct_values else []) + nested_candidates
        return matched, mapping_candidates
    if isinstance(value, (list, tuple)):
        matched = forced
        sequence_candidates: list[tuple[str, Any]] = []
        for index, nested_value in enumerate(value):
            child_matched, child_candidates = _collect_json_evidence_candidates(
                nested_value,
                matcher,
                path=_json_path_child(path, index),
                forced=forced,
                record=isinstance(nested_value, Mapping),
            )
            matched = matched or child_matched
            sequence_candidates.extend(child_candidates)
        return matched, sequence_candidates
    scalar_matched = forced or matcher.search(str(value).casefold()) is not None
    return scalar_matched, [(path, value)] if scalar_matched else []


def _collect_matching_json_leaves(
    value: Any,
    matcher: re.Pattern[str],
    *,
    path: str,
) -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        leaves: list[tuple[str, Any]] = []
        columns, rows = value.get("columns"), value.get("rows")
        if isinstance(columns, list) and isinstance(rows, list):
            # 超限表按完整行摘录：标签、数值和本表单位必须一起送给模型，
            # 不能退化为无列名的单个匹配值，也不能把摘录当作完整构成。
            header = {key: value[key] for key in ("name", "columns", "columnMeta") if key in value}
            header_matched = matcher.search(_json_text(header).casefold()) is not None
            ordered_rows = sorted(
                ((index, row) for index, row in enumerate(rows)
                 if isinstance(row, list) and len(row) == len(columns)),
                key=lambda item: not (header_matched or matcher.search(_json_text(item[1]).casefold())),
            )
            for index, row in ordered_rows:
                leaves.append((f"{path}.rows[{index}]", {
                    **header, "rows": [row], "sourceRowIndex": index,
                    "sourceRowCount": len(rows),
                }))
        for key, nested_value in value.items():
            if isinstance(columns, list) and isinstance(rows, list) and key in {"columns", "rows", "columnMeta"}:
                continue
            child_path = _json_path_child(path, key)
            if _json_scalar(nested_value):
                if matcher.search(child_path.casefold()) or matcher.search(
                    str(nested_value).casefold()
                ):
                    leaves.append((child_path, nested_value))
            else:
                leaves.extend(
                    _collect_matching_json_leaves(
                        nested_value,
                        matcher,
                        path=child_path,
                    )
                )
        return leaves
    if isinstance(value, (list, tuple)):
        leaves = []
        for index, nested_value in enumerate(value):
            leaves.extend(
                _collect_matching_json_leaves(
                    nested_value,
                    matcher,
                    path=_json_path_child(path, index),
                )
            )
        return leaves
    return [(path, value)] if matcher.search(str(value).casefold()) else []


def _project_json_evidence(
    content: str,
    matcher: re.Pattern[str],
    *,
    token_budget: int,
) -> tuple[str, dict[str, Any]] | None:
    try:
        decoded = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return None
    _, candidates = _collect_json_evidence_candidates(decoded, matcher)
    selected: list[dict[str, Any]] = []
    selected_paths: set[str] = set()
    projected_chars = len('{"selected":[]}')
    projected_tokens = _estimated_section_tokens('{"selected":[]}')

    def append_candidate(path: str, value: Any) -> bool:
        nonlocal projected_chars, projected_tokens
        if path in selected_paths:
            return True
        candidate = {"path": path, "value": value}
        encoded_candidate = _json_text(candidate)
        # JSON 分隔符和 tokenizer 分组边界均按 1 token 计入，增量记账保持保守，
        # 避免为每个候选反复序列化整个 selected 列表造成 O(n²)。
        candidate_chars = len(encoded_candidate) + int(bool(selected))
        candidate_tokens = _estimated_section_tokens(encoded_candidate) + 1
        if projected_chars + candidate_chars > token_budget * 4:
            return False
        if projected_tokens + candidate_tokens > token_budget:
            return False
        selected.append(candidate)
        selected_paths.add(path)
        projected_chars += candidate_chars
        projected_tokens += candidate_tokens
        return True

    ranked_candidates = sorted(
        (
            (
                *_section_relevance_score(matcher, f"{path} {_json_text(value)}"),
                index,
                path,
                value,
            )
            for index, (path, value) in enumerate(candidates)
        ),
        key=lambda item: (-item[0], -item[1], item[2]),
    )
    omitted = False
    for _, _, _, path, value in ranked_candidates:
        if append_candidate(path, value):
            continue
        omitted = True
        for leaf_path, leaf_value in _collect_matching_json_leaves(
            value,
            matcher,
            path=path,
        ):
            if not append_candidate(leaf_path, leaf_value):
                omitted = True

    if len(selected) == 1 and selected[0]["path"] == "$" and selected[0]["value"] == decoded:
        projected_content = content
        format_name = "json_full"
    else:
        projected_content = _json_text({"selected": selected})
        format_name = "json_paths"
        omitted = omitted or selected != [{"path": "$", "value": decoded}]
    return projected_content, {
        "format": format_name,
        "truncated": omitted,
    }


def _project_text_evidence(
    content: str,
    matcher: re.Pattern[str],
    *,
    token_budget: int,
) -> tuple[str, dict[str, Any]]:
    lines = content.splitlines()
    matching = [
        index for index, line in enumerate(lines) if matcher.search(line.casefold()) is not None
    ]
    ranked_matching = sorted(
        matching,
        key=lambda index: (
            -_section_relevance_score(matcher, lines[index])[0],
            -_section_relevance_score(matcher, lines[index])[1],
            index,
        ),
    )
    selected_indices: set[int] = set()
    remaining_chars = token_budget * 4
    remaining_tokens = token_budget

    def render(indices: set[int]) -> str:
        rendered: list[str] = []
        previous: int | None = None
        for selected_index in sorted(indices):
            if previous is not None and selected_index > previous + 1:
                rendered.append(_SECTION_BLOCK_OMISSION_MARKER)
            rendered.append(lines[selected_index])
            previous = selected_index
        return "\n".join(rendered)

    for index in ranked_matching:
        start = max(0, index - _SECTION_BLOCK_TEXT_CONTEXT_LINES)
        stop = min(len(lines), index + _SECTION_BLOCK_TEXT_CONTEXT_LINES + 1)
        additions = [
            line_index for line_index in range(start, stop) if line_index not in selected_indices
        ]
        if not additions:
            continue
        added_text = "\n".join(lines[line_index] for line_index in additions)
        added_chars = len(added_text) + len(_SECTION_BLOCK_OMISSION_MARKER) + 2
        added_tokens = (
            _estimated_section_tokens(added_text)
            + _estimated_section_tokens(_SECTION_BLOCK_OMISSION_MARKER)
            + 2
        )
        if added_chars > remaining_chars or added_tokens > remaining_tokens:
            continue
        selected_indices.update(additions)
        remaining_chars -= added_chars
        remaining_tokens -= added_tokens

    projected = render(selected_indices)
    if not projected:
        projected = "[当前正文块在该文件中无直接关键词命中；仅使用冻结 claims 与事实摘要。]"
    return projected, {
        "format": "text_neighborhoods",
        "truncated": len(selected_indices) < len(lines),
        "matchedLineCount": len(matching),
    }


def _verified_caption(text: str, number_contents: tuple[str, ...]) -> str:
    """图注标题/替代文字与正文同规则核对数值；没有核对依据时原样返回。"""

    if not number_contents:
        return text
    checked = replace_unregistered_numbers(normalize_number_notation(text), number_contents)
    # “待核实”比被替换的数字长，超出图注 200 字上限时截断而不是让装配失败。
    return checked if len(checked) <= 200 else f"{checked[:199]}…"


def _project_section_evidence_files(
    agent: Any,
    files: Sequence[Any],
    *,
    fact_summaries: Sequence[str],
    relevance_values: Sequence[Any],
    base_payload: Mapping[str, Any],
    run_context: RunContext,
) -> dict[str, Any]:
    if not files:
        return {"files": [], "factSummaries": list(fact_summaries)}
    terms = _section_block_relevance_terms(*relevance_values)
    matcher = _compile_section_relevance_matcher(terms)
    budget_payload = {
        **base_payload,
        "evidence": {"files": [], "factSummaries": list(fact_summaries)},
    }
    remaining_budget = _section_block_evidence_token_budget(
        agent,
        budget_payload,
        file_count=len(files),
        run_context=run_context,
    )
    minimum_file_budgets = [
        _estimated_section_tokens(_json_text(item.identity.model_dump(mode="json", by_alias=True)))
        + _SECTION_BLOCK_MIN_FILE_TOKENS
        for item in files
    ]
    if sum(minimum_file_budgets) > remaining_budget:
        raise ReportingError(
            "report_section_context_too_large",
            "章节证据文件身份超过当前 block 的可用输入预算。",
            details={
                "availableEvidenceTokens": remaining_budget,
                "requiredIdentityTokens": sum(minimum_file_budgets),
                "evidenceFileCount": len(files),
            },
        )
    projected_files: list[dict[str, Any]] = []
    for index, item in enumerate(files):
        remaining_files = len(files) - index
        minimum_for_rest = sum(minimum_file_budgets[index + 1 :])
        file_budget = min(
            remaining_budget - minimum_for_rest,
            max(minimum_file_budgets[index], remaining_budget // remaining_files),
        )
        identity = item.identity.model_dump(mode="json", by_alias=True)
        identity_tokens = _estimated_section_tokens(_json_text(identity))
        content_budget = max(1, file_budget - identity_tokens)
        max_projected_tokens = remaining_budget - minimum_for_rest
        for projection_attempt in range(_SECTION_BLOCK_MAX_PROJECTION_ATTEMPTS):
            projected_json = _project_json_evidence(
                item.content,
                matcher,
                token_budget=content_budget,
            )
            if projected_json is None:
                content, view = _project_text_evidence(
                    item.content,
                    matcher,
                    token_budget=content_budget,
                )
            else:
                content, view = projected_json
            projected_file = {"identity": identity, "content": content, "view": view}
            projected_tokens = _estimated_section_tokens(_json_text(projected_file))
            if projected_tokens <= max_projected_tokens:
                break
            # content 会作为字符串再次编码进外层 JSON；引号、反斜杠等转义会使最终
            # payload 大于内层投影预算。按实际超额量收紧正文后重新投影，冻结身份、
            # view 元数据和事实摘要始终保留，且最终仍由同一个硬预算门禁验收。
            overflow = projected_tokens - max_projected_tokens
            if (
                content_budget <= 1
                or projection_attempt == _SECTION_BLOCK_MAX_PROJECTION_ATTEMPTS - 1
            ):
                raise ReportingError(
                    "report_section_context_too_large",
                    "章节证据视图无法在保留冻结文件身份后满足当前输入预算。",
                    details={
                        "availableEvidenceTokens": max_projected_tokens,
                        "projectedEvidenceTokens": projected_tokens,
                    },
                )
            # 比例收缩通常一次即可吸收 JSON 转义开销；最后一次固定尝试最小正文，
            # 避免投影结果在相邻预算上不变时对大文件逐 token 重算。
            proportional_budget = content_budget * max_projected_tokens // projected_tokens
            next_content_budget = min(
                content_budget - max(1, overflow),
                max(1, proportional_budget),
            )
            if projection_attempt == _SECTION_BLOCK_MAX_PROJECTION_ATTEMPTS - 2:
                next_content_budget = 1
            content_budget = next_content_budget
        projected_files.append(projected_file)
        remaining_budget -= projected_tokens
    return {"files": projected_files, "factSummaries": list(fact_summaries)}


def _section_retry_context(error: Exception | CheckpointError | None) -> dict[str, Any] | None:
    """把章节上轮失败的稳定字段带入 fresh retry，避免模型重新猜测冲突原因。"""

    if error is None:
        return None
    if isinstance(error, CheckpointError):
        return {
            "code": error.code,
            "message": error.message,
            "details": dict(error.details) if isinstance(error.details, Mapping) else {},
        }
    if isinstance(error, ReportingError):
        details = dict(error.details) if isinstance(error.details, Mapping) else {}
        return {"code": error.code, "message": error.message, "details": details}
    return {"code": "report_section_phase_failed", "message": str(error), "details": {}}


def _section_stage_agent(
    agent: Any,
    output_schema: type[Any],
    stage: str,
    response_validator: Callable[[Any], Any] | None = None,
) -> Any:
    """从现有 Reporting 生成器派生无工具、无历史的短输出阶段 Agent。"""

    if stage == "plan":
        instructions = [
            "只返回满足 output_schema 的 JSON 对象，不得返回解释、Markdown 或代码围栏。"
        ]
        if output_schema is RenderSectionPlan:
            instructions.append(
                "补证次数已达到上限，不得再请求补证；仅使用现有冻结证据规划 render，"
                "省略没有证据支持的结论。"
            )
        else:
            instructions.append(
                "先判断证据是否足够；足够时返回 render 规划，缺少必要数据或计算结果时才返回 rework。"
                "单位待确认、业务名称或可比性争议、对账告警及图表口径/视觉回执冲突均为软告警，"
                "不能单独成为 rework 理由，也不得要求补证脚本确认源数据未提供的单位或业务定义。"
                "这些情形返回 render：金额沿用冻结单位，默认人民币元已由服务端登记，名称沿用源字段说明，"
                "省略存在冲突的图表及无证据结论，在正文披露限制；不得标记验收通过。"
            )
        instructions.extend(
            [
                "render 只规划必要的正文 block 和结构化 claims，不在 objective 中撰写正文。",
                "numberGuide 给出服务端确认的数值期间与粒度。按它选择结论，原始行统计不能规划成月度统计，完整分组组合不能规划成单一科室累计。",
                "claims.value中的数字只取规划输入内可直接核对的登记数值，不把分析摘要或图表标题"
                "里的合并占比当作已登记比例；没有可核对的补证百分数时，规划描述各类别构成，"
                "让正文从本表columnMeta.isPercent=true的对应行取值，不要求模型自行累加比例。",
                "每个 claim 必须由至少一个 block 引用；只使用输入中的 metric、管理问题、citation 和 chart ID。",
                "逐张核对 charts 的 title、altText、metricCodes 与 visualInspectionReceipt.summary；"
                "视觉passed只表示呈现可读，不证明指标正确。回执描述收入金额而图表声明工作量人次等"
                "明显冲突时，不得在任何claim中引用该chartId；正文只用冻结事实陈述，block objective "
                "不得要求说明图表单位、标注、标题或是否采用某图。",
                (
                    "每张图表只绑定到最直接阐述它的那个 block 的 claim；多张图表应分散到各自"
                    "对应的 block，不要集中绑定到总览或总结 block，避免图表堆叠渲染。"
                ),
                "存在 correction 时逐项修正 issues，只能使用 allowedValues，并返回完整规划。",
            ]
        )
    else:
        instructions = [
            "只返回满足 output_schema 的 JSON 对象，不得把整个响应写成 Markdown 或代码围栏。",
            (
                "一次生成 sectionPlan 中全部 block 的完整简体中文 Markdown 正文，"
                "返回 blocks 数组，每项仅含 blockId 和 markdown。blockId 必须与规划一一对应，"
                "不得遗漏、重复或新增；按规划顺序组织全文，统筹标题层级，避免重复。"
                if stage == "content"
                else "只在 JSON 的 markdown 字段中撰写当前 block 的完整简体中文 Markdown 正文，不得生成其他 block。"
            ),
            "每个 block 必须完成 objective 对应的事实陈述，不得以‘整体呈’‘分别为’等半句结尾；没有证据的结论直接删去，不逐句写待核实。",
            "不得输出 H1/H2、图片语法、协议标记或无证据数字；内部 ID 仅可用于 frozenNumbers 提供的数值占位符。",
            "管理层正文禁止出现 block、Markdown、CSV、SQL、ACF/PACF、服务端、数据集、字段、x轴/y轴 等实现或验收术语；改写为段落、正文、明细数据、统计相关性、指标、横轴/纵轴。不要解释 harness、生成流程、文件格式或验收过程。",
            "读者是医院领导或财务、业务人员，不是数据技术人员：每段首句先写结论与管理含义，再给关键数字；每章第一个正文段的首句会摘入报告开头的“核心结论”，须是可单独阅读、含关键数字的结论句；财务口径（收入、成本、预算执行、差额、完成率）按财务习惯表述并写清期间与单位；用“1—11月”“11月”等日常说法，不写“月度桶”“登记值”“登记结果”“冻结”“补证”“净额口径”“数值引用”等技术用语；同一口径说明全章只写一次，不复述图表画法、标注位置或图表质量。",
            "月度日期（如2025-11-01）只表示所属月份，不是数据截止时点；其他模型摘要或图表标题中的推测不构成直接证据。不得补写目录中不存在的月均值或派生金额。",
            "月均值必须与正文月份范围一致；完整12个月的均值不得用于1—10月；期末有连续零值月份时优先用 monthlyStatistics.averageBeforeTrailingZeros 并写明月份范围。多个指标各取前N名后并集展示时，分类数量可以超过N，不能据此认定图表超范围。声称各月方向一致前须逐月核对；存在反向月份时明确例外，不写全部一致。",
            "异常或偏低只描述事实；没有入账状态、数据截断等证据时，不推测其原因，也不得断言月份数据不完整。",
            "frozenNumbers 中的数值必须使用对应 {{value:...}} 占位符，不得手抄或换算；服务端在正文落盘前替换为带单位的显示值。需要元值和亿元同时展示时分别选择两个占位符；大额人次可选择万人次占位。",
            "占位符渲染后已带单位，其后不得再写单位（不写“{{value:…:亿元}}亿元”）；每个数值写在其所属指标、科室或期间的名下，不得把一个科室或指标的引用写到另一个名下。数字与百分号用半角，百分点写“个百分点”，不写 pp、pct。",
            "reportGoal要求精确原始元值时，已登记元单位的关键金额必须选择元值占位符展示；"
            "可另附亿元或万元显示，但不得只写舍入后的大单位金额。",
            "金额默认币种为 CNY（人民币），单位在事实冻结时确定；正文优先选择 frozenNumbers 已登记的元、万元、亿元引用，未提供对应引用的补证表值按下一条规则处理。明确的其他币种或展示单位优先保留；非金额字段或旧事实 unit 为空时，不自行补单位或换算。",
            "已签发补证表列元数据明确单位且 frozenNumbers 未提供对应占位符时，可直接引用对应行列的数值，并按列单位规范换算；必须同时核对分组维度、指标和期间，不得用 topGroups 多维明细替代院区或科室汇总。缺少占位符不代表缺少证据，不得拿相近值替代。已签发补证表同一列的 columnMeta.isPercent=true 时，该列是已计算的百分数，可按对应行直接引用并四舍五入；不得因 frozenNumbers 缺少补证占位符就称其未登记或待核实，不得重新计算或累加出新比例。",
            "先按 numberGuide 确认指标、期间、粒度和完整分组再选数值引用。rowStatistics 是原始行统计；monthlyStatistics 才是月度统计。已登记零值月份保留；局部最高/最低必须明确子期间。目录未提供的比率不能根据图注或模型摘要推算；只写已登记分子分母，或说明该比率待核实。",
            "budgetComparisons 是服务端按同口径事实计算的差额与百分数。表格有对应引用时必须填写，包括零分子的0%；只有百分数引用为空时才写不可计算。负差额写‘差额为负’或‘实际减预算为……’，不得写‘少-……’；零值月份仅称‘记录为零’，不称‘尚无数据’或‘未执行月份’。",
            "正文中的完成率、同比增速、构成占比与差额一律优先使用 numberGuide 提供的 budgetComparisons、comparisons、metricShares 引用占位符，不得用两个登记数值现场相除或相减得出新数值。metricShares 是该指标占同口径合计的百分比，写“某项占……的X%”时必须使用它；目录没有对应派生引用时，只分别写出分子与分母（或本期与基期）的登记数值，或说明该比率待核实。",
            "total 是该事实完整期间的总额；正文写1—10月时必须使用相应 periodTotals 累计引用，不能套用12个月 total。零分子且分母非零时完成率为0%，只有分母为零或缺失时才不能计算。",
            (
                "可使用 H3/H4、段落、列表和有报告意义的 Markdown 管道表；"
                "H3/H4 必须是不超过 40 个中文字符的短标题，并独占一个物理行。"
                "标题行后必须立即换行；有正文时，使用『### 收入分析\n\n本季度收入……』格式。"
                "禁止『### 收入分析：本季度收入……』同一行混写。"
                "小标题是不超过 24 字的主题短语，结论和数值写进正文。"
            ),
            (
                "Markdown 的标题和正文都不得出现 citationIds、chartIds、图表文件名、"
                "HTML 标签或 <sup> 脚注；这些引用只能通过输入中的结构化字段绑定。"
            ),
            (
                "输入 charts 非空时，按 charts 顺序为每张图表各写一个独立段落解读，段落中写出"
                "图表标题的主题词；图表会插在最匹配的段落之后，不要把多张图表合并到一段描述。"
                "成品图表与表格不编号，不要写“如图1所示”“见表2”，用标题主题词指代。"
            ),
            (
                "口径纪律：每个结论必须沿用当前 block facts 的同一数据集、期间、单位和分子分母；"
                "若输入同时存在台账、汇总、预算或不同期间口径，先在正文说明差异，再分别表述，"
                "禁止无标记切换口径或把不同口径的数值直接相加比较。"
            ),
            (
                "数据质量优先：facts 或 warnings 出现字段为零、预算为零、期间不一致或不可比声明时，"
                "只能将其作为软告警写明影响；其他模型写的未入账或数据不完整不能证明数据状态。不得把缺失或不可比数据"
                "写成确定的经营归因。证据不足时不写原因，也不得自行添加可能原因；需要补核的对象与口径限制在本章末合并为一段说明，不单设‘待核实事项’小节，同一限制只写一次，其他段落不重复‘待核实’‘口径不可混用’等提示。"
            ),
            (
                "相关性高不证明两套口径等价或可互换；预算为零须逐项核对预算列；超支与差额贡献使用差额列，不能使用实际金额列。结构化绑定的图表会展示，正文不得声称它未引用或已剔除。强结论门槛：‘全院性’‘主要原因’‘核心驱动’等判断必须同时给出覆盖范围、贡献额、"
                "排名或可复核的对比证据；没有这些证据时降级为观察性描述。每个主题按‘发现—证据—"
                "管理动作’组织，管理动作写在该主题末段，不单设同名小标题；避免重复复述图表和管理结论。"
            ),
            (
                "提交前逐行检查所有 ###/#### 标题。存在 correction 时只修正 issues 指向的内容，保留本次规划的全部 block；"
                "对 report_draft_heading_title_too_long，必须把该行重写为不超过 40 个字符的短标题，"
                "并将原标题行中的全部正文移到空行后的段落，最后返回完整 JSON 对象。"
            ),
        ]
    identifier = str(getattr(agent, "id", None) or "reporting-section-generator")
    update: dict[str, Any] = {
        "id": f"{identifier}-{stage}",
        "name": f"{identifier}-{stage}",
        "role": f"Reporting 章节{stage}阶段结构化生成器。",
        "output_schema": output_schema,
        "instructions": instructions,
        "tools": [],
        "tool_choice": None,
        "add_history_to_context": False,
        "enable_session_summaries": False,
        "retries": 0,
        "exponential_backoff": False,
    }
    if response_validator is not None and getattr(agent, "model", None) is not None:
        stage_model = copy(agent.model)
        setattr(stage_model, "_report_response_validator", response_validator)
        update["model"] = stage_model
    return agent.deep_copy(update=update)


async def _run_section_stage(
    agent: Any,
    output_schema: type[Any],
    stage: str,
    payload: Mapping[str, Any],
    *,
    scope: TaskExecutionScope,
    run_context: RunContext,
    thinking_request: ThinkingRequest,
    section_code: str,
    response_validator: Callable[[Any], Any] | None = None,
    attempt_key: str = "1",
) -> Any:
    loguru_logger.info(
        "report_section_generation_started section_code={} stage={} attempt={} failure_kind={}",
        section_code,
        stage,
        thinking_request.attempt,
        thinking_request.failure_kind or "-",
    )
    stage_agent = _section_stage_agent(agent, output_schema, stage, response_validator)
    try:
        result = await ReportingStructuredOutputExecutor(stage_agent).execute(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            routing_context=run_context,
            agent_run_context=run_context,
            # 章节阶段代理明确关闭 history；每次尝试使用独立 session，避免失败响应
            # 在同一 session 中累积并把后续请求推过 provider hard cap。
            session_id=(
                f"task-execution:{scope.external_run_id}:{section_code}:"
                f"{stage}:attempt-{thinking_request.attempt}-{attempt_key}"
            ),
            user_id=scope.owner_user_id,
            thinking_request=thinking_request,
        )
    except ModelProviderError as error:
        from ...models import reporting_failure

        failure = reporting_failure(error)
        raise ReportingError(
            "report_model_provider_unavailable",
            f"模型请求失败（HTTP {error.status_code}）：{failure['message']}",
            details={**failure, "retryable": False, "stage": stage},
        ) from error
    return result.content


def _section_stage_thinking_request(
    request: ThinkingRequest, stage: str, *, block_count: int = 1
) -> ThinkingRequest:
    """规划独立推理；正文只在自己的结构纠错中升级。"""

    is_plan = stage == "plan"
    return ThinkingRequest(
        operation="section_planning" if is_plan else "section_generation",
        complexity=request.complexity,
        attempt=request.attempt if is_plan else 0,
        failure_kind=request.failure_kind if is_plan else None,
        configured_budget_cap=request.configured_budget_cap,
        # 正文不继承规划阶段的显式 effort；默认请求仍可使用基础预算，
        # 规划失败恢复时则关闭正文思考，避免在同一失败上下文重复消耗调用。
        thinking_enabled=(
            request.thinking_enabled
            if is_plan
            else request.thinking_enabled and request.reasoning_effort is None and request.failure_kind is None
        ),
        reasoning_effort=request.reasoning_effort if is_plan else None,
        section_block_count=block_count if stage == "content" else 1,
    )


def _section_recovery_failure_kind(
    diagnostic: Mapping[str, Any],
) -> ThinkingFailureKind | None:
    """仅把结构化输出耗尽归类为 schema failure。"""

    return "schema_failure" if diagnostic.get("code") == "report_phase_output_invalid" else None


def _fit_section_plan_budget(plan: RenderSectionPlan, work_item: SectionWorkItem) -> RenderSectionPlan:
    """按冻结预算合并正文规划块，保留全部结论引用；结构容量不足时留给软告警。"""
    limit = work_item.max_blocks
    if limit is None or len(plan.blocks) <= limit:
        return plan
    tail = plan.blocks[limit - 1:]
    claim_ids = tuple(dict.fromkeys(item for block in tail for item in block.claim_ids))
    if len(claim_ids) > 100:
        return plan
    objective = "；".join(block.objective for block in tail)
    if len(objective) > 2000:
        objective = tail[0].objective[:1900] + "；同时解释其余已绑定结论"
    merged = tail[0].model_copy(update={"objective": objective, "claim_ids": claim_ids})
    return plan.model_copy(update={"blocks": (*plan.blocks[:limit - 1], merged)})


def _section_plan_reference_issues(
    decision: RenderSectionPlan,
    work_item: SectionWorkItem,
) -> list[dict[str, Any]]:
    """返回模型可直接修正的动态引用问题，不把业务 ID 写入日志。"""

    known_metrics = {item.code for item in work_item.metric_definitions}
    known_questions = {item.ref for item in work_item.management_question_catalog}
    known_citations = {item.citation_id for item in work_item.citations}
    known_charts = {item.chart_id for item in work_item.charts}
    issues: list[dict[str, Any]] = []
    for index, claim in enumerate(decision.claims):
        if set(claim.finding_ids) - set(work_item.finding_ids):
            issues.append({
                "path": f"$.claims[{index}].findingIds",
                "type": "unknown_finding_id",
                "message": "findingIds 只能引用当前章节分配的管理发现。",
                "allowedValues": list(work_item.finding_ids),
            })
        elif work_item.finding_ids and not claim.finding_ids:
            issues.append({
                "path": f"$.claims[{index}].findingIds",
                "type": "missing_finding_id",
                "message": "动态章节结论必须绑定所解释的已分配管理发现。",
                "allowedValues": list(work_item.finding_ids),
            })
        if claim.metric_code not in known_metrics:
            issues.append(
                {
                    "path": f"$.claims[{index}].metricCode",
                    "type": "unknown_metric_code",
                    "message": "metricCode 必须来自当前 SectionWorkItem。",
                    "allowedValues": sorted(known_metrics),
                }
            )
        if claim.management_question_ref not in known_questions:
            issues.append(
                {
                    "path": f"$.claims[{index}].managementQuestionRef",
                    "type": "unknown_management_question_ref",
                    "message": "managementQuestionRef 必须来自当前 SectionWorkItem。",
                    "allowedValues": sorted(known_questions),
                }
            )
        if set(claim.citation_ids) - known_citations:
            issues.append(
                {
                    "path": f"$.claims[{index}].citationIds",
                    "type": "unknown_citation_id",
                    "message": "citationIds 只能引用当前 SectionWorkItem。",
                    "allowedValues": sorted(known_citations),
                }
            )
        if set(claim.chart_ids) - known_charts:
            issues.append(
                {
                    "path": f"$.claims[{index}].chartIds",
                    "type": "unknown_chart_id",
                    "message": "chartIds 只能引用当前 SectionWorkItem。",
                    "allowedValues": sorted(known_charts),
                }
            )
    return issues


# 服务端先确定性修复可唯一推断的引用，模型只负责剩余歧义；两轮后仍未解决的引用
# 交给渲染工具软告警处理，避免单条结论拖垮整章（原先 5 轮纠错后整章失败并从头重试）。
_MAX_PLAN_REFERENCE_CORRECTIONS = 2


def _section_plan_response_validator(
    work_item: SectionWorkItem,
    output_schema: type[SectionPlanOutput] | type[RenderSectionPlan] = SectionPlanOutput,
    previous_output: Mapping[str, Any] | None = None,
) -> Callable[[Any], SectionPlanOutput | RenderSectionPlan]:
    """规划响应先合并修正补丁、做无歧义 claim 引用回填，再进入领域校验。"""

    def validate_response(content: Any) -> SectionPlanOutput | RenderSectionPlan:
        candidate = _planner_candidate(content)
        if previous_output is not None:
            candidate = _merge_claim_patch(candidate, previous_output, work_item)
        if (
            output_schema is RenderSectionPlan
            and isinstance(candidate, Mapping)
            and len(candidate) == 1
            and isinstance(candidate.get("render"), Mapping)
        ):
            candidate = {**candidate["render"], "kind": "render"}
        candidate = _backfill_claim_management_question_refs(candidate, work_item)
        try:
            return output_schema.model_validate(candidate)
        except ValidationError as error:
            # 与 planner 校验器同契约：候选回灌纠错，不进日志或公开错误。
            error._report_candidate = candidate  # type: ignore[attr-defined]
            raise

    return validate_response


def _merge_claim_patch(
    candidate: Any, previous_output: Mapping[str, Any], work_item: SectionWorkItem
) -> Any:
    """引用纠错轮中模型只回传被修正的 claim 时，按 claimId 合并回上一版完整规划。

    弱模型在 correction 中高频只返回单个 claim、claim 数组或 {"claims": [...]}，
    缺少 sectionCode/blocks 必然结构失败；结构纠错又把这个补丁当 previousOutput
    回灌，模型继续输出补丁，章节阶段被整轮重试放大。上一版规划已通过结构校验，
    claimId 全部命中时替换是确定性合并；任一 claimId 未知则保持原样由严格校验失败关闭。
    """

    patches: list[Any] | None = None
    if isinstance(candidate, Mapping):
        if "blocks" in candidate or "sectionCode" in candidate or "section_code" in candidate:
            return candidate
        if "claimId" in candidate and "claims" not in candidate:
            patches = [candidate]
        elif set(candidate) <= {"claims", "kind"} and isinstance(candidate.get("claims"), list):
            patches = list(candidate["claims"])
    elif isinstance(candidate, list):
        patches = list(candidate)
    previous_claims = previous_output.get("claims")
    if not patches or not isinstance(previous_claims, list):
        return candidate
    index = {
        claim.get("claimId"): position
        for position, claim in enumerate(previous_claims)
        if isinstance(claim, Mapping)
    }
    if any(
        not isinstance(patch, Mapping)
        or not isinstance(patch.get("claimId"), str)
        or patch["claimId"] not in index
        for patch in patches
    ):
        return candidate
    merged = list(previous_claims)
    for patch in patches:
        merged[index[patch["claimId"]]] = dict(patch)
    loguru_logger.bind(
        section_code=work_item.section_code,
        patched_claim_count=len(patches),
    ).warning("report_section_plan_claim_patch_merged")
    return {**previous_output, "claims": merged}


def _management_question_ref_index(
    work_item: SectionWorkItem,
) -> tuple[str | None, dict[str, str]]:
    """返回唯一管理问题引用，以及 metricCode 唯一归属 analysis 的确定性映射。"""

    catalog = work_item.management_question_catalog
    single_ref = catalog[0].ref if len(catalog) == 1 else None
    metric_refs: dict[str, set[str]] = {}
    for evidence_item in work_item.evidence:
        for metric in evidence_item.metrics:
            metric_refs.setdefault(metric, set()).add(evidence_item.analysis_id)
    unique_metric_refs = {
        metric: next(iter(refs)) for metric, refs in metric_refs.items() if len(refs) == 1
    }
    return single_ref, unique_metric_refs


def _repair_section_plan_references(
    decision: RenderSectionPlan, work_item: SectionWorkItem
) -> RenderSectionPlan:
    """确定性修复可唯一推断的规划引用错误，剩余问题才回灌模型纠错。

    只做无歧义修复并软告警：metricCode 写成指标名称或大小写不同的代码；
    managementQuestionRef 不在目录内但目录唯一或 metricCode 唯一归属；
    citationIds/chartIds 混入当前 WorkItem 外的 ID 时剔除，citation 剔空后优先使用
    已绑定冻结图表的 citation，否则仅在所属 analysis 恰有一个 citation 时回填。单个 claim 修复后不满足提交契约时
    保持原样，交给纠错循环。
    """

    known_metrics = {item.code for item in work_item.metric_definitions}
    metric_aliases: dict[str, set[str]] = {}
    for item in work_item.metric_definitions:
        for alias in (item.code, item.name):
            metric_aliases.setdefault(alias.strip().casefold(), set()).add(item.code)
    known_questions = {item.ref for item in work_item.management_question_catalog}
    known_citations = {item.citation_id for item in work_item.citations}
    known_charts = {item.chart_id for item in work_item.charts}
    chart_citations = {item.chart_id: item.citation_ids for item in work_item.charts}
    analysis_citations = {
        item.analysis_id: tuple(
            dict.fromkeys(cid for cid in item.citation_ids if cid in known_citations)
        )
        for item in work_item.evidence
    }
    single_ref, unique_metric_refs = _management_question_ref_index(work_item)
    repaired_claims: list[SectionClaimSubmission] = []
    repair_types: set[str] = set()
    for claim in decision.claims:
        payload = claim.model_dump(mode="json", by_alias=True)
        claim_repairs: set[str] = set()
        if claim.metric_code not in known_metrics:
            aliases = metric_aliases.get(claim.metric_code.strip().casefold(), set())
            if len(aliases) == 1:
                payload["metricCode"] = next(iter(aliases))
                claim_repairs.add("metric_code")
        if claim.management_question_ref not in known_questions:
            replacement = single_ref or unique_metric_refs.get(payload["metricCode"])
            if replacement in known_questions:
                payload["managementQuestionRef"] = replacement
                claim_repairs.add("management_question_ref")
        chart_ids = [item for item in claim.chart_ids if item in known_charts]
        if len(chart_ids) != len(claim.chart_ids):
            payload["chartIds"] = chart_ids
            claim_repairs.add("chart_ids")
        citation_ids = [item for item in claim.citation_ids if item in known_citations]
        if not citation_ids:
            # 与渲染工具一致：已绑定冻结图表的 citation 是可验证锚点；否则仅在所属
            # analysis 恰有一个 citation 时回填。
            citation_ids = list(
                dict.fromkeys(
                    citation_id
                    for chart_id in chart_ids
                    for citation_id in chart_citations[chart_id]
                    if citation_id in known_citations
                )
            )
        if not citation_ids:
            owned = analysis_citations.get(payload["managementQuestionRef"], ())
            citation_ids = list(owned) if len(owned) == 1 else []
        if citation_ids and citation_ids != list(claim.citation_ids):
            payload["citationIds"] = citation_ids
            claim_repairs.add("citation_ids")
        if claim_repairs:
            try:
                claim = SectionClaimSubmission.model_validate(payload)
            except ValidationError:
                claim_repairs.clear()
        repair_types |= claim_repairs
        repaired_claims.append(claim)
    if not repair_types:
        return decision
    loguru_logger.bind(
        section_code=work_item.section_code,
        repair_types=sorted(repair_types),
    ).warning("report_section_plan_references_repaired")
    return decision.model_copy(update={"claims": tuple(repaired_claims)})


def _has_verifiable_anchor(claim: SectionClaimSubmission, work_item: SectionWorkItem) -> bool:
    """claim 是否仍有渲染工具可接受的事实锚点（已知 citation 或已知图表）。"""

    known_citations = {item.citation_id for item in work_item.citations}
    known_charts = {item.chart_id for item in work_item.charts}
    return bool(set(claim.citation_ids) & known_citations or set(claim.chart_ids) & known_charts)


def _backfill_claim_management_question_refs(candidate: Any, work_item: SectionWorkItem) -> Any:
    """仅无歧义时回填模型遗漏的 managementQuestionRef，歧义时保持缺失由严格校验失败关闭。

    managementQuestionRef 是服务端冻结目录的引用抄录（与 periodBasis、
    managementQuestion 同类），弱模型批量遗漏是高频故障；单一目录或
    metricCode 唯一归属某个 analysis 时回填是确定性事实，不属于猜测。
    已提交（即使错误）的引用一律不覆盖，交给引用校验循环纠错。
    """

    if not isinstance(candidate, Mapping):
        return candidate
    render: Any = candidate
    wrapper_key: str | None = None
    if candidate.get("kind") != "render":
        if len(candidate) != 1:
            return candidate
        key, inner = next(iter(candidate.items()))
        if key != "render" or not isinstance(inner, Mapping):
            return candidate
        render, wrapper_key = inner, key
    claims = render.get("claims")
    if not isinstance(claims, list):
        return candidate
    if not work_item.management_question_catalog:
        return candidate
    single_ref, unique_metric_refs = _management_question_ref_index(work_item)
    backfilled = 0
    normalized_claims: list[Any] = []
    for claim in claims:
        if (
            isinstance(claim, Mapping)
            and "managementQuestionRef" not in claim
            and "management_question_ref" not in claim
        ):
            metric_code = claim.get("metricCode")
            if not isinstance(metric_code, str):
                metric_code = claim.get("metric_code")
            backfill_ref = single_ref
            if backfill_ref is None and isinstance(metric_code, str):
                backfill_ref = unique_metric_refs.get(metric_code)
            if backfill_ref is not None:
                claim = {**claim, "managementQuestionRef": backfill_ref}
                backfilled += 1
        normalized_claims.append(claim)
    if not backfilled:
        return candidate
    loguru_logger.bind(
        section_code=work_item.section_code,
        backfilled_count=backfilled,
    ).warning("report_section_plan_claim_ref_backfilled")
    normalized_render = {**render, "claims": normalized_claims}
    return {wrapper_key: normalized_render} if wrapper_key else normalized_render


def _verified_table_sources(files: Sequence[SectionEvidenceFile]) -> dict[str, bytes]:
    """只从未投影证据的冻结身份签发表格来源；冲突来源整组弃用。"""

    sources: dict[str, bytes] = {}
    conflicting: set[str] = set()
    for evidence_file in files:
        identity = evidence_file.identity
        resource_id = derive_resource_id(identity.path)
        try:
            content = evidence_file.content.encode("utf-8")
        except UnicodeEncodeError:
            conflicting.add(resource_id)
            sources.pop(resource_id, None)
            loguru_logger.warning("report_table_source_invalid_utf8 resource_id={}", resource_id)
            continue
        if len(content) != identity.size or hashlib.sha256(content).hexdigest() != identity.sha256:
            conflicting.add(resource_id)
            sources.pop(resource_id, None)
            loguru_logger.warning("report_table_source_identity_mismatch resource_id={}", resource_id)
            continue
        if resource_id in sources and sources[resource_id] != content:
            conflicting.add(resource_id)
            sources.pop(resource_id)
            loguru_logger.warning("report_table_source_identity_conflict resource_id={}", resource_id)
        elif resource_id not in conflicting:
            sources[resource_id] = content
    return sources


def _evidence_and_computation_layers(
    evidence_manifest: Any,
) -> tuple[tuple[ComputationRecordV1, ...], tuple[FileIdentity, ...]]:
    """B4：计算记录/脚本只随有效记录登记；补证文件身份始终登记。

    修订产物包只收 manifest/index/job 登记过的身份；补证文件不进索引时，编辑器
    导出的修订包会整棵丢失 evidence 树，编辑器与离线回放随之失去核验来源。
    计算记录无效或存在循环依赖时只丢弃计算层，不连补证文件一起丢。
    """

    records: list[ComputationRecordV1] = []
    scripts: list[FileIdentity] = []
    evidence_files: list[FileIdentity] = []
    for item in (evidence_manifest.evidence if evidence_manifest is not None else ()):
        evidence_files.extend(item.evidence_files)
        raw = item.computation_record
        if not isinstance(raw, dict):
            continue
        try:
            record = ComputationRecordV1.model_validate(raw)
        except ValidationError:
            loguru_logger.warning(
                "report_computation_record_invalid analysis_id={}",
                item.analysis_id,
            )
            continue
        records.append(record)
        if item.computation_script_file is not None:
            scripts.append(item.computation_script_file)
    cycles = detect_computation_cycles(tuple(records))
    if cycles:
        loguru_logger.warning("report_computation_cycle_dropped cycles={}", cycles[:5])
        return (), tuple(evidence_files)
    return tuple(records), tuple((*scripts, *evidence_files))


async def _generate_section_in_blocks(
    agent: Any,
    instruction_payload: Mapping[str, Any],
    evidence: SectionEvidenceBundle,
    work_item: SectionWorkItem,
    *,
    scope: TaskExecutionScope,
    run_context: RunContext,
    thinking_request: ThinkingRequest,
    recovery: Mapping[str, Any] | None = None,
    whole_section: bool = False,
    review_notices: dict[str, list[dict[str, Any]]] | None = None,
) -> SectionDecision:
    """复用章节规划，按开关整章生成或沿用原有逐块生成。

    review_notices 按 blockId 收集纠错后仍残留的复核告警，供章节提交时并入质量告警。
    """

    original_evidence_files = evidence.files
    table_sources = _verified_table_sources(original_evidence_files)
    scoped_fact_ids: set[str] | None = None
    if work_item.finding_ids:
        scoped_files, scoped_fact_ids, source_warnings = finding_evidence_view(
            evidence.files, work_item
        )
        evidence = evidence.model_copy(update={
            "files": scoped_files,
            "factSummaries": (*evidence.fact_summaries, *(
                f"warning: {item['message']}" for item in source_warnings
            )),
        })

    if work_item.narrative_role == "appendix":
        # 文件已由 SectionWorkflow 校验；这里只精简模型写作视图，提交仍核对原始 WorkItem。
        evidence = evidence.model_copy(update={"fact_summaries": ()})
        work_item = work_item.model_copy(update={"evidence": tuple(
            item.model_copy(update={
                "summary": "本节只呈现 findingSummaries 分配的冻结发现。",
                "computation_record": None, "computation_script_file": None,
            }) for item in work_item.evidence
        )})

    # 规划阶段只收到文件身份，不能要求模型从摘要猜测内容寻址的事实 ID。
    # 目录仅从本轮已验证 SHA 的证据正文提取，不接受模型提交的编号别名。
    fact_catalog: list[dict[str, Any]] = []
    for evidence_file in original_evidence_files:
        try:
            document = json.loads(evidence_file.content)
        except ValueError:
            continue
        if (
            not isinstance(document, dict)
            or document.get("analysisId") not in work_item.analysis_ids
        ):
            continue
        for kind in ("metrics", "derivedMetrics", "comparisons", "reconciliations"):
            for entry in document.get(kind, ()):
                if not isinstance(entry, dict) or not isinstance(entry.get("factId"), str):
                    continue
                fact_catalog.append(
                    {
                        "analysisId": document["analysisId"],
                        "kind": kind,
                        **{
                            key: entry[key]
                            for key in (
                                "factId",
                                "metricCodes",
                                "code",
                                "field",
                                "unit",
                                "formula",
                                "periodStart",
                                "periodEnd",
                                "periodRoles",
                                "total",
                                "value",
                                "currentTotal",
                                "baselineTotal",
                                "change",
                                "changeRate",
                            )
                            if key in entry
                        },
                    }
                )
    if scoped_fact_ids is not None:
        fact_catalog = [item for item in fact_catalog if item["factId"] in scoped_fact_ids]
    known_fact_ids = {item["factId"] for item in fact_catalog}
    number_contents = tuple(item.content for item in original_evidence_files)
    plan_payload = {
        **instruction_payload,
        "generationStage": "plan",
        "evidenceFiles": [
            item.identity.model_dump(mode="json", by_alias=True) for item in evidence.files
        ],
        "factCatalog": fact_catalog,
        "numberGuide": _section_number_context(
            number_contents, instruction_payload.get("fieldDefinitions", {}),
            allowed_fact_ids=scoped_fact_ids,
        )[1],
        "requiredAction": (
            f"证据充足时返回 1 到 {min(work_item.max_blocks or 12, 12)} 个必要 block 的结构规划及完整 claims；"
            "block 只包含 blockId、objective、claimIds，不生成 Markdown 正文。"
            "claim.factIds 必须原样复制 factCatalog 中支持结论的 factId，"
            "不得自行编造 fact_001 等编号；没有支持该结论的登记事实时不填 factIds。"
            "动态章节的 claim.findingIds 必须从当前分配的发现中选择，不得引用其他章节发现。"
        ),
        "requiredOutputShape": {
            "kind": "render",
            "sectionCode": work_item.section_code,
            "blocks": [
                {
                    "blockId": "block_001",
                    "objective": "当前 block 的写作目标",
                    "claimIds": ["claim_001"],
                }
            ],
            "claims": [
                {
                    "claimId": "claim_001",
                    **({"findingIds": list(work_item.finding_ids[:1])} if work_item.finding_ids else {}),
                    "metricCode": "必须来自 allowedMetricCodes",
                    "value": "必须来自证据",
                    "managementQuestionRef": "必须来自 managementQuestionRefs",
                    "citationIds": ["必须来自当前 citations"],
                    "chartIds": [],
                }
            ],
        },
    }
    plan_payload.pop("assertionPolicy", None)
    analysis_rework_allowed = instruction_payload.get("analysisReworkAllowed") is not False
    plan_schema = SectionPlanOutput if analysis_rework_allowed else RenderSectionPlan
    plan_payload["analysisReworkAllowed"] = analysis_rework_allowed
    if not analysis_rework_allowed:
        plan_payload["requiredAction"] = (
            "补证次数已达到上限，不得再次请求补证；只使用当前冻结证据返回 1 到 12 个必要 "
            "block 的结构规划及完整 claims，省略没有证据支持的结论；block 不生成 Markdown 正文。"
        )
    if recovery is not None:
        plan_payload["recovery"] = dict(recovery)
    previous_output: dict[str, Any] | None = None
    for plan_call in range(1, _MAX_PLAN_REFERENCE_CORRECTIONS + 2):
        planned = await _run_section_stage(
            agent,
            plan_schema,
            "plan",
            plan_payload,
            scope=scope,
            run_context=run_context,
            thinking_request=_section_stage_thinking_request(thinking_request, "plan"),
            section_code=work_item.section_code,
            response_validator=_section_plan_response_validator(
                work_item, plan_schema, previous_output
            ),
            attempt_key=f"plan-{plan_call}",
        )
        if analysis_rework_allowed:
            if not isinstance(planned, SectionPlanOutput):
                raise ReportingError(
                    "report_phase_output_invalid", "章节规划 Agent 未返回声明的结果。"
                )
            decision = planned.root
        else:
            if not isinstance(planned, RenderSectionPlan):
                raise ReportingError(
                    "report_phase_output_invalid", "降级章节规划 Agent 未返回 render 结果。"
                )
            decision = planned
        if isinstance(decision, AnalysisReworkDecision):
            return decision
        if not isinstance(decision, RenderSectionPlan):
            raise ReportingError("report_phase_output_invalid", "章节规划结果类型无效。")
        if decision.section_code != work_item.section_code:
            raise ReportingError(
                "report_section_artifact_invalid", "章节规划没有绑定当前 sectionCode。"
            )
        decision = _repair_section_plan_references(decision, work_item)
        reference_issues = _section_plan_reference_issues(decision, work_item)
        for index, claim in enumerate(decision.claims):
            if set(claim.fact_ids) - known_fact_ids:
                reference_issues.append(
                    {
                        "path": f"$.claims[{index}].factIds",
                        "type": "unknown_fact_id",
                        "message": "factIds 必须来自当前冻结事实目录，不得编造编号。",
                        "allowedValues": sorted(known_fact_ids),
                    }
                )
        if not reference_issues:
            break
        if plan_call > _MAX_PLAN_REFERENCE_CORRECTIONS:
            if any(item["type"] == "unknown_fact_id" for item in reference_issues):
                raise ReportingError(
                    "report_claim_fact_unknown",
                    "章节规划仍包含不存在的登记事实引用。",
                    details={"issues": reference_issues},
                )
            # 纠错预算耗尽后交给渲染工具按软告警契约处理：未知指标/管理问题保留并告警，
            # 未知 citation/chart 解绑，失去全部 claim 的 block 并入相邻 block，告警写入
            # 章节产物。只有没有任何 claim 保留事实锚点时才提前失败，避免白跑正文生成。
            if not any(_has_verifiable_anchor(claim, work_item) for claim in decision.claims):
                raise ReportingError(
                    "report_section_plan_reference_invalid",
                    "章节规划引用了当前 WorkItem 外的指标、管理问题、citation 或 chart。",
                    details={"issues": reference_issues},
                )
            loguru_logger.bind(
                section_code=work_item.section_code,
                issue_count=len(reference_issues),
                issue_types=sorted({str(item["type"]) for item in reference_issues}),
            ).warning("report_section_plan_references_unresolved")
            break
        previous_output = decision.model_dump(mode="json", by_alias=True)
        encoded_previous = json.dumps(
            previous_output,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        correction: dict[str, Any] = {
            "attempt": plan_call,
            "code": "report_section_plan_reference_invalid",
            "issues": reference_issues,
            "requiredAction": (
                "逐项修正 issues，保留其余有效规划；返回包含 kind、sectionCode、blocks、"
                "claims 的完整规划对象，不得只返回被修正的 claim、补丁、解释或 schema 外字段。"
            ),
        }
        if len(encoded_previous) <= 32 * 1024:
            correction["previousOutput"] = previous_output
        plan_payload["correction"] = correction
        loguru_logger.bind(
            section_code=work_item.section_code,
            correction_number=plan_call,
            issue_count=len(reference_issues),
            issue_types=sorted({str(item["type"]) for item in reference_issues}),
        ).warning("report_section_plan_correction_requested")
    else:
        raise AssertionError("章节规划纠错循环未终止。")

    decision = _fit_section_plan_budget(decision, work_item)
    if whole_section:
        for compact in (False, True):
            try:
                return await _generate_whole_section_content(
                    agent, instruction_payload, evidence, work_item, decision,
                    scope=scope, run_context=run_context, thinking_request=thinking_request,
                    review_notices=review_notices, number_contents=number_contents,
                    table_sources=table_sources,
                    allowed_fact_ids=scoped_fact_ids, compact=compact,
                )
            except (ReportingError, TaskExecutionContextHardLimitError) as error:
                if (
                    not isinstance(error, TaskExecutionContextHardLimitError)
                    and error.code != "report_section_context_too_large"
                ):
                    raise
                loguru_logger.warning(
                    "{} section={} reason={}",
                    "report_section_content_split" if compact else "report_section_content_compact_retry",
                    work_item.section_code,
                    getattr(error, "code", "task_execution_context_hard_limit_exceeded"),
                )

    claims_by_id = {item.claim_id: item for item in decision.claims}
    files_by_path = {item.identity.path: item for item in evidence.files}
    blocks: list[ReportDraftBlock] = []
    for index, block_plan in enumerate(decision.blocks, start=1):
        block_claims = tuple(claims_by_id[item] for item in block_plan.claim_ids)
        citation_ids = tuple(
            dict.fromkeys(
                citation_id for claim in block_claims for citation_id in claim.citation_ids
            )
        )
        chart_ids = tuple(
            dict.fromkeys(chart_id for claim in block_claims for chart_id in claim.chart_ids)
        )
        analysis_ids = {claim.management_question_ref for claim in block_claims}
        selected_evidence = tuple(
            item
            for item in work_item.evidence
            if item.analysis_id in analysis_ids or set(item.citation_ids).intersection(citation_ids)
        )
        selected_paths = tuple(
            dict.fromkeys(
                identity.path for item in selected_evidence for identity in item.evidence_files
            )
        )
        block_facts = [item.model_dump(mode="json", by_alias=True) for item in selected_evidence]
        block_citations = [
            item.model_dump(mode="json", by_alias=True)
            for item in work_item.citations
            if item.citation_id in citation_ids
        ]
        block_charts = [_writer_chart(item) for item in work_item.charts if item.chart_id in chart_ids]
        block_metrics = [
            item.model_dump(mode="json", by_alias=True)
            for item in work_item.metric_definitions
            if item.code in {claim.metric_code for claim in block_claims}
        ]
        block_questions = [
            item.model_dump(mode="json", by_alias=True)
            for item in work_item.management_question_catalog
            if item.ref in analysis_ids
        ]
        block_fact_summaries = tuple(dict.fromkeys(item.summary for item in selected_evidence))
        selected_files = tuple(
            files_by_path[path] for path in selected_paths if path in files_by_path
        )
        block_payload = {
            "phase": "section",
            "generationStage": "block",
            "reportGoal": instruction_payload.get("reportGoal", ""),
            "sectionGoal": instruction_payload.get("sectionGoal", {}),
            "blockPlan": block_plan.model_dump(mode="json", by_alias=True),
            "claims": [item.model_dump(mode="json", by_alias=True) for item in block_claims],
            "frozenNumbers": frozen_number_catalog(
                number_contents if scoped_fact_ids is not None
                else tuple(item.content for item in selected_files)
            ),
            "fieldDefinitions": instruction_payload.get("fieldDefinitions", {}),
            "facts": block_facts,
            "metricDefinitions": block_metrics,
            "managementQuestions": block_questions,
            "citations": block_citations,
            "charts": block_charts,
            "markdownRequirements": list(work_item.markdown_requirements),
            "requiredAction": (
                "只返回当前 block 的完整 Markdown；围绕 objective 解释 claims，"
                "正文不展示任何内部 ID，每个数字必须来自给定事实。"
                "只陈述可核对的数据质量事实；模型摘要中的未入账、月份不完整等猜测不能作为已验证原因。没有直接证据时不写原因，限制只在本章数据限制段落说明一次。"
            ),
        }
        # 完整证据只驻留在当前固定 Workflow 内存中；模型按 block 消费带身份的相关视图。
        block_number_catalog = block_payload["frozenNumbers"]
        block_payload["frozenNumbers"], block_payload["numberGuide"] = _section_number_context(
            number_contents if scoped_fact_ids is not None
            else tuple(item.content for item in selected_files),
            block_payload["fieldDefinitions"],
            claims=block_claims,
            allowed_fact_ids=scoped_fact_ids,
        )
        block_assertions = _controlled_assertions(number_contents, block_payload, instruction_payload.get("assertionPolicy"))
        if "questionSpecs" in instruction_payload:
            block_payload["questionSpecs"] = instruction_payload["questionSpecs"]
        # claims、冻结摘要和引用对象始终完整保留，切片只移除与当前 block 无关的文件正文。
        block_payload["evidence"] = _project_section_evidence_files(
            agent,
            selected_files,
            fact_summaries=block_fact_summaries,
            relevance_values=(
                block_payload["reportGoal"],
                block_payload["sectionGoal"],
                block_payload["blockPlan"],
                block_payload["claims"],
                block_facts,
                block_metrics,
                block_questions,
                block_citations,
                block_charts,
                block_fact_summaries,
            ),
            base_payload=block_payload,
            run_context=run_context,
        )
        review_warnings: list[str] = []
        first_block_content: Any = None
        first_block_warnings: list[str] = []
        first_block_score = (0, 0)
        for block_attempt in range(2):
            try:
                content = await _run_section_stage(
                    agent,
                    SectionBlockContent,
                    f"block-{index}",
                    block_payload,
                    scope=scope,
                    run_context=run_context,
                    thinking_request=_section_stage_thinking_request(
                        thinking_request, f"block-{index}"
                    ),
                    section_code=work_item.section_code,
                    attempt_key=f"block-{index}-{block_attempt + 1}",
                )
                if not isinstance(content, SectionBlockContent):
                    raise ReportingError(
                        "report_phase_output_invalid", "章节正文 Agent 未返回声明的结果。"
                    )
            except (ReportingError, ModelProviderError, TaskExecutionContextHardLimitError) as error:
                if block_attempt == 0 or not isinstance(first_block_content, SectionBlockContent):
                    raise
                loguru_logger.warning("report_content_review_correction_unavailable section={} code={}", work_item.section_code, getattr(error, "code", type(error).__name__))
                # 不让无效纠错响应覆盖已验证的首轮正文。
                content = first_block_content
            from ...trace.semantic_bindings import expand_assertion_placeholders

            aligned_markdown, _ = align_number_selections(
                expand_assertion_placeholders(content.markdown, block_assertions),
                number_contents, block_payload["fieldDefinitions"],
            )
            content = content.model_copy(update={"markdown": aligned_markdown})
            content_review = review_content_result(content.markdown, number_contents,
                                             field_definitions=block_payload["fieldDefinitions"],
                                             fact_ids=(fact_id for claim in block_claims for fact_id in claim.fact_ids),
                                             bound_chart_ids=chart_ids)
            review_warnings = list(content_review.warnings)
            accuracy_count = content_review.accuracy_count
            # 各 block 独立生成，常重复前文的开场与结论；逐句重复同样进入纠错轮次。
            review_warnings.extend(repeated_sentence_warnings(
                content.markdown, (block.markdown for block in blocks), block_number_catalog,
            ))
            # 长句与数值堆砌按读者所见（占位换成显示值）度量，同样进入纠错轮次。
            review_warnings.extend(readability_warnings(content.markdown, block_number_catalog))
            # 准确性问题优先：先比准确性问题数，再比可读性（重复、长句）问题数。
            review_score = (accuracy_count, len(review_warnings) - accuracy_count)
            if block_attempt == 1 and review_score > first_block_score:
                # 纠错后问题反而更严重时保留首轮版本，纠错不能让正文变差。
                loguru_logger.warning("report_content_correction_reverted section={} blocks={}",
                                      work_item.section_code, block_plan.block_id)
                content, review_warnings = first_block_content, first_block_warnings
            loguru_logger.info("report_content_review_completed section={} block={} attempt={} issue_count={}",
                               work_item.section_code, block_plan.block_id, block_attempt, len(review_warnings))
            if review_warnings and block_attempt == 0:
                first_block_content, first_block_warnings, first_block_score = content, review_warnings, review_score
                block_payload["correction"] = {
                    "issues": review_warnings, "previousOutput": content.model_dump(mode="json", by_alias=True),
                    "referenceIssues": list(content_review.reference_issues),
                    "requiredAction": (
                        "逐条处理 issues：修正有依据的数字和口径；内部 ID 和英文字段名改用业务名称；"
                        "负值改写为正的下降幅度或“变化率为…”；删去与前文重复的表述；拆分过长或数值堆砌的句子；"
                        "大额金额与人次改用万元、亿元或万人次占位；补全未写完的句子；删除无直接证据的原因。"
                        + _LATER_CORRECTION_ACTIONS + "返回当前 block 完整正文；语义问题不阻断发布。"
                    ),
                }
                continue
            for warning in review_warnings:
                loguru_logger.warning("report_content_review_warning section={} message={}", work_item.section_code, warning)
            from ...trace.semantic_bindings import render_bound_numbers

            bound_markdown, number_references, number_notices = render_bound_numbers(
                content.markdown, number_contents,
                key=f"{work_item.section_code}:{block_plan.block_id}",
                field_definitions=block_payload["fieldDefinitions"],
                table_sources=table_sources,
                assertions=block_assertions,
            )
            candidate = ReportDraftBlock(
                blockId=block_plan.block_id,
                markdown=bound_markdown,
                numberReferences=number_references,
                reviewNotices=number_notices,
                chartPlacement="explicit",
                citationIds=citation_ids,
                chartIds=chart_ids,
                claimIds=block_plan.claim_ids,
            )
            if review_notices is not None:
                review_notices[block_plan.block_id] = _block_review_notices(
                    work_item.section_code, block_plan.block_id, review_warnings,
                    content.markdown, candidate.markdown, number_notices=candidate.review_notices,
                )
            try:
                validate_report_draft_blocks(
                    (*blocks, candidate),
                    expected_section_title=work_item.title,
                )
            except ReportingError as error:
                promoted = _promoted_heading_block(error, candidate, blocks, work_item)
                if promoted is not None:
                    blocks.append(promoted)
                    break
                if error.code != "report_draft_heading_parent_missing" or block_attempt == 1:
                    raise
                issues = error.details.get("issues") if isinstance(error.details, Mapping) else None
                if not isinstance(issues, list):
                    raise
                block_payload["correction"] = {
                    "attempt": block_attempt + 1,
                    "code": error.code,
                    "issues": issues,
                    "previousOutput": {"markdown": content.markdown},
                    "requiredAction": (
                        "仅修正 issues 指向的当前 block；在 output_schema.markdown 字段中返回完整正文，"
                        "保留其余有效内容，不得返回解释、代码围栏或 schema 外字段。"
                    ),
                }
                continue
            blocks.append(candidate)
            break
    return RenderSectionDecision(
        sectionCode=decision.section_code,
        blocks=tuple(blocks),
        claims=decision.claims,
    )


async def _generate_whole_section_content(
    agent: Any,
    instruction_payload: Mapping[str, Any],
    evidence: SectionEvidenceBundle,
    work_item: SectionWorkItem,
    plan: RenderSectionPlan,
    *,
    scope: TaskExecutionScope,
    run_context: RunContext,
    thinking_request: ThinkingRequest,
    review_notices: dict[str, list[dict[str, Any]]] | None = None,
    number_contents: Sequence[str] | None = None,
    table_sources: Mapping[str, bytes] | None = None,
    allowed_fact_ids: set[str] | None = None,
    compact: bool = False,
) -> RenderSectionDecision:
    """一次生成整章正文；引用与顺序始终由已校验规划决定。"""

    number_contents = tuple(number_contents or (item.content for item in evidence.files))
    if table_sources is None:
        table_sources = _verified_table_sources(evidence.files)
    payload = {
        "phase": "section",
        "generationStage": "content",
        "frozenNumbers": prompt_number_catalog(frozen_number_catalog(number_contents)),
        "fieldDefinitions": instruction_payload.get("fieldDefinitions", {}),
        "reportGoal": instruction_payload.get("reportGoal", ""),
        "sectionGoal": instruction_payload.get("sectionGoal", {}),
        "sectionPlan": plan.model_dump(mode="json", by_alias=True),
        "facts": [item.model_dump(mode="json", by_alias=True) for item in work_item.evidence],
        "metricDefinitions": [
            item.model_dump(mode="json", by_alias=True) for item in work_item.metric_definitions
        ],
        "managementQuestions": [
            item.model_dump(mode="json", by_alias=True)
            for item in work_item.management_question_catalog
        ],
        "citations": [item.model_dump(mode="json", by_alias=True) for item in work_item.citations],
        "charts": [_writer_chart(item) for item in work_item.charts],
        "markdownRequirements": list(work_item.markdown_requirements),
        "requiredAction": (
            "一次返回规划中所有 block 的 blockId 和完整 markdown，围绕各自 objective 与 claims"
            "组织整章正文。各 block 仅解读其 claim 绑定的图表；引用由服务端绑定，不要输出引用字段。"
            "每个数字必须来自冻结事实；数据质量问题优先说明，业务归因必须有直接证据；证据不足时不写原因；口径限制与需补核事项在章末合并说明一次，不逐段重复待核实提示。"
        ),
    }
    section_number_catalog = payload["frozenNumbers"]
    block_fact_ids = {
        block.block_id: tuple(fact_id for claim in plan.claims if claim.claim_id in block.claim_ids
                             for fact_id in claim.fact_ids)
        for block in plan.blocks
    }
    block_chart_ids = {
        block.block_id: tuple(chart for claim in plan.claims if claim.claim_id in block.claim_ids
                              for chart in claim.chart_ids)
        for block in plan.blocks
    }
    payload["frozenNumbers"], payload["numberGuide"] = _section_number_context(
        number_contents, payload["fieldDefinitions"],
        claims=plan.claims,
        allowed_fact_ids=allowed_fact_ids,
    )
    section_assertions = _controlled_assertions(number_contents, payload, instruction_payload.get("assertionPolicy"))
    if "questionSpecs" in instruction_payload:
        payload["questionSpecs"] = instruction_payload["questionSpecs"]
    # 摘要和计算审计不再与已核验的原子事实重复发送；原 WorkItem 留供提交验收。
    if evidence.files:
        payload["facts"] = [
            {key: value for key, value in item.items()
             if key not in {"summary", "computationRecord", "computationScriptFile"}}
            for item in payload["facts"]
        ]
    fact_summaries = tuple(dict.fromkeys(evidence.fact_summaries))
    if compact and evidence.files:
        # 压缩重试只省略非权威的分析摘要，不删预算、基期、分解或对账原子记录。
        fact_summaries = tuple(item for item in fact_summaries if item.startswith("warning:"))
    payload["evidence"] = _project_section_evidence_files(
        agent,
        tuple({item.identity.path: item for item in evidence.files}.values()),
        fact_summaries=fact_summaries,
        relevance_values=tuple(payload.values()),
        base_payload=payload,
        run_context=run_context,
    )

    def review_blocks(
        candidate: SectionContent,
    ) -> tuple[dict[str, tuple[int, int]], dict[str, list[str]], dict[str, list[dict[str, Any]]]]:
        # 默认整章生成路径与分块路径使用同一组复核：数值口径、跨 block 重复与可读性。
        content_reviews = {
            block.block_id: review_content_result(block.markdown, number_contents,
                                           field_definitions=payload["fieldDefinitions"],
                                           fact_ids=block_fact_ids[block.block_id],
                                           bound_chart_ids=block_chart_ids[block.block_id])
            for block in candidate.blocks
        }
        style_warnings = {
            block.block_id: [
                *repeated_sentence_warnings(
                    block.markdown, (earlier.markdown for earlier in candidate.blocks[:position]),
                    section_number_catalog,
                ),
                *readability_warnings(block.markdown, section_number_catalog),
            ]
            for position, block in enumerate(candidate.blocks)
        }
        # 准确性问题优先于可读性问题：比较纠错前后时先比准确性问题数，再比可读性问题数。
        review_scores = {key: (review.accuracy_count, review.presentation_count + len(style_warnings[key]))
                         for key, review in content_reviews.items()}
        review_warnings = {
            key: [*review.warnings, *style_warnings[key]]
            for key, review in content_reviews.items() if review.warnings or style_warnings[key]
        }
        return review_scores, review_warnings, {
            key: list(review.reference_issues) for key, review in content_reviews.items() if review.reference_issues
        }

    first_by_id: dict[str, Any] = {}
    first_warnings: dict[str, list[str]] = {}
    first_scores: dict[str, tuple[int, int]] = {}
    flagged_ids: set[str] = set()
    for review_attempt in range(2):
        try:
            request_tokens = _section_request_tokens(agent, payload, run_context)
            input_budget = _section_block_input_token_budget(agent, run_context)
            loguru_logger.info(
                "report_section_content_budget section={} attempt={} compact={} input_tokens={} input_budget={} payload_bytes={}",
                work_item.section_code, review_attempt, compact, request_tokens, input_budget,
                len(_json_text(payload).encode("utf-8")),
            )
            if request_tokens > input_budget:
                raise ReportingError("report_section_context_too_large", "整章请求超过当前模型输入预算。",
                                     details={"requestTokens": request_tokens, "inputTokenBudget": input_budget})
            content = await _run_section_stage(
                agent,
                SectionContent,
                "content",
                payload,
                scope=scope,
                run_context=run_context,
                thinking_request=_section_stage_thinking_request(
                    thinking_request, "content", block_count=len(plan.blocks)
                ),
                section_code=work_item.section_code,
                attempt_key=f"content-{review_attempt + 1}",
            )
            if not isinstance(content, SectionContent):
                raise ReportingError("report_phase_output_invalid", "整章正文 Agent 未返回声明的结果。")
            content_by_id = {item.block_id: item for item in content.blocks}
            expected_ids = flagged_ids if review_attempt else {item.block_id for item in plan.blocks}
            duplicate_ids = len(content_by_id) != len(content.blocks)
            # 兼容仍返回整章的旧模型，只接收登记的问题段落，其他内容继续使用首轮原文。
            if review_attempt and set(content_by_id) == {item.block_id for item in plan.blocks}:
                content_by_id = {key: value for key, value in content_by_id.items() if key in flagged_ids}
            if duplicate_ids or set(content_by_id) != expected_ids:
                raise ReportingError(
                    "report_section_content_blocks_invalid",
                    "正文 blockId 必须与本轮规划一一对应，不得遗漏、重复或新增。",
                    details={"expectedBlockIds": sorted(expected_ids),
                             "actualBlockIds": [item.block_id for item in content.blocks]},
                )
        except (ReportingError, ModelProviderError, TaskExecutionContextHardLimitError) as error:
            if review_attempt == 0:
                raise
            loguru_logger.warning("report_content_review_correction_unavailable section={} code={}", work_item.section_code, getattr(error, "code", type(error).__name__))
            content_by_id, review_warnings = first_by_id, first_warnings
            break
        # 模型响应可乱序；复核与最终装配必须使用同一规划顺序。
        if review_attempt:
            content_by_id = {**first_by_id, **content_by_id}
        from ...trace.semantic_bindings import expand_assertion_placeholders

        content = content.model_copy(update={"blocks": tuple(
            content_by_id[block.block_id].model_copy(update={"markdown": align_number_selections(
                expand_assertion_placeholders(content_by_id[block.block_id].markdown, section_assertions),
                number_contents, payload["fieldDefinitions"],
            )[0]}) for block in plan.blocks
        )})
        # 复核、回退与最终签发共用已经确定性对齐的候选，避免恢复已失效的原始告警。
        content_by_id = {block.block_id: block for block in content.blocks}
        review_scores, review_warnings, reference_issues = review_blocks(content)
        if review_attempt == 1:
            # 纠错后问题反而更严重的 block 回退到首轮版本，纠错不能让正文变差。
            worse = {block_id for block_id in flagged_ids
                     if review_scores[block_id] > first_scores[block_id]}
            if worse:
                loguru_logger.warning("report_content_correction_reverted section={} blocks={}",
                                      work_item.section_code, ",".join(sorted(worse)))
                content = content.model_copy(update={"blocks": tuple(
                    first_by_id[block.block_id] if block.block_id in worse else block
                    for block in content.blocks
                )})
                content_by_id = {item.block_id: item for item in content.blocks}
                # 部分回退会改变其他 block 的“前文”，旧的重复检测结果已失效。
                _, review_warnings, _ = review_blocks(content)
        loguru_logger.info("report_content_review_completed section={} attempt={} issue_count={} block_count={}",
                           work_item.section_code, review_attempt,
                           len({warning for warnings in review_warnings.values() for warning in warnings}), len(content.blocks))
        if not review_warnings:
            break
        if review_attempt == 0:
            first_by_id = content_by_id
            first_warnings = review_warnings
            first_scores = review_scores
            flagged_ids = set(review_warnings)
            correction_plan = plan.model_copy(update={
                "blocks": tuple(block for block in plan.blocks if block.block_id in flagged_ids),
                "claims": tuple(claim for claim in plan.claims if any(
                    claim.claim_id in block.claim_ids for block in plan.blocks if block.block_id in flagged_ids
                )),
            })
            payload["sectionPlan"] = correction_plan.model_dump(mode="json", by_alias=True)
            payload["requiredAction"] = "仅返回 sectionPlan 中本轮待修正的 block；其他段落由服务端保留。"
            payload["preservedContext"] = [
                {"blockId": block.block_id, "objective": block.objective,
                 "markdown": first_by_id[block.block_id].markdown}
                for block in plan.blocks if block.block_id not in flagged_ids
            ]
            payload["correction"] = {
                "issues": review_warnings,
                "referenceIssues": {key: issues for key, issues in reference_issues.items() if key in flagged_ids},
                "previousOutput": {"blocks": [block.model_dump(mode="json", by_alias=True)
                                              for block in content.blocks if block.block_id in flagged_ids]},
                "requiredAction": (
                    "逐条处理 issues：修正数字与字段口径并使用冻结数值引用；内部 ID 和英文字段名改用业务名称；"
                    "负值改写为正的下降幅度或“变化率为…”；删去与前文重复的表述；拆分过长或数值堆砌的句子；"
                    "大额金额与人次改用万元、亿元或万人次占位；补全未写完的句子。"
                    + _LATER_CORRECTION_ACTIONS
                    + "删去无直接证据的推测与重复的待核实提示。只返回 issues 列出的 block 完整正文，保留 blockId；"
                    "preservedContext 仅供衔接和去重，不得返回或改写。"
                ),
            }
        else:
            for block_id, warnings in review_warnings.items():
                for warning in warnings:
                    loguru_logger.warning("report_content_review_warning section={} block={} message={}",
                                         work_item.section_code, block_id, warning)
    claims_by_id = {item.claim_id: item for item in plan.claims}
    blocks: list[ReportDraftBlock] = []
    for block_plan in plan.blocks:
        claims = tuple(claims_by_id[item] for item in block_plan.claim_ids)
        from ...trace.semantic_bindings import render_bound_numbers

        bound_markdown, number_references, number_notices = render_bound_numbers(
            content_by_id[block_plan.block_id].markdown, number_contents,
            key=f"{work_item.section_code}:{block_plan.block_id}",
            field_definitions=payload["fieldDefinitions"],
            table_sources=table_sources,
            assertions=section_assertions,
        )
        block = ReportDraftBlock(
            blockId=block_plan.block_id,
            markdown=bound_markdown,
            numberReferences=number_references,
            reviewNotices=number_notices,
            chartPlacement="explicit",
            claimIds=block_plan.claim_ids,
            citationIds=tuple(dict.fromkeys(ref for claim in claims for ref in claim.citation_ids)),
            chartIds=tuple(dict.fromkeys(ref for claim in claims for ref in claim.chart_ids)),
        )
        if review_notices is not None:
            review_notices[block_plan.block_id] = _block_review_notices(
                work_item.section_code, block_plan.block_id, review_warnings.get(block_plan.block_id, ()),
                content_by_id[block_plan.block_id].markdown, block.markdown, number_notices=block.review_notices,
            )
        try:
            validate_report_draft_blocks((*blocks, block), expected_section_title=work_item.title)
        except ReportingError as error:
            promoted = _promoted_heading_block(error, block, blocks, work_item)
            if promoted is None:
                raise
            block = promoted
        blocks.append(block)
    return RenderSectionDecision(
        sectionCode=plan.section_code, blocks=tuple(blocks), claims=plan.claims
    )


def _promoted_heading_block(
    error: ReportingError,
    candidate: ReportDraftBlock,
    blocks: Sequence[ReportDraftBlock],
    work_item: SectionWorkItem,
) -> ReportDraftBlock | None:
    """孤立 H4 由服务端确定性提升为 H3，省去一次模型重写；无法修正时交回模型纠错。"""

    if error.code != "report_draft_heading_parent_missing":
        return None
    from ...trace.semantic_bindings import anchor_bound_numbers, strip_bound_anchors

    markdown = promote_orphan_h4_headings(
        anchor_bound_numbers(candidate.markdown, candidate.number_references, candidate.review_notices),
        expected_section_title=None if blocks else work_item.title,
    )
    if markdown is None:
        return None
    markdown, references, notices = strip_bound_anchors(
        markdown, candidate.number_references, candidate.review_notices or (),
    )
    promoted = candidate.model_copy(update={
        "markdown": markdown, "number_references": references,
        "review_notices": notices if candidate.review_notices is not None else None,
    })
    try:
        validate_report_draft_blocks((*blocks, promoted), expected_section_title=work_item.title)
    except ReportingError:
        return None
    loguru_logger.bind(
        section_code=work_item.section_code,
        block_id=candidate.block_id,
    ).warning("report_section_block_heading_promoted")
    return promoted


def _section_model_work_item_payload(work_item: SectionWorkItem) -> dict[str, Any]:
    payload = work_item.model_dump(mode="json", by_alias=True)
    payload.pop("factFiles", None)
    if work_item.finding_ids or work_item.narrative_role == "appendix":
        # 动态章节已有发现摘要；整项分析摘要和计算审计仍保留在冻结 WorkItem。
        payload.pop("factSummaries", None)
        for finding in payload["findingSummaries"]:
            finding.pop("sourceRefs", None)
            if work_item.narrative_role == "appendix":
                finding.pop("relatedFindingIds", None)
        for evidence in payload["evidence"]:
            for field in ("summary", "computationRecord", "computationScriptFile"):
                evidence.pop(field, None)
    return payload


def _section_claim_authoring_contract(work_item: SectionWorkItem) -> dict[str, Any]:
    """从当前冻结 WorkItem 生成章节 claim 的动态约束，避免模型猜测业务指标代码。"""

    return {
        "allowedFindingIds": list(work_item.finding_ids),
        "contentBudget": {"maxBlocks": work_item.max_blocks, "maxCharts": work_item.max_charts},
        "findingRule": (
            "动态章节的每个结论通过 findingIds 绑定当前章节发现；仅解释分配的发现，"
            "不得把同一分析的其他发现重复写成独立结论。旧章节没有 findingIds 时不填该字段。"
        ),
        "allowedMetricCodes": [item.code for item in work_item.metric_definitions],
        "managementQuestionRefs": [
            item.model_dump(mode="json", by_alias=True)
            for item in work_item.management_question_catalog
        ],
        "serverDerivedFields": ["periodBasis", "managementQuestion"],
        "chartDerivedFields": [
            "currentPeriod",
            "comparisonPeriod",
            "comparisonType",
            "comparability",
            "chartCitationIds",
        ],
        "standaloneClaimRequiredFields": ["currentPeriod"],
        "comparisonRule": (
            "comparisonType 非 none 时必须提供 comparisonPeriod；绑定图表时以图表冻结语义为准"
        ),
    }


class RuntimeSectionsMixin:
    def _build_narrative_section_work_item(
        self,
        section: NarrativeSection,
        *,
        graph: FindingGraph,
        detailed_plan: DetailedAnalysisPlan,
        analysis_artifact: AnalysisArtifact,
        citation_bindings: tuple[Citation, ...],
    ) -> SectionWorkItem:
        cards = {card.finding_id: card for card in graph.findings}
        return self._build_section_work_item(
            ReportOutlineSection(
                code=section.code, sectionNumber=section.section_number, title=section.title,
                focus=(section.objective,), analysisIds=section.analysis_ids,
            ),
            detailed_plan=detailed_plan, analysis_artifact=analysis_artifact,
            citation_bindings=citation_bindings,
            finding_ids=section.finding_ids,
            finding_summaries=tuple(
                cards[finding_id].model_dump(mode="json", by_alias=True)
                for finding_id in section.finding_ids
            ),
            narrative_role=section.narrative_role, grouping_reason=section.grouping_reason,
            max_blocks=section.max_blocks, max_charts=section.max_charts,
        )

    def _fit_narrative_outline_context(
        self,
        outline: NarrativeOutline,
        *,
        graph: FindingGraph,
        detailed_plan: DetailedAnalysisPlan,
        analysis_artifact: AnalysisArtifact,
        citation_bindings: tuple[Citation, ...],
    ) -> NarrativeOutline:
        """冻结前按渲染器的完整投影拆分附录，不用发现条数近似上下文大小。"""
        cards = {card.finding_id: card for card in graph.findings}
        fitted: list[NarrativeSection] = []

        def append(section: NarrativeSection, finding_ids: tuple[str, ...]) -> None:
            index = len(fitted) + 1
            projected = section.model_copy(update={
                "code": f"section_{index:03d}", "section_number": str(index),
                "finding_ids": finding_ids,
                "analysis_ids": tuple(dict.fromkeys(
                    aid for finding_id in finding_ids for aid in cards[finding_id].analysis_ids
                )),
            })
            try:
                work_item = self._build_narrative_section_work_item(
                    projected, graph=graph, detailed_plan=detailed_plan,
                    analysis_artifact=analysis_artifact, citation_bindings=citation_bindings,
                )
                fits = len(_json_text(_section_model_work_item_payload(work_item)).encode(
                    "utf-8"
                )) <= MAX_SECTION_WORK_ITEM_BYTES
            except ValidationError as error:
                # 多个发现可绑定很多证据文件；先满足 WorkItem 的集合容量，
                # 其他结构错误必须照常暴露，不能伪装成输入过大。
                if any(item["type"] != "too_long" for item in error.errors()):
                    raise
                fits = False
            if fits:
                fitted.append(projected)
                return
            if len(finding_ids) == 1:
                raise ReportingError(
                    "report_section_context_too_large",
                    "单条附录发现及其冻结证据超过章节输入预算，无法继续无损拆分。",
                    details={"findingId": finding_ids[0], "maxBytes": MAX_SECTION_WORK_ITEM_BYTES},
                )
            middle = len(finding_ids) // 2
            append(section, finding_ids[:middle])
            append(section, finding_ids[middle:])

        for section in outline.sections:
            if section.narrative_role == "appendix":
                append(section, section.finding_ids)
            else:
                index = len(fitted) + 1
                fitted.append(section.model_copy(update={
                    "code": f"section_{index:03d}", "section_number": str(index),
                }))
        return NarrativeOutline.model_validate({
            **outline.model_dump(mode="python"), "sections": tuple(fitted),
        })

    @staticmethod
    def _analysis_rework_constraints(
        *,
        detailed_plan: DetailedAnalysisPlan,
        profile_coverage: ProfileCoverageManifest,
        analysis_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        analyses = {item.analysis_id: item for item in detailed_plan.analyses}
        profiles = {item.dataset_id: item for item in profile_coverage.datasets}
        constraints: dict[str, Any] = {}
        try:
            for analysis_id in analysis_ids:
                analysis = analyses[analysis_id]
                bound_profiles = tuple(profiles[dataset_id] for dataset_id in analysis.dataset_ids)
                constraints[analysis_id] = {
                    "datasetIds": list(analysis.dataset_ids),
                    "periods": list(analysis.periods),
                    "metrics": list(analysis.metrics),
                    "profileDatasets": [
                        {
                            "datasetId": item.dataset_id,
                            "rowCount": item.row_count,
                            "profileSnapshotHash": item.profile_file.sha256,
                        }
                        for item in bound_profiles
                    ],
                    "planHash": payload_sha256(analysis.model_dump(mode="json", by_alias=True)),
                }
        except KeyError as error:
            raise ReportingError(
                "report_analysis_rework_invalid",
                "章节返工约束没有绑定冻结分析计划或完整 Profile Dataset。",
            ) from error
        return constraints

    @staticmethod
    def _build_section_work_item(
        section: Any,
        *,
        detailed_plan: DetailedAnalysisPlan,
        analysis_artifact: AnalysisArtifact,
        citation_bindings: tuple[Citation, ...],
        finding_ids: tuple[str, ...] = (),
        finding_summaries: tuple[dict[str, Any], ...] = (),
        narrative_role: str | None = None,
        grouping_reason: str | None = None,
        max_blocks: int | None = None,
        max_charts: int | None = None,
    ) -> SectionWorkItem:
        analyses = {item.analysis_id: item for item in detailed_plan.analyses}
        evidence = {item.analysis_id: item for item in analysis_artifact.evidence_manifest.evidence}
        missing_analysis_ids = tuple(item for item in section.analysis_ids if item not in analyses)
        missing_evidence_ids = tuple(item for item in section.analysis_ids if item not in evidence)
        selected_analyses = tuple(
            analyses[item] for item in section.analysis_ids if item in analyses
        )
        selected_evidence = tuple(
            evidence[item] for item in section.analysis_ids if item in evidence
        )
        section_warnings = tuple(
            dict.fromkeys(
                (
                    *(f"analysisId {item} 缺少冻结分析计划" for item in missing_analysis_ids),
                    *(f"analysisId {item} 缺少冻结 evidence" for item in missing_evidence_ids),
                )
            )
        )
        receipt_ids = {
            receipt_id for item in selected_evidence for receipt_id in item.profile_read_receipt_ids
        }
        citation_ids = {
            citation_id for item in selected_evidence for citation_id in item.citation_ids
        }
        selected_metric_codes = {metric for item in selected_analyses for metric in item.metrics}
        receipts = tuple(
            item
            for item in analysis_artifact.profile_read_receipts
            if item.receipt_id in receipt_ids
        )
        # 调用方按 section_codes 构造章节级 AnalysisArtifact；图表晚于 analysis evidence
        # 生成，不能再依赖 evidence.chartIds 反向筛选，否则新生成图表会全部丢失。
        charts = analysis_artifact.evidence_manifest.charts
        selected_metric_codes.update(code for chart in charts for code in chart.metric_codes)
        citations = tuple(
            SectionCitation(
                citationId=item.citation_id,
                datasetId=item.dataset_id,
                requirementId=item.requirement_id,
                snapshotHash=item.snapshot_hash,
            )
            for item in citation_bindings
            if item.citation_id in citation_ids
        )
        objective_parts = tuple(section.focus) or tuple(
            item.management_question for item in selected_analyses
        )
        return SectionWorkItem(
            sectionCode=section.code,
            sectionNumber=section.section_number,
            title=section.title,
            objective="；".join(objective_parts),
            completionConditions=(
                ("仅呈现当前章节分配的管理发现及其证据、经营影响和管理动作" if finding_ids
                 else "完整呈现当前章节全部冻结事实及其管理结论"),
                "分别标注各发现的期间、单位和共享指标口径，不把不同口径改写成同一事实",
                "覆盖当前章节 evidence 提供的 citation",
                "仅使用当前 SectionWorkItem 提供的 chart",
                *(f"warning: {item}" for item in section_warnings),
            ),
            analysisIds=tuple(section.analysis_ids),
            findingIds=finding_ids,
            findingSummaries=finding_summaries,
            narrativeRole=narrative_role,
            groupingReason=grouping_reason,
            maxBlocks=max_blocks,
            maxCharts=max_charts,
            evidence=selected_evidence,
            metricDefinitions=tuple(
                item
                for item in analysis_artifact.evidence_manifest.metric_definitions
                if item.code in selected_metric_codes
            ),
            managementQuestionCatalog=tuple(
                SectionManagementQuestion(
                    ref=item.analysis_id,
                    question=item.management_question,
                )
                for item in selected_analyses
            ),
            # receipt 的完整查询正文只用于服务端血缘与最终 Manifest。章节只需要知道
            # 当前 evidence 已绑定哪些受信回执，避免把几十次 Profile 导航重复注入模型。
            profileReadReceiptIds=tuple(item.receipt_id for item in receipts),
            charts=charts,
            citations=citations,
            factFiles=tuple(
                identity for item in selected_evidence for identity in item.evidence_files
            ),
            factSummaries=tuple(item.summary for item in selected_evidence),
            markdownRequirements=(
                "章节编号和 title 由服务端插入，模型不得在标题中写编号或重复 H1/H2",
                (
                    "章节内部标题只使用 H3/H4，H4 必须位于对应 H3 之后；"
                    "H3/H4 必须是不超过 40 个中文字符的短标题并独占一行；"
                    "标题行后必须立即换行，正文再隔一个空行另起段落；"
                    "正确格式是『### 标题\n\n正文』，禁止『### 标题：正文……』同一行混写"
                ),
                "粗体强调必须使用 **文本**，两个标记的内侧不得留空格",
                "表格直接使用标准 Markdown 管道表，不得渲染为图片",
                (
                    "Markdown 标题和正文不得自行写 citationId、chartId、analysisId、"
                    "sectionId、图表文件名、HTML 标签或 <sup> 脚注；"
                    "citationIds、chartIds 只填入 JSON 结构化字段"
                ),
                "最后且只调用一次 render_report_section；证据不足时改用 request_analysis_rework",
            ),
        )

    async def _durable_completed_section(
        self,
        run_context: RunContext,
        *,
        revision: int,
        section_code: str,
        section_title: str,
        analysis_ids: tuple[str, ...],
        work_item_hash: str,
    ) -> tuple[CompletedSection, SectionArtifact] | None:
        durable = await self.state_repository.get_by_external_run_id(
            self._scope(run_context)["externalRunId"]
        )
        section_artifacts = durable.payload.get("sectionArtifacts") if durable is not None else None
        bound = section_artifacts.get(section_code) if isinstance(section_artifacts, dict) else None
        if not isinstance(bound, Mapping):
            return None
        # Durable sectionArtifacts 是章节完成身份的权威来源。只有 revision、WorkItem 和
        # analysis 绑定完全一致时才允许恢复；不同身份继续由既有冲突门禁失败关闭。
        if (
            bound.get("revision") != revision
            or bound.get("workItemHash") != work_item_hash
            or tuple(bound.get("analysisIds", ())) != analysis_ids
        ):
            raise ReportingError(
                "report_section_completion_conflict",
                f"章节 {section_code} 已绑定其他完成产物。",
            )
        try:
            identity = FileIdentity.model_validate(bound.get("artifactFile"))
            artifact = cast(
                SectionArtifact,
                await self._read_identity_model(
                    self._scope(run_context)["threadId"], identity, SectionArtifact
                ),
            )
        except ValidationError as error:
            raise ReportingError(
                "report_section_artifact_invalid", "Durable 章节产物身份无效。"
            ) from error
        if artifact.section_code != section_code:
            raise ReportingError(
                "report_section_artifact_invalid", "Durable 章节产物没有绑定当前 sectionCode。"
            )
        # 兼容修复前已经写入 durable state 的章节：恢复时重新执行当前正文协议校验，
        # 非法旧产物不得绕过工具接收边界进入最终装配。
        validate_report_draft_blocks(
            artifact.blocks,
            expected_section_title=section_title,
        )
        return (
            CompletedSection(
                sectionCode=section_code,
                workItemHash=work_item_hash,
                artifactFile=identity,
            ),
            artifact,
        )

    async def _run_section_phase(
        self,
        run_context: RunContext,
        *,
        checkpoint: ReportingCheckpoint,
        revision: int,
        sandbox_id: str,
        validation_context_file: FileIdentity,
        work_item: SectionWorkItem,
        analysis_rework_constraints: Mapping[str, Any],
        analysis_rework_allowed: bool,
        degraded_rework: Mapping[str, Any] | None,
    ) -> tuple[
        ReportingCheckpoint,
        SectionArtifact | None,
        AnalysisReworkRequest | None,
    ]:
        model_work_item_payload = _section_model_work_item_payload(work_item)
        context_bytes = len(_json_text(model_work_item_payload).encode("utf-8"))
        if context_bytes > MAX_SECTION_WORK_ITEM_BYTES:
            raise ReportingError(
                "report_section_context_too_large",
                "章节紧凑事实投影超过输入软上限；请减少单章绑定的 analysis 数量。",
            )
        scope = self._scope(run_context)
        work_item_payload = work_item.model_dump(mode="json", by_alias=True)
        work_item_hash = payload_sha256(work_item_payload)
        restored = await self._durable_completed_section(
            run_context,
            revision=revision,
            section_code=work_item.section_code,
            section_title=work_item.title,
            analysis_ids=work_item.analysis_ids,
            work_item_hash=work_item_hash,
        )
        if restored is not None:
            completed_section, artifact = restored
            checkpoint = self._update_reporting_checkpoint(
                checkpoint,
                phase="analysis",
                completed_sections=tuple(
                    item
                    for item in checkpoint.completed_sections
                    if item.section_code != work_item.section_code
                )
                + (completed_section,),
                pending_sections=tuple(
                    item for item in checkpoint.pending_sections if item != work_item.section_code
                ),
                last_error=None,
                files=self._merge_checkpoint_files(
                    checkpoint.files, completed_section.artifact_file
                ),
            )
            checkpoint = await self._persist_reporting_checkpoint(run_context, checkpoint)
            return checkpoint, artifact, None
        await self._apply_durable_command(
            run_context,
            ReportingCommand(
                name="start_section",
                commandId=(f"section-start:{revision}:{work_item.section_code}:{work_item_hash}"),
                payload={
                    "sectionCode": work_item.section_code,
                    "workItemHash": work_item_hash,
                },
            ),
        )
        work_item_path = (
            f"报表/智能分析/{run_context.run_id}/phases/revision-{revision}/"
            f"{work_item.section_code}-work-item-{work_item_hash[:16]}.json"
        )
        work_item_file = FileIdentity.model_validate(
            await self._write_artifact_validation_context(
                scope["threadId"], work_item_path, work_item_payload
            )
        )
        constraints_hash = payload_sha256(dict(analysis_rework_constraints))
        constraints_file = FileIdentity.model_validate(
            await self._write_artifact_validation_context(
                scope["threadId"],
                f"报表/智能分析/{run_context.run_id}/phases/revision-{revision}/"
                f"{work_item.section_code}-rework-constraints-{constraints_hash[:16]}.json",
                dict(analysis_rework_constraints),
            )
        )
        checkpoint = self._update_reporting_checkpoint(
            checkpoint,
            files=self._merge_checkpoint_files(checkpoint.files, work_item_file, constraints_file),
        )
        await self._persist_reporting_checkpoint(run_context, checkpoint)
        checkpoint_error = checkpoint.last_error
        last_error: Exception | None = (
            ReportingError(
                checkpoint_error.code,
                checkpoint_error.message,
                details=checkpoint_error.details,
            )
            if checkpoint_error is not None
            and checkpoint_error.phase == "section"
            and checkpoint_error.section_code == work_item.section_code
            else None
        )
        max_attempts = MAX_REPORT_SECTION_PHASE_ATTEMPTS * (
            MAX_REPORT_ANALYSIS_REWORKS_PER_SECTION + 1
        )

        for _ in range(max_attempts):
            started_trace = next(
                (
                    item
                    for item in reversed(checkpoint.trace)
                    if item.phase == "section"
                    and item.section_code == work_item.section_code
                    and item.status == "started"
                ),
                None,
            )
            attempt = (
                started_trace.attempt
                if started_trace is not None
                else max(
                    (
                        item.attempt
                        for item in checkpoint.trace
                        if item.phase == "section" and item.section_code == work_item.section_code
                    ),
                    default=-1,
                )
                + 1
            )
            task_id = reporting_phase_task_key(
                str(run_context.run_id or "report"),
                revision,
                "section",
                section_code=work_item.section_code,
                attempt=attempt,
            )
            phase_root = f"报表/智能分析/{run_context.run_id}/phases/revision-{revision}"
            section_output_path = (
                f"{phase_root}/{work_item.section_code}-attempt-{attempt + 1}.json"
            )
            rework_request_path = (
                f"{phase_root}/{work_item.section_code}-attempt-{attempt + 1}.rework.json"
            )
            try:
                report_goal = self._envelope(run_context).report_goal
            except ReportingError:
                report_goal = ""
            instruction_payload = {
                "phase": "section",
                "reportGoal": report_goal,
                "sectionGoal": {
                    "sectionCode": work_item.section_code,
                    "title": work_item.title,
                    "focus": list(work_item.completion_conditions),
                    "analysisIds": list(work_item.analysis_ids),
                },
                "sectionWorkItem": model_work_item_payload,
                "completionConditions": list(work_item.completion_conditions),
                "claimAuthoringContract": _section_claim_authoring_contract(work_item),
                "fieldDefinitions": {
                    column["name"]: column["description"]
                    for context in self._state(run_context).get("report_analysis_data_context", ())
                    for table in context.get("schema", {}).get("tables", ())
                    for column in table.get("columns", ())
                    if column.get("name") and column.get("description")
                },
                "sectionOutputPath": section_output_path,
                "reworkRequestPath": rework_request_path,
                "analysisReworkAllowed": analysis_rework_allowed,
            }
            assertion_policy = self._state(run_context).get("report_request_context", {}).get("assertionPolicy")
            if isinstance(assertion_policy, dict):
                from ...trace.contracts_v1 import canonical_sha256

                instruction_payload["assertionPolicy"] = {
                    **assertion_policy,
                    "profileHash": self._profile(run_context).effective_profile_hash,
                    "authorizationScopeHash": canonical_sha256({
                        key: scope[key] for key in ("userId", "threadId")
                    }),
                }
                if assertion_policy.get("mode") == "enabled":
                    instruction_payload["assertionPolicy"]["trustedFactSha256"] = [
                        identity.sha256 for identity in checkpoint.deterministic_fact_files.values()
                    ]
                    try:
                        from ..questions import QuestionSet

                        durable_questions = await self.state_repository.get(str(run_context.run_id or scope["externalRunId"]))
                        raw_questions = durable_questions.payload.get("questionSpecs") if durable_questions is not None else None
                        question_specs = QuestionSet.model_validate(raw_questions) if raw_questions is not None else None
                        if question_specs is not None:
                            instruction_payload["questionSpecs"] = {
                                "version": question_specs.version,
                                "questions": [item.model_dump(mode="json", by_alias=True)
                                              for item in question_specs.questions
                                              if item.kind == "request" or set(item.analysis_ids) & set(work_item.analysis_ids)],
                                "requiredAction": "保留原始需求及补充要求；分析分配不等于问题已回答。明确说明未回答与缺证据的部分。",
                            }
                        else:
                            instruction_payload["questionEvaluationStatus"] = "specification_unavailable"
                    except Exception as error:
                        loguru_logger.warning("report_frozen_questions_unavailable reason={}", type(error).__name__)
                        instruction_payload["questionEvaluationStatus"] = "specification_unavailable"
            if degraded_rework is not None:
                instruction_payload["degradedDraftContext"] = dict(degraded_rework)
            retry_context = _section_retry_context(last_error)
            if retry_context is not None:
                instruction_payload["retryContext"] = retry_context
            instruction = json.dumps(instruction_payload, ensure_ascii=False, separators=(",", ":"))
            instruction_bytes = len(instruction.encode("utf-8"))
            if instruction_bytes > MAX_REPORT_INSTRUCTION_BYTES:
                raise ReportingError(
                    "report_section_context_too_large",
                    "章节紧凑事实投影超过模型输入边界；请减少单章绑定的 analysis 数量。",
                )
            contract = build_report_phase_acceptance_contract(
                phase="section",
                validation_context_file=validation_context_file.model_dump(
                    mode="json", by_alias=True
                ),
                phase_contract={
                    "reportRunId": str(run_context.run_id or scope["externalRunId"]),
                    "taskKind": "section",
                    "thinkingEffort": "off",
                    "sectionWorkItemFile": work_item_file.model_dump(mode="json", by_alias=True),
                    "analysisReworkConstraintsFile": constraints_file.model_dump(
                        mode="json", by_alias=True
                    ),
                },
                section_output_path=section_output_path,
                rework_request_path=rework_request_path,
            )
            task_scope = TaskExecutionScope(
                task_id,
                scope["userId"],
                scope["threadId"],
                sandbox_id,
                "reporting-section-agent",
            )
            if started_trace is None:
                checkpoint = self._update_reporting_checkpoint(
                    checkpoint,
                    trace=(
                        *checkpoint.trace,
                        ContextTrace(
                            phase="section",
                            taskId=task_id,
                            workKind="section",
                            sectionCode=work_item.section_code,
                            attempt=attempt,
                            instructionBytes=instruction_bytes,
                            projectedContextBytes=instruction_bytes,
                        ),
                    ),
                    last_error=None,
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
            trace_metrics: dict[str, Any] = {}
            try:
                existing = await self.task_runner.repository.get_task_snapshot(task_id)
                if existing is None:
                    await self.task_runner.start(
                        task_scope, instruction, acceptance_contract=contract
                    )
                elif existing.state in {TaskState.FAILED, TaskState.CANCELLED}:
                    raise ReportingError(
                        "report_section_task_terminal",
                        f"章节 {work_item.section_code} task 未签发阶段产物即终止。",
                    )
                if self.section_generator is None:
                    raise ReportingError(
                        "report_section_executor_missing", "章节结构化生成器未配置。"
                    )

                async def execute_fixed_section(
                    invocation: ReportingTaskInvocation,
                ) -> SectionDecision:
                    toolkits = build_reporting_tools(
                        self.workspace_service,
                        self.task_runner.repository,
                        state_repository=self.state_repository,
                        run_context=invocation.run_context,
                    )
                    if len(toolkits) != 1:
                        raise ReportingError(
                            "report_phase_contract_invalid", "章节 Toolkit 装配结果无效。"
                        )
                    toolkit = toolkits[0]
                    validated_evidence: SectionEvidenceBundle | None = None
                    # 本次生成（或恢复生成）纠错后仍残留的块级复核告警，随章节提交进入质量告警。
                    review_notices: dict[str, list[dict[str, Any]]] = {}

                    async def read_evidence(
                        path: str, offset: int, task_context: RunContext
                    ) -> Mapping[str, Any]:
                        receipt = await toolkit.read_file(
                            path, offset=offset, run_context=task_context
                        )
                        if receipt.get("ok") is False:
                            raise ReportingError(
                                str(receipt.get("code", "report_section_evidence_invalid")),
                                str(receipt.get("message", "章节证据读取未被接受。")),
                                details=dict(receipt),
                            )
                        return receipt

                    async def generate(
                        evidence: SectionEvidenceBundle, task_context: RunContext
                    ) -> SectionDecision:
                        nonlocal validated_evidence
                        validated_evidence = evidence
                        review_notices.clear()
                        return await _generate_section_in_blocks(
                            self.section_generator,
                            instruction_payload,
                            evidence,
                            work_item,
                            whole_section=self.section_whole_generation,
                            review_notices=review_notices,
                            scope=invocation.scope,
                            run_context=task_context,
                            thinking_request=ThinkingRequest(
                                operation="section_generation",
                                complexity="standard",
                                attempt=0,
                                configured_budget_cap=self._analysis_thinking_budget_cap,
                                thinking_enabled=self._analysis_thinking_enabled,
                                reasoning_effort=self._planner_reasoning_effort,
                            ),
                        )

                    async def recover(
                        repair: Mapping[str, Any], task_context: RunContext
                    ) -> SectionDecision:
                        if self.section_recovery is None:
                            raise ReportingError(
                                "report_section_recovery_missing", "章节恢复生成器未配置。"
                            )
                        diagnostic = repair.get("diagnostic")
                        recovery_diagnostic = (
                            dict(diagnostic)
                            if isinstance(diagnostic, Mapping)
                            else {"message": "章节重试"}
                        )
                        # recovery 只允许复用本进程、本次执行已经过 SHA 校验的 bundle。
                        # durable replay 会重新读取并验证证据；若闭包对象不存在必须失败关闭，
                        # 禁止从持久化 repair 中反序列化正文绕过当前文件身份校验。
                        if validated_evidence is None:
                            raise ReportingError(
                                "report_section_recovery_evidence_missing",
                                "章节恢复缺少当前执行已验证的证据对象。",
                            )
                        review_notices.clear()
                        return await _generate_section_in_blocks(
                            self.section_recovery,
                            instruction_payload,
                            validated_evidence,
                            work_item,
                            whole_section=self.section_whole_generation,
                            review_notices=review_notices,
                            scope=invocation.scope,
                            run_context=task_context,
                            thinking_request=ThinkingRequest(
                                operation="section_generation",
                                complexity="standard",
                                attempt=1,
                                failure_kind=_section_recovery_failure_kind(recovery_diagnostic),
                                configured_budget_cap=self._analysis_thinking_budget_cap,
                                thinking_enabled=self._analysis_thinking_enabled,
                                reasoning_effort=self._planner_reasoning_effort,
                            ),
                            recovery=recovery_diagnostic,
                        )

                    async def render(
                        decision: RenderSectionDecision, task_context: RunContext
                    ) -> Mapping[str, Any]:
                        return await toolkit.render_report_section(
                            decision.section_code,
                            [
                                item.model_dump(mode="json", by_alias=True)
                                for item in decision.blocks
                            ],
                            [
                                item.model_dump(mode="json", by_alias=True)
                                for item in decision.claims
                            ],
                            run_context=task_context,
                            review_warnings=[
                                notice for block in decision.blocks
                                for notice in review_notices.get(block.block_id, ())
                            ],
                        )

                    async def rework(
                        decision: AnalysisReworkDecision, task_context: RunContext
                    ) -> Mapping[str, Any]:
                        return await toolkit.request_analysis_rework(
                            list(decision.analysis_ids),
                            decision.reason,
                            list(decision.missing_evidence),
                            run_context=task_context,
                        )

                    return (
                        await SectionWorkflow(
                            read_evidence=read_evidence,
                            generate=generate,
                            recover=recover if self.section_recovery is not None else None,
                            render=render,
                            rework=rework,
                        ).run(work_item, invocation.run_context)
                    ).decision

                receipt = await self.task_runner.run(
                    task_scope,
                    parent_run_id=str(run_context.run_id or ""),
                    executor=execute_fixed_section,
                )
                trace_metrics = self._trace_metrics_from_receipt(receipt)
                identity = await self._phase_artifact_from_receipt(
                    scope["threadId"],
                    receipt,
                    (section_output_path, rework_request_path),
                )
                if identity.path == rework_request_path:
                    request = cast(
                        AnalysisReworkRequest,
                        await self._read_identity_model(
                            scope["threadId"], identity, AnalysisReworkRequest
                        ),
                    )
                    if request.section_code != work_item.section_code:
                        raise ReportingError(
                            "report_analysis_rework_invalid",
                            "分析补证请求没有绑定当前章节。",
                        )
                    checkpoint = self._replace_trace(
                        checkpoint,
                        task_id,
                        status="rework",
                        artifact_file=identity,
                        retry_reason=request.reason,
                        **trace_metrics,
                    )
                    checkpoint = self._update_reporting_checkpoint(
                        checkpoint,
                        files=self._merge_checkpoint_files(checkpoint.files, identity),
                    )
                    await self._persist_reporting_checkpoint(run_context, checkpoint)
                    return checkpoint, None, request

                artifact = cast(
                    SectionArtifact,
                    await self._read_identity_model(scope["threadId"], identity, SectionArtifact),
                )
                if artifact.section_code != work_item.section_code:
                    raise ReportingError(
                        "report_section_artifact_invalid",
                        "独立章节产物没有绑定当前 sectionCode。",
                    )
                validate_report_draft_blocks(
                    artifact.blocks,
                    expected_section_title=work_item.title,
                )
                checkpoint = self._replace_trace(
                    checkpoint,
                    task_id,
                    status="completed",
                    artifact_file=identity,
                    pointer_receipt_ids=work_item.profile_read_receipt_ids,
                    **trace_metrics,
                )
                completed = tuple(
                    item
                    for item in checkpoint.completed_sections
                    if item.section_code != work_item.section_code
                ) + (
                    CompletedSection(
                        sectionCode=work_item.section_code,
                        workItemHash=work_item_hash,
                        artifactFile=identity,
                        retryCount=sum(
                            1
                            for item in checkpoint.trace
                            if item.phase == "section"
                            and item.section_code == work_item.section_code
                            and item.status in {"failed", "rework"}
                        ),
                    ),
                )
                checkpoint = self._update_reporting_checkpoint(
                    checkpoint,
                    phase="analysis",
                    completed_sections=completed,
                    pending_sections=tuple(
                        item
                        for item in checkpoint.pending_sections
                        if item != work_item.section_code
                    ),
                    last_error=None,
                    files=self._merge_checkpoint_files(checkpoint.files, identity),
                )
                await self._apply_durable_command(
                    run_context,
                    ReportingCommand(
                        name="complete_section",
                        commandId=f"section-complete:{revision}:{work_item.section_code}:{identity.sha256}",
                        payload={
                            "sectionCode": work_item.section_code,
                            "analysisIds": list(work_item.analysis_ids),
                            "workItemHash": work_item_hash,
                            "revision": revision,
                            "artifactFile": identity.model_dump(mode="json", by_alias=True),
                        },
                    ),
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
                return checkpoint, artifact, None
            except Exception as error:
                last_error = error
                code = (
                    error.code
                    if isinstance(error, ReportingError)
                    else "report_section_phase_failed"
                )
                if isinstance(error, ReportingError) and error.code == (
                    "report_worker_terminal_tool_missing"
                ):
                    error = ReportingError(
                        error.code,
                        f"章节 {work_item.section_code} 未提交 render_report_section 或 "
                        "request_analysis_rework。",
                        details={
                            **(error.details if isinstance(error.details, Mapping) else {}),
                            "sectionCode": work_item.section_code,
                            "attempt": attempt + 1,
                        },
                    )
                    last_error = error
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
                        "phase": "section",
                        "code": code,
                        "message": message or "独立章节阶段失败。",
                        "sectionCode": work_item.section_code,
                        "retryReason": code,
                        "details": dict(error.details)
                        if isinstance(error, ReportingError) and isinstance(error.details, Mapping)
                        else None,
                    },
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
                if code in {
                    "report_section_completion_conflict",
                    "report_section_start_conflict",
                } or fresh_attempt_futile(error):
                    # 与分析项、可视化章节同一口径：基础设施/部署配置类失败不再开新 attempt。
                    raise error
        assert last_error is not None
        raise last_error

    async def _registered_number_contents(
        self, thread_id: str, checkpoint: ReportingCheckpoint
    ) -> tuple[str, ...]:
        """冻结事实与补证 evidence 原文，供图注等装配期文本核对数值。

        与章节正文核对同源（全部 evidence 文本文件）；非 UTF-8 文件本身无法登记数值，
        跳过即可。任一文件不可读时返回空元组：依据不全时无法判断数值是否登记，不做替换。
        """

        identities = list(checkpoint.deterministic_fact_files.values())
        if checkpoint.evidence_manifest is not None:
            identities.extend(
                identity
                for item in checkpoint.evidence_manifest.evidence
                for identity in item.evidence_files
            )
            # 作图数据（chart-input/v1）与事实同源；图表行值会进入图注与正文解读，
            # 不并入核对依据会把逐行数值误判为无依据（numeric_text 识别该 schema）。
            identities.extend(
                identity
                for chart in checkpoint.evidence_manifest.charts
                for identity in chart.plot_data_files
            )
        contents: list[str] = []
        seen: set[str] = set()
        for identity in identities:
            if identity.path in seen:
                continue
            seen.add(identity.path)
            try:
                raw = await self._read_identity_bytes(thread_id, identity, max_bytes=16 * 1024 * 1024)
            except Exception as error:  # noqa: BLE001 - 依据不全时只放弃核对
                loguru_logger.warning(
                    "report_chart_text_verification_skipped path={} error_type={}",
                    identity.path,
                    type(error).__name__,
                )
                return ()
            try:
                contents.append(raw.decode("utf-8"))
            except UnicodeDecodeError:
                continue
        return tuple(contents)

    async def _build_server_tables(
        self,
        run_context: RunContext,
        *,
        checkpoint: ReportingCheckpoint,
        outline: Any,
    ) -> tuple[tuple[ReportServerTable, ...], tuple[TableTraceV1, ...], dict[str, tuple[str, str]], dict[str, tuple[Any, str | None]]]:
        """从冻结确定性 facts 生成服务端结构化表格（B2，计划 4.2）。

        规则：宽表按最多五个数值列拆分；
        表格追加到第一个引用该 analysis 的批准章节尾部。bundle 不可读或
        生成失败按软告警跳过（语义缺失软告警，不阻断发布），但已生成的
        表格与其 trace 严格同源。

        返回 (tables, traces, factId→(analysisId, jsonPointer) 目录, 冻结显示值)——
        目录供 B6 正文 subject 绑定构造复用（不重复读 bundle）。
        """

        from ...trace.fact_index import (
            fact_binding_records,
            fact_entry_from_pointer,
            fact_pointer,
            frozen_fact_content,
            merge_binding_records,
        )

        scope = self._scope(run_context)
        thread_id = scope["threadId"]
        section_by_analysis: dict[str, str] = {}
        for section in outline.sections:
            for analysis_id in section.analysis_ids:
                section_by_analysis.setdefault(analysis_id, section.code)
        tables: list[ReportServerTable] = []
        traces: list[TableTraceV1] = []
        table_signatures: set[str] = set()
        fact_directory: dict[str, tuple[str, str]] = {}
        fact_values: dict[str, tuple[Any, str | None]] = {}
        fact_documents: dict[str, dict[str, Any]] = {}
        ambiguous_fact_ids: set[str] = set()
        try:
            # 表头指标名的兜底来源；Profile 不可读时表格照常生成（显示字段名）。
            metric_descriptions = {
                metric.code: metric.description
                for metric in self._profile(run_context).metrics
                if metric.description
            }
        except ReportingError:
            metric_descriptions = {}
        for analysis_id, identity in checkpoint.deterministic_fact_files.items():
            try:
                raw = await self._read_identity_bytes(
                    thread_id, identity, max_bytes=16 * 1024 * 1024
                )
                bundle = DeterministicAnalysisBundle.model_validate_json(raw)
                document = bundle.model_dump(mode="json", by_alias=True)
                binding_records = fact_binding_records(bundle)
                for fact in (
                    *bundle.metrics,
                    *bundle.comparisons,
                    *bundle.derived_metrics,
                    *bundle.reconciliations,
                    *bundle.correlation_details,
                ):
                    if fact.fact_id:
                        pointer = fact_pointer(bundle, fact.fact_id)
                        if pointer:
                            frozen_fact = fact.model_dump(mode="json", by_alias=True)
                            binding_record = binding_records[fact.fact_id]
                            if fact.fact_id in ambiguous_fact_ids:
                                continue
                            if (fact.fact_id in fact_documents
                                    and merge_binding_records(fact_documents[fact.fact_id], binding_record) is None):
                                # 兼容旧快照：同 ID 不同内容不能按文件顺序选择来源。
                                ambiguous_fact_ids.add(fact.fact_id)
                                fact_directory.pop(fact.fact_id, None)
                                fact_values.pop(fact.fact_id, None)
                                loguru_logger.warning(
                                    "report_claim_fact_binding_omitted fact_id={} reason=conflicting_identity",
                                    fact.fact_id,
                                )
                                continue
                            fact_documents[fact.fact_id] = binding_record
                            fact_directory[fact.fact_id] = (analysis_id, pointer)
                            fact_values[fact.fact_id] = (
                                fact_display_value(frozen_fact),
                                fact_display_unit(frozen_fact),
                            )
                section_code = section_by_analysis.get(analysis_id)
                if section_code is None:
                    continue
                fact_resource = derive_resource_id(identity.path)
                built = build_analysis_tables(
                    bundle, fact_file_resource_id=fact_resource,
                    dataset_contexts=self._state(run_context).get("report_analysis_data_context", ()),
                    metric_descriptions=metric_descriptions,
                )
                for trace, markdown in built:
                    # 仅折叠行列及完整冻结事实均一致的表；金额相等不足以认定重复。
                    # 不同分析对同一数据集同一指标各自冻结出内容完全相同、仅 factId 不同的事实，
                    # 附录会出现两张一模一样的表：比较时不计 factId。
                    signature = json.dumps({
                        "rows": trace.row_keys,
                        "columns": trace.column_keys,
                        "facts": [
                            {key: value for key, value in frozen_fact_content(
                                fact_entry_from_pointer(document, ref.json_pointer)[1]).items()
                             if key != "factId"}
                            for cell in trace.cells for ref in cell.fact_refs
                        ],
                    }, sort_keys=True, ensure_ascii=False)
                    if signature in table_signatures:
                        continue
                    table_signatures.add(signature)
                    tables.append(
                        ReportServerTable(sectionCode=section_code, markdown=markdown)
                    )
                    traces.append(trace)
            except (ReportingError, ValidationError, ValueError) as error:
                loguru_logger.warning(
                    "report_server_table_skipped analysis_id={} error={}",
                    analysis_id,
                    error,
                )
        return tuple(tables), tuple(traces), fact_directory, fact_values

    async def _finalize_reporting_sections(
        self,
        run_context: RunContext,
        *,
        checkpoint: ReportingCheckpoint,
        revision: int,
        markdown_path: str,
        manifest_path: str,
        lineage: tuple[DatasetLineage, ...],
        citation_bindings: tuple[Citation, ...],
        source_warnings: tuple[SourceWarning, ...],
    ) -> tuple[ReportingCheckpoint, ReportArtifactManifest]:
        if checkpoint.evidence_manifest is None:
            raise ReportingError("report_analysis_artifact_missing", "Finalize 缺少冻结分析产物。")
        outline = _frozen_outline(self._state(run_context))
        scope = self._scope(run_context)
        narrative_section_finding_ids: dict[str, tuple[str, ...]] = {}
        narrative_section_grouping_reasons: dict[str, str] = {}
        if checkpoint.narrative_outline_file is not None:
            try:
                narrative = await self._read_identity_model(
                    scope["threadId"], checkpoint.narrative_outline_file, NarrativeOutline
                )
                narrative_section_finding_ids = {
                    item.code: item.finding_ids for item in narrative.sections
                }
                narrative_section_grouping_reasons = {
                    item.code: item.grouping_reason for item in narrative.sections
                }
            except (ReportingError, ValidationError) as error:
                loguru_logger.warning("report_narrative_manifest_mapping_unavailable error={}", error)
        completed = {item.section_code: item for item in checkpoint.completed_sections}
        if set(completed) != {item.code for item in outline.sections}:
            raise ReportingError("report_section_artifact_missing", "Finalize 缺少完整章节产物。")
        section_artifacts: list[SectionArtifact] = []
        for section in outline.sections:
            artifact = cast(
                SectionArtifact,
                await self._read_identity_model(
                    scope["threadId"], completed[section.code].artifact_file, SectionArtifact
                ),
            )
            if artifact.section_code != section.code:
                raise ReportingError(
                    "report_section_artifact_invalid", "章节产物顺序或 sectionCode 已变化。"
                )
            section_artifacts.append(artifact)

        server_tables, server_table_traces, fact_directory, fact_values = await self._build_server_tables(
            run_context, checkpoint=checkpoint, outline=outline
        )
        section_artifacts = list(bind_local_claim_values(section_artifacts, fact_values))
        draft = ReportDraft(
            sections=tuple(
                ReportDraftSection(sectionCode=item.section_code, blocks=item.blocks)
                for item in section_artifacts
            )
        )
        chart_inputs: list[ReportChartInput] = []
        destination_by_chart: dict[str, str] = {}
        report_parent = PurePosixPath(markdown_path).parent
        # 图注标题/替代文字由模型登记，装配时直接进入正文；与正文数值同规则核对。
        number_contents = await self._registered_number_contents(scope["threadId"], checkpoint)
        for index, chart in enumerate(checkpoint.evidence_manifest.charts, start=1):
            suffix = PurePosixPath(chart.source_file.path).suffix.lower()
            if suffix not in {".png", ".jpg", ".jpeg"}:
                raise ReportingError(
                    "report_analysis_chart_invalid", "冻结图表必须是 PNG 或 JPEG。"
                )
            file_name = f"chart-{index:03d}{suffix}"
            destination_by_chart[chart.chart_id] = report_parent.joinpath(file_name).as_posix()
            chart_inputs.append(
                ReportChartInput(
                    chartId=chart.chart_id,
                    fileName=file_name,
                    title=_verified_caption(chart.title, number_contents),
                    altText=_verified_caption(chart.alt_text, number_contents),
                    citationIds=chart.citation_ids,
                )
            )
        rendered = assemble_report_markdown(
            draft,
            expected_title=outline.title,
            markdown_path=markdown_path,
            sections=tuple(
                ReportSectionDefinition(
                    code=item.code,
                    sectionNumber=item.section_number,
                    title=item.title,
                    protocolMarker=True,
                    analysisIds=item.analysis_ids,
                )
                for item in outline.sections
            ),
            citation_ids=tuple(item.citation_id for item in citation_bindings),
            charts=tuple(chart_inputs),
            require_table=False,
            server_tables=server_tables,
            claim_values={
                (artifact.section_code, claim.claim_id): fact_values[claim.fact_ids[0]]
                for artifact in section_artifacts for claim in artifact.claims
                if claim.fact_ids and claim.fact_ids[0] in fact_values
            },
        )
        await self.report_tools.complete_document_heading_numbers(
            str(self._workflow_result(self._state(run_context))["jobId"]),
            [item.model_dump(mode="json", by_alias=True) for item in rendered.heading_numbers],
            run_context=self._tool_context(run_context),
        )
        referenced_chart_ids = tuple(
            dict.fromkeys(
                chart_id
                for section in section_artifacts
                for block in section.blocks
                for chart_id in block.chart_ids
            )
        )
        chart_by_id = {item.chart_id: item for item in checkpoint.evidence_manifest.charts}
        chart_files: list[FileIdentity] = []
        interactive_files: list[FileIdentity] = []
        interactive_charts: dict[str, str] = {}
        plot_data_files: list[FileIdentity] = []
        plot_files_by_chart: dict[str, list[FileIdentity]] = {}
        for chart_id in referenced_chart_ids:
            chart = chart_by_id[chart_id]
            content = await self._read_identity_bytes(
                scope["threadId"], chart.source_file, max_bytes=10 * 1024 * 1024
            )
            chart_files.append(
                await self._write_immutable_artifact(
                    scope["threadId"], destination_by_chart[chart_id], content
                )
            )
            # B3：作图数据（chart-input/v1）与图片一起归档进 revision 目录，
            # 供追溯索引登记 ChartTraceV1；不进交付 manifest（非渲染产物）。
            for plot_index, plot_identity in enumerate(chart.plot_data_files, start=1):
                plot_content = await self._read_identity_bytes(
                    scope["threadId"], plot_identity, max_bytes=8 * 1024 * 1024
                )
                image_stem = PurePosixPath(destination_by_chart[chart_id]).stem
                plot_destination = report_parent.joinpath(
                    f"{image_stem}--{plot_index}.chart-input.json"
                ).as_posix()
                plot_data_files.append(
                    await self._write_immutable_artifact(
                        scope["threadId"], plot_destination, plot_content
                    )
                )
                plot_files_by_chart.setdefault(chart_id, []).append(plot_data_files[-1])
            if chart.interactive_file is not None:
                spec_content = await self._read_identity_bytes(
                    scope["threadId"], chart.interactive_file, max_bytes=2 * 1024 * 1024
                )
                image_path = destination_by_chart[chart_id]
                spec_path = _archived_interactive_path(image_path)
                interactive_files.append(
                    await self._write_immutable_artifact(scope["threadId"], spec_path, spec_content)
                )
                interactive_charts[image_path] = spec_path
        if tuple(item.path for item in chart_files) != rendered.chart_paths:
            raise ReportingError(
                "report_draft_chart_path_invalid", "服务端图表归档路径与 Markdown 装配结果不一致。"
            )
        # B3：图片由登记的同一份作图数据生成——ChartTraceV1 绑定归档后的
        # 图片与作图数据文件及数据集来源；无作图数据或数据集映射的图不伪造
        # trace（读取层按"来源不足"降级，计划 G3）。
        citation_dataset_by_id = {
            item.citation_id: item.dataset_id for item in citation_bindings
        }
        chart_traces: list[ChartTraceV1] = []
        chart_trace_files: list[FileIdentity] = []
        for chart_id in referenced_chart_ids:
            chart = chart_by_id[chart_id]
            plot_files = plot_files_by_chart.get(chart_id)
            dataset_ids = tuple(
                dict.fromkeys(
                    citation_dataset_by_id[citation_id]
                    for citation_id in chart.citation_ids
                    if citation_id in citation_dataset_by_id
                )
            )
            if not plot_files or not dataset_ids:
                continue
            chart_traces.append(
                ChartTraceV1(
                    chartId=chart_id,
                    imageFileResourceId=derive_resource_id(
                        destination_by_chart[chart_id]
                    ),
                    plotDataFileResourceIds=tuple(
                        derive_resource_id(item.path) for item in plot_files
                    ),
                    datasetIds=dataset_ids,
                    transformNotes=(
                        "作图数据由服务端 chart-input/v1 物化，图片以同一份数据生成",
                    ),
                )
            )
            chart_trace_files.extend(plot_files)
        markdown_file = await self._write_immutable_artifact(
            scope["threadId"], markdown_path, rendered.markdown.encode("utf-8")
        )
        accepted_artifacts = [
            markdown_file.model_dump(mode="json", by_alias=True),
            *(item.model_dump(mode="json", by_alias=True) for item in chart_files),
            *(item.model_dump(mode="json", by_alias=True) for item in interactive_files),
        ]
        analysis_task_id = next(
            (
                item.task_id
                for item in reversed(checkpoint.trace)
                if item.phase == "analysis" and item.status == "completed" and item.task_id
            ),
            None,
        )
        if analysis_task_id is None:
            raise ReportingError(
                "report_checkpoint_invalid", "Checkpoint 缺少已完成 analysis task。"
            )
        trace_handles = tuple(
            DatasetHandle.from_state(item)
            for item in self._workflow_result(self._state(run_context)).get(
                "datasets", ()
            )
        )
        # B2：把冻结确定性事实文件登记进追溯索引，供 Editor FactRef 查询解析。
        trace_fact_files: dict[str, ArtifactFile] = {}
        for analysis_id, identity in checkpoint.deterministic_fact_files.items():
            trace_fact_files[analysis_id] = ArtifactFile(
                path=identity.path,
                mediaType="application/json",
                size=identity.size,
                sha256=identity.sha256,
            )
        # B6：正文 claim 冻结为 subject 绑定（定位锚 = [[claim:id]] 协议标记）。
        subject_bindings = build_claim_subject_bindings(
            section_artifacts,
            fact_directory,
            {
                analysis_id: derive_resource_id(item.path)
                for analysis_id, item in trace_fact_files.items()
            },
        )
        used_table_source_ids = {
            operand.file_resource_id
            for subject in subject_bindings
            if subject.number_reference is not None
            and subject.number_reference.table_derivation is not None
            for operand in subject.number_reference.table_derivation.operands
        }
        # 来源身份独立于计算记录；保留重复项供索引识别冲突身份。
        table_source_files = tuple(
            identity
            for entry in (
                checkpoint.evidence_manifest.evidence
                if checkpoint.evidence_manifest is not None else ()
            )
            for identity in entry.evidence_files
            if derive_resource_id(identity.path) in used_table_source_ids
        )
        # B4：补充分析计算记录（ComputationRecordV1）与脚本文件进索引。
        computation_records, computation_files = _evidence_and_computation_layers(
            checkpoint.evidence_manifest
        )
        manifest = await self._build_and_write_artifact_manifest(
            manifest_path,
            accepted_artifacts=accepted_artifacts,
            handles=trace_handles,
            fact_files=trace_fact_files,
            server_table_traces=server_table_traces,
            chart_trace_files=(*chart_files, *interactive_files, *chart_trace_files),
            chart_traces=tuple(chart_traces),
            computation_files=tuple(computation_files),
            computations=tuple(computation_records),
            table_source_files=table_source_files,
            subject_bindings=subject_bindings,
            review_notices=(tuple(
                notice.model_copy(update={"section_id": artifact.section_code})
                for artifact in section_artifacts for block in artifact.blocks
                for notice in block.review_notices or ()
            ) if all(block.review_notices is not None
                     for artifact in section_artifacts for block in artifact.blocks) else None),
            interactive_charts=interactive_charts,
            markdown_path=markdown_path,
            lineage=lineage,
            source_warnings=source_warnings,
            revision=revision,
            task_key=analysis_task_id,
            section_numbers=rendered.section_numbers,
            heading_numbers=rendered.heading_numbers,
            section_finding_ids=narrative_section_finding_ids,
            section_grouping_reasons=narrative_section_grouping_reasons,
            run_context=run_context,
        )
        if not _accepted_artifacts_match_manifest(manifest, manifest_path, accepted_artifacts):
            raise ReportingError(
                "report_artifact_acceptance_incomplete",
                "服务端装配产物未精确绑定 Markdown 和正文引用图表。",
            )
        manifest_file = FileIdentity.model_validate(
            await self.workspace_service.ahash_file(scope["threadId"], manifest_path)
        )
        trace_index_identity = None
        if manifest.trace_index is not None:
            trace_index_identity = FileIdentity.model_validate(
                await self.workspace_service.ahash_file(
                    scope["threadId"], trace_index_path_for(manifest_path)
                )
            )
        warning_values = tuple((*checkpoint.warnings, *rendered.warnings)[-500:])
        checkpoint = self._update_reporting_checkpoint(
            checkpoint,
            phase="completed",
            warnings=warning_values,
            last_error=None,
            files=self._merge_checkpoint_files(
                checkpoint.files,
                markdown_file,
                *chart_files,
                *interactive_files,
                manifest_file,
                *((trace_index_identity,) if trace_index_identity is not None else ()),
            ),
            trace=(
                *checkpoint.trace,
                ContextTrace(
                    phase="finalize",
                    status="completed",
                    artifactFile=markdown_file,
                    projectedContextBytes=0,
                ),
            ),
        )
        await self._apply_durable_command(
            run_context,
            ReportingCommand(
                name="complete",
                commandId=f"report-complete:{revision}:{manifest_file.sha256}",
                payload={
                    "markdown": markdown_file.model_dump(mode="json", by_alias=True),
                    "manifest": manifest_file.model_dump(mode="json", by_alias=True),
                    "charts": [item.model_dump(mode="json", by_alias=True) for item in chart_files],
                },
            ),
        )
        await self._persist_reporting_checkpoint(run_context, checkpoint)
        return checkpoint, manifest

    async def _build_reporting_artifact(
        self,
        run_context: RunContext,
        *,
        analysis_ids: Sequence[str],
        detailed_plan: DetailedAnalysisPlan,
        fact_files: Mapping[str, FileIdentity],
        citation_bindings: tuple[Citation, ...],
        section_codes: Sequence[str] | None = None,
    ) -> AnalysisArtifact:
        """从本次运行的 durable analysisItems 和章节图表确定性构造分析产物。

        章节 Agent 只能消费这里派生的 facts/evidence/charts；模型没有第二个全局登记
        入口。Dataset/evidence 文件身份漂移由既有工具记录为 warning，不改变发布路径。
        """
        scope = self._scope(run_context)
        durable = await self.state_repository.get(str(run_context.run_id or scope["externalRunId"]))
        payload = durable.payload if durable is not None else {}
        raw_items = payload.get("analysisItems", {})
        if not isinstance(raw_items, Mapping):
            raise ReportingError("report_analysis_evidence_invalid", "durable analysisItems 无效。")
        selected_ids = tuple(analysis_ids)
        evidence: list[AnalysisEvidence] = []
        fact_bundles: dict[str, Mapping[str, Any]] = {}
        warnings: list[str] = [
            str(item.get("message"))
            for item in payload.get("warnings", ())
            if isinstance(item, Mapping) and item.get("message")
        ]
        plans_by_id = {item.analysis_id: item for item in detailed_plan.analyses}
        for analysis_id in selected_ids:
            raw_item = raw_items.get(analysis_id)
            if not isinstance(raw_item, Mapping):
                raise ReportingError(
                    "report_analysis_evidence_incomplete", f"analysisId {analysis_id} 尚未完成。"
                )
            # 兼容修复前已写入 durable state 的超长/重复告警；完整证据文件仍保留。
            normalized_item = dict(raw_item)
            normalized_warnings, _ = normalize_analysis_warnings(
                normalized_item.get("warnings", ())
            )
            normalized_item["warnings"] = normalized_warnings
            evidence.append(AnalysisEvidence.model_validate(normalized_item))
            try:
                fact = await self._read_identity_model(
                    scope["threadId"], fact_files[analysis_id], DeterministicAnalysisBundle
                )
            except ReportingError as error:
                if error.code != "report_phase_artifact_changed":
                    raise
                # facts 身份漂移只作质量告警；仍读取当前完整 JSON，缺失或结构损坏继续失败。
                warnings.append(
                    f"analysisId {analysis_id} 的 facts 文件身份或 SHA-256 已变化，已按当前内容继续发布。"
                )
                content = await self.workspace_service.read_limited_regular_file(
                    scope["threadId"],
                    fact_files[analysis_id].path,
                    max_bytes=10 * 1024 * 1024,
                )
                try:
                    fact = DeterministicAnalysisBundle.model_validate_json(content)
                except ValidationError as validation_error:
                    raise ReportingError(
                        "report_phase_artifact_invalid", "固定 facts 文件结构无效。"
                    ) from validation_error
            fact_bundles[analysis_id] = fact.model_dump(mode="json", by_alias=True)

        dataset_ids = tuple(
            dict.fromkeys(dataset_id for item in evidence for dataset_id in item.dataset_ids)
        )
        plans = {
            analysis_id: _reporting_detailed_analysis_plan(
                detailed_plan, analysis_ids=(analysis_id,)
            )["analyses"][0]
            for analysis_id in selected_ids
            if analysis_id in plans_by_id
        }
        dataset_semantics, metric_definitions, findings = _finalize_semantic_catalog(
            analysis_plans=plans,
            fact_bundles=fact_bundles,
            dataset_ids=dataset_ids,
        )
        chart_values: list[AnalysisChart] = []
        visualization_sections = payload.get("visualizationSections", {})
        if isinstance(visualization_sections, Mapping):
            selected_section_codes = set(section_codes) if section_codes is not None else None
            outline = _frozen_outline(self._state(run_context))
            ordered_sections = tuple(
                section
                for section in outline.sections
                if selected_section_codes is None or section.code in selected_section_codes
            )
            file_by_path: dict[str, Mapping[str, Any]] = {}
            interactive_by_path: dict[str, Mapping[str, Any]] = {}
            receipt_by_path: dict[str, Mapping[str, Any]] = {}
            plot_data_by_chart: dict[str, Mapping[str, Any]] = {}
            for section in ordered_sections:
                section_payload = visualization_sections.get(section.code)
                if not isinstance(section_payload, Mapping):
                    continue
                for raw_receipt in section_payload.get("visualReceipts", ()):
                    if isinstance(raw_receipt, Mapping) and isinstance(
                        raw_receipt.get("sourcePath"), str
                    ):
                        receipt_by_path[raw_receipt["sourcePath"]] = raw_receipt
                for raw_file in section_payload.get("files", ()):
                    if isinstance(raw_file, Mapping) and isinstance(raw_file.get("path"), str):
                        file_by_path[raw_file["path"]] = raw_file
                for raw_file in section_payload.get("interactiveFiles", ()):
                    if isinstance(raw_file, Mapping) and isinstance(raw_file.get("path"), str):
                        interactive_by_path[raw_file["path"]] = raw_file
                for raw_plot in section_payload.get("plotDataFiles", ()):
                    if isinstance(raw_plot, Mapping) and isinstance(raw_plot.get("chartId"), str):
                        plot_data_by_chart[raw_plot["chartId"]] = raw_plot
            for section in ordered_sections:
                section_payload = visualization_sections.get(section.code)
                if not isinstance(section_payload, Mapping):
                    continue
                for raw_chart in section_payload.get("charts", ()):
                    if not isinstance(raw_chart, Mapping):
                        continue
                    source_path = raw_chart.get("sourcePath")
                    if not isinstance(source_path, str):
                        continue
                    source_file = file_by_path.get(source_path)
                    if source_file is None:
                        continue
                    chart_values.append(
                        _analysis_chart_from_registration(
                            raw_chart,
                            source_file,
                            interactive_by_path.get(str(raw_chart.get("interactivePath") or "")),
                            receipt_by_path.get(source_path),
                            plot_data=plot_data_by_chart.get(str(raw_chart.get("chartId") or "")),
                        )
                    )
        warnings.extend(
            warning
            for item in evidence
            for warning in item.warnings
            if isinstance(warning, str) and warning
        )
        warnings.extend(
            item["message"]
            for item in findings
            if isinstance(item, Mapping) and item.get("message")
        )
        receipts = tuple(
            ProfileReadReceipt.model_validate(item)
            for item in payload.get("profileReadReceipts", ())
            if isinstance(item, Mapping)
        )
        report_goal = self._envelope(run_context).report_goal
        questions = tuple(item.management_question for item in detailed_plan.analyses)
        outline = _frozen_outline(self._state(run_context))
        selected_id_set = set(selected_ids)
        ordered_analysis_ids = tuple(
            analysis_id
            for section in outline.sections
            for analysis_id in section.analysis_ids
            if analysis_id in selected_id_set
        )
        ordered_analysis_ids += tuple(
            analysis_id for analysis_id in selected_ids if analysis_id not in ordered_analysis_ids
        )
        evidence_by_id = {item.analysis_id: item for item in evidence}
        summary = _bounded_executive_summary(
            [
                evidence_by_id[analysis_id].summary
                for analysis_id in ordered_analysis_ids
                if analysis_id in evidence_by_id
            ]
        )
        return AnalysisArtifact(
            reportBrief=ReportBrief(
                objective=report_goal,
                executiveSummary=summary,
                managementQuestions=questions or (report_goal,),
                warnings=tuple(dict.fromkeys(warnings))[-500:],
            ),
            evidenceManifest=AnalysisEvidenceManifest(
                evidence=tuple(evidence),
                metricDefinitions=tuple(
                    MetricDefinition.model_validate(item) for item in metric_definitions
                ),
                charts=tuple(chart_values),
                datasetSemantics=tuple(
                    AnalysisDatasetSemantics.model_validate(item) for item in dataset_semantics
                ),
                warnings=tuple(dict.fromkeys(warnings))[-500:],
            ),
            profileReadReceipts=receipts,
            profileReadReceiptIds=tuple(item.receipt_id for item in receipts),
        )
