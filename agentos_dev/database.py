import os

import psycopg
from agno.db.postgres import PostgresDb


DEFAULT_AGENT_DB_URL = "postgresql+psycopg://odoo@127.0.0.1:55432/dev"


def agent_db_url() -> str:
    return (
        os.getenv("AGENT_DB_URL")
        or os.getenv("DATABASE_URL")
        or DEFAULT_AGENT_DB_URL
    ).strip()


def psycopg_db_url(db_url: str | None = None) -> str:
    return (db_url or agent_db_url()).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )


class SerializedPostgresDb(PostgresDb):
    def _create_all_tables(self):
        with psycopg.connect(psycopg_db_url(self.db_url)) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("agno:create-all-tables",),
            )
            return super()._create_all_tables()
