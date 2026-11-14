"""配置清单只暴露已声明项目项，读取实际启动值并隐藏秘密。"""

from dataclasses import replace

import pytest

from smart_reporting.runtime.settings import AgentSettings


def settings():
    return AgentSettings.from_environment({}, load_env_file=False)


def inventory(current=None, keys=None):
    from smart_reporting.management.configuration_catalog import configuration_inventory

    return {item["key"]: item for item in configuration_inventory(current or settings(), deployment_keys=keys)}


def test_inventory_does_not_dump_ambient_environment(monkeypatch):
    monkeypatch.setenv("UNRELATED_SECRET", "do-not-show-this")
    monkeypatch.setenv("AGENT_FAKE_NEW_SETTING", "not-registered")
    items = inventory(keys=frozenset({"UNRELATED_SECRET", "AGENT_FAKE_NEW_SETTING"}))
    assert "UNRELATED_SECRET" not in items
    assert "AGENT_FAKE_NEW_SETTING" not in items
    assert "do-not-show-this" not in str(items)


def test_actual_startup_values_are_used_instead_of_current_environment(monkeypatch):
    current = replace(settings(), model_timeout_seconds=321)
    monkeypatch.setenv("AGENT_MODEL_TIMEOUT_SECONDS", "654")
    item = inventory(current, frozenset({"AGENT_MODEL_TIMEOUT_SECONDS"}))["AGENT_MODEL_TIMEOUT_SECONDS"]
    assert item["value"] == 321
    assert item["source"] == "deployment"
    assert item["activation"] == "restart"
    assert item["unit"] == "秒"


def test_credentials_and_bootstrap_database_are_never_returned_as_plaintext():
    current = replace(settings(), openai_api_key="model-test-secret", workspace_hmac_secret="workspace-test-secret",
        report_metadata_token="metadata-test-secret", database_url="postgresql://db:database-secret@localhost/db")
    items = inventory(current)
    for key in ("OPENAI_API_KEY", "AGENT_WORKSPACE_HMAC_SECRET", "AGENT_REPORT_METADATA_TOKEN", "AGENT_DB_URL"):
        assert items[key]["value"] is None
        assert items[key]["configured"] is True
        assert items[key]["sensitive"] is True
    assert "test-secret" not in str(items)
    assert "database-secret" not in str(items)
    assert items["AGENT_DB_URL"]["activation"] == "deployment"


@pytest.mark.parametrize("url", ["https://user:url-secret@example.com/v1", "https://example.com/v1?token=url-secret"])
def test_model_base_url_with_embedded_secret_is_redacted(url):
    item = inventory(replace(settings(), openai_base_url=url))["OPENAI_BASE_URL"]
    assert item["value"] is None
    assert item["redacted"] is True
    assert "url-secret" not in str(item)


def test_branding_variables_have_one_preferences_owner_and_no_organization_entity():
    items = inventory()
    for key in ("AGENT_REPORT_ORGANIZATION_NAME", "AGENT_REPORT_GENERATED_BY_LABEL", "AGENT_REPORT_WATERMARK_TEXT",
        "AGENT_REPORT_HEADER_LEFT", "AGENT_REPORT_HEADER_RIGHT", "AGENT_REPORT_FOOTER_LEFT", "AGENT_REPORT_FOOTER_RIGHT"):
        assert items[key]["owner"] == "preferences"
        assert items[key]["activation"] == "preferences"
    assert items["AGENT_REPORT_ORGANIZATION_NAME"]["label"] == "落款署名"


def test_legacy_aliases_report_source_and_do_not_create_competing_settings():
    current = replace(settings(), native_docx_enabled=True)
    items = inventory(current, frozenset({"AGENT_NATIVE_DOCX_ENABLED"}))
    assert "AGENT_NATIVE_DOCX_ENABLED" not in items
    assert items["AGENT_REPORT_EDITOR_DOCX_ENABLED"]["sourceKey"] == "AGENT_NATIVE_DOCX_ENABLED"
    items = inventory(current, frozenset({"AGENT_NATIVE_DOCX_ENABLED", "AGENT_REPORT_EDITOR_DOCX_ENABLED"}))
    assert items["AGENT_REPORT_EDITOR_DOCX_ENABLED"]["sourceKey"] == "AGENT_REPORT_EDITOR_DOCX_ENABLED"


def test_catalog_has_no_duplicate_keys_and_validates_managed_scalar_values():
    from smart_reporting.management.configuration_catalog import (
        CONFIGURATION_CATALOG,
        validate_system_values,
    )

    keys = [item.key for item in CONFIGURATION_CATALOG]
    assert len(keys) == len(set(keys))
    assert validate_system_values({"AGENT_MODEL_TIMEOUT_SECONDS": 300, "AGENT_DEBUG": False}) == {
        "AGENT_MODEL_TIMEOUT_SECONDS": 300, "AGENT_DEBUG": False}
    for values in ({"AGENT_MODEL_TIMEOUT_SECONDS": True}, {"AGENT_DEBUG": "false"},
        {"AGENT_MODEL_TIMEOUT_SECONDS": 3601}, {"AGENT_REPORT_ANALYSIS_CONCURRENCY": 6},
        {"AGENT_REPORT_CODING_TEMPERATURE": float("nan")},
        {"AGENT_REPORT_CODING_REASONING_EFFORT": "medium"},
        {"AGENT_REPORT_CODING_EXECUTION_MODE": "unknown"},
        {"OPENAI_API_KEY": "plain-secret"}, {"AGENT_DB_URL": "should-not-change"},
        {"UNKNOWN": True}, {"AGENT_REPORT_ORGANIZATION_NAME": "second-owner"}):
        with pytest.raises(ValueError):
            validate_system_values(values)


def test_budget_reserve_is_checked_against_effective_context_not_only_patch():
    from smart_reporting.management.configuration_catalog import resolve_system_settings

    current = replace(settings(), report_context_token_budget=1000, report_output_token_reserve=500)
    with pytest.raises(ValueError):
        resolve_system_settings(current, {"AGENT_REPORT_CONTEXT_TOKEN_BUDGET": 400})
    resolved = resolve_system_settings(current, {"AGENT_REPORT_CONTEXT_TOKEN_BUDGET": 400,
        "AGENT_REPORT_OUTPUT_TOKEN_RESERVE": 100})
    assert resolved.report_context_token_budget == 400
    assert resolved.report_output_token_reserve == 100
    assert current.report_context_token_budget == 1000


def test_missing_provenance_is_reported_as_startup_value_instead_of_guessed_default():
    item = inventory(replace(settings(), deployment_keys=None))["AGENT_MODEL_TIMEOUT_SECONDS"]
    assert item["source"] == "startup"
    assert item["sourceKey"] is None


def test_platform_connection_secrets_are_redacted_even_inside_settings():
    from dingyi_agno.platform.settings import PlatformSettings

    current = replace(settings(), platform_settings=PlatformSettings(platform_url="https://platform.example",
        service_token="platform-test-secret", database_url="postgresql://db:platform-db-secret@localhost/db"))
    items = inventory(current)
    assert items["DINGYI_PLATFORM_URL"]["value"] == "https://platform.example"
    assert items["DINGYI_PLATFORM_SERVICE_TOKEN"]["value"] is None
    assert items["DINGYI_PLATFORM_DATABASE_URL"]["value"] is None
    assert "platform-test-secret" not in str(items)
    assert "platform-db-secret" not in str(items)
