from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, text

from smart_reporting.tests.test_management_access import client as client, login
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD, auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_scopes_require_admin_csrf_and_explicit_registration(client):
    url = '/management/api/v1/scopes'
    assert (await client.get(url)).status_code == 401
    await login(client)
    payload = {'database': 'warehouse', 'companyId': '100', 'name': '华东公司'}
    assert (await client.post(url, json=payload)).status_code == 403
    csrf = (await client.get('/management/api/v1/me')).json()['csrfToken']
    headers = {'origin': 'https://reports.example', 'x-csrf-token': csrf}
    result = await client.post(url, json=payload, headers=headers)
    assert result.status_code == 201, result.text
    assert result.json()['version'] == 1
    assert (await client.post(url, json=payload, headers=headers)).status_code == 409
    await client.post(url, json={**payload, 'companyId': '200'}, headers=headers)
    first = (await client.get(url, params={'limit': 1})).json()
    assert len(first['items']) == 1
    second = (await client.get(url, params={'limit': 1, 'after': first['nextCursor']})).json()
    assert second['items'][0]['companyId'] != first['items'][0]['companyId']
    assert second['nextCursor'] is None
    assert (await client.post(url, json={**payload, 'companyId': ' '}, headers=headers)).status_code == 422
    events = (await client.get('/management/api/v1/audit')).json()['items']
    created = [item for item in events if item['action'] == 'scope_created']
    assert len(created) == 2
    assert created[0]['details']['database'] == 'warehouse'


async def test_selected_actor_cannot_write_after_logout(auth_context):
    from smart_reporting.management.models import AdminSessionInvalid, ManagementError, ManagementScope
    from smart_reporting.management.scopes import ScopeService
    auth, repository, _ = auth_context
    service = ScopeService(auth)
    await auth.bootstrap(OLD_PASSWORD)
    login = await auth.login('admin', OLD_PASSWORD, '127.0.0.1')
    scope = ManagementScope('warehouse', '100')
    with pytest.raises(ManagementError, match='management_scope_not_found'):
        await service.actor(login.raw_token, scope)
    await service.register(login.raw_token, scope, '华东公司')
    actor = await service.actor(login.raw_token, scope)
    await auth.logout(login.raw_token)
    with pytest.raises(AdminSessionInvalid):
        async with service.write_transaction(actor):
            pytest.fail('撤销会话不应进入资源写事务')


async def test_resource_write_serializes_with_revocation_and_rolls_back_audit(auth_context):
    from smart_reporting.management.models import ManagementScope
    from smart_reporting.management.scopes import ScopeService, tenant_settings
    from smart_reporting.management.repository import audit_events
    auth, repository, _ = auth_context
    service = ScopeService(auth)
    await auth.bootstrap(OLD_PASSWORD)
    login = await auth.login('admin', OLD_PASSWORD, '127.0.0.1')
    scope = ManagementScope('warehouse', '100')
    await service.register(login.raw_token, scope, '原名称')
    actor = await service.actor(login.raw_token, scope)
    async with service.write_transaction(actor) as connection:
        await connection.execute(tenant_settings.update().values(name='新名称'))
        logout = asyncio.create_task(auth.logout(login.raw_token))
        # 独立连接可见撤销正在等待资源事务持有的 advisory lock。
        async with repository.engine.connect() as observer:
            async def wait_for_lock():
                while not await observer.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' AND granted=false)")):
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(wait_for_lock(), 5)
        assert not logout.done()
    await asyncio.wait_for(logout, 5)
    new_login = await auth.login('admin', OLD_PASSWORD, '127.0.0.1')
    actor = await service.actor(new_login.raw_token, scope)
    with pytest.raises(RuntimeError, match='故障注入'):
        async with service.write_transaction(actor) as connection:
            await connection.execute(tenant_settings.update().values(name='不应提交'))
            await service.audit(connection, actor, 'resource_changed', {'id': 'test'})
            raise RuntimeError('故障注入')
    async with repository.engine.connect() as connection:
        assert await connection.scalar(select(tenant_settings.c.name)) == '新名称'
        assert not (await connection.execute(select(audit_events).where(audit_events.c.action == 'resource_changed'))).first()
