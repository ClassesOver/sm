"""真实引用与语义支持分开；数值正确不能替代知识关系复核。"""

from datetime import UTC, datetime

import pytest

from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs
from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle


def candidate():
    from smart_reporting.reporting.business_knowledge.claims import candidate_for_hit
    from smart_reporting.reporting.business_knowledge.retrieval import EvidenceHit
    from smart_reporting.reporting.semantics.models import Period

    return candidate_for_hit(basis_id='basis-selection', section_code='section_001', receipt_id='knowledge-rules',
        release_id='release-rules', period=Period(start='2026-11-01', end='2026-12-01'),
        hit=EvidenceHit(documentId='budget-rules', revision=1, sourceHash='a' * 64,
            locator={'kind': 'text_lines', 'lineStart': 1, 'lineEnd': 1},
            quote='预算按原始金额累计，不取期间平均。', title='预算制度', role='rule_evidence',
            recordedAt=datetime(2026, 10, 1, tzinfo=UTC)))


@pytest.mark.anyio
@pytest.mark.parametrize('relation,expected', [('supports', 'supported'), ('irrelevant', 'unverified'),
    ('unknown', 'unverified'), ('contradicts', 'conflicted')])
async def test_c34_current_original_still_requires_grounded_semantic_relationship(tmp_path, relation, expected):
    evidence = candidate()
    def interpretation(item):
        item.update(claimKind='inference', knowledgeRelations=[{
            'evidenceId': evidence.reference.evidence_id, 'relationship': relation,
            'explanationType': 'interpretation', 'sourceEvidence': [evidence.hit.quote], 'claimEvidence': ['预算合计']}])
    index, markdown, sources = await native_quality_inputs(tmp_path, change=interpretation,
        knowledge_candidates={evidence.reference.evidence_id: evidence})
    result = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64,
        knowledge_evidence={evidence.reference.evidence_id: evidence})
    assert result.claim_support[0].support_status == expected
    assert result.claim_support[0].evidence_refs == (evidence.reference.evidence_id,)
    missing = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64)
    assert missing.claim_support[0].support_status == 'unverified'
    assert not missing.claim_support[0].evidence_refs
    assert missing.input_sha256 != result.input_sha256


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['not_reviewed', 'ungrounded', 'foreign_section', 'changed_quote', 'causal_without_event', 'edited_statement', 'wrong_metric', 'wrong_period'])
async def test_knowledge_reference_cannot_grant_support_by_its_existence(tmp_path, fault):
    evidence = candidate()
    def interpretation(item):
        item['claimKind'] = 'inference'
        if fault != 'not_reviewed':
            item['knowledgeRelations'] = [{'evidenceId': evidence.reference.evidence_id, 'relationship': 'supports',
                'explanationType': 'causal' if fault == 'causal_without_event' else 'interpretation',
                'sourceEvidence': [evidence.hit.quote], 'claimEvidence': ['本文不存在的依据' if fault == 'ungrounded' else '预算合计']}]
    index, markdown, sources = await native_quality_inputs(tmp_path, change=interpretation,
        knowledge_candidates={evidence.reference.evidence_id: evidence})
    current = evidence
    if fault in {'foreign_section', 'changed_quote'}:
        from dataclasses import replace
        current = replace(evidence, reference=evidence.reference.model_copy(update=(
            {'section_code': 'section_002'} if fault == 'foreign_section' else {'quote_sha256': 'b' * 64})))
    if fault in {'wrong_metric', 'wrong_period'}:
        from dataclasses import replace

        from smart_reporting.reporting.business_knowledge.models import BusinessObjectRef
        from smart_reporting.reporting.semantics.models import Period

        current = replace(evidence, hit=evidence.hit.model_copy(update={
            'applies_to': (BusinessObjectRef(kind='metric', id='foreign-metric'),)})) if fault == 'wrong_metric' else replace(
                evidence, period=Period(start='2025-01-01', end='2026-01-01'))
    if fault == 'edited_statement':
        markdown = markdown.replace('预算合计', '预算合计增加源于政策调整')
    result = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64,
        knowledge_evidence={evidence.reference.evidence_id: current})
    assert result.claim_support[0].support_status == 'unverified'


