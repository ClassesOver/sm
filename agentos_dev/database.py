import psycopg
from agno.db.postgres import PostgresDb

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


class SerializedPostgresDb(PostgresDb):
    def _create_all_tables(self):
        with psycopg.connect(psycopg_db_url(self.db_url)) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("agno:create-all-tables",),
            )
            return super()._create_all_tables()
