"""业务原件HTTP契约：鉴权、CSRF、组织隔离和有界multipart。"""

import json

import httpx
import pytest
from fastapi import FastAPI

from smart_reporting.management.api import SESSION_COOKIE, csrf_token
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def document_client(document_context):
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.settings import ManagementSettings
    service, token, *_ = document_context
    app = FastAPI()
    app.include_router(create_business_documents_router(service, ManagementSettings(public_origin="https://reports.example")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://reports.example") as client:
        client.cookies.set(SESSION_COOKIE, token, path="/management")
        yield client, {"origin": "https://reports.example", "x-csrf-token": csrf_token(token)}


def upload_fields(**changes):
    return {
        "scopeDatabase": "warehouse", "companyId": "a", "expectedVersion": "0",
        "requestId": "upload-1", "metadata": json.dumps({
            "id": "rules", "title": "合成口径", "kind": "rule_evidence",
            "validFrom": "2026-01-01", "validTo": "2027-01-01",
        }), **changes,
    }


async def test_business_upload_requires_admin_csrf_and_exact_form_contract(document_client):
    client, headers = document_client
    files = {"file": ("rules.txt", b"text", "text/plain")}
    assert (await client.post("/management/api/v1/business-documents", data=upload_fields(), files=files)).status_code == 403
    assert (await client.post("/management/api/v1/business-documents", data=upload_fields(serverPath="/tmp/foreign"), files=files, headers=headers)).status_code == 422
    assert (await client.post("/management/api/v1/business-documents", data=upload_fields(metadata='{"id":"rules","title":"t","kind":"rule_evidence","profileId":"old"}'), files=files, headers=headers)).status_code == 422
    client.cookies.clear()
    assert (await client.post("/management/api/v1/business-documents", data=upload_fields(), files=files, headers=headers)).status_code == 401


async def test_upload_over_64k_readback_review_and_original_are_authorized(document_client, document_context):
    client, headers = document_client
    service = document_context[0]
    text = ("执行率使用合计比值。\n" * 10000).encode()
    uploaded = await client.post("/management/api/v1/business-documents", data=upload_fields(), files={"file": ("rules.txt", text, "text/plain")}, headers=headers)
    assert uploaded.status_code == 201
    receipt = uploaded.json()
    params = {"scopeDatabase": "warehouse", "companyId": "a"}
    job_url = f"/management/api/v1/business-ingestion-jobs/{receipt['jobId']}"
    assert (await client.get(job_url, params={**params, "companyId": "b"})).status_code == 404
    assert (await client.get(job_url, params=params)).json()["status"] == "queued"
    await service.ingest_revision(await service.claim_next())
    detail = await client.get("/management/api/v1/business-documents/rules", params=params)
    assert detail.status_code == 200
    state = detail.json()["revisions"][0]
    reviewed = await client.post("/management/api/v1/business-documents/rules/revisions/1/review", json={
        **params, "expectedVersion": state["stateVersion"], "decision": "approved", "reason": "核对原件",
    }, headers=headers)
    assert reviewed.status_code == 200
    assert reviewed.json()["ingestionStatus"] == "parsed"
    original_url = "/management/api/v1/business-documents/rules/revisions/1/original"
    original = await client.get(original_url, params=params)
    assert original.content == text
    assert original.headers["cache-control"] == "no-store"
    assert original.headers["x-content-type-options"] == "nosniff"
    assert (await client.get(original_url, params={**params, "companyId": "b"})).status_code == 404


async def test_file_over_20mib_and_streamed_envelope_over_budget_are_rejected(document_client):
    from smart_reporting.http.request_limits import MAX_BUSINESS_DOCUMENT_REQUEST_BYTES
    client, headers = document_client
    too_large = await client.post("/management/api/v1/business-documents", data=upload_fields(),
        files={"file": ("large.txt", b"x" * (20 * 1024 * 1024 + 1), "text/plain")}, headers=headers)
    assert too_large.status_code == 422

    async def chunks():
        yield b'--missing\r\nContent-Disposition: form-data; name="file"; filename="large.txt"\r\nContent-Type: text/plain\r\n\r\n'
        yield b"x" * (MAX_BUSINESS_DOCUMENT_REQUEST_BYTES // 2)
        yield b"x" * (MAX_BUSINESS_DOCUMENT_REQUEST_BYTES // 2 + 1)

    streamed = await client.post("/management/api/v1/business-documents", content=chunks(), headers={
        **headers, "content-type": "multipart/form-data; boundary=missing",
    })
    assert streamed.status_code == 413


async def test_application_mounts_upload_with_persistent_worker(document_context, monkeypatch, tmp_path):
    import asyncio
    from types import SimpleNamespace

    from smart_reporting import app as module
    from smart_reporting.tests.test_business_ingestion_worker import wait_status

    service, token, scope, *_ = document_context
    monkeypatch.setattr(module, "agent_database", SimpleNamespace(async_engine=service.repository.engine))
    monkeypatch.setattr(module, "AdminAuthService", lambda repository: service.scopes.auth)
    monkeypatch.setattr(module, "reporting_workspace_registry", SimpleNamespace(root=tmp_path / "workspace"))
    monkeypatch.setenv("AGENT_MANAGEMENT_PUBLIC_ORIGIN", "https://reports.example")
    application = module.create_base_app(module.application_context)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(application), base_url="https://reports.example") as client:
        client.cookies.set(SESSION_COOKIE, token, path="/management")
        headers = {"origin": "https://reports.example", "x-csrf-token": csrf_token(token)}
        body = b"budget definition\n" * 10000
        response = await client.post("/management/api/v1/business-documents", data=upload_fields(),
            files={"file": ("rules.txt", body, "text/plain")}, headers=headers)
        assert response.status_code == 201
        worker = application.state.business_ingestion_worker
        assert worker.start in application.router.on_startup
        assert worker.aclose in application.router.on_shutdown
        await worker.start()
        try:
            parsed = await wait_status(worker.service, token, scope, response.json()["jobId"], "parsed")
            assert parsed.attempt == 1
            original = await client.get("/management/api/v1/business-documents/rules/revisions/1/original",
                params={"scopeDatabase": "warehouse", "companyId": "a"})
            assert original.content == body
        finally:
            await asyncio.wait_for(worker.aclose(), 10)
