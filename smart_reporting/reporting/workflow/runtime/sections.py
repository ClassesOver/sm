# mypy: disable-error-code="attr-defined"
# 运行时由 facade 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。
from __future__ import annotations

from ...hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
from ...structured_output import ReportingStructuredOutputExecutor
from ...tools import build_reporting_tools
from ..checkpoint import ChartVisualInspectionReceipt, CheckpointError, ProfileReadReceipt
from ..execution import ReportingTaskInvocation
from .analysis import (
    _finalize_semantic_catalog,
    _reporting_detailed_analysis_plan,
    _run_bounded,
)
from .base import (
    MAX_REPORT_ANALYSIS_REWORKS_PER_SECTION,
    MAX_REPORT_INSTRUCTION_BYTES,
    MAX_REPORT_SECTION_PHASE_ATTEMPTS,
    MAX_SECTION_WORK_ITEM_BYTES,
    AnalysisArtifact,
    AnalysisChart,
    AnalysisDatasetSemantics,
    AnalysisEvidence,
    AnalysisEvidenceManifest,
    AnalysisReworkRequest,
    Any,
    Awaitable,
    Callable,
    Citation,
    CompletedSection,
    ContextTrace,
    DatasetLineage,
    DetailedAnalysisPlan,
    FileIdentity,
    Mapping,
    MetricDefinition,
    ProfileCoverageManifest,
    PurePosixPath,
    ReportArtifactManifest,
    ReportBrief,
    ReportChartInput,
    ReportDraft,
    ReportDraftSection,
    ReportingCheckpoint,
    ReportingCommand,
    ReportingError,
    ReportSectionDefinition,
    RunContext,
    SectionArtifact,
    SectionCitation,
    SectionManagementQuestion,
    SectionWorkItem,
    Sequence,
    SourceWarning,
    TaskExecutionScope,
    TaskState,
    ValidationError,
    _frozen_outline,
    assemble_report_markdown,
    build_report_phase_acceptance_contract,
    cast,
    hashlib,
    json,
    logger,
    payload_sha256,
    reporting_phase_task_key,
    validate_report_draft_blocks,
)
from .phase_models import (
    AnalysisReworkDecision,
    RenderSectionDecision,
    SectionDecision,
    SectionDecisionOutput,
)
from .publication import _accepted_artifacts_match_manifest
from .section_workflow import SectionWorkflow


async def _run_section_batches_until_rework(
    items: Sequence[Any],
    *,
    concurrency: int,
    executor: Callable[[Any], Awaitable[Any]],
) -> list[Any]:
    """每批只启动 concurrency 个章节；批内返工会阻止下一批启动。"""

    results: list[Any] = []
    for offset in range(0, len(items), concurrency):
        batch_results = await _run_bounded(
            items[offset : offset + concurrency],
            concurrency=concurrency,
            operation=executor,
        )
        results.extend(batch_results)
        if any(result[2] is not None for result in batch_results):
            break
    return results


def _section_retry_context(error: Exception | CheckpointError | None) -> dict[str, Any] | None:
    """把章节上轮失败的稳定字段带入 fresh retry，避免模型重新猜测冲突原因。"""

    if error is None:
        return None
    if isinstance(error, CheckpointError):
        return {
            "code": error.code,
            "message": error.message,
            "details": dict(error.details) if isinstance(error.details, Mapping) else {},
        }
    if isinstance(error, ReportingError):
        details = dict(error.details) if isinstance(error.details, Mapping) else {}
        return {"code": error.code, "message": error.message, "details": details}
    return {"code": "report_section_phase_failed", "message": str(error), "details": {}}


def _section_claim_authoring_contract(work_item: SectionWorkItem) -> dict[str, Any]:
    """从当前冻结 WorkItem 生成章节 claim 的动态约束，避免模型猜测业务指标代码。"""

    return {
        "allowedMetricCodes": [item.code for item in work_item.metric_definitions],
        "managementQuestionRefs": [
            item.model_dump(mode="json", by_alias=True)
            for item in work_item.management_question_catalog
        ],
        "serverDerivedFields": ["periodBasis", "managementQuestion"],
        "chartDerivedFields": [
            "currentPeriod",
            "comparisonPeriod",
            "comparisonType",
            "comparability",
            "chartCitationIds",
        ],
        "standaloneClaimRequiredFields": ["currentPeriod"],
        "comparisonRule": (
            "comparisonType 非 none 时必须提供 comparisonPeriod；绑定图表时以图表冻结语义为准"
        ),
    }


