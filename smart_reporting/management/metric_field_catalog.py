"""只读已发布暴露目录供规则编辑选字段；不读取连接密文或查询业务库。"""

from sqlalchemy import select

from ..reporting.contract import ModelTermsResponse
from .models import ManagementError
from .report_bases import ReportBasisService
from .repository import catalog_versions


async def read_field_catalog(
    service, token, scope, source_id, source_revision, *, query="", limit=50, after=None
):
    if (
        type(source_revision) is not int
        or source_revision < 1
        or type(limit) is not int
        or not 1 <= limit <= 100
        or not isinstance(query, str)
        or len(query) > 200
        or after is not None
        and (not isinstance(after, str) or len(after) > 520)
    ):
        raise ManagementError("management_metric_invalid", "字段目录查询参数无效。", 422)
    async with service.repository.transaction() as connection:
        await service.repository.authenticate_in_transaction(
            connection, token, service.scopes.auth.clock()
        )
        scope_id = (await service.scopes.require_registered(connection, scope))["id"]
        source_ref, catalog_ref = await ReportBasisService._source(
            connection, scope_id, source_id, source_revision
        )
        snapshot = await connection.scalar(
            select(catalog_versions.c.catalog).where(
                catalog_versions.c.scope_id == scope_id,
                catalog_versions.c.source_id == source_id,
                catalog_versions.c.revision == catalog_ref.revision,
            )
        )
        model = ModelTermsResponse.model_validate(snapshot["metadata"])
        needle = query.casefold().strip()
        fields = []
        for table in model.tables:
            for column in table.columns:
                field = f"{table.source_id}.{table.database}.{table.name}.{column.name}"
                if after is not None and field <= after:
                    continue
                if (
                    needle
                    and needle
                    not in " ".join(
                        (field, table.description, column.description, column.data_type)
                    ).casefold()
                ):
                    continue
                fields.append(
                    {
                        "fieldRef": field,
                        "database": table.database,
                        "table": table.name,
                        "column": column.name,
                        "dataType": column.data_type,
                        "nullable": column.nullable,
                        "description": column.description,
                        "tableDescription": table.description,
                    }
                )
        fields.sort(key=lambda row: row["fieldRef"])
        return {
            "sourceVersion": source_ref.model_dump(mode="json", by_alias=True),
            "catalogVersion": catalog_ref.model_dump(mode="json", by_alias=True),
            "items": fields[:limit],
            "nextCursor": fields[limit - 1]["fieldRef"] if len(fields) > limit else None,
        }
