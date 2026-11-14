"""系统凭据独立加密、版本引用及启动消费，不借用数据源身份。"""
import asyncio
import os
from dataclasses import replace

import pytest
from sqlalchemy import select

from smart_reporting.management.data_sources.secrets import CredentialVault
from smart_reporting.management.models import ManagementError
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def context(auth_context, monkeypatch):
    from smart_reporting.management.system_configuration import SystemConfigurationService

    auth, repo, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    token = (await auth.login('admin', OLD_PASSWORD, '127.0.0.1')).raw_token
    monkeypatch.setenv('AGENT_MANAGEMENT_CREDENTIAL_KEYS', 'test:' + CredentialVault.generate_key())
    startup = replace(AgentSettings.from_environment({}, load_env_file=False),
        database_url=str(repo.engine.url.render_as_string(hide_password=False)), openai_api_key='deployment-secret')
    return SystemConfigurationService(auth, startup), token, repo


async def test_replacement_is_encrypted_referenced_and_only_effective_after_restart(context):
    from smart_reporting.management.repository import audit_events, system_credentials
    from smart_reporting.runtime.system_configuration import load_system_configuration

    service, token, repo = context
    await service.detail(token)
    saved = await service.replace_credential(token, 'OPENAI_API_KEY', 'replacement-secret', 1)
    assert saved['version'] == 2
    detail = await service.detail(token)
    reference = detail['draft']['document']['credentials']['OPENAI_API_KEY']
    assert 'replacement-secret' not in str(detail)
    assert any(change['path'] == 'credentials.OPENAI_API_KEY' for change in detail['changes'])
    async with repo.engine.connect() as connection:
        row = (await connection.execute(select(system_credentials))).mappings().one()
        audits = (await connection.execute(select(audit_events))).mappings().all()
    assert row['reference'] == reference
    assert 'replacement-secret' not in str(row) + str(audits)
    assert CredentialVault().decrypt(row['key_id'], row['ciphertext'].encode()) == 'replacement-secret'
    assert service.startup.openai_api_key == 'deployment-secret'
    assert (await asyncio.to_thread(load_system_configuration, service.startup)).settings.openai_api_key == 'deployment-secret'
    await service.publish(token, 2)
    loaded = await asyncio.to_thread(load_system_configuration, service.startup)
    assert loaded.settings.openai_api_key == 'replacement-secret'
    assert loaded.state.issue is None
    assert 'OPENAI_API_KEY' in loaded.state.managed_keys
    from smart_reporting.management.models import INSTANCE_SCOPE
    from smart_reporting.management.runtime import ManagedConfigurationProvider
    from smart_reporting.management.scopes import ScopeService

    provider = ManagedConfigurationProvider(ScopeService(service.auth), CredentialVault(), startup_settings=loaded.settings)
    snapshot = await provider.register_run('credential-task', INSTANCE_SCOPE, user_id='user', thread_id='thread', entrypoint='cli')
    assert snapshot['systemRevision'] == 1
    assert 'replacement-secret' not in str(snapshot)
    assert 'OPENAI_API_KEY' not in snapshot['systemValues']
    assert (await service.replace_credential(token, 'OPENAI_API_KEY', 'second-secret', 2))['version'] == 3
    await service.publish(token, 3)
    await service.restore_draft(token, 1, 3)
    await service.publish(token, 4)
    assert (await asyncio.to_thread(load_system_configuration, service.startup)).settings.openai_api_key == 'replacement-secret'


@pytest.mark.parametrize('key,secret,version', [('AGENT_DB_URL', 'secret', 1), ('OPENAI_API_KEY', '', 1),
    ('OPENAI_API_KEY', 'has\nnewline', 1), ('OPENAI_API_KEY', 'secret', 99)])
async def test_invalid_replacement_does_not_change_draft(context, key, secret, version):
    from smart_reporting.management.repository import system_credentials

    service, token, repo = context
    await service.detail(token)
    with pytest.raises(ManagementError):
        await service.replace_credential(token, key, secret, version)
    assert (await service.detail(token))['draft']['version'] == 1
    async with repo.engine.connect() as connection:
        assert not (await connection.execute(select(system_credentials))).all()


async def test_unknown_reference_and_missing_encryption_key_never_silently_apply(context, monkeypatch):
    from uuid import uuid4

    from smart_reporting.runtime.system_configuration import load_system_configuration

    service, token, _ = context
    document = (await service.detail(token))['draft']['document']
    document['credentials'] = {'OPENAI_API_KEY': str(uuid4())}
    with pytest.raises(ManagementError):
        await service.save_draft(token, document, 1)
    await service.replace_credential(token, 'OPENAI_API_KEY', 'managed-secret', 1)
    await service.publish(token, 2)
    monkeypatch.delenv('AGENT_MANAGEMENT_CREDENTIAL_KEYS')
    loaded = await asyncio.to_thread(load_system_configuration, service.startup)
    assert loaded.settings.openai_api_key == 'deployment-secret'
    assert loaded.state.issue['code'] == 'management_configuration_credential_unavailable'
    assert loaded.state.revision is None


async def test_parallel_replacement_is_cas_and_credentials_remain_immutable(context):
    from sqlalchemy import update
    from sqlalchemy.exc import DBAPIError

    from smart_reporting.management.repository import system_credentials

    service, token, repo = context
    await service.detail(token)
    results = await asyncio.gather(service.replace_credential(token, 'OPENAI_API_KEY', 'first', 1),
        service.replace_credential(token, 'OPENAI_API_KEY', 'second', 1), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert any(isinstance(result, ManagementError) and result.code == 'management_version_conflict' for result in results)
    async with repo.engine.connect() as connection:
        assert len((await connection.execute(select(system_credentials))).all()) == 1
    with pytest.raises(DBAPIError):
        async with repo.engine.begin() as connection:
            await connection.execute(update(system_credentials).values(ciphertext='rewritten'))


async def test_expired_session_and_missing_vault_do_not_store_credentials(context, monkeypatch):
    from datetime import timedelta

    from smart_reporting.management.repository import system_credentials

    service, token, repo = context
    await service.detail(token)
    monkeypatch.delenv('AGENT_MANAGEMENT_CREDENTIAL_KEYS')
    with pytest.raises(ManagementError):
        await service.replace_credential(token, 'OPENAI_API_KEY', 'never-saved', 1)
    now = service.auth.clock()
    service.auth.clock = lambda: now + timedelta(hours=48)
    with pytest.raises(ManagementError):
        await service.replace_credential(token, 'OPENAI_API_KEY', 'expired-secret', 1)
    async with repo.engine.connect() as connection:
        assert not (await connection.execute(select(system_credentials))).all()


async def test_metadata_token_uses_same_vault_and_old_key_survives_key_rotation(context, monkeypatch):
    from smart_reporting.runtime.system_configuration import load_system_configuration

    service, token, _ = context
    await service.detail(token)
    old_keys = os.environ['AGENT_MANAGEMENT_CREDENTIAL_KEYS']
    await service.replace_credential(token, 'AGENT_REPORT_METADATA_TOKEN', 'metadata-secret', 1)
    await service.publish(token, 2)
    monkeypatch.setenv('AGENT_MANAGEMENT_CREDENTIAL_KEYS', 'new:' + CredentialVault.generate_key() + ',' + old_keys)
    loaded = await asyncio.to_thread(load_system_configuration, service.startup)
    assert loaded.settings.report_metadata_token == 'metadata-secret'
    assert loaded.state.issue is None
    assert 'metadata-secret' not in str(await service.detail(token))
