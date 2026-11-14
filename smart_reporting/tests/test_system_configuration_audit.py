"""系统配置清单的真实启动来源及服务地址边界回归；不连接数据库。"""

from dataclasses import replace

import pytest

from smart_reporting.management.configuration_catalog import (
    configuration_inventory,
    validate_system_values,
)
from smart_reporting.runtime.settings import AgentSettings


def test_inventory_preserves_actual_startup_input_sources_without_ambient_reread(monkeypatch):
    startup = AgentSettings.from_environment({
        "AGENT_MODEL_FAST": "startup-fast",
        "UNRELATED_SECRET": "private-input-never-registered",
    }, load_env_file=False)
    monkeypatch.setenv("AGENT_MODEL_TIMEOUT_SECONDS", "321")
    monkeypatch.delenv("AGENT_MODEL_FAST", raising=False)

    items = {item["key"]: item for item in configuration_inventory(startup)}

    assert items["AGENT_MODEL_FAST"]["source"] == "deployment"
    assert items["AGENT_MODEL_FAST"]["sourceKey"] == "AGENT_MODEL_FAST"
    assert items["AGENT_MODEL_TIMEOUT_SECONDS"]["source"] == "default"
    assert items["AGENT_MODEL_TIMEOUT_SECONDS"]["sourceKey"] is None
    assert "UNRELATED_SECRET" not in str(items)
    assert "private-input-never-registered" not in str(items)


def test_dotenv_sources_precede_injected_defaults_and_replacement_preserves_source(tmp_path):
    env_file = tmp_path / "startup.env"
    env_file.write_text("AGENT_MODEL_FAST=file-fast\nAGENT_MODEL_STANDARD=file-standard\n"
        "AGENT_FAKE_NEW_SETTING=never-declared\nUNRELATED_SECRET=private-file-secret\n")
    startup = AgentSettings.from_environment({
        "AGENT_ENV_FILE": str(env_file), "AGENT_MODEL_FAST": "environment-fast",
    })
    reconfigured = replace(startup, model_timeout_seconds=321)
    items = {item["key"]: item for item in configuration_inventory(reconfigured)}

    assert items["AGENT_MODEL_FAST"]["value"] == "environment-fast"
    assert items["AGENT_MODEL_STANDARD"]["value"] == "file-standard"
    assert items["AGENT_MODEL_STANDARD"]["source"] == "deployment"
    assert items["REPORTING_HOST_WORKSPACE_ROOT"]["source"] == "default"
    assert reconfigured.deployment_keys == startup.deployment_keys
    assert "AGENT_FAKE_NEW_SETTING" not in startup.deployment_keys
    assert "UNRELATED_SECRET" not in startup.deployment_keys
    assert "deployment_keys=" not in repr(startup)


def test_inventory_preserves_actual_alias_and_reports_untracked_settings_honestly():
    startup = AgentSettings.from_environment({"AGENT_NATIVE_DOCX_ENABLED": "true"}, load_env_file=False)
    items = {item["key"]: item for item in configuration_inventory(startup)}
    assert items["AGENT_REPORT_EDITOR_DOCX_ENABLED"]["sourceKey"] == "AGENT_NATIVE_DOCX_ENABLED"
    items = {item["key"]: item for item in configuration_inventory(replace(startup, deployment_keys=None))}
    assert items["AGENT_REPORT_EDITOR_DOCX_ENABLED"]["source"] == "startup"


@pytest.mark.parametrize("key,alias", [
    ("AGENT_REPORT_EDITOR_DOCX_ENABLED", "AGENT_NATIVE_DOCX_ENABLED"),
    ("AGENT_REPORT_EDITOR_PDF_ENABLED", "AGENT_NATIVE_PDF_ENABLED"),
    ("AGENT_REPORT_EDITOR_AI_ENABLED", "AGENT_NATIVE_AI_ENABLED"),
    ("AGENT_REPORT_EDITOR_PDF_TEXT_ENABLED", "AGENT_NATIVE_PDF_TEXT_ENABLED"),
    ("AGENT_REPORT_EDITOR_UPLOAD_ENABLED", "AGENT_NATIVE_UPLOAD_ENABLED"),
])
def test_empty_boolean_primary_keeps_its_actual_priority_over_nonempty_alias(key, alias):
    startup = AgentSettings.from_environment({key: "", alias: "true"}, load_env_file=False)
    item = next(item for item in configuration_inventory(startup) if item["key"] == key)
    assert item["value"] is False
    assert item["source"] == "deployment"
    assert item["sourceKey"] == key


def test_empty_boolean_without_alias_is_an_explicit_false_deployment_value():
    key = "AGENT_REPORT_EDITOR_CHART_AI_ENABLED"
    startup = AgentSettings.from_environment({key: ""}, load_env_file=False)
    item = next(item for item in configuration_inventory(startup) if item["key"] == key)
    assert item["value"] is False
    assert item["source"] == "deployment"
    assert item["sourceKey"] == key


def test_empty_database_primary_still_uses_the_existing_nonempty_alias_fallback():
    startup = AgentSettings.from_environment({
        "AGENT_DB_URL": "", "DATABASE_URL": "postgresql://test@localhost/source-only",
    }, load_env_file=False)
    item = next(item for item in configuration_inventory(startup) if item["key"] == "AGENT_DB_URL")
    assert startup.database_url == "postgresql://test@localhost/source-only"
    assert item["sourceKey"] == "DATABASE_URL"


@pytest.mark.parametrize("key", ["OPENAI_BASE_URL", "AGENT_REPORT_METADATA_URL"])
@pytest.mark.parametrize("url", [
    "https://:443/v1",
    "https://example.com:invalid/v1",
    "https://example.com:65536/v1",
    "https://exam\nple.com/v1",
    "https://example.com/\x00v1",
    "https://@example.com/v1",
])
def test_managed_service_addresses_reject_unusable_or_obscured_authorities(key, url):
    with pytest.raises(ValueError):
        validate_system_values({key: url})


@pytest.mark.parametrize("key", ["OPENAI_BASE_URL", "AGENT_REPORT_METADATA_URL"])
@pytest.mark.parametrize("url", ["https://exa mple.com/v1", "https://example.com :443/v1"])
def test_managed_service_address_rejects_hostname_whitespace(key, url):
    with pytest.raises(ValueError):
        validate_system_values({key: url})


@pytest.mark.parametrize("url", ["https://example.com:443/v1", "http://[::1]:8080/v1"])
def test_managed_service_addresses_keep_supported_explicit_ports(url):
    assert validate_system_values({"OPENAI_BASE_URL": url}) == {"OPENAI_BASE_URL": url}
