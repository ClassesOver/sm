import pytest

from agentos_dev.settings import DEFAULT_AGENT_DB_URL, AgentSettings


def settings(values=None, **overrides):
    environ = {} if values is None else values
    environ.update(overrides)
    return AgentSettings.from_environment(environ, load_env_file=False)


def test_settings_defaults():
    current = settings()
    assert current.port == 7777
    assert current.workers == 4
    assert current.database_url == DEFAULT_AGENT_DB_URL
    assert current.cors_allowed_origins == (
        "http://127.0.0.1:18069",
        "http://localhost:18069",
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
