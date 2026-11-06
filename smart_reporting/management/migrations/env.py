from __future__ import annotations

import asyncio

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.management.repository import metadata
from smart_reporting.runtime.database import _normalized_database_urls
from smart_reporting.runtime.settings import database_url_from_environment


def migrate(connection):
    context.configure(
        connection=connection,
        target_metadata=metadata,
        version_table_schema="reporting_management",
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def online():
    load_dotenv()
    _, url, _ = _normalized_database_urls(database_url_from_environment())
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("CREATE SCHEMA IF NOT EXISTS reporting_management"))
            await connection.commit()
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("管理迁移要求连接目标 PostgreSQL；不输出含连接信息的离线 SQL。")
else:
    asyncio.run(online())
