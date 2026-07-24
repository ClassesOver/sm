from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .context_management import clear_terminal_session_reasoning
from .settings import DEFAULT_AGENT_DB_URL as SETTINGS_DEFAULT_AGENT_DB_URL
from .settings import database_url_from_environment

DEFAULT_AGENT_DB_URL = SETTINGS_DEFAULT_AGENT_DB_URL
SQLITE_BUSY_TIMEOUT_MS = 30_000


def agent_db_url() -> str:
    return database_url_from_environment()


def _normalized_database_urls(db_url: str) -> tuple[str, str, str]:
    try:
        url = make_url(db_url)
    except Exception as error:
        raise ValueError("AGENT_DB_URL 不是有效的数据库地址。") from error

    if url.drivername in {"postgresql", "postgresql+psycopg"}:
        normalized = str(url.set(drivername="postgresql+psycopg"))
        return "postgresql", normalized, normalized

    if url.drivername in {"sqlite", "sqlite+aiosqlite"}:
        database = str(url.database or "")
        query = {str(key).lower(): str(value).lower() for key, value in url.query.items()}
        if not database or database == ":memory:" or query.get("mode") == "memory":
            raise ValueError("SQLite 必须使用持久化文件，不能使用内存数据库。")
        async_url = str(url.set(drivername="sqlite+aiosqlite"))
        sync_url = str(url.set(drivername="sqlite"))
        return "sqlite", async_url, sync_url

    raise ValueError("AGENT_DB_URL 只支持 postgresql[+psycopg]:// 或 sqlite[+aiosqlite]:///。")


def psycopg_db_url(db_url: str | None = None) -> str:
    backend, _async_url, sync_url = _normalized_database_urls(db_url or agent_db_url())
    if backend != "postgresql":
        raise ValueError("当前数据库不是 PostgreSQL，不能创建 psycopg 连接。")
    return sync_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _configure_sqlite_engine(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def configure_connection(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()


class SerializedAsyncPostgresDb(AsyncPostgresDb):
    async def _create_all_tables(self):
        connection = await psycopg.AsyncConnection.connect(psycopg_db_url(self.db_url))
        async with connection:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("agno:create-all-tables",),
            )
            return await super()._create_all_tables()

    async def upsert_session(self, session, deserialize=True):
        clear_terminal_session_reasoning(session)
        return await super().upsert_session(session, deserialize=deserialize)


class SerializedAsyncSqliteDb(AsyncSqliteDb):
    async def upsert_session(self, session, deserialize=True):
        clear_terminal_session_reasoning(session)
        return await super().upsert_session(session, deserialize=deserialize)


@dataclass(frozen=True)
class AgentDatabase:
    backend: str
    async_url: str
    sync_url: str
    async_db: AsyncBaseDb
    sync_db: BaseDb

    @property
    def async_engine(self) -> AsyncEngine:
        return self.async_db.db_engine  # type: ignore[attr-defined,no-any-return]

    @property
    def sync_engine(self) -> Engine:
        return self.sync_db.db_engine  # type: ignore[attr-defined,no-any-return]


def create_agent_database(db_url: str | None = None) -> AgentDatabase:
    backend, async_url, sync_url = _normalized_database_urls(db_url or agent_db_url())
    if backend == "postgresql":
        async_engine = create_async_engine(
            async_url,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        sync_engine = create_engine(
            sync_url,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        async_db: AsyncBaseDb = SerializedAsyncPostgresDb(
            db_url=async_url,
            db_engine=async_engine,
        )
        sync_db: BaseDb = PostgresDb(db_url=sync_url, db_engine=sync_engine)
    else:
        sqlite_path = make_url(sync_url).database
        if sqlite_path:
            Path(sqlite_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        async_engine = create_async_engine(async_url)
        sync_engine = create_engine(sync_url)
        _configure_sqlite_engine(async_engine.sync_engine)
        _configure_sqlite_engine(sync_engine)
        async_db = SerializedAsyncSqliteDb(db_url=async_url, db_engine=async_engine)
        sync_db = SqliteDb(db_url=sync_url, db_engine=sync_engine)
    return AgentDatabase(
        backend=backend,
        async_url=async_url,
        sync_url=sync_url,
        async_db=async_db,
        sync_db=sync_db,
    )


def check_database(database: AgentDatabase | BaseDb | str | None = None) -> None:
    owns_database = isinstance(database, str) or database is None
    bundle = (
        create_agent_database(database if isinstance(database, str) else None)
        if owns_database
        else None
    )
    if bundle is not None:
        sync_db = bundle.sync_db
    elif isinstance(database, AgentDatabase):
        sync_db = database.sync_db
    else:
        assert isinstance(database, BaseDb)
        sync_db = database
    try:
        with sync_db.db_engine.connect() as connection:  # type: ignore[attr-defined]
            connection.execute(text("SELECT 1")).scalar_one()
    finally:
        if bundle is not None:
            bundle.sync_db.close()
