"""管理员目录发现与不可变表范围；发现快照不进入报告上下文。"""

from __future__ import annotations

import uuid

import anyio
from loguru import logger
from sqlalchemy import insert, inspect, select, update

from ..reporting.contract import ModelTable, ModelTermsResponse, schema_hash
from ..reporting.data_source.starrocks import StarRocksDataSourceAdapter, parse_starrocks_source
from .catalog import CatalogService
from .data_sources.service import SourceService
from .models import ManagementActor, ManagementError
from .repository import catalog_versions, source_drafts, sources, table_discoveries


class TableAccessService:
    def __init__(self, scopes, vault, metadata_client=None):
        self.scopes = scopes
        self.repository = scopes.repository
        self.auth = scopes.auth
        self.sources = SourceService(scopes, vault)
        self.vault = vault
        self.metadata_client = metadata_client
        self.catalogs = CatalogService(scopes)

    async def _draft(self, conn, token, scope, source_id, expected=None):
        account = await self.repository.authenticate_in_transaction(conn, token, self.auth.clock())
        scope_id = await self.sources.sources.scope_id(conn, scope)
        draft = await self.sources.sources.get_draft(conn, scope_id, source_id)
        if expected is not None and draft["version"] != expected:
            raise ManagementError(
                "management_version_conflict", "草稿已变化，请核对最新版本。", 409
            )
        return account, scope_id, draft

    async def _config(self, conn, scope_id, source_id, draft):
        dsn = await self.vault.resolve(conn, scope_id, source_id, draft["credential_ref"])
        return parse_starrocks_source(
            {
                "id": source_id,
                "type": "starrocks",
                "name": draft["name"],
                "database": draft["database"],
                "dsnEnv": "MANAGEMENT_DSN",
                **(draft["execution_parameters"] or {}),
            },
            {"MANAGEMENT_DSN": dsn},
        )

    @staticmethod
    async def bound_catalog(conn, scope_id, source_id, reference):
        if not reference:
            return {}
        from .data_sources.releases import split_version

        owner, revision = split_version(reference)
        if owner != source_id:
            return {}
        payload = await conn.scalar(
            select(catalog_versions.c.catalog).where(
                catalog_versions.c.scope_id == scope_id,
                catalog_versions.c.source_id == source_id,
                catalog_versions.c.revision == revision,
            )
        )
        if not isinstance(payload, dict):
            return {}
        return payload

    @staticmethod
    async def bound_tables(conn, scope_id, source_id, reference):
        payload = await TableAccessService.bound_catalog(conn, scope_id, source_id, reference)
        return sorted(
            [
                {"database": t["database"], "name": t["name"]}
                for t in (payload or {}).get("tables", [])
            ],
            key=lambda t: (t["database"], t["name"]),
        )

    async def _access(self, conn, scope_id, source_id, draft):
        _, _, published = await self.sources._read_detail(conn, scope_id, source_id)
        current = await self.bound_tables(
            conn, scope_id, source_id, published["metadata_version_id"] if published else None
        )
        selected = await self.bound_tables(conn, scope_id, source_id, draft["metadata_version_id"])
        latest = (
            (
                await conn.execute(
                    select(table_discoveries)
                    .where(
                        table_discoveries.c.scope_id == scope_id,
                        table_discoveries.c.source_id == source_id,
                        table_discoveries.c.credential_ref == draft["credential_ref"],
                        table_discoveries.c.database == draft["database"],
                    )
                    .order_by(
                        table_discoveries.c.discovered_at.desc(),
                        table_discoveries.c.discovery_id.desc(),
                    )
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        payload = await self.bound_catalog(conn, scope_id, source_id, draft["metadata_version_id"])
        return {
            "draftVersion": draft["version"],
            "draftTables": selected,
            "publishedTables": current,
            "needsDiscovery": bool(draft["requires_table_discovery"]),
            "discoveryId": latest["discovery_id"] if latest else None,
            "discoveredAt": latest["discovered_at"].isoformat() if latest else None,
            "warnings": list(
                dict.fromkeys(
                    [*(latest["warnings"] if latest else []), *payload.get("warnings", [])]
                )
            ),
        }

    async def access(self, token, scope, source_id):
        async with self.repository.transaction() as conn:
            _, scope_id, draft = await self._draft(conn, token, scope, source_id)
            return await self._access(conn, scope_id, source_id, draft)

    async def _discover(self, config):
        adapter = StarRocksDataSourceAdapter(config)

        def read():
            from sqlalchemy import text

            inspector = inspect(adapter._engine)
            # StarRocks 驱动的 get_view_names 会吞异常返回空列表；直接读取目录，
            # 保留真实视图并让目录读取失败显式失败，不读取业务表内容。
            with adapter._engine.connect() as connection:
                objects = (
                    connection.execute(
                        text(
                            "SELECT TABLE_NAME AS name, TABLE_TYPE AS object_type, "
                            "TABLE_COMMENT AS description FROM information_schema.tables "
                            "WHERE TABLE_SCHEMA=:database ORDER BY TABLE_NAME"
                        ),
                        {"database": config.database},
                    )
                    .mappings()
                    .all()
                )
            result = []
            for item in objects:
                name = item["name"]
                columns = inspector.get_columns(name, schema=config.database)
                result.append(
                    {
                        "sourceId": config.id,
                        "database": config.database,
                        "name": name,
                        "type": "view" if item["object_type"].upper() == "VIEW" else "table",
                        "description": item["description"] or "",
                        "columns": [
                            {
                                "name": c["name"],
                                "dataType": str(c["type"]),
                                "nullable": bool(c.get("nullable", True)),
                                "description": c.get("comment") or "",
                            }
                            for c in columns
                        ],
                    }
                )
            return result

        try:
            return await anyio.to_thread.run_sync(read)
        finally:
            await adapter.aclose()

    async def _read_selected(self, config, selected):
        adapter = StarRocksDataSourceAdapter(
            config, allowed_tables=tuple(f"{db}.{name}" for db, name in selected)
        )
        try:
            return await adapter.catalog()
        finally:
            await adapter.aclose()

    async def discover(self, token, scope, source_id, expected):
        async with self.repository.transaction() as conn:
            _, scope_id, draft = await self._draft(conn, token, scope, source_id, expected)
            config = await self._config(conn, scope_id, source_id, draft)
            existing_metadata = None
            if draft["metadata_version_id"]:
                from .data_sources.releases import split_version

                owner, revision = split_version(draft["metadata_version_id"])
                if owner == source_id:
                    payload = await conn.scalar(
                        select(catalog_versions.c.catalog).where(
                            catalog_versions.c.scope_id == scope_id,
                            catalog_versions.c.source_id == source_id,
                            catalog_versions.c.revision == revision,
                        )
                    )
                    if isinstance(payload, dict):
                        existing_metadata = payload.get("metadata")
        try:
            tables = await self._discover(config)
        except Exception as error:
            logger.warning(
                "management_table_discovery_failed source={} error_type={}",
                source_id,
                type(error).__name__,
            )
            raise ManagementError(
                "management_table_discovery_failed",
                "数据库目录读取失败，请核对连接后重新发现。",
                422,
            ) from error
        warnings, metadata = [], existing_metadata
        try:
            if self.metadata_client is None:
                raise ValueError("metadata unavailable")
            agent = await self.metadata_client.query_agent()
            model = await self.metadata_client.query_model(agent_id=agent.code, sources=(config,))
            metadata = model.model_dump(mode="json", by_alias=True)
        except Exception as error:
            logger.info(
                "management_discovery_metadata_unavailable source={} error_type={}",
                source_id,
                type(error).__name__,
            )
            warnings.append("业务说明补充失败；仍可使用数据库真实结构和注释选择表。")
        discovery_id = str(uuid.uuid4())
        now = self.auth.clock()
        async with self.repository.transaction() as conn:
            account, current_scope, current = await self._draft(
                conn, token, scope, source_id, expected
            )
            if current["credential_ref"] != draft["credential_ref"]:
                self._conflict()
            await conn.execute(
                insert(table_discoveries).values(
                    scope_id=current_scope,
                    source_id=source_id,
                    discovery_id=discovery_id,
                    database=config.database,
                    credential_ref=draft["credential_ref"],
                    credential_revision=draft["credential_revision"],
                    discovered_at=now,
                    tables=tables,
                    business_metadata=metadata,
                    warnings=warnings,
                )
            )
            await self.scopes.audit(
                conn,
                ManagementActor(
                    account.account_id, account.username, scope, account.auth_version, token
                ),
                "tables_discovered",
                {"sourceId": source_id, "discoveryId": discovery_id, "tableCount": len(tables)},
            )
        return {
            "discoveryId": discovery_id,
            "discoveredAt": now.isoformat(),
            "tableCount": len(tables),
            "draftVersion": expected,
            "warnings": warnings,
        }

    @staticmethod
    def _conflict():
        raise ManagementError(
            "management_discovery_conflict",
            "连接或发现快照已变化，请重新发现并核对范围；本地选择可保留。",
            409,
        )

    async def _snapshot(self, conn, scope_id, source_id, discovery_id, draft):
        row = (
            (
                await conn.execute(
                    select(table_discoveries).where(
                        table_discoveries.c.scope_id == scope_id,
                        table_discoveries.c.source_id == source_id,
                        table_discoveries.c.discovery_id == discovery_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ManagementError("management_discovery_not_found", "发现快照不存在。", 404)
        if (
            row["database"] != draft["database"]
            or row["credential_ref"] != draft["credential_ref"]
            or row["credential_revision"] != draft["credential_revision"]
        ):
            self._conflict()
        return row

    @staticmethod
    def _described_tables(row):
        metadata = row["business_metadata"] or {}
        descriptions = {(t["database"], t["name"]): t for t in metadata.get("tables", [])}
        result = []
        for table in row["tables"]:
            business = descriptions.get((table["database"], table["name"]), {})
            columns = {c["name"]: c for c in business.get("columns", [])}
            result.append(
                {
                    **table,
                    "description": business.get("description") or table["description"],
                    "columns": [
                        {
                            **c,
                            "description": columns.get(c["name"], {}).get("description")
                            or c["description"],
                        }
                        for c in table["columns"]
                    ],
                }
            )
        return result

    async def tables(
        self,
        token,
        scope,
        source_id,
        discovery_id,
        *,
        q="",
        kind="all",
        offset=0,
        limit=50,
        selected_only=False,
    ):
        async with self.repository.transaction() as conn:
            _, scope_id, draft = await self._draft(conn, token, scope, source_id)
            row = await self._snapshot(conn, scope_id, source_id, discovery_id, draft)
            access = await self._access(conn, scope_id, source_id, draft)
            selected = {(t["database"], t["name"]) for t in access["draftTables"]}
            published = {(t["database"], t["name"]) for t in access["publishedTables"]}
            all_tables = self._described_tables(row)
            candidates = {(t["database"], t["name"]) for t in all_tables}
            summaries = [
                {k: v for k, v in t.items() if k not in ("columns", "sourceId")}
                | {
                    "selected": (t["database"], t["name"]) in selected,
                    "published": (t["database"], t["name"]) in published,
                }
                for t in all_tables
            ]
            selected_items = sorted(
                [t for t in summaries if t["selected"]],
                key=lambda t: (t["database"], t["name"]),
            )[:200]
            items = [
                t
                for t in summaries
                if (kind == "all" or t["type"] == kind)
                and (not q or q.casefold() in (t["name"] + " " + t["description"]).casefold())
                and (not selected_only or (t["database"], t["name"]) in selected)
            ]
            items.sort(key=lambda t: (t["database"], t["name"]))
            return {
                "items": items[offset : offset + limit],
                "selectedItems": selected_items,
                "total": len(items),
                "missingTables": [
                    {"database": db, "name": name} for db, name in sorted(selected - candidates)
                ],
                "nextOffset": offset + limit if len(items) > offset + limit else None,
            }

    async def columns(self, token, scope, source_id, discovery_id, database, table):
        async with self.repository.transaction() as conn:
            _, scope_id, draft = await self._draft(conn, token, scope, source_id)
            row = await self._snapshot(conn, scope_id, source_id, discovery_id, draft)
            for item in self._described_tables(row):
                if (item["database"], item["name"]) == (database, table):
                    return {"database": database, "name": table, "columns": item["columns"]}
            raise ManagementError("management_table_not_found", "表不在当前发现快照中。", 404)

    @staticmethod
    def _model(catalog, source_id, metadata):
        """DDL 始终由所选真实结构生成；不保留可能泄露未选表的旧 DDL。"""
        tables = tuple(ModelTable.model_validate(t) for t in CatalogService._payload(catalog))
        available = {
            f"{t.source_id}.{t.database}.{t.name}.{c.name}".lower()
            for t in tables
            for c in t.columns
        }
        metadata = metadata or {}
        terms = [
            t
            for t in metadata.get("terms", [])
            if t.get("fieldRefs") and all(r.lower() in available for r in t["fieldRefs"])
        ]
        semantics = []
        for sem in metadata.get("measureSemantics", []):
            if sem["fieldRef"].lower() not in available or (
                sem.get("reconcileWith") and sem["reconcileWith"].lower() not in available
            ):
                continue
            table_ref = sem["fieldRef"].rsplit(".", 1)[0].lower()
            columns = {
                ref.rsplit(".", 1)[1] for ref in available if ref.rsplit(".", 1)[0] == table_ref
            }
            if (
                set(sem.get("additiveAcross", [])) <= columns
                and set(sem.get("exclusiveScope", {})) <= columns
            ):
                semantics.append(sem)

        def quote(name):
            return "`" + name.replace("`", "``") + "`"

        ddls = [
            {
                "id": i + 1,
                "modelName": t.name,
                "modelDesc": t.description,
                "ddl": f"CREATE TABLE {quote(t.database)}.{quote(t.name)} ("
                + ", ".join(
                    f"{quote(c.name)} {c.data_type}" + ("" if c.nullable else " NOT NULL")
                    for c in t.columns
                )
                + ")",
            }
            for i, t in enumerate(tables)
        ]
        model = ModelTermsResponse.model_validate(
            {
                "revision": "table-access-" + schema_hash(tables)[:32],
                "schemaHash": schema_hash(tables),
                "sourceRefs": [{"sourceId": source_id}],
                "ddlModels": ddls,
                "tables": [t.model_dump(mode="json", by_alias=True) for t in tables],
                "terms": terms,
                "measureSemantics": semantics,
            }
        )
        removed = len(terms) != len(metadata.get("terms", [])) or len(semantics) != len(
            metadata.get("measureSemantics", [])
        )
        return model, [
            "已移除引用未选表或已变化字段的业务语义，请核对业务口径。"
        ] if removed else []

    async def save(self, token, scope, source_id, expected, discovery_id, selected):
        if not 1 <= len(selected) <= 200 or len(set(selected)) != len(selected):
            raise ManagementError(
                "management_table_selection_invalid",
                "有效范围必须选择 1 至 200 张不重复的表；空选择可留在页面编辑。",
                422,
            )
        async with self.repository.transaction() as conn:
            _, scope_id, draft = await self._draft(conn, token, scope, source_id, expected)
            row = await self._snapshot(conn, scope_id, source_id, discovery_id, draft)
            candidates = {(t["database"], t["name"]) for t in row["tables"]}
            if not set(selected) <= candidates:
                raise ManagementError(
                    "management_table_selection_invalid",
                    "所选表不在当前发现结果中，请核对消失对象。",
                    422,
                )
            config = await self._config(conn, scope_id, source_id, draft)
        try:
            catalog = await self._read_selected(config, sorted(selected))
            if {(t.database, t.name) for t in catalog} != set(selected):
                raise ValueError("catalog changed")
            # 真实字段结构优先；业务说明仅补充仍然存在的对象和字段。
            descriptions = {
                (t["database"], t["name"]): t
                for t in (row["business_metadata"] or {}).get("tables", [])
            }
            from dataclasses import replace

            catalog = tuple(
                replace(
                    t,
                    description=descriptions.get((t.database, t.name), {}).get("description")
                    or t.description,
                    columns=tuple(
                        replace(
                            c,
                            description=next(
                                (
                                    b.get("description")
                                    for b in descriptions.get((t.database, t.name), {}).get(
                                        "columns", []
                                    )
                                    if b["name"] == c.name
                                ),
                                None,
                            )
                            or c.description,
                        )
                        for c in t.columns
                    ),
                )
                for t in catalog
            )
            model, warnings = self._model(catalog, source_id, row["business_metadata"])
            payload = {
                "tables": self.catalogs._payload(catalog),
                "metadata": model.model_dump(mode="json", by_alias=True),
                "sourceDraftVersion": expected + 1,
                "connectionIdentity": {
                    "database": draft["database"],
                    "credentialRef": draft["credential_ref"],
                    "credentialRevision": draft["credential_revision"],
                },
                "warnings": warnings,
            }
            self.catalogs.validate_snapshot(payload, source_id, config.database)
        except ManagementError:
            raise
        except Exception as error:
            logger.warning(
                "management_table_access_read_failed source={} error_type={}",
                source_id,
                type(error).__name__,
            )
            raise ManagementError(
                "management_table_access_read_failed",
                "所选表结构读取失败，范围未保存，请重新发现后核对。",
                422,
            ) from error
        async with self.repository.transaction() as conn:
            account, scope_id, current = await self._draft(conn, token, scope, source_id, expected)
            await self._snapshot(conn, scope_id, source_id, discovery_id, current)
            # 锁定草稿并 CAS；目录版本与草稿绑定在同一事务提交。
            changed = await conn.scalar(
                update(source_drafts)
                .where(
                    source_drafts.c.scope_id == scope_id,
                    source_drafts.c.source_id == source_id,
                    source_drafts.c.version == expected,
                )
                .values(version=expected + 1, requires_table_discovery=0)
                .returning(source_drafts.c.version)
            )
            if changed is None:
                self._conflict()
            previous = await conn.scalar(
                select(catalog_versions.c.revision)
                .where(
                    catalog_versions.c.scope_id == scope_id,
                    catalog_versions.c.source_id == source_id,
                )
                .order_by(catalog_versions.c.revision.desc())
                .limit(1)
            )
            revision = (previous or 0) + 1
            now = self.auth.clock()
            await conn.execute(
                insert(catalog_versions).values(
                    scope_id=scope_id,
                    source_id=source_id,
                    revision=revision,
                    status="published",
                    catalog=payload,
                    content_hash=self.catalogs._hash(payload),
                    synced_at=now,
                )
            )
            content = {
                "name": current["name"],
                "type": current["source_type"],
                "database": current["database"],
                "reportingProfileVersionId": current["profile_version_id"],
                "metadataVersionId": f"{source_id}:{revision}",
            }
            digest = self.sources._config_hash(
                content, current["credential_revision"], current["execution_parameters"]
            )
            await conn.execute(
                update(source_drafts)
                .where(source_drafts.c.scope_id == scope_id, source_drafts.c.source_id == source_id)
                .values(metadata_version_id=f"{source_id}:{revision}", content_hash=digest)
            )
            await conn.execute(
                update(sources)
                .where(sources.c.scope_id == scope_id, sources.c.source_id == source_id)
                .values(draft_version=expected + 1, updated_at=now)
            )
            await self.scopes.audit(
                conn,
                ManagementActor(
                    account.account_id, account.username, scope, account.auth_version, token
                ),
                "table_access_saved",
                {
                    "sourceId": source_id,
                    "discoveryId": discovery_id,
                    "version": expected + 1,
                    "catalogRevision": revision,
                    "tableCount": len(selected),
                },
            )
        return {
            "draftVersion": expected + 1,
            "metadataVersionId": f"{source_id}:{revision}",
            "warnings": warnings,
        }
