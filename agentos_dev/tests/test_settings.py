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
    assert current.workers == 1
    assert current.database_url == DEFAULT_AGENT_DB_URL
    assert current.workspace_snapshot == DEFAULT_WORKSPACE_SNAPSHOT
    assert current.daytona_network_allow_list is None
    assert current.cors_allowed_origins == (
        "http://127.0.0.1:18069",
        "http://localhost:18069",
    )
    assert current.enable_tool_result_compression is True
    assert current.enable_session_summaries is True
    assert current.assistant_enable_thinking is False
    assert current.coding_temperature == 0.1
    assert current.coding_enable_thinking is True
    assert current.coding_reasoning_effort == "medium"
    assert current.coding_thinking_budget == 16384
    assert current.report_coding_enable_thinking is True
    assert current.report_coding_temperature == 0.1
    assert current.report_coding_reasoning_effort == "max"
    assert current.report_coding_thinking_budget == 16384
    assert current.report_enable_thinking is True
    assert current.report_enable_vision is False
    assert current.model_timeout_seconds == 900
    assert current.tracing_enabled is False
    assert current.tracing_phoenix_endpoint is None
    assert current.tracing_phoenix_api_key is None
    assert current.tracing_phoenix_project_name == "agentos"
    assert current.context_token_budget == 262144
    assert current.history_token_budget == 196608
    assert current.output_token_reserve == 32768
    assert current.report_context_token_budget == 1048576
    assert current.report_output_token_reserve == 393216
    assert current.report_data_sources_dir is None
    assert current.report_metadata_url is None
    assert current.report_metadata_token is None
    assert current.agentos_jwt_verification_key is None
    assert current.agentos_jwt_algorithm == "HS256"
    assert current.agentos_jwt_audience is None


def test_agentos_jwt_config_is_loaded():
    current = settings(
        JWT_VERIFICATION_KEY=" secret ",
        JWT_ALGORITHM="RS256",
        JWT_AUDIENCE=" report-agent-os ",
    )

    assert current.agentos_jwt_verification_key == "secret"
    assert current.agentos_jwt_algorithm == "RS256"
    assert current.agentos_jwt_audience == "report-agent-os"


def test_agent_feature_flags_can_be_disabled():
    current = settings(
        AGENT_ENABLE_TOOL_RESULT_COMPRESSION="false",
        AGENT_ENABLE_SESSION_SUMMARIES="0",
        AGENT_ASSISTANT_ENABLE_THINKING="true",
        AGENT_CODING_TEMPERATURE="0.25",
        AGENT_CODING_ENABLE_THINKING="off",
        AGENT_CODING_REASONING_EFFORT="high",
        AGENT_CODING_THINKING_BUDGET="8192",
        AGENT_REPORT_CODING_ENABLE_THINKING="no",
        AGENT_REPORT_CODING_TEMPERATURE="0.35",
        AGENT_REPORT_CODING_REASONING_EFFORT="medium",
        AGENT_REPORT_CODING_THINKING_BUDGET="4096",
        AGENT_REPORT_ENABLE_THINKING="false",
        AGENT_REPORT_ENABLE_VISION="true",
        AGENT_HISTORY_TOKEN_BUDGET="32768",
        AGENT_CONTEXT_TOKEN_BUDGET="131072",
        AGENT_OUTPUT_TOKEN_RESERVE="16384",
        AGENT_REPORT_CONTEXT_TOKEN_BUDGET="524288",
        AGENT_REPORT_OUTPUT_TOKEN_RESERVE="131072",
    )

    assert current.enable_tool_result_compression is False
    assert current.enable_session_summaries is False
    assert current.assistant_enable_thinking is True
    assert current.coding_temperature == 0.25
    assert current.coding_enable_thinking is False
    assert current.coding_reasoning_effort == "high"
    assert current.coding_thinking_budget == 8192
    assert current.report_coding_enable_thinking is False
    assert current.report_coding_temperature == 0.35
    assert current.report_coding_reasoning_effort == "medium"
    assert current.report_coding_thinking_budget == 4096
    assert current.report_enable_thinking is False
    assert current.report_enable_vision is True
    assert current.history_token_budget == 32768
    assert current.context_token_budget == 131072
    assert current.output_token_reserve == 16384
    assert current.report_context_token_budget == 524288
    assert current.report_output_token_reserve == 131072


def test_model_timeout_comes_from_environment():
    assert settings(AGENT_MODEL_TIMEOUT_SECONDS="3600").model_timeout_seconds == 3600


@pytest.mark.parametrize(
    "name", ["AGENT_CODING_TEMPERATURE", "AGENT_REPORT_CODING_TEMPERATURE"]
)
@pytest.mark.parametrize("value", ["invalid", "-0.1", "2.1"])
def test_invalid_coding_temperature_is_rejected(name, value):
    with pytest.raises(ValueError, match=name):
        settings(**{name: value})


