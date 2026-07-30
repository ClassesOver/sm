from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from copy import copy
from difflib import SequenceMatcher
from typing import Any, Literal

import anyio
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.workflow.types import StepInput, StepOutput
from openai import APITimeoutError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ...workspace import WorkspaceService
from .. import CodingScope, CodingTaskSupervisor, TaskState
from .acceptance import (
    REPORT_ARTIFACT_VALIDATOR_ID,
    build_report_artifact_acceptance_contract,
)
from .artifacts_v1 import (
    ArtifactFile,
    PdfArtifactManifest,
    ReportArtifactManifest,
    dataset_snapshot_hash,
    validate_rendered_artifacts,
)
from .contract import (
    ModelColumn,
    ModelTable,
    ModelTermsResponse,
    ReportRequestEnvelope,
    SourceSchemaSnapshot,
    parse_ddl,
)
from .data_source import (
    CatalogColumn,
    CatalogTable,
    DataShape,
    ReportSourceRegistryConfig,
    StarRocksDataSourceAdapter,
    StarRocksSourceConfig,
    collect_data_shape,
    require_sources,
)
from .data_sources import ReportDatasetStore
from .entrypoints import current_server_identity
from .metadata import ReportingMetadataClient, select_reporting_agent
from .models import ReportingError
from .profile import (
    CapabilitySet,
    EffectiveReportingProfile,
    ReconciliationShape,
    ReportingProfileRegistry,
    build_outline_shape_view,
    resolve_reporting_profile,
)
from .profile import (
    resolve_capabilities as resolve_profile_capabilities,
)
from .publishing import (
    ReportDownloadGrantService,
    ReportDownloadScope,
    cli_result,
    publication_result,
)
from .workflow import create_reporting_workflow
from .workflow_v1 import (
    ApprovedQuery,
    DatasetLineage,
    QueryRequirement,
    approve_query_batch,
    coding_task_key,
    resolve_schema_snapshot,
    state_contains_connection_data,
)
from .workspace import WorkspaceReportToolkit

logger = logging.getLogger(__name__)

REPORT_WORKFLOW_INPUT_STATE_KEY = "report_workflow_input"
REPORT_WORKFLOW_SCOPE_STATE_KEY = "report_workflow_scope"
REPORT_SCHEMA_SNAPSHOTS_STATE_KEY = "report_schema_snapshots"
REPORT_DATA_UNDERSTANDING_STATE_KEY = "report_data_understanding"
REPORT_DATA_SHAPES_STATE_KEY = "report_data_shapes"
REPORT_EFFECTIVE_PROFILE_STATE_KEY = "report_effective_profile"
REPORT_CAPABILITIES_STATE_KEY = "report_capabilities"
REPORT_RECONCILIATIONS_STATE_KEY = "report_reconciliations"
REPORT_OUTLINE_CONTEXT_STATE_KEY = "report_outline_context"
REPORT_OUTLINE_STATE_KEY = "report_outline"
REPORT_ANALYSIS_PLAN_STATE_KEY = "report_analysis_plan"
REPORT_DATA_REQUIREMENTS_STATE_KEY = "report_data_requirements"
REPORT_APPROVED_QUERIES_STATE_KEY = "report_approved_queries"
REPORT_DATASET_LINEAGE_STATE_KEY = "report_dataset_lineage"
REPORT_WORKFLOW_RESULT_STATE_KEY = "report_workflow_result"
REPORT_ARTIFACTS_STATE_KEY = "report_artifacts"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


_SERIALIZED_MEMBER_PATTERN = re.compile(
    r'(?:"?)[A-Za-z_][A-Za-z0-9_.-]*"?\s*:\s*(?:true|false|null|"|\{|\[|-?\d)',
    re.IGNORECASE,
)
_JSON_FENCE_PATTERN = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
_SNAKE_CASE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+$")
_LEADING_PUNCTUATION_PREFIX_PATTERN = re.compile(r"^[^\w\s]+\s+")
_MISSING_DATA_PATTERN = re.compile(
    r"(?:缺失|缺少|缺口|未提供|不可用|空缺|missing|unavailable|null)",
    re.IGNORECASE,
)
_MISSING_DATA_FABRICATION_PATTERN = re.compile(
    r"(?:估算|估计|推算|插值|外推|填补|补齐|视为(?:未发生|零|0)|"
    r"imput(?:e|ed|ation)|interpolat\w*|extrapolat\w*|estimat\w*)",
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


def _looks_like_serialized_structure(value: str) -> bool:
    normalized = value.strip().replace('\\"', '"')
    try:
        parsed = json.loads(normalized)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, (dict, list)):
        return True
    return bool(_SERIALIZED_MEMBER_PATTERN.search(normalized))


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


