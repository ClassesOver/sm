"""当前证据核验后原子关闭；重复请求仅恢复不可变原结果。"""

from pydantic import TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from ..reporting.semantics.issue_resolution import (
    BasisIssueResolutionReceipt,
    IssueResolutionRequest,
    ResolutionEvidence,
    resolution_receipt_id,
)
from ..reporting.semantics.models import Identity
from .business_documents import _digest
from .models import ManagementError
from .report_issue_regression_checks import _current
from .report_issue_regressions import _issue, _saved
from .report_issue_resolution_evidence import (
    IssueResolutionCheckRequest,
    _approval_snapshot,
    _original_snapshots,
    check_resolution_evidence,
)
from .report_issue_reviews import _parse, report_revision_identity
from .repository import business_document_revisions, report_basis_receipts, report_issue_reviews


async def _saved_resolution(service, connection, row, request_id):
    receipt_id = resolution_receipt_id(row['basis_id'], row['issue_id'], request_id)
    saved = (await connection.execute(select(report_basis_receipts).where(
        report_basis_receipts.c.scope_id == row['scope_id'], report_basis_receipts.c.basis_id == row['basis_id'],
        report_basis_receipts.c.receipt_id == receipt_id))).mappings().one_or_none()
    if saved is None:
        return None
    receipt = service.bases._receipt(saved, row['basis_id'])
    if not isinstance(receipt, BasisIssueResolutionReceipt) or receipt.issue_id != row['issue_id']:
        raise ManagementError('management_issue_resolution_identity_invalid', '关闭回执与本问题不一致。', 409)
    return receipt


def _same(saved, request):
    if saved is not None and saved.request != request:
        raise ManagementError('management_version_conflict', '此关闭请求已用于其他内容，请读取原结果。', 409)
    return saved


async def read_resolution(service, token, scope, issue_id, request_id):
    TypeAdapter(Identity).validate_python(request_id)
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(connection, token, service.scopes.auth.clock())
        return await _saved_resolution(service, connection, await _issue(service, connection, scope, issue_id), request_id)


