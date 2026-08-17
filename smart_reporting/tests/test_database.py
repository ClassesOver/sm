import asyncio
from types import SimpleNamespace

import pytest
from agno.db.postgres import AsyncPostgresDb

from smart_reporting.database import (
    DEFAULT_AGENT_DB_URL,
    SerializedAsyncPostgresDb,
    agent_db_url,
    create_agent_database,
    psycopg_db_url,
)

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
    assert psycopg_db_url(url) == (
        "postgresql://agent%20user:p%40ss%3A%2Fword@127.0.0.1:55432/agent%20data"
    )


def test_database_url_does_not_validate_unrelated_agentos_settings(monkeypatch):
    clear_database_env(monkeypatch)
    monkeypatch.setenv("AGENT_OS_PORT", "invalid")

    assert agent_db_url() == DEFAULT_AGENT_DB_URL


@pytest.mark.anyio
async def test_session_upsert_clears_terminal_reasoning_before_database_write(monkeypatch):
    captured = []

    async def fake_upsert(_self, session, deserialize=True):
        captured.append((session, deserialize))
        return session

    monkeypatch.setattr(AsyncPostgresDb, "upsert_session", fake_upsert)
    run = SimpleNamespace(status="error", reasoning_content="private", messages=[])
    session = SimpleNamespace(runs=[run])
    database = SerializedAsyncPostgresDb(db_url=DEFAULT_AGENT_DB_URL)

    result = await database.upsert_session(session, deserialize=False)

    assert result is session
    assert run.reasoning_content is None
    assert captured == [(session, False)]


def test_sqlite_database_factory_rejects_memory_and_enables_required_pragmas(tmp_path):
    with pytest.raises(ValueError, match="不能使用内存数据库"):
        create_agent_database("sqlite:///:memory:")

    database = create_agent_database(f"sqlite:///{tmp_path / 'agent.db'}")
    try:
        assert database.backend == "sqlite"
        assert database.async_db.db_engine is database.async_engine
        with database.sync_engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 30_000
    finally:
        database.sync_engine.dispose()


@pytest.mark.anyio
async def test_sqlite_async_engine_connects_with_required_pragmas_without_hanging(tmp_path):
    database = create_agent_database(f"sqlite:///{tmp_path / 'agent.db'}")
    try:
        async with asyncio.timeout(5):
            async with database.async_engine.connect() as connection:
                assert (
                    await connection.exec_driver_sql("PRAGMA journal_mode")
                ).scalar_one() == "wal"
                assert (await connection.exec_driver_sql("PRAGMA foreign_keys")).scalar_one() == 1
                assert (
                    await connection.exec_driver_sql("PRAGMA busy_timeout")
                ).scalar_one() == 30_000
    finally:
        await database.async_engine.dispose()
        database.sync_engine.dispose()
