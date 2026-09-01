# mypy: disable-error-code="attr-defined"
# 运行时由 facade 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。
from __future__ import annotations

from typing import Literal

from ..checkpoint import CheckpointRetryUsage
from .base import (
    _VISUALIZATION_RECOVERY_ERROR_CODES,
    MAX_REPORT_INSTRUCTION_BYTES,
    MAX_REPORT_SECTION_PHASE_ATTEMPTS,
    REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY,
    REPORT_DOCUMENT_GENERATED_DATE_STATE_KEY,
    REPORT_OUTLINE_HASH_STATE_KEY,
    REPORT_OUTLINE_STATE_KEY,
    REPORT_VISUAL_THEME,
    REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR,
    REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
    AnalysisArtifact,
    AnalysisReworkRequest,
    Any,
    Awaitable,
    BaseModel,
    Callable,
    Citation,
    ContextTrace,
    DatasetAnalysisContext,
    DatasetHandle,
    DatasetLineage,
    DetailedAnalysisPlan,
    DeterministicAnalysisBundle,
    DurableReportingPhase,
    FileIdentity,
    Mapping,
    OpenAIChat,
    ProfileCoverageManifest,
    ReportingCheckpoint,
    ReportingCommand,
    ReportingError,
    ReportingStateError,
    ReportOutline,
    RunContext,
    Sequence,
    StepInput,
    StepOutput,
    TaskScope,
    TaskState,
    ValidationError,
    WorkspaceService,
    ZoneInfo,
    _frozen_outline,
    _payload_sha256,
    _source_warnings_from_state,
    anyio,
    asyncio,
    build_deterministic_analysis_bundle,
    build_report_phase_acceptance_contract,
    cast,
    date,
    datetime,
    hashlib,
    json,
    logger,
    loguru_logger,
    partial,
    payload_sha256,
    re,
    reporting_phase_task_key,
    reporting_thinking_profile_from_model,
    time,
    validate_metric_code_bindings,
)
from .datasets import _profile_coverage_instruction_projection

__all__ = ["RuntimeAnalysisMixin", "_visualization_retry_budget"]


