"""工作簿摘要冻结和正文声明别名投影，复用原生分析说明契约。"""

from ..delivery.draft_v1 import ReportDraftSection
from ..trace.semantic_bindings import anchor_bound_numbers
from .analysis_summaries import AnalysisSummarySection, build_analysis_summary_section


class WorkbookSummaryProjection(ReportDraftSection):
    """装配时的声明别名视图，不替换已登记的摘要及语义回执。"""

    @property
    def claims(self):
        return ()


def project_workbook_summary_sections(section_artifacts, summaries):
    from ..trace.claim_semantics import semantic_receipt_status
    from ..trace.contracts_v1 import canonical_sha256

    used = {ref.claim_id for artifact in section_artifacts for block in artifact.blocks
        for ref in (*block.number_references, *block.narrative_references)}
    used.update(claim.claim_id for artifact in section_artifacts for claim in artifact.claims)
    reserved = used | {ref.claim_id for summary in summaries for block in summary.blocks
        for ref in block.narrative_references}
    projected = []
    for summary in summaries:
        blocks = []
        for block in summary.blocks:
            marked = anchor_bound_numbers(block.markdown, block.narrative_references)
            references = []
            for ref in block.narrative_references:
                if ref.claim_id in used:
                    counter = 0
                    while True:
                        alias = 'workbook-' + canonical_sha256([summary.section_code, ref.claim_id, counter])[:32]
                        if alias not in reserved:
                            break
                        counter += 1
                    receipt = ref.semantic_receipt
                    if semantic_receipt_status(marked, ref.claim_id, receipt) == 'interpreted':
                        receipt = receipt.model_copy(update={'interpretation':
                            receipt.interpretation.model_copy(update={'claim_id': alias})})
                        if semantic_receipt_status(marked.replace(f'[[claim:{ref.claim_id}]]',
                                f'[[claim:{alias}]]'), alias, receipt) != 'interpreted':
                            receipt = None
                    else:
                        # 无效回执不能因新锚点而重新有效；原始回执仍保留在冻结文件。
                        receipt = None
                    ref = ref.model_copy(update={'claim_id': alias, 'semantic_receipt': receipt})
                    reserved.add(alias)
                used.add(ref.claim_id)
                references.append(ref)
            blocks.append(block.model_copy(update={'narrative_references': tuple(references)}))
        projected.append(WorkbookSummaryProjection(sectionCode=summary.section_code, blocks=tuple(blocks)))
    return tuple(projected)


async def freeze_workbook_summary_sections(runtime, run_context, *, checkpoint, outline, root, view, execution=None):
    """首次与修订共用精确文件登记；未知写入只核对，不覆盖或重跑语义复核。"""
    from ..models import ReportingError
    from ..trace.contracts_v1 import derive_resource_id
    from .checkpoint import FileIdentity
    from .state import ReportingCommand

    options = {} if execution is None else {'execution': execution}
    thread_id = runtime._scope(run_context)['threadId']
    included, selected = set(), []
    for section in outline.sections:
        evidence = tuple(item for item in checkpoint.evidence_manifest.evidence
            if item.analysis_id in section.analysis_ids and item.analysis_id not in included)
        if evidence:
            selected.append((section, evidence, f'{root}/summary-{section.code}.json'))
            included.update(item.analysis_id for item in evidence)
    summaries = []
    if checkpoint.workbook_summary_files:
        if execution is None:
            durable = await runtime.state_repository.get(str(run_context.run_id))
        else:
            from .revision_execution import require_revision_execution

            durable = await require_revision_execution(runtime, run_context, execution)
        registered = {item['path']: FileIdentity.model_validate(item) for item in durable.payload.get('artifacts', ())}
        if tuple(file.path for file in checkpoint.workbook_summary_files) != tuple(item[2] for item in selected):
            raise ReportingError('report_revision_execution_mismatch', '工作簿摘要范围与本修订提纲不一致。')
        for file, (section, evidence, _) in zip(checkpoint.workbook_summary_files, selected, strict=True):
            if registered.get(file.path) != file:
                raise ReportingError('report_revision_execution_mismatch', '工作簿摘要未登记到本修订。')
            summary = await runtime._read_identity_model(thread_id, file, AnalysisSummarySection)
            if ((summary.basis_id, summary.report_revision, summary.period, summary.section_code) !=
                    (view.basis_id, view.report_revision, view.request.period, section.code)
                    or tuple((block.block_id, block.markdown) for block in summary.blocks) !=
                    tuple((item.analysis_id, item.summary.strip()) for item in evidence)):
                raise ReportingError('report_revision_execution_mismatch', '工作簿摘要不属于当前计算依据、修订及原始分析。')
            summaries.append(summary)
        return checkpoint, tuple(summaries)
    paths = [item[2] for item in selected]
    if paths:
        existing = await runtime.workspace_service.abatch_hash_files(thread_id, paths)
        if any(not item.get('missing') for item in existing):
            raise ReportingError('report_revision_workbook_outcome_unknown',
                '工作簿摘要已有文件但未完成登记，需核对结果，禁止自动重写。')
    files = []
    for section, evidence, path in selected:
        summary = await build_analysis_summary_section(runtime, run_context, section=section, evidence=evidence, view=view)
        file = await runtime._write_immutable_artifact(thread_id, path, summary.model_dump_json(by_alias=True).encode('utf-8'))
        await runtime._apply_durable_command(run_context, ReportingCommand(name='record_artifact',
            commandId=f'workbook-summary:{derive_resource_id(file.path)}:{file.sha256}',
            payload={'artifact': file.model_dump(mode='json', by_alias=True)}), **options)
        summaries.append(summary)
        files.append(file)
    checkpoint = runtime._update_reporting_checkpoint(checkpoint, workbook_summary_files=tuple(files),
        files=runtime._merge_checkpoint_files(checkpoint.files, *files))
    checkpoint = await runtime._persist_reporting_checkpoint(run_context, checkpoint, **options)
    return checkpoint, tuple(summaries)
