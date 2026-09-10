# mypy: disable-error-code="attr-defined"
# 运行时由 facade 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。
from __future__ import annotations

import re

from loguru import logger as loguru_logger

from ....task_execution import (
    TASK_EXECUTION_CONTEXT_TOKEN_LIMIT,
    TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
)
from ...delivery.draft_v1 import ReportDraftBlock
from ...hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
from ...model_policy import resolve_reporting_input_token_hard_cap
from ...phase import reporting_model_route_from_run_context
from ...structured_output import ReportingStructuredOutputExecutor
from ...tools import build_reporting_tools
from ..checkpoint import ChartVisualInspectionReceipt, CheckpointError, ProfileReadReceipt
from ..execution import ReportingTaskInvocation
from .analysis import (
    _finalize_semantic_catalog,
    _reporting_detailed_analysis_plan,
    _run_bounded,
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
    Awaitable,
    Callable,
    Citation,
    CompletedSection,
    ContextTrace,
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
    assemble_report_markdown,
    build_report_phase_acceptance_contract,
    cast,
    hashlib,
    json,
    payload_sha256,
    reporting_phase_task_key,
    validate_report_draft_blocks,
)
from .phase_models import (
    AnalysisReworkDecision,
    RenderSectionDecision,
    RenderSectionPlan,
    SectionBlockContent,
    SectionDecision,
    SectionEvidenceBundle,
    SectionPlanOutput,
)
from .publication import _accepted_artifacts_match_manifest
from .section_workflow import SectionWorkflow

_SECTION_BLOCK_DEFAULT_INPUT_TOKEN_BUDGET = 64 * 1024
_SECTION_BLOCK_PAYLOAD_TOKEN_NUMERATOR = 3
_SECTION_BLOCK_PAYLOAD_TOKEN_DENOMINATOR = 4
_SECTION_BLOCK_EVIDENCE_TOKEN_DIVISOR = 2
_SECTION_BLOCK_TEXT_CONTEXT_LINES = 2
_SECTION_BLOCK_MAX_RELEVANCE_TERMS = 128
_SECTION_BLOCK_MIN_FILE_TOKENS = 128
_SECTION_BLOCK_MAX_PROJECTION_ATTEMPTS = 16
_SECTION_BLOCK_OMISSION_MARKER = "[...已省略与当前正文块无关的证据内容...]"
_MAX_EXECUTIVE_SUMMARY_CHARS = 8_000
_EXECUTIVE_SUMMARY_SEPARATOR = "；"
_EXECUTIVE_SUMMARY_ELLIPSIS = "…"


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
    return resolve_reporting_input_token_hard_cap(
        configured_input_token_cap=configured_cap,
        model_id=model_id if isinstance(model_id, str) else None,
        output_token_reserve=TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
        absolute_input_token_cap=(
            TASK_EXECUTION_CONTEXT_TOKEN_LIMIT - TASK_EXECUTION_OUTPUT_TOKEN_RESERVE
        ),
    )


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _section_block_evidence_token_budget(
    agent: Any,
    base_payload: Mapping[str, Any],
    *,
    file_count: int,
    run_context: RunContext,
) -> int:
    input_budget = _section_block_input_token_budget(agent, run_context)
    base_tokens = _estimated_section_tokens(_json_text(base_payload))
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
        for key, nested_value in value.items():
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


async def _run_section_batches_until_rework(
    items: Sequence[Any],
    *,
    concurrency: int,
    executor: Callable[[Any], Awaitable[Any]],
) -> list[Any]:
    """每批只启动 concurrency 个章节；批内返工会阻止下一批启动。"""

    results: list[Any] = []
    for offset in range(0, len(items), concurrency):
        batch_results = await _run_bounded(
            items[offset : offset + concurrency],
            concurrency=concurrency,
            operation=executor,
        )
        results.extend(batch_results)
        if any(result[2] is not None for result in batch_results):
            break
    return results


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


