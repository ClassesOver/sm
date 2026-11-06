from __future__ import annotations

import pytest
from sqlalchemy import select

from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_source_release_versions_credentials_and_cas(auth_context):
    from cryptography.fernet import Fernet

    from smart_reporting.management.data_sources.models import SourceDraftInput
    from smart_reporting.management.data_sources.secrets import CredentialVault
    from smart_reporting.management.data_sources.service import SourceService
    from smart_reporting.management.models import ManagementScope
    from smart_reporting.management.repository import source_credentials, source_versions
    from smart_reporting.management.scopes import ScopeService

    auth, repository, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    admin = await auth.login('admin', OLD_PASSWORD, '127.0.0.1')
    scope_service = ScopeService(auth)
    scope = ManagementScope('warehouse', '100')
    await scope_service.register(admin.raw_token, scope, '华东公司')
    vault = CredentialVault(f'key-a:{Fernet.generate_key().decode()}')
    service = SourceService(scope_service, vault)
    payload = SourceDraftInput.model_validate({
        'name': '生产数仓', 'type': 'starrocks', 'database': 'warehouse',
        'dsn': 'starrocks://reporter:first-secret@localhost:9030/warehouse',
        'reportingProfileVersionId': 'base:1', 'metadataVersionId': 'operations:1',
    })
    draft = await service.create_draft(admin.raw_token, scope, 'operations', payload)
    assert draft['version'] == 1
    assert 'first-secret' not in str(draft)
    from smart_reporting.tests.management_fixtures import publish_dependencies
    await publish_dependencies(scope_service, admin.raw_token, scope)
    with pytest.raises(Exception, match='management_version_conflict'):
        await service.publish(admin.raw_token, scope, 'operations', 2)
    first = await service.publish(admin.raw_token, scope, 'operations', 1)
    assert first['revision'] == 1
    assert 'first-secret' not in str(first)
    assert await service.resolve_credentials(scope, 'operations', 1) == 'starrocks://reporter:first-secret@localhost:9030/warehouse'
    updated_payload = SourceDraftInput.model_validate({
        'name': '生产数仓改密', 'type': 'starrocks', 'database': 'warehouse',
        'dsn': 'starrocks://reporter:second-secret@localhost:9030/warehouse',
        'reportingProfileVersionId': 'base:1', 'metadataVersionId': 'operations:1',
    })
    with pytest.raises(Exception, match='management_version_conflict'):
        await service.save_draft(admin.raw_token, scope, 'operations', updated_payload, 2)
    second_draft = await service.save_draft(admin.raw_token, scope, 'operations', updated_payload, 1)
    second = await service.publish(admin.raw_token, scope, 'operations', second_draft['version'])
    assert second['revision'] == 2
    assert first['contentHash'] != second['contentHash']
    assert await service.resolve_credentials(scope, 'operations', 1) == 'starrocks://reporter:first-secret@localhost:9030/warehouse'
    assert await service.resolve_credentials(scope, 'operations', 2) == 'starrocks://reporter:second-secret@localhost:9030/warehouse'
    async with repository.engine.connect() as connection:
        stored = (await connection.execute(select(source_credentials))).mappings().all()
        versions = (await connection.execute(select(source_versions))).mappings().all()
    assert len(versions) == 2
    assert all('first-secret' not in row['ciphertext'] and 'second-secret' not in row['ciphertext'] for row in stored)
    assert all('password' not in str(row) for row in versions)


async def test_source_rejects_unsupported_database_and_unrequested_fields():
    from pydantic import ValidationError

    from smart_reporting.management.data_sources.models import SourceDraftInput
    with pytest.raises(ValidationError):
        SourceDraftInput.model_validate({'name': 'x', 'type': 'mysql', 'database': 'warehouse', 'dsn': 'mysql://x'})
    with pytest.raises(ValidationError):
        SourceDraftInput.model_validate({'name': 'x', 'database': 'warehouse', 'dsn': 'starrocks://x:y@localhost/warehouse', 'owner': 'someone'})
    with pytest.raises(ValidationError):
        SourceDraftInput.model_validate({'name': 'x', 'database': 'warehouse', 'dsn': 'starrocks://x:y@localhost/warehouse', 'queryLimit': 100})
