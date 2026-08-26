# mypy: disable-error-code="attr-defined"
# 运行时由 Facade 组合的多重继承提供跨阶段成员；静态检查无法解析该装配。
from __future__ import annotations

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
    AnalysisBundle,
    Any,
    ApprovedQuery,
    BaseModel,
    DataShape,
    DataUnderstandingPlan,
    DetailedAnalysisPlan,
    GeneratedQueryBatch,
    MeasureSemanticProposal,
    NormalizedReportPrompt,
    QueryRequirement,
    ReconciliationShape,
    ReportArtifactSpec,
    ReportDownloadScope,
    ReportingCheckpoint,
    ReportingError,
    ReportingWorkflowInput,
    ReportOutline,
    ReportOutlineProposal,
    ReportPromptInput,
    ReportRequestEnvelope,
    RunContext,
    SourceSchemaSnapshot,
    StarRocksDataSourceAdapter,
    StarRocksSourceConfig,
    StepInput,
    StepOutput,
    TaskState,
    ValidationError,
    _analysis_allowed_mutation_paths,
    _analysis_context_payload,
    _analysis_required_deletion_paths,
    _apply_confirmed_measure_semantics,
    _apply_profile_scope_filters_to_snapshots,
    _approve_generated_queries,
    _bounded_rejected_value,
    _catalog_scope,
    _compact_validation_feedback,
    _data_understanding_result,
    _explicit_report_type,
    _measure_semantic_candidate_refs,
    _model_table,
    _payload_sha256,
    _planning_schema_payload,
    _proposal_with_profile_scope_filters,
    _resolved_report_type,
    _row_preserving_requirement_ids,
    _schema_scope_tables,
    _single_explicit_year,
    _unexpected_correction_paths,
    _validate_hospital_operation_profile_schema,
    _validate_proposed_exclusive_scopes,
    anyio,
    build_outline_shape_view,
    cli_result,
    collect_data_shape,
    complete_cleanup,
    freeze_outline,
    json,
    logger,
    loguru_logger,
    parse_field_ref,
    parse_reporting_workflow_input,
    publication_result,
    require_sources,
    resolve_domain_mentions,
    resolve_profile_capabilities,
    resolve_schema_snapshot,
    ruijin_profile,
)
from .validation import (
    _analysis_bundle_semantic_issues,
    _normalize_analysis_bundle_grain,
    _normalize_comparison_roles,
    _normalize_duplicate_requirements,
    _normalize_requirement_columns,
    _normalize_requirement_columns_in_payload,
    _normalize_requirement_periods,
)

__all__ = ["RuntimePlanningMixin", "_PLANNER_DISPLAY_NAMES"]


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
        await self._destroy_or_quarantine_workspace(
            scope["thread_id"],
            message="报表工作流已结束，但运行环境删除失败，已隔离并转入后台清理。",
        )

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
        await self._destroy_or_quarantine_workspace(
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
