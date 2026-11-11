# mypy: disable-error-code="attr-defined"
# 运行时由 facade 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote, urlencode

from loguru import logger

from ....quality_warnings import (
    QualityAuditCollector,
    QualityWarningContractError,
    TenantScope,
    WarningAdapter,
)
from ...delivery.office_engine import run_office_engine
from ...delivery.pptx import build_editable_pptx
from ...hospital_operation.findings import FindingGraph
from ...hospital_operation.narrative_outline import (
    NarrativeOutline,
    evaluate_narrative_quality,
)
from ...trace.contracts_v1 import RevisionTraceIndexV1
from ...trace.drilldown_builder import build_drilldown_metrics
from ...trace.fact_service import read_fact_document, resolve_fact_from_document
from ...trace.index_builder import (
    build_csv_trace_index,
    encode_trace_index,
    trace_index_path_for,
)
from ...trace.narrative_claims import narrative_paragraphs
from ..checkpoint import AnalysisEvidenceManifest, SectionArtifact, SectionCitation
from .base import (
    REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY,
    REPORT_ANALYSIS_PLAN_STATE_KEY,
    REPORT_ARTIFACTS_STATE_KEY,
    REPORT_DATA_REQUIREMENTS_STATE_KEY,
    REPORT_DATASET_LINEAGE_STATE_KEY,
    REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
    REPORT_ROW_PRESERVING_REQUIREMENTS_STATE_KEY,
    REPORT_WORKFLOW_RESULT_STATE_KEY,
    AnalysisItem,
    Any,
    ArtifactFile,
    DatasetHandle,
    DatasetLineage,
    DetailedAnalysisPlan,
    DocxArtifactManifest,
    DurableReportingPhase,
    FileIdentity,
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
from .workbook import build_workbook_sheets, validate_workbook_snapshot, workbook_dataset_rows


def _narrative_reuse_snapshot_hash(graph, finding_graph_hash: str | None) -> str | None:
    """跨章节复用 analysisId 只承认发现图谱哈希，不使用数据集快照哈希。"""
    if not isinstance(finding_graph_hash, str) or finding_graph_hash != graph.snapshot_hash:
        return None
    return graph.snapshot_hash


def _without_verified_analysis_reuse(
    issues: list[dict[str, Any]],
    *,
    graph,
    narrative,
    outline,
    finding_graph_hash: str | None,
) -> list[dict[str, Any]]:
    """发现映射与图谱哈希一致时，去掉跨章节复用同一分析的门禁。"""
    snapshot_hash = _narrative_reuse_snapshot_hash(graph, finding_graph_hash)
    if (
        outline is None
        or snapshot_hash is None
        or not _matches_narrative_analysis_bindings(graph, narrative, outline, snapshot_hash)
    ):
        return issues
    return [item for item in issues if item.get("code") != "outline_analysis_duplicate"]


def _matches_narrative_analysis_bindings(graph, narrative, outline, snapshot_hash: str) -> bool:
    """仅已核验快照和逐章节发现映射可解释跨章节复用同一分析。"""
    if graph.snapshot_hash != snapshot_hash or narrative.snapshot_hash != snapshot_hash:
        return False
    expected = {section.code: tuple(section.analysis_ids) for section in outline.sections}
    if expected != {section.code: tuple(section.analysis_ids) for section in narrative.sections}:
        return False
    cards = {card.finding_id: card for card in graph.findings}
    for section in narrative.sections:
        if not section.finding_ids or any(finding_id not in cards for finding_id in section.finding_ids):
            return False
        analysis_ids = {analysis_id for finding_id in section.finding_ids
                        for analysis_id in cards[finding_id].analysis_ids}
        if analysis_ids != set(section.analysis_ids):
            return False
    return True


def narrative_quality_warnings(
    graph: FindingGraph,
    outline: NarrativeOutline,
    rendered_section_codes: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    """将章节覆盖和重复指标转换为发布质量软告警。"""
    quality = evaluate_narrative_quality(
        graph, outline, rendered_section_codes=rendered_section_codes
    )
    return tuple(
        {
            **issue,
            "message": {
                "report_narrative_duplicate_finding": "同一管理发现被多个章节重复呈现。",
                "report_narrative_unassigned_finding": "存在未分配到正文或附录的管理发现。",
                "report_narrative_empty_section": "存在没有管理发现的空章节。",
                "report_narrative_section_unrendered": "批准提纲中有章节尚未生成正文。",
            }.get(str(issue.get("code")), "动态章节质量需要复核。"),
            "details": {"coverageRate": quality.coverage_rate},
        }
        for issue in quality.issues
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
        if chart.source_dataset_id not in dataset_semantics:
            warnings.append(
                {
                    "code": "report_chart_dataset_unfrozen",
                    "message": "图表引用了尚未冻结语义的 Dataset。",
                    "details": {
                        "chartId": chart.chart_id,
                        "datasetId": chart.source_dataset_id,
                    },
                }
            )
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


def build_with_optional_computation_layer(
    build: Callable[[tuple[FileIdentity, ...], tuple], Any],
    computation_files: tuple[FileIdentity, ...],
    computations: tuple,
) -> Any:
    """补充分析计算层（计算记录、脚本与补证文件）只是追溯元数据；契约不接受时不登记该层，
    其余索引照常生成。审阅：补证文件现在即使没有有效计算记录也会登记，只在有计算记录时
    回退会让补证文件的问题拖垮整份索引与产物清单。"""
    try:
        return build(computation_files, computations)
    except (ValidationError, ValueError) as error:
        if not computations and not computation_files:
            raise
        logger.warning(
            "report_trace_computations_dropped count={} files={} error_type={} reason={}",
            len(computations), len(computation_files), type(error).__name__, str(error)[:500],
        )
    # 先只丢计算记录、保留补证与脚本文件身份：整层一起丢会让导出的修订包缺少图表输入
    # 声明来源的 evidence 文件，离线核验无从复算。文件身份本身仍不被接受时才全部丢弃。
    if computations and computation_files:
        try:
            return build(computation_files, ())
        except (ValidationError, ValueError) as error:
            logger.warning(
                "report_trace_computation_files_dropped files={} error_type={} reason={}",
                len(computation_files), type(error).__name__, str(error)[:500],
            )
    return build((), ())


def _quality_source_ids(index: RevisionTraceIndexV1) -> set[str]:
    source_ids = {entry.file_resource_id for entry in index.fact_files}
    source_ids.update(cell.source_cell.file_resource_id for table in index.tables
                      for cell in table.cells if cell.source_cell is not None)
    from ...trace.table_sources import derivation_resource_ids

    for subject in index.subject_bindings:
        number = subject.number_reference
        if number is not None and number.table_derivation is not None:
            source_ids.update(derivation_resource_ids(number.table_derivation))
    source_ids.update(resource_id for chart in index.chart_traces
                      for resource_id in (chart.image_file_resource_id, *chart.plot_data_file_resource_ids))
    from ...trace.chart_quality import standard_proof_source_ids

    source_ids.update(standard_proof_source_ids(index))
    return source_ids


class RuntimePublicationMixin:
    async def _retain_rendered_report(
        self, run_context: RunContext, result: dict[str, Any],
        pdf_path: str, word_path: str, validation: dict[str, Any],
    ) -> dict[str, Any]:
        """验收失败时按实际文件身份保留下载输入，不伪造通过回执。"""
        available = 0
        validation = {**validation, "issues": list(validation.get("issues") or [])}
        for label, path in (("pdf", pdf_path), ("word", word_path)):
            for suffix in ("Path", "Size", "Sha256"):
                result.pop(f"{label}{suffix}", None)
            try:
                identity = await self.workspace_service.ahash_file(self._scope(run_context)["threadId"], path)
                if identity.get("missing") or not identity.get("sha256") or not identity.get("size"):
                    raise OSError("artifact identity unavailable")
            except Exception:
                validation["issues"].append({"code": f"report_{label}_unavailable", "message": f"{'PDF' if label == 'pdf' else 'Word'} 未生成或身份不可读取。"})
                continue
            result.update({f"{label}Path": path, f"{label}Size": int(identity["size"]), f"{label}Sha256": str(identity["sha256"])})
            available += 1
            if hasattr(self, "state_repository"):
                try:
                    await self._apply_durable_command(run_context, ReportingCommand(
                        name="record_artifact", commandId=f"retained-{label}:{path}:{identity['sha256']}", payload={"artifact": identity},
                    ))
                except Exception:
                    logger.warning("report_retained_artifact_checkpoint_unavailable format={}", label)
                    validation["issues"].append({"code": "report_artifact_checkpoint_unavailable", "message": "产物检查点写入失败，实际可读格式仍可下载。"})
        if not available:
            raise ReportingError("report_artifact_unavailable", "没有可读取身份的报告文件。")
        issues = validation.get("issues")
        result.update({
            "status": "validation_failed", "validation": {**validation, "ok": False},
            "validationIssues": [
                {key: str(item[key])[:500] for key in ("code", "message") if item.get(key) is not None}
                for item in (issues[:20] if isinstance(issues, list) else []) if isinstance(item, dict)
            ],
        })
        self._state(run_context)[REPORT_WORKFLOW_RESULT_STATE_KEY] = result
        return result

    async def validate_report(self, _step_input: StepInput, run_context: RunContext) -> StepOutput:
        return StepOutput(content=await self._render_and_validate(run_context))

    async def _render_and_validate(self, run_context: RunContext, *, execution=None) -> dict[str, Any]:
        if execution is not None:
            return await self._render_revision_document(run_context, execution)
        state = self._state(run_context)
        result = self._workflow_result(state)
        outline = _frozen_outline(state)
        if state.get("report_request_context", {}).get("deliveryFormat") == "xlsx":
            return await self._render_xlsx(run_context, result, outline)
        if state.get("report_request_context", {}).get("deliveryFormat") == "pptx":
            return await self._render_pptx(run_context, result, outline)
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
        pdf_path = _report_pdf_path(
            str(run_context.run_id), draft.revision, outline.title, self._envelope(run_context).period,
        )
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
        source_link_issue = None
        try:
            source_links = await self._source_links_by_dataset(draft, run_context)
        except Exception as error:
            logger.warning("report_source_appendix_unavailable reason={}", type(error).__name__)
            source_links = {}
            source_link_issue = {
                "code": "report_source_appendix_unavailable",
                "message": "来源附录追溯索引无法读取或解析，未标记验收通过；报告产物仍继续生成。",
            }
            issue = {**source_link_issue, "status": "unknown", "revision": draft.revision}
            issues = state.setdefault("report_quality_issues", [])
            if issue not in issues:
                issues.append(issue)
        await self.report_tools.bind_citation_presentations(
            str(result["jobId"]),
            _citation_presentations(
                lineage=lineage,
                requirements=requirements,
                analyses=analyses,
                snapshots=self._snapshots(run_context),
                observed_facts=observed_facts,
                source_links_by_dataset=source_links,
            ),
            run_context=context,
        )
        # 总览始终保留问题缺项；没有业务批准映射也不能回退到未经核验的摘录。
        from ..management_overview import unavailable_management_overview_projection

        overview_projection = unavailable_management_overview_projection(draft.markdown.sha256)
        try:
            from ...trace.contracts_v1 import canonical_sha256
            from ..management_overview import management_overview_projection
            from ..overview_sources import registered_management_overview

            scope = self._scope(run_context)
            overview = await registered_management_overview(
                self.workspace_service, scope["threadId"], draft,
                canonical_sha256({key: scope[key] for key in ("userId", "threadId")}),
            )
            job = self.report_tools._load_job(str(result["jobId"]), context)
            overview_projection = management_overview_projection(
                overview, draft.markdown.sha256, job.get("_citationPresentations"),
            )
        except Exception as error:
            logger.warning("report_management_overview_unavailable reason={}", type(error).__name__)
            # 带修订号：反馈重跑时按修订清理，不重复累积或残留到后续修订。
            issue = {
                "code": "management_overview_evidence_unavailable", "status": "unknown",
                "revision": draft.revision,
                "message": "经营总览证据不可用，已保留缺项说明并继续生成报告。",
            }
            issues = state.setdefault("report_quality_issues", [])
            if issue not in issues:
                issues.append(issue)
        document_issues = []
        try:
            from ..claim_presentation import registered_document_presentations

            job = self.report_tools._load_job(str(result['jobId']), context)
            job['_claimSupportProjection'] = {'invalid': 'claim_support_unavailable'}
            job.pop('_traceSourcePresentations', None)
            self.report_tools._store_job(job, context)
            presentations = await registered_document_presentations(self, run_context, draft)
            job['_claimSupportProjection'] = presentations['claimSupport']
            job['_traceSourcePresentations'] = presentations['traceSources']
            if presentations['traceSources'] is not None:
                options = job.get('_reportDesign', {}).get('options', {})
                job.setdefault('_editorExportSettings', {}).setdefault('sources', options.get('sources', True))
            if presentations.get('sourceIssue'):
                document_issues.append(presentations['sourceIssue'])
            self.report_tools._store_job(job, context)
        except Exception as error:
            logger.warning('report_claim_support_projection_unavailable reason={}', type(error).__name__)
            document_issues.append({'code': 'claim_support_projection_unavailable',
                'revision': draft.revision, 'status': 'unknown', 'message': '解释支持状态无法核验，已保留提示和下载。'})
        state.setdefault('report_quality_issues', []).extend(document_issues)
        rendered_result = await self.report_tools._render_report_pair(
            str(result["jobId"]),
            str(result["markdownPath"]),
            pdf_path,
            artifact_manifest=draft.model_dump(mode="json", by_alias=True),
            management_overview=overview_projection,
            run_context=context,
        )

        word_path = str(PurePosixPath(pdf_path).with_suffix(".docx"))
        validation = rendered_result.get("validation") if isinstance(rendered_result, dict) else None
        if source_link_issue is not None:
            document_issues.append(source_link_issue)
        if document_issues:
            validation = validation if isinstance(validation, dict) else {"ok": False, "issues": []}
            validation = {
                **validation,
                "ok": False,
                "issues": [
                    *(validation.get("issues") if isinstance(validation.get("issues"), list) else []),
                    *document_issues,
                ],
            }
        if not isinstance(validation, dict) or validation.get("ok") is not True:
            validation = validation if isinstance(validation, dict) else {
                "ok": False,
                "issues": [{"code": "validation_receipt_invalid"}],
            }
            return await self._retain_rendered_report(
                run_context, result, pdf_path, word_path, validation
            )
        try:
            if not isinstance(rendered_result, dict):
                raise ReportingError(
                    "report_artifact_validation_failed", "PDF/Word 联合验收回执无效。"
                )
            if rendered_result.get("wordPath") != word_path:
                raise ReportingError(
                    "report_artifact_validation_failed", "Word 验收路径缺失或不匹配。"
                )
            pdf_identity = await self.workspace_service.ahash_file(
                self._scope(run_context)["threadId"], pdf_path
            )
            word_identity = await self.workspace_service.ahash_file(
                self._scope(run_context)["threadId"], word_path
            )
            validated_pdf_sha256 = validation.get("pdfSha256")
            validated_word_sha256 = validation.get("wordSha256")
            if (
                not isinstance(validated_pdf_sha256, str)
                or pdf_identity.get("sha256") != validated_pdf_sha256
                or not isinstance(validated_word_sha256, str)
                or word_identity.get("sha256") != validated_word_sha256
            ):
                raise ReportingError(
                    "report_artifact_changed",
                    "PDF 或 Word 在验收后发生变化，必须重新渲染并验收。",
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
            common_manifest_fields = {
                "reportId": draft.report_id,
                "revision": draft.revision,
                "reportBasisId": draft.report_basis_id,
                "sourceMarkdownSha256": draft.markdown.sha256,
                "sourceChartSha256s": source_chart_sha256s,
                "renderedChartIds": tuple(validation.get("chartIds") or ()),
                "citationIds": tuple(validation.get("citationIds") or ()),
                "sections": tuple(validation.get("sectionIds") or ()),
                "sectionNumbers": draft.section_numbers,
                "headingNumbers": draft.heading_numbers,
                "sourceWarnings": source_warnings,
            }
            rendered_pdf = PdfArtifactManifest(
                **common_manifest_fields,
                pdf=ArtifactFile(
                    path=pdf_path,
                    mediaType="application/pdf",
                    size=pdf_identity["size"],
                    sha256=pdf_identity["sha256"],
                ),
                pageCount=page_count,
            )
            rendered_word = DocxArtifactManifest(
                **common_manifest_fields,
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
                "validation": validation,
            }
        except Exception as error:
            # 回执、状态或发布验收异常不应删除已生成文件。重新读取实际身份，
            # 由下载签发保留文件；失败原因随回执明确返回。
            logger.warning("report_artifact_validation_failed error_type={}", type(error).__name__)
            raw_issues = validation.get("issues")
            safe_issues = raw_issues if isinstance(raw_issues, list) else []
            return await self._retain_rendered_report(
                run_context, result, pdf_path, word_path,
                {**validation, "ok": False, "issues": [
                    *safe_issues,
                    {
                        "code": error.code if isinstance(error, ReportingError) else "report_artifact_validation_failed",
                        "message": error.message if isinstance(error, ReportingError) else "PDF/Word 验收无法完成，产物已保留。",
                    },
                ]},
            )
        except BaseException:
            # _render_report_pair 返回即表示 revision 目录已正式发布。之后任何回执、
            # 身份、manifest 或状态异常都必须删除同一 revision 的两种产物；取消也不能打断清理。
            await complete_cleanup(
                self.report_tools.discard_report_revision(
                    str(result["jobId"]), pdf_path, word_path, run_context=context
                )
            )
            raise

    async def _render_revision_document(self, run_context: RunContext, execution) -> dict[str, Any]:
        """以独立原生文档任务渲染新修订；已登记文件的恢复不依赖来源仍可读取。"""
        from datetime import datetime
        from uuid import NAMESPACE_URL, uuid5
        from zoneinfo import ZoneInfo

        from ...data_sources import thread_binding
        from ..management_overview import unavailable_management_overview_projection
        from ..policy_adoption import (
            PolicyAdoptionExecution,
            policy_adoption_run_context,
            require_policy_adoption_execution,
        )
        from ..revision_execution import load_revision_outline, require_revision_execution

        source_context = run_context
        adoption = isinstance(execution, PolicyAdoptionExecution)
        if adoption:
            durable = await require_policy_adoption_execution(self, source_context, execution)
            execution_run_id = execution.scope.run_id
            report_id = execution.scope.run_id
            thread_id = execution.scope.workspace_key
            report_revision = 'initial'
            execution_options = {}
            run_context = policy_adoption_run_context(execution)
        else:
            durable = await require_revision_execution(self, run_context, execution)
            execution_run_id = execution.execution_run_id
            report_id = execution.source_scope.run_id
            thread_id = execution.source_scope.workspace_key
            report_revision = execution.report_revision
            execution_options = {'execution': execution}
        if (not set(execution.requested_outputs) <= {'pdf', 'docx'}
                or durable.payload.get('deliveryFormat') != 'document'
                or durable.phase is not DurableReportingPhase.COMPLETED):
            raise ReportingError('report_revision_execution_mismatch', '文档渲染需要本修订已完成的文档装配。')
        revision = execution.output_revision
        root = f'报表/智能分析/{execution_run_id}/document-render/revision-{revision}'
        paths = {'pdf': f'{root}/report.pdf', 'word': f'{root}/report.docx'}
        requested = tuple(label for label, output in (('pdf', 'pdf'), ('word', 'docx'))
            if output in execution.requested_outputs)
        registered = {item['path']: FileIdentity.model_validate(item) for item in durable.payload.get('artifacts', ())}
        job_id = str(uuid5(NAMESPACE_URL, f'{execution_run_id}:document:{revision}'))
        result = {'revision': revision, 'jobId': job_id, 'deliveryFormat': 'document'}
        restored = {label: registered[paths[label]] for label in requested if paths[label] in registered}
        if restored:
            invalid = []
            for label, file in tuple(restored.items()):
                try:
                    await self._read_identity_bytes(thread_id, file, max_bytes=file.size)
                except Exception as error:
                    logger.warning('revision_document_artifact_unavailable format={} error_type={}', label, type(error).__name__)
                    restored.pop(label)
                    invalid.append({'code': f'report_{label}_artifact_unavailable',
                        'message': f'{"PDF" if label == "pdf" else "Word"} 已登记文件的实际身份无法核验，未使用该文件。'})
            saved = durable.payload.get('result', {}).get('renderedDocument')
            if (not invalid and isinstance(saved, dict) and saved.get('revision') == revision and saved.get('jobId') == job_id
                    and isinstance(saved.get('validation'), dict) and isinstance(saved['validation'].get('ok'), bool)
                    and all((saved.get(f'{label}Path'), saved.get(f'{label}Sha256'), saved.get(f'{label}Size')) == (
                        paths[label], restored[label].sha256, restored[label].size)
                        if label in restored and label in requested else not saved.get(f'{label}Path') for label in paths)
                    and any(saved.get(f'{label}Path') for label in requested)):
                return dict(saved)
            issue = {'code': 'document_validation_receipt_unavailable',
                'message': '文档文件已恢复，验收记录缺失或身份不一致，需复核。'}
            for label in requested:
                if label in restored:
                    result.update({f'{label}Path': paths[label], f'{label}Sha256': restored[label].sha256,
                        f'{label}Size': restored[label].size})
            if not any(result.get(f'{label}Path') for label in requested):
                raise ReportingError('report_artifact_unavailable', '没有可读取身份的已请求报告格式。')
            return {**result, 'status': 'validation_failed', 'validation': {'ok': False, 'issues': [issue, *invalid]},
                'validationIssues': [issue, *invalid]}
        job_path = f'{root}.job.json'
        existing = await self.workspace_service.abatch_hash_files(thread_id, [*paths.values(), job_path])
        if any(not item.get('missing') for item in existing):
            raise ReportingError('report_revision_document_outcome_unknown',
                '文档渲染已有任务或文件但无可恢复产物登记，需核对实际结果，禁止自动覆盖或重跑。')
        assembly = durable.payload.get('result', {})
        manifest_file = FileIdentity.model_validate(assembly.get('manifest'))
        if registered.get(manifest_file.path) != manifest_file:
            raise ReportingError('report_revision_execution_mismatch', '文档清单未登记到本修订。')
        draft = await self._read_identity_model(thread_id, manifest_file, ReportArtifactManifest)
        if (draft.report_id != report_id or draft.revision != revision
                or draft.report_basis_id != execution.basis_id):
            raise ReportingError('report_revision_execution_mismatch', '文档清单与本修订计算依据不一致。')
        markdown_file = FileIdentity(path=draft.markdown.path, size=draft.markdown.size, sha256=draft.markdown.sha256)
        if registered.get(markdown_file.path) != markdown_file:
            raise ReportingError('report_revision_execution_mismatch', '文档正文未登记到本修订。')
        await self._read_identity_bytes(thread_id, markdown_file, max_bytes=markdown_file.size)
        if adoption:
            from ..policy_adoption_analysis import assemble_policy_adoption_document

            run_context = await assemble_policy_adoption_document(self, source_context, execution)
            outline = _frozen_outline(self._state(run_context))
        else:
            outline = await load_revision_outline(self, run_context, execution)
        view = await self._metric_planning_context(run_context, report_revision=report_revision)
        handles = await self._registered_metric_dataset_handles(run_context, report_revision=report_revision)
        lineage = tuple(DatasetLineage(datasetId=item.dataset_id, sourceId=item.source_id,
            requirementId=item.requirement_id, sqlHash=item.sql_hash, rowCount=item.row_count, size=item.size,
            sha256=item.sha256, periodRoles=item.period_roles, queryWindowId=item.query_window_id) for item in handles)
        if draft.citations != authoritative_citations(lineage):
            raise ReportingError('report_revision_execution_mismatch', '文档引用与新修订数据集不一致。')
        context = RunContext(run_id=execution_run_id, session_id=thread_id,
            user_id=execution.source_scope.user_id, session_state={})
        sources = [await self.workspace_service.ahash_file(thread_id, item.path) for item in handles]
        if any(item.get('missing') or (item.get('size'), item.get('sha256')) != (handle.size, handle.sha256)
                for item, handle in zip(sources, handles, strict=True)):
            raise ReportingError('report_revision_execution_mismatch', '文档数据集实际身份与新修订不一致。')
        self.report_tools._store_job({'jobId': job_id, '_threadBinding': thread_binding(thread_id),
            'sources': sources}, context)
        branding = self.delivery_settings.branding
        await self.report_tools.bind_page_layout(job_id,
            self.delivery_settings.page_layout.model_dump(mode='json', by_alias=True), run_context=context)
        await self.report_tools.bind_document_context(job_id, {
            'title': outline.title,
            'periodLabel': f'[{view.request.period.start.isoformat()}, {view.request.period.end.isoformat()})',
            'organizationName': branding.organization_name, 'generatedByLabel': branding.generated_by_label,
            'watermarkText': branding.watermark_text,
            'generatedDate': datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(),
            'sectionNumbers': list(draft.section_numbers),
            'sections': [{'code': section.code, 'sectionNumber': section.section_number, 'title': section.title}
                for section in outline.sections],
        }, run_context=context)
        await self.report_tools.complete_document_heading_numbers(job_id,
            [item.model_dump(mode='json', by_alias=True) for item in draft.heading_numbers], run_context=context)
        issues = []
        try:
            source_links = await self._source_links_by_dataset(draft, run_context)
        except Exception as error:
            logger.warning('revision_document_sources_unavailable error_type={}', type(error).__name__)
            source_links = {}
            issues.append({'code': 'report_source_appendix_unavailable',
                'message': '来源附录无法核对，已继续生成文档。'})
        await self.report_tools.bind_citation_presentations(job_id, _citation_presentations(
            lineage=lineage, requirements=(), analyses=(), snapshots=(), observed_facts=[],
            source_links_by_dataset=source_links), run_context=context)
        job_file = await self._write_immutable_artifact(thread_id, job_path, json.dumps({
            'execution': execution.model_dump(mode='json', by_alias=True),
            'manifest': manifest_file.model_dump(mode='json', by_alias=True),
            'job': self.report_tools._load_job(job_id, context),
        }, ensure_ascii=False, sort_keys=True, allow_nan=False).encode())
        await self._apply_durable_command(run_context, ReportingCommand(name='record_artifact',
            commandId=f'revision-document-job:{job_file.sha256}',
            payload={'artifact': job_file.model_dump(mode='json', by_alias=True)}), **execution_options)
        overview = unavailable_management_overview_projection(draft.markdown.sha256)
        try:
            from ...trace.contracts_v1 import canonical_sha256
            from ..management_overview import management_overview_projection
            from ..overview_sources import registered_management_overview

            scope = self._scope(run_context)
            registered_overview = await registered_management_overview(self.workspace_service, thread_id, draft,
                canonical_sha256({key: scope[key] for key in ('userId', 'threadId')}))
            overview = management_overview_projection(registered_overview, draft.markdown.sha256,
                self.report_tools._load_job(job_id, context).get('_citationPresentations'))
        except Exception as error:
            logger.warning('revision_document_overview_unavailable error_type={}', type(error).__name__)
            issues.append({'code': 'management_overview_evidence_unavailable',
                'message': '经营总览证据不可用，已保留缺项说明并继续生成文档。'})
        try:
            from ..claim_presentation import registered_document_presentations

            job = self.report_tools._load_job(job_id, context)
            job['_claimSupportProjection'] = {'invalid': 'claim_support_unavailable'}
            job.pop('_traceSourcePresentations', None)
            self.report_tools._store_job(job, context)
            presentations = await registered_document_presentations(self, run_context, draft)
            job['_claimSupportProjection'] = presentations['claimSupport']
            job['_traceSourcePresentations'] = presentations['traceSources']
            if presentations['traceSources'] is not None:
                options = job.get('_reportDesign', {}).get('options', {})
                job.setdefault('_editorExportSettings', {}).setdefault('sources', options.get('sources', True))
            if presentations.get('sourceIssue'):
                issues.append(presentations['sourceIssue'])
            self.report_tools._store_job(job, context)
        except Exception as error:
            logger.warning('revision_claim_support_projection_unavailable reason={}', type(error).__name__)
            issues.append({'code': 'claim_support_projection_unavailable',
                'message': '解释支持状态无法核验，已保留提示和下载。'})
        try:
            rendered = await self.report_tools._render_report_pair(job_id, draft.markdown.path, paths['pdf'],
                artifact_manifest=draft.model_dump(mode='json', by_alias=True), management_overview=overview, run_context=context)
        except Exception as error:
            logger.warning('revision_document_render_response_unavailable error_type={}', type(error).__name__)
            rendered = None
        raw_validation = rendered.get('validation') if isinstance(rendered, dict) else None
        validation = dict(raw_validation) if isinstance(raw_validation, dict) else {'ok': False, 'issues': [
            {'code': 'document_validation_receipt_unavailable', 'message': '文档验收记录不可用。'}]}
        validation['issues'] = [*(validation.get('issues') or []), *issues]
        if issues:
            validation['ok'] = False
        actual_files = {}
        for label, path in paths.items():
            try:
                actual = await self.workspace_service.ahash_file(thread_id, path)
                if actual.get('missing') or not actual.get('size') or not actual.get('sha256'):
                    raise OSError('document identity unavailable')
                actual_files[label] = actual
                if label in requested:
                    result.update({f'{label}Path': path, f'{label}Sha256': actual['sha256'], f'{label}Size': actual['size']})
                if validation.get(f'{label}Sha256') != actual['sha256']:
                    validation['ok'] = False
                    validation['issues'].append({'code': f'report_{label}_receipt_mismatch',
                        'message': '文档验收回执与实际身份不一致，实际文件已保留。'})
                await self._apply_durable_command(run_context, ReportingCommand(name='record_artifact',
                    commandId=f'revision-document-{label}:{revision}:{actual["sha256"]}', payload={'artifact': actual}),
                    **execution_options)
            except Exception as error:
                logger.warning('revision_document_checkpoint_unavailable format={} error_type={}', label, type(error).__name__)
                validation['ok'] = False
                validation['issues'].append({'code': f'report_{label}_checkpoint_unavailable',
                    'message': '文档身份或检查点无法核对，实际可读格式已保留。'})
        if not any(result.get(f'{label}Path') for label in requested):
            raise ReportingError('report_artifact_unavailable', '没有可读取身份的已请求报告格式。')
        if validation.get('ok') is True:
            try:
                common = dict(reportId=draft.report_id, revision=revision, reportBasisId=draft.report_basis_id,
                    sourceMarkdownSha256=draft.markdown.sha256, sourceChartSha256s=tuple(item.sha256 for item in draft.charts),
                    renderedChartIds=tuple(validation.get('chartIds') or ()), citationIds=tuple(validation.get('citationIds') or ()),
                    sections=tuple(validation.get('sectionIds') or ()), sectionNumbers=draft.section_numbers,
                    headingNumbers=draft.heading_numbers, sourceWarnings=draft.source_warnings)
                def artifact(label, media):
                    return ArtifactFile(path=paths[label], size=actual_files[label]['size'],
                        sha256=actual_files[label]['sha256'], mediaType=media)
                pdf = PdfArtifactManifest(**common, pdf=artifact('pdf', 'application/pdf'), pageCount=validation['pageCount'])
                word = DocxArtifactManifest(**common, docx=artifact('word',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
                    convertedPageCount=validation['word']['convertedPageCount'],
                    sectionCount=validation['word']['sectionCount'], tocEntryCount=validation['word']['tocEntryCount'])
                validate_rendered_artifacts(draft, pdf, word, lineage=lineage)
            except Exception as error:
                logger.warning('revision_document_validation_failed error_type={}', type(error).__name__)
                validation['ok'] = False
                validation['issues'].append({'code': 'report_artifact_validation_failed',
                    'message': '文档联合验收无法完成，实际文件已保留。'})
        result.update({'markdownPath': draft.markdown.path, 'status': 'validated' if validation.get('ok') is True else 'validation_failed',
            'validation': validation, 'validationIssues': list(validation['issues'])})
        try:
            await self._apply_durable_command(run_context, ReportingCommand(name='complete',
                commandId=f'revision-document-render-complete:{revision}:{job_file.sha256}',
                payload={**assembly, 'renderedDocument': dict(result)}), **execution_options)
        except Exception as error:
            logger.warning('revision_document_result_unavailable error_type={}', type(error).__name__)
            issue = {'code': 'document_result_checkpoint_unavailable', 'message': '文档完成状态未确认，实际文件已保留，请读取任务结果核对。'}
            result = {**result, 'status': 'validation_failed', 'validation': {**validation, 'ok': False,
                'issues': [*validation['issues'], issue]}, 'validationIssues': [*validation['issues'], issue]}
        return result

    async def _native_claim_presentations(self, run_context, *, execution=None):
        from ..claim_presentation import registered_native_claim_presentations
        from ..policy_adoption import PolicyAdoptionExecution

        if execution is None:
            manifest = ReportArtifactManifest.model_validate(self._state(run_context)[REPORT_ARTIFACTS_STATE_KEY]['draft'])
        else:
            target_id = (execution.scope.run_id if isinstance(execution, PolicyAdoptionExecution)
                else execution.execution_run_id)
            durable = await self.state_repository.get(target_id)
            identity = FileIdentity.model_validate(durable.payload['result']['manifest'])
            if identity.model_dump(mode='json', by_alias=True) not in durable.payload.get('artifacts', ()):
                raise ValueError('native claim manifest not registered')
            manifest = await self._read_identity_model(self._scope(run_context)['threadId'], identity, ReportArtifactManifest)
        return await registered_native_claim_presentations(self, run_context, manifest)

    async def _render_pptx(self, run_context: RunContext, result: dict[str, Any], outline: Any, *, execution=None) -> dict[str, Any]:
        from ..policy_adoption import (
            PolicyAdoptionExecution,
            policy_adoption_run_context,
            require_policy_adoption_execution,
        )

        source_context = run_context
        adoption = isinstance(execution, PolicyAdoptionExecution)
        if adoption:
            durable = await require_policy_adoption_execution(self, source_context, execution)
            run_context = policy_adoption_run_context(execution)
        execution_options = {} if execution is None or adoption else {'execution': execution}
        revision = max(1, int(result.get("revision", 0)))
        if execution is None:
            title = outline.title
            state = self._state(run_context)
            period = self._envelope(run_context).period
            pptx_path = str(PurePosixPath(_report_pdf_path(
                str(run_context.run_id), revision, title, period,
            )).with_suffix(".pptx"))
            period = f'{period.start.isoformat()} 至 {period.end.isoformat()}' if period is not None else ''
        else:
            from ..revision_execution import load_revision_outline, require_revision_execution

            if not adoption:
                durable = await require_revision_execution(self, run_context, execution, revision=revision)
            if revision != execution.output_revision:
                raise ReportingError('report_revision_execution_mismatch', '幻灯片修订号与已登记执行不同。')
            target_run_id = execution.scope.run_id if adoption else execution.execution_run_id
            thread_id = execution.scope.workspace_key if adoption else execution.source_scope.workspace_key
            report_revision = 'initial' if adoption else execution.report_revision
            if execution.requested_outputs != ('pptx',) or durable.payload.get('deliveryFormat') != 'pptx':
                raise ReportingError('report_revision_execution_mismatch', 'PPTX渲染必须使用本修订冻结格式。')
            # 新请求契约尚未冻结主题；使用引擎默认主题，不读取原报告可变会话配置。
            state = {}
            pptx_path = f'报表/智能分析/{target_run_id}/slides/revision-{revision}/report.pptx'
            registered = next((FileIdentity.model_validate(item) for item in durable.payload.get('artifacts', ())
                if item.get('path') == pptx_path), None)
            if registered is not None:
                await self._read_identity_bytes(thread_id, registered)
                saved = durable.payload.get('result', {}).get('renderedPptx')
                if isinstance(saved, Mapping) and (saved.get('pptxPath'), saved.get('pptxSha256'), saved.get('pptxSize')) == (
                        registered.path, registered.sha256, registered.size):
                    return dict(saved)
                issue = {'code': 'pptx_validation_receipt_unavailable', 'message': 'PPTX文件已恢复，验收记录缺失或身份不一致，需复核。'}
                return {**result, 'status': 'validation_failed', 'deliveryFormat': 'pptx',
                    'pptxPath': registered.path, 'pptxSize': registered.size, 'pptxSha256': registered.sha256,
                    'validation': {'ok': False, 'issues': [issue]}, 'validationIssues': [issue]}
            existing = (await self.workspace_service.abatch_hash_files(self._scope(run_context)['threadId'], [pptx_path]))[0]
            if not existing.get('missing'):
                raise ReportingError('report_revision_execution_mismatch', '发现未登记PPTX，禁止自动覆盖或重新渲染，需核对实际结果。')
            if adoption:
                from ..policy_adoption_analysis import assemble_policy_adoption_slides

                run_context = await assemble_policy_adoption_slides(self, source_context, execution)
                expected_outline = _frozen_outline(self._state(run_context))
                durable = await require_policy_adoption_execution(self, source_context, execution)
            else:
                expected_outline = await load_revision_outline(self, run_context, execution)
            if outline != expected_outline:
                raise ReportingError('report_revision_execution_mismatch', 'PPTX渲染必须使用本修订冻结提纲。')
            title = outline.title
            view = await self._metric_planning_context(run_context, report_revision=report_revision)
            period = f'[{view.request.period.start.isoformat()}, {view.request.period.end.isoformat()})'
        validation: dict[str, Any] = {"ok": False, "issues": []}
        try:
            if execution is None:
                durable = await self.state_repository.get(
                    str(run_context.run_id or self._scope(run_context)["externalRunId"])
                )
            checkpoint = ReportingCheckpoint.model_validate(
                durable.payload.get("workflowCheckpoint") if durable is not None else None
            )
            manifest = checkpoint.evidence_manifest
            if manifest is None:
                raise ValueError("frozen analysis evidence unavailable")
            from .slides import SlideOutline, build_slide_outline

            fact_contents = {key: await self._read_identity_bytes(self._scope(run_context)['threadId'], identity)
                for key, identity in checkpoint.deterministic_fact_files.items()}
            if checkpoint.slide_outline_file is not None:
                slide_outline = await self._read_identity_model(
                    self._scope(run_context)["threadId"], checkpoint.slide_outline_file, SlideOutline,
                )
                if slide_outline.snapshot_hash != checkpoint.finding_graph_hash:
                    raise ValueError("slide outline snapshot mismatch")
                graph = await self._read_identity_model(
                    self._scope(run_context)["threadId"], checkpoint.finding_graph_file, FindingGraph,
                )
                if slide_outline != build_slide_outline(graph, manifest, title=title, fact_contents=fact_contents,
                        analysis_summaries=slide_outline.analysis_summaries):
                    raise ValueError("slide outline evidence mismatch")
            else:
                graph = await self._read_identity_model(
                    self._scope(run_context)["threadId"], checkpoint.finding_graph_file, FindingGraph,
                )
                slide_outline = build_slide_outline(graph, manifest, title=title, fact_contents=fact_contents)
            chart_files = {item.chart_id: item.source_file for item in manifest.charts}
            from ...trace.native_claims import present_native_summary

            try:
                claim_presentations = await self._native_claim_presentations(run_context, execution=execution)
            except Exception as error:
                logger.warning('report_native_claim_support_unavailable format=pptx error_type={}', type(error).__name__)
                claim_presentations = {}
                validation['issues'].append({'code': 'native_claim_support_unavailable',
                    'message': '解释支持关系未能核验，已保留待核实提示和实际文件。'})
            validation['claimSupport'] = []
            pages: list[dict[str, object]] = []
            chart_assets: dict[str, bytes] = {}
            presented_analyses = set()
            for slide in slide_outline.slides:
                conclusion = present_native_summary(slide.bullets[0], claim_presentations,
                    section_ids=tuple(section.code for section in outline.sections
                        if set(section.analysis_ids).intersection(slide.evidence_ids)),
                    analysis_ids=slide.evidence_ids)
                validation['claimSupport'].append({'slideId': slide.slide_id, 'bulletIndex': 0,
                    'support': conclusion['support']})
                bullets = [conclusion['text'], *slide.bullets[1:]]
                for summary in slide_outline.analysis_summaries:
                    for block in summary.blocks:
                        if block.block_id in presented_analyses or block.block_id not in slide.evidence_ids:
                            continue
                        fragments, cursor = [], 0
                        try:
                            for _, end, text in narrative_paragraphs(block):
                                prefix = block.markdown[cursor:end - len(text)].strip()
                                if prefix:
                                    fragments.append(prefix)
                                fragments.append(text)
                                cursor = end
                            suffix = block.markdown[cursor:].strip()
                            if suffix:
                                fragments.append(suffix)
                        except Exception as error:
                            logger.warning('pptx_narrative_paragraphs_unavailable error_type={}', type(error).__name__)
                            validation['issues'].append({'code': 'pptx_narrative_paragraphs_unavailable',
                                'message': '分析说明逐段展示未能核验，已保留原文和实际文件。'})
                            fragments = [block.markdown]
                        for text in fragments:
                            shown = present_native_summary(text, claim_presentations,
                                section_ids=(summary.section_code,), analysis_ids=(block.block_id,))
                            validation['claimSupport'].append({'slideId': slide.slide_id, 'bulletIndex': len(bullets),
                                'support': shown['support']})
                            bullets.append(shown['text'])
                        presented_analyses.add(block.block_id)
                chart_name = None
                for chart_id in slide.chart_ids:
                    chart = chart_files.get(chart_id)
                    if chart is None or PurePosixPath(chart.path).suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                        continue
                    try:
                        data = await self.workspace_service.read_limited_regular_file(
                            self._scope(run_context)["threadId"], chart.path, max_bytes=chart.size,
                        )
                        if len(data) != chart.size or hashlib.sha256(data).hexdigest() != chart.sha256:
                            raise ValueError("chart identity mismatch")
                    except Exception as error:
                        validation["issues"].append({
                            "code": "pptx_chart_unavailable",
                            "message": "冻结图表无法读取，页面仍保留文字证据。",
                            "details": {"chartId": chart_id, "errorType": type(error).__name__},
                        })
                        continue
                    chart_name = f"{chart_id}{PurePosixPath(chart.path).suffix.lower()}"
                    chart_assets[chart_name] = data
                    break
                pages.append({
                    "title": slide.title,
                    "bullets": bullets,
                    "evidenceIds": [*slide.finding_ids, *slide.evidence_ids],
                    **({"chartPath": chart_name} if chart_name else {}),
                })
            if not pages:
                raise ValueError("no frozen analysis evidence")
            theme = state.get("report_request_context", {}).get("pptxTheme", "executive")

            def build() -> tuple[Any, bytes]:
                # 同步构建器（Node 子进程）在工作线程执行，避免阻塞事件循环；
                # 临时目录由工作线程持有，协程取消时不会删除仍被构建器使用的文件。
                with TemporaryDirectory(prefix="report-pptx-assets-") as temporary:
                    root = Path(temporary)
                    for name, data in chart_assets.items():
                        (root / name).write_bytes(data)
                    local_pptx = root / "report.pptx"
                    built = build_editable_pptx(
                        output_path=local_pptx, title=title, period=str(period), theme=theme,
                        slides=tuple({
                            **page,
                            **({"chartPath": str(root / str(page["chartPath"]))} if page.get("chartPath") else {}),
                        } for page in pages),
                    )
                    return built, local_pptx.read_bytes()

            built, content = await run_office_engine(build)
            if built.issues:
                validation["issues"].extend(
                    {"code": "pptx_layout_audit", "message": str(item.get("message", "版式需要复核。")), "details": {"page": item.get("page")}}
                    for item in built.issues
                )
            await self.workspace_service.awrite_bytes(
                self._scope(run_context)["threadId"], pptx_path, content,
            )
            actual = await self.workspace_service.ahash_file(self._scope(run_context)["threadId"], pptx_path)
            if actual.get("missing") or actual.get("sha256") != built.sha256 or actual.get("size") != built.size:
                raise ValueError("generated pptx identity mismatch")
            validation.update({"ok": not validation["issues"], "slideCount": built.slide_count})
            result.update({
                "status": "validated" if validation["ok"] else "validation_failed",
                "deliveryFormat": "pptx",
                "pptxPath": pptx_path,
                "pptxSize": int(actual["size"]),
                "pptxSha256": str(actual["sha256"]),
                "validation": validation,
                "validationIssues": list(validation["issues"]),
            })
            await self._apply_durable_command(
                run_context,
                ReportingCommand(
                    name="record_artifact",
                    commandId=f"rendered-pptx:{revision}:{actual['sha256']}",
                    payload={"artifact": actual},
                ), **execution_options,
            )
            if execution is not None:
                await self._apply_durable_command(run_context, ReportingCommand(
                    name='complete', commandId=f'revision-pptx-complete:{revision}:{actual["sha256"]}',
                    payload={**durable.payload['result'], 'renderedPptx': dict(result)}), **execution_options)
        except Exception as error:
            logger.warning("report_pptx_generation_failed error_type={}", type(error).__name__)
            validation["issues"].append({"code": "pptx_generation_failed", "message": "PPTX 生成或验收失败。"})
            try:
                actual = await self.workspace_service.ahash_file(self._scope(run_context)["threadId"], pptx_path)
                if not actual.get("missing") and actual.get("sha256") and actual.get("size"):
                    result.update({"pptxPath": pptx_path, "pptxSize": int(actual["size"]), "pptxSha256": str(actual["sha256"])})
            except Exception:
                pass
            result.update({"status": "validation_failed", "deliveryFormat": "pptx", "validation": {**validation, "ok": False}, "validationIssues": list(validation["issues"])})
        if execution is None:
            self._state(run_context)[REPORT_WORKFLOW_RESULT_STATE_KEY] = result
        return result

    async def _draft_workbook(self, run_context: RunContext, *, spec_path: str, output_path: str, execution=None) -> Any:
        from ...code_agent.context import ReportingCodingTaskContext
        from .code_generation import ReportingCodeGenerationRunner

        if self.code_mode_runtime is None:
            raise ReportingError("report_code_mode_runtime_missing", "工作簿汇编 CodeMode runtime 未配置。")
        task_run_id = str(run_context.run_id)
        if execution is not None:
            from ..revision_execution import require_revision_execution

            await require_revision_execution(self, run_context, execution)
            root = PurePosixPath(f'报表/智能分析/{execution.execution_run_id}/workbook/revision-{execution.output_revision}')
            if execution.requested_outputs != ('xlsx',) or any(
                    not PurePosixPath(self.workspace_service.normalize_path(path, allow_root=False)).is_relative_to(root)
                    for path in (spec_path, output_path)):
                raise ReportingError('report_revision_execution_mismatch', '工作簿汇编只能读写本修订声明的目录。')
            task_run_id = execution.execution_run_id
        workspace = self._run_workspace(run_context)
        task_id = f"workbook:{task_run_id}:{hashlib.sha256(output_path.encode()).hexdigest()[:20]}"
        script_path = str(PurePosixPath(output_path).with_suffix(".workbook.py"))
        task = ReportingCodingTaskContext(
            task_id=task_id, task_kind="workbook", code_mode_session_id=task_id,
            workspace_key=workspace.identity.workspace_key, workspace_root=workspace.identity.root,
            script_path=script_path, authorized_read_paths=(spec_path,),
            authorized_write_paths=(script_path, output_path), declared_output_paths=(output_path,),
            max_source_bytes=32 * 1024,
        )
        source = (
            "import json, sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parents[4])!r})\n"
            "from smart_reporting.reporting.delivery.xlsx import build_workbook\n"
            f"spec = json.loads(Path({spec_path!r}).read_text(encoding='utf-8'))\n"
            f"build_workbook(output_path=Path({output_path!r}), title=spec['title'], "
            "period=spec['period'], sheets=tuple(spec['sheets']), source_mapping=spec['sourceMapping'])\n"
        )
        runner = ReportingCodeGenerationRunner(
            self._analysis_script_agent_factory, self.code_mode_runtime,
            lsp_manager=getattr(self, "lsp_manager", None), registry=self.coding_task_registry,
        )
        return await runner.run_workbook(task, workspace, source)

    async def _render_xlsx(self, run_context: RunContext, result: dict[str, Any], outline: Any, *, execution=None) -> dict[str, Any]:
        """只从冻结事实与实际使用的 CSV 汇编；所有后续故障保留已生成文件。"""
        from ...delivery.xlsx import inspect_workbook
        from ..policy_adoption import (
            PolicyAdoptionExecution,
            policy_adoption_run_context,
            require_policy_adoption_execution,
        )

        source_context = run_context
        adoption = isinstance(execution, PolicyAdoptionExecution)
        if adoption:
            durable = await require_policy_adoption_execution(self, source_context, execution)
            run_context = policy_adoption_run_context(execution)
        execution_options = {} if execution is None or adoption else {'execution': execution}
        thread_id = self._scope(run_context)["threadId"]
        if execution is None:
            state = self._state(run_context)
            revision = int(result['revision'])
            period = self._envelope(run_context).period
            period_label = f"{period.start.isoformat()} 至 {period.end.isoformat()}"
            path = str(PurePosixPath(_report_pdf_path(str(run_context.run_id), revision, outline.title, period)).with_suffix(".xlsx"))
        else:
            from ..revision_execution import (
                load_revision_outline,
                prepare_revision_dataset_contexts,
                require_revision_execution,
            )

            revision = int(result.get('revision', 0))
            if not adoption:
                durable = await require_revision_execution(self, run_context, execution, revision=revision)
            if revision != execution.output_revision:
                raise ReportingError('report_revision_execution_mismatch', '工作簿修订号与已登记执行不同。')
            target_run_id = execution.scope.run_id if adoption else execution.execution_run_id
            report_revision = 'initial' if adoption else execution.report_revision
            if execution.requested_outputs != ('xlsx',) or durable.payload.get('deliveryFormat') != 'xlsx':
                raise ReportingError('report_revision_execution_mismatch', '工作簿必须使用本修订冻结格式。')
            # 恢复只接受本修订登记来源，不能把调用方携带的旧结果当成新文件依据。
            result = {key: value for key, value in result.items() if key not in {
                'datasets', 'workbookSources', 'xlsxPath', 'xlsxSize', 'xlsxSha256',
                'validation', 'validationIssues', 'status'}}
            path = f'报表/智能分析/{target_run_id}/workbook/revision-{revision}/report.xlsx'
            registered = {item['path']: FileIdentity.model_validate(item) for item in durable.payload.get('artifacts', ())}
            if path in registered:
                actual = registered[path]
                await self._read_identity_bytes(thread_id, actual, max_bytes=actual.size)
                try:
                    receipt_identity = registered[path + '.receipt.json']
                    saved = json.loads(await self._read_identity_bytes(thread_id, receipt_identity, max_bytes=receipt_identity.size))
                    if (saved.get('execution') != execution.model_dump(mode='json', by_alias=True)
                            or FileIdentity.model_validate(saved['artifact']) != actual
                            or FileIdentity.model_validate(saved['spec']) != registered.get(saved['spec']['path'])):
                        raise ValueError('workbook receipt identity mismatch')
                    spec_identity = FileIdentity.model_validate(saved['spec'])
                    await self._read_identity_bytes(thread_id, spec_identity, max_bytes=spec_identity.size)
                    from ...code_agent.context import ExecutionReceipt

                    receipt = ExecutionReceipt.model_validate(saved['executionReceipt'])
                    if (receipt.source_file != registered.get(receipt.source_file.path)
                            or receipt.output_files != (actual,)):
                        raise ValueError('workbook execution receipt mismatch')
                    await self._read_identity_bytes(thread_id, receipt.source_file, max_bytes=receipt.source_file.size)
                    return {**result, 'deliveryFormat': 'xlsx', 'xlsxPath': path,
                        'xlsxSize': actual.size, 'xlsxSha256': actual.sha256,
                        'validation': saved['validation'], 'validationIssues': saved['validation'].get('issues', []),
                        'workbookSources': saved.get('workbookSources', []),
                        'status': 'validated' if saved['validation'].get('ok') else 'validation_failed'}
                except Exception as error:
                    logger.warning('report_revision_workbook_receipt_unavailable error_type={}', type(error).__name__)
                    issue = {'code': 'xlsx_validation_receipt_unavailable', 'message': '工作簿已恢复，验收或来源记录未获核验，需复核。'}
                    return {**result, 'status': 'validation_failed', 'deliveryFormat': 'xlsx',
                        'xlsxPath': path, 'xlsxSize': actual.size, 'xlsxSha256': actual.sha256,
                        'validation': {'ok': False, 'issues': [issue]}, 'validationIssues': [issue]}
            existing = (await self.workspace_service.abatch_hash_files(thread_id, [path]))[0]
            if not existing.get('missing'):
                raise ReportingError('report_revision_execution_mismatch', '发现未登记工作簿，禁止自动覆盖或重新汇编，需核对实际结果。')
            if adoption:
                from ..policy_adoption_analysis import prepare_policy_adoption_narrative

                run_context = await prepare_policy_adoption_narrative(self, source_context, execution)
                expected_outline = _frozen_outline(self._state(run_context))
            else:
                expected_outline = await load_revision_outline(self, run_context, execution)
            if outline != expected_outline:
                raise ReportingError('report_revision_execution_mismatch', '工作簿必须使用本修订冻结提纲。')
            view = await self._metric_planning_context(run_context, report_revision=report_revision)
            period = view.request.period
            period_label = f'[{period.start.isoformat()}, {period.end.isoformat()})'
            if adoption:
                state = self._state(run_context)
            else:
                contexts = await prepare_revision_dataset_contexts(self, run_context, execution)
                state = {REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY: [item.model_dump(mode='json', by_alias=True) for item in contexts]}
            handles = await self._registered_metric_dataset_handles(run_context, report_revision=report_revision)
            result = {**result, 'datasets': [item.public_dict() for item in handles]}
        receipt_path = str(PurePosixPath(path).with_suffix(".xlsx.receipt.json"))
        validation: dict[str, Any] = {"ok": False, "issues": []}
        try:
            if execution is None:
                durable = await self.state_repository.get(str(run_context.run_id or self._scope(run_context)["externalRunId"]))
            checkpoint = ReportingCheckpoint.model_validate(durable.payload.get("workflowCheckpoint") if durable is not None else None)
            if execution is not None:
                from ..checkpoint import AnalysisArtifact

                identities = (checkpoint.analysis_manifest_file, *checkpoint.deterministic_fact_files.values())
                if any(file is None or registered.get(file.path) != file for file in identities):
                    raise ValueError('workbook analysis evidence not registered')
                artifact = await self._read_identity_model(thread_id, checkpoint.analysis_manifest_file, AnalysisArtifact)
                if artifact.evidence_manifest != checkpoint.evidence_manifest:
                    raise ValueError('workbook frozen evidence mismatch')
            # 与 PDF/Word 一样复用当前 revision 检查点；读取回执前验证其登记身份。
            frozen_receipt = next((item for item in checkpoint.files if item.path == receipt_path), None)
            if execution is None and frozen_receipt is not None:
                raw = await self._read_identity_bytes(thread_id, frozen_receipt, max_bytes=4 * 1024 * 1024)
                saved = json.loads(raw)
                actual = await self.workspace_service.ahash_file(thread_id, path)
                if actual.get("size") == saved["artifact"]["size"] and actual.get("sha256") == saved["artifact"]["sha256"]:
                    result.update({"deliveryFormat": "xlsx", "xlsxPath": path, "xlsxSize": actual["size"], "xlsxSha256": actual["sha256"],
                        "validation": saved["validation"], "validationIssues": saved["validation"].get("issues", []),
                        "workbookSources": saved.get("workbookSources", []),
                        "status": "validated" if saved["validation"].get("ok") else "validation_failed"})
                    state[REPORT_WORKFLOW_RESULT_STATE_KEY] = result
                    return result
            manifest = checkpoint.evidence_manifest
            if manifest is None:
                raise ValueError("frozen analysis evidence unavailable")
            handles = {item.dataset_id: item for item in (DatasetHandle.from_state(raw) for raw in result.get("datasets", ()))}
            used_ids = tuple(dict.fromkeys(key for evidence in manifest.evidence for key in evidence.dataset_ids))
            requirements = {item.requirement_id: item for item in (QueryRequirement.model_validate(raw) for raw in state.get(REPORT_DATA_REQUIREMENTS_STATE_KEY, ()))}
            datasets: dict[str, dict[str, Any]] = {}
            for dataset_id in used_ids:
                handle = handles[dataset_id]
                content = await self.workspace_service.read_limited_regular_file(thread_id, handle.path, max_bytes=handle.size)
                if len(content) != handle.size or hashlib.sha256(content).hexdigest() != handle.sha256:
                    raise ValueError("frozen dataset identity changed")
                requirement = requirements.get(handle.requirement_id)
                measures = {column for table in requirement.tables for column in table.measure_columns} if requirement else set()
                schema = next((item.get("schema", {}) for item in state.get(REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY, ())
                    if item.get("datasetId") == dataset_id and item.get("sha256") == handle.sha256), {})
                columns, rows, type_issues = workbook_dataset_rows(content, dataset_id=dataset_id, measures=measures, schema=schema)
                validation["issues"].extend(type_issues)
                if len(rows) != handle.row_count:
                    raise ValueError("frozen dataset row count changed")
                datasets[dataset_id] = {"columns": columns, "rows": rows, "path": handle.path, "size": handle.size,
                    "sha256": handle.sha256, "periodRoles": list(handle.period_roles), "requirementId": handle.requirement_id}
            documents: dict[str, dict[str, Any]] = {}
            for evidence in manifest.evidence:
                identities = [checkpoint.deterministic_fact_files[evidence.analysis_id]] if evidence.analysis_id in checkpoint.deterministic_fact_files else list(evidence.evidence_files)
                for identity in identities:
                    if not identity.path.lower().endswith(".json"):
                        continue
                    raw = await self._read_identity_bytes(thread_id, identity, max_bytes=identity.size)
                    document = read_fact_document(raw)
                    if document.get("analysisId") == evidence.analysis_id:
                        documents[evidence.analysis_id] = dict(document)
                        break
                if evidence.analysis_id not in documents:
                    validation["issues"].append({"code": "xlsx_fact_values_unavailable", "message": "部分分析未登记结构化数值，工作簿保留结论与明细，不从正文反推指标。", "analysisId": evidence.analysis_id})
            try:
                claim_presentations = await self._native_claim_presentations(run_context, execution=execution)
            except Exception as error:
                logger.warning('report_native_claim_support_unavailable format=xlsx error_type={}', type(error).__name__)
                claim_presentations = {}
                validation['issues'].append({'code': 'native_claim_support_unavailable',
                    'message': '解释支持关系未能核验，已保留待核实提示和实际文件。'})
            sheets, sources = build_workbook_sheets(manifest=manifest, outline=outline,
                fact_documents=documents, datasets=datasets, period=period_label, claim_presentations=claim_presentations)
            validation['claimSupport'] = sources['claims']
            workbook_sources = [{**item, "datasets": {key: sources["datasets"][key] for key in item["datasetIds"] if key in sources["datasets"]}} for item in sources["cells"]]
            spec = json.dumps({"title": outline.title, "period": period_label, "sheets": sheets, "sourceMapping": sources}, ensure_ascii=False, allow_nan=False).encode()
            spec_path = str(PurePosixPath(path).parent / f"workbook-spec-{hashlib.sha256(spec).hexdigest()}.json")
            spec_identity = await self._write_immutable_artifact(thread_id, spec_path, spec)
            generated = await self._draft_workbook(run_context, spec_path=spec_path, output_path=path, **execution_options)
            actual = await self.workspace_service.ahash_file(thread_id, path)
            output = next(item for item in generated.execution_receipt.output_files if item.path == path)
            if actual.get("missing") or actual.get("sha256") != output.sha256 or actual.get("size") != output.size:
                raise ValueError("generated workbook identity mismatch")
            content = await self.workspace_service.read_limited_regular_file(thread_id, path, max_bytes=output.size)
            inspected = await run_office_engine(inspect_workbook, content)
            validation["issues"].extend(validate_workbook_snapshot(inspected, sheets, sources, content))
            actual_sheets = inspected.get("sheets", inspected.get("worksheets", []))
            if len(actual_sheets) != len(sheets):
                validation["issues"].append({"code": "xlsx_sheet_count_invalid", "message": "工作表数量与冻结工作簿计划不一致。"})
            validation.update({"ok": not validation["issues"], "sheetCount": len(actual_sheets)})
            result.update({"status": "validated" if validation["ok"] else "validation_failed", "deliveryFormat": "xlsx",
                "xlsxPath": path, "xlsxSize": actual["size"], "xlsxSha256": actual["sha256"],
                "validation": validation, "validationIssues": list(validation["issues"]), "workbookSources": workbook_sources})
            receipt_data = json.dumps({"artifact": actual, "spec": spec_identity.model_dump(mode="json", by_alias=True),
                "executionReceipt": generated.execution_receipt.model_dump(mode="json", by_alias=True), "validation": validation, "workbookSources": workbook_sources,
                **({'execution': execution.model_dump(mode='json', by_alias=True)} if execution is not None else {})}, ensure_ascii=False).encode()
            receipt_identity = await self._write_immutable_artifact(thread_id, receipt_path, receipt_data)
            if execution is None:
                await self._apply_durable_command(run_context, ReportingCommand(name="record_artifact",
                    commandId=f"rendered-xlsx:{revision}:{actual['sha256']}", payload={"artifact": actual}))
            else:
                for file in (spec_identity, generated.script_file, output, receipt_identity):
                    await self._apply_durable_command(run_context, ReportingCommand(name='record_artifact',
                        commandId=f'revision-workbook:{hashlib.sha256(file.path.encode()).hexdigest()}:{file.sha256}',
                        payload={'artifact': file.model_dump(mode='json', by_alias=True)}), **execution_options)
            files = self._merge_checkpoint_files(checkpoint.files, spec_identity, receipt_identity, generated.script_file, output)
            await self._persist_reporting_checkpoint(run_context, checkpoint.model_copy(update={"files": files}), **execution_options)
        except Exception as error:
            logger.warning("report_xlsx_generation_failed error_type={}", type(error).__name__)
            validation["issues"].append({"code": "xlsx_generation_failed", "message": "工作簿汇编、验收或检查点登记未完成，实际已生成文件仍可下载。", "details": {"errorType": type(error).__name__}})
            try:
                actual = await self.workspace_service.ahash_file(thread_id, path)
                if not actual.get("missing") and actual.get("size") and actual.get("sha256"):
                    result.update({"xlsxPath": path, "xlsxSize": actual["size"], "xlsxSha256": actual["sha256"]})
            except Exception:
                pass
            result.update({"status": "validation_failed", "deliveryFormat": "xlsx", "validation": {**validation, "ok": False}, "validationIssues": list(validation["issues"])})
        if execution is None:
            state[REPORT_WORKFLOW_RESULT_STATE_KEY] = result
        return result

    async def _source_links_by_dataset(
        self,
        manifest: ReportArtifactManifest,
        run_context: RunContext,
    ) -> dict[str, list[dict[str, str]]]:
        """从冻结 trace index 生成 report/revision/subject 在线定位链接。"""

        identity = manifest.trace_index
        base_url = self.report_public_base_url
        if identity is None or not isinstance(base_url, str) or not base_url:
            return {}
        thread_id = self._scope(run_context)["threadId"]
        raw_index = await self.workspace_service.read_limited_regular_file(
            thread_id, identity.path, max_bytes=max(identity.size, 4 * 1024 * 1024)
        )
        if (
            len(raw_index) != identity.size
            or hashlib.sha256(raw_index).hexdigest() != identity.sha256
        ):
            raise ReportingError(
                "snapshot_integrity_failed", "来源附录引用的追溯索引身份不一致。"
            )
        try:
            index = RevisionTraceIndexV1.model_validate_json(raw_index)
        except ValueError as error:
            raise ReportingError(
                "snapshot_integrity_failed", "来源附录引用的追溯索引无法解析。"
            ) from error
        files = {item.resource_id: item for item in index.files}
        documents: dict[str, Mapping[str, Any] | None] = {}
        links: dict[str, list[dict[str, str]]] = {}
        kind_labels = {
            "text_claim": "正文结论",
            "table_cell": "表格单元格",
            "chart": "图表",
            "chart_caption": "图表说明",
        }
        for subject in index.subject_bindings:
            dataset_ids: set[str] = set()
            for fact_ref in subject.fact_refs:
                file = files.get(fact_ref.file_resource_id)
                if file is None:
                    continue
                if file.resource_id not in documents:
                    raw = await self.workspace_service.read_limited_regular_file(
                        thread_id, file.path, max_bytes=16 * 1024 * 1024
                    )
                    if (
                        len(raw) != file.size
                        or hashlib.sha256(raw).hexdigest() != file.sha256
                    ):
                        raise ReportingError(
                            "snapshot_integrity_failed",
                            "来源附录引用的事实文件身份不一致。",
                        )
                    try:
                        documents[file.resource_id] = read_fact_document(raw)
                    except ReportingError:
                        documents[file.resource_id] = None
                document = documents[file.resource_id]
                if document is None:
                    continue
                try:
                    resolved = resolve_fact_from_document(document, fact_ref, with_inputs=False)
                except ReportingError:
                    continue
                dataset_id = resolved["entry"].get("datasetId")
                if isinstance(dataset_id, str):
                    dataset_ids.add(dataset_id)
            if not dataset_ids:
                continue
            path = f"/reports/v1/editor/{quote(index.report_id, safe='')}/{index.revision}"
            link = {
                "subjectId": subject.subject_id,
                "label": kind_labels[subject.subject_kind],
                "url": (
                    f"{base_url.rstrip('/')}{path}?"
                    f"{urlencode({'subject': subject.subject_id})}"
                ),
            }
            for dataset_id in sorted(dataset_ids):
                links.setdefault(dataset_id, []).append(link)
        return links

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

        audit_complete = True

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
            warnings.extend(
                warning for warning in checkpoint.warnings
                if warning.get("code") == "chart_caption_numeric_review"
            )
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
                from .business_evidence import revalidate_section_knowledge

                try:
                    current_section = await revalidate_section_knowledge(
                        self, run_context, stored_section,
                        report_revision=str(checkpoint.revision),
                    )
                except Exception as error:  # 知识核验失败不阻断已生成文件签发
                    logger.warning("publication_section_knowledge_unavailable reason={}", type(error).__name__)
                    warning = {
                        "code": "report_section_knowledge_unavailable",
                        "message": "发布前无法核验章节知识依据，相关解释未获确认；已有文件仍可下载。",
                        "sectionCode": stored_section.section_code,
                    }
                    warnings.append(warning)
                    issue(warning["code"], warning["message"], sectionCode=stored_section.section_code)
                    # 不把旧 claims 交给后续语义验收。
                    continue
                if current_section.knowledge_status in {"partial", "unavailable"}:
                    issue(
                        "report_section_knowledge_unavailable",
                        "发布前章节知识依据已撤销或不可核验，已有文件可能包含旧解释，仍可下载。",
                        sectionCode=current_section.section_code,
                    )
                parsed_section_artifacts.append(
                    SectionArtifact.model_validate(
                        current_section.model_dump(mode="json", by_alias=True)
                    )
                )
            section_artifacts = tuple(parsed_section_artifacts)
            if checkpoint.finding_graph_file is not None and checkpoint.narrative_outline_file is not None:
                graph = await self._read_identity_model(
                    thread_id, checkpoint.finding_graph_file, FindingGraph
                )
                narrative = await self._read_identity_model(
                    thread_id, checkpoint.narrative_outline_file, NarrativeOutline
                )
                issues[:] = _without_verified_analysis_reuse(
                    issues,
                    graph=graph,
                    narrative=narrative,
                    outline=outline,
                    finding_graph_hash=checkpoint.finding_graph_hash,
                )
                warnings.extend(
                    narrative_quality_warnings(
                        graph,
                        narrative,
                        tuple(item.section_code for item in checkpoint.completed_sections),
                    )
                )
            claim_fact_issues, claim_fact_warnings = await self._verify_claim_fact_bindings(
                thread_id, checkpoint, section_artifacts
            )
            issues.extend(claim_fact_issues)
            warnings.extend(claim_fact_warnings)
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
            # 分析/语义/章节告警未能收集时，本次审计不完整，不能关闭既有告警。
            audit_complete = False
            issue("analysis_checkpoint_invalid", "发布门禁无法核验冻结分析产物。")

        delivery_format = result.get(
            "deliveryFormat", self._state(run_context).get("report_request_context", {}).get("deliveryFormat", "document")
        )
        if result.get("status") != "validated":
            artifact_label = delivery_format.upper() if delivery_format in {"pptx", "xlsx"} else "PDF 或 DOCX"
            issue(
                "artifact_not_validated",
                f"Markdown、{artifact_label} 尚未完成验收。",
                validationIssues=result.get("validationIssues", [])[:20],
            )
        artifact_paths = (
            ("markdownPath", f"{delivery_format}Path")
            if delivery_format in {"pptx", "xlsx"}
            else ("markdownPath", "pdfPath", "wordPath")
        )
        for key in artifact_paths:
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
        quality_warning_service = getattr(self, "quality_warning_service", None)
        tenant = None
        if quality_warning_service is not None:
            scope = self._scope(run_context)
            tenant = TenantScope(
                database_name=scope["database"], company_id=str(scope["companyId"])
            )
        try:
            invalid_notice_count = await _record_publication_audit(
                audit,
                warnings,
                service=quality_warning_service,
                tenant=tenant,
                complete=audit_complete,
            )
        except Exception as error:
            # 审计写入失败与其他门禁问题一样记为 issue；保留已收集的问题和告警，
            # 不用 raise 把整个门禁替换成一条笼统问题（AGENTS.md 非阻断要求）。
            logger.warning(
                "report_quality_audit_write_failed error_type={}", type(error).__name__
            )
            invalid_notice_count = 0
            issue("report_quality_audit_failed", "发布质量告警审计写入失败，已有产物仍可下载。")
        audit_summary = audit.build().as_dict()
        if invalid_notice_count:
            audit_summary["invalidNoticeCount"] = invalid_notice_count
        return {
            "formalReleaseAllowed": not issues,
            "issues": issues,
            "warnings": warnings,
            "auditSummary": audit_summary,
        }

    async def _publish_revision_report(self, run_context: RunContext, execution) -> StepOutput:
        """从已登记子执行恢复发布输入；不借用原会话，也不重新渲染。"""
        from ..policy_adoption import PolicyAdoptionExecution, require_policy_adoption_execution
        from ..revision_execution import require_revision_execution

        adoption = isinstance(execution, PolicyAdoptionExecution)
        if adoption:
            durable = await require_policy_adoption_execution(self, run_context, execution)
            self.workspace_service.registry.resolve(execution.scope)
            execution_run_id = execution.scope.run_id
            report_id = execution.scope.run_id
            thread_id = execution.scope.workspace_key
        else:
            durable = await require_revision_execution(self, run_context, execution)
            execution_run_id = execution.execution_run_id
            report_id = execution.source_scope.run_id
            thread_id = execution.source_scope.workspace_key
        delivery = durable.payload.get('deliveryFormat')
        if delivery not in {'document', 'pptx', 'xlsx'}:
            raise ReportingError('report_revision_publication_unavailable', '本修订格式尚未完成正式交付登记。')
        root = f'报表/智能分析/{execution_run_id}'
        expected = ({'pdf': f'{root}/document-render/revision-{execution.output_revision}/report.pdf',
            'docx': f'{root}/document-render/revision-{execution.output_revision}/report.docx'}
            if delivery == 'document' else {delivery: f'{root}/{"slides" if delivery == "pptx" else "workbook"}/revision-{execution.output_revision}/report.{delivery}'})
        registered = {item['path']: FileIdentity.model_validate(item) for item in durable.payload.get('artifacts', ())}
        if not any(expected[output] in registered for output in execution.requested_outputs):
            raise ReportingError('report_artifact_unavailable', '本修订尚无可恢复的已登记交付文件，发布不会自动启动渲染。')
        rendered = (await self._render_and_validate(run_context, execution=execution) if delivery == 'document'
            else await (self._render_pptx if delivery == 'pptx' else self._render_xlsx)(
                run_context, {'revision': execution.output_revision}, None, execution=execution))
        issues = [{'code': 'revision_publication_review_incomplete',
            'message': '新修订业务发布核对尚未完成，已生成文件仍可下载；不表示业务验收通过。'}]
        content = {**rendered, 'reportId': report_id,
            'revision': execution.output_revision, 'deliveryFormat': delivery,
            'jobId': rendered.get('jobId', execution_run_id),
            'editorJob': {'jobId': rendered.get('jobId', execution_run_id)},
            'editorAvailable': False, 'reportTitle': '新修订报告',
            'markdownPath': f'{root}/unavailable.md', 'sourceWarnings': [], 'codingReceipts': []}
        manifest = None
        try:
            identity = FileIdentity.model_validate(durable.payload['result']['manifest'])
            if registered.get(identity.path) != identity:
                raise ValueError('revision manifest registration mismatch')
            manifest = await self._read_identity_model(thread_id, identity, ReportArtifactManifest)
            if (manifest.report_id != report_id or manifest.revision != execution.output_revision
                    or manifest.report_basis_id != execution.basis_id):
                raise ValueError('revision manifest ownership mismatch')
            markdown = FileIdentity(path=manifest.markdown.path, size=manifest.markdown.size, sha256=manifest.markdown.sha256)
            if registered.get(markdown.path) != markdown:
                raise ValueError('revision markdown registration mismatch')
            data = await self._read_identity_bytes(thread_id, markdown)
            content.update({'artifactManifest': {**identity.model_dump(mode='json', by_alias=True), 'mediaType': 'application/json'},
                'artifactManifestPath': identity.path, 'markdownPath': markdown.path,
                'reportTitle': data.decode('utf-8').splitlines()[0].lstrip('# ').strip() or '新修订报告'})
        except Exception as error:
            logger.warning('revision_publication_manifest_unavailable error_type={}', type(error).__name__)
            issues.append({'code': 'revision_publication_manifest_unavailable',
                'message': '新修订来源清单或正文身份无法核验，未提供编辑与追溯；实际文件仍可下载。'})
        if content.get('artifactManifest'):
            try:
                if delivery == 'document':
                    job_path = f'{root}/document-render/revision-{execution.output_revision}.job.json'
                    job_file = registered[job_path]
                    saved = json.loads(await self._read_identity_bytes(thread_id, job_file))
                    if (saved['execution'] != execution.model_dump(mode='json', by_alias=True)
                            or FileIdentity.model_validate(saved['manifest']) != identity
                            or saved['job']['jobId'] != rendered['jobId']):
                        raise ValueError('revision document job mismatch')
                    job = saved['job']
                    job['render'] = {'markdown': manifest.markdown.model_dump(mode='json', by_alias=True),
                        **{label: {'path': rendered[f'{label}Path'], 'size': rendered[f'{label}Size'],
                            'sha256': rendered[f'{label}Sha256']} for label in ('pdf', 'word') if rendered.get(f'{label}Path')}}
                else:
                    job = {'jobId': content['jobId'], 'sources': [], 'render': {
                        'markdown': manifest.markdown.model_dump(mode='json', by_alias=True)}}
                    if delivery == 'xlsx':
                        if not isinstance(rendered.get('workbookSources'), list):
                            raise ValueError('workbook source receipt unavailable')
                        job['workbookSources'] = rendered['workbookSources']
                if adoption:
                    from ...trace.contracts_v1 import canonical_sha256
                    from ..policy_adoption_analysis import PolicyAdoptionAnalysis

                    preparation = await self._read_identity_model(thread_id,
                        registered[f'{root}/policy-adoption/analysis-preparation.json'], PolicyAdoptionAnalysis)
                    if preparation.execution_sha256 != canonical_sha256(execution.model_dump(mode='json', by_alias=True)):
                        raise ValueError('policy adoption analysis preparation mismatch')
                    context_file = preparation.context_file
                    if registered.get(context_file.path) != context_file:
                        raise ValueError('policy adoption analysis context not registered')
                else:
                    context_path = (f'报表/智能分析/{execution.source_scope.run_id}/revision-executions/'
                        f'{execution_run_id}/dataset-contexts.json')
                    context_file = registered[context_path]
                await self._read_identity_bytes(thread_id, context_file)
                content.update({'editorJob': job, 'editorAvailable': True,
                    'analysisContextFile': context_file.model_dump(mode='json', by_alias=True)})
            except Exception as error:
                logger.warning('revision_publication_editor_job_unavailable error_type={}', type(error).__name__)
                issues.append({'code': 'revision_publication_editor_job_unavailable',
                    'message': '新修订编辑任务身份无法核验，暂不提供编辑入口；实际文件仍可下载。'})
        content.update({'formalReleaseAllowed': False,
            'publicationGate': {'formalReleaseAllowed': False, 'issues': issues, 'warnings': []}})
        return StepOutput(content=content)

    async def publish_report(self, step_input: StepInput, run_context: RunContext, *, execution=None) -> StepOutput:
        if execution is not None:
            return await self._publish_revision_report(run_context, execution)
        feedback = self._feedback(step_input)
        if feedback:
            # 反馈恢复沿用已冻结的交付分支，不让 PPT 进入文档成稿。
            if self._state(run_context).get("report_request_context", {}).get("deliveryFormat") == "pptx":
                await self.generate_slide_outline(step_input, run_context)
                await self.assemble_slides(step_input, run_context)
            else:
                await self.run_reporting_analysis(step_input, run_context)
            await self._render_and_validate(run_context)
        result = self._workflow_result(self._state(run_context))
        state = self._state(run_context)
        # AGENTS：产物清单核验失败属于发布门禁问题，不得阻止已生成 PDF/Word 的签发。
        # 失败时不使用该清单（本修订不带溯源与交互图），照常继续并在门禁中返回原因；
        # 与 issue_http_publication 的 _drop_lineage 口径一致。
        manifest_issues: list[dict[str, str]] = []
        manifest: ReportArtifactManifest | None
        try:
            manifest = ReportArtifactManifest.model_validate(
                state[REPORT_ARTIFACTS_STATE_KEY]["draft"]
            )
        except Exception as error:
            logger.warning(
                "report_publication_manifest_dropped code=report_artifact_manifest_invalid "
                "error_type={}",
                type(error).__name__,
            )
            manifest = None
            manifest_issues.append({
                "code": "report_artifact_manifest_invalid",
                "message": "发布门禁缺少已验收的产物清单，本修订不提供来源追溯；已有产物仍可下载。",
            })
        try:
            gate = await self._dataset_publication_gate(run_context, result)
        except Exception as error:
            logger.warning("report_publication_gate_failed error_type={}", type(error).__name__)
            gate = {
                "formalReleaseAllowed": False,
                "issues": [{
                    "code": error.code if isinstance(error, ReportingError) else "report_publication_gate_failed",
                    "message": error.message if isinstance(error, ReportingError) else "发布验收无法完成，已有产物仍可下载。",
                }],
                "warnings": [],
            }
        manifest_identity = None
        if result.get("artifactManifest") is not None:
            try:
                manifest_identity = ArtifactFile.model_validate(result["artifactManifest"])
                content_bytes = await self.workspace_service.read_limited_regular_file(
                    self._scope(run_context)["threadId"],
                    manifest_identity.path,
                    max_bytes=manifest_identity.size,
                )
                if (
                    manifest is None
                    or len(content_bytes) != manifest_identity.size
                    or hashlib.sha256(content_bytes).hexdigest() != manifest_identity.sha256
                    or ReportArtifactManifest.model_validate_json(content_bytes) != manifest
                    or manifest.markdown.path != result["markdownPath"]
                    or manifest.report_id != str(run_context.run_id)
                    or manifest.revision != result.get("revision")
                ):
                    raise ReportingError(
                        "report_artifact_manifest_changed", "已验收报告产物清单发生变化。"
                    )
            except Exception as error:
                code = (
                    error.code if isinstance(error, ReportingError)
                    else "report_artifact_manifest_changed"
                )
                logger.warning(
                    "report_publication_manifest_dropped code={} error_type={}",
                    code,
                    type(error).__name__,
                )
                manifest_identity = None
                manifest = None
                manifest_issues.append({
                    "code": code,
                    "message": "报告产物清单核验未通过，本修订不提供来源追溯；已有产物仍可下载。",
                })
        elif result.get("artifactManifestPath") is not None:
            manifest = None
            manifest_issues.append({
                "code": "report_artifact_manifest_invalid",
                "message": "报告产物清单缺少已验收身份，本修订不提供来源追溯；已有产物仍可下载。",
            })
        if manifest_issues:
            gate = {
                **gate,
                "formalReleaseAllowed": False,
                "issues": [*gate.get("issues", []), *manifest_issues],
            }
        # 同一会话的历史修订告警不能带进本次发布：只取本修订的质量问题（无修订号的沿用）。
        quality_issues = [
            item for item in self._state(run_context).get("report_quality_issues", [])
            if not isinstance(item, dict) or item.get("revision") in {None, result.get("revision")}
        ]
        if quality_issues:
            gate = {**gate, "warnings": [*gate.get("warnings", []), *quality_issues]}
        editor_job = self.report_tools._load_job(
            str(result["jobId"]), self._tool_context(run_context)
        )
        if result.get("deliveryFormat") == "xlsx":
            editor_job = {**editor_job, "workbookSources": result.get("workbookSources", [])}
        return StepOutput(
            content={
                "status": result.get("status", "validated"),
                "formalReleaseAllowed": gate["formalReleaseAllowed"],
                "publicationGate": gate,
                "auditSummary": gate.get("auditSummary", {}),
                "jobId": result["jobId"],
                "editorJob": editor_job,
                "reportId": str(run_context.run_id),
                "reportTitle": _frozen_outline(state).title,
                "deliveryFormat": state.get("report_request_context", {}).get("deliveryFormat", "document"),
                "revision": (
                    manifest.revision if manifest is not None else
                    int(result.get("revision", 1))
                    if state.get("report_request_context", {}).get("deliveryFormat") in {"pptx", "xlsx"}
                    else int(result.get("revision", 0)) + 1
                ),
                "markdownPath": result["markdownPath"],
                **(
                    {
                        "artifactManifestPath": manifest_identity.path,
                        "artifactManifest": manifest_identity.model_dump(
                            mode="json", by_alias=True
                        ),
                    }
                    if manifest_identity is not None else {}
                ),
                **{key: result[key] for label in ("pdf", "word", "pptx", "xlsx") for suffix in ("Path", "Size", "Sha256")
                   if (key := f"{label}{suffix}") in result},
                "validation": result.get("validation", {"ok": False, "issues": []}),
                "validationIssues": result.get("validationIssues", []),
                "sourceWarnings": result.get("sourceWarnings", []),
                "codingReceipts": result.get("codingReceipts", []),
            }
        )

    async def _verify_claim_fact_bindings(
        self,
        thread_id: str,
        checkpoint: ReportingCheckpoint,
        section_artifacts: tuple[SectionArtifact, ...],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """核对 claim.factIds 是否存在于冻结事实或正式计算，异常写入验收原因。

        SectionClaim 未绑定数值选择器，不能将其 value 与事实的 total/change
        猜测比较；基期、月均和单月均可能引用同一事实。正文数值由已有的
        NumberReference 精确选择器重算与绑定状态检查负责，本检查不签发数值
        已核验状态；缺少引用的正文保留原有未核验状态。验收失败不阻断下载。
        """

        issues: list[dict[str, Any]] = []
        warnings_out: list[dict[str, Any]] = []
        bundles_with_claims = any(
            claim.fact_ids for artifact in section_artifacts for claim in artifact.claims
        )
        if not bundles_with_claims:
            return issues, warnings_out
        fact_ids: dict[str, dict[str, Any]] = {}
        for analysis_id, identity in checkpoint.deterministic_fact_files.items():
            try:
                raw = await self._read_identity_bytes(thread_id, identity, max_bytes=16 * 1024 * 1024)
                document = read_fact_document(raw)
                document_facts = {}
                context = document.get("metricContext")
                if context is not None:
                    for calculation in context["calculations"]:
                        for entry in calculation["results"]:
                            document_facts[entry["factId"]] = entry
                for array_name in ("metrics", "breakdowns", "derivedMetrics", "comparisons", "reconciliations"):
                    for entry in document.get(array_name, ()) or ():
                        fact_id = entry.get("factId") if isinstance(entry, dict) else None
                        if isinstance(fact_id, str):
                            document_facts[fact_id] = entry
            except Exception:
                issues.append(
                    {
                        "code": "report_claim_fact_file_unreadable",
                        "message": "发布门禁无法读取冻结事实文件。",
                        "details": {"analysisId": analysis_id},
                    }
                )
                continue
            fact_ids.update(document_facts)
        for artifact in section_artifacts:
            for claim in artifact.claims:
                for fact_id in claim.fact_ids:
                    entry = fact_ids.get(fact_id)
                    if entry is None:
                        issues.append(
                            {
                                "code": "report_claim_fact_unknown",
                                "message": "章节 claim 引用了冻结事实中不存在的事实 ID。",
                                "details": {
                                    "sectionCode": artifact.section_code,
                                    "claimId": claim.claim_id,
                                    "factId": fact_id,
                                },
                            }
                        )
                        continue
        return issues, warnings_out

    async def _build_and_write_artifact_manifest(
        self,
        manifest_path: str,
        *,
        accepted_artifacts: list[dict[str, Any]],
        handles: tuple[DatasetHandle, ...] = (),
        fact_files: Mapping[str, ArtifactFile] | None = None,
        server_table_traces: tuple = (),
        chart_trace_files: tuple[FileIdentity, ...] = (),
        chart_traces: tuple = (),
        computation_files: tuple[FileIdentity, ...] = (),
        computations: tuple = (),
        table_source_files: tuple[FileIdentity, ...] = (),
        subject_bindings: tuple = (),
        review_notices: tuple | None = None,
        markdown_path: str,
        lineage: tuple[DatasetLineage, ...],
        revision: int,
        task_key: str,
        section_numbers: tuple[str, ...],
        heading_numbers: tuple[HeadingNumber, ...],
        run_context: RunContext,
        source_warnings: tuple[SourceWarning, ...] = (),
        section_finding_ids: Mapping[str, tuple[str, ...]] | None = None,
        section_grouping_reasons: Mapping[str, str] | None = None,
        execution=None,
    ) -> ReportArtifactManifest:
        scope = self._scope(run_context)
        execution_options = {} if execution is None else {'execution': execution}
        if execution is not None:
            from ..revision_execution import load_revision_outline, require_revision_execution

            child = await require_revision_execution(self, run_context, execution, revision=revision)
            output_root = f'报表/智能分析/{execution.execution_run_id}/'
            if any(not self.workspace_service.normalize_path(path, allow_root=False).startswith(output_root)
                    for path in (manifest_path, markdown_path)):
                raise ReportingError('report_revision_execution_mismatch', '新修订清单不得写入原报告或其他执行目录。')
            checkpoint = ReportingCheckpoint.model_validate(child.payload['workflowCheckpoint'])
            expected_handles = await self._registered_metric_dataset_handles(run_context, report_revision=execution.report_revision)
            expected_lineage = tuple(DatasetLineage(datasetId=item.dataset_id, sourceId=item.source_id,
                requirementId=item.requirement_id, sqlHash=item.sql_hash, rowCount=item.row_count,
                size=item.size, sha256=item.sha256, periodRoles=item.period_roles, queryWindowId=item.query_window_id)
                for item in expected_handles)
            if (handles != expected_handles or lineage != expected_lineage
                    or {key: (item.path, item.size, item.sha256) for key, item in (fact_files or {}).items()}
                    != {key: (item.path, item.size, item.sha256) for key, item in checkpoint.deterministic_fact_files.items()}):
                raise ReportingError('report_revision_execution_mismatch', '新修订清单必须使用完整登记的数据集和事实。')
            source_outline = await load_revision_outline(self, run_context, execution)
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
        _relative = self.workspace_service.normalize_path(
            markdown_path, allow_root=False
        )
        manifest_relative = self.workspace_service.normalize_path(
            manifest_path, allow_root=False
        )
        try:
            markdown_bytes = await self.workspace_service.read_limited_regular_file(
                scope["threadId"], markdown_path, max_bytes=10 * 1024 * 1024
            )
            if len(markdown_bytes) != accepted.get("size") or hashlib.sha256(
                markdown_bytes
            ).hexdigest() != accepted.get("sha256"):
                raise ReportingError(
                    "report_artifact_file_changed",
                    "报告 Markdown 在正式验收后发生变化。",
                )
            if execution is None:
                basis_id = (await self._basis_execution_context(run_context)).basis.id
                source_outline = _frozen_outline(self._state(run_context))
            else:
                view = await self._metric_planning_context(run_context, report_revision=execution.report_revision)
                basis_id = view.basis_id
            trace_index_file = None
            if getattr(self, "trace_registration_enabled", True):
                trace_index_file = await self._write_trace_index(
                    manifest_relative,
                    report_basis_id=basis_id,
                    handles=handles,
                    lineage=lineage,
                    markdown_artifact=ArtifactFile(
                        path=markdown_path,
                        mediaType="text/markdown",
                        size=accepted["size"],
                        sha256=accepted["sha256"],
                    ),
                    fact_files=fact_files,
                    server_table_traces=server_table_traces,
                    chart_trace_files=chart_trace_files,
                    chart_traces=chart_traces,
                    computation_files=computation_files,
                    computations=computations,
                    table_source_files=table_source_files,
                    subject_bindings=subject_bindings,
                    review_notices=review_notices,
                    markdown=markdown_bytes.decode("utf-8"),
                    heading_numbers=heading_numbers,
                    revision=revision,
                    run_context=run_context,
                    **execution_options,
                )
            manifest = build_authoritative_manifest(
                report_id=str(run_context.run_id),
                revision=revision,
                task_key=task_key,
                report_basis_id=basis_id,
                markdown_path=markdown_path,
                markdown=markdown_bytes.decode("utf-8"),
                accepted_artifacts=current_artifacts,
                lineage=lineage,
                sections=tuple(
                    section.code for section in source_outline.sections
                ),
                section_finding_ids=section_finding_ids,
                section_grouping_reasons=section_grouping_reasons,
                section_numbers=section_numbers,
                heading_numbers=heading_numbers,
                source_warnings=source_warnings,
                trace_index=trace_index_file,
            )
            content = json.dumps(
                manifest.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            self.workspace_service.validate_content(content)
            await self.workspace_service.awrite_bytes(
                scope["threadId"], manifest_relative, content, overwrite=True
            )
            stored = await self.workspace_service.read_limited_regular_file(
                scope["threadId"], manifest_relative, max_bytes=len(content)
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

    async def _write_trace_index(
        self,
        manifest_relative: str,
        *,
        report_basis_id: str,
        handles: tuple[DatasetHandle, ...],
        lineage: tuple[DatasetLineage, ...],
        markdown_artifact: ArtifactFile,
        revision: int,
        run_context: RunContext,
        fact_files: Mapping[str, ArtifactFile] | None = None,
        server_table_traces: tuple = (),
        chart_trace_files: tuple[FileIdentity, ...] = (),
        chart_traces: tuple = (),
        computation_files: tuple[FileIdentity, ...] = (),
        computations: tuple = (),
        table_source_files: tuple[FileIdentity, ...] = (),
        subject_bindings: tuple = (),
        review_notices: tuple | None = None,
        markdown: str | None = None,
        heading_numbers: tuple[HeadingNumber, ...] = (),
        execution=None,
    ) -> ArtifactFile:
        """构建并写入 revision 追溯索引，返回供权威清单登记的产物身份。

        句柄缺失或与血缘不一致时失败关闭，不生成半份索引；索引内容为
        canonical JSON，写入后回读校验（与清单同一模式）。
        """

        scope = self._scope(run_context)
        run_id = str(run_context.run_id or scope["externalRunId"])
        execution_options = {} if execution is None else {'execution': execution}
        if execution is None:
            quality_state = {}
            durable_run_id = run_id
        else:
            from ..revision_execution import require_revision_execution

            await require_revision_execution(self, run_context, execution, revision=revision)
            if report_basis_id != execution.basis_id:
                raise ReportingError('report_revision_execution_mismatch', '追溯计算依据与新执行不同。')
            durable_run_id = execution.execution_run_id
            quality_state = {'report_quality_issues': []}
        drilldown_metrics = await self._build_drilldown_metrics(
            fact_files=fact_files or {}, run_context=run_context, **execution_options
        )
        from .business_evidence import register_section_knowledge

        knowledge_dependencies, knowledge_registration_status = await register_section_knowledge(
            self, run_context, basis_id=report_basis_id, **execution_options)
        def build(computation_files: tuple[FileIdentity, ...], computations: tuple) -> Any:
            return build_csv_trace_index(
                handles=handles,
                lineage=lineage,
                report_id=run_id,
                revision=revision,
                workflow_run_id=run_id,
                markdown_file=markdown_artifact,
                report_basis_id=report_basis_id,
                fact_files=fact_files,
                server_table_traces=server_table_traces,
                chart_trace_files=chart_trace_files,
                chart_traces=chart_traces,
                computation_files=computation_files,
                computations=computations,
                table_source_files=table_source_files,
                subject_bindings=subject_bindings,
                review_notices=review_notices,
                drilldown_metrics=drilldown_metrics,
                knowledge_dependencies=knowledge_dependencies,
                knowledge_registration_status=knowledge_registration_status,
            )

        index = build_with_optional_computation_layer(build, computation_files, computations)
        if markdown is not None:
            from ...trace.chart_subjects import freeze_chart_presentations

            encoded_markdown = markdown.encode("utf-8")
            if len(encoded_markdown) != markdown_artifact.size or hashlib.sha256(encoded_markdown).hexdigest() != markdown_artifact.sha256:
                raise ReportingError("report_trace_index_invalid", "图注基线与已验收正文身份不一致。")
            index = freeze_chart_presentations(index, markdown)
            # Register a versioned shadow record through the existing file
            # channel; old strict manifest/index shapes remain unchanged.
            try:
                if execution is None:
                    quality_state = self._state(run_context)
                quality_state["report_quality_issues"] = [
                    item for item in quality_state.get("report_quality_issues", [])
                    if item.get("revision") != revision
                ]
                from functools import partial

                import anyio

                from ...trace.chart_quality import QUALITY_IMAGE_BYTE_BUDGET
                from ...trace.contracts_v1 import (
                    TraceFileRefV1,
                    canonical_json_bytes,
                    canonical_sha256,
                    derive_resource_id,
                )
                from ...trace.quality_bundle import (
                    QUALITY_FILENAME,
                    QualityIssue,
                    evaluate_quality_bundle,
                )
                from ..questions import QuestionSet

                policy = quality_state.get("report_request_context", {}).get("assertionPolicy", {})
                if policy.get("mode", "shadow") != "off":
                    if policy.get("ruleVersion", "assertions/1") != "assertions/1":
                        raise ReportingError("quality_rule_unavailable", "历史质量规则不可执行，不能用新规则替代原核验。")
                    sources = {}
                    durable_questions = await self.state_repository.get(durable_run_id)
                    raw_questions = durable_questions.payload.get("questionSpecs") if durable_questions is not None else None
                    questions = QuestionSet.model_validate(raw_questions) if raw_questions is not None else None
                    from ..answer_review import AnswerReviewPlan

                    raw_review_plan = durable_questions.payload.get("answerReviewPlan") if durable_questions is not None else None
                    answer_review_plan = None
                    registration_failed = False
                    registration_failure_reason = "registered_plan_invalid"
                    if raw_review_plan is not None:
                        try:
                            answer_review_plan = AnswerReviewPlan.model_validate(raw_review_plan)
                            if questions is None:
                                raise ValueError("registered questions unavailable")
                            answer_review_plan.validate_questions(questions)
                        except Exception as error:
                            answer_review_plan = None
                            registration_failed = True
                            logger.warning("report_answer_review_registration_unavailable reason={}", type(error).__name__)
                    quality_source_ids = _quality_source_ids(index)
                    quality_image_ids = {chart.image_file_resource_id for chart in index.chart_traces}
                    quality_image_bytes = 0
                    for file in index.files:
                        if file.resource_id not in quality_source_ids:
                            continue
                        if file.resource_id in quality_image_ids:
                            if file.size > QUALITY_IMAGE_BYTE_BUDGET - quality_image_bytes:
                                continue
                        try:
                            raw_source = await self.workspace_service.read_limited_regular_file(
                                scope["threadId"], file.path,
                                max_bytes=min(file.size, QUALITY_IMAGE_BYTE_BUDGET) if file.resource_id in quality_image_ids else 16 * 1024 * 1024,
                            )
                            if file.resource_id in quality_image_ids:
                                if len(raw_source) != file.size or hashlib.sha256(raw_source).hexdigest() != file.sha256:
                                    logger.warning("quality_source_unavailable resource_id={}", file.resource_id)
                                    continue
                                quality_image_bytes += len(raw_source)
                            sources[file.resource_id] = raw_source
                        except Exception:
                            logger.warning("quality_source_unavailable resource_id={}", file.resource_id)
                    from .business_evidence import resolve_runtime_knowledge

                    _, knowledge_evidence = await resolve_runtime_knowledge(self, run_context, index)
                    evaluate = partial(
                        evaluate_quality_bundle, index, markdown, sources,
                        knowledge_evidence=knowledge_evidence,
                        authorization_scope_hash=canonical_sha256({key: scope[key] for key in ("userId", "threadId")}),
                        mode="enabled" if policy.get("mode") == "enabled" else "shadow",
                        questions=questions,
                        heading_numbers=heading_numbers,
                    )
                    bundle = await anyio.to_thread.run_sync(partial(evaluate, answer_review_plan=answer_review_plan))
                    if bundle.registered_question_coverage and questions is not None:
                        from ...semantics.question_coverage import RegisteredAnswerPlan
                        from ..registered_answer_registration import (
                            RegisteredAnswerRegistrationContext,
                            validate_registered_answer_plan,
                        )

                        native_raw = durable_questions.payload.get('registeredAnswerPlan') if durable_questions else None
                        native_provider = getattr(self, 'registered_answer_plan_provider', None)
                        native_stage = 'read'
                        try:
                            approved_native = None
                            if native_raw is not None:
                                approved_native = RegisteredAnswerPlan.model_validate(native_raw)
                                approved_native.validate_questions(questions, index.report_basis_id)
                            elif native_provider is not None:
                                import copy

                                native_context = RegisteredAnswerRegistrationContext(index.report_id, index.revision,
                                    index.report_basis_id, questions, bundle.claim_support, index.subject_bindings)
                                if len(repr(native_context).encode()) > 2 * 1024 * 1024:
                                    raise ValueError('正式问题批准上下文超出容量限制')
                                native_stage = 'provider'
                                with anyio.fail_after(10):
                                    proposal = await native_provider(copy.deepcopy(native_context))
                                if proposal is not None:
                                    native_stage = 'proposal'
                                    approved_native = RegisteredAnswerPlan.model_validate_json(proposal.model_dump_json(by_alias=True))
                                    validate_registered_answer_plan(approved_native, native_context)
                                    frozen_native = approved_native.model_dump(mode='json', by_alias=True)
                                    native_stage = 'freeze'
                                    committed = await self._apply_durable_command(run_context, ReportingCommand(
                                        name='freeze_registered_answer_plan', commandId='registered-answer:' + canonical_sha256(frozen_native),
                                        payload={'basisId': index.report_basis_id, 'plan': frozen_native}), **execution_options)
                                    native_stage = 'receipt'
                                    if (committed.state.report_run_id != durable_run_id
                                        or committed.state.payload.get('registeredAnswerPlan') != frozen_native
                                        or committed.state.payload.get('questionSpecs') != questions.model_dump(mode='json', by_alias=True)):
                                        raise ValueError('正式问题完成映射的持久化回执不一致')
                            if approved_native is not None:
                                native_stage = 'evaluation'
                                bundle = await anyio.to_thread.run_sync(partial(evaluate,
                                    registered_answer_plan=approved_native))
                        except Exception as error:
                            logger.warning('registered_answer_plan_unavailable stage={} reason={}', native_stage, type(error).__name__)
                            bundle = bundle.model_copy(update={'issues': (*bundle.issues, QualityIssue(
                                code='registered_answer_plan_unavailable', reasons=(f'registration_{native_stage}_unavailable',)))})
                            quality_state.setdefault('report_quality_issues', []).append({
                                'code': 'registered_answer_plan_unavailable', 'status': 'unknown', 'revision': revision,
                                'reason': f'registration_{native_stage}_unavailable',
                                'message': '正式问题完成映射未能核验，保留逐问题缺项；实际可用产物仍可下载。'})
                    # The provider is application construction, never request/session/model data.
                    provider = (getattr(self, "answer_review_plan_provider", None)
                                if not bundle.registered_question_coverage else None)
                    if raw_review_plan is None and questions is not None and provider is not None:
                        registration_stage = "context"
                        try:
                            import copy

                            from ..answer_registration import (
                                PROVIDER_TIMEOUT_SECONDS,
                                registration_context,
                                validate_registration,
                            )

                            registration = registration_context(bundle, index, canonical_sha256({
                                key: scope[key] for key in ("userId", "threadId")
                            }))
                            registration_stage = "provider"
                            with anyio.fail_after(PROVIDER_TIMEOUT_SECONDS):
                                proposed = await provider(copy.deepcopy(registration))
                            if proposed is not None:
                                registration_stage = "proposal"
                                # Revalidate even model_copy-created objects; the hook gets detached inputs.
                                approved = AnswerReviewPlan.model_validate_json(proposed.model_dump_json(by_alias=True))
                                validate_registration(approved, registration)
                                frozen = approved.model_dump(mode="json", by_alias=True)
                                registration_stage = "freeze"
                                committed = await self._apply_durable_command(run_context, ReportingCommand(
                                    name="freeze_answer_review_plan",
                                    commandId="answer-plan:" + canonical_sha256(frozen),
                                    payload={"plan": frozen},
                                ), **execution_options)
                                registration_stage = "receipt"
                                if (committed.state.report_run_id != durable_run_id
                                        or committed.state.payload.get("answerReviewPlan") != frozen
                                        or committed.state.payload.get("questionSpecs") != questions.model_dump(mode="json", by_alias=True)):
                                    raise ValueError("answer registration durable receipt mismatch")
                                registration_stage = "evaluation"
                                bundle = await anyio.to_thread.run_sync(partial(evaluate, answer_review_plan=approved))
                        except Exception as error:
                            registration_failed = True
                            registration_failure_reason = f"registration_{registration_stage}_unavailable"
                            logger.warning("report_answer_review_registration_unavailable stage={} reason={}", registration_stage, type(error).__name__)
                    if registration_failed:
                        bundle = bundle.model_copy(update={"issues": (*bundle.issues, QualityIssue(
                            code="answer_review_registration_unavailable", reasons=("approved_mapping_unavailable", registration_failure_reason),
                        ))})
                        quality_state.setdefault("report_quality_issues", []).append({
                            "code": "answer_review_registration_unavailable", "status": "unknown", "revision": revision,
                            "reason": registration_failure_reason,
                            "message": "审核映射未能登记或核验，已保留独立事实和未知回答状态；实际可用产物仍可下载。",
                        })
                    if bundle.answer_review is not None:
                        try:
                            await self._apply_durable_command(run_context, ReportingCommand(
                                name="record_answer_review", commandId=f"answer-review:{index.revision}:{bundle.input_sha256}",
                                payload={"revision": index.revision, "review": bundle.answer_review.model_dump(mode="json", by_alias=True)},
                            ), **execution_options)
                        except Exception:
                            logger.warning("report_answer_review_checkpoint_unavailable")
                    quality_path = str(PurePosixPath(manifest_relative).with_name(QUALITY_FILENAME))
                    if any(file.path == quality_path for file in index.files):
                        raise ReportingError("quality_path_conflict", "质量记录不能覆盖已登记来源。")
                    quality_bytes = canonical_json_bytes(bundle.model_dump(mode="json", by_alias=True))
                    await self.workspace_service.awrite_bytes(scope["threadId"], quality_path, quality_bytes, overwrite=True)
                    stored_quality = await self.workspace_service.read_limited_regular_file(
                        scope["threadId"], quality_path, max_bytes=len(quality_bytes),
                    )
                    if stored_quality != quality_bytes:
                        raise ReportingError("quality_snapshot_changed", "质量记录写入后发生变化。")
                    quality_file = TraceFileRefV1(
                        resourceId=derive_resource_id(quality_path), path=quality_path,
                        mediaType="application/json", size=len(quality_bytes),
                        sha256=hashlib.sha256(quality_bytes).hexdigest(),
                    )
                    index = RevisionTraceIndexV1.model_validate(index.model_copy(update={
                        "files": (*index.files, quality_file),
                    }).model_dump(mode="json", by_alias=True))
            except Exception as error:
                logger.warning("report_quality_evaluation_unavailable reason={}", type(error).__name__)
                try:
                    quality_state.setdefault("report_quality_issues", []).append({
                        "code": "quality_evaluation_unavailable", "status": "unknown",
                        "reason": type(error).__name__, "revision": revision,
                        "message": "质量检查或记录暂不可用，未标记通过；实际可用产物仍可下载。",
                    })
                except Exception:
                    logger.warning("report_quality_issue_state_unavailable revision={}", revision)
        from ...trace.chart_facts import recover_chart_fact_refs

        async def read_chart_source(file):
            return await self.workspace_service.read_limited_regular_file(
                scope["threadId"], file.path, max_bytes=file.size
            )

        bound_charts = []
        for chart in index.chart_traces:
            if not chart.fact_refs:
                try:
                    refs = await recover_chart_fact_refs(index, chart, read_chart_source)
                    chart = chart.model_copy(update={"fact_refs": refs})
                except Exception as error:
                    logger.warning("report_chart_fact_binding_unavailable chart={} error={}",
                                   chart.chart_id, type(error).__name__)
                    try:
                        if execution is None:
                            quality_state = self._state(run_context)
                        quality_state.setdefault("report_quality_issues", []).append({
                            "code": "chart_fact_binding_unavailable", "status": "unknown",
                            "chartId": chart.chart_id, "revision": revision,
                            "message": "图表事实引用未能精确核验，保留图表与下载产物，不标记来源核验通过。",
                        })
                    except Exception:
                        logger.warning("report_chart_fact_binding_notice_unavailable")
            bound_charts.append(chart)
        index = index.model_copy(update={"chart_traces": tuple(bound_charts)})
        if execution is not None and quality_state.get('report_quality_issues'):
            try:
                await self._apply_durable_command(run_context, ReportingCommand(name='record_warnings',
                    commandId=f'revision-trace-quality:{revision}:{markdown_artifact.sha256}',
                    payload={'warnings': quality_state['report_quality_issues']}), **execution_options)
            except Exception:
                logger.warning('report_revision_quality_notice_unavailable')
        content = encode_trace_index(index)
        index_path = trace_index_path_for(manifest_relative)
        self.workspace_service.validate_content(content)
        await self.workspace_service.awrite_bytes(
            scope["threadId"], index_path, content, overwrite=True
        )
        stored = await self.workspace_service.read_limited_regular_file(
            scope["threadId"], index_path, max_bytes=len(content)
        )
        if stored != content:
            raise ReportingError(
                "report_trace_index_changed", "追溯索引写入后发生变化。"
            )
        logger.info(
            "revision 追溯索引已写入: revision={} datasets={} path={}",
            revision,
            len(handles),
            index_path,
        )
        return ArtifactFile(
            path=index_path,
            mediaType="application/json",
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )

    async def _build_drilldown_metrics(
        self,
        *,
        fact_files: Mapping[str, ArtifactFile],
        run_context: RunContext,
        execution=None,
    ) -> tuple:
        """从已冻结 facts/Profile/快照列签发 B7 能力；歧义项保持不可用。"""

        if execution is not None:
            from ..revision_execution import require_revision_execution

            await require_revision_execution(self, run_context, execution)
            # 正式聚合结果尚未登记可授权下钻的明细粒度；不借用旧Profile签发能力。
            return ()
        state = self._state(run_context)
        raw_contexts = state.get(REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY, ())
        dataset_columns: dict[str, tuple[str, ...]] = {}
        if isinstance(raw_contexts, (list, tuple)):
            for context in raw_contexts:
                if not isinstance(context, Mapping):
                    continue
                dataset_id = context.get("datasetId")
                fields = context.get("fields")
                if (
                    isinstance(dataset_id, str)
                    and isinstance(fields, (list, tuple))
                    and all(isinstance(field, str) for field in fields)
                ):
                    dataset_columns[dataset_id] = tuple(fields)
        bundles: list[Mapping[str, Any]] = []
        thread_id = self._scope(run_context)["threadId"]
        for analysis_id, identity in fact_files.items():
            try:
                raw = await self.workspace_service.read_limited_regular_file(
                    thread_id, identity.path, max_bytes=16 * 1024 * 1024
                )
                document = json.loads(raw)
            except (OSError, ValueError, UnicodeDecodeError) as error:
                raise ReportingError(
                    "snapshot_integrity_failed",
                    f"下钻声明无法读取冻结事实文件: {analysis_id}",
                ) from error
            if (
                len(raw) != identity.size
                or hashlib.sha256(raw).hexdigest() != identity.sha256
                or not isinstance(document, Mapping)
            ):
                raise ReportingError(
                    "snapshot_integrity_failed",
                    f"下钻声明引用的事实文件与登记身份不一致: {analysis_id}",
                )
            bundles.append(document)
        # 正式计算上下文不是旧式明细指标；没有下钻操作数就不读取旧Profile或签发能力。
        if not any(bundle.get('metrics') or bundle.get('derivedMetrics') for bundle in bundles):
            return ()
        profile = self._profile(run_context)
        snapshots = self._snapshots(run_context)
        row_preserving_requirements = set(
            state.get(REPORT_ROW_PRESERVING_REQUIREMENTS_STATE_KEY, ())
        )
        row_preserving_dataset_ids = tuple(
            str(item.get("datasetId"))
            for item in self._workflow_result(state).get("datasets", ())
            if isinstance(item, Mapping)
            and isinstance(item.get("provenance"), Mapping)
            and item["provenance"].get("requirementId") in row_preserving_requirements
        )
        return build_drilldown_metrics(
            bundles=bundles,
            dataset_columns=dataset_columns,
            profile_dimensions=tuple(
                item.model_dump(mode="json", by_alias=True)
                for item in profile.dimensions
            ),
            profile_metrics=tuple(
                item.model_dump(mode="json", by_alias=True) for item in profile.metrics
            ),
            measure_semantics=tuple(
                item.model_dump(mode="json", by_alias=True)
                for snapshot in snapshots
                for item in snapshot.measure_semantics
            ),
            row_preserving_dataset_ids=row_preserving_dataset_ids,
        )


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


async def _record_publication_audit(
    audit: QualityAuditCollector,
    warnings: list[Any],
    *,
    service: Any,
    tenant: TenantScope | None,
    complete: bool,
) -> int:
    """把发布告警写入质量台账，返回因不符合审计契约而跳过的告警数。

    告警记录不符合审计契约（规则未登记、主体不允许、超出数量上限等）属于审计自身
    的质量问题，按“语义业务校验只需软告警”只记录日志并跳过，不阻断正式发布；此时
    本次审计不完整，不得据此关闭既有告警。台账写入失败等其他异常照常抛出。
    """

    invalid_codes: list[str] = []
    for item in warnings:
        if not isinstance(item, Mapping):
            continue
        code = item.get("code")
        if not isinstance(code, str):
            continue
        try:
            audit.add(
                _publication_warning_notice(
                    item,
                    run_id=audit.report_run_id,
                    source_phase=("analysis" if code.startswith("analysis_") else "publication"),
                )
            )
        except QualityWarningContractError:
            invalid_codes.append(code[:64])
    if invalid_codes:
        logger.warning(
            "report_quality_warning_notice_invalid report_run_id={} count={} codes={}",
            audit.report_run_id,
            len(invalid_codes),
            sorted(set(invalid_codes))[:10],
        )
    if service is not None and tenant is not None:
        try:
            await audit.flush(
                service=service, tenant=tenant, complete=complete and not invalid_codes
            )
        except QualityWarningContractError as error:
            logger.warning(
                "report_quality_audit_invalid report_run_id={} error_type={}",
                audit.report_run_id,
                type(error).__name__,
            )
    return len(invalid_codes)


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


_MAX_PRESENTED_COVERAGE_PERIODS = 12
_MAX_PRESENTED_PERIOD_LENGTH = 32
# 附录读者可见的期间角色名称；current/yoy/mom 是内部代码。
_PERIOD_ROLE_LABELS = {"current": "本期", "yoy": "同比基期", "mom": "环比基期"}


def _coverage_period_bounds(periods: set[str]) -> list[str]:
    """PDF 不再展示来源附录，覆盖期间只用于展示信息的结构校验。

    日粒度数据一年就有数百个期间，完整列表会让绑定到 job 的展示信息越过状态边界，
    导致整份报告渲染失败；期间较多时只保留覆盖首尾。
    """

    ordered = sorted(periods)
    if len(ordered) <= _MAX_PRESENTED_COVERAGE_PERIODS:
        return ordered
    # 首尾写成一个区间：两项并列会被读成两个孤立期间。渲染端单项上限 32 字符，
    # 带时刻的长期间写不下区间时保留首尾两项，不能让展示信息导致渲染失败。
    span = f"{ordered[0]}至{ordered[-1]}"
    return [span] if len(span) <= _MAX_PRESENTED_PERIOD_LENGTH else [ordered[0], ordered[-1]]


def _citation_presentations(
    *,
    lineage: tuple[DatasetLineage, ...],
    requirements: tuple[QueryRequirement, ...],
    analyses: tuple[AnalysisItem, ...],
    snapshots: tuple[SourceSchemaSnapshot, ...],
    observed_facts: list[dict[str, Any]],
    source_links_by_dataset: Mapping[str, list[dict[str, str]]] | None = None,
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
    lineage_by_key = {
        (item.dataset_id, item.requirement_id): item for item in lineage
    }
    for index, citation in enumerate(authoritative_citations(lineage), start=1):
        binding = lineage_by_key[(citation.dataset_id, citation.requirement_id)]
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
            coverage_items.append(
                {"label": coverage_label, "periods": _coverage_period_bounds(coverage - missing)}
            )
        presentations.append(
            {
                "citationId": citation.citation_id,
                "label": label,
                "coverageItems": coverage_items,
                "status": "valid",
                "method": (
                    "StarRocks 查询冻结快照"
                    if binding.source_type == "starrocks_materialized"
                    else "CSV 文件冻结快照"
                ),
                "scope": "、".join(_PERIOD_ROLE_LABELS.get(role, role) for role in binding.period_roles),
                "summary": f"{binding.row_count} 行，快照 {binding.sha256[:12]}",
                "links": list((source_links_by_dataset or {}).get(citation.dataset_id, ())),
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
    declared = [
        manifest.markdown,
        *manifest.charts,
    ]
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
