from __future__ import annotations

import pytest

from smart_reporting.tests.test_management_persistence import OLD_PASSWORD, auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def test_catalog_versions_publish_and_failed_sync_keeps_previous(auth_context):
    from smart_reporting.management.data_sources.models import SourceDraftInput
    from smart_reporting.management.data_sources.secrets import CredentialVault
    from smart_reporting.management.data_sources.service import SourceService
    from smart_reporting.management.catalog import CatalogService
    from smart_reporting.management.models import ManagementScope
    from smart_reporting.management.scopes import ScopeService
    from smart_reporting.reporting.data_source.models import CatalogColumn, CatalogTable
    from cryptography.fernet import Fernet

    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    login = await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    scopes = ScopeService(auth)
    scope = ManagementScope("warehouse", "100")
    await scopes.register(login.raw_token, scope, "华东公司")
    source = SourceService(scopes, CredentialVault(f"key-a:{Fernet.generate_key().decode()}"))
    await source.create_draft(login.raw_token, scope, "operations", SourceDraftInput.model_validate({
        "name": "生产数仓", "type": "starrocks", "database": "warehouse",
        "dsn": "starrocks://reporter:secret@localhost:9030/warehouse",
    }))
    catalogs = CatalogService(scopes)
    table = CatalogTable("operations", "warehouse", "orders", (
        CatalogColumn("id", "BIGINT", False, "主键"),
    ), "订单")
    preview = await catalogs.sync(login.raw_token, scope, "operations", 1, (table,))
    assert preview["changed"] is True
    published = await catalogs.publish(login.raw_token, scope, "operations", preview["revision"])
    assert published["revision"] == 1
    assert published["contentHash"] == preview["contentHash"]

    with pytest.raises(Exception, match="management_catalog_sync_failed"):
        await catalogs.sync(login.raw_token, scope, "operations", 1, None)
    current = await catalogs.current(login.raw_token, scope, "operations")
    assert current["revision"] == 1
    assert current["status"] == "published"

