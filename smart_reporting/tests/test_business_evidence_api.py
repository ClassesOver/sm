"""证据集合HTTP权限、显式发布与丢响应读回。"""

import httpx
import pytest
from fastapi import FastAPI

from smart_reporting.management.api import SESSION_COOKIE, csrf_token
from smart_reporting.reporting.tests.test_business_evidence_index import (
    index_context as index_context,
)
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_business_evidence_publication import (
    approved_document,
    evidence_service,
)
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def evidence_client(document_context, index_context):
    from smart_reporting.management.business_evidence_api import create_business_evidence_router
    from smart_reporting.management.settings import ManagementSettings
    app = FastAPI()
    service = evidence_service(document_context, index_context)
    app.include_router(create_business_evidence_router(service, ManagementSettings(public_origin="https://reports.example")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://reports.example") as client:
        client.cookies.set(SESSION_COOKIE, document_context[1], path="/management")
        yield client, {"origin": "https://reports.example", "x-csrf-token": csrf_token(document_context[1])}


def release_payload(**changes):
    return {"scopeDatabase": "warehouse", "companyId": "a", "requestId": "release-http-1",
        "kind": "rule_evidence", "revisionIds": [{"documentId": "budget-rules", "revision": 1}], **changes}


async def test_release_http_enforces_session_csrf_and_exact_contract(evidence_client):
    client, headers = evidence_client
    path = "/management/api/v1/business-evidence-releases"
    assert (await client.post(path, json=release_payload())).status_code == 403
    assert (await client.post(path, json=release_payload(profileId="old"), headers=headers)).status_code == 422
    client.cookies.clear()
    assert (await client.post(path, json=release_payload(), headers=headers)).status_code == 401


async def test_release_http_readback_by_request_search_and_organization_isolation(evidence_client, document_context):
    await approved_document(document_context)
    client, headers = evidence_client
    path = "/management/api/v1/business-evidence-releases"
    published = await client.post(path, json=release_payload(), headers=headers)
    assert published.status_code == 201
    release = published.json()
    params = {"scopeDatabase": "warehouse", "companyId": "a"}
    readback = await client.get(path, params={**params, "requestId": "release-http-1"})
    assert readback.status_code == 200 and readback.json() == release
    assert readback.headers["cache-control"] == "no-store"
    assert (await client.get(f"{path}/{release['releaseId']}", params={**params, "companyId": "b"})).status_code == 404
    result = await client.post(f"{path}/{release['releaseId']}/search-preview", headers=headers, json={
        **params, "query": "执行率", "metricIds": ["execution-rate"],
        "period": {"start": "2026-01-01", "end": "2026-10-01"},
        "knowledgeAsOf": document_context[0].clock().isoformat(),
    })
    assert result.status_code == 200 and result.json()["status"] == "matched"


async def test_unconfigured_index_does_not_publish_or_report_no_match(document_context):
    from smart_reporting.management.business_evidence import BusinessEvidenceService
    from smart_reporting.management.models import ManagementError
    from smart_reporting.tests.test_business_evidence_publication import publish
    await approved_document(document_context)
    service = BusinessEvidenceService(document_context[0], None)
    with pytest.raises(ManagementError) as unavailable:
        await publish(service, document_context)
    assert unavailable.value.status == 503


async def test_application_mounts_evidence_routes_with_explicit_unavailable_backend(document_context, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from cryptography.fernet import Fernet

    monkeypatch.setenv("AGENT_MANAGEMENT_CREDENTIAL_KEYS", f"isolated-test:{Fernet.generate_key().decode()}")
    from smart_reporting import app as module
    await approved_document(document_context)
    documents, token, _, *_ = document_context
    monkeypatch.setattr(module, "agent_database", SimpleNamespace(async_engine=documents.repository.engine))
    monkeypatch.setattr(module, "AdminAuthService", lambda repository: documents.scopes.auth)
    monkeypatch.setattr(module, "reporting_workspace_registry", SimpleNamespace(root=tmp_path / "workspace"))
    monkeypatch.setenv("AGENT_MANAGEMENT_PUBLIC_ORIGIN", "https://reports.example")
    application = module.create_base_app(module.application_context)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(application), base_url="https://reports.example") as client:
        client.cookies.set(SESSION_COOKIE, token, path="/management")
        response = await client.post("/management/api/v1/business-evidence-releases", json=release_payload(), headers={
            "origin": "https://reports.example", "x-csrf-token": csrf_token(token),
        })
        assert response.status_code == 503
