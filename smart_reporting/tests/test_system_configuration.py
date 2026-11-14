"""系统普通配置复用版本契约，秘密与启动基础配置不能混入文档。"""

from dataclasses import replace

import pytest

from smart_reporting.management.models import ManagementError
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def context(auth_context):
    from smart_reporting.management.system_configuration import SystemConfigurationService

    auth, repository, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    token = (await auth.login("admin", OLD_PASSWORD, "127.0.0.1")).raw_token
    startup = replace(AgentSettings.from_environment({}, load_env_file=False), model_timeout_seconds=321,
        openai_api_key="must-stay-out-of-config-documents")
    return SystemConfigurationService(auth, startup), token, repository


async def test_system_initial_values_are_typed_and_contain_no_credentials(context):
    service, token, _ = context
    detail = await service.detail(token)
    assert detail["draft"]["document"]["values"]["AGENT_MODEL_TIMEOUT_SECONDS"] == 321
    assert "OPENAI_API_KEY" not in detail["initial"]["values"]
    assert "must-stay-out-of-config-documents" not in str(detail)
    assert "AGENT_DB_URL" not in detail["initial"]["values"]


async def test_system_versions_are_separate_from_preferences_and_restore_without_mutating_startup(context):
    from smart_reporting.management.format_preferences import FormatPreferenceService
    from smart_reporting.preferences.models import FormatPreferences

    service, token, _ = context
    preferences = FormatPreferenceService(service.auth, FormatPreferences.model_validate({"common": {"signer": "测试署名"}}))
    detail = await service.detail(token)
    payload = detail["draft"]["document"]
    payload["values"]["AGENT_MODEL_TIMEOUT_SECONDS"] = 456
    saved = await service.save_draft(token, payload, 1)
    assert saved["version"] == 2
    assert (await service.publish(token, 2))["revision"] == 1
    assert (await preferences.detail(token))["effective"] is None
    assert (await preferences.detail(token))["draft"]["version"] == 1
    assert service.resolve_document((await service.version(token, 1))["document"]).model_timeout_seconds == 456
    assert service.startup.model_timeout_seconds == 321
    await service.reset_draft(token, 2)
    await service.publish(token, 3)
    assert (await service.restore_draft(token, 1, 3))["version"] == 4
    assert (await service.detail(token))["draft"]["document"]["values"]["AGENT_MODEL_TIMEOUT_SECONDS"] == 456


@pytest.mark.parametrize("patch", [{"OPENAI_API_KEY": "raw-secret"}, {"AGENT_DB_URL": "new-database"},
    {"AGENT_REPORT_ORGANIZATION_NAME": "wrong-owner"}, {"AGENT_REPORT_CONTEXT_TOKEN_BUDGET": 1}])
async def test_unsafe_or_cross_field_invalid_system_values_are_not_saved(context, patch):
    service, token, _ = context
    document = (await service.detail(token))["draft"]["document"]
    document["values"].update(patch)
    with pytest.raises(ManagementError) as error:
        await service.save_draft(token, document, 1)
    assert error.value.code == "management_system_configuration_invalid"
    assert (await service.detail(token))["draft"]["version"] == 1


async def test_unconfigured_unused_model_url_does_not_prevent_management_startup(context):
    from smart_reporting.management.system_configuration import SystemConfigurationService

    service, token, _ = context
    current = replace(service.startup, openai_base_url="")
    initialized = SystemConfigurationService(service.auth, current)
    detail = await initialized.detail(token)
    assert "OPENAI_BASE_URL" not in detail["initial"]["values"]
