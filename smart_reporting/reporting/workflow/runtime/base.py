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
from ....context_management import TaskExecutionContextHardLimitError
from ....quality_warnings.service import QualityWarningService
from ....task_execution import TaskExecutionScope, TaskState
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
from ...delivery.report_runtime.markdown import REPORT_VISUAL_THEME
from ...hospital_operation.delivery import (
    PlanExecutionReceipt,
    SourceWarning,
)
from ...hospital_operation.detailed_analysis import (
    DatasetAnalysisContext,
    DetailedAnalysisItem,
    DetailedAnalysisPlan,
    profile_csv_dataset,
    time_series_diagnostics_requested,
)
from ...hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
    build_deterministic_analysis_bundle,
    validate_metric_code_bindings,
)
from ...hospital_operation.domains import DOMAIN_CODES, resolve_domain_mentions
from ...hospital_operation.outline import (
    ReportOutline,
    ReportOutlineProposal,
    freeze_outline,
    normalize_outline_proposal_candidate,
)
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
from ...phase import (
    REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR,
    REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
)
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
from ...structured_output import ReportingStructuredOutputExecutor, StructuredOutputCallBudget
from ...vision import ReportVisionReviewer
from ...workspace import WorkspaceReportService
from ..checkpoint import (
    AnalysisArtifact,
    AnalysisChart,
    AnalysisDatasetSemantics,
    AnalysisEvidence,
    AnalysisEvidenceManifest,
    AnalysisReworkRequest,
    CompletedSection,
    ContextTrace,
    FileIdentity,
    MetricDefinition,
    ProfileCoverageManifest,
    ProfileReadReceipt,
    ReportBrief,
    ReportingCheckpoint,
    SectionArtifact,
    SectionCitation,
    SectionManagementQuestion,
    SectionWorkItem,
    build_profile_coverage_manifest,
    payload_sha256,
    reporting_phase_task_key,
)
from ..execution import (
    MAX_REPORT_INSTRUCTION_BYTES,
    ReportingTaskCoordinator,
)
from ..orchestration import create_reporting_workflow, record_step_model_metrics
from ..query_pipeline import (
    ApprovedQuery,
    DatasetLineage,
    QueryRequirement,
    approve_query_batch,
    project_measure_semantics_to_query_outputs,
    resolve_schema_snapshot,
    state_contains_connection_data,
)
from ..repository import ReportingStateRepository
from ..state import ReportingCommand, ReportingStateError
from ..state import ReportingPhase as DurableReportingPhase
from .analysis_item_workflow import (
    AnalysisEvidenceDecision,
    AnalysisScriptDraft,
    AnalysisSummaryDraft,
)
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
# 每个章节/分析项的 fresh retry 上限；模型未调用工具、工具拒绝或验收失败都必须
# 重新创建上下文，最多三次，避免单次模型异常直接拖垮整条报表链路。
MAX_REPORT_SECTION_PHASE_ATTEMPTS = 3
MAX_REPORT_ANALYSIS_REWORKS_PER_SECTION = 1
MAX_SECTION_WORK_ITEM_BYTES = 256 * 1024


_VISUALIZATION_RECOVERY_ERROR_CODES = frozenset(
    {
        "report_worker_terminal_tool_missing",
        "report_visualization_tool_budget_exhausted",
        "report_visualization_exploration_budget_exhausted",
        "report_visualization_script_failure_limit_exhausted",
    }
)


_JSON_FENCE_PATTERN = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
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


