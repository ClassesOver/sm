# mypy: disable-error-code="attr-defined"
# 运行时方法由 facade 组合的多重继承提供；静态检查无法解析该装配顺序。
from __future__ import annotations

# 能力模块通过本中立底座复用共享符号；这些导入是稳定的组合边界依赖面。
# ruff: noqa: F401
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
from loguru import logger as loguru_logger
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from ....async_utils import complete_cleanup
from ....task_execution import TaskScope, TaskState
from ....workspace import WorkspaceService
from ...contract import (
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
from ...data_source import (
    CatalogColumn,
    CatalogTable,
    DataShape,
    ReportSourceRegistryConfig,
    StarRocksDataSourceAdapter,
    StarRocksSourceConfig,
    collect_data_shape,
    require_sources,
)
from ...data_sources import MAX_REPORT_INPUTS, DatasetHandle, ReportDatasetStore
from ...delivery.acceptance import (
    build_report_artifact_validation_context,
    build_report_phase_acceptance_contract,
)
from ...delivery.artifacts_v1 import (
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
from ...delivery.draft_v1 import (
    HeadingNumber,
    ReportChartInput,
    ReportDraft,
    ReportDraftSection,
    ReportSectionDefinition,
    assemble_report_markdown,
    validate_report_draft_blocks,
)
from ...delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportArtifactSpec,
    ReportDownloadGrantService,
    ReportDownloadScope,
    cli_result,
    publication_result,
)
from ...delivery.report_runtime import REPORT_VISUAL_THEME
from ...hospital_operation.delivery import (
    PlanExecutionReceipt,
    SourceWarning,
)
from ...hospital_operation.detailed_analysis import (
    DatasetAnalysisContext,
    DetailedAnalysisItem,
    DetailedAnalysisPlan,
    profile_csv_dataset,
)
from ...hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from ...hospital_operation.domains import DOMAIN_CODES, resolve_domain_mentions
from ...hospital_operation.outline import (
    ReportOutline,
    ReportOutlineProposal,
    freeze_outline,
)
from ...hospital_operation.profiles import HospitalOperationProfile, ruijin_profile
from ...instructions import (
    HOSPITAL_ANALYSIS_INSTRUCTIONS,
    HOSPITAL_DATA_UNDERSTANDING_INSTRUCTIONS,
    HOSPITAL_OUTLINE_INSTRUCTIONS,
    HOSPITAL_REQUEST_INSTRUCTIONS,
)
from ...metadata import ReportingMetadataClient
from ...model_policy import (
    ReportingThinkingProfile,
    apply_reporting_thinking_profile,
    reporting_thinking_profile_from_model,
)
from ...models import ReportingError
from ...phase import REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR
from ...profile import (
    CapabilitySet,
    EffectiveReportingProfile,
    ReconciliationShape,
    ReportingProfileRegistry,
    bind_reporting_profile_sources,
    build_outline_shape_view,
    parse_field_ref,
    resolve_reporting_profile,
)
from ...profile import (
    resolve_capabilities as resolve_profile_capabilities,
)
from ...workspace import WorkspaceReportService
from ..checkpoint import (
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
from ..execution import (
    MAX_REPORT_INSTRUCTION_BYTES,
    ReportTaskRunner,
    _raise_recorded_agent_error,
)
from ..orchestration import create_reporting_workflow, record_step_model_metrics
from ..query_pipeline import (
    ApprovedQuery,
    DatasetLineage,
    QueryRequirement,
    approve_query_batch,
    resolve_schema_snapshot,
    state_contains_connection_data,
)
from ..repository import ReportingStateRepository
from ..state import ReportingCommand, ReportingStateError
from ..state import ReportingPhase as DurableReportingPhase
from .models import (
    AnalysisBundle,
    AnalysisItem,
    DataUnderstandingPlan,
    DataUnderstandingTable,
    GeneratedQuery,
    GeneratedQueryBatch,
    MeasureSemanticDecision,
    MeasureSemanticProposal,
    NormalizedReportPrompt,
    PlanningSchema,
    PlanningSchemaColumn,
    PlanningSchemaTable,
    TableReference,
    _normalize_analysis_bundle_table_refs,
    _StrictModel,
)

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
    if _visualization_recovery_required(last_error):
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


_VISUALIZATION_RECOVERY_ERROR_CODES = frozenset(
    {
        "report_visualization_tool_budget_exhausted",
        "report_visualization_exploration_budget_exhausted",
        "report_visualization_script_failure_limit_exhausted",
    }
)


def _visualization_recovery_required(last_error: Exception | None) -> bool:
    """仅预算类终态错误进入禁止重新探索的恢复模式。"""

    return isinstance(last_error, ReportingError) and last_error.code in (
        _VISUALIZATION_RECOVERY_ERROR_CODES
    )


def _visualization_retry_budget(last_error: Exception | None) -> tuple[int, int]:
    usage = _visualization_retry_usage(last_error)
    return usage["visualizationToolCalls"], usage["visualizationScriptFailures"]


def _visualization_retry_usage(last_error: Exception | None) -> dict[str, int]:
    source: Any = getattr(last_error, REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR, None)
    details = last_error.details if isinstance(last_error, ReportingError) else None

    def count(raw: Any) -> int:
        return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0

    if isinstance(source, Mapping):
        usage = {
            "visualizationReadUnitsUsed": count(source.get("visualizationReadUnitsUsed")),
            "visualizationFactQueriesUsed": count(source.get("visualizationFactQueriesUsed")),
            "visualizationToolCalls": count(
                source.get("visualizationToolCalls", source.get("totalToolCalls"))
            ),
            "visualizationScriptFailures": count(
                source.get("visualizationScriptFailures", source.get("scriptFailureCount"))
            ),
        }
        # 预算终态错误在动态预留点生成，details 对总调用和脚本失败的计数最及时；
        # read/fact 则只能来自 worker 退出时附加的完整累计快照，两者必须合并。
        if isinstance(details, Mapping):
            if "totalToolCalls" in details:
                usage["visualizationToolCalls"] = count(details.get("totalToolCalls"))
            if "scriptFailureCount" in details:
                usage["visualizationScriptFailures"] = count(details.get("scriptFailureCount"))
        return usage
    if isinstance(source, Sequence) and not isinstance(source, (str, bytes)) and len(source) == 2:
        return {
            "visualizationReadUnitsUsed": 0,
            "visualizationFactQueriesUsed": 0,
            "visualizationToolCalls": count(source[0]),
            "visualizationScriptFailures": count(source[1]),
        }
    if isinstance(details, Mapping):
        return {
            "visualizationReadUnitsUsed": 0,
            "visualizationFactQueriesUsed": 0,
            "visualizationToolCalls": count(details.get("totalToolCalls")),
            "visualizationScriptFailures": count(details.get("scriptFailureCount")),
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
    read_limit = max(12, evidence_read_units + 8)
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


_PLANNER_DISPLAY_NAMES = {
    "report-request-normalizer": "需求理解",
    "report-data-understanding-planner": "数据范围分析",
    "report-measure-semantic-proposer": "指标口径整理",
    "report-analysis-planner": "分析计划设计",
    "report-sql-planner": "取数方案设计",
    "report-outline-planner": "报告提纲规划",
}


class _ReportWorkflowRuntimeBase:
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
            profile = resolve_reporting_profile(self.profiles, next(iter(profile_ids)))
            return bind_reporting_profile_sources(
                profile, {source.id: source.database for source in sources}
            )
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
        state = _ReportWorkflowRuntimeBase._state(run_context)
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
        description=table.description,
        columns=tuple(
            ModelColumn(
                name=item.name,
                dataType=item.data_type,
                nullable=item.nullable,
                description=item.description,
            )
            for item in table.columns
        ),
    )


def _catalog_scope(tables: tuple[ModelTable, ...]) -> tuple[CatalogTable, ...]:
    return tuple(
        CatalogTable(
            source_id=table.source_id,
            database=table.database,
            name=table.name,
            description=table.description,
            columns=tuple(
                CatalogColumn(
                    name=column.name,
                    data_type=column.data_type,
                    nullable=column.nullable,
                    description=column.description,
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
