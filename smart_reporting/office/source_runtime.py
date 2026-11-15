from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from ..management.data_sources.repository import SourceRepository
from ..management.models import ManagementScope
from ..management.repository import sources, source_versions
from ..management.table_access import TableAccessService
from ..reporting.data_source.starrocks import StarRocksDataSourceAdapter, parse_starrocks_source
from .repository import OfficeError
from .schema import source_grants


@dataclass(frozen=True)
class SourceAccess:
    source: str
    revision: int
    tables: tuple[str, ...]
    config: object


class OfficeSourceRuntime:
    def __init__(self, office, vault, *, adapter_factory=StarRocksDataSourceAdapter):
        self.office, self.vault, self.adapter_factory = office, vault, adapter_factory

    async def published(self, connection, actor, source):
        scope = ManagementScope(actor.database, actor.company)
        scope_id = await SourceRepository.scope_id(connection, scope)
        row = (await connection.execute(select(source_versions).join(
            sources, (sources.c.scope_id == source_versions.c.scope_id)
            & (sources.c.source_id == source_versions.c.source_id)
            & (sources.c.published_revision == source_versions.c.revision),
        ).where(source_versions.c.scope_id == scope_id,
                source_versions.c.source_id == source, sources.c.enabled == 1,
        ))).mappings().first()
        if row is None:
            raise OfficeError("office_source_unavailable", "数据源未发布或已停用。")
        catalog = await TableAccessService.bound_tables(connection, scope_id, source, row["metadata_version_id"])
        tables = tuple(f'{table["database"]}.{table["name"]}' for table in catalog)
        return scope_id, dict(row), tables

    async def authorize_grant(self, actor, source, tables):
        async with self.office.transaction(actor) as connection:
            await self.office._user(connection, actor, admin=True)
            _, _, published_tables = await self.published(connection, actor, source)
            if not set(tables).issubset(published_tables):
                raise OfficeError("office_source_table_denied", "授权表须在数据源已发布表范围内。", 422)

    async def access(self, actor, space, source):
        async with self.office.transaction(actor) as connection:
            scope_id, row, tables = await self._authorized_tables(connection, actor, space, source)
            dsn = await self.vault.resolve(connection, scope_id, source, row["credential_ref"])
            config = parse_starrocks_source({
                "id": source, "name": row["name"], "type": row["source_type"],
                "database": row["database"], "dsnEnv": "OFFICE_SOURCE_DSN",
                **(row["execution_parameters"] or {}),
            }, {"OFFICE_SOURCE_DSN": dsn})
            return SourceAccess(source, row["revision"], tables, config)

    async def _authorized_tables(self, connection, actor, space, source):
        granted = await self.office._source_tables(connection, actor, space, source)
        scope_id, row, published_tables = await self.published(connection, actor, source)
        tables = tuple(sorted(set(granted).intersection(published_tables)))
        if not tables:
            raise OfficeError("office_source_table_denied", "当前授权表已失效。")
        return scope_id, row, tables

    async def available(self, actor, space):
        await self.office.space_access(actor, space)
        async with self.office.transaction(actor) as connection:
            ids = (await connection.execute(select(source_grants.c.source).where(
                source_grants.c.space == space))).scalars().all()
        result = []
        for source in ids:
            try:
                access = await self.access(actor, space, source)
                result.append({"id": source, "name": access.config.name, "revision": access.revision,
                               "tables": access.tables, "available": True})
            except OfficeError as error:
                result.append({"id": source, "available": False, "reason": error.message})
        return result

    async def describe(self, actor, space, source, table):
        async with self.office.transaction(actor) as connection:
            scope_id, row, granted = await self._authorized_tables(connection, actor, space, source)
            if table not in granted:
                raise OfficeError("office_source_table_denied", "无权读取此表结构。")
            catalog = await TableAccessService.bound_catalog(connection, scope_id, source, row["metadata_version_id"])
            target = next((item for item in catalog.get("tables", [])
                           if f'{item["database"]}.{item["name"]}' == table), None)
            if target is None:
                raise OfficeError("office_source_table_missing", "表结构不可用，请重新发现并发布。", 409)
            return {"sourceId": source, "revision": row["revision"], "table": {
                key: target[key] for key in ("database", "name", "description", "columns") if key in target}}

    async def query(self, actor, space, source, sql):
        access = await self.access(actor, space, source)
        adapter = self.adapter_factory(access.config, allowed_tables=access.tables)
        try:
            result = await adapter.query(sql)
        finally:
            await adapter.aclose()
        query_id = str(uuid4())
        async with self.office.transaction(actor) as connection:
            _, row, tables = await self._authorized_tables(connection, actor, space, source)
            if access.revision != row["revision"] or access.tables != tables:
                raise OfficeError("office_source_changed", "数据源授权或版本已变化，请重新查询。", 409)
            await self.office._audit(connection, actor, "source_queried", space=space, source=source,
                                     revision=access.revision, query=query_id, tables=list(access.tables))
        return {"columns": result.columns, "rows": result.rows,
                "source": {"id": source, "revision": access.revision, "tables": access.tables,
                           "queryId": query_id, "queriedAt": datetime.now(UTC).isoformat()}}


def restrict_report_execution(execution, grants):
    from dataclasses import replace

    from ..reporting.contract import schema_hash
    from ..reporting.models import ReportingError

    revisions = {ref.source_id: ref.revision for ref in execution.basis.source_versions}
    scoped_metadata = {}
    for source_id, metadata in execution.metadata.items():
        grant = grants.get(source_id)
        if grant is None or revisions[source_id] != grant["revision"]:
            raise ReportingError("office_report_source_denied",
                "报告使用的数据源或版本已不在当前工作区的授权内。")
        allowed = set(grant["tables"])
        tables = tuple(table for table in metadata.tables
                       if f"{table.database}.{table.name}" in allowed)
        if not tables:
            raise ReportingError("office_report_source_denied", "报告数据源没有已授权的表。")
        ddl = tuple(raw for raw, table in zip(metadata.ddl_models, metadata.tables, strict=True)
                    if table in tables)
        fields = {f"{source_id}.{table.database}.{table.name}.{column.name}".lower()
                  for table in tables for column in table.columns}
        terms = []
        for term in metadata.terms:
            refs = tuple(ref for ref in term.field_refs if ref.lower() in fields)
            if refs or not term.field_refs:
                terms.append(term.model_copy(update={"field_refs": refs}))
        scoped_metadata[source_id] = metadata.model_copy(update={
            "tables": tables, "ddl_models": ddl, "schema_hash": schema_hash(tables),
            "terms": tuple(terms),
            "measure_semantics": tuple(item for item in metadata.measure_semantics
                                       if item.field_ref.lower() in fields),
        })
    return replace(execution, metadata=scoped_metadata)
