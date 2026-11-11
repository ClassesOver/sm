"""关闭准备的原件和新依据父链核对；父链成立不等于报告已交付。"""

from sqlalchemy import select

from ..reporting.business_knowledge.retrieval import DocumentRevisionRef
from ..reporting.semantics.models import Identity
from .business_documents import _digest
from .models import ManagementError
from .report_issue_business_approvals import _saved_approval, _sources
from .report_issue_delivery_checks import check_adopted_delivery
from .report_issue_fixes import _document, _release
from .report_issue_regression_checks import (
    IssueRegressionCheckRequest,
    _current,
    check_regression_evidence,
)
from .report_issue_regressions import _saved, _target_calculation
from .report_issue_reviews import _parse
from .report_policy_adoption import _read_registered_adoption
from .repository import runtime_snapshots


class IssueResolutionCheckRequest(IssueRegressionCheckRequest):
    business_approval_request_id: Identity | None = None


async def _approval_snapshot(service, evidence, connection, row, record, request):
    check = {'requestId': request.business_approval_request_id, 'status': 'not_selected', 'issues': []}
    if request.business_approval_request_id is None:
        return check, None
    check['status'] = 'unavailable'
    try:
        approval = await _saved_approval(service, connection, row, request.business_approval_request_id)
        if approval is None:
            raise ManagementError('management_issue_approval_not_found', '本问题未登记所选业务预期签认。', 409)
        check.update(receiptId=approval.receipt_id, approvedByAccountId=approval.approved_by_account_id,
            approvedByUsername=approval.approved_by_username, approvedAt=approval.created_at.isoformat(),
            approvalScope=approval.approval_scope)
        if (approval.request.expected_issue_version != row['version']
                or approval.corrected_versions != record.review.corrected_versions
                or set(approval.request.regression_receipt_ids) != set(request.regression_receipt_ids)):
            raise ManagementError('management_issue_approval_stale', '签认的问题版本、修复引用或所选回归不匹配，须重新明确签认。', 409)
        for reference in approval.regressions:
            regression = await _saved(service, connection, row, reference.receipt_id)
            if regression is None or _digest(regression.model_dump(mode='json', by_alias=True)) != reference.content_hash:
                raise ManagementError('management_issue_approval_identity_invalid', '签认绑定的精确回归身份不一致。', 409)
        if await _sources(evidence, connection, row['scope_id'], approval.request) != approval.sources:
            raise ManagementError('management_issue_approval_stale', '签认后的原件审核或解析身份已变化，须重新签认。', 409)
        check['status'] = 'prepared'
        return check, approval
    except ManagementError as error:
        if error.status not in (403, 404, 409):
            raise
        check['issues'].append({'code': error.code, 'message': error.message})
        return check, None


async def _original_snapshots(evidence, connection, scope_id, references):
    result = {}
    for document_id, revision in sorted(references):
        await _document(connection, scope_id, document_id, revision)
        row = (await evidence._rows(connection, scope_id, (DocumentRevisionRef(document_id=document_id, revision=revision),)))[0]
        # 原件登记不可变，审核版本仍会变化；IO后必须核对状态版本。
        result[(document_id, revision)] = {'documentId': document_id, 'revision': revision,
            'title': row['document']['metadata']['title'],
            'stateVersion': row['state_version'], 'sha256': row['original_hash'], 'size': row['size_bytes'],
            'metadataHash': row['content_hash']}
    return result


