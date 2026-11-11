"""原生分析说明共用完整原文、分析身份和知识支持复核契约。"""

from pydantic import Field, model_validator

from ..contract import StrictModel
from ..delivery.draft_v1 import ReportDraftBlock
from ..model_policy import ThinkingRequest
from ..semantics.models import Identity, Period, RunIdentity
from ..trace.narrative_claims import discover_narrative_references
from ..trace.semantic_bindings import anchor_bound_numbers, statement_fingerprints


class AnalysisSummarySection(StrictModel):
    basis_id: Identity = Field(alias='basisId')
    report_revision: RunIdentity = Field(alias='reportRevision')
    period: Period
    section_code: str = Field(alias='sectionCode', min_length=1, max_length=128)
    knowledge_receipt_ids: tuple[str, ...] = Field(default=(), alias='knowledgeReceiptIds', max_length=2)
    blocks: tuple[ReportDraftBlock, ...] = Field(min_length=1, max_length=200)
    warnings: tuple[dict, ...] = Field(default=(), max_length=500)

    @property
    def claims(self):
        return ()

    @model_validator(mode='after')
    def validate_summary_identity(self):
        if len({block.block_id for block in self.blocks}) != len(self.blocks):
            raise ValueError('分析摘要分析身份不能重复')
        for block in self.blocks:
            expected = discover_narrative_references(block, section_code=self.section_code,
                basis_id=self.basis_id, period=self.period)
            actual = block.narrative_references
            fingerprints = statement_fingerprints(anchor_bound_numbers(block.markdown, actual),
                (ref.claim_id for ref in actual))
            if (block.number_references or block.claim_ids
                    or len(expected) != len(actual) or any(
                        (ref.claim_id, ref.offset, ref.basis_id) !=
                        (registered.claim_id, registered.offset, registered.basis_id)
                        or registered.statement_sha256 != fingerprints[registered.claim_id]
                        or registered.period != self.period
                        or registered.analysis_id != block.block_id
                        for ref, registered in zip(expected, actual, strict=True))):
                raise ValueError('分析摘要声明必须完整绑定原文、计算依据及分析身份')
        return self


async def build_analysis_summary_section(runtime, run_context, *, section, evidence, view):
    from ...task_execution.models import TaskExecutionScope
    from .runtime.business_evidence import business_knowledge_context
    from .runtime.sections import _disambiguate_section_claims

    knowledge = await business_knowledge_context(runtime, run_context,
        query=section.title[:4000], report_revision=view.report_revision, section_code=section.code)
    # 服务端登记身份来自当前正式计算上下文，不由检索服务或模型补写。
    knowledge = {**knowledge, 'reportBasisId': view.basis_id,
        'requestedPeriod': view.request.period.model_dump(mode='json')}
    blocks = tuple(ReportDraftBlock(blockId=item.analysis_id, markdown=item.summary,
        chartPlacement='explicit', reviewNotices=()) for item in evidence if item.analysis_id in section.analysis_ids)
    blocks = tuple(block.model_copy(update={'narrative_references': discover_narrative_references(
        block, section_code=section.code, basis_id=view.basis_id, period=view.request.period)}) for block in blocks)
    scope = runtime._scope(run_context)
    notices = {}
    agent = getattr(runtime, 'section_generator', None)
    reviewed = await _disambiguate_section_claims(agent, blocks, (),
        section_code=section.code, run_context=run_context,
        scope=TaskExecutionScope('analysis-summary-' + section.code, scope['userId'], scope['threadId'],
            'analysis-summary', 'reporting-section-agent'),
        thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'),
        business_knowledge=knowledge, review_notices=notices) if agent is not None else blocks
    for block in reviewed:
        if (not block.narrative_references or any(ref.semantic_receipt is None for ref in block.narrative_references)) and block.block_id not in notices:
            notices[block.block_id] = [{'code': 'report_claim_semantics_unavailable',
                'message': '摘要语义尚未核实，计算成功不能替代解释依据。'}]
    # 原生摘要只包含本段，不能沿用整章或前段才能成立的支持关系。
    blocks = []
    for block in reviewed:
        fingerprints = statement_fingerprints(anchor_bound_numbers(block.markdown, block.narrative_references),
            (ref.claim_id for ref in block.narrative_references))
        blocks.append(block.model_copy(update={'narrative_references': tuple(ref.model_copy(update={
            'analysis_id': block.block_id, 'statement_sha256': fingerprints[ref.claim_id]})
            for ref in block.narrative_references)}))
    return AnalysisSummarySection(basisId=view.basis_id, reportRevision=view.report_revision,
        period=view.request.period, sectionCode=section.code, knowledgeReceiptIds=tuple(knowledge['receiptIds']), blocks=blocks,
        warnings=tuple(notice for values in notices.values() for notice in values))