def _pending_analysis_rework_file(checkpoint: ReportingCheckpoint) -> FileIdentity | None:
    """返回尚未被后续全局分析冻结覆盖的最新章节返工身份。"""

    if checkpoint.phase != "analysis":
        return None
    latest_rework = next(
        (
            (index, item.artifact_file)
            for index, item in reversed(tuple(enumerate(checkpoint.trace)))
            if item.phase == "section"
            and item.status == "rework"
            and item.artifact_file is not None
        ),
        None,
    )
    if latest_rework is None:
        return None
    rework_index, rework_file = latest_rework
    later_freeze = any(
        index > rework_index
        and item.phase == "analysis"
        and item.work_kind == "visualization_section"
        and item.status == "completed"
        for index, item in enumerate(checkpoint.trace)
    )
    return None if later_freeze else rework_file


class RuntimeSectionsMixin:
    @staticmethod
    def _analysis_rework_constraints(
        *,
        detailed_plan: DetailedAnalysisPlan,
        profile_coverage: ProfileCoverageManifest,
        analysis_ids: tuple[str, ...],
    ) -> dict[str, Any]:
        analyses = {item.analysis_id: item for item in detailed_plan.analyses}
        profiles = {item.dataset_id: item for item in profile_coverage.datasets}
        constraints: dict[str, Any] = {}
        try:
            for analysis_id in analysis_ids:
                analysis = analyses[analysis_id]
                bound_profiles = tuple(profiles[dataset_id] for dataset_id in analysis.dataset_ids)
                constraints[analysis_id] = {
                    "datasetIds": list(analysis.dataset_ids),
                    "periods": list(analysis.periods),
                    "metrics": list(analysis.metrics),
                    "profileDatasets": [
                        {
                            "datasetId": item.dataset_id,
                            "rowCount": item.row_count,
                            "profileSnapshotHash": item.profile_file.sha256,
                        }
                        for item in bound_profiles
                    ],
                    "planHash": payload_sha256(analysis.model_dump(mode="json", by_alias=True)),
                }
        except KeyError as error:
            raise ReportingError(
                "report_analysis_rework_invalid",
                "章节返工约束没有绑定冻结分析计划或完整 Profile Dataset。",
            ) from error
        return constraints

    async def _commit_section_rework_batch(
        self,
        run_context: RunContext,
        *,
        checkpoint: ReportingCheckpoint,
        revision: int,
        rework_results: Sequence[tuple[ReportingCheckpoint, AnalysisReworkRequest]],
    ) -> tuple[ReportingCheckpoint, AnalysisReworkRequest]:
        """批内章节执行器全部结束后，一次性提交返工并撤销受影响章节。"""

        requests = tuple(request for _candidate, request in rework_results)
        affected_analysis_ids = tuple(
            dict.fromkeys(
                analysis_id for request in requests for analysis_id in request.analysis_ids
            )
        )
        rework = AnalysisReworkRequest(
            sectionCode=requests[0].section_code,
            analysisIds=affected_analysis_ids,
            reason="；".join(dict.fromkeys(item.reason for item in requests)),
            missingEvidence=tuple(
                dict.fromkeys(item for request in requests for item in request.missing_evidence)
            ),
        )
        await self._apply_durable_command(
            run_context,
            ReportingCommand(
                name="request_analysis_rework",
                commandId=(
                    f"analysis-rework:{revision}:"
                    f"{payload_sha256(rework.model_dump(mode='json', by_alias=True))}"
                ),
                payload={
                    "analysisIds": list(rework.analysis_ids),
                    "missingEvidence": list(rework.missing_evidence),
                    "reason": rework.reason,
                    "sectionCode": rework.section_code,
                },
            ),
        )
        invalid_section_codes = {
            section.code
            for section in _frozen_outline(self._state(run_context)).sections
            if set(section.analysis_ids) & set(affected_analysis_ids)
        }
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
                dict.fromkeys([*checkpoint.pending_sections, *sorted(invalid_section_codes)])
            ),
            last_error={
                "phase": "section",
                "code": "report_analysis_evidence_insufficient",
                "message": rework.reason,
                "sectionCode": rework.section_code,
                "retryReason": payload_sha256(rework.model_dump(mode="json", by_alias=True)),
            },
        )
        # 通用并发 merge 会保留 completedSections 的并集；这里是批次收口后的有意撤销，
        # 必须以已读取的最新 checkpoint 为基线精确替换，否则 sibling 的旧完成态会被回灌。
        serialized = json.dumps(
            checkpoint.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(serialized).hexdigest()
        identity = await self._write_immutable_artifact(
            self._scope(run_context)["threadId"],
            (
                f"报表/智能分析/{run_context.run_id}/audit/"
                f"reporting-checkpoint-{checkpoint.revision}-{digest}.json"
            ),
            serialized,
        )
        await self._apply_durable_command(
            run_context,
            ReportingCommand(
                name="set_workflow_checkpoint",
                commandId=f"workflow-checkpoint:{checkpoint.revision}:{digest}",
                payload={
                    "checkpoint": checkpoint.model_dump(mode="json", by_alias=True),
                    "mirrorFile": identity.model_dump(mode="json", by_alias=True),
                },
            ),
        )
        return checkpoint, rework

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
        missing_analysis_ids = tuple(item for item in section.analysis_ids if item not in analyses)
        missing_evidence_ids = tuple(item for item in section.analysis_ids if item not in evidence)
        selected_analyses = tuple(
            analyses[item] for item in section.analysis_ids if item in analyses
        )
        selected_evidence = tuple(
            evidence[item] for item in section.analysis_ids if item in evidence
        )
        section_warnings = tuple(
            dict.fromkeys(
                (
                    *(f"analysisId {item} 缺少冻结分析计划" for item in missing_analysis_ids),
                    *(f"analysisId {item} 缺少冻结 evidence" for item in missing_evidence_ids),
                )
            )
        )
        receipt_ids = {
            receipt_id for item in selected_evidence for receipt_id in item.profile_read_receipt_ids
        }
        citation_ids = {
            citation_id for item in selected_evidence for citation_id in item.citation_ids
        }
        selected_metric_codes = {metric for item in selected_analyses for metric in item.metrics}
        receipts = tuple(
            item
            for item in analysis_artifact.profile_read_receipts
            if item.receipt_id in receipt_ids
        )
        # 调用方按 section_codes 构造章节级 AnalysisArtifact；图表晚于 analysis evidence
        # 生成，不能再依赖 evidence.chartIds 反向筛选，否则新生成图表会全部丢失。
        charts = analysis_artifact.evidence_manifest.charts
        selected_metric_codes.update(code for chart in charts for code in chart.metric_codes)
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
            sectionNumber=section.section_number,
            title=section.title,
            objective="；".join(objective_parts),
            completionConditions=(
                "完整呈现当前章节全部冻结事实及其管理结论",
                "保持期间、单位和共享指标口径一致",
                "覆盖当前章节 evidence 提供的 citation",
                "仅使用当前 SectionWorkItem 提供的 chart",
                *(f"warning: {item}" for item in section_warnings),
            ),
            analysisIds=tuple(section.analysis_ids),
            evidence=selected_evidence,
            metricDefinitions=tuple(
                item
                for item in analysis_artifact.evidence_manifest.metric_definitions
                if item.code in selected_metric_codes
            ),
            managementQuestionCatalog=tuple(
                SectionManagementQuestion(
                    ref=item.analysis_id,
                    question=item.management_question,
                )
                for item in selected_analyses
            ),
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
                "章节编号和 title 由服务端插入，模型不得在标题中写编号或重复 H1/H2",
                "章节内部标题只使用 H3/H4，H4 必须位于对应 H3 之后",
                "粗体强调必须使用 **文本**，两个标记的内侧不得留空格",
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
        analysis_rework_constraints: Mapping[str, Any],
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
        model_work_item_payload = dict(work_item_payload)
        # factFiles 仍进入 durable work item 与身份 hash，保证恢复和追溯语义不变；章节
        # Agent 没有读取这些文件的授权，因此模型输入只暴露可直接使用的 factSummaries。
        model_work_item_payload.pop("factFiles", None)
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
                phase="analysis",
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
        checkpoint_error = checkpoint.last_error
        last_error: Exception | None = (
            ReportingError(
                checkpoint_error.code,
                checkpoint_error.message,
                details=checkpoint_error.details,
            )
            if checkpoint_error is not None
            and checkpoint_error.phase == "section"
            and checkpoint_error.section_code == work_item.section_code
            else None
        )
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
            try:
                report_goal = self._envelope(run_context).report_goal
            except ReportingError:
                report_goal = ""
            instruction_payload = {
                "phase": "section",
                "reportGoal": report_goal,
                "sectionGoal": {
                    "sectionCode": work_item.section_code,
                    "title": work_item.title,
                    "focus": list(work_item.completion_conditions),
                    "analysisIds": list(work_item.analysis_ids),
                },
                "sectionWorkItem": model_work_item_payload,
                "completionConditions": list(work_item.completion_conditions),
                "claimAuthoringContract": _section_claim_authoring_contract(work_item),
                "sectionOutputPath": section_output_path,
                "reworkRequestPath": rework_request_path,
            }
            retry_context = _section_retry_context(last_error)
            if retry_context is not None:
                instruction_payload["retryContext"] = retry_context
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
                    "analysisReworkConstraints": dict(analysis_rework_constraints),
                },
                section_output_path=section_output_path,
                rework_request_path=rework_request_path,
            )
            task_scope = TaskExecutionScope(
                task_id,
                scope["userId"],
                scope["threadId"],
                sandbox_id,
                "reporting-section-agent",
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
                if self.section_generator is None:
                    raise ReportingError(
                        "report_section_executor_missing", "章节结构化生成器未配置。"
                    )

                async def execute_fixed_section(
                    invocation: ReportingTaskInvocation,
                ) -> SectionDecision:
                    toolkits = build_reporting_tools(
                        self.workspace_service,
                        self.task_runner.repository,
                        state_repository=self.state_repository,
                        run_context=invocation.run_context,
                    )
                    if len(toolkits) != 1:
                        raise ReportingError(
                            "report_phase_contract_invalid", "章节 Toolkit 装配结果无效。"
                        )
                    toolkit = toolkits[0]

                    async def read_evidence(
                        path: str, offset: int, task_context: RunContext
                    ) -> Mapping[str, Any]:
                        receipt = await toolkit.read_file(
                            path, offset=offset, run_context=task_context
                        )
                        if receipt.get("ok") is False:
                            raise ReportingError(
                                str(receipt.get("code", "report_section_evidence_invalid")),
                                str(receipt.get("message", "章节证据读取未被接受。")),
                                details=dict(receipt),
                            )
                        return receipt

                    async def generate(evidence: Any, task_context: RunContext) -> SectionDecision:
                        payload = json.dumps(
                            {
                                **instruction_payload,
                                "evidence": evidence.model_dump(mode="json", by_alias=True),
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        output = await ReportingStructuredOutputExecutor(
                            self.section_generator
                        ).run(
                            payload,
                            scope=invocation.scope,
                            run_context=task_context,
                        )
                        if not isinstance(output, SectionDecisionOutput):
                            raise ReportingError(
                                "report_phase_output_invalid",
                                "章节结构化 Agent 未返回声明的决策结果。",
                            )
                        return output.root

                    async def recover(
                        repair: Mapping[str, Any], task_context: RunContext
                    ) -> SectionDecision:
                        if self.section_recovery is None:
                            raise ReportingError(
                                "report_section_recovery_missing", "章节恢复生成器未配置。"
                            )
                        payload = json.dumps(
                            {**instruction_payload, "recovery": dict(repair)},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        output = await ReportingStructuredOutputExecutor(self.section_recovery).run(
                            payload,
                            scope=invocation.scope,
                            run_context=task_context,
                        )
                        if not isinstance(output, SectionDecisionOutput):
                            raise ReportingError(
                                "report_phase_output_invalid",
                                "章节恢复 Agent 未返回声明的决策结果。",
                            )
                        return output.root

                    async def render(
                        decision: RenderSectionDecision, task_context: RunContext
                    ) -> Mapping[str, Any]:
                        return await toolkit.render_report_section(
                            decision.section_code,
                            [
                                item.model_dump(mode="json", by_alias=True)
                                for item in decision.blocks
                            ],
                            [
                                item.model_dump(mode="json", by_alias=True)
                                for item in decision.claims
                            ],
                            run_context=task_context,
                        )

                    async def rework(
                        decision: AnalysisReworkDecision, task_context: RunContext
                    ) -> Mapping[str, Any]:
                        return await toolkit.request_analysis_rework(
                            list(decision.analysis_ids),
                            decision.reason,
                            list(decision.missing_evidence),
                            run_context=task_context,
                        )

                    return (
                        await SectionWorkflow(
                            read_evidence=read_evidence,
                            generate=generate,
                            recover=recover if self.section_recovery is not None else None,
                            render=render,
                            rework=rework,
                        ).run(work_item, invocation.run_context)
                    ).decision

                receipt = await self.task_runner.run(
                    task_scope,
                    parent_run_id=str(run_context.run_id or ""),
                    executor=execute_fixed_section,
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
                    phase="analysis",
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
                    phase="analysis",
                    last_error={
                        "phase": "section",
                        "code": code,
                        "message": message or "独立章节阶段失败。",
                        "sectionCode": work_item.section_code,
                        "retryReason": code,
                        "details": dict(error.details)
                        if isinstance(error, ReportingError) and isinstance(error.details, Mapping)
                        else None,
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
                    sectionNumber=item.section_number,
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
        await self.report_tools.complete_document_heading_numbers(
            str(self._workflow_result(self._state(run_context))["jobId"]),
            [item.model_dump(mode="json", by_alias=True) for item in rendered.heading_numbers],
            run_context=self._tool_context(run_context),
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
            task_key=analysis_task_id,
            section_numbers=rendered.section_numbers,
            heading_numbers=rendered.heading_numbers,
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

    async def _build_reporting_artifact(
        self,
        run_context: RunContext,
        *,
        analysis_ids: Sequence[str],
        detailed_plan: DetailedAnalysisPlan,
        fact_files: Mapping[str, FileIdentity],
        citation_bindings: tuple[Citation, ...],
        section_codes: Sequence[str] | None = None,
    ) -> AnalysisArtifact:
        """从本次运行的 durable analysisItems 和章节图表确定性构造分析产物。

        章节 Agent 只能消费这里派生的 facts/evidence/charts；模型没有第二个全局登记
        入口。Dataset/evidence 文件身份漂移由既有工具记录为 warning，不改变发布路径。
        """
        scope = self._scope(run_context)
        durable = await self.state_repository.get(str(run_context.run_id or scope["externalRunId"]))
        payload = durable.payload if durable is not None else {}
        raw_items = payload.get("analysisItems", {})
        if not isinstance(raw_items, Mapping):
            raise ReportingError("report_analysis_evidence_invalid", "durable analysisItems 无效。")
        selected_ids = tuple(analysis_ids)
        evidence: list[AnalysisEvidence] = []
        fact_bundles: dict[str, Mapping[str, Any]] = {}
        warnings: list[str] = [
            str(item.get("message"))
            for item in payload.get("warnings", ())
            if isinstance(item, Mapping) and item.get("message")
        ]
        plans_by_id = {item.analysis_id: item for item in detailed_plan.analyses}
        for analysis_id in selected_ids:
            raw_item = raw_items.get(analysis_id)
            if not isinstance(raw_item, Mapping):
                raise ReportingError(
                    "report_analysis_evidence_incomplete", f"analysisId {analysis_id} 尚未完成。"
                )
            evidence.append(AnalysisEvidence.model_validate(raw_item))
            try:
                fact = await self._read_identity_model(
                    scope["threadId"], fact_files[analysis_id], DeterministicAnalysisBundle
                )
            except ReportingError as error:
                if error.code != "report_phase_artifact_changed":
                    raise
                # facts 身份漂移只作质量告警；仍读取当前完整 JSON，缺失或结构损坏继续失败。
                warnings.append(
                    f"analysisId {analysis_id} 的 facts 文件身份或 SHA-256 已变化，已按当前内容继续发布。"
                )
                _relative, remote = self.workspace_service.normalize_path(
                    fact_files[analysis_id].path, allow_root=False
                )
                async with self.workspace_service._async_client() as client:
                    sandbox = await self.workspace_service._asandbox_for(client, scope["threadId"])
                    content = await self.workspace_service._adownload_file(
                        sandbox, remote, 10 * 1024 * 1024
                    )
                try:
                    fact = DeterministicAnalysisBundle.model_validate_json(content)
                except ValidationError as validation_error:
                    raise ReportingError(
                        "report_phase_artifact_invalid", "固定 facts 文件结构无效。"
                    ) from validation_error
            fact_bundles[analysis_id] = fact.model_dump(mode="json", by_alias=True)

        dataset_ids = tuple(
            dict.fromkeys(dataset_id for item in evidence for dataset_id in item.dataset_ids)
        )
        plans = {
            analysis_id: _reporting_detailed_analysis_plan(
                detailed_plan, analysis_ids=(analysis_id,)
            )["analyses"][0]
            for analysis_id in selected_ids
            if analysis_id in plans_by_id
        }
        dataset_semantics, metric_definitions, findings = _finalize_semantic_catalog(
            analysis_plans=plans,
            fact_bundles=fact_bundles,
            dataset_ids=dataset_ids,
        )
        chart_values: list[AnalysisChart] = []
        visualization_sections = payload.get("visualizationSections", {})
        if isinstance(visualization_sections, Mapping):
            selected_section_codes = set(section_codes) if section_codes is not None else None
            outline = _frozen_outline(self._state(run_context))
            ordered_sections = tuple(
                section
                for section in outline.sections
                if selected_section_codes is None or section.code in selected_section_codes
            )
            file_by_path: dict[str, Mapping[str, Any]] = {}
            for section in ordered_sections:
                section_payload = visualization_sections.get(section.code)
                if not isinstance(section_payload, Mapping):
                    continue
                for raw_file in section_payload.get("files", ()):
                    if isinstance(raw_file, Mapping) and isinstance(raw_file.get("path"), str):
                        file_by_path[raw_file["path"]] = raw_file
            for section in ordered_sections:
                section_payload = visualization_sections.get(section.code)
                if not isinstance(section_payload, Mapping):
                    continue
                for raw_chart in section_payload.get("charts", ()):
                    if not isinstance(raw_chart, Mapping):
                        continue
                    source_path = raw_chart.get("sourcePath")
                    if not isinstance(source_path, str):
                        continue
                    source_file = file_by_path.get(source_path)
                    if source_file is None:
                        continue
                    inspection = ChartVisualInspectionReceipt(
                        sourcePath=source_path,
                        sha256=str(source_file.get("sha256", "")),
                        inspectionMode="deterministic",
                        visualReviewStatus="not_run",
                        inspectorId="deterministic-raster-inspector-v1",
                        reviewed=True,
                        requiresRevision=False,
                    )
                    chart_values.append(
                        AnalysisChart.model_validate(
                            {
                                # sourcePath 仅是 visualizationSections 内部索引键；
                                # AnalysisChart 的稳定契约以带哈希的 sourceFile 表达文件身份。
                                # 不得把内部索引字段带入 extra=forbid 的最终分析产物。
                                **{
                                    key: value
                                    for key, value in raw_chart.items()
                                    if key != "sourcePath"
                                },
                                "sourceFile": dict(source_file),
                                "visualInspectionReceipt": inspection.model_dump(
                                    mode="json", by_alias=True
                                ),
                            }
                        )
                    )
        warnings.extend(
            warning
            for item in evidence
            for warning in item.warnings
            if isinstance(warning, str) and warning
        )
        warnings.extend(
            item["message"]
            for item in findings
            if isinstance(item, Mapping) and item.get("message")
        )
        receipts = tuple(
            ProfileReadReceipt.model_validate(item)
            for item in payload.get("profileReadReceipts", ())
            if isinstance(item, Mapping)
        )
        report_goal = self._envelope(run_context).report_goal
        questions = tuple(item.management_question for item in detailed_plan.analyses)
        outline = _frozen_outline(self._state(run_context))
        selected_id_set = set(selected_ids)
        ordered_analysis_ids = tuple(
            analysis_id
            for section in outline.sections
            for analysis_id in section.analysis_ids
            if analysis_id in selected_id_set
        )
        ordered_analysis_ids += tuple(
            analysis_id for analysis_id in selected_ids if analysis_id not in ordered_analysis_ids
        )
        evidence_by_id = {item.analysis_id: item for item in evidence}
        summary = "；".join(
            evidence_by_id[analysis_id].summary
            for analysis_id in ordered_analysis_ids
            if analysis_id in evidence_by_id
        )
        return AnalysisArtifact(
            reportBrief=ReportBrief(
                objective=report_goal,
                executiveSummary=summary or "已完成冻结分析。",
                managementQuestions=questions or (report_goal,),
                warnings=tuple(dict.fromkeys(warnings))[-500:],
            ),
            evidenceManifest=AnalysisEvidenceManifest(
                evidence=tuple(evidence),
                metricDefinitions=tuple(
                    MetricDefinition.model_validate(item) for item in metric_definitions
                ),
                charts=tuple(chart_values),
                datasetSemantics=tuple(
                    AnalysisDatasetSemantics.model_validate(item) for item in dataset_semantics
                ),
                warnings=tuple(dict.fromkeys(warnings))[-500:],
            ),
            profileReadReceipts=receipts,
            profileReadReceiptIds=tuple(item.receipt_id for item in receipts),
        )
