"""管理员用不可变计算回执和实际CSV核验预期；不自动关闭问题或重算报告。"""

from agno.run import RunContext
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..reporting.models import ReportingError
from ..reporting.semantics.basis import BasisCalculationReceipt
from ..reporting.semantics.compiler import compile_metric
from ..reporting.semantics.issue_regression import (
    BasisIssueRegressionReceipt,
    IssueRegressionRequest,
    RegressionComparison,
    regression_receipt_id,
)
from ..reporting.semantics.snapshot_replay import replay_metric_calculation
from ..reporting.workflow.scope import ReportingWorkflowScope, reporting_scope_keys
from .business_documents import _digest
from .models import ManagementError
from .report_issue_fixes import basis_version_references, validate_fix_versions
from .report_issue_reviews import IssueRecord, _parse
from .repository import report_basis_receipts, report_issue_reviews, runtime_snapshots


async def _issue(service, connection, scope, issue_id):
    scope_id = (await service.scopes.require_registered(connection, scope))['id']
    row = (await connection.execute(select(report_issue_reviews).where(
        report_issue_reviews.c.scope_id == scope_id, report_issue_reviews.c.issue_id == issue_id))).mappings().one_or_none()
    if row is None:
        raise ManagementError('management_issue_not_found', '该组织未登记此报告问题。', 404)
    service._public(row)
    return row


async def _saved(service, connection, row, receipt_id):
    saved = (await connection.execute(select(report_basis_receipts).where(
        report_basis_receipts.c.scope_id == row['scope_id'], report_basis_receipts.c.basis_id == row['basis_id'],
        report_basis_receipts.c.receipt_id == receipt_id))).mappings().one_or_none()
    if saved is None:
        return None
    result = service.bases._receipt(saved, row['basis_id'])
    if not isinstance(result, BasisIssueRegressionReceipt) or result.issue_id != row['issue_id']:
        raise ManagementError('management_issue_regression_identity_invalid', '回归记录不属于当前问题。', 409)
    return result


async def read_regression(service, token, scope, issue_id, receipt_id):
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(connection, token, service.scopes.auth.clock())
        row = await _issue(service, connection, scope, issue_id)
        return await _saved(service, connection, row, receipt_id)


async def list_regressions(service, token, scope, issue_id, *, limit=50, after=None, request_id=None):
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(connection, token, service.scopes.auth.clock())
        row = await _issue(service, connection, scope, issue_id)
        query = select(report_basis_receipts).where(
            report_basis_receipts.c.scope_id == row['scope_id'],
            report_basis_receipts.c.basis_id == row['basis_id'],
            report_basis_receipts.c.report_revision == 'issue-regression-verification',
            report_basis_receipts.c.document['issueId'].as_string() == issue_id)
        if after is not None:
            query = query.where(report_basis_receipts.c.receipt_id > after)
        if request_id is not None:
            query = query.where(report_basis_receipts.c.receipt_id == regression_receipt_id(row['basis_id'], issue_id, request_id))
        rows = (await connection.execute(query.order_by(report_basis_receipts.c.receipt_id).limit(limit + 1))).mappings().all()
        items = []
        for saved in rows[:limit]:
            result = service.bases._receipt(saved, row['basis_id'])
            if not isinstance(result, BasisIssueRegressionReceipt) or result.issue_id != issue_id:
                raise ManagementError('management_issue_regression_identity_invalid', '回归记录不属于当前问题。', 409)
            items.append(result.model_dump(mode='json', by_alias=True))
        return {'items': items, 'nextCursor': rows[limit - 1]['receipt_id'] if len(rows) > limit else None}


