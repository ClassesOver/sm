"""明确签认独立预期及原文；当前可读核验不代替管理员的业务判断。"""

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..reporting.business_knowledge.models import ParsedDocument
from ..reporting.business_knowledge.retrieval import DocumentRevisionRef
from ..reporting.semantics.issue_approval import (
    ApprovedRegressionRef,
    ApprovedSourceSnapshot,
    BasisIssueBusinessApprovalReceipt,
    IssueBusinessApprovalRequest,
    approval_receipt_id,
)
from ..reporting.semantics.models import Identity
from .business_documents import _digest
from .models import ManagementError
from .report_issue_fixes import _document
from .report_issue_regression_checks import _current, check_regression_evidence
from .report_issue_regressions import _issue, _saved
from .report_issue_reviews import _parse
from .repository import report_basis_receipts


async def _saved_approval(service, connection, row, request_id):
    receipt_id = approval_receipt_id(row['basis_id'], row['issue_id'], request_id)
    saved = (await connection.execute(select(report_basis_receipts).where(
        report_basis_receipts.c.scope_id == row['scope_id'], report_basis_receipts.c.basis_id == row['basis_id'],
        report_basis_receipts.c.receipt_id == receipt_id))).mappings().one_or_none()
    if saved is None:
        return None
    receipt = service.bases._receipt(saved, row['basis_id'])
    if not isinstance(receipt, BasisIssueBusinessApprovalReceipt) or receipt.issue_id != row['issue_id']:
        raise ManagementError('management_issue_approval_identity_invalid', '签认回执与本问题身份不一致。', 409)
    return receipt


async def read_approval(service, token, scope, issue_id, request_id):
    TypeAdapter(Identity).validate_python(request_id)
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(connection, token, service.scopes.auth.clock())
        row = await _issue(service, connection, scope, issue_id)
        return await _saved_approval(service, connection, row, request_id)


def _same_request(saved, request):
    if saved is not None and saved.request != request:
        raise ManagementError('management_version_conflict', '此签认请求已用于其他内容，请先读取原回执。', 409)
    return saved


async def _sources(evidence, connection, scope_id, request):
    snapshots = []
    for document_id, revision in sorted({(item.document_id, item.revision) for item in request.sources}):
        await _document(connection, scope_id, document_id, revision)
        row, = await evidence._rows(connection, scope_id,
            (DocumentRevisionRef(document_id=document_id, revision=revision),))
        parsed = ParsedDocument.model_validate(row['parse_receipt'])
        for source in request.sources:
            if (source.document_id, source.revision) == (document_id, revision) and not any(
                    item.locator == source.locator and source.quote in item.text for item in parsed.fragments):
                raise ManagementError('management_issue_approval_source_mismatch', '预期来源的原文摘录或精确位置与已解析原件不符。', 409)
        snapshots.append(ApprovedSourceSnapshot(document_id=document_id, revision=revision,
            state_version=row['state_version'], sha256=row['original_hash'], size=row['size_bytes'],
            metadata_hash=row['content_hash'], parse_hash=_digest(parsed.model_dump(mode='json', by_alias=True))))
    return tuple(snapshots)


async def approve_expectations(service, token, scope, issue_id, payload, *, runtime):
    request = _parse(IssueBusinessApprovalRequest, payload)
    actor = await service.scopes.actor(token, scope)
    # 先恢复已提交结果；原件后来撤销不改写历史签认，也不触发再次签认。
    async with service.scopes.write_transaction(actor) as connection:
        row = await _issue(service, connection, scope, issue_id)
        saved = _same_request(await _saved_approval(service, connection, row, request.request_id), request)
        if saved is not None:
            return saved
        await _current(service, connection, scope, issue_id, request)
    evidence = getattr(runtime, 'business_evidence_service', None)
    if evidence is None:
        raise ManagementError('management_issue_original_check_unavailable', '尚未配置可信原件服务，不能签认预期来源。', 503)
    async with service.scopes.write_transaction(actor) as connection:
        row, record = await _current(service, connection, scope, issue_id, request)
        sources = await _sources(evidence, connection, row['scope_id'], request)
        regressions = []
        for receipt_id in request.regression_receipt_ids:
            regression = await _saved(service, connection, row, receipt_id)
            if regression is None:
                raise ManagementError('management_issue_regression_not_found', '本问题未登记所选回归。', 409)
            regressions.append(ApprovedRegressionRef(receipt_id=receipt_id,
                content_hash=_digest(regression.model_dump(mode='json', by_alias=True))))
    # 实际文件读取不占管理事务；提交时重读审核/解析状态及问题版本。
    for source in sources:
        await evidence.documents.read_original(token, scope, source.document_id, source.revision)
    checked = await check_regression_evidence(service, token, scope, issue_id,
        {'expectedIssueVersion': request.expected_issue_version, 'regressionReceiptIds': list(request.regression_receipt_ids)}, runtime=runtime)
    if not checked['regressionEvidenceReady']:
        raise ManagementError('management_issue_approval_regression_unavailable', '所选回归当前未全部通过或不能复核，不能签认其预期。', 409)
    receipt = BasisIssueBusinessApprovalReceipt(receipt_id=approval_receipt_id(row['basis_id'], issue_id, request.request_id),
        basis_id=row['basis_id'], issue_id=issue_id, request=request, corrected_versions=record.review.corrected_versions,
        regressions=tuple(regressions), sources=sources, approved_by_account_id=actor.account_id,
        approved_by_username=actor.username, created_at=service.scopes.auth.clock())
    async with service.scopes.write_transaction(actor) as connection:
        row = await _issue(service, connection, scope, issue_id)
        saved = _same_request(await _saved_approval(service, connection, row, request.request_id), request)
        if saved is not None:
            return saved
        _, current = await _current(service, connection, scope, issue_id, request)
        if current != record or await _sources(evidence, connection, row['scope_id'], request) != sources:
            raise ManagementError('management_version_conflict', '签认期间问题、原件审核或解析身份已变化，请重新核对。', 409)
        body = receipt.model_dump(mode='json', by_alias=True)
        inserted = (await connection.execute(insert(report_basis_receipts).values(scope_id=row['scope_id'],
            basis_id=receipt.basis_id, receipt_id=receipt.receipt_id, report_revision=receipt.report_revision,
            document=body, content_hash=_digest(body), created_at=receipt.created_at)
            .on_conflict_do_nothing().returning(report_basis_receipts.c.receipt_id))).scalar_one_or_none()
        if inserted is None:
            return _same_request(await _saved_approval(service, connection, row, request.request_id), request)
        await service.scopes.audit(connection, actor, 'report_issue_expectations_approved', {
            'issueId': issue_id, 'receiptId': receipt.receipt_id, 'issueVersion': request.expected_issue_version,
            'regressionReceiptIds': list(request.regression_receipt_ids),
            'approvedByAccountId': actor.account_id, 'approvalScope': receipt.approval_scope})
    return receipt
