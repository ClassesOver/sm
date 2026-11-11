"""关闭前重新核验回归当前证据；只读检查不构成业务签认或关闭决定。"""

from pydantic import Field, model_validator

from ..reporting.semantics.models import Identity, SemanticModel
from .business_documents import _digest
from .models import ManagementError
from .report_issue_fixes import validate_fix_versions
from .report_issue_regressions import (
    _issue,
    _replay_registered_calculation,
    _saved,
    _target_calculation,
)
from .report_issue_reviews import IssueRecord, _parse


class IssueRegressionCheckRequest(SemanticModel):
    expected_issue_version: int = Field(ge=1, strict=True)
    regression_receipt_ids: tuple[Identity, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode='after')
    def distinct_receipts(self):
        if len(set(self.regression_receipt_ids)) != len(self.regression_receipt_ids):
            raise ValueError('核验回执不能重复')
        return self


async def _current(service, connection, scope, issue_id, request):
    row = await _issue(service, connection, scope, issue_id)
    record = IssueRecord.model_validate(row['document'])
    if row['version'] != request.expected_issue_version or row['status'] != 'accepted' or not record.review.corrected_versions:
        raise ManagementError('management_version_conflict', '问题已变化或缺少正式修复引用，请重新核对。', 409)
    await validate_fix_versions(service, connection, scope, row['basis_id'], record, record.review.corrected_versions)
    return row, record


async def check_regression_evidence(service, token, scope, issue_id, payload, *, runtime):
    request = _parse(IssueRegressionCheckRequest, payload)
    prepared, checks = [], []
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(connection, token, service.scopes.auth.clock())
        row, record = await _current(service, connection, scope, issue_id, request)
        for receipt_id in request.regression_receipt_ids:
            check = {'receiptId': receipt_id, 'status': 'failed', 'issues': []}
            checks.append(check)
            try:
                receipt = await _saved(service, connection, row, receipt_id)
                if receipt is None:
                    raise ManagementError('management_issue_regression_not_found', '本问题未登记此回归核验。', 409)
                if receipt.status != 'passed':
                    raise ManagementError('management_issue_regression_failed', '原回归未符合预期，不能作为通过证据。', 409)
                if (receipt.corrected_versions != record.review.corrected_versions
                        or receipt.request.expected_issue_version != row['version']):
                    raise ManagementError('management_issue_regression_stale', '回归针对的问题版本或修复引用已变化，须重新明确核验。', 409)
                identity, basis, calculation = await _target_calculation(service, connection, row, record,
                    receipt.request.target_run_id, receipt.request.target_report_revision, receipt.request.calculation_receipt_id)
                if (receipt.target_basis_hash != _digest(basis.model_dump(mode='json', by_alias=True))
                        or receipt.calculation_hash != _digest(calculation.model_dump(mode='json', by_alias=True))
                        or receipt.snapshot_files != tuple(item.file for item in calculation.datasets)):
                    raise ManagementError('management_issue_regression_identity_invalid', '原核验与当前登记计算或文件身份不一致。', 409)
                prepared.append((check, receipt, identity, basis, calculation))
            except ManagementError as error:
                if error.status != 409:
                    raise
                check['issues'].append({'code': error.code, 'message': error.message})
    covered = set()
    for check, receipt, identity, basis, calculation in prepared:
        try:
            comparisons, versions = await _replay_registered_calculation(service, scope, receipt.request, record,
                identity, basis, calculation, runtime=runtime)
            if comparisons != receipt.comparisons or versions != receipt.covered_metric_versions:
                raise ManagementError('management_issue_regression_identity_invalid', '当前复算未重现原回归比较或修复覆盖。', 409)
            check.update(status='passed', targetBasisId=basis.id,
                calculationHash=receipt.calculation_hash, snapshotFiles=[item.model_dump(mode='json', by_alias=True) for item in receipt.snapshot_files])
            covered.update((ref.metric_id, ref.revision) for ref in versions)
        except ManagementError as error:
            if error.status not in (409, 503):
                raise
            check['issues'].append({'code': error.code, 'message': error.message})
    # 文件IO/原生复算不占管理事务；结果返回前重读版本和引用，不能签认旧决定。
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(connection, token, service.scopes.auth.clock())
        _, current = await _current(service, connection, scope, issue_id, request)
        if current != record:
            raise ManagementError('management_version_conflict', '复算期间问题发生变化，请重新核对。', 409)
    required = {(ref.asset_id, ref.revision) for ref in record.review.corrected_versions if ref.asset_type == 'metric'}
    issues = []
    if not required <= covered:
        issues.append({'code': 'management_issue_regression_incomplete', 'message': '通过的回归尚未覆盖全部关联修复指标。'})
    return {'issueId': issue_id, 'issueVersion': request.expected_issue_version,
        'checkedAt': service.scopes.auth.clock().isoformat(), 'checks': checks, 'issues': issues,
        'regressionEvidenceReady': not issues and all(check['status'] == 'passed' for check in checks),
        'businessApproval': 'not_performed', 'issueClosed': False}