async def _prepare(service, connection, scope, issue_id, request):
    row = await _issue(service, connection, scope, issue_id)
    record = IssueRecord.model_validate(row['document'])
    if row['version'] != request.expected_issue_version or row['status'] != 'accepted' or not record.review.corrected_versions:
        raise ManagementError('management_version_conflict', '问题已变化或尚未关联正式修复版本，请先读回核对。', 409)
    receipt_id = regression_receipt_id(row['basis_id'], issue_id, request.request_id)
    saved = await _saved(service, connection, row, receipt_id)
    if saved is not None:
        if saved.request != request or saved.corrected_versions != record.review.corrected_versions:
            raise ManagementError('management_version_conflict', '原回归请求已登记其他内容，请读取原结果。', 409)
        return row, record, None, None, None, saved
    await validate_fix_versions(service, connection, scope, row['basis_id'], record, record.review.corrected_versions)
    identity, basis, calculation = await _target_calculation(service, connection, row, record,
        request.target_run_id, request.target_report_revision, request.calculation_receipt_id)
    return row, record, identity, basis, calculation, None


async def _target_calculation(service, connection, row, record, run_id, report_revision, receipt_id):
    identity = (await connection.execute(select(runtime_snapshots).where(runtime_snapshots.c.scope_id == row['scope_id'],
        runtime_snapshots.c.run_id == run_id))).mappings().one_or_none()
    if identity is None:
        raise ManagementError('management_issue_regression_scope_mismatch', '目标计算不属于当前组织可信运行。', 403)
    basis_row = await service.bases._basis_row(connection, row['scope_id'], run_id)
    if basis_row is None:
        raise ManagementError('management_issue_regression_missing', '目标运行尚无已登记计算依据。', 409)
    basis = await service.bases._restore(connection, identity, basis_row)
    versions = await basis_version_references(connection, basis)
    if any((ref.asset_type, ref.asset_id, ref.revision) not in versions for ref in record.review.corrected_versions):
        raise ManagementError('management_issue_regression_fix_mismatch', '目标计算依据未采用本问题关联的全部精确修复版本。', 409)
    calculation_row = (await connection.execute(select(report_basis_receipts).where(
        report_basis_receipts.c.scope_id == row['scope_id'], report_basis_receipts.c.basis_id == basis.id,
        report_basis_receipts.c.receipt_id == receipt_id))).mappings().one_or_none()
    if calculation_row is None:
        raise ManagementError('management_issue_regression_missing', '目标计算回执尚未登记。', 409)
    calculation = service.bases._receipt(calculation_row, basis.id)
    if not isinstance(calculation, BasisCalculationReceipt) or calculation.report_revision != report_revision:
        raise ManagementError('management_issue_regression_identity_invalid', '目标修订或回执类型不匹配。', 409)
    return identity, basis, calculation


async def verify_regression(service, token, scope, issue_id, payload, *, runtime):
    request = _parse(IssueRegressionRequest, payload)
    actor = await service.scopes.actor(token, scope)
    async with service.scopes.write_transaction(actor) as connection:
        row, record, identity, basis, calculation, saved = await _prepare(service, connection, scope, issue_id, request)
        if saved is not None:
            return saved
    comparisons, covered = await _replay_registered_calculation(service, scope, request, record, identity, basis, calculation,
        runtime=runtime)
    receipt = BasisIssueRegressionReceipt(receipt_id=regression_receipt_id(row['basis_id'], issue_id, request.request_id),
        basis_id=row['basis_id'], issue_id=issue_id, request=request, corrected_versions=record.review.corrected_versions,
        target_basis_id=basis.id, target_basis_hash=_digest(basis.model_dump(mode='json', by_alias=True)),
        calculation_hash=_digest(calculation.model_dump(mode='json', by_alias=True)), covered_metric_versions=covered,
        snapshot_files=tuple(item.file for item in calculation.datasets), comparisons=comparisons,
        status='passed' if all(item.matches for item in comparisons) else 'failed',
        verifier_build=runtime.report_build_identity, created_at=service.scopes.auth.clock())
    async with service.scopes.write_transaction(actor) as connection:
        current, _, _, _, _, saved = await _prepare(service, connection, scope, issue_id, request)
        if saved is not None:
            return saved
        body = receipt.model_dump(mode='json', by_alias=True)
        inserted = (await connection.execute(insert(report_basis_receipts).values(scope_id=current['scope_id'],
            basis_id=receipt.basis_id, receipt_id=receipt.receipt_id, report_revision=receipt.report_revision,
            document=body, content_hash=_digest(body), created_at=receipt.created_at)
            .on_conflict_do_nothing().returning(report_basis_receipts.c.receipt_id))).scalar_one_or_none()
        if inserted is None:
            saved = await _saved(service, connection, current, receipt.receipt_id)
            if saved.request != request or saved.corrected_versions != receipt.corrected_versions:
                raise ManagementError('management_version_conflict', '该回归请求已有其他结果，请读取原记录。', 409)
            return saved
        await service.scopes.audit(connection, actor, 'report_issue_regression_verified', {'issueId': issue_id,
            'receiptId': receipt.receipt_id, 'caseId': request.case_id, 'issueVersion': request.expected_issue_version,
            'targetBasisId': basis.id, 'calculationReceiptId': request.calculation_receipt_id, 'status': receipt.status})
    return receipt


