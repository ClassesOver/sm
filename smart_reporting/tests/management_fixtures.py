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
    from smart_reporting.management.profiles import ProfileService

    profiles = ProfileService(scopes)
    try:
        await profiles.get_version(raw_session, scope, "base", 1)
    except Exception as error:
        from smart_reporting.management.models import ManagementError

        if (
            not isinstance(error, ManagementError)
            or error.code != "management_profile_version_not_found"
        ):
            raise
        draft = await profiles.save_draft(
            raw_session,
            scope,
            {
                "profileId": "base",
                "revision": "r1",
                "dimensions": [],
            },
            0,
        )
        await profiles.publish(raw_session, scope, "base", draft["version"])
    catalogs = CatalogService(scopes)
    synced = await catalogs.sync(
        raw_session,
        scope,
        source_id,
        draft_version,
        physical_catalog(source_id, scope.database),
        metadata=business_metadata(source_id, scope.database),
    )
    await catalogs.publish(raw_session, scope, source_id, synced["revision"])
