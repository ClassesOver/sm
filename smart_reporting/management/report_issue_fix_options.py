"""按原问题浏览本组织正式版本；候选可用性不代替保存时的依赖核验。"""

import json

from sqlalchemy import literal, select, tuple_

from ..reporting.semantics.models import CorrectedVersionRef
from .models import ManagementError
from .report_issue_fixes import validate_fix_versions
from .report_issue_regressions import _issue
from .report_issue_reviews import IssueRecord
from .repository import (
    business_document_revisions,
    business_evidence_release_documents,
    business_evidence_releases,
    metric_versions,
    statistical_policy_versions,
)


async def list_fix_options(service, token, scope, issue_id, *, asset_type, query='', limit=50, after=None):
    tables = {'metric': (metric_versions, metric_versions.c.metric_id),
        'statistical_policy': (statistical_policy_versions, statistical_policy_versions.c.policy_id),
        'document': (business_document_revisions, business_document_revisions.c.document_id),
        'evidence_release': (business_evidence_releases, business_evidence_releases.c.release_id)}
    table, identifier = tables[asset_type]
    revision = literal(0) if asset_type == 'evidence_release' else table.c.revision
    if asset_type == 'document':
        name = table.c.document['metadata']['title'].as_string()
    elif asset_type == 'evidence_release':
        name = table.c.kind
    else:
        name = table.c.document['name'].as_string()
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(connection, token, service.scopes.auth.clock())
        row = await _issue(service, connection, scope, issue_id)
        record = IssueRecord.model_validate(row['document'])
        statement = select(identifier.label('asset_id'), revision.label('revision'), name.label('name')).where(
            table.c.scope_id == row['scope_id'])
        if asset_type == 'document':
            members = business_evidence_release_documents
            statement = statement.where(select(members.c.release_id).where(
                members.c.scope_id == table.c.scope_id, members.c.document_id == identifier,
                members.c.revision == revision).exists())
        if query:
            statement = statement.where(identifier.contains(query, autoescape=True) | name.contains(query, autoescape=True))
        if after is not None:
            try:
                cursor = json.loads(after)
                if (not isinstance(cursor, list) or len(cursor) != 2 or not isinstance(cursor[0], str)
                        or type(cursor[1]) is not int or cursor[1] < 0):
                    raise ValueError('invalid_cursor')
            except (ValueError, TypeError):
                raise ManagementError('management_issue_cursor_invalid', '版本分页游标无效，请重新读取。', 422) from None
            statement = statement.where(tuple_(identifier, revision) > tuple(cursor))
        rows = (await connection.execute(statement.order_by(identifier, revision).limit(limit + 1))).mappings().all()
        items = []
        for candidate in rows[:limit]:
            reference = CorrectedVersionRef(asset_type=asset_type, asset_id=candidate['asset_id'],
                revision=candidate['revision'] or None)
            reason = ''
            try:
                await validate_fix_versions(service, connection, scope, row['basis_id'], record, (reference,))
            except ManagementError as error:
                if error.status != 409:
                    raise
                reason = error.message
            items.append({'reference': reference.model_dump(mode='json', by_alias=True),
                'name': {'rule_evidence': '规则证据集合', 'background': '背景知识集合'}.get(candidate['name'], candidate['name']),
                'available': not reason, 'reason': reason})
        cursor = json.dumps([rows[limit - 1]['asset_id'], rows[limit - 1]['revision']]) if len(rows) > limit else None
        return {'items': items, 'nextCursor': cursor}