async def _replay_registered_calculation(service, scope, request, record, identity, basis, calculation, *, runtime):
    if (runtime is None or runtime.report_build_identity is None or runtime.configuration_provider is None
            or runtime.datasets is None):
        raise ManagementError('management_issue_regression_unavailable', '快照回归尚缺可信构建或工作区配置。', 503)
    if calculation.workspace is None:
        raise ManagementError('management_issue_regression_missing', '目标计算缺少实际CSV工作区。', 409)
    execution = await service.bases.load_execution_context(request.target_run_id, scope,
        user_id=identity['user_id'], thread_id=identity['thread_id'], vault=runtime.configuration_provider.vault)
    if execution.basis != basis:
        raise ManagementError('management_issue_regression_identity_invalid', '回归期间目标计算依据发生变化。', 409)
    keys = reporting_scope_keys(database=scope.database, company_id=scope.company_id, user_id=identity['user_id'],
        thread_id=identity['thread_id'], run_id=request.target_run_id)
    workflow_scope = ReportingWorkflowScope(run_id=request.target_run_id, external_run_id=request.target_run_id,
        session_id=calculation.workspace.session_id, caller_thread_id=identity['thread_id'], user_id=identity['user_id'],
        database=scope.database, company_id=scope.company_id, thread_lease_key=keys.thread_lease_key, workspace_key=keys.workspace_key)
    context = RunContext(run_id=request.target_run_id, session_id=keys.workspace_key, session_state={})
    binding = service.bases._workspace_binding(request.target_run_id, scope, identity['user_id'], identity['thread_id'],
        runtime.datasets, context, workflow_scope)
    if binding != calculation.workspace:
        raise ManagementError('management_issue_regression_scope_mismatch', '回归工作区与登记CSV不一致。', 403)
    catalog = tuple(table for metadata in execution.metadata.values() for table in metadata.tables)
    try:
        plan = compile_metric(calculation.request, execution.policy, execution.metrics, catalog)
        fixed = {(ref.asset_id, ref.revision) for ref in record.review.corrected_versions if ref.asset_type == 'metric'}
        covered = tuple(metric.version_ref() for metric in plan.metrics if (metric.id, metric.revision) in fixed)
        if fixed and not covered:
            raise ManagementError('management_issue_regression_fix_mismatch', '目标计算没有覆盖本问题的修复指标。', 409)
        actual = await replay_metric_calculation(plan, calculation, execution.sources, datasets=runtime.datasets, run_context=context)
    except ReportingError as error:
        raise ManagementError(error.code, error.message, 409) from error
    roots = {item.fact_id: item for item in actual.results if item.metric_version == calculation.request.metric_version}
    if set(roots) != {item.fact_id for item in request.assertions}:
        raise ManagementError('management_issue_regression_incomplete', '预期断言必须完整覆盖目标指标的全部分组事实，不能选择性通过。', 409)
    comparisons = tuple(RegressionComparison(assertion=item, actual=roots[item.fact_id], matches=item.matches(roots[item.fact_id]))
        for item in request.assertions)
    return comparisons, covered
