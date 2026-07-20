from agentos_dev.database import DEFAULT_AGENT_DB_URL, agent_db_url, psycopg_db_url

DATABASE_ENV = (
    "AGENT_DB_URL",
    "DATABASE_URL",
    "AGENT_POSTGRES_HOST",
    "AGENT_POSTGRES_PORT",
    "AGENT_POSTGRES_DB",
    "AGENT_POSTGRES_USER",
    "AGENT_POSTGRES_PASSWORD",
)


def clear_database_env(monkeypatch):
    for name in DATABASE_ENV:
        monkeypatch.delenv(name, raising=False)


def test_database_url_precedence_and_default(monkeypatch):
    clear_database_env(monkeypatch)
    assert agent_db_url() == DEFAULT_AGENT_DB_URL

    monkeypatch.setenv("DATABASE_URL", "postgresql://database-url/db")
    assert agent_db_url() == "postgresql://database-url/db"
    monkeypatch.setenv("AGENT_DB_URL", "postgresql+psycopg://agent-url/db")
    assert agent_db_url() == "postgresql+psycopg://agent-url/db"


def test_database_url_uses_postgres_environment(monkeypatch):
    clear_database_env(monkeypatch)
    monkeypatch.setenv("AGENT_POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("AGENT_POSTGRES_PORT", "55432")
    monkeypatch.setenv("AGENT_POSTGRES_DB", "agent data")
    monkeypatch.setenv("AGENT_POSTGRES_USER", "agent user")
    monkeypatch.setenv("AGENT_POSTGRES_PASSWORD", "p@ss:/word")

    url = agent_db_url()
    assert url == (
        "postgresql+psycopg://agent%20user:p%40ss%3A%2Fword@127.0.0.1:55432/agent%20data"
    )
    assert psycopg_db_url(url).startswith("postgresql://")
