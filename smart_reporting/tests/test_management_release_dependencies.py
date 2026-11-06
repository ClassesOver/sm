from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select, update

from smart_reporting.management.catalog import CatalogService
from smart_reporting.management.data_sources.models import SourceDraftInput
from smart_reporting.management.data_sources.secrets import CredentialVault
from smart_reporting.management.data_sources.service import SourceService
from smart_reporting.management.models import ManagementError, ManagementScope
from smart_reporting.management.repository import (
    audit_events,
    catalog_versions,
    source_versions,
    sources,
)
from smart_reporting.management.scopes import ScopeService
from smart_reporting.tests.management_fixtures import (
    business_metadata,
    physical_catalog,
    publish_dependencies,
)
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
async def release_context(auth_context):
    auth, repository, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    login = await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    scopes = ScopeService(auth)
    scope = ManagementScope("warehouse", "100")
    await scopes.register(login.raw_token, scope, "公司一")
    vault = CredentialVault(f"test:{Fernet.generate_key().decode()}")
    service = SourceService(scopes, vault)
    payload = SourceDraftInput.model_validate(
        {
            "name": "经营数仓",
            "database": "warehouse",
            "dsn": "starrocks://reporter:test-secret@localhost:9030/warehouse",
            "reportingProfileVersionId": "base:1",
            "metadataVersionId": "operations:1",
        }
    )
    await service.create_draft(login.raw_token, scope, "operations", payload)
    return service, scopes, repository, login.raw_token, scope


async def test_source_publication_rejects_missing_dependencies_without_partial_release(
    release_context,
):
    service, _, repo, token, scope = release_context
    with pytest.raises(ManagementError, match="management_source_dependencies_invalid"):
        await service.publish(token, scope, "operations", 1)
    async with repo.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(source_versions)) == 0
        assert await connection.scalar(select(sources.c.published_revision)) is None
        assert (
            await connection.scalar(
                select(func.count())
                .select_from(audit_events)
                .where(audit_events.c.action == "source_version_published")
            )
            == 0
        )


async def test_publication_requires_published_complete_catalog_in_same_scope(release_context):
    service, scopes, repo, token, scope = release_context
    await publish_dependencies(scopes, token, scope)
    async with repo.transaction() as connection:
        await connection.execute(update(catalog_versions).values(status="draft"))
    with pytest.raises(ManagementError, match="management_source_dependencies_invalid"):
        await service.publish(token, scope, "operations", 1)
    async with repo.transaction() as connection:
        await connection.execute(update(catalog_versions).values(status="published"))
    published = await service.publish(token, scope, "operations", 1)
    assert published["revision"] == 1
    assert published["metadataVersionId"] == "operations:1"
    retried = await service.publish(token, scope, "operations", 1)
    assert retried["revision"] == 1
    async with repo.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(source_versions)) == 1
        assert (
            await connection.scalar(
                select(func.count())
                .select_from(audit_events)
                .where(audit_events.c.action == "source_version_published")
            )
            == 1
        )
    foreign = ManagementScope("warehouse", "200")
    await scopes.register(token, foreign, "公司二")
    payload = SourceDraftInput.model_validate(
        {
            "name": "另一公司",
            "database": "warehouse",
            "dsn": "starrocks://reporter:other-secret@localhost:9030/warehouse",
            "reportingProfileVersionId": "base:1",
            "metadataVersionId": "operations:1",
        }
    )
    await service.create_draft(token, foreign, "operations", payload)
    with pytest.raises(ManagementError, match="management_source_dependencies_invalid"):
        await service.publish(token, foreign, "operations", 1)


async def test_catalog_preserves_business_terms_and_audit_and_rejects_legacy_publication(
    release_context,
):
    _, scopes, repo, token, scope = release_context
    catalogs = CatalogService(scopes)
    synced = await catalogs.sync(
        token, scope, "operations", 1, physical_catalog(), metadata=business_metadata()
    )
    await catalogs.publish(token, scope, "operations", synced["revision"])
    current = await catalogs.current(token, scope, "operations")
    assert current["metadata"]["terms"][0]["name"] == "收入"
    assert current["metadata"]["measureSemantics"][0]["unit"] == "元"
    assert current["sourceDraftVersion"] == 1
    async with repo.engine.connect() as connection:
        actions = (await connection.scalars(select(audit_events.c.action))).all()
    assert "catalog_synced" in actions
    assert "catalog_published" in actions
    async with repo.transaction() as connection:
        await connection.execute(update(catalog_versions).values(catalog=[]))
    with pytest.raises(ManagementError, match="management_catalog_incomplete"):
        await catalogs.publish(token, scope, "operations", synced["revision"])


async def test_catalog_metadata_scope_and_structure_are_checked_before_storage(release_context):
    _, scopes, repo, token, scope = release_context
    catalogs = CatalogService(scopes)
    with pytest.raises(ManagementError, match="management_catalog_invalid"):
        await catalogs.sync(
            token, scope, "operations", 1, physical_catalog(), metadata=business_metadata("foreign")
        )
    async with repo.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(catalog_versions)) == 0
