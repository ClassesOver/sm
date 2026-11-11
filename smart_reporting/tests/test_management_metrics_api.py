"""指标HTTP契约：组织列表、草稿CAS与显式发布。"""

import httpx
import pytest
from fastapi import FastAPI

from smart_reporting.management.api import SESSION_COOKIE, csrf_token
from smart_reporting.reporting.tests.test_semantic_models import metric_payload
from smart_reporting.tests.test_management_metrics import context, draft
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def metric_client(auth_context):
    from smart_reporting.management.metrics_api import create_metrics_router
    from smart_reporting.management.settings import ManagementSettings
    service, token, scope, other = await context(auth_context)
    application = FastAPI()
    application.include_router(create_metrics_router(service, ManagementSettings(public_origin="https://reports.example")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(application), base_url="https://reports.example") as client:
        client.cookies.set(SESSION_COOKIE, token, path="/management")
        yield client, {"origin": "https://reports.example", "x-csrf-token": csrf_token(token)}, service, token, scope, other


async def test_metric_http_requires_auth_csrf_and_rejects_old_fields(metric_client):
    client, headers, *_ = metric_client
    payload = {"scopeDatabase": "warehouse", "companyId": "a", "expectedVersion": 0, "definition": draft(metric_payload())}
    path = "/management/api/v1/metrics/budget/draft"
    assert (await client.put(path, json=payload)).status_code == 403
    assert (await client.put(path, json={**payload, "profileId": "old"}, headers=headers)).status_code == 422
    assert (await client.put("/management/api/v1/metrics/other/draft", json=payload, headers=headers)).status_code == 422
    client.cookies.clear()
    assert (await client.get("/management/api/v1/metrics", params={"scopeDatabase": "warehouse", "companyId": "a"})).status_code == 401


async def test_metric_http_publish_readback_and_scope_pagination(metric_client):
    client, headers, service, token, scope, other = metric_client
    params = {"scopeDatabase": "warehouse", "companyId": "a"}
    for identity in ("budget", "actual"):
        saved = await client.put(f"/management/api/v1/metrics/{identity}/draft", json={
            **params, "expectedVersion": 0, "definition": draft(metric_payload(identity)),
        }, headers=headers)
        assert saved.status_code == 200
    await service.save_draft(token, other, draft(metric_payload("foreign-only")), 0)
    published = await client.post("/management/api/v1/metrics/budget/publish", json={**params, "expectedVersion": 1}, headers=headers)
    assert published.status_code == 200 and published.json()["revision"] == 1
    stale = await client.post("/management/api/v1/metrics/budget/publish", json={**params, "expectedVersion": 2}, headers=headers)
    assert stale.status_code == 409
    first = await client.get("/management/api/v1/metrics", params={**params, "limit": 1})
    assert first.status_code == 200 and first.json()["items"][0]["metricId"] == "actual"
    second = await client.get("/management/api/v1/metrics", params={**params, "limit": 1, "after": first.json()["nextCursor"]})
    assert second.json()["items"][0]["metricId"] == "budget" and second.json()["nextCursor"] is None
    assert (await client.get("/management/api/v1/metrics/foreign-only", params=params)).status_code == 404
    assert (await client.get("/management/api/v1/metrics/budget", params=params)).json()["published"]["revision"] == 1


async def test_metric_http_reads_exact_retired_revision_and_replacement(metric_client):
    client, _, service, token, scope, _ = metric_client
    for version in (1, 2):
        await service.save_draft(token, scope, draft(metric_payload(name=f"第{version}版")), version - 1)
        await service.publish(token, scope, "budget", expected_version=version)
    await service.retire(token, scope, "budget", 1, reason="使用第二版", replacement={"metricId": "budget", "revision": 2})
    path = "/management/api/v1/metrics/budget"
    params = {"scopeDatabase": "warehouse", "companyId": "a"}
    first = (await client.get(path, params={**params, "revision": 1})).json()
    assert first["published"]["document"]["name"] == "第1版"
    assert first["retirement"]["reason"] == "使用第二版"
    assert first["retirement"]["replacement"] == {"metricId": "budget", "revision": 2}
    assert (await client.get(path, params=params)).json()["published"]["revision"] == 2
    assert (await client.get(path, params={**params, "revision": 3})).status_code == 404
