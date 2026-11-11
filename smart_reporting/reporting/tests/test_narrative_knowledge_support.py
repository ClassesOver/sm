"""纯文字解释也进入当前授权与逐声明支持核验。"""

from types import SimpleNamespace

import pytest

from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
from smart_reporting.reporting.model_policy import ThinkingRequest
from smart_reporting.reporting.tests.test_claim_knowledge_support import candidate
from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs
from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle
from smart_reporting.reporting.trace.subject_builder import build_claim_subject_bindings
from smart_reporting.reporting.workflow.runtime import sections
from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview


def knowledge_context(evidence):
    from smart_reporting.reporting.business_knowledge.retrieval import (
        EvidenceQuery,
        EvidenceSearchReceipt,
        ReportEvidenceSearchReceipt,
    )

    receipt = ReportEvidenceSearchReceipt(basisId=evidence.reference.basis_id, kind='rule_evidence',
        search=EvidenceSearchReceipt(releaseId=evidence.reference.release_id, status='matched', hits=(evidence.hit,),
            request=EvidenceQuery(query='预算如何计算', period=evidence.period, knowledgeAsOf=evidence.hit.recorded_at)))
    return {'reportBasisId': evidence.reference.basis_id, 'requestedPeriod': evidence.period.model_dump(mode='json'),
        'receiptIds': [evidence.reference.receipt_id], 'receipts': [receipt.model_dump(mode='json', by_alias=True)]}


@pytest.mark.anyio
@pytest.mark.parametrize('case,expected', [('supports', 'supported'), ('contradicts', 'conflicted'),
    ('irrelevant', 'unverified'), ('no_review', 'unverified'), ('revoked', 'unverified'),
    ('edited', 'unverified'), ('duplicated', 'unverified'), ('fact', 'unverified')])
async def test_plain_text_explanation_reaches_actual_semantic_stage_and_quality(tmp_path, monkeypatch, case, expected):
    evidence = candidate()
    block = ReportDraftBlock(blockId='advice', markdown='建议按原始金额累计预算，避免把期间平均当作合计。')
    calls = []

    async def reviewer(agent, schema, stage, payload, **kwargs):
        assert stage == 'semantics'
        assert payload['knowledgeEvidence'][0]['quote'] == evidence.hit.quote
        reference, = payload['references']
        assert reference['referenceKind'] == 'narrative'
        calls.append(reference['claimId'])
        return SectionSemanticReview.model_validate({'interpretations': [] if case == 'no_review' else [{
            'claimId': reference['claimId'], 'claimKind': 'fact' if case == 'fact' else 'recommendation',
            'kindEvidence': ['建议'], 'knowledgeRelations': [{
                'evidenceId': evidence.reference.evidence_id,
                'relationship': case if case in {'supports', 'contradicts', 'irrelevant'} else 'supports',
                'explanationType': 'recommendation', 'claimEvidence': ['按原始金额累计预算'],
                'sourceEvidence': ['预算按原始金额累计']}]}]})

    monkeypatch.setattr(sections, '_run_section_stage', reviewer)
    blocks = await sections._disambiguate_section_claims(object(), (block,), (), section_code='section_001',
        scope=SimpleNamespace(), run_context=SimpleNamespace(),
        thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'),
        business_knowledge=knowledge_context(evidence))
    assert len(calls) == 1
    narrative, = blocks[0].narrative_references
    from smart_reporting.reporting.trace.semantic_bindings import anchor_bound_numbers

    markdown = anchor_bound_numbers(blocks[0].markdown, blocks[0].narrative_references)
    subjects = build_claim_subject_bindings((SimpleNamespace(section_code='section_001', blocks=blocks, claims=()),), {}, {})
    assert len(subjects) == 1
    assert subjects[0].narrative_reference == narrative
    index, _, sources = await native_quality_inputs(tmp_path)
    index = type(index).model_validate({**dict(index), 'subject_bindings': subjects, 'tables': ()})
    if case == 'edited':
        markdown = markdown.replace('避免', '应该')
    if case == 'duplicated':
        markdown += '\n\n' + markdown
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64,
        knowledge_evidence={} if case == 'revoked' else {evidence.reference.evidence_id: evidence})
    support, = quality.claim_support
    assert support.support_status == expected
    assert support.kind == ('fact' if case == 'fact' else 'inference' if case in {'no_review', 'edited', 'duplicated'} else 'recommendation')
    assert not support.fact_refs
    if case == 'revoked':
        assert not support.evidence_refs


