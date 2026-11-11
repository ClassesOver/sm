"""浏览可信运行中已登记的计算，预期由管理员独立填写；不读取实际CSV。"""

import json

from sqlalchemy import and_, select, tuple_

from .models import ManagementError
from .report_issue_fixes import validate_fix_versions
from .report_issue_regressions import _issue, _target_calculation
from .report_issue_reviews import IssueRecord
from .repository import report_bases, report_basis_receipts


async def list_regression_targets(service, token, scope, issue_id, *, query='', limit=50, after=None):
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(connection, token, service.scopes.auth.clock())
        row = await _issue(service, connection, scope, issue_id)
        record = IssueRecord.model_validate(row['document'])
        if row['status'] != 'accepted' or not record.review.corrected_versions:
            raise ManagementError('management_version_conflict', '先采纳问题并关联正式修复版本，再选择回归计算。', 409)
        await validate_fix_versions(service, connection, scope, row['basis_id'], record, record.review.corrected_versions)
        receipts, bases = report_basis_receipts, report_bases
        statement = select(receipts, bases.c.run_id.label('target_run_id')).join(bases, and_(
            bases.c.scope_id == receipts.c.scope_id, bases.c.basis_id == receipts.c.basis_id)).where(
                receipts.c.scope_id == row['scope_id'], receipts.c.document['kind'].as_string() == 'metric_calculation')
        if query:
            statement = statement.where(bases.c.run_id.contains(query, autoescape=True)
                | bases.c.document['requestSummary']['goal'].as_string().contains(query, autoescape=True))
        if after is not None:
            try:
                cursor = json.loads(after)
                if not isinstance(cursor, list) or len(cursor) != 2 or not all(isinstance(item, str) and item for item in cursor):
                    raise ValueError('invalid_cursor')
            except (ValueError, TypeError):
                raise ManagementError('management_issue_cursor_invalid', '计算分页游标无效，请重新读取。', 422) from None
            statement = statement.where(tuple_(receipts.c.basis_id, receipts.c.receipt_id) > tuple(cursor))
        rows = (await connection.execute(statement.order_by(receipts.c.basis_id, receipts.c.receipt_id).limit(limit + 1))).mappings().all()
        items = []
        for candidate in rows[:limit]:
            item = {'targetRunId': candidate['target_run_id'], 'targetReportRevision': candidate['report_revision'],
                'calculationReceiptId': candidate['receipt_id'], 'basisId': candidate['basis_id'],
                'available': False, 'reason': '', 'facts': []}
            try:
                _, basis, calculation = await _target_calculation(service, connection, row, record,
                    candidate['target_run_id'], candidate['report_revision'], candidate['receipt_id'])
                fixed = {(ref.asset_id, ref.revision) for ref in record.review.corrected_versions if ref.asset_type == 'metric'}
                if fixed and not any((result.metric_version.metric_id, result.metric_version.revision) in fixed for result in calculation.results):
                    raise ManagementError('management_issue_regression_fix_mismatch', '此计算未覆盖问题的修复指标。', 409)
                if not calculation.datasets or calculation.workspace is None:
                    raise ManagementError('management_issue_regression_missing', '此计算缺少已登记CSV工作区。', 409)
                facts = [result for result in calculation.results if result.metric_version == calculation.request.metric_version]
                if len(facts) > 200:
                    raise ManagementError('management_issue_regression_limit', '分组事实超过当前一次核验支持的200项。', 409)
                graph = await service.bases.policies._metric_refs(connection, basis.scope_id, (calculation.request.metric_version,), require_available=False)
                item.update(available=True, goal=basis.request_summary.goal, metricName=graph[calculation.request.metric_version].name,
                    metricVersion=calculation.request.metric_version.model_dump(mode='json', by_alias=True),
                    period=calculation.request.period.model_dump(mode='json', by_alias=True),
                    facts=[{'factId': result.fact_id, 'unit': result.unit,
                        'dimensions': [dimension.model_dump(mode='json', by_alias=True) for dimension in result.dimensions]} for result in facts])
            except ManagementError as error:
                if error.status != 409:
                    raise
                item['reason'] = error.message
            items.append(item)
        cursor = json.dumps([rows[limit - 1]['basis_id'], rows[limit - 1]['receipt_id']]) if len(rows) > limit else None
        return {'issueVersion': row['version'], 'items': items, 'nextCursor': cursor}
