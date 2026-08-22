from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import copy
from datetime import date, datetime
from difflib import SequenceMatcher
from functools import partial
from pathlib import PurePosixPath
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

import anyio
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.workflow.types import StepInput, StepOutput
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from ...async_utils import complete_cleanup
from ...task_execution import TaskScope, TaskState
from ...workspace import WorkspaceService
from ..contract import (
    FIELD_REF_PATTERN,
    REPORT_WORKFLOW_SCOPE_STATE_KEY,
    MeasureSemantic,
    ModelColumn,
    ModelTable,
    ModelTermsResponse,
    ReportingWorkflowInput,
    ReportPeriod,
    ReportPeriodWindows,
    ReportPromptInput,
    ReportRequestEnvelope,
    SourceSchemaSnapshot,
    parse_ddl,
    parse_reporting_workflow_input,
)
from ..data_source import (
    CatalogColumn,
    CatalogTable,
    DataShape,
    ReportSourceRegistryConfig,
    StarRocksDataSourceAdapter,
    StarRocksSourceConfig,
    collect_data_shape,
    require_sources,
)
from ..data_sources import MAX_REPORT_INPUTS, DatasetHandle, ReportDatasetStore
from ..delivery.acceptance import (
    build_report_artifact_validation_context,
    build_report_phase_acceptance_contract,
)
from ..delivery.artifacts_v1 import (
    ArtifactFile,
    Citation,
    DocxArtifactManifest,
    PdfArtifactManifest,
    ReportArtifactManifest,
    authoritative_citations,
    build_authoritative_manifest,
    dataset_snapshot_hash,
    validate_rendered_artifacts,
)
from ..delivery.draft_v1 import (
    ReportChartInput,
    ReportDraft,
    ReportDraftSection,
    ReportSectionDefinition,
    assemble_report_markdown,
    validate_report_draft_blocks,
)
from ..delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportArtifactSpec,
    ReportDownloadGrantService,
    ReportDownloadScope,
    cli_result,
    publication_result,
)
from ..delivery.report_runtime import REPORT_VISUAL_THEME
from ..hospital_operation.delivery import (
    PlanExecutionReceipt,
    SourceWarning,
)
from ..hospital_operation.detailed_analysis import (
    DatasetAnalysisContext,
    DetailedAnalysisItem,
    DetailedAnalysisPlan,
    profile_csv_dataset,
)
from ..hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from ..hospital_operation.domains import DOMAIN_CODES, resolve_domain_mentions
from ..hospital_operation.outline import (
    ReportOutline,
    ReportOutlineProposal,
    freeze_outline,
)
from ..hospital_operation.profiles import HospitalOperationProfile, ruijin_profile
from ..instructions import (
    HOSPITAL_ANALYSIS_INSTRUCTIONS,
    HOSPITAL_DATA_UNDERSTANDING_INSTRUCTIONS,
    HOSPITAL_OUTLINE_INSTRUCTIONS,
    HOSPITAL_REQUEST_INSTRUCTIONS,
)
from ..metadata import ReportingMetadataClient
from ..model_policy import (
    ReportingThinkingProfile,
    apply_reporting_thinking_profile,
    reporting_thinking_profile_from_model,
)
from ..models import ReportingError
from ..phase import REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR
from ..profile import (
    CapabilitySet,
    EffectiveReportingProfile,
    ReconciliationShape,
    ReportingProfileRegistry,
    build_outline_shape_view,
    parse_field_ref,
    resolve_reporting_profile,
)
from ..profile import (
    resolve_capabilities as resolve_profile_capabilities,
)
from ..workspace import WorkspaceReportService
from .checkpoint import (
    AnalysisArtifact,
    AnalysisReworkRequest,
    CompletedSection,
    ContextTrace,
    FileIdentity,
    MetricDefinition,
    ProfileCoverageManifest,
    ReportingCheckpoint,
    SectionArtifact,
    SectionCitation,
    SectionWorkItem,
    build_profile_coverage_manifest,
    payload_sha256,
    reporting_phase_task_key,
)
from .execution import (
    MAX_REPORT_INSTRUCTION_BYTES,
    ReportTaskRunner,
    _raise_recorded_agent_error,
)
from .orchestration import create_reporting_workflow, record_step_model_metrics
from .query_pipeline import (
    ApprovedQuery,
    DatasetLineage,
    QueryRequirement,
    approve_query_batch,
    resolve_schema_snapshot,
    state_contains_connection_data,
)
from .repository import ReportingStateRepository
from .state import ReportingCommand, ReportingStateError
from .state import ReportingPhase as DurableReportingPhase

logger = logging.getLogger(__name__)

# 显式期间模式最多为每个需求生成 current、yoy、mom 三条唯一窗口查询；
# 与物化批次的 100 条硬上限保持一致，防止模型输出服务端必然无法完整审批的需求数。
MAX_ANALYSIS_REQUIREMENTS = MAX_REPORT_INPUTS // 3
REPORT_WORKFLOW_INPUT_STATE_KEY = "report_workflow_input"
REPORT_SCHEMA_SNAPSHOTS_STATE_KEY = "report_schema_snapshots"
REPORT_DATA_UNDERSTANDING_STATE_KEY = "report_data_understanding"
REPORT_DATA_SHAPES_STATE_KEY = "report_data_shapes"
REPORT_EFFECTIVE_PROFILE_STATE_KEY = "report_effective_profile"
REPORT_CAPABILITIES_STATE_KEY = "report_capabilities"
REPORT_SOURCE_WARNINGS_STATE_KEY = "report_source_warnings"
REPORT_REQUEST_CONTEXT_STATE_KEY = "report_request_context"
REPORT_OUTLINE_STATE_KEY = "report_outline"
REPORT_ANALYSIS_PLAN_STATE_KEY = "report_analysis_plan"
REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY = "report_analysis_data_context"
REPORT_ANALYSIS_CONTEXT_FILE_STATE_KEY = "report_analysis_context_file"
REPORT_PROFILE_COVERAGE_STATE_KEY = "report_profile_coverage"
REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY = "report_detailed_analysis_plan"
REPORT_DATA_REQUIREMENTS_STATE_KEY = "report_data_requirements"
REPORT_ROW_PRESERVING_REQUIREMENTS_STATE_KEY = "report_row_preserving_requirements"
REPORT_APPROVED_QUERIES_STATE_KEY = "report_approved_queries"
REPORT_DATASET_LINEAGE_STATE_KEY = "report_dataset_lineage"
REPORT_OUTLINE_HASH_STATE_KEY = "report_outline_hash"
REPORT_DOCUMENT_GENERATED_DATE_STATE_KEY = "report_document_generated_date"
REPORT_WORKFLOW_RESULT_STATE_KEY = "report_workflow_result"
REPORT_ARTIFACTS_STATE_KEY = "report_artifacts"
MAX_REPORT_SECTION_PHASE_ATTEMPTS = 2
MAX_REPORT_ANALYSIS_REWORKS_PER_SECTION = 1
MAX_SECTION_WORK_ITEM_BYTES = 256 * 1024


async def _run_bounded(
    items: Sequence[Any],
    *,
    concurrency: int,
    worker: Callable[[Any], Awaitable[Any]],
) -> list[Any]:
    """按输入索引返回并发结果；完成顺序不改变最终提纲顺序。"""

    if isinstance(concurrency, bool) or concurrency < 1:
        raise ValueError("concurrency 必须大于 0")
    semaphore = asyncio.Semaphore(concurrency)
    results: list[Any] = [None] * len(items)
    failures: dict[int, Exception] = {}

    async def run_one(index: int, item: Any) -> None:
        async with semaphore:
            try:
                results[index] = await worker(item)
            except Exception as error:
                # 业务失败不能让 TaskGroup 取消已启动的兄弟任务，也不能让 Python 把
                # 稳定 ReportingError 包成 ExceptionGroup。外部取消仍直接穿透。
                failures[index] = error

    async with asyncio.TaskGroup() as task_group:
        for index, item in enumerate(items):
            task_group.create_task(run_one(index, item))
    if failures:
        raise failures[min(failures)]
    return results


async def _run_pending_analysis_items(
    analysis_ids: Sequence[str],
    *,
    completed_analysis_ids: set[str],
    concurrency: int,
    worker: Callable[[str], Awaitable[Any]],
) -> tuple[str, ...]:
    """并发执行未完成分析项；返回本轮实际调度的稳定计划顺序。"""

    pending = tuple(item for item in analysis_ids if item not in completed_analysis_ids)
    if pending:
        failures: dict[str, Exception] = {}

        async def run_one(analysis_id: str) -> None:
            try:
                await worker(analysis_id)
            except Exception as error:
                # 单项业务失败不能取消已经并发运行的其他 analysis；成功项已通过
                # durable CAS 冻结，下一轮只重试失败项。外部取消仍由 CancelledError
                # 直接穿透 TaskGroup，确保用户终止不会被吞掉。
                failures[analysis_id] = error

        await _run_bounded(pending, concurrency=concurrency, worker=run_one)
        for analysis_id in pending:
            if analysis_id in failures:
                raise failures[analysis_id]
    return pending


def _coding_detailed_analysis_plan(
    plan: DetailedAnalysisPlan,
    *,
    analysis_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """向成稿 Worker 投影 Codex 风格步骤，完整事实继续由受信上下文承载。"""
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
            }
            for item in plan.analyses
            if allowed is None or item.analysis_id in allowed
        ],
    }


def _analysis_item_completion_conditions(
    recovery_payload: dict[str, Any] | None,
    last_error: Exception | None,
) -> list[str]:
    if recovery_payload is not None:
        return [
            "durable 单项事实已冻结；不要重算或改写 evidence",
            "使用 durableAnalysisItem 的相同字段重新调用 complete_analysis_item 完成 Task 收尾",
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
        "优先查询 deterministicFactFile；固定事实足够时不创建脚本或 evidence，"
        "complete_analysis_item 的 evidencePaths 传空数组",
        "只为 deterministicFactFile 未覆盖的事实缺口创建补充 evidence",
        "本阶段禁止生成或登记图表",
        "最后且只调用一次 complete_analysis_item",
    ]


def _visualization_completion_conditions(
    last_error: Exception | None,
    charts_registered: bool,
) -> list[str]:
    if charts_registered:
        return [
            "durable state 已完成整批图表登记；禁止改图、换 chartId、重复登记或继续自检",
            "不要调用任何读取、写入、执行、Skill 或视觉工具",
            "立即且只调用一次 finalize_report_analysis",
        ]
    previous_tool_calls, _ = _visualization_retry_budget(last_error)
    if previous_tool_calls > 0 or (
        isinstance(last_error, ReportingError)
        and last_error.code
        in {
            "report_visualization_tool_budget_exhausted",
            "report_visualization_script_failure_limit_exhausted",
        }
    ):
        return [
            "上一轮因工具调用或脚本失败达到上限而终止；禁止重新规划、重复读取事实或重新探索工作区",
            "复用工作区已有脚本和图表，只完成尚缺的最小执行或检查",
            "整批图表只调用一次 register_report_charts，成功后立即调用 finalize_report_analysis",
        ]
    return [
        "只整合 completedAnalysisItems 和 deterministicFactFiles，不重跑单项分析",
        "批量读取事实、生成和执行图表脚本；相同文件不得重复读取、执行或视觉检查",
        "按批准提纲生成必要图表并整批登记 citation",
        "最后且只调用一次 finalize_report_analysis",
        "evidence、receipt、citation 和文件身份由服务端 durable state 派生",
    ]


def _visualization_retry_budget(last_error: Exception | None) -> tuple[int, int]:
    if (
        isinstance(last_error, ReportingError)
        and isinstance(last_error.details, Mapping)
        and ("totalToolCalls" in last_error.details or "scriptFailureCount" in last_error.details)
    ):
        source: Any = last_error.details
    else:
        source = getattr(last_error, REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR, None)

    def count(raw: Any) -> int:
        return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0

    if isinstance(source, Mapping):
        return count(source.get("totalToolCalls")), count(source.get("scriptFailureCount"))
    if isinstance(source, Sequence) and not isinstance(source, (str, bytes)) and len(source) == 2:
        return count(source[0]), count(source[1])
    return 0, 0


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class NormalizedReportPrompt(_StrictModel):
    period: ReportPeriod | None = None
    report_type: Literal["comprehensive", "topic"] | None = Field(default=None, alias="reportType")
    clarification_question: str | None = Field(
        default=None, alias="clarificationQuestion", min_length=1, max_length=1000
    )


_JSON_FENCE_PATTERN = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
_FORBIDDEN_DERIVATION_PATTERN = re.compile(
    r"(?:拟合|估算|估计|推算|插值|外推|年化|平滑|填补|补齐|视为(?:未发生|零|0)|"
    r"imput(?:e|ed|ation)|interpolat\w*|extrapolat\w*|estimat\w*|annualiz\w*|smooth\w*)",
    re.IGNORECASE,
)
_FABRICATION_NEGATION_PATTERN = re.compile(
    r"(?:(?:不得|禁止|避免|拒绝|无需|无须|不应|不可).{0,24}|"
    r"不(?:进行|采用|使用|予以|做|作).{0,8})$"
)
_NUMERIC_MEASURE_TYPE_PATTERN = re.compile(
    r"^(?:TINYINT|SMALLINT|INT|INTEGER|BIGINT|LARGEINT|FLOAT|DOUBLE|DECIMAL)",
    re.IGNORECASE,
)
_VISIBLE_MACHINE_SCALAR_KEYS = frozenset(
    {
        "code",
        "datasetId",
        "leftTable",
        "periodColumn",
        "requirementId",
        "rightTable",
        "sourceId",
        "table",
    }
)
_VISIBLE_MACHINE_LIST_KEYS = frozenset(
    {"dimensionColumns", "grainColumns", "joinColumns", "measureColumns"}
)


def _report_machine_terms(*values: Any) -> tuple[str, ...]:
    terms: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if key in _VISIBLE_MACHINE_SCALAR_KEYS and isinstance(item, str):
                    terms.add(item)
                elif key in _VISIBLE_MACHINE_LIST_KEYS and isinstance(item, (list, tuple)):
                    terms.update(part for part in item if isinstance(part, str))
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    for value in values:
        visit(value)
    return tuple(sorted(terms))


def _frozen_outline(state: Mapping[str, Any]) -> ReportOutline:
    try:
        raw = state[REPORT_OUTLINE_STATE_KEY]
        outline = ReportOutline.model_validate(raw)
    except Exception as error:
        raise ReportingError("report_outline_invalid", "报告提纲状态无效。") from error
    expected_hash = state.get(REPORT_OUTLINE_HASH_STATE_KEY)
    if isinstance(expected_hash, str) and expected_hash != _payload_sha256(raw):
        raise ReportingError("report_outline_changed", "已批准报告提纲发生变化，必须重新审核。")
    return outline