async def check_resolution_evidence(service, token, scope, issue_id, payload, *, runtime):
    request = _parse(IssueResolutionCheckRequest, payload)
    regression = await check_regression_evidence(service, token, scope, issue_id,
        request.model_dump(mode='json', by_alias=True, exclude={'business_approval_request_id'}), runtime=runtime)
    evidence = getattr(runtime, 'business_evidence_service', None)
    if evidence is None:
        raise ManagementError('management_issue_original_check_unavailable', '尚未配置可信业务原件服务，不能核对当前原件。', 503)
    passed = {item['receiptId'] for item in regression['checks'] if item['status'] == 'passed'}
    relationships, references, deliveries = [], set(), []
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(connection, token, service.scopes.auth.clock())
        row, record = await _current(service, connection, scope, issue_id, request)
        approval_check, approval = await _approval_snapshot(service, evidence, connection, row, record, request)
        if approval is not None:
            references.update((item.document_id, item.revision) for item in approval.sources)
        parent_row = await service.bases._basis_row(connection, row['scope_id'], record.run_id)
        # 原报告运行身份由反馈绑定恢复，不能接受客户端提供的父报告身份。
        identity = (await connection.execute(select(runtime_snapshots).where(
            runtime_snapshots.c.scope_id == row['scope_id'], runtime_snapshots.c.run_id == record.run_id,
            runtime_snapshots.c.user_id == record.submitted_by))).mappings().one_or_none()
        if parent_row is None or identity is None:
            raise ManagementError('management_issue_scope_mismatch', '原问题的可信报告身份不可恢复。', 409)
        parent = await service.bases._restore(connection, identity, parent_row)
        bases = {parent.id: parent}
        for receipt_id in request.regression_receipt_ids:
            if receipt_id not in passed:
                continue
            receipt = await _saved(service, connection, row, receipt_id)
            _, basis, calculation = await _target_calculation(service, connection, row, record, receipt.request.target_run_id,
                receipt.request.target_report_revision, receipt.request.calculation_receipt_id)
            bases[basis.id] = basis
            relationship = {'receiptId': receipt_id, 'targetRunId': basis.run_id, 'targetBasisId': basis.id,
                'parentBasisId': parent.id, 'status': 'unverified', 'deliveryVerified': False, 'issues': []}
            relationships.append(relationship)
            try:
                adoption = await _read_registered_adoption(service.bases, connection, parent, parent_row, scope,
                    record.submitted_by, identity['thread_id'], basis.run_id)
                if adoption is None:
                    raise ManagementError('management_issue_report_relationship_missing', '目标缺少原报告明确采用新口径的登记父链。', 409)
                deliveries.append((relationship, adoption, calculation))
                relationship.update(status='verified', adoptionReceiptId=adoption.receipt_id,
                    registrationHash=_digest(adoption.model_dump(mode='json', by_alias=True)))
            except ManagementError as error:
                if error.status not in (403, 409):
                    raise
                relationship['issues'].append({'code': error.code, 'message': error.message})
        for basis in bases.values():
            for release_id, kind in ((basis.evidence_release_id, 'rule_evidence'), (basis.background_release_id, 'background')):
                if release_id is not None:
                    release = await service.bases._release(connection, row['scope_id'], release_id, kind)
                    references.update((item.reference.document_id, item.reference.revision) for item in release.documents)
        for reference in record.review.corrected_versions:
            if reference.asset_type == 'document':
                references.add((reference.asset_id, reference.revision))
            elif reference.asset_type == 'evidence_release':
                release = await _release(service, connection, row['scope_id'], reference.asset_id)
                references.update((item.reference.document_id, item.reference.revision) for item in release.documents)
        originals = await _original_snapshots(evidence, connection, row['scope_id'], references)
    for relationship, adoption, calculation in deliveries:
        relationship.update(await check_adopted_delivery(runtime, adoption, scope, parent_run_id=record.run_id,
            user_id=record.submitted_by, thread_id=identity['thread_id'], calculation=calculation))
    checks = []
    for (document_id, revision), snapshot in originals.items():
        check = {**snapshot, 'status': 'unavailable', 'issues': []}
        checks.append(check)
        try:
            await evidence.documents.read_original(token, scope, document_id, revision)
            check['status'] = 'readable'
        except ManagementError as error:
            if error.status != 409 and error.code != 'management_document_revoked':
                raise
            check['issues'].append({'code': error.code, 'message': error.message})
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(connection, token, service.scopes.auth.clock())
        _, current = await _current(service, connection, scope, issue_id, request)
        if current != record or await _original_snapshots(evidence, connection, row['scope_id'], references) != originals:
            raise ManagementError('management_version_conflict', '核对期间问题或原件审核状态发生变化，请重新检查。', 409)
        if approval is not None:
            _, current_approval = await _approval_snapshot(service, evidence, connection, row, current, request)
            if current_approval != approval:
                raise ManagementError('management_version_conflict', '核对期间签认来源或身份发生变化，请重新检查。', 409)
    approval_ready = approval is not None and regression['regressionEvidenceReady'] and all(
        item['status'] == 'readable' for item in checks
        if (item['documentId'], item['revision']) in {(source.document_id, source.revision) for source in approval.sources})
    if approval is not None:
        approval_check['status'] = 'verified' if approval_ready else 'unavailable'
        if not approval_ready:
            approval_check['issues'].append({'code': 'management_issue_approval_evidence_unavailable',
                'message': '签认的回归或独立来源本次不可复核，历史签认不能代表当前就绪。'})
    return {**regression, 'checkedAt': service.scopes.auth.clock().isoformat(), 'originalChecks': checks,
        'businessApproval': 'explicitly_approved' if approval_ready else 'not_performed',
        'businessApprovalReady': approval_ready, 'businessApprovalCheck': approval_check,
        'originalEvidenceReady': bool(checks) and all(item['status'] == 'readable' for item in checks),
        'reportRelationships': relationships,
        'deliveryReady': len(relationships) == len(request.regression_receipt_ids) and all(item['status'] == 'verified' and item['deliveryVerified'] for item in relationships),
        'factPresentationReady': len(relationships) == len(request.regression_receipt_ids) and all(
            item.get('factPresentationVerified', False) for item in relationships),
        'issueClosed': False}
