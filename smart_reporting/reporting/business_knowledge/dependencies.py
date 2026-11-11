"""按可信报告身份重读知识依赖；登记和原文存在都不等于支持业务结论。"""

from loguru import logger


async def read_knowledge_dependencies(bases, service, **kwargs):
    status, _ = await resolve_knowledge_dependencies(bases, service, **kwargs)
    return status


async def resolve_knowledge_dependencies(bases, service, *, identity, basis_id, dependencies, registration_status):
    result = {'status': 'unavailable', 'interpretationStatus': 'unverified', 'sections': [], 'issueCodes': []}
    if registration_status != 'registered':
        result['issueCodes'] = ['knowledge_registration_unavailable']
        return result, {}
    if bases is None or service is None:
        result['issueCodes'] = ['knowledge_service_unavailable']
        result['sections'] = [{**item.model_dump(mode='json', by_alias=True), 'status': 'unavailable',
            'issueCodes': ['knowledge_service_unavailable']} for item in dependencies]
        return result, {}
    from ..semantics.basis import BasisKnowledgeReceipt

    receipts_by_revision = {}
    try:
        basis = await bases.load_report_basis(**identity)
        if basis.id != basis_id:
            raise ValueError('knowledge_basis_mismatch')
        for dependency in dependencies:
            revision = dependency.report_revision
            if revision not in receipts_by_revision:
                receipts_by_revision[revision] = {
                    item.receipt_id: item for item in await bases.load_basis_receipts(
                        **identity, report_revision=revision) if isinstance(item, BasisKnowledgeReceipt)}
    except Exception as error:  # 依赖读取失败只撤回支持，不妨碍正文保存或导出
        logger.warning('knowledge_dependency_registry_unavailable reason={}', type(error).__name__)
        result['issueCodes'] = ['knowledge_registry_unavailable']
        result['sections'] = [{**item.model_dump(mode='json', by_alias=True), 'status': 'unavailable',
            'issueCodes': result['issueCodes']} for item in dependencies]
        return result, {}
    authorized = {}
    for dependency in dependencies:
        issues, matched, invalid = [], False, False
        section_candidates = {}
        for receipt_id in dependency.receipt_ids:
            try:
                receipt = receipts_by_revision[dependency.report_revision].get(receipt_id)
                if receipt is None or receipt.basis_id != basis_id or receipt.section_code != dependency.section_code:
                    issues.append('knowledge_receipt_identity_invalid')
                    invalid = True
                    continue
                current = await service.revalidate_report(bases, **identity, saved=receipt.evidence)
                original_hits = receipt.evidence.search.hits if receipt.evidence.search else ()
                current_hits = current.search.hits if current.search else ()
                codes = current.issue_codes or (current.search.issue_codes if current.search else ())
                issues.extend(codes)
                if current_hits != original_hits:
                    issues.append('knowledge_dependency_changed')
                    invalid = True
                matched = matched or bool(current_hits)
                from .claims import candidate_for_hit

                for hit in current_hits:
                    if hit not in original_hits:
                        continue
                    candidate = candidate_for_hit(basis_id=basis_id, section_code=dependency.section_code,
                        receipt_id=receipt_id, release_id=current.search.release_id,
                        period=current.search.request.period, hit=hit)
                    section_candidates[candidate.reference.evidence_id] = candidate
            except Exception as error:  # 该回执失败不使用历史片段，其他已独立核验回执保留
                logger.warning('knowledge_dependency_revalidation_unavailable reason={}', type(error).__name__)
                issues.append('knowledge_revalidation_unavailable')
                invalid = True
        status = 'available' if matched and not invalid else 'unavailable'
        # 章节整体缺项不能撤销其他已逐条核验的材料；仅返回身份未变的当前授权命中。
        authorized.update(section_candidates)
        if status == 'unavailable' and not issues:
            issues.append('knowledge_evidence_unavailable')
        result['sections'].append({**dependency.model_dump(mode='json', by_alias=True),
            'status': status, 'issueCodes': list(dict.fromkeys(issues))})
    result['status'] = 'available' if result['sections'] and all(
        item['status'] == 'available' for item in result['sections']) else 'unavailable'
    if not dependencies:
        result['issueCodes'] = ['knowledge_dependencies_not_registered']
    return result, authorized