def _reporting_observed_data_facts(
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


def _human_label(value: str | None, fallback: str) -> str:
    normalized = " ".join(str(value or "").split())
    if normalized and re.search(r"[\u4e00-\u9fff]", normalized):
        return normalized[:120]
    return fallback


_PLANNER_DISPLAY_NAMES = {
    "report-request-normalizer": "需求理解",
    "report-data-understanding-planner": "数据范围分析",
    "report-measure-semantic-proposer": "指标口径整理",
    "report-analysis-planner": "分析计划设计",
    "report-analysis-evidence-planner": "补充证据规划",
    "report-analysis-script-writer": "补证脚本生成",
    "report-analysis-summary-writer": "单项分析总结",
    "report-sql-planner": "取数方案设计",
    "report-outline-planner": "报告提纲规划",
}

OUTLINE_SECTION_COUNT_INSTRUCTION = (
    "按详细分析计划的重要性组织动态章节；未涉及或无数据领域不得生成空章。"
    "必须优先遵守 reportGoal 中明确的章节数量约束（例如‘一个章节’）；"
    "该约束高于按 analysisId 拆分章节的默认组织方式，所有相关 analysisId 应合并到"
    "不超过用户指定数量的章节中。用户未指定数量时才按分析计划动态拆分。"
)


class _ReportWorkflowRuntimeBase:
    """v1 报表运行时；数据库连接只存在于服务端 adapter 内。"""

    def __init__(
        self,
        *,
        db: Any,
        reporting_agent_template: Agent,
        task_runner: ReportingTaskCoordinator,
        visualization_generator: Agent | None = None,
        visualization_recovery: Agent | None = None,
        section_generator: Agent | None = None,
        section_recovery: Agent | None = None,
        vision_reviewer: ReportVisionReviewer | None = None,
        vision_enabled: bool | None = None,
        workspace_service: WorkspaceService,
        registry: ReportSourceRegistryConfig,
        profiles: ReportingProfileRegistry,
        planner_enable_thinking: bool,
        planner_reasoning_effort: str = "high",
        planner_thinking_budget: int = 8192,
        metadata_client: ReportingMetadataClient | None = None,
        download_grants: ReportDownloadGrantService | None = None,
        artifact_persistence: ReportArtifactPersistenceService | None = None,
        quality_warning_service: QualityWarningService | None = None,
        report_public_base_url: str | None = None,
        state_repository: ReportingStateRepository,
        analysis_concurrency: int = 1,
        section_concurrency: int = 1,
        reporting_execution_mode: str = "sequential",
    ):
        if (download_grants is None) != (artifact_persistence is None):
            raise ValueError("下载授权和产物持久化服务必须同时配置")
        if download_grants is not None and report_public_base_url is None:
            raise ValueError("启用 HTTP 报表发布时必须配置公开下载基址")
        self.db = db
        self.reporting_agent_template = reporting_agent_template
        self._analysis_thinking_enabled = planner_enable_thinking
        self._vision_enabled = (
            bool(getattr(reporting_agent_template.model, "_report_vision_enabled", True))
            if vision_enabled is None
            else vision_enabled
        )
        self.task_runner = task_runner
        self.visualization_generator = visualization_generator
        self.visualization_recovery = visualization_recovery
        self.section_generator = section_generator
        self.section_recovery = section_recovery
        self.vision_reviewer = vision_reviewer
        self.workspace_service = workspace_service
        self.registry = registry
        self.profiles = profiles
        self.metadata_client = metadata_client
        self.download_grants = download_grants
        self.artifact_persistence = artifact_persistence
        self.quality_warning_service = quality_warning_service
        self.report_public_base_url = report_public_base_url
        self.state_repository = state_repository
        if isinstance(analysis_concurrency, bool) or not 1 <= analysis_concurrency <= 4:
            raise ValueError("analysis_concurrency 必须在 1 到 4 之间")
        if isinstance(section_concurrency, bool) or not 1 <= section_concurrency <= 5:
            raise ValueError("section_concurrency 必须在 1 到 5 之间")
        if reporting_execution_mode not in {"sequential", "parallel"}:
            raise ValueError("reporting_execution_mode 必须是 sequential 或 parallel")
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
        self.reporting_execution_mode = reporting_execution_mode
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
        # 分析计划首次请求只需要整理已冻结的 Schema、画像能力和管理问题；将
        # 首次推理预算减半可以避免每次正常请求都支付 max 档成本。结构化校验
        # 或服务端 correction 仍通过 planner_max 使用完整预算，不能削弱失败修复能力。
        planner_analysis_initial = (
            ReportingThinkingProfile.on(
                reasoning_effort="high",
                thinking_budget=max(4096, planner_thinking_budget // 2),
            )
            if planner_enable_thinking
            else planner_off
        )
        # DeepSeek V4 只有 off/high/max 三个真实档位。数据理解和指标语义 Planner
        # 首次请求关闭 thinking，只有 Schema 校验失败或服务端签发 correction 时才升级；
        # 分析计划首次使用 high，只有 Schema 校验失败或服务端签发 correction 时才升级 max，
        # 因为正常请求只需整理已批准能力，失败修复才需要完整推理预算。
        # SQL 在首次请求关闭 thinking，失败后升到 max；归一化和提纲始终 off。
        self._request_normalizer = self._planning_agent(
            reporting_agent_template,
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
            reporting_agent_template,
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
            reporting_agent_template,
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
            reporting_agent_template,
            "report-outline-planner",
            ReportOutlineProposal,
            thinking_profile=planner_off,
            stage_instructions=(
                *HOSPITAL_OUTLINE_INSTRUCTIONS,
                "只返回 reportType、中文报告标题、sections 和 assumptions；sections 不得提交 code",
                "每个章节必须引用一个或多个 outlineContext.analyses 中已注册的 analysisId",
                OUTLINE_SECTION_COUNT_INSTRUCTION,
                "section code 由服务端在批准后生成，模型不得提交或猜测 section_NNN",
            ),
        )
        self._analysis_agent = self._planning_agent(
            reporting_agent_template,
            "report-analysis-planner",
            AnalysisBundle,
            thinking_profile=planner_analysis_initial,
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
        self._analysis_evidence_agent = self._planning_agent(
            reporting_agent_template,
            "report-analysis-evidence-planner",
            AnalysisEvidenceDecision,
            thinking_profile=planner_high,
            escalation_thinking_profile=planner_max,
            stage_instructions=(
                "先对照 currentAnalysis 的管理问题与 deterministicFacts，只有缺少回答该问题的必需构成、归因或对比事实时才设置 requiresSupplementalEvidence=true。",
                "只返回 requiresSupplementalEvidence、reason、missingFacts，不得生成 script 或任何代码。",
                "固定事实足够时 missingFacts 必须为空数组，不得为了探索数据而声明缺口。",
            ),
        )
        self._analysis_script_agent = self._planning_agent(
            reporting_agent_template,
            "report-analysis-script-writer",
            AnalysisScriptDraft,
            thinking_profile=planner_high,
            escalation_thinking_profile=planner_max,
            stage_instructions=(
                "只针对 evidenceDecision.missingFacts 生成一个最小 Python 脚本；不得重新判断事实缺口。",
                "脚本只能读取 datasets 中签发的 CSV path，并只写入输入给定的 evidencePath。",
                "使用单向线性数据流；所有后续读取的局部变量必须在进入条件分支前初始化，并确保每个分支都赋值。",
                "每个 CSV 只能使用同一 datasets[] 项声明的 columns；不得把 currentAnalysis.fields 或其他 Dataset 的字段用于该 CSV。",
                "evidencePath 必须写为 JSON 对象，且只含 analysisId、datasetIds、findings、reconciliations、warnings；findings 至少一项，reconciliations 至少一项且每项含 name 和 passed。",
                "表格型 finding 必须使用 name、columns、rows 列式结构：columns 只声明一次字段名，rows 使用等长值数组；不得输出重复字段名的对象行数组。",
                "写入 evidencePath 时必须使用 json.dump(..., ensure_ascii=False, separators=(',', ':')) 紧凑编码；不得使用 indent，且不得删减任何已计算事实。",
                "构成分析必须计算分项合计与总量差异，对账成功才把 passed 写为 true；不得猜测、补齐或替换缺失值。",
                "脚本不得访问网络、环境变量、数据库、工作区其他路径或启动子进程。",
                "correction 存在时保留 evidenceDecision，不改变事实缺口，只修正导致执行或 evidence 校验失败的代码。",
                "correction.error 是服务端结构化失败事实；必须逐项读取 code、message 和 details.path，不得原样返回与 previousScript 相同的脚本。",
            ),
        )
        self._analysis_summary_agent = self._planning_agent(
            reporting_agent_template,
            "report-analysis-summary-writer",
            AnalysisSummaryDraft,
            thinking_profile=planner_high,
            escalation_thinking_profile=planner_max,
            stage_instructions=(
                "只回答 currentAnalysis 的原子管理问题，所有数字和结论必须来自 deterministicFacts 或 supplementalEvidence。",
                "优先给出结论、关键数值、构成或变化驱动，再说明可比性和数据限制；不得输出分析过程或虚构因果。",
                "supplementalEvidence 为 null 且 evidenceWarnings 声明补证已放弃时，只能使用 deterministicFacts；不得声称缺失事实已经验证。",
                "summary 使用可直接进入报告的中文业务表述，不使用 Markdown 标题；warnings 只保留会影响结论解释的事实限制。",
            ),
        )
        self._sql_agent = self._planning_agent(
            reporting_agent_template,
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
            elif output_schema is ReportOutlineProposal:
                candidate = normalize_outline_proposal_candidate(candidate)
            try:
                return output_schema.model_validate(candidate)
            except ValidationError as error:
                # 把候选载荷附在异常上。Reporting 结构化执行器据此向同一模型回灌
                # previousOutput 和逐项 issues；候选不进入日志或公开错误 details。
                error._report_candidate = candidate  # type: ignore[attr-defined]
                raise

        setattr(planner_model, "_report_response_validator", validate_response)
        agent_retries = (
            0
            if output_schema in {AnalysisBundle, AnalysisEvidenceDecision, AnalysisScriptDraft}
            else 2
        )
        agent = planner.deep_copy(
            update={
                "id": agent_id,
                # ID 供状态恢复、日志关联和代码判断；name 只负责面向用户的 Trace 展示。
                "name": _PLANNER_DISPLAY_NAMES.get(agent_id, agent_id),
                "role": "只根据已批准的结构、术语和画像生成结构化报表规划。",
                "model": planner_model,
                # 结构化执行器会显式回灌 ValidationError；这些阶段关闭 Agno 对同一
                # 输入的盲重试，其他 planner 继续沿用既有 Agno retry 边界。
                "retries": agent_retries,
                "exponential_backoff": agent_retries > 0,
                "instructions": [
                    "只返回与 output_schema 匹配的 JSON。",
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
                # 摘要。若从 Reporting Agent 继承摘要配置，Agno 会在每次大目录分析后再次
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
            run_reporting_analysis=self.run_reporting_analysis,
            validate_report=self.validate_report,
            finalize_publication=finalize_publication,
        )

    async def _run_planner(
        self,
        agent: Agent,
        payload: dict[str, Any],
        run_context: RunContext,
        *,
        call_budget: StructuredOutputCallBudget | None = None,
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
        try:
            structured = await ReportingStructuredOutputExecutor(agent).execute(
                serialized_payload,
                routing_context=run_context,
                session_id=f"report-planning-{digest}",
                user_id=scope["userId"],
                # Planner 维持既有的无外层 session_state 语义；模型路由只从
                # routing_context 读取，不把任务工具上下文传入无工具规划器。
                agent_run_context=None,
                call_budget=call_budget,
            )
        except TaskExecutionContextHardLimitError as error:
            hard_limit_metrics = error.metrics
            loguru_logger.bind(
                agent_id=agent.id,
                error_code=error.code,
                canonical_estimated_tokens=hard_limit_metrics.get("canonical_estimated_tokens", 0),
                irreducible_prefix_estimated_tokens=hard_limit_metrics.get(
                    "irreducible_prefix_estimated_tokens", 0
                ),
                input_token_hard_cap=hard_limit_metrics.get("input_token_hard_cap", 0),
                tool_schema_bytes=hard_limit_metrics.get("tool_schema_bytes", 0),
                response_format_bytes=hard_limit_metrics.get("response_format_bytes", 0),
            ).warning("report_planner_context_hard_limit_exceeded")
            raise ReportingError(
                "report_planner_context_budget_exceeded",
                f"报表规划输入的不可约简上下文超过当前模型输入预算（{agent.id}）。",
                details=dict(hard_limit_metrics),
            ) from error
        except ReportingError:
            raise
        output = structured.run_output
        content = structured.content
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
                key: str(value.get(key) or "")
                for key in ("externalRunId", "threadId", "userId", "database", "companyId")
            }
        else:
            value = state.get(REPORT_WORKFLOW_SCOPE_STATE_KEY)
            scope = (
                {
                    key: str(value.get(key) or "")
                    for key in ("externalRunId", "threadId", "userId", "database", "companyId")
                }
                if isinstance(value, dict)
                else {
                    "externalRunId": str(run_context.run_id or ""),
                    "threadId": str(run_context.session_id or ""),
                    "userId": str(run_context.user_id or ""),
                    "database": "",
                    "companyId": "",
                }
            )
        if not scope["database"] and not scope["companyId"]:
            scope["database"] = "default"
            scope["companyId"] = "default"
        elif not scope["database"] or not scope["companyId"]:
            raise ReportingError("report_workflow_context_missing", "报表工作流作用域不完整。")
        if (
            any(not item for key, item in scope.items() if key not in {"database", "companyId"})
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
            "htmlPath": content.get("htmlPath"),
            "htmlSize": content.get("htmlSize"),
            "htmlSha256": content.get("htmlSha256"),
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
            or not isinstance(values["htmlPath"], str)
            or not isinstance(values["htmlSize"], int)
            or values["htmlSize"] <= 0
            or not isinstance(values["htmlSha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", values["htmlSha256"]) is None
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
                "报表来源告警或 Reporting 回执无效。",
            ) from error
        return values

    @staticmethod
    def _require_artifact_identity(
        expected: dict[str, Any],
        current: dict[str, Any],
        *,
        artifact: Literal["pdf", "word", "html"],
    ) -> None:
        prefix = artifact
        if (
            current.get("size") != expected[f"{prefix}Size"]
            or current.get("sha256") != expected[f"{prefix}Sha256"]
        ):
            raise ReportingError(
                "report_artifact_changed",
                "PDF、Word 或 HTML 在验收或审核后发生变化，必须重新验收。",
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
