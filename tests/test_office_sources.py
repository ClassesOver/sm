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
@pytest.mark.parametrize('change', ['none', 'grant', 'member_limit', 'membership', 'session', 'release'])
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
            elif change == 'member_limit':
                await office.limit_source_member(admin, space, 'source', '20', ['db.b'])
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
async def test_workspace_sources_keep_healthy_sources_when_one_credential_is_unavailable():
    from smart_reporting.management.models import ManagementError
    from smart_reporting.office.source_runtime import OfficeSourceRuntime

    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine)
        await office.create_schema()
        admin = Identity('db', '1', '10')
        await office.bootstrap(admin, 'Admin')
        space = (await office.create_space(admin, 'Team', admin.user))['id']
        for source in ('legacy', 'invalid', 'healthy'):
            await office.grant_source(admin, space, source, ['db.a'])

        class Vault:
            async def resolve(self, connection, scope, source, reference):
                if source == 'legacy':
                    raise ManagementError('management_credential_key_missing', '缺少解密历史凭据所需的密钥。', 503)
                if source == 'invalid':
                    return 'invalid-private-dsn'
                return 'starrocks://test:local-test-password@localhost/db'

        class Runtime(OfficeSourceRuntime):
            async def published(self, connection, actor, source):
                return 'scope', dict(revision=1, name=source, source_type='starrocks',
                                     database='db', credential_ref='ref', execution_parameters={}), ('db.a',)

        runtime = Runtime(office, Vault())
        listing = {item['id']: item for item in await runtime.available(admin, space)}
        assert listing['healthy']['available'] and listing['healthy']['tables'] == ('db.a',)
        assert listing['legacy'] == {'id': 'legacy', 'available': False, 'reason': '缺少解密历史凭据所需的密钥。'}
        assert not listing['invalid']['available']
        assert 'local-test-password' not in repr(listing) and 'invalid-private-dsn' not in repr(listing)
        with pytest.raises(OfficeError) as error:
            await runtime.query(admin, space, 'legacy', 'SELECT value FROM db.a')
        assert error.value.code == 'management_credential_key_missing'
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
        from smart_reporting.management.models import INSTANCE_SCOPE_ID, ManagementScope
        from smart_reporting.office.source_migration import adopt_instance_sources
        async with engine.begin() as connection:
            for table in (sources, source_drafts, source_credentials):
                row = (await connection.execute(select(table))).mappings().one()
                await connection.execute(insert(table).values(dict(row, scope_id=INSTANCE_SCOPE_ID)))
        preview = await adopt_instance_sources(office, other, ['sales'], dry_run=True)
        assert preview['dryRun']
        async with engine.connect() as connection:
            assert await OfficeSourceScopes.scope_id(connection, other) is None
        await adopt_instance_sources(office, other, ['sales'])
        other_scope = ManagementScope(other.database, other.company)
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


@pytest.mark.asyncio
async def test_office_query_http_enforces_member_table_scope_before_database_execution(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.office.api import COOKIE, create_office_router, csrf_token
    from smart_reporting.office.source_runtime import OfficeSourceRuntime
    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter

    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine)
        await office.create_schema()
        admin = Identity('db', '1', 'admin')
        viewer = Identity('db', '1', 'viewer')
        await office.bootstrap(admin, 'Admin')
        await office.provision(admin, viewer.user, 'Viewer')
        space = (await office.create_space(admin, 'Team', admin.user))['id']
        await office.set_member(admin, space, viewer.user, 'viewer')
        await office.grant_source(admin, space, 'sales', ['db.allowed', 'db.private'])
        await office.limit_source_member(admin, space, 'sales', viewer.user, ['db.allowed'])

        class Vault:
            async def resolve(self, *_args):
                return 'starrocks://test:test@localhost/db'

        async def published(*_args):
            return 'scope', dict(revision=1, name='Sales', source_type='starrocks',
                                 database='db', credential_ref='ref', execution_parameters={}), ('db.allowed', 'db.private')

        executed = []

        def query(_adapter, sql):
            executed.append(sql)
            return SimpleNamespace(columns=['amount'], rows=[[42]])

        monkeypatch.setattr(OfficeSourceRuntime, 'published', published)
        monkeypatch.setattr(StarRocksDataSourceAdapter, '_query', query)
        app = FastAPI()
        app.include_router(create_office_router(office, public_origin='http://test', source_vault=Vault()))
        token = await office.create_session(viewer)
        headers = {'origin': 'http://test', 'x-csrf-token': csrf_token(token)}
        endpoint = f'/office/api/workspaces/{space}/data-sources/sales/query'
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', cookies={COOKIE: token}) as client:
            restricted = await client.post(endpoint, headers=headers, json={'sql': 'SELECT amount FROM db.private'})
            assert restricted.status_code == 422, restricted.text
            assert restricted.json()['code'] == 'sql_table_denied', restricted.text
            assert executed == []

            authorized = await client.post(endpoint, headers=headers, json={'sql': 'SELECT amount FROM db.allowed'})
            assert authorized.status_code == 200, authorized.text
            assert authorized.json()['rows'] == [[42]]
            assert authorized.json()['source']['tables'] == ['db.allowed']
            assert executed == ['SELECT amount FROM db.allowed']
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('prefix', ['', '/admin'])
async def test_member_source_permissions_require_company_admin_even_for_workspace_owner(prefix):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from smart_reporting.office.api import COOKIE, create_office_router, csrf_token

    engine = create_async_engine('sqlite+aiosqlite://')
    try:
        office = OfficeRepository(engine)
        await office.create_schema()
        admin, owner, foreign = Identity('db', '1', 'admin'), Identity('db', '1', 'owner'), Identity('db', '2', 'admin')
        await office.bootstrap(admin, 'Admin')
        await office.provision(admin, owner.user, 'Owner')
        await office.bootstrap(foreign, 'Foreign admin')
        space = (await office.create_space(admin, 'Team', owner.user))['id']
        await office.grant_source(admin, space, 'sales', ['db.allowed', 'db.private'])
        app = FastAPI()
        app.include_router(create_office_router(office, public_origin='http://test', source_vault=object()))
        endpoint = f'/office/api{prefix}/workspaces/{space}/data-sources/sales/members'
        for actor, expected in ((owner, 403), (foreign, 404), (admin, 200)):
            token = await office.create_session(actor)
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', cookies={COOKIE: token}) as client:
                headers = {'origin': 'http://test', 'x-csrf-token': csrf_token(token)}
                result = await client.put(endpoint + '/owner', headers=headers, json={'tables': ['db.allowed']})
                assert result.status_code == expected, result.text
                listing = await client.get(endpoint)
                assert listing.status_code == expected, listing.text
                if expected == 200:
                    assert listing.json()['members'] == [{'user': 'owner', 'name': 'Owner', 'role': 'owner'}]
                    assert listing.json()['items'] == [{'user': 'owner', 'tables': ['db.allowed']}]
                    forbidden = await client.put(endpoint + '/owner', headers=headers, json={'tables': ['db.foreign']})
                    assert forbidden.status_code == 422
                    assert (await client.put(endpoint + '/owner', headers=headers, json={'tables': None})).status_code == 200
                    assert (await client.get(endpoint)).json()['items'] == []
        assert await office.source_tables(owner, space, 'sales') == ['db.allowed', 'db.private']
    finally:
        await engine.dispose()
