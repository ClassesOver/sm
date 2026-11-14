# mypy: disable-error-code="attr-defined"
# 运行时由 Facade 组合的多重继承提供跨阶段成员；静态检查无法解析该装配。
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Literal

from pydantic import ConfigDict, Field
from sqlglot import exp

from ....report_editor.service import ReportEditorContext
from ....workspace import WorkspacePathConflict
from ...delivery.artifacts_v1 import ArtifactFile, ReportArtifactManifest
from ...semantics.basis import BasisCalculationReceipt, BasisSelectionReceipt
from ...semantics.models import MetricDefinition, SemanticIssue
from ...semantics.selection import MetricSelectionProposal
from ...structured_output import StructuredOutputCallBudget
from ...trace.contracts_v1 import RevisionTraceIndexV1, derive_resource_id
from ..query_pipeline import period_column_has_time
from .base import (
    _PLANNER_DISPLAY_NAMES,
    DOMAIN_CODES,
    REPORT_ANALYSIS_PLAN_STATE_KEY,
    REPORT_APPROVED_QUERIES_STATE_KEY,
    REPORT_CAPABILITIES_STATE_KEY,
    REPORT_DATA_REQUIREMENTS_STATE_KEY,
    REPORT_DATA_SHAPE_ISSUES_STATE_KEY,
    REPORT_DATA_SHAPES_STATE_KEY,
    REPORT_DATA_UNDERSTANDING_STATE_KEY,
    REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
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
    GeneratedQueryBatch,
    Mapping,
    ModelColumn,
    ModelTable,
    ModelTermsResponse,
    NormalizedReportPrompt,
    PlanningSchema,
    PlanningSchemaColumn,
    PlanningSchemaTable,
    QueryRequirement,
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
    _json_text,
    _planner_input_token_budget,
    _planner_request_token_counter,
    _validation_issue,
    anyio,
    approve_query_batch,
    cli_result,
    collect_data_shape,
    complete_cleanup,
    date,
    freeze_outline,
    infer_delivery_format,
    json,
    logger,
    loguru_logger,
    parse_ddl,
    parse_reporting_workflow_input,
    payload_sha256,
    publication_result,
    re,
    resolve_profile_capabilities,
    resolve_reporting_workflow_scope,
    resolve_schema_snapshot,
)
from .validation import (
    SPLIT_REQUIREMENTS_ACTION,
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



def _apply_bundle_normalizers(
    bundle: AnalysisBundle,
    *normalizers: Callable[[AnalysisBundle], tuple[AnalysisBundle, list[dict[str, Any]]]],
) -> tuple[AnalysisBundle, bool]:
    """按顺序应用服务端确定性修复；只有产生修复记录时才采用归一化结果。"""

    repaired = False
    for normalize in normalizers:
        normalized, repairs = normalize(bundle)
        if repairs:
            bundle, repaired = normalized, True
    return bundle, repaired


class _TerminalCleanupTrace(BaseModel):
    """终态清理只读取关闭 phase task 所需的受限身份。"""

    model_config = ConfigDict(extra="ignore")

    task_id: str | None = Field(default=None, alias="taskId", max_length=128)


class _TerminalCleanupCheckpoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    trace: tuple[_TerminalCleanupTrace, ...] = Field(default=(), max_length=2000)


class RuntimePlanningMixin:
    async def select_report_metrics(
        self, step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        """首轮选择以不可变回执恢复，模型只能提出已发布指标候选。"""
        from ....management.models import ManagementError, ManagementScope

        context = await self._basis_execution_context(run_context)
        scope = self._scope(run_context)
        identity = {
            "user_id": scope["userId"], "thread_id": scope["callerThreadId"],
            "report_revision": "initial",
        }
        managed_scope = ManagementScope(scope["database"], scope["companyId"])
        service = self.report_basis_service
        try:
            receipts = await service.load_basis_receipts(
                str(run_context.run_id), managed_scope, **identity,
            )
            stored = next((item for item in receipts if isinstance(item, BasisSelectionReceipt)
                and item.receipt_id == "initial-metric-selection"), None)
            if stored is None:
                proposal = MetricSelectionProposal.model_validate(await self._run_planner(
                    self._metric_selection_agent, {
                        "questions": [item.model_dump(mode="json", by_alias=True)
                            for item in context.basis.request_summary.questions],
                        "metrics": [item.model_dump(mode="json", by_alias=True)
                            for item in context.metrics if item.version_ref() in context.policy.metric_versions],
                        "request": context.basis.request_summary.model_dump(mode="json", by_alias=True),
                    }, run_context,
                ))
                stored = await service.append_selection_receipt(
                    str(run_context.run_id), managed_scope, **identity,
                    receipt_id="initial-metric-selection",
                    requests=[item.model_dump(mode="json", by_alias=True) for item in proposal.questions],
                    vault=self.configuration_provider.vault,
                )
        except ManagementError as error:
            raise ReportingError(error.code, error.message) from error
        return StepOutput(content=stored.model_dump(mode="json", by_alias=True))

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
        reference_materials = state.get("report_reference_materials", [])
        reference_issues = state.get("report_reference_issues", [])
        if isinstance(request, ReportRequestEnvelope):
            self._record_request_context(
                state,
                request.report_goal,
                feedback,
                request.delivery_format,
            )
            frozen_format = state[REPORT_REQUEST_CONTEXT_STATE_KEY]["deliveryFormat"]
            if frozen_format != request.delivery_format:
                request = request.model_copy(update={"delivery_format": frozen_format})
            self._record_normalized_request(state, request)
            return StepOutput(
                content=request.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_unset=True)
            )

        assert isinstance(request, ReportPromptInput)
        prompt_payload: dict[str, Any] = {"prompt": request.prompt}
        if reference_materials or reference_issues:
            prompt_payload["referenceMaterials"] = [
                {
                    "filename": item.get("filename"),
                    "content": item.get("content", "")[:20_000],
                    "layout": item.get("layout", {}),
                    "visualLayout": item.get("visualLayout"),
                }
                for item in reference_materials
            ]
            prompt_payload["referenceIssues"] = reference_issues
        if state.get("report_template_input"):
            template = state["report_template_input"]
            prompt_payload["templateInput"] = {key: template[key] for key in
                ("identity", "filename", "content", "layout", "businessFactsAllowed") if key in template}
        if feedback:
            prompt_payload["supplement"] = feedback
        basis_service = getattr(self, "report_basis_service", None)
        scenario_candidates = None
        if basis_service is not None:
            from ....management.models import ManagementScope

            scope = self._scope(run_context)
            scenario_candidates = await basis_service.scenario_candidates(
                str(run_context.run_id), ManagementScope(scope["database"], scope["companyId"]),
                user_id=scope["userId"], thread_id=scope["callerThreadId"],
            )
            prompt_payload["scenarioCandidates"] = [
                item.model_dump(mode="json", by_alias=True) for item in scenario_candidates]
        normalized = await self._run_planner(self._request_normalizer, prompt_payload, run_context)
        assert isinstance(normalized, NormalizedReportPrompt)
        # 恢复时沿用已冻结的交付格式，不重新解释原始需求。
        frozen = state.get(REPORT_REQUEST_CONTEXT_STATE_KEY)
        frozen_format = (
            frozen.get("deliveryFormat")
            if isinstance(frozen, dict) and request.delivery_format is None
            else None
        )
        if request.delivery_format is None and frozen_format is None and normalized.delivery_format_ambiguous:
            return StepOutput(content={"clarificationQuestion": normalized.clarification_question
                or "请选择本次交付形式：PDF/Word、演示文稿或 Excel 工作簿。"})
        delivery_format = (
            request.delivery_format or frozen_format or normalized.delivery_format
            or infer_delivery_format(request.prompt)
        )
        self._record_request_context(state, request.prompt, feedback, delivery_format)
        period = normalized.period or _single_explicit_period(request.prompt, feedback)
        missing: list[str] = []
        if scenario_candidates is not None and normalized.scenario not in {
            item.scenario for item in scenario_candidates
        }:
            missing.append("请明确已登记的报告场景；尚未登记统计口径的场景暂不可选用。")
        if period is None:
            missing.append(normalized.clarification_question or "请明确唯一的分析期间。")
        semantic_domains = tuple(dict.fromkeys(normalized.domains))
        report_type = normalized.report_type
        if report_type is None:
            missing.append(
                normalized.clarification_question or "请明确报告是整体运营分析还是专题分析。"
            )
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
                **({"scenario": normalized.scenario} if normalized.scenario else {}),
                **({"questions": [item.model_dump(mode="json", by_alias=True) for item in normalized.questions]}
                    if normalized.questions else {}),
                **({"displayUnit": normalized.display_unit} if normalized.display_unit else {}),
                **({"comparisonPeriod": normalized.comparison_period.model_dump(mode="json")}
                    if normalized.comparison_period else {}),
                "reportType": report_type,
                "deliveryFormat": delivery_format,
                **({"fileInputs": [item.model_dump(mode="json", by_alias=True) for item in request.file_inputs]}
                    if request.file_inputs else {}),
                **({"templateInput": request.template_input.model_dump(mode="json", by_alias=True)}
                    if request.template_input else {}),
                **({"sectionCount": normalized.section_count} if normalized.section_count is not None else {}),
                **({"domains": domains} if domains else {}),
                "period": period.model_dump(mode="json"),
            }
        )
        self._record_normalized_request(state, envelope)
        return StepOutput(
            content=envelope.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_unset=True)
        )

    @staticmethod
    def _record_request_context(
        state: dict[str, Any],
        original_goal: str,
        feedback: str | None,
        delivery_format: str,
    ) -> None:
        current = state.get(REPORT_REQUEST_CONTEXT_STATE_KEY)
        if not isinstance(current, dict):
            import os

            mode = os.environ.get("REPORT_ASSERTION_MODE", "shadow")
            current = {"originalGoal": original_goal, "feedback": [], "deliveryFormat": delivery_format, "assertionPolicy": {
                "version": "1", "mode": mode if mode in {"off", "shadow", "enabled"} else "shadow",
                "ruleVersion": "assertions/1",
            }}
            state[REPORT_REQUEST_CONTEXT_STATE_KEY] = current
        elif current.get("originalGoal") != original_goal:
            raise ReportingError(
                "report_context_restart_required", "原始报告目标已变化，必须重新发起。"
            )
        frozen_format = current.setdefault("deliveryFormat", delivery_format)
        if frozen_format != delivery_format:
            raise ReportingError(
                "report_context_restart_required", "交付格式已冻结，必须重新发起。"
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
        from .request_materials import freeze_request_materials

        freeze_request_materials(state, envelope)
        current = state.get(REPORT_REQUEST_CONTEXT_STATE_KEY)
        if not isinstance(current, dict):
            raise ReportingError("report_workflow_state_invalid", "报表请求语境状态无效。")
        # Pin at run creation; a restart or deployment toggle must not silently
        # change an in-flight run's authoring contract.
        current.setdefault("assertionPolicy", {
            "version": "1", "mode": "shadow",
            "ruleVersion": "assertions/1",
        })
        from ..questions import request_questions

        fresh = request_questions(
            current["originalGoal"], tuple(item["content"] for item in current.get("feedback", ())
                                           if isinstance(item, dict) and isinstance(item.get("content"), str)),
            questions=envelope.questions or (),
        )
        stored = current.get("questionSpecs") or {}
        # 已冻结到分析阶段的问题只在请求未变时沿用；同一会话追加反馈会带来新的必答问题，
        # 须重新从请求阶段冻结，否则新反馈永远不进入必答问题。
        if stored.get("stage") != "analysis" or set(fresh.required_question_ids) - set(
            stored.get("requiredQuestionIds", ())
        ):
            current["questionSpecs"] = fresh.model_dump(mode="json", by_alias=True)
        current.update(
            {
                "knowledgeAsOf": envelope.knowledge_as_of.isoformat().replace("+00:00", "Z") if envelope.knowledge_as_of else None,
                "scenario": envelope.scenario,
                "statisticalPolicyVersion": (envelope.statistical_policy_version.model_dump(mode="json", by_alias=True)
                    if envelope.statistical_policy_version else None),
                "questions": ([item.model_dump(mode="json", by_alias=True) for item in envelope.questions]
                    if envelope.questions else None),
                "displayUnit": envelope.display_unit,
                "comparisonPeriod": (envelope.comparison_period.model_dump(mode="json")
                    if envelope.comparison_period else None),
                "reportType": envelope.report_type,
                "deliveryFormat": envelope.delivery_format,
                "sectionCount": envelope.section_count,
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
            # 跳过已启动任务。这里只验证并读取 taskId，任何结构损坏都会阻止释放
            # 工作区，避免遗漏仍在运行的 phase task。
            checkpoint = _TerminalCleanupCheckpoint.model_validate(stored_checkpoint)
            task_ids = tuple(
                dict.fromkeys(item.task_id for item in checkpoint.trace if item.task_id)
            )

        # phase task 的 ID 包含 revision、work item 和 attempt，不能由 Workflow run ID
        # 反推。必须以启动任务前持久化的 trace 为事实来源，并在全部活动任务关闭后
        # 才释放共享工作区；任一查询或取消失败都保留现场供后续重试清理。
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
        self._release_workspace(scope["thread_id"])

    def _release_workspace(self, thread_id: str) -> None:
        # 只释放进程内 Workspace 身份，保留会话目录和全部产物供审计/恢复与报告编辑器续写。
        if getattr(self, "workspace_registry", None) is None:
            return
        self.workspace_registry.release(thread_id)
        getattr(self, "_host_workspaces", {}).pop(thread_id, None)
        loguru_logger.info("report_host_workspace_released workspace_key={}", thread_id)

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
        if download_grants is None or artifact_persistence is None:
            raise RuntimeError("HTTP 报表发布依赖配置不完整")
        report_public_base_url = self.report_public_base_url
        if report_public_base_url is None:
            raise RuntimeError("HTTP 报表发布缺少公开下载基址")
        content = self._publication_content(output)
        if content.get("deliveryFormat") in {"pptx", "xlsx"}:
            return await self._issue_http_office_publication(
                delivery_format=content["deliveryFormat"],
                thread_id=thread_id,
                caller_thread_id=caller_thread_id,
                user_id=user_id,
                workflow_session_id=workflow_session_id,
                workflow_run_id=workflow_run_id,
                dependencies=dependencies,
                content=content,
                base_url=report_public_base_url,
            )
        if editor_grants is None:
            raise RuntimeError("HTTP 报表发布缺少编辑授权服务")
        source_manifest = None
        source_index = None
        manifest_identity = None
        # AGENTS：清单/追溯索引核验失败属于发布门禁问题，不得阻止已生成 PDF/Word 的签发。
        # 失败时不使用该清单与索引（新修订不带溯源），照常签发并返回问题。
        publication_issues: list[dict[str, str]] = []

        def _drop_lineage(error: Exception) -> None:
            nonlocal source_manifest, source_index, manifest_identity
            source_manifest = source_index = manifest_identity = None
            content["artifactManifest"] = None
            content.pop("artifactManifestPath", None)
            code = error.code if isinstance(error, ReportingError) else "report_lineage_unavailable"
            loguru_logger.warning(
                "report_publication_lineage_dropped report_id={} code={} error_type={}",
                content["reportId"], code, type(error).__name__,
            )
            publication_issues.append({
                "code": code,
                "message": "报告溯源清单或索引核验未通过，本修订不提供来源追溯；下载链接已签发。",
            })

        if content.get("artifactManifest") is not None:
            try:
                manifest_identity = ArtifactFile.model_validate(content["artifactManifest"])
                manifest_bytes = await self.workspace_service.read_limited_regular_file(
                    thread_id, manifest_identity.path, max_bytes=manifest_identity.size
                )
                if (
                    len(manifest_bytes) != manifest_identity.size
                    or sha256(manifest_bytes).hexdigest() != manifest_identity.sha256
                ):
                    raise ReportingError(
                        "report_artifact_manifest_changed", "已验收报告产物清单发生变化。"
                    )
                source_manifest = ReportArtifactManifest.model_validate_json(manifest_bytes)
                if (
                    source_manifest.report_id != content["reportId"]
                    or source_manifest.markdown.path != content["markdownPath"]
                    or source_manifest.revision not in {content["revision"], content["revision"] - 1}
                ):
                    raise ReportingError(
                        "report_artifact_manifest_invalid", "报告产物清单与发布身份不一致。"
                    )
                if source_manifest.trace_index is not None:
                    index_file = source_manifest.trace_index
                    index_bytes = await self.workspace_service.read_limited_regular_file(
                        thread_id, index_file.path, max_bytes=index_file.size
                    )
                    if (
                        len(index_bytes) != index_file.size
                        or sha256(index_bytes).hexdigest() != index_file.sha256
                    ):
                        raise ReportingError(
                            "report_trace_index_changed", "已验收追溯索引发生变化。"
                        )
                    source_index = RevisionTraceIndexV1.model_validate_json(index_bytes)
                    index_markdown = next(
                        (file for file in source_index.files
                         if file.resource_id == source_index.markdown_file_resource_id),
                        None,
                    )
                    if (
                        index_markdown is None
                        or source_index.report_basis_id != source_manifest.report_basis_id
                        or source_index.report_id != source_manifest.report_id
                        or source_index.revision != source_manifest.revision
                        or source_index.workflow_run_id != workflow_run_id
                        or source_index.markdown_file_resource_id
                        != derive_resource_id(source_manifest.markdown.path)
                        or index_markdown.path != source_manifest.markdown.path
                        or index_markdown.size != source_manifest.markdown.size
                        or index_markdown.sha256 != source_manifest.markdown.sha256
                    ):
                        raise ReportingError(
                            "report_trace_index_invalid", "报告追溯索引与发布身份不一致。"
                        )
            except Exception as error:  # noqa: BLE001 - 溯源是附加能力，任意故障均不得阻断签发
                _drop_lineage(error)
        source_markdown = PurePosixPath(content["markdownPath"])
        revision_directory = f"revision-{content['revision']}"
        default_revision_markdown = (
            source_markdown
            if source_markdown.parent.name == revision_directory
            else source_markdown.parent / revision_directory / source_markdown.name
        )

        async def _prepare_editor_snapshot() -> tuple[PurePosixPath, dict[str, Any]]:
            """准备可选编辑快照；失败由调用方降级，不能影响 PDF/Word 签发。"""

            revision_markdown = default_revision_markdown
            editor_job = deepcopy(content["editorJob"])
            path_map: dict[str, str] = {}
            if revision_markdown != source_markdown:
                markdown = await self.workspace_service.aread_text(
                    thread_id, str(source_markdown)
                )
                if await self.workspace_service.apath_exists(
                    thread_id, str(revision_markdown)
                ):
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
                source_root = source_markdown.parent
                target_root = revision_markdown.parent

                async def _copy_asset(source_path: str) -> str | None:
                    try:
                        relative = PurePosixPath(source_path).relative_to(source_root)
                    except ValueError:
                        return None
                    target_path = str(target_root / relative)
                    if target_path == source_path:
                        return target_path
                    if not await self.workspace_service.apath_exists(thread_id, source_path):
                        return None
                    content_bytes, _ = await self.workspace_service.afile_bytes(
                        thread_id, source_path
                    )
                    try:
                        await self.workspace_service.awrite_bytes(
                            thread_id, target_path, content_bytes
                        )
                    except WorkspacePathConflict:
                        existing_bytes, _ = await self.workspace_service.afile_bytes(
                            thread_id, target_path
                        )
                        if existing_bytes != content_bytes:
                            raise ReportingError(
                                "report_editor_revision_conflict",
                                "当前报告 revision 已存在不同的资源快照。",
                            ) from None
                    path_map[source_path] = target_path
                    return target_path

                render = editor_job.get("render") or {}
                images = render.get("images") if isinstance(render, dict) else None
                if isinstance(images, list):
                    for image in images:
                        if isinstance(image, dict):
                            await _copy_asset(image.get("path", ""))


                def _remap_paths(obj: Any) -> Any:
                    if isinstance(obj, dict):
                        return {
                            path_map.get(key, key): _remap_paths(value)
                            for key, value in obj.items()
                        }
                    if isinstance(obj, list):
                        return [_remap_paths(item) for item in obj]
                    if isinstance(obj, str) and obj in path_map:
                        return path_map[obj]
                    return obj

                editor_job = _remap_paths(editor_job)
            if source_manifest is not None and manifest_identity is not None:
                from ....report_editor.trace_revisions import (
                    snapshot_revision_lineage,
                    verify_revision_lineage_files,
                )

                if source_markdown == revision_markdown and source_manifest.revision == content['revision']:
                    try:
                        await verify_revision_lineage_files(self.workspace_service, thread_id,
                            manifest=source_manifest, index=source_index)
                    except Exception as error:
                        _drop_lineage(error)
                    # 本修订已经冻结在目标目录；重写清单/索引会与原不可变登记冲突。
                    return revision_markdown, editor_job
                target_manifest_path = str(
                    revision_markdown.parent / PurePosixPath(manifest_identity.path).name
                )
                source_root = source_markdown.parent
                target_root = revision_markdown.parent
                source_paths = [chart.path for chart in source_manifest.charts]
                if source_index is not None:
                    source_paths.extend(str(item.path) for item in source_index.files)
                for source_path in source_paths:
                    if source_path == str(source_markdown):
                        path_map[source_path] = str(revision_markdown)
                        continue
                    try:
                        relative = PurePosixPath(source_path).relative_to(source_root)
                    except ValueError:
                        relative = PurePosixPath("trace-resources") / source_path
                    path_map.setdefault(source_path, str(target_root / relative))
                try:
                    _relocated_manifest, relocated_identity = await snapshot_revision_lineage(
                        self.workspace_service,
                        thread_id,
                        manifest=source_manifest,
                        index=source_index,
                        markdown_file=ArtifactFile(
                            path=str(revision_markdown),
                            mediaType="text/markdown",
                            size=source_manifest.markdown.size,
                            sha256=source_manifest.markdown.sha256,
                        ),
                        target_revision=int(content["revision"]),
                        path_map=path_map,
                        manifest_path=target_manifest_path,
                    )
                except Exception as error:  # noqa: BLE001 - 溯源故障只降级来源能力
                    _drop_lineage(error)
                else:
                    content["artifactManifestPath"] = relocated_identity.path
                    content["artifactManifest"] = relocated_identity.model_dump(
                        mode="json", by_alias=True
                    )
            return revision_markdown, editor_job

        editor_available = content.get('editorAvailable', True) is True
        try:
            if not editor_available:
                raise ValueError('published editor input unavailable')
            revision_markdown, editor_job = await _prepare_editor_snapshot()
        except Exception as error:  # noqa: BLE001 - 编辑快照是附加交付项
            editor_available = False
            revision_markdown = default_revision_markdown
            editor_job = deepcopy(content["editorJob"])
            loguru_logger.warning(
                "report_editor_snapshot_failed report_id={} revision={} error_type={}",
                content["reportId"], content["revision"], type(error).__name__,
            )
            publication_issues.append({
                "code": "report_editor_snapshot_unavailable",
                "message": "编辑快照准备失败，PDF/Word 下载链接已签发；本修订暂不提供编辑入口。",
            })
        content["editorJob"] = editor_job
        try:
            durable = await self.state_repository.get(workflow_run_id)
        except Exception as error:  # noqa: BLE001 - 状态读取只影响编辑入口，不能阻断下载签发
            durable = None
            editor_available = False
            loguru_logger.warning(
                "report_editor_context_read_failed report_id={} revision={} error_type={}",
                content["reportId"], content["revision"], type(error).__name__,
            )
            publication_issues.append({
                "code": "report_editor_context_unavailable",
                "message": "报告编辑上下文读取失败，PDF/Word 下载链接已签发；本修订暂不提供编辑入口。",
            })
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
            # AGENTS：作用域不一致只拒绝使用编辑上下文，不能拒绝签发已核验身份的 PDF/Word。
            if editor_available:
                loguru_logger.warning(
                    "report_editor_scope_mismatch report_id={} revision={} durable_missing={}",
                    content["reportId"], content["revision"], durable is None,
                )
                publication_issues.append({
                    "code": "report_editor_scope_mismatch",
                    "message": "报告编辑上下文与发布作用域不一致，PDF/Word 下载链接已签发；本修订不提供编辑入口。",
                })
            editor_available = False
        # 下载 grant 本身是 256 bit 随机 bearer 凭证。Scope 仅用于持久化产物身份、
        # 修订撤销和审计，不再作为下载时的调用方权限条件。必须与编辑器导出使用同一
        # 解析作用域：撤销与防回退按 database/company 精确匹配，写死常量会让编辑器
        # 导出的新 revision 无法撤销首次发布的旧链接。
        download_scope = ReportDownloadScope(
            database=scope.database,
            user_id=user_id,
            company_id=scope.company_id,
            session_id=workflow_session_id,
            thread_id=thread_id,
            workflow_run_id=workflow_run_id,
        )
        format_labels: tuple[Literal["pdf", "word"], ...] = ("pdf", "word")
        selected_specs = tuple(
            ReportArtifactSpec(artifact=label, path=content[f"{label}Path"], size=content[f"{label}Size"], sha256=content[f"{label}Sha256"])
            for label in format_labels if content.get(f"{label}Path")
        )
        if hasattr(artifact_persistence, "persist_available"):
            saved_specs = await artifact_persistence.persist_available(
                scope=download_scope,
                report_id=content["reportId"],
                revision=content["revision"],
                artifacts=selected_specs,
            )
        else:
            await artifact_persistence.persist(scope=download_scope, report_id=content["reportId"], revision=content["revision"], artifacts=selected_specs)
            saved_specs = selected_specs
        saved_labels = {spec.artifact for spec in saved_specs}
        for spec in selected_specs:
            if spec.artifact not in saved_labels:
                for suffix in ("Path", "Size", "Sha256"):
                    content.pop(f"{spec.artifact}{suffix}", None)
                publication_issues.append({"code": "report_format_persistence_failed", "message": f"{'PDF' if spec.artifact == 'pdf' else 'Word'} 持久化失败，其他已保存格式仍可下载。"})
        editor_context: ReportEditorContext | None = None
        if editor_available:
            try:
                editor_context = ReportEditorContext(
                    reportId=content["reportId"],
                    revision=content["revision"],
                    jobId=content["jobId"],
                    workflowRunId=workflow_run_id,
                    markdownPath=str(revision_markdown),
                    artifactManifest=content.get("artifactManifest"),
                    analysisContextFile=content.get("analysisContextFile"),
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
                        commandId=(
                            f"editor-context:{content['revision']}:{editor_context.digest()}"
                        ),
                    ),
                    expected_version=durable.state_version,
                )
            except Exception as error:  # noqa: BLE001 - 编辑上下文不能阻断下载签发
                editor_context = None
                loguru_logger.warning(
                    "report_editor_context_failed report_id={} revision={} error_type={}",
                    content["reportId"], content["revision"], type(error).__name__,
                )
                publication_issues.append({
                    "code": "report_editor_context_unavailable",
                    "message": "编辑上下文保存失败，PDF/Word 下载链接已签发；本修订暂不提供编辑入口。",
                })
        self._release_workspace(thread_id)
        # 产物已经落库，签发失败后的重试可以直接复用持久化身份。
        raw, grant = await download_grants.issue(
            scope=download_scope,
            report_id=content["reportId"],
            revision=content["revision"],
            pdf_path=content.get("pdfPath"),
            pdf_size=content.get("pdfSize"),
            pdf_sha256=content.get("pdfSha256"),
            word_path=content.get("wordPath"),
            word_size=content.get("wordSize"),
            word_sha256=content.get("wordSha256"),
        )
        editor_raw: str | None = None
        editor_expires_at: datetime | None = None
        if editor_context is not None:
            try:
                editor_raw, editor_expires_at = await editor_grants.issue(editor_context)
            except Exception as error:
                # 编辑入口是附加交付项；下载凭证已签发，不能因编辑授权失败丢弃下载链接。
                loguru_logger.warning(
                    "report_editor_grant_failed report_id={} revision={} error_type={}",
                    content["reportId"], content["revision"], type(error).__name__,
                )
                publication_issues.append({
                    "code": "report_editor_grant_unavailable",
                    "message": "编辑链接签发失败，PDF/Word 下载链接已签发；请稍后重新打开报告编辑入口。",
                })
        result = publication_result(
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
        if publication_issues:
            result["publicationIssues"] = publication_issues
        if isinstance(content.get("validation"), dict):
            result["validation"] = content["validation"]
            result["validationIssues"] = list(content.get("validationIssues") or [])
        return result

    async def _issue_http_pptx_publication(self, **values: Any) -> dict[str, Any]:
        return await self._issue_http_office_publication(delivery_format="pptx", **values)

    async def _issue_http_xlsx_publication(self, **values: Any) -> dict[str, Any]:
        return await self._issue_http_office_publication(delivery_format="xlsx", **values)

    async def _issue_http_office_publication(
        self,
        *,
        delivery_format: Literal["pptx", "xlsx"],
        thread_id: str,
        caller_thread_id: str,
        user_id: str,
        workflow_session_id: str,
        workflow_run_id: str,
        dependencies: dict[str, Any] | None,
        content: dict[str, Any],
        base_url: str,
    ) -> dict[str, Any]:
        """签发共享工作流的演示文稿/工作簿；编辑和验收故障不丢失可读产物。"""
        label = delivery_format.upper()
        editor_kind = "slides" if delivery_format == "pptx" else "workbooks"
        gate = content.get("publicationGate")
        if not isinstance(gate, dict):
            gate = {"formalReleaseAllowed": False, "issues": []}
        issues: list[dict[str, Any]] = []
        path = content.get(f"{delivery_format}Path")
        size = content.get(f"{delivery_format}Size")
        digest = content.get(f"{delivery_format}Sha256")
        selected: tuple[ReportArtifactSpec, ...] = ()
        if isinstance(path, str) and path:
            try:
                actual = await self.workspace_service.ahash_file(thread_id, path)
                if actual.get("missing") or actual.get("size") != size or actual.get("sha256") != digest:
                    raise ReportingError(f"report_{delivery_format}_identity_changed", f"{label} 文件身份发生变化。")
                selected = (ReportArtifactSpec(artifact=delivery_format, path=path, size=size, sha256=digest),)
            except Exception as error:
                issues.append({
                    "code": error.code if isinstance(error, ReportingError) else f"report_{delivery_format}_unavailable",
                    "message": f"{label} 身份无法核验，未签发下载链接。",
                })
        scope = resolve_reporting_workflow_scope(
            run_id=workflow_run_id, session_id=workflow_session_id,
            user_id=user_id, dependencies=dependencies,
        )
        scope_matches = scope.caller_thread_id == caller_thread_id
        if not scope_matches:
            issues.append({"code": f"report_{delivery_format}_scope_mismatch",
                "message": f"{label} 编辑上下文作用域与请求不一致；已核验的文件下载仍继续签发。"})
        download_scope = ReportDownloadScope(
            database=scope.database, user_id=user_id, company_id=scope.company_id,
            session_id=workflow_session_id, thread_id=thread_id, workflow_run_id=workflow_run_id,
        )
        saved = ()
        if selected:
            try:
                saved = await self.artifact_persistence.persist_available(
                    scope=download_scope, report_id=content["reportId"],
                    revision=content["revision"], artifacts=selected,
                )
                if not any(item.artifact == delivery_format for item in saved):
                    saved = ()
                    issues.append({"code": f"report_{delivery_format}_persistence_failed",
                        "message": f"{label} 未完成持久化，使用已核验的工作区文件继续签发下载。"})
            except Exception as error:
                saved = ()
                issues.append({"code": f"report_{delivery_format}_persistence_failed",
                    "message": f"{label} 持久化失败，使用已核验的工作区文件继续签发下载。",
                    "details": {"errorType": type(error).__name__}})
        editor_context: ReportEditorContext | None = None
        editor_context_persisted = False
        editor_raw: str | None = None
        editor_expires_at: datetime | None = None
        if selected and self.editor_grants is not None and scope_matches and content.get('editorAvailable', True) is True:
            try:
                editor_context = ReportEditorContext(
                    reportId=content["reportId"], revision=content["revision"],
                    jobId=content["jobId"], workflowRunId=workflow_run_id,
                    markdownPath=content["markdownPath"], job=content["editorJob"],
                    scope=scope.as_state(), deliveryFormat=delivery_format,
                    artifactManifest=content.get("artifactManifest"),
                    analysisContextFile=content.get("analysisContextFile"),
                    **{f"{delivery_format}Path": path, f"{delivery_format}Size": size,
                       f"{delivery_format}Sha256": digest},
                )
                durable = await self.state_repository.get(workflow_run_id)
                if durable is None:
                    raise ReportingError("report_editor_context_missing", "报告编辑上下文不存在。")
                await self.state_repository.apply(
                    workflow_run_id,
                    ReportingCommand(name="set_report_editor_context",
                        payload={"context": editor_context.model_dump(mode="json", by_alias=True)},
                        commandId=f"editor-context:{content['revision']}:{editor_context.digest()}"),
                    expected_version=durable.state_version,
                )
                editor_context_persisted = True
                editor_raw, editor_expires_at = await self.editor_grants.issue(
                    editor_context, capabilities={f"{delivery_format}_editor": True},
                )
            except Exception as error:
                loguru_logger.warning("report_office_editor_grant_failed format={} error_type={}", delivery_format, type(error).__name__)
                issues.append({"code": f"report_{'slides' if delivery_format == 'pptx' else 'workbook'}_editor_unavailable",
                    "message": f"{label} 编辑入口暂不可用，已核验文件继续签发下载。"})
        elif selected:
            issues.append({"code": f"report_{'slides' if delivery_format == 'pptx' else 'workbook'}_editor_{'scope_mismatch' if not scope_matches else 'unavailable'}",
                "message": f"{label} 编辑授权不可用，已核验文件继续签发下载。"})
        raw = None
        grant = None
        if selected:
            # 持久化失败时保留工作区绑定，HTTP 下载按 grant 身份读取并复核原文件。
            try:
                raw, grant = await self.download_grants.issue(
                    scope=download_scope, report_id=content["reportId"], revision=content["revision"],
                    **{f"{delivery_format}_path": path, f"{delivery_format}_size": size,
                       f"{delivery_format}_sha256": digest},
                )
            except Exception as error:  # noqa: BLE001 - use the verified editor download fallback
                issues.append({"code": f"report_{delivery_format}_download_grant_failed",
                    "message": f"{label} 下载授权签发失败，将尝试使用编辑会话下载。",
                    "details": {"errorType": type(error).__name__}})
            else:
                if saved:
                    self._release_workspace(thread_id)
        fallback_raw: str | None = None
        fallback_expires_at: datetime | None = None
        if (grant is None or raw is None) and editor_context_persisted and editor_context is not None and self.editor_grants is not None and scope_matches:
            try:
                fallback_raw, fallback_expires_at = await self.editor_grants.issue(
                    editor_context, capabilities={f"{delivery_format}_download": True},
                )
            except Exception as error:  # noqa: BLE001 - retain the validation issue without blocking publication
                issues.append({"code": f"report_{delivery_format}_download_grant_failed",
                    "message": f"{label} 下载授权签发失败，已核验文件暂不可通过 HTTP 下载。",
                    "details": {"errorType": type(error).__name__}})
        if grant is None or raw is None:
            result: dict[str, Any] = {
                "reportId": content["reportId"], "revision": content["revision"],
                "sourceWarnings": list(content.get("sourceWarnings", ())),
                "codingReceipts": list(content.get("codingReceipts", ())),
            }
            if fallback_raw is not None and selected:
                result[delivery_format] = {
                    "downloadUrl": f"{base_url.rstrip('/')}/reports/v1/{editor_kind}/download/{fallback_raw}",
                    "path": path, "size": size, "sha256": digest,
                    "expiresAt": fallback_expires_at.isoformat() if fallback_expires_at else None,
                }
        else:
            result = publication_result(
                report_id=content["reportId"], revision=content["revision"],
                raw_grant=raw, grant=grant, base_url=base_url,
                editor_raw_grant=None, editor_expires_at=editor_expires_at,
                source_warnings=content.get("sourceWarnings"), task_receipts=content.get("codingReceipts"),
            )
        if editor_raw is not None and editor_expires_at is not None:
            result["editor"] = {"openUrl": f"{base_url.rstrip('/')}/reports/v1/{editor_kind}/open/{editor_raw}",
                "expiresAt": editor_expires_at.isoformat()}
        if issues:
            gate = {**gate, "formalReleaseAllowed": False, "issues": [*gate.get("issues", []), *issues]}
        result.update({"deliveryFormat": delivery_format,
            "validation": content.get("validation") or {"ok": False, "issues": []},
            "validationIssues": content.get("validationIssues", []), "publicationGate": gate})
        if issues:
            result["publicationIssues"] = issues
        return result

    async def issue_workspace_publication(
        self,
        *,
        thread_id: str,
        output: Any,
    ) -> dict[str, Any]:
        content = self._publication_content(output)
        if content.get("deliveryFormat") in {"pptx", "xlsx"}:
            delivery_format = content["deliveryFormat"]
            if content.get(f"{delivery_format}Path"):
                current = await self.workspace_service.ahash_file(thread_id, content[f"{delivery_format}Path"])
                self._require_artifact_identity(content, current, artifact=delivery_format)
            result = cli_result(
                **{f"{delivery_format}_path": content.get(f"{delivery_format}Path"),
                   f"{delivery_format}_size": content.get(f"{delivery_format}Size"),
                   f"{delivery_format}_sha256": content.get(f"{delivery_format}Sha256")},
                source_warnings=content.get("sourceWarnings"), task_receipts=content.get("codingReceipts"),
            )
            result.update({"deliveryFormat": delivery_format,
                "validation": content.get("validation") or {"ok": False, "issues": []},
                "validationIssues": content.get("validationIssues", []),
                "publicationGate": content.get("publicationGate") or {"formalReleaseAllowed": False, "issues": []}})
            return result
        for label in ("pdf", "word"):
            if content.get(f"{label}Path"):
                current = await self.workspace_service.ahash_file(thread_id, content[f"{label}Path"])
                self._require_artifact_identity(content, current, artifact=label)
        return cli_result(
            path=content.get("pdfPath"),
            size=content.get("pdfSize"),
            sha256=content.get("pdfSha256"),
            word_path=content.get("wordPath"),
            word_size=content.get("wordSize"),
            word_sha256=content.get("wordSha256"),
            source_warnings=content["sourceWarnings"],
            task_receipts=content["codingReceipts"],
        )

    async def confirm_source(self, step_input: StepInput, run_context: RunContext) -> StepOutput:
        envelope = ReportRequestEnvelope.from_untrusted(
            step_input.previous_step_content
            if step_input.previous_step_content is not None
            else step_input.input
        )
        from ....management.models import ManagementError, ManagementScope

        service = getattr(self, "report_basis_service", None)
        build = getattr(self, "report_build_identity", None)
        if service is None or build is None:
            raise ReportingError("report_configuration_missing", "尚未配置新报告计算依据及构建身份。")
        scope = self._scope(run_context)
        try:
            basis = await service.register_request_basis(
                str(run_context.run_id), ManagementScope(scope["database"], scope["companyId"]),
                user_id=scope["userId"], thread_id=scope["callerThreadId"],
                request=envelope, build_identity=build,
            )
        except ManagementError as error:
            raise ReportingError(error.code, error.message) from error
        managed = await self._basis_execution_context(run_context)
        sources = tuple(managed.sources.values())
        default_source_ids = tuple(managed.sources)

        snapshots: list[SourceSchemaSnapshot] = []
        previews: list[dict[str, Any]] = []
        configuration_warnings: list[dict[str, str]] = []
        for source in sources:
            if managed is not None:
                metadata = managed.metadata[source.id]
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
                preserve_metadata=True,
            )
            if managed is not None:
                actual = {(table.database.lower(), table.name.lower()): table for table in catalog}
                for table in snapshot.tables:
                    current = actual[(table.database.lower(), table.name.lower())]
                    columns = {column.name.lower(): column for column in current.columns}
                    differences = []
                    if table.description != current.description:
                        differences.append(f"{table.database}.{table.name} 的说明")
                    for column in table.columns:
                        live = columns[column.name.lower()]
                        fields = [
                            label
                            for attr, label in (
                                ("data_type", "类型"),
                                ("nullable", "可空性"),
                                ("description", "说明"),
                            )
                            if getattr(column, attr) != getattr(live, attr)
                        ]
                        if fields:
                            differences.append(
                                f"{table.database}.{table.name}.{column.name} 的{'、'.join(fields)}"
                            )
                    if differences:
                        configuration_warnings.append(
                            {
                                "code": "report_catalog_drift",
                                "sourceId": source.id,
                                "message": f"实时目录与发布版本存在差异：{'；'.join(differences)}。本次仍使用已发布元数据。",
                            }
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
                    "basisId": basis.id,
                }
            )

        state = self._state(run_context)
        workflow_input = envelope.workflow_payload(default_source_ids=default_source_ids)
        workflow_input.pop("schemaInput", None)
        state[REPORT_WORKFLOW_INPUT_STATE_KEY] = workflow_input
        state[REPORT_SCHEMA_SNAPSHOTS_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in snapshots
        ]
        if managed is not None:
            state["report_configuration_warnings"] = configuration_warnings
        # 元数据 Agent 只用于本步服务端查询；report_workflow_input 是后续各步
        # 反序列化的公开请求契约，不能写入未声明的 agentId 等内部字段。
        self._assert_state_safe(state)
        return StepOutput(
            content={"basisId": basis.id, "sources": previews, "configurationWarnings": configuration_warnings}
        )

    def _budgeted_data_scope_schemas(
        self,
        base_payload: dict[str, Any],
        snapshots: tuple[SourceSchemaSnapshot, ...],
        run_context: RunContext,
    ) -> list[dict[str, Any]]:
        """选表阶段要看完整目录；超出输入预算时逐级截短说明，最后才去掉度量语义。"""

        agent = self._data_understanding_agent
        budget = _planner_input_token_budget(agent, run_context)
        count_tokens = _planner_request_token_counter(
            agent,
            run_context,
            DataUnderstandingPlan,
            session_id="data-understanding-budget",
            fallback_event="report_data_scope_tokenizer_fallback",
        )
        schemas: list[dict[str, Any]] = []
        tokens = 0
        for description_limit, keep_semantics in _DATA_SCOPE_SCHEMA_PROJECTIONS:
            schemas = _planning_schema_payload(snapshots, description_limit=description_limit)
            if not keep_semantics:
                for schema in schemas:
                    schema["measureSemantics"] = []
            tokens = count_tokens({**base_payload, "schemas": schemas})
            if tokens <= budget:
                if description_limit is not None:
                    loguru_logger.warning(
                        "report_data_scope_schema_compacted description_limit={} "
                        "measure_semantics={} input_tokens={} input_token_budget={}",
                        description_limit, keep_semantics, tokens, budget,
                    )
                return schemas
        # 最紧凑视图仍超限时照常请求，由统一 hard cap 给出可诊断的预算错误。
        loguru_logger.warning(
            "report_data_scope_schema_over_budget input_tokens={} input_token_budget={}",
            tokens, budget,
        )
        return schemas

    async def plan_data_scope(self, _step_input: StepInput, run_context: RunContext) -> StepOutput:
        await self._ensure_managed_execution_state(run_context)
        envelope = self._envelope(run_context)
        snapshots = self._snapshots(run_context)
        base_payload = {
            "reportGoal": envelope.report_goal,
            "period": envelope.period.model_dump(mode="json"),
            "periodWindows": envelope.period_windows().public_dict(),
            "domains": list(envelope.domains or ()),
        }
        base_payload["schemas"] = self._budgeted_data_scope_schemas(
            base_payload, snapshots, run_context
        )
        previous_output: Any = None
        validation_feedback: dict[str, Any] | None = None
        call_budget = StructuredOutputCallBudget()
        for attempt in range(1, 6):
            payload = dict(base_payload)
            if validation_feedback is not None:
                payload["correction"] = _planner_correction_payload(
                    attempt,
                    validation_feedback,
                    "修正所有 issues；直接替换错误值，不把修正说明或标记写入字段；"
                    "返回完整 JSON，不返回补丁、解释或 Markdown",
                )
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

        raise _planner_diagnostic_error(
            "report_data_understanding_invalid",
            "数据理解计划连续五次未通过校验。最后一次诊断：",
            previous_output,
            validation_feedback,
        )

    async def prepare_data_profile(
        self, step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        """在一个 Workflow 边界内先确定画像范围，再执行受限数据画像。

        两个内部动作仍保持独立实现和状态写入顺序：画像只能读取已通过校验的数据理解
        计划，后续探索只能消费完整 DataShape。合并的是外部状态转换，不是数据
        探查权限或失败语义；任一动作失败都会让当前步骤失败关闭，不能伪造完整画像。正式指标结果仍由登记回执提供。
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
        execution = await self._basis_execution_context(run_context)
        envelope = self._envelope(run_context)
        snapshots = self._snapshots(run_context)
        if _semantic_data_understanding_issues(
            self._data_understanding(run_context).model_dump(mode="json", by_alias=True), snapshots
        ):
            raise ReportingError("report_data_understanding_invalid", "画像范围不属于已冻结目录。")
        selected_source_ids = {
            item.source_id for item in self._data_understanding(run_context).tables
        }
        inputs = tuple(
            (snapshot.tables[0].source_id, snapshot)
            for snapshot in snapshots
            if snapshot.tables[0].source_id in selected_source_ids
        )
        sources = tuple([await self._source(source_id, run_context) for source_id, _snapshot in inputs])
        global_limiter = anyio.CapacityLimiter(
            min(source.limits.profile_concurrency for source in sources)
        )
        shapes: list[DataShape | None] = [None] * len(inputs)
        errors: list[ReportingError | None] = [None] * len(inputs)
        issues: list[SemanticIssue | None] = [None] * len(inputs)

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
            allowed_tables = tuple(sorted(f"{table.database}.{table.name}" for table in snapshot.tables))
            adapter = StarRocksDataSourceAdapter(source, allowed_tables=allowed_tables)
            try:
                shapes[index] = await collect_data_shape(
                    adapter,
                    catalog_scope=_catalog_scope(selected_tables),
                    preserve_metadata=getattr(self, "configuration_provider", None) is not None,
                    policy=execution.policy,
                    policy_catalog=_catalog_scope(tuple(table for item in snapshots for table in item.tables)),
                    period_start=envelope.period.start,
                    period_end=envelope.period.end,
                    period_columns={item.table: item.period_column for item in selected},
                    period_granularities={item.table: item.period_granularity for item in selected},
                    metadata_revision=snapshot.revision,
                    schema_hash=snapshot.schema_hash,
                    global_limiter=global_limiter,
                )
            except ReportingError as error:
                if error.code in {"metric_filter_not_applicable", "metric_filter_null_comparison",
                    "metric_join_not_supported", "join_fanout"}:
                    issues[index] = SemanticIssue(code=error.code, object_id=source.id,
                        message=error.message, impact="unavailable")
                else:
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
        if len(completed) + sum(issue is not None for issue in issues) != len(inputs):
            raise ReportingError("report_data_shape_failed", "数据画像采集结果不完整。")
        state = self._state(run_context)
        state[REPORT_DATA_SHAPES_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in completed
        ]
        state[REPORT_DATA_SHAPE_ISSUES_STATE_KEY] = [
            issue.model_dump(mode="json", by_alias=True) for issue in issues if issue is not None
        ]
        self._assert_state_safe(state)
        return StepOutput(content={"dataShapes": state[REPORT_DATA_SHAPES_STATE_KEY],
            "issues": state[REPORT_DATA_SHAPE_ISSUES_STATE_KEY]})

    async def resolve_capabilities(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        await self._ensure_managed_execution_state(run_context)
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
        await self._ensure_managed_execution_state(run_context)
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
        request_context = dict(state.get(REPORT_REQUEST_CONTEXT_STATE_KEY) or {})
        assertion_policy = request_context.pop("assertionPolicy", {})
        if assertion_policy.get("mode") != "enabled":
            request_context.pop("questionSpecs", None)
        outline_context = {
            "reportType": envelope.report_type,
            "domains": list(envelope.domains or ()),
            "analyses": [
                item.model_dump(mode="json", by_alias=True) for item in detailed_plan.analyses
            ],
            "dataShapes": state.get(REPORT_DATA_SHAPES_STATE_KEY, []),
            "dataShapeIssues": state.get(REPORT_DATA_SHAPE_ISSUES_STATE_KEY, []),
            "warnings": list(detailed_plan.warnings),
            "requestContext": request_context,
            "referenceMaterials": [
                {
                    "filename": item.get("filename"),
                    "content": item.get("content", "")[:20_000],
                    "layout": item.get("layout", {}),
                    "visualLayout": item.get("visualLayout"),
                }
                for item in state.get("report_reference_materials", [])
            ],
            "referenceIssues": list(state.get("report_reference_issues", [])),
        }
        base_payload = {
            "reportGoal": envelope.report_goal,
            "reportType": envelope.report_type,
            "period": envelope.period.model_dump(mode="json"),
            "outlineContext": outline_context,
            "deliveryFormat": envelope.delivery_format,
            "feedback": feedback,
        }
        validation_feedback: dict[str, Any] | None = None
        previous_output: dict[str, Any] | None = None
        allowed_paths: tuple[str, ...] = ()
        outline: ReportOutline | None = None
        ordered_analysis_ids = tuple(item.analysis_id for item in detailed_plan.analyses)
        last_proposal: ReportOutlineProposal | None = None
        reference_corrections = 0
        call_budget = StructuredOutputCallBudget()
        for attempt in range(1, 6):
            payload: dict[str, Any] = dict(base_payload)
            if validation_feedback is not None:
                correction = _planner_correction_payload(
                    attempt,
                    validation_feedback,
                    "修正全部 issues 并返回完整 ReportOutlineProposal；sections 每项只能包含 "
                    "title 和 analysisIds，不得包含 code 或 focus；每个章节必须引用已注册 "
                    "analysisId；不返回正文、解释或 Markdown",
                )
                correction["previousOutput"] = previous_output
                correction["allowedPaths"] = list(allowed_paths)
                payload["correction"] = correction
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
            except ReportingError as error:
                # 共享预算耗尽或超时：已有结构有效的提纲时交给下方确定性兜底。
                if error.code not in _PLANNER_MODEL_EXHAUSTED_CODES or last_proposal is None:
                    raise
                loguru_logger.bind(error_code=error.code, attempt=attempt).warning(
                    "report_outline_model_path_exhausted"
                )
                break
            assert isinstance(output, ReportOutlineProposal)
            last_proposal = output
            # 冻结校验失败已回灌过一次时，模型仍无法修正的引用走确定性兜底。
            output = _repair_outline_proposal(
                output,
                report_type=envelope.report_type,
                ordered_analysis_ids=ordered_analysis_ids,
                fallback=reference_corrections >= 1,
            )
            try:
                outline = freeze_outline(output, analyses=detailed_plan.analyses)
            except ValueError as error:
                reference_corrections += 1
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
        if outline is None and last_proposal is not None:
            try:
                outline = freeze_outline(
                    _repair_outline_proposal(
                        last_proposal,
                        report_type=envelope.report_type,
                        ordered_analysis_ids=ordered_analysis_ids,
                        fallback=True,
                    ),
                    analyses=detailed_plan.analyses,
                )
            except ValueError:
                outline = None
        if outline is None:
            raise _planner_exhausted_error(
                "report_outline_invalid",
                "报告提纲连续五次未通过校验。最后一次反馈：",
                validation_feedback,
            )
        state[REPORT_OUTLINE_STATE_KEY] = outline.model_dump(mode="json", by_alias=True)
        state[REPORT_OUTLINE_HASH_STATE_KEY] = payload_sha256(state[REPORT_OUTLINE_STATE_KEY])
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

    async def _registered_metric_dataset_handles(self, run_context: RunContext, *, report_revision: str = 'initial'):
        from ....management.models import ManagementError, ManagementScope

        scope = self._scope(run_context)
        workflow_scope = resolve_reporting_workflow_scope(
            run_id=str(run_context.run_id), session_id=scope['sessionId'],
            user_id=scope['userId'], stored_scope=scope,
        )
        try:
            if report_revision != 'initial':
                return await self.report_basis_service.load_revision_dataset_handles(
                    str(run_context.run_id), ManagementScope(scope['database'], scope['companyId']),
                    user_id=scope['userId'], thread_id=scope['callerThreadId'], report_revision=report_revision,
                    vault=self.configuration_provider.vault, dataset_store=self.datasets,
                    run_context=self._tool_context(run_context), workflow_scope=workflow_scope,
                )
            return await self.report_basis_service.verify_receipt_datasets(
                str(run_context.run_id), ManagementScope(scope['database'], scope['companyId']),
                user_id=scope['userId'], thread_id=scope['callerThreadId'], report_revision='initial',
                dataset_store=self.datasets, run_context=self._tool_context(run_context),
                workflow_scope=workflow_scope,
            )
        except ManagementError as error:
            raise ReportingError(error.code, error.message) from error

    async def _metric_planning_context(self, run_context: RunContext, *, report_revision: str = 'initial'):
        execution = await self._basis_execution_context(run_context)
        from ....management.models import ManagementError, ManagementScope
        from ...semantics.planning import build_metric_planning_context

        scope = self._scope(run_context)
        try:
            if report_revision != 'initial':
                workflow_scope = resolve_reporting_workflow_scope(
                    run_id=str(run_context.run_id), session_id=scope['sessionId'],
                    user_id=scope['userId'], stored_scope=scope)
                return await self.report_basis_service.load_revision_planning_context(
                    str(run_context.run_id), ManagementScope(scope['database'], scope['companyId']),
                    user_id=scope['userId'], thread_id=scope['callerThreadId'], report_revision=report_revision,
                    vault=self.configuration_provider.vault, dataset_store=self.datasets,
                    run_context=self._tool_context(run_context), workflow_scope=workflow_scope,
                )
            receipts = await self.report_basis_service.load_basis_receipts(
                str(run_context.run_id), ManagementScope(scope['database'], scope['companyId']),
                user_id=scope['userId'], thread_id=scope['callerThreadId'], report_revision='initial',
            )
            if any(isinstance(item, BasisCalculationReceipt) and item.datasets for item in receipts):
                await self._registered_metric_dataset_handles(run_context)
        except ManagementError as error:
            raise ReportingError(error.code, error.message) from error
        return build_metric_planning_context(execution, receipts, report_revision='initial')

    async def generate_analysis_plan(
        self, _step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        metric_context = await self._metric_planning_context(run_context)
        state = self._state(run_context)
        snapshots = self._snapshots(run_context)
        data_shapes = self._data_shapes(run_context)
        data_understanding = DataUnderstandingPlan.model_validate(
            state[REPORT_DATA_UNDERSTANDING_STATE_KEY]
        )
        base_payload = {
            "reportGoal": self._envelope(run_context).report_goal,
            "deliveryFormat": self._envelope(run_context).delivery_format,
            "templateInput": state.get("report_template_input"),
            "domains": list(self._envelope(run_context).domains or ()),
            "periodWindows": self._envelope(run_context).period_windows().public_dict(),
            "analysisSequence": [
                "整体规模与结构",
                "趋势与拐点",
                "异常贡献",
                "归因验证",
                "经营影响",
            ],
            "metricContext": metric_context.model_dump(mode="json", by_alias=True),
            "dataShapeIssues": state.get(REPORT_DATA_SHAPE_ISSUES_STATE_KEY, []),
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
                correction = _planner_correction_payload(
                    attempt,
                    validation_feedback,
                    "修正所有 issues；直接替换错误值，不把修正说明或标记写入字段；"
                    "返回完整 AnalysisBundle JSON，不返回补丁、解释或 Markdown；"
                    "存在 previousOutput 时只能修改 allowedMutationPaths，其他字段必须原样保留",
                )
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
            output, _ = _apply_bundle_normalizers(
                output,
                lambda bundle: _normalize_requirement_columns(bundle, snapshots),
                lambda bundle: _normalize_requirement_periods(
                    bundle, self._data_understanding(run_context)
                ),
            )
            output_payload = output.model_dump(mode="json", by_alias=True)
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
            output, repaired = _apply_bundle_normalizers(
                output,
                lambda bundle: _normalize_unsafe_multi_table_requirements(
                    bundle, snapshots, data_shapes
                ),
                lambda bundle: _normalize_analysis_bundle_grain(bundle, snapshots, data_shapes),
                _normalize_duplicate_requirements,
                lambda bundle: _normalize_comparison_roles(
                    bundle, self._envelope(run_context).comparison_roles
                ),
            )
            if repaired:
                output_payload = output.model_dump(mode="json", by_alias=True)
            semantic_issues = _analysis_bundle_semantic_issues(
                output,
                self._data_understanding(run_context),
                snapshots,
                self._envelope(run_context),
                data_shapes,
                registered_metrics=metric_context.metrics,
            )
            if semantic_issues:
                validation_feedback = {
                    "code": "report_analysis_plan_invalid",
                    "summary": "分析计划不可执行或与数据理解计划不一致",
                    "issues": semantic_issues,
                }
                correction_signature = payload_sha256(
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
                        payload_sha256(output_payload),
                        payload_sha256(_compact_validation_feedback(validation_feedback)),
                    )
                    raise _planner_exhausted_error(
                        "report_analysis_plan_invalid",
                        "分析计划纠错连续两次没有进展。最后一次反馈：",
                        validation_feedback,
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
            raise _planner_exhausted_error(
                "report_analysis_plan_invalid",
                "分析计划连续五次未通过校验。最后一次反馈：",
                validation_feedback,
            )
        state[REPORT_ANALYSIS_PLAN_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in bundle.analyses
        ]
        state[REPORT_DATA_REQUIREMENTS_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in bundle.requirements
        ]
        state[REPORT_ROW_PRESERVING_REQUIREMENTS_STATE_KEY] = []
        return StepOutput(content=bundle)

    async def generate_query_candidates(
        self, step_input: StepInput, run_context: RunContext
    ) -> StepOutput:
        await self._ensure_managed_execution_state(run_context)
        state = self._state(run_context)
        metric_context = await self._metric_planning_context(run_context)
        data_shapes = self._data_shapes(run_context)
        requirements = tuple(
            QueryRequirement.model_validate(item)
            for item in state[REPORT_DATA_REQUIREMENTS_STATE_KEY]
        )
        referenced_tables = {
            table.table for requirement in requirements for table in requirement.tables
        }
        envelope = self._envelope(run_context)
        row_preserving_ids = tuple(
            state.get(REPORT_ROW_PRESERVING_REQUIREMENTS_STATE_KEY, ())
        )
        base_payload = {
            "metricContext": metric_context.model_dump(mode="json", by_alias=True),
            "requirements": state[REPORT_DATA_REQUIREMENTS_STATE_KEY],
            # requirements 已包含每张表的期间字段和粒度；SQL planner 只需列名、类型
            # 和聚合语义，完整 DataUnderstanding 留在服务端状态用于严格审核。
            "schemas": _planning_schema_payload(
                self._snapshots(run_context),
                tables=referenced_tables,
                description_limit=0,
            ),
            "period": envelope.period.model_dump(mode="json"),
            "requirementPeriodWindows": {
                requirement.requirement_id: envelope.model_copy(update={
                    "comparison_roles": requirement.resolved_comparison_roles(envelope.comparison_roles),
                }).period_windows(granularity=requirement.tables[0].period_granularity).public_dict()
                for requirement in requirements
            },
            "feedback": self._feedback(step_input),
            "queryExecutionModes": [
                {
                    "requirementId": requirement_id,
                    "mode": "row_preserving_conflict_probe",
                }
                for requirement_id in row_preserving_ids
            ],
        }
        sources = {item.id: item for item in await self._sources(run_context)}
        snapshots = self._snapshots(run_context)
        validation_feedback: dict[str, Any] | None = None
        approved: tuple[ApprovedQuery, ...] | None = None
        call_budget = StructuredOutputCallBudget()
        for attempt in range(1, 6):
            payload = dict(base_payload)
            if validation_feedback is not None:
                payload["correction"] = _planner_correction_payload(
                    attempt,
                    validation_feedback,
                    "修正所有 issues；只覆盖每个 requirementId 的 requirementPeriodWindows 中唯一期间窗口，返回完整 SQL 批次 JSON，"
                    "每个查询只使用所属 periodRole 的精确窗口；直接替换错误值，不把修正说明或标记写入字段；"
                    "不返回补丁、解释或 Markdown",
                )
            try:
                output = await self._run_planner(
                    self._sql_agent,
                    payload,
                    run_context,
                    call_budget=call_budget,
                    attempt=min(attempt - 1, 1),
                    failure_kind=(
                        "sql_validation_failure" if validation_feedback is not None else None
                    ),
                )
            except ReportingError as error:
                # 共享调用预算耗尽或结构化输出超时时，模型路径已无法产出结果；必须落到
                # 下方确定性编译兜底，而不是绕过兜底让整条报表失败。
                if error.code not in _PLANNER_MODEL_EXHAUSTED_CODES:
                    raise
                loguru_logger.bind(error_code=error.code, attempt=attempt).warning(
                    "report_sql_model_path_exhausted"
                )
                if validation_feedback is None:
                    validation_feedback = {"code": error.code, "summary": error.message}
                approved = None
                break
            assert isinstance(output, GeneratedQueryBatch)
            approved, issues = _approve_generated_queries(
                output,
                sources=sources,
                snapshots=snapshots,
                envelope=envelope,
                requirements=requirements,
                registered_metrics=metric_context.metrics,
                row_preserving_requirement_ids=row_preserving_ids,
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
                registered_metrics=metric_context.metrics,
                snapshots=snapshots,
                envelope=envelope,
                row_preserving_requirement_ids=row_preserving_ids,
            )
            if compiled is not None:
                compiled_approved, compilation_issues = _approve_generated_queries(
                    compiled,
                    sources=sources,
                    snapshots=snapshots,
                    envelope=envelope,
                    requirements=requirements,
                    registered_metrics=metric_context.metrics,
                    row_preserving_requirement_ids=row_preserving_ids,
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
            raise _planner_exhausted_error(
                "report_query_batch_invalid",
                "SQL 批次连续五次未通过校验。最后一次反馈：",
                validation_feedback,
            )
        state[REPORT_APPROVED_QUERIES_STATE_KEY] = [
            item.model_dump(mode="json", by_alias=True) for item in approved
        ]
        return StepOutput(content={"queries": state[REPORT_APPROVED_QUERIES_STATE_KEY]})


def _repair_outline_proposal(
    proposal: ReportOutlineProposal,
    *,
    report_type: str,
    ordered_analysis_ids: tuple[str, ...],
    fallback: bool = False,
) -> ReportOutlineProposal:
    """确定性修复提纲中可由已确认事实唯一决定的部分，省去模型往返（软告警）。

    - reportType 已由确认请求冻结，直接覆盖；
    - 恰有一个未注册 analysisId 且恰有一个遗漏的已注册 analysisId 时原位替换，
      保留模型给出的章节归属；
    - 没有遗漏时，未注册 analysisId 只是多余引用，剔除（剔空的章节移除）；
    - 其余歧义交给模型纠错。fallback=True 时（模型已获得纠错机会或预算耗尽）剔除
      剩余未注册 analysisId，并把遗漏项按分析计划顺序归入末章。
    """

    registered = set(ordered_analysis_ids)
    payload = proposal.model_dump(mode="json", by_alias=True)
    repairs: list[str] = []
    if payload["reportType"] != report_type:
        payload["reportType"] = report_type
        repairs.append("report_type")
    referenced = {item for section in payload["sections"] for item in section["analysisIds"]}
    unknown = [
        item
        for section in payload["sections"]
        for item in section["analysisIds"]
        if item not in registered
    ]
    missing = [item for item in ordered_analysis_ids if item not in referenced]
    if len(unknown) == 1 and len(missing) == 1:
        substitution = {unknown[0]: missing[0]}
        payload["sections"] = [
            {
                **section,
                "analysisIds": [substitution.get(item, item) for item in section["analysisIds"]],
            }
            for section in payload["sections"]
        ]
        repairs.append("unknown_analysis_id_substituted")
        unknown, missing = [], []
    if unknown and (fallback or not missing):
        payload["sections"] = [
            {
                **section,
                "analysisIds": [item for item in section["analysisIds"] if item in registered],
            }
            for section in payload["sections"]
        ]
        repairs.append("unknown_analysis_id_dropped")
    if missing and fallback:
        # 先归入末章再移除空章节：全部引用都未注册时，末章仍可承接遗漏项。
        last = payload["sections"][-1]
        payload["sections"][-1] = {**last, "analysisIds": [*last["analysisIds"], *missing]}
        repairs.append("missing_analysis_assigned")
    payload["sections"] = [section for section in payload["sections"] if section["analysisIds"]]
    if not repairs or not payload["sections"]:
        return proposal
    try:
        repaired = ReportOutlineProposal.model_validate(payload)
    except ValidationError:
        return proposal
    loguru_logger.bind(
        repair_types=repairs,
        unknown_analysis_ids=unknown,
        missing_analysis_ids=missing if fallback else [],
    ).warning("report_outline_proposal_repaired")
    return repaired


_PLANNER_MODEL_EXHAUSTED_CODES = frozenset(
    {"report_phase_output_invalid", "report_structured_output_timeout"}
)


_MONTH_RANGE_SEPARATOR = r"(?:-|－|—|–|~|～|至|到)"
_CHINESE_QUARTERS = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}


def _month_period(year: int, first: int, last: int) -> ReportPeriod | None:
    if not 1 <= first <= last <= 12:
        return None
    end = date(year + (last == 12), 1 if last == 12 else last + 1, 1) - timedelta(days=1)
    return ReportPeriod(start=date(year, first, 1), end=end)


def _single_explicit_period(prompt: str, feedback: str | None) -> ReportPeriod | None:
    """只确定性解析唯一年份下的常见期间写法；无法唯一确定时交给模型或澄清。"""
    value = f"{prompt}\n{feedback or ''}"
    years = set(re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", value))
    if len(years) != 1:
        return None
    raw_year = years.pop()
    if re.search(rf"{raw_year}[-/.]\d{{1,2}}", value):
        return None
    year = int(raw_year)
    month_ranges = {
        (int(first), int(last))
        for first, last in re.findall(
            rf"(?<!\d)(\d{{1,2}})\s*月?\s*{_MONTH_RANGE_SEPARATOR}\s*(\d{{1,2}})\s*月", value
        )
    }
    for cutoff, month in re.findall(
        rf"(截至|截止)?\s*{raw_year}\s*年\s*(\d{{1,2}})\s*月(?!\s*{_MONTH_RANGE_SEPARATOR})", value
    ):
        # “截至某月”是年初至该月的累计窗口，不是单月。
        month_ranges.add((1 if cutoff else int(month), int(month)))
    for quarter in re.findall(r"第\s*([一二三四1-4])\s*季度|(?<![A-Za-z])Q([1-4])", value):
        number = _CHINESE_QUARTERS["".join(quarter)]
        month_ranges.add((3 * number - 2, 3 * number))
    for phrase, months in (("前三季度", (1, 9)), ("上半年", (1, 6)), ("下半年", (7, 12))):
        if phrase in value:
            month_ranges.add(months)
    if len(month_ranges) == 1:
        return _month_period(year, *month_ranges.pop())
    if month_ranges or re.search(r"\d\s*月|季度|半年|(?<![A-Za-z])Q[1-4]", value):
        # 多个或未识别的期间写法不能默认为全年，交给模型或澄清。
        return None
    return ReportPeriod(start=date(year, 1, 1), end=date(year, 12, 31))


def _compile_single_table_queries(
    requirements: tuple[QueryRequirement, ...],
    *,
    registered_metrics: tuple[MetricDefinition, ...],
    snapshots: tuple[SourceSchemaSnapshot, ...],
    envelope: ReportRequestEnvelope,
    row_preserving_requirement_ids: tuple[str, ...] = (),
) -> GeneratedQueryBatch | None:
    """从已批准契约确定性编译单表 SQL；多表继续交由 SQL planner。"""

    if not requirements or any(len(requirement.tables) != 1 for requirement in requirements):
        return None
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

        from ..query_pipeline import registered_metric_requirement_issues
        if registered_metric_requirement_issues(requirement, 0, registered_metrics):
            return None

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
            predicates: list[exp.Expression] = [
                exp.column(table.period_column).between(
                    *_period_bound_expressions(window.period, table.period_granularity)
                )
            ]
            # 统计口径由执行适配器绑定；编译器只保留登记粒度与期间。
            query_grain_columns = requirement.grain_columns
            if row_preserving:
                projections = [exp.column(column) for column in query_grain_columns]
                projections.extend(exp.column(column) for column in table.measure_columns)
            else:
                projections = [exp.column(column) for column in query_grain_columns]
                for measure in table.measure_columns:
                    aggregate = _measure_aggregate_expression(
                        measure,
                        "sum",
                    )
                    projections.append(aggregate.as_(measure))
            statement = (
                exp.select(*projections)
                .from_(exp.to_table(qualified_table))
                .where(exp.and_(*predicates))
            )
            if not row_preserving and query_grain_columns:
                statement = statement.group_by(
                    *(exp.column(column) for column in query_grain_columns)
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


# 选表请求的 Schema 投影顺序：完整说明 → 截短说明 → 去掉说明 → 再去掉度量语义。
_DATA_SCOPE_SCHEMA_PROJECTIONS: tuple[tuple[int | None, bool], ...] = (
    (None, True),
    (160, True),
    (40, True),
    (0, True),
    (0, False),
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

    raw_output = _repair_data_understanding_tables(raw_output, snapshots)
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


def _repair_data_understanding_tables(
    raw_output: Any,
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> Any:
    """确定性修复可唯一定位的表引用，省去模型往返（软告警）。

    - table 大小写不同或 sourceId 写错，但 database.table 在全部输入 Schema 中
      唯一时，改写为规范 sourceId 与 table；
    - 同一 sourceId/table 被重复选择时保留首次出现的条目。
    无法唯一定位的引用保持原样，由语义校验回灌模型纠错。
    """

    if not isinstance(raw_output, dict) or not isinstance(raw_output.get("tables"), list):
        return raw_output
    canonical: dict[str, list[tuple[str, str]]] = {}
    for reference in dict.fromkeys(
        (item.source_id, item.table) for item in _table_references(snapshots)
    ):
        canonical.setdefault(reference[1].lower(), []).append(reference)
    available = {
        (source_id, table.lower()) for matches in canonical.values() for source_id, table in matches
    }
    repairs: set[str] = set()
    selected: set[tuple[str, str]] = set()
    tables: list[Any] = []
    for raw_table in raw_output["tables"]:
        if not isinstance(raw_table, dict):
            tables.append(raw_table)
            continue
        source_id = raw_table.get("sourceId")
        table = raw_table.get("table")
        if not isinstance(source_id, str) or not isinstance(table, str):
            tables.append(raw_table)
            continue
        matches = canonical.get(table.lower(), [])
        if (source_id, table.lower()) in available:
            matches = [item for item in matches if item[0] == source_id]
        if len(matches) == 1 and matches[0] != (source_id, table):
            source_id, table = matches[0]
            raw_table = {**raw_table, "sourceId": source_id, "table": table}
            repairs.add("table_reference")
        key = (source_id, table.lower())
        if key in available and key in selected:
            repairs.add("duplicate_table")
            continue
        selected.add(key)
        tables.append(raw_table)
    if not repairs:
        return raw_output
    loguru_logger.bind(repair_types=sorted(repairs)).warning(
        "report_data_understanding_tables_repaired"
    )
    return {**raw_output, "tables": tables}


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
        and issue.get("actionCode") == SPLIT_REQUIREMENTS_ACTION
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


def _planner_correction_payload(
    attempt: int,
    validation_feedback: dict[str, Any],
    instruction: str,
) -> dict[str, Any]:
    """五个 planner 纠错循环共用的 correction 回灌形状；额外键由调用方按各自契约补充。"""
    return {
        "attempt": attempt,
        "validationFeedback": _compact_validation_feedback(validation_feedback),
        "instruction": instruction,
    }


def _planner_exhausted_error(
    code: str, message: str, validation_feedback: dict[str, Any] | None
) -> ReportingError:
    return ReportingError(
        code, message + _json_text(_compact_validation_feedback(validation_feedback))
    )


def _planner_diagnostic_error(
    code: str,
    message: str,
    previous_output: Any,
    validation_feedback: dict[str, Any] | None,
) -> ReportingError:
    return ReportingError(
        code,
        message
        + _json_text(
            {
                "previousOutput": _bounded_rejected_value(previous_output),
                "validationFeedback": _compact_validation_feedback(validation_feedback),
            }
        ),
    )


def _approve_generated_queries(
    generated: GeneratedQueryBatch,
    *,
    sources: dict[str, StarRocksSourceConfig],
    snapshots: tuple[SourceSchemaSnapshot, ...],
    envelope: ReportRequestEnvelope,
    requirements: tuple[QueryRequirement, ...],
    registered_metrics: tuple[MetricDefinition, ...],
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
                registered_metrics=registered_metrics,
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
                    snapshots=snapshots,
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



def _expected_period_predicates(
    requirement: QueryRequirement,
    envelope: ReportRequestEnvelope,
    *,
    period_role: Literal["current", "yoy", "mom"] = "current",
    snapshots: tuple[SourceSchemaSnapshot, ...] | list[SourceSchemaSnapshot] = (),
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
            if _period_column_has_time(snapshots, requirement.source_id, table):
                # 带时分秒的期间列用半开区间，闭区间上界只到期末当天 00:00:00。
                next_day = (period.end + timedelta(days=1)).isoformat()
                predicates.append(f"{column} >= {lower} AND {column} < '{next_day}'")
                continue
        predicates.append(f"{column} BETWEEN {lower} AND {upper}")
    return predicates


def _period_column_has_time(
    snapshots: tuple[SourceSchemaSnapshot, ...] | list[SourceSchemaSnapshot], source_id: str, table: Any
) -> bool:
    name = table.table.lower()
    return any(
        period_column_has_time(item, table.period_column)
        for snapshot in snapshots
        for item in snapshot.tables
        if item.source_id == source_id
        and name in {f"{item.database.lower()}.{item.name.lower()}", item.name.lower()}
    )


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
        if _TYPED_PERIOD_TYPE.match(data_type):
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


def _preferred_typed_period_column(columns: tuple[Any, ...], *, reference_text: str) -> Any | None:
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
        if current is None or _TYPED_PERIOD_TYPE.match(current.data_type.strip().upper()):
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
