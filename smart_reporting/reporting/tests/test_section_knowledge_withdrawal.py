"""知识撤销只保留依赖完整且仍获授权的正文块。"""


import pytest

from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
from smart_reporting.reporting.tests.test_claim_knowledge_support import candidate
from smart_reporting.reporting.trace.claim_semantics import freeze_interpretation
from smart_reporting.reporting.trace.narrative_claims import discover_narrative_references
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    statement_fingerprints,
)
from smart_reporting.reporting.workflow.checkpoint import SectionArtifact


def reviewed_block(evidence, *, block_id, text, claim_id):
    block = ReportDraftBlock(blockId=block_id, markdown=text, claimIds=(claim_id,))
    ref, = discover_narrative_references(block, section_code='section_001',
        basis_id=evidence.reference.basis_id, period=evidence.period)
    marked = anchor_bound_numbers(text, (ref,))
    receipt = freeze_interpretation(marked, ref.claim_id, {'claimId': ref.claim_id, 'claimKind': 'recommendation',
        'kindEvidence': [text], 'knowledgeRelations': [{'evidenceId': evidence.reference.evidence_id,
            'relationship': 'supports', 'explanationType': 'recommendation', 'claimEvidence': [text],
            'sourceEvidence': [evidence.hit.quote]}]}, reference={'entry': {'basisId': evidence.reference.basis_id}},
        knowledge_candidates={evidence.reference.evidence_id: evidence})
    return block.model_copy(update={'narrative_references': (ref.model_copy(update={
        'semantic_receipt': receipt, 'statement_sha256': statement_fingerprints(marked, (ref.claim_id,))[ref.claim_id]}),)})


def artifact_for(blocks):
    return SectionArtifact(sectionCode='section_001', blocks=blocks, claims=[{
        'claimId': claim_id, 'metricCode': 'budget', 'value': 1, 'periodBasis': '本期',
        'managementQuestion': '预算建议', 'currentPeriod': '本期', 'citationIds': ['citation_001']}
        for block in blocks for claim_id in block.claim_ids], knowledgeReceiptIds=['knowledge-rules'])


def test_local_withdrawal_preserves_current_independent_block_and_removes_affected_claims():
    from smart_reporting.reporting.business_knowledge.claims import candidate_for_hit
    from smart_reporting.reporting.workflow.runtime.business_evidence import (
        withdraw_knowledge_blocks,
    )

    original = candidate()
    other = candidate_for_hit(basis_id=original.reference.basis_id, section_code='section_001', receipt_id='other',
        release_id='other-rules', period=original.period, hit=original.hit.model_copy(update={'document_id': 'other-doc'}))
    keep = reviewed_block(other, block_id='keep', text='建议核对预算累计规则。', claim_id='c-keep')
    drop = reviewed_block(original, block_id='drop', text='建议按已撤销制度调整预算。', claim_id='c-drop')
    artifact = artifact_for((keep, drop))
    current = withdraw_knowledge_blocks(artifact, {other.reference.evidence_id: other}, basis_id=original.reference.basis_id,
        issues=['document_revoked'])
    assert current.knowledge_status == 'partial'
    assert current.blocks[0] == keep
    assert '建议按已撤销制度' not in current.model_dump_json()
    assert [claim.claim_id for claim in current.claims] == ['c-keep']
    assert any(block.knowledge_withdrawn for block in current.blocks)
    assert SectionArtifact.model_validate(current.model_dump()) == current
    assert withdraw_knowledge_blocks(current, {other.reference.evidence_id: other}, basis_id=original.reference.basis_id,
        issues=['document_revoked']) == current


