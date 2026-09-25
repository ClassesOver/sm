# mypy: disable-error-code="attr-defined"
# 运行时由 Facade 组合的多重继承提供跨阶段成员；静态检查无法解析该装配。
from __future__ import annotations

from copy import deepcopy
from pathlib import PurePosixPath
from typing import Literal

from pydantic import ConfigDict, Field
from sqlglot import exp

from ....report_editor.service import ReportEditorContext
from ...structured_output import StructuredOutputCallBudget
from .base import (
    _PLANNER_DISPLAY_NAMES,
    DOMAIN_CODES,
    REPORT_ANALYSIS_PLAN_STATE_KEY,
    REPORT_APPROVED_QUERIES_STATE_KEY,
    REPORT_CAPABILITIES_STATE_KEY,
    REPORT_DATA_REQUIREMENTS_STATE_KEY,
    REPORT_DATA_SHAPES_STATE_KEY,
    REPORT_DATA_UNDERSTANDING_STATE_KEY,
    REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
    REPORT_EFFECTIVE_PROFILE_STATE_KEY,
    REPORT_OUTLINE_HASH_STATE_KEY,
    REPORT_OUTLINE_STATE_KEY,
    REPORT_REQUEST_CONTEXT_STATE_KEY,
    REPORT_ROW_PRESERVING_REQUIREMENTS_STATE_KEY,
    REPORT_SCHEMA_SNAPSHOTS_STATE_KEY,
    REPORT_WORKFLOW_INPUT_STATE_KEY,
    REPORT_WORKFLOW_SCOPE_STATE_KEY,
    AnalysisBundle,
    Any,
    ApprovedQuery,
    BaseModel,
    CatalogColumn,
    CatalogTable,
    DataShape,
    DataUnderstandingPlan,
    DataUnderstandingTable,
    DetailedAnalysisPlan,
    EffectiveReportingProfile,
    GeneratedQueryBatch,
    Mapping,
    MeasureSemantic,
    MeasureSemanticProposal,
    ModelColumn,
    ModelTable,
    ModelTermsResponse,
    NormalizedReportPrompt,
    PlanningSchema,
    PlanningSchemaColumn,
    PlanningSchemaTable,
    QueryRequirement,
    ReconciliationShape,
    ReportArtifactSpec,
    ReportDownloadScope,
    ReportingCommand,
    ReportingError,
    ReportingWorkflowInput,
    ReportOutline,
    ReportOutlineProposal,
    ReportPeriod,
    ReportPeriodWindows,
    ReportPromptInput,
    ReportRequestEnvelope,
    RunContext,
    SourceSchemaSnapshot,
    StarRocksDataSourceAdapter,
    StarRocksSourceConfig,
    StepInput,
    StepOutput,
    TableReference,
    TaskState,
    ValidationError,
    _payload_sha256,
    _validation_issue,
    anyio,
    approve_query_batch,
    build_outline_shape_view,
    cli_result,
    collect_data_shape,
    complete_cleanup,
    date,
    freeze_outline,
    json,
    logger,
    loguru_logger,
    parse_ddl,
    parse_field_ref,
    parse_reporting_workflow_input,
    publication_result,
    re,
    require_sources,
    resolve_profile_capabilities,
    resolve_reporting_workflow_scope,
    resolve_schema_snapshot,
)
from .datasets import _analysis_context_payload
from .models import _NUMERIC_MEASURE_TYPE_PATTERN
from .validation import (
    _analysis_bundle_semantic_issues,
    _available_table_columns,
    _available_tables,
    _normalize_analysis_bundle_grain,
    _normalize_comparison_roles,
    _normalize_duplicate_requirements,
    _normalize_requirement_columns,
    _normalize_requirement_columns_in_payload,
    _normalize_requirement_periods,
    _normalize_unsafe_multi_table_requirements,
    _resolve_requirement_comparison_roles,
)

__all__ = ["RuntimePlanningMixin", "_PLANNER_DISPLAY_NAMES"]


class _TerminalCleanupTrace(BaseModel):
    """终态清理只读取关闭 phase task 所需的受限身份。"""

    model_config = ConfigDict(extra="ignore")

    task_id: str | None = Field(default=None, alias="taskId", max_length=128)


class _TerminalCleanupCheckpoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    trace: tuple[_TerminalCleanupTrace, ...] = Field(default=(), max_length=2000)