def test_final_assembly_preserves_narrative_identity_and_semantic_receipt():
    from smart_reporting.reporting.delivery.draft_v1 import (
        ReportDraft,
        ReportDraftSection,
        ReportSectionDefinition,
        assemble_report_markdown,
    )
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_receipt_status,
    )
    from smart_reporting.reporting.trace.narrative_claims import discover_narrative_references
    from smart_reporting.reporting.trace.semantic_bindings import (
        anchor_bound_numbers,
        statement_fingerprints,
    )

    evidence = candidate()
    block = ReportDraftBlock(blockId='b', markdown='建议按原始金额累计预算。')
    ref, = discover_narrative_references(block, section_code='section_001',
        basis_id=evidence.reference.basis_id, period=evidence.period)
    marked = anchor_bound_numbers(block.markdown, (ref,))
    receipt = freeze_interpretation(marked, ref.claim_id, {'claimId': ref.claim_id,
        'claimKind': 'recommendation', 'kindEvidence': ['建议']})
    block = block.model_copy(update={'narrative_references': (ref.model_copy(update={'semantic_receipt': receipt,
        'statement_sha256': statement_fingerprints(marked, (ref.claim_id,))[ref.claim_id]}),)})
    result = assemble_report_markdown(ReportDraft(sections=(ReportDraftSection(sectionCode='section_001', blocks=(block,)),)),
        expected_title='预算报告', markdown_path='reports/report.md',
        sections=(ReportSectionDefinition(code='section_001', sectionNumber='1', title='预算建议'),), citation_ids=())
    assert result.markdown.count('[[claim:' + ref.claim_id + ']]') == 1
    assert semantic_receipt_status(result.markdown, ref.claim_id, receipt) == 'interpreted'

    assert statement_fingerprints(result.markdown, (ref.claim_id,))[ref.claim_id] == block.narrative_references[0].statement_sha256


@pytest.mark.parametrize('citation', ['', '[[citation:sub-example]]'])
@pytest.mark.parametrize('punctuation', ['。', '！', '；'])
@pytest.mark.parametrize('separator', ['', '\n\n'])
def test_sentence_end_narrative_fingerprint_binds_the_statement_before_its_anchor(citation, punctuation, separator):
    import hashlib

    from smart_reporting.reporting.trace.semantic_bindings import statement_fingerprint

    marker = '[[claim:narr-example]]'
    markdown = '前一项。\n\n建议核对采购付款安排' + punctuation + citation + marker + separator + '后一项。'
    fingerprint = statement_fingerprint(markdown, 'narr-example')
    assert fingerprint != hashlib.sha256(b'').hexdigest()
    assert fingerprint != statement_fingerprint(markdown.replace('核对采购', '忽略采购'), 'narr-example')
    assert fingerprint == statement_fingerprint(markdown.replace('前一项', '其他前文').replace('后一项', '其他后文'), 'narr-example')


