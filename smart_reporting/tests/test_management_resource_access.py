from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from smart_reporting.management.api import csrf_token
from smart_reporting.management.catalog_api import create_catalog_router
from smart_reporting.management.data_sources.api import create_source_router
from smart_reporting.management.import_api import create_import_router
from smart_reporting.management.profile_api import create_profile_router
from smart_reporting.tests.test_management_catalog_sync import metadata_client as metadata_client
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_management_release_dependencies import (
    release_context as release_context,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def test_all_business_resource_writes_require_admin_before_other_validation(
    release_context, metadata_client, monkeypatch
):
    service, scopes, _, token, _ = release_context
    monkeypatch.setenv("AGENT_MANAGEMENT_PUBLIC_ORIGIN", "https://reports.test")
    app = FastAPI()
    app.include_router(create_source_router(scopes, service.vault))
    app.include_router(create_profile_router(scopes))
    app.include_router(create_catalog_router(scopes, service.vault, metadata_client))
    app.include_router(create_import_router(scopes, service.vault))
    scope = {"scopeDatabase": "warehouse", "companyId": "100"}
    cases = [
        (
            "POST",
            "/sources",
            {
                **scope,
                "sourceId": "another",
                "name": "数仓",
                "database": "warehouse",
                "dsn": "starrocks://r:s@localhost:9030/warehouse",
            },
        ),
        ("POST", "/sources/operations/publish", {**scope, "expectedVersion": 1}),
        ("POST", "/sources/operations/catalog/sync", {**scope, "expectedDraftVersion": 1}),
        (
            "POST",
            "/profiles/preview",
            {**scope, "profile": {"profileId": "base", "revision": "r1"}},
        ),
        ("POST", "/config/import", {**scope, "directory": "/missing", "dryRun": True}),
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://reports.test"
    ) as client:
        for method, path, payload in cases:
            response = await client.request(method, "/management/api/v1" + path, json=payload)
            assert response.status_code == 401, (path, response.text)
        client.cookies.set("report_management_session", token, path="/management")
        response = await client.post(
            "/management/api/v1/sources/operations/catalog/sync",
            json={
                **scope,
                "expectedDraftVersion": 1,
                "catalog": [],
            },
            headers={"origin": "https://reports.test", "x-csrf-token": csrf_token(token)},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "management_input_invalid"


async def test_source_api_creates_and_saves_using_public_aliases(release_context, monkeypatch):
    service, scopes, _, token, _ = release_context
    monkeypatch.setenv("AGENT_MANAGEMENT_PUBLIC_ORIGIN", "https://reports.test")
    app = FastAPI()
    app.include_router(create_source_router(scopes, service.vault))
    headers = {"origin": "https://reports.test", "x-csrf-token": csrf_token(token)}
    payload = {
        "scopeDatabase": "warehouse",
        "companyId": "100",
        "name": " 数仓 ",
        "database": "WAREHOUSE",
        "dsn": "starrocks://r:s@localhost:9030/warehouse",
        "type": "starrocks",
        "reportingProfileVersionId": "base:1",
        "metadataVersionId": "another:1",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://reports.test"
    ) as client:
        client.cookies.set("report_management_session", token, path="/management")
        created = await client.post(
            "/management/api/v1/sources", json={**payload, "sourceId": "another"}, headers=headers
        )
        assert created.status_code == 201, created.text
        assert created.json()["profile_version_id"] == "base:1"
        assert created.json()["name"] == "数仓"
        saved = await client.put(
            "/management/api/v1/sources/another/draft",
            json={**payload, "name": "新名称", "expectedVersion": 1},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["version"] == 2
        assert saved.json()["metadata_version_id"] is None  # 新连接须重新发现并确认范围
        assert "r:s@" not in saved.text
        forbidden = await client.put(
            "/management/api/v1/sources/another/draft",
            json={**payload, "expectedVersion": 2, "maxRows": 1},
            headers=headers,
        )
        assert forbidden.status_code == 422
