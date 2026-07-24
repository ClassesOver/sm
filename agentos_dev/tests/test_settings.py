import pytest

from agentos_dev.settings import DEFAULT_AGENT_DB_URL, DEFAULT_WORKSPACE_SNAPSHOT, AgentSettings


def settings(values=None, **overrides):
    environ = {} if values is None else values
    environ.update(overrides)
    return AgentSettings.from_environment(environ, load_env_file=False)


def test_settings_defaults():
    current = settings()
    assert current.env_file == ".env"
    assert current.port == 7777
    assert current.workers == 4
    assert current.database_url == DEFAULT_AGENT_DB_URL
    assert current.workspace_snapshot == DEFAULT_WORKSPACE_SNAPSHOT
    assert current.cors_allowed_origins == (
        "http://127.0.0.1:18069",
        "http://localhost:18069",
    )
    assert current.enable_tool_result_compression is True
    assert current.enable_session_summaries is True
    assert current.enable_thinking is True
    assert current.context_token_budget == 262144
    assert current.history_token_budget == 196608
    assert current.output_token_reserve == 32768
    assert current.report_data_sources_file is None


def test_agent_feature_flags_can_be_disabled():
    current = settings(
        AGENT_ENABLE_TOOL_RESULT_COMPRESSION="false",
        AGENT_ENABLE_SESSION_SUMMARIES="0",
        AGENT_ENABLE_THINKING="off",
        AGENT_HISTORY_TOKEN_BUDGET="32768",
        AGENT_CONTEXT_TOKEN_BUDGET="131072",
        AGENT_OUTPUT_TOKEN_RESERVE="16384",
    )

    assert current.enable_tool_result_compression is False
    assert current.enable_session_summaries is False
    assert current.enable_thinking is False
    assert current.history_token_budget == 32768
    assert current.context_token_budget == 131072
    assert current.output_token_reserve == 16384


def test_workspace_snapshot_comes_from_environment():
    assert settings(DAYTONA_DEFAULT_SNAPSHOT=" custom-snapshot ").workspace_snapshot == (
        "custom-snapshot"
    )
    assert settings(DAYTONA_DEFAULT_SNAPSHOT=" ").workspace_snapshot == DEFAULT_WORKSPACE_SNAPSHOT


def test_report_data_sources_file_is_trimmed():
    assert settings(
        AGENT_REPORT_DATA_SOURCES_FILE=" /run/report-sources.json "
    ).report_data_sources_file == ("/run/report-sources.json")


def test_context_budget_rejects_invalid_reserve():
    with pytest.raises(ValueError, match="AGENT_OUTPUT_TOKEN_RESERVE"):
        settings(
            AGENT_CONTEXT_TOKEN_BUDGET="1024",
            AGENT_HISTORY_TOKEN_BUDGET="512",
            AGENT_OUTPUT_TOKEN_RESERVE="1024",
        )


def test_environment_precedes_file_and_file_populates_missing_values(tmp_path):
    env_file = tmp_path / "agent.env"
    env_file.write_text("MODEL=file-model\nOPENAI_API_KEY=file-key\n", encoding="utf-8")
    environ = {"AGENT_ENV_FILE": str(env_file), "MODEL": "process-model"}

    current = AgentSettings.from_environment(environ)

    assert current.model_id == "process-model"
    assert current.openai_api_key == "file-key"
    assert environ["OPENAI_API_KEY"] == "file-key"


@pytest.mark.parametrize(
    "name,value",
    [
        ("AGENT_OS_PORT", "x"),
        ("AGENT_OS_PORT", "0"),
        ("AGENT_OS_PORT", "65536"),
        ("AGENT_OS_WORKERS", "-1"),
    ],
)
def test_invalid_port_and_workers(name, value):
    with pytest.raises(ValueError, match=name):
        settings(**{name: value})


def test_cors_discards_empty_entries():
    assert settings(
        AGENTOS_CORS_ORIGINS=" https://one.example, ,https://two.example "
    ).cors_allowed_origins == (
        "https://one.example",
        "https://two.example",
    )


def test_database_precedence_and_url_escaping():
    assert (
        settings(
            DATABASE_URL="postgresql://database/db", AGENT_DB_URL="postgresql://agent/db"
        ).database_url
        == "postgresql://agent/db"
    )
    current = settings(
        AGENT_POSTGRES_USER="agent user",
        AGENT_POSTGRES_PASSWORD="p@ss:/word",
        AGENT_POSTGRES_DB="agent data",
    )
    assert current.database_url == (
        "postgresql+psycopg://agent%20user:p%40ss%3A%2Fword@127.0.0.1:55432/agent%20data"
    )
