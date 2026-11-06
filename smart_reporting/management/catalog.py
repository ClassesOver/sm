from __future__ import annotations

import hashlib
import json

from loguru import logger
from sqlalchemy import insert, select, update

from ..reporting.contract import ModelTable, ModelTermsResponse, validate_catalog
from ..reporting.data_source.models import CatalogTable
from ..reporting.data_source.starrocks import (
    StarRocksDataSourceAdapter,
    StarRocksSourceConfig,
    parse_starrocks_source,
)
from ..reporting.metadata import ReportingMetadataClient
from .data_sources.secrets import CredentialVault
from .models import ManagementActor, ManagementError, ManagementScope
from .repository import catalog_versions
from .scopes import ScopeService


class CatalogService:
    def __init__(
        self,
        scope_service: ScopeService,
        *,
        vault: CredentialVault | None = None,
        metadata_client: ReportingMetadataClient | None = None,
    ):
        self.scope_service = scope_service
        self.repository = scope_service.repository
        self.auth = scope_service.auth
        self.vault = vault
        self.metadata_client = metadata_client

    async def fetch(
        self, source: StarRocksSourceConfig
    ) -> tuple[ModelTermsResponse, tuple[CatalogTable, ...]]:
        """外部 I/O 不持有管理事务；结果由 sync 的 CAS 再核对草稿。"""
        if self.metadata_client is None:
            raise ManagementError("management_metadata_unavailable", "未配置业务元数据服务。", 503)
        try:
            agent = await self.metadata_client.query_agent()
            model = await self.metadata_client.query_model(agent_id=agent.code, sources=(source,))
            allowed = tuple(f"{item.database}.{item.name}" for item in model.tables)
            adapter = StarRocksDataSourceAdapter(source, allowed_tables=allowed)
            try:
                catalog = await adapter.catalog()
            finally:
                await adapter.aclose()
            self.validate_snapshot(
                {
                    "metadata": model.model_dump(mode="json", by_alias=True),
                    "tables": self._payload(catalog),
                },
                source.id,
                source.database,
            )
            return model, catalog
        except ManagementError:
            raise
        except Exception as error:
            logger.warning(
                "management_catalog_sync_failed source_id={} error_type={}",
                source.id,
                type(error).__name__,
            )
            raise ManagementError(
                "management_catalog_sync_failed",
                "业务元数据或实际目录同步失败，旧版本保持不变。",
                422,
            ) from error

    async def synchronize(
        self, raw_session: str, scope: ManagementScope, source_id: str, expected_draft_version: int
    ) -> dict:
        if self.vault is None:
            raise ManagementError("management_secrets_unavailable", "未配置数据源加密密钥。", 503)
        from .repository import source_drafts

        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(
                connection, raw_session, self.auth.clock()
            )
            scope_id = await self._scope_id(connection, scope)
            draft = (
                (
                    await connection.execute(
                        select(source_drafts).where(
                            source_drafts.c.scope_id == scope_id,
                            source_drafts.c.source_id == source_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if draft is None:
                raise ManagementError("management_source_not_found", "数据源不存在。", 404)
            if draft["version"] != expected_draft_version:
                raise ManagementError(
                    "management_version_conflict", "数据源草稿已变化，请重新同步。", 409
                )
            dsn = await self.vault.resolve(connection, scope_id, source_id, draft["credential_ref"])
            config = parse_starrocks_source(
                {
                    "id": source_id,
                    "type": "starrocks",
                    "name": draft["name"],
                    "database": draft["database"],
                    "dsnEnv": "MANAGED_DSN",
                },
                {"MANAGED_DSN": dsn},
            )
        metadata, catalog = await self.fetch(config)
        return await self.sync(
            raw_session, scope, source_id, expected_draft_version, catalog, metadata=metadata
        )

    @staticmethod
    def _payload(catalog: tuple[CatalogTable, ...]) -> list[dict]:
        return [
            {
                "sourceId": table.source_id,
                "database": table.database,
                "name": table.name,
                "description": table.description,
                "columns": [
                    {
                        "name": column.name,
                        "dataType": column.data_type,
                        "nullable": column.nullable,
                        "description": column.description,
                    }
                    for column in table.columns
                ],
            }
            for table in catalog
        ]

    @classmethod
    def _hash(cls, payload: dict) -> str:
        # 同一内容的重复导入不因测试/草稿版本号产生新的目录身份。
        content = {key: value for key, value in payload.items() if key != "sourceDraftVersion"}
        raw = json.dumps(content, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def validate_snapshot(payload: dict, source_id: str, database: str) -> ModelTermsResponse:
        if not isinstance(payload, dict) or "metadata" not in payload:
            raise ManagementError(
                "management_catalog_incomplete", "目录缺少业务元数据，请重新同步。", 422
            )
        try:
            model = ModelTermsResponse.model_validate(payload["metadata"])
            tables = tuple(ModelTable.model_validate(item) for item in payload["tables"])
            if {item.source_id for item in model.source_refs} != {source_id} or any(
                item.source_id != source_id or item.database.lower() != database.lower()
                for item in (*model.tables, *tables)
            ):
                raise ValueError("catalog scope mismatch")
            validate_catalog(
                model.tables,
                tables,
                allowed_tables=tuple(f"{item.database}.{item.name}" for item in model.tables),
            )
            if not tables:
                raise ValueError("empty catalog")
            return model
        except ManagementError:
            raise
        except Exception as error:
            raise ManagementError(
                "management_catalog_invalid", "目录与业务元数据的范围或结构不一致。", 422
            ) from error

    async def _scope_id(self, connection, scope: ManagementScope) -> str:
        row = await ScopeService.require_registered(connection, scope)
        return row["id"]

    async def sync(
        self,
        raw_session: str,
        scope: ManagementScope,
        source_id: str,
        expected_draft_version: int,
        catalog: tuple[CatalogTable, ...] | None,
        *,
        metadata: ModelTermsResponse | None = None,
    ) -> dict:
        if catalog is None or metadata is None:
            raise ManagementError(
                "management_catalog_sync_failed", "Catalog 同步失败，旧版本保持不变。", 422
            )
        payload = {
            "tables": self._payload(catalog),
            "metadata": metadata.model_dump(mode="json", by_alias=True),
            "sourceDraftVersion": expected_draft_version,
        }
        digest = self._hash(payload)
        now = self.auth.clock()
        async with self.repository.transaction() as connection:
            account = await self.repository.authenticate_in_transaction(
                connection, raw_session, now
            )
            scope_id = await self._scope_id(connection, scope)
            from .repository import source_drafts

            draft = (
                (
                    await connection.execute(
                        select(source_drafts).where(
                            source_drafts.c.scope_id == scope_id,
                            source_drafts.c.source_id == source_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if draft is None:
                raise ManagementError("management_source_not_found", "数据源不存在。", 404)
            if draft["version"] != expected_draft_version:
                raise ManagementError(
                    "management_version_conflict", "数据源草稿已变化，请重新同步。", 409
                )
            self.validate_snapshot(payload, source_id, draft["database"])
            previous = (
                await connection.execute(
                    select(catalog_versions.c.revision)
                    .where(
                        catalog_versions.c.scope_id == scope_id,
                        catalog_versions.c.source_id == source_id,
                    )
                    .order_by(catalog_versions.c.revision.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            previous_hash = await self._last_hash(connection, scope_id, source_id)
            revision = (previous or 0) + 1
            await connection.execute(
                insert(catalog_versions).values(
                    scope_id=scope_id,
                    source_id=source_id,
                    revision=revision,
                    status="draft",
                    catalog=payload,
                    content_hash=digest,
                    synced_at=now,
                )
            )
            await self.scope_service.audit(
                connection,
                ManagementActor(
                    account.account_id,
                    account.username,
                    scope,
                    account.auth_version,
                    raw_session,
                ),
                "catalog_synced",
                {
                    "sourceId": source_id,
                    "revision": revision,
                    "sourceDraftVersion": expected_draft_version,
                },
            )
            return {
                "sourceId": source_id,
                "revision": revision,
                "status": "draft",
                "changed": previous is None or digest != previous_hash,
                "contentHash": digest,
                "syncedAt": now.isoformat(),
            }

    async def _last_hash(self, connection, scope_id: str, source_id: str) -> str | None:
        return await connection.scalar(
            select(catalog_versions.c.content_hash)
            .where(
                catalog_versions.c.scope_id == scope_id,
                catalog_versions.c.source_id == source_id,
            )
            .order_by(catalog_versions.c.revision.desc())
            .limit(1)
        )

    async def publish(
        self, raw_session: str, scope: ManagementScope, source_id: str, revision: int
    ) -> dict:
        now = self.auth.clock()
        async with self.repository.transaction() as connection:
            account = await self.repository.authenticate_in_transaction(
                connection, raw_session, now
            )
            scope_id = await self._scope_id(connection, scope)
            row = (
                (
                    await connection.execute(
                        select(catalog_versions).where(
                            catalog_versions.c.scope_id == scope_id,
                            catalog_versions.c.source_id == source_id,
                            catalog_versions.c.revision == revision,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ManagementError("management_catalog_not_found", "Catalog 版本不存在。", 404)
            from .repository import source_drafts

            database = await connection.scalar(
                select(source_drafts.c.database).where(
                    source_drafts.c.scope_id == scope_id,
                    source_drafts.c.source_id == source_id,
                )
            )
            self.validate_snapshot(row["catalog"], source_id, database)
            await connection.execute(
                update(catalog_versions)
                .where(
                    catalog_versions.c.scope_id == scope_id,
                    catalog_versions.c.source_id == source_id,
                    catalog_versions.c.revision == revision,
                )
                .values(status="published")
            )
            if row["status"] != "published":
                await self.scope_service.audit(
                    connection,
                    ManagementActor(
                        account.account_id,
                        account.username,
                        scope,
                        account.auth_version,
                        raw_session,
                    ),
                    "catalog_published",
                    {"sourceId": source_id, "revision": revision},
                )
            return {
                "sourceId": source_id,
                "revision": revision,
                "status": "published",
                "contentHash": row["content_hash"],
                "publishedAt": now.isoformat(),
            }

    async def current(self, raw_session: str, scope: ManagementScope, source_id: str) -> dict:
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(
                connection, raw_session, self.auth.clock()
            )
            scope_id = await self._scope_id(connection, scope)
            row = (
                (
                    await connection.execute(
                        select(catalog_versions)
                        .where(
                            catalog_versions.c.scope_id == scope_id,
                            catalog_versions.c.source_id == source_id,
                            catalog_versions.c.status == "published",
                        )
                        .order_by(catalog_versions.c.revision.desc())
                        .limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise ManagementError("management_catalog_not_found", "Catalog 尚未发布。", 404)
            payload = row["catalog"]
            return {
                "sourceId": source_id,
                "revision": row["revision"],
                "status": row["status"],
                "catalog": payload.get("tables", []) if isinstance(payload, dict) else payload,
                "metadata": payload.get("metadata") if isinstance(payload, dict) else None,
                "sourceDraftVersion": payload.get("sourceDraftVersion")
                if isinstance(payload, dict)
                else None,
                "contentHash": row["content_hash"],
            }