def test_supported_recommendation_requires_knowledge_beyond_correct_amount():
    from pydantic import ValidationError

    from smart_reporting.reporting.semantics.models import ClaimSupport

    with pytest.raises(ValidationError):
        ClaimSupport(subjectId='subject-1', kind='recommendation', factRefs=['fact-budget'], supportStatus='supported')


@pytest.mark.anyio
async def test_actual_semantic_stage_receives_originals_and_freezes_only_identity(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from smart_reporting.reporting.business_knowledge.retrieval import (
        EvidenceQuery,
        EvidenceSearchReceipt,
        ReportEvidenceSearchReceipt,
    )
    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.trace.semantic_bindings import strip_bound_anchors
    from smart_reporting.reporting.workflow.runtime import sections
    from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview

    evidence = candidate()
    index, markdown, sources = await native_quality_inputs(tmp_path)
    number = index.subject_bindings[0].number_reference
    plain, numbers, _ = strip_bound_anchors(markdown, (number,), ())
    block = ReportDraftBlock(blockId='b', markdown=plain, numberReferences=numbers)
    search = ReportEvidenceSearchReceipt(basisId=evidence.reference.basis_id, kind='rule_evidence',
        search=EvidenceSearchReceipt(releaseId=evidence.reference.release_id, status='matched', hits=(evidence.hit,),
            request=EvidenceQuery(query='预算如何计算', period=evidence.period, knowledgeAsOf=evidence.hit.recorded_at)))
    context = {'receiptIds': [evidence.reference.receipt_id], 'receipts': [search.model_dump(mode='json', by_alias=True)]}
    async def reviewer(agent, schema, stage, payload, **kwargs):
        assert stage == 'semantics'
        assert payload['knowledgeEvidence'][0]['quote'] == evidence.hit.quote
        assert payload['knowledgeEvidence'][0]['evidenceId'] == evidence.reference.evidence_id
        interpretation = number.semantic_receipt.interpretation.model_dump(mode='json', by_alias=True)
        interpretation.update(claimKind='inference', knowledgeRelations=[{
            'evidenceId': evidence.reference.evidence_id, 'relationship': 'irrelevant',
            'explanationType': 'interpretation', 'sourceEvidence': [evidence.hit.quote], 'claimEvidence': ['预算合计']}])
        return SectionSemanticReview.model_validate({'interpretations': [interpretation]})
    monkeypatch.setattr(sections, '_run_section_stage', reviewer)
    blocks = await sections._disambiguate_section_claims(object(), (block,),
        tuple(raw.decode() for key, raw in sources.items() if key == index.fact_files[0].file_resource_id),
        section_code='section_001', scope=SimpleNamespace(), run_context=SimpleNamespace(),
        thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'), business_knowledge=context)
    receipt = blocks[0].number_references[0].semantic_receipt
    assert receipt.knowledge_references == (evidence.reference,)
    relation = receipt.interpretation.knowledge_relations[0]
    assert relation.relationship == 'irrelevant'
    assert not relation.source_evidence
    assert relation.source_spans
    assert evidence.hit.quote not in receipt.model_dump_json(by_alias=True)
    assert evidence.hit.quote not in receipt.model_dump_json(by_alias=True)


@pytest.mark.anyio
@pytest.mark.parametrize('kind,explanation_type,expected', [('inference', 'causal', 'supported'),
    ('recommendation', 'recommendation', 'supported'), ('recommendation', 'interpretation', 'unverified')])
async def test_background_event_and_recommendation_have_separate_support_conditions(tmp_path, kind, explanation_type, expected):
    from datetime import date

    from smart_reporting.reporting.business_knowledge.claims import candidate_for_hit
    from smart_reporting.reporting.business_knowledge.models import BusinessObjectRef
    from smart_reporting.reporting.tests.test_registered_analysis_facts import analysis_inputs

    original = candidate()
    evidence = candidate_for_hit(basis_id=original.reference.basis_id, section_code=original.reference.section_code,
        receipt_id='knowledge-background', release_id='release-background', period=original.period,
        hit=original.hit.model_copy(update={'role': 'background', 'event_time': date(2026, 11, 3),
            'applies_to': (BusinessObjectRef(kind='metric', id=analysis_inputs()[2].metric_version.metric_id),)}))
    def interpretation(item):
        item.update(claimKind=kind, knowledgeRelations=[{'evidenceId': evidence.reference.evidence_id,
            'relationship': 'supports', 'explanationType': explanation_type, 'sourceEvidence': [evidence.hit.quote], 'claimEvidence': ['预算合计']}])
    index, markdown, sources = await native_quality_inputs(tmp_path, change=interpretation,
        knowledge_candidates={evidence.reference.evidence_id: evidence})
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64,
        knowledge_evidence={evidence.reference.evidence_id: evidence})
    assert quality.claim_support[0].kind == kind
    assert quality.claim_support[0].support_status == expected


@pytest.mark.anyio
@pytest.mark.parametrize('fault,expected', [('source_not_grounded', 'unverified'), ('unknown_alongside_support', 'unverified'), ('grounded', 'supported'), ('forged_spans', 'unverified'), ('changed_span', 'unverified')])
async def test_unresolved_relationship_cannot_be_hidden_by_another_support(tmp_path, fault, expected):
    evidence = candidate()
    def interpretation(item):
        supported = {'evidenceId': evidence.reference.evidence_id, 'relationship': 'supports',
            'explanationType': 'interpretation', 'claimEvidence': ['预算合计'],
            'sourceEvidence': ['材料中不存在的内容' if fault == 'source_not_grounded' else '不取期间平均']}
        if fault == 'forged_spans':
            supported['sourceEvidence'] = []
            supported['sourceSpans'] = [{'start': 0, 'end': 2, 'sha256': 'a' * 64}]
        relations = [supported]
        if fault == 'unknown_alongside_support':
            relations.append({**supported, 'relationship': 'unknown'})
        item.update(claimKind='inference', knowledgeRelations=relations)
    index, markdown, sources = await native_quality_inputs(tmp_path, change=interpretation,
        knowledge_candidates={evidence.reference.evidence_id: evidence})
    if fault == 'changed_span':
        receipt = index.subject_bindings[0].number_reference.semantic_receipt
        span = receipt.interpretation.knowledge_relations[0].source_spans[0]
        object.__setattr__(span, 'sha256', 'b' * 64)
    quality = evaluate_quality_bundle(index, markdown, sources, authorization_scope_hash='a' * 64,
        knowledge_evidence={evidence.reference.evidence_id: evidence})
    assert quality.claim_support[0].support_status == expected


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case,expected",
    [
        ("grounded", "supported"),
        ("missing_event", "unverified"),
        ("missing_metric", "unverified"),
        ("outside_period", "unverified"),
        ("irrelevant", "unverified"),
        ("contradicts", "conflicted"),
    ],
)
async def test_c33_background_event_requires_scope_time_and_independent_semantic_support(
    tmp_path, case, expected
):
    from dataclasses import replace
    from datetime import date

    from smart_reporting.reporting.business_knowledge.models import BusinessObjectRef

    original = candidate()
    evidence = replace(
        original,
        hit=original.hit.model_copy(
            update={
                "role": "background",
                "event_time": None
                if case == "missing_event"
                else date(2026, 10, 31)
                if case == "outside_period"
                else date(2026, 11, 1),
                "applies_to": ()
                if case == "missing_metric"
                else (BusinessObjectRef(kind="metric", id="budget"),),
            }
        ),
        reference=original.reference.model_copy(update={"role": "background"}),
    )

    def interpretation(item):
        item.update(
            claimKind="inference",
            knowledgeRelations=[
                {
                    "evidenceId": evidence.reference.evidence_id,
                    "relationship": case if case in {"irrelevant", "contradicts"} else "supports",
                    "explanationType": "causal",
                    "sourceEvidence": [evidence.hit.quote],
                    "claimEvidence": ["预算合计"],
                }
            ],
        )

    index, markdown, sources = await native_quality_inputs(
        tmp_path,
        change=interpretation,
        knowledge_candidates={evidence.reference.evidence_id: evidence},
    )
    quality = evaluate_quality_bundle(
        index,
        markdown,
        sources,
        authorization_scope_hash="a" * 64,
        knowledge_evidence={evidence.reference.evidence_id: evidence},
    )
    assert quality.claim_support[0].support_status == expected
    if case in {"missing_event", "missing_metric", "outside_period"}:
        assert any("business_event_time_unverified" in issue.reasons for issue in quality.issues)
