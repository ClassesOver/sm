import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.office.repository import Identity, OfficeRepository, OfficeError
from smart_reporting.office.source_management import OfficeSourceScopes


def test_source_management_requires_current_company_admin():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite://")
        office = OfficeRepository(engine)
        await office.create_schema()
        admin = Identity("db", "1", "10")
        await office.bootstrap(admin, "Admin")
        await office.provision(admin, "20", "User")
        admin_token = await office.create_session(admin)
        user_token = await office.create_session(Identity("db", "1", "20"))
        scopes = OfficeSourceScopes(office)
        async with scopes.repository.transaction() as connection:
            account = await scopes.repository.authenticate_in_transaction(connection, admin_token, scopes.auth.clock())
            assert account.username == "10"
        async with scopes.repository.transaction() as connection:
            with pytest.raises(OfficeError):
                await scopes.repository.authenticate_in_transaction(connection, user_token, scopes.auth.clock())
        await office.logout(admin_token)
        async with scopes.repository.transaction() as connection:
            with pytest.raises(OfficeError):
                await scopes.repository.authenticate_in_transaction(connection, admin_token, scopes.auth.clock())
        await engine.dispose()
    asyncio.run(scenario())


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['none', 'grant', 'membership', 'session', 'release'])
async def test_source_query_rechecks_authority_after_execution(change):
    from smart_reporting.office.source_runtime import OfficeSourceRuntime

    engine = create_async_engine('sqlite+aiosqlite://')
    office = OfficeRepository(engine)
    await office.create_schema()
    admin = Identity('db', '1', '10')
    await office.bootstrap(admin, 'Admin')
    await office.provision(admin, '20', 'User')
    space = (await office.create_space(admin, 'Team', '10'))['id']
    await office.set_member(admin, space, '20', 'viewer')
    await office.grant_source(admin, space, 'source', ['db.a', 'db.b'])
    await office.limit_source_member(admin, space, 'source', '20', ['db.a'])
    raw = await office.create_session(Identity('db', '1', '20'))
    actor = await office.authenticate(raw)
    revision = 1
    closed = False

    class Vault:
        async def resolve(self, *args):
            return 'starrocks://test:test@localhost/db'

    class Runtime(OfficeSourceRuntime):
        async def published(self, *args):
            return 'scope', dict(revision=revision, name='Source', source_type='starrocks',
                                 database='db', credential_ref='ref', execution_parameters={}), ('db.a', 'db.b')

    class Adapter:
        def __init__(self, config, *, allowed_tables):
            assert allowed_tables == ('db.a',)

        async def query(self, sql):
            nonlocal revision
            assert sql == 'SELECT value FROM db.a'
            if change == 'grant':
                await office.grant_source(admin, space, 'source', [])
            elif change == 'membership':
                await office.set_member(admin, space, '20', None)
            elif change == 'session':
                await office.logout(raw)
            elif change == 'release':
                revision += 1
            return SimpleNamespace(columns=['value'], rows=[[42]])

        async def aclose(self):
            nonlocal closed
            closed = True

    runtime = Runtime(office, Vault(), adapter_factory=Adapter)
    try:
        if change == 'none':
            result = await runtime.query(actor, space, 'source', 'SELECT value FROM db.a')
            assert result['rows'] == [[42]]
            assert result['source']['tables'] == ('db.a',)
        else:
            with pytest.raises(OfficeError):
                await runtime.query(actor, space, 'source', 'SELECT value FROM db.a')
        assert closed
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_existing_source_service_uses_office_company_and_encrypted_vault():
    from smart_reporting.management.repository import (
        metadata, tenant_settings, sources, source_drafts, source_versions,
        source_credentials, catalog_versions, table_discoveries,
    )
    from smart_reporting.management.data_sources.models import SourceDraftInput
    from smart_reporting.management.data_sources.secrets import CredentialVault
    from smart_reporting.management.data_sources.service import SourceService
    from sqlalchemy import insert, select

    engine = create_async_engine('sqlite+aiosqlite://',
                                 execution_options={'schema_translate_map': {'reporting_management': None}})
    office = OfficeRepository(engine)
    await office.create_schema()
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: metadata.create_all(conn, tables=[
            tenant_settings, sources, source_drafts, source_versions, source_credentials, catalog_versions, table_discoveries,
        ]))
    admin = Identity('db', '1', '10')
    await office.bootstrap(admin, 'Admin')
    token = await office.create_session(admin)
    scopes = OfficeSourceScopes(office)
    scope = await scopes.ensure_registered(admin)
    vault = CredentialVault('test:' + CredentialVault.generate_key())
    service = SourceService(scopes, vault)
    try:
        created = await service.create_draft(token, scope, 'sales', SourceDraftInput(
            name='Sales', database='sales', dsn='starrocks://test:secret@localhost/sales'))
        assert created['version'] == 1
        assert 'dsn' not in created
        listing = await service.list(token, scope)
        assert listing['items'][0]['source_id'] == 'sales'
        async with engine.begin() as connection:
            stored = (await connection.execute(select(source_credentials))).mappings().one()
            assert 'secret' not in stored['ciphertext']
            assert await vault.resolve(connection, stored['scope_id'], 'sales', stored['credential_ref']) == 'starrocks://test:secret@localhost/sales'
        other = Identity('db', '2', '10')
        await office.bootstrap(other, 'Other admin')
        other_token = await office.create_session(other)
        other_scope = await scopes.ensure_registered(other)
        assert (await service.list(other_token, other_scope))['items'] == []
        from smart_reporting.management.models import INSTANCE_SCOPE_ID
        from smart_reporting.office.source_migration import adopt_instance_sources
        async with engine.begin() as connection:
            for table in (sources, source_drafts, source_credentials):
                row = (await connection.execute(select(table))).mappings().one()
                await connection.execute(insert(table).values(dict(row, scope_id=INSTANCE_SCOPE_ID)))
        preview = await adopt_instance_sources(office, other, ['sales'], dry_run=True)
        assert preview['dryRun']
        assert (await service.list(other_token, other_scope))['items'] == []
        await adopt_instance_sources(office, other, ['sales'])
        assert (await service.list(other_token, other_scope))['items'][0]['source_id'] == 'sales'
        with pytest.raises(OfficeError, match='已有'):
            await adopt_instance_sources(office, other, ['sales'])
        async with engine.begin() as connection:
            assert await connection.scalar(select(sources.c.source_id).where(
                sources.c.scope_id == INSTANCE_SCOPE_ID)) == 'sales'
    finally:
        await engine.dispose()


