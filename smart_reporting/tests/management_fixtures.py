"""管理集成测试的脱敏业务资料，不依赖真实数仓或模型。"""

from smart_reporting.reporting.contract import (
    MeasureSemantic,
    ModelColumn,
    ModelTable,
    ModelTerm,
    ModelTermsResponse,
    RawDdlModel,
    SourceRef,
    schema_hash,
)
from smart_reporting.reporting.data_source.models import CatalogColumn, CatalogTable


def business_metadata(source_id="operations", database="warehouse"):
    table = ModelTable(
        sourceId=source_id,
        database=database,
        name="orders",
        columns=(ModelColumn(name="amount", dataType="DECIMAL(18,2)", nullable=False),),
    )
    return ModelTermsResponse(
        revision="metadata-r1",
        schemaHash=schema_hash((table,)),
        sourceRefs=(SourceRef(sourceId=source_id),),
        ddlModels=(
            RawDdlModel(
                id=1,
                modelName="订单",
                ddl=(f"CREATE TABLE {database}.orders (amount DECIMAL(18,2) NOT NULL)"),
            ),
        ),
        tables=(table,),
        terms=(
            ModelTerm(
                code="income",
                name="收入",
                kind="measure",
                fieldRefs=(f"{source_id}.{database}.orders.amount",),
            ),
        ),
        measureSemantics=(
            MeasureSemantic(
                fieldRef=f"{source_id}.{database}.orders.amount",
                aggregation="sum",
                unit="元",
            ),
        ),
    )


def physical_catalog(source_id="operations", database="warehouse"):
    return (
        CatalogTable(
            source_id, database, "orders", (CatalogColumn("amount", "DECIMAL(18,2)", False),)
        ),
    )


async def publish_dependencies(scopes, raw_session, scope, source_id="operations", draft_version=1):
    from smart_reporting.management.catalog import CatalogService
    from smart_reporting.management.repository import source_drafts
    from sqlalchemy import select
    async with scopes.repository.transaction() as connection:
        scope_id = (await scopes.require_registered(connection, scope))["id"]
        database = await connection.scalar(select(source_drafts.c.database).where(
            source_drafts.c.scope_id == scope_id, source_drafts.c.source_id == source_id))
    catalogs = CatalogService(scopes)
    synced = await catalogs.sync(
        raw_session,
        scope,
        source_id,
        draft_version,
        physical_catalog(source_id, database),
        metadata=business_metadata(source_id, database),
    )
    await catalogs.publish(raw_session, scope, source_id, synced["revision"])


async def confirm_table_access(scopes, vault, token, scope, source_id, expected_version, monkeypatch):
    """仅替换外部数仓 I/O，真实执行发现、范围保存和版本 CAS。"""
    from smart_reporting.management.catalog import CatalogService
    from smart_reporting.management.table_access import TableAccessService

    access = TableAccessService(scopes, vault)
    async with scopes.repository.transaction() as connection:
        from smart_reporting.management.repository import source_drafts
        from sqlalchemy import select
        scope_id = (await scopes.require_registered(connection, scope))["id"]
        database = await connection.scalar(select(source_drafts.c.database).where(
            source_drafts.c.scope_id == scope_id, source_drafts.c.source_id == source_id))
    catalog = physical_catalog(source_id, database)

    async def discover(config):
        return [dict(table, type="table") for table in CatalogService._payload(catalog)]

    async def read_selected(config, selected):
        assert selected == [(database, "orders")]
        return catalog

    monkeypatch.setattr(access, "_discover", discover)
    monkeypatch.setattr(access, "_read_selected", read_selected)
    discovered = await access.discover(token, scope, source_id, expected_version)
    return await access.save(token, scope, source_id, expected_version,
                             discovered["discoveryId"], [(database, "orders")])
