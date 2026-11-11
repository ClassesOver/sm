"""统计口径HTTP契约：授权、版本冲突、发布与默认绑定分离。"""

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
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_management_statistical_policies import policy_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def policy_client(document_context, index_context):
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.management.statistical_policy_api import create_statistical_policy_router
    service, definition = await policy_context(document_context, index_context)
    token, scope, other = document_context[1:4]
    app = FastAPI()
    app.include_router(create_statistical_policy_router(service, ManagementSettings(public_origin="https://reports.example")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://reports.example") as client:
        client.cookies.set(SESSION_COOKIE, token, path="/management")
        yield client, {"origin": "https://reports.example", "x-csrf-token": csrf_token(token)}, service, token, scope, other, definition


async def test_policy_http_rejects_unauthorized_and_client_server_identity(policy_client):
    client, headers, *_, definition = policy_client
    params = {"scopeDatabase": "warehouse", "companyId": "a"}
    payload = {**params, "expectedVersion": 0, "definition": definition}
    path = "/management/api/v1/statistical-policies/monthly-budget/draft"
    assert (await client.put(path, json=payload)).status_code == 403
    for changes in ({"scopeId": "draft"}, {"revision": 1}, {"profileId": "old"}):
        assert (await client.put(path, json={**payload, "definition": {**definition, **changes}}, headers=headers)).status_code == 422
    assert (await client.put(path.replace("monthly-budget", "other"), json=payload, headers=headers)).status_code == 422
    assert (await client.post(path.replace("/draft", "/publish"), json={**params, "expectedVersion": 0}, headers=headers)).status_code == 422
    assert (await client.put(path, json=payload, headers={**headers, "origin": "https://foreign.example"})).status_code == 403
    client.cookies.clear()
    assert (await client.get("/management/api/v1/statistical-policies", params=params)).status_code == 401


async def test_policy_http_publish_default_readback_and_scope_pagination(policy_client):
    client, headers, service, token, scope, other, definition = policy_client
    params = {"scopeDatabase": "warehouse", "companyId": "a"}
    base = "/management/api/v1/statistical-policies"
    for identity in ("monthly-budget", "another"):
        response = await client.put(f"{base}/{identity}/draft", json={**params, "expectedVersion": 0,
            "definition": {**definition, "id": identity}}, headers=headers)
        assert response.status_code == 200
    await service.save_draft(token, other, {**definition, "id": "foreign-only"}, expected_version=0)
    assert (await client.get(f"{base}/foreign-only", params=params)).status_code == 404
    published = await client.post(f"{base}/monthly-budget/publish", json={**params, "expectedVersion": 1}, headers=headers)
    assert published.status_code == 200 and published.json()["revision"] == 1
    defaults = "/management/api/v1/report-policy-defaults/budget_execution"
    assert (await client.get(defaults, params=params)).json()["policyVersion"] is None
    selection = {**params, "expectedVersion": 0, "policyVersion": {"policyId": "monthly-budget", "revision": 1}}
    assert (await client.put(defaults, json=selection, headers=headers)).status_code == 200
    assert (await client.put(defaults, json=selection, headers=headers)).status_code == 409
    # 丢失写响应后仅GET读回，不能再写入以猜测结果。
    actual = (await client.get(defaults, params=params)).json()
    assert actual["version"] == 1 and actual["policyVersion"] == {"policyId": "monthly-budget", "revision": 1}
    assert (await client.get(f"{base}/monthly-budget", params=params)).json()["published"]["revision"] == 1
    stale = await client.put(f"{base}/monthly-budget/draft", json={**params, "expectedVersion": 0, "definition": definition}, headers=headers)
    assert stale.status_code == 409
    first = (await client.get(base, params={**params, "limit": 1})).json()
    assert first["items"][0]["policyId"] == "another"
    second = (await client.get(base, params={**params, "limit": 1, "after": first["nextCursor"]})).json()
    assert second["items"][0]["policyId"] == "monthly-budget" and second["nextCursor"] is None
    preview = await client.post(f"{base}/monthly-budget/preview", json={**params,
        "definition": {**definition, "name": "只修改业务名称"}}, headers=headers)
    assert preview.status_code == 200 and preview.json()["calculationChanged"] is False


async def test_retirement_http_is_protected_and_preserves_published_definition(policy_client):
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.metrics_api import create_metrics_router
    from smart_reporting.management.settings import ManagementSettings
    client, headers, service, token, scope, _, definition = policy_client
    params = {"scopeDatabase": "warehouse", "companyId": "a"}
    await service.save_draft(token, scope, definition, expected_version=0)
    await service.publish(token, scope, "monthly-budget", expected_version=1)
    path = "/management/api/v1/statistical-policies/monthly-budget/versions/1/retire"
    payload = {**params, "reason": "规则需修正"}
    assert (await client.post(path, json=payload)).status_code == 403
    assert (await client.post(path, json={**payload, "reason": " "}, headers=headers)).status_code == 422
    assert (await client.post(path, json={**payload, "companyId": "b"}, headers=headers)).status_code == 404
    assert (await client.post(path, json=payload, headers=headers)).status_code == 200
    current = await client.get("/management/api/v1/statistical-policies/monthly-budget", params=params)
    assert current.json()["published"]["revision"] == 1
    app = FastAPI()
    app.include_router(create_metrics_router(MetricService(service.scopes), ManagementSettings(public_origin="https://reports.example")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://reports.example") as metric_client:
        metric_client.cookies.set(SESSION_COOKIE, token, path="/management")
        metric_path = "/management/api/v1/metrics/budget/versions/1/retire"
        assert (await metric_client.post(metric_path, json=payload)).status_code == 403
        assert (await metric_client.post(metric_path, json={**payload, "replacement": {"metricId": "foreign", "revision": 1}}, headers=headers)).status_code == 404
        assert (await metric_client.post(metric_path, json=payload, headers=headers)).status_code == 200


async def test_policy_impact_http_uses_registered_scope_and_exact_revision(policy_client):
    from smart_reporting.reporting.semantics.models import PolicyVersionRef
    client, _, service, token, scope, _, definition = policy_client
    await service.save_draft(token, scope, definition, expected_version=0)
    await service.publish(token, scope, "monthly-budget", expected_version=1)
    await service.set_default(token, scope, "budget_execution", policy_version=PolicyVersionRef(policy_id="monthly-budget", revision=1), expected_version=0)
    path = "/management/api/v1/statistical-policies/monthly-budget/impact"
    params = {"scopeDatabase": "warehouse", "companyId": "a", "revision": 1}
    response = await client.get(path, params=params)
    assert response.status_code == 200
    assert response.json()["items"] == [{"kind": "default", "referenceId": "budget_execution", "policyRevision": 1, "basisId": None}]
    assert (await client.get(path, params={**params, "companyId": "b"})).status_code == 404
    assert (await client.get(path, params={**params, "revision": 2})).status_code == 404
    client.cookies.clear()
    assert (await client.get(path, params=params)).status_code == 401


async def test_policy_detail_reads_exact_retired_revision_without_changing_latest(policy_client):
    client, headers, service, token, scope, _, definition = policy_client
    await service.save_draft(token, scope, definition, expected_version=0)
    await service.publish(token, scope, "monthly-budget", expected_version=1)
    await service.save_draft(token, scope, {**definition, "name": "第二版"}, expected_version=1)
    await service.publish(token, scope, "monthly-budget", expected_version=2)
    path = "/management/api/v1/statistical-policies/monthly-budget"
    params = {"scopeDatabase": "warehouse", "companyId": "a"}
    await service.retire(token, scope, "monthly-budget", 1, reason="使用第二版", replacement={"policyId": "monthly-budget", "revision": 2})
    historical = (await client.get(path, params={**params, "revision": 1})).json()
    assert historical["published"]["revision"] == 1
    assert historical["retirement"]["replacement"] == {"policyId": "monthly-budget", "revision": 2}
    latest = (await client.get(path, params=params)).json()
    assert latest["published"]["revision"] == 2 and latest["retirement"] is None
    assert (await client.get(path, params={**params, "revision": 3})).status_code == 404
