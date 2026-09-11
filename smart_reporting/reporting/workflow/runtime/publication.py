# mypy: disable-error-code="attr-defined"
# 运行时由 facade 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。
from __future__ import annotations

from loguru import logger

from ....quality_warnings import (
    QualityAuditCollector,
    QualityWarningContractError,
    TenantScope,
    WarningAdapter,
)
from ..checkpoint import AnalysisEvidenceManifest, SectionArtifact, SectionCitation
from .base import (
    REPORT_ANALYSIS_PLAN_STATE_KEY,
    REPORT_ARTIFACTS_STATE_KEY,
    REPORT_DATA_REQUIREMENTS_STATE_KEY,
    REPORT_DATASET_LINEAGE_STATE_KEY,
    REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
    REPORT_WORKFLOW_RESULT_STATE_KEY,
    AnalysisItem,
    Any,
    ArtifactFile,
    DatasetHandle,
    DatasetLineage,
    DetailedAnalysisPlan,
    DocxArtifactManifest,
    DurableReportingPhase,
    HeadingNumber,
    Mapping,
    MetricDefinition,
    PdfArtifactManifest,
    PurePosixPath,
    QueryRequirement,
    ReportArtifactManifest,
    ReportingCheckpoint,
    ReportingCommand,
    ReportingError,
    ReportPeriod,
    RunContext,
    SourceSchemaSnapshot,
    SourceWarning,
    StepInput,
    StepOutput,
    ValidationError,
    _frozen_outline,
    _human_label,
    _report_pdf_filename,
    _reporting_observed_data_facts,
    _source_warnings_from_state,
    authoritative_citations,
    build_authoritative_manifest,
    complete_cleanup,
    dataset_snapshot_hash,
    hashlib,
    json,
    re,
    validate_rendered_artifacts,
)


def evaluate_publication_semantics(
    *,
    evidence_manifest: AnalysisEvidenceManifest,
    section_artifacts: tuple[SectionArtifact, ...],
    citations: tuple[SectionCitation, ...],
) -> dict[str, Any]:
    """交叉核对冻结指标、Dataset 语义与正文 claim，并返回非阻断质量警告。"""

    warnings: list[dict[str, Any]] = []
    metrics = {item.code: item for item in evidence_manifest.metric_definitions}
    citation_datasets = {item.citation_id: item.dataset_id for item in citations}
    dataset_semantics = {item.dataset_id: item for item in evidence_manifest.dataset_semantics}

    for chart in evidence_manifest.charts:
        for metric_code in sorted(set(chart.metric_codes) - set(metrics)):
            warnings.append(
                {
                    "code": "report_chart_metric_unfrozen",
                    "message": "图表引用了尚未冻结定义的指标代码。",
                    "details": {"chartId": chart.chart_id, "metricCode": metric_code},
                }
            )

    def issue(code: str, claim_id: str) -> None:
        warnings.append(
            {
                "code": code,
                "message": code,
                "details": {"claimId": claim_id},
            }
        )

    for artifact in section_artifacts:
        referenced_claims = {claim_id for block in artifact.blocks for claim_id in block.claim_ids}
        for claim in artifact.claims:
            if claim.claim_id not in referenced_claims:
                continue
            metric = metrics.get(claim.metric_code)
            if metric is None or claim.period_basis != metric.period_basis:
                issue("report_period_basis_conflict", claim.claim_id)
            datasets = {
                citation_datasets[citation_id]
                for citation_id in claim.citation_ids
                if citation_id in citation_datasets
            }
            if any(
                dataset_semantics.get(dataset_id) is not None
                and dataset_semantics[dataset_id].duplicate_resolution == "unresolved"
                for dataset_id in datasets
            ):
                issue("report_aggregation_duplicate_unresolved", claim.claim_id)
            if claim.conclusion_type == "entity_ratio" and (
                claim.aggregation_grain != claim.entity_grain
                or any(
                    dataset_semantics.get(dataset_id) is None
                    or dataset_semantics[dataset_id].row_grain != claim.entity_grain
                    for dataset_id in datasets
                )
            ):
                issue("report_entity_grain_unproven", claim.claim_id)
            referenced_charts = {
                item.chart_id: item
                for item in evidence_manifest.charts
                if item.chart_id in claim.chart_ids
            }
            non_strict_source = claim.comparability == "reference_only" or any(
                item.comparability == "reference_only" for item in referenced_charts.values()
            )
            if non_strict_source and claim.conclusion_type in {
                "comparison",
                "profit",
                "efficiency",
            }:
                issue("report_cross_source_inference_unsupported", claim.claim_id)
    return {"formalReleaseAllowed": True, "issues": [], "warnings": warnings}


