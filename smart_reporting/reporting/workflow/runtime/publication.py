# mypy: disable-error-code="attr-defined"
# 运行时由 facade 末尾组合的多重继承提供跨阶段成员；静态检查无法解析该延迟装配。
from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote, urlencode

from loguru import logger

from ....quality_warnings import (
    QualityAuditCollector,
    QualityWarningContractError,
    TenantScope,
    WarningAdapter,
)
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


def _editor_interactive_charts(manifest: ReportArtifactManifest) -> dict[str, dict[str, Any]]:
    return {
        chart.path: {
            "path": chart.interactive_spec.path,
            "size": chart.interactive_spec.size,
            "sha256": chart.interactive_spec.sha256,
        }
        for chart in manifest.charts
        if chart.interactive_spec is not None
    }


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


class _OverviewDisabled(Exception):
    """未注入回答审核计划提供方：不构建经营总览，渲染沿用各章核心结论。"""


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


def _quality_source_ids(
    index: RevisionTraceIndexV1, interactive_charts: Mapping[str, str],
) -> set[str]:
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
    interactive_paths = set(interactive_charts.values())
    source_ids.update(file.resource_id for file in index.files if file.path in interactive_paths)
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
        # 经营问题矩阵依赖服务端注入的回答审核计划提供方；应用/CLI 默认不注入。未启用时沿用
        # 各章核心结论，避免每份报告的首页都只剩缺项说明。启用后缺少证据才显示缺项说明。
        overview_enabled = getattr(self, "answer_review_plan_provider", None) is not None
        from ..management_overview import unavailable_management_overview_projection

        overview_projection = (
            unavailable_management_overview_projection(draft.markdown.sha256) if overview_enabled else None
        )
        try:
            if not overview_enabled:
                raise _OverviewDisabled
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
        except _OverviewDisabled:
            pass
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
            validation = validation if isinstance(validation, dict) else {"ok": False, "issues": []}
            validation = {
                **validation,
                "ok": False,
                "issues": [
                    *(validation.get("issues") if isinstance(validation.get("issues"), list) else []),
                    source_link_issue,
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

        if result.get("status") != "validated":
            issue(
                "artifact_not_validated",
                "Markdown、PDF 或 DOCX 尚未完成验收。",
                validationIssues=result.get("validationIssues", [])[:20],
            )
        for key in ("markdownPath", "pdfPath", "wordPath"):
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

    async def publish_report(self, step_input: StepInput, run_context: RunContext) -> StepOutput:
        feedback = self._feedback(step_input)
        if feedback:
            # 反馈重跑继续走唯一的 Agno ReportingAnalysisAndDraftWorkflow 入口，
            # 避免发布路径维护第二套手写章节循环。
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
        interactive_charts = _editor_interactive_charts(manifest) if manifest is not None else {}
        if interactive_charts:
            editor_job = {**editor_job, "interactiveCharts": interactive_charts}
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
                "revision": int(result.get("revision", 0)) + 1,
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
                **{key: result[key] for label in ("pdf", "word") for suffix in ("Path", "Size", "Sha256")
                   if (key := f"{label}{suffix}") in result},
                "validation": result["validation"],
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
        """核对 claim.factIds 是否存在于冻结 bundle，异常写入验收原因。

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
                document = json.loads(raw)
            except Exception:
                issues.append(
                    {
                        "code": "report_claim_fact_file_unreadable",
                        "message": "发布门禁无法读取冻结事实文件。",
                        "details": {"analysisId": analysis_id},
                    }
                )
                continue
            for array_name in ("metrics", "breakdowns", "derivedMetrics", "comparisons", "reconciliations"):
                for entry in document.get(array_name, ()) or ():
                    fact_id = entry.get("factId") if isinstance(entry, dict) else None
                    if isinstance(fact_id, str):
                        fact_ids[fact_id] = entry
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
        interactive_charts: Mapping[str, str] | None = None,
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
            trace_index_file = None
            if getattr(self, "trace_registration_enabled", True):
                trace_index_file = await self._write_trace_index(
                    manifest_relative,
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
                    interactive_charts=interactive_charts,
                    revision=revision,
                    run_context=run_context,
                )
            manifest = build_authoritative_manifest(
                report_id=str(run_context.run_id),
                revision=revision,
                task_key=task_key,
                effective_profile_hash=self._profile(run_context).effective_profile_hash,
                markdown_path=markdown_path,
                markdown=markdown_bytes.decode("utf-8"),
                accepted_artifacts=current_artifacts,
                interactive_charts=interactive_charts,
                lineage=lineage,
                sections=tuple(
                    section.code for section in _frozen_outline(self._state(run_context)).sections
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
        handles: tuple[DatasetHandle, ...],
        lineage: tuple[DatasetLineage, ...],
        markdown_artifact: ArtifactFile,
        revision: int,
        run_context: RunContext,
        fact_files: Mapping[str, ArtifactFile] | None = None,
        server_table_traces: tuple = (),
        chart_trace_files: tuple[FileIdentity, ...] = (),
        chart_traces: tuple = (),
        interactive_charts: Mapping[str, str] | None = None,
        computation_files: tuple[FileIdentity, ...] = (),
        computations: tuple = (),
        table_source_files: tuple[FileIdentity, ...] = (),
        subject_bindings: tuple = (),
        review_notices: tuple | None = None,
        markdown: str | None = None,
    ) -> ArtifactFile:
        """构建并写入 revision 追溯索引，返回供权威清单登记的产物身份。

        句柄缺失或与血缘不一致时失败关闭，不生成半份索引；索引内容为
        canonical JSON，写入后回读校验（与清单同一模式）。
        """

        scope = self._scope(run_context)
        run_id = str(run_context.run_id or scope["externalRunId"])
        drilldown_metrics = await self._build_drilldown_metrics(
            fact_files=fact_files or {}, run_context=run_context
        )
        def build(computation_files: tuple[FileIdentity, ...], computations: tuple) -> Any:
            return build_csv_trace_index(
                handles=handles,
                lineage=lineage,
                report_id=run_id,
                revision=revision,
                workflow_run_id=run_id,
                markdown_file=markdown_artifact,
                profile_hash=self._profile(run_context).effective_profile_hash,
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

                policy = self._state(run_context).get("report_request_context", {}).get("assertionPolicy", {})
                if policy.get("mode", "shadow") != "off":
                    if policy.get("ruleVersion", "assertions/1") != "assertions/1":
                        raise ReportingError("quality_rule_unavailable", "历史质量规则不可执行，不能用新规则替代原核验。")
                    sources = {}
                    durable_questions = await self.state_repository.get(run_id)
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
                    quality_source_ids = _quality_source_ids(index, interactive_charts or {})
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
                    evaluate = partial(
                        evaluate_quality_bundle, index, markdown, sources,
                        authorization_scope_hash=canonical_sha256({key: scope[key] for key in ("userId", "threadId")}),
                        mode="enabled" if policy.get("mode") == "enabled" else "shadow",
                        questions=questions,
                        interactive_charts=interactive_charts,
                    )
                    bundle = await anyio.to_thread.run_sync(partial(evaluate, answer_review_plan=answer_review_plan))
                    # The provider is application construction, never request/session/model data.
                    provider = getattr(self, "answer_review_plan_provider", None)
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
                                ))
                                registration_stage = "receipt"
                                if (committed.state.report_run_id != index.report_id
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
                            ))
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
                    self._state(run_context).setdefault("report_quality_issues", []).append({
                        "code": "quality_evaluation_unavailable", "status": "unknown",
                        "reason": type(error).__name__, "revision": revision,
                        "message": "质量检查或记录暂不可用，未标记通过；实际可用产物仍可下载。",
                    })
                except Exception:
                    logger.warning("report_quality_issue_state_unavailable revision={}", revision)
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
    ) -> tuple:
        """从已冻结 facts/Profile/快照列签发 B7 能力；歧义项保持不可用。"""

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
        *(chart.interactive_spec for chart in manifest.charts if chart.interactive_spec),
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