def _section_stage_agent(agent: Any, output_schema: type[Any], stage: str) -> Any:
    """从现有 Reporting 生成器派生无工具、无历史的短输出阶段 Agent。"""

    if stage == "plan":
        instructions = [
            "只返回满足 output_schema 的 JSON 对象，不得返回解释、Markdown 或代码围栏。",
            "先判断证据是否足够；足够时返回 render 规划，不足时返回 rework。",
            "render 只规划必要的正文 block 和结构化 claims，不在 objective 中撰写正文。",
            "每个 claim 必须由至少一个 block 引用；只使用输入中的 metric、管理问题、citation 和 chart ID。",
            "存在 correction 时逐项修正 issues，只能使用 allowedValues，并返回完整规划。",
        ]
    else:
        instructions = [
            "只返回满足 output_schema 的 JSON 对象，不得把整个响应写成 Markdown 或代码围栏。",
            "只在 JSON 的 markdown 字段中撰写当前 block 的完整简体中文 Markdown 正文，不得生成其他 block。",
            "不得输出 H1/H2、图片语法、内部 ID、协议标记或无证据数字。",
            (
                "可使用 H3/H4、段落、列表和有报告意义的 Markdown 管道表；"
                "H3/H4 必须是不超过 40 个中文字符的短标题，并独占一个物理行。"
                "标题行后必须立即换行；有正文时，使用『### 收入分析\n\n本季度收入……』格式。"
                "禁止『### 收入分析：本季度收入……』同一行混写。"
            ),
            (
                "Markdown 的标题和正文都不得出现 citationIds、chartIds、图表文件名、"
                "HTML 标签或 <sup> 脚注；这些引用只能通过输入中的结构化字段绑定。"
            ),
            (
                "提交前逐行检查所有 ###/#### 标题。存在 correction 时只修正 issues 指向的当前 block；"
                "对 report_draft_heading_title_too_long，必须把该行重写为不超过 40 个字符的短标题，"
                "并将原标题行中的全部正文移到空行后的段落，最后返回完整 JSON 对象。"
            ),
        ]
    identifier = str(getattr(agent, "id", None) or "reporting-section-generator")
    return agent.deep_copy(
        update={
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
    )


async def _run_section_stage(
    agent: Any,
    output_schema: type[Any],
    stage: str,
    payload: Mapping[str, Any],
    *,
    scope: TaskExecutionScope,
    run_context: RunContext,
) -> Any:
    stage_agent = _section_stage_agent(agent, output_schema, stage)
    result = await ReportingStructuredOutputExecutor(stage_agent).execute(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        routing_context=run_context,
        agent_run_context=run_context,
        session_id=f"task-execution:{scope.external_run_id}:{stage}",
        user_id=scope.owner_user_id,
    )
    return result.content


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


async def _generate_section_in_blocks(
    agent: Any,
    instruction_payload: Mapping[str, Any],
    evidence: SectionEvidenceBundle,
    work_item: SectionWorkItem,
    *,
    scope: TaskExecutionScope,
    run_context: RunContext,
    recovery: Mapping[str, Any] | None = None,
) -> SectionDecision:
    """规划后串行生成正文块，限制单次模型输出的故障半径。"""

    plan_payload = {
        **instruction_payload,
        "generationStage": "plan",
        "evidenceFiles": [
            item.identity.model_dump(mode="json", by_alias=True) for item in evidence.files
        ],
        "requiredAction": (
            "证据充足时返回 1 到 12 个必要 block 的结构规划及完整 claims；"
            "block 只包含 blockId、objective、claimIds，不生成 Markdown 正文。"
        ),
    }
    if recovery is not None:
        plan_payload["recovery"] = dict(recovery)
    for plan_call in range(1, 7):
        planned = await _run_section_stage(
            agent,
            SectionPlanOutput,
            "plan",
            plan_payload,
            scope=scope,
            run_context=run_context,
        )
        if not isinstance(planned, SectionPlanOutput):
            raise ReportingError("report_phase_output_invalid", "章节规划 Agent 未返回声明的结果。")
        decision = planned.root
        if isinstance(decision, AnalysisReworkDecision):
            return decision
        if not isinstance(decision, RenderSectionPlan):
            raise ReportingError("report_phase_output_invalid", "章节规划结果类型无效。")
        if decision.section_code != work_item.section_code:
            raise ReportingError(
                "report_section_artifact_invalid", "章节规划没有绑定当前 sectionCode。"
            )
        reference_issues = _section_plan_reference_issues(decision, work_item)
        if not reference_issues:
            break
        if plan_call >= 6:
            raise ReportingError(
                "report_section_plan_reference_invalid",
                "章节规划引用了当前 WorkItem 外的指标、管理问题、citation 或 chart。",
                details={"issues": reference_issues},
            )
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
                "逐项修正 issues，保留其余有效规划；返回完整 SectionPlanOutput，"
                "不得输出补丁、解释或 schema 外字段。"
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
        block_charts = [
            item.model_dump(mode="json", by_alias=True)
            for item in work_item.charts
            if item.chart_id in chart_ids
        ]
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
            "facts": block_facts,
            "metricDefinitions": block_metrics,
            "managementQuestions": block_questions,
            "citations": block_citations,
            "charts": block_charts,
            "markdownRequirements": list(work_item.markdown_requirements),
            "requiredAction": (
                "只返回当前 block 的完整 Markdown；围绕 objective 解释 claims，"
                "正文不展示任何内部 ID，每个数字必须来自给定事实。"
            ),
        }
        # 完整证据只驻留在当前固定 Workflow 内存中；模型按 block 消费带身份的相关视图。
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
        for block_attempt in range(2):
            content = await _run_section_stage(
                agent,
                SectionBlockContent,
                f"block-{index}",
                block_payload,
                scope=scope,
                run_context=run_context,
            )
            if not isinstance(content, SectionBlockContent):
                raise ReportingError(
                    "report_phase_output_invalid", "章节正文 Agent 未返回声明的结果。"
                )
            candidate = ReportDraftBlock(
                blockId=block_plan.block_id,
                markdown=content.markdown,
                citationIds=citation_ids,
                chartIds=chart_ids,
                claimIds=block_plan.claim_ids,
            )
            try:
                validate_report_draft_blocks(
                    (*blocks, candidate),
                    expected_section_title=work_item.title,
                )
            except ReportingError as error:
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


