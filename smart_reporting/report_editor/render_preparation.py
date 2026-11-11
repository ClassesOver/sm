"""编辑器预览与发布共用来源、附录和经营总览的只读准备流程。"""
from __future__ import annotations

import copy
from typing import Any

from loguru import logger

from ..reporting.models import ReportingError
from ..reporting.workflow.management_overview import (
    ManagementOverview,
    management_overview_projection,
    unavailable_management_overview_projection,
)
from ..reporting.workflow.registered_overview import RegisteredManagementOverview
from ..reporting.workspace import REPORT_JOBS_STATE_KEY
from .trace_revisions import rebuild_edited_manifest, verify_revision_lineage_files


async def prepare_editor_render(editor, *, context, source_context, document, snapshot_path,
                                scope, session_state, next_revision, export_settings, public_base_url):
    from .service import (
        _build_export_trace_sources,
        _export_citation_presentations,
        _lineage_unavailable_issue,
    )
    artifact_manifest = None
    trace_index = None
    render_manifest = None
    rebuilt = None
    # AGENTS：追溯数据不可用只拒绝使用该数据，不能阻止导出已核验身份的 PDF/Word；
    # 原因写入 validation.issues 并照常签发。
    lineage_issues: list[dict[str, str]] = []
    target_job = session_state[REPORT_JOBS_STATE_KEY][context.job_id]
    target_job['_claimSupportProjection'] = {'invalid': 'claim_support_unavailable'}
    original_presentations = copy.deepcopy(target_job.get("_citationPresentations"))
    # 报告没有实际评估过的经营总览（旧报告或未启用回答审核）时沿用各章核心结论；
    # 评估过时才用总览投影，缺证据的问题显示缺项说明。
    overview_projection: dict[str, Any] | None = None
    try:
        artifact_manifest, trace_index = await editor.trace.load_manifest_and_index(
            source_context
        )
        if artifact_manifest is not None:
            await verify_revision_lineage_files(
                editor.workspace,
                scope.workspace_key,
                manifest=artifact_manifest,
                index=trace_index,
            )
            # AGENTS：改图登记读取或身份校验失败只降级对应追溯数据，不阻断
            # 渲染与签发；原因写入 issues。正文引用了改图但登记不可用时，
            # rebuild 会按未登记图表拒绝，整体追溯随之降级（同样非阻断）。
            try:
                edited_charts, edited_index = await editor._chart_edit_lineage(
                    source_context,
                    markdown=document.markdown,
                    markdown_path=snapshot_path,
                    manifest=artifact_manifest,
                    index=trace_index,
                )
            except Exception as error:  # noqa: BLE001 - 改图追溯降级，导出继续
                edited_charts, edited_index = {}, None
                reason = (
                    error.message if isinstance(error, ReportingError) else type(error).__name__
                )
                lineage_issues.append({
                    "code": "report_editor_chart_edit_lineage_unavailable",
                    "message": f"AI 改图追溯不可用（{reason}），新版本按未改图登记追溯。"[:500],
                })
                logger.opt(exception=error).warning(
                    "report_editor_chart_edit_lineage_dropped report_id={} base_revision={}",
                    context.report_id,
                    context.revision,
                )
            try:
                edited_tables, table_index = await editor._table_edit_lineage(
                    source_context,
                    markdown=document.markdown,
                    manifest=artifact_manifest,
                    index=edited_index or trace_index,
                )
            except Exception as error:  # noqa: BLE001 - 改表追溯降级，导出继续
                edited_tables, table_index = {}, None
                reason = error.message if isinstance(error, ReportingError) else type(error).__name__
                lineage_issues.append({
                    "code": "report_editor_table_edit_lineage_unavailable",
                    "message": f"AI 改表追溯不可用（{reason}），新版本按原表追溯。"[:500],
                })
                logger.opt(exception=error).warning(
                    "report_editor_table_edit_lineage_dropped report_id={} base_revision={}",
                    context.report_id, context.revision,
                )
            if edited_tables:
                table_index = table_index or trace_index

            rebuilt = await rebuild_edited_manifest(
                editor.workspace,
                scope.workspace_key,
                manifest=artifact_manifest,
                index=edited_index or table_index or trace_index,
                markdown_path=snapshot_path,
                markdown=document.markdown,
                target_revision=next_revision,
                edited_charts=edited_charts,
            )
            render_manifest = rebuilt.model_dump(mode="json", by_alias=True)
            if edited_index is not None:
                # 增强索引携带改图文件与图表追溯；validate、来源附录、
                # path_map 与 snapshot 全部使用同一份索引。
                trace_index = edited_index
            if table_index is not None:
                trace_index = table_index
        if trace_index is not None:
            validation = await editor.trace.validate(
                source_context,
                document.markdown,
                document.sha256,
                analysis_context_file=await editor._registered_analysis_context_file(
                    source_context
                ),
            )
            from ..reporting.trace.claim_presentation import claim_support_projection

            target_job['_claimSupportProjection'] = claim_support_projection(
                trace_index, document.sha256, validation.get('quality', {}).get('claimSupport', ()))
            if validation.get("revisionImpactIssues"):
                lineage_issues.append({
                    "code": "report_editor_revision_impact_unavailable",
                    "message": "修订影响范围暂无法核验，请复核修改；原计算快照保留，文件仍可下载。",
                })
            knowledge = validation.get("businessKnowledge", {})
            if trace_index.knowledge_dependencies and knowledge.get("status") != "available":
                lineage_issues.append({
                    "code": "report_editor_knowledge_unavailable",
                    "message": "章节知识依据已撤销、不可用或无法核验，相关解释未获确认；导出可能保留旧解释，文件仍可下载。",
                })
            if isinstance(target_job.get("_citationPresentations"), list):
                target_job["_citationPresentations"] = _export_citation_presentations(
                    target_job["_citationPresentations"],
                    validation,
                    trace_index,
                    public_base_url=public_base_url,
                    report_id=context.report_id,
                    revision=next_revision,
                    citations=artifact_manifest.citations if artifact_manifest is not None else (),
                )
            native_overview = validation.get("quality", {}).get("registeredManagementOverview")
            raw_overview = native_overview if isinstance(native_overview, dict) else validation.get("quality", {}).get("managementOverview")
            # 原生总览保留部分回答与缺项；通过当前来源核验后才展示事实。
            if isinstance(raw_overview, dict) and (isinstance(native_overview, dict) or raw_overview.get("status") == "evaluated"):
                # 总览只是展示载荷：单独降级，不能连带丢弃已核验的追溯与引用展示。
                try:
                    overview_projection = management_overview_projection(
                        (RegisteredManagementOverview if isinstance(native_overview, dict) else ManagementOverview).model_validate(raw_overview),
                        document.sha256, target_job.get("_citationPresentations"),
                    )
                except Exception as error:  # noqa: BLE001 - 总览降级，导出继续
                    overview_projection = unavailable_management_overview_projection(document.sha256)
                    lineage_issues.append({
                        "code": "report_editor_management_overview_unavailable",
                        "message": "经营总览未能核验，已显示缺项说明；数据来源追溯照常保留。",
                    })
                    logger.opt(exception=error).warning(
                        "report_editor_management_overview_unavailable report_id={} revision={}",
                        context.report_id, next_revision,
                    )
            # B8：数据来源附录与引用展示同一次快照联合渲染，编号由渲染器
            # 按正文首次出现顺序分配；无追溯索引的旧报告保持无附录导出。
            target_job.pop("_traceSourcePresentations", None)
            if export_settings.get("sources") is True:
                try:
                    target_job["_traceSourcePresentations"] = _build_export_trace_sources(
                        trace_index, validation, public_base_url=public_base_url,
                        report_id=context.report_id, revision=next_revision,
                    )
                except Exception as error:
                    # 附录是展示载荷；失败不能丢弃已核验的追溯索引。
                    lineage_issues.append({
                        "code": "report_editor_source_appendix_unavailable",
                        "message": "来源附录未能生成，在线数据来源仍保留。"
                                   + (error.message if isinstance(error, ReportingError) else "附录构建异常。"),
                    })
                    logger.opt(exception=error).warning(
                        "report_editor_source_appendix_unavailable report_id={} revision={}",
                        context.report_id, next_revision,
                    )
    except Exception as error:  # noqa: BLE001 - 追溯降级，导出继续
        lineage_issues.append(_lineage_unavailable_issue(error, rendered=False))
        artifact_manifest = trace_index = render_manifest = rebuilt = None
        if isinstance(original_presentations, list):
            target_job["_citationPresentations"] = original_presentations
        target_job.pop("_traceSourcePresentations", None)
        target_job['_claimSupportProjection'] = {'invalid': 'claim_support_unavailable'}
        if overview_projection is not None:
            overview_projection = unavailable_management_overview_projection(document.sha256)
        logger.opt(exception=error).warning(
            "report_editor_export_lineage_dropped report_id={} base_revision={} stage=prepare",
            context.report_id,
            context.revision,
        )
    return artifact_manifest, trace_index, render_manifest, rebuilt, lineage_issues, overview_projection
