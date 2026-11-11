"""预期签认的已发布原件候选；原报告用过的原件仍可用于独立核对。"""

import json

from sqlalchemy import select, tuple_

from .models import ManagementError
from .report_issue_fixes import _document
from .report_issue_regressions import _issue
from .repository import business_document_revisions as revisions
from .repository import business_evidence_release_documents as members


async def list_approval_sources(service, token, scope, issue_id, *, query='', limit=50, after=None):
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(connection, token, service.scopes.auth.clock())
        row = await _issue(service, connection, scope, issue_id)
        name = revisions.c.document['metadata']['title'].as_string()
        statement = select(revisions.c.document_id, revisions.c.revision, name.label('name')).where(
            revisions.c.scope_id == row['scope_id'], select(members.c.release_id).where(
                members.c.scope_id == revisions.c.scope_id, members.c.document_id == revisions.c.document_id,
                members.c.revision == revisions.c.revision).exists())
        if query:
            statement = statement.where(revisions.c.document_id.contains(query, autoescape=True) | name.contains(query, autoescape=True))
        if after is not None:
            try:
                cursor = json.loads(after)
                if (not isinstance(cursor, list) or len(cursor) != 2 or not isinstance(cursor[0], str)
                        or type(cursor[1]) is not int or cursor[1] < 1):
                    raise ValueError('invalid_cursor')
            except (ValueError, TypeError):
                raise ManagementError('management_issue_cursor_invalid', '原件分页游标无效，请重新读取。', 422) from None
            statement = statement.where(tuple_(revisions.c.document_id, revisions.c.revision) > tuple(cursor))
        rows = (await connection.execute(statement.order_by(revisions.c.document_id, revisions.c.revision)
            .limit(limit + 1))).mappings().all()
        items = []
        for candidate in rows[:limit]:
            reason = ''
            try:
                await _document(connection, row['scope_id'], candidate['document_id'], candidate['revision'])
            except ManagementError as error:
                if error.status != 409:
                    raise
                reason = error.message
            items.append({'documentId': candidate['document_id'], 'revision': candidate['revision'],
                'name': candidate['name'], 'available': not reason, 'reason': reason})
        cursor = json.dumps([rows[limit - 1]['document_id'], rows[limit - 1]['revision']]) if len(rows) > limit else None
        return {'items': items, 'nextCursor': cursor}
