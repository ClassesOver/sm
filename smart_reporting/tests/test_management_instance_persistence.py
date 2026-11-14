"""在独立 PostgreSQL 验证无登记首次访问与实例配置持久化。"""

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from smart_reporting.management.api import SESSION_COOKIE, csrf_token
from smart_reporting.management.data_sources.api import create_source_router
from smart_reporting.management.data_sources.secrets import CredentialVault
from smart_reporting.management.models import INSTANCE_SCOPE, INSTANCE_SCOPE_ID
from smart_reporting.management.repository import tenant_settings
from smart_reporting.management.scopes import ScopeService
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_first_source_read_initializes_once_and_create_needs_no_registration(auth_context, monkeypatch):
    auth, repository, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    token = (await auth.login("admin", OLD_PASSWORD, "127.0.0.1")).raw_token
    monkeypatch.setenv("AGENT_MANAGEMENT_PUBLIC_ORIGIN", "https://reports.example")
    app = FastAPI()
    app.include_router(create_source_router(ScopeService(auth), CredentialVault("test:" + CredentialVault.generate_key())))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://reports.example") as client:
        client.cookies.set(SESSION_COOKIE, token)
        reads = await asyncio.gather(*(client.get("/management/api/v1/sources") for _ in range(3)))
        assert all(response.status_code == 200 and response.json()["items"] == [] for response in reads)
        created = await client.post("/management/api/v1/sources", json={
            "sourceId": "budget", "name": "预算数仓", "database": "budget", "dsn": "starrocks://test:test@localhost:9030/budget",
        }, headers={"origin": "https://reports.example", "x-csrf-token": csrf_token(token)})
        assert created.status_code == 201, created.text
        normal = await client.get("/management/api/v1/sources")
        legacy_url = await client.get("/management/api/v1/sources?scopeDatabase=foreign&companyId=foreign")
        assert normal.json() == legacy_url.json()
        assert normal.json()["items"][0]["source_id"] == "budget"
    async with repository.engine.connect() as connection:
        rows = (await connection.execute(select(tenant_settings))).mappings().all()
        assert len(rows) == 1
        assert rows[0]["database"] == INSTANCE_SCOPE.database
        assert rows[0]["id"] == INSTANCE_SCOPE_ID


async def test_document_upload_and_original_read_need_no_organization(auth_context, tmp_path):
    from smart_reporting.management.business_documents import BusinessDocumentService
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.reporting.business_knowledge.originals import BusinessOriginalStore

    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    token = (await auth.login("admin", OLD_PASSWORD, "127.0.0.1")).raw_token
    service = BusinessDocumentService(ScopeService(auth), BusinessOriginalStore(tmp_path / "originals"))
    app = FastAPI()
    app.include_router(create_business_documents_router(service, ManagementSettings(public_origin="https://reports.example")))
    headers = {"origin": "https://reports.example", "x-csrf-token": csrf_token(token)}
    data = {"expectedVersion": "0", "requestId": "upload-instance-1", "metadata": json.dumps({
        "id": "budget-rules", "title": "预算制度", "kind": "rule_evidence", "validFrom": "2026-01-01",
    })}
    content = "预算金额按项目合计。".encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://reports.example") as client:
        client.cookies.set(SESSION_COOKIE, token)
        response = await client.post("/management/api/v1/business-documents", data=data,
            files={"file": ("rules.txt", content, "text/plain")}, headers=headers)
        assert response.status_code == 201, response.text
        assert response.json()["revision"] == 1
        assert await service.read_original(token, INSTANCE_SCOPE, "budget-rules", 1) == content
        rejected = await client.post("/management/api/v1/business-documents", data={**data, "companyId": "foreign"},
            files={"file": ("rules.txt", content, "text/plain")}, headers=headers)
        assert rejected.status_code == 422
