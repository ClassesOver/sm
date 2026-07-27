from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from agno.agent import Agent
from agno.run import RunContext
from agno.workflow.types import StepInput, StepOutput
from pydantic import BaseModel, ConfigDict, Field

from ...workspace import WorkspaceService
from .. import CodingScope, CodingTaskSupervisor, TaskState
from .binding import TemporarySourceBindingService
from .credentials import TemporaryCredentialStore
from .data_sources import ReportDataSourceToolkit
from .models import (
    AnalysisPlan,
    DataRequirement,
    QueryCandidate,
    ReportingError,
    ReportOutline,
    ReportSourceBinding,
    SourceMode,
)
from .providers import (
    SqlGenerationProvider,
    StarRocksClientFactory,
    try_generate_vanna_sql,
)
from .state import (
    REPORT_ANALYSIS_PLAN_STATE_KEY,
    REPORT_ARTIFACTS_STATE_KEY,
    REPORT_OUTLINE_STATE_KEY,
    bind_report_source,
)
from .workflow import create_reporting_workflow
from .workspace import WorkspaceReportToolkit

REPORT_DATA_REQUIREMENTS_STATE_KEY = "report_data_requirements"
REPORT_QUERY_CANDIDATES_STATE_KEY = "report_query_candidates"
REPORT_SOURCE_PROFILE_STATE_KEY = "report_source_profile"
REPORT_WORKFLOW_INPUT_STATE_KEY = "report_workflow_input"
REPORT_WORKFLOW_RESULT_STATE_KEY = "report_workflow_result"


class _DataRequirementSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[DataRequirement] = Field(min_length=1, max_length=30)


class _GeneratedSql(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1, max_length=262_144)


