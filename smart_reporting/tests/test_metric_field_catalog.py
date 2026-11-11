"""指标字段候选只从已发布、已暴露且身份核验过的目录读取。"""

import httpx
import pytest
from fastapi import FastAPI

from smart_reporting.management.api import SESSION_COOKIE
from smart_reporting.reporting.tests.test_business_evidence_index import (
    index_context as index_context,
)
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_report_basis_persistence import basis_context as basis_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_field_catalog_uses_exact_published_exposure_and_scope(basis_context):
    from sqlalchemy import update

    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.repository import sources

    ctx = basis_context
    service = MetricService(ctx["scopes"])
    first = await service.field_catalog(ctx["token"], ctx["scope"], "warehouse", 1, limit=1)
    assert (
        first["sourceVersion"]["sourceId"] == "warehouse"
        and first["sourceVersion"]["revision"] == 1
    )
    assert (
        first["catalogVersion"]["sourceId"] == "warehouse"
        and first["catalogVersion"]["revision"] == 1
    )
    assert first["items"] == [
        {
            "fieldRef": "warehouse.test.budget.amount",
            "database": "test",
            "table": "budget",
            "column": "amount",
            "dataType": "DECIMAL(18,2)",
            "nullable": False,
            "description": "",
            "tableDescription": "",
        }
    ]
    assert first["nextCursor"] == "warehouse.test.budget.amount"
    page = await service.field_catalog(
        ctx["token"],
        ctx["scope"],
        "warehouse",
        1,
        limit=1,
        after=first["nextCursor"],
        query="period",
    )
    assert [v["fieldRef"] for v in page["items"]] == ["warehouse.test.budget.period"] and page[
        "nextCursor"
    ] is None
    assert (
        await service.field_catalog(ctx["token"], ctx["scope"], "warehouse", 1, query="unexposed")
    )["items"] == []
    with pytest.raises(ManagementError):
        await service.field_catalog(ctx["token"], ctx["other_scope"], "warehouse", 1)
    with pytest.raises(ManagementError):
        await service.field_catalog(ctx["token"], ctx["scope"], "warehouse", 99)
    async with ctx["repository"].transaction() as conn:
        await conn.execute(
            update(sources)
            .where(sources.c.scope_id == ctx["scope_id"], sources.c.source_id == "warehouse")
            .values(enabled=0)
        )
    with pytest.raises(ManagementError) as disabled:
        await service.field_catalog(ctx["token"], ctx["scope"], "warehouse", 1)
    assert disabled.value.status == 403


async def test_field_catalog_http_session_no_store_and_parameters(basis_context):
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.metrics_api import create_metrics_router
    from smart_reporting.management.settings import ManagementSettings

    ctx = basis_context
    app = FastAPI()
    app.include_router(
        create_metrics_router(
            MetricService(ctx["scopes"]),
            ManagementSettings(public_origin="https://reports.example"),
        )
    )
    path = "/management/api/v1/metric-field-catalog"
    params = {
        "scopeDatabase": ctx["scope"].database,
        "companyId": ctx["scope"].company_id,
        "sourceId": "warehouse",
        "sourceRevision": 1,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://reports.example"
    ) as client:
        assert (await client.get(path, params=params)).status_code == 401
        client.cookies.set(SESSION_COOKIE, ctx["token"], path="/management")
        result = await client.get(path, params=params)
        assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
        assert len(result.json()["items"]) == 3
        assert "credential" not in result.text.lower() and "dsn" not in result.text.lower()
        for patch in ({"sourceRevision": 0}, {"limit": 0}, {"q": "x" * 201}, {"after": "x" * 521}):
            assert (await client.get(path, params={**params, **patch})).status_code == 422


async def test_field_catalog_ignores_new_unpublished_directory_binding(basis_context):
    import copy

    from sqlalchemy import insert, select, update

    from smart_reporting.management.catalog import CatalogService
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.repository import catalog_versions, source_drafts

    ctx = basis_context
    async with ctx["repository"].transaction() as connection:
        original = (
            (
                await connection.execute(
                    select(catalog_versions).where(
                        catalog_versions.c.scope_id == ctx["scope_id"],
                        catalog_versions.c.source_id == "warehouse",
                        catalog_versions.c.revision == 1,
                    )
                )
            )
            .mappings()
            .one()
        )
        snapshot = copy.deepcopy(original["catalog"])
        snapshot["metadata"]["tables"][0]["columns"][0]["description"] = "draft-only 未发布字段说明"
        snapshot["tables"][0]["columns"][0]["description"] = "draft-only 未发布字段说明"
        await connection.execute(
            insert(catalog_versions).values(
                scope_id=ctx["scope_id"],
                source_id="warehouse",
                revision=2,
                status="draft",
                catalog=snapshot,
                content_hash=CatalogService._hash(snapshot),
                synced_at=original["synced_at"],
            )
        )
        await connection.execute(
            update(source_drafts)
            .where(
                source_drafts.c.scope_id == ctx["scope_id"],
                source_drafts.c.source_id == "warehouse",
            )
            .values(metadata_version_id="warehouse:2")
        )
    service = MetricService(ctx["scopes"])
    result = await service.field_catalog(ctx["token"], ctx["scope"], "warehouse", 1)
    assert result["catalogVersion"]["revision"] == 1 and len(result["items"]) == 3
    assert all(row["description"] == "" for row in result["items"])
    assert (
        await service.field_catalog(ctx["token"], ctx["scope"], "warehouse", 1, query="draft-only")
    )["items"] == []
