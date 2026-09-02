from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import psycopg
from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .context_management import clear_terminal_session_reasoning
from .settings import DEFAULT_AGENT_DB_URL as SETTINGS_DEFAULT_AGENT_DB_URL
from .settings import database_url_from_environment

DEFAULT_AGENT_DB_URL = SETTINGS_DEFAULT_AGENT_DB_URL


def _duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))


def _session_type_name(value: Any) -> str:
    return str(getattr(value, "value", value) or "-")


def agent_db_url() -> str:
    return database_url_from_environment()


def _normalized_database_urls(db_url: str) -> tuple[str, str, str]:
    try:
        url = make_url(db_url)
    except Exception as error:
        raise ValueError("AGENT_DB_URL 不是有效的数据库地址。") from error

    if url.drivername in {"postgresql", "postgresql+psycopg"}:
        _driver, separator, connection = db_url.partition("://")
        normalized = f"postgresql+psycopg{separator}{connection}"
        return "postgresql", normalized, normalized

    raise ValueError("AGENT_DB_URL 只支持 postgresql[+psycopg]://。")


def psycopg_db_url(db_url: str | None = None) -> str:
    backend, _async_url, sync_url = _normalized_database_urls(db_url or agent_db_url())
    if backend != "postgresql":
        raise ValueError("当前数据库不是 PostgreSQL，不能创建 psycopg 连接。")
    return sync_url.replace("postgresql+psycopg://", "postgresql://", 1)


class SerializedAsyncPostgresDb(AsyncPostgresDb):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._table_initialization_locks: dict[str, asyncio.Lock] = {}

    async def _get_or_create_table(
        self,
        table_name: str,
        table_type: str,
        create_table_if_not_found: bool | None = False,
    ) -> Any:
        # Agno 的惰性建表会先查数据库再向共享 MetaData 注册 Table；同名
        # trace/span 首次并发写入时，两个协程都可能通过不存在检查并重复注册。必须按
        # 表名锁住完整检查与创建区间；不能用全局锁，因为建表过程会递归初始化版本表。
        lock = self._table_initialization_locks.setdefault(table_name, asyncio.Lock())
        async with lock:
            return await super()._get_or_create_table(
                table_name,
                table_type,
                create_table_if_not_found,
            )

    async def _create_all_tables(self):
        connection = await psycopg.AsyncConnection.connect(psycopg_db_url(self.db_url))
        async with connection:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("agno:create-all-tables",),
            )
            return await super()._create_all_tables()

    async def get_session(
        self,
        session_id,
        session_type=None,
        user_id=None,
        deserialize=True,
        runs_limit=None,
    ):
        started_at = perf_counter()
        logger.info(
            "agent_session_read_started backend=postgresql session_type={} user_id_present={}",
            _session_type_name(session_type),
            str(user_id is not None).lower(),
        )
        try:
            result = await super().get_session(
                session_id=session_id,
                session_type=session_type,
                user_id=user_id,
                deserialize=deserialize,
                runs_limit=runs_limit,
            )
        except BaseException as error:
            logger.warning(
                "agent_session_read_failed backend=postgresql session_type={} duration_ms={} "
                "error_type={}",
                _session_type_name(session_type),
                _duration_ms(started_at),
                type(error).__name__,
            )
            raise
        logger.info(
            "agent_session_read_completed backend=postgresql session_type={} duration_ms={} "
            "found={}",
            _session_type_name(session_type),
            _duration_ms(started_at),
            str(result is not None).lower(),
        )
        return result

    async def upsert_session(self, session, deserialize=True):
        started_at = perf_counter()
        session_type = type(session).__name__
        logger.info(
            "agent_session_write_started backend=postgresql session_type={} run_count={}",
            session_type,
            len(getattr(session, "runs", None) or []),
        )
        try:
            clear_terminal_session_reasoning(session)
            result = await super().upsert_session(session, deserialize=deserialize)
        except BaseException as error:
            logger.warning(
                "agent_session_write_failed backend=postgresql session_type={} duration_ms={} "
                "error_type={}",
                session_type,
                _duration_ms(started_at),
                type(error).__name__,
            )
            raise
        logger.info(
            "agent_session_write_completed backend=postgresql session_type={} duration_ms={} "
            "stored={}",
            session_type,
            _duration_ms(started_at),
            str(result is not None).lower(),
        )
        return result


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
