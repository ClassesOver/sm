from __future__ import annotations

import hashlib
import json
from typing import Any

import anyio
from agno.agent import Agent
from agno.run import RunContext
from agno.workflow.types import StepInput, StepOutput
from pydantic import BaseModel, ConfigDict, Field

from ...workspace import WorkspaceService
from .. import CodingScope, CodingTaskSupervisor, TaskState
from .artifacts_v1 import (
    ArtifactFile,
    PdfArtifactManifest,
    ReportArtifactManifest,
    dataset_snapshot_hash,
    validate_rendered_artifacts,
)
from .contract import ModelColumn, ModelTable, ReportRequestEnvelope, SourceSchemaSnapshot
from .data_source import (
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

REPORT_WORKFLOW_INPUT_STATE_KEY = "report_workflow_input"
REPORT_SCHEMA_SNAPSHOTS_STATE_KEY = "report_schema_snapshots"
REPORT_DATA_SHAPES_STATE_KEY = "report_data_shapes"
REPORT_OUTLINE_STATE_KEY = "report_outline"
REPORT_ANALYSIS_PLAN_STATE_KEY = "report_analysis_plan"
REPORT_DATA_REQUIREMENTS_STATE_KEY = "report_data_requirements"
REPORT_APPROVED_QUERIES_STATE_KEY = "report_approved_queries"
REPORT_DATASET_LINEAGE_STATE_KEY = "report_dataset_lineage"
REPORT_WORKFLOW_RESULT_STATE_KEY = "report_workflow_result"
REPORT_ARTIFACTS_STATE_KEY = "report_artifacts"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class ReportOutline(_StrictModel):
    title: str = Field(min_length=1, max_length=300)
    sections: tuple[str, ...] = Field(min_length=1, max_length=30)
    assumptions: tuple[str, ...] = Field(default=(), max_length=30)


class AnalysisItem(_StrictModel):
    code: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=2_000)
    requirement_ids: tuple[str, ...] = Field(alias="requirementIds", min_length=1, max_length=100)


class AnalysisBundle(_StrictModel):
    analyses: tuple[AnalysisItem, ...] = Field(min_length=1, max_length=100)
    requirements: tuple[QueryRequirement, ...] = Field(min_length=1, max_length=100)


class GeneratedQuery(_StrictModel):
    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    source_id: str = Field(alias="sourceId", min_length=1, max_length=64)
    sql: str = Field(min_length=1, max_length=262_144)