class RuntimePlanningMixin:
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
            self._record_request_context(state, request.report_goal, feedback)
            self._record_normalized_request(state, request)
            return StepOutput(
                content=request.model_dump(mode="json", by_alias=True, exclude_none=True)
            )

        assert isinstance(request, ReportPromptInput)
        self._record_request_context(state, request.prompt, feedback)
        prompt_payload: dict[str, Any] = {"prompt": request.prompt}
        if feedback:
            prompt_payload["supplement"] = feedback
        normalized = await self._run_planner(self._request_normalizer, prompt_payload, run_context)
        assert isinstance(normalized, NormalizedReportPrompt)
        period = _single_explicit_year(request.prompt, feedback) or normalized.period
        missing: list[str] = []
        if period is None:
            missing.append(normalized.clarification_question or "请明确唯一的分析期间。")
        semantic_domains = tuple(dict.fromkeys(normalized.domains))
        report_type = normalized.report_type
        if report_type is None:
            missing.append(normalized.clarification_question or "请明确报告是整体运营分析还是专题分析。")
        if report_type == "topic" and not semantic_domains:
            missing.append(normalized.clarification_question or "请明确需要分析的业务主题。")
        if missing:
            return StepOutput(content={"clarificationQuestion": " ".join(dict.fromkeys(missing))})
        assert period is not None
        assert report_type is not None
        domains = semantic_domains or DOMAIN_CODES
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
            # 无法解析的旧 checkpoint 仍由业务恢复路径失败关闭；终态清理不能因此
            # 跳过已启动任务。这里只验证并读取 taskId，任何结构损坏都会阻止销毁
            # sandbox，避免遗漏仍在运行的 phase task。
            checkpoint = _TerminalCleanupCheckpoint.model_validate(stored_checkpoint)
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
        await self._release_or_destroy_workspace(
            scope["thread_id"],
            message="报表工作流已结束，但运行环境删除失败，已隔离并转入后台清理。",
        )

    async def _release_or_destroy_workspace(self, thread_id: str, *, message: str) -> None:
        if getattr(self, "workspace_registry", None) is not None:
            # 宿主机模式只释放进程内 Workspace 身份，保留会话目录和全部产物供审计/恢复
            # 与报告编辑器续写；宿主机路由不提供 sandbox 删除/隔离能力。
            self.workspace_registry.release(thread_id)
            getattr(self, "_host_workspaces", {}).pop(thread_id, None)
            loguru_logger.info("report_host_workspace_released workspace_key={}", thread_id)
            return
        await self._destroy_or_quarantine_workspace(thread_id, message=message)

    async def _destroy_or_quarantine_workspace(self, thread_id: str, *, message: str) -> None:
        """删除失败时先轮换持久化 generation，再允许控制器释放 owner。"""

        try:
            await complete_cleanup(self.workspace_service.adestroy(thread_id))
            return
        except Exception as cleanup_error:
            try:
                workspace_label = await complete_cleanup(
                    self.workspace_service.aquarantine(thread_id)
                )
            except Exception as quarantine_error:
                # 只有 generation 已持久化轮换，旧 sandbox 才对新请求不可达。隔离本身
                # 失败时必须使用不同错误码，让 Controller 保留 owner，不能为了可用性
                # 绕过运行环境隔离不变量。
                raise ReportingError(
                    "report_sandbox_quarantine_failed",
                    "报表工作流已结束，但失败运行环境无法隔离，请稍后重试。",
                ) from quarantine_error
            loguru_logger.warning(
                "report_sandbox_cleanup_deferred thread_id={} workspace_label={} error_type={}",
                thread_id,
                workspace_label,
                type(cleanup_error).__name__,
            )
            raise ReportingError("report_sandbox_cleanup_failed", message) from cleanup_error

    async def issue_http_publication(
        self,
        *,
        thread_id: str,
        caller_thread_id: str,
        user_id: str,
        workflow_session_id: str,
        workflow_run_id: str,
        dependencies: dict[str, Any] | None = None,
        output: Any,
    ) -> dict[str, Any]:
        download_grants = self.download_grants
        editor_grants = self.editor_grants
        artifact_persistence = self.artifact_persistence
        if download_grants is None or artifact_persistence is None or editor_grants is None:
            raise RuntimeError("HTTP 报表发布依赖配置不完整")
        report_public_base_url = self.report_public_base_url
        if report_public_base_url is None:
            raise RuntimeError("HTTP 报表发布缺少公开下载基址")
        content = self._publication_content(output)
        source_markdown = PurePosixPath(content["markdownPath"])
        revision_directory = f"revision-{content['revision']}"
        revision_markdown = (
            source_markdown
            if source_markdown.parent.name == revision_directory
            else source_markdown.parent / revision_directory / source_markdown.name
        )
        if revision_markdown != source_markdown:
            markdown = await self.workspace_service.aread_text(thread_id, str(source_markdown))
            if await self.workspace_service.apath_exists(thread_id, str(revision_markdown)):
                existing = await self.workspace_service.aread_text(
                    thread_id, str(revision_markdown)
                )
                if existing != markdown:
                    raise ReportingError(
                        "report_editor_revision_conflict",
                        "当前报告 revision 已存在不同的 Markdown 快照。",
                    )
            else:
                await self.workspace_service.awrite_text(
                    thread_id, str(revision_markdown), markdown
                )
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
        durable = await self.state_repository.get(workflow_run_id)
        stored_scope = (
            durable.payload.get(REPORT_WORKFLOW_SCOPE_STATE_KEY)
            if durable is not None and isinstance(durable.payload, dict)
            else None
        )
        # Durable payload 不固化作用域；调用方 thread 只能从发布时的 run_context
        # dependencies 恢复，与 _scope() 的解析来源保持一致，否则 caller_thread_id
        # 会回退到 workflow 内部会话 id，误判编辑上下文作用域不一致。
        # thread_id 是 as_state() 里的 workspace_key（供工作区 IO 寻址），安全比对
        # 必须对着调用方 thread（callerThreadId），两者不是同一语义。
        scope = resolve_reporting_workflow_scope(
            run_id=workflow_run_id,
            session_id=workflow_session_id,
            user_id=user_id,
            dependencies=dependencies,
            stored_scope=stored_scope if isinstance(stored_scope, dict) else None,
        )
        if durable is None or scope.caller_thread_id != caller_thread_id:
            raise ReportingError(
                "report_editor_scope_mismatch", "报告编辑上下文与发布作用域不一致。"
            )
        editor_context = ReportEditorContext(
            reportId=content["reportId"],
            revision=content["revision"],
            jobId=content["jobId"],
            workflowRunId=workflow_run_id,
            markdownPath=str(revision_markdown),
            job=content["editorJob"],
            scope=scope.as_state(),
        )
        await self.state_repository.apply(
            workflow_run_id,
            ReportingCommand(
                name="set_report_editor_context",
                payload={
                    "context": editor_context.model_dump(mode="json", by_alias=True)
                },
                commandId=f"editor-context:{content['revision']}:{editor_context.digest()}",
            ),
            expected_version=durable.state_version,
        )
        await self._release_or_destroy_workspace(
            thread_id,
            message="报告已持久化，但运行环境删除失败，已隔离并转入后台清理。",
        )
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
        editor_raw, editor_expires_at = await editor_grants.issue(editor_context)
        return publication_result(
            report_id=content["reportId"],
            revision=content["revision"],
            raw_grant=raw,
            grant=grant,
            base_url=report_public_base_url,
            editor_raw_grant=editor_raw,
            editor_expires_at=editor_expires_at,
            source_warnings=content["sourceWarnings"],
            task_receipts=content["codingReceipts"],
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
            task_receipts=content["codingReceipts"],
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
        _validate_reporting_profile_schema(profile, tuple(snapshots))
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
        call_budget = StructuredOutputCallBudget()
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
                call_budget=call_budget,
                attempt=min(attempt - 1, 1),
                failure_kind=(
                    "capability_mapping_failure" if validation_feedback is not None else None
                ),
            )
            plan, previous_output, validation_feedback = _data_understanding_result(
                output, snapshots
            )
            if plan is None:
                continue
            plan = _normalize_preferred_typed_period_fields(
                plan,
                snapshots,
                report_goal=envelope.report_goal,
            )
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
        call_budget = StructuredOutputCallBudget()
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
            try:
                proposal = await self._run_planner(
                    self._measure_semantic_agent,
                    payload,
                    run_context,
                    call_budget=call_budget,
                    attempt=min(attempt - 1, 1),
                    failure_kind=(
                        "capability_mapping_failure" if validation_feedback is not None else None
                    ),
                )
            except ValidationError as error:
                # 兼容端点可能接受 strict tool schema 却仍漏掉嵌套必填字段。
                # 不在服务端猜测字段值，而是把完整候选和精简校验路径回灌给同一
                # planner，让模型在既有五次上限内返回完整分类。
                previous_output = _outline_candidate(error)
                validation_feedback = {
                    "code": "report_measure_semantic_proposal_invalid",
                    "summary": "指标语义候选未通过结构校验",
                    "issues": _outline_validation_issues(error),
                }
                continue
            assert isinstance(proposal, MeasureSemanticProposal)
            proposal = _project_measure_semantic_candidates(proposal, candidate_refs)
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
        call_budget = StructuredOutputCallBudget()
        for attempt in range(1, 6):
            payload: dict[str, Any] = dict(base_payload)
            if validation_feedback is not None:
                payload["correction"] = {
                    "attempt": attempt,
                    "previousOutput": previous_output,
                    "allowedPaths": list(allowed_paths),
                    "validationFeedback": _compact_validation_feedback(validation_feedback),
                    "instruction": (
                        "修正全部 issues 并返回完整 ReportOutlineProposal；sections 每项只能包含 "
                        "title 和 analysisIds，不得包含 code 或 focus；每个章节必须引用已注册 "
                        "analysisId；不返回正文、解释或 Markdown"
                    ),
                }
            try:
                output = await self._run_planner(
                    self._outline_agent,
                    payload,
                    run_context,
                    call_budget=call_budget,
                    attempt=min(attempt - 1, 1),
                    failure_kind="schema_failure" if validation_feedback is not None else None,
                )
            except ValidationError as error:
                # Agno 的 Agent 重试只对同一输入盲重试，无法携带结构校验失败的原因；
                # 这里把 planner 抛出的 ValidationError 转成 correction 回灌，让模型
                # 在下一次调用时看到 previousOutput 与逐项 issues 并修正，而不是直接
                # 让整条 workflow 失败。
                previous_output = _outline_candidate(error)
                validation_issues = _outline_validation_issues(error)
                allowed_paths = _outline_allowed_paths(validation_issues)
                validation_feedback = {
                    "code": "report_outline_invalid",
                    "summary": "报告提纲未通过结构校验",
                    "issues": validation_issues,
                }
                continue
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
                # freeze_outline 会再次校验服务端生成的稳定提纲。Pydantic 错误必须
                # 保留真实顶层字段，否则 assumptions 失败却只授权修改 sections，
                # 模型无论重试多少次都无法满足门禁。普通引用错误没有结构化位置，
                # 继续只授权 sections，不能借异常文本扩大可修改范围。
                freeze_issues = (
                    _outline_validation_issues(error)
                    if isinstance(error, ValidationError)
                    else [{"path": "sections", "reason": str(error)}]
                )
                allowed_paths = _outline_allowed_paths(freeze_issues)
                validation_feedback = {
                    "code": "report_outline_invalid",
                    "summary": "报告提纲引用的分析未通过服务端冻结校验",
                    "issues": freeze_issues,
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
        logger.info(
            "report_outline_planned outline={}",
            json.dumps(
                {
                    "reportTitle": outline.title,
                    "sectionCount": len(outline.sections),
                    "sections": [
                        {
                            "sectionNumber": section.section_number,
                            "sectionCode": section.code,
                            "title": section.title,
                            "analysisCount": len(section.analysis_ids),
                        }
                        for section in outline.sections
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
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
        data_shapes = self._data_shapes(run_context)
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
            data_shapes,
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
            # DataUnderstanding 与 Schema 共享 source/table；将期间元数据附加到
            # Schema 的表项后只保留一份模型输入投影。完整 DataUnderstanding 仍保存在
            # Workflow state，并由服务端 validation 使用，不改变任何硬校验边界。
            "schemas": _planning_schema_payload_with_periods(
                snapshots,
                tables={item.table for item in data_understanding.tables},
                description_limit=160,
                data_understanding=data_understanding,
            ),
        }
        validation_feedback: dict[str, Any] | None = None
        previous_output: dict[str, Any] | None = None
        allowed_mutation_paths: tuple[str, ...] = ()
        required_deletion_paths: tuple[str, ...] = ()
        last_semantic_correction_signature: str | None = None
        bundle: AnalysisBundle | None = None
        call_budget = StructuredOutputCallBudget()
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
            try:
                output = await self._run_planner(
                    self._analysis_agent,
                    payload,
                    run_context,
                    call_budget=call_budget,
                    attempt=min(attempt - 1, 1),
                    failure_kind="schema_failure" if validation_feedback is not None else None,
                )
            except ValidationError as error:
                # Analysis planner 已关闭 Agno 对同一输入的盲重试。结构错误必须携带
                # 原始候选和精确字段路径进入 Reporting 纠错循环；否则复杂 Bundle
                # 会在 Pydantic 边界直接终止，模型永远看不到拒绝原因。
                previous_output = _outline_candidate(error)
                validation_issues = _analysis_validation_issues(error)
                required_deletion_paths = _analysis_required_deletion_paths(
                    validation_issues, previous_output
                )
                allowed_mutation_paths = _analysis_allowed_mutation_paths(
                    validation_issues,
                    previous_output=previous_output,
                    required_deletion_paths=required_deletion_paths,
                )
                validation_feedback = {
                    "code": "report_analysis_plan_invalid",
                    "summary": "分析计划未通过结构校验",
                    "issues": validation_issues,
                }
                continue
            assert isinstance(output, AnalysisBundle)
            output_payload = output.model_dump(mode="json", by_alias=True)
            normalized_output, column_repairs = _normalize_requirement_columns(output, snapshots)
            if column_repairs:
                normalized_payload = normalized_output.model_dump(mode="json", by_alias=True)
                output = normalized_output
                output_payload = normalized_payload
            normalized_output, period_repairs = _normalize_requirement_periods(
                output,
                self._data_understanding(run_context),
            )
            if period_repairs:
                normalized_payload = normalized_output.model_dump(mode="json", by_alias=True)
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
                    output_payload = _restore_unapproved_correction_changes(
                        previous_output,
                        output_payload,
                        tuple(unexpected_paths),
                    )
                    output = AnalysisBundle.model_validate(output_payload)
            normalized_output, split_repairs = _normalize_unsafe_multi_table_requirements(
                output, snapshots, data_shapes
            )
            if split_repairs:
                normalized_payload = normalized_output.model_dump(mode="json", by_alias=True)
                output = normalized_output
                output_payload = normalized_payload
            normalized_output, grain_repairs = _normalize_analysis_bundle_grain(
                output, snapshots, data_shapes
            )
            if grain_repairs:
                normalized_payload = normalized_output.model_dump(mode="json", by_alias=True)
                output = normalized_output
                output_payload = normalized_payload
            normalized_output, requirement_repairs = _normalize_duplicate_requirements(output)
            if requirement_repairs:
                normalized_payload = normalized_output.model_dump(mode="json", by_alias=True)
                output = normalized_output
                output_payload = normalized_payload
            normalized_output, comparison_repairs = _normalize_comparison_roles(
                output, self._envelope(run_context).comparison_roles
            )
            if comparison_repairs:
                normalized_payload = normalized_output.model_dump(mode="json", by_alias=True)
                output = normalized_output
                output_payload = normalized_payload
            semantic_issues = _analysis_bundle_semantic_issues(
                output,
                self._data_understanding(run_context),
                snapshots,
                self._envelope(run_context),
                data_shapes,
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
                        "report_planner_no_progress agent_id={} attempt={} "
                        "output_sha256={} issue_signature={}",
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
            _row_preserving_requirement_ids(bundle.requirements, self._profile(run_context))
        )
        return StepOutput(content=bundle)

    async def generate_query_candidates(
        self, step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        state = self._state(run_context)
        data_shapes = self._data_shapes(run_context)
        requirements = tuple(
            QueryRequirement.model_validate(item)
            for item in state[REPORT_DATA_REQUIREMENTS_STATE_KEY]
        )
        referenced_tables = {
            table.table for requirement in requirements for table in requirement.tables
        }
        base_payload = {
            "requirements": state[REPORT_DATA_REQUIREMENTS_STATE_KEY],
            # requirements 已包含每张表的期间字段和粒度；SQL planner 只需列名、类型
            # 和聚合语义，完整 DataUnderstanding 留在服务端状态用于严格审核。
            "schemas": _planning_schema_payload(
                self._snapshots(run_context),
                tables=referenced_tables,
                description_limit=0,
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
        call_budget = StructuredOutputCallBudget()
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
            output = await self._run_planner(
                self._sql_agent,
                payload,
                run_context,
                call_budget=call_budget,
                attempt=min(attempt - 1, 1),
                failure_kind="sql_validation_failure" if validation_feedback is not None else None,
            )
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
                data_shapes=data_shapes,
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
            # 模型是 SQL 的首选决策者；仅在模型连续五次无法产出通过校验的结果时，
            # 单表查询才使用既有确定性编译兜底，避免可恢复的模型波动阻断报表。
            compiled = _compile_single_table_queries(
                requirements,
                snapshots=snapshots,
                envelope=envelope,
                row_preserving_requirement_ids=tuple(
                    state.get(REPORT_ROW_PRESERVING_REQUIREMENTS_STATE_KEY, ())
                ),
            )
            if compiled is not None:
                compiled_approved, compilation_issues = _approve_generated_queries(
                    compiled,
                    sources=sources,
                    snapshots=snapshots,
                    envelope=envelope,
                    requirements=requirements,
                    row_preserving_requirement_ids=tuple(
                        state.get(REPORT_ROW_PRESERVING_REQUIREMENTS_STATE_KEY, ())
                    ),
                    data_shapes=data_shapes,
                )
                if not compilation_issues:
                    state[REPORT_APPROVED_QUERIES_STATE_KEY] = [
                        item.model_dump(mode="json", by_alias=True) for item in compiled_approved
                    ]
                    loguru_logger.warning(
                        "report_sql_model_fallback_to_compiler requirement_count={}",
                        len(requirements),
                    )
                    return StepOutput(content={"queries": state[REPORT_APPROVED_QUERIES_STATE_KEY]})
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


def _compile_single_table_queries(
    requirements: tuple[QueryRequirement, ...],
    *,
    snapshots: tuple[SourceSchemaSnapshot, ...],
    envelope: ReportRequestEnvelope,
    row_preserving_requirement_ids: tuple[str, ...] = (),
) -> GeneratedQueryBatch | None:
    """从已批准契约确定性编译单表 SQL；多表继续交由 SQL planner。"""

    if not requirements or any(len(requirement.tables) != 1 for requirement in requirements):
        return None
    semantics = {
        item.field_ref.lower(): item
        for snapshot in snapshots
        for item in snapshot.measure_semantics
    }
    snapshot_tables = {
        (table.source_id.lower(), f"{table.database}.{table.name}".lower()): table
        for snapshot in snapshots
        for table in snapshot.tables
    }
    row_preserving_ids = set(row_preserving_requirement_ids)
    queries: list[dict[str, Any]] = []
    for requirement in requirements:
        table = requirement.tables[0]
        qualified_table = table.table.lower()
        if "." not in qualified_table:
            matches = [
                qualified
                for source_id, qualified in snapshot_tables
                if source_id == requirement.source_id.lower()
                and qualified.endswith(f".{qualified_table}")
            ]
            if len(matches) != 1:
                return None
            qualified_table = matches[0]
        if (requirement.source_id.lower(), qualified_table) not in snapshot_tables:
            return None

        semantic_by_measure = {}
        for measure in table.measure_columns:
            semantic = semantics.get(f"{requirement.source_id}.{qualified_table}.{measure}".lower())
            if semantic is None:
                return None
            semantic_by_measure[measure] = semantic

        try:
            comparison_roles = requirement.resolved_comparison_roles(envelope.comparison_roles)
        except ValueError:
            return None
        windows = envelope.model_copy(update={"comparison_roles": comparison_roles}).period_windows(
            granularity=table.period_granularity
        )
        seen_window_ids: set[str] = set()
        for window in windows.windows:
            if window.query_window_id in seen_window_ids:
                continue
            seen_window_ids.add(window.query_window_id)
            row_preserving = requirement.requirement_id in row_preserving_ids
            projections: list[exp.Expression] = [
                exp.column(column) for column in requirement.grain_columns
            ]
            if row_preserving:
                projections.extend(exp.column(column) for column in table.measure_columns)
            else:
                for measure, semantic in semantic_by_measure.items():
                    aggregate = _measure_aggregate_expression(
                        measure,
                        semantic.aggregation,
                    )
                    projections.append(aggregate.as_(measure))

            predicates: list[exp.Expression] = [
                exp.column(table.period_column).between(
                    *_period_bound_expressions(window.period, table.period_granularity)
                )
            ]
            scope_values: dict[str, str] = {}
            for semantic in semantic_by_measure.values():
                for column, value in semantic.exclusive_scope.items():
                    previous = scope_values.setdefault(column, value)
                    if previous != value:
                        return None
            predicates.extend(
                exp.EQ(this=exp.column(column), expression=exp.Literal.string(value))
                for column, value in sorted(scope_values.items())
            )
            statement = (
                exp.select(*projections)
                .from_(exp.to_table(qualified_table))
                .where(exp.and_(*predicates))
            )
            if not row_preserving and requirement.grain_columns:
                statement = statement.group_by(
                    *(exp.column(column) for column in requirement.grain_columns)
                )
            queries.append(
                {
                    "requirementId": requirement.requirement_id,
                    "sourceId": requirement.source_id,
                    "sql": statement.sql(dialect="mysql"),
                    "periodRole": window.role,
                }
            )
    return GeneratedQueryBatch.model_validate({"queries": queries})


def _measure_aggregate_expression(column: str, aggregation: str) -> exp.Expression:
    source = exp.column(column)
    if aggregation == "sum":
        return exp.Sum(this=source)
    if aggregation == "average":
        return exp.Avg(this=source)
    if aggregation == "min":
        return exp.Min(this=source)
    if aggregation == "max":
        return exp.Max(this=source)
    if aggregation == "count":
        return exp.Count(this=source)
    if aggregation == "count_distinct":
        return exp.Count(this=exp.Distinct(expressions=[source]))
    raise ValueError(f"unsupported measure aggregation: {aggregation}")


def _period_bound_expressions(
    period: ReportPeriod,
    granularity: Literal["date", "month", "year"],
) -> tuple[exp.Expression, exp.Expression]:
    if granularity == "year":
        return exp.Literal.number(period.start.year), exp.Literal.number(period.end.year)
    if granularity == "month":
        return (
            exp.Literal.string(f"{period.start.year:04d}-{period.start.month:02d}"),
            exp.Literal.string(f"{period.end.year:04d}-{period.end.month:02d}"),
        )
    return (
        exp.Literal.string(period.start.isoformat()),
        exp.Literal.string(period.end.isoformat()),
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


def _planning_schema_payload_with_periods(
    snapshots: tuple[SourceSchemaSnapshot, ...],
    *,
    data_understanding: DataUnderstandingPlan,
    tables: set[str] | None = None,
    description_limit: int | None = None,
) -> list[dict[str, Any]]:
    """把 DataUnderstanding 的期间元数据合并进 Schema 的模型投影。

    DataUnderstanding 和 PlanningSchema 都按 source/table 标识同一张物理表。
    这里仅合并发送给 planner 的 JSON，不修改受信状态或 Pydantic 契约；服务端仍
    使用原始 DataUnderstanding 做字段、期间和身份校验。若某表未被选中，保持
    ``_planning_schema_payload`` 的筛选结果，不把额外表暴露给模型。
    """

    period_by_table = {
        (item.source_id.lower(), item.table.lower()): {
            "periodColumn": item.period_column,
            "periodGranularity": item.period_granularity,
        }
        for item in data_understanding.tables
    }
    payload = _planning_schema_payload(
        snapshots,
        tables=tables,
        description_limit=description_limit,
    )
    for schema in payload:
        for table in schema.get("tables", ()):
            if not isinstance(table, dict):
                continue
            key = (
                str(table.get("sourceId", "")).lower(),
                str(table.get("table", "")).lower(),
            )
            period = period_by_table.get(key)
            if period is not None:
                table.update(period)
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


def _project_measure_semantic_candidates(
    proposal: MeasureSemanticProposal,
    candidate_refs: tuple[str, ...],
) -> MeasureSemanticProposal:
    """只保留服务端签发的待确认字段，候选自身仍交由提交校验严格验证。"""

    allowed = set(candidate_refs)
    return proposal.model_copy(
        update={
            "decisions": tuple(
                decision for decision in proposal.decisions if decision.field_ref in allowed
            )
        }
    )


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
    if limit <= 0:
        return ""
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


def _restore_unapproved_correction_changes(
    previous: dict[str, Any],
    current: dict[str, Any],
    unexpected_paths: tuple[str, ...],
) -> dict[str, Any]:
    """以服务端基线恢复模型在纠错中越权改写的具体字段。"""

    projected = deepcopy(current)
    for path in unexpected_paths:
        if path == "$":
            return deepcopy(previous)
        tokens: list[str | int] = []
        for key, index in re.findall(r"([^.\[\]]+)|\[(\d+)]", path):
            tokens.append(int(index) if index else key)
        if not tokens:
            return deepcopy(previous)
        source: Any = previous
        target: Any = projected
        try:
            target_tokens = _current_correction_tokens(previous, projected, tokens)
            if target_tokens is None:
                return deepcopy(previous)
            for token, target_token in zip(tokens[:-1], target_tokens[:-1], strict=True):
                source = source[token]
                target = target[target_token]
            target[target_tokens[-1]] = deepcopy(source[tokens[-1]])
        except (IndexError, KeyError, TypeError):
            # 无法精确恢复说明候选改变了容器形状。此时回退整份可信基线，不能猜测
            # 列表身份或扩大允许修改范围；后续无进展门禁仍会按原规则失败关闭。
            return deepcopy(previous)
    return projected


def _current_correction_tokens(
    previous: Mapping[str, Any], current: Mapping[str, Any], tokens: list[str | int]
) -> list[str | int] | None:
    """把按 previous 下标给出的差异路径换算到 current 中同一业务对象的下标。

    _analysis_bundle_diff_paths 对 requirements/analyses 按业务标识比较，路径使用
    previous 下标；删除或重排后同一下标在 current 中是另一个对象，不能直接写回。
    """

    if len(tokens) < 2 or not isinstance(tokens[1], int):
        return tokens
    identity_key = {"requirements": "requirementId", "analyses": "code"}.get(str(tokens[0]))
    if identity_key is None:
        return tokens
    previous_items = previous.get(str(tokens[0]))
    current_items = current.get(str(tokens[0]))
    if not isinstance(previous_items, list) or not isinstance(current_items, list):
        return tokens
    previous_item = previous_items[tokens[1]] if tokens[1] < len(previous_items) else None
    identity = previous_item.get(identity_key) if isinstance(previous_item, Mapping) else None
    matches = [
        index
        for index, item in enumerate(current_items)
        if isinstance(item, Mapping) and item.get(identity_key) == identity
    ]
    if identity is None or len(matches) != 1:
        return None
    return [tokens[0], matches[0], *tokens[2:]]


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


def _analysis_validation_issues(error: ValidationError) -> list[dict[str, Any]]:
    """把 Pydantic 结构错误转换为分析计划纠错使用的稳定路径。"""

    candidates = [
        {
            "path": _validation_path(tuple(issue.get("loc") or ())),
            "rejectedValue": _bounded_rejected_value(issue.get("input")),
            "reason": str(issue.get("msg")),
            "type": str(issue.get("type") or ""),
        }
        for issue in error.errors()
    ]
    issues: list[dict[str, Any]] = []
    for candidate in candidates:
        path = str(candidate["path"])
        # Pydantic 会在叶节点失败后继续报告父 tuple 为空；父错误不是独立根因，若
        # 一并授权会把单字段修正扩大成整个 requirements 可改，破坏纠错范围门禁。
        if candidate["type"] == "too_short" and any(
            str(other["path"]).startswith(f"{path}[") or str(other["path"]).startswith(f"{path}.")
            for other in candidates
            if other is not candidate
        ):
            continue
        issues.append({key: value for key, value in candidate.items() if key != "type"})
    return issues


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
        allowed_candidates = [
            candidate
            for candidate in candidates
            if not any(
                candidate == prefix or candidate.startswith(f"{prefix}.")
                for prefix in deletion_prefixes
            )
        ]
        paths.extend(allowed_candidates)
        if previous_output is None:
            continue
        requirements = previous_output.get("requirements")
        if not isinstance(requirements, list):
            continue
        for candidate in allowed_candidates:
            match = re.fullmatch(r"requirements\[(\d+)]\.grainColumns", candidate)
            if match is None:
                continue
            requirement_index = int(match.group(1))
            if requirement_index >= len(requirements):
                continue
            requirement = requirements[requirement_index]
            relations = requirement.get("relations") if isinstance(requirement, Mapping) else None
            if not isinstance(relations, list):
                continue
            # 多表 requirement 的 grainColumns 与关联键必须同步；这里只授权可信
            # 基线中已存在 relation 的 joinColumns，不允许模型新增关联或改写表身份。
            paths.extend(
                f"requirements[{requirement_index}].relations[{relation_index}].joinColumns"
                for relation_index, relation in enumerate(relations)
                if isinstance(relation, Mapping)
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


def _outline_candidate(error: ValidationError) -> dict[str, Any] | None:
    """从响应校验异常中恢复候选载荷，作为纠错 previousOutput 基线。

    优先使用校验边界附带的 _report_candidate（解码后的原始 JSON），它在字段级
    校验失败时仍能给出整体结构；退化到模型级 error.input，最后返回 None。
    """
    candidate = getattr(error, "_report_candidate", None)
    if isinstance(candidate, Mapping):
        return dict(candidate)
    for issue in error.errors():
        if not issue.get("loc"):
            value = issue.get("input")
            if isinstance(value, Mapping):
                return dict(value)
    return None


def _outline_validation_issues(error: ValidationError) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for issue in error.errors():
        loc = issue.get("loc") or ()
        path = ".".join(str(part) for part in loc) or "sections"
        issues.append(
            {
                "path": path,
                "rejectedValue": _bounded_rejected_value(issue.get("input")),
                "reason": str(issue.get("msg")),
            }
        )
    return issues


def _outline_allowed_paths(issues: list[dict[str, Any]]) -> tuple[str, ...]:
    allowed_fields = {"reportType", "title", "sections", "assumptions"}
    paths: list[str] = []
    for issue in issues:
        raw_path = issue.get("path")
        path = raw_path.split(".", 1)[0] if isinstance(raw_path, str) else ""
        if path in allowed_fields and path not in paths:
            paths.append(path)
    return tuple(paths) or ("sections",)


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


def _row_preserving_requirement_ids(
    requirements: tuple[QueryRequirement, ...],
    profile: EffectiveReportingProfile,
) -> tuple[str, ...]:
    """只有当前 Profile 明确声明重复冲突策略时才允许保留原始行。"""
    # EffectiveReportingProfile 是跨领域公共契约，不包含医院旧 Profile 的
    # duplicateConflicts 扩展；未声明该能力时必须关闭而不是猜测表名。
    governed_tables = {
        str(rule.table_ref).rsplit(".", 1)[-1].lower()
        for rule in getattr(profile, "duplicate_conflicts", ())
        if getattr(rule, "table_ref", None)
    }
    if not governed_tables:
        return ()
    return tuple(
        requirement.requirement_id
        for requirement in requirements
        if len(requirement.tables) == 1
        and requirement.tables[0].table.rsplit(".", 1)[-1].lower() in governed_tables
    )


def _validate_reporting_profile_schema(
    profile: EffectiveReportingProfile,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> None:
    """启动前核对当前 Profile 的物理字段，避免列名漂移到 CSV 后才暴露。"""
    table_columns = {
        (table.source_id.lower(), table.database.lower(), table.name.lower()): {
            column.name.lower() for column in table.columns
        }
        for snapshot in snapshots
        for table in snapshot.tables
    }
    missing: list[str] = []
    field_refs = tuple(item.field_ref for item in profile.metrics if item.field_ref is not None)
    field_refs += tuple(field_ref for item in profile.dimensions for field_ref in item.field_refs)
    field_refs += tuple(
        field_ref for item in profile.scope_filters for field_ref in item.field_refs
    )
    field_refs += tuple(item.field_ref for item in profile.measure_semantics)
    field_refs += tuple(
        item.reconcile_with for item in profile.measure_semantics if item.reconcile_with is not None
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
            "report_profile_schema_mismatch",
            "报表 Profile 与当前 Schema 不一致：" + ", ".join(sorted(missing)),
        )


def _approve_generated_queries(
    generated: GeneratedQueryBatch,
    *,
    sources: dict[str, StarRocksSourceConfig],
    snapshots: tuple[SourceSchemaSnapshot, ...],
    envelope: ReportRequestEnvelope,
    requirements: tuple[QueryRequirement, ...],
    row_preserving_requirement_ids: tuple[str, ...] = (),
    data_shapes: tuple[DataShape, ...] = (),
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
                data_shapes=data_shapes,
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


_TYPED_PERIOD_TYPE = re.compile(r"^(?:DATE|DATETIME|TIMESTAMP)\b")
# 审计时间戳几乎从不代表业务期间；存在业务日期列时不参与候选。
_AUDIT_TIME_COLUMN = re.compile(
    r"(?:^|_)(?:created?|updated?|modified|insert(?:ed)?|etl|load(?:ed)?|sync(?:ed)?)(?:_|$)"
    r"|创建|更新|修改|入库|同步|抽取",
)
# 所有日期列都会共享的泛化词元不能区分候选，避免“日期”“数据”等把任意列判为匹配。
_PERIOD_GENERIC_TERMS = frozenset(
    {"date", "time", "at", "dt", "data", "day", "日期", "时间", "数据", "期间"}
)


def _period_terms(text: str) -> frozenset[str]:
    terms = {item for item in re.split(r"[^a-z0-9]+", text.casefold()) if item}
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        terms.update(run[index : index + 2] for index in range(len(run) - 1))
    return frozenset(terms - _PERIOD_GENERIC_TERMS)


def _preferred_typed_period_column(
    columns: tuple[Any, ...], *, reference_text: str
) -> Any | None:
    """在类型化日期列中选出与当前期间字段、表用途和报告目标唯一最相关的一列。

    只有一列时直接采用；多列时按词元重合度选唯一最高分，并在存在业务日期列时排除
    审计时间戳。无法唯一判定时返回 None 保留模型选择，不能把出生日期、创建时间等
    列静默冻结为报告期间口径。
    """

    typed = [
        column for column in columns if _TYPED_PERIOD_TYPE.match(column.data_type.strip().upper())
    ]
    business = [
        column
        for column in typed
        if _AUDIT_TIME_COLUMN.search(f"{column.name.casefold()} {column.description}") is None
    ]
    candidates = business or typed
    if len(candidates) <= 1:
        return candidates[0] if candidates else None
    reference = _period_terms(reference_text)
    scores = [
        len(reference & _period_terms(f"{column.name} {column.description}"))
        for column in candidates
    ]
    best = max(scores)
    if best == 0 or scores.count(best) != 1:
        loguru_logger.bind(
            candidates=[column.name for column in candidates], scores=scores
        ).warning("report_period_typed_column_ambiguous")
        return None
    return candidates[scores.index(best)]


def _normalize_preferred_typed_period_fields(
    plan: DataUnderstandingPlan,
    snapshots: tuple[SourceSchemaSnapshot, ...],
    *,
    report_goal: str,
) -> DataUnderstandingPlan:
    """用户未指定代码口径时，优先冻结可精确过滤的类型化日期字段。"""

    goal = report_goal.casefold()
    explicitly_requests_code = any(
        marker in goal for marker in ("期间码", "月份代码", "月度代码", "代码口径")
    )
    tables = {
        (table.source_id, f"{table.database}.{table.name}".casefold()): table
        for snapshot in snapshots
        for table in snapshot.tables
    }
    normalized: list[DataUnderstandingTable] = []
    changed = False
    for selected in plan.tables:
        table = tables.get((selected.source_id, selected.table.casefold()))
        current_is_explicit = selected.period_column.casefold() in goal
        if table is None or explicitly_requests_code or current_is_explicit:
            normalized.append(selected)
            continue
        current = next(
            (
                column
                for column in table.columns
                if column.name.casefold() == selected.period_column.casefold()
            ),
            None,
        )
        if current is None or re.match(
            r"^(?:DATE|DATETIME|TIMESTAMP)\b", current.data_type.strip().upper()
        ):
            normalized.append(selected)
            continue
        preferred = _preferred_typed_period_column(
            table.columns,
            reference_text=" ".join(
                (current.name, current.description, selected.role, report_goal)
            ),
        )
        if preferred is None:
            normalized.append(selected)
            continue
        normalized.append(
            selected.model_copy(
                update={"period_column": preferred.name, "period_granularity": "date"}
            )
        )
        changed = True
    return plan.model_copy(update={"tables": tuple(normalized)}) if changed else plan


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
