from __future__ import annotations

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from smart_reporting.management.data_sources.api import create_source_router
from smart_reporting.management.data_sources.models import SourceDraftInput
from smart_reporting.management.data_sources.secrets import CredentialVault
from smart_reporting.management.data_sources.service import SourceService
from smart_reporting.management.models import ManagementScope
from smart_reporting.management.scopes import ScopeService
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_source_list_requires_admin_is_scoped_paginated_and_redacted(auth_context):
    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    token = (await auth.login("admin", OLD_PASSWORD, "127.0.0.1")).raw_token
    scopes = ScopeService(auth)
    vault = CredentialVault(f"test:{Fernet.generate_key().decode()}")
    service = SourceService(scopes, vault)
    for company in ("100", "200"):
        scope = ManagementScope("warehouse", company)
        await scopes.register(token, scope, company)
        for source_id in ("a", "b"):
            await service.create_draft(token, scope, source_id, SourceDraftInput(
                name=f"{company}-{source_id}", database="warehouse",
                dsn="starrocks://reporter:secret-password@localhost:9030/warehouse",
            ))
    app = FastAPI()
    app.include_router(create_source_router(scopes, vault))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://reports.test") as client:
        path = "/management/api/v1/sources"
        params = {"scopeDatabase": "warehouse", "companyId": "100", "limit": 1}
        assert (await client.get(path, params=params)).status_code == 401
        client.cookies.set("report_management_session", token, path="/management")
        first = await client.get(path, params=params)
        assert first.status_code == 200, first.text
        assert [item["source_id"] for item in first.json()["items"]] == ["a"]
        assert first.json()["nextCursor"] == "a"
        assert first.json()["items"][0]["name"] == "100-a"
        assert first.json()["items"][0]["enabled"] is True
        assert first.json()["items"][0]["publishedRevision"] is None
        for forbidden in ("dsn", "credential", "secret-password", "ciphertext", "200-"):
            assert forbidden not in first.text
        second = await client.get(path, params={**params, "after": first.json()["nextCursor"]})
        assert second.json()["items"][0]["source_id"] == "b"
        assert second.json()["nextCursor"] is None
        missing = await client.get(path, params={**params, "companyId": "missing"})
        assert missing.status_code == 404
        assert (await client.get(path, params={**params, "limit": 101})).status_code == 422
