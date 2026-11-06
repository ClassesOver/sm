from __future__ import annotations

import hashlib
import json

from sqlalchemy import insert, select, update

from .models import ManagementError, ManagementScope
from .repository import catalog_versions
from .scopes import ScopeService
from ..reporting.data_source.models import CatalogTable


class CatalogService:
    def __init__(self, scope_service: ScopeService):
        self.scope_service = scope_service
        self.repository = scope_service.repository
        self.auth = scope_service.auth

    @staticmethod
    def _payload(catalog: tuple[CatalogTable, ...]) -> list[dict]:
        return [{
            "sourceId": table.source_id,
            "database": table.database,
            "name": table.name,
            "description": table.description,
            "columns": [{
                "name": column.name,
                "dataType": column.data_type,
                "nullable": column.nullable,
                "description": column.description,
            } for column in table.columns],
        } for table in catalog]

    @classmethod
    def _hash(cls, payload: list[dict]) -> str:
        raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    async def _scope_id(self, connection, scope: ManagementScope) -> str:
        row = await ScopeService.require_registered(connection, scope)
        return row["id"]

    async def sync(self, raw_session: str, scope: ManagementScope, source_id: str,
                   expected_draft_version: int, catalog: tuple[CatalogTable, ...] | None) -> dict:
        if catalog is None:
            raise ManagementError("management_catalog_sync_failed", "Catalog 同步失败，旧版本保持不变。", 422)
        payload = self._payload(catalog)
        digest = self._hash(payload)
        now = self.auth.clock()
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, now)
            scope_id = await self._scope_id(connection, scope)
            from .repository import source_drafts
            draft = (await connection.execute(select(source_drafts.c.version).where(
                source_drafts.c.scope_id == scope_id, source_drafts.c.source_id == source_id,
            ))).scalar_one_or_none()
            if draft is None:
                raise ManagementError("management_source_not_found", "数据源不存在。", 404)
            if draft != expected_draft_version:
                raise ManagementError("management_version_conflict", "数据源草稿已变化，请重新同步。", 409)
            previous = (await connection.execute(select(catalog_versions.c.revision).where(
                catalog_versions.c.scope_id == scope_id, catalog_versions.c.source_id == source_id,
            ).order_by(catalog_versions.c.revision.desc()).limit(1))).scalar_one_or_none()
            previous_hash = await self._last_hash(connection, scope_id, source_id)
            revision = (previous or 0) + 1
            await connection.execute(insert(catalog_versions).values(
                scope_id=scope_id, source_id=source_id, revision=revision,
                status="draft", catalog=payload, content_hash=digest, synced_at=now,
            ))
            return {"sourceId": source_id, "revision": revision, "status": "draft",
                    "changed": previous is None or digest != previous_hash,
                    "contentHash": digest, "syncedAt": now.isoformat()}

    async def _last_hash(self, connection, scope_id: str, source_id: str) -> str | None:
        return await connection.scalar(select(catalog_versions.c.content_hash).where(
            catalog_versions.c.scope_id == scope_id, catalog_versions.c.source_id == source_id,
        ).order_by(catalog_versions.c.revision.desc()).limit(1))

    async def publish(self, raw_session: str, scope: ManagementScope,
                      source_id: str, revision: int) -> dict:
        now = self.auth.clock()
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, now)
            scope_id = await self._scope_id(connection, scope)
            row = (await connection.execute(select(catalog_versions).where(
                catalog_versions.c.scope_id == scope_id, catalog_versions.c.source_id == source_id,
                catalog_versions.c.revision == revision,
            ))).mappings().one_or_none()
            if row is None:
                raise ManagementError("management_catalog_not_found", "Catalog 版本不存在。", 404)
            await connection.execute(update(catalog_versions).where(
                catalog_versions.c.scope_id == scope_id, catalog_versions.c.source_id == source_id,
                catalog_versions.c.revision == revision,
            ).values(status="published"))
            return {"sourceId": source_id, "revision": revision, "status": "published",
                    "contentHash": row["content_hash"], "publishedAt": now.isoformat()}

    async def current(self, raw_session: str, scope: ManagementScope, source_id: str) -> dict:
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            scope_id = await self._scope_id(connection, scope)
            row = (await connection.execute(select(catalog_versions).where(
                catalog_versions.c.scope_id == scope_id, catalog_versions.c.source_id == source_id,
                catalog_versions.c.status == "published",
            ).order_by(catalog_versions.c.revision.desc()).limit(1))).mappings().one_or_none()
            if row is None:
                raise ManagementError("management_catalog_not_found", "Catalog 尚未发布。", 404)
            return {"sourceId": source_id, "revision": row["revision"], "status": row["status"],
                    "catalog": row["catalog"], "contentHash": row["content_hash"]}
