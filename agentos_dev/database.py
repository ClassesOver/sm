import os
from urllib.parse import quote

import psycopg
from agno.db.postgres import PostgresDb


DEFAULT_AGENT_DB_URL = "postgresql+psycopg://odoo@127.0.0.1:55432/dev"


def agent_db_url() -> str:
    configured = os.getenv("AGENT_DB_URL") or os.getenv("DATABASE_URL")
    if configured:
        return configured.strip()
    if not any(name in os.environ for name in (
        "AGENT_POSTGRES_HOST", "AGENT_POSTGRES_PORT", "AGENT_POSTGRES_DB",
        "AGENT_POSTGRES_USER", "AGENT_POSTGRES_PASSWORD",
    )):
        return DEFAULT_AGENT_DB_URL
    user = quote((os.getenv("AGENT_POSTGRES_USER") or "odoo").strip(), safe="")
    password = os.getenv("AGENT_POSTGRES_PASSWORD") or ""
    credentials = "%s:%s" % (user, quote(password, safe="")) if password else user
    host = (os.getenv("AGENT_POSTGRES_HOST") or "127.0.0.1").strip()
    port = (os.getenv("AGENT_POSTGRES_PORT") or "55432").strip()
    database = quote((os.getenv("AGENT_POSTGRES_DB") or "dev").strip(), safe="")
    return "postgresql+psycopg://%s@%s:%s/%s" % (
        credentials, host, port, database,
    )


def psycopg_db_url(db_url: str | None = None) -> str:
    return (db_url or agent_db_url()).replace(
        "postgresql+psycopg://", "postgresql://", 1
    )


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
