"""管理表单使用的已发布依赖选项。"""

from __future__ import annotations

import base64
import json
import re
from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from .api import SESSION_COOKIE, create_protected_router
from .data_sources.repository import SourceRepository
from .models import INSTANCE_SCOPE, ManagementError
from .repository import catalog_versions
from .scopes import ScopeService


def decode_cursor(value: str | None, kind: str):
    if not value:
        return None
    try:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if not isinstance(data, list) or len(data) != 3 or data[0] != kind:
            raise ValueError
        if (
            not isinstance(data[1], str)
            or not isinstance(data[2], int)
            or isinstance(data[2], bool)
            or data[2] < 1
        ):
            raise ValueError
        return data[1], data[2]
    except (ValueError, TypeError, UnicodeDecodeError) as error:
        raise ManagementError("management_cursor_invalid", "分页位置无效。", 422) from error


def create_version_options_router(scopes: ScopeService) -> APIRouter:
    router = create_protected_router(scopes.auth, "management-version-options")

    async def options(request, limit, after, source_id):
        cursor = decode_cursor(after, 'catalog')
        async with scopes.repository.transaction() as connection:
            await scopes.repository.authenticate_in_transaction(
                connection, request.cookies[SESSION_COOKIE], scopes.auth.clock())
            scope_id = await SourceRepository.scope_id(
                connection, INSTANCE_SCOPE)
            await SourceRepository().get_draft(connection, scope_id, source_id)
            query = select(catalog_versions).where(
                catalog_versions.c.scope_id == scope_id,
                catalog_versions.c.source_id == source_id,
                catalog_versions.c.status == 'published')
            if cursor:
                if cursor[0] != source_id:
                    raise ManagementError('management_cursor_invalid', '分页位置无效。', 422)
                query = query.where(catalog_versions.c.revision < cursor[1])
            rows = (await connection.execute(
                query.order_by(catalog_versions.c.revision.desc()).limit(limit + 1))).mappings().all()
            items = [{'ref': f"{source_id}:{row['revision']}", 'revision': row['revision'],
                      'publishedAt': None, 'syncedAt': row['synced_at'].isoformat()}
                     for row in rows[:limit]]
            next_cursor = None
            if len(rows) > limit:
                next_cursor = base64.urlsafe_b64encode(json.dumps(
                    ['catalog', source_id, rows[limit - 1]['revision']]).encode()).decode().rstrip('=')
            return {'items': items, 'nextCursor': next_cursor}

    @router.get("/management/api/v1/sources/{source_id}/catalog/versions")
    async def catalogs(
        request: Request,
        source_id: str,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=1024)] = None,
    ):
        return await options(request, limit, after, source_id)

    return router