def _validate_natural_language_items(value: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    if any(not any(character.isalnum() for character in item) for item in value):
        raise ValueError(f"{label}每项必须包含有效文字或数字，不得只包含标点或空白")
    if any(_SNAKE_CASE_IDENTIFIER_PATTERN.fullmatch(item.strip()) for item in value):
        raise ValueError(f"{label}必须是可直接展示的自然语言，不得使用 snake_case 配置标识")
    if any(_LEADING_PUNCTUATION_PREFIX_PATTERN.match(item.strip()) for item in value):
        raise ValueError(f"{label}不得以孤立标点和空白开头")
    normalized = tuple(item.strip().casefold() for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{label}不得重复")
    if any(_looks_like_serialized_structure(item) for item in value):
        raise ValueError(f"{label}必须是自然语言，不得包含 JSON 或配置序列化片段")
    return value


def _contains_missing_data_fabrication(value: str) -> bool:
    if not _MISSING_DATA_PATTERN.search(value):
        return False
    for match in _MISSING_DATA_FABRICATION_PATTERN.finditer(value):
        if not _FABRICATION_NEGATION_PATTERN.search(value[: match.start()]):
            return True
    return False


def _coding_observed_data_facts(data_shapes: tuple[DataShape, ...]) -> list[dict[str, Any]]:
    return [
        {
            "sourceId": table.source_id,
            "table": f"{table.database}.{table.table}",
            "periodGranularity": table.period_granularity,
            "firstEffectiveDate": table.first_effective_date,
            "lastEffectiveDate": table.last_effective_date,
            "periodCoverage": list(table.period_coverage),
            "missingPeriods": list(table.missing_periods),
            "periodRowCount": table.period_row_count,
        }
        for shape in data_shapes
        for table in shape.tables
    ]


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


class ReportOutline(_StrictModel):
    title: str = Field(
        min_length=1,
        max_length=300,
        description="自然语言报告标题，不得包含 JSON、页面布局或配置序列化内容。",
    )
    sections: tuple[str, ...] = Field(
        min_length=1,
        max_length=30,
        description=(
            "按报告阅读顺序排列的自然语言章节标题；每项只能是一个章节标题，"
            "必须包含有效文字或数字且不得重复；不得包含 JSON、键值配置、页面布局、"
            "模板、snake_case 配置标识或转义后的序列化片段。"
        ),
    )
    assumptions: tuple[str, ...] = Field(
        default=(),
        max_length=30,
        description=(
            "报告成立所需的自然语言假设；每项必须包含有效文字或数字且不得重复；"
            "不得使用 snake_case 配置标识；不得填补、估算、插值或外推缺失数据，"
            "缺失数据只能如实披露为限制；没有假设时返回空数组。"
        ),
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not any(character.isalnum() for character in value):
            raise ValueError("报告标题必须包含有效文字或数字，不得只包含标点或空白")
        if _looks_like_serialized_structure(value):
            raise ValueError("报告标题必须是自然语言，不得包含 JSON 或配置序列化片段")
        return value

    @field_validator("sections")
    @classmethod
    def validate_sections(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_natural_language_items(value, label="章节标题")

    @field_validator("assumptions")
    @classmethod
    def validate_assumptions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        validated = _validate_natural_language_items(value, label="报告假设")
        if any(_contains_missing_data_fabrication(item) for item in validated):
            raise ValueError("报告假设不得填补、估算、插值或外推缺失数据，只能如实披露限制")
        return validated


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


class AnalysisItem(_StrictModel):
    code: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2_000)
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


class AnalysisBundle(_StrictModel):
    analyses: tuple[AnalysisItem, ...] = Field(min_length=1, max_length=100)
    requirements: tuple[QueryRequirement, ...] = Field(min_length=1, max_length=100)


class GeneratedQuery(_StrictModel):
    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    source_id: str = Field(alias="sourceId", min_length=1, max_length=64)
    sql: str = Field(min_length=1, max_length=262_144)


class GeneratedQueryBatch(_StrictModel):
    queries: tuple[GeneratedQuery, ...] = Field(min_length=1, max_length=100)


class _PlannerOutputValidationError(ReportingError):
    def __init__(self, output: Any, issues: list[dict[str, Any]]):
        super().__init__("report_planner_invalid", "报表规划器返回无效结构。")
        self.output = output
        self.issues = issues


class ReportWorkflowRuntime:
    """v1 报表运行时；数据库连接只存在于服务端 adapter 内。"""

    def __init__(
        self,
        *,
        db: Any,
        planner: Agent,
        report_worker: Agent,
        supervisor: CodingTaskSupervisor,
        workspace_service: WorkspaceService,
        registry: ReportSourceRegistryConfig,
        profiles: ReportingProfileRegistry,
        planner_enable_thinking: bool,
        metadata_client: ReportingMetadataClient | None = None,
        download_grants: ReportDownloadGrantService | None = None,
    ):
        self.db = db
        self.report_worker = report_worker
        self.supervisor = supervisor
        self.workspace_service = workspace_service
        self.registry = registry
        self.profiles = profiles
        self.metadata_client = metadata_client
        self.download_grants = download_grants
        self.datasets = ReportDatasetStore(workspace_service)
        self.report_tools = WorkspaceReportToolkit(workspace_service, data_sources=self.datasets)
        self._data_understanding_agent = self._planning_agent(
            planner,
            "report-data-understanding-planner",
            DataUnderstandingPlan,
            enable_thinking=planner_enable_thinking,
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
            ),
        )
        self._outline_agent = self._planning_agent(
            planner,
            "report-outline-planner",
            ReportOutline,
            enable_thinking=planner_enable_thinking,
        )
        self._analysis_agent = self._planning_agent(
            planner,
            "report-analysis-planner",
            AnalysisBundle,
            enable_thinking=planner_enable_thinking,
            stage_instructions=(
                "一次返回完整分析计划和全部 requirements",
                "每项 requirement 显式声明维度、指标、期间字段、期间粒度、共同粒度和表关系",
                "grainColumns 必须全部包含在 dimensionColumns 中",
                "measureColumns 只能包含 Schema 中可聚合的数值指标，分类字段放入 dimensionColumns",
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
            ),
        )
        self._sql_agent = self._planning_agent(
            planner,
            "report-sql-planner",
            GeneratedQueryBatch,
            enable_thinking=planner_enable_thinking,
            stage_instructions=(
                "一次返回覆盖全部 requirements 的 SQL 批次",
                "每项只生成一条 SELECT 或只读 CTE",
                "每张表使用完整精确期间并按共同粒度预聚合",
                "每个查询块的非聚合 SELECT 列和 GROUP BY 列必须逐项等于 grainColumns；只能额外 SELECT 聚合后的 measureColumns，不得把 dimensionColumns 全量带入",
                "多表 requirement 必须为每张表建立独立聚合 CTE，再按完整 relations.joinColumns 连接 CTE；禁止直接连接基础表",
            ),
        )

    @staticmethod
    def _planning_agent(
        planner: Agent,
        agent_id: str,
        output_schema: type[BaseModel],
        *,
        enable_thinking: bool,
        stage_instructions: tuple[str, ...] = (),
    ) -> Agent:
        if not isinstance(planner.model, OpenAIChat):
            raise TypeError("Report planner requires OpenAIChat")
        planner_model = copy(planner.model)
        planner_model.extra_body = {
            **(getattr(planner.model, "extra_body", None) or {}),
            "enable_thinking": enable_thinking,
        }
        planner_model.reasoning_effort = None
        agent = planner.deep_copy(
            update={
                "id": agent_id,
                "name": agent_id,
                "role": "只根据已批准的结构、术语和画像生成结构化报表规划。",
                "model": planner_model,
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
                "parse_response": False,
                "post_hooks": [],
            }
        )
        agent.num_history_runs = None
        return agent

    def workflow(self):
        return create_reporting_workflow(
            db=self.db,
            confirm_source=self.confirm_source,
            plan_data_scope=self.plan_data_scope,
            profile_source=self.profile_source,
            resolve_capabilities=self.resolve_capabilities,
            reconcile_sources=self.reconcile_sources,
            generate_outline=self.generate_outline,
            generate_analysis_plan=self.generate_analysis_plan,
            generate_query_candidates=self.generate_query_candidates,
            materialize_datasets=self.materialize_datasets,
            run_coding_analysis=self.run_coding_analysis,
            validate_report=self.validate_report,
            publish_report=self.publish_report,
        )

    async def cleanup_cancelled(
        self, scope: dict[str, str], _workflow_session_id: str, workflow_run_id: str
    ) -> None:
        task_id = coding_task_key(workflow_run_id)
        task = await self.supervisor.repository.get_task_snapshot(task_id)
        if task is not None and task.state not in {
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }:
            await self.supervisor.cancel_task(task.scope)

    async def issue_http_publication(
        self,
        scope: dict[str, str],
        _workflow_session_id: str,
        workflow_run_id: str,
        output: Any,
    ) -> dict[str, Any]:
        if self.download_grants is None:
            raise ReportingError("report_publication_unavailable", "报表下载授权服务未配置。")
        identity = current_server_identity()
        if identity is None or identity.thread_id != scope["thread_id"]:
            raise ReportingError("report_publication_scope_missing", "报表发布作用域缺失。")
        content = self._publication_content(output)
        current = await self.workspace_service.ahash_file(scope["thread_id"], content["pdfPath"])
        download_scope = ReportDownloadScope(
            database=identity.database,
            user_id=identity.user_id,
            company_id=identity.company_id,
            session_id=identity.session_id,
            thread_id=identity.thread_id,
            workflow_run_id=workflow_run_id,
        )
        raw, grant = await self.download_grants.issue(
            scope=download_scope,
            report_id=content["reportId"],
            revision=content["revision"],
            pdf_path=content["pdfPath"],
            pdf_size=int(current["size"]),
            pdf_sha256=str(current["sha256"]),
        )
        return publication_result(
            report_id=content["reportId"],
            revision=content["revision"],
            raw_grant=raw,
            grant=grant,
        )

    async def issue_cli_publication(
        self,
        scope: dict[str, str],
        _workflow_session_id: str,
        _workflow_run_id: str,
        output: Any,
    ) -> dict[str, Any]:
        content = self._publication_content(output)
        current = await self.workspace_service.ahash_file(scope["thread_id"], content["pdfPath"])
        return cli_result(
            path=content["pdfPath"],
            size=int(current["size"]),
            sha256=str(current["sha256"]),
        )

    async def confirm_source(self, step_input: StepInput, run_context: RunContext) -> StepOutput:
        envelope = ReportRequestEnvelope.from_untrusted(step_input.input)
        source_ids = envelope.source_ids or self.registry.require_defaults()
        configured = require_sources(self.registry.sources, source_ids)
        sources = tuple(self._starrocks_source(item) for item in configured)
        profile = self._resolve_profile(sources)
        metadata = None
        selected_agent = None
        if self.metadata_client is not None:
            agents = await self.metadata_client.query_agents(source_ids)
            selected = select_reporting_agent(
                agents, envelope.agent_id or self._selected_agent_feedback(step_input)
            )
            if isinstance(selected, tuple):
                return StepOutput(
                    content={
                        "agents": [item.model_dump(mode="json", by_alias=True) for item in selected]
                    }
                )
            selected_agent = selected
            if selected_agent is not None:
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
        if selected_agent is not None:
            state[REPORT_WORKFLOW_INPUT_STATE_KEY]["agentId"] = selected_agent.code
        self._assert_state_safe(state)
        return StepOutput(content={"sources": previews})

    async def plan_data_scope(self, _step_input: StepInput, run_context: RunContext) -> StepOutput:
        envelope = self._envelope(run_context)
        snapshots = self._snapshots(run_context)
        base_payload = {
            "reportGoal": envelope.report_goal,
            "period": envelope.period.model_dump(mode="json"),
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
            try:
                output = await self._run_planner(
                    self._data_understanding_agent,
                    payload,
                    run_context,
                )
            except _PlannerOutputValidationError as error:
                output = error.output
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

    async def reconcile_sources(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        state = self._state(run_context)
        state[REPORT_RECONCILIATIONS_STATE_KEY] = []
        self._assert_state_safe(state)
        return StepOutput(content={"reconciliations": []})

    async def generate_outline(self, step_input: StepInput, run_context: RunContext) -> StepOutput:
        state = self._state(run_context)
        outline_context = build_outline_shape_view(
            self._profile(run_context),
            self._capabilities(run_context),
            self._snapshots(run_context),
            self._data_shapes(run_context),
            self._reconciliations(run_context),
        )
        state[REPORT_OUTLINE_CONTEXT_STATE_KEY] = outline_context
        payload = {
            "reportGoal": self._envelope(run_context).report_goal,
            "period": self._envelope(run_context).period.model_dump(mode="json"),
            "outlineContext": outline_context,
            "feedback": self._feedback(step_input),
        }
        base_payload = payload
        validation_feedback: dict[str, Any] | None = None
        outline: ReportOutline | None = None
        for attempt in range(1, 6):
            payload = dict(base_payload)
            if validation_feedback is not None:
                payload["correction"] = {
                    "attempt": attempt,
                    "validationFeedback": _compact_validation_feedback(validation_feedback),
                    "instruction": (
                        "修正所有 issues；返回完整 ReportOutline JSON，"
                        "sections 只能包含可直接展示的自然语言章节标题，assumptions 只能包含"
                        "可直接展示的自然语言假设或空数组；不得返回 snake_case 字段名、默认占位值、"
                        "纯标点、孤立标点前缀或重复项；缺失数据只能如实披露为限制，不得填补、"
                        "估算、插值或外推；直接替换错误值，不把修正说明或标记写入字段；"
                        "不返回章节正文、解释或 Markdown"
                    ),
                }
            try:
                output = await self._run_planner(self._outline_agent, payload, run_context)
            except _PlannerOutputValidationError as error:
                validation_feedback = {
                    "code": "report_outline_invalid",
                    "summary": "报告提纲不符合严格输出契约",
                    "issues": error.issues,
                }
                continue
            assert isinstance(output, ReportOutline)
            outline = output
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
        return StepOutput(content=outline)

    async def generate_analysis_plan(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        state = self._state(run_context)
        snapshots = self._snapshots(run_context)
        data_understanding = DataUnderstandingPlan.model_validate(
            state[REPORT_DATA_UNDERSTANDING_STATE_KEY]
        )
        base_payload = {
            "reportGoal": self._envelope(run_context).report_goal,
            "outline": state[REPORT_OUTLINE_STATE_KEY],
            "analysisContext": _analysis_context_payload(
                state.get(REPORT_OUTLINE_CONTEXT_STATE_KEY)
            ),
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
                payload["correction"] = correction
                logger.info(
                    "report_planner_correction agent_id=%s attempt=%s "
                    "previous_output_sha256=%s allowed_mutation_paths=%s issue_signature=%s",
                    getattr(self._analysis_agent, "id", "report-analysis-planner"),
                    attempt,
                    _payload_sha256(previous_output) if previous_output is not None else "none",
                    json.dumps(allowed_mutation_paths, ensure_ascii=True, separators=(",", ":")),
                    _payload_sha256(_compact_validation_feedback(validation_feedback)),
                )
            try:
                output = await self._run_planner(self._analysis_agent, payload, run_context)
            except _PlannerOutputValidationError as error:
                issues = _analysis_validation_issues(
                    error.issues,
                    error.output,
                    snapshots,
                )
                validation_feedback = {
                    "code": "report_analysis_plan_invalid",
                    "summary": "分析计划不符合严格输出契约",
                    "issues": issues,
                }
                continue
            assert isinstance(output, AnalysisBundle)
            output_payload = output.model_dump(mode="json", by_alias=True)
            if previous_output is not None:
                unexpected_paths = _unexpected_correction_paths(
                    previous_output,
                    output_payload,
                    allowed_mutation_paths,
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
                    continue
            semantic_issues = _analysis_bundle_semantic_issues(
                output,
                self._data_understanding(run_context),
                snapshots,
            )
            if semantic_issues:
                validation_feedback = {
                    "code": "report_analysis_plan_invalid",
                    "summary": "分析计划不可执行或与数据理解计划不一致",
                    "issues": semantic_issues,
                }
                previous_output = output_payload
                allowed_mutation_paths = _analysis_allowed_mutation_paths(semantic_issues)
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
            "feedback": self._feedback(step_input),
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
                        "修正所有 issues；返回覆盖全部 requirements 的完整 SQL 批次 JSON，"
                        "直接替换错误值，不把修正说明或标记写入字段；不返回补丁、解释或 Markdown"
                    ),
                }
            try:
                output = await self._run_planner(self._sql_agent, payload, run_context)
            except _PlannerOutputValidationError as error:
                validation_feedback = {
                    "code": "report_query_batch_invalid",
                    "summary": "SQL 批次不符合严格输出契约",
                    "issues": error.issues,
                }
                continue
            assert isinstance(output, GeneratedQueryBatch)
            approved, issues = _approve_generated_queries(
                output,
                sources=sources,
                snapshots=snapshots,
                envelope=envelope,
                requirements=requirements,
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

    async def run_coding_analysis(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        return StepOutput(content=await self._run_coding(run_context, feedback=None))

    async def _run_coding(self, run_context: RunContext, *, feedback: str | None) -> dict[str, Any]:
        state = self._state(run_context)
        result = self._workflow_result(state)
        revision = int(result.get("revision", 0)) + (1 if feedback else 0)
        scope = self._scope(run_context)
        async with self.workspace_service._async_client() as client:
            sandbox = await self.workspace_service._asandbox_for(client, scope["threadId"])
            sandbox_id = str(getattr(sandbox, "id", "") or "")
        if not sandbox_id or not self.report_worker.id:
            raise ReportingError("report_worker_unavailable", "报表 Coding 工作区不可用。")
        task_id = coding_task_key(str(run_context.run_id or "report"))
        coding_scope = CodingScope(
            task_id,
            scope["userId"],
            scope["threadId"],
            sandbox_id,
            str(self.report_worker.id),
        )
        markdown_path = f"报表/智能分析/{run_context.run_id}/report-revision-{revision + 1}.md"
        manifest_path = (
            f"报表/智能分析/{run_context.run_id}/report-revision-{revision + 1}.manifest.json"
        )
        lineage = tuple(
            DatasetLineage.model_validate(item) for item in state[REPORT_DATASET_LINEAGE_STATE_KEY]
        )
        expected_manifest_identity = {
            "reportId": str(run_context.run_id),
            "revision": revision + 1,
            "codingTaskKey": task_id,
            "datasetSnapshotHash": dataset_snapshot_hash(lineage),
            "effectiveProfileHash": self._profile(run_context).effective_profile_hash,
            "markdownPath": markdown_path,
            "artifactManifestPath": manifest_path,
        }
        acceptance_contract = build_report_artifact_acceptance_contract(expected_manifest_identity)
        instruction = json.dumps(
            {
                "reportGoal": self._envelope(run_context).report_goal,
                "outline": state[REPORT_OUTLINE_STATE_KEY],
                "effectiveProfile": state[REPORT_EFFECTIVE_PROFILE_STATE_KEY],
                "reconciliations": state[REPORT_RECONCILIATIONS_STATE_KEY],
                "analysisPlan": state[REPORT_ANALYSIS_PLAN_STATE_KEY],
                "dataRequirements": state[REPORT_DATA_REQUIREMENTS_STATE_KEY],
                "datasets": result["datasets"],
                "observedDataFacts": _coding_observed_data_facts(self._data_shapes(run_context)),
                "reportId": str(run_context.run_id),
                "codingTaskKey": task_id,
                "datasetSnapshotHash": dataset_snapshot_hash(lineage),
                "effectiveProfileHash": self._profile(run_context).effective_profile_hash,
                "task": "revise" if feedback else "analyze",
                "revision": revision + 1,
                "markdownPath": markdown_path,
                "artifactManifestPath": manifest_path,
                "artifactAcceptance": {
                    "validatorId": REPORT_ARTIFACT_VALIDATOR_ID,
                    "requiredArtifactPaths": [markdown_path, manifest_path],
                    "includeManifestChartPaths": True,
                },
                "reviewFeedback": feedback,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        existing = await self.supervisor.repository.get_task_snapshot(task_id)
        if existing is None:
            await self.supervisor.start_task(
                coding_scope,
                instruction,
                acceptance_contract=acceptance_contract,
            )
        elif feedback:
            await self.supervisor.revise_task(
                coding_scope,
                f"report-revision-{revision + 1}",
                instruction,
                acceptance_contract=acceptance_contract,
            )
        completed = False
        async for event in self.supervisor.run_task(coding_scope):
            if event.type == "terminal":
                completed = event.data.get("state") == "completed"
            elif event.type == "suspended":
                raise ReportingError(
                    str(event.data.get("code") or "report_worker_suspended"),
                    "报表 Coding 分析已暂停。",
                )
        if not completed:
            raise ReportingError("report_worker_failed", "报表 Coding 分析未完成。")
        completed_task = await self.supervisor.repository.get_task_snapshot(task_id)
        finish_receipt = completed_task.finish_receipt if completed_task is not None else None
        accepted_artifacts = (
            finish_receipt.get("artifacts") if isinstance(finish_receipt, dict) else None
        )
        acceptance = finish_receipt.get("acceptance") if isinstance(finish_receipt, dict) else None
        if not isinstance(accepted_artifacts, list) or not isinstance(acceptance, dict):
            raise ReportingError(
                "report_artifact_acceptance_missing",
                "报表 Coding 任务缺少正式产物验收回执。",
            )
        logger.info(
            "report_artifact_acceptance task_id=%s validator_id=%s artifact_count=%s status=passed",
            task_id,
            REPORT_ARTIFACT_VALIDATOR_ID,
            len(accepted_artifacts),
        )
        manifest = await self._load_artifact_manifest(
            manifest_path,
            accepted_artifacts=accepted_artifacts,
            run_context=run_context,
        )
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
        return {"jobId": result["jobId"], "markdownPath": markdown_path}

    async def validate_report(self, _step_input: StepInput, run_context: RunContext) -> StepOutput:
        return StepOutput(content=await self._render_and_validate(run_context))

    async def _render_and_validate(self, run_context: RunContext) -> dict[str, Any]:
        state = self._state(run_context)
        result = self._workflow_result(state)
        revision = int(result.get("revision", 0))
        pdf_path = f"报表/智能分析/{run_context.run_id}/report-revision-{revision + 1}.pdf"
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
        await self.report_tools.report_render_markdown(
            str(result["jobId"]),
            str(result["markdownPath"]),
            pdf_path,
            run_context=context,
        )
        validation = await self.report_tools.report_validate_pdf(
            str(result["jobId"]),
            pdf_path,
            artifact_manifest=draft.model_dump(mode="json", by_alias=True),
            run_context=context,
        )
        if validation.get("ok") is not True:
            raise ReportingError("report_pdf_validation_failed", "PDF 验收未通过。")
        pdf_identity = await self.workspace_service.ahash_file(
            self._scope(run_context)["threadId"], pdf_path
        )
        rendered = PdfArtifactManifest(
            reportId=draft.report_id,
            revision=draft.revision,
            pdf=ArtifactFile(
                path=pdf_path,
                mediaType="application/pdf",
                size=pdf_identity["size"],
                sha256=pdf_identity["sha256"],
            ),
            pageCount=validation.get("pageCount"),
            renderedChartIds=tuple(validation.get("chartIds") or ()),
            citationIds=tuple(validation.get("citationIds") or ()),
            sections=tuple(validation.get("sectionIds") or ()),
        )
        validate_rendered_artifacts(draft, rendered, lineage=lineage)
        result.update({"pdfPath": pdf_path, "validation": validation, "status": "validated"})
        state[REPORT_WORKFLOW_RESULT_STATE_KEY] = result
        state[REPORT_ARTIFACTS_STATE_KEY] = {
            "draft": draft.model_dump(mode="json", by_alias=True),
            "pdf": rendered.model_dump(mode="json", by_alias=True),
        }
        return {
            "status": "validated",
            "jobId": result["jobId"],
            "markdownPath": result["markdownPath"],
            "pdfPath": pdf_path,
            "validation": validation,
        }

    async def publish_report(self, step_input: StepInput, run_context: RunContext) -> StepOutput:
        feedback = self._feedback(step_input)
        if feedback:
            await self._run_coding(run_context, feedback=feedback)
            await self._render_and_validate(run_context)
        result = self._workflow_result(self._state(run_context))
        return StepOutput(
            content={
                "status": "validated",
                "jobId": result["jobId"],
                "reportId": str(run_context.run_id),
                "revision": int(result.get("revision", 0)) + 1,
                "markdownPath": result["markdownPath"],
                "pdfPath": result["pdfPath"],
                "validation": result["validation"],
            }
        )

    async def _load_artifact_manifest(
        self,
        manifest_path: str,
        *,
        accepted_artifacts: list[dict[str, Any]],
        run_context: RunContext,
    ) -> ReportArtifactManifest:
        scope = self._scope(run_context)
        accepted = next(
            (
                item
                for item in accepted_artifacts
                if isinstance(item, dict) and item.get("path") == manifest_path
            ),
            None,
        )
        if not isinstance(accepted, dict):
            raise ReportingError(
                "report_artifact_acceptance_missing",
                "正式产物验收回执缺少 ReportArtifactManifest。",
            )
        _relative, remote = self.workspace_service.normalize_path(manifest_path, allow_root=False)
        try:
            async with self.workspace_service._async_client() as client:
                sandbox = await self.workspace_service._asandbox_for(client, scope["threadId"])
                content = await self.workspace_service._adownload_file(sandbox, remote, 1024 * 1024)
            if len(content) != accepted.get("size") or hashlib.sha256(
                content
            ).hexdigest() != accepted.get("sha256"):
                raise ReportingError(
                    "report_artifact_file_changed",
                    "ReportArtifactManifest 在正式验收后发生变化。",
                )
            manifest = ReportArtifactManifest.model_validate_json(content)
        except ReportingError:
            raise
        except Exception as error:
            raise ReportingError(
                "report_artifact_manifest_invalid", "报告产物清单不存在或格式无效。"
            ) from error
        return manifest

    async def _run_planner(
        self, agent: Agent, payload: dict[str, Any], run_context: RunContext
    ) -> BaseModel:
        scope = self._scope(run_context)
        digest = hashlib.sha256(f"{run_context.run_id}:{agent.id}".encode()).hexdigest()[:32]
        serialized_payload = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), default=str
        )
        input_bytes = serialized_payload.encode()
        input_sha256 = hashlib.sha256(input_bytes).hexdigest()
        logger.info(
            "report_planner_request agent_id=%s input_bytes=%s input_sha256=%s",
            agent.id,
            len(input_bytes),
            input_sha256,
        )
        try:
            output = await agent.arun(
                serialized_payload,
                session_id=f"report-planning-{digest}",
                user_id=scope["userId"],
                stream=False,
            )
        except (APITimeoutError, TimeoutError) as error:
            timeout_seconds = getattr(agent.model, "timeout", None)
            logger.warning(
                "report_planner_timeout agent_id=%s timeout_seconds=%s input_sha256=%s",
                agent.id,
                timeout_seconds,
                input_sha256,
            )
            raise ReportingError(
                "report_planner_timeout",
                f"报表规划模型在 {timeout_seconds} 秒内未响应（{agent.id}）。",
            ) from error
        content = getattr(output, "content", None)
        metrics = getattr(output, "metrics", None)
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
        candidate = _planner_candidate(content)
        try:
            return content if isinstance(content, schema) else schema.model_validate(candidate)
        except ValidationError as error:
            issues = [_planner_validation_issue(item) for item in error.errors(include_url=False)]
            logger.warning(
                "report_planner_validation_failed agent_id=%s output_sha256=%s "
                "issue_count=%s issue_paths=%s",
                agent.id,
                hashlib.sha256(content_bytes).hexdigest(),
                len(issues),
                json.dumps(
                    [issue["path"] for issue in issues],
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
            )
            raise _PlannerOutputValidationError(
                candidate,
                issues,
            ) from error

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

    def _reconciliations(self, run_context: RunContext) -> tuple[ReconciliationShape, ...]:
        try:
            return tuple(
                ReconciliationShape.model_validate(item)
                for item in self._state(run_context)[REPORT_RECONCILIATIONS_STATE_KEY]
            )
        except Exception as error:
            raise ReportingError("report_reconciliation_state_invalid", "对账状态无效。") from error

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
    def _selected_agent_feedback(step_input: StepInput) -> str | None:
        value = ReportWorkflowRuntime._feedback(step_input)
        prefix = "agentId:"
        if value is None or not value.startswith(prefix):
            return None
        agent_id = value[len(prefix) :].strip()
        return agent_id or None

    @staticmethod
    def _state(run_context: RunContext) -> dict[str, Any]:
        if not isinstance(run_context.session_state, dict):
            raise ReportingError("report_workflow_state_invalid", "报表工作流状态无效。")
        return run_context.session_state

    @staticmethod
    def _assert_state_safe(state: dict[str, Any]) -> None:
        if state_contains_connection_data(state):
            raise ReportingError("state_contains_connection_data", "Workflow state 包含连接信息。")

    @staticmethod
    def _scope(run_context: RunContext) -> dict[str, str]:
        state = ReportWorkflowRuntime._state(run_context)
        value = (run_context.dependencies or {}).get("AgentOS 报表工作流")
        if isinstance(value, dict):
            state[REPORT_WORKFLOW_SCOPE_STATE_KEY] = dict(value)
        else:
            value = state.get(REPORT_WORKFLOW_SCOPE_STATE_KEY)
        if not isinstance(value, dict):
            raise ReportingError("report_workflow_context_missing", "报表工作流作用域缺失。")
        scope = {key: str(value.get(key) or "") for key in ("externalRunId", "threadId", "userId")}
        if (
            any(not item for item in scope.values())
            or str(run_context.user_id or "") != scope["userId"]
        ):
            raise ReportingError("report_workflow_context_missing", "报表工作流作用域不完整。")
        return scope

    @staticmethod
    def _workflow_result(state: dict[str, Any]) -> dict[str, Any]:
        value = state.get(REPORT_WORKFLOW_RESULT_STATE_KEY)
        if not isinstance(value, dict):
            raise ReportingError("report_workflow_result_invalid", "报表工作流产物状态无效。")
        return dict(value)

    @staticmethod
    def _publication_content(output: Any) -> dict[str, Any]:
        content = getattr(output, "content", None)
        if not isinstance(content, dict):
            raise ReportingError("report_publication_invalid", "报表发布产物无效。")
        values = {
            "reportId": content.get("reportId"),
            "revision": content.get("revision"),
            "pdfPath": content.get("pdfPath"),
        }
        if (
            not isinstance(values["reportId"], str)
            or not isinstance(values["revision"], int)
            or not isinstance(values["pdfPath"], str)
        ):
            raise ReportingError("report_publication_invalid", "报表发布产物无效。")
        return values

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
            )
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


def _validate_data_understanding(
    plan: DataUnderstandingPlan,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> None:
    validated, _output, feedback = _data_understanding_result(plan, snapshots)
    if validated is None:
        raise ReportingError(
            "report_data_understanding_invalid",
            json.dumps(feedback, ensure_ascii=False, separators=(",", ":"), default=str),
        )


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
) -> list[str]:
    return [
        path
        for path in _json_diff_paths(previous, current)
        if not any(_correction_path_allowed(path, allowed) for allowed in allowed_paths)
    ]


def _correction_path_allowed(path: str, allowed: str) -> bool:
    if "[*]" not in allowed:
        return path == allowed or path.startswith(f"{allowed}.") or path.startswith(f"{allowed}[")
    pattern = re.escape(allowed).replace(r"\[\*\]", r"\[\d+\]")
    return re.match(rf"^{pattern}(?:\.|\[|$)", path) is not None


def _analysis_allowed_mutation_paths(issues: list[dict[str, Any]]) -> tuple[str, ...]:
    if any(
        isinstance(issue.get("path"), str)
        and str(issue["path"]).startswith("requirements[")
        and "拆分为单表" in str(issue.get("requiredAction", ""))
        for issue in issues
    ):
        return ("requirements", "analyses[*].requirementIds")
    return tuple(
        dict.fromkeys(str(issue["path"]) for issue in issues if isinstance(issue.get("path"), str))
    )


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


def _raw_analysis_requirement(raw_output: Any, index: int) -> Mapping[str, Any] | None:
    if not isinstance(raw_output, Mapping):
        return None
    requirements = raw_output.get("requirements")
    if not isinstance(requirements, list) or index < 0 or index >= len(requirements):
        return None
    requirement = requirements[index]
    return requirement if isinstance(requirement, Mapping) else None


def _raw_analysis_table(
    raw_output: Any, requirement_index: int, table_index: int
) -> tuple[str, str, Mapping[str, Any]] | None:
    requirement = _raw_analysis_requirement(raw_output, requirement_index)
    if requirement is None or not isinstance(requirement.get("sourceId"), str):
        return None
    tables = requirement.get("tables")
    if not isinstance(tables, list) or table_index < 0 or table_index >= len(tables):
        return None
    table = tables[table_index]
    if not isinstance(table, Mapping) or not isinstance(table.get("table"), str):
        return None
    return str(requirement["sourceId"]), str(table["table"]), table


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


def _analysis_validation_issues(
    issues: list[dict[str, Any]],
    raw_output: Any,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    requirement_ids = [
        str(item["requirementId"])
        for item in (raw_output.get("requirements", []) if isinstance(raw_output, Mapping) else [])
        if isinstance(item, Mapping) and isinstance(item.get("requirementId"), str)
    ]
    for original in issues:
        issue = dict(original)
        path = str(issue.get("path", ""))
        allowed_values: list[str] = []
        measure_match = re.fullmatch(
            r"requirements\[(\d+)\]\.tables\[(\d+)\]\.measureColumns", path
        )
        field_match = re.fullmatch(r"requirements\[(\d+)\]\.(dimensionColumns|grainColumns)", path)
        if measure_match:
            raw_table = _raw_analysis_table(
                raw_output, int(measure_match.group(1)), int(measure_match.group(2))
            )
            if raw_table is not None:
                source_id, table_name, table = raw_table
                period_column = str(table.get("periodColumn", "")).lower()
                allowed_values = sorted(
                    column.name
                    for column in _analysis_table_columns(source_id, table_name, snapshots)
                    if _NUMERIC_MEASURE_TYPE_PATTERN.match(column.data_type) is not None
                    and column.name.lower() != period_column
                )
                issue["requiredAction"] = (
                    "从 allowedValues 选择必要的可聚合数值字段，每个字段只保留一次"
                )
        elif field_match:
            requirement = _raw_analysis_requirement(raw_output, int(field_match.group(1)))
            if requirement is not None and isinstance(requirement.get("tables"), list):
                column_sets = []
                for index in range(len(requirement["tables"])):
                    raw_table = _raw_analysis_table(raw_output, int(field_match.group(1)), index)
                    if raw_table is None:
                        continue
                    source_id, table_name, _table = raw_table
                    column_sets.append(
                        {
                            column.name
                            for column in _analysis_table_columns(source_id, table_name, snapshots)
                        }
                    )
                if column_sets:
                    available = (
                        set.intersection(*column_sets)
                        if field_match.group(2) == "grainColumns"
                        else set.union(*column_sets)
                    )
                    allowed_values = sorted(available)
                    issue["requiredAction"] = "从 allowedValues 选择必要字段，每个字段只保留一次"
        elif re.fullmatch(r"analyses\[\d+\]\.requirementIds", path):
            allowed_values = sorted(set(requirement_ids))
            issue["requiredAction"] = "只引用 allowedValues 中已有的 requirementId"
        elif re.fullmatch(r"requirements\[\d+\]", path) and (
            "多表 requirement 必须声明 relations" in str(issue.get("reason", ""))
        ):
            issue["requiredAction"] = (
                "优先拆分为单表 requirements，并由 analyses.requirementIds 组合；"
                "只有存在真实共同粒度和关联键时才声明 relations"
            )
        if allowed_values:
            issue["allowedValues"] = allowed_values
            suggested = _suggested_replacement(issue.get("rejectedValue"), allowed_values)
            if suggested is not None:
                issue["suggestedReplacement"] = suggested
        enriched.append(issue)
    return enriched


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


def _planner_validation_issue(error: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": _validation_path(tuple(error.get("loc", ()))),
        "rejectedValue": error.get("input"),
        "reason": str(error.get("msg", "字段不符合严格输出契约")),
        "requiredAction": "根据 reason 修正该字段，并返回完整输出 JSON",
    }


def _approve_generated_queries(
    generated: GeneratedQueryBatch,
    *,
    sources: dict[str, StarRocksSourceConfig],
    snapshots: tuple[SourceSchemaSnapshot, ...],
    envelope: ReportRequestEnvelope,
    requirements: tuple[QueryRequirement, ...],
) -> tuple[tuple[ApprovedQuery, ...], list[dict[str, Any]]]:
    requirements_by_id = {item.requirement_id: item for item in requirements}
    query_ids = [item.requirement_id for item in generated.queries]
    issues: list[dict[str, Any]] = []
    approved: list[ApprovedQuery] = []
    for index, query in enumerate(generated.queries):
        requirement = requirements_by_id.get(query.requirement_id)
        if requirement is None or query_ids.count(query.requirement_id) > 1:
            issues.append(
                {
                    "path": f"queries[{index}].requirementId",
                    "rejectedValue": query.requirement_id,
                    "reason": (
                        "requirementId 不存在于输入 requirements"
                        if requirement is None
                        else "同一 requirementId 只能生成一条 SQL"
                    ),
                    "allowedValues": sorted(requirements_by_id),
                    "requiredAction": "为每个输入 requirementId 返回且只返回一条 SQL",
                }
            )
            continue
        try:
            approved.extend(
                approve_query_batch(
                    [query.model_dump(mode="json", by_alias=True)],
                    sources=sources,
                    snapshots=snapshots,
                    envelope=envelope,
                    requirements=(requirement,),
                )
            )
        except ReportingError as error:
            expected_period_predicates: list[str] | None = None
            if error.code == "report_query_join_grain_invalid":
                required_action = (
                    "按 requirementContract 为每张表建立独立 CTE，逐表使用完整期间条件并按全部 "
                    "grainColumns 聚合，再仅按 relations[].joinColumns 等值连接 CTE；禁止直接连接基础表"
                )
            elif error.code == "report_query_period_invalid":
                expected_period_predicates = _expected_period_predicates(
                    requirement,
                    envelope,
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
            else:
                required_action = "严格按 requirementContract 的 tables、measureColumns、grainColumns 和 relations 修正 SQL"
            issue = {
                "path": f"queries[{index}].sql",
                "rejectedValue": query.sql,
                "reason": f"{error.code}: {error.message}",
                "requirementContract": requirement.model_dump(mode="json", by_alias=True),
                "requiredAction": required_action,
            }
            if expected_period_predicates is not None:
                issue["expectedPeriodPredicates"] = expected_period_predicates
            if error.code == "report_query_grain_invalid":
                issue["expectedGrainColumns"] = list(requirement.grain_columns)
            issues.append(issue)
    missing = sorted(set(requirements_by_id) - set(query_ids))
    if missing:
        issues.append(
            {
                "path": "queries",
                "rejectedValue": missing,
                "reason": "SQL 批次缺少输入 requirementId",
                "allowedValues": sorted(requirements_by_id),
                "requiredAction": "补齐每个缺失 requirementId 对应的完整 SQL",
            }
        )
    return tuple(approved), issues


def _expected_period_predicates(
    requirement: QueryRequirement,
    envelope: ReportRequestEnvelope,
) -> list[str]:
    period = envelope.period
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
        issues.extend(_measure_column_issues(requirement, index, snapshots))
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


def _measure_column_issues(
    requirement: QueryRequirement,
    requirement_index: int,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> list[dict[str, Any]]:
    available_tables = _available_tables(snapshots)
    issues: list[dict[str, Any]] = []
    dimensions = set(requirement.dimension_columns)
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
        invalid = [
            columns[name]
            for name in table.measure_columns
            if name in columns
            and (
                _NUMERIC_MEASURE_TYPE_PATTERN.match(columns[name].data_type) is None
                or name == table.period_column
                or name in dimensions
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
        issues.append(
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
    return issues


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
