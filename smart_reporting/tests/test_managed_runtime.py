from __future__ import annotations

import pytest

from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def test_managed_runtime_freezes_published_source_and_profile(auth_context):
    from cryptography.fernet import Fernet

    from smart_reporting.management.data_sources.models import SourceDraftInput
    from smart_reporting.management.data_sources.secrets import CredentialVault
    from smart_reporting.management.data_sources.service import SourceService
    from smart_reporting.management.models import ManagementScope
    from smart_reporting.management.profiles import ProfileService
    from smart_reporting.management.runtime import ManagedConfigurationProvider
    from smart_reporting.management.scopes import ScopeService

    auth, repository, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    login = await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    scopes = ScopeService(auth)
    scope = ManagementScope("warehouse", "100")
    await scopes.register(login.raw_token, scope, "华东公司")
    profiles = ProfileService(scopes)
    profile = {"profileId": "base", "revision": "r1", "dimensions": []}
    draft = await profiles.save_draft(login.raw_token, scope, profile, 0)
    await profiles.publish(login.raw_token, scope, "base", draft["version"])
    vault = CredentialVault(f"key-a:{Fernet.generate_key().decode()}")
    sources = SourceService(scopes, vault)
    source_draft = await sources.create_draft(login.raw_token, scope, "operations", SourceDraftInput.model_validate({
        "name": "生产数仓", "type": "starrocks", "database": "warehouse",
        "dsn": "starrocks://reporter:secret@localhost:9030/warehouse",
        "reportingProfileVersionId": "base:1",
        "metadataVersionId": "operations:1",
    }))
    from smart_reporting.tests.management_fixtures import publish_dependencies
    await publish_dependencies(scopes, login.raw_token, scope)
    await sources.publish(login.raw_token, scope, "operations", source_draft["version"])
    async with repository.transaction() as connection:
        from sqlalchemy import update

        from smart_reporting.management.repository import tenant_settings
        await connection.execute(update(tenant_settings).where(
            tenant_settings.c.database == "warehouse", tenant_settings.c.company_id == "100"
        ).values(default_source_ids=["operations"]))
    provider = ManagedConfigurationProvider(scopes, vault)
    await provider.register_run("run-1", scope, user_id="7", thread_id="thread-1", entrypoint="cli")
    snapshot = await provider.freeze("run-1", scope)
    assert snapshot.source_versions == {"operations": 1}
    assert snapshot.profile.profile_id == "base"
    assert "secret" not in str(snapshot.public_state())
    assert snapshot.sources["operations"].connection_dsn().endswith("/warehouse")
