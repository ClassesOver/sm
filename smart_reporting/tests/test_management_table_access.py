from __future__ import annotations

import pytest
from sqlalchemy import select

from smart_reporting.management.models import ManagementError, ManagementScope
from smart_reporting.management.repository import catalog_versions, source_drafts
from smart_reporting.tests.management_fixtures import publish_dependencies
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_management_release_dependencies import (
    release_context as release_context,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
async def access_context(release_context, monkeypatch):
    from smart_reporting.management.table_access import TableAccessService

    sources, scopes, repo, token, scope = release_context
    await publish_dependencies(scopes, token, scope)
    await sources.publish(token, scope, "operations", 1)
    service = TableAccessService(scopes, sources.vault)
    from smart_reporting.reporting.data_source.models import CatalogColumn, CatalogTable

    tables = (
        CatalogTable(
            "operations", "warehouse", "orders", (CatalogColumn("amount", "DECIMAL(18,2)", False),)
        ),
        CatalogTable(
            "operations", "warehouse", "private_orders", (CatalogColumn("id", "BIGINT", False),)
        ),
    )

    async def discover(config):
        return [
            {
                "database": t.database,
                "name": t.name,
                "type": "view" if t.name == "private_orders" else "table",
                **service.catalogs._payload((t,))[0],
            }
            for t in tables
        ]

    async def read(config, selected):
        return tuple(t for t in tables if (t.database, t.name) in set(selected))

    monkeypatch.setattr(service, "_discover", discover)
    monkeypatch.setattr(service, "_read_selected", read)
    return service, sources, scopes, repo, token, scope


async def test_selection_is_atomic_and_only_changes_newly_published_runs(access_context):
    service, sources, scopes, repo, token, scope = access_context
    from smart_reporting.management.runtime import ManagedConfigurationProvider

    provider = ManagedConfigurationProvider(scopes, sources.vault)

    async def freeze(run_id):
        await provider.register_run(run_id, scope, user_id="7", thread_id=run_id, entrypoint="cli")
        return await provider.freeze(run_id, scope, ("operations",))

    old_run = await freeze("before-range-change")
    assert [t.name for t in old_run.metadata["operations"].tables] == ["orders"]
    snapshot = await service.discover(token, scope, "operations", 1)
    before = await service.access(token, scope, "operations")
    assert before["draftTables"] == [{"database": "warehouse", "name": "orders"}]
    page = await service.tables(
        token, scope, "operations", snapshot["discoveryId"], q="private", limit=1
    )
    assert page["total"] == 1 and page["items"][0]["type"] == "view"
    assert page["items"][0]["selected"] is False
    saved = await service.save(
        token, scope, "operations", 1, snapshot["discoveryId"], [("warehouse", "private_orders")]
    )
    assert saved["draftVersion"] == 2
    assert saved["warnings"]
    access = await service.access(token, scope, "operations")
    assert any("业务语义" in warning for warning in access["warnings"])
    assert access["publishedTables"] == [{"database": "warehouse", "name": "orders"}]
    assert access["draftTables"] == [{"database": "warehouse", "name": "private_orders"}]
    async with repo.engine.connect() as conn:
        draft = (await conn.execute(select(source_drafts))).mappings().one()
        assert draft["metadata_version_id"] == "operations:2"
        row = (
            (await conn.execute(select(catalog_versions).where(catalog_versions.c.revision == 2)))
            .mappings()
            .one()
        )
        assert [t["name"] for t in row["catalog"]["metadata"]["tables"]] == ["private_orders"]
        assert "orders.amount" not in str(row["catalog"]["metadata"])
    check = await sources.release_check(token, scope, "operations", 2)
    assert check["warnings"]
    assert check["canPublish"] is True
    assert check["tableAccessChanges"]["added"] == ["warehouse.private_orders"]
    assert check["tableAccessChanges"]["removed"] == ["warehouse.orders"]
    assert (await sources.list(token, scope))["items"][0]["publishedTableCount"] == 1
    before_publish = await freeze("before-range-publication")
    assert [t.name for t in before_publish.metadata["operations"].tables] == ["orders"]
    await sources.publish(token, scope, "operations", 2)
    new_run = await freeze("after-range-publication")
    assert [t.name for t in new_run.metadata["operations"].tables] == ["private_orders"]
    assert new_run.metadata["operations"].terms == ()
    restored = await ManagedConfigurationProvider(scopes, sources.vault).load_pinned(
        scope, old_run.references
    )
    assert [t.name for t in restored.metadata["operations"].tables] == ["orders"]
    assert restored.references == old_run.references
    assert (await service.access(token, scope, "operations"))["publishedTables"] == access[
        "draftTables"
    ]
    with pytest.raises(ManagementError) as error:
        await service.save(
            token, scope, "operations", 1, snapshot["discoveryId"], [("warehouse", "orders")]
        )
    assert error.value.status == 409


async def test_foreign_snapshot_empty_unknown_and_changed_connection_are_rejected(access_context):
    service, sources, scopes, repo, token, scope = access_context
    snapshot = await service.discover(token, scope, "operations", 1)
    with pytest.raises(ManagementError) as empty:
        await service.save(token, scope, "operations", 1, snapshot["discoveryId"], [])
    assert empty.value.status == 422
    with pytest.raises(ManagementError):
        await service.save(
            token, scope, "operations", 1, snapshot["discoveryId"], [("warehouse", "*")]
        )
    foreign = ManagementScope("warehouse", "200")
    await scopes.register(token, foreign, "公司二")
    from smart_reporting.management.data_sources.models import SourceDraftInput

    await sources.create_draft(
        token,
        foreign,
        "operations",
        SourceDraftInput.model_validate(
            {
                "name": "同名数仓",
                "database": "warehouse",
                "dsn": "starrocks://reader:foreign@localhost:9030/warehouse",
            }
        ),
    )
    with pytest.raises(ManagementError) as foreign_error:
        await service.tables(token, foreign, "operations", snapshot["discoveryId"])
    assert foreign_error.value.code == "management_discovery_not_found"
    with pytest.raises(ManagementError) as foreign_save:
        await service.save(
            token, foreign, "operations", 1, snapshot["discoveryId"], [("warehouse", "orders")]
        )
    assert foreign_save.value.status == 404

    await sources.save_draft(
        token,
        scope,
        "operations",
        SourceDraftInput.model_validate(
            {
                "name": "更换连接",
                "database": "warehouse",
                "dsn": "starrocks://reader:new@localhost:9030/warehouse",
                "reportingProfileVersionId": "base:1",
                "metadataVersionId": "operations:1",
            }
        ),
        1,
    )
    with pytest.raises(ManagementError) as stale:
        await service.save(
            token, scope, "operations", 2, snapshot["discoveryId"], [("warehouse", "orders")]
        )
    assert stale.value.status == 409
    assert (await sources.release_check(token, scope, "operations", 2))["canPublish"] is False


async def test_save_rechecks_draft_after_external_io_and_rolls_back_catalog(
    access_context, monkeypatch
):
    service, sources, _, repo, token, scope = access_context
    snapshot = await service.discover(token, scope, "operations", 1)
    original = service._read_selected

    async def racing(config, selected):
        from smart_reporting.management.data_sources.models import SourceDraftInput

        await sources.save_draft(
            token,
            scope,
            "operations",
            SourceDraftInput.model_validate(
                {
                    "name": "并发更新",
                    "database": "warehouse",
                    "reportingProfileVersionId": "base:1",
                    "metadataVersionId": "operations:1",
                }
            ),
            1,
        )
        return await original(config, selected)

    monkeypatch.setattr(service, "_read_selected", racing)
    with pytest.raises(ManagementError) as stale:
        await service.save(
            token, scope, "operations", 1, snapshot["discoveryId"], [("warehouse", "orders")]
        )
    assert stale.value.status == 409
    async with repo.engine.connect() as conn:
        assert len((await conn.execute(select(catalog_versions))).all()) == 1


async def test_http_contract_csrf_paging_columns_and_cross_scope(access_context, monkeypatch):
    import httpx
    from fastapi import FastAPI

    from smart_reporting.management.api import csrf_token
    from smart_reporting.management.table_access import TableAccessService
    from smart_reporting.management.table_access_api import create_table_access_router

    service, sources, scopes, _, token, scope = access_context
    monkeypatch.setenv("AGENT_MANAGEMENT_PUBLIC_ORIGIN", "https://reports.test")

    async def discover(self, config):
        return await service._discover(config)

    async def read(self, config, selected):
        return await service._read_selected(config, selected)

    monkeypatch.setattr(TableAccessService, "_discover", discover)
    monkeypatch.setattr(TableAccessService, "_read_selected", read)
    app = FastAPI()
    app.include_router(create_table_access_router(scopes, sources.vault))
    base = "/management/api/v1/sources/operations"
    identity = {"scopeDatabase": "warehouse", "companyId": "100"}
    headers = {"origin": "https://reports.test", "x-csrf-token": csrf_token(token)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://reports.test"
    ) as client:
        assert (await client.get(base + "/table-access", params=identity)).status_code == 401
        client.cookies.set("report_management_session", token, path="/management")
        body = {**identity, "expectedDraftVersion": 1}
        assert (await client.post(base + "/table-discoveries", json=body)).status_code == 403
        response = await client.post(base + "/table-discoveries", json=body, headers=headers)
        assert response.status_code == 201, response.text
        snapshot = response.json()
        assert snapshot["warnings"]
        path = base + "/table-discoveries/" + snapshot["discoveryId"]
        first = (await client.get(path + "/tables", params={**identity, "limit": 1})).json()
        assert first["items"][0]["name"] == "orders" and first["nextOffset"] == 1
        second = (
            await client.get(path + "/tables", params={**identity, "limit": 1, "offset": 1})
        ).json()
        assert second["items"][0]["name"] == "private_orders"
        columns = await client.get(
            path + "/columns", params={**identity, "database": "warehouse", "table": "orders"}
        )
        assert columns.json()["columns"][0]["dataType"] == "DECIMAL(18,2)"
        assert (
            await client.get(path + "/tables", params={**identity, "companyId": "foreign"})
        ).status_code == 404
        invalid = {
            **body,
            "discoveryId": snapshot["discoveryId"],
            "selectedTables": [{"database": "warehouse", "name": "*"}],
        }
        assert (
            await client.put(base + "/table-access", json=invalid, headers=headers)
        ).status_code == 422
        valid = {**invalid, "selectedTables": [{"database": "warehouse", "name": "private_orders"}]}
        saved = await client.put(base + "/table-access", json=valid, headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.json()["draftVersion"] == 2
        assert (
            await client.put(base + "/table-access", json=valid, headers=headers)
        ).status_code == 409
        assert "test-secret" not in saved.text + response.text + columns.text


async def test_missing_selected_objects_are_reported_and_read_failure_keeps_range(
    access_context, monkeypatch
):
    service, _, _, _, token, scope = access_context
    original = service._discover

    async def without_orders(config):
        return [t for t in await original(config) if t["name"] != "orders"]

    monkeypatch.setattr(service, "_discover", without_orders)
    snapshot = await service.discover(token, scope, "operations", 1)
    page = await service.tables(token, scope, "operations", snapshot["discoveryId"])
    assert page["missingTables"] == [{"database": "warehouse", "name": "orders"}]

    async def fail(config, selected):
        raise RuntimeError("private credentials")

    monkeypatch.setattr(service, "_read_selected", fail)
    with pytest.raises(ManagementError) as error:
        await service.save(
            token,
            scope,
            "operations",
            1,
            snapshot["discoveryId"],
            [("warehouse", "private_orders")],
        )
    assert error.value.status == 422 and "private credentials" not in error.value.message
    assert (await service.access(token, scope, "operations"))["draftVersion"] == 1


async def test_existing_business_semantics_survive_selection_and_unbound_terms_do_not_leak(
    access_context,
):
    service, _, _, repo, token, scope = access_context
    snapshot = await service.discover(token, scope, "operations", 1)
    await service.save(
        token, scope, "operations", 1, snapshot["discoveryId"], [("warehouse", "orders")]
    )
    async with repo.engine.connect() as conn:
        payload = await conn.scalar(
            select(catalog_versions.c.catalog).where(catalog_versions.c.revision == 2)
        )
    assert payload["metadata"]["terms"][0]["name"] == "收入"
    assert payload["metadata"]["measureSemantics"][0]["unit"] == "元"
    from smart_reporting.reporting.contract import parse_ddl

    parsed = parse_ddl(
        payload["metadata"]["ddlModels"][0]["ddl"],
        source_id="operations",
        default_database="warehouse",
    )
    assert [t.name for t in parsed] == ["orders"]


async def test_concurrent_range_saves_only_one_creates_a_catalog(access_context):
    import asyncio

    service, _, _, repo, token, scope = access_context
    snapshot = await service.discover(token, scope, "operations", 1)
    results = await asyncio.gather(
        service.save(
            token, scope, "operations", 1, snapshot["discoveryId"], [("warehouse", "orders")]
        ),
        service.save(
            token,
            scope,
            "operations",
            1,
            snapshot["discoveryId"],
            [("warehouse", "private_orders")],
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    errors = [result for result in results if isinstance(result, ManagementError)]
    assert len(errors) == 1 and errors[0].status == 409
    async with repo.engine.connect() as conn:
        assert len((await conn.execute(select(catalog_versions))).all()) == 2
    assert (await service.access(token, scope, "operations"))["draftVersion"] == 2