@pytest.mark.parametrize(
    "name",
    ["AGENT_CODING_REASONING_EFFORT", "AGENT_REPORT_CODING_REASONING_EFFORT"],
)
def test_invalid_coding_reasoning_effort_is_rejected(name):
    with pytest.raises(ValueError, match=name):
        settings(**{name: "unbounded"})


@pytest.mark.parametrize(
    "name",
    ["AGENT_CODING_THINKING_BUDGET", "AGENT_REPORT_CODING_THINKING_BUDGET"],
)
@pytest.mark.parametrize("value", ["invalid", "0", "131073"])
def test_invalid_coding_thinking_budget_is_rejected(name, value):
    with pytest.raises(ValueError, match=name):
        settings(**{name: value})


@pytest.mark.parametrize("value", ["invalid", "0", "3601"])
def test_model_timeout_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="AGENT_MODEL_TIMEOUT_SECONDS"):
        settings(AGENT_MODEL_TIMEOUT_SECONDS=value)


def test_agent_tracing_can_be_enabled():
    current = settings(
        AGENT_TRACING_ENABLED="true",
        AGENT_TRACING_PHOENIX_ENDPOINT=" http://phoenix:6006/ ",
        AGENT_TRACING_PHOENIX_API_KEY=" secret ",
        AGENT_TRACING_PHOENIX_PROJECT=" hrp ",
    )

    assert current.tracing_enabled is True
    assert current.tracing_phoenix_endpoint == "http://phoenix:6006/v1/traces"
    assert current.tracing_phoenix_api_key == "secret"
    assert current.tracing_phoenix_project_name == "hrp"


def test_phoenix_trace_endpoint_keeps_complete_trace_path():
    current = settings(AGENT_TRACING_PHOENIX_ENDPOINT="https://example.test/org/v1/traces")

    assert current.tracing_phoenix_endpoint == "https://example.test/org/v1/traces"


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://phoenix.example",
        "https://user:password@phoenix.example",
        "https://phoenix.example?token=secret",
    ],
)
def test_phoenix_trace_endpoint_rejects_invalid_values(endpoint):
    with pytest.raises(ValueError, match="AGENT_TRACING_PHOENIX_ENDPOINT"):
        settings(AGENT_TRACING_PHOENIX_ENDPOINT=endpoint)


def test_phoenix_project_rejects_empty_value():
    with pytest.raises(ValueError, match="AGENT_TRACING_PHOENIX_PROJECT"):
        settings(AGENT_TRACING_PHOENIX_PROJECT=" ")


def test_workspace_snapshot_comes_from_environment():
    assert settings(DAYTONA_DEFAULT_SNAPSHOT=" custom-snapshot ").workspace_snapshot == (
        "custom-snapshot"
    )
    assert settings(DAYTONA_DEFAULT_SNAPSHOT=" ").workspace_snapshot == DEFAULT_WORKSPACE_SNAPSHOT


def test_daytona_network_allow_list_is_validated_and_normalized():
    current = settings(DAYTONA_NETWORK_ALLOW_LIST=" 203.0.113.10/32, 192.168.1.0/24 ")

    assert current.daytona_network_allow_list == "203.0.113.10/32,192.168.1.0/24"


@pytest.mark.parametrize(
    "value",
    [
        "203.0.113.10",
        "203.0.113.10/24",
        "2001:db8::/32",
        ",".join(f"10.0.0.{index}/32" for index in range(11)),
    ],
)
def test_daytona_network_allow_list_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="DAYTONA_NETWORK_ALLOW_LIST"):
        settings(DAYTONA_NETWORK_ALLOW_LIST=value)


def test_report_data_sources_dir_is_trimmed():
    assert settings(
        AGENT_REPORT_DATA_SOURCES_DIR=" /run/agentos/reporting "
    ).report_data_sources_dir == ("/run/agentos/reporting")


def test_report_metadata_config_is_normalized():
    current = settings(
        AGENT_REPORT_METADATA_URL=" https://metadata.internal/ ",
        AGENT_REPORT_METADATA_TOKEN=" token ",
    )

    assert current.report_metadata_url == "https://metadata.internal"
    assert current.report_metadata_token == "token"


@pytest.mark.parametrize(
    "value",
    ["ftp://metadata.internal", "https://user@metadata.internal", "https://metadata/x?q=1"],
)
def test_report_metadata_url_rejects_unsafe_values(value):
    with pytest.raises(ValueError, match="AGENT_REPORT_METADATA_URL"):
        settings(AGENT_REPORT_METADATA_URL=value)


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
        ("AGENT_OS_WORKERS", "2"),
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