async def resolve_issue(service, token, scope, issue_id, payload, *, runtime):
    request = _parse(IssueResolutionRequest, payload)
    actor = await service.scopes.actor(token, scope)
    async with service.scopes.write_transaction(actor) as connection:
        row = await _issue(service, connection, scope, issue_id)
        saved = _same(await _saved_resolution(service, connection, row, request.request_id), request)
        if saved is not None:
            return saved
        row, record = await _current(service, connection, scope, issue_id, request)
    check_request = IssueResolutionCheckRequest(expected_issue_version=request.expected_issue_version,
        regression_receipt_ids=request.regression_receipt_ids, business_approval_request_id=request.business_approval_request_id)
    try:
        checked = await check_resolution_evidence(service, token, scope, issue_id,
            check_request.model_dump(mode='json', by_alias=True), runtime=runtime)
    except ManagementError as error:
        if error.status == 409:
            # 同请求并发提交可能先完成；只读精确结果，不重试检查或写入。
            saved = _same(await read_resolution(service, token, scope, issue_id, request.request_id), request)
            if saved is not None:
                return saved
        raise
    required = ['regressionEvidenceReady', 'originalEvidenceReady', 'businessApprovalReady']
    if request.mode == 'recalculated':
        required += ['deliveryReady', 'factPresentationReady']
    if not all(checked[key] for key in required):
        raise ManagementError('management_issue_resolution_unverified', '关闭所需当前证据不齐全，请先核对具体失败原因。', 409)
    originals = {(item['documentId'], item['revision']): {key: value for key, value in item.items()
        if key not in ('status', 'issues')} for item in checked['originalChecks']}
    evidence_service = runtime.business_evidence_service
    async with service.scopes.write_transaction(actor) as connection:
        # 串行化同一问题的关闭；等待并发提交后先恢复原结果，而非再次裁定。
        await connection.execute(select(report_issue_reviews.c.issue_id).where(
            report_issue_reviews.c.scope_id == row['scope_id'], report_issue_reviews.c.issue_id == issue_id).with_for_update())
        row = await _issue(service, connection, scope, issue_id)
        saved = _same(await _saved_resolution(service, connection, row, request.request_id), request)
        if saved is not None:
            return saved
        _, current = await _current(service, connection, scope, issue_id, request)
        # 锁定已核验原件的审核行，阻止复核与最终写入之间的撤销覆盖。
        for document_id, revision in sorted(originals):
            await connection.execute(select(business_document_revisions.c.document_id).where(
                business_document_revisions.c.scope_id == row['scope_id'],
                business_document_revisions.c.document_id == document_id,
                business_document_revisions.c.revision == revision).with_for_update())
        approval_check, approval = await _approval_snapshot(service, evidence_service, connection, row, current, check_request)
        if (current != record or approval is None or approval_check['status'] != 'prepared'
                or await _original_snapshots(evidence_service, connection, row['scope_id'], originals) != originals):
            raise ManagementError('management_version_conflict', '关闭期间问题或签认来源发生变化，请重新核对。', 409)
        regressions = [await _saved(service, connection, row, item) for item in request.regression_receipt_ids]
        if any(item is None for item in regressions):
            raise ManagementError('management_issue_resolution_unverified', '关闭所选回归不可恢复。', 409)
        revisions = {report_revision_identity(item['targetRunId'], item['outputRevision'])
            for item in checked['reportRelationships'] if item.get('deliveryVerified')}
        if request.mode == 'recalculated' and len(revisions) != 1:
            raise ManagementError('management_issue_resolution_unverified', '请选择同一新报告修订的完整回归。', 409)
        new_revision = next(iter(revisions)) if request.mode == 'recalculated' else None
        receipt = BasisIssueResolutionReceipt(receipt_id=resolution_receipt_id(row['basis_id'], issue_id, request.request_id),
            basis_id=row['basis_id'], issue_id=issue_id, request=request, corrected_versions=current.review.corrected_versions,
            evidence=ResolutionEvidence(checked_at=checked['checkedAt'], regression_evidence_ready=True,
                original_evidence_ready=True, business_approval_ready=True, delivery_ready=checked['deliveryReady'],
                fact_presentation_ready=checked['factPresentationReady'], approval_receipt_id=approval.receipt_id,
                approval_hash=_digest(approval.model_dump(mode='json', by_alias=True)),
                regressions=[next(item for item in approval.regressions if item.receipt_id == identity)
                    for identity in request.regression_receipt_ids],
                originals=[{key: value for key, value in item.items() if key != 'title'} for item in originals.values()],
                deliveries=[{'regressionReceiptId': item['receiptId'], 'targetRunId': item['targetRunId'],
                    'targetBasisId': item['targetBasisId'], 'adoptionReceiptId': item['adoptionReceiptId'],
                    'registrationHash': item['registrationHash'], 'outputRevision': item['outputRevision'],
                    'validationPassed': item['validationPassed'], 'artifacts': item['deliveryArtifacts']}
                    for item in checked['reportRelationships'] if item.get('deliveryVerified')],
                new_report_revision=new_revision), resolved_issue_version=row['version'] + 1,
            resolved_by_account_id=actor.account_id, resolved_by_username=actor.username, created_at=service.scopes.auth.clock())
        review = current.review.model_copy(update={'status': 'resolved', 'decision_reason': request.decision_reason,
            'regression_case_ids': tuple(item.request.case_id for item in regressions),
            'new_report_revision': new_revision, 'not_recalculated_reason': request.not_recalculated_reason})
        document = current.model_copy(update={'review': review, 'resolution_request_id': request.request_id}).model_dump(mode='json', by_alias=True)
        # 使用同一事务保存不可变处理证据、CAS状态及审计，任一步失败整体回滚。
        body = receipt.model_dump(mode='json', by_alias=True)
        await connection.execute(insert(report_basis_receipts).values(scope_id=row['scope_id'], basis_id=row['basis_id'],
            receipt_id=receipt.receipt_id, report_revision=receipt.report_revision, document=body,
            content_hash=_digest(body), created_at=receipt.created_at))
        changed = (await connection.execute(update(report_issue_reviews).where(
            report_issue_reviews.c.scope_id == row['scope_id'], report_issue_reviews.c.issue_id == issue_id,
            report_issue_reviews.c.version == request.expected_issue_version, report_issue_reviews.c.status == 'accepted')
            .values(version=receipt.resolved_issue_version, status='resolved', document=document, updated_at=receipt.created_at)
            .returning(report_issue_reviews.c.version))).scalar_one_or_none()
        if changed is None:
            raise ManagementError('management_version_conflict', '关闭期间问题已变化，请先读回。', 409)
        await service.scopes.audit(connection, actor, 'report_issue_resolved', {'issueId': issue_id,
            'receiptId': receipt.receipt_id, 'previousVersion': row['version'], 'version': changed,
            'mode': request.mode, 'approvalReceiptId': approval.receipt_id,
            'requestHash': _digest(request.model_dump(mode='json', by_alias=True))})
    return receipt