def _analysis_fact_query_limit_for_plan(analysis_plan: Mapping[str, Any]) -> int:
    """按当前分析项复杂度分配事实查询额度，并保留硬上限。"""

    metrics = analysis_plan.get("metrics") if isinstance(analysis_plan, Mapping) else None
    datasets = analysis_plan.get("datasetIds") if isinstance(analysis_plan, Mapping) else None
    periods = analysis_plan.get("periods") if isinstance(analysis_plan, Mapping) else None
    complexity = sum(
        len(value) for value in (metrics, datasets, periods) if isinstance(value, (list, tuple))
    )
    return min(8, max(4, 2 + (complexity + 2) // 3))


class RuntimeAnalysisMixin:
    async def _run_visualization_finalize(
        self,
        *,
        task_scope: TaskScope,
        instruction: str,
        acceptance_contract: dict[str, Any],
        parent_run_id: str,
    ) -> Mapping[str, Any]:
        """启动并运行汇总 Task；产物冻结仍由调用方按 receipt 做身份校验。"""
        task_id = task_scope.external_run_id
        existing = await self.task_runner.repository.get_task_snapshot(task_id)
        if existing is None:
            await self.task_runner.start(
                task_scope, instruction, acceptance_contract=acceptance_contract
            )
        elif existing.state in {TaskState.FAILED, TaskState.CANCELLED}:
            raise ReportingError(
                "report_analysis_task_terminal", "可视化汇总 Task 已在未签发阶段产物前终止。"
            )
        return await self.task_runner.run(task_scope, parent_run_id=parent_run_id)

    async def _run_visualization_section_task(self, section_code: str) -> None:
        """执行单章图表 worker；章节草案由 durable submit 工具作为唯一完成信号。

        失败按 sectionCode 记入 checkpoint 账本并驱动同章 fresh retry(上限
        MAX_REPORT_SECTION_PHASE_ATTEMPTS);重试章继承已消耗预算并关闭探索
        (visualizationRecovery),已完成章由入口 durable 判定直接跳过。
        """
        context = self._visualization_context
        run_context = context["run_context"]
        checkpoint = await self._current_reporting_checkpoint(run_context, context["checkpoint"])
        outline = _frozen_outline(self._state(run_context))
        section = next((item for item in outline.sections if item.code == section_code), None)
        if section is None:
            raise ReportingError("report_visualization_section_invalid", "提纲中不存在当前章节。")
        durable = await self.state_repository.get(
            str(run_context.run_id or context["external_run_id"])
        )
        payload = durable.payload if durable is not None else {}
        completed = payload.get("completedVisualizationSections", ())
        if section_code in completed:
            return
        analysis_items = payload.get("analysisItems", {})
        facts = []
        section_analysis_items: dict[str, Mapping[str, Any]] = {}
        section_fact_files: dict[str, FileIdentity] = {}
        for analysis_id in section.analysis_ids:
            fact_file = context["fact_files"].get(analysis_id)
            durable_item = (
                analysis_items.get(analysis_id) if isinstance(analysis_items, Mapping) else None
            )
            if fact_file is None or not isinstance(durable_item, Mapping):
                raise ReportingError(
                    "report_analysis_evidence_incomplete",
                    f"章节 {section_code} 缺少 analysisId {analysis_id} 的冻结 facts 或 durable 分析项。",
                )
            facts.append(
                await self._visualization_section_fact_projection(
                    analysis_id, fact_file, durable_item
                )
            )
            section_analysis_items[analysis_id] = durable_item
            section_fact_files[analysis_id] = fact_file
        # 按章动态预算以该章 analysisIds 的 evidence/fact 文件为基数,与全局汇总预算
        # 同构但互不共享;TaskRunner 解析(visualizationBudgetVersion 等 10 个标量)
        # 缺一即拒绝,因此必须整组注入 acceptance contract。
        section_budget = _visualization_dynamic_budget(section_analysis_items, section_fact_files)
        last_error: Exception | None = _visualization_section_retry_error(
            checkpoint, section_code=section_code
        )
        matching = [
            item
            for item in checkpoint.trace
            if item.phase == "analysis"
            and item.work_kind == "visualization_section"
            and item.section_code == section_code
        ]
        next_attempt = max((item.attempt for item in matching), default=-1) + 1
        if next_attempt >= MAX_REPORT_SECTION_PHASE_ATTEMPTS:
            raise ReportingError(
                "report_visualization_section_attempts_exhausted",
                "章节图表 fresh attempt 已达到上限，拒绝创建新的 Task。",
            )
        scope = self._scope(run_context)
        for attempt in range(next_attempt, MAX_REPORT_SECTION_PHASE_ATTEMPTS):
            root = f"报表/智能分析/{run_context.run_id}/analysis/charts/{section_code}/attempt-{attempt + 1}"
            task_id = reporting_phase_task_key(
                str(run_context.run_id or "report"),
                context["revision"],
                "analysis",
                section_code=section_code,
                task_kind="visualization_section",
                attempt=attempt,
            )
            script_path = f"{root}/charts.py"
            instruction_payload = {
                "phase": "analysis",
                "taskKind": "visualization_section",
                "sectionCode": section_code,
                "section": section.model_dump(mode="json", by_alias=True),
                "analysisIds": list(section.analysis_ids),
                "visualInspectionMode": context["visual_inspection_mode"],
                "visualizationFacts": facts,
                "visualizationWorkspace": {
                    "scriptPath": script_path,
                    "chartOutputRoot": root,
                    "allowedTerminalCommand": f"python3 {script_path}",
                },
                "completionConditions": _visualization_section_completion_conditions(last_error),
            }
            instruction = json.dumps(instruction_payload, ensure_ascii=False, separators=(",", ":"))
            if len(instruction.encode("utf-8")) > MAX_REPORT_INSTRUCTION_BYTES:
                raise ReportingError(
                    "report_analysis_context_too_large", "单章可视化投影超过输入边界。"
                )
            contract = build_report_phase_acceptance_contract(
                phase="analysis",
                validation_context_file=context["validation_context_file"].model_dump(
                    mode="json", by_alias=True
                ),
                phase_contract={
                    "reportRunId": str(run_context.run_id or context["external_run_id"]),
                    "taskKind": "visualization_section",
                    "sectionCode": section_code,
                    "analysisIds": list(section.analysis_ids),
                    "visualInspectionMode": context["visual_inspection_mode"],
                    "visualizationRecovery": _visualization_recovery_required(last_error),
                    **section_budget,
                    **_visualization_retry_usage(last_error),
                    "visualizationWorkspace": {
                        "scriptPath": script_path,
                        "chartOutputRoot": root,
                    },
                },
                analysis_output_path=f"{root}/section.json",
            )
            task_scope = TaskScope(
                task_id,
                scope["userId"],
                scope["threadId"],
                context["sandbox_id"],
                str(self.report_worker.id),
            )
            checkpoint = self._update_reporting_checkpoint(
                checkpoint,
                trace=(
                    *checkpoint.trace,
                    ContextTrace(
                        phase="analysis",
                        taskId=task_id,
                        workKind="visualization_section",
                        sectionCode=section_code,
                        attempt=attempt,
                        instructionBytes=len(instruction.encode("utf-8")),
                        projectedContextBytes=len(instruction.encode("utf-8")),
                        visualInspectionMode=context["visual_inspection_mode"],
                    ),
                ),
            )
            await self._persist_reporting_checkpoint(run_context, checkpoint)
            try:
                existing = await self.task_runner.repository.get_task_snapshot(task_id)
                if existing is None:
                    await self.task_runner.start(
                        task_scope, instruction, acceptance_contract=contract
                    )
                elif existing.state in {TaskState.FAILED, TaskState.CANCELLED}:
                    raise ReportingError(
                        "report_visualization_section_task_terminal",
                        "章节图表 Task 未完成收尾即终止。",
                    )
                await self.task_runner.run(task_scope, parent_run_id=str(run_context.run_id or ""))
                latest = await self.state_repository.get(
                    str(run_context.run_id or context["external_run_id"])
                )
                latest_payload = latest.payload if latest is not None else {}
                if section_code not in latest_payload.get("completedVisualizationSections", ()):
                    raise ReportingError(
                        "report_visualization_section_incomplete", "章节图表 durable 收口缺失。"
                    )
                checkpoint = self._replace_trace(checkpoint, task_id, status="completed")
                checkpoint = self._update_reporting_checkpoint(
                    checkpoint,
                    visualization_section_errors={
                        key: value
                        for key, value in checkpoint.visualization_section_errors.items()
                        if key != section_code
                    },
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
                return
            except Exception as error:
                last_error = error
                checkpoint = self._replace_trace(checkpoint, task_id, status="failed")
                checkpoint = self._update_reporting_checkpoint(
                    checkpoint,
                    visualization_section_errors={
                        **checkpoint.visualization_section_errors,
                        section_code: {
                            "phase": "analysis",
                            "code": getattr(error, "code", "report_visualization_section_failed"),
                            "message": str(getattr(error, "message", error))[:2000],
                            "sectionCode": section_code,
                            "taskId": task_id,
                            "workKind": "visualization_section",
                            "attempt": attempt,
                            "retryUsage": _checkpoint_retry_usage(
                                error, work_kind="visualization_section"
                            ).model_dump(mode="json", by_alias=True),
                        },
                    },
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
        assert last_error is not None
        raise last_error

    async def _visualization_section_fact_projection(
        self,
        analysis_id: str,
        fact_file: FileIdentity,
        durable_item: Any,
    ) -> dict[str, Any]:
        fact_model = await self._read_identity_model(
            self._visualization_context["thread_id"], fact_file, DeterministicAnalysisBundle
        )
        payload = fact_model.model_dump(mode="json", by_alias=True)
        return {
            "analysisId": analysis_id,
            "factFile": fact_file.model_dump(mode="json", by_alias=True),
            "summary": durable_item.get("summary") if isinstance(durable_item, Mapping) else None,
            "metrics": [
                {
                    "metricIndex": index,
                    **{
                        key: metric.get(key)
                        for key in (
                            "datasetId",
                            "field",
                            "metricCodes",
                            "aggregation",
                            "unit",
                            "scope",
                            "periodRoles",
                            "periodStart",
                            "periodEnd",
                            "total",
                        )
                    },
                    "periodValueCount": len(metric.get("periodValues", ())),
                    "topGroupCount": len(metric.get("topGroups", ())),
                    "bottomGroupCount": len(metric.get("bottomGroups", ())),
                    "dataPaths": {
                        "metric": f"metrics[{index}]",
                        "periodValues": f"metrics[{index}].periodValues",
                        "topGroups": f"metrics[{index}].topGroups",
                        "bottomGroups": f"metrics[{index}].bottomGroups",
                    },
                }
                for index, metric in enumerate(payload.get("metrics", ()))
                if isinstance(metric, Mapping)
            ],
            "derivedMetrics": [
                {
                    "derivedMetricIndex": index,
                    **{
                        key: metric.get(key)
                        for key in (
                            "code",
                            "kind",
                            "unit",
                            "periodRole",
                            "periodStart",
                            "periodEnd",
                            "datasetIds",
                            "value",
                            "percentage",
                        )
                    },
                    "dataPath": f"derivedMetrics[{index}]",
                }
                for index, metric in enumerate(payload.get("derivedMetrics", ()))
                if isinstance(metric, Mapping)
            ],
            "comparisons": [
                {
                    "comparisonIndex": index,
                    **{
                        key: item.get(key)
                        for key in (
                            "comparisonType",
                            "field",
                            "unit",
                            "periodStart",
                            "periodEnd",
                            "currentDatasetId",
                            "baselineDatasetId",
                            "currentTotal",
                            "baselineTotal",
                            "change",
                            "changeRate",
                        )
                    },
                    "dataPath": f"comparisons[{index}]",
                }
                for index, item in enumerate(payload.get("comparisons", ()))
                if isinstance(item, Mapping)
            ],
            "evidenceFiles": durable_item.get("evidenceFiles", [])
            if isinstance(durable_item, Mapping)
            else [],
            "citationIds": durable_item.get("citationIds", [])
            if isinstance(durable_item, Mapping)
            else [],
        }

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
                "sectionNumbers": [section.section_number for section in outline.sections],
                "sections": [
                    {
                        "code": section.code,
                        "sectionNumber": section.section_number,
                        "title": section.title,
                    }
                    for section in outline.sections
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
        current_fact_files = current.deterministic_fact_files
        incoming_fact_files = incoming.deterministic_fact_files
        if current_fact_files and incoming_fact_files and current_fact_files != incoming_fact_files:
            raise ReportingError(
                "report_checkpoint_conflict",
                "并发任务 checkpoint 与当前确定性 facts 身份不一致。",
            )
        deterministic_fact_files = current_fact_files or incoming_fact_files
        merged_files = RuntimeAnalysisMixin._merge_checkpoint_files(current.files, *incoming.files)
        merged_files_by_path = {item.path: item for item in merged_files}
        if any(
            identity.path in merged_files_by_path
            and merged_files_by_path[identity.path] != identity
            for identity in deterministic_fact_files.values()
        ):
            raise ReportingError(
                "report_checkpoint_conflict",
                "并发任务 files 账本试图覆盖已冻结的确定性 facts 身份。",
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
        section_errors = dict(current.visualization_section_errors)
        for section_code, error in incoming.visualization_section_errors.items():
            existing = section_errors.get(section_code)
            # checkpoint 持久化可乱序回放；同章账本只能由更高 attempt，或同 attempt
            # 的确定性 taskId 覆盖。否则旧 worker 的失败写回会抹掉新 worker 的恢复预算。
            if existing is None or (
                error.attempt if error.attempt is not None else -1,
                error.task_id or "",
            ) >= (
                existing.attempt if existing.attempt is not None else -1,
                existing.task_id or "",
            ):
                section_errors[section_code] = error
        for section_code, error in tuple(section_errors.items()):
            completed_attempts = (
                (item.attempt, item.task_id or "")
                for item in (*current.trace, *incoming.trace)
                if item.work_kind == "visualization_section"
                and item.status == "completed"
                and item.section_code == section_code
            )
            if any(
                completed_identity
                >= (error.attempt if error.attempt is not None else -1, error.task_id or "")
                for completed_identity in completed_attempts
            ):
                section_errors.pop(section_code)
        merged_phase = incoming.phase
        if current.phase == "completed" or incoming.phase == "completed":
            merged_phase = "completed"
        elif current.phase == "finalize" or incoming.phase == "finalize":
            merged_phase = "finalize"
        elif not freezes_analysis and (current.phase == "analysis" or incoming.phase == "analysis"):
            merged_phase = "analysis"
        return RuntimeAnalysisMixin._update_reporting_checkpoint(
            incoming,
            phase=merged_phase,
            completed_sections=tuple(completed_by_code.values()),
            pending_sections=pending,
            warnings=tuple((*current.warnings, *incoming.warnings)[-500:]),
            last_error=incoming.last_error or current.last_error,
            deterministic_fact_files=dict(deterministic_fact_files),
            visualization_section_errors=section_errors,
            files=merged_files,
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
            if (
                stored_checkpoint.get("version") == "1"
                and stored_checkpoint.get("phase") != "completed"
            ):
                raise ReportingError(
                    "report_semantic_contract_upgrade_required",
                    "运行中的 v1 checkpoint 缺少 v2 语义契约，必须重新分析。",
                )
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
        return RuntimeAnalysisMixin._update_reporting_checkpoint(checkpoint, trace=tuple(traces))

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

    @staticmethod
    def _instruction_component_bytes(payload: Mapping[str, Any]) -> dict[str, int]:
        """按主要上下文字段统计 UTF-8 字节数，不记录字段内容。"""
        components = (
            ("current_analysis", "currentAnalysis"),
            ("deterministic_facts", "deterministicFacts"),
            ("profile_coverage", "profileCoverage"),
            ("analysis_context_file", "analysisContextFile"),
            ("datasets", "datasets"),
            ("dataset_lineage", "datasetLineage"),
            ("citation_registry", "citationRegistry"),
            ("completion_conditions", "completionConditions"),
            ("durable_analysis_item", "durableAnalysisItem"),
            ("outline", "outline"),
            ("registered_charts", "registeredCharts"),
            ("analysis_plans", "analysisPlans"),
            ("analysis_citation_ids", "analysisCitationIds"),
            ("citation_dataset_ids", "citationDatasetIds"),
            ("deterministic_fact_files", "deterministicFactFiles"),
            ("visualization_facts", "visualizationFacts"),
            ("dataset_semantics", "datasetSemantics"),
            ("metric_definitions", "metricDefinitions"),
            ("section_evidence_catalog", "sectionEvidenceCatalog"),
            ("chart_registration_rules", "chartRegistrationRules"),
            ("visualization_workspace", "visualizationWorkspace"),
            ("source_warnings", "sourceWarnings"),
            ("review_feedback", "reviewFeedback"),
        )
        return {
            name: len(
                json.dumps(payload[field], ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            for name, field in components
            if field in payload
        }

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
        coding_analysis_plan = _coding_detailed_analysis_plan(
            detailed_plan,
            analysis_ids=(analysis_id,),
        )
        analysis_plan = coding_analysis_plan["analyses"][0]
        deterministic_facts = cast(
            DeterministicAnalysisBundle,
            await self._read_identity_model(
                scope["threadId"], fact_files[analysis_id], DeterministicAnalysisBundle
            ),
        )
        if deterministic_facts.analysis_id != analysis_id:
            raise ReportingError(
                "report_analysis_facts_invalid",
                "固定 facts 文件与当前分析项身份不一致。",
            )
        last_error: Exception | None = _checkpoint_retry_error(
            checkpoint,
            work_kind="analysis_item",
            analysis_id=analysis_id,
            retry_reason=retry_reason,
        )

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
                        "metrics",
                        "chartIds",
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
                "deterministicFacts": deterministic_facts.model_dump(mode="json", by_alias=True),
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
            instruction_component_bytes = self._instruction_component_bytes(instruction_payload)
            instruction = json.dumps(instruction_payload, ensure_ascii=False, separators=(",", ":"))
            instruction_bytes = len(instruction.encode("utf-8"))
            if instruction_bytes > MAX_REPORT_INSTRUCTION_BYTES:
                raise ReportingError(
                    "report_analysis_context_too_large",
                    "单项分析投影超过模型输入边界；证据未被静默截断。",
                )
            retry = any(item.status == "failed" for item in matching_traces)
            analysis_fact_queries_used = _analysis_fact_retry_usage(last_error)
            analysis_recovery = _analysis_fact_recovery_required(last_error)
            contract = build_report_phase_acceptance_contract(
                phase="analysis",
                validation_context_file=validation_context_file.model_dump(
                    mode="json", by_alias=True
                ),
                phase_contract={
                    "reportRunId": report_run_id,
                    "taskKind": "analysis_item",
                    # 单项分析首次继承 Worker 的 high 档位；只有服务端判定上一次尝试
                    # 失败时才升为 max。全局关闭 thinking 时 Worker 策略仍会返回 off。
                    "thinkingEffort": self._worker_thinking_effort(retry=retry),
                    "analysisIds": [analysis_id],
                    "currentAnalysisId": analysis_id,
                    "analysisFactBudgetVersion": 1,
                    "analysisFactQueryLimit": _analysis_fact_query_limit_for_plan(analysis_plan),
                    "analysisFactQueriesUsed": analysis_fact_queries_used,
                    "analysisRecovery": analysis_recovery,
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
                    "component_bytes=%s tool_events=%s attempt=%s retry_reason=%s",
                    analysis_id,
                    task_id,
                    instruction_bytes,
                    trace_metrics["duration_seconds"],
                    instruction_component_bytes,
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
                        "taskId": task_id,
                        "workKind": "analysis_item",
                        "analysisId": analysis_id,
                        "attempt": attempt,
                        "retryUsage": _checkpoint_retry_usage(
                            error, work_kind="analysis_item"
                        ).model_dump(mode="json", by_alias=True),
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
        checkpoint, fact_files = await self._restore_or_create_deterministic_analysis_facts(
            run_context=run_context,
            checkpoint=checkpoint,
            thread_id=scope["threadId"],
            report_run_id=str(run_context.run_id or scope["externalRunId"]),
            revision=revision,
            detailed_plan=detailed_plan,
            dataset_handles=dataset_handles,
        )
        analysis_ids = tuple(item.analysis_id for item in detailed_plan.analyses)
        candidate_analysis_ids = (
            rework_request.analysis_ids if rework_request is not None else analysis_ids
        )
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
            candidate_analysis_ids,
            completed_analysis_ids=completed_task_ids,
            concurrency=self.analysis_concurrency,
            worker=run_one,
        )
        if scheduled_analysis_ids:
            checkpoint = await self._current_reporting_checkpoint(run_context, checkpoint)
        visual_inspection_mode: Literal["vision", "deterministic"] = (
            "vision"
            if getattr(getattr(self.report_worker, "model", None), "_report_vision_enabled", True)
            else "deterministic"
        )
        _ensure_visual_inspection_capability(checkpoint, visual_inspection_mode)
        self._visualization_context = {
            "run_context": run_context,
            "checkpoint": checkpoint,
            "revision": revision,
            "sandbox_id": sandbox_id,
            "external_run_id": str(run_context.run_id or scope["externalRunId"]),
            "thread_id": scope["threadId"],
            "validation_context_file": validation_context_file,
            "fact_files": fact_files,
            "visual_inspection_mode": visual_inspection_mode,
        }
        durable_visualization = await self.state_repository.get(
            str(run_context.run_id or scope["externalRunId"])
        )
        visualization_payload = (
            durable_visualization.payload if durable_visualization is not None else {}
        )
        completed_visualization_sections = {
            item
            for item in visualization_payload.get("completedVisualizationSections", ())
            if isinstance(item, str)
        }
        raw_outline = self._state(run_context).get(REPORT_OUTLINE_STATE_KEY)
        outline = (
            _frozen_outline(self._state(run_context))
            if isinstance(raw_outline, Mapping) and "sections" in raw_outline
            else None
        )
        section_codes = (
            tuple(section.code for section in outline.sections) if outline is not None else ()
        )
        await _run_pending_visualization_sections(
            section_codes,
            completed_section_codes=completed_visualization_sections,
            concurrency=getattr(self, "visualization_concurrency", 1),
            worker=self._run_visualization_section_task,
        )
        checkpoint = await self._current_reporting_checkpoint(run_context, checkpoint)
        last_error: Exception | None = _checkpoint_retry_error(
            checkpoint,
            work_kind="visualization_finalize",
            analysis_id=None,
            retry_reason=retry_reason,
        )
        _ensure_visual_inspection_capability(checkpoint, visual_inspection_mode)
        # finalize 的 Dataset 语义必须来自本次已授权的 snapshot；空 handles 没有可绑定的
        # 身份和语义，继续构造空目录会把不完整输入交给 worker，并可能产生无效 finalize
        # Task。此校验位于 finalize Task 启动前，确保运行时边界直接拒绝且不产生副作用。
        if not dataset_handles:
            raise ReportingError(
                "report_analysis_dataset_inconsistent",
                "可视化汇总缺少授权 Dataset snapshot。",
            )

        # 图表 Worker 需要一次拿到完整的、已校验身份的事实包；把 facts 读取放在
        # Workflow 边界而不是交给模型反复 query/read，消除日志中因路径歧义产生的
        # 探索往返。包只在本次 visualization 阶段首次构建，fresh retry 复用内存对象，
        # 不重新下载或计算 deterministic facts。
        visualization_facts_package: list[dict[str, Any]] | None = None
        fact_bundles: dict[str, dict[str, Any]] = {}

        for _ in range(MAX_REPORT_SECTION_PHASE_ATTEMPTS):
            started_trace = next(
                (
                    item
                    for item in reversed(checkpoint.trace)
                    if item.phase == "analysis"
                    and item.work_kind == "visualization_finalize"
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
                        if item.phase == "analysis" and item.work_kind == "visualization_finalize"
                    ),
                    default=-1,
                )
                + 1
            )
            task_id = reporting_phase_task_key(
                str(run_context.run_id or "report"),
                revision,
                "analysis",
                task_key="viz-finalize",
                task_kind="visualization_finalize",
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
            visualization_payload = durable_payload
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
                    "organizationGrain": list(item.organization_grain),
                }
                for item in detailed_plan.analyses
            }
            analysis_items = durable_payload.get("analysisItems")
            visualization_budget = _visualization_dynamic_budget(analysis_items, fact_files)
            if visualization_facts_package is None:
                visualization_facts_package = []
                for analysis in detailed_plan.analyses:
                    fact_model = await self._read_identity_model(
                        scope["threadId"],
                        fact_files[analysis.analysis_id],
                        DeterministicAnalysisBundle,
                    )
                    fact_payload = fact_model.model_dump(mode="json", by_alias=True)
                    fact_bundles[analysis.analysis_id] = fact_payload
                    raw_metrics = fact_payload.get("metrics", [])
                    raw_derived_metrics = fact_payload.get("derivedMetrics", [])
                    raw_comparisons = fact_payload.get("comparisons", [])
                    durable_item = (
                        analysis_items.get(analysis.analysis_id)
                        if isinstance(analysis_items, Mapping)
                        else None
                    )
                    visualization_facts_package.append(
                        {
                            "analysisId": analysis.analysis_id,
                            "plan": analysis_plans[analysis.analysis_id],
                            "summary": (
                                durable_item.get("summary")
                                if isinstance(durable_item, Mapping)
                                else None
                            ),
                            "factFile": fact_files[analysis.analysis_id].model_dump(
                                mode="json", by_alias=True
                            ),
                            # 模型只需要知道可画哪些字段及其在真实 facts schema 中的精确位置。
                            # 完整数值序列继续留在已验哈希的 facts 文件，由图表脚本按签发路径
                            # 一次读取；禁止复制大数组，也禁止让模型猜 periodValues/topGroups
                            # 位于根节点还是 metric 内。
                            "metrics": [
                                {
                                    "metricIndex": metric_index,
                                    **{
                                        key: metric.get(key)
                                        for key in (
                                            "datasetId",
                                            "field",
                                            "metricCodes",
                                            "aggregation",
                                            "unit",
                                            "scope",
                                            "periodRoles",
                                            "periodStart",
                                            "periodEnd",
                                            "total",
                                        )
                                    },
                                    "periodValueCount": len(metric.get("periodValues", ())),
                                    "topGroupCount": len(metric.get("topGroups", ())),
                                    "bottomGroupCount": len(metric.get("bottomGroups", ())),
                                    "dataPaths": {
                                        "metric": f"metrics[{metric_index}]",
                                        "periodValues": f"metrics[{metric_index}].periodValues",
                                        "topGroups": f"metrics[{metric_index}].topGroups",
                                        "bottomGroups": f"metrics[{metric_index}].bottomGroups",
                                    },
                                }
                                for metric_index, metric in enumerate(raw_metrics)
                                if isinstance(metric, Mapping)
                            ],
                            "derivedMetrics": [
                                {
                                    "derivedMetricIndex": metric_index,
                                    **{
                                        key: metric.get(key)
                                        for key in (
                                            "code",
                                            "kind",
                                            "unit",
                                            "periodRole",
                                            "periodStart",
                                            "periodEnd",
                                            "datasetIds",
                                            "value",
                                            "percentage",
                                        )
                                    },
                                    "dataPath": f"derivedMetrics[{metric_index}]",
                                }
                                for metric_index, metric in enumerate(raw_derived_metrics)
                                if isinstance(metric, Mapping)
                            ],
                            "comparisons": [
                                {
                                    "comparisonIndex": comparison_index,
                                    **{
                                        key: comparison.get(key)
                                        for key in (
                                            "comparisonType",
                                            "field",
                                            "unit",
                                            "periodStart",
                                            "periodEnd",
                                            "currentDatasetId",
                                            "baselineDatasetId",
                                            "currentTotal",
                                            "baselineTotal",
                                            "change",
                                            "changeRate",
                                        )
                                    },
                                    "dataPath": f"comparisons[{comparison_index}]",
                                }
                                for comparison_index, comparison in enumerate(raw_comparisons)
                                if isinstance(comparison, Mapping)
                            ],
                            "correlationCount": len(fact_payload.get("correlations", {})),
                            "correlationsPath": "correlations",
                            "reconciliationCount": len(fact_payload.get("reconciliations", ())),
                            "reconciliationsPath": "reconciliations",
                            "warningCount": len(fact_payload.get("warnings", ())),
                            "warningsPath": "warnings",
                            "fields": sorted(
                                {
                                    *(
                                        metric["field"]
                                        for metric in raw_metrics
                                        if isinstance(metric, Mapping)
                                        and isinstance(metric.get("field"), str)
                                    ),
                                }
                            ),
                            "allowedMetricCodes": sorted(
                                {
                                    *(
                                        code
                                        for metric in raw_metrics
                                        if isinstance(metric, Mapping)
                                        for code in metric.get("metricCodes", ())
                                        if isinstance(code, str)
                                    ),
                                    *(
                                        metric["code"]
                                        for metric in raw_derived_metrics
                                        if isinstance(metric, Mapping)
                                        and isinstance(metric.get("code"), str)
                                    ),
                                }
                            ),
                            "evidenceFiles": (
                                durable_item.get("evidenceFiles", [])
                                if isinstance(durable_item, Mapping)
                                else []
                            ),
                            "citationIds": (
                                durable_item.get("citationIds", [])
                                if isinstance(durable_item, Mapping)
                                else []
                            ),
                        }
                    )
            visualization_root = f"报表/智能分析/{run_context.run_id}/analysis"
            allowed_metric_codes = sorted(
                {
                    code
                    for item in visualization_facts_package
                    for code in item["allowedMetricCodes"]
                }
            )
            if set(fact_bundles) != set(analysis_ids):
                raise ReportingError(
                    "report_analysis_evidence_incomplete",
                    "确定性 facts 没有精确覆盖冻结分析计划。",
                )
            evidence_dataset_ids = {
                dataset_id
                for analysis_id in analysis_ids
                for item in (
                    (analysis_items.get(analysis_id),)
                    if isinstance(analysis_items, Mapping)
                    else ()
                )
                if isinstance(item, Mapping)
                for dataset_id in _require_dataset_id_sequence(
                    item.get("datasetIds"), error_message="durable analysis Dataset 无效。"
                )
            }
            authorized_dataset_ids = {item.dataset_id for item in dataset_handles}
            if authorized_dataset_ids and (
                not evidence_dataset_ids
                or not evidence_dataset_ids.issubset(authorized_dataset_ids)
            ):
                raise ReportingError(
                    "report_analysis_dataset_inconsistent",
                    "durable analysis evidence Dataset 不属于授权 Dataset snapshot。",
                )
            if authorized_dataset_ids:
                dataset_semantics, metric_definitions = _finalize_semantic_catalog(
                    analysis_plans=analysis_plans,
                    fact_bundles=fact_bundles,
                    dataset_ids=tuple(sorted(evidence_dataset_ids)),
                )
            else:
                # 没有授权 snapshot 时不能伪造 Dataset 语义；保留空投影让 worker 的
                # 终态校验先给出原始错误。真实报表入口总会提供非空授权 snapshot。
                dataset_semantics, metric_definitions = [], []
            chart_registration_rules = {
                # null 明确表示冻结 facts 没有 Profile metric code，Worker 可定义
                # 图表 code，但 finalize 时必须以同名 metricDefinitions 冻结语义；
                # 非空目录仍由 register_report_charts 严格拒绝未知 code。
                "allowedMetricCodes": allowed_metric_codes or None,
                "comparisonPeriodRequiredFor": ["period", "yoy", "mom"],
                "referenceOnlyTitleAndAltTextMustContain": "参考",
                "vision": visual_inspection_mode == "vision",
            }
            instruction_payload = {
                "phase": "analysis",
                "taskKind": "visualization_finalize",
                "reportGoal": self._envelope(run_context).report_goal,
                "completionConditions": _visualization_completion_conditions(
                    last_error,
                    charts_registered,
                    tuple(item["chartId"] for item in registered_charts),
                ),
                "outline": self._state(run_context)[REPORT_OUTLINE_STATE_KEY],
                "visualTheme": REPORT_VISUAL_THEME,
                "registeredCharts": registered_charts,
                "visualInspectionMode": visual_inspection_mode,
                "analysisPlans": analysis_plans,
                "analysisCitationIds": _visualization_analysis_citation_ids(
                    detailed_plan, citation_bindings
                ),
                "citationDatasetIds": {
                    item.citation_id: item.dataset_id for item in citation_bindings
                },
                "deterministicFactFiles": {
                    analysis_id: identity.model_dump(mode="json", by_alias=True)
                    for analysis_id, identity in fact_files.items()
                },
                "visualizationFacts": visualization_facts_package,
                "datasetSemantics": dataset_semantics,
                "metricDefinitions": metric_definitions,
                "sectionEvidenceCatalog": {
                    section_code: visualization_payload.get("visualizationSections", {}).get(
                        section_code, {}
                    )
                    for section_code in section_codes
                },
                "chartRegistrationRules": chart_registration_rules,
                # 可视化脚本与 evidence/facts 分属兄弟目录。由服务端签发完整工作区相对路径，
                # 禁止 Worker 依据脚本位置猜测父目录，否则会把 evidence 错拼成 analysis/evidence。
                "visualizationWorkspace": {
                    "scriptPath": f"{visualization_root}/charts.py",
                    "chartOutputRoot": f"{visualization_root}/charts",
                    "allowedTerminalCommand": f"python3 {visualization_root}/charts.py",
                },
                "sourceWarnings": [
                    item.model_dump(mode="json", by_alias=True)
                    for item in _source_warnings_from_state(self._state(run_context))
                ],
                "reviewFeedback": feedback,
                "analysisOutputPath": output_path,
            }
            instruction_component_bytes = self._instruction_component_bytes(instruction_payload)
            instruction = json.dumps(instruction_payload, ensure_ascii=False, separators=(",", ":"))
            instruction_bytes = len(instruction.encode("utf-8"))
            if instruction_bytes > MAX_REPORT_INSTRUCTION_BYTES:
                raise ReportingError(
                    "report_analysis_context_too_large",
                    "全局分析投影超过模型输入边界；证据未被静默截断。",
                )
            visualization_usage = _visualization_retry_usage(last_error)
            contract = build_report_phase_acceptance_contract(
                phase="analysis",
                validation_context_file=validation_context_file.model_dump(
                    mode="json", by_alias=True
                ),
                phase_contract={
                    "reportRunId": str(run_context.run_id or scope["externalRunId"]),
                    "taskKind": "visualization_finalize",
                    "chartsRegistered": charts_registered,
                    "retainedChartIds": [item["chartId"] for item in registered_charts],
                    "visualizationRecovery": _visualization_recovery_required(last_error),
                    "visualInspectionMode": visual_inspection_mode,
                    **visualization_budget,
                    **visualization_usage,
                    "visualizationWorkspace": {
                        "scriptPath": f"{visualization_root}/charts.py",
                        "chartOutputRoot": f"{visualization_root}/charts",
                    },
                    "thinkingEffort": self._worker_thinking_effort(
                        retry=any(
                            item.status == "failed"
                            for item in checkpoint.trace
                            if item.phase == "analysis"
                            and item.work_kind == "visualization_finalize"
                            and item.retry_reason == retry_reason
                        )
                    ),
                    "analysisIds": list(analysis_ids),
                    "currentAnalysisId": None,
                    "datasetSemantics": dataset_semantics,
                    "metricDefinitions": metric_definitions,
                    "sectionEvidenceCatalog": {
                        section_code: visualization_payload.get("visualizationSections", {}).get(
                            section_code, {}
                        )
                        for section_code in section_codes
                    },
                    "analysisPlans": analysis_plans,
                    "analysisDatasetIds": {
                        item.analysis_id: list(item.dataset_ids) for item in detailed_plan.analyses
                    },
                    "allowedMetricCodes": allowed_metric_codes or None,
                    "deterministicFactFiles": {
                        analysis_id: identity.model_dump(mode="json", by_alias=True)
                        for analysis_id, identity in fact_files.items()
                    },
                    "datasetIds": sorted(evidence_dataset_ids),
                    "authorizedDatasetIds": [item.dataset_id for item in dataset_handles],
                    "citationIds": [item.citation_id for item in citation_bindings],
                    "citationRegistry": [
                        item.model_dump(mode="json", by_alias=True) for item in citation_bindings
                    ],
                    "citationDatasetIds": {
                        item.citation_id: item.dataset_id for item in citation_bindings
                    },
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
                            workKind="visualization_finalize",
                            attempt=attempt,
                            instructionBytes=instruction_bytes,
                            projectedContextBytes=instruction_bytes,
                            retryReason=retry_reason,
                            visualInspectionMode=visual_inspection_mode,
                        ),
                    ),
                    last_error=None,
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
            trace_metrics: dict[str, Any] = {}
            visualization_usage_metrics: Mapping[str, Any] = {}
            started_at = time.monotonic()
            try:
                receipt = await self._run_visualization_finalize(
                    task_scope=task_scope,
                    instruction=instruction,
                    acceptance_contract=contract,
                    parent_run_id=str(run_context.run_id or ""),
                )
                raw_projection_metrics = receipt.get("projectionMetrics")
                if isinstance(raw_projection_metrics, Mapping):
                    visualization_usage_metrics = raw_projection_metrics
                trace_metrics = self._trace_metrics_from_receipt(receipt)
                trace_metrics["duration_seconds"] = time.monotonic() - started_at
                identity = await self._phase_artifact_from_receipt(
                    scope["threadId"], cast(dict[str, Any], receipt), (output_path,)
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
                artifact_analysis_ids = {
                    evidence.analysis_id for evidence in artifact.evidence_manifest.evidence
                }
                trace_metrics["completed_analysis_count"] = len(
                    completed_by_worker & artifact_analysis_ids
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
                    "component_bytes=%s "
                    "profile_receipts=%s model_input_tokens=%s model_requests=%s "
                    "max_projected_tokens=%s rebases=%s hard_cap=%s "
                    "completed_analysis=%s retry_reason=%s budget_version=%s "
                    "evidence_read_units=%s read_limit=%s fact_query_limit=%s "
                    "attempt_tool_limit=%s total_tool_limit=%s read_units_used=%s "
                    "fact_queries_used=%s tool_calls=%s script_failures=%s "
                    "attempt_successful_tools=%s attempt_rejected_tools=%s",
                    task_id,
                    instruction_bytes,
                    trace_metrics["duration_seconds"],
                    trace_metrics.get("tool_event_count", 0),
                    instruction_component_bytes,
                    len(artifact.profile_read_receipts),
                    trace_metrics.get("model_input_tokens"),
                    trace_metrics.get("model_request_count", 0),
                    trace_metrics.get("max_projected_tokens", 0),
                    trace_metrics.get("rebase_count", 0),
                    trace_metrics.get("input_token_hard_cap", 0),
                    trace_metrics.get("completed_analysis_count", 0),
                    retry_reason or "-",
                    visualization_budget["visualizationBudgetVersion"],
                    visualization_budget["visualizationEvidenceReadUnits"],
                    visualization_budget["visualizationReadLimit"],
                    visualization_budget["visualizationFactQueryLimit"],
                    visualization_budget["visualizationAttemptToolLimit"],
                    visualization_budget["visualizationTotalToolLimit"],
                    visualization_usage_metrics.get("visualizationReadUnitsUsed", 0),
                    visualization_usage_metrics.get("visualizationFactQueriesUsed", 0),
                    visualization_usage_metrics.get("visualizationToolCalls", 0),
                    visualization_usage_metrics.get("visualizationScriptFailures", 0),
                    visualization_usage_metrics.get("visualizationAttemptSuccessfulToolCalls", 0),
                    visualization_usage_metrics.get("visualizationAttemptRejectedToolCalls", 0),
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
                        "taskId": task_id,
                        "workKind": "visualization_finalize",
                        "attempt": attempt,
                        "retryUsage": _checkpoint_retry_usage(
                            error, work_kind="visualization_finalize"
                        ).model_dump(mode="json", by_alias=True),
                    },
                )
                await self._persist_reporting_checkpoint(run_context, checkpoint)
        assert last_error is not None
        raise last_error

    async def _restore_or_create_deterministic_analysis_facts(
        self,
        *,
        run_context: RunContext,
        checkpoint: ReportingCheckpoint,
        thread_id: str,
        report_run_id: str,
        revision: int,
        detailed_plan: DetailedAnalysisPlan,
        dataset_handles: tuple[DatasetHandle, ...],
    ) -> tuple[ReportingCheckpoint, dict[str, FileIdentity]]:
        """恢复同 revision 的 facts 权威身份；只有无分析进度的新 checkpoint 可生成。"""

        analysis_ids = tuple(item.analysis_id for item in detailed_plan.analyses)
        facts_root = f"报表/智能分析/{report_run_id}/facts/revision-{revision}"
        expected_paths = {
            analysis_id: f"{facts_root}/{analysis_id}.json" for analysis_id in analysis_ids
        }
        fact_files = dict(checkpoint.deterministic_fact_files)
        recovered_legacy_mapping = False

        if not fact_files:
            # 旧 v2 没有 analysisId 映射，只允许从通用账本中精确恢复当前 run/revision
            # 的规范文件集；部分匹配或额外 facts 都无法证明计划绑定，必须失败关闭。
            candidates_by_path: dict[str, list[FileIdentity]] = {}
            for identity in checkpoint.files:
                if identity.path.startswith(f"{facts_root}/"):
                    candidates_by_path.setdefault(identity.path, []).append(identity)
            if candidates_by_path:
                if set(candidates_by_path) != set(expected_paths.values()) or any(
                    len(candidates) != 1 for candidates in candidates_by_path.values()
                ):
                    raise ReportingError(
                        "report_semantic_contract_upgrade_required",
                        "运行中的 Reporting checkpoint 缺少完整的确定性 facts 身份映射。",
                    )
                fact_files = {
                    analysis_id: candidates_by_path[path][0]
                    for analysis_id, path in expected_paths.items()
                }
                recovered_legacy_mapping = True
            else:
                has_unmapped_fact_identity = any(
                    "/facts/revision-" in identity.path for identity in checkpoint.files
                )
                has_analysis_progress = (
                    checkpoint.phase != "analysis"
                    or checkpoint.report_brief is not None
                    or checkpoint.evidence_manifest is not None
                    or checkpoint.analysis_manifest_file is not None
                    or has_unmapped_fact_identity
                    or (
                        checkpoint.last_error is not None
                        and checkpoint.last_error.phase == "analysis"
                    )
                    or any(item.phase == "analysis" for item in checkpoint.trace)
                )
                if has_analysis_progress:
                    raise ReportingError(
                        "report_semantic_contract_upgrade_required",
                        "运行中的 Reporting checkpoint 缺少确定性 facts 身份映射。",
                    )
                fact_files = await self._prepare_deterministic_analysis_facts(
                    run_context=run_context,
                    thread_id=thread_id,
                    report_run_id=report_run_id,
                    revision=revision,
                    detailed_plan=detailed_plan,
                    dataset_handles=dataset_handles,
                )
                if set(fact_files) != set(analysis_ids) or any(
                    fact_files[analysis_id].path != expected_paths[analysis_id]
                    for analysis_id in analysis_ids
                ):
                    raise ReportingError(
                        "report_analysis_facts_invalid",
                        "确定性 facts 没有精确覆盖冻结分析计划。",
                    )
                checkpoint = self._update_reporting_checkpoint(
                    checkpoint,
                    deterministic_fact_files=fact_files,
                    files=self._merge_checkpoint_files(checkpoint.files, *fact_files.values()),
                )
                checkpoint = await self._persist_reporting_checkpoint(run_context, checkpoint)
                return checkpoint, fact_files

        # 映射是后续 Worker 的唯一 facts 来源。每次恢复均先核验计划、规范路径和普通
        # 文件的 size/SHA-256；不允许重新读取 Dataset 重算后覆盖已签发的事实身份。
        if set(fact_files) != set(analysis_ids) or any(
            fact_files[analysis_id].path != expected_paths[analysis_id]
            for analysis_id in analysis_ids
        ):
            raise ReportingError(
                "report_semantic_contract_upgrade_required",
                "运行中的 Reporting checkpoint 缺少完整的确定性 facts 身份映射。",
            )

        for analysis_id in analysis_ids:
            expected = fact_files[analysis_id]
            actual_value: Any = None
            try:
                actual_value = await self.workspace_service.ahash_file(thread_id, expected.path)
                actual = FileIdentity.model_validate(actual_value)
            except Exception as error:
                actual_size = (
                    actual_value.get("size") if isinstance(actual_value, Mapping) else None
                )
                actual_sha256 = (
                    actual_value.get("sha256") if isinstance(actual_value, Mapping) else None
                )
                loguru_logger.warning(
                    "report_analysis_facts_changed path={} expected_size={} actual_size={} "
                    "expected_sha256={} actual_sha256={}",
                    expected.path,
                    expected.size,
                    actual_size,
                    expected.sha256,
                    actual_sha256,
                )
                raise ReportingError(
                    "report_analysis_facts_changed",
                    "确定性 facts 文件缺失、类型无效或身份已变化。",
                ) from error
            if actual != expected:
                loguru_logger.warning(
                    "report_analysis_facts_changed path={} expected_size={} actual_size={} "
                    "expected_sha256={} actual_sha256={}",
                    expected.path,
                    expected.size,
                    actual.size,
                    expected.sha256,
                    actual.sha256,
                )
                raise ReportingError(
                    "report_analysis_facts_changed",
                    "确定性 facts 文件身份已变化。",
                )

        if recovered_legacy_mapping:
            checkpoint = self._update_reporting_checkpoint(
                checkpoint,
                deterministic_fact_files=fact_files,
            )
            checkpoint = await self._persist_reporting_checkpoint(run_context, checkpoint)
        return checkpoint, fact_files

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
            try:
                validate_metric_code_bindings(bundle)
            except ValueError as error:
                raise ReportingError(
                    "report_analysis_metric_definition_incomplete",
                    "确定性数值事实缺少 Effective Profile 提供的权威指标定义，已拒绝冻结。",
                    details={"analysisId": analysis.analysis_id, "reason": str(error)},
                ) from error
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


async def _run_pending_visualization_sections(
    section_codes: Sequence[str],
    *,
    completed_section_codes: set[str],
    concurrency: int,
    worker: Callable[[str], Awaitable[None]],
) -> tuple[str, ...]:
    """并发执行未完成图表章节，并在全部兄弟章节收口后汇总失败。"""

    pending = tuple(code for code in section_codes if code not in completed_section_codes)
    failures: dict[str, Exception] = {}

    async def run_one(section_code: str) -> None:
        try:
            await worker(section_code)
        except Exception as error:
            # 章节 worker 自己先把稳定错误写入 checkpoint 账本。调度层必须等兄弟章节
            # 全部结束后再失败，确保成功草案可 durable 冻结并在 fresh attempt 中跳过。
            failures[section_code] = error

    if pending:
        await _run_bounded(pending, concurrency=concurrency, worker=run_one)
    if failures:
        raise ExceptionGroup(
            "visualization sections failed",
            [failures[code] for code in pending if code in failures],
        )
    return pending


def _ensure_visual_inspection_capability(
    checkpoint: ReportingCheckpoint,
    current_mode: Literal["vision", "deterministic"],
) -> None:
    previous_mode = next(
        (
            item.visual_inspection_mode
            for item in reversed(checkpoint.trace)
            if item.phase == "analysis"
            and item.work_kind in {"visualization_section", "visualization_finalize"}
            and item.visual_inspection_mode is not None
        ),
        None,
    )
    if previous_mode is not None and previous_mode != current_mode:
        raise ReportingError(
            "report_visualization_capability_changed",
            "visualization fresh retry 的图表检查能力与已签发 checkpoint 不一致。",
        )


def _visualization_section_retry_error(
    checkpoint: ReportingCheckpoint,
    *,
    section_code: str,
) -> ReportingError | None:
    """按 sectionCode 从失败账本恢复该章的稳定错误与预算,驱动章节 fresh retry。

    账本条目必须与 trace 中该章最近一次失败记录的 taskId/attempt 完全一致,
    且携带完整 retryUsage;否则说明 checkpoint 状态不可信(例如账本与 trace
    来自不同写入轮次),必须失败关闭而不是静默重置预算。
    """

    stored = checkpoint.visualization_section_errors.get(section_code)
    if stored is None:
        return None
    matching_failure = next(
        (
            item
            for item in reversed(checkpoint.trace)
            if item.phase == "analysis"
            and item.work_kind == "visualization_section"
            and item.section_code == section_code
            and item.status == "failed"
        ),
        None,
    )
    if (
        stored.phase != "analysis"
        or stored.work_kind != "visualization_section"
        or stored.section_code != section_code
        or stored.retry_usage is None
        or matching_failure is None
        or stored.task_id != matching_failure.task_id
        or stored.attempt != matching_failure.attempt
    ):
        raise ReportingError(
            "report_semantic_contract_upgrade_required",
            "运行中的 Reporting checkpoint 缺少可信章节恢复身份或预算，请重新分析。",
        )
    error = ReportingError(stored.code, stored.message)
    setattr(
        error,
        REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
        stored.retry_usage.model_dump(mode="python", by_alias=True),
    )
    return error


def _visualization_section_completion_conditions(last_error: Exception | None) -> list[str]:
    if _visualization_recovery_required(last_error):
        return [
            "上一轮本章因预算耗尽或无进展终止;禁止重新规划、探索事实或重复读取",
            "脚本尚未执行或需要修复时,只把签发的 scriptPath 修复后执行一次",
            "立即且只调用一次 submit_visualization_charts 提交该章现存图表草案;缺失的图表不要提交",
        ]
    return [
        "只处理当前 sectionCode 及其 outline.analysisIds；跨域章节不得扩大事实范围",
        "脚本只写入签发的 scriptPath 和 chartOutputRoot",
        "允许零图，最后且只调用一次 submit_visualization_charts",
    ]


def _checkpoint_retry_error(
    checkpoint: ReportingCheckpoint,
    *,
    work_kind: Literal["analysis_item", "visualization_section", "visualization_finalize"],
    analysis_id: str | None,
    retry_reason: str | None,
) -> ReportingError | None:
    """仅将当前失败工作对应的稳定错误恢复为 fresh attempt 状态。"""

    matching_failure = next(
        (
            item
            for item in reversed(checkpoint.trace)
            if item.phase == "analysis"
            and item.work_kind == work_kind
            and item.analysis_id == analysis_id
            and item.retry_reason == retry_reason
            and item.status == "failed"
        ),
        None,
    )
    if matching_failure is None:
        return None
    stored = checkpoint.last_error
    if (
        stored is None
        or stored.phase != "analysis"
        or stored.task_id != matching_failure.task_id
        or stored.work_kind != matching_failure.work_kind
        or stored.analysis_id != matching_failure.analysis_id
        or stored.attempt != matching_failure.attempt
        or stored.retry_usage is None
    ):
        raise ReportingError(
            "report_semantic_contract_upgrade_required",
            "运行中的 Reporting checkpoint 缺少可信恢复身份或预算，请重新分析。",
        )
    error = ReportingError(stored.code, stored.message)
    usage = stored.retry_usage
    if work_kind == "analysis_item":
        setattr(
            error,
            REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR,
            {"queryCount": usage.analysis_fact_queries_used},
        )
    else:
        setattr(
            error,
            REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
            usage.model_dump(mode="python", by_alias=True),
        )
    return error


def _checkpoint_retry_usage(
    error: Exception,
    *,
    work_kind: Literal["analysis_item", "visualization_section", "visualization_finalize"],
) -> CheckpointRetryUsage:
    if work_kind == "analysis_item":
        return CheckpointRetryUsage(analysisFactQueriesUsed=_analysis_fact_retry_usage(error))
    source = getattr(error, REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR, None)
    attempt_successes = (
        source.get("visualizationAttemptSuccessfulToolCalls", 0)
        if isinstance(source, Mapping)
        else 0
    )
    attempt_rejections = (
        source.get("visualizationAttemptRejectedToolCalls", 0) if isinstance(source, Mapping) else 0
    )
    return CheckpointRetryUsage(
        **_visualization_retry_usage(error),
        visualizationAttemptSuccessfulToolCalls=attempt_successes,
        visualizationAttemptRejectedToolCalls=attempt_rejections,
    )


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
                "fields": list(item.fields),
                "metrics": list(item.metrics),
                "organizationGrain": list(item.organization_grain),
                "actions": list(item.actions),
                "limitations": list(item.limitations),
            }
            for item in plan.analyses
            if allowed is None or item.analysis_id in allowed
        ],
    }


def _finalize_semantic_catalog(
    *,
    analysis_plans: Mapping[str, Mapping[str, Any]],
    fact_bundles: Mapping[str, Mapping[str, Any]],
    dataset_ids: Sequence[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """从冻结计划与 facts 投影目录；语义事实不完整时拒绝冻结。"""

    _require_dataset_id_sequence(
        dataset_ids,
        error_message="evidence Dataset 集合不能为空。",
        error_code="report_analysis_semantic_invalid",
    )
    if not analysis_plans:
        raise ReportingError("report_analysis_semantic_invalid", "分析计划不能为空。")

    grains_by_dataset: dict[str, set[str]] = {dataset_id: set() for dataset_id in dataset_ids}
    planned_dataset_ids: set[str] = set()
    for plan in analysis_plans.values():
        raw_dataset_ids = plan.get("datasetIds")
        raw_grain = plan.get("organizationGrain")
        if not isinstance(raw_dataset_ids, Sequence) or isinstance(raw_dataset_ids, (str, bytes)):
            raise ReportingError("report_analysis_dataset_inconsistent", "分析计划 Dataset 无效。")
        if not isinstance(raw_grain, Sequence) or isinstance(raw_grain, (str, bytes)):
            raise ReportingError(
                "report_analysis_semantic_invalid", "分析计划缺少 organization grain。"
            )
        grains = {item for item in raw_grain if isinstance(item, str) and item}
        if not grains:
            raise ReportingError(
                "report_analysis_semantic_invalid", "分析计划缺少 organization grain。"
            )
        for dataset_id in raw_dataset_ids:
            if not isinstance(dataset_id, str) or not dataset_id:
                raise ReportingError(
                    "report_analysis_dataset_inconsistent", "分析计划包含无效 Dataset。"
                )
            planned_dataset_ids.add(dataset_id)
            if dataset_id not in grains_by_dataset:
                raise ReportingError(
                    "report_analysis_semantic_invalid",
                    "分析计划 Dataset 与 evidence-derived Dataset 不一致。",
                )
            grains_by_dataset[dataset_id].update(grains)
    if planned_dataset_ids != set(dataset_ids):
        raise ReportingError(
            "report_analysis_dataset_inconsistent",
            "分析计划 Dataset 必须精确覆盖 evidence-derived Dataset。",
        )
    if any(not grains for grains in grains_by_dataset.values()):
        raise ReportingError(
            "report_analysis_semantic_invalid", "Dataset 缺少冻结 organization grain。"
        )

    dataset_semantics = []
    for dataset_id in dataset_ids:
        grains = grains_by_dataset[dataset_id]
        dataset_semantics.append(
            {
                "datasetId": dataset_id,
                "rowGrain": "+".join(sorted(grains)) or "record",
                "duplicateResolution": "not_applicable",
            }
        )

    facts_by_code: dict[str, list[Mapping[str, Any]]] = {}
    for bundle in fact_bundles.values():
        raw_metrics = bundle.get("metrics", ())
        if isinstance(raw_metrics, Sequence) and not isinstance(raw_metrics, (str, bytes)):
            for metric in raw_metrics:
                if not isinstance(metric, Mapping):
                    continue
                raw_codes = metric.get("metricCodes", ())
                if isinstance(raw_codes, Sequence) and not isinstance(raw_codes, (str, bytes)):
                    for code in raw_codes:
                        if isinstance(code, str) and code:
                            facts_by_code.setdefault(code, []).append(metric)
        raw_derived = bundle.get("derivedMetrics", ())
        if isinstance(raw_derived, Sequence) and not isinstance(raw_derived, (str, bytes)):
            for metric in raw_derived:
                if isinstance(metric, Mapping) and isinstance(metric.get("code"), str):
                    facts_by_code.setdefault(metric["code"], []).append(metric)

    metric_definitions = []
    for code in sorted(facts_by_code):
        facts = facts_by_code[code]
        name = code
        formulas = sorted(
            {
                formula
                for fact in facts
                if isinstance((formula := fact.get("formula")), str) and formula
            }
        )
        units = sorted(
            {unit for fact in facts if isinstance((unit := fact.get("unit")), str) and unit}
        )
        starts = sorted(
            {
                value
                for fact in facts
                if isinstance((value := fact.get("periodStart")), str) and value
            }
        )
        ends = sorted(
            {value for fact in facts if isinstance((value := fact.get("periodEnd")), str) and value}
        )
        if len(formulas) != len(facts) or len(units) != 1 or len(starts) != 1 or len(ends) != 1:
            raise ReportingError(
                "report_analysis_semantic_invalid",
                f"指标 {code} 的 formula、unit 或期间缺失或冲突。",
            )
        period_start = starts[0]
        period_end = ends[0]
        period_basis = (
            period_start
            if period_start is not None and period_start == period_end
            else " 至 ".join(item for item in (period_start, period_end) if item is not None)
        )
        metric_definitions.append(
            {
                "code": code,
                "name": name,
                "definition": "；".join((name, *formulas))[:2000],
                "unit": units[0],
                "periodBasis": period_basis,
            }
        )
    return dataset_semantics, metric_definitions


def _require_dataset_id_sequence(
    value: object,
    *,
    error_message: str,
    error_code: str = "report_analysis_dataset_inconsistent",
) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ReportingError(error_code, error_message)
    return tuple(value)


def _visualization_analysis_citation_ids(
    plan: DetailedAnalysisPlan,
    citations: tuple[Citation, ...],
) -> dict[str, list[str]]:
    return {
        analysis.analysis_id: [
            citation.citation_id
            for citation in citations
            if citation.dataset_id in analysis.dataset_ids
        ]
        for analysis in plan.analyses
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
    if _analysis_fact_recovery_required(last_error):
        return [
            "上一轮已耗尽 facts 查询额度；不得重新查询、读取、写入或执行任何工具",
            "直接使用 deterministicFacts 中已内联的受信事实，立即且只调用一次 complete_analysis_item",
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
        "deterministicFacts 已内联当前分析项的完整受信固定事实；不得为探索 facts 结构、"
        "重复验证任务 JSON 已投影的元数据或空命中调用 query_analysis_facts",
        "只有当前管理问题确实缺少必需事实时，才按缺口精确调用 query_analysis_facts 或读取实际使用的 Profile；"
        "不得猜测、补齐或替代缺失事实",
        "固定事实足够时立即调用 complete_analysis_item；不创建脚本或 evidence，"
        "evidencePaths 传空数组",
        "只为 deterministicFactFile 未覆盖的事实缺口创建补充 evidence",
        "本阶段禁止生成或登记图表",
        "最后且只调用一次 complete_analysis_item",
    ]


def _visualization_completion_conditions(
    last_error: Exception | None,
    charts_registered: bool,
    retained_chart_ids: tuple[str, ...] = (),
) -> list[str]:
    if charts_registered:
        return [
            "durable state 已完成整批图表登记；禁止改图、换 chartId、重复登记或继续自检",
            "不要调用任何读取、写入、执行、Skill 或视觉工具",
            "立即且只调用一次 finalize_report_analysis",
        ]
    retained_requirement = (
        "registeredCharts 是已冻结的保留图表；不得重新生成、改写、检查或登记其中 chartId，只补缺失图表"
        if retained_chart_ids
        else "当前没有保留图表，按批准提纲生成必要图表"
    )
    if _visualization_recovery_required(last_error):
        return [
            "上一轮因工具调用或脚本失败达到上限而终止，且已关闭事实探索；禁止重新规划、重复读取事实或重新探索工作区",
            retained_requirement,
            "仅使用任务 JSON 中 deterministicFactFiles 签发的路径以及既有脚本和图表，完成尚缺的最小修复或执行",
            "整批图表只调用一次 register_report_charts，成功后立即调用 finalize_report_analysis",
        ]
    return [
        "只整合 completedAnalysisItems 和 deterministicFactFiles，不重跑单项分析",
        "visualizationFacts 已提供完整字段目录和真实 dataPaths；图表脚本按 factFile.path 一次读取 facts，"
        "不得调用 query_analysis_facts 或用 read_file 探索 facts/evidence",
        retained_requirement,
        "analysisCitationIds 是 citationId 的唯一受信来源；不得用 read_file、terminal 或目录探测寻找 citationId",
        "图表脚本只写入 visualizationWorkspace.scriptPath，服务端提交后 terminal 仅可执行 python3 <scriptPath>；"
        "不得传 workdir、cd、ls、find、wc、管道、heredoc 或运行其他脚本",
        "批量读取事实、生成和执行图表脚本；相同文件不得重复读取、执行或视觉检查",
        "按批准提纲生成必要图表并整批登记 citation",
        "最后且只调用一次 finalize_report_analysis",
        "evidence、receipt、citation 和文件身份由服务端 durable state 派生",
    ]


def _visualization_recovery_required(last_error: Exception | None) -> bool:
    """预算耗尽或 no-progress 终止后只允许复用既有可视化产物。"""

    return isinstance(last_error, ReportingError) and (
        last_error.code in _VISUALIZATION_RECOVERY_ERROR_CODES
        or (
            isinstance(last_error.details, dict)
            and last_error.details.get("terminalReason") == "tool_no_progress"
        )
    )


def _analysis_fact_recovery_required(last_error: Exception | None) -> bool:
    return (
        isinstance(last_error, ReportingError)
        and last_error.code == "report_analysis_fact_query_budget_exhausted"
    )


def _analysis_fact_retry_usage(last_error: Exception | None) -> int:
    source: Any = getattr(last_error, REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR, None)
    details = last_error.details if isinstance(last_error, ReportingError) else None

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    if isinstance(source, Mapping):
        return count(source.get("queryCount"))
    if isinstance(details, Mapping):
        return count(details.get("queryCount"))
    return 0


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
    read_limit = 12
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