def _single_explicit_year(prompt: str, feedback: str | None) -> ReportPeriod | None:
    value = f"{prompt}\n{feedback or ''}"
    years = set(re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", value))
    if len(years) != 1:
        return None
    raw_year = years.pop()
    if re.search(rf"{raw_year}\s*年\s*\d{{1,2}}\s*月|{raw_year}[-/.]\d{{1,2}}", value):
        return None
    year = int(raw_year)
    return ReportPeriod(start=date(year, 1, 1), end=date(year, 12, 31))


def _explicit_report_type(*values: str | None) -> Literal["comprehensive", "topic"] | None:
    text = "\n".join(value for value in values if isinstance(value, str))
    found: set[Literal["comprehensive", "topic"]] = set()
    if re.search(
        r"(?:reportType\s*[:=]\s*comprehensive|(?:综合|整体)(?:运营|经营)?(?:分析)?(?:报告|情况)?)",
        text,
        re.I,
    ):
        found.add("comprehensive")
    if re.search(r"(?:reportType\s*[:=]\s*topic|专题(?:分析)?报告|\S+专题)", text, re.I):
        found.add("topic")
    return next(iter(found)) if len(found) == 1 else None


def _resolved_report_type(
    explicit: Literal["comprehensive", "topic"] | None,
    domains: tuple[str, ...] | None,
) -> Literal["comprehensive", "topic"]:
    """保留显式兼容值；否则由规范化领域范围确定报告类型。"""
    if explicit is not None:
        return explicit
    if domains and len(domains) < len(DOMAIN_CODES):
        return "topic"
    return "comprehensive"


def _planner_candidate(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    candidate = content.strip()
    fenced = _JSON_FENCE_PATTERN.fullmatch(candidate)
    if fenced is not None:
        candidate = fenced.group(1).strip()
    try:
        decoded = json.loads(candidate)
    except ValueError:
        return content
    if not isinstance(decoded, str):
        return decoded
    try:
        return json.loads(decoded)
    except ValueError:
        return decoded


def _compact_output_schema(output_schema: type[BaseModel]) -> str:
    def compact(value: Any, *, preserve_keys: bool = False) -> Any:
        if isinstance(value, dict):
            return {
                key: compact(item, preserve_keys=key in {"$defs", "properties"})
                for key, item in value.items()
                if preserve_keys or key not in {"default", "description", "title"}
            }
        if isinstance(value, list):
            return [compact(item) for item in value]
        return value

    schema = compact(output_schema.model_json_schema(by_alias=True))
    return json.dumps(schema, ensure_ascii=False, separators=(",", ":"))


def _contains_forbidden_derivation(value: str) -> bool:
    for match in _FORBIDDEN_DERIVATION_PATTERN.finditer(value):
        if not _FABRICATION_NEGATION_PATTERN.search(value[: match.start()]):
            return True
    return False


def _coding_observed_data_facts(
    data_shapes: tuple[DataShape, ...],
    requirements: tuple[QueryRequirement, ...],
    lineage: tuple[DatasetLineage, ...],
) -> list[dict[str, Any]]:
    lineage_by_requirement = {(item.source_id, item.requirement_id): item for item in lineage}
    facts: list[dict[str, Any]] = []
    for requirement in requirements:
        binding = lineage_by_requirement.get((requirement.source_id, requirement.requirement_id))
        if binding is None:
            raise ReportingError(
                "report_observed_facts_binding_invalid", "期间事实缺少数据集绑定。"
            )
        for required_table in requirement.tables:
            candidates = [
                table
                for shape in data_shapes
                for table in shape.tables
                if table.source_id == requirement.source_id
                and required_table.table
                in {table.table.lower(), f"{table.database}.{table.table}".lower()}
            ]
            if len(candidates) != 1:
                raise ReportingError(
                    "report_observed_facts_binding_invalid", "期间事实无法唯一绑定数据表。"
                )
            table = candidates[0]
            facts.append(
                {
                    "datasetId": binding.dataset_id,
                    "requirementId": binding.requirement_id,
                    "sourceId": table.source_id,
                    "table": f"{table.database}.{table.table}",
                    "periodGranularity": table.period_granularity,
                    "firstEffectiveDate": table.first_effective_date,
                    "lastEffectiveDate": table.last_effective_date,
                    "periodCoverage": list(table.period_coverage),
                    "missingPeriods": list(table.missing_periods),
                    "periodRowCount": table.period_row_count,
                }
            )
    return facts


def _source_warnings_from_state(state: Mapping[str, Any]) -> tuple[SourceWarning, ...]:
    """读取服务端对账告警；非法或模型伪造的告警不会进入交付回执。"""

    raw = state.get(REPORT_SOURCE_WARNINGS_STATE_KEY)
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ReportingError("report_source_warning_invalid", "来源差异告警状态无效。")
    try:
        return tuple(SourceWarning.model_validate(item) for item in raw)
    except Exception as error:
        raise ReportingError("report_source_warning_invalid", "来源差异告警状态无效。") from error


def _analysis_quality_warnings(
    metric_definitions: tuple[MetricDefinition, ...],
    analysis_warnings: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    """把冻结分析披露的不可比与数据缺失转换为发布告警。"""

    warnings: list[dict[str, Any]] = []
    comparability_markers = ("期间跨度不一致", "同期不可比", "仅作参考性对比")
    for metric in metric_definitions:
        description = f"{metric.definition} {metric.period_basis}"
        mismatched_budget_actual = (
            "执行" in metric.name
            and "预算" in description
            and "实际" in description
            and description.count("覆盖") >= 2
        )
        zero_period_comparison = "同比" in description and re.search(
            r"\d{1,2}(?:月|[-—至到]\d{1,2}月)为0", description
        )
        if (
            any(marker in description for marker in comparability_markers)
            or mismatched_budget_actual
            or zero_period_comparison is not None
        ):
            warnings.append(
                {
                    "code": "analysis_period_incomparable",
                    "message": "冻结指标包含不可比期间，报告结论需按披露口径谨慎使用。",
                    "details": {"metricCode": metric.code, "periodBasis": metric.period_basis},
                }
            )
    for warning in analysis_warnings:
        classified = False
        if any(marker in warning for marker in comparability_markers):
            classified = True
            warnings.append(
                {
                    "code": "analysis_period_incomparable",
                    "message": "冻结分析 Warning 标记了不可比期间，报告结论需谨慎使用。",
                    "details": {"warning": warning[:500]},
                }
            )
        if any(
            marker in warning
            for marker in (
                "数据缺失",
                "数据不完整",
                "期间不完整",
                "期间不足",
                "缺失月份",
                "疑似未入账",
            )
        ):
            classified = True
            warnings.append(
                {
                    "code": "analysis_data_incomplete",
                    "message": "冻结分析披露数据缺失或期间不完整，报告结论需按实际覆盖范围使用。",
                    "details": {"warning": warning[:500]},
                }
            )
        if not classified:
            warnings.append(
                {
                    "code": "analysis_data_quality",
                    "message": "冻结分析披露数据质量限制，报告结论需结合告警内容谨慎使用。",
                    "details": {"warning": warning[:500]},
                }
            )
    return tuple(warnings)


def _human_label(value: str | None, fallback: str) -> str:
    normalized = " ".join(str(value or "").split())
    if normalized and re.search(r"[\u4e00-\u9fff]", normalized):
        return normalized[:120]
    return fallback


def _citation_presentations(
    *,
    lineage: tuple[DatasetLineage, ...],
    requirements: tuple[QueryRequirement, ...],
    analyses: tuple[AnalysisItem, ...],
    snapshots: tuple[SourceSchemaSnapshot, ...],
    observed_facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requirements_by_id = {item.requirement_id: item for item in requirements}
    table_descriptions: dict[tuple[str, str], str] = {}
    for snapshot in snapshots:
        for table in snapshot.tables:
            qualified = f"{table.database}.{table.name}".lower()
            label = _human_label(table.description, "")
            if label:
                table_descriptions[(table.source_id, qualified)] = label
                table_descriptions[(table.source_id, table.name.lower())] = label
    presentations: list[dict[str, Any]] = []
    for index, citation in enumerate(authoritative_citations(lineage), start=1):
        requirement = requirements_by_id.get(citation.requirement_id)
        metadata_labels = []
        if requirement is not None:
            metadata_labels = [
                table_descriptions.get((requirement.source_id, table.table.lower()), "")
                for table in requirement.tables
            ]
            metadata_labels = list(dict.fromkeys(item for item in metadata_labels if item))
        analysis_label = next(
            (
                analysis.description
                for analysis in analyses
                if citation.requirement_id in analysis.requirement_ids
            ),
            None,
        )
        label = _human_label(
            "、".join(metadata_labels) if metadata_labels else analysis_label,
            f"第 {index} 项已审核业务数据",
        )
        coverage_items: list[dict[str, Any]] = []
        bound_facts = [
            fact
            for fact in observed_facts
            if fact.get("datasetId") == citation.dataset_id
            and fact.get("requirementId") == citation.requirement_id
        ]
        for coverage_index, fact in enumerate(bound_facts, start=1):
            table_name = str(fact.get("table") or "").lower()
            source_id = str(fact.get("sourceId") or "")
            coverage_label = _human_label(
                table_descriptions.get((source_id, table_name)),
                f"来源项 {coverage_index}",
            )
            coverage = {
                str(period) for period in fact.get("periodCoverage", []) if isinstance(period, str)
            }
            missing = {
                str(period) for period in fact.get("missingPeriods", []) if isinstance(period, str)
            }
            coverage_items.append({"label": coverage_label, "periods": sorted(coverage - missing)})
        presentations.append(
            {
                "citationId": citation.citation_id,
                "label": label,
                "coverageItems": coverage_items,
            }
        )
    return presentations


def _accepted_artifacts_match_manifest(
    manifest: ReportArtifactManifest,
    manifest_path: str,
    accepted_artifacts: list[dict[str, Any]],
) -> bool:
    accepted: dict[str, dict[str, Any]] = {
        path: item
        for item in accepted_artifacts
        if isinstance(item, dict) and isinstance(path := item.get("path"), str)
    }
    if len(accepted) != len(accepted_artifacts):
        return False
    declared = [manifest.markdown, *manifest.charts]
    declared_paths = {item.path for item in declared}
    extra_paths = set(accepted) - declared_paths
    if manifest_path in accepted or any(
        PurePosixPath(path).suffix.lower() not in {".png", ".jpg", ".jpeg"} for path in extra_paths
    ):
        return False
    if not declared_paths.issubset(accepted):
        return False
    return all(
        accepted[item.path].get("size") == item.size
        and accepted[item.path].get("sha256") == item.sha256
        for item in declared
    )


def _analysis_context_payload(outline_context: Any) -> dict[str, Any]:
    if not isinstance(outline_context, Mapping):
        return {}
    context: dict[str, Any] = {}
    profile = outline_context.get("profile")
    if isinstance(profile, Mapping):
        context["profile"] = {
            key: profile[key]
            for key in (
                "profileId",
                "revision",
                "effectiveProfileHash",
                "dimensions",
                "metrics",
                "reconciliations",
            )
            if key in profile
        }
    for key in ("capabilities", "terms", "reconciliations"):
        if key in outline_context:
            context[key] = outline_context[key]
    tables = outline_context.get("tables")
    if isinstance(tables, list):
        context["observedDataFacts"] = [
            {
                key: table[key]
                for key in (
                    "sourceId",
                    "table",
                    "periodGranularity",
                    "periodRowCount",
                    "periodCoverage",
                    "missingPeriods",
                )
                if key in table
            }
            for table in tables
            if isinstance(table, Mapping)
        ]
    return context


def _profile_coverage_instruction_projection(
    manifest: ProfileCoverageManifest,
    analysis_context_file: FileIdentity,
    *,
    dataset_ids: set[str] | None = None,
) -> dict[str, Any]:
    """投影高优先级 coverage 事实；长序列和完整字段仍从受信文件定点恢复。"""

    def bounded_periods(values: tuple[str, ...]) -> tuple[list[str], bool]:
        if len(values) <= 24:
            return list(values), False
        return [*values[:12], *values[-12:]], True

    def bounded_warnings(values: tuple[str, ...]) -> tuple[list[str], bool]:
        return list(values[:10]), len(values) > 10

    datasets: list[dict[str, Any]] = []
    for item in manifest.datasets:
        if dataset_ids is not None and item.dataset_id not in dataset_ids:
            continue
        periods, periods_truncated = bounded_periods(item.period_coverage)
        source_warnings, source_warnings_truncated = bounded_warnings(item.source_warnings)
        quality_warnings, quality_warnings_truncated = bounded_warnings(item.quality_warnings)
        datasets.append(
            {
                "datasetId": item.dataset_id,
                "fieldCount": item.field_count,
                "coverageStart": item.period_coverage[0] if item.period_coverage else None,
                "coverageEnd": item.period_coverage[-1] if item.period_coverage else None,
                "coveragePeriodCount": len(item.period_coverage),
                "periodCoverage": periods,
                "periodCoverageTruncated": periods_truncated,
                "sourceWarnings": source_warnings,
                "sourceWarningsTruncated": source_warnings_truncated,
                "qualityWarnings": quality_warnings,
                "qualityWarningsTruncated": quality_warnings_truncated,
            }
        )

    return {
        "manifestFile": analysis_context_file.model_dump(mode="json", by_alias=True),
        "manifestPointer": "/profileCoverageManifest",
        "authorizedDatasetCount": len(datasets),
        "coveredDatasetCount": len(datasets),
        "datasets": datasets,
    }


class TableReference(_StrictModel):
    source_id: str = Field(
        alias="sourceId",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$",
        description="候选表所属数据源 ID，必须与输入 Schema 完全一致。",
    )
    table: str = Field(
        min_length=3,
        max_length=256,
        pattern=r"^[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*$",
        description="规范 database.table，必须直接复制输入 Schema 中的 table。",
    )

    @field_validator("table")
    @classmethod
    def normalize_table(cls, value: str) -> str:
        return value.lower()


class DataUnderstandingTable(TableReference):
    role: str = Field(min_length=1, max_length=200, description="该表对报告目标的必要作用。")
    period_column: str = Field(
        alias="periodColumn",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$",
        description="用于限定请求期间的物理字段，必须来自该表。",
    )
    period_granularity: Literal["date", "month", "year"] = Field(
        alias="periodGranularity",
        description=(
            "期间值的时间语义，与数据库字段类型无关：完整日期值使用 date，"
            "YYYY/MM、YYYY-MM 或 YYYYMM 月份值使用 month，仅存日历年份的值使用 year；"
            "不得根据报告汇总粒度选择。"
        ),
    )


class DataUnderstandingPlan(_StrictModel):
    tables: tuple[DataUnderstandingTable, ...] = Field(
        min_length=1,
        max_length=200,
        description="完成报告目标所必需的表及其物理期间字段，不包含指标、SQL 或报告提纲。",
    )


class PlanningSchemaColumn(_StrictModel):
    name: str = Field(min_length=1, max_length=128)
    data_type: str = Field(alias="dataType", min_length=1, max_length=128)
    description: str = Field(default="", max_length=2_000)


class PlanningSchemaTable(TableReference):
    description: str = Field(default="", max_length=4_000)
    columns: tuple[PlanningSchemaColumn, ...] = Field(min_length=1, max_length=500)


class PlanningSchema(_StrictModel):
    tables: tuple[PlanningSchemaTable, ...] = Field(min_length=1, max_length=200)
    measure_semantics: tuple[MeasureSemantic, ...] = Field(
        default=(), alias="measureSemantics", max_length=2_000
    )


class MeasureSemanticDecision(_StrictModel):
    field_ref: str = Field(alias="fieldRef", pattern=FIELD_REF_PATTERN)
    classification: Literal["measure", "dimension"]
    reason: str = Field(min_length=1, max_length=1_000)
    measure_semantic: MeasureSemantic | None = Field(default=None, alias="measureSemantic")

    @field_validator("field_ref")
    @classmethod
    def normalize_field_ref(cls, value: str) -> str:
        return value.lower()

    @model_validator(mode="after")
    def validate_classification(self) -> MeasureSemanticDecision:
        # 决策对象同时保留字段分类和可审阅理由，但只有 measure 可以携带
        # MeasureSemantic。这个互斥约束防止模型把同一字段一边声明为维度，
        # 一边又偷偷提供聚合规则，导致审核界面与最终提交内容不一致。
        if self.classification == "measure":
            if self.measure_semantic is None:
                raise ValueError("measure 分类必须提供 measureSemantic")
            if self.measure_semantic.field_ref.lower() != self.field_ref:
                raise ValueError("measureSemantic.fieldRef 必须与决策字段一致")
        elif self.measure_semantic is not None:
            raise ValueError("dimension 分类不得提供 measureSemantic")
        return self


class MeasureSemanticProposal(_StrictModel):
    decisions: tuple[MeasureSemanticDecision, ...] = Field(default=(), max_length=2_000)

    @field_validator("decisions")
    @classmethod
    def validate_decisions(
        cls, value: tuple[MeasureSemanticDecision, ...]
    ) -> tuple[MeasureSemanticDecision, ...]:
        field_refs = [item.field_ref for item in value]
        if len(field_refs) != len(set(field_refs)):
            raise ValueError("指标语义候选不能重复分类同一字段")
        return value


class AnalysisItem(_StrictModel):
    code: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2_000)
    management_question: str = Field(alias="managementQuestion", min_length=1, max_length=2_000)
    primary_metric_family: str = Field(alias="primaryMetricFamily", min_length=1, max_length=256)
    requirement_ids: tuple[str, ...] = Field(
        alias="requirementIds",
        min_length=1,
        max_length=100,
        description="引用 requirements 中已有的 ID，每个 ID 只出现一次；maxItems 只是上限。",
    )

    @field_validator("requirement_ids")
    @classmethod
    def validate_requirement_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("requirementIds 不能重复")
        return value

    @field_validator("description", "management_question")
    @classmethod
    def validate_analysis_text(cls, value: str) -> str:
        if _contains_forbidden_derivation(value):
            raise ValueError("分析项不得拟合、估算、推算、插值、外推、年化、平滑或补齐数据")
        return value


class AnalysisBundle(_StrictModel):
    analyses: tuple[AnalysisItem, ...] = Field(min_length=1, max_length=100)
    requirements: tuple[QueryRequirement, ...] = Field(
        min_length=1, max_length=MAX_ANALYSIS_REQUIREMENTS
    )


def _normalize_analysis_bundle_table_refs(candidate: Any) -> Any:
    if not isinstance(candidate, dict) or not isinstance(candidate.get("requirements"), list):
        return candidate

    # 模型偶尔把 sourceId 当成 SQL catalog 前缀，生成 sourceId.database.table。
    # 仅精确移除当前 requirement 的 sourceId；其他三段式引用仍由严格 Schema 拒绝。
    normalized = copy(candidate)
    normalized_requirements: list[Any] = []
    for raw_requirement in candidate["requirements"]:
        if not isinstance(raw_requirement, dict):
            normalized_requirements.append(raw_requirement)
            continue
        source_id = raw_requirement.get("sourceId", raw_requirement.get("source_id"))
        if not isinstance(source_id, str):
            normalized_requirements.append(raw_requirement)
            continue

        requirement = copy(raw_requirement)
        for key in ("tables", "relations"):
            raw_items = raw_requirement.get(key)
            if not isinstance(raw_items, list):
                continue
            items: list[Any] = []
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    items.append(raw_item)
                    continue
                item = copy(raw_item)
                fields = (
                    ("table",)
                    if key == "tables"
                    else (
                        "leftTable",
                        "rightTable",
                        "left_table",
                        "right_table",
                    )
                )
                for field in fields:
                    value = item.get(field)
                    if not isinstance(value, str):
                        continue
                    parts = value.split(".")
                    if len(parts) == 3 and parts[0] == source_id:
                        item[field] = ".".join(parts[1:])
                items.append(item)
            requirement[key] = items
        normalized_requirements.append(requirement)
    normalized["requirements"] = normalized_requirements
    return normalized


class GeneratedQuery(_StrictModel):
    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    source_id: str = Field(alias="sourceId", min_length=1, max_length=64)
    sql: str = Field(min_length=1, max_length=262_144)
    period_role: Literal["current", "yoy", "mom"] = Field(default="current", alias="periodRole")


class GeneratedQueryBatch(_StrictModel):
    queries: tuple[GeneratedQuery, ...] = Field(min_length=1, max_length=100)


_PLANNER_DISPLAY_NAMES = {
    "report-request-normalizer": "需求理解",
    "report-data-understanding-planner": "数据范围分析",
    "report-measure-semantic-proposer": "指标口径整理",
    "report-analysis-planner": "分析计划设计",
    "report-sql-planner": "取数方案设计",
    "report-outline-planner": "报告提纲规划",
}


class ReportWorkflowRuntime:
    """v1 报表运行时；数据库连接只存在于服务端 adapter 内。"""

    def __init__(
        self,
        *,
        db: Any,
        report_worker: Agent,
        task_runner: ReportTaskRunner,
        workspace_service: WorkspaceService,
        registry: ReportSourceRegistryConfig,
        profiles: ReportingProfileRegistry,
        planner_enable_thinking: bool,
        planner_reasoning_effort: str = "high",
        planner_thinking_budget: int = 8192,
        metadata_client: ReportingMetadataClient | None = None,
        download_grants: ReportDownloadGrantService | None = None,
        artifact_persistence: ReportArtifactPersistenceService | None = None,
        report_public_base_url: str | None = None,
        state_repository: ReportingStateRepository,
        analysis_concurrency: int = 1,
        section_concurrency: int = 1,
    ):
        if (download_grants is None) != (artifact_persistence is None):
            raise ValueError("下载授权和产物持久化服务必须同时配置")
        if download_grants is not None and report_public_base_url is None:
            raise ValueError("启用 HTTP 报表发布时必须配置公开下载基址")
        self.db = db
        self.report_worker = report_worker
        self.task_runner = task_runner
        self.workspace_service = workspace_service
        self.registry = registry
        self.profiles = profiles
        self.metadata_client = metadata_client
        self.download_grants = download_grants
        self.artifact_persistence = artifact_persistence
        self.report_public_base_url = report_public_base_url
        self.state_repository = state_repository
        if isinstance(analysis_concurrency, bool) or not 1 <= analysis_concurrency <= 4:
            raise ValueError("analysis_concurrency 必须在 1 到 4 之间")
        if isinstance(section_concurrency, bool) or not 1 <= section_concurrency <= 5:
            raise ValueError("section_concurrency 必须在 1 到 5 之间")
        if planner_reasoning_effort not in {"high", "max"}:
            raise ValueError("planner_reasoning_effort 必须是 high 或 max")
        if (
            isinstance(planner_thinking_budget, bool)
            or not isinstance(planner_thinking_budget, int)
            or planner_thinking_budget <= 0
        ):
            raise ValueError("planner_thinking_budget 必须是正整数")
        self.analysis_concurrency = analysis_concurrency
        self.section_concurrency = section_concurrency
        self._durable_command_lock = asyncio.Lock()
        self._checkpoint_persist_lock = asyncio.Lock()
        self.datasets = ReportDatasetStore(workspace_service)
        self.report_tools = WorkspaceReportService(workspace_service, data_sources=self.datasets)
        planner_off = ReportingThinkingProfile.off()
        planner_high = (
            ReportingThinkingProfile.on(
                reasoning_effort="high",
                thinking_budget=planner_thinking_budget,
            )
            if planner_enable_thinking
            else planner_off
        )
        planner_max = (
            ReportingThinkingProfile.on(
                reasoning_effort="max",
                thinking_budget=planner_thinking_budget,
            )
            if planner_enable_thinking
            else planner_off
        )
        # DeepSeek V4 只有 off/high/max 三个真实档位。数据理解和指标语义 Planner
        # 首次请求关闭 thinking，只有 Schema 校验失败或服务端签发 correction 时才升级；
        # 分析计划从首次请求就使用 max，因为它必须同时满足指标、粒度、期间和关系约束。
        # SQL 在首次请求关闭 thinking，失败后升到 max；归一化和提纲始终 off。
        self._request_normalizer = self._planning_agent(
            report_worker,
            "report-request-normalizer",
            NormalizedReportPrompt,
            thinking_profile=planner_off,
            stage_instructions=(
                *HOSPITAL_REQUEST_INSTRUCTIONS,
                "只归一化分析期间；领域优先由服务端别名规则识别，领域歧义状态返回澄清内容",
                "不得推断或返回数据源、Agent、医院或系统标识",
                "单个明确日历年份转换为该年1月1日至12月31日",
                "期间缺失、存在多个互相冲突的期间或无法唯一判断时，只返回一个简短且陈述式的 clarificationQuestion",
                "不得改写或返回用户原始报告目标",
            ),
        )
        self._data_understanding_agent = self._planning_agent(
            report_worker,
            "report-data-understanding-planner",
            DataUnderstandingPlan,
            thinking_profile=planner_off,
            escalation_thinking_profile=planner_high,
            stage_instructions=(
                "只选择完成报告目标所需的数据表",
                "sourceId 必须与输入 Schema 完全一致",
                "table 必须直接复制输入 Schema 中的规范值",
                "periodColumn 必须直接选择对应输入表的 columns[].name",
                "只返回选表及物理期间字段，不规划指标、SQL、章节或结论",
                "完整日期值使用 date；YYYY/MM、YYYY-MM 或 YYYYMM 月份值使用 month；仅存日历年份的值使用 year",
                "date、month、year 表示值的时间语义，不等同于数据库字段类型；字符串字段也可以承载这三种语义",
                "periodGranularity 描述字段值的时间语义，不是报告汇总粒度",
                (
                    "同一表存在语义等价的 DATE/DATETIME 字段和字符串期间码时，优先选择可直接验证的"
                    "日期字段；仅在目标明确要求代码口径或没有日期字段时选择字符串期间码"
                ),
                "不得使用文件名、不完整表名、table.column 或 DDL 外名称",
                "不得虚构表、字段或业务含义",
                *HOSPITAL_DATA_UNDERSTANDING_INSTRUCTIONS,
            ),
        )
        self._measure_semantic_agent = self._planning_agent(
            report_worker,
            "report-measure-semantic-proposer",
            MeasureSemanticProposal,
            thinking_profile=planner_off,
            escalation_thinking_profile=planner_max,
            stage_instructions=(
                "这是待用户审核的候选，不是已确认业务事实；只依据输入 Schema、术语和受限数据画像分类",
                "candidateFieldRefs 中每个字段必须且只能在 decisions 中出现一次，不得增加、遗漏或替换字段",
                "金额、数量等可聚合事实分类为 measure；年份、期间码、主外键、排序码、状态码和分类编码应分类为 dimension",
                "measureSemantic.fieldRef 必须与当前 decision.fieldRef 完全一致",
                (
                    "additiveAcross 每项只能从当前 candidateFieldContexts.sameTableColumnNames "
                    "复制裸列名，不得使用完整 fieldRef、table.column 或重复值；不确定时返回空数组"
                ),
                (
                    "exclusiveScope 的键只能从当前 candidateFieldContexts.sameTableColumnNames "
                    "复制裸列名；值必须逐字来自输入画像 topValues。字段说明、字段类别名和术语不能证明"
                    "具体取值；没有精确观测值时必须返回空对象"
                ),
                "additiveAcross 只声明跨该字段汇总不会重复计数的真实维度；组织层级并存时不得默认全部可加",
                "reconcileWith 只有在两个字段业务定义确实相同且输入提供依据时才声明，并同时提供 tolerance",
                "reason 使用简体中文说明判断依据和仍需人工确认的风险",
            ),
        )
        self._outline_agent = self._planning_agent(
            report_worker,
            "report-outline-planner",
            ReportOutlineProposal,
            thinking_profile=planner_off,
            stage_instructions=(
                *HOSPITAL_OUTLINE_INSTRUCTIONS,
                "只返回 reportType、中文报告标题、sections 和 assumptions；sections 不得提交 code",
                "每个章节必须引用一个或多个 outlineContext.analyses 中已注册的 analysisId",
                "按详细分析计划的重要性组织动态章节；未涉及或无数据领域不得生成空章",
                "section code 由服务端在批准后生成，模型不得提交或猜测 section_NNN",
            ),
        )
        self._analysis_agent = self._planning_agent(
            report_worker,
            "report-analysis-planner",
            AnalysisBundle,
            thinking_profile=planner_max,
            escalation_thinking_profile=planner_max,
            stage_instructions=(
                "一次返回完整分析计划和全部 requirements",
                "每个 analyses 项只回答一个原子管理问题，并且只声明一个主要指标族；复杂问题必须拆成多个分析项",
                "managementQuestion 写可直接回答的单一管理问题，primaryMetricFamily 写该项唯一的主要指标族",
                "每项 requirement 显式声明维度、指标、期间字段、期间粒度、共同粒度和表关系",
                "grainColumns 必须全部包含在 dimensionColumns 中",
                (
                    "measureColumns 只能复制 schemas[].measureSemantics[].fieldRef 最后一段中"
                    "已批准的数值指标；分类字段放入 dimensionColumns；某张表没有任何"
                    " measureSemantics 时不得为该表生成 requirement"
                ),
                "优先为每张表生成独立 requirement，由 analyses 引用多个单表 requirement 完成综合分析",
                "比较、差异和相关性分析默认引用多个单表 requirement，由后续分析组合，不为这些分析直接生成多表 SQL",
                "数据覆盖、缺失期间和局限性直接引用 observedDataFacts，不为这些叙述创建多表 requirement",
                "analyses[].description 只描述分析动作、比较方式和所引用 requirement，不复述数据覆盖、缺失期间、时间进度或事实结论",
                "单表 requirement 的 relations 必须为空；多表 requirement 的 relations 必须连接全部表",
                (
                    "仅当各表 periodGranularity 一致、全部 grainColumns 真实存在于每张表、"
                    "每条 relation.joinColumns 完整等于 grainColumns，且独立物化后无法完成目标时，"
                    "才可生成多表 requirement"
                ),
                "禁止为汇总展示强行拼接期间语义、事实粒度或关联键不兼容的表",
                "披露数据差异、期间缺失、零分母和口径限制，不做未授权推算",
                *HOSPITAL_ANALYSIS_INSTRUCTIONS,
            ),
        )
        self._sql_agent = self._planning_agent(
            report_worker,
            "report-sql-planner",
            GeneratedQueryBatch,
            thinking_profile=planner_off,
            escalation_thinking_profile=planner_max,
            stage_instructions=(
                "一次返回覆盖全部 requirements 的 SQL 批次",
                "每项只生成一条 SELECT 或只读 CTE",
                "每个 requirement 对 periodWindows 中每个唯一 queryWindowId 生成一条查询，并提交对应 periodRole",
                "每张表只使用该 periodRole 的完整精确期间并按共同粒度预聚合",
                "每个查询块的非聚合 SELECT 列和 GROUP BY 列必须逐项等于 grainColumns；只能额外 SELECT 聚合后的 measureColumns，不得把 dimensionColumns 全量带入",
                "多表 requirement 必须为每张表建立独立聚合 CTE，再按完整 relations.joinColumns 连接 CTE；禁止直接连接基础表",
                (
                    "queryExecutionModes 中标记 row_preserving_conflict_probe 的 requirement "
                    "必须直接 SELECT 全部 grainColumns 和原始 measureColumns，不得使用聚合函数、"
                    "GROUP BY、DISTINCT、ORDER BY 或 LIMIT"
                ),
            ),
        )

    @staticmethod
    def _planning_agent(
        planner: Agent,
        agent_id: str,
        output_schema: type[BaseModel],
        *,
        thinking_profile: ReportingThinkingProfile,
        escalation_thinking_profile: ReportingThinkingProfile | None = None,
        thinking_escalation_fields: tuple[str, ...] = ("correction",),
        stage_instructions: tuple[str, ...] = (),
    ) -> Agent:
        if not isinstance(planner.model, OpenAIChat):
            raise TypeError("Report planner requires OpenAIChat")
        planner_model = copy(planner.model)
        apply_reporting_thinking_profile(planner_model, thinking_profile)
        planner_model.top_p = 1.0
        planner_model.retries = 0
        planner_model.exponential_backoff = False
        setattr(
            planner_model,
            "_report_escalation_thinking_profile",
            escalation_thinking_profile,
        )
        setattr(planner_model, "_report_thinking_escalation_fields", thinking_escalation_fields)

        def validate_response(content: Any) -> BaseModel:
            candidate = _planner_candidate(content)
            if output_schema is AnalysisBundle:
                candidate = _normalize_analysis_bundle_table_refs(candidate)
            return output_schema.model_validate(candidate)

        setattr(planner_model, "_report_response_validator", validate_response)
        agent = planner.deep_copy(
            update={
                "id": agent_id,
                # ID 供状态恢复、日志关联和代码判断；name 只负责面向用户的 Trace 展示。
                "name": _PLANNER_DISPLAY_NAMES.get(agent_id, agent_id),
                "role": "只根据已批准的结构、术语和画像生成结构化报表规划。",
                "model": planner_model,
                "retries": 2,
                "exponential_backoff": True,
                "instructions": [
                    f"实际输出契约：{_compact_output_schema(output_schema)}",
                    (
                        "上述契约已完整列出且与运行时 output_schema 同源；不得声称契约缺失或不可见，"
                        "不得按惯例猜测字段；只返回与其匹配的 JSON。"
                    ),
                    "不得输出分析过程、解释、Markdown 或 schema 之外的字段。",
                    "字符串字段只写最终可用的业务值；不得写占位符、变量名、生成过程或修正元数据。",
                    "发现候选值错误时直接替换或删除；不得把 correction、removed、clean 等修正标记追加到字段值或数组。",
                    "不得虚构字段、数据或结论。",
                    "不得输出连接信息，不得调用工具，不得执行 SQL。",
                    *stage_instructions,
                ],
                "tools": [],
                "skills": None,
                "tool_choice": None,
                "output_schema": output_schema,
                "parse_response": True,
                "telemetry": False,
                "post_hooks": [],
                # 规划步骤的输入由 Workflow 每次完整签发，既不依赖历史，也不消费会话
                # 摘要。若从 Coding Worker 继承摘要配置，Agno 会在每次大目录分析后再次
                # 把整份输入交给摘要模型，即使摘要从未加入下一次规划上下文。这既增加
                # 成本和延迟，也扩大了无意义的数据暴露面，因此在复制边界显式关闭。
                "enable_session_summaries": False,
                "add_session_summary_to_context": False,
                "session_summary_manager": None,
                "add_session_state_to_context": False,
            }
        )
        agent.num_history_runs = None
        return agent

    def workflow(self):
        async def finalize_publication(
            step_input: StepInput, run_context: RunContext
        ) -> StepOutput:
            # 发布门禁和外部签发共用一个可观察步骤，但保留明确的先后顺序：
            # publish_report 先重新核对产物、血缘和快照，只有门禁允许时才调用
            # issuer。这样减少一次 Workflow 状态恢复，不会把副作用提前到验收之前。
            gate_output = await self.publish_report(step_input, run_context)
            content = gate_output.content
            if not isinstance(content, dict):
                raise ReportingError("report_publication_invalid", "报表发布产物无效。")
            if content.get("formalReleaseAllowed") is False:
                if self.download_grants is not None:
                    # AgentOS 的正式交付只承诺持久化后的公开下载 URL。门禁失败时
                    # sandbox 路径既不是 HTTP 下载地址，也可能随终态回收失效，
                    # 因此不得把它作为完成回执暴露给 facade 或前端。
                    gate = content.get("publicationGate")
                    raw_issues = gate.get("issues") if isinstance(gate, dict) else None
                    issue_codes = tuple(
                        dict.fromkeys(
                            str(item.get("code"))
                            for item in (raw_issues if isinstance(raw_issues, list) else ())
                            if isinstance(item, dict)
                            and isinstance(item.get("code"), str)
                            and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", item["code"])
                        )
                    )[:10]
                    diagnostic = ", ".join(issue_codes) or "unknown"
                    logger.warning(
                        "report_publication_blocked issue_codes=%s issue_count=%d",
                        diagnostic,
                        len(raw_issues) if isinstance(raw_issues, list) else 0,
                    )
                    raise ReportingError(
                        "report_publication_blocked",
                        f"报告未通过正式发布门禁，未生成下载链接。问题代码：{diagnostic}。",
                    )
                return StepOutput(
                    content={
                        "status": "formal_release_blocked",
                        "reportId": content.get("reportId"),
                        "revision": content.get("revision"),
                        "path": content.get("pdfPath"),
                        "size": content.get("pdfSize"),
                        "sha256": content.get("pdfSha256"),
                        "word": {
                            "path": content.get("wordPath"),
                            "size": content.get("wordSize"),
                            "sha256": content.get("wordSha256"),
                        },
                        "publicationGate": content.get("publicationGate"),
                        "sourceWarnings": content.get("sourceWarnings", []),
                        "codingReceipts": content.get("codingReceipts", []),
                    }
                )
            scope = self._scope(run_context)
            if self.download_grants is not None:
                published = await self.issue_http_publication(
                    thread_id=scope["threadId"],
                    user_id=scope["userId"],
                    workflow_session_id=run_context.session_id,
                    workflow_run_id=run_context.run_id,
                    output=content,
                )
            else:
                published = await self.issue_workspace_publication(
                    thread_id=scope["threadId"],
                    output=content,
                )
            published["publicationGate"] = content.get("publicationGate")
            return StepOutput(content=published)

        return create_reporting_workflow(
            db=self.db,
            normalize_report_request=self.normalize_report_request,
            confirm_source=self.confirm_source,
            prepare_data_profile=self.prepare_data_profile,
            propose_measure_semantics=self.propose_measure_semantics,
            commit_measure_semantics=self.commit_measure_semantics,
            generate_outline=self.generate_outline,
            generate_analysis_plan=self.generate_analysis_plan,
            generate_query_candidates=self.generate_query_candidates,
            materialize_datasets=self.materialize_datasets,
            prepare_analysis_context=self.prepare_analysis_context,
            generate_detailed_analysis_plan=self.generate_detailed_analysis_plan,
            run_coding_analysis=self.run_coding_analysis,
            validate_report=self.validate_report,
            finalize_publication=finalize_publication,
        )

    async def normalize_report_request(
        self, step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        if run_context.session_state is None:
            run_context.session_state = {}
        state = self._state(run_context)
        workflow_input = (
            parse_reporting_workflow_input(step_input.input)
            if isinstance(step_input.input, str)
            else ReportingWorkflowInput.model_validate(step_input.input)
        )
        request = workflow_input.request()
        feedback = self._feedback(step_input)
        if isinstance(request, ReportRequestEnvelope):
            explicit_type = request.report_type
            resolution = resolve_domain_mentions(f"{request.report_goal}\n{feedback or ''}")
            if (
                request.domains is None
                and resolution.is_ambiguous
                and explicit_type != "comprehensive"
            ):
                return StepOutput(
                    content={"clarificationQuestion": "请明确主分析领域：全成本或费控。"}
                )
            domains = request.domains or (
                DOMAIN_CODES
                if explicit_type == "comprehensive" and resolution.is_ambiguous
                else resolution.selected or None
            )
            report_type = _resolved_report_type(explicit_type, domains)
            if report_type == "comprehensive" and domains is None:
                domains = DOMAIN_CODES
            request = request.model_copy(
                update={
                    "domains": domains,
                    "report_type": report_type,
                }
            )
            self._record_request_context(state, request.report_goal, feedback)
            self._record_normalized_request(state, request)
            return StepOutput(
                content=request.model_dump(mode="json", by_alias=True, exclude_none=True)
            )

        assert isinstance(request, ReportPromptInput)
        self._record_request_context(state, request.prompt, feedback)
        explicit_type = _explicit_report_type(request.prompt, feedback)
        resolution = resolve_domain_mentions(f"{request.prompt}\n{feedback or ''}")
        if resolution.is_ambiguous and explicit_type != "comprehensive":
            return StepOutput(content={"clarificationQuestion": "请明确主分析领域：全成本或费控。"})
        prompt_payload: dict[str, Any] = {"prompt": request.prompt}
        if feedback:
            prompt_payload["supplement"] = feedback
        normalized = await self._run_planner(self._request_normalizer, prompt_payload, run_context)
        assert isinstance(normalized, NormalizedReportPrompt)
        period = _single_explicit_year(request.prompt, feedback) or normalized.period
        missing: list[str] = []
        if period is None:
            missing.append(normalized.clarification_question or "请明确唯一的分析期间。")
        if missing:
            return StepOutput(content={"clarificationQuestion": " ".join(missing)})
        assert period is not None
        domains = DOMAIN_CODES if explicit_type == "comprehensive" else resolution.selected or None
        report_type = _resolved_report_type(explicit_type or normalized.report_type, domains)
        if report_type == "comprehensive" and domains is None:
            domains = DOMAIN_CODES
        envelope = ReportRequestEnvelope.from_untrusted(
            {
                "version": "1",
                "reportGoal": request.prompt,
                "reportType": report_type,
                **({"domains": domains} if domains else {}),
                "period": period.model_dump(mode="json"),
            }
        )
        self._record_normalized_request(state, envelope)
        return StepOutput(
            content=envelope.model_dump(mode="json", by_alias=True, exclude_none=True)
        )

    @staticmethod
    def _record_request_context(
        state: dict[str, Any], original_goal: str, feedback: str | None
    ) -> None:
        current = state.get(REPORT_REQUEST_CONTEXT_STATE_KEY)
        if not isinstance(current, dict):
            current = {"originalGoal": original_goal, "feedback": []}
            state[REPORT_REQUEST_CONTEXT_STATE_KEY] = current
        elif current.get("originalGoal") != original_goal:
            raise ReportingError(
                "report_context_restart_required", "原始报告目标已变化，必须重新发起。"
            )
        values = current.get("feedback")
        if not isinstance(values, list):
            raise ReportingError("report_workflow_state_invalid", "报表请求语境状态无效。")
        if feedback:
            values.append(
                {
                    "sequence": len(values) + 1,
                    "stage": "request_supplement",
                    "content": feedback,
                }
            )

    @staticmethod
    def _record_normalized_request(state: dict[str, Any], envelope: ReportRequestEnvelope) -> None:
        current = state.get(REPORT_REQUEST_CONTEXT_STATE_KEY)
        if not isinstance(current, dict):
            raise ReportingError("report_workflow_state_invalid", "报表请求语境状态无效。")
        current.update(
            {
                "reportType": envelope.report_type,
                "domains": list(envelope.domains) if envelope.domains else None,
                "primaryDomain": envelope.domains[0] if envelope.domains else None,
                "period": envelope.period.model_dump(mode="json"),
                "comparisonRoles": list(envelope.comparison_roles),
            }
        )

    async def cleanup_terminal(
        self, scope: dict[str, str], _workflow_session_id: str, workflow_run_id: str
    ) -> None:
        durable = await complete_cleanup(self.state_repository.get(workflow_run_id))
        stored_checkpoint = (
            durable.payload.get("workflowCheckpoint") if durable is not None else None
        )
        task_ids: tuple[str, ...] = ()
        if stored_checkpoint is not None:
            checkpoint = ReportingCheckpoint.model_validate(stored_checkpoint)
            task_ids = tuple(
                dict.fromkeys(item.task_id for item in checkpoint.trace if item.task_id)
            )

        # phase task 的 ID 包含 revision、work item 和 attempt，不能由 Workflow run ID
        # 反推。必须以启动任务前持久化的 trace 为事实来源，并在全部活动任务关闭后
        # 才删除共享 sandbox；任一查询或取消失败都保留现场供后续重试清理。
        task_cleanup_error: Exception | None = None
        for task_id in task_ids:
            try:
                task = await complete_cleanup(
                    self.task_runner.repository.get_task_snapshot(task_id)
                )
                if task is not None and task.state not in {
                    TaskState.COMPLETED,
                    TaskState.FAILED,
                    TaskState.CANCELLED,
                }:
                    await complete_cleanup(self.task_runner.cancel(task.scope))
            except Exception as error:
                task_cleanup_error = task_cleanup_error or error
        if task_cleanup_error is not None:
            raise task_cleanup_error
        try:
            await complete_cleanup(self.workspace_service.adestroy(scope["thread_id"]))
        except Exception as error:
            raise ReportingError(
                "report_sandbox_cleanup_failed",
                "报表工作流已结束，但运行环境删除失败，请重试清理。",
            ) from error

    async def issue_http_publication(
        self,
        *,
        thread_id: str,
        user_id: str,
        workflow_session_id: str,
        workflow_run_id: str,
        output: Any,
    ) -> dict[str, Any]:
        download_grants = self.download_grants
        artifact_persistence = self.artifact_persistence
        if download_grants is None or artifact_persistence is None:
            raise RuntimeError("HTTP 报表发布依赖配置不完整")
        report_public_base_url = self.report_public_base_url
        if report_public_base_url is None:
            raise RuntimeError("HTTP 报表发布缺少公开下载基址")
        content = self._publication_content(output)
        # 下载 grant 本身是 256 bit 随机 bearer 凭证。Scope 仅用于持久化产物身份、
        # 修订撤销和审计，不再作为下载时的调用方权限条件。
        download_scope = ReportDownloadScope(
            database="agentos",
            user_id=user_id,
            company_id="public",
            session_id=workflow_session_id,
            thread_id=thread_id,
            workflow_run_id=workflow_run_id,
        )
        await artifact_persistence.persist(
            scope=download_scope,
            report_id=content["reportId"],
            revision=content["revision"],
            artifacts=(
                ReportArtifactSpec(
                    artifact="pdf",
                    path=content["pdfPath"],
                    size=content["pdfSize"],
                    sha256=content["pdfSha256"],
                ),
                ReportArtifactSpec(
                    artifact="word",
                    path=content["wordPath"],
                    size=content["wordSize"],
                    sha256=content["wordSha256"],
                ),
            ),
        )
        try:
            await complete_cleanup(self.workspace_service.adestroy(thread_id))
        except Exception as error:
            raise ReportingError(
                "report_sandbox_cleanup_failed",
                "报告已持久化，但运行环境删除失败，请重试发布步骤。",
            ) from error
        # bearer 只能在所有可能失败的外部清理完成后签发；否则 Workflow 重试前
        # 调用方拿不到 token，但 token 已经有效。产物已经落库，签发失败后的重试
        # 可以在 sandbox 已删除的情况下直接复用持久化身份。
        raw, grant = await download_grants.issue(
            scope=download_scope,
            report_id=content["reportId"],
            revision=content["revision"],
            pdf_path=content["pdfPath"],
            pdf_size=content["pdfSize"],
            pdf_sha256=content["pdfSha256"],
            word_path=content["wordPath"],
            word_size=content["wordSize"],
            word_sha256=content["wordSha256"],
        )
        return publication_result(
            report_id=content["reportId"],
            revision=content["revision"],
            raw_grant=raw,
            grant=grant,
            base_url=report_public_base_url,
            source_warnings=content["sourceWarnings"],
            coding_receipts=content["codingReceipts"],
        )

    async def issue_workspace_publication(
        self,
        *,
        thread_id: str,
        output: Any,
    ) -> dict[str, Any]:
        content = self._publication_content(output)
        current_pdf = await self.workspace_service.ahash_file(thread_id, content["pdfPath"])
        current_word = await self.workspace_service.ahash_file(thread_id, content["wordPath"])
        self._require_artifact_identity(content, current_pdf, artifact="pdf")
        self._require_artifact_identity(content, current_word, artifact="word")
        return cli_result(
            path=content["pdfPath"],
            size=content["pdfSize"],
            sha256=content["pdfSha256"],
            word_path=content["wordPath"],
            word_size=content["wordSize"],
            word_sha256=content["wordSha256"],
            source_warnings=content["sourceWarnings"],
            coding_receipts=content["codingReceipts"],
        )

    async def confirm_source(self, step_input: StepInput, run_context: RunContext) -> StepOutput:
        envelope = ReportRequestEnvelope.from_untrusted(
            step_input.previous_step_content
            if step_input.previous_step_content is not None
            else step_input.input
        )
        source_ids = envelope.source_ids or self.registry.require_defaults()
        configured = require_sources(self.registry.sources, source_ids)
        sources = tuple(self._starrocks_source(item) for item in configured)
        profile = self._resolve_profile(sources)
        metadata = None
        selected_agent = None
        if self.metadata_client is not None:
            selected_agent = await self.metadata_client.query_agent()
            metadata = await self.metadata_client.query_model(
                agent_id=selected_agent.code,
                sources=configured,
            )

        snapshots: list[SourceSchemaSnapshot] = []
        previews: list[dict[str, Any]] = []
        for source in sources:
            scope_tables = _schema_scope_tables(envelope, source=source, metadata=metadata)
            allowed_tables = tuple(
                f"{table.database.lower()}.{table.name.lower()}" for table in scope_tables
            )
            adapter = StarRocksDataSourceAdapter(source, allowed_tables=allowed_tables)
            try:
                catalog = tuple(_model_table(item) for item in await adapter.catalog())
            finally:
                await adapter.aclose()
            snapshot = resolve_schema_snapshot(
                envelope,
                source=source,
                metadata=metadata,
                catalog=catalog,
                profile_measure_semantics=profile.measure_semantics,
            )
            snapshots.append(snapshot)
            previews.append(
                {
                    "sourceId": source.id,
                    "name": source.name,
                    "database": source.database,
                    "allowedTables": list(allowed_tables),
                    "metadataRevision": snapshot.revision,
                    "schemaHash": snapshot.schema_hash,
                    "reportingProfile": profile.profile_id,
                    "effectiveProfileHash": profile.effective_profile_hash,
                }
            )

        snapshots = list(_apply_profile_scope_filters_to_snapshots(tuple(snapshots), profile))
        if any(source.id == "rj" for source in sources):
            _validate_hospital_operation_profile_schema(ruijin_profile(), tuple(snapshots))
        state = self._state(run_context)
        workflow_input = envelope.workflow_payload(
            default_source_ids=self.registry.default_source_ids
        )
        workflow_input.pop("schemaInput", None)
        state[REPORT_WORKFLOW_INPUT_STATE_KEY] = workflow_input
        state[REPORT_SCHEMA_SNAPSHOTS_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in snapshots
        ]
        state[REPORT_EFFECTIVE_PROFILE_STATE_KEY] = profile.model_dump(mode="json", by_alias=True)
        # 元数据 Agent 只用于本步服务端查询；report_workflow_input 是后续各步
        # 反序列化的公开请求契约，不能写入未声明的 agentId 等内部字段。
        self._assert_state_safe(state)
        return StepOutput(content={"sources": previews})

    async def plan_data_scope(self, _step_input: StepInput, run_context: RunContext) -> StepOutput:
        envelope = self._envelope(run_context)
        snapshots = self._snapshots(run_context)
        base_payload = {
            "reportGoal": envelope.report_goal,
            "period": envelope.period.model_dump(mode="json"),
            "periodWindows": envelope.period_windows().public_dict(),
            "domains": list(envelope.domains or ()),
            "schemas": _planning_schema_payload(snapshots),
        }
        previous_output: Any = None
        validation_feedback: dict[str, Any] | None = None
        for attempt in range(1, 6):
            payload = dict(base_payload)
            if validation_feedback is not None:
                payload["correction"] = {
                    "attempt": attempt,
                    "validationFeedback": _compact_validation_feedback(validation_feedback),
                    "instruction": (
                        "修正所有 issues；直接替换错误值，不把修正说明或标记写入字段；"
                        "返回完整 JSON，不返回补丁、解释或 Markdown"
                    ),
                }
            output = await self._run_planner(
                self._data_understanding_agent,
                payload,
                run_context,
            )
            plan, previous_output, validation_feedback = _data_understanding_result(
                output, snapshots
            )
            if plan is None:
                continue
            state = self._state(run_context)
            state[REPORT_DATA_UNDERSTANDING_STATE_KEY] = plan.model_dump(mode="json", by_alias=True)
            self._assert_state_safe(state)
            return StepOutput(content=plan)

        diagnostic = {
            "previousOutput": _bounded_rejected_value(previous_output),
            "validationFeedback": _compact_validation_feedback(validation_feedback),
        }
        raise ReportingError(
            "report_data_understanding_invalid",
            "数据理解计划连续五次未通过校验。最后一次诊断："
            + json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":"), default=str),
        )

    async def prepare_data_profile(
        self, step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        """在一个 Workflow 边界内先确定画像范围，再执行受限数据画像。

        两个内部动作仍保持独立实现和状态写入顺序：画像只能读取已通过校验的数据理解
        计划，后续语义候选也只能消费完整 DataShape。合并的是外部状态转换，不是数据
        探查权限或失败语义；任一动作失败都会让当前步骤失败关闭，不能继续到指标语义。
        """
        plan_output = await self.plan_data_scope(step_input, run_context)
        profile_output = await self.profile_source(
            StepInput(previous_step_content=plan_output.content), run_context
        )
        profile_content = (
            profile_output.content.model_dump(mode="json", by_alias=True)
            if isinstance(profile_output.content, BaseModel)
            else profile_output.content
        )
        # 数据理解计划已写入受信 session_state，后续步骤都从 state 读取；StepOutput
        # 只保留原画像步骤的紧凑结果，避免合并后把同一计划再次带入下一步上下文。
        return StepOutput(content=profile_content)

    async def profile_source(self, _step_input: StepInput, run_context: RunContext) -> StepOutput:
        envelope = self._envelope(run_context)
        snapshots = self._snapshots(run_context)
        selected_source_ids = {
            item.source_id for item in self._data_understanding(run_context).tables
        }
        inputs = tuple(
            (snapshot.tables[0].source_id, snapshot)
            for snapshot in snapshots
            if snapshot.tables[0].source_id in selected_source_ids
        )
        sources = tuple(self._source(source_id) for source_id, _snapshot in inputs)
        global_limiter = anyio.CapacityLimiter(
            min(source.limits.profile_concurrency for source in sources)
        )
        shapes: list[DataShape | None] = [None] * len(inputs)
        errors: list[ReportingError | None] = [None] * len(inputs)

        async def profile(
            index: int,
            source: StarRocksSourceConfig,
            snapshot: SourceSchemaSnapshot,
        ) -> None:
            selected = tuple(
                item
                for item in self._data_understanding(run_context).tables
                if item.source_id == source.id
            )
            selected_names = {item.table.lower() for item in selected}
            selected_tables = tuple(
                table
                for table in snapshot.tables
                if f"{table.database.lower()}.{table.name.lower()}" in selected_names
            )
            allowed_tables = tuple(sorted(selected_names))
            adapter = StarRocksDataSourceAdapter(source, allowed_tables=allowed_tables)
            try:
                shapes[index] = await collect_data_shape(
                    adapter,
                    catalog_scope=_catalog_scope(selected_tables),
                    period_start=envelope.period.start,
                    period_end=envelope.period.end,
                    period_columns={item.table: item.period_column for item in selected},
                    period_granularities={item.table: item.period_granularity for item in selected},
                    metadata_revision=snapshot.revision,
                    schema_hash=snapshot.schema_hash,
                    global_limiter=global_limiter,
                )
            except ReportingError as error:
                errors[index] = error
                task_group.cancel_scope.cancel()
            finally:
                with anyio.CancelScope(shield=True):
                    await adapter.aclose()

        async with anyio.create_task_group() as task_group:
            for index, (source, (_source_id, snapshot)) in enumerate(
                zip(sources, inputs, strict=True)
            ):
                task_group.start_soon(profile, index, source, snapshot)
        if any(errors):
            raise next(error for error in errors if error is not None)
        completed = [shape for shape in shapes if shape is not None]
        if len(completed) != len(inputs):
            raise ReportingError("report_data_shape_failed", "数据画像采集结果不完整。")
        state = self._state(run_context)
        state[REPORT_DATA_SHAPES_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in completed
        ]
        self._assert_state_safe(state)
        return StepOutput(content={"dataShapes": state[REPORT_DATA_SHAPES_STATE_KEY]})

    async def propose_measure_semantics(
        self, step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        snapshots = self._snapshots(run_context)
        plan = self._data_understanding(run_context)
        profile = self._profile(run_context)
        candidate_refs = _measure_semantic_candidate_refs(snapshots, plan, profile)
        if not candidate_refs:
            # API/Profile 已覆盖全部候选，或剩余数值字段已经由 Profile 明确声明为维度。
            # 此分支不调用模型，HumanReview 谓词也会返回 False，因此不会制造无意义暂停。
            return StepOutput(content=MeasureSemanticProposal())

        selected_tables = {item.table for item in plan.tables}
        tables_by_ref = {
            (table.source_id.lower(), table.database.lower(), table.name.lower()): table
            for snapshot in snapshots
            for table in snapshot.tables
        }
        candidate_contexts = []
        for field_ref in candidate_refs:
            parsed = parse_field_ref(field_ref)
            table = tables_by_ref[(parsed.source_id.lower(), parsed.database, parsed.table)]
            candidate_contexts.append(
                {
                    "fieldRef": field_ref,
                    "sameTableColumnNames": [
                        column.name
                        for column in table.columns
                        if column.name.lower() != parsed.column
                    ],
                }
            )
        base_payload: dict[str, Any] = {
            "reportGoal": self._envelope(run_context).report_goal,
            "candidateFieldRefs": list(candidate_refs),
            "candidateFieldContexts": candidate_contexts,
            "schemas": _planning_schema_payload(snapshots, tables=selected_tables),
            "terms": [
                item.model_dump(mode="json", by_alias=True)
                for snapshot in snapshots
                for item in snapshot.terms
            ],
            "dataShapes": [
                item.model_dump(mode="json", by_alias=True)
                for item in self._data_shapes(run_context)
            ],
            "scopeFilters": [
                item.model_dump(mode="json", by_alias=True) for item in profile.scope_filters
            ],
        }
        review_feedback = self._feedback(step_input)
        if review_feedback:
            base_payload["userReviewFeedback"] = review_feedback

        previous_output: Any = None
        validation_feedback: dict[str, Any] | None = None
        for attempt in range(1, 6):
            payload = dict(base_payload)
            if validation_feedback is not None:
                payload["correction"] = {
                    "attempt": attempt,
                    "validationFeedback": _compact_validation_feedback(validation_feedback),
                    "instruction": (
                        "逐项修正 issues，并重新返回 candidateFieldRefs 的完整分类；"
                        "不得删除候选、增加字段、返回补丁或解释性 Markdown"
                    ),
                }
            proposal = await self._run_planner(
                self._measure_semantic_agent,
                payload,
                run_context,
            )
            assert isinstance(proposal, MeasureSemanticProposal)
            try:
                _validate_proposed_exclusive_scopes(proposal, self._data_shapes(run_context))
                proposal = _proposal_with_profile_scope_filters(proposal, snapshots, profile)
            except ReportingError as error:
                previous_output = proposal.model_dump(mode="json", by_alias=True)
                validation_feedback = {
                    "issues": [
                        {
                            "path": "decisions",
                            "rejectedValue": previous_output,
                            "reason": error.message,
                            "requiredAction": "不得覆盖 Profile 强制范围，按 scopeFilters 重新生成完整候选",
                        }
                    ]
                }
                continue
            try:
                # 这里只调用同一套确定性提交校验来验证候选，但不使用返回值，也不写 state。
                # 用户在 Agno Output Review 中看到的对象，因此与批准后真正提交的对象完全同构。
                _apply_confirmed_measure_semantics(snapshots, proposal, candidate_refs)
            except ReportingError as error:
                previous_output = proposal.model_dump(mode="json", by_alias=True)
                validation_feedback = {
                    "issues": [
                        {
                            "path": "decisions",
                            "rejectedValue": previous_output,
                            "reason": error.message,
                            "allowedValues": list(candidate_refs),
                            "requiredAction": "完整分类 allowedValues，且只使用结构快照内的字段和值",
                        }
                    ]
                }
                continue
            return StepOutput(content=proposal)

        diagnostic = {
            "previousOutput": _bounded_rejected_value(previous_output),
            "validationFeedback": _compact_validation_feedback(validation_feedback),
        }
        raise ReportingError(
            "report_measure_semantic_proposal_invalid",
            "指标语义候选连续五次未通过校验。最后一次诊断："
            + json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":"), default=str),
        )

    async def commit_measure_semantics(
        self, step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        try:
            proposal = MeasureSemanticProposal.model_validate(step_input.previous_step_content)
        except Exception as error:
            raise ReportingError(
                "report_measure_semantic_proposal_invalid", "已审核指标语义候选无效。"
            ) from error
        snapshots = self._snapshots(run_context)
        candidate_refs = _measure_semantic_candidate_refs(
            snapshots,
            self._data_understanding(run_context),
            self._profile(run_context),
        )
        profile = self._profile(run_context)
        _validate_proposed_exclusive_scopes(
            proposal,
            self._data_shapes(run_context),
            trusted_profile=profile,
        )
        scoped_proposal = _proposal_with_profile_scope_filters(proposal, snapshots, profile)
        if scoped_proposal != proposal:
            raise ReportingError(
                "report_measure_semantic_proposal_invalid",
                "已审核指标语义候选缺少 Profile 强制范围或与其冲突。",
            )
        # 不信任上一步输出中隐含的候选范围。提交时依据当前已持久化快照重新计算，
        # 要求审核对象与待定字段精确相等；缺项、增项、重复项和未知字段全部失败关闭。
        updated = _apply_confirmed_measure_semantics(snapshots, proposal, candidate_refs)
        state = self._state(run_context)
        state[REPORT_SCHEMA_SNAPSHOTS_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in updated
        ]
        self._assert_state_safe(state)
        confirmed = [
            decision.measure_semantic.model_dump(mode="json", by_alias=True)
            for decision in proposal.decisions
            if decision.measure_semantic is not None
        ]
        return StepOutput(content={"measureSemantics": confirmed})

    async def resolve_capabilities(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        capabilities = resolve_profile_capabilities(
            self._profile(run_context),
            self._snapshots(run_context),
            self._data_shapes(run_context),
        )
        state = self._state(run_context)
        state[REPORT_CAPABILITIES_STATE_KEY] = capabilities.model_dump(mode="json", by_alias=True)
        self._assert_state_safe(state)
        return StepOutput(content=capabilities)

    async def generate_outline(self, step_input: StepInput, run_context: RunContext) -> StepOutput:
        state = self._state(run_context)
        envelope = self._envelope(run_context)
        if envelope.report_type is None:
            raise ReportingError("report_type_required", "报告类型尚未确认。")
        feedback = self._feedback(step_input)
        self._record_outline_feedback(state, feedback)
        try:
            detailed_plan = DetailedAnalysisPlan.model_validate(
                state.get(REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY)
            )
        except Exception as error:
            raise ReportingError(
                "report_detailed_analysis_plan_invalid",
                "动态提纲缺少有效的详细分析计划。",
            ) from error
        if not detailed_plan.analyses:
            raise ReportingError(
                "report_detailed_analysis_plan_unavailable",
                "没有可供动态提纲引用的分析任务。",
            )
        outline_context = {
            "reportType": envelope.report_type,
            "domains": list(envelope.domains or ()),
            "analyses": [
                item.model_dump(mode="json", by_alias=True) for item in detailed_plan.analyses
            ],
            "dataShapes": state.get(REPORT_DATA_SHAPES_STATE_KEY, []),
            "warnings": list(detailed_plan.warnings),
            "requestContext": dict(state.get(REPORT_REQUEST_CONTEXT_STATE_KEY) or {}),
        }
        base_payload = {
            "reportGoal": envelope.report_goal,
            "reportType": envelope.report_type,
            "period": envelope.period.model_dump(mode="json"),
            "outlineContext": outline_context,
            "feedback": feedback,
        }
        validation_feedback: dict[str, Any] | None = None
        previous_output: dict[str, Any] | None = None
        allowed_paths: tuple[str, ...] = ()
        outline: ReportOutline | None = None
        for attempt in range(1, 6):
            payload: dict[str, Any] = dict(base_payload)
            if validation_feedback is not None:
                payload["correction"] = {
                    "attempt": attempt,
                    "previousOutput": previous_output,
                    "allowedPaths": list(allowed_paths),
                    "validationFeedback": _compact_validation_feedback(validation_feedback),
                    "instruction": (
                        "修正全部 issues 并返回完整 ReportOutlineProposal；sections 不得包含 code，"
                        "每个章节必须引用已注册 analysisId；不返回正文、解释或 Markdown"
                    ),
                }
            output = await self._run_planner(self._outline_agent, payload, run_context)
            assert isinstance(output, ReportOutlineProposal)
            issues: list[dict[str, Any]] = []
            if output.report_type != envelope.report_type:
                issues.append(
                    {
                        "path": "reportType",
                        "rejectedValue": output.report_type,
                        "allowedValues": [envelope.report_type],
                        "reason": "提纲报告类型必须与已确认请求一致",
                    }
                )
            if issues:
                previous_output = output.model_dump(mode="json", by_alias=True)
                allowed_paths = tuple(str(item["path"]) for item in issues)
                validation_feedback = {
                    "code": "report_outline_invalid",
                    "summary": "报告提纲违反动态章节契约",
                    "issues": issues,
                }
                continue
            try:
                outline = freeze_outline(output, analyses=detailed_plan.analyses)
            except ValueError as error:
                previous_output = output.model_dump(mode="json", by_alias=True)
                allowed_paths = ("sections",)
                validation_feedback = {
                    "code": "report_outline_invalid",
                    "summary": "报告提纲引用的分析未通过服务端冻结校验",
                    "issues": [{"path": "sections", "reason": str(error)}],
                }
                continue
            break
        if outline is None:
            raise ReportingError(
                "report_outline_invalid",
                "报告提纲连续五次未通过校验。最后一次反馈："
                + json.dumps(
                    _compact_validation_feedback(validation_feedback),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        state[REPORT_OUTLINE_STATE_KEY] = outline.model_dump(mode="json", by_alias=True)
        state[REPORT_OUTLINE_HASH_STATE_KEY] = _payload_sha256(state[REPORT_OUTLINE_STATE_KEY])
        self._assert_state_safe(state)
        return StepOutput(content=outline)

    @staticmethod
    def _record_outline_feedback(state: dict[str, Any], feedback: str | None) -> None:
        if not feedback:
            return
        current = state.get(REPORT_REQUEST_CONTEXT_STATE_KEY)
        if not isinstance(current, dict) or not isinstance(current.get("feedback"), list):
            raise ReportingError("report_workflow_state_invalid", "报表请求语境状态无效。")
        values = current["feedback"]
        values.append(
            {
                "sequence": len(values) + 1,
                "stage": "outline_feedback",
                "content": feedback,
            }
        )

    async def generate_analysis_plan(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        state = self._state(run_context)
        snapshots = self._snapshots(run_context)
        data_understanding = DataUnderstandingPlan.model_validate(
            state[REPORT_DATA_UNDERSTANDING_STATE_KEY]
        )
        # 报表能力是 Profile/Schema 的确定性投影，不需要独立的 Workflow 状态转换。
        # 在生成分析计划前重新计算并持久化，保证恢复运行时不会信任旧的能力快照，且
        # Planner 仍能看到与当前结构快照一致的能力集合。
        await self.resolve_capabilities(_step_input, run_context)
        profile = self._profile(run_context)
        analysis_context = build_outline_shape_view(
            profile,
            self._capabilities(run_context),
            snapshots,
            self._data_shapes(run_context),
            tuple(
                ReconciliationShape(
                    code=item.code,
                    status="unavailable",
                    leftMetric=item.left_metric,
                    rightMetric=item.right_metric,
                    grain=item.grain,
                    issues=("等待语义事实物化后执行服务端对账。",),
                )
                for item in profile.reconciliations
            ),
        )
        base_payload = {
            "reportGoal": self._envelope(run_context).report_goal,
            "domains": list(self._envelope(run_context).domains or ()),
            "periodWindows": self._envelope(run_context).period_windows().public_dict(),
            "analysisSequence": [
                "整体规模与结构",
                "趋势与拐点",
                "异常贡献",
                "归因验证",
                "经营影响",
            ],
            "analysisContext": _analysis_context_payload(analysis_context),
            "dataUnderstanding": state[REPORT_DATA_UNDERSTANDING_STATE_KEY],
            "schemas": _planning_schema_payload(
                snapshots,
                tables={item.table for item in data_understanding.tables},
                description_limit=160,
            ),
        }
        validation_feedback: dict[str, Any] | None = None
        previous_output: dict[str, Any] | None = None
        allowed_mutation_paths: tuple[str, ...] = ()
        required_deletion_paths: tuple[str, ...] = ()
        last_semantic_correction_signature: str | None = None
        bundle: AnalysisBundle | None = None
        for attempt in range(1, 6):
            payload = dict(base_payload)
            if validation_feedback is not None:
                correction: dict[str, Any] = {
                    "attempt": attempt,
                    "validationFeedback": _compact_validation_feedback(validation_feedback),
                    "instruction": (
                        "修正所有 issues；直接替换错误值，不把修正说明或标记写入字段；"
                        "返回完整 AnalysisBundle JSON，不返回补丁、解释或 Markdown；"
                        "存在 previousOutput 时只能修改 allowedMutationPaths，其他字段必须原样保留"
                    ),
                }
                if previous_output is not None:
                    correction["previousOutput"] = previous_output
                    correction["allowedMutationPaths"] = list(allowed_mutation_paths)
                    if required_deletion_paths:
                        correction["requiredDeletionPaths"] = list(required_deletion_paths)
                        correction["instruction"] += (
                            "；requiredDeletionPaths 中的对象必须精确删除，不能改写、替换"
                            "或移动到其他字段；analysis 同时引用可用 requirement 时，只从"
                            " requirementIds 删除失效引用"
                        )
                payload["correction"] = correction
                logger.info(
                    "report_planner_correction agent_id=%s attempt=%s "
                    "previous_output_sha256=%s allowed_mutation_paths=%s "
                    "required_deletion_paths=%s issue_signature=%s",
                    getattr(self._analysis_agent, "id", "report-analysis-planner"),
                    attempt,
                    _payload_sha256(previous_output) if previous_output is not None else "none",
                    json.dumps(allowed_mutation_paths, ensure_ascii=True, separators=(",", ":")),
                    json.dumps(required_deletion_paths, ensure_ascii=True, separators=(",", ":")),
                    _payload_sha256(_compact_validation_feedback(validation_feedback)),
                )
            output = await self._run_planner(self._analysis_agent, payload, run_context)
            assert isinstance(output, AnalysisBundle)
            output_payload = output.model_dump(mode="json", by_alias=True)
            normalized_output, column_repairs = _normalize_requirement_columns(output, snapshots)
            if column_repairs:
                normalized_payload = normalized_output.model_dump(mode="json", by_alias=True)
                logger.info(
                    "report_planner_columns_normalized repairs=%s",
                    json.dumps(column_repairs, ensure_ascii=False, separators=(",", ":")),
                )
                output = normalized_output
                output_payload = normalized_payload
            normalized_output, period_repairs = _normalize_requirement_periods(
                output,
                self._data_understanding(run_context),
            )
            if period_repairs:
                normalized_payload = normalized_output.model_dump(mode="json", by_alias=True)
                logger.info(
                    "report_planner_periods_normalized repairs=%s",
                    json.dumps(period_repairs, ensure_ascii=False, separators=(",", ":")),
                )
                output = normalized_output
                output_payload = normalized_payload
            if previous_output is not None:
                try:
                    previous_bundle = AnalysisBundle.model_validate(previous_output)
                except ValidationError:
                    # AnalysisItem 的业务校验可能失败，但 requirements 已经各自满足
                    # 严格 Schema。纠错基线必须先应用与当前候选相同的确定性列规范化，
                    # 否则服务端自身删除的别名字段会被误判为模型越权修改。
                    previous_output = _normalize_requirement_columns_in_payload(
                        previous_output, snapshots
                    )
                else:
                    normalized_previous, _previous_column_repairs = _normalize_requirement_columns(
                        previous_bundle, snapshots
                    )
                    previous_output = normalized_previous.model_dump(mode="json", by_alias=True)
                unexpected_paths = _unexpected_correction_paths(
                    previous_output,
                    output_payload,
                    allowed_mutation_paths,
                    required_deletion_paths,
                )
                if unexpected_paths:
                    validation_feedback = {
                        "code": "report_correction_scope_violation",
                        "summary": "模型纠错修改了允许路径之外的字段",
                        "issues": [
                            {
                                "path": "$",
                                "rejectedValue": {"unexpectedPaths": unexpected_paths},
                                "reason": "纠错输出包含与当前 issues 无关的改动",
                                "allowedValues": list(allowed_mutation_paths),
                                "requiredAction": (
                                    "以 previousOutput 为基线，只修改 allowedMutationPaths 后返回完整输出"
                                ),
                            }
                        ],
                    }
                    logger.warning(
                        "report_planner_correction_scope_violation agent_id=%s attempt=%s "
                        "unexpected_paths=%s",
                        getattr(self._analysis_agent, "id", "report-analysis-planner"),
                        attempt,
                        json.dumps(unexpected_paths, ensure_ascii=True, separators=(",", ":")),
                    )
                    last_semantic_correction_signature = None
                    continue
            normalized_output, grain_repairs = _normalize_analysis_bundle_grain(output, snapshots)
            if grain_repairs:
                normalized_payload = normalized_output.model_dump(mode="json", by_alias=True)
                logger.info(
                    "report_planner_grain_normalized agent_id=%s before_sha256=%s "
                    "after_sha256=%s repairs=%s",
                    getattr(self._analysis_agent, "id", "report-analysis-planner"),
                    _payload_sha256(output_payload),
                    _payload_sha256(normalized_payload),
                    json.dumps(grain_repairs, ensure_ascii=True, separators=(",", ":")),
                )
                output = normalized_output
                output_payload = normalized_payload
            normalized_output, requirement_repairs = _normalize_duplicate_requirements(output)
            if requirement_repairs:
                normalized_payload = normalized_output.model_dump(mode="json", by_alias=True)
                logger.info(
                    "report_planner_requirements_normalized repairs=%s",
                    json.dumps(requirement_repairs, ensure_ascii=False, separators=(",", ":")),
                )
                output = normalized_output
                output_payload = normalized_payload
            normalized_output, comparison_repairs = _normalize_comparison_roles(
                output, self._envelope(run_context).comparison_roles
            )
            if comparison_repairs:
                normalized_payload = normalized_output.model_dump(mode="json", by_alias=True)
                logger.info(
                    "report_planner_comparison_roles_normalized repairs=%s",
                    json.dumps(comparison_repairs, ensure_ascii=False, separators=(",", ":")),
                )
                output = normalized_output
                output_payload = normalized_payload
            semantic_issues = _analysis_bundle_semantic_issues(
                output,
                self._data_understanding(run_context),
                snapshots,
                self._envelope(run_context),
            )
            if semantic_issues:
                validation_feedback = {
                    "code": "report_analysis_plan_invalid",
                    "summary": "分析计划不可执行或与数据理解计划不一致",
                    "issues": semantic_issues,
                }
                correction_signature = _payload_sha256(
                    {
                        "output": output_payload,
                        "feedback": _compact_validation_feedback(validation_feedback),
                    }
                )
                if correction_signature == last_semantic_correction_signature:
                    logger.warning(
                        "report_planner_no_progress agent_id=%s attempt=%s "
                        "output_sha256=%s issue_signature=%s",
                        getattr(self._analysis_agent, "id", "report-analysis-planner"),
                        attempt,
                        _payload_sha256(output_payload),
                        _payload_sha256(_compact_validation_feedback(validation_feedback)),
                    )
                    raise ReportingError(
                        "report_analysis_plan_invalid",
                        "分析计划纠错连续两次没有进展。最后一次反馈："
                        + json.dumps(
                            _compact_validation_feedback(validation_feedback),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )
                last_semantic_correction_signature = correction_signature
                previous_output = output_payload
                required_deletion_paths = _analysis_required_deletion_paths(
                    semantic_issues, previous_output
                )
                allowed_mutation_paths = _analysis_allowed_mutation_paths(
                    semantic_issues,
                    previous_output=previous_output,
                    required_deletion_paths=required_deletion_paths,
                )
                continue
            bundle = output
            break
        if bundle is None:
            raise ReportingError(
                "report_analysis_plan_invalid",
                "分析计划连续五次未通过校验。最后一次反馈："
                + json.dumps(
                    _compact_validation_feedback(validation_feedback),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        state[REPORT_ANALYSIS_PLAN_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in bundle.analyses
        ]
        state[REPORT_DATA_REQUIREMENTS_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in bundle.requirements
        ]
        state[REPORT_ROW_PRESERVING_REQUIREMENTS_STATE_KEY] = list(
            _row_preserving_requirement_ids(bundle.requirements, ruijin_profile())
        )
        return StepOutput(content=bundle)

    async def generate_query_candidates(
        self, step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        state = self._state(run_context)
        requirements = tuple(
            QueryRequirement.model_validate(item)
            for item in state[REPORT_DATA_REQUIREMENTS_STATE_KEY]
        )
        referenced_tables = {
            table.table for requirement in requirements for table in requirement.tables
        }
        base_payload = {
            "requirements": state[REPORT_DATA_REQUIREMENTS_STATE_KEY],
            "dataUnderstanding": state[REPORT_DATA_UNDERSTANDING_STATE_KEY],
            "schemas": _planning_schema_payload(
                self._snapshots(run_context),
                tables=referenced_tables,
            ),
            "period": self._envelope(run_context).period.model_dump(mode="json"),
            "periodWindows": self._envelope(run_context).period_windows().public_dict(),
            "feedback": self._feedback(step_input),
            "queryExecutionModes": [
                {
                    "requirementId": requirement_id,
                    "mode": "row_preserving_conflict_probe",
                }
                for requirement_id in state.get(REPORT_ROW_PRESERVING_REQUIREMENTS_STATE_KEY, ())
            ],
        }
        sources = {item.id: item for item in self._sources(run_context)}
        snapshots = self._snapshots(run_context)
        envelope = self._envelope(run_context)
        validation_feedback: dict[str, Any] | None = None
        approved: tuple[ApprovedQuery, ...] | None = None
        for attempt in range(1, 6):
            payload = dict(base_payload)
            if validation_feedback is not None:
                payload["correction"] = {
                    "attempt": attempt,
                    "validationFeedback": _compact_validation_feedback(validation_feedback),
                    "instruction": (
                        "修正所有 issues；返回覆盖全部 requirements 和唯一期间窗口的完整 SQL 批次 JSON，"
                        "每个查询只使用所属 periodRole 的精确窗口；直接替换错误值，不把修正说明或标记写入字段；"
                        "不返回补丁、解释或 Markdown"
                    ),
                }
            output = await self._run_planner(self._sql_agent, payload, run_context)
            assert isinstance(output, GeneratedQueryBatch)
            approved, issues = _approve_generated_queries(
                output,
                sources=sources,
                snapshots=snapshots,
                envelope=envelope,
                requirements=requirements,
                row_preserving_requirement_ids=tuple(
                    state.get(REPORT_ROW_PRESERVING_REQUIREMENTS_STATE_KEY, ())
                ),
            )
            if issues:
                validation_feedback = {
                    "code": "report_query_batch_invalid",
                    "summary": "SQL 批次未通过只读、范围或期间契约审核",
                    "issues": issues,
                }
                approved = None
                continue
            break
        if approved is None:
            raise ReportingError(
                "report_query_batch_invalid",
                "SQL 批次连续五次未通过校验。最后一次反馈："
                + json.dumps(
                    _compact_validation_feedback(validation_feedback),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        state[REPORT_APPROVED_QUERIES_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in approved
        ]
        return StepOutput(content={"queries": state[REPORT_APPROVED_QUERIES_STATE_KEY]})

    async def materialize_datasets(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        approved = tuple(
            ApprovedQuery.model_validate(item)
            for item in self._state(run_context)[REPORT_APPROVED_QUERIES_STATE_KEY]
        )
        adapters = {
            source.id: self._adapter(source, run_context) for source in self._sources(run_context)
        }
        try:
            handles, lineage = await self.datasets.materialize_batch(
                approved, adapters, run_context=self._tool_context(run_context)
            )
        finally:
            for adapter in adapters.values():
                await adapter.aclose()
        prepared = await self.report_tools.report_prepare_dataset(
            [item.dataset_id for item in handles], run_context=self._tool_context(run_context)
        )
        await self.report_tools.bind_page_layout(
            str(prepared["jobId"]),
            self._profile(run_context).page_layout.model_dump(mode="json", by_alias=True),
            run_context=self._tool_context(run_context),
        )
        state = self._state(run_context)
        datasets = [item.public_dict() for item in handles]
        state[REPORT_DATASET_LINEAGE_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in lineage
        ]
        state[REPORT_WORKFLOW_RESULT_STATE_KEY] = {
            "datasets": datasets,
            "jobId": prepared["jobId"],
            "revision": 0,
        }
        return StepOutput(content={"datasets": datasets, "jobId": prepared["jobId"]})

    async def prepare_analysis_context(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        """并发生成完整 Profile 文件，并只把同源模型视图保存在 Workflow state。"""
        state = self._state(run_context)
        result = self._workflow_result(state)
        handles = tuple(DatasetHandle.from_state(item) for item in result.get("datasets", ()))
        if not handles:
            raise ReportingError("report_analysis_context_unavailable", "没有可分析的数据集。")
        scope = self._scope(run_context)
        thread_id = scope["threadId"]
        run_id = str(run_context.run_id or "report")
        snapshots = self._snapshots(run_context)
        requirements = {
            item.requirement_id: item
            for item in (
                QueryRequirement.model_validate(value)
                for value in state.get(REPORT_DATA_REQUIREMENTS_STATE_KEY, ())
            )
        }
        try:
            cached_contexts = {
                item.dataset_id: item
                for item in (
                    DatasetAnalysisContext.model_validate(value)
                    for value in state.get(REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY, ())
                )
            }
        except (TypeError, ValueError, ValidationError) as error:
            raise ReportingError(
                "report_analysis_context_invalid", "已保存的分析数据上下文无效。"
            ) from error
        contexts: list[DatasetAnalysisContext | None] = [None] * len(handles)
        errors: list[Exception | None] = [None] * len(handles)
        profile_limiter = anyio.CapacityLimiter(2)
        source_warning_messages = tuple(
            str(item.message)
            for item in _source_warnings_from_state(state)
            if getattr(item, "message", None)
        )

        def profile_path(handle: DatasetHandle) -> str:
            return f"报表/分析计划/{run_id}/profiles/{handle.dataset_id}.profile.json"

        def cached_context(handle: DatasetHandle) -> DatasetAnalysisContext | None:
            candidate = cached_contexts.get(handle.dataset_id)
            if (
                candidate is None
                or candidate.path != handle.path
                or candidate.size != handle.size
                or candidate.sha256 != handle.sha256
                or candidate.row_count != handle.row_count
                or candidate.profile_file.path != profile_path(handle)
            ):
                return None
            return candidate

        async with self.workspace_service._async_client() as client:
            sandbox = await self.workspace_service._asandbox_for(client, thread_id)

            async def prepare_one(index: int, handle: DatasetHandle) -> None:
                started_at = time.monotonic()
                cache_hit = False
                try:
                    cached = cached_context(handle)
                    if cached is not None:
                        _relative_profile, profile_remote = self.workspace_service.normalize_path(
                            cached.profile_file.path, allow_root=False
                        )
                        try:
                            stored_profile = await self.workspace_service._adownload_file(
                                sandbox, profile_remote, cached.profile_file.size
                            )
                        except Exception:
                            stored_profile = b""
                        if (
                            len(stored_profile) == cached.profile_file.size
                            and hashlib.sha256(stored_profile).hexdigest()
                            == cached.profile_file.sha256
                        ):
                            contexts[index] = cached
                            cache_hit = True
                            return

                    _relative, remote = self.workspace_service.normalize_path(
                        handle.path, allow_root=False
                    )
                    content = await self.workspace_service._adownload_file(
                        sandbox, remote, handle.size
                    )
                    if (
                        len(content) != handle.size
                        or hashlib.sha256(content).hexdigest() != handle.sha256
                    ):
                        raise ReportingError("stale_dataset", "分析数据集已变化。")
                    requirement = requirements.get(handle.requirement_id)
                    # measureColumns 属于每个 RequirementTable，不是 QueryRequirement
                    # 顶层字段。这里按完整 fieldRef 绑定语义，避免多表存在同名指标时
                    # 把未授权表的语义混入当前不可变数据集上下文。
                    measure_field_refs = (
                        _requirement_measure_field_refs(requirement, snapshots)
                        if requirement is not None
                        else set()
                    )
                    requirement_tables = (
                        {table.table.lower() for table in requirement.tables}
                        if requirement is not None
                        else set()
                    )
                    profiled = await anyio.to_thread.run_sync(
                        lambda: profile_csv_dataset(
                            content,
                            dataset_id=handle.dataset_id,
                            path=handle.path,
                            expected_sha256=handle.sha256,
                            profile_path=profile_path(handle),
                            period_fields=(
                                tuple(
                                    dict.fromkeys(
                                        table.period_column for table in requirement.tables
                                    )
                                )
                                if requirement is not None
                                else ()
                            ),
                            schema={
                                "sourceId": handle.source_id,
                                "requirementId": handle.requirement_id,
                                "tables": [
                                    table.model_dump(mode="json", by_alias=True)
                                    for snapshot in snapshots
                                    for table in snapshot.tables
                                    if table.source_id == handle.source_id
                                    and (
                                        not requirement_tables
                                        or f"{table.database}.{table.name}".lower()
                                        in requirement_tables
                                        or table.name.lower() in requirement_tables
                                    )
                                ],
                            },
                            organization_grain=(
                                tuple(requirement.grain_columns) if requirement is not None else ()
                            ),
                            metric_semantics=tuple(
                                item.model_dump(mode="json", by_alias=True)
                                for snapshot in snapshots
                                for item in snapshot.measure_semantics
                                if item.field_ref.lower() in measure_field_refs
                            ),
                            source_warnings=source_warning_messages,
                        ),
                        limiter=profile_limiter,
                    )
                    # 生产 WorkspaceService 始终提供内容边界校验；极小的单元测试夹具
                    # 可以只实现读写原语，不应改变 Profile 或其哈希契约。
                    validate_content = getattr(self.workspace_service, "_validate_content", None)
                    if callable(validate_content):
                        validate_content(profiled.profile_content)
                    _relative_profile, profile_remote = self.workspace_service.normalize_path(
                        profiled.context.profile_file.path, allow_root=False
                    )
                    filesystem = getattr(sandbox, "fs", None)
                    if filesystem is not None and hasattr(filesystem, "upload_file"):
                        ensure_directory = getattr(
                            self.workspace_service, "_aensure_directory", None
                        )
                        if callable(ensure_directory):
                            await ensure_directory(sandbox, profile_remote.rsplit("/", 1)[0])
                        await filesystem.upload_file(profiled.profile_content, profile_remote)
                        stored_profile = await self.workspace_service._adownload_file(
                            sandbox, profile_remote, profiled.context.profile_file.size
                        )
                        if (
                            len(stored_profile) != profiled.context.profile_file.size
                            or hashlib.sha256(stored_profile).hexdigest()
                            != profiled.context.profile_file.sha256
                        ):
                            raise ReportingError(
                                "report_analysis_profile_changed",
                                "完整数据画像写入后发生变化。",
                            )
                    contexts[index] = profiled.context
                except Exception as error:
                    errors[index] = error
                finally:
                    context = contexts[index]
                    logger.info(
                        "report_dataset_profile dataset_id=%s row_count=%s profile_bytes=%s "
                        "model_view_bytes=%s duration_ms=%s cache_hit=%s",
                        handle.dataset_id,
                        context.row_count if context is not None else handle.row_count,
                        context.profile_file.size if context is not None else 0,
                        (
                            len(
                                json.dumps(
                                    context.profile_model_view,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                ).encode("utf-8")
                            )
                            if context is not None
                            else 0
                        ),
                        int((time.monotonic() - started_at) * 1000),
                        cache_hit,
                    )

            async with anyio.create_task_group() as task_group:
                for index, handle in enumerate(handles):
                    task_group.start_soon(prepare_one, index, handle)

        failure = next((item for item in errors if item is not None), None)
        if failure is not None:
            if isinstance(failure, ReportingError):
                raise failure
            raise ReportingError(
                "report_analysis_context_invalid", "CSV 数据集画像生成失败。"
            ) from failure
        completed_contexts = tuple(item for item in contexts if item is not None)
        if len(completed_contexts) != len(handles):
            raise ReportingError("report_analysis_context_invalid", "CSV 数据集画像结果不完整。")
        state[REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in completed_contexts
        ]
        try:
            coverage = build_profile_coverage_manifest(
                dataset_handles=[item.public_dict() for item in handles],
                dataset_contexts=state[REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY],
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ReportingError(
                "report_profile_coverage_invalid",
                "完整 Profile 没有精确覆盖全部授权数据集和字段。",
            ) from error
        state[REPORT_PROFILE_COVERAGE_STATE_KEY] = coverage.model_dump(mode="json", by_alias=True)
        self._assert_state_safe(state)
        return StepOutput(
            content={"datasetContexts": state[REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY]}
        )

    async def generate_detailed_analysis_plan(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        """把已批准分析范围与 Profile 索引编排成可执行计划。"""
        state = self._state(run_context)
        raw_contexts = state.get(REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY, ())
        if not raw_contexts:
            raise ReportingError("report_analysis_context_unavailable", "分析数据上下文缺失。")
        contexts = tuple(DatasetAnalysisContext.model_validate(value) for value in raw_contexts)
        try:
            profile_coverage = ProfileCoverageManifest.model_validate(
                state.get(REPORT_PROFILE_COVERAGE_STATE_KEY)
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ReportingError(
                "report_profile_coverage_invalid", "完整 Profile coverage 状态缺失或无效。"
            ) from error
        envelope = self._envelope(run_context)
        requested_domains = set(envelope.domains or DOMAIN_CODES)
        initial = tuple(
            AnalysisItem.model_validate(item)
            for item in state.get(REPORT_ANALYSIS_PLAN_STATE_KEY, ())
            if isinstance(item, dict)
        )
        if not initial:
            raise ReportingError("report_analysis_plan_invalid", "已批准分析计划缺失。")

        covered_domains: set[str] = set()
        for item in initial:
            if item.code in DOMAIN_CODES:
                covered_domains.add(item.code)
            covered_domains.update(
                resolve_domain_mentions(f"{item.code} {item.description}").selected
            )
        # 领域范围先服从步骤 9 的已批准计划；只有步骤 9 没有给出稳定领域时，
        # 才依据 Profile 的真实指标字段收敛。步骤 13 只做计划编排，不重新解释
        # 用户范围，也不在此阶段读取 CSV 或生成经营数字。
        profile_domains: set[str] = set()
        known_bindings = tuple(ruijin_profile().bindings)
        for context in contexts:
            fields = {field.rsplit(".", 1)[-1].casefold() for field in context.fields}
            semantic_fields = {
                str(item.get("fieldRef", "")).rsplit(".", 1)[-1].casefold()
                for item in context.metric_semantics
                if isinstance(item, Mapping)
            }
            observed_fields = fields | semantic_fields
            profile_domains.update(
                binding.domain
                for binding in known_bindings
                if binding.field_ref.rsplit(".", 1)[-1].casefold() in observed_fields
            )
        candidate_domains = covered_domains or profile_domains
        domains = tuple(
            code
            for code in DOMAIN_CODES
            if code in requested_domains and (not candidate_domains or code in candidate_domains)
        )
        if not domains:
            raise ReportingError("report_analysis_plan_invalid", "授权 CSV 没有形成可分析领域。")

        result = self._workflow_result(state)
        handles = tuple(DatasetHandle.from_state(item) for item in result.get("datasets", ()))
        context_by_id = {item.dataset_id: item for item in contexts}
        if (
            not handles
            or len(context_by_id) != len(contexts)
            or {item.dataset_id for item in handles} != set(context_by_id)
        ):
            raise ReportingError(
                "report_analysis_context_invalid",
                "分析数据上下文没有精确绑定本轮不可变数据集。",
            )

        profile_warnings = tuple(
            dict.fromkeys(
                warning
                for context in contexts
                for warning in (*context.source_warnings, *context.quality_warnings)
            )
        )
        context_payload = {
            "version": 1,
            "datasetIds": [item.dataset_id for item in contexts],
            "datasetContexts": [item.model_dump(mode="json", by_alias=True) for item in contexts],
            "profileCoverageManifest": profile_coverage.model_dump(mode="json", by_alias=True),
            "initialRequirements": state.get(REPORT_DATA_REQUIREMENTS_STATE_KEY, []),
            "reportGoal": envelope.report_goal,
            "analysisGoal": envelope.report_goal,
            "allowedDomains": list(domains),
            "dataShapes": state.get(REPORT_DATA_SHAPES_STATE_KEY, []),
            "warnings": list(profile_warnings),
        }
        context_path = f"报表/分析计划/{run_context.run_id}/detailed-analysis-context.json"
        context_file = await self._write_artifact_validation_context(
            self._scope(run_context)["threadId"], context_path, context_payload
        )
        state[REPORT_ANALYSIS_CONTEXT_FILE_STATE_KEY] = context_file

        analyses: list[DetailedAnalysisItem] = []
        covered_dataset_ids: set[str] = set()
        plan_warnings = list(profile_warnings)
        role_labels = {"current": "本期", "yoy": "同比", "mom": "环比"}
        for initial_item in initial:
            requirement_ids = set(initial_item.requirement_ids)
            referenced_handles = tuple(
                handle for handle in handles if handle.requirement_id in requirement_ids
            )
            if not referenced_handles:
                raise ReportingError(
                    "report_analysis_plan_invalid",
                    "已批准分析项没有绑定本轮不可变数据集。",
                )
            referenced_contexts = tuple(
                context_by_id[handle.dataset_id] for handle in referenced_handles
            )
            covered_dataset_ids.update(handle.dataset_id for handle in referenced_handles)

            resolved = resolve_domain_mentions(
                f"{initial_item.code} {initial_item.description}"
            ).selected
            domain = (
                initial_item.code
                if initial_item.code in domains
                else next((item for item in resolved if item in domains), domains[0])
            )

            field_candidates: list[str] = []
            metric_candidates: list[str] = []
            periods: list[str] = []
            for context in referenced_contexts:
                field_candidates.extend(context.organization_grain)
                if context.time_series_sort_field:
                    field_candidates.append(context.time_series_sort_field)
                field_candidates.extend(context.numeric_fields)
                field_candidates.extend(context.fields)
                semantic_metrics = [
                    str(item.get("fieldRef", "")).rsplit(".", 1)[-1]
                    for item in context.metric_semantics
                    if isinstance(item, Mapping) and item.get("fieldRef")
                ]
                metric_candidates.extend(semantic_metrics or context.numeric_fields)
                period_values = list(context.period_values)
                periods.extend(
                    period_values
                    if len(period_values) <= 24
                    else [period_values[0], period_values[-1]]
                )
            indexed_fields = tuple(dict.fromkeys(field_candidates))
            metrics = tuple(dict.fromkeys(metric_candidates))
            if len(indexed_fields) > 100:
                plan_warnings.append(
                    f"分析项 {initial_item.code} 的字段索引超过 100 个；计划保留前 100 个关键字段，完整字段仍保存在 Profile 索引中。"
                )
            if len(metrics) > 100:
                plan_warnings.append(
                    f"分析项 {initial_item.code} 的指标索引超过 100 个；计划保留前 100 个指标，完整指标仍保存在 Profile 索引中。"
                )
            comparison_basis = tuple(
                dict.fromkeys(
                    role_labels[role]
                    for handle in referenced_handles
                    for role in handle.period_roles
                )
            )
            actions = ["核验数据范围、指标口径和 Profile 告警"]
            actions.append("从不可变 CSV 复算规模、结构和关键指标")
            if periods:
                actions.append("分析期间趋势、变化幅度和比较基准")
            if any(context.organization_grain for context in referenced_contexts):
                actions.append("按组织粒度下钻贡献与异常")
            if len(referenced_contexts) > 1:
                actions.append("校验跨数据集期间、粒度和口径的可比性")

            item_warnings = tuple(
                dict.fromkeys(
                    warning
                    for context in referenced_contexts
                    for warning in (*context.source_warnings, *context.quality_warnings)
                )
            )
            profile_coverages = tuple(
                coverage
                for context in referenced_contexts
                for coverage in (context.profile_model_view.get("coverage"),)
                if isinstance(coverage, Mapping)
            )
            correlation_methods = tuple(
                dict.fromkeys(
                    str(method)
                    for coverage in profile_coverages
                    for method in coverage.get("correlationMethods", ())
                    if isinstance(method, str)
                )
            )
            profile_signal = (
                "Profile 定位信号包含 "
                f"{sum(int(item.get('variableCount', 0)) for item in profile_coverages)} 个变量、"
                f"{sum(int(item.get('alertCount', 0)) for item in profile_coverages)} 条告警、"
                f"{sum(int(item.get('timeSeriesFieldCount', 0)) for item in profile_coverages)} 个时序字段"
                f"和相关性方法 {', '.join(correlation_methods) or '无'}；"
                "先检查 coverage 与 alerts，再按变量、相关性和时序 Pointer 定点读取完整 Profile。"
            )
            recommended_charts = [
                str(opportunity["label"])
                for context in referenced_contexts
                for opportunity in context.profile_model_view.get("chartOpportunities", ())
                if isinstance(opportunity, Mapping) and isinstance(opportunity.get("label"), str)
            ]
            if periods:
                recommended_charts.append("月度趋势带或同比哑铃图")
            if any(context.organization_grain for context in referenced_contexts):
                recommended_charts.append("组织贡献排名、Pareto 图或结构图")
            if len(referenced_contexts) > 1:
                recommended_charts.append("跨域散点、相关矩阵或气泡象限图")
            lowered_fields = {
                field.casefold() for context in referenced_contexts for field in context.fields
            }
            if any("budget" in field for field in lowered_fields) and any(
                "actual" in field for field in lowered_fields
            ):
                recommended_charts.append("预算与实际子弹图或偏差瀑布图")
            if all(
                any(token in field for field in lowered_fields)
                for token in ("budget", "contract", "pay")
            ):
                recommended_charts.append("预算、合同与付款转化漏斗图")
            recommended_charts = list(dict.fromkeys(recommended_charts))[:12]
            description = initial_item.description.rstrip("。？?")
            analyses.append(
                DetailedAnalysisItem(
                    analysisId=f"analysis_{len(analyses) + 1:03d}",
                    domain=domain,
                    managementQuestion=(initial_item.management_question),
                    primaryMetricFamily=initial_item.primary_metric_family,
                    datasetIds=tuple(handle.dataset_id for handle in referenced_handles),
                    fields=indexed_fields[:100],
                    metrics=metrics[:100],
                    periods=tuple(dict.fromkeys(periods)),
                    comparisonBasis=comparison_basis,
                    organizationGrain=tuple(
                        dict.fromkeys(
                            grain
                            for context in referenced_contexts
                            for grain in context.organization_grain
                        )
                    ),
                    actions=tuple(actions),
                    evidenceSummary=(
                        f"计划绑定 {len(referenced_contexts)} 个不可变数据集、"
                        f"{sum(context.row_count for context in referenced_contexts)} 行记录；"
                        f"{profile_signal}最终数字由 Coding 从 CSV 复算。"
                    ),
                    limitations=item_warnings[:100],
                    recommendedTables=("按期间与组织粒度汇总关键指标",),
                    recommendedCharts=tuple(recommended_charts),
                    suggestedSection=(description or domain)[:128],
                    completionConditions=(
                        "核验全部绑定数据集的路径、大小和 SHA-256",
                        "按 analysisId 完成 CSV 复算并保存可复现证据",
                        "正文、表格和图表只绑定已登记 citationId",
                    ),
                )
            )

        if covered_dataset_ids != set(context_by_id):
            raise ReportingError(
                "report_analysis_plan_invalid",
                "已批准分析计划没有覆盖全部授权数据集。",
            )
        unique_warnings = tuple(dict.fromkeys(plan_warnings))
        if len(unique_warnings) > 500:
            unique_warnings = unique_warnings[:499] + (
                f"另有 {len(unique_warnings) - 499} 条完整 Warning 保存在分析数据上下文中。",
            )
        plan = DetailedAnalysisPlan(
            analyses=tuple(analyses),
            datasetIds=tuple(context.dataset_id for context in contexts),
            reportGoal=envelope.report_goal,
            analysisGoal=envelope.report_goal,
            warnings=unique_warnings,
        )
        state[REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY] = plan.model_dump(mode="json", by_alias=True)
        await self._apply_durable_command(
            run_context,
            ReportingCommand(
                name="set_analysis_plan",
                commandId=f"analysis-plan:{_payload_sha256(plan.model_dump(mode='json', by_alias=True))}",
                payload={
                    "analysisIds": [item.analysis_id for item in plan.analyses],
                    "datasetIds": list(plan.dataset_ids),
                },
            ),
        )
        self._assert_state_safe(state)
        return StepOutput(content=plan)

    async def run_coding_analysis(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        state = self._state(run_context)
        scope = self._scope(run_context)
        durable = await self.state_repository.get_or_create(
            report_run_id=str(run_context.run_id or scope["externalRunId"]),
            external_run_id=scope["externalRunId"],
            thread_id=scope["threadId"],
            owner_user_id=scope["userId"],
            revision=int(state.get(REPORT_OUTLINE_STATE_KEY, {}).get("revision", 1))
            if isinstance(state.get(REPORT_OUTLINE_STATE_KEY), Mapping)
            else 1,
        )
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
                "sections": [
                    {"code": section.code, "title": section.title} for section in outline.sections
                ],
            },
            run_context=self._tool_context(run_context),
        )
        return StepOutput(content=await self._run_coding(run_context, feedback=None))

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
        self.workspace_service._validate_content(content)
        relative, remote = self.workspace_service.normalize_path(path, allow_root=False)
        async with self.workspace_service._async_client() as client:
            sandbox = await self.workspace_service._asandbox_for(client, thread_id)
            await self.workspace_service._aensure_directory(sandbox, remote.rsplit("/", 1)[0])
            await sandbox.fs.upload_file(content, remote)
            stored = await self.workspace_service._adownload_file(sandbox, remote, len(content))
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
                commandId=(f"workflow-checkpoint:{checkpoint.revision}:{digest}"),
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
        merged_phase = incoming.phase
        if current.phase == "completed" or incoming.phase == "completed":
            merged_phase = "completed"
        elif current.phase == "finalize" or incoming.phase == "finalize":
            merged_phase = "finalize"
        elif not freezes_analysis and (current.phase == "analysis" or incoming.phase == "analysis"):
            merged_phase = "analysis"
        return ReportWorkflowRuntime._update_reporting_checkpoint(
            incoming,
            phase=merged_phase,
            completed_sections=tuple(completed_by_code.values()),
            pending_sections=pending,
            warnings=tuple((*current.warnings, *incoming.warnings)[-500:]),
            last_error=incoming.last_error or current.last_error,
            files=ReportWorkflowRuntime._merge_checkpoint_files(current.files, *incoming.files),
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
        _relative, remote = self.workspace_service.normalize_path(identity.path, allow_root=False)
        async with self.workspace_service._async_client() as client:
            sandbox = await self.workspace_service._asandbox_for(client, thread_id)
            content = await self.workspace_service._adownload_file(sandbox, remote, identity.size)
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
        self.workspace_service._validate_content(content)
        digest = hashlib.sha256(content).hexdigest()
        current = (await self.workspace_service.abatch_hash_files(thread_id, [path]))[0]
        if current.get("missing") is not True:
            if current.get("size") == len(content) and current.get("sha256") == digest:
                return FileIdentity.model_validate(current)
            raise ReportingError(
                "report_artifact_file_changed", "当前 revision 的服务端产物已存在但身份不同。"
            )
        relative, remote = self.workspace_service.normalize_path(path, allow_root=False)
        async with self.workspace_service._async_client() as client:
            sandbox = await self.workspace_service._asandbox_for(client, thread_id)
            await self.workspace_service._aensure_directory(sandbox, remote.rsplit("/", 1)[0])
            await sandbox.fs.upload_file(content, remote)
            stored = await self.workspace_service._adownload_file(sandbox, remote, len(content))
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
        return ReportWorkflowRuntime._update_reporting_checkpoint(checkpoint, trace=tuple(traces))

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

    def _worker_thinking_effort(self, *, retry: bool) -> Literal["off", "high", "max"]:
        model = self.report_worker.model
        if not isinstance(model, OpenAIChat):
            raise TypeError("Report worker requires OpenAIChat")
        profile = reporting_thinking_profile_from_model(model)
        if not profile.enabled:
            return "off"
        return "max" if retry else "high"

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
        selected_lineage = tuple(
            item for item in lineage if item.dataset_id in selected_dataset_ids
        )
        selected_citations = tuple(
            item for item in citation_bindings if item.dataset_id in selected_dataset_ids
        )
        analysis_plan = {
            "analysisId": analysis.analysis_id,
            "domain": analysis.domain,
            "step": analysis.management_question,
            "primaryMetricFamily": analysis.primary_metric_family,
            "datasetIds": list(analysis.dataset_ids),
        }
        last_error: Exception | None = None

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
                        "profileReadReceiptIds",
                        "warnings",
                    }
                }
            instruction_payload = {
                "phase": "analysis",
                "taskKind": "analysis_item",
                "reportGoal": self._envelope(run_context).report_goal,
                "currentAnalysisId": analysis_id,
                "currentAnalysis": analysis_plan,
                "analysisOutputRoot": (f"报表/智能分析/{report_run_id}/evidence/{analysis_id}"),
                "completionConditions": _analysis_item_completion_conditions(
                    recovery_payload,
                    last_error,
                ),
                "deterministicFactFile": fact_files[analysis_id].model_dump(
                    mode="json", by_alias=True
                ),
                "detailedAnalysisPlan": _coding_detailed_analysis_plan(
                    detailed_plan,
                    analysis_ids=(analysis_id,),
                ),
                "profileCoverage": _profile_coverage_instruction_projection(
                    checkpoint.profile_coverage,
                    analysis_context_file,
                    dataset_ids=selected_dataset_ids,
                ),
                "analysisContextFile": analysis_context_file.model_dump(mode="json", by_alias=True),
                "datasets": [item.public_dict() for item in selected_handles],
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
            retry = any(item.status == "failed" for item in matching_traces)
            contract = build_report_phase_acceptance_contract(
                phase="analysis",
                validation_context_file=validation_context_file.model_dump(
                    mode="json", by_alias=True
                ),
                phase_contract={
                    "reportRunId": report_run_id,
                    "taskKind": "analysis_item",
                    # 单项分析的正常路径以工具回执和固定事实为主，不需要持续开启深度
                    # 思考；只有服务端判定上一次尝试失败时才升级，避免把每个分析项都
                    # 付出完整 reasoning budget 的墙钟成本。
                    "thinkingEffort": (
                        self._worker_thinking_effort(retry=True) if retry else "off"
                    ),
                    "analysisIds": [analysis_id],
                    "currentAnalysisId": analysis_id,
                    "analysisOutputRoot": (f"报表/智能分析/{report_run_id}/evidence/{analysis_id}"),
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
            task_scope = TaskScope(
                task_id,
                scope["userId"],
                scope["threadId"],
                sandbox_id,
                str(self.report_worker.id),
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
                receipt = await self.task_runner.run(
                    task_scope,
                    parent_run_id=str(run_context.run_id or ""),
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
                logger.info(
                    "report_phase_context phase=analysis work_kind=analysis_item "
                    "analysis_id=%s task_id=%s instruction_bytes=%s duration_seconds=%.3f "
                    "tool_events=%s attempt=%s retry_reason=%s",
                    analysis_id,
                    task_id,
                    instruction_bytes,
                    trace_metrics["duration_seconds"],
                    trace_metrics.get("tool_event_count", 0),
                    attempt,
                    retry_reason or "-",
                )
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
                    },
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
        assert last_error is not None
        raise last_error

    async def _run_analysis_phase(
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
        feedback: str | None,
        rework_request: AnalysisReworkRequest | None,
    ) -> tuple[ReportingCheckpoint, AnalysisArtifact]:
        scope = self._scope(run_context)
        fact_files = await self._prepare_deterministic_analysis_facts(
            run_context=run_context,
            thread_id=scope["threadId"],
            report_run_id=str(run_context.run_id or scope["externalRunId"]),
            revision=revision,
            detailed_plan=detailed_plan,
            dataset_handles=dataset_handles,
        )
        analysis_ids = tuple(item.analysis_id for item in detailed_plan.analyses)
        if rework_request is not None:
            checkpoint = self._update_reporting_checkpoint(
                checkpoint,
                phase="analysis",
                report_brief=None,
                evidence_manifest=None,
                analysis_manifest_file=None,
                last_error=None,
            )
            await self._apply_durable_command(
                run_context,
                ReportingCommand(
                    name="start_analysis",
                    commandId=(
                        f"analysis-rework-start:{revision}:"
                        f"{payload_sha256(rework_request.model_dump(mode='json', by_alias=True))}"
                    ),
                ),
            )
            await self._persist_reporting_checkpoint(run_context, checkpoint)
        retry_reason = (
            f"analysis_rework:{payload_sha256(rework_request.model_dump(mode='json', by_alias=True))}"
            if rework_request is not None
            else ("report_revision_feedback" if feedback else None)
        )

        completed_task_ids = {
            item.analysis_id
            for item in checkpoint.trace
            if item.phase == "analysis"
            and item.work_kind == "analysis_item"
            and item.status == "completed"
            and item.retry_reason == retry_reason
            and item.analysis_id is not None
        }

        async def run_one(analysis_id: str) -> ReportingCheckpoint:
            return await self._run_analysis_item_task(
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
                retry_reason=retry_reason,
                feedback=feedback,
                rework_request=rework_request,
            )

        scheduled_analysis_ids = await _run_pending_analysis_items(
            analysis_ids,
            completed_analysis_ids=completed_task_ids,
            concurrency=self.analysis_concurrency,
            worker=run_one,
        )
        if scheduled_analysis_ids:
            checkpoint = await self._current_reporting_checkpoint(run_context, checkpoint)
        last_error: Exception | None = None

        for _ in range(MAX_REPORT_SECTION_PHASE_ATTEMPTS):
            started_trace = next(
                (
                    item
                    for item in reversed(checkpoint.trace)
                    if item.phase == "analysis"
                    and item.work_kind == "visualization"
                    and item.status == "started"
                    and item.retry_reason == retry_reason
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
                        if item.phase == "analysis" and item.work_kind == "visualization"
                    ),
                    default=-1,
                )
                + 1
            )
            task_id = reporting_phase_task_key(
                str(run_context.run_id or "report"),
                revision,
                "analysis",
                analysis_id="visualization",
                attempt=attempt,
            )
            output_path = (
                f"报表/智能分析/{run_context.run_id}/phases/revision-{revision}/"
                f"visualization-attempt-{attempt + 1}.json"
            )
            durable_state = await self.state_repository.get(
                str(run_context.run_id or scope["externalRunId"])
            )
            durable_payload = durable_state.payload if durable_state is not None else {}
            registered_charts = [
                dict(item)
                for item in durable_payload.get("charts", ())
                if isinstance(item, Mapping) and isinstance(item.get("chartId"), str)
            ]
            charts_registered = durable_payload.get("chartsRegistered") is True or (
                "chartsRegistered" not in durable_payload and bool(registered_charts)
            )
            current_analysis_id = durable_payload.get("currentAnalysisId")
            completed_analysis_ids = {
                item
                for item in durable_payload.get("completedAnalysisIds", ())
                if isinstance(item, str)
            }
            if current_analysis_id is not None or completed_analysis_ids != set(analysis_ids):
                raise ReportingError(
                    "report_analysis_evidence_incomplete",
                    "visualization 启动前 analysisId 尚未按冻结计划全部完成。",
                )
            analysis_plans = {
                item.analysis_id: {
                    "analysisId": item.analysis_id,
                    "domain": item.domain,
                    "step": item.management_question,
                    "primaryMetricFamily": item.primary_metric_family,
                    "datasetIds": list(item.dataset_ids),
                }
                for item in detailed_plan.analyses
            }
            analysis_items = durable_payload.get("analysisItems")
            completed_analysis_summaries = [
                {
                    "analysisId": analysis_id,
                    "summary": analysis_items[analysis_id].get("summary"),
                    "evidenceFiles": analysis_items[analysis_id].get("evidenceFiles", []),
                    "citationIds": analysis_items[analysis_id].get("citationIds", []),
                    "profileReadReceiptIds": analysis_items[analysis_id].get(
                        "profileReadReceiptIds", []
                    ),
                }
                for analysis_id in analysis_ids
                if isinstance(analysis_items, dict)
                and isinstance(analysis_items.get(analysis_id), dict)
            ]
            visualization_root = f"报表/智能分析/{run_context.run_id}/analysis"
            instruction_payload = {
                "phase": "analysis",
                "taskKind": "visualization",
                "reportGoal": self._envelope(run_context).report_goal,
                "completionConditions": _visualization_completion_conditions(
                    last_error, charts_registered
                ),
                "outline": self._state(run_context)[REPORT_OUTLINE_STATE_KEY],
                "currentAnalysisId": None,
                "completedAnalysisIds": sorted(completed_analysis_ids),
                "completedAnalysisItems": completed_analysis_summaries,
                "deterministicFactFiles": {
                    analysis_id: identity.model_dump(mode="json", by_alias=True)
                    for analysis_id, identity in fact_files.items()
                },
                "detailedAnalysisPlan": _coding_detailed_analysis_plan(detailed_plan),
                "visualTheme": REPORT_VISUAL_THEME,
                "datasetLineage": [item.model_dump(mode="json", by_alias=True) for item in lineage],
                "citationRegistry": [
                    item.model_dump(mode="json", by_alias=True) for item in citation_bindings
                ],
                "registeredCharts": registered_charts,
                # 可视化脚本与 evidence/facts 分属兄弟目录。由服务端签发完整工作区相对路径，
                # 禁止 Worker 依据脚本位置猜测父目录，否则会把 evidence 错拼成 analysis/evidence。
                "visualizationWorkspace": {
                    "scriptPath": f"{visualization_root}/charts.py",
                    "chartOutputRoot": f"{visualization_root}/charts",
                },
                "sourceWarnings": [
                    item.model_dump(mode="json", by_alias=True)
                    for item in _source_warnings_from_state(self._state(run_context))
                ],
                "reviewFeedback": feedback,
                "analysisOutputPath": output_path,
            }
            instruction = json.dumps(instruction_payload, ensure_ascii=False, separators=(",", ":"))
            instruction_bytes = len(instruction.encode("utf-8"))
            if instruction_bytes > MAX_REPORT_INSTRUCTION_BYTES:
                raise ReportingError(
                    "report_analysis_context_too_large",
                    "全局分析投影超过模型输入边界；证据未被静默截断。",
                )
            visualization_tool_calls, visualization_script_failures = _visualization_retry_budget(
                last_error
            )
            contract = build_report_phase_acceptance_contract(
                phase="analysis",
                validation_context_file=validation_context_file.model_dump(
                    mode="json", by_alias=True
                ),
                phase_contract={
                    "reportRunId": str(run_context.run_id or scope["externalRunId"]),
                    "taskKind": "visualization",
                    "chartsRegistered": charts_registered,
                    "visualizationToolCalls": visualization_tool_calls,
                    "visualizationScriptFailures": visualization_script_failures,
                    "thinkingEffort": self._worker_thinking_effort(
                        retry=any(
                            item.status == "failed"
                            for item in checkpoint.trace
                            if item.phase == "analysis"
                            and item.work_kind == "visualization"
                            and item.retry_reason == retry_reason
                        )
                    ),
                    "analysisIds": list(analysis_ids),
                    "currentAnalysisId": None,
                    "analysisPlans": analysis_plans,
                    "analysisDatasetIds": {
                        item.analysis_id: list(item.dataset_ids) for item in detailed_plan.analyses
                    },
                    "deterministicFactFiles": {
                        analysis_id: identity.model_dump(mode="json", by_alias=True)
                        for analysis_id, identity in fact_files.items()
                    },
                    "datasetIds": [item.dataset_id for item in dataset_handles],
                    "citationIds": [item.citation_id for item in citation_bindings],
                    "citationRegistry": [
                        item.model_dump(mode="json", by_alias=True) for item in citation_bindings
                    ],
                },
                analysis_output_path=output_path,
            )
            task_scope = TaskScope(
                task_id,
                scope["userId"],
                scope["threadId"],
                sandbox_id,
                str(self.report_worker.id),
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
                            workKind="visualization",
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
                        "全局分析 task 已在未签发阶段产物前终止。",
                    )
                receipt = await self.task_runner.run(
                    task_scope,
                    parent_run_id=str(run_context.run_id or ""),
                )
                trace_metrics = self._trace_metrics_from_receipt(receipt)
                trace_metrics["duration_seconds"] = time.monotonic() - started_at
                identity = await self._phase_artifact_from_receipt(
                    scope["threadId"], receipt, (output_path,)
                )
                artifact = cast(
                    AnalysisArtifact,
                    await self._read_identity_model(scope["threadId"], identity, AnalysisArtifact),
                )
                if (
                    tuple(item.analysis_id for item in artifact.evidence_manifest.evidence)
                    != analysis_ids
                ):
                    raise ReportingError(
                        "report_analysis_evidence_incomplete",
                        "全局分析产物没有按冻结顺序覆盖全部 analysisId。",
                    )
                coverage_hashes = {
                    item.dataset_id: item.profile_file.sha256
                    for item in checkpoint.profile_coverage.datasets
                }
                if any(
                    coverage_hashes.get(item.dataset_id) != item.snapshot_hash
                    for item in artifact.profile_read_receipts
                ):
                    raise ReportingError(
                        "report_profile_receipt_changed",
                        "ProfileReadReceipt 没有绑定当前完整 Profile 快照。",
                    )
                durable_after_worker = await self.state_repository.get(
                    str(run_context.run_id or scope["externalRunId"])
                )
                completed_by_worker = set(
                    durable_after_worker.payload.get("completedAnalysisIds", ())
                    if durable_after_worker is not None
                    else ()
                )
                for evidence in artifact.evidence_manifest.evidence:
                    if evidence.analysis_id in completed_by_worker:
                        continue
                    await self._apply_durable_command(
                        run_context,
                        ReportingCommand(
                            name="complete_analysis_item",
                            commandId=f"analysis-item:{revision}:{evidence.analysis_id}:{identity.sha256}",
                            payload={
                                "analysisId": evidence.analysis_id,
                                "summary": evidence.summary,
                                "datasetIds": list(evidence.dataset_ids),
                                "evidenceFiles": [
                                    item.model_dump(mode="json", by_alias=True)
                                    for item in evidence.evidence_files
                                ],
                                "citationIds": list(evidence.citation_ids),
                                "profileReadReceiptIds": list(evidence.profile_read_receipt_ids),
                                "chartIds": list(evidence.chart_ids),
                                "warnings": list(evidence.warnings),
                            },
                        ),
                    )
                await self._apply_durable_command(
                    run_context,
                    ReportingCommand(
                        name="finalize_report_analysis",
                        commandId=f"analysis-freeze:{revision}:{identity.sha256}",
                        payload={
                            "reportBrief": artifact.report_brief.model_dump(
                                mode="json", by_alias=True
                            ),
                            "evidenceManifest": artifact.evidence_manifest.model_dump(
                                mode="json", by_alias=True
                            ),
                            "warnings": list(artifact.evidence_manifest.warnings),
                        },
                    ),
                )
                await self._apply_durable_command(
                    run_context,
                    ReportingCommand(
                        name="enter_sections",
                        commandId=f"sections-start:{revision}:{identity.sha256}",
                    ),
                )
                checkpoint = self._replace_trace(
                    checkpoint,
                    task_id,
                    status="completed",
                    artifact_file=identity,
                    pointer_receipt_ids=tuple(
                        item.receipt_id for item in artifact.profile_read_receipts
                    ),
                    **trace_metrics,
                )
                analysis_warnings = tuple(
                    {"code": "analysis_warning", "message": warning}
                    for warning in artifact.evidence_manifest.warnings
                )
                checkpoint = self._update_reporting_checkpoint(
                    checkpoint,
                    phase="sections",
                    profile_read_receipts=artifact.profile_read_receipts,
                    report_brief=artifact.report_brief,
                    evidence_manifest=artifact.evidence_manifest,
                    analysis_manifest_file=identity,
                    warnings=tuple((*checkpoint.warnings, *analysis_warnings)[-500:]),
                    last_error=None,
                    files=self._merge_checkpoint_files(checkpoint.files, identity),
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
                logger.info(
                    "report_phase_context phase=analysis work_kind=visualization "
                    "task_id=%s instruction_bytes=%s duration_seconds=%.3f tool_events=%s "
                    "profile_receipts=%s model_input_tokens=%s model_requests=%s "
                    "max_projected_tokens=%s rebases=%s hard_cap=%s "
                    "completed_analysis=%s retry_reason=%s",
                    task_id,
                    instruction_bytes,
                    trace_metrics["duration_seconds"],
                    trace_metrics.get("tool_event_count", 0),
                    len(artifact.profile_read_receipts),
                    trace_metrics.get("model_input_tokens"),
                    trace_metrics.get("model_request_count", 0),
                    trace_metrics.get("max_projected_tokens", 0),
                    trace_metrics.get("rebase_count", 0),
                    trace_metrics.get("input_token_hard_cap", 0),
                    trace_metrics.get("completed_analysis_count", 0),
                    retry_reason or "-",
                )
                return checkpoint, artifact
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
                        "message": message or "可视化冻结阶段失败。",
                        "retryReason": retry_reason,
                    },
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
        assert last_error is not None
        raise last_error

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
            _relative, remote = self.workspace_service.normalize_path(handle.path, allow_root=False)
            async with self.workspace_service._async_client() as client:
                sandbox = await self.workspace_service._asandbox_for(client, thread_id)
                content = await self.workspace_service._adownload_file(sandbox, remote, handle.size)
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
        try:
            selected_analyses = tuple(analyses[item] for item in section.analysis_ids)
            selected_evidence = tuple(evidence[item] for item in section.analysis_ids)
        except KeyError as error:
            raise ReportingError(
                "report_section_evidence_incomplete",
                "章节引用的 analysisId 缺少冻结 evidence。",
            ) from error
        receipt_ids = {
            receipt_id for item in selected_evidence for receipt_id in item.profile_read_receipt_ids
        }
        chart_ids = {chart_id for item in selected_evidence for chart_id in item.chart_ids}
        citation_ids = {
            citation_id for item in selected_evidence for citation_id in item.citation_ids
        }
        receipts = tuple(
            item
            for item in analysis_artifact.profile_read_receipts
            if item.receipt_id in receipt_ids
        )
        charts = tuple(
            item
            for item in analysis_artifact.evidence_manifest.charts
            if item.chart_id in chart_ids
        )
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
            title=section.title,
            objective="；".join(objective_parts),
            completionConditions=(
                "完整呈现当前章节全部冻结事实及其管理结论",
                "保持期间、单位和共享指标口径一致",
                "覆盖当前章节 evidence 提供的 citation",
                "仅使用当前 SectionWorkItem 提供的 chart",
            ),
            analysisIds=tuple(section.analysis_ids),
            evidence=selected_evidence,
            metricDefinitions=analysis_artifact.evidence_manifest.metric_definitions,
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
                "章节 title 由服务端插入，正文不得重复一级或二级章节标题",
                "章节内部标题从三级标题开始",
                "表格直接使用标准 Markdown 管道表，不得渲染为图片",
                "正文不得自行写 citation、analysis、section 或图片协议标记",
                "最后且只调用一次 render_report_section；证据不足时改用 request_analysis_rework",
            ),
        )

    async def _durable_completed_section(
        self,
        run_context: RunContext,
        *,
        revision: int,
        section_code: str,
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
        validate_report_draft_blocks(artifact.blocks)
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
        restored = await self._durable_completed_section(
            run_context,
            revision=revision,
            section_code=work_item.section_code,
            analysis_ids=work_item.analysis_ids,
            work_item_hash=work_item_hash,
        )
        if restored is not None:
            completed_section, artifact = restored
            checkpoint = self._update_reporting_checkpoint(
                checkpoint,
                phase="sections",
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
        last_error: Exception | None = None
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
            instruction_payload = {
                "phase": "section",
                "sectionWorkItem": work_item_payload,
                "completionConditions": list(work_item.completion_conditions),
                "sectionOutputPath": section_output_path,
                "reworkRequestPath": rework_request_path,
            }
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
                },
                section_output_path=section_output_path,
                rework_request_path=rework_request_path,
            )
            task_scope = TaskScope(
                task_id,
                scope["userId"],
                scope["threadId"],
                sandbox_id,
                str(self.report_worker.id),
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
                receipt = await self.task_runner.run(
                    task_scope, parent_run_id=str(run_context.run_id or "")
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
                    await self._apply_durable_command(
                        run_context,
                        ReportingCommand(
                            name="request_analysis_rework",
                            commandId=f"analysis-rework:{revision}:{identity.sha256}",
                            payload={
                                "analysisIds": list(request.analysis_ids),
                                "missingEvidence": list(request.missing_evidence),
                                "reason": request.reason,
                                "sectionCode": request.section_code,
                            },
                        ),
                    )
                    invalid_section_codes = {
                        section.code
                        for section in _frozen_outline(self._state(run_context)).sections
                        if set(section.analysis_ids) & set(request.analysis_ids)
                    }
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
                            dict.fromkeys(
                                [*checkpoint.pending_sections, *sorted(invalid_section_codes)]
                            )
                        ),
                        last_error={
                            "phase": "section",
                            "code": "report_analysis_evidence_insufficient",
                            "message": request.reason,
                            "sectionCode": work_item.section_code,
                            "retryReason": payload_sha256(
                                request.model_dump(mode="json", by_alias=True)
                            ),
                        },
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
                validate_report_draft_blocks(artifact.blocks)
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
                    phase="sections",
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
                logger.info(
                    "report_phase_context phase=section task_id=%s section_code=%s "
                    "instruction_bytes=%s model_input_tokens=%s model_requests=%s "
                    "max_projected_tokens=%s rebases=%s hard_cap=%s attempt=%s",
                    task_id,
                    work_item.section_code,
                    instruction_bytes,
                    trace_metrics.get("model_input_tokens"),
                    trace_metrics.get("model_request_count", 0),
                    trace_metrics.get("max_projected_tokens", 0),
                    trace_metrics.get("rebase_count", 0),
                    trace_metrics.get("input_token_hard_cap", 0),
                    attempt,
                )
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
                    phase="sections",
                    last_error={
                        "phase": "section",
                        "code": code,
                        "message": message or "独立章节阶段失败。",
                        "sectionCode": work_item.section_code,
                        "retryReason": code,
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
            coding_task_key=analysis_task_id,
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

    async def _run_coding(self, run_context: RunContext, *, feedback: str | None) -> dict[str, Any]:
        state = self._state(run_context)
        outline = _frozen_outline(state)
        result = self._workflow_result(state)
        revision = int(result.get("revision", 0)) + 1 + (1 if feedback else 0)
        scope = self._scope(run_context)
        async with self.workspace_service._async_client() as client:
            sandbox = await self.workspace_service._asandbox_for(client, scope["threadId"])
            sandbox_id = str(getattr(sandbox, "id", "") or "")
        if not sandbox_id or not self.report_worker.id:
            raise ReportingError("report_worker_unavailable", "报表 Coding 工作区不可用。")
        markdown_path = f"报表/智能分析/{run_context.run_id}/report-revision-{revision}.md"
        manifest_path = (
            f"报表/智能分析/{run_context.run_id}/report-revision-{revision}.manifest.json"
        )
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
        try:
            analysis_context_file = FileIdentity.model_validate(
                state.get(REPORT_ANALYSIS_CONTEXT_FILE_STATE_KEY)
            )
            profile_coverage = ProfileCoverageManifest.model_validate(
                state.get(REPORT_PROFILE_COVERAGE_STATE_KEY)
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise ReportingError(
                "report_analysis_context_unavailable",
                "完整分析数据上下文或 Profile coverage 缺失。",
            ) from error
        dataset_handles = tuple(
            DatasetHandle.from_state(item) for item in result.get("datasets", ())
        )
        if not dataset_handles:
            raise ReportingError("report_analysis_context_unavailable", "授权 Dataset 缺失。")
        observed_data_facts = _coding_observed_data_facts(
            self._data_shapes(run_context), requirements, lineage
        )
        render_sections: list[dict[str, Any]] = [
            {
                "code": section.code,
                "title": section.title,
                "protocolMarker": True,
                "analysisIds": list(section.analysis_ids),
            }
            for section in outline.sections
        ]
        citation_bindings = authoritative_citations(lineage)
        source_warnings = _source_warnings_from_state(state)
        validation_context = build_report_artifact_validation_context(
            forbidden_visible_terms=_report_machine_terms(
                state[REPORT_DATA_REQUIREMENTS_STATE_KEY],
                state[REPORT_DATASET_LINEAGE_STATE_KEY],
                state[REPORT_EFFECTIVE_PROFILE_STATE_KEY],
            ),
            observed_data_facts=observed_data_facts,
            expected_sections=tuple(section["code"] for section in render_sections),
            expected_citation_bindings=tuple(
                (item.dataset_id, item.requirement_id) for item in citation_bindings
            ),
            expected_citations=tuple(
                (
                    item.citation_id,
                    item.dataset_id,
                    item.requirement_id,
                    item.snapshot_hash,
                )
                for item in citation_bindings
            ),
            analysis_context_file=analysis_context_file.model_dump(mode="json", by_alias=True),
        )
        render_contract_data = {
            "title": state[REPORT_OUTLINE_STATE_KEY]["title"],
            "sections": render_sections,
            "citationIds": [item.citation_id for item in citation_bindings],
            "requireTable": False,
        }
        validation_context["renderContract"] = render_contract_data
        validation_context_path = (
            f"报表/智能分析/{run_context.run_id}/report-revision-{revision}.validation-context.json"
        )
        validation_context_file = FileIdentity.model_validate(
            await self._write_artifact_validation_context(
                scope["threadId"], validation_context_path, validation_context
            )
        )
        checkpoint = await self._load_or_create_reporting_checkpoint(
            run_context,
            revision=revision,
            profile_coverage=profile_coverage,
            analysis_context_file=analysis_context_file,
            outline=outline,
        )
        checkpoint = self._update_reporting_checkpoint(
            checkpoint,
            files=self._merge_checkpoint_files(checkpoint.files, validation_context_file),
        )
        await self._persist_reporting_checkpoint(run_context, checkpoint)

        pending_rework: AnalysisReworkRequest | None = None
        if checkpoint.phase == "analysis" and checkpoint.analysis_manifest_file is not None:
            last_rework_index = max(
                (
                    index
                    for index, item in enumerate(checkpoint.trace)
                    if item.phase == "section"
                    and item.status == "rework"
                    and item.artifact_file is not None
                ),
                default=-1,
            )
            last_analysis_index = max(
                (
                    index
                    for index, item in enumerate(checkpoint.trace)
                    if item.phase == "analysis" and item.status == "completed"
                ),
                default=-1,
            )
            if last_rework_index > last_analysis_index:
                rework_file = checkpoint.trace[last_rework_index].artifact_file
                assert rework_file is not None
                pending_rework = cast(
                    AnalysisReworkRequest,
                    await self._read_identity_model(
                        scope["threadId"], rework_file, AnalysisReworkRequest
                    ),
                )

        if checkpoint.phase == "analysis":
            checkpoint, analysis_artifact = await self._run_analysis_phase(
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
                feedback=feedback,
                rework_request=pending_rework,
            )
        else:
            if checkpoint.analysis_manifest_file is None:
                raise ReportingError(
                    "report_analysis_artifact_missing", "Checkpoint 缺少全局分析产物身份。"
                )
            analysis_artifact = cast(
                AnalysisArtifact,
                await self._read_identity_model(
                    scope["threadId"],
                    checkpoint.analysis_manifest_file,
                    AnalysisArtifact,
                ),
            )

        while True:
            checkpoint = await self._current_reporting_checkpoint(run_context, checkpoint)
            completed_codes = {item.section_code for item in checkpoint.completed_sections}
            pending_sections = [
                section for section in outline.sections if section.code not in completed_codes
            ]
            if not pending_sections:
                break

            async def run_one(
                section: Any,
            ) -> tuple[ReportingCheckpoint, SectionArtifact | None, AnalysisReworkRequest | None]:
                work_item = self._build_section_work_item(
                    section,
                    detailed_plan=detailed_plan,
                    analysis_artifact=analysis_artifact,
                    citation_bindings=citation_bindings,
                )
                return await self._run_section_phase(
                    run_context,
                    checkpoint=checkpoint,
                    revision=revision,
                    sandbox_id=sandbox_id,
                    validation_context_file=validation_context_file,
                    work_item=work_item,
                )

            results = await _run_bounded(
                pending_sections,
                concurrency=self.section_concurrency,
                worker=run_one,
            )

            checkpoint = await self._current_reporting_checkpoint(run_context, checkpoint)
            rework_requests = [result[2] for result in results if result[2] is not None]
            if not rework_requests:
                continue
            affected_analysis_ids = tuple(
                dict.fromkeys(
                    analysis_id
                    for request in rework_requests
                    for analysis_id in request.analysis_ids
                )
            )
            missing_evidence = tuple(
                dict.fromkeys(
                    item for request in rework_requests for item in request.missing_evidence
                )
            )
            rework = AnalysisReworkRequest(
                sectionCode=rework_requests[0].section_code,
                analysisIds=affected_analysis_ids,
                reason="；".join(dict.fromkeys(item.reason for item in rework_requests)),
                missingEvidence=missing_evidence,
            )
            checkpoint, analysis_artifact = await self._run_analysis_phase(
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
                feedback=feedback,
                rework_request=rework,
            )

        checkpoint = self._update_reporting_checkpoint(
            checkpoint, phase="finalize", last_error=None
        )
        await self._apply_durable_command(
            run_context,
            ReportingCommand(
                name="start_finalize",
                commandId=f"finalize-start:{revision}",
            ),
        )
        await self._persist_reporting_checkpoint(run_context, checkpoint)
        try:
            checkpoint, manifest = await self._finalize_reporting_sections(
                run_context,
                checkpoint=checkpoint,
                revision=revision,
                markdown_path=markdown_path,
                manifest_path=manifest_path,
                lineage=lineage,
                citation_bindings=citation_bindings,
                source_warnings=source_warnings,
            )
        except Exception as error:
            code = error.code if isinstance(error, ReportingError) else "report_finalize_failed"
            message = (error.message if isinstance(error, ReportingError) else str(error))[:2000]
            checkpoint = self._update_reporting_checkpoint(
                checkpoint,
                phase="finalize",
                last_error={
                    "phase": "finalize",
                    "code": code,
                    "message": message or "服务端 Finalize 失败。",
                },
            )
            await self._persist_reporting_checkpoint(run_context, checkpoint)
            raise
        result.update(
            {
                "markdownPath": markdown_path,
                "artifactManifestPath": manifest_path,
                "revision": revision - 1,
                "sourceWarnings": [
                    item.model_dump(mode="json", by_alias=True) for item in source_warnings
                ],
                "codingReceipts": [],
            }
        )
        state[REPORT_WORKFLOW_RESULT_STATE_KEY] = result
        state[REPORT_ARTIFACTS_STATE_KEY] = {
            "draft": manifest.model_dump(mode="json", by_alias=True)
        }
        return {"jobId": result["jobId"], "markdownPath": markdown_path}

    async def validate_report(self, _step_input: StepInput, run_context: RunContext) -> StepOutput:
        return StepOutput(content=await self._render_and_validate(run_context))

    async def _render_and_validate(self, run_context: RunContext) -> dict[str, Any]:
        state = self._state(run_context)
        result = self._workflow_result(state)
        outline = _frozen_outline(state)
        pdf_path = _report_pdf_path(
            str(run_context.run_id),
            int(result.get("revision", 0)) + 1,
            outline.title,
            self._envelope(run_context).period,
        )
        context = self._tool_context(run_context)
        try:
            draft = ReportArtifactManifest.model_validate(
                state[REPORT_ARTIFACTS_STATE_KEY]["draft"]
            )
            lineage = tuple(
                DatasetLineage.model_validate(item)
                for item in state[REPORT_DATASET_LINEAGE_STATE_KEY]
            )
        except Exception as error:
            raise ReportingError(
                "report_artifact_manifest_invalid", "报告产物清单状态无效。"
            ) from error
        requirements = tuple(
            QueryRequirement.model_validate(item)
            for item in state[REPORT_DATA_REQUIREMENTS_STATE_KEY]
        )
        source_warnings = _source_warnings_from_state(state)
        analyses = tuple(
            AnalysisItem.model_validate(item) for item in state[REPORT_ANALYSIS_PLAN_STATE_KEY]
        )
        observed_facts = _coding_observed_data_facts(
            self._data_shapes(run_context), requirements, lineage
        )
        await self.report_tools.bind_citation_presentations(
            str(result["jobId"]),
            _citation_presentations(
                lineage=lineage,
                requirements=requirements,
                analyses=analyses,
                snapshots=self._snapshots(run_context),
                observed_facts=observed_facts,
            ),
            run_context=context,
        )
        rendered_result = await self.report_tools._render_report_pair(
            str(result["jobId"]),
            str(result["markdownPath"]),
            pdf_path,
            artifact_manifest=draft.model_dump(mode="json", by_alias=True),
            run_context=context,
        )
        word_path = str(PurePosixPath(pdf_path).with_suffix(".docx"))
        try:
            if not isinstance(rendered_result, dict):
                raise ReportingError(
                    "report_artifact_validation_failed", "PDF/Word 联合验收回执无效。"
                )
            validation = rendered_result.get("validation")
            if not isinstance(validation, dict) or validation.get("ok") is not True:
                raise ReportingError(
                    "report_artifact_validation_failed", "PDF/Word 联合验收未通过。"
                )
            if rendered_result.get("wordPath") != word_path:
                raise ReportingError(
                    "report_artifact_validation_failed", "Word 验收路径缺失或不匹配。"
                )
            pdf_identity = await self.workspace_service.ahash_file(
                self._scope(run_context)["threadId"], pdf_path
            )
            word_identity = await self.workspace_service.ahash_file(
                self._scope(run_context)["threadId"], word_path
            )
            validated_pdf_sha256 = validation.get("pdfSha256")
            validated_word_sha256 = validation.get("wordSha256")
            if (
                not isinstance(validated_pdf_sha256, str)
                or pdf_identity.get("sha256") != validated_pdf_sha256
                or not isinstance(validated_word_sha256, str)
                or word_identity.get("sha256") != validated_word_sha256
            ):
                raise ReportingError(
                    "report_artifact_changed",
                    "PDF 或 Word 在验收后发生变化，必须重新渲染并验收。",
                )
            source_chart_sha256s = tuple(item.sha256 for item in draft.charts)
            page_count = validation.get("pageCount")
            word_validation = validation.get("word")
            if not isinstance(word_validation, dict):
                raise ReportingError("report_artifact_validation_failed", "Word 验收回执无效。")
            converted_page_count = word_validation.get("convertedPageCount")
            section_count = word_validation.get("sectionCount")
            toc_entry_count = word_validation.get("tocEntryCount")
            if (
                isinstance(page_count, bool)
                or not isinstance(page_count, int)
                or isinstance(converted_page_count, bool)
                or not isinstance(converted_page_count, int)
                or isinstance(section_count, bool)
                or not isinstance(section_count, int)
                or isinstance(toc_entry_count, bool)
                or not isinstance(toc_entry_count, int)
            ):
                raise ReportingError(
                    "report_artifact_validation_failed", "PDF/Word 验收回执缺少有效计数。"
                )
            rendered_pdf = PdfArtifactManifest(
                reportId=draft.report_id,
                revision=draft.revision,
                effectiveProfileHash=draft.effective_profile_hash,
                sourceMarkdownSha256=draft.markdown.sha256,
                sourceChartSha256s=source_chart_sha256s,
                pdf=ArtifactFile(
                    path=pdf_path,
                    mediaType="application/pdf",
                    size=pdf_identity["size"],
                    sha256=pdf_identity["sha256"],
                ),
                pageCount=page_count,
                renderedChartIds=tuple(validation.get("chartIds") or ()),
                citationIds=tuple(validation.get("citationIds") or ()),
                sections=tuple(validation.get("sectionIds") or ()),
                sourceWarnings=source_warnings,
            )
            rendered_word = DocxArtifactManifest(
                reportId=draft.report_id,
                revision=draft.revision,
                effectiveProfileHash=draft.effective_profile_hash,
                sourceMarkdownSha256=draft.markdown.sha256,
                sourceChartSha256s=source_chart_sha256s,
                docx=ArtifactFile(
                    path=word_path,
                    mediaType=(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                    size=word_identity["size"],
                    sha256=word_identity["sha256"],
                ),
                convertedPageCount=converted_page_count,
                sectionCount=section_count,
                tocEntryCount=toc_entry_count,
                renderedChartIds=tuple(validation.get("chartIds") or ()),
                citationIds=tuple(validation.get("citationIds") or ()),
                sections=tuple(validation.get("sectionIds") or ()),
                sourceWarnings=source_warnings,
            )
            validate_rendered_artifacts(draft, rendered_pdf, rendered_word, lineage=lineage)
            # PDF/DOCX 仍由既有渲染链生成，但其最终身份属于同一 Reporting checkpoint。
            # 先核对 revision 再写回文件清单，避免恢复时把其他 revision 的交付物误认为当前产物。
            durable = await self.state_repository.get(
                str(run_context.run_id or self._scope(run_context)["externalRunId"])
            )
            if (
                durable is None
                or durable.phase is not DurableReportingPhase.COMPLETED
                or durable.revision != draft.revision
            ):
                raise ReportingError(
                    "report_checkpoint_conflict",
                    "PDF/Word 验收结果与 Reporting checkpoint revision 不一致。",
                )
            await self._apply_durable_command(
                run_context,
                ReportingCommand(
                    name="record_artifact",
                    commandId=f"rendered-pdf:{draft.revision}:{pdf_identity['sha256']}",
                    payload={"artifact": pdf_identity},
                ),
            )
            await self._apply_durable_command(
                run_context,
                ReportingCommand(
                    name="record_artifact",
                    commandId=f"rendered-word:{draft.revision}:{word_identity['sha256']}",
                    payload={"artifact": word_identity},
                ),
            )
            result.update(
                {
                    "pdfPath": pdf_path,
                    "pdfSize": int(pdf_identity["size"]),
                    "pdfSha256": str(pdf_identity["sha256"]),
                    "wordPath": word_path,
                    "wordSize": int(word_identity["size"]),
                    "wordSha256": str(word_identity["sha256"]),
                    "validation": validation,
                    "status": "validated",
                }
            )
            state[REPORT_WORKFLOW_RESULT_STATE_KEY] = result
            state[REPORT_ARTIFACTS_STATE_KEY] = {
                "draft": draft.model_dump(mode="json", by_alias=True),
                "pdf": rendered_pdf.model_dump(mode="json", by_alias=True),
                "word": rendered_word.model_dump(mode="json", by_alias=True),
            }
            return {
                "status": "validated",
                "jobId": result["jobId"],
                "markdownPath": result["markdownPath"],
                "pdfPath": pdf_path,
                "wordPath": word_path,
                "validation": validation,
            }
        except BaseException:
            # _render_report_pair 返回即表示 revision 目录已正式发布。之后任何回执、
            # 身份、manifest 或状态异常都必须删除同目录双文件；取消也不能打断清理。
            await complete_cleanup(
                self.report_tools.discard_report_revision(
                    str(result["jobId"]), pdf_path, word_path, run_context=context
                )
            )
            raise

    async def _dataset_publication_gate(
        self, run_context: RunContext, result: Mapping[str, Any]
    ) -> dict[str, Any]:
        """在发布前重新核对 DatasetLineage、分析计划、提纲和产物身份。

        该门禁只依赖本轮不可变 CSV、DatasetLineage 和服务端生成的产物清单；Profile
        质量 Warning 会继续传播但不阻断发布，路径越界、哈希漂移和结构引用错误则
        必须失败关闭。
        """
        state = self._state(run_context)
        issues: list[dict[str, Any]] = []
        raw_warnings = result.get("sourceWarnings", [])
        warnings = list(raw_warnings) if isinstance(raw_warnings, list) else []

        def issue(code: str, message: str, **details: Any) -> None:
            item: dict[str, Any] = {"code": code, "message": message}
            if details:
                item["details"] = details
            issues.append(item)

        try:
            lineage = tuple(
                DatasetLineage.model_validate(item)
                for item in state.get(REPORT_DATASET_LINEAGE_STATE_KEY, ())
            )
        except (TypeError, ValueError, ValidationError):
            lineage = ()
            issue("dataset_lineage_invalid", "DatasetLineage 状态无法解析。")
        try:
            handles = tuple(
                DatasetHandle.from_state(item)
                for item in self._workflow_result(state).get("datasets", ())
            )
        except (TypeError, ValueError, ReportingError):
            handles = ()
            issue("dataset_handle_invalid", "DatasetHandle 状态无法解析。")

        lineage_by_id = {item.dataset_id: item for item in lineage}
        handle_by_id = {item.dataset_id: item for item in handles}
        if set(lineage_by_id) != set(handle_by_id) or len(lineage_by_id) != len(lineage):
            issue("dataset_lineage_binding_invalid", "DatasetHandle 与 DatasetLineage 未精确对应。")
        thread_id = self._scope(run_context)["threadId"]
        for dataset_id, handle in handle_by_id.items():
            source = lineage_by_id.get(dataset_id)
            if source is None:
                continue
            if (
                handle.source_id != source.source_id
                or handle.requirement_id != source.requirement_id
                or handle.size != source.size
                or handle.sha256 != source.sha256
                or handle.row_count != source.row_count
                or handle.sql_hash != source.sql_hash
            ):
                issue(
                    "dataset_lineage_binding_invalid",
                    "DatasetHandle 与 DatasetLineage 身份不一致。",
                    datasetId=dataset_id,
                )
            try:
                current = await self.workspace_service.ahash_file(thread_id, handle.path)
                if (
                    current.get("missing")
                    or current.get("size") != handle.size
                    or current.get("sha256") != handle.sha256
                ):
                    issue(
                        "dataset_snapshot_changed",
                        "不可变 CSV 在发布前发生变化。",
                        datasetId=dataset_id,
                    )
            except Exception:
                issue(
                    "dataset_snapshot_unavailable",
                    "不可变 CSV 路径不可读取或越界。",
                    datasetId=dataset_id,
                )

        try:
            detailed_plan = DetailedAnalysisPlan.model_validate(
                state.get(REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY)
            )
            authorized_ids = set(lineage_by_id)
            if set(detailed_plan.dataset_ids) != authorized_ids:
                issue("analysis_dataset_coverage_invalid", "详细分析计划未精确覆盖授权数据集。")
            covered_ids = {
                dataset_id for item in detailed_plan.analyses for dataset_id in item.dataset_ids
            }
            if covered_ids != authorized_ids:
                issue("analysis_dataset_coverage_invalid", "详细分析项未覆盖全部授权数据集。")
        except (TypeError, ValueError, ValidationError):
            detailed_plan = None
            issue("analysis_plan_invalid", "详细分析计划状态无效。")

        try:
            outline = _frozen_outline(state)
            known_analysis_ids = {
                item.analysis_id for item in (detailed_plan.analyses if detailed_plan else ())
            }
            referenced_analysis_ids = [
                analysis_id for section in outline.sections for analysis_id in section.analysis_ids
            ]
            if len(referenced_analysis_ids) != len(set(referenced_analysis_ids)):
                issue("outline_analysis_duplicate", "批准提纲重复引用 analysisId。")
            if set(referenced_analysis_ids) - known_analysis_ids:
                issue("outline_analysis_unknown", "批准提纲引用不存在的 analysisId。")
            if outline.report_type != self._envelope(run_context).report_type:
                issue("outline_report_type_mismatch", "提纲报告类型与用户范围不一致。")
        except (ReportingError, TypeError, ValueError, ValidationError):
            outline = None
            issue("outline_invalid", "批准提纲状态无效。")

        try:
            manifest = ReportArtifactManifest.model_validate(
                state.get(REPORT_ARTIFACTS_STATE_KEY, {}).get("draft")
            )
            expected_citations = authoritative_citations(lineage)
            actual_citations = {
                (item.citation_id, item.dataset_id, item.requirement_id, item.snapshot_hash)
                for item in manifest.citations
            }
            expected_citation_values = {
                (item.citation_id, item.dataset_id, item.requirement_id, item.snapshot_hash)
                for item in expected_citations
            }
            if actual_citations != expected_citation_values:
                issue("citation_lineage_invalid", "产物引用未精确绑定当前 DatasetLineage。")
            if manifest.dataset_snapshot_hash != dataset_snapshot_hash(lineage):
                issue("manifest_dataset_snapshot_invalid", "产物清单未绑定当前数据快照。")
            if outline is not None:
                expected_outline_analysis_ids = {
                    analysis_id
                    for section in outline.sections
                    for analysis_id in section.analysis_ids
                }
                if set(manifest.analysis_ids) != expected_outline_analysis_ids:
                    issue("manifest_analysis_binding_invalid", "产物清单未精确绑定批准提纲分析。")
        except (TypeError, ValueError, ValidationError, AttributeError):
            manifest = None
            issue("manifest_invalid", "服务端产物清单状态无效。")

        try:
            durable = await self.state_repository.get(
                str(run_context.run_id or self._scope(run_context)["externalRunId"])
            )
            stored_checkpoint = (
                durable.payload.get("workflowCheckpoint") if durable is not None else None
            )
            checkpoint = ReportingCheckpoint.model_validate(stored_checkpoint)
            if checkpoint.evidence_manifest is None:
                raise ValueError("checkpoint 缺少冻结分析产物")
            analysis_warnings = tuple(
                dict.fromkeys(
                    (
                        *checkpoint.evidence_manifest.warnings,
                        *(
                            warning
                            for evidence in checkpoint.evidence_manifest.evidence
                            for warning in evidence.warnings
                        ),
                    )
                )
            )
            # 缺失月份属于数据质量事实，无法通过重跑修复。报告已经明确披露不可比
            # 口径时允许带警告发布；只有血缘、快照、路径和产物身份等完整性问题
            # 进入 issues 并关闭发布，避免把真实数据缺口误判成系统发布故障。
            warnings.extend(
                _analysis_quality_warnings(
                    checkpoint.evidence_manifest.metric_definitions,
                    analysis_warnings,
                )
            )
        except (TypeError, ValueError, ValidationError, AttributeError):
            issue("analysis_checkpoint_invalid", "发布门禁无法核验冻结分析产物。")

        if result.get("status") != "validated":
            issue("artifact_not_validated", "Markdown、PDF 或 DOCX 尚未完成验收。")
        for key in ("markdownPath", "pdfPath", "wordPath"):
            path = result.get(key)
            if not isinstance(path, str) or not path:
                issue("artifact_identity_invalid", "验收回执缺少产物路径。", field=key)
                continue
            try:
                current = await self.workspace_service.ahash_file(thread_id, path)
                expected_size: Any
                expected_sha: Any
                if key == "markdownPath" and manifest is not None:
                    expected_size = manifest.markdown.size
                    expected_sha = manifest.markdown.sha256
                else:
                    expected_size = result.get(key.replace("Path", "Size"))
                    expected_sha = result.get(key.replace("Path", "Sha256"))
                if (
                    current.get("missing")
                    or current.get("size") != expected_size
                    or current.get("sha256") != expected_sha
                ):
                    issue("artifact_identity_changed", "已验收产物在发布前发生变化。", field=key)
            except Exception:
                issue("artifact_path_invalid", "已验收产物路径不可读取或越界。", field=key)

        return {
            "formalReleaseAllowed": not issues,
            "issues": issues,
            "warnings": warnings,
        }

    async def publish_report(self, step_input: StepInput, run_context: RunContext) -> StepOutput:
        feedback = self._feedback(step_input)
        if feedback:
            await self._run_coding(run_context, feedback=feedback)
            await self._render_and_validate(run_context)
        result = self._workflow_result(self._state(run_context))
        state = self._state(run_context)
        try:
            ReportArtifactManifest.model_validate(state[REPORT_ARTIFACTS_STATE_KEY]["draft"])
        except Exception as error:
            raise ReportingError(
                "report_artifact_manifest_invalid", "发布门禁缺少已验收的产物清单。"
            ) from error
        gate = await self._dataset_publication_gate(run_context, result)
        return StepOutput(
            content={
                "status": "validated",
                "formalReleaseAllowed": gate["formalReleaseAllowed"],
                "publicationGate": gate,
                "jobId": result["jobId"],
                "reportId": str(run_context.run_id),
                "revision": int(result.get("revision", 0)) + 1,
                "markdownPath": result["markdownPath"],
                "pdfPath": result["pdfPath"],
                "pdfSize": result["pdfSize"],
                "pdfSha256": result["pdfSha256"],
                "wordPath": result["wordPath"],
                "wordSize": result["wordSize"],
                "wordSha256": result["wordSha256"],
                "validation": result["validation"],
                "sourceWarnings": result.get("sourceWarnings", []),
                "codingReceipts": result.get("codingReceipts", []),
            }
        )

    async def _build_and_write_artifact_manifest(
        self,
        manifest_path: str,
        *,
        accepted_artifacts: list[dict[str, Any]],
        markdown_path: str,
        lineage: tuple[DatasetLineage, ...],
        revision: int,
        coding_task_key: str,
        run_context: RunContext,
        source_warnings: tuple[SourceWarning, ...] = (),
    ) -> ReportArtifactManifest:
        scope = self._scope(run_context)
        accepted_by_path: dict[str, dict[str, Any]] = {}
        for item in accepted_artifacts:
            path = item.get("path") if isinstance(item, dict) else None
            if not isinstance(path, str) or path in accepted_by_path:
                raise ReportingError(
                    "report_artifact_acceptance_incomplete", "正式产物回执包含重复或无效路径。"
                )
            accepted_by_path[path] = item
        current_artifacts = await self.workspace_service.abatch_hash_files(
            scope["threadId"], list(accepted_by_path)
        )
        current_by_path = {
            item.get("path"): item
            for item in current_artifacts
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        if (
            len(current_by_path) != len(accepted_by_path)
            or set(current_by_path) != set(accepted_by_path)
            or any(
                current_by_path[path].get("missing")
                or current_by_path[path].get("size") != accepted_by_path[path].get("size")
                or current_by_path[path].get("sha256") != accepted_by_path[path].get("sha256")
                for path in accepted_by_path
            )
        ):
            raise ReportingError("report_artifact_file_changed", "正式产物在完成验收后发生变化。")
        accepted = next(
            (
                item
                for item in current_artifacts
                if isinstance(item, dict) and item.get("path") == markdown_path
            ),
            None,
        )
        if not isinstance(accepted, dict):
            raise ReportingError(
                "report_artifact_acceptance_missing",
                "正式产物验收回执缺少报告 Markdown。",
            )
        _relative, markdown_remote = self.workspace_service.normalize_path(
            markdown_path, allow_root=False
        )
        _relative, manifest_remote = self.workspace_service.normalize_path(
            manifest_path, allow_root=False
        )
        try:
            async with self.workspace_service._async_client() as client:
                sandbox = await self.workspace_service._asandbox_for(client, scope["threadId"])
                markdown_bytes = await self.workspace_service._adownload_file(
                    sandbox, markdown_remote, 10 * 1024 * 1024
                )
            if len(markdown_bytes) != accepted.get("size") or hashlib.sha256(
                markdown_bytes
            ).hexdigest() != accepted.get("sha256"):
                raise ReportingError(
                    "report_artifact_file_changed",
                    "报告 Markdown 在正式验收后发生变化。",
                )
            manifest = build_authoritative_manifest(
                report_id=str(run_context.run_id),
                revision=revision,
                coding_task_key=coding_task_key,
                effective_profile_hash=self._profile(run_context).effective_profile_hash,
                markdown_path=markdown_path,
                markdown=markdown_bytes.decode("utf-8"),
                accepted_artifacts=current_artifacts,
                lineage=lineage,
                sections=tuple(
                    section.code for section in _frozen_outline(self._state(run_context)).sections
                ),
                source_warnings=source_warnings,
            )
            content = json.dumps(
                manifest.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            self.workspace_service._validate_content(content)
            async with self.workspace_service._async_client() as client:
                sandbox = await self.workspace_service._asandbox_for(client, scope["threadId"])
                await self.workspace_service._aensure_directory(
                    sandbox, manifest_remote.rsplit("/", 1)[0]
                )
                await sandbox.fs.upload_file(content, manifest_remote)
                stored = await self.workspace_service._adownload_file(
                    sandbox, manifest_remote, len(content)
                )
            if stored != content:
                raise ReportingError(
                    "report_artifact_manifest_changed",
                    "服务端报告产物清单写入后发生变化。",
                )
        except ReportingError:
            raise
        except Exception as error:
            raise ReportingError(
                "report_artifact_manifest_invalid", "服务端无法生成报告产物清单。"
            ) from error
        return manifest

    async def _run_planner(
        self, agent: Agent, payload: dict[str, Any], run_context: RunContext
    ) -> BaseModel:
        scope = self._scope(run_context)
        block_identity = payload.get("analysisBlock")
        if isinstance(block_identity, Mapping):
            session_suffix = str(block_identity.get("blockId", ""))
        else:
            session_suffix = ""
        digest = hashlib.sha256(
            f"{run_context.run_id}:{agent.id}:{session_suffix}".encode()
        ).hexdigest()[:32]
        serialized_payload = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), default=str
        )
        input_bytes = serialized_payload.encode()
        input_sha256 = hashlib.sha256(input_bytes).hexdigest()
        logger.info(
            "report_planner_request agent_id=%s block_id=%s attempt=%s "
            "input_bytes=%s input_sha256=%s",
            agent.id,
            session_suffix or "-",
            (
                payload["correction"].get("attempt", 1)
                if isinstance(payload.get("correction"), Mapping)
                else 1
            ),
            len(input_bytes),
            input_sha256,
        )
        output = await agent.arun(
            serialized_payload,
            session_id=f"report-planning-{digest}",
            user_id=scope["userId"],
            stream=False,
        )
        _raise_recorded_agent_error(agent)
        content = getattr(output, "content", None)
        if isinstance(content, str) and (
            "不可约简的编码上下文前缀与工具 schema 超过模型输入 hard cap" in content
        ):
            raise ReportingError(
                "report_planner_context_budget_exceeded",
                f"报表规划输入超过当前模型上下文预算（{agent.id}）。",
            )
        metrics = getattr(output, "metrics", None)
        record_step_model_metrics(metrics)
        content_bytes = _payload_bytes(content)
        logger.info(
            "report_planner_response agent_id=%s input_sha256=%s output_bytes=%s "
            "output_sha256=%s input_tokens=%s output_tokens=%s total_tokens=%s "
            "reasoning_tokens=%s cache_read_tokens=%s cache_write_tokens=%s "
            "duration=%s time_to_first_token=%s",
            agent.id,
            input_sha256,
            len(content_bytes),
            hashlib.sha256(content_bytes).hexdigest(),
            getattr(metrics, "input_tokens", None),
            getattr(metrics, "output_tokens", None),
            getattr(metrics, "total_tokens", None),
            getattr(metrics, "reasoning_tokens", None),
            getattr(metrics, "cache_read_tokens", None),
            getattr(metrics, "cache_write_tokens", None),
            getattr(metrics, "duration", None),
            getattr(metrics, "time_to_first_token", None),
        )
        schema = agent.output_schema
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise ReportingError("report_planner_invalid", "报表规划器缺少结构化输出。")
        schema_model = cast(type[BaseModel], schema)
        if not isinstance(content, schema_model):
            raise TypeError(f"报表规划器 {agent.id} 未返回已校验的 {schema_model.__name__}。")
        return content

    def _envelope(self, run_context: RunContext) -> ReportRequestEnvelope:
        return ReportRequestEnvelope.from_untrusted(
            self._state(run_context).get(REPORT_WORKFLOW_INPUT_STATE_KEY)
        )

    def _snapshots(self, run_context: RunContext) -> tuple[SourceSchemaSnapshot, ...]:
        try:
            return tuple(
                SourceSchemaSnapshot.model_validate(item)
                for item in self._state(run_context)[REPORT_SCHEMA_SNAPSHOTS_STATE_KEY]
            )
        except Exception as error:
            raise ReportingError("report_schema_snapshot_invalid", "结构快照状态无效。") from error

    def _data_understanding(self, run_context: RunContext) -> DataUnderstandingPlan:
        try:
            return DataUnderstandingPlan.model_validate(
                self._state(run_context)[REPORT_DATA_UNDERSTANDING_STATE_KEY]
            )
        except Exception as error:
            raise ReportingError(
                "report_data_understanding_invalid", "数据理解计划状态无效。"
            ) from error

    def _profile(self, run_context: RunContext) -> EffectiveReportingProfile:
        try:
            return EffectiveReportingProfile.model_validate(
                self._state(run_context)[REPORT_EFFECTIVE_PROFILE_STATE_KEY]
            )
        except Exception as error:
            raise ReportingError(
                "report_profile_state_invalid", "有效 Profile 状态无效。"
            ) from error

    def _capabilities(self, run_context: RunContext) -> CapabilitySet:
        try:
            return CapabilitySet.model_validate(
                self._state(run_context)[REPORT_CAPABILITIES_STATE_KEY]
            )
        except Exception as error:
            raise ReportingError("report_capability_state_invalid", "报表能力状态无效。") from error

    def _data_shapes(self, run_context: RunContext) -> tuple[DataShape, ...]:
        try:
            return tuple(
                DataShape.model_validate(item)
                for item in self._state(run_context)[REPORT_DATA_SHAPES_STATE_KEY]
            )
        except Exception as error:
            raise ReportingError("report_data_shape_state_invalid", "数据画像状态无效。") from error

    def _resolve_profile(
        self, sources: tuple[StarRocksSourceConfig, ...]
    ) -> EffectiveReportingProfile:
        profile_ids = {source.reporting_profile for source in sources}
        if len(profile_ids) != 1:
            raise ReportingError("report_profile_conflict", "本次数据源未绑定同一个报表 Profile。")
        try:
            return resolve_reporting_profile(self.profiles, next(iter(profile_ids)))
        except ValueError as error:
            raise ReportingError("report_profile_invalid", "报表 Profile 无效。") from error

    def _sources(self, run_context: RunContext) -> tuple[StarRocksSourceConfig, ...]:
        return tuple(self._source(item) for item in self._envelope(run_context).source_ids or ())

    def _source(self, source_id: str) -> StarRocksSourceConfig:
        return self._starrocks_source(require_sources(self.registry.sources, (source_id,))[0])

    def _adapter(
        self, source: StarRocksSourceConfig, run_context: RunContext
    ) -> StarRocksDataSourceAdapter:
        allowed_tables = tuple(
            f"{table.database.lower()}.{table.name.lower()}"
            for snapshot in self._snapshots(run_context)
            for table in snapshot.tables
            if table.source_id == source.id
        )
        return StarRocksDataSourceAdapter(source, allowed_tables=allowed_tables)

    @staticmethod
    def _starrocks_source(source: Any) -> StarRocksSourceConfig:
        if not isinstance(source, StarRocksSourceConfig):
            raise ReportingError("report_source_type_invalid", "v1 仅支持 StarRocks 数据源。")
        return source

    @staticmethod
    def _feedback(step_input: StepInput) -> str | None:
        value = (step_input.additional_data or {}).get("rejection_feedback")
        return str(value).strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _state(run_context: RunContext) -> dict[str, Any]:
        if not isinstance(run_context.session_state, dict):
            raise ReportingError("report_workflow_state_invalid", "报表工作流状态无效。")
        return run_context.session_state

    async def _apply_durable_command(
        self,
        run_context: RunContext,
        command: ReportingCommand,
    ) -> Any:
        scope = self._scope(run_context)
        report_run_id = str(run_context.run_id or scope["externalRunId"])
        durable = await self.state_repository.get_by_external_run_id(scope["externalRunId"])
        if durable is None:
            durable = await self.state_repository.get_or_create(
                report_run_id=report_run_id,
                external_run_id=scope["externalRunId"],
                thread_id=scope["threadId"],
                owner_user_id=scope["userId"],
            )
        # 多个章节 child task 可以同时完成；CAS 冲突只重读当前版本并重放同一
        # commandId。Reducer 对已应用 command 返回幂等结果，副作用不会重复。
        async with self._durable_command_lock:
            for _ in range(3):
                durable = await self.state_repository.get_by_external_run_id(scope["externalRunId"])
                if durable is None:
                    durable = await self.state_repository.get_or_create(
                        report_run_id=report_run_id,
                        external_run_id=scope["externalRunId"],
                        thread_id=scope["threadId"],
                        owner_user_id=scope["userId"],
                    )
                try:
                    return await self.state_repository.apply(
                        durable.report_run_id,
                        command,
                        expected_version=durable.state_version,
                    )
                except ReportingStateError as error:
                    if error.code == "report_state_conflict":
                        continue
                    raise ReportingError(error.code, error.message) from error
            raise ReportingError("report_state_conflict", "Reporting 状态并发更新冲突，请重试。")

    @staticmethod
    def _assert_state_safe(state: dict[str, Any]) -> None:
        if state_contains_connection_data(state):
            raise ReportingError("state_contains_connection_data", "Workflow state 包含连接信息。")

    @staticmethod
    def _scope(run_context: RunContext) -> dict[str, str]:
        state = ReportWorkflowRuntime._state(run_context)
        value = (run_context.dependencies or {}).get("AgentOS 报表工作流")
        if isinstance(value, dict):
            scope = {
                key: str(value.get(key) or "") for key in ("externalRunId", "threadId", "userId")
            }
        else:
            value = state.get(REPORT_WORKFLOW_SCOPE_STATE_KEY)
            scope = (
                {key: str(value.get(key) or "") for key in ("externalRunId", "threadId", "userId")}
                if isinstance(value, dict)
                else {
                    "externalRunId": str(run_context.run_id or ""),
                    "threadId": str(run_context.session_id or ""),
                    "userId": str(run_context.user_id or ""),
                }
            )
        if (
            any(not item for item in scope.values())
            or str(run_context.user_id or "") != scope["userId"]
        ):
            raise ReportingError("report_workflow_context_missing", "报表工作流作用域不完整。")
        state[REPORT_WORKFLOW_SCOPE_STATE_KEY] = dict(scope)
        return scope

    @staticmethod
    def _workflow_result(state: dict[str, Any]) -> dict[str, Any]:
        value = state.get(REPORT_WORKFLOW_RESULT_STATE_KEY)
        if not isinstance(value, dict):
            raise ReportingError("report_workflow_result_invalid", "报表工作流产物状态无效。")
        return dict(value)

    @staticmethod
    def _publication_content(output: Any) -> dict[str, Any]:
        content = output if isinstance(output, dict) else getattr(output, "content", None)
        if not isinstance(content, dict):
            raise ReportingError("report_publication_invalid", "报表发布产物无效。")
        values = {
            "reportId": content.get("reportId"),
            "revision": content.get("revision"),
            "pdfPath": content.get("pdfPath"),
            "pdfSize": content.get("pdfSize"),
            "pdfSha256": content.get("pdfSha256"),
            "wordPath": content.get("wordPath"),
            "wordSize": content.get("wordSize"),
            "wordSha256": content.get("wordSha256"),
            "sourceWarnings": content.get("sourceWarnings", []),
            "codingReceipts": content.get("codingReceipts", []),
        }
        if (
            not isinstance(values["reportId"], str)
            or not isinstance(values["revision"], int)
            or not isinstance(values["pdfPath"], str)
            or not isinstance(values["pdfSize"], int)
            or values["pdfSize"] <= 0
            or not isinstance(values["pdfSha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", values["pdfSha256"]) is None
            or not isinstance(values["wordPath"], str)
            or not isinstance(values["wordSize"], int)
            or values["wordSize"] <= 0
            or not isinstance(values["wordSha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", values["wordSha256"]) is None
            or not isinstance(values["sourceWarnings"], list)
            or not isinstance(values["codingReceipts"], list)
        ):
            raise ReportingError("report_publication_invalid", "报表发布产物无效。")
        try:
            values["sourceWarnings"] = [
                SourceWarning.model_validate(item).model_dump(mode="json", by_alias=True)
                for item in values["sourceWarnings"]
            ]
            values["codingReceipts"] = [
                PlanExecutionReceipt.model_validate(item).model_dump(mode="json", by_alias=True)
                for item in values["codingReceipts"]
            ]
        except Exception as error:
            raise ReportingError(
                "report_publication_invalid",
                "报表来源告警或 Coding 回执无效。",
            ) from error
        return values

    @staticmethod
    def _require_artifact_identity(
        expected: dict[str, Any],
        current: dict[str, Any],
        *,
        artifact: Literal["pdf", "word"],
    ) -> None:
        prefix = "pdf" if artifact == "pdf" else "word"
        if (
            current.get("size") != expected[f"{prefix}Size"]
            or current.get("sha256") != expected[f"{prefix}Sha256"]
        ):
            raise ReportingError(
                "report_artifact_changed",
                "PDF 或 Word 在验收或审核后发生变化，必须重新验收。",
            )

    def _tool_context(self, run_context: RunContext) -> RunContext:
        scope = self._scope(run_context)
        return RunContext(
            run_id=run_context.run_id,
            session_id=scope["threadId"],
            user_id=scope["userId"],
            session_state=run_context.session_state,
            dependencies=run_context.dependencies,
        )


def _model_table(table: Any) -> ModelTable:
    return ModelTable(
        sourceId=table.source_id,
        database=table.database,
        name=table.name,
        columns=tuple(
            ModelColumn(name=item.name, dataType=item.data_type, nullable=item.nullable)
            for item in table.columns
        ),
    )


def _catalog_scope(tables: tuple[ModelTable, ...]) -> tuple[CatalogTable, ...]:
    return tuple(
        CatalogTable(
            source_id=table.source_id,
            database=table.database,
            name=table.name,
            columns=tuple(
                CatalogColumn(
                    name=column.name,
                    data_type=column.data_type,
                    nullable=column.nullable,
                )
                for column in table.columns
            ),
        )
        for table in tables
    )


def _planning_schemas(
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> tuple[PlanningSchema, ...]:
    return tuple(
        PlanningSchema(
            tables=tuple(
                PlanningSchemaTable(
                    sourceId=table.source_id,
                    table=f"{table.database}.{table.name}",
                    description=table.description,
                    columns=tuple(
                        PlanningSchemaColumn(
                            name=column.name,
                            dataType=column.data_type,
                            description=column.description,
                        )
                        for column in table.columns
                    ),
                )
                for table in snapshot.tables
            ),
            measureSemantics=snapshot.measure_semantics,
        )
        for snapshot in snapshots
    )


def _planning_schema_payload(
    snapshots: tuple[SourceSchemaSnapshot, ...],
    *,
    tables: set[str] | None = None,
    description_limit: int | None = None,
) -> list[dict[str, Any]]:
    normalized_tables = {item.lower() for item in tables} if tables is not None else None
    payload: list[dict[str, Any]] = []
    for schema in _planning_schemas(snapshots):
        selected = tuple(
            table
            for table in schema.tables
            if normalized_tables is None or table.table.lower() in normalized_tables
        )
        if selected:
            schema_payload = schema.model_copy(update={"tables": selected}).model_dump(
                mode="json", by_alias=True
            )
            if description_limit is not None:
                for table_payload in schema_payload["tables"]:
                    table_payload["description"] = _bounded_description(
                        table_payload["description"], description_limit
                    )
                    for column_payload in table_payload["columns"]:
                        column_payload["description"] = _bounded_description(
                            column_payload["description"], description_limit
                        )
            payload.append(schema_payload)
    return payload


def _profile_scope_filters_by_table(
    profile: EffectiveReportingProfile,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> dict[tuple[str, str, str], dict[str, str]]:
    table_columns = {
        (table.source_id.lower(), table.database.lower(), table.name.lower()): {
            column.name.lower() for column in table.columns
        }
        for snapshot in snapshots
        for table in snapshot.tables
    }
    constraints: dict[tuple[str, str, str], dict[str, str]] = {}
    for scope_filter in profile.scope_filters:
        refs_by_table: dict[tuple[str, str, str], list[str]] = {}
        for field_ref in scope_filter.field_refs:
            parsed = parse_field_ref(field_ref)
            table_key = (
                parsed.source_id.lower(),
                parsed.database.lower(),
                parsed.table.lower(),
            )
            refs_by_table.setdefault(table_key, []).append(parsed.column.lower())
        if any(len(columns) != 1 for columns in refs_by_table.values()):
            raise ReportingError(
                "report_profile_scope_filter_invalid",
                f"Profile 范围过滤 {scope_filter.code} 在同一表中必须只映射一个字段。",
            )
        if scope_filter.required_for_all_tables and set(table_columns) - set(refs_by_table):
            raise ReportingError(
                "report_profile_scope_filter_invalid",
                f"Profile 范围过滤 {scope_filter.code} 未覆盖结构快照中的全部表。",
            )
        for table_key, columns in refs_by_table.items():
            # Profile 可以覆盖同一医院数据源的表超集；本次 Snapshot 未包含的表按现有
            # capability 缩小原则忽略。只要表实际进入 Snapshot，就必须验证物理字段。
            available = table_columns.get(table_key)
            if available is None:
                continue
            column = columns[0]
            if column not in available:
                raise ReportingError(
                    "report_profile_scope_filter_invalid",
                    f"Profile 范围过滤 {scope_filter.code} 引用了结构快照外的字段。",
                )
            table_constraints = constraints.setdefault(table_key, {})
            current = table_constraints.get(column)
            if current is not None and current != scope_filter.value:
                raise ReportingError(
                    "report_profile_scope_filter_conflict",
                    f"Profile 范围过滤在同一字段上声明了冲突值: {field_ref}",
                )
            table_constraints[column] = scope_filter.value
    return constraints


def _semantic_with_scope_filters(
    semantic: MeasureSemantic,
    constraints: dict[tuple[str, str, str], dict[str, str]],
) -> MeasureSemantic:
    parsed = parse_field_ref(semantic.field_ref)
    required = constraints.get(
        (parsed.source_id.lower(), parsed.database.lower(), parsed.table.lower()), {}
    )
    exclusive_scope = dict(semantic.exclusive_scope)
    for column, value in required.items():
        current = exclusive_scope.get(column)
        if current is not None and current != value:
            raise ReportingError(
                "report_profile_scope_filter_conflict",
                f"指标语义与 Profile 强制范围冲突: {semantic.field_ref}.{column}",
            )
        exclusive_scope[column] = value
    return semantic.model_copy(update={"exclusive_scope": exclusive_scope})


def _apply_profile_scope_filters_to_snapshots(
    snapshots: tuple[SourceSchemaSnapshot, ...],
    profile: EffectiveReportingProfile,
) -> tuple[SourceSchemaSnapshot, ...]:
    constraints = _profile_scope_filters_by_table(profile, snapshots)
    updated: list[SourceSchemaSnapshot] = []
    for snapshot in snapshots:
        payload = snapshot.model_dump(mode="json", by_alias=True)
        payload["measureSemantics"] = [
            _semantic_with_scope_filters(item, constraints).model_dump(mode="json", by_alias=True)
            for item in snapshot.measure_semantics
        ]
        try:
            updated.append(SourceSchemaSnapshot.model_validate(payload))
        except ValidationError as error:
            raise ReportingError(
                "report_profile_scope_filter_invalid",
                "Profile 强制范围无法应用到结构快照指标语义。",
            ) from error
    return tuple(updated)


def _proposal_with_profile_scope_filters(
    proposal: MeasureSemanticProposal,
    snapshots: tuple[SourceSchemaSnapshot, ...],
    profile: EffectiveReportingProfile,
) -> MeasureSemanticProposal:
    constraints = _profile_scope_filters_by_table(profile, snapshots)
    return proposal.model_copy(
        update={
            "decisions": tuple(
                decision.model_copy(
                    update={
                        "measure_semantic": _semantic_with_scope_filters(
                            decision.measure_semantic, constraints
                        )
                    }
                )
                if decision.measure_semantic is not None
                else decision
                for decision in proposal.decisions
            )
        }
    )


def _measure_semantic_candidate_refs(
    snapshots: tuple[SourceSchemaSnapshot, ...],
    plan: DataUnderstandingPlan,
    profile: EffectiveReportingProfile,
) -> tuple[str, ...]:
    """确定必须由模型分类并经用户确认的数值字段集合。"""

    selected_period_columns = {
        (item.source_id.lower(), item.table.lower()): item.period_column.lower()
        for item in plan.tables
    }
    existing_semantics = {
        item.field_ref.lower() for snapshot in snapshots for item in snapshot.measure_semantics
    }
    profile_dimensions = {
        field_ref.lower() for dimension in profile.dimensions for field_ref in dimension.field_refs
    }
    profile_metrics = {
        metric.field_ref.lower() for metric in profile.metrics if metric.field_ref is not None
    }
    candidates: list[str] = []

    # DDL 只能证明字段是数值类型，不能证明它是可聚合指标。程序先排除已确认
    # 语义、已声明维度和本次期间字段，再让模型对剩余字段逐项提出候选。Profile
    # 同时把同一字段声明为 metric 和 dimension 时，以 metric 为待确认对象，避免
    # 配置冲突被静默解释成维度后绕过指标语义审核。
    for snapshot in snapshots:
        for table in snapshot.tables:
            qualified = f"{table.database.lower()}.{table.name.lower()}"
            period_column = selected_period_columns.get((table.source_id.lower(), qualified))
            if period_column is None:
                continue
            for column in table.columns:
                field_ref = f"{table.source_id}.{table.database}.{table.name}.{column.name}".lower()
                if field_ref in existing_semantics:
                    continue
                if _NUMERIC_MEASURE_TYPE_PATTERN.match(column.data_type) is None:
                    continue
                if column.name.lower() == period_column:
                    continue
                if field_ref in profile_dimensions and field_ref not in profile_metrics:
                    continue
                candidates.append(field_ref)
    return tuple(candidates)


def _apply_confirmed_measure_semantics(
    snapshots: tuple[SourceSchemaSnapshot, ...],
    proposal: MeasureSemanticProposal,
    expected_refs: tuple[str, ...],
) -> tuple[SourceSchemaSnapshot, ...]:
    """验证用户审核对象并生成只包含已确认语义的新快照。"""

    actual_refs = tuple(item.field_ref for item in proposal.decisions)
    if set(actual_refs) != set(expected_refs) or len(actual_refs) != len(expected_refs):
        raise ReportingError(
            "report_measure_semantic_proposal_invalid",
            "指标语义候选必须完整且只能分类当前待确认字段。",
        )

    additions = {
        decision.field_ref: decision.measure_semantic
        for decision in proposal.decisions
        if decision.classification == "measure" and decision.measure_semantic is not None
    }
    available_by_snapshot = [
        {
            f"{table.source_id}.{table.database}.{table.name}.{column.name}".lower()
            for table in snapshot.tables
            for column in table.columns
        }
        for snapshot in snapshots
    ]
    if set(actual_refs) - set().union(*available_by_snapshot):
        raise ReportingError(
            "report_measure_semantic_proposal_invalid",
            "指标语义候选引用了结构快照外的字段。",
        )

    updated: list[SourceSchemaSnapshot] = []
    for snapshot, available in zip(snapshots, available_by_snapshot, strict=True):
        snapshot_additions = tuple(
            semantic
            for field_ref, semantic in additions.items()
            if field_ref in available and semantic is not None
        )
        payload = snapshot.model_dump(mode="json", by_alias=True)
        payload["measureSemantics"] = [
            item.model_dump(mode="json", by_alias=True)
            for item in (*snapshot.measure_semantics, *snapshot_additions)
        ]
        try:
            # 重新走 SourceSchemaSnapshot 的完整 Pydantic 校验，确保 additiveAcross、
            # exclusiveScope 和 reconcileWith 只能引用同一受信结构快照中的真实字段。
            # model_copy(update=...) 默认不重跑 validator，因此这里不能使用它提交候选。
            updated.append(SourceSchemaSnapshot.model_validate(payload))
        except ValidationError as error:
            raise ReportingError(
                "report_measure_semantic_proposal_invalid",
                "指标语义候选包含未知维度、固定口径或对账字段。",
            ) from error
    return tuple(updated)


def _validate_proposed_exclusive_scopes(
    proposal: MeasureSemanticProposal,
    data_shapes: tuple[DataShape, ...],
    *,
    trusted_profile: EffectiveReportingProfile | None = None,
) -> None:
    """拒绝模型把字段说明或类别名称伪装成已观测的固定口径值。"""
    observed_values = {
        (
            table.source_id.lower(),
            table.database.lower(),
            table.table.lower(),
            column.name.lower(),
        ): {str(item.value) for item in column.top_values}
        for shape in data_shapes
        for table in shape.tables
        for column in table.columns
    }
    trusted_values = {
        (
            parsed.source_id.lower(),
            parsed.database.lower(),
            parsed.table.lower(),
            parsed.column.lower(),
            scope_filter.value,
        )
        for scope_filter in (() if trusted_profile is None else trusted_profile.scope_filters)
        for field_ref in scope_filter.field_refs
        for parsed in (parse_field_ref(field_ref),)
    }
    for decision in proposal.decisions:
        semantic = decision.measure_semantic
        if semantic is None:
            continue
        parsed = parse_field_ref(semantic.field_ref)
        for column, value in semantic.exclusive_scope.items():
            observed = observed_values.get(
                (
                    parsed.source_id.lower(),
                    parsed.database.lower(),
                    parsed.table.lower(),
                    column.lower(),
                ),
                set(),
            )
            # 模型只能从本次受限画像引用精确值；没有 topValues 不是放宽理由。
            # 部署方明确声明的 Profile scopeFilters 在此校验之后合并，继续以受信
            # 配置为事实来源，不受画像采样上限影响。
            trusted_key = (
                parsed.source_id.lower(),
                parsed.database.lower(),
                parsed.table.lower(),
                column.lower(),
                value,
            )
            if value not in observed and trusted_key not in trusted_values:
                allowed = sorted(observed)
                suffix = f"；允许值：{allowed}" if allowed else "；该字段没有可引用的观测值"
                raise ReportingError(
                    "report_measure_semantic_scope_unobserved",
                    f"指标固定口径未被受限画像证明: {semantic.field_ref}.{column}={value!r}"
                    f"{suffix}。无法证明时必须删除该 exclusiveScope 项。",
                )


def _bounded_description(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _schema_scope_tables(
    envelope: ReportRequestEnvelope,
    *,
    source: StarRocksSourceConfig,
    metadata: ModelTermsResponse | None,
) -> tuple[ModelTable, ...]:
    if metadata is not None:
        tables = tuple(table for table in metadata.tables if table.source_id == source.id)
    elif envelope.schema_input is not None and envelope.schema_input.ddl:
        tables = parse_ddl(
            envelope.schema_input.ddl,
            source_id=source.id,
            default_database=source.database,
        )
    else:
        tables = ()
    if not tables:
        raise ReportingError("report_schema_required", "当前数据源没有可用 DDL 模型。")
    if any(table.database.lower() != source.database.lower() for table in tables):
        raise ReportingError("report_schema_not_allowed", "DDL 数据表不属于当前数据源数据库。")
    return tables


def _data_understanding_result(
    output: Any,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> tuple[DataUnderstandingPlan | None, Any, dict[str, Any] | None]:
    if isinstance(output, BaseModel):
        raw_output: Any = output.model_dump(mode="json", by_alias=True)
    elif isinstance(output, str):
        try:
            raw_output = json.loads(output)
        except ValueError:
            raw_output = output
    else:
        raw_output = output

    plan: DataUnderstandingPlan | None = None
    structural_issues: list[dict[str, Any]] = []
    try:
        plan = DataUnderstandingPlan.model_validate(raw_output)
    except ValidationError as error:
        structural_issues = [
            _structure_validation_issue(item, raw_output, snapshots)
            for item in error.errors(include_url=False)
        ]

    semantic_issues = _semantic_data_understanding_issues(raw_output, snapshots)
    issues_by_path = {item["path"]: item for item in structural_issues}
    issues_by_path.update({item["path"]: item for item in semantic_issues})
    issues = list(issues_by_path.values())
    if plan is not None and not issues:
        return plan, raw_output, None
    feedback = {
        "code": "report_data_understanding_invalid",
        "summary": "数据理解计划不符合严格输出契约或输入 Schema 引用",
        "issues": issues,
    }
    return None, raw_output, feedback


def _structure_validation_issue(
    error: Mapping[str, Any],
    raw_output: Any,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> dict[str, Any]:
    location = tuple(error.get("loc", ()))
    path = _validation_path(location)
    rejected = None if error.get("type") == "missing" else error.get("input")
    candidates = _table_references(snapshots)
    allowed_values: list[Any] = []
    field = location[-1] if location else None
    if field in {"sourceId", "table"} or path == "tables":
        source_id = _raw_table_source(raw_output, location)
        allowed_values = _table_reference_values(candidates, source_id=source_id)
    elif field == "periodColumn":
        allowed_values = list(_raw_table_columns(raw_output, location, snapshots))
    elif field == "periodGranularity":
        allowed_values = ["date", "month", "year"]

    error_type = str(error.get("type", "validation_error"))
    if field == "table" and isinstance(rejected, str):
        reason = _invalid_table_reason(rejected, snapshots)
        required_action = "从 allowedValues 选择一项并完整复制 sourceId 和 table"
    elif field == "sourceId":
        reason = "sourceId 必须是输入 Schema 中存在且完全一致的字符串"
        required_action = "从 allowedValues 选择一项并完整复制 sourceId 和 table"
    elif field == "periodColumn":
        reason = "periodColumn 必须是对应输入表 columns[].name 中的字符串"
        required_action = "从 allowedValues 选择一个字段并返回完整 DataUnderstandingPlan"
    elif field == "periodGranularity":
        reason = "periodGranularity 只能是 date、month 或 year"
        required_action = "根据期间字段值的时间语义选择 date、month 或 year"
    elif error_type == "extra_forbidden":
        reason = "输出包含 Schema 未定义的多余字段"
        required_action = "删除该字段并返回完整 DataUnderstandingPlan"
    elif error_type == "missing":
        reason = "输出缺少严格 Schema 要求的必填字段"
        required_action = "补齐该字段并返回完整 DataUnderstandingPlan"
    else:
        reason = f"字段不符合严格输出 Schema：{error_type}"
        required_action = "按输出 Schema 修正该字段并返回完整 DataUnderstandingPlan"
    return _validation_issue(
        path=path,
        rejected_value=rejected,
        reason=reason,
        allowed_values=allowed_values,
        required_action=required_action,
    )


def _semantic_data_understanding_issues(
    raw_output: Any,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> list[dict[str, Any]]:
    if not isinstance(raw_output, dict) or not isinstance(raw_output.get("tables"), list):
        return []
    candidates = _table_references(snapshots)
    available_columns = _available_table_columns(snapshots)
    available_tables = _available_tables(snapshots)
    source_ids = {item.source_id for item in candidates}
    selected: set[tuple[str, str]] = set()
    issues: list[dict[str, Any]] = []
    for index, raw_table in enumerate(raw_output["tables"]):
        if not isinstance(raw_table, dict):
            continue
        source_id = raw_table.get("sourceId")
        table = raw_table.get("table")
        if isinstance(source_id, str) and source_id not in source_ids:
            issues.append(
                _validation_issue(
                    path=f"tables[{index}].sourceId",
                    rejected_value=source_id,
                    reason="sourceId 不存在于输入 Schema",
                    allowed_values=_table_reference_values(candidates),
                    required_action="从 allowedValues 选择一项并完整复制 sourceId 和 table",
                )
            )
        if not isinstance(source_id, str) or not isinstance(table, str):
            continue
        key = (source_id, table.lower())
        columns = available_columns.get(key)
        allowed_tables = _table_reference_values(candidates, source_id=source_id)
        if columns is None:
            issues.append(
                _validation_issue(
                    path=f"tables[{index}].table",
                    rejected_value=table,
                    reason=_invalid_table_reason(table, snapshots),
                    allowed_values=allowed_tables or _table_reference_values(candidates),
                    required_action="从 allowedValues 选择一项并完整复制 sourceId 和 table",
                )
            )
            continue
        if key in selected:
            issues.append(
                _validation_issue(
                    path=f"tables[{index}].table",
                    rejected_value=table,
                    reason="同一 sourceId/table 组合不能重复选择",
                    allowed_values=allowed_tables,
                    required_action="删除重复项或选择另一个完整表引用",
                )
            )
        else:
            selected.add(key)
        period_column = raw_table.get("periodColumn")
        if isinstance(period_column, str) and period_column.lower() not in {
            item.lower() for item in columns
        }:
            issues.append(
                _validation_issue(
                    path=f"tables[{index}].periodColumn",
                    rejected_value=period_column,
                    reason="periodColumn 不属于对应输入表的 columns[].name",
                    allowed_values=list(columns),
                    required_action=(
                        "从 allowedValues 选择一个字段并返回完整 DataUnderstandingPlan"
                    ),
                )
            )
        elif isinstance(period_column, str):
            granularity = raw_table.get("periodGranularity")
            table_model = available_tables[key]
            choices = _period_encoding_choices(table_model)
            selected_choice = next(
                (
                    item
                    for item in choices
                    if item["periodColumn"].lower() == period_column.lower()
                    and item["periodGranularity"] == granularity
                ),
                None,
            )
            if selected_choice is None and granularity in {"date", "month", "year"}:
                column = next(
                    item
                    for item in table_model.columns
                    if item.name.lower() == period_column.lower()
                )
                issues.append(
                    _validation_issue(
                        path=f"tables[{index}].periodGranularity",
                        rejected_value=granularity,
                        reason=(
                            f"periodColumn {period_column} 的实际类型是 {column.data_type}，"
                            f"字段名称或说明不能支持 {granularity} 时间语义；"
                            "请按字段值实际表达的完整日期、月份或年份声明粒度"
                        ),
                        allowed_values=choices,
                        required_action=(
                            "从 allowedValues 完整复制 periodColumn 和 periodGranularity；"
                            "字符串字段可以承载 date、month 或 year，但必须与值语义一致"
                        ),
                    )
                )
    return issues


def _bounded_rejected_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return {"truncated": True, "type": type(value).__name__}
    if isinstance(value, str):
        if len(value) <= 500:
            return value
        return value[:500] + f"...[truncated {len(value) - 500} chars]"
    if isinstance(value, Mapping):
        items = list(value.items())
        bounded_mapping = {
            str(key): _bounded_rejected_value(item, depth=depth + 1) for key, item in items[:16]
        }
        if len(items) > 16:
            bounded_mapping["__truncated__"] = {"omittedKeys": len(items) - 16}
        return bounded_mapping
    if isinstance(value, (list, tuple)):
        bounded_sequence = [_bounded_rejected_value(item, depth=depth + 1) for item in value[:8]]
        if len(value) > 8:
            bounded_sequence.append({"__truncated__": {"omittedItems": len(value) - 8}})
        return bounded_sequence
    return value


def _payload_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode()


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_payload_bytes(value)).hexdigest()


def _json_diff_paths(previous: Any, current: Any, path: str = "") -> list[str]:
    if type(previous) is not type(current):
        return [path or "$"]
    if isinstance(previous, Mapping):
        paths: list[str] = []
        keys = sorted(set(previous) | set(current))
        for key in keys:
            child = f"{path}.{key}" if path else str(key)
            if key not in previous or key not in current:
                paths.append(child)
            else:
                paths.extend(_json_diff_paths(previous[key], current[key], child))
        return paths
    if isinstance(previous, (list, tuple)):
        if len(previous) != len(current):
            return [path or "$"]
        paths = []
        for index, (left, right) in enumerate(zip(previous, current, strict=True)):
            paths.extend(_json_diff_paths(left, right, f"{path}[{index}]"))
        return paths
    return [] if previous == current else [path or "$"]


def _unexpected_correction_paths(
    previous: dict[str, Any],
    current: dict[str, Any],
    allowed_paths: tuple[str, ...],
    required_deletion_paths: tuple[str, ...] = (),
) -> list[str]:
    return [
        path
        for path in _analysis_bundle_diff_paths(previous, current)
        if path not in required_deletion_paths
        and not any(_correction_path_allowed(path, allowed) for allowed in allowed_paths)
    ]


def _analysis_bundle_diff_paths(previous: Any, current: Any) -> list[str]:
    """按稳定业务标识比较计划列表，使定点删除不会放宽其他对象的修改权限。"""

    if not isinstance(previous, Mapping) or not isinstance(current, Mapping):
        return _json_diff_paths(previous, current)
    paths: list[str] = []
    keys = sorted(set(previous) | set(current))
    for key in keys:
        if key not in previous or key not in current:
            paths.append(str(key))
            continue
        left = previous[key]
        right = current[key]
        identity_key = {"requirements": "requirementId", "analyses": "code"}.get(str(key))
        if (
            identity_key is None
            or not isinstance(left, (list, tuple))
            or not isinstance(right, (list, tuple))
        ):
            paths.extend(_json_diff_paths(left, right, str(key)))
            continue
        paths.extend(_keyed_sequence_diff_paths(left, right, str(key), identity_key))
    return paths


def _keyed_sequence_diff_paths(
    previous: list[Any] | tuple[Any, ...],
    current: list[Any] | tuple[Any, ...],
    path: str,
    identity_key: str,
) -> list[str]:
    previous_ids = [
        item.get(identity_key) if isinstance(item, Mapping) else None for item in previous
    ]
    current_ids = [
        item.get(identity_key) if isinstance(item, Mapping) else None for item in current
    ]
    if (
        any(not isinstance(item, str) or not item for item in (*previous_ids, *current_ids))
        or len(set(previous_ids)) != len(previous_ids)
        or len(set(current_ids)) != len(current_ids)
    ):
        return _json_diff_paths(previous, current, path)

    previous_by_id = {
        identity: (index, previous[index]) for index, identity in enumerate(previous_ids)
    }
    current_by_id = {identity: current[index] for index, identity in enumerate(current_ids)}
    surviving_ids = [identity for identity in previous_ids if identity in current_by_id]
    paths: list[str] = []
    if current_ids != surviving_ids:
        paths.append(path)
    for identity, (index, previous_item) in previous_by_id.items():
        item_path = f"{path}[{index}]"
        current_item = current_by_id.get(identity)
        if current_item is None:
            paths.append(item_path)
            continue
        paths.extend(_json_diff_paths(previous_item, current_item, item_path))
    return paths


def _correction_path_allowed(path: str, allowed: str) -> bool:
    if "[*]" not in allowed:
        return path == allowed or path.startswith(f"{allowed}.") or path.startswith(f"{allowed}[")
    pattern = re.escape(allowed).replace(r"\[\*\]", r"\[\d+\]")
    return re.match(rf"^{pattern}(?:\.|\[|$)", path) is not None


def _analysis_required_deletion_paths(
    issues: list[dict[str, Any]], previous_output: Mapping[str, Any] | None
) -> tuple[str, ...]:
    if previous_output is None:
        return ()
    requirements = previous_output.get("requirements")
    analyses = previous_output.get("analyses")
    if not isinstance(requirements, list) or not isinstance(analyses, list):
        return ()

    requirement_indices: set[int] = set()
    for issue in issues:
        path = issue.get("path")
        match = (
            re.fullmatch(r"requirements\[(\d+)]\.tables\[\d+]\.measureColumns", path)
            if isinstance(path, str)
            else None
        )
        if match is not None and issue.get("allowedValues") == []:
            requirement_indices.add(int(match.group(1)))

    invalid_ids = {
        str(requirements[index].get("requirementId"))
        for index in requirement_indices
        if index < len(requirements)
        and isinstance(requirements[index], Mapping)
        and isinstance(requirements[index].get("requirementId"), str)
    }
    paths = [f"requirements[{index}]" for index in sorted(requirement_indices)]
    for index, analysis in enumerate(analyses):
        if not isinstance(analysis, Mapping):
            continue
        requirement_ids = analysis.get("requirementIds")
        if (
            isinstance(requirement_ids, list)
            and requirement_ids
            and set(requirement_ids).issubset(invalid_ids)
        ):
            paths.append(f"analyses[{index}]")
    return tuple(paths)


def _analysis_allowed_mutation_paths(
    issues: list[dict[str, Any]],
    *,
    previous_output: Mapping[str, Any] | None = None,
    required_deletion_paths: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if any(
        isinstance(issue.get("path"), str)
        and str(issue["path"]).startswith("requirements[")
        and "拆分为单表" in str(issue.get("requiredAction", ""))
        for issue in issues
    ):
        return ("requirements", "analyses[*].requirementIds")
    deletion_prefixes = tuple(
        path for path in required_deletion_paths if path.startswith("requirements[")
    )
    paths: list[str] = []
    for issue in issues:
        repair_targets = issue.get("repairTargets")
        candidates = (
            [str(item) for item in repair_targets if isinstance(item, str)]
            if isinstance(repair_targets, list)
            else [str(issue["path"])]
            if isinstance(issue.get("path"), str)
            else []
        )
        paths.extend(
            candidate
            for candidate in candidates
            if not any(
                candidate == prefix or candidate.startswith(f"{prefix}.")
                for prefix in deletion_prefixes
            )
        )
    if previous_output is not None and deletion_prefixes:
        requirements = previous_output.get("requirements")
        analyses = previous_output.get("analyses")
        if isinstance(requirements, list) and isinstance(analyses, list):
            invalid_ids = {
                str(requirements[int(match.group(1))].get("requirementId"))
                for prefix in deletion_prefixes
                if (match := re.fullmatch(r"requirements\[(\d+)]", prefix)) is not None
                and int(match.group(1)) < len(requirements)
                and isinstance(requirements[int(match.group(1))], Mapping)
            }
            for index, analysis in enumerate(analyses):
                if not isinstance(analysis, Mapping):
                    continue
                requirement_ids = analysis.get("requirementIds")
                if (
                    isinstance(requirement_ids, list)
                    and set(requirement_ids) & invalid_ids
                    and not set(requirement_ids).issubset(invalid_ids)
                ):
                    paths.append(f"analyses[{index}].requirementIds")
    return tuple(dict.fromkeys(paths))


def _suggested_replacement(rejected: Any, allowed_values: list[str]) -> str | None:
    if isinstance(rejected, list) and len(rejected) == 1:
        rejected = rejected[0]
    if not isinstance(rejected, str) or not allowed_values:
        return None
    ranked = sorted(
        (
            (SequenceMatcher(None, rejected, candidate).ratio(), candidate)
            for candidate in allowed_values
        ),
        reverse=True,
    )
    best_score, best = ranked[0]
    next_score = ranked[1][0] if len(ranked) > 1 else 0.0
    if best_score < 0.85 or best_score - next_score < 0.1:
        return None
    return best


def _analysis_table_columns(
    source_id: str,
    table: str,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> tuple[ModelColumn, ...]:
    matches = [
        model.columns
        for (candidate_source, qualified), model in _available_tables(snapshots).items()
        if candidate_source == source_id
        and (qualified == table.lower() or qualified.endswith(f".{table.lower()}"))
    ]
    return matches[0] if len(matches) == 1 else ()


def _requirement_measure_field_refs(
    requirement: QueryRequirement,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> set[str]:
    """把 Requirement 的裸指标列绑定到结构快照中的标准四段 fieldRef。"""

    available_tables = _available_tables(snapshots)
    field_refs: set[str] = set()
    for table in requirement.tables:
        table_ref = table.table.lower()
        matches = [
            model
            for (source_id, qualified), model in available_tables.items()
            if source_id == requirement.source_id
            and (qualified == table_ref or qualified.endswith(f".{table_ref}"))
        ]
        # 裸表名只能在当前 source 下唯一命中。多义时不绑定任何指标语义，避免把
        # 同名表的聚合规则混入不可变 Dataset；前置计划校验会把该歧义作为错误关闭。
        if len(matches) != 1:
            continue
        model = matches[0]
        available_columns = {column.name.lower() for column in model.columns}
        field_refs.update(
            f"{model.source_id}.{model.database}.{model.name}.{measure}".lower()
            for measure in table.measure_columns
            if measure.lower() in available_columns
        )
    return field_refs


def _compact_validation_feedback(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    compact = dict(value)
    issues = value.get("issues")
    if isinstance(issues, list):
        compact["issues"] = [
            {
                **issue,
                **(
                    {"rejectedValue": _bounded_rejected_value(issue["rejectedValue"])}
                    if isinstance(issue, dict) and "rejectedValue" in issue
                    else {}
                ),
            }
            if isinstance(issue, dict)
            else issue
            for issue in issues[:20]
        ]
        if len(issues) > 20:
            compact["omittedIssueCount"] = len(issues) - 20
    return compact


def _report_pdf_filename(title: str, period: ReportPeriod) -> str:
    safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" ._")
    if not safe_title:
        safe_title = "智能分析报告"
    # 文件系统通常限制单个文件名为 255 bytes，为日期和扩展名预留固定空间。
    encoded = safe_title.encode("utf-8")
    if len(encoded) > 180:
        encoded = encoded[:180]
        while True:
            try:
                safe_title = encoded.decode("utf-8")
                break
            except UnicodeDecodeError:
                encoded = encoded[:-1]
    period_label = f"{period.start.isoformat()}至{period.end.isoformat()}"
    return f"{safe_title}_{period_label}.pdf"


def _report_pdf_path(run_id: str, revision: int, title: str, period: ReportPeriod) -> str:
    filename = _report_pdf_filename(title, period)
    return f"报表/智能分析/{run_id}/revision-{revision}/{filename}"


def _validation_issue(
    *,
    path: str,
    rejected_value: Any,
    reason: str,
    allowed_values: list[Any],
    required_action: str,
) -> dict[str, Any]:
    return {
        "path": path,
        "rejectedValue": rejected_value,
        "reason": reason,
        "allowedValues": allowed_values,
        "requiredAction": required_action,
    }


def _row_preserving_requirement_ids(
    requirements: tuple[QueryRequirement, ...],
    profile: HospitalOperationProfile,
) -> tuple[str, ...]:
    """只有 Profile 明确要求重复核验的单表需求才能绕过聚合，模型不能自行扩大权限。"""
    governed_tables = {
        rule.table_ref.rsplit(".", 1)[-1].lower() for rule in profile.duplicate_conflicts
    }
    return tuple(
        requirement.requirement_id
        for requirement in requirements
        if len(requirement.tables) == 1
        and requirement.tables[0].table.rsplit(".", 1)[-1].lower() in governed_tables
    )


def _validate_hospital_operation_profile_schema(
    profile: HospitalOperationProfile,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> None:
    """启动前核对已存在物理表的绑定列，避免列名漂移到 CSV 物化后才暴露。"""
    table_columns = {
        (table.source_id.lower(), table.database.lower(), table.name.lower()): {
            column.name.lower() for column in table.columns
        }
        for snapshot in snapshots
        for table in snapshot.tables
    }
    missing: list[str] = []
    field_refs = tuple(item.field_ref for item in profile.bindings) + tuple(
        item.field_ref for item in profile.dimension_bindings
    )
    for field_ref in field_refs:
        parts = field_ref.lower().split(".")
        if len(parts) != 4:
            missing.append(field_ref)
            continue
        source_id, database, table, column = parts
        available = table_columns.get((source_id, database, table))
        if available is not None and column not in available:
            missing.append(field_ref)
    if missing:
        raise ReportingError(
            "hospital_operation_profile_schema_mismatch",
            "医院运营 Profile 与当前 Schema 不一致：" + ", ".join(sorted(missing)),
        )


def _resolve_requirement_comparison_roles(
    requirement: QueryRequirement,
    requirement_index: int,
    envelope: ReportRequestEnvelope,
) -> tuple[tuple[Literal["yoy", "mom"], ...] | None, dict[str, Any] | None]:
    """把 Planner 的比较范围越界转换为可定点修正的结构化反馈。"""
    try:
        return requirement.resolved_comparison_roles(envelope.comparison_roles), None
    except ValueError as error:
        selected = (
            envelope.comparison_roles
            if requirement.comparison_roles is None
            else requirement.comparison_roles
        )
        rejected = [role for role in selected if role not in envelope.comparison_roles]
        if rejected:
            reason = "comparisonRoles 超出请求允许的比较范围"
            allowed = list(envelope.comparison_roles)
            required_action = (
                "删除 rejectedValue，只保留 allowedValues；省略 comparisonRoles 表示继承请求范围"
            )
        else:
            rejected = ["mom"] if "mom" in selected else list(selected)
            allowed = [role for role in envelope.comparison_roles if role != "mom"]
            reason = str(error)
            required_action = "删除 rejectedValue，只保留当前期间粒度支持的 allowedValues"
        return None, {
            "path": f"requirements[{requirement_index}].comparisonRoles",
            "rejectedValue": rejected,
            "reason": reason,
            "allowedValues": allowed,
            "requiredAction": required_action,
        }


def _approve_generated_queries(
    generated: GeneratedQueryBatch,
    *,
    sources: dict[str, StarRocksSourceConfig],
    snapshots: tuple[SourceSchemaSnapshot, ...],
    envelope: ReportRequestEnvelope,
    requirements: tuple[QueryRequirement, ...],
    row_preserving_requirement_ids: tuple[str, ...] = (),
) -> tuple[tuple[ApprovedQuery, ...], list[dict[str, Any]]]:
    requirements_by_id = {item.requirement_id: item for item in requirements}
    explicit_period_mode = any("period_role" in item.model_fields_set for item in generated.queries)
    approved_window_keys: set[tuple[str, str]] = set()
    issues: list[dict[str, Any]] = []
    windows_by_requirement: dict[str, ReportPeriodWindows] = {}
    invalid_requirement_ids: set[str] = set()
    for index, planned_requirement in enumerate(requirements):
        comparison_roles, comparison_issue = _resolve_requirement_comparison_roles(
            planned_requirement,
            index,
            envelope,
        )
        if comparison_issue is not None:
            issues.append(comparison_issue)
            invalid_requirement_ids.add(planned_requirement.requirement_id)
            continue
        assert comparison_roles is not None
        windows_by_requirement[planned_requirement.requirement_id] = envelope.model_copy(
            update={"comparison_roles": comparison_roles}
        ).period_windows(granularity=planned_requirement.tables[0].period_granularity)
    approved: list[ApprovedQuery] = []
    for index, query in enumerate(generated.queries):
        requirement = requirements_by_id.get(query.requirement_id)
        if requirement is None:
            issues.append(
                {
                    "path": f"queries[{index}].requirementId",
                    "rejectedValue": query.requirement_id,
                    "reason": "requirementId 不存在于输入 requirements",
                    "allowedValues": sorted(requirements_by_id),
                    "requiredAction": "为每个输入 requirementId 和唯一期间窗口返回且只返回一条 SQL",
                }
            )
            continue
        if requirement.requirement_id in invalid_requirement_ids:
            continue
        windows_by_role = {
            item.role: item for item in windows_by_requirement[requirement.requirement_id].windows
        }
        period_role = query.period_role if explicit_period_mode else "current"
        if period_role not in windows_by_role:
            issues.append(
                {
                    "path": f"queries[{index}].periodRole",
                    "rejectedValue": period_role,
                    "reason": "periodRole 超出 requirement 允许的比较范围",
                    "allowedValues": sorted(windows_by_role),
                    "requiredAction": "删除超出请求或 requirement 比较范围的查询",
                }
            )
            continue
        query_key = (query.requirement_id, windows_by_role[period_role].query_window_id)
        if query_key in approved_window_keys:
            issues.append(
                {
                    "path": f"queries[{index}]",
                    "rejectedValue": query.model_dump(mode="json", by_alias=True),
                    "reason": "同一 requirementId 和 queryWindowId 只能生成一条 SQL",
                    "allowedValues": [],
                    "requiredAction": "删除该重复查询；共享同一 queryWindowId 的期间角色只保留一条 SQL",
                }
            )
            continue
        try:
            query_approved = approve_query_batch(
                [
                    query.model_dump(
                        mode="json",
                        by_alias=True,
                        exclude_unset=not explicit_period_mode,
                    )
                ],
                sources=sources,
                snapshots=snapshots,
                envelope=envelope,
                requirements=(requirement,),
                row_preserving_requirement_ids=(
                    (requirement.requirement_id,)
                    if requirement.requirement_id in row_preserving_requirement_ids
                    else ()
                ),
                require_complete_batch=False,
            )
            approved.extend(query_approved)
            approved_window_keys.add(query_key)
        except ReportingError as error:
            expected_period_predicates: list[str] | None = None
            expected_scope_filters: list[dict[str, str]] | None = None
            if error.code == "report_query_join_grain_invalid":
                required_action = (
                    "按 requirementContract 为每张表建立独立 CTE，逐表使用完整期间条件并按全部 "
                    "grainColumns 聚合，再仅按 relations[].joinColumns 等值连接 CTE；禁止直接连接基础表"
                )
            elif error.code == "report_query_period_invalid":
                expected_period_predicates = _expected_period_predicates(
                    requirement,
                    envelope,
                    period_role=query.period_role,
                )
                required_action = (
                    "逐字使用 expectedPeriodPredicates 为每张表添加完整精确期间条件；"
                    "不得使用其他期间字段、缩短范围或省略任一表的期间条件"
                )
            elif error.code == "report_query_grain_invalid":
                required_action = (
                    "只保留 expectedGrainColumns 作为非聚合 SELECT 列和 GROUP BY 列；"
                    "measureColumns 必须聚合；不得把 dimensionColumns 全量带入"
                )
            elif error.code == "report_query_row_preserving_invalid":
                required_action = (
                    "直接投影 requirementContract 的全部 grainColumns 和原始 measureColumns；"
                    "删除聚合函数、GROUP BY、DISTINCT、ORDER BY 和 LIMIT"
                )
            elif error.code == "report_query_scope_semantic_invalid":
                expected_scope_filters = _expected_scope_filters(requirement, snapshots)
                required_action = (
                    "逐字使用 expectedScopeFilters 中每个 table、column、value 添加等值过滤；"
                    "不得改为 IN、非空判断、字段类别名或近义值"
                )
            else:
                required_action = "严格按 requirementContract 的 tables、measureColumns、grainColumns 和 relations 修正 SQL"
            query_issue: dict[str, Any] = {
                "path": f"queries[{index}].sql",
                "rejectedValue": query.sql,
                "reason": f"{error.code}: {error.message}",
                "requirementContract": requirement.model_dump(mode="json", by_alias=True),
                "requiredAction": required_action,
            }
            if expected_period_predicates is not None:
                query_issue["expectedPeriodPredicates"] = expected_period_predicates
            if expected_scope_filters is not None:
                query_issue["expectedScopeFilters"] = expected_scope_filters
            if error.code == "report_query_grain_invalid":
                query_issue["expectedGrainColumns"] = list(requirement.grain_columns)
            issues.append(query_issue)
    actual_keys = {(item.requirement_id, item.query_window_id) for item in approved}
    expected_keys = {
        (requirement.requirement_id, window.query_window_id)
        for requirement in requirements
        if requirement.requirement_id in windows_by_requirement
        for window in (
            windows_by_requirement[requirement.requirement_id].windows
            if explicit_period_mode
            else windows_by_requirement[requirement.requirement_id].windows[:1]
        )
    }
    missing = sorted(expected_keys - actual_keys)
    if missing:
        issues.append(
            {
                "path": "queries",
                "rejectedValue": [
                    {"requirementId": requirement_id, "queryWindowId": query_window_id}
                    for requirement_id, query_window_id in missing
                ],
                "reason": "SQL 批次缺少输入 requirementId 对应的期间窗口",
                "allowedValues": [
                    {
                        "requirementId": requirement_id,
                        "periodRole": next(
                            window.role
                            for window in windows_by_requirement[requirement_id].windows
                            if window.query_window_id == query_window_id
                        ),
                    }
                    for requirement_id, query_window_id in sorted(expected_keys)
                ],
                "requiredAction": "只补齐缺失的 requirementId 与 periodRole 对应 SQL",
            }
        )
    return tuple(approved), issues


def _expected_scope_filters(
    requirement: QueryRequirement,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> list[dict[str, str]]:
    semantics = {
        item.field_ref.lower(): item
        for snapshot in snapshots
        for item in snapshot.measure_semantics
    }
    filters: dict[tuple[str, str, str], dict[str, str]] = {}
    for table in requirement.tables:
        for measure in table.measure_columns:
            field_ref = f"{requirement.source_id}.{table.table}.{measure}".lower()
            semantic = semantics.get(field_ref)
            if semantic is None:
                continue
            for column, value in semantic.exclusive_scope.items():
                filters[(table.table, column, value)] = {
                    "table": table.table,
                    "column": column,
                    "value": value,
                }
    return [filters[key] for key in sorted(filters)]


def _expected_period_predicates(
    requirement: QueryRequirement,
    envelope: ReportRequestEnvelope,
    *,
    period_role: Literal["current", "yoy", "mom"] = "current",
) -> list[str]:
    roles = requirement.resolved_comparison_roles(envelope.comparison_roles)
    period = next(
        item.period
        for item in envelope.model_copy(update={"comparison_roles": roles})
        .period_windows(granularity=requirement.tables[0].period_granularity)
        .windows
        if item.role == period_role
    )
    predicates: list[str] = []
    for table in requirement.tables:
        column = f"{table.table}.{table.period_column}"
        if table.period_granularity == "year":
            lower = str(period.start.year)
            upper = str(period.end.year)
        elif table.period_granularity == "month":
            lower = f"'{period.start.year:04d}-{period.start.month:02d}'"
            upper = f"'{period.end.year:04d}-{period.end.month:02d}'"
        else:
            lower = f"'{period.start.isoformat()}'"
            upper = f"'{period.end.isoformat()}'"
        predicates.append(f"{column} BETWEEN {lower} AND {upper}")
    return predicates


def _table_references(
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> tuple[TableReference, ...]:
    return tuple(
        TableReference(
            sourceId=table.source_id,
            table=f"{table.database}.{table.name}",
        )
        for snapshot in snapshots
        for table in snapshot.tables
    )


def _table_reference_values(
    candidates: tuple[TableReference, ...],
    *,
    source_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        item.model_dump(mode="json", by_alias=True)
        for item in candidates
        if source_id is None or item.source_id == source_id
    ]


def _available_table_columns(
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> dict[tuple[str, str], tuple[str, ...]]:
    return {
        (table.source_id, f"{table.database.lower()}.{table.name.lower()}"): tuple(
            column.name for column in table.columns
        )
        for snapshot in snapshots
        for table in snapshot.tables
    }


def _available_tables(
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> dict[tuple[str, str], ModelTable]:
    return {
        (table.source_id, f"{table.database.lower()}.{table.name.lower()}"): table
        for snapshot in snapshots
        for table in snapshot.tables
    }


def _period_encoding_choices(table: ModelTable) -> list[dict[str, str]]:
    choices: list[dict[str, str]] = []
    for column in table.columns:
        data_type = column.data_type.strip().upper()
        granularity = None
        name = column.name.lower()
        description = column.description.lower()
        if re.match(r"^(?:DATE|DATETIME|TIMESTAMP)\b", data_type):
            granularity = "date"
        elif (
            data_type.startswith("YEAR")
            or name == "year"
            or name.endswith("_year")
            or "年度" in description
            or "年份" in description
        ):
            granularity = "year"
        elif "月份" in description or "月度" in description or "month" in name:
            granularity = "month"
        elif "日期" in description or name == "date" or name.endswith("_date"):
            granularity = "date"
        if granularity is not None:
            choices.append(
                {
                    "periodColumn": column.name,
                    "dataType": column.data_type,
                    "periodGranularity": granularity,
                }
            )
    return choices


def _validation_path(location: tuple[Any, ...]) -> str:
    path = ""
    for item in location:
        if isinstance(item, int):
            path += f"[{item}]"
        else:
            path += ("." if path else "") + str(item)
    return path or "$"


def _raw_table_source(raw_output: Any, location: tuple[Any, ...]) -> str | None:
    raw_table = _raw_table_at_location(raw_output, location)
    source_id = raw_table.get("sourceId") if raw_table is not None else None
    return source_id if isinstance(source_id, str) else None


def _raw_table_columns(
    raw_output: Any,
    location: tuple[Any, ...],
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> tuple[str, ...]:
    raw_table = _raw_table_at_location(raw_output, location)
    if raw_table is None:
        return ()
    source_id = raw_table.get("sourceId")
    table = raw_table.get("table")
    if not isinstance(source_id, str) or not isinstance(table, str):
        return ()
    return _available_table_columns(snapshots).get((source_id, table.lower()), ())


def _raw_table_at_location(raw_output: Any, location: tuple[Any, ...]) -> dict[str, Any] | None:
    if (
        not isinstance(raw_output, dict)
        or len(location) < 2
        or location[0] != "tables"
        or not isinstance(location[1], int)
    ):
        return None
    tables = raw_output.get("tables")
    index = location[1]
    if not isinstance(tables, list) or index < 0 or index >= len(tables):
        return None
    return tables[index] if isinstance(tables[index], dict) else None


def _invalid_table_reason(
    rejected_value: str,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> str:
    normalized = rejected_value.lower()
    if normalized.endswith(".sql"):
        return "table 必须与 schemas[].tables[].table 完全一致，不能使用文件名"
    field_references = {
        reference
        for snapshot in snapshots
        for table in snapshot.tables
        for column in table.columns
        for reference in (
            f"{table.name.lower()}.{column.name.lower()}",
            f"{table.database.lower()}.{table.name.lower()}.{column.name.lower()}",
        )
    }
    if normalized in field_references or normalized.count(".") >= 2:
        return "table 必须复制规范 database.table，不能使用 table.column 字段引用"
    if "." not in normalized:
        return "table 必须复制输入 Schema 中完整的 database.table，不能省略数据库名"
    return "sourceId 与 table 组合不存在于输入 Schema，必须复制一个规范表引用"


def _validate_requirements_match_understanding(
    requirements: tuple[QueryRequirement, ...],
    plan: DataUnderstandingPlan,
) -> None:
    selected = {(item.source_id, item.table): item for item in plan.tables}
    for requirement in requirements:
        for table in requirement.tables:
            matches = [
                item
                for (source_id, qualified), item in selected.items()
                if source_id == requirement.source_id
                and (qualified == table.table or qualified.endswith(f".{table.table}"))
            ]
            if len(matches) != 1:
                raise ReportingError(
                    "report_analysis_plan_invalid",
                    "分析计划引用了数据理解计划外的数据表。",
                )
            understood = matches[0]
            if (
                understood.period_column.lower() != table.period_column.lower()
                or understood.period_granularity != table.period_granularity
            ):
                raise ReportingError(
                    "report_analysis_plan_invalid",
                    "分析计划的期间语义与数据理解计划不一致。",
                )


def _analysis_bundle_semantic_issues(
    bundle: AnalysisBundle,
    plan: DataUnderstandingPlan,
    snapshots: tuple[SourceSchemaSnapshot, ...],
    envelope: ReportRequestEnvelope | None = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        _validate_requirements_match_understanding(bundle.requirements, plan)
    except ReportingError as error:
        issues.append(
            {
                "path": "requirements",
                "rejectedValue": [
                    item.model_dump(mode="json", by_alias=True) for item in bundle.requirements
                ],
                "reason": error.message,
                "requiredAction": (
                    "只引用 dataUnderstanding 中已选择的 sourceId、table、periodColumn "
                    "和 periodGranularity"
                ),
            }
        )
    for index, requirement in enumerate(bundle.requirements):
        if envelope is not None:
            _, comparison_issue = _resolve_requirement_comparison_roles(
                requirement,
                index,
                envelope,
            )
            if comparison_issue is not None:
                issues.append(comparison_issue)
        issues.extend(_requirement_column_issues(requirement, index, snapshots))
        issues.extend(_measure_column_issues(requirement, index, snapshots))
        issues.extend(_measure_semantic_issues(requirement, index, snapshots))
        issues.extend(_multi_table_requirement_issues(requirement, index, snapshots))
    requirement_ids = {item.requirement_id for item in bundle.requirements}
    for index, analysis in enumerate(bundle.analyses):
        unknown = sorted(set(analysis.requirement_ids) - requirement_ids)
        if unknown:
            allowed_values = sorted(requirement_ids)
            issue = {
                "path": f"analyses[{index}].requirementIds",
                "rejectedValue": unknown,
                "reason": "分析计划引用了 requirements 中不存在的 requirementId",
                "allowedValues": allowed_values,
                "requiredAction": "从 allowedValues 选择正确引用或在 requirements 中补齐完整需求",
            }
            suggested = _suggested_replacement(unknown, allowed_values)
            if suggested is not None:
                issue["suggestedReplacement"] = suggested
            issues.append(issue)
    return issues


def _requirement_column_issues(
    requirement: QueryRequirement,
    requirement_index: int,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> list[dict[str, Any]]:
    available_tables = _available_tables(snapshots)
    table_columns: list[set[str]] = []
    issues: list[dict[str, Any]] = []
    for table_index, table in enumerate(requirement.tables):
        matches = [
            model
            for (source_id, qualified), model in available_tables.items()
            if source_id == requirement.source_id
            and (qualified == table.table or qualified.endswith(f".{table.table}"))
        ]
        if len(matches) != 1:
            continue
        model = matches[0]
        columns = {column.name.lower() for column in model.columns}
        table_columns.append(columns)
        unknown_measures = sorted(set(table.measure_columns) - columns)
        if unknown_measures:
            allowed = sorted(
                column.name
                for column in model.columns
                if _NUMERIC_MEASURE_TYPE_PATTERN.match(column.data_type) is not None
                and column.name.lower() != table.period_column
            )
            issues.append(
                {
                    "path": (
                        f"requirements[{requirement_index}].tables[{table_index}].measureColumns"
                    ),
                    "rejectedValue": unknown_measures,
                    "reason": "measureColumns 引用了当前表结构快照中不存在的字段",
                    "allowedValues": allowed,
                    "requiredAction": "删除 rejectedValue，或从 allowedValues 选择真实数值指标字段",
                }
            )

    if not table_columns:
        return issues
    dimension_columns = set().union(*table_columns)
    unknown_dimensions = sorted(set(requirement.dimension_columns) - dimension_columns)
    if unknown_dimensions:
        issues.append(
            {
                "path": f"requirements[{requirement_index}].dimensionColumns",
                "rejectedValue": unknown_dimensions,
                "reason": "dimensionColumns 引用了 requirement 数据表结构快照中不存在的字段",
                "allowedValues": sorted(dimension_columns),
                "requiredAction": "删除或替换 rejectedValue，保留其他有效维度",
            }
        )

    if len(requirement.tables) == 1:
        grain_columns = table_columns[0]
        unknown_grain = sorted(set(requirement.grain_columns) - grain_columns)
        if unknown_grain:
            issues.append(
                {
                    "path": f"requirements[{requirement_index}].grainColumns",
                    "rejectedValue": unknown_grain,
                    "reason": "grainColumns 引用了当前表结构快照中不存在的字段",
                    "allowedValues": sorted(grain_columns),
                    "requiredAction": "删除或替换 rejectedValue，保留其他有效粒度",
                }
            )
    return issues


def _measure_column_issues(
    requirement: QueryRequirement,
    requirement_index: int,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> list[dict[str, Any]]:
    available_tables = _available_tables(snapshots)
    dimensions = set(requirement.dimension_columns)
    overlapping_dimensions: set[str] = set()
    measure_issues: list[dict[str, Any]] = []
    for table_index, table in enumerate(requirement.tables):
        matches = [
            model
            for (source_id, qualified), model in available_tables.items()
            if source_id == requirement.source_id
            and (qualified == table.table or qualified.endswith(f".{table.table}"))
        ]
        if len(matches) != 1:
            continue
        model = matches[0]
        columns = {column.name.lower(): column for column in model.columns}
        overlapping_dimensions.update(
            name
            for name in table.measure_columns
            if name in dimensions
            and name in columns
            and _NUMERIC_MEASURE_TYPE_PATTERN.match(columns[name].data_type) is not None
            and name != table.period_column
        )
        invalid = [
            columns[name]
            for name in table.measure_columns
            if name in columns
            and (
                _NUMERIC_MEASURE_TYPE_PATTERN.match(columns[name].data_type) is None
                or name == table.period_column
            )
        ]
        if not invalid:
            continue
        allowed = sorted(
            column.name
            for column in model.columns
            if _NUMERIC_MEASURE_TYPE_PATTERN.match(column.data_type) is not None
            and column.name.lower() != table.period_column
            and column.name.lower() not in dimensions
        )
        measure_issues.append(
            {
                "path": (f"requirements[{requirement_index}].tables[{table_index}].measureColumns"),
                "rejectedValue": [
                    {"column": column.name, "dataType": column.data_type} for column in invalid
                ],
                "reason": (
                    "measureColumns 只能声明需要聚合的数值指标；期间、分类和文本字段不是可聚合指标"
                ),
                "allowedValues": allowed,
                "requiredAction": (
                    "从 allowedValues 选择可聚合数值字段；需要分组展示的分类字段"
                    "放入 dimensionColumns 和适用的 grainColumns"
                ),
            }
        )
    issues: list[dict[str, Any]] = []
    if overlapping_dimensions:
        rejected = [
            column for column in requirement.dimension_columns if column in overlapping_dimensions
        ]
        issues.append(
            {
                "path": f"requirements[{requirement_index}].dimensionColumns",
                "rejectedValue": rejected,
                "reason": "数值指标不能同时声明为 measureColumns 和 dimensionColumns",
                "allowedValues": [
                    column
                    for column in requirement.dimension_columns
                    if column not in overlapping_dimensions
                ],
                "requiredAction": "从 dimensionColumns 删除 rejectedValue，保留原有其他维度",
            }
        )
        overlapping_grain = [
            column for column in requirement.grain_columns if column in overlapping_dimensions
        ]
        if overlapping_grain:
            issues.append(
                {
                    "path": f"requirements[{requirement_index}].grainColumns",
                    "rejectedValue": overlapping_grain,
                    "reason": "聚合数值指标不能作为分组粒度",
                    "allowedValues": [
                        column
                        for column in requirement.grain_columns
                        if column not in overlapping_dimensions
                    ],
                    "requiredAction": "从 grainColumns 删除 rejectedValue，保留原有其他粒度",
                }
            )
    return [*issues, *measure_issues]


def _measure_semantic_issues(
    requirement: QueryRequirement,
    requirement_index: int,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> list[dict[str, Any]]:
    semantics = {
        item.field_ref.lower(): item
        for snapshot in snapshots
        for item in snapshot.measure_semantics
    }
    issues: list[dict[str, Any]] = []
    missing_grain_columns: set[str] = set()
    ordered_table_columns: list[str] = []
    for table_index, table in enumerate(requirement.tables):
        qualified = table.table if "." in table.table else ""
        if not qualified:
            matches = [
                model
                for snapshot in snapshots
                for model in snapshot.tables
                if model.source_id == requirement.source_id and model.name.lower() == table.table
            ]
            if len(matches) != 1:
                continue
            qualified = f"{matches[0].database}.{matches[0].name}".lower()
        table_models = [
            model
            for snapshot in snapshots
            for model in snapshot.tables
            if model.source_id == requirement.source_id
            and f"{model.database}.{model.name}".lower() == qualified
        ]
        if len(table_models) != 1:
            continue
        columns = {column.name.lower(): column for column in table_models[0].columns}
        table_columns = set(columns)
        ordered_table_columns.extend(
            column.name.lower()
            for column in table_models[0].columns
            if column.name.lower() not in ordered_table_columns
        )
        # periodColumn 不只是 SQL WHERE 边界，也是 CSV 分析的期间事实来源。
        # 即使指标声明可跨该列相加，也必须保留在 SELECT/GROUP BY 和不可变数据集中；
        # 否则 Coding 无法判断每行属于哪个月，不能用查询窗口代替行事实。
        if table.period_column not in requirement.grain_columns:
            missing_grain_columns.add(table.period_column)
        table_prefix = f"{requirement.source_id}.{qualified}.".lower()
        declared_measure_columns = {
            field_ref.rsplit(".", 1)[-1]
            for field_ref in semantics
            if field_ref.startswith(table_prefix)
        }
        for measure in table.measure_columns:
            column = columns.get(measure)
            if (
                column is None
                or _NUMERIC_MEASURE_TYPE_PATTERN.match(column.data_type) is None
                or measure in requirement.dimension_columns
            ):
                continue
            field_ref = f"{requirement.source_id}.{qualified}.{measure}".lower()
            semantic = semantics.get(field_ref)
            path = f"requirements[{requirement_index}].tables[{table_index}].measureColumns"
            if semantic is None:
                allowed = sorted(
                    item.field_ref.rsplit(".", 1)[-1]
                    for item in semantics.values()
                    if item.field_ref.lower().startswith(
                        f"{requirement.source_id}.{qualified}.".lower()
                    )
                )
                issues.append(
                    {
                        "path": path,
                        "rejectedValue": measure,
                        "reason": "字段未获服务端结构快照批准为可聚合指标，禁止猜测聚合口径",
                        "allowedValues": allowed,
                        "requiredAction": (
                            "只保留 allowedValues 中已批准的指标；为空时删除整个 requirement，"
                            "并删除仅引用它的 analysis 或从混合引用中移除该 requirementId；"
                            "不得改用无关指标或把 rejectedValue 移入维度伪装通过"
                        ),
                    }
                )
                continue
            forbidden = sorted(
                table_columns
                - declared_measure_columns
                - set(requirement.grain_columns)
                - set(semantic.additive_across)
                - set(semantic.exclusive_scope)
            )
            missing_grain_columns.update(forbidden)
    if missing_grain_columns:
        missing = [name for name in ordered_table_columns if name in missing_grain_columns]
        target_dimensions = list(dict.fromkeys((*requirement.dimension_columns, *missing)))
        target_grain = list(dict.fromkeys((*requirement.grain_columns, *missing)))
        issue: dict[str, Any] = {
            "path": f"requirements[{requirement_index}].grainColumns",
            "missingValues": missing,
            "reason": "指标表存在未保留、未固定且未声明为可加的维度",
            "repairTargets": [
                f"requirements[{requirement_index}].dimensionColumns",
                f"requirements[{requirement_index}].grainColumns",
            ],
            "requiredAction": (
                "将 missingValues 同时追加到 dimensionColumns 和 grainColumns；"
                "不得删除原有字段或修改表、指标及分析引用"
            ),
        }
        if len(target_dimensions) <= 30 and len(target_grain) <= 30:
            issue["targetValues"] = {
                "dimensionColumns": target_dimensions,
                "grainColumns": target_grain,
            }
        else:
            issue["requiredColumnCount"] = max(len(target_dimensions), len(target_grain))
            issue["maxColumnCount"] = 30
            issue["requiredAction"] = (
                "完整安全粒度超过契约上限；减少当前 requirement 的 measureColumns，"
                "或通过已审核 Profile/metadata 补充可加维度或固定范围后重新规划"
            )
        issues.append(issue)
    return issues


def _normalize_analysis_bundle_grain(
    bundle: AnalysisBundle,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> tuple[AnalysisBundle, list[dict[str, Any]]]:
    """只追加服务端可证明的安全粒度，不替模型改写分析意图。"""

    normalized_requirements: list[QueryRequirement] = []
    repairs: list[dict[str, Any]] = []
    for index, requirement in enumerate(bundle.requirements):
        if len(requirement.tables) != 1:
            normalized_requirements.append(requirement)
            continue
        semantic_issues = _measure_semantic_issues(requirement, index, snapshots)
        if any(str(issue.get("path", "")).endswith(".measureColumns") for issue in semantic_issues):
            normalized_requirements.append(requirement)
            continue
        grain_issue = next(
            (
                issue
                for issue in semantic_issues
                if issue.get("path") == f"requirements[{index}].grainColumns"
                and isinstance(issue.get("targetValues"), Mapping)
            ),
            None,
        )
        if grain_issue is None:
            normalized_requirements.append(requirement)
            continue
        target_values = grain_issue["targetValues"]
        payload = requirement.model_dump(mode="json", by_alias=True)
        payload["dimensionColumns"] = target_values["dimensionColumns"]
        payload["grainColumns"] = target_values["grainColumns"]
        try:
            normalized = QueryRequirement.model_validate(payload)
        except ValidationError:
            normalized_requirements.append(requirement)
            continue
        normalized_requirements.append(normalized)
        repairs.append(
            {
                "requirementId": requirement.requirement_id,
                "addedColumns": grain_issue["missingValues"],
                "repairTargets": grain_issue["repairTargets"],
            }
        )
    if not repairs:
        return bundle, []
    normalized_bundle = AnalysisBundle.model_validate(
        {
            "analyses": [item.model_dump(mode="json", by_alias=True) for item in bundle.analyses],
            "requirements": [
                item.model_dump(mode="json", by_alias=True) for item in normalized_requirements
            ],
        }
    )
    return normalized_bundle, repairs


def _normalize_requirement_columns(
    bundle: AnalysisBundle,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> tuple[AnalysisBundle, list[dict[str, Any]]]:
    """删除结构快照外的维度/粒度字段，不猜测语义别名或补充新字段。"""

    normalized_requirements: list[QueryRequirement] = []
    repairs: list[dict[str, Any]] = []
    for requirement in bundle.requirements:
        normalized, repair = _normalize_requirement_column_values(requirement, snapshots)
        normalized_requirements.append(normalized)
        if repair is not None:
            repairs.append(repair)
    if not repairs:
        return bundle, []
    return (
        AnalysisBundle.model_validate(
            {
                "analyses": [
                    item.model_dump(mode="json", by_alias=True) for item in bundle.analyses
                ],
                "requirements": [
                    item.model_dump(mode="json", by_alias=True) for item in normalized_requirements
                ],
            }
        ),
        repairs,
    )


def _normalize_requirement_periods(
    bundle: AnalysisBundle,
    plan: DataUnderstandingPlan,
) -> tuple[AnalysisBundle, list[dict[str, Any]]]:
    """把取数期间恢复为已冻结的数据理解事实，不让规划模型重新解释字段语义。

    DataUnderstandingPlan 已依据真实 Schema 和字段值完成审批，是期间字段与粒度的
    唯一事实来源。这里只处理 sourceId/table 能唯一命中的表；未知或多义引用仍交给
    后续语义校验失败关闭，不能通过相似名称猜测替换。
    """

    selected = {(item.source_id, item.table): item for item in plan.tables}
    normalized_requirements: list[QueryRequirement] = []
    repairs: list[dict[str, Any]] = []
    for requirement in bundle.requirements:
        normalized_tables = []
        for table_index, table in enumerate(requirement.tables):
            matches = [
                item
                for (source_id, qualified), item in selected.items()
                if source_id == requirement.source_id
                and (qualified == table.table or qualified.endswith(f".{table.table}"))
            ]
            if len(matches) != 1:
                normalized_tables.append(table)
                continue
            understood = matches[0]
            if (
                understood.period_column.lower() == table.period_column.lower()
                and understood.period_granularity == table.period_granularity
            ):
                normalized_tables.append(table)
                continue
            normalized_tables.append(
                table.model_copy(
                    update={
                        "period_column": understood.period_column,
                        "period_granularity": understood.period_granularity,
                    }
                )
            )
            repairs.append(
                {
                    "requirementId": requirement.requirement_id,
                    "tableIndex": table_index,
                    "table": table.table,
                    "periodColumn": understood.period_column,
                    "periodGranularity": understood.period_granularity,
                }
            )
        normalized_requirements.append(
            requirement.model_copy(update={"tables": tuple(normalized_tables)})
        )
    if not repairs:
        return bundle, []
    return (
        AnalysisBundle.model_validate(
            {
                "analyses": [
                    item.model_dump(mode="json", by_alias=True) for item in bundle.analyses
                ],
                "requirements": [
                    item.model_dump(mode="json", by_alias=True) for item in normalized_requirements
                ],
            }
        ),
        repairs,
    )


def _normalize_requirement_column_values(
    requirement: QueryRequirement,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> tuple[QueryRequirement, dict[str, Any] | None]:
    column_sets = [
        {
            column.name
            for column in _analysis_table_columns(requirement.source_id, table.table, snapshots)
        }
        for table in requirement.tables
    ]
    if not column_sets or any(not columns for columns in column_sets):
        return requirement, None
    dimension_allowed = set.union(*column_sets)
    grain_allowed = set.intersection(*column_sets)
    dimensions = tuple(
        value for value in requirement.dimension_columns if value in dimension_allowed
    )
    grain = tuple(
        value
        for value in requirement.grain_columns
        if value in grain_allowed and value in dimensions
    )
    if (
        not dimensions
        or not grain
        or (dimensions == requirement.dimension_columns and grain == requirement.grain_columns)
    ):
        return requirement, None
    return (
        requirement.model_copy(update={"dimension_columns": dimensions, "grain_columns": grain}),
        {
            "requirementId": requirement.requirement_id,
            "removedDimensionColumns": [
                value for value in requirement.dimension_columns if value not in dimensions
            ],
            "removedGrainColumns": [
                value for value in requirement.grain_columns if value not in grain
            ],
        },
    )


def _normalize_requirement_columns_in_payload(
    payload: dict[str, Any],
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> dict[str, Any]:
    requirements = payload.get("requirements")
    if not isinstance(requirements, list):
        return payload
    normalized_payload = dict(payload)
    normalized_requirements = list(requirements)
    changed = False
    for index, candidate in enumerate(requirements):
        try:
            requirement = QueryRequirement.model_validate(candidate)
        except ValidationError:
            continue
        normalized, repair = _normalize_requirement_column_values(requirement, snapshots)
        if repair is None:
            continue
        normalized_requirements[index] = normalized.model_dump(mode="json", by_alias=True)
        changed = True
    if not changed:
        return payload
    normalized_payload["requirements"] = normalized_requirements
    return normalized_payload


def _normalize_comparison_roles(
    bundle: AnalysisBundle,
    requested_roles: tuple[Literal["yoy", "mom"], ...],
) -> tuple[AnalysisBundle, list[dict[str, Any]]]:
    """把需求比较窗口收敛到用户已授权集合，分析层环比计算不因此受限。"""

    requested = tuple(role for role in ("yoy", "mom") if role in requested_roles)
    repairs: list[dict[str, Any]] = []
    normalized_requirements: list[QueryRequirement] = []
    for requirement in bundle.requirements:
        selected = requirement.comparison_roles
        if selected is None:
            normalized_requirements.append(requirement)
            continue
        normalized = tuple(role for role in requested if role in selected)
        stored = None if normalized == requested else normalized
        if stored == selected:
            normalized_requirements.append(requirement)
            continue
        normalized_requirements.append(requirement.model_copy(update={"comparison_roles": stored}))
        repairs.append(
            {
                "requirementId": requirement.requirement_id,
                "removedRoles": [role for role in selected if role not in requested],
                "comparisonRoles": list(normalized),
            }
        )
    if not repairs:
        return bundle, []
    return (
        AnalysisBundle.model_validate(
            {
                "analyses": [
                    item.model_dump(mode="json", by_alias=True) for item in bundle.analyses
                ],
                "requirements": [
                    item.model_dump(mode="json", by_alias=True) for item in normalized_requirements
                ],
            }
        ),
        repairs,
    )


def _normalize_duplicate_requirements(
    bundle: AnalysisBundle,
) -> tuple[AnalysisBundle, list[dict[str, Any]]]:
    """合并同一物理窗口的重复取数需求，避免物化后把同一事实当成多来源冲突。

    同一张表的不同分析视角只需要一次包含完整指标和安全粒度的查询；Coding 会按
    详细计划从不可变 CSV 复算。合并只扩展字段集合并改写引用，不对数值
    做加法，也不吞掉真实的跨数据集冲突。
    """

    canonical_by_key: dict[tuple[Any, ...], int] = {}
    merged: list[QueryRequirement] = []
    replacement: dict[str, str] = {}
    repairs: list[dict[str, Any]] = []
    for requirement in bundle.requirements:
        if len(requirement.tables) != 1:
            merged.append(requirement)
            continue
        table = requirement.tables[0]
        key = (
            requirement.source_id.lower(),
            table.table.lower(),
            table.period_column.lower(),
            table.period_granularity,
            requirement.comparison_roles,
        )
        canonical_index = canonical_by_key.get(key)
        if canonical_index is None:
            canonical_by_key[key] = len(merged)
            merged.append(requirement)
            continue
        canonical = merged[canonical_index]
        canonical_table = canonical.tables[0]
        merged_table = canonical_table.model_copy(
            update={
                "measure_columns": tuple(
                    dict.fromkeys((*canonical_table.measure_columns, *table.measure_columns))
                ),
            }
        )
        merged_requirement = canonical.model_copy(
            update={
                "tables": (merged_table,),
                "dimension_columns": tuple(
                    dict.fromkeys((*canonical.dimension_columns, *requirement.dimension_columns))
                ),
                "grain_columns": tuple(
                    dict.fromkeys((*canonical.grain_columns, *requirement.grain_columns))
                ),
            }
        )
        try:
            merged[canonical_index] = QueryRequirement.model_validate(
                merged_requirement.model_dump(mode="json", by_alias=True)
            )
        except ValidationError:
            # 只有合并后的字段集合超过协议上限时才保留原需求，让语义校验给出
            # 精确的可修复路径；不能静默丢字段。
            merged.append(requirement)
            continue
        replacement[requirement.requirement_id] = canonical.requirement_id
        repairs.append(
            {
                "removedRequirementId": requirement.requirement_id,
                "canonicalRequirementId": canonical.requirement_id,
                "table": table.table,
            }
        )

    if not repairs:
        return bundle, []
    analyses: list[AnalysisItem] = []
    for analysis in bundle.analyses:
        analyses.append(
            analysis.model_copy(
                update={
                    "requirement_ids": tuple(
                        dict.fromkeys(
                            replacement.get(item, item) for item in analysis.requirement_ids
                        )
                    )
                }
            )
        )
    normalized = AnalysisBundle.model_validate(
        {
            "analyses": [item.model_dump(mode="json", by_alias=True) for item in analyses],
            "requirements": [item.model_dump(mode="json", by_alias=True) for item in merged],
        }
    )
    return normalized, repairs


def _multi_table_requirement_issues(
    requirement: QueryRequirement,
    requirement_index: int,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> list[dict[str, Any]]:
    if len(requirement.tables) <= 1:
        return []

    path = f"requirements[{requirement_index}]"
    issues: list[dict[str, Any]] = []
    granularities = sorted({table.period_granularity for table in requirement.tables})
    if len(granularities) > 1:
        issues.append(
            {
                "path": f"{path}.tables",
                "rejectedValue": [
                    {
                        "table": table.table,
                        "periodColumn": table.period_column,
                        "periodGranularity": table.period_granularity,
                    }
                    for table in requirement.tables
                ],
                "reason": "多表 requirement 的 periodGranularity 不一致，不能在同一 SQL 中强行拼接",
                "allowedValues": granularities,
                "requiredAction": (
                    "拆分为单表 requirements，并让 analyses.requirementIds 同时引用它们"
                ),
            }
        )

    available_columns = _available_table_columns(snapshots)
    grain_columns = set(requirement.grain_columns)
    for table_index, table in enumerate(requirement.tables):
        matches = [
            columns
            for (source_id, qualified), columns in available_columns.items()
            if source_id == requirement.source_id
            and (qualified == table.table or qualified.endswith(f".{table.table}"))
        ]
        if len(matches) != 1:
            continue
        columns = {column.lower() for column in matches[0]}
        missing = sorted(grain_columns - columns)
        if missing:
            issues.append(
                {
                    "path": f"{path}.grainColumns",
                    "rejectedValue": {"table": table.table, "missingColumns": missing},
                    "reason": (
                        "多表 requirement 的全部 grainColumns 必须真实存在于每张表；"
                        f"{table.table} 缺少 {', '.join(missing)}"
                    ),
                    "allowedValues": sorted(columns),
                    "requiredAction": (
                        "拆分为单表 requirements；只有确实存在完整共同粒度时才保留多表 requirement"
                    ),
                }
            )

    for relation_index, relation in enumerate(requirement.relations):
        if set(relation.join_columns) != grain_columns:
            issues.append(
                {
                    "path": f"{path}.relations[{relation_index}].joinColumns",
                    "rejectedValue": list(relation.join_columns),
                    "reason": (
                        "多表预聚合结果必须按完整 grainColumns 等值关联，"
                        "否则可能产生多对多重复和指标放大"
                    ),
                    "allowedValues": list(requirement.grain_columns),
                    "requiredAction": (
                        "joinColumns 必须完整等于 grainColumns；无法满足时拆分为单表 requirements"
                    ),
                }
            )
    return issues