def _section_claim_authoring_contract(work_item: SectionWorkItem) -> dict[str, Any]:
    """从当前冻结 WorkItem 生成章节 claim 的动态约束，避免模型猜测业务指标代码。"""

    return {
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


def _pending_analysis_rework_file(checkpoint: ReportingCheckpoint) -> FileIdentity | None:
    """返回尚未被后续全局分析冻结覆盖的最新章节返工身份。"""

    if checkpoint.phase != "analysis":
        return None
    latest_rework = next(
        (
            (index, item.artifact_file)
            for index, item in reversed(tuple(enumerate(checkpoint.trace)))
            if item.phase == "section"
            and item.status == "rework"
            and item.artifact_file is not None
        ),
        None,
    )
    if latest_rework is None:
        return None
    rework_index, rework_file = latest_rework
    later_freeze = any(
        index > rework_index
        and item.phase == "analysis"
        and item.work_kind == "visualization_section"
        and item.status == "completed"
        for index, item in enumerate(checkpoint.trace)
    )
    return None if later_freeze else rework_file


class RuntimeSectionsMixin:
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

    async def _commit_section_rework_batch(
        self,
        run_context: RunContext,
        *,
        checkpoint: ReportingCheckpoint,
        revision: int,
        rework_results: Sequence[tuple[ReportingCheckpoint, AnalysisReworkRequest]],
    ) -> tuple[ReportingCheckpoint, AnalysisReworkRequest]:
        """批内章节执行器全部结束后，一次性提交返工并撤销受影响章节。"""

        requests = tuple(request for _candidate, request in rework_results)
        affected_analysis_ids = tuple(
            dict.fromkeys(
                analysis_id for request in requests for analysis_id in request.analysis_ids
            )
        )
        rework = AnalysisReworkRequest(
            sectionCode=requests[0].section_code,
            analysisIds=affected_analysis_ids,
            reason="；".join(dict.fromkeys(item.reason for item in requests)),
            missingEvidence=tuple(
                dict.fromkeys(item for request in requests for item in request.missing_evidence)
            ),
        )
        await self._apply_durable_command(
            run_context,
            ReportingCommand(
                name="request_analysis_rework",
                commandId=(
                    f"analysis-rework:{revision}:"
                    f"{payload_sha256(rework.model_dump(mode='json', by_alias=True))}"
                ),
                payload={
                    "analysisIds": list(rework.analysis_ids),
                    "missingEvidence": list(rework.missing_evidence),
                    "reason": rework.reason,
                    "sectionCode": rework.section_code,
                },
            ),
        )
        invalid_section_codes = {
            section.code
            for section in _frozen_outline(self._state(run_context)).sections
            if set(section.analysis_ids) & set(affected_analysis_ids)
        }
        checkpoint = self._update_reporting_checkpoint(
            checkpoint,
            phase="analysis",
            report_brief=None,
            evidence_manifest=None,
            analysis_manifest_file=None,
            completed_sections=tuple(
                item
                for item in checkpoint.completed_sections
                if item.section_code not in invalid_section_codes
            ),
            pending_sections=tuple(
                dict.fromkeys([*checkpoint.pending_sections, *sorted(invalid_section_codes)])
            ),
            last_error={
                "phase": "section",
                "code": "report_analysis_evidence_insufficient",
                "message": rework.reason,
                "sectionCode": rework.section_code,
                "retryReason": payload_sha256(rework.model_dump(mode="json", by_alias=True)),
            },
        )
        # 通用并发 merge 会保留 completedSections 的并集；这里是批次收口后的有意撤销，
        # 必须以已读取的最新 checkpoint 为基线精确替换，否则 sibling 的旧完成态会被回灌。
        serialized = json.dumps(
            checkpoint.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(serialized).hexdigest()
        identity = await self._write_immutable_artifact(
            self._scope(run_context)["threadId"],
            (
                f"报表/智能分析/{run_context.run_id}/audit/"
                f"reporting-checkpoint-{checkpoint.revision}-{digest}.json"
            ),
            serialized,
        )
        await self._apply_durable_command(
            run_context,
            ReportingCommand(
                name="set_workflow_checkpoint",
                commandId=f"workflow-checkpoint-v2:{checkpoint.revision}:{digest}",
                payload={
                    "checkpoint": checkpoint.model_dump(mode="json", by_alias=True),
                    "mirrorFile": identity.model_dump(mode="json", by_alias=True),
                },
            ),
        )
        return checkpoint, rework

    @staticmethod
    def _build_section_work_item(
        section: Any,
        *,
        detailed_plan: DetailedAnalysisPlan,
        analysis_artifact: AnalysisArtifact,
        citation_bindings: tuple[Citation, ...],
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
                "完整呈现当前章节全部冻结事实及其管理结论",
                "保持期间、单位和共享指标口径一致",
                "覆盖当前章节 evidence 提供的 citation",
                "仅使用当前 SectionWorkItem 提供的 chart",
                *(f"warning: {item}" for item in section_warnings),
            ),
            analysisIds=tuple(section.analysis_ids),
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
    ) -> tuple[
        ReportingCheckpoint,
        SectionArtifact | None,
        AnalysisReworkRequest | None,
    ]:
        if work_item.serialized_bytes() > MAX_SECTION_WORK_ITEM_BYTES:
            raise ReportingError(
                "report_section_context_too_large",
                "章节紧凑事实投影超过输入软上限；请减少单章绑定的 analysis 数量。",
            )
        scope = self._scope(run_context)
        work_item_payload = work_item.model_dump(mode="json", by_alias=True)
        work_item_hash = payload_sha256(work_item_payload)
        model_work_item_payload = dict(work_item_payload)
        # factFiles 仍进入 durable work item 与身份 hash，保证恢复和追溯语义不变；章节
        # Agent 没有读取这些文件的授权，因此模型输入只暴露可直接使用的 factSummaries。
        model_work_item_payload.pop("factFiles", None)
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
        checkpoint = self._update_reporting_checkpoint(
            checkpoint,
            files=self._merge_checkpoint_files(checkpoint.files, work_item_file),
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
                "sectionOutputPath": section_output_path,
                "reworkRequestPath": rework_request_path,
            }
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
                    "analysisReworkConstraints": dict(analysis_rework_constraints),
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
                        return await _generate_section_in_blocks(
                            self.section_generator,
                            instruction_payload,
                            evidence,
                            work_item,
                            scope=invocation.scope,
                            run_context=task_context,
                        )

                    async def recover(
                        repair: Mapping[str, Any], task_context: RunContext
                    ) -> SectionDecision:
                        if self.section_recovery is None:
                            raise ReportingError(
                                "report_section_recovery_missing", "章节恢复生成器未配置。"
                            )
                        diagnostic = repair.get("diagnostic")
                        # recovery 只允许复用本进程、本次执行已经过 SHA 校验的 bundle。
                        # durable replay 会重新读取并验证证据；若闭包对象不存在必须失败关闭，
                        # 禁止从持久化 repair 中反序列化正文绕过当前文件身份校验。
                        if validated_evidence is None:
                            raise ReportingError(
                                "report_section_recovery_evidence_missing",
                                "章节恢复缺少当前执行已验证的证据对象。",
                            )
                        return await _generate_section_in_blocks(
                            self.section_recovery,
                            instruction_payload,
                            validated_evidence,
                            work_item,
                            scope=invocation.scope,
                            run_context=task_context,
                            recovery=(
                                diagnostic
                                if isinstance(diagnostic, Mapping)
                                else {"message": "章节重试"}
                            ),
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
                }:
                    raise error
        assert last_error is not None
        raise last_error

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

        draft = ReportDraft(
            sections=tuple(
                ReportDraftSection(sectionCode=item.section_code, blocks=item.blocks)
                for item in section_artifacts
            )
        )
        chart_inputs: list[ReportChartInput] = []
        destination_by_chart: dict[str, str] = {}
        report_parent = PurePosixPath(markdown_path).parent
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
                    title=chart.title,
                    altText=chart.alt_text,
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
        if tuple(item.path for item in chart_files) != rendered.chart_paths:
            raise ReportingError(
                "report_draft_chart_path_invalid", "服务端图表归档路径与 Markdown 装配结果不一致。"
            )
        markdown_file = await self._write_immutable_artifact(
            scope["threadId"], markdown_path, rendered.markdown.encode("utf-8")
        )
        accepted_artifacts = [
            markdown_file.model_dump(mode="json", by_alias=True),
            *(item.model_dump(mode="json", by_alias=True) for item in chart_files),
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
        manifest = await self._build_and_write_artifact_manifest(
            manifest_path,
            accepted_artifacts=accepted_artifacts,
            markdown_path=markdown_path,
            lineage=lineage,
            source_warnings=source_warnings,
            revision=revision,
            task_key=analysis_task_id,
            section_numbers=rendered.section_numbers,
            heading_numbers=rendered.heading_numbers,
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
        warning_values = tuple((*checkpoint.warnings, *rendered.warnings)[-500:])
        checkpoint = self._update_reporting_checkpoint(
            checkpoint,
            phase="completed",
            warnings=warning_values,
            last_error=None,
            files=self._merge_checkpoint_files(
                checkpoint.files, markdown_file, *chart_files, manifest_file
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
            evidence.append(AnalysisEvidence.model_validate(raw_item))
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
                _relative, remote = self.workspace_service.normalize_path(
                    fact_files[analysis_id].path, allow_root=False
                )
                async with self.workspace_service._async_client() as client:
                    sandbox = await self.workspace_service._asandbox_for(client, scope["threadId"])
                    content = await self.workspace_service._adownload_file(
                        sandbox, remote, 10 * 1024 * 1024
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
            for section in ordered_sections:
                section_payload = visualization_sections.get(section.code)
                if not isinstance(section_payload, Mapping):
                    continue
                for raw_file in section_payload.get("files", ()):
                    if isinstance(raw_file, Mapping) and isinstance(raw_file.get("path"), str):
                        file_by_path[raw_file["path"]] = raw_file
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
                    inspection = ChartVisualInspectionReceipt(
                        sourcePath=source_path,
                        sha256=str(source_file.get("sha256", "")),
                        inspectionMode="deterministic",
                        visualReviewStatus="not_run",
                        inspectorId="deterministic-raster-inspector-v1",
                        reviewed=True,
                        requiresRevision=False,
                    )
                    chart_values.append(
                        AnalysisChart.model_validate(
                            {
                                # sourcePath 仅是 visualizationSections 内部索引键；
                                # AnalysisChart 的稳定契约以带哈希的 sourceFile 表达文件身份。
                                # 不得把内部索引字段带入 extra=forbid 的最终分析产物。
                                **{
                                    key: value
                                    for key, value in raw_chart.items()
                                    if key != "sourcePath"
                                },
                                "sourceFile": dict(source_file),
                                "visualInspectionReceipt": inspection.model_dump(
                                    mode="json", by_alias=True
                                ),
                            }
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
