"""真实管理认证下的配置草稿 API；执行器接通前不提供应用入口。"""

import httpx
import pytest
from fastapi import FastAPI

from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
from smart_reporting.management.settings import ManagementSettings
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(auth_context):
    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    token = (await auth.login("admin", OLD_PASSWORD, "127.0.0.1")).raw_token
    app = FastAPI()
    app.include_router(create_management_router(auth, ManagementSettings(public_origin="https://reports.example"),
        startup_settings=AgentSettings.from_environment({}, load_env_file=False)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://reports.example") as client:
        yield client, token


async def test_api_requires_authentication_and_csrf_before_mutation(client):
    c, token = client
    path = "/management/api/v1/configuration/preferences"
    assert (await c.get(path)).status_code == 401
    c.cookies.set(SESSION_COOKIE, token)
    response = await c.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = {"expectedVersion": 1, "document": response.json()["draft"]["document"]}
    assert (await c.put(path + "/draft", json=body)).status_code == 403
    assert (await c.put(path + "/draft", json=body, headers={
        "origin": "https://other.example", "x-csrf-token": csrf_token(token)})).status_code == 403
    assert (await c.get(path)).json()["draft"]["version"] == 1


async def test_api_saves_reads_back_and_rejects_stale_versions_and_unapproved_apply(client):
    c, token = client
    c.cookies.set(SESSION_COOKIE, token)
    path = "/management/api/v1/configuration/preferences"
    response = await c.get(path)
    assert response.json()["application"]["canApply"] is False
    document = response.json()["draft"]["document"]
    document["common"]["signer"] = "管理员维护署名"
    headers = {"origin": "https://reports.example", "x-csrf-token": csrf_token(token)}
    body = {"expectedVersion": 1, "document": document}
    saved = await c.put(path + "/draft", json=body, headers=headers)
    assert saved.status_code == 200 and saved.json()["version"] == 2
    assert (await c.get(path)).json()["draft"]["document"]["common"]["signer"] == "管理员维护署名"
    assert (await c.put(path + "/draft", json=body, headers=headers)).status_code == 409
    assert (await c.post(path + "/apply", json={"expectedVersion": 2}, headers=headers)).status_code == 422
    assert (await c.post(path + "/draft/reset", json={"expectedVersion": 2}, headers=headers)).json()["version"] == 3


async def test_api_rejects_plain_credentials_and_unknown_fields_without_echo(client):
    c, token = client
    c.cookies.set(SESSION_COOKIE, token)
    path = "/management/api/v1/configuration/system"
    detail = (await c.get(path)).json()
    headers = {"origin": "https://reports.example", "x-csrf-token": csrf_token(token)}
    document = detail["draft"]["document"]
    document["values"]["OPENAI_API_KEY"] = "must-not-echo-secret"
    rejected = await c.put(path + "/draft", json={"expectedVersion": 1, "document": document}, headers=headers)
    assert rejected.status_code == 422
    assert "must-not-echo-secret" not in rejected.text
    assert (await c.put(path + "/draft", json={"expectedVersion": 1, "document": {}, "companyId": "foreign"}, headers=headers)).status_code == 422
    assert (await c.get(path + "/catalog")).status_code == 200
    assert (await c.get(path + "/versions")).json()["items"] == []
    assert (await c.get(path + "/versions/99")).status_code == 404
    assert (await c.get(path + "/versions?limit=101")).status_code == 422
    assert (await c.get("/management/api/v1/configuration/unknown")).status_code == 422


async def test_api_reset_and_restore_require_positive_integer_versions(client):
    c, token = client
    c.cookies.set(SESSION_COOKIE, token)
    path = "/management/api/v1/configuration/preferences"
    headers = {"origin": "https://reports.example", "x-csrf-token": csrf_token(token)}
    for version in (True, "1", 0, -1):
        assert (await c.post(path + "/draft/reset", json={"expectedVersion": version}, headers=headers)).status_code == 422
    missing = await c.post(path + "/draft/restore", json={"expectedVersion": 1, "revision": 99}, headers=headers)
    assert missing.status_code == 404


async def test_preview_requires_csrf_and_current_saved_version_without_mutating_draft(client, monkeypatch):
    from smart_reporting.management import configuration_preview
    calls = []
    def render(document, format, *, generated_date):
        calls.append((document, format, generated_date))
        return {'format': format, 'generatedDate': generated_date, 'artifact': {}, 'pdf': None, 'issues': []}
    monkeypatch.setattr(configuration_preview, 'render_preference_preview', render)
    c, token = client
    c.cookies.set(SESSION_COOKIE, token)
    path = '/management/api/v1/configuration/preferences'
    before = (await c.get(path)).json()
    headers = {'origin': 'https://reports.example', 'x-csrf-token': csrf_token(token)}
    assert (await c.post(path + '/preview/word', json={'expectedVersion': 1})).status_code == 403
    assert (await c.post(path + '/preview/word', json={'expectedVersion': 2}, headers=headers)).status_code == 409
    assert not calls
    response = await c.post(path + '/preview/word', json={'expectedVersion': 1}, headers=headers)
    assert response.status_code == 200
    assert response.json()['draftVersion'] == 1
    assert response.json()['contentHash'] == before['draft']['contentHash']
    assert calls[0][0] == before['draft']['document'] and calls[0][1] == 'word'
    assert (await c.get(path)).json()['draft'] == before['draft']
    assert (await c.post(path + '/preview/unknown', json={'expectedVersion': 1}, headers=headers)).status_code == 422


async def test_preview_engine_failure_returns_specific_error_and_keeps_draft(client, monkeypatch):
    from smart_reporting.management import configuration_preview

    def fail(*args, **kwargs):
        raise RuntimeError('internal-engine-private-details')

    monkeypatch.setattr(configuration_preview, 'render_preference_preview', fail)
    c, token = client
    c.cookies.set(SESSION_COOKIE, token)
    path = '/management/api/v1/configuration/preferences'
    before = (await c.get(path)).json()['draft']
    headers = {'origin': 'https://reports.example', 'x-csrf-token': csrf_token(token)}
    response = await c.post(path + '/preview/pdf', json={'expectedVersion': 1}, headers=headers)
    assert response.status_code == 503
    assert response.json()['code'] == 'management_preview_failed'
    assert 'internal-engine-private-details' not in response.text
    assert (await c.get(path)).json()['draft'] == before


async def test_system_credential_replacement_requires_csrf_cas_and_never_echoes_secret(client, monkeypatch):
    from smart_reporting.management.data_sources.secrets import CredentialVault

    monkeypatch.setenv('AGENT_MANAGEMENT_CREDENTIAL_KEYS', 'test:' + CredentialVault.generate_key())
    c, token = client
    c.cookies.set(SESSION_COOKIE, token)
    path = '/management/api/v1/configuration/system'
    await c.get(path)
    payload = {'expectedVersion': 1, 'secret': 'api-private-replacement'}
    route = path + '/credentials/OPENAI_API_KEY'
    assert (await c.put(route, json=payload)).status_code == 403
    headers = {'origin': 'https://reports.example', 'x-csrf-token': csrf_token(token)}
    saved = await c.put(route, json=payload, headers=headers)
    assert saved.status_code == 200 and saved.json()['version'] == 2
    assert 'api-private-replacement' not in saved.text
    detail = await c.get(path)
    assert 'api-private-replacement' not in detail.text
    assert 'OPENAI_API_KEY' in detail.json()['draft']['document']['credentials']
    assert (await c.put(route, json=payload, headers=headers)).status_code == 409
    invalid = await c.put(route, json={'expectedVersion': 2, 'secret': 'bad\nsecret'}, headers=headers)
    assert invalid.status_code == 422 and 'bad' not in invalid.text
    assert (await c.put(path + '/credentials/AGENT_DB_URL', json=payload, headers=headers)).status_code == 422
    assert (await c.put(route, json={**payload, 'organization': 'x'}, headers=headers)).status_code == 422
