from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import func, select

from smart_reporting.management.catalog import CatalogService
from smart_reporting.management.data_sources.models import SourceDraftInput
from smart_reporting.management.models import ManagementError
from smart_reporting.management.repository import catalog_versions
from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
from smart_reporting.reporting.metadata import ReportingMetadataClient
from smart_reporting.tests.management_fixtures import physical_catalog
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_management_release_dependencies import (
    release_context as release_context,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
async def metadata_client():
    def respond(request):
        if request.url.path == "/get_agent_json":
            data = {"agent_list": [{"id": 1, "name": "经营报告", "desc": ""}]}
        else:
            assert json.loads(request.content) == {"agent_id": 1}
            data = {
                "ddl": [
                    {
                        "id": 1,
                        "modelName": "订单",
                        "ddl": ("CREATE TABLE warehouse.orders (amount DECIMAL(18,2) NOT NULL)"),
                    }
                ],
                "term": [{"id": 1, "key": "收入", "value": "经营业务收入"}],
                "measureSemantics": [
                    {
                        "fieldRef": "operations.warehouse.orders.amount",
                        "aggregation": "sum",
                        "unit": "元",
                    }
                ],
            }
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(
        base_url="https://metadata.test", transport=httpx.MockTransport(respond)
    ) as client:
        yield ReportingMetadataClient("https://metadata.test", client_factory=lambda: client)


async def test_sync_reads_server_draft_connection_and_metadata(
    release_context, metadata_client, monkeypatch
):
    sources, scopes, repo, token, scope = release_context

    # 只替换数仓网络 I/O；保留真实 adapter 构造、关闭和 metadata 响应解析。
    def catalog(adapter):
        assert adapter.config.dsn.get_secret_value().endswith("/warehouse")
        assert adapter.allowed_tables == ("warehouse.orders",)
        return physical_catalog()

    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", catalog)
    catalogs = CatalogService(scopes, vault=sources.vault, metadata_client=metadata_client)
    result = await catalogs.synchronize(token, scope, "operations", 1)
    await catalogs.publish(token, scope, "operations", result["revision"])
    current = await catalogs.current(token, scope, "operations")
    assert current["catalog"][0]["columns"][0]["name"] == "amount"
    assert current["metadata"]["terms"][0]["name"] == "收入"
    assert current["metadata"]["measureSemantics"][0]["aggregation"] == "sum"
    assert "test-secret" not in str(current)


async def test_draft_change_during_sync_cannot_publish_stale_result(
    release_context, metadata_client, monkeypatch
):
    sources, scopes, repo, token, scope = release_context

    async def catalog(adapter):
        await sources.save_draft(
            token,
            scope,
            "operations",
            SourceDraftInput.model_validate(
                {
                    "name": "新连接",
                    "database": "warehouse",
                    "dsn": "starrocks://reporter:changed-secret@localhost:9030/warehouse",
                }
            ),
            1,
        )
        return physical_catalog()

    monkeypatch.setattr(StarRocksDataSourceAdapter, "catalog", catalog)
    catalogs = CatalogService(scopes, vault=sources.vault, metadata_client=metadata_client)
    with pytest.raises(ManagementError, match="management_version_conflict"):
        await catalogs.synchronize(token, scope, "operations", 1)
    async with repo.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(catalog_versions)) == 0


async def test_sync_failure_keeps_previous_published_catalog(
    release_context, metadata_client, monkeypatch
):
    sources, scopes, _, token, scope = release_context
    from smart_reporting.tests.management_fixtures import publish_dependencies

    await publish_dependencies(scopes, token, scope)

    def fail(adapter):
        raise RuntimeError("private upstream dsn and password")

    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", fail)
    catalogs = CatalogService(scopes, vault=sources.vault, metadata_client=metadata_client)
    with pytest.raises(ManagementError) as error:
        await catalogs.synchronize(token, scope, "operations", 1)
    assert error.value.code == "management_catalog_sync_failed"
    assert "private" not in error.value.message
    assert (await catalogs.current(token, scope, "operations"))["revision"] == 1