class GeneratedQueryBatch(_StrictModel):
    queries: tuple[GeneratedQuery, ...] = Field(min_length=1, max_length=100)


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
        metadata_client: ReportingMetadataClient | None = None,
        download_grants: ReportDownloadGrantService | None = None,
    ):
        self.db = db
        self.report_worker = report_worker
        self.supervisor = supervisor
        self.workspace_service = workspace_service
        self.registry = registry
        self.metadata_client = metadata_client
        self.download_grants = download_grants
        self.datasets = ReportDatasetStore(workspace_service)
        self.report_tools = WorkspaceReportToolkit(workspace_service, data_sources=self.datasets)
        self._outline_agent = self._planning_agent(planner, "report-outline-planner", ReportOutline)
        self._analysis_agent = self._planning_agent(
            planner, "report-analysis-planner", AnalysisBundle
        )
        self._sql_agent = self._planning_agent(planner, "report-sql-planner", GeneratedQueryBatch)

    @staticmethod
    def _planning_agent(planner: Agent, agent_id: str, output_schema: type[BaseModel]) -> Agent:
        agent = planner.deep_copy(
            update={
                "id": agent_id,
                "name": agent_id,
                "role": "只根据已批准的结构、术语和画像生成结构化报表规划。",
                "instructions": [
                    "严格返回 output_schema，不得虚构字段、数据或结论。",
                    "不得输出连接信息，不得调用工具，不得执行 SQL。",
                ],
                "tools": [],
                "skills": None,
                "tool_choice": None,
                "output_schema": output_schema,
                "post_hooks": [],
            }
        )
        agent.num_history_runs = None
        return agent

    def workflow(self):
        return create_reporting_workflow(
            db=self.db,
            confirm_source=self.confirm_source,
            profile_source=self.profile_source,
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
        prefix = coding_task_key(workflow_run_id)
        for revision in range(4):
            task_id = prefix if revision == 0 else f"{prefix}-revision-{revision}"
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
                    source_ids=source_ids,
                    expected_revision=selected_agent.model_revision,
                )

        snapshots: list[SourceSchemaSnapshot] = []
        previews: list[dict[str, Any]] = []
        for source in sources:
            adapter = StarRocksDataSourceAdapter(source)
            try:
                await adapter.verify_read_only()
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
                    "allowedTables": list(source.tables),
                    "metadataRevision": snapshot.revision,
                    "schemaHash": snapshot.schema_hash,
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
        if selected_agent is not None:
            state[REPORT_WORKFLOW_INPUT_STATE_KEY]["agentId"] = selected_agent.code
        self._assert_state_safe(state)
        return StepOutput(content={"sources": previews})

    async def profile_source(self, _step_input: StepInput, run_context: RunContext) -> StepOutput:
        envelope = self._envelope(run_context)
        snapshots = self._snapshots(run_context)
        inputs = tuple(zip(envelope.source_ids or (), snapshots, strict=True))
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
            adapter = StarRocksDataSourceAdapter(source)
            try:
                shapes[index] = await collect_data_shape(
                    adapter,
                    period_start=envelope.period.start,
                    period_end=envelope.period.end,
                    period_columns=source.period_columns,
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

    async def generate_outline(self, step_input: StepInput, run_context: RunContext) -> StepOutput:
        payload = {
            "reportGoal": self._envelope(run_context).report_goal,
            "schemas": self._state(run_context)[REPORT_SCHEMA_SNAPSHOTS_STATE_KEY],
            "dataShapes": self._state(run_context)[REPORT_DATA_SHAPES_STATE_KEY],
            "requiredSections": [
                "管理摘要",
                "月度趋势",
                "院区对比",
                "科室排名",
                "预算偏差",
                "收入结构",
                "成本收入比",
                "结余率",
                "工作量效率",
                "异常归因",
                "管理建议",
            ],
            "feedback": self._feedback(step_input),
        }
        outline = await self._run_planner(self._outline_agent, payload, run_context)
        state = self._state(run_context)
        state[REPORT_OUTLINE_STATE_KEY] = outline.model_dump(mode="json", by_alias=True)
        return StepOutput(content=outline)

    async def generate_analysis_plan(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        state = self._state(run_context)
        bundle = await self._run_planner(
            self._analysis_agent,
            {
                "reportGoal": self._envelope(run_context).report_goal,
                "outline": state[REPORT_OUTLINE_STATE_KEY],
                "schemas": state[REPORT_SCHEMA_SNAPSHOTS_STATE_KEY],
                "dataShapes": state[REPORT_DATA_SHAPES_STATE_KEY],
                "rules": [
                    "一次返回完整分析计划和全部 requirements",
                    "每项 requirement 显式声明维度、指标、共同粒度和表关系",
                    "跨表先按月份、院区、一级科室共同粒度聚合再关联",
                    "披露差异、缺失月份、零分母和口径限制，不静默年化",
                ],
            },
            run_context,
        )
        assert isinstance(bundle, AnalysisBundle)
        requirement_ids = {item.requirement_id for item in bundle.requirements}
        if any(set(item.requirement_ids) - requirement_ids for item in bundle.analyses):
            raise ReportingError("report_analysis_plan_invalid", "分析计划引用了未知 requirement。")
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
        generated = await self._run_planner(
            self._sql_agent,
            {
                "requirements": state[REPORT_DATA_REQUIREMENTS_STATE_KEY],
                "schemas": state[REPORT_SCHEMA_SNAPSHOTS_STATE_KEY],
                "period": self._envelope(run_context).period.model_dump(mode="json"),
                "feedback": self._feedback(step_input),
                "rules": [
                    "一次返回覆盖全部 requirements 的 SQL 批次",
                    "每项只生成一条 SELECT 或只读 CTE",
                    "每张表使用完整精确期间并按共同粒度预聚合",
                ],
            },
            run_context,
        )
        assert isinstance(generated, GeneratedQueryBatch)
        approved = approve_query_batch(
            [item.model_dump(mode="json", by_alias=True) for item in generated.queries],
            sources={item.id: item for item in self._sources(run_context)},
            envelope=self._envelope(run_context),
            requirements=requirements,
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
            source.id: StarRocksDataSourceAdapter(source) for source in self._sources(run_context)
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
        root_key = coding_task_key(str(run_context.run_id or "report"))
        task_id = root_key if revision == 0 else f"{root_key}-revision-{revision}"
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
        instruction = json.dumps(
            {
                "task": "revise" if feedback else "analyze",
                "reportGoal": self._envelope(run_context).report_goal,
                "outline": state[REPORT_OUTLINE_STATE_KEY],
                "analysisPlan": state[REPORT_ANALYSIS_PLAN_STATE_KEY],
                "dataRequirements": state[REPORT_DATA_REQUIREMENTS_STATE_KEY],
                "datasets": result["datasets"],
                "lineage": state[REPORT_DATASET_LINEAGE_STATE_KEY],
                "markdownPath": markdown_path,
                "artifactManifestPath": manifest_path,
                "reportId": str(run_context.run_id),
                "revision": revision + 1,
                "codingTaskKey": task_id,
                "datasetSnapshotHash": dataset_snapshot_hash(lineage),
                "reviewFeedback": feedback,
                "constraints": [
                    "只读取 Workflow 提交的不可变数据集，不连接数据库",
                    "核验口径、空数据、对账、事实粒度和图表引用",
                    "正文必须为每个 manifest citationId 和 section code 写入可检索标识",
                    "生成严格 ReportArtifactManifest JSON，引用的文件 hash 必须与工作区一致",
                    "生成 Markdown、图表和结论后调用 finish_task",
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        existing = await self.supervisor.repository.get_task_snapshot(task_id)
        if existing is None:
            await self.supervisor.start_task(coding_scope, instruction)
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
        manifest = await self._load_artifact_manifest(
            manifest_path,
            markdown_path=markdown_path,
            report_id=str(run_context.run_id),
            revision=revision + 1,
            task_id=task_id,
            lineage=lineage,
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
            str(result["jobId"]), str(result["markdownPath"]), pdf_path, run_context=context
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
        markdown_path: str,
        report_id: str,
        revision: int,
        task_id: str,
        lineage: tuple[DatasetLineage, ...],
        run_context: RunContext,
    ) -> ReportArtifactManifest:
        scope = self._scope(run_context)
        _relative, remote = self.workspace_service.normalize_path(manifest_path, allow_root=False)
        try:
            async with self.workspace_service._async_client() as client:
                sandbox = await self.workspace_service._asandbox_for(client, scope["threadId"])
                content = await self.workspace_service._adownload_file(sandbox, remote, 1024 * 1024)
            manifest = ReportArtifactManifest.model_validate_json(content)
        except Exception as error:
            raise ReportingError(
                "report_artifact_manifest_invalid", "报告产物清单不存在或格式无效。"
            ) from error
        if (
            manifest.report_id != report_id
            or manifest.revision != revision
            or manifest.coding_task_key != task_id
            or manifest.dataset_snapshot_hash != dataset_snapshot_hash(lineage)
            or manifest.markdown.path != markdown_path
        ):
            raise ReportingError(
                "report_artifact_manifest_invalid", "报告产物清单与当前任务不一致。"
            )
        for artifact in (manifest.markdown, *manifest.charts):
            current = await self.workspace_service.ahash_file(scope["threadId"], artifact.path)
            if current.get("sha256") != artifact.sha256 or current.get("size") != artifact.size:
                raise ReportingError("report_artifact_file_changed", "报告产物文件与清单不一致。")
        return manifest

    async def _run_planner(
        self, agent: Agent, payload: dict[str, Any], run_context: RunContext
    ) -> BaseModel:
        scope = self._scope(run_context)
        digest = hashlib.sha256(f"{run_context.run_id}:{agent.id}".encode()).hexdigest()[:32]
        output = await agent.arun(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
            session_id=f"report-planning-{digest}",
            user_id=scope["userId"],
            stream=False,
        )
        content = getattr(output, "content", None)
        schema = agent.output_schema
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise ReportingError("report_planner_invalid", "报表规划器缺少结构化输出。")
        try:
            return content if isinstance(content, schema) else schema.model_validate(content)
        except Exception as error:
            raise ReportingError("report_planner_invalid", "报表规划器返回无效结构。") from error

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

    def _sources(self, run_context: RunContext) -> tuple[StarRocksSourceConfig, ...]:
        return tuple(self._source(item) for item in self._envelope(run_context).source_ids or ())

    def _source(self, source_id: str) -> StarRocksSourceConfig:
        return self._starrocks_source(require_sources(self.registry.sources, (source_id,))[0])

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
        value = (run_context.dependencies or {}).get("AgentOS 报表工作流")
        if not isinstance(value, dict):
            raise ReportingError("report_workflow_context_missing", "报表工作流作用域缺失。")
        scope = {key: str(value.get(key) or "") for key in ("externalRunId", "threadId", "userId")}
        if any(not item for item in scope.values()):
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