@pytest.mark.parametrize('fault', ['unreviewed_paragraph', 'missing_receipt', 'changed_text', 'wrong_basis', 'identity_unavailable', 'unreviewed_numeric_notice', 'chapter_context'])
def test_incomplete_block_dependencies_cannot_preserve_old_explanation(fault):
    from smart_reporting.reporting.trace.contracts_v1 import ReviewNoticeV1
    from smart_reporting.reporting.workflow.runtime.business_evidence import (
        withdraw_knowledge_blocks,
    )

    evidence = candidate()
    block = reviewed_block(evidence, block_id='b', text='建议核对预算累计规则。', claim_id='c')
    if fault == 'unreviewed_paragraph':
        block = block.model_copy(update={'markdown': block.markdown + '\n\n额外原因是政策调整。'})
    elif fault == 'changed_text':
        block = block.model_copy(update={'markdown': block.markdown.replace('核对', '跳过')})
    elif fault == 'chapter_context':
        ref = block.narrative_references[0]
        block = block.model_copy(update={'narrative_references': (ref.model_copy(update={
            'semantic_receipt': ref.semantic_receipt.model_copy(update={'includes_section': True})}),)})
    elif fault == 'missing_receipt':
        block = block.model_copy(update={'narrative_references': (block.narrative_references[0].model_copy(update={'semantic_receipt': None}),)})
    elif fault == 'unreviewed_numeric_notice':
        block = block.model_copy(update={'review_notices': (ReviewNoticeV1(offset=3, claimId='unreviewed', kind='numeric_unverified'),)})
    artifact = artifact_for((block,))
    current = withdraw_knowledge_blocks(artifact, {evidence.reference.evidence_id: evidence},
        basis_id=None if fault == 'identity_unavailable' else 'foreign' if fault == 'wrong_basis' else evidence.reference.basis_id, issues=['revoked'])
    assert current.knowledge_status == 'unavailable'
    assert not current.claims
    assert '建议核对' not in current.model_dump_json()
    assert '政策调整' not in current.model_dump_json()


def test_revocation_of_unused_material_does_not_withdraw_independently_reviewed_block():
    from smart_reporting.reporting.workflow.runtime.business_evidence import (
        withdraw_knowledge_blocks,
    )

    evidence = candidate()
    block = reviewed_block(evidence, block_id='b', text='建议核对预算累计规则。', claim_id='c')
    artifact = artifact_for((block,))
    result = withdraw_knowledge_blocks(artifact, {evidence.reference.evidence_id: evidence},
        basis_id=evidence.reference.basis_id, issues=['unused_document_revoked'])
    assert result.blocks == artifact.blocks
    assert result.claims == artifact.claims
    assert result.knowledge_status == 'unverified'
    assert result.warnings


@pytest.mark.anyio
@pytest.mark.parametrize('changed', [False, True])
async def test_current_dependency_resolver_retains_only_unchanged_authorized_hits(changed):
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.business_knowledge.dependencies import (
        resolve_knowledge_dependencies,
    )
    from smart_reporting.reporting.semantics.basis import BasisKnowledgeReceipt
    from smart_reporting.reporting.tests.test_narrative_knowledge_support import knowledge_context
    from smart_reporting.reporting.trace.contracts_v1 import SectionKnowledgeDependencyV1

    evidence = candidate()
    raw = knowledge_context(evidence)['receipts'][0]
    second = evidence.hit.model_copy(update={'document_id': 'removed-doc'})
    raw['search']['hits'].append(second.model_dump(mode='json', by_alias=True))
    receipt = BasisKnowledgeReceipt(receiptId=evidence.reference.receipt_id, basisId=evidence.reference.basis_id,
        reportRevision='1', sectionCode='section_001', query=raw['search']['request']['query'], evidence=raw,
        createdAt=datetime.now(UTC))
    # 第二条已撤销，第一条的身份/原件与当前授权仍完全相同。
    current_hits = (evidence.hit, second.model_copy(update={'quote': '已替换的原文'})) if changed else (evidence.hit,)
    current = receipt.evidence.model_copy(update={'search': receipt.evidence.search.model_copy(update={'hits': current_hits})})
    bases = SimpleNamespace(load_report_basis=AsyncMock(return_value=SimpleNamespace(id=evidence.reference.basis_id)),
        load_basis_receipts=AsyncMock(return_value=(receipt,)))
    service = SimpleNamespace(revalidate_report=AsyncMock(return_value=current))
    dependency = SectionKnowledgeDependencyV1(sectionCode='section_001', reportRevision='1', receiptIds=(receipt.receipt_id,))
    status, authorized = await resolve_knowledge_dependencies(bases, service, identity={}, basis_id=evidence.reference.basis_id,
        dependencies=(dependency,), registration_status='registered')
    assert status['status'] == 'unavailable'
    assert list(authorized) == [evidence.reference.evidence_id]
