"""幻灯片说明冻结原文与分析身份，不能借用数值或其他章节的知识支持。"""

from types import SimpleNamespace

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.narrative_helpers import finding, graph
from smart_reporting.reporting.tests.test_claim_knowledge_support import candidate
from smart_reporting.reporting.tests.test_narrative_knowledge_support import knowledge_context
from smart_reporting.reporting.trace.native_claims import (
    native_claim_presentations,
    present_native_summary,
)
from smart_reporting.reporting.trace.registered_claims import registered_narrative_support
from smart_reporting.reporting.trace.semantic_bindings import anchor_bound_numbers
from smart_reporting.reporting.trace.subject_builder import build_claim_subject_bindings
from smart_reporting.reporting.workflow.analysis_summaries import build_analysis_summary_section
from smart_reporting.reporting.workflow.runtime import business_evidence, sections
from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview
from smart_reporting.reporting.workflow.runtime.slides import (
    SlideOutline,
    build_slide_outline,
    validate_slide_summaries,
)


async def summary_inputs(monkeypatch, relation='supports'):
    evidence = candidate()
    text = ('建议按原始金额累计预算，避免把期间平均当作合计。\n\n建议采用期间平均作为预算合计。'
        if relation == 'mixed' else '建议按原始金额累计预算，避免把期间平均当作合计。')
    view = SimpleNamespace(basis_id=evidence.reference.basis_id, report_revision='initial',
        request=SimpleNamespace(period=evidence.period))
    section = SimpleNamespace(code='section_001', title='预算管理', analysis_ids=('analysis_001',))

    async def knowledge(*args, **kwargs):
        return knowledge_context(evidence)

    async def review(agent, schema, stage, payload, **kwargs):
        if relation == 'outage':
            raise OSError('isolated slide semantic review outage')
        return SectionSemanticReview.model_validate({'interpretations': [{
            'claimId': reference['claimId'], 'claimKind': 'recommendation', 'kindEvidence': ['建议'],
            'knowledgeRelations': [{'evidenceId': evidence.reference.evidence_id,
                'relationship': ('supports' if index == 0 else 'contradicts') if relation == 'mixed' else relation,
                'explanationType': 'recommendation',
                'claimEvidence': ['采用期间平均'] if index else ['按原始金额累计预算'],
                'sourceEvidence': [evidence.hit.quote]}]}
            for index, reference in enumerate(payload['references'])]})

    monkeypatch.setattr(business_evidence, 'business_knowledge_context', knowledge)
    monkeypatch.setattr(sections, '_run_section_stage', review)
    runtime = SimpleNamespace(section_generator=object(),
        _scope=lambda _: {'userId': 'tester', 'threadId': 'workspace'})
    sources = SimpleNamespace(evidence=(SimpleNamespace(analysis_id='analysis_001', summary=text,
        citation_ids=('citation_001',), chart_ids=()),), charts=())
    artifact = await build_analysis_summary_section(runtime, SimpleNamespace(), section=section,
        evidence=sources.evidence, view=view)
    return artifact, SimpleNamespace(sections=(section,)), sources, view, evidence


@pytest.mark.anyio
@pytest.mark.parametrize('relation,current,expected', [('supports', True, 'supported'),
    ('contradicts', True, 'conflicted'), ('irrelevant', True, 'unverified'),
    ('supports', False, 'unverified'), ('outage', True, 'unverified')])
async def test_slide_summary_preserves_own_support_and_current_original(monkeypatch, relation, current, expected):
    artifact, source, manifest, view, evidence = await summary_inputs(monkeypatch, relation)
    validate_slide_summaries((artifact,), source, manifest, view)
    outline = build_slide_outline(graph(finding()), manifest, title='预算核对', analysis_summaries=(artifact,))
    restored = SlideOutline.model_validate_json(outline.model_dump_json(by_alias=True))
    assert restored == outline and len(restored.slides) == 1
    block, = restored.analysis_summaries[0].blocks
    subject, = build_claim_subject_bindings(restored.analysis_summaries, {}, {})
    markdown = anchor_bound_numbers(block.markdown, block.narrative_references)
    support, _ = registered_narrative_support(subject, markdown, basis_id=view.basis_id,
        knowledge_evidence={evidence.reference.evidence_id: evidence} if current else {})
    assert support.support_status == expected
    presentations = native_claim_presentations(SimpleNamespace(subject_bindings=(subject,)), markdown, (support,))
    shown = present_native_summary(block.markdown, presentations,
        section_ids=('section_001',), analysis_ids=('analysis_001',))
    assert shown['support']['subjectId'] == subject.subject_id
    assert shown['support']['supportStatus'] == expected
    assert 'subjectId' not in present_native_summary(block.markdown, presentations,
        section_ids=('foreign',), analysis_ids=('analysis_001',))['support']
    if relation == 'outage':
        assert artifact.warnings and block.narrative_references[0].semantic_receipt is None


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['omitted', 'duplicate', 'section', 'analysis', 'statement', 'basis', 'revision', 'period'])
async def test_slide_summary_cannot_change_frozen_analysis_scope(monkeypatch, fault):
    summary, outline, manifest, view, _ = await summary_inputs(monkeypatch)
    summaries = (summary,)
    if fault == 'omitted':
        summaries = ()
    elif fault == 'duplicate':
        summaries = (summary, summary)
    elif fault in ('section', 'basis', 'revision'):
        field = {'section': 'section_code', 'basis': 'basis_id', 'revision': 'report_revision'}[fault]
        summaries = (summary.model_copy(update={field: 'foreign'}),)
    elif fault == 'period':
        summaries = (summary.model_copy(update={'period': summary.period.model_copy(update={'start': '2025-11-01'})}),)
    else:
        block, = summary.blocks
        block = block.model_copy(update={'block_id': 'analysis_999'} if fault == 'analysis' else {'markdown': '已确认付款安排导致变化。'})
        summaries = (summary.model_copy(update={'blocks': (block,)}),)
    with pytest.raises(ReportingError, match='完整绑定'):
        validate_slide_summaries(summaries, outline, manifest, view)
    if fault in ('duplicate', 'analysis', 'statement'):
        with pytest.raises(ReportingError, match='冻结原文'):
            build_slide_outline(graph(finding()), manifest, title='预算核对', analysis_summaries=summaries)
