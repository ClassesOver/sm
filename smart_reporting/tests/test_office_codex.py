"""Office 复杂场景编码任务入口：默认关闭，沙箱与命令环境边界由 Codex 原生配置声明。"""

import pytest
from pydantic import BaseModel

from smart_reporting.office.codex import (
    OFFICE_CODEX_PROVIDER,
    OfficeCodexUnavailable,
    create_office_codex_agent,
)
from smart_reporting.runtime.settings import AgentSettings


class _Result(BaseModel):
    summary: str


def _settings(**extra: str) -> AgentSettings:
    return AgentSettings.from_environment(
        {
            "OPENAI_BASE_URL": "https://models.example.invalid/v1",
            "OPENAI_API_KEY": "test-key",
            "AGENT_MODEL_STANDARD": "standard-model",
            **extra,
        },
        load_env_file=False,
    )


def test_office_codex_is_disabled_by_default(tmp_path):
    with pytest.raises(OfficeCodexUnavailable):
        create_office_codex_agent(_settings(), cwd=tmp_path, output_schema=_Result)


def test_office_codex_requires_existing_workspace(tmp_path):
    settings = _settings(AGENT_OFFICE_CODEX_ENABLED="true")
    with pytest.raises(OfficeCodexUnavailable):
        create_office_codex_agent(settings, cwd=tmp_path / "missing", output_schema=_Result)


def test_office_codex_declares_sandbox_and_command_environment_in_native_config(tmp_path):
    settings = _settings(
        AGENT_OFFICE_CODEX_ENABLED="true",
        AGENT_OFFICE_CODEX_BASE_URL="https://codex.example.invalid/v1",
        AGENT_OFFICE_CODEX_MODEL="codex-model",
    )
    agent = create_office_codex_agent(settings, cwd=tmp_path, output_schema=_Result)

    assert agent.model == "codex-model"
    assert agent.model_provider == OFFICE_CODEX_PROVIDER
    assert agent.cwd == str(tmp_path)
    assert agent.ephemeral is True
    assert agent.approval_policy == "never"
    # 作为启动参数传入会按默认规则重建策略并放开 /tmp，必须只经配置声明。
    assert agent.sandbox_mode is None
    config = agent.config
    assert config["sandbox_mode"] == "workspace-write"
    assert config["sandbox_workspace_write"] == {
        "exclude_tmpdir_env_var": True,
        "exclude_slash_tmp": True,
        "network_access": False,
    }
    assert config["shell_environment_policy"]["inherit"] == "core"
    provider = config["model_providers"][OFFICE_CODEX_PROVIDER]
    assert provider["base_url"] == "https://codex.example.invalid/v1"
    assert provider["wire_api"] == "responses"
    assert agent.env == {"OPENAI_API_KEY": "test-key"}


def test_office_codex_falls_back_to_general_model_settings(tmp_path):
    agent = create_office_codex_agent(
        _settings(AGENT_OFFICE_CODEX_ENABLED="true"), cwd=tmp_path, output_schema=_Result
    )
    assert agent.model == "standard-model"
    assert agent.config["model_providers"][OFFICE_CODEX_PROVIDER]["base_url"] == (
        "https://models.example.invalid/v1"
    )
