"""把当前逐声明支持结果映射到登记位置；不修改来源正文。"""

from ..semantics.models import ClaimSupport


def claim_support_projection(index, source_sha256, supports):
    resolved = {item.subject_id: item for item in (ClaimSupport.model_validate(item) for item in supports)}
    claims = []
    for subject in index.subject_bindings:
        reference = subject.narrative_reference or subject.number_reference
        if reference is None:
            continue
        support = resolved.get(subject.subject_id)
        receipt = reference.semantic_receipt
        kind = support.kind if support else receipt.interpretation.claim_kind if receipt else 'unknown'
        kind = kind if kind in {'fact', 'inference', 'recommendation'} else 'inference'
        status = support.support_status if support else 'unverified'
        if kind != 'fact' or status != 'supported':
            claims.append({'sectionId': subject.locator.section_id, 'claimId': subject.claim_id,
                'kind': kind, 'supportStatus': status})
    return {'version': 'claim-support-render/1', 'sourceSha256': source_sha256, 'claims': claims}