def test_causal_explanation_without_registered_observation_is_not_supported():
    from datetime import date

    from smart_reporting.reporting.business_knowledge.claims import candidate_for_hit
    from smart_reporting.reporting.business_knowledge.models import BusinessObjectRef
    from smart_reporting.reporting.trace.claim_semantics import freeze_interpretation
    from smart_reporting.reporting.trace.narrative_claims import discover_narrative_references
    from smart_reporting.reporting.trace.registered_claims import registered_narrative_support
    from smart_reporting.reporting.trace.semantic_bindings import (
        anchor_bound_numbers,
        statement_fingerprints,
    )

    original = candidate()
    evidence = candidate_for_hit(basis_id=original.reference.basis_id, section_code='section_001',
        receipt_id='event', release_id='background', period=original.period,
        hit=original.hit.model_copy(update={'role': 'background', 'event_time': date(2026, 11, 3),
            'applies_to': (BusinessObjectRef(kind='metric', id='budget'),)}))
    block = ReportDraftBlock(blockId='cause', markdown='预算下降源于政策调整。')
    ref, = discover_narrative_references(block, section_code='section_001', basis_id=evidence.reference.basis_id,
        period=evidence.period)
    markdown = anchor_bound_numbers(block.markdown, (ref,))
    receipt = freeze_interpretation(markdown, ref.claim_id, {'claimId': ref.claim_id, 'claimKind': 'inference',
        'kindEvidence': ['源于'], 'metricVersion': {'metricId': 'budget', 'revision': 1},
        'knowledgeRelations': [{'evidenceId': evidence.reference.evidence_id, 'relationship': 'supports',
            'explanationType': 'causal', 'claimEvidence': ['预算下降'], 'sourceEvidence': [evidence.hit.quote]}]},
        reference={'entry': {'basisId': evidence.reference.basis_id}},
        knowledge_candidates={evidence.reference.evidence_id: evidence})
    ref = ref.model_copy(update={'semantic_receipt': receipt,
        'statement_sha256': statement_fingerprints(markdown, (ref.claim_id,))[ref.claim_id]})
    block = block.model_copy(update={'narrative_references': (ref,)})
    subject, = build_claim_subject_bindings((SimpleNamespace(section_code='section_001', blocks=(block,), claims=()),), {}, {})
    support, issues = registered_narrative_support(subject, markdown, basis_id=evidence.reference.basis_id,
        knowledge_evidence={evidence.reference.evidence_id: evidence})
    assert support.support_status == 'unverified'
    assert 'registered_observation_unavailable' in issues


@pytest.mark.anyio
async def test_missing_model_review_keeps_plain_text_as_explicit_unverified_subject(tmp_path, monkeypatch):
    evidence = candidate()
    context = knowledge_context(evidence)
    context.update(receipts=[], receiptIds=[], status='unavailable')

    async def unavailable(*args, **kwargs):
        raise OSError('semantic model unavailable')

    monkeypatch.setattr(sections, '_run_section_stage', unavailable)
    blocks = await sections._disambiguate_section_claims(object(),
        (ReportDraftBlock(blockId='b', markdown='建议核对预算累计规则。'),), (), section_code='section_001',
        scope=SimpleNamespace(), run_context=SimpleNamespace(),
        thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'), business_knowledge=context)
    assert blocks[0].markdown == '建议核对预算累计规则。'
    ref, = blocks[0].narrative_references
    assert ref.semantic_receipt is None
    assert len(build_claim_subject_bindings((SimpleNamespace(section_code='section_001', blocks=blocks, claims=()),), {}, {})) == 1


def test_discovery_uses_markdown_structure_and_skips_registered_numeric_paragraph():
    from smart_reporting.reporting.trace.contracts_v1 import NumberReferenceV1
    from smart_reporting.reporting.trace.narrative_claims import discover_narrative_references

    evidence = candidate()
    text = '# 预算建议\n\n合计为100。\n\n建议核对规则。\n\n```text\n不要当作声明\n```\n\n![示意图](a.png)'
    block = ReportDraftBlock(blockId='b', markdown=text, numberReferences=(NumberReferenceV1(
        offset=text.index('100') + 3, claimId='n', token='x', statementSha256='a' * 64),))
    ref, = discover_narrative_references(block, section_code='section_001', basis_id=evidence.reference.basis_id,
        period=evidence.period)
    assert text[:ref.offset].endswith('建议核对规则。')
