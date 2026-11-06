from __future__ import annotations

from sqlalchemy import select

from ..models import ManagementError, ManagementScope
from ..repository import source_drafts, source_versions, tenant_settings
from .models import SourceDraft, SourceVersion


class SourceRepository:
    @staticmethod
    async def scope_id(connection, scope: ManagementScope) -> str:
        row = (await connection.execute(select(tenant_settings).where(
            tenant_settings.c.database == scope.database,
            tenant_settings.c.company_id == scope.company_id))).mappings().one_or_none()
        if row is None:
            raise ManagementError('management_scope_not_found', '请先登记组织。', 404)
        return row['id']

    @staticmethod
    def draft_model(row) -> SourceDraft:
        return SourceDraft(row['source_id'], row['scope_id'], row['version'], row['name'],
                           row['source_type'], row['database'], row['credential_ref'],
                           row['profile_version_id'], row['metadata_version_id'])

    @staticmethod
    def version_model(row) -> SourceVersion:
        return SourceVersion(row['source_id'], row['revision'], row['content_hash'],
                             row['published_at'], row['name'], row['source_type'],
                             row['database'], row['profile_version_id'],
                             row['metadata_version_id'], row['credential_revision'])

    async def get_draft(self, connection, scope_id: str, source_id: str):
        row = (await connection.execute(select(source_drafts).where(
            source_drafts.c.scope_id == scope_id, source_drafts.c.source_id == source_id
        ))).mappings().one_or_none()
        if row is None:
            raise ManagementError('management_source_not_found', '数据源不存在。', 404)
        return row

    async def get_published(self, connection, scope_id: str, source_id: str, revision: int | None = None):
        query = select(source_versions).where(source_versions.c.scope_id == scope_id,
                                               source_versions.c.source_id == source_id)
        query = query.order_by(source_versions.c.revision.desc()) if revision is None else query.where(
            source_versions.c.revision == revision)
        row = (await connection.execute(query.limit(1))).mappings().one_or_none()
        if row is None:
            raise ManagementError('management_source_version_not_found', '数据源发布版本不存在。', 404)
        return self.version_model(row)