class RuntimePublicationMixin:
    async def validate_report(self, _step_input: StepInput, run_context: RunContext) -> StepOutput:
        return StepOutput(content=await self._render_and_validate(run_context))

    async def _render_and_validate(self, run_context: RunContext) -> dict[str, Any]:
        state = self._state(run_context)
        result = self._workflow_result(state)
        outline = _frozen_outline(state)
        pdf_path = _report_pdf_path(
            str(run_context.run_id),
            int(result.get("revision", 0)) + 1,
            outline.title,
            self._envelope(run_context).period,
        )
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
        requirements = tuple(
            QueryRequirement.model_validate(item)
            for item in state[REPORT_DATA_REQUIREMENTS_STATE_KEY]
        )
        source_warnings = _source_warnings_from_state(state)
        analyses = tuple(
            AnalysisItem.model_validate(item) for item in state[REPORT_ANALYSIS_PLAN_STATE_KEY]
        )
        observed_facts = _reporting_observed_data_facts(
            self._data_shapes(run_context), requirements, lineage
        )
        await self.report_tools.bind_citation_presentations(
            str(result["jobId"]),
            _citation_presentations(
                lineage=lineage,
                requirements=requirements,
                analyses=analyses,
                snapshots=self._snapshots(run_context),
                observed_facts=observed_facts,
            ),
            run_context=context,
        )
        rendered_result = await self.report_tools._render_report_pair(
            str(result["jobId"]),
            str(result["markdownPath"]),
            pdf_path,
            artifact_manifest=draft.model_dump(mode="json", by_alias=True),
            run_context=context,
        )
        word_path = str(PurePosixPath(pdf_path).with_suffix(".docx"))
        html_path = str(PurePosixPath(pdf_path).with_suffix(".html"))
        try:
            if not isinstance(rendered_result, dict):
                raise ReportingError(
                    "report_artifact_validation_failed", "PDF/Word/HTML 联合验收回执无效。"
                )
            validation = rendered_result.get("validation")
            if not isinstance(validation, dict) or validation.get("ok") is not True:
                raise ReportingError(
                    "report_artifact_validation_failed", "PDF/Word/HTML 联合验收未通过。"
                )
            if rendered_result.get("wordPath") != word_path:
                raise ReportingError(
                    "report_artifact_validation_failed", "Word 验收路径缺失或不匹配。"
                )
            if rendered_result.get("htmlPath") != html_path:
                raise ReportingError(
                    "report_artifact_validation_failed", "HTML 验收路径缺失或不匹配。"
                )
            pdf_identity = await self.workspace_service.ahash_file(
                self._scope(run_context)["threadId"], pdf_path
            )
            word_identity = await self.workspace_service.ahash_file(
                self._scope(run_context)["threadId"], word_path
            )
            html_identity = await self.workspace_service.ahash_file(
                self._scope(run_context)["threadId"], html_path
            )
            validated_pdf_sha256 = validation.get("pdfSha256")
            validated_word_sha256 = validation.get("wordSha256")
            validated_html_sha256 = validation.get("htmlSha256")
            if (
                not isinstance(validated_pdf_sha256, str)
                or pdf_identity.get("sha256") != validated_pdf_sha256
                or not isinstance(validated_word_sha256, str)
                or word_identity.get("sha256") != validated_word_sha256
                or not isinstance(validated_html_sha256, str)
                or html_identity.get("sha256") != validated_html_sha256
            ):
                raise ReportingError(
                    "report_artifact_changed",
                    "PDF、Word 或 HTML 在验收后发生变化，必须重新渲染并验收。",
                )
            source_chart_sha256s = tuple(item.sha256 for item in draft.charts)
            page_count = validation.get("pageCount")
            word_validation = validation.get("word")
            if not isinstance(word_validation, dict):
                raise ReportingError("report_artifact_validation_failed", "Word 验收回执无效。")
            converted_page_count = word_validation.get("convertedPageCount")
            section_count = word_validation.get("sectionCount")
            toc_entry_count = word_validation.get("tocEntryCount")
            if (
                isinstance(page_count, bool)
                or not isinstance(page_count, int)
                or isinstance(converted_page_count, bool)
                or not isinstance(converted_page_count, int)
                or isinstance(section_count, bool)
                or not isinstance(section_count, int)
                or isinstance(toc_entry_count, bool)
                or not isinstance(toc_entry_count, int)
            ):
                raise ReportingError(
                    "report_artifact_validation_failed", "PDF/Word 验收回执缺少有效计数。"
                )
            rendered_pdf = PdfArtifactManifest(
                reportId=draft.report_id,
                revision=draft.revision,
                effectiveProfileHash=draft.effective_profile_hash,
                sourceMarkdownSha256=draft.markdown.sha256,
                sourceChartSha256s=source_chart_sha256s,
                pdf=ArtifactFile(
                    path=pdf_path,
                    mediaType="application/pdf",
                    size=pdf_identity["size"],
                    sha256=pdf_identity["sha256"],
                ),
                pageCount=page_count,
                renderedChartIds=tuple(validation.get("chartIds") or ()),
                citationIds=tuple(validation.get("citationIds") or ()),
                sections=tuple(validation.get("sectionIds") or ()),
                sectionNumbers=draft.section_numbers,
                headingNumbers=draft.heading_numbers,
                sourceWarnings=source_warnings,
            )
            rendered_word = DocxArtifactManifest(
                reportId=draft.report_id,
                revision=draft.revision,
                effectiveProfileHash=draft.effective_profile_hash,
                sourceMarkdownSha256=draft.markdown.sha256,
                sourceChartSha256s=source_chart_sha256s,
                docx=ArtifactFile(
                    path=word_path,
                    mediaType=(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                    size=word_identity["size"],
                    sha256=word_identity["sha256"],
                ),
                convertedPageCount=converted_page_count,
                sectionCount=section_count,
                tocEntryCount=toc_entry_count,
                renderedChartIds=tuple(validation.get("chartIds") or ()),
                citationIds=tuple(validation.get("citationIds") or ()),
                sections=tuple(validation.get("sectionIds") or ()),
                sectionNumbers=draft.section_numbers,
                headingNumbers=draft.heading_numbers,
                sourceWarnings=source_warnings,
            )
            validate_rendered_artifacts(draft, rendered_pdf, rendered_word, lineage=lineage)
            # PDF/DOCX 仍由既有渲染链生成，但其最终身份属于同一 Reporting checkpoint。
            # 先核对 revision 再写回文件清单，避免恢复时把其他 revision 的交付物误认为当前产物。
            durable = await self.state_repository.get(
                str(run_context.run_id or self._scope(run_context)["externalRunId"])
            )
            if (
                durable is None
                or durable.phase is not DurableReportingPhase.COMPLETED
                or durable.revision != draft.revision
            ):
                raise ReportingError(
                    "report_checkpoint_conflict",
                    "PDF/Word 验收结果与 Reporting checkpoint revision 不一致。",
                )
            await self._apply_durable_command(
                run_context,
                ReportingCommand(
                    name="record_artifact",
                    commandId=f"rendered-pdf:{draft.revision}:{pdf_identity['sha256']}",
                    payload={"artifact": pdf_identity},
                ),
            )
            await self._apply_durable_command(
                run_context,
                ReportingCommand(
                    name="record_artifact",
                    commandId=f"rendered-word:{draft.revision}:{word_identity['sha256']}",
                    payload={"artifact": word_identity},
                ),
            )
            result.update(
                {
                    "pdfPath": pdf_path,
                    "pdfSize": int(pdf_identity["size"]),
                    "pdfSha256": str(pdf_identity["sha256"]),
                    "wordPath": word_path,
                    "wordSize": int(word_identity["size"]),
                    "wordSha256": str(word_identity["sha256"]),
                    "htmlPath": html_path,
                    "htmlSize": int(html_identity["size"]),
                    "htmlSha256": str(html_identity["sha256"]),
                    "validation": validation,
                    "status": "validated",
                }
            )
            state[REPORT_WORKFLOW_RESULT_STATE_KEY] = result
            state[REPORT_ARTIFACTS_STATE_KEY] = {
                "draft": draft.model_dump(mode="json", by_alias=True),
                "pdf": rendered_pdf.model_dump(mode="json", by_alias=True),
                "word": rendered_word.model_dump(mode="json", by_alias=True),
            }
            return {
                "status": "validated",
                "jobId": result["jobId"],
                "markdownPath": result["markdownPath"],
                "pdfPath": pdf_path,
                "wordPath": word_path,
                "htmlPath": html_path,
                "validation": validation,
            }
        except BaseException:
            # _render_report_pair 返回即表示 revision 目录已正式发布。之后任何回执、
            # 身份、manifest 或状态异常都必须删除同一 revision 的三种产物；取消也不能打断清理。
            await complete_cleanup(
                self.report_tools.discard_report_revision(
                    str(result["jobId"]), pdf_path, word_path, run_context=context
                )
            )
            raise

    async def _dataset_publication_gate(
        self, run_context: RunContext, result: Mapping[str, Any]
    ) -> dict[str, Any]:
        """在发布前重新核对 DatasetLineage、分析计划、提纲和产物身份。

        该门禁只依赖本轮不可变 CSV、DatasetLineage 和服务端生成的产物清单；Profile
        质量 Warning 会继续传播但不阻断发布，路径越界、哈希漂移和结构引用错误则
        必须失败关闭。
        """
        state = self._state(run_context)
        issues: list[dict[str, Any]] = []
        raw_warnings = result.get("sourceWarnings", [])
        warnings = list(raw_warnings) if isinstance(raw_warnings, list) else []
        audit = QualityAuditCollector(
            report_run_id=str(run_context.run_id or self._scope(run_context)["externalRunId"]),
            revision=int(result.get("revision", 0)),
        )

        def issue(code: str, message: str, **details: Any) -> None:
            item: dict[str, Any] = {"code": code, "message": message}
            if details:
                item["details"] = details
            issues.append(item)

        try:
            lineage = tuple(
                DatasetLineage.model_validate(item)
                for item in state.get(REPORT_DATASET_LINEAGE_STATE_KEY, ())
            )
        except (TypeError, ValueError, ValidationError):
            lineage = ()
            issue("dataset_lineage_invalid", "DatasetLineage 状态无法解析。")
        try:
            handles = tuple(
                DatasetHandle.from_state(item)
                for item in self._workflow_result(state).get("datasets", ())
            )
        except (TypeError, ValueError, ReportingError):
            handles = ()
            issue("dataset_handle_invalid", "DatasetHandle 状态无法解析。")

        lineage_by_id = {item.dataset_id: item for item in lineage}
        handle_by_id = {item.dataset_id: item for item in handles}
        if set(lineage_by_id) != set(handle_by_id) or len(lineage_by_id) != len(lineage):
            issue("dataset_lineage_binding_invalid", "DatasetHandle 与 DatasetLineage 未精确对应。")
        thread_id = self._scope(run_context)["threadId"]
        for dataset_id, handle in handle_by_id.items():
            source = lineage_by_id.get(dataset_id)
            if source is None:
                continue
            if (
                handle.source_id != source.source_id
                or handle.source_type != source.source_type
                or handle.requirement_id != source.requirement_id
                or handle.size != source.size
                or handle.sha256 != source.sha256
                or handle.row_count != source.row_count
                or handle.sql_hash != source.sql_hash
            ):
                issue(
                    "dataset_lineage_binding_invalid",
                    "DatasetHandle 与 DatasetLineage 身份不一致。",
                    datasetId=dataset_id,
                )
            try:
                current = await self.workspace_service.ahash_file(thread_id, handle.path)
                if (
                    current.get("missing")
                    or current.get("size") != handle.size
                    or current.get("sha256") != handle.sha256
                ):
                    issue(
                        "dataset_snapshot_changed",
                        "不可变 CSV 在发布前发生变化。",
                        datasetId=dataset_id,
                    )
            except Exception:
                issue(
                    "dataset_snapshot_unavailable",
                    "不可变 CSV 路径不可读取或越界。",
                    datasetId=dataset_id,
                )

        try:
            detailed_plan = DetailedAnalysisPlan.model_validate(
                state.get(REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY)
            )
            authorized_ids = set(lineage_by_id)
            if set(detailed_plan.dataset_ids) != authorized_ids:
                issue("analysis_dataset_coverage_invalid", "详细分析计划未精确覆盖授权数据集。")
            covered_ids = {
                dataset_id for item in detailed_plan.analyses for dataset_id in item.dataset_ids
            }
            if covered_ids != authorized_ids:
                issue("analysis_dataset_coverage_invalid", "详细分析项未覆盖全部授权数据集。")
        except (TypeError, ValueError, ValidationError):
            detailed_plan = None
            issue("analysis_plan_invalid", "详细分析计划状态无效。")

        try:
            outline = _frozen_outline(state)
            known_analysis_ids = {
                item.analysis_id for item in (detailed_plan.analyses if detailed_plan else ())
            }
            referenced_analysis_ids = [
                analysis_id for section in outline.sections for analysis_id in section.analysis_ids
            ]
            if len(referenced_analysis_ids) != len(set(referenced_analysis_ids)):
                issue("outline_analysis_duplicate", "批准提纲重复引用 analysisId。")
            if set(referenced_analysis_ids) - known_analysis_ids:
                issue("outline_analysis_unknown", "批准提纲引用不存在的 analysisId。")
            if outline.report_type != self._envelope(run_context).report_type:
                issue("outline_report_type_mismatch", "提纲报告类型与用户范围不一致。")
        except (ReportingError, TypeError, ValueError, ValidationError):
            outline = None
            issue("outline_invalid", "批准提纲状态无效。")

        try:
            manifest = ReportArtifactManifest.model_validate(
                state.get(REPORT_ARTIFACTS_STATE_KEY, {}).get("draft")
            )
            expected_citations = authoritative_citations(lineage)
            actual_citations = {
                (item.citation_id, item.dataset_id, item.requirement_id, item.snapshot_hash)
                for item in manifest.citations
            }
            expected_citation_values = {
                (item.citation_id, item.dataset_id, item.requirement_id, item.snapshot_hash)
                for item in expected_citations
            }
            if actual_citations != expected_citation_values:
                issue("citation_lineage_invalid", "产物引用未精确绑定当前 DatasetLineage。")
            if manifest.dataset_snapshot_hash != dataset_snapshot_hash(lineage):
                issue("manifest_dataset_snapshot_invalid", "产物清单未绑定当前数据快照。")
            if outline is not None:
                expected_outline_analysis_ids = {
                    analysis_id
                    for section in outline.sections
                    for analysis_id in section.analysis_ids
                }
                if set(manifest.analysis_ids) != expected_outline_analysis_ids:
                    issue("manifest_analysis_binding_invalid", "产物清单未精确绑定批准提纲分析。")
        except (TypeError, ValueError, ValidationError, AttributeError):
            manifest = None
            issue("manifest_invalid", "服务端产物清单状态无效。")

        try:
            durable = await self.state_repository.get(
                str(run_context.run_id or self._scope(run_context)["externalRunId"])
            )
            stored_checkpoint = (
                durable.payload.get("workflowCheckpoint") if durable is not None else None
            )
            checkpoint = ReportingCheckpoint.model_validate(stored_checkpoint)
            if checkpoint.evidence_manifest is None:
                raise ValueError("checkpoint 缺少冻结分析产物")
            analysis_warnings = tuple(
                dict.fromkeys(
                    (
                        *checkpoint.evidence_manifest.warnings,
                        *(
                            warning
                            for evidence in checkpoint.evidence_manifest.evidence
                            for warning in evidence.warnings
                        ),
                    )
                )
            )
            # 缺失月份属于数据质量事实，无法通过重跑修复。报告已经明确披露不可比
            # 口径时允许带警告发布；只有血缘、快照、路径和产物身份等完整性问题
            # 进入 issues 并关闭发布，避免把真实数据缺口误判成系统发布故障。
            warnings.extend(
                _analysis_quality_warnings(
                    checkpoint.evidence_manifest.metric_definitions,
                    analysis_warnings,
                )
            )
            parsed_section_artifacts: list[SectionArtifact] = []
            for completed in checkpoint.completed_sections:
                stored_section = await self._read_identity_model(
                    thread_id,
                    completed.artifact_file,
                    SectionArtifact,
                )
                parsed_section_artifacts.append(
                    SectionArtifact.model_validate(
                        stored_section.model_dump(mode="json", by_alias=True)
                    )
                )
            section_artifacts = tuple(parsed_section_artifacts)
            semantic_gate = evaluate_publication_semantics(
                evidence_manifest=checkpoint.evidence_manifest,
                section_artifacts=section_artifacts,
                citations=tuple(
                    SectionCitation(
                        citationId=item.citation_id,
                        datasetId=item.dataset_id,
                        requirementId=item.requirement_id,
                        snapshotHash=item.snapshot_hash,
                    )
                    for item in authoritative_citations(lineage)
                ),
            )
            warnings.extend(semantic_gate["warnings"])
            warnings.extend(
                warning for artifact in section_artifacts for warning in artifact.warnings
            )
        except (TypeError, ValueError, ValidationError, AttributeError):
            issue("analysis_checkpoint_invalid", "发布门禁无法核验冻结分析产物。")

        if result.get("status") != "validated":
            issue("artifact_not_validated", "Markdown、PDF、DOCX 或 HTML 尚未完成验收。")
        for key in ("markdownPath", "pdfPath", "wordPath", "htmlPath"):
            path = result.get(key)
            if not isinstance(path, str) or not path:
                issue("artifact_identity_invalid", "验收回执缺少产物路径。", field=key)
                continue
            try:
                current = await self.workspace_service.ahash_file(thread_id, path)
                expected_size: Any
                expected_sha: Any
                if key == "markdownPath" and manifest is not None:
                    expected_size = manifest.markdown.size
                    expected_sha = manifest.markdown.sha256
                else:
                    expected_size = result.get(key.replace("Path", "Size"))
                    expected_sha = result.get(key.replace("Path", "Sha256"))
                if (
                    current.get("missing")
                    or current.get("size") != expected_size
                    or current.get("sha256") != expected_sha
                ):
                    issue("artifact_identity_changed", "已验收产物在发布前发生变化。", field=key)
            except Exception:
                issue("artifact_path_invalid", "已验收产物路径不可读取或越界。", field=key)

        # 质量告警用于后续修复审计，与完整性/身份类发布阻断相互独立；即使正式发布
        # 被 issues 阻断，也必须保留本次检查发现，避免丢失后续修复所需的历史记录。
        try:
            for item in warnings:
                if not isinstance(item, Mapping):
                    continue
                code = item.get("code")
                if not isinstance(code, str):
                    continue
                notice = _publication_warning_notice(
                    item,
                    run_id=audit.report_run_id,
                    source_phase=("analysis" if code.startswith("analysis_") else "publication"),
                )
                audit.add(notice)
            quality_warning_service = getattr(self, "quality_warning_service", None)
            if quality_warning_service is not None:
                scope = self._scope(run_context)
                tenant = TenantScope(
                    database_name=scope["database"], company_id=str(scope["companyId"])
                )
                await audit.flush(service=quality_warning_service, tenant=tenant)
        except QualityWarningContractError as error:
            issue("report_quality_audit_invalid", "发布质量告警不符合审计契约。")
            logger.warning(
                "report_quality_audit_invalid report_run_id={} error_type={}",
                audit.report_run_id,
                type(error).__name__,
            )
        except Exception as error:
            raise ReportingError(
                "report_quality_audit_failed", "发布质量告警审计写入失败。"
            ) from error
        audit_summary = audit.build().as_dict()
        return {
            "formalReleaseAllowed": not issues,
            "issues": issues,
            "warnings": warnings,
            "auditSummary": audit_summary,
        }

    async def publish_report(self, step_input: StepInput, run_context: RunContext) -> StepOutput:
        feedback = self._feedback(step_input)
        if feedback:
            # 反馈重跑继续走唯一的 Agno ReportingAnalysisAndDraftWorkflow 入口，
            # 避免发布路径维护第二套手写章节循环。
            await self.run_reporting_analysis(step_input, run_context)
            await self._render_and_validate(run_context)
        result = self._workflow_result(self._state(run_context))
        state = self._state(run_context)
        try:
            ReportArtifactManifest.model_validate(state[REPORT_ARTIFACTS_STATE_KEY]["draft"])
        except Exception as error:
            raise ReportingError(
                "report_artifact_manifest_invalid", "发布门禁缺少已验收的产物清单。"
            ) from error
        gate = await self._dataset_publication_gate(run_context, result)
        return StepOutput(
            content={
                "status": "validated",
                "formalReleaseAllowed": gate["formalReleaseAllowed"],
                "publicationGate": gate,
                "auditSummary": gate.get("auditSummary", {}),
                "jobId": result["jobId"],
                "reportId": str(run_context.run_id),
                "reportTitle": _frozen_outline(state).title,
                "revision": int(result.get("revision", 0)) + 1,
                "markdownPath": result["markdownPath"],
                "pdfPath": result["pdfPath"],
                "pdfSize": result["pdfSize"],
                "pdfSha256": result["pdfSha256"],
                "wordPath": result["wordPath"],
                "wordSize": result["wordSize"],
                "wordSha256": result["wordSha256"],
                "htmlPath": result["htmlPath"],
                "htmlSize": result["htmlSize"],
                "htmlSha256": result["htmlSha256"],
                "validation": result["validation"],
                "sourceWarnings": result.get("sourceWarnings", []),
                "codingReceipts": result.get("codingReceipts", []),
            }
        )

    async def _build_and_write_artifact_manifest(
        self,
        manifest_path: str,
        *,
        accepted_artifacts: list[dict[str, Any]],
        markdown_path: str,
        lineage: tuple[DatasetLineage, ...],
        revision: int,
        task_key: str,
        section_numbers: tuple[str, ...],
        heading_numbers: tuple[HeadingNumber, ...],
        run_context: RunContext,
        source_warnings: tuple[SourceWarning, ...] = (),
    ) -> ReportArtifactManifest:
        scope = self._scope(run_context)
        accepted_by_path: dict[str, dict[str, Any]] = {}
        for item in accepted_artifacts:
            path = item.get("path") if isinstance(item, dict) else None
            if not isinstance(path, str) or path in accepted_by_path:
                raise ReportingError(
                    "report_artifact_acceptance_incomplete", "正式产物回执包含重复或无效路径。"
                )
            accepted_by_path[path] = item
        current_artifacts = await self.workspace_service.abatch_hash_files(
            scope["threadId"], list(accepted_by_path)
        )
        current_by_path = {
            item.get("path"): item
            for item in current_artifacts
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        if (
            len(current_by_path) != len(accepted_by_path)
            or set(current_by_path) != set(accepted_by_path)
            or any(
                current_by_path[path].get("missing")
                or current_by_path[path].get("size") != accepted_by_path[path].get("size")
                or current_by_path[path].get("sha256") != accepted_by_path[path].get("sha256")
                for path in accepted_by_path
            )
        ):
            raise ReportingError("report_artifact_file_changed", "正式产物在完成验收后发生变化。")
        accepted = next(
            (
                item
                for item in current_artifacts
                if isinstance(item, dict) and item.get("path") == markdown_path
            ),
            None,
        )
        if not isinstance(accepted, dict):
            raise ReportingError(
                "report_artifact_acceptance_missing",
                "正式产物验收回执缺少报告 Markdown。",
            )
        _relative, markdown_remote = self.workspace_service.normalize_path(
            markdown_path, allow_root=False
        )
        _relative, manifest_remote = self.workspace_service.normalize_path(
            manifest_path, allow_root=False
        )
        try:
            async with self.workspace_service._async_client() as client:
                sandbox = await self.workspace_service._asandbox_for(client, scope["threadId"])
                markdown_bytes = await self.workspace_service._adownload_file(
                    sandbox, markdown_remote, 10 * 1024 * 1024
                )
            if len(markdown_bytes) != accepted.get("size") or hashlib.sha256(
                markdown_bytes
            ).hexdigest() != accepted.get("sha256"):
                raise ReportingError(
                    "report_artifact_file_changed",
                    "报告 Markdown 在正式验收后发生变化。",
                )
            manifest = build_authoritative_manifest(
                report_id=str(run_context.run_id),
                revision=revision,
                task_key=task_key,
                effective_profile_hash=self._profile(run_context).effective_profile_hash,
                markdown_path=markdown_path,
                markdown=markdown_bytes.decode("utf-8"),
                accepted_artifacts=current_artifacts,
                lineage=lineage,
                sections=tuple(
                    section.code for section in _frozen_outline(self._state(run_context)).sections
                ),
                section_numbers=section_numbers,
                heading_numbers=heading_numbers,
                source_warnings=source_warnings,
            )
            content = json.dumps(
                manifest.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            self.workspace_service._validate_content(content)
            async with self.workspace_service._async_client() as client:
                sandbox = await self.workspace_service._asandbox_for(client, scope["threadId"])
                await self.workspace_service._aensure_directory(
                    sandbox, manifest_remote.rsplit("/", 1)[0]
                )
                await sandbox.fs.upload_file(content, manifest_remote)
                stored = await self.workspace_service._adownload_file(
                    sandbox, manifest_remote, len(content)
                )
            if stored != content:
                raise ReportingError(
                    "report_artifact_manifest_changed",
                    "服务端报告产物清单写入后发生变化。",
                )
        except ReportingError:
            raise
        except Exception as error:
            raise ReportingError(
                "report_artifact_manifest_invalid", "服务端无法生成报告产物清单。"
            ) from error
        return manifest


def _analysis_quality_warnings(
    metric_definitions: tuple[MetricDefinition, ...],
    analysis_warnings: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    """把冻结分析披露的不可比与数据缺失转换为发布告警。"""

    warnings: list[dict[str, Any]] = []
    comparability_markers = ("期间跨度不一致", "同期不可比", "仅作参考性对比")
    for metric in metric_definitions:
        description = f"{metric.definition} {metric.period_basis}"
        mismatched_budget_actual = (
            "执行" in metric.name
            and "预算" in description
            and "实际" in description
            and description.count("覆盖") >= 2
        )
        zero_period_comparison = "同比" in description and re.search(
            r"\d{1,2}(?:月|[-—至到]\d{1,2}月)为0", description
        )
        if (
            any(marker in description for marker in comparability_markers)
            or mismatched_budget_actual
            or zero_period_comparison is not None
        ):
            warnings.append(
                {
                    "code": "analysis_period_incomparable",
                    "message": "冻结指标包含不可比期间，报告结论需按披露口径谨慎使用。",
                    "details": {"metricCode": metric.code, "periodBasis": metric.period_basis},
                }
            )
    for warning in analysis_warnings:
        classified = False
        if any(marker in warning for marker in comparability_markers):
            classified = True
            warnings.append(
                {
                    "code": "analysis_period_incomparable",
                    "message": "冻结分析 Warning 标记了不可比期间，报告结论需谨慎使用。",
                    "details": {"warning": warning[:500]},
                }
            )
        if any(
            marker in warning
            for marker in (
                "数据缺失",
                "数据不完整",
                "期间不完整",
                "期间不足",
                "缺失月份",
                "疑似未入账",
            )
        ):
            classified = True
            warnings.append(
                {
                    "code": "analysis_data_incomplete",
                    "message": "冻结分析披露数据缺失或期间不完整，报告结论需按实际覆盖范围使用。",
                    "details": {"warning": warning[:500]},
                }
            )
        if not classified:
            warnings.append(
                {
                    "code": "analysis_data_quality",
                    "message": "冻结分析披露数据质量限制，报告结论需结合告警内容谨慎使用。",
                    "details": {"warning": warning[:500]},
                }
            )
    return tuple(warnings)


def _publication_warning_notice(item: Mapping[str, Any], *, run_id: str, source_phase: str):
    """按已知 warning 协议显式绑定主体，不从任意 details 字段猜测优先级。"""

    code = item.get("code")
    if not isinstance(code, str):
        raise QualityWarningContractError("质量告警缺少 code。")
    if code.startswith("source_"):
        return WarningAdapter.from_source_warning(item, source_phase="analysis")
    details = item.get("details", {})
    if not isinstance(details, Mapping):
        details = {}
    details = dict(details)
    # 图表检查器历史上将 chartId 放在 warning 顶层；这是已知协议字段，显式搬入
    # notice details，避免发布边界再通过任意字段优先级推断主体。
    if isinstance(item.get("chartId"), str) and "chartId" not in details:
        details["chartId"] = item["chartId"]
    if isinstance(item.get("sectionCode"), str) and "sectionCode" not in details:
        details["sectionCode"] = item["sectionCode"]
    if isinstance(details.get("claimId"), str):
        subject_type, subject_id = "section_claim", details["claimId"]
    elif isinstance(details.get("blockId"), str):
        subject_type, subject_id = "section_block", details["blockId"]
    elif isinstance(details.get("chartId"), str):
        subject_type, subject_id = "analysis_chart", details["chartId"]
    elif isinstance(details.get("metricCode"), str):
        subject_type, subject_id = "metric", details["metricCode"]
    elif isinstance(details.get("sectionCode"), str):
        subject_type, subject_id = "section", details["sectionCode"]
    else:
        subject_type, subject_id = "report", run_id
    return WarningAdapter.from_mapping(
        {**item, "details": details},
        source_phase=("analysis" if code.startswith("analysis_") else source_phase),
        subject_type=subject_type,
        subject_id=subject_id,
    )


def _citation_presentations(
    *,
    lineage: tuple[DatasetLineage, ...],
    requirements: tuple[QueryRequirement, ...],
    analyses: tuple[AnalysisItem, ...],
    snapshots: tuple[SourceSchemaSnapshot, ...],
    observed_facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requirements_by_id = {item.requirement_id: item for item in requirements}
    table_descriptions: dict[tuple[str, str], str] = {}
    for snapshot in snapshots:
        for table in snapshot.tables:
            qualified = f"{table.database}.{table.name}".lower()
            label = _human_label(table.description, "")
            if label:
                table_descriptions[(table.source_id, qualified)] = label
                table_descriptions[(table.source_id, table.name.lower())] = label
    presentations: list[dict[str, Any]] = []
    for index, citation in enumerate(authoritative_citations(lineage), start=1):
        requirement = requirements_by_id.get(citation.requirement_id)
        metadata_labels = []
        if requirement is not None:
            metadata_labels = [
                table_descriptions.get((requirement.source_id, table.table.lower()), "")
                for table in requirement.tables
            ]
            metadata_labels = list(dict.fromkeys(item for item in metadata_labels if item))
        analysis_label = next(
            (
                analysis.description
                for analysis in analyses
                if citation.requirement_id in analysis.requirement_ids
            ),
            None,
        )
        label = _human_label(
            "、".join(metadata_labels) if metadata_labels else analysis_label,
            f"第 {index} 项已审核业务数据",
        )
        coverage_items: list[dict[str, Any]] = []
        bound_facts = [
            fact
            for fact in observed_facts
            if fact.get("datasetId") == citation.dataset_id
            and fact.get("requirementId") == citation.requirement_id
        ]
        for coverage_index, fact in enumerate(bound_facts, start=1):
            table_name = str(fact.get("table") or "").lower()
            source_id = str(fact.get("sourceId") or "")
            coverage_label = _human_label(
                table_descriptions.get((source_id, table_name)),
                f"来源项 {coverage_index}",
            )
            coverage = {
                str(period) for period in fact.get("periodCoverage", []) if isinstance(period, str)
            }
            missing = {
                str(period) for period in fact.get("missingPeriods", []) if isinstance(period, str)
            }
            coverage_items.append({"label": coverage_label, "periods": sorted(coverage - missing)})
        presentations.append(
            {
                "citationId": citation.citation_id,
                "label": label,
                "coverageItems": coverage_items,
            }
        )
    return presentations


def _accepted_artifacts_match_manifest(
    manifest: ReportArtifactManifest,
    manifest_path: str,
    accepted_artifacts: list[dict[str, Any]],
) -> bool:
    accepted: dict[str, dict[str, Any]] = {
        path: item
        for item in accepted_artifacts
        if isinstance(item, dict) and isinstance(path := item.get("path"), str)
    }
    if len(accepted) != len(accepted_artifacts):
        return False
    declared = [manifest.markdown, *manifest.charts]
    declared_paths = {item.path for item in declared}
    extra_paths = set(accepted) - declared_paths
    if manifest_path in accepted or any(
        PurePosixPath(path).suffix.lower() not in {".png", ".jpg", ".jpeg"} for path in extra_paths
    ):
        return False
    if not declared_paths.issubset(accepted):
        return False
    return all(
        accepted[item.path].get("size") == item.size
        and accepted[item.path].get("sha256") == item.sha256
        for item in declared
    )


def _report_pdf_path(run_id: str, revision: int, title: str, period: ReportPeriod) -> str:
    filename = _report_pdf_filename(title, period)
    return f"报表/智能分析/{run_id}/revision-{revision}/{filename}"