def test_report_execution_exposes_only_the_workspace_table_metadata():
    from dataclasses import dataclass
    from smart_reporting.office.source_runtime import restrict_report_execution
    from smart_reporting.reporting.contract import schema_hash
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.tests.management_fixtures import business_metadata

    @dataclass
    class Execution:
        basis: object
        metadata: dict

    metadata = business_metadata()
    table = metadata.tables[0]
    hidden = table.model_copy(update={"name": "confidential"})
    ddl = metadata.ddl_models[0].model_copy(update={"ddl": "CREATE TABLE confidential (id INT)"})
    full = metadata.model_copy(update={
        "tables": (table, hidden), "ddl_models": (metadata.ddl_models[0], ddl),
        "schema_hash": schema_hash((table, hidden)),
    })
    source = table.source_id
    execution = Execution(SimpleNamespace(source_versions=[SimpleNamespace(source_id=source, revision=10)]),
                          {source: full})
    grant = {"revision": 10, "tables": [f"{table.database}.{table.name}"]}
    filtered = restrict_report_execution(execution, {source: grant}).metadata[source]
    assert filtered.tables == (table,)
    assert filtered.ddl_models == metadata.ddl_models
    assert filtered.schema_hash == schema_hash((table,))
    assert full.tables == (table, hidden)
    for missing in ({}, {source: {**grant, "revision": 11}}, {source: {**grant, "tables": []}}):
        with pytest.raises(ReportingError, match="授权"):
            restrict_report_execution(execution, missing)
