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


def knowledge_source_presentations(index, supports, current):
    """复用本次授权候选，逐声明核对完整引用；可访问不自动获得语义支持。"""
    from ..semantics.models import ClaimSupport
    from .claim_models import KnowledgeSourcePresentation

    supported = {item.subject_id: item for item in map(ClaimSupport.model_validate, supports)}
    entries = []
    for subject in index.subject_bindings:
        binding = subject.narrative_reference or subject.number_reference
        receipt = binding.semantic_receipt if binding else None
        if receipt is None:
            continue
        for ref in receipt.knowledge_references:
            candidate = current.get(ref.evidence_id)
            valid = (candidate is not None and candidate.reference == ref
                and ref.basis_id == index.report_basis_id and ref.section_code == subject.locator.section_id)
            if valid:
                actual = candidate_for_hit(basis_id=ref.basis_id, section_code=ref.section_code,
                    receipt_id=ref.receipt_id, release_id=ref.release_id, period=candidate.period, hit=candidate.hit)
                valid = actual.reference == ref
            values = dict(subject_id=subject.subject_id, evidence_id=ref.evidence_id,
                available=bool(valid), support_status='unverified')
            if valid:
                hit = candidate.hit
                support = supported.get(subject.subject_id)
                values.update(title=hit.title, document_revision=hit.revision, role=hit.role,
                    locator=hit.locator, quote=hit.quote, period=candidate.period,
                    recorded_at=hit.recorded_at, event_time=hit.event_time,
                    support_status=support.support_status if support and ref.evidence_id in support.evidence_refs else 'unverified')
            else:
                values['issue_codes'] = ('business_evidence_unavailable',)
            entries.append(KnowledgeSourcePresentation(**values).model_dump(mode='json', by_alias=True))
    return entries


def knowledge_source_summary(raw):
    """只把已核验展示模型转成人读文字，原件坐标不得当作报告页码。"""
    from .claim_models import KnowledgeSourcePresentation

    item = KnowledgeSourcePresentation.model_validate(raw)
    status = {'supported': '已获支持', 'unverified': '待核实', 'conflicted': '存在反证'}[item.support_status]
    if not item.available:
        return ['原文未能按当前权限核验（材料撤销、身份变化或核验不可用），未附旧摘录。',
            '解释支持状态：待核实']
    locator = item.locator
    location = {
        'text_lines': f'原件第{locator.line_start}–{locator.line_end}行',
        'pdf_page': f'原件第{locator.page}页',
        'docx_paragraph': f'原件第{locator.paragraph}段',
        'docx_table_cell': f'原件第{locator.table}表，第{locator.row}行第{locator.column}列',
    }[locator.kind]
    return [f'登记引用：{item.title}（第{item.document_revision}版）',
        '用途：' + {'rule_evidence': '规则依据', 'background': '背景资料'}[item.role],
        f'原文定位：{location}', f'原文摘录：{item.quote}',
        f'请求期间：[{item.period.start}, {item.period.end})（含起日、不含止日）',
        f'登记时间：{item.recorded_at.isoformat()}；事件时间：{item.event_time or "未登记"}',
        f'解释支持状态：{status}；原文可访问不等于解释已获支持。']
