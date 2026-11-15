"""Copy explicitly assigned instance sources into a company's Office management scope."""
import argparse
import asyncio
from loguru import logger
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from ..management.models import INSTANCE_SCOPE_ID
from ..management.repository import (
    sources, source_drafts, source_versions, source_credentials, table_discoveries, catalog_versions,
)
from ..runtime.settings import database_url_from_environment
from .repository import Identity, OfficeError, OfficeRepository
from .source_management import OfficeSourceScopes


async def adopt_instance_sources(office, actor, source_ids: list[str], *, dry_run=False):
    """Deployment operation; no HTTP route or automatic company assignment."""
    if not source_ids or len(source_ids) != len(set(source_ids)):
        raise OfficeError("office_source_migration_invalid", "请指定不重复的数据源标识。", 422)
    async with office.transaction(actor) as connection:
        await office._user(connection, actor, admin=True)
        target_scope = await OfficeSourceScopes.scope_id(connection, actor)
        # Lock source heads so a publication cannot change halfway through copying.
        rows = (await connection.execute(select(sources).where(
            sources.c.scope_id == INSTANCE_SCOPE_ID, sources.c.source_id.in_(source_ids),
        ).order_by(sources.c.source_id).with_for_update())).mappings().all()
        if {row['source_id'] for row in rows} != set(source_ids):
            raise OfficeError("office_source_migration_missing", "部分原数据源不存在。", 404)
        existing = (await connection.execute(select(sources.c.source_id).where(
            sources.c.scope_id == target_scope, sources.c.source_id.in_(source_ids),
        ))).scalars().all()
        if existing:
            raise OfficeError("office_source_migration_conflict", "目标公司已有同标识数据源：" + ', '.join(existing), 409)
        summary = {'sourceIds': sorted(source_ids), 'database': actor.database,
                   'company': actor.company, 'dryRun': dry_run}
        if dry_run:
            return summary
        if target_scope is None:
            target_scope = await OfficeSourceScopes.scope_id(connection, actor, create=True)
        for table in (sources, source_credentials, catalog_versions, table_discoveries,
                      source_drafts, source_versions):
            values = (await connection.execute(select(table).where(
                table.c.scope_id == INSTANCE_SCOPE_ID, table.c.source_id.in_(source_ids),
            ))).mappings().all()
            if values:
                await connection.execute(insert(table), [dict(row, scope_id=target_scope) for row in values])
        await office._audit(connection, actor, 'instance_sources_adopted', sourceIds=sorted(source_ids))
        return summary


async def main(args):
    url = database_url_from_environment(load_env_file=True)
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    engine = create_async_engine(url)
    try:
        result = await adopt_instance_sources(OfficeRepository(engine),
            Identity(args.database, args.company, args.user), args.source, dry_run=args.dry_run)
        logger.info('Office source assignment: {}', result)
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--company', required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--source', action='append', required=True)
    parser.add_argument('--dry-run', action='store_true')
    asyncio.run(main(parser.parse_args()))
