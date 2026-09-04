import asyncio
from types import SimpleNamespace

import pytest
from agno.db.postgres import AsyncPostgresDb
from loguru import logger

from smart_reporting.runtime.database import (
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


@pytest.mark.anyio
async def test_session_database_logs_safe_timing_without_identifiers(monkeypatch):
    private_session_id = "private-session-id"
    private_user_id = "private-user-id"
    captured_get: list[tuple[object, object, object, object, object]] = []

    async def fake_get_session(
        _self,
        session_id,
        session_type=None,
        user_id=None,
        deserialize=True,
        runs_limit=None,
    ):
        captured_get.append((session_id, session_type, user_id, deserialize, runs_limit))
        return SimpleNamespace(runs=[])

    async def fake_upsert(_self, session, deserialize=True):
        _ = deserialize
        return session

    monkeypatch.setattr(AsyncPostgresDb, "get_session", fake_get_session)
    monkeypatch.setattr(AsyncPostgresDb, "upsert_session", fake_upsert)
    database = SerializedAsyncPostgresDb(db_url=DEFAULT_AGENT_DB_URL)
    session = SimpleNamespace(session_id=private_session_id, runs=[])
    records: list[str] = []
    sink_id = logger.add(records.append, level="INFO", format="{message}")

    try:
        result = await database.get_session(
            private_session_id,
            session_type="agent",
            user_id=private_user_id,
            runs_limit=3,
        )
        stored = await database.upsert_session(session)
    finally:
        logger.remove(sink_id)

    log_text = "".join(records)
    assert result is not None
    assert captured_get == [(private_session_id, "agent", private_user_id, True, 3)]
    assert stored is session
    assert "agent_session_read_completed" in log_text
    assert "agent_session_write_completed" in log_text
    assert "backend=postgresql" in log_text
    assert private_session_id not in log_text
    assert private_user_id not in log_text


@pytest.mark.anyio
async def test_postgres_table_initialization_serializes_only_same_table(monkeypatch):
    active_calls = 0
    max_active_calls = 0

    async def fake_get_or_create_table(
        _self, table_name, table_type, create_table_if_not_found=False
    ):
        nonlocal active_calls, max_active_calls
        _ = table_name, table_type, create_table_if_not_found
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        await asyncio.sleep(0)
        active_calls -= 1
        return object()

    monkeypatch.setattr(AsyncPostgresDb, "_get_or_create_table", fake_get_or_create_table)
    database = SerializedAsyncPostgresDb(db_url=DEFAULT_AGENT_DB_URL)

    await asyncio.gather(
        database._get_or_create_table("agno_traces", "traces", True),
        database._get_or_create_table("agno_traces", "traces", True),
    )

    assert max_active_calls == 1

    max_active_calls = 0
    await asyncio.gather(
        database._get_or_create_table("agno_traces", "traces", True),
        database._get_or_create_table("agno_spans", "spans", True),
    )

    assert max_active_calls == 2


def test_database_factory_rejects_non_postgresql_url():
    with pytest.raises(ValueError, match="只支持 postgresql"):
        create_agent_database("mysql://database/example")
