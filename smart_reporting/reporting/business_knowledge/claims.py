"""引用身份由服务端构建；支持关系由独立语义复核与当前授权共同确认。"""

import hashlib
from dataclasses import dataclass

from ..semantics.models import Period
from .claim_models import KnowledgeReference
from .retrieval import EvidenceHit, ReportEvidenceSearchReceipt


@dataclass(frozen=True)
class KnowledgeCandidate:
    reference: KnowledgeReference
    hit: EvidenceHit
    period: Period

    def prompt(self):
        return {**self.reference.model_dump(mode='json', by_alias=True), 'quote': self.hit.quote,
            'eventTime': self.hit.event_time.isoformat() if self.hit.event_time else None,
            'appliesTo': [item.model_dump(mode='json', by_alias=True) for item in self.hit.applies_to],
            'requestedPeriod': self.period.model_dump(mode='json')}


def candidate_for_hit(*, basis_id, section_code, receipt_id, release_id, period, hit):
    from ..trace.contracts_v1 import canonical_sha256

    values = dict(basis_id=basis_id, section_code=section_code, receipt_id=receipt_id,
        release_id=release_id, document_id=hit.document_id, document_revision=hit.revision,
        source_hash=hit.source_hash, locator=hit.locator, quote_sha256=hashlib.sha256(hit.quote.encode()).hexdigest(),
        role=hit.role)
    fingerprint = {**values, 'locator': hit.locator.model_dump(mode='json', by_alias=True)}
    ref = KnowledgeReference(evidence_id='evidence-' + canonical_sha256(fingerprint), **values)
    return KnowledgeCandidate(ref, hit, period)


def candidates_from_context(context, *, section_code):
    """只用于已由报告服务核验的生成输入；不能以本函数替代运行授权。"""
    candidates = {}
    for receipt_id, raw in zip(context.get('receiptIds', ()), context.get('receipts', ()), strict=True):
        receipt = ReportEvidenceSearchReceipt.model_validate(raw)
        if receipt.search is None or receipt.search.status != 'matched':
            continue
        for hit in receipt.search.hits:
            item = candidate_for_hit(basis_id=receipt.basis_id, section_code=section_code, receipt_id=receipt_id,
                release_id=receipt.search.release_id, period=receipt.search.request.period, hit=hit)
            candidates[item.reference.evidence_id] = item
    return candidates


def knowledge_support(subject, interpretation, receipt, context, current, reference):
    """数值通过之外仍须复核语义关系；失效材料不再参与支持或冲突判断。"""
    refs, issues, relationships = [], [], []
    registered = {item.evidence_id: item for item in receipt.knowledge_references}
    if not interpretation.knowledge_relations:
        return (), ('business_explanation_unverified',), False
    for relation in interpretation.knowledge_relations:
        ref, candidate = registered.get(relation.evidence_id), current.get(relation.evidence_id)
        if (ref is None or candidate is None or candidate.reference != ref
                or ref.section_code != subject.locator.section_id):
            issues.append('business_evidence_unavailable')
            continue
        metric_ids = {item.id for item in candidate.hit.applies_to if item.kind == 'metric'}
        if candidate.period.model_dump(mode='json') != reference['period'] or (
            metric_ids and reference['entry']['metricVersion']['metricId'] not in metric_ids):
            issues.append('business_evidence_inapplicable')
            continue
        if (not relation.claim_evidence or any(not text.strip() or len(text) > 512 or text not in context
                for text in relation.claim_evidence)):
            issues.append('business_relationship_ungrounded')
            continue
        if (not relation.source_spans or any(span.end <= span.start or span.end > len(candidate.hit.quote)
                or hashlib.sha256(candidate.hit.quote[span.start:span.end].encode()).hexdigest() != span.sha256
                for span in relation.source_spans)):
            issues.append('business_source_relationship_ungrounded')
            continue
        refs.append(ref.evidence_id)
        if relation.explanation_type == 'unknown' or (
            interpretation.claim_kind == 'recommendation' and relation.explanation_type != 'recommendation') or (
            interpretation.claim_kind == 'inference' and relation.explanation_type == 'recommendation'):
            issues.append('business_explanation_type_unverified')
            continue
        if relation.explanation_type == 'causal' and (candidate.hit.role != 'background' or not metric_ids or candidate.hit.event_time is None
                or not candidate.period.start <= candidate.hit.event_time < candidate.period.end):
            issues.append('business_event_time_unverified')
            continue
        if relation.relationship in {'unknown', 'irrelevant'}:
            issues.append('business_explanation_unverified')
        relationships.append(relation.relationship)
    conflicted = 'contradicts' in relationships
    if conflicted:
        issues.append('business_evidence_conflict')
    elif 'supports' not in relationships:
        issues.append('business_explanation_unverified')
    return tuple(dict.fromkeys(refs)), tuple(dict.fromkeys(issues)), conflicted
