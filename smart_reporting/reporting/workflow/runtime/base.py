# mypy: disable-error-code="attr-defined"
# 运行时方法由 facade 组合的多重继承提供；静态检查无法解析该装配顺序。
from __future__ import annotations

# 能力模块通过本中立底座复用共享符号；这些导入是稳定的组合边界依赖面。
# ruff: noqa: F401
import asyncio
import hashlib
import json
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
from ....model_routing import TaskComplexity
from ....quality_warnings.service import QualityWarningService
from ....task_execution import TaskExecutionScope, TaskState
from ....workspace import WorkspaceService
from ...code_agent.context import ReportingCodingTaskRegistry
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
from ...hospital_operation.domains import DOMAIN_CODES
from ...hospital_operation.outline import (
    ReportOutline,
    ReportOutlineProposal,
    freeze_outline,
    normalize_outline_proposal_candidate,
)
from ...host_workspace import (
    HostReportingWorkspace,
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from ...instructions import (
    HOSPITAL_ANALYSIS_INSTRUCTIONS,
    HOSPITAL_DATA_UNDERSTANDING_INSTRUCTIONS,
    HOSPITAL_OUTLINE_INSTRUCTIONS,
    HOSPITAL_REQUEST_INSTRUCTIONS,
)
from ...knowledge import ReportingKnowledgeIndex
from ...metadata import ReportingMetadataClient
from ...model_policy import (
    ReportingThinkingProfile,
    ThinkingFailureKind,
    ThinkingPolicyConfig,
    ThinkingRequest,
    apply_reporting_thinking_profile,
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
from ..benchmark_variants import BenchmarkPlannerSpec
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
from ..orchestration import (
    PlannerRequestRecorder,
    bind_planner_request_recorder,
    create_reporting_workflow,
    record_step_model_metrics,
    reset_planner_request_recorder,
)
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
from ..scope import (
    REPORT_WORKFLOW_ENTRYPOINT_DEPENDENCY,
    REPORT_WORKFLOW_ENTRYPOINT_STATE_KEY,
    ReportingWorkflowScope,
    reporting_scope_keys,
    resolve_reporting_workflow_scope,
)
from ..state import ReportingCommand, ReportingStateError
from ..state import ReportingPhase as DurableReportingPhase
from .analysis_item_workflow import (
    AnalysisEvidenceDecision,
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

logger = loguru_logger

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
REPORT_PLANNER_REQUEST_METRICS_STATE_KEY = "planner_request_metrics"
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

# 确定性 infra 缺陷（工作区适配缺少协议能力）重试不可修复；章节 fresh attempt
# 循环必须在记账后立即上抛，避免整段 planner + Coding 反复重放。只收录该类
# 缺陷的显式错误码，不把其他 fatal 策略码一并引入循环行为变化。
_VISUALIZATION_FATAL_ERROR_CODES = frozenset({"report_workspace_capability_missing"})


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


_ANALYSIS_CODE_EXISTING_FACTS_INSTRUCTION = (
    "existingFacts 是当前分析项已确认的紧凑事实和对账基准；直接复用，不重复计算已确定总量，"
    "也不得把业务对账差异强行改成相等。"
)

_ANALYSIS_CODE_COMMON_INSTRUCTIONS = (
    "脚本只能读取 datasets 中签发的 CSV path，并只写入输入给定的 evidencePath。",
    "使用单向线性数据流；所有后续读取的局部变量必须在进入条件分支前初始化，并确保每个分支都赋值。",
    "每个 CSV 只能使用同一 datasets[] 项声明的 columns；不得改用 currentAnalysis.fields、其他 Dataset 字段或为了验证假设读取未签发数据。",
    "evidencePath 的 JSON 结构、null、行编码和对账语义以 outputContract 为准；analysisId 和 datasetIds 由固定 Workflow 注入，脚本不得输出。",
    "构成分析必须计算分项合计与总量差异，对账成功才把 passed 写为 true；不得猜测、补齐或替换缺失值。",
    "脚本不得访问网络、环境变量、数据库、工作区其他路径或启动子进程。",
    "readReceipt 存在时只修复该受信脚本，不改变原始事实缺口或签发路径。",
    "diagnostic 是服务端结构化失败事实；必须逐项读取 code、message 和 details.path，修正导致执行或 evidence 校验失败的代码。",
)

_ANALYSIS_CODE_LEGACY_INSTRUCTIONS = (
    "首轮 write_script 直接实现 evidenceDecision.missingFacts 中所有可计算缺口，输出对应 findings 和对账；currentAnalysis.actions 仅作背景。不得先写探索占位脚本或用行数、字段概览代替待计算的业务事实。",
    "同比按当前任务的时间粒度和比较窗口对齐可比期间；仅月度同比按 month（1-12）对齐，不把跨年 YYYYMM/日期整数直接求交集；其他粒度不得降为月份。缺失期间在 warnings 说明。某维度只出现在一侧时另一侧指标、占比和同比值写 JSON null，并在 warnings 说明，不得按 0 补齐。",
    "字段、维度、时间字段和指标必须从当前 missingFacts、datasets.columns 及 outputContract 推导；不得假定收入主题、固定字段名或固定维度。",
    "签发数据无法提供的缺失期间或字段如实写入 warnings；继续完成可计算缺口，不推算缺失数据，不设计额外数据获取或通用兼容框架。",
    _ANALYSIS_CODE_EXISTING_FACTS_INSTRUCTION,
    *_ANALYSIS_CODE_COMMON_INSTRUCTIONS,
)

_ANALYSIS_CODE_INSTRUCTIONS = (
    "只针对 codingRequirements 生成一个最小 Python 脚本；事实缺口已由上游决定，不得重新判断。",
    "逐项使用 codingRequirements 中已签发的 datasetId、fields、calculation 和 outputName；不得重新选择数据集、字段或计算目标。",
    "比较按当前任务声明的时间粒度和窗口对齐；任一维度只出现在一侧时，另一侧指标、占比和变化值写 JSON null，并在 warnings 说明，不得按 0 补齐。",
    _ANALYSIS_CODE_EXISTING_FACTS_INSTRUCTION,
    *_ANALYSIS_CODE_COMMON_INSTRUCTIONS,
)

_ANALYSIS_EVIDENCE_LEGACY_INSTRUCTIONS = (
    "先对照 currentAnalysis 的管理问题与 deterministicFacts，只有缺少回答该问题的必需构成、归因或对比事实时才设置 requiresSupplementalEvidence=true。",
    "只返回 requiresSupplementalEvidence、reason、missingFacts，不得生成 script 或任何代码。",
    "固定事实足够时 missingFacts 必须是空数组，不得为了探索数据而声明缺口。",
)

_ANALYSIS_EVIDENCE_CANDIDATE_INSTRUCTIONS = (
    "先对照 currentAnalysis 的管理问题与 deterministicFacts，只有缺少回答该问题的必需构成、归因或对比事实时才设置 requiresSupplementalEvidence=true。",
    "只返回 requiresSupplementalEvidence、reason、missingFacts、codingRequirements，不得生成 script 或任何代码。",
    "需要补证时，codingRequirements 逐项声明当前授权 datasets 中的 datasetId、fields、calculation 和 outputName；不得编造数据集或字段。",
    "固定事实足够时 missingFacts 和 codingRequirements 必须都是空数组，不得为了探索数据而声明缺口。",
    "同一 datasetId、同一维度粒度的多个指标合并为一个 codingRequirement（一个 outputName，fields 同时列出维度列与全部指标列），"
    "不要按指标逐条拆分；可参考 datasets[].columnProfile 的列角色（dimension/measure/period）与基数选择字段。",
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
        visualization_code_agent_factory: Callable[[Sequence[Any]], Agent] | None = None,
        section_generator: Agent | None = None,
        section_recovery: Agent | None = None,
        vision_reviewer: ReportVisionReviewer | None = None,
        vision_enabled: bool | None = None,
        workspace_service: WorkspaceService | ReportingWorkspaceRouter,
        workspace_registry: ReportingWorkspaceRegistry | None = None,
        code_mode_runtime: Any | None = None,
        knowledge_index: ReportingKnowledgeIndex | None = None,
        lsp_manager: Any | None = None,
        coding_task_registry: ReportingCodingTaskRegistry | None = None,
        registry: ReportSourceRegistryConfig,
        profiles: ReportingProfileRegistry,
        planner_enable_thinking: bool,
        planner_reasoning_effort: str = "high",
        planner_thinking_budget: int = 8192,
        metadata_client: ReportingMetadataClient | None = None,
        download_grants: ReportDownloadGrantService | None = None,
        editor_grants: Any | None = None,
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
        self._analysis_thinking_budget_cap = planner_thinking_budget
        self._vision_enabled = (
            bool(getattr(reporting_agent_template.model, "_report_vision_enabled", True))
            if vision_enabled is None
            else vision_enabled
        )
        self.task_runner = task_runner
        self.visualization_generator = visualization_generator
        self.visualization_code_agent_factory = visualization_code_agent_factory
        self.section_generator = section_generator
        self.section_recovery = section_recovery
        self.vision_reviewer = vision_reviewer
        self.workspace_service = workspace_service
        self.workspace_registry = workspace_registry
        self.code_mode_runtime = code_mode_runtime
        self.knowledge_index = knowledge_index
        self.lsp_manager = lsp_manager
        self.coding_task_registry = coding_task_registry or ReportingCodingTaskRegistry()
        self._host_workspaces: dict[str, HostReportingWorkspace] = {}
        self.registry = registry
        self.profiles = profiles
        self.metadata_client = metadata_client
        self.download_grants = download_grants
        self.editor_grants = editor_grants
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
        if planner_reasoning_effort not in {"low", "high", "max"}:
            raise ValueError("planner_reasoning_effort 必须是 low、high 或 max")
        self._planner_reasoning_effort = planner_reasoning_effort
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
        self._request_normalizer = self._planning_agent(
            reporting_agent_template,
            "report-request-normalizer",
            NormalizedReportPrompt,
            thinking_policy=ThinkingPolicyConfig(
                operation="request_normalization",
                thinking_enabled=planner_enable_thinking,
                configured_budget_cap=planner_thinking_budget,
                reasoning_effort=planner_reasoning_effort,
            ),
            stage_instructions=(
                *HOSPITAL_REQUEST_INSTRUCTIONS,
                "只根据用户完整目标及补充说明的业务语义，同时决策 reportType、domains 和分析期间；不得按关键词机械匹配",
                "reportType 表示分析的组织意图，与 domains 数量相互独立；不得根据领域多少反推报告类型",
                "topic 表示围绕一个聚焦的管理问题、变化机制或专项主题深入分析，即使问题横跨多个领域也仍可返回多个相关 domains",
                "comprehensive 表示从综合经营视角统筹评价多个管理维度，即使用户明确限定了若干领域也仍是 comprehensive；不得因范围有限降级为 topic",
                "comprehensive 未限定范围时 domains 返回全部六域，明确限定范围时只返回语义涉及的领域",
                "医院成本、总成本、科室成本、成本结构或成本趋势优先归入 full_cost；次均费用、药耗、耗材或费用管控归入 cost_control",
                "只有完整语义仍无法判断 reportType、业务领域或唯一期间时才返回 clarificationQuestion",
                "domains 只能使用输入指引中的领域代码，并按语义相关性排序",
                "不得推断或返回数据源、Agent、医院或系统标识",
                "相对日期必须以系统上下文中的当前日期为基准；“去年”表示当前年份减一对应的完整日历年",
                "单个明确日历年份转换为该年1月1日至12月31日",
                "期间缺失、存在多个互相冲突的期间或无法唯一判断时，只返回一个简短且陈述式的 clarificationQuestion",
                "不得改写或返回用户原始报告目标",
            ),
        )
        self._data_understanding_agent = self._planning_agent(
            reporting_agent_template,
            "report-data-understanding-planner",
            DataUnderstandingPlan,
            thinking_policy=ThinkingPolicyConfig(
                operation="data_understanding",
                thinking_enabled=planner_enable_thinking,
                configured_budget_cap=planner_thinking_budget,
                reasoning_effort=planner_reasoning_effort,
            ),
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
            thinking_policy=ThinkingPolicyConfig(
                operation="measure_semantics",
                thinking_enabled=planner_enable_thinking,
                configured_budget_cap=planner_thinking_budget,
                reasoning_effort=planner_reasoning_effort,
            ),
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
            thinking_policy=ThinkingPolicyConfig(
                operation="outline_planning",
                thinking_enabled=planner_enable_thinking,
                configured_budget_cap=planner_thinking_budget,
                reasoning_effort=planner_reasoning_effort,
            ),
            stage_instructions=(
                *HOSPITAL_OUTLINE_INSTRUCTIONS,
                "只返回 reportType、中文报告标题、sections 和 assumptions；sections 每项只能包含 title 和 analysisIds",
                "analysisIds 必须逐字复制 outlineContext.analyses 中已注册的 analysisId，不得生成、截断或改写",
                "章节重点由服务端根据 analysisIds 对应的 managementQuestion 生成，模型不得提交 focus",
                OUTLINE_SECTION_COUNT_INSTRUCTION,
                "section code 由服务端在批准后生成，模型不得提交或猜测 section_NNN",
            ),
        )
        self._analysis_agent = self._planning_agent(
            reporting_agent_template,
            "report-analysis-planner",
            AnalysisBundle,
            thinking_policy=ThinkingPolicyConfig(
                operation="analysis_planning",
                thinking_enabled=planner_enable_thinking,
                configured_budget_cap=planner_thinking_budget,
                reasoning_effort=planner_reasoning_effort,
            ),
            stage_instructions=(
                "一次返回完整分析计划和全部 requirements",
                "根 JSON 必须是对象且只能包含 analyses 和 requirements；不得返回单个 analysis、单个 requirement、裸数组或占位值",
                "每个 analyses 项只回答一个原子管理问题，并且只声明一个主要指标族；复杂问题必须拆成多个分析项",
                "每个 analyses[].domain 必须根据该管理问题的完整业务语义，从请求 domains 中选择唯一值；不得按关键词匹配",
                "managementQuestion 写可直接回答的单一管理问题，primaryMetricFamily 写该项唯一的主要指标族",
                "每个 analyses 项必须同时显式输出 description 和 managementQuestion；二者语义不同，即使内容相近也不得省略",
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
                (
                    "analyses[].description 只描述分析动作、比较方式和所引用 requirement，"
                    "不复述数据覆盖、缺失期间、时间进度、事实结论或『不外推/不估算/不补齐』等系统限制"
                ),
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
        # Coding 首轮需要上游签发的动态计算要求，避免模型再次从 missingFacts 规划字段和算法。
        self._analysis_evidence_agent = self._planning_agent(
            reporting_agent_template,
            "report-analysis-evidence-planner",
            AnalysisEvidenceDecision,
            thinking_policy=ThinkingPolicyConfig(
                operation="analysis_evidence",
                thinking_enabled=planner_enable_thinking,
                configured_budget_cap=planner_thinking_budget,
                reasoning_effort=planner_reasoning_effort,
            ),
            stage_instructions=_ANALYSIS_EVIDENCE_CANDIDATE_INSTRUCTIONS,
        )
        from ...agent import create_reporting_code_agent_factory

        if not isinstance(reporting_agent_template.model, OpenAIChat):
            raise TypeError("Report analysis code agent requires OpenAIChat")
        analysis_code_model = copy(reporting_agent_template.model)
        if not planner_enable_thinking:
            apply_reporting_thinking_profile(analysis_code_model, planner_off)
        analysis_code_model.top_p = 1.0
        analysis_code_model.retries = 0
        analysis_code_model.exponential_backoff = False
        analysis_code_model.__dict__.pop("_report_escalation_thinking_profile", None)
        analysis_code_model.__dict__.pop("_report_thinking_escalation_fields", None)
        self._analysis_script_agent_factory = create_reporting_code_agent_factory(
            model=analysis_code_model,
            name="report-analysis-script-writer",
            task_kind="analysis",
            role="只根据签发事实缺口生成或修复补证 Python 脚本。",
            instructions=_ANALYSIS_CODE_INSTRUCTIONS,
        )
        self._analysis_summary_agent = self._planning_agent(
            reporting_agent_template,
            "report-analysis-summary-writer",
            AnalysisSummaryDraft,
            thinking_policy=ThinkingPolicyConfig(
                operation="analysis_summary",
                thinking_enabled=planner_enable_thinking,
                configured_budget_cap=planner_thinking_budget,
                reasoning_effort=planner_reasoning_effort,
            ),
            stage_instructions=(
                "只回答 currentAnalysis 的原子管理问题，所有数字和结论必须来自 deterministicFacts 或 supplementalEvidence。",
                "优先给出结论、关键数值、构成或变化驱动，再说明可比性和数据限制；不得输出分析过程或虚构因果。",
                "supplementalEvidence.findings[].view.truncated 为 true 时 rows 只是投影视图，不得当作完整明细；format=ranked_extremes 表示变化指标正负两端极值，format=head_tail 表示原始顺序首尾。",
                "omittedNumericSums 只汇总未进入 rows 的有限数值，不是全量总值。",
                "完整总量等于 rows 数值与 omittedNumericSums 之和；原始行数以 view.rowCount 为准，完整文件身份以 sourceFile 为准。",
                "supplementalEvidence 为 null 且 evidenceWarnings 声明补证已放弃时，只能使用 deterministicFacts；不得声称缺失事实已经验证。",
                "summary 使用可直接进入报告的中文业务表述，不使用 Markdown 标题；warnings 只保留会影响结论解释的事实限制。",
            ),
        )
        self._sql_agent = self._planning_agent(
            reporting_agent_template,
            "report-sql-planner",
            GeneratedQueryBatch,
            thinking_policy=ThinkingPolicyConfig(
                operation="sql_planning",
                thinking_enabled=planner_enable_thinking,
                configured_budget_cap=planner_thinking_budget,
                reasoning_effort=planner_reasoning_effort,
            ),
            stage_instructions=(
                "一次返回覆盖全部 requirements 的 SQL 批次",
                "每项只生成一条 SELECT 或只读 CTE",
                "每个 requirement 对 periodWindows 中每个唯一 queryWindowId 生成一条查询，并提交对应 periodRole",
                "每张表只使用该 periodRole 的完整精确期间并按共同粒度预聚合",
                "每个查询块的非聚合 SELECT 列和 GROUP BY 列必须逐项等于 grainColumns；只能额外 SELECT 聚合后的 measureColumns，不得把 dimensionColumns 全量带入",
                "多表 requirement 必须为每张表建立独立聚合 CTE，再按完整 relations.joinColumns 连接 CTE；禁止直接连接基础表",
                '目标数据库是 StarRocks；字段和表标识符使用反引号或裸名称，禁止使用双引号包裹标识符（例如 t."column"）；字符串值仍使用单引号',
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
        thinking_policy: ThinkingPolicyConfig,
        stage_instructions: tuple[str, ...] = (),
    ) -> Agent:
        if not isinstance(planner.model, OpenAIChat):
            raise TypeError("Report planner requires OpenAIChat")
        planner_model = copy(planner.model)
        apply_reporting_thinking_profile(planner_model, ReportingThinkingProfile.off())
        planner_model.top_p = 1.0
        planner_model.retries = 0
        planner_model.exponential_backoff = False
        planner_model.__dict__.pop("_report_escalation_thinking_profile", None)
        planner_model.__dict__.pop("_report_thinking_escalation_fields", None)

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
        agent = planner.deep_copy(
            update={
                "id": agent_id,
                # ID 供状态恢复、日志关联和代码判断；name 只负责面向用户的 Trace 展示。
                "name": _PLANNER_DISPLAY_NAMES.get(agent_id, agent_id),
                "role": "只根据已批准的结构、术语和画像生成结构化报表规划。",
                "model": planner_model,
                # 结构化执行器负责携带校验事实的有界重试，Agent 不再对相同输入盲重试。
                "retries": 0,
                "exponential_backoff": False,
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
        setattr(agent, "_reporting_thinking", thinking_policy)
        return agent

    @staticmethod
    def _benchmark_planning_agent(
        planner: Agent,
        spec: BenchmarkPlannerSpec,
        *,
        thinking_policy: ThinkingPolicyConfig,
    ) -> Agent:
        """按冻结 benchmark spec 在首次请求前创建 planner 副本。"""

        return _ReportWorkflowRuntimeBase._planning_agent(
            planner,
            f"benchmark-{spec.task_kind}-{spec.variant.value}-planner",
            spec.output_schema,
            thinking_policy=thinking_policy,
            stage_instructions=spec.instructions,
        )

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
                        "report_publication_blocked issue_codes={} issue_count={}",
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
            published["reportTitle"] = content["reportTitle"]
            published["publicationGate"] = content.get("publicationGate")
            return StepOutput(content=published)

        return create_reporting_workflow(
            db=self.db,
            lifecycle=self,
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
            assemble_report=self.assemble_report,
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
        thinking_complexity: TaskComplexity = "standard",
        failure_kind: ThinkingFailureKind | None = None,
        attempt: int = 0,
        model_metrics_recorder: Callable[[Any, int], None] | None = None,
    ) -> BaseModel:
        thinking_policy = getattr(agent, "_reporting_thinking", None)
        if not isinstance(thinking_policy, ThinkingPolicyConfig):
            raise ReportingError(
                "report_thinking_policy_missing",
                f"报表规划器缺少调用级 thinking 策略（{agent.id}）。",
            )
        thinking_request = ThinkingRequest(
            operation=thinking_policy.operation,
            complexity=thinking_complexity,
            attempt=min(attempt, 1),
            failure_kind=failure_kind,
            configured_budget_cap=thinking_policy.configured_budget_cap,
            thinking_enabled=thinking_policy.thinking_enabled,
            reasoning_effort=thinking_policy.reasoning_effort,
        )
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
        planner_recorder = PlannerRequestRecorder(
            planner_id=str(getattr(agent, "id", "unknown")),
            model_id=str(getattr(getattr(agent, "model", None), "id", "unknown")),
            sink=self._state(run_context).setdefault(REPORT_PLANNER_REQUEST_METRICS_STATE_KEY, []),
        )
        loguru_logger.bind(
            reporting_progress="planner",
            planner_id=planner_recorder.planner_id,
            model_id=planner_recorder.model_id,
            status="started",
        ).info(
            "report_planner_started planner_id={} model_id={}",
            planner_recorder.planner_id,
            planner_recorder.model_id,
        )
        recorder_token = bind_planner_request_recorder(planner_recorder)
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
                thinking_request=thinking_request,
            )
        except TaskExecutionContextHardLimitError as error:
            hard_limit_metrics = error.metrics
            raise ReportingError(
                "report_planner_context_budget_exceeded",
                f"报表规划输入的不可约简上下文超过当前模型输入预算（{agent.id}）。",
                details=dict(hard_limit_metrics),
            ) from error
        except ReportingError:
            raise
        finally:
            reset_planner_request_recorder(recorder_token)
            loguru_logger.bind(
                reporting_progress="planner",
                planner_id=planner_recorder.planner_id,
                model_id=planner_recorder.model_id,
                provider_request_count=len(planner_recorder.requests),
            ).info(
                "report_planner_observation_saved planner_id={} model_id={} provider_request_count={}",
                planner_recorder.planner_id,
                planner_recorder.model_id,
                len(planner_recorder.requests),
            )
        output = structured.run_output
        content = structured.content
        metrics = getattr(output, "metrics", None)
        if model_metrics_recorder is not None:
            model_metrics_recorder(output, structured.model_request_count)
        else:
            record_step_model_metrics(metrics, structured.model_request_count)
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
                thread_id=scope["callerThreadId"],
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
                        thread_id=scope["callerThreadId"],
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
        stored = state.get(REPORT_WORKFLOW_SCOPE_STATE_KEY)
        scope = resolve_reporting_workflow_scope(
            run_id=str(run_context.run_id or ""),
            session_id=str(run_context.session_id or ""),
            user_id=str(run_context.user_id or "") or None,
            dependencies=(
                dict(run_context.dependencies)
                if isinstance(run_context.dependencies, Mapping)
                else None
            ),
            stored_scope=stored if isinstance(stored, dict) and "sessionId" in stored else None,
        ).as_state()
        state[REPORT_WORKFLOW_SCOPE_STATE_KEY] = scope
        return scope

    def _workspace_for_scope(
        self, scope: ReportingWorkflowScope
    ) -> HostReportingWorkspace:
        if getattr(self, "workspace_registry", None) is None:
            raise ReportingError(
                "report_host_workspace_missing",
                "Reporting Workspace 注册表未配置。",
            )
        workspaces = getattr(self, "_host_workspaces", None)
        if workspaces is None:
            workspaces = {}
            self._host_workspaces = workspaces
        workspace = workspaces.get(scope.workspace_key)
        if workspace is None:
            workspace = HostReportingWorkspace(self.workspace_registry.resolve(scope))
            workspaces[scope.workspace_key] = workspace
        return workspace

    def workspace_for(
        self,
        *,
        run_id: str,
        session_id: str,
        user_id: str | None,
        dependencies: dict[str, Any] | None,
        stored_scope: dict[str, Any] | None = None,
    ) -> HostReportingWorkspace:
        scope = resolve_reporting_workflow_scope(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            dependencies=dependencies,
            stored_scope=stored_scope,
        )
        return self._workspace_for_scope(scope)

    def prepare_run(
        self,
        *,
        run_id: str,
        session_id: str,
        user_id: str | None,
        dependencies: dict[str, Any] | None,
    ) -> dict[str, Any]:
        scope = resolve_reporting_workflow_scope(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            dependencies=dependencies,
        )
        entrypoint = str(
            (dependencies or {}).get(REPORT_WORKFLOW_ENTRYPOINT_DEPENDENCY) or "agentos"
        )
        if entrypoint not in {"agentos", "cli", "mcp"}:
            raise ReportingError("report_workflow_context_invalid", "Reporting Workflow 入口无效。")
        if getattr(self, "workspace_registry", None) is not None:
            self._workspace_for_scope(scope)
        return {
            REPORT_WORKFLOW_SCOPE_STATE_KEY: scope.as_state(),
            REPORT_WORKFLOW_ENTRYPOINT_STATE_KEY: entrypoint,
        }

    async def start_run(self, run_id: str, session_state: dict[str, Any]) -> None:
        value = session_state.get(REPORT_WORKFLOW_SCOPE_STATE_KEY)
        if not isinstance(value, dict):
            raise ReportingError("report_workflow_context_missing", "报表工作流作用域不完整。")
        scope = resolve_reporting_workflow_scope(
            run_id=run_id,
            session_id=str(value.get("sessionId") or ""),
            user_id=str(value.get("userId") or "") or None,
            stored_scope=value,
        )
        entrypoint = str(session_state.get(REPORT_WORKFLOW_ENTRYPOINT_STATE_KEY) or "")
        if entrypoint not in {"agentos", "cli", "mcp"}:
            raise ReportingError("report_workflow_context_invalid", "Reporting Workflow 入口无效。")
        if getattr(self, "workspace_registry", None) is not None:
            self._workspace_for_scope(scope)
        has_external_caller = (
            scope.external_run_id != run_id or scope.caller_thread_id != scope.session_id
        )
        await self.state_repository.register_run(
            report_run_id=run_id,
            external_run_id=scope.external_run_id,
            entrypoint=entrypoint,
            workflow_id="enterprise-reporting-workflow-v1",
            agno_session_id=scope.session_id,
            agno_run_id=run_id,
            caller_session_id=(
                scope.caller_thread_id if entrypoint == "cli" or has_external_caller else None
            ),
            caller_run_id=(
                scope.external_run_id if entrypoint == "cli" or has_external_caller else None
            ),
            thread_id=scope.caller_thread_id,
            owner_user_id=scope.user_id,
            database=scope.database,
            company_id=scope.company_id,
            status="running",
        )
        claimed = await self.state_repository.claim_workflow_thread(
            thread_id=scope.thread_lease_key,
            external_run_id=scope.external_run_id,
            owner_user_id=scope.user_id,
        )
        if not claimed:
            await self.state_repository.update_run_status(run_id, status="failed")
            raise ReportingError(
                "report_workflow_thread_busy",
                "当前 thread 已有进行中的报表工作流，请等待其结束。",
            )

    async def assert_resumable(self, run_id: str) -> None:
        run = await self.state_repository.get_run(run_id)
        if run is None or str(run.get("status")) != "paused":
            raise ReportingError("report_workflow_not_paused", "Reporting Workflow 不处于暂停状态。")
        keys = reporting_scope_keys(
            database=str(run["database"]),
            company_id=str(run["company_id"]),
            user_id=str(run["owner_user_id"]),
            thread_id=str(run["thread_id"]),
            run_id=run_id,
        )
        owner = await self.state_repository.get_workflow_thread_owner(keys.thread_lease_key)
        if owner is None or owner["external_run_id"] != run["external_run_id"]:
            raise ReportingError("report_workflow_scope_mismatch", "Reporting Workflow 不再拥有当前 thread。")

    async def settle_run(self, run_id: str, status: str) -> None:
        if status not in {"completed", "cancelled", "failed", "paused"}:
            raise ValueError(f"未知 Reporting Workflow 状态：{status}")
        if status == "paused":
            await self.state_repository.update_run_status(run_id, status="paused")
            return
        run = await self.state_repository.get_run(run_id)
        if run is None:
            raise ReportingError("report_run_not_found", "Reporting run 不存在。")
        await self.state_repository.update_run_status(
            run_id,
            status=status,
            finalization_pending=True,
        )
        keys = reporting_scope_keys(
            database=str(run["database"]),
            company_id=str(run["company_id"]),
            user_id=str(run["owner_user_id"]),
            thread_id=str(run["thread_id"]),
            run_id=run_id,
        )
        async with self.state_repository.workflow_thread_lifecycle_lock(
            keys.thread_lease_key
        ):
            try:
                await self.cleanup_terminal(
                    {"thread_id": keys.workspace_key},
                    str(run["agno_session_id"]),
                    run_id,
                )
            except ReportingError as error:
                if error.code != "report_sandbox_cleanup_failed":
                    raise
                loguru_logger.warning(
                    "report_workflow_workspace_cleanup_deferred run_id={} workspace_key={}",
                    run_id,
                    keys.workspace_key,
                )
            released = await self.state_repository.release_workflow_thread(
                thread_id=keys.thread_lease_key,
                external_run_id=str(run["external_run_id"]),
                owner_user_id=str(run["owner_user_id"]),
            )
            if not released:
                raise ReportingError(
                    "report_workflow_scope_mismatch",
                    "Reporting Workflow thread owner 释放失败。",
                )
        await self.state_repository.update_run_status(
            run_id,
            status=status,
            finalization_pending=False,
        )

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
            "jobId": content.get("jobId"),
            "editorJob": content.get("editorJob"),
            "markdownPath": content.get("markdownPath"),
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
            or not isinstance(values["jobId"], str)
            or not isinstance(values["editorJob"], dict)
            or values["editorJob"].get("jobId") != values["jobId"]
            or not isinstance(values["markdownPath"], str)
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
                "报表来源告警或 Reporting 回执无效。",
            ) from error
        return values

    @staticmethod
    def _require_artifact_identity(
        expected: dict[str, Any],
        current: dict[str, Any],
        *,
        artifact: Literal["pdf", "word"],
    ) -> None:
        prefix = artifact
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
