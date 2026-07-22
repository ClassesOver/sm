import psycopg
from agno.db.postgres import AsyncPostgresDb

from .context_management import clear_terminal_session_reasoning
from .settings import DEFAULT_AGENT_DB_URL as SETTINGS_DEFAULT_AGENT_DB_URL
from .settings import database_url_from_environment

DEFAULT_AGENT_DB_URL = SETTINGS_DEFAULT_AGENT_DB_URL


def agent_db_url() -> str:
    return database_url_from_environment()


def psycopg_db_url(db_url: str | None = None) -> str:
    return (db_url or agent_db_url()).replace("postgresql+psycopg://", "postgresql://", 1)


def check_database(db_url: str | None = None) -> None:
    with psycopg.connect(psycopg_db_url(db_url), connect_timeout=3) as connection:
        connection.execute("SELECT 1").fetchone()


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
