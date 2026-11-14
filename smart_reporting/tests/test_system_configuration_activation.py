"""真实数据库发布值进入新启动，运行中的对象与环境保持不变。"""

import asyncio
import os
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text, update

from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
from smart_reporting.management.repository import configuration_versions
from smart_reporting.management.settings import ManagementSettings
from smart_reporting.management.system_configuration import SystemConfigurationService
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def context(auth_context):
    auth, repository, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    token = (await auth.login("admin", OLD_PASSWORD, "127.0.0.1")).raw_token
    startup = replace(AgentSettings.from_environment({"AGENT_MODEL_TIMEOUT_SECONDS": "321"}, load_env_file=False),
        database_url=os.environ["REPORTING_MANAGEMENT_TEST_DB_URL"])
    return SystemConfigurationService(auth, startup), token, repository


async def loaded(service):
    from smart_reporting.runtime.system_configuration import load_system_configuration

    return await asyncio.to_thread(load_system_configuration, service.startup)


async def test_published_values_enter_next_startup_without_mutating_environment_or_running_settings(context, monkeypatch):
    service, token, _ = context
    detail = await service.detail(token)
    document = detail["draft"]["document"]
    document["values"]["AGENT_MODEL_TIMEOUT_SECONDS"] = 456
    await service.save_draft(token, document, 1)
    published = await service.publish(token, 2)
    monkeypatch.setenv("AGENT_MODEL_TIMEOUT_SECONDS", "987")
    result = await loaded(service)
    assert result.settings.model_timeout_seconds == 456
    assert result.state.revision == published["revision"]
    assert result.state.content_hash == published["contentHash"]
    assert result.state.issue is None
    assert service.startup.model_timeout_seconds == 321
    assert os.environ["AGENT_MODEL_TIMEOUT_SECONDS"] == "987"
    assert result.settings.database_url == service.startup.database_url


async def test_unpublished_draft_does_not_change_startup(context):
    service, token, _ = context
    detail = await service.detail(token)
    document = detail["draft"]["document"]
    document["values"]["AGENT_MODEL_TIMEOUT_SECONDS"] = 456
    await service.save_draft(token, document, 1)
    result = await loaded(service)
    assert result.settings.model_timeout_seconds == 321
    assert result.state.revision is None
    assert result.state.issue is None


async def test_corrupt_published_values_are_reported_and_never_activated(context):
    service, token, repository = context
    await service.detail(token)
    await service.publish(token, 1)
    async with repository.engine.begin() as connection:
        await connection.execute(text("ALTER TABLE reporting_management.configuration_versions DISABLE TRIGGER USER"))
        await connection.execute(update(configuration_versions).where(configuration_versions.c.kind == "system").values(content_hash="0" * 64))
        await connection.execute(text("ALTER TABLE reporting_management.configuration_versions ENABLE TRIGGER USER"))
    result = await loaded(service)
    assert result.settings is service.startup
    assert result.state.revision is None
    assert result.state.issue["code"] == "management_configuration_corrupt"


async def test_unmigrated_storage_is_explicit_and_does_not_prevent_bootstrap(context):
    service, _, repository = context
    async with repository.engine.begin() as connection:
        await connection.execute(text("DROP TABLE reporting_management.configuration_versions"))
    result = await loaded(service)
    assert result.settings is service.startup
    assert result.state.issue["code"] == "management_configuration_schema_missing"


async def test_system_apply_reports_restart_required_until_loader_has_consumed_the_published_revision(context):
    service, token, _ = context
    boot = await loaded(service)
    app = FastAPI()
    app.include_router(create_management_router(service.auth, ManagementSettings(public_origin="https://reports.example"),
        startup_settings=boot.settings, system_configuration_state=boot.state))
    headers = {"origin": "https://reports.example", "x-csrf-token": csrf_token(token)}
    path = "/management/api/v1/configuration/system"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://reports.example") as client:
        client.cookies.set(SESSION_COOKIE, token)
        detail = (await client.get(path)).json()
        assert detail["application"]["canApply"] is True
        catalog = (await client.get(path + "/catalog")).json()["items"]
        timeout = next(item for item in catalog if item["key"] == "AGENT_MODEL_TIMEOUT_SECONDS")
        assert timeout["source"] == "deployment"
        assert timeout["sourceKey"] == "AGENT_MODEL_TIMEOUT_SECONDS"
        document = detail["draft"]["document"]
        document["values"]["AGENT_MODEL_TIMEOUT_SECONDS"] = 456
        assert (await client.put(path + "/draft", json={"expectedVersion": 1, "document": document}, headers=headers)).status_code == 200
        assert (await client.post(path + "/apply", json={"expectedVersion": 2})).status_code == 403
        applied = await client.post(path + "/apply", json={"expectedVersion": 2}, headers=headers)
        assert applied.status_code == 200, applied.text
        assert applied.json()["requiresRestart"] is True
        state = (await client.get(path)).json()["application"]
        assert state["status"] == "restart_required"
        assert state["effectiveRevision"] is None
        assert state["publishedRevision"] == 1
    restarted = await loaded(service)
    assert restarted.settings.deployment_keys == service.startup.deployment_keys
    restarted_app = FastAPI()
    restarted_app.include_router(create_management_router(service.auth, ManagementSettings(public_origin="https://reports.example"),
        startup_settings=restarted.settings, system_configuration_state=restarted.state))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(restarted_app), base_url="https://reports.example") as client:
        client.cookies.set(SESSION_COOKIE, token)
        detail = (await client.get(path)).json()
        assert detail["application"]["status"] == "active"
        assert detail["application"]["requiresRestart"] is False
        assert detail["application"]["effectiveRevision"] == 1
        assert detail["initial"]["values"]["AGENT_MODEL_TIMEOUT_SECONDS"] == 321
        assert "deployment_keys" not in str(detail)
        catalog = (await client.get(path + "/catalog")).json()["items"]
        timeout = next(item for item in catalog if item["key"] == "AGENT_MODEL_TIMEOUT_SECONDS")
        assert timeout["value"] == 456
        assert timeout["source"] == "management"
        assert timeout["sourceKey"] == "AGENT_MODEL_TIMEOUT_SECONDS"
