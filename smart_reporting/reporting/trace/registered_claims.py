"""正式数据事实的支持关系；不认证缺乏业务证据的解释或建议。"""

from ..semantics.models import ClaimSupport
from .claim_semantics import claim_context, semantic_receipt_status


def registered_claim_support(subject, reference, markdown, detail, reasons, *, knowledge_evidence=None):
    """数值、期间及原始结果身份通过后，再核对正文实际表达的指标与统计方式。"""
    issues = list(reasons)
    issues.extend(reference['entry'].get('issueCodes', ()))
    receipt = subject.number_reference.semantic_receipt
    kind = 'fact'
    evidence_refs, knowledge_conflict = (), False
    if detail['status'] != 'valid' or detail['warnings']:
        issues.append('statement_not_supported')
    if receipt is None or semantic_receipt_status(markdown, receipt.interpretation.claim_id, receipt) != 'interpreted':
        issues.append('claim_interpretation_unavailable')
    else:
        item = receipt.interpretation
        context = claim_context(markdown, item.claim_id, include_previous=receipt.includes_previous,
                                include_section=receipt.includes_section) or ''
        context = (receipt.reviewed_context or context).replace('【当前数值引用】', '')

        def grounded(evidence):
            return bool(evidence) and all(text in context for text in evidence)

        if item.claim_kind in {'fact', 'inference', 'recommendation'}:
            kind = item.claim_kind
        if item.claim_kind == 'unknown' or not grounded(item.kind_evidence):
            issues.append('claim_kind_unverified')
        if kind != 'fact':
            from ..business_knowledge.claims import knowledge_support

            evidence_refs, knowledge_issues, knowledge_conflict = knowledge_support(
                subject, item, receipt, context, knowledge_evidence or {}, reference)
            issues.extend(knowledge_issues)
        expected = reference['entry']['metricVersion']
        if item.metric_version is None or not grounded(item.metric_evidence):
            issues.append('claim_metric_unverified')
        elif item.metric_version.model_dump(by_alias=True) != expected:
            issues.append('claim_metric_conflict')
        # 正式公式没有均值操作，不能把已计算合计重新解释成期间平均。
        definition = reference['metric_definition']
        statistic = 'other' if definition['kind'] == 'ratio' else 'period_total'
        if item.statistic == 'unknown' or not grounded(item.statistic_evidence):
            issues.append('claim_statistic_unverified')
        elif item.statistic != statistic:
            issues.append('claim_statistic_conflict')
    status = 'unverified' if issues else 'supported'
    if knowledge_conflict or any(code in issues for code in ('claim_metric_conflict', 'claim_statistic_conflict')):
        status = 'conflicted'
    return ClaimSupport(subject_id=subject.subject_id, kind=kind,
        fact_refs=tuple(ref.fact_key for ref in subject.fact_refs), evidence_refs=evidence_refs, support_status=status), tuple(dict.fromkeys(issues))


def registered_narrative_support(subject, markdown, *, basis_id, knowledge_evidence):
    """纯文字声明仍需当前授权及独立关系复核，不作为计算事实。"""
    from ..business_knowledge.claims import knowledge_support
    from .semantic_bindings import statement_fingerprints

    narrative = subject.narrative_reference
    receipt = narrative.semantic_receipt
    issues, refs, conflict = [], (), False
    kind = 'inference'
    if narrative.basis_id != basis_id:
        issues.append('claim_basis_mismatch')
    if statement_fingerprints(markdown, (narrative.claim_id,))[narrative.claim_id] != narrative.statement_sha256:
        issues.append('statement_changed')
    if receipt is None or semantic_receipt_status(markdown, narrative.claim_id, receipt) != 'interpreted':
        issues.append('claim_interpretation_unavailable')
    else:
        item = receipt.interpretation
        if item.claim_kind in {'fact', 'inference', 'recommendation'}:
            kind = item.claim_kind
        context = claim_context(markdown, narrative.claim_id) or ''
        if item.claim_kind == 'unknown' or not item.kind_evidence or any(text not in context for text in item.kind_evidence):
            issues.append('claim_kind_unverified')
        if kind == 'fact':
            issues.append('registered_result_unavailable')
        if any(relation.explanation_type == 'causal' for relation in item.knowledge_relations):
            issues.append('registered_observation_unavailable')
        reference = {'period': narrative.period.model_dump(mode='json'), 'entry': {
            'metricVersion': {'metricId': item.metric_version.metric_id if item.metric_version else None}}}
        refs, knowledge_issues, conflict = knowledge_support(subject, item, receipt, context,
            knowledge_evidence, reference)
        issues.extend(knowledge_issues)
        if any(ref.basis_id != basis_id for ref in receipt.knowledge_references):
            refs, conflict = (), False
            issues.append('claim_basis_mismatch')
    status = 'conflicted' if conflict else 'unverified' if issues else 'supported'
    return ClaimSupport(subject_id=subject.subject_id, kind=kind, evidence_refs=refs,
        support_status=status), tuple(dict.fromkeys(issues))