class ReportWorkflowRuntime:
    """默认报表 Workflow executor 集合；数据库能力不进入 Agent 工具面。"""

    def __init__(
        self,
        *,
        db: Any,
        planner: Agent,
        report_worker: Agent,
        supervisor: CodingTaskSupervisor,
        workspace_service: WorkspaceService,
        binding_service: TemporarySourceBindingService,
        credentials: TemporaryCredentialStore,
        client_factory: StarRocksClientFactory,
        data_sources: ReportDataSourceToolkit,
        vanna_sql_provider: SqlGenerationProvider | None = None,
    ):
        self.db = db
        self.report_worker = report_worker
        self.supervisor = supervisor
        self.workspace_service = workspace_service
        self.binding_service = binding_service
        self.credentials = credentials
        self.client_factory = client_factory
        self.data_sources = data_sources
        self.vanna_sql_provider = vanna_sql_provider
        self.report_tools = WorkspaceReportToolkit(workspace_service, data_sources=data_sources)
        self._outline_agent = self._planning_agent(planner, "report-outline-planner", ReportOutline)
        self._analysis_agent = self._planning_agent(
            planner, "report-analysis-planner", AnalysisPlan
        )
        self._requirements_agent = self._planning_agent(
            planner, "report-requirements-planner", _DataRequirementSet
        )
        self._sql_agent = self._planning_agent(planner, "report-sql-planner", _GeneratedSql)

    @staticmethod
    def _planning_agent(planner: Agent, agent_id: str, output_schema: type[BaseModel]) -> Agent:
        agent = planner.deep_copy(
            update={
                "id": agent_id,
                "name": agent_id,
                "role": "只根据已批准元数据生成结构化报表规划，不调用工具。",
                "instructions": [
                    "严格返回 output_schema；不得虚构字段、数据或结论。",
                    "只使用输入中的报表目标、已批准来源、受限画像和审核反馈。",
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
            generate_data_requirements=self.generate_data_requirements,
            generate_query_candidates=self.generate_query_candidates,
            materialize_datasets=self.materialize_datasets,
            run_coding_analysis=self.run_coding_analysis,
            validate_report=self.validate_report,
            publish_report=self.publish_report,
        )

    async def cleanup_cancelled(
        self,
        scope: dict[str, str],
        workflow_session_id: str,
        workflow_run_id: str,
    ) -> None:
        for revision in range(4):
            task = await self.supervisor.repository.get_task_snapshot(
                f"{workflow_run_id}-coding-{revision}"
            )
            if task is not None and task.state not in {
                TaskState.COMPLETED,
                TaskState.FAILED,
                TaskState.CANCELLED,
            }:
                await self.supervisor.cancel_task(task.scope)
        workflow = self.workflow()
        state = await workflow.aget_session_state(workflow_session_id)
        binding = state.get("report_source_binding") if isinstance(state, dict) else None
        binding_id = binding.get("bindingId") if isinstance(binding, dict) else None
        if isinstance(binding_id, str):
            self.credentials.close(binding_id)
        result = state.get(REPORT_WORKFLOW_RESULT_STATE_KEY) if isinstance(state, dict) else None
        paths = (
            [result.get("markdownPath"), result.get("pdfPath")] if isinstance(result, dict) else []
        )
        tool_context = RunContext(
            run_id=workflow_run_id,
            session_id=scope["thread_id"],
            user_id=scope["user_id"],
            session_state=state if isinstance(state, dict) else {},
        )
        for path in paths:
            if not isinstance(path, str):
                continue
            try:
                _relative, remote = self.workspace_service.normalize_path(path, allow_root=False)
                await self.report_tools._delete_report_path(remote, tool_context, recursive=False)
            except Exception:
                pass

    async def validated_delivery(
        self,
        scope: dict[str, str],
        workflow_session_id: str,
        workflow_run_id: str,
    ) -> dict[str, Any] | None:
        state = await self.workflow().aget_session_state(workflow_session_id)
        result = state.get(REPORT_WORKFLOW_RESULT_STATE_KEY) if isinstance(state, dict) else None
        if not isinstance(result, dict) or not isinstance(result.get("jobId"), str):
            return None
        tool_context = RunContext(
            run_id=workflow_run_id,
            session_id=scope["thread_id"],
            user_id=scope["user_id"],
            session_state=state,
        )
        try:
            status = await self.report_tools.report_job_status(
                result["jobId"], run_context=tool_context
            )
        except Exception:
            return None
        artifacts = status.get("artifacts")
        markdown = artifacts.get("markdown") if isinstance(artifacts, dict) else None
        pdf = artifacts.get("pdf") if isinstance(artifacts, dict) else None
        if (
            status.get("status") != "validated"
            or not isinstance(markdown, dict)
            or not isinstance(pdf, dict)
            or markdown.get("changed") is not False
            or pdf.get("changed") is not False
            or markdown.get("path") != result.get("markdownPath")
            or pdf.get("path") != result.get("pdfPath")
        ):
            return None
        return {
            "jobId": result["jobId"],
            "status": "validated",
            "markdownPath": markdown["path"],
            "pdfPath": pdf["path"],
        }

    async def confirm_source(self, step_input: StepInput, run_context: RunContext) -> StepOutput:
        payload = step_input.input
        if not isinstance(payload, dict):
            raise ReportingError("report_workflow_input_invalid", "报表工作流输入无效。")
        goal = str(payload.get("reportGoal") or "").strip()
        source_ids = payload.get("sourceIds")
        source_ids = [str(item) for item in source_ids] if isinstance(source_ids, list) else []
        state = self._state(run_context)
        state[REPORT_WORKFLOW_INPUT_STATE_KEY] = {
            "reportGoal": goal,
            "sourceIds": source_ids,
        }
        source = payload.get("source")
        scope = self._scope(run_context)
        if isinstance(source, dict) and isinstance(source.get("confirmationId"), str):
            binding = await asyncio.to_thread(
                self.binding_service.approve,
                source["confirmationId"],
                user_id=scope["userId"],
                thread_id=scope["threadId"],
                session_id=scope["threadId"],
            )
        elif source_ids:
            binding = await self._bind_explicit_sources(source_ids, run_context)
        else:
            raise ReportingError("report_source_required", "报表工作流必须绑定明确的数据来源。")
        bind_report_source(state, binding)
        return StepOutput(content={"source": binding.public_dict()})

    async def _bind_explicit_sources(
        self, source_ids: list[str], run_context: RunContext
    ) -> ReportSourceBinding:
        descriptions = []
        tool_context = self._tool_context(run_context)
        for source_id in source_ids:
            descriptions.append(
                await self.data_sources.report_describe_data_source(
                    source_id, run_context=tool_context
                )
            )
        encoded = json.dumps(descriptions, ensure_ascii=True, sort_keys=True, default=str).encode()
        fingerprint = hashlib.sha256(encoded).hexdigest()
        source_types = {str(item.get("sourceType") or "") for item in descriptions}
        if len(source_ids) > 1:
            mode = SourceMode.HYBRID
        elif source_types & {"postgresql", "starrocks"}:
            mode = SourceMode.MANAGED_QUERY
        elif source_types == {"odoo_export"}:
            mode = SourceMode.ODOO_EXPORT
        else:
            mode = SourceMode.WORKSPACE_REFERENCE
        allowed_tables: list[str] = []
        for description in descriptions:
            tables = description.get("tables")
            if isinstance(tables, dict):
                allowed_tables.extend(str(item) for item in tables)
            elif isinstance(tables, list):
                allowed_tables.extend(str(item) for item in tables)
        scope = self._scope(run_context)
        return ReportSourceBinding(
            bindingId=f"src_{fingerprint[:32]}",
            sourceMode=mode,
            database=(
                str(descriptions[0].get("database"))
                if len(descriptions) == 1 and descriptions[0].get("database")
                else None
            ),
            allowedTables=tuple(dict.fromkeys(allowed_tables)),
            metadataFingerprint=fingerprint,
            threadId=scope["threadId"],
            userId=scope["userId"],
            sessionId=scope["threadId"],
            expiresAt=datetime.now(UTC) + timedelta(hours=24),
        )

    async def profile_source(self, _step_input: StepInput, run_context: RunContext) -> StepOutput:
        state = self._state(run_context)
        binding = self._binding(state)
        result: dict[str, Any]
        if binding.source_mode is SourceMode.TEMPORARY_DATABASE:
            scope = self._scope(run_context)
            request = self.credentials.resolve(
                binding.binding_id,
                user_id=scope["userId"],
                thread_id=scope["threadId"],
                session_id=scope["threadId"],
            )
            client = self.client_factory(request.secret_payload())
            try:
                description = await asyncio.to_thread(client.describe, binding.allowed_tables)
                profile = await asyncio.to_thread(
                    client.profile, binding.allowed_tables, timeout_seconds=30
                )
            finally:
                await asyncio.to_thread(client.close)
            if description.metadata_fingerprint != binding.metadata_fingerprint:
                raise ReportingError("source_metadata_changed", "数据源元数据已变化，请重新确认。")
            result = {
                "database": description.database,
                "tables": description.tables,
                "profile": profile.tables,
                "metadataFingerprint": description.metadata_fingerprint,
            }
        else:
            source_ids = self._workflow_input(state)["sourceIds"]
            result = {
                "sources": [
                    await self.data_sources.report_describe_data_source(
                        source_id, run_context=self._tool_context(run_context)
                    )
                    for source_id in source_ids
                ]
            }
        state[REPORT_SOURCE_PROFILE_STATE_KEY] = result
        return StepOutput(content=result)

    async def generate_outline(self, step_input: StepInput, run_context: RunContext) -> StepOutput:
        state = self._state(run_context)
        binding = self._binding(state)
        feedback = self._feedback(step_input)
        outline = await self._run_planner(
            self._outline_agent,
            {
                "reportGoal": self._workflow_input(state)["reportGoal"],
                "sourceProfile": state.get(REPORT_SOURCE_PROFILE_STATE_KEY),
                "requiredHospitalSections": [
                    "管理摘要",
                    "收入规模与结构",
                    "收入及工作量预算达成",
                    "支出与项目预算执行",
                    "成本结构与收支效率",
                    "工作量与资源效率",
                    "院区/科室排名和异常",
                    "差异归因及管理建议",
                ],
                "feedback": feedback,
            },
            run_context,
        )
        assert isinstance(outline, ReportOutline)
        outline = outline.model_copy(
            update={
                "outline_id": f"outline_{hashlib.sha256(str(outline).encode()).hexdigest()[:24]}",
                "binding_id": binding.binding_id,
                "metadata_fingerprint": binding.metadata_fingerprint,
                "approved": False,
            }
        )
        state[REPORT_OUTLINE_STATE_KEY] = outline.model_dump(mode="json", by_alias=True)
        return StepOutput(content=outline)

    async def generate_analysis_plan(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        state = self._state(run_context)
        binding = self._binding(state)
        outline = ReportOutline.model_validate(state.get(REPORT_OUTLINE_STATE_KEY))
        plan = await self._run_planner(
            self._analysis_agent,
            {
                "reportGoal": self._workflow_input(state)["reportGoal"],
                "outline": outline.model_dump(mode="json", by_alias=True),
                "sourceProfile": state.get(REPORT_SOURCE_PROFILE_STATE_KEY),
                "rules": {
                    "requiredMethods": [
                        "comprehensive",
                        "year_over_year",
                        "month_over_month",
                        "attribution",
                    ],
                    "yearOverYear": "仅在上一年可比期间存在时 execute",
                    "monthOverMonth": "仅在上一连续月份存在时 execute",
                },
            },
            run_context,
        )
        assert isinstance(plan, AnalysisPlan)
        plan = plan.model_copy(
            update={
                "plan_id": f"plan_{hashlib.sha256(str(plan).encode()).hexdigest()[:24]}",
                "outline_id": outline.outline_id,
                "binding_id": binding.binding_id,
            }
        )
        state[REPORT_ANALYSIS_PLAN_STATE_KEY] = plan.model_dump(mode="json", by_alias=True)
        return StepOutput(content=plan)

    async def generate_data_requirements(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        state = self._state(run_context)
        binding = self._binding(state)
        plan = AnalysisPlan.model_validate(state.get(REPORT_ANALYSIS_PLAN_STATE_KEY))
        generated = await self._run_planner(
            self._requirements_agent,
            {
                "analysisPlan": plan.model_dump(mode="json", by_alias=True),
                "sourceProfile": state.get(REPORT_SOURCE_PROFILE_STATE_KEY),
                "rules": [
                    "每项需求只声明指标、维度、粒度、期间、对比期间和用途",
                    "不得在 DataRequirement 中携带 SQL",
                    "不同事实表先分别按一致粒度聚合",
                ],
            },
            run_context,
        )
        assert isinstance(generated, _DataRequirementSet)
        requirements = [
            item.model_copy(
                update={
                    "requirement_id": f"req_{index:02d}_{hashlib.sha256(str(item).encode()).hexdigest()[:16]}",
                    "binding_id": binding.binding_id,
                }
            )
            for index, item in enumerate(generated.requirements, start=1)
        ]
        serialized = [item.model_dump(mode="json", by_alias=True) for item in requirements]
        state[REPORT_DATA_REQUIREMENTS_STATE_KEY] = serialized
        return StepOutput(content={"requirements": serialized})

    async def generate_query_candidates(
        self, step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        state = self._state(run_context)
        binding = self._binding(state)
        requirements = [
            DataRequirement.model_validate(item)
            for item in state.get(REPORT_DATA_REQUIREMENTS_STATE_KEY, [])
        ]
        if binding.source_mode not in {
            SourceMode.TEMPORARY_DATABASE,
            SourceMode.MANAGED_QUERY,
        }:
            state[REPORT_QUERY_CANDIDATES_STATE_KEY] = []
            return StepOutput(content={"candidates": []})
        candidates = []
        for requirement in requirements:
            vanna_sql = await asyncio.to_thread(
                try_generate_vanna_sql,
                self.vanna_sql_provider,
                requirement,
                binding,
            )
            if vanna_sql is not None:
                candidates.append(
                    QueryCandidate(
                        requirementId=requirement.requirement_id,
                        bindingId=binding.binding_id,
                        sql=vanna_sql,
                        generator="vanna",
                        requiresApproval=False,
                    )
                )
                continue
            generated = await self._run_planner(
                self._sql_agent,
                {
                    "requirement": requirement.model_dump(mode="json", by_alias=True),
                    "source": {
                        "database": binding.database,
                        "allowedTables": list(binding.allowed_tables),
                        "profile": state.get(REPORT_SOURCE_PROFILE_STATE_KEY),
                    },
                    "feedback": self._feedback(step_input),
                    "rules": "仅生成一条 SELECT 或只读 CTE，不跨库，不使用未批准表。",
                },
                run_context,
            )
            assert isinstance(generated, _GeneratedSql)
            candidates.append(
                QueryCandidate(
                    requirementId=requirement.requirement_id,
                    bindingId=binding.binding_id,
                    sql=generated.sql,
                    generator="agent",
                    requiresApproval=binding.source_mode is SourceMode.MANAGED_QUERY,
                )
            )
        serialized = [item.model_dump(mode="json", by_alias=True) for item in candidates]
        state[REPORT_QUERY_CANDIDATES_STATE_KEY] = serialized
        review = {
            "requirements": [item.requirement_id for item in requirements],
            "generators": [item.generator for item in candidates],
            "approvalReason": "受管来源的 Agent SQL 需要单独审核。",
        }
        return StepOutput(content={"candidates": serialized, **review})

    async def materialize_datasets(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        state = self._state(run_context)
        binding = self._binding(state)
        tool_context = self._tool_context(run_context)
        datasets: list[dict[str, Any]] = []
        candidates = [
            QueryCandidate.model_validate(item)
            for item in state.get(REPORT_QUERY_CANDIDATES_STATE_KEY, [])
        ]
        if candidates:
            source_ids = self._workflow_input(state)["sourceIds"]
            source_id = (
                binding.binding_id
                if binding.source_mode is SourceMode.TEMPORARY_DATABASE
                else source_ids[0]
            )
            for candidate in candidates:
                result = await self.data_sources.report_materialize_dataset(
                    source_id,
                    sql=candidate.sql,
                    output_format="parquet",
                    run_context=tool_context,
                )
                datasets.extend(result["datasets"])
        else:
            for source_id in self._workflow_input(state)["sourceIds"]:
                result = await self.data_sources.report_materialize_dataset(
                    source_id, output_format="parquet", run_context=tool_context
                )
                datasets.extend(result["datasets"])
        dataset_ids = [str(item["datasetId"]) for item in datasets]
        prepared = await self.report_tools.report_prepare_dataset(
            dataset_ids, run_context=tool_context
        )
        state[REPORT_WORKFLOW_RESULT_STATE_KEY] = {
            "datasets": datasets,
            "jobId": prepared["jobId"],
            "revision": 0,
        }
        return StepOutput(content={"datasets": datasets, "jobId": prepared["jobId"]})

    async def run_coding_analysis(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        result = await self._run_coding(run_context, feedback=None)
        return StepOutput(content=result)

    async def _run_coding(self, run_context: RunContext, *, feedback: str | None) -> dict[str, Any]:
        state = self._state(run_context)
        workflow_result = self._workflow_result(state)
        revision = int(workflow_result.get("revision", 0)) + (1 if feedback else 0)
        scope = self._scope(run_context)
        async with self.workspace_service._async_client() as client:
            sandbox = await self.workspace_service._asandbox_for(client, scope["threadId"])
            sandbox_id = str(getattr(sandbox, "id", "") or "")
        if not sandbox_id or not self.report_worker.id:
            raise ReportingError("report_worker_unavailable", "报表 Coding 工作区不可用。")
        workflow_run_id = str(run_context.run_id or "report")
        coding_scope = CodingScope(
            f"{workflow_run_id}-coding-{revision}",
            scope["userId"],
            scope["threadId"],
            sandbox_id,
            str(self.report_worker.id),
        )
        markdown_path = f"报表/智能分析/{workflow_run_id}/report.md"
        instruction = {
            "task": "revise" if feedback else "analyze",
            "analysisPlan": state.get(REPORT_ANALYSIS_PLAN_STATE_KEY),
            "dataRequirements": state.get(REPORT_DATA_REQUIREMENTS_STATE_KEY),
            "datasets": workflow_result["datasets"],
            "markdownPath": markdown_path,
            "reviewFeedback": feedback,
            "constraints": [
                "只使用 DatasetHandle 中的工作区文件，不连接数据库",
                "核验指标口径、空数据、累计值、对账和事实粒度",
                "完成统计、归因、图表和 Markdown 后调用 finish_task",
            ],
        }
        await self.supervisor.start_task(
            coding_scope,
            json.dumps(instruction, ensure_ascii=False, separators=(",", ":")),
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
        workflow_result.update({"markdownPath": markdown_path, "revision": revision})
        state[REPORT_WORKFLOW_RESULT_STATE_KEY] = workflow_result
        return {"jobId": workflow_result["jobId"], "markdownPath": markdown_path}

    async def validate_report(self, _step_input: StepInput, run_context: RunContext) -> StepOutput:
        result = await self._render_and_validate(run_context)
        return StepOutput(content=result)

    async def _render_and_validate(self, run_context: RunContext) -> dict[str, Any]:
        state = self._state(run_context)
        result = self._workflow_result(state)
        revision = int(result.get("revision", 0))
        workflow_run_id = str(run_context.run_id or "report")
        suffix = "" if revision == 0 else f"-revision-{revision}"
        pdf_path = f"报表/智能分析/{workflow_run_id}/report{suffix}.pdf"
        tool_context = self._tool_context(run_context)
        await self.report_tools.report_render_markdown(
            str(result["jobId"]),
            str(result["markdownPath"]),
            pdf_path,
            run_context=tool_context,
        )
        validation = await self.report_tools.report_validate_pdf(
            str(result["jobId"]), pdf_path, run_context=tool_context
        )
        if validation.get("ok") is not True:
            raise ReportingError("report_pdf_validation_failed", "PDF 验收未通过。")
        result.update({"pdfPath": pdf_path, "validation": validation, "status": "validated"})
        state[REPORT_WORKFLOW_RESULT_STATE_KEY] = result
        state[REPORT_ARTIFACTS_STATE_KEY] = {
            "markdownPath": result["markdownPath"],
            "pdfPath": pdf_path,
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
                "markdownPath": result["markdownPath"],
                "pdfPath": result["pdfPath"],
                "validation": result["validation"],
            }
        )

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

    @staticmethod
    def _feedback(step_input: StepInput) -> str | None:
        value = (step_input.additional_data or {}).get("rejection_feedback")
        return str(value).strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _state(run_context: RunContext) -> dict[str, Any]:
        if not isinstance(run_context.session_state, dict):
            raise ReportingError("report_workflow_state_invalid", "报表工作流状态无效。")
        return run_context.session_state

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
    def _binding(state: dict[str, Any]) -> ReportSourceBinding:
        try:
            return ReportSourceBinding.model_validate(state.get("report_source_binding"))
        except Exception as error:
            raise ReportingError("source_binding_missing", "报表来源尚未绑定。") from error

    @staticmethod
    def _workflow_input(state: dict[str, Any]) -> dict[str, Any]:
        value = state.get(REPORT_WORKFLOW_INPUT_STATE_KEY)
        if not isinstance(value, dict):
            raise ReportingError("report_workflow_input_invalid", "报表工作流输入状态无效。")
        return value

    @staticmethod
    def _workflow_result(state: dict[str, Any]) -> dict[str, Any]:
        value = state.get(REPORT_WORKFLOW_RESULT_STATE_KEY)
        if not isinstance(value, dict):
            raise ReportingError("report_workflow_result_invalid", "报表工作流产物状态无效。")
        return dict(value)

    def _tool_context(self, run_context: RunContext) -> RunContext:
        scope = self._scope(run_context)
        return RunContext(
            run_id=run_context.run_id,
            session_id=scope["threadId"],
            user_id=scope["userId"],
            session_state=run_context.session_state,
            dependencies=run_context.dependencies,
        )
