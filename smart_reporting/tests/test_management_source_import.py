"""新连接文件导入不读取、转换或发布旧业务Profile。"""

from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select, update

from smart_reporting.management.data_sources.models import SourceDraftInput
from smart_reporting.management.data_sources.secrets import CredentialVault
from smart_reporting.management.data_sources.service import SourceService
from smart_reporting.management.importer import ConfigurationImporter
from smart_reporting.management.models import AdminSessionInvalid, ManagementError, ManagementScope
from smart_reporting.management.repository import (
    catalog_versions,
    profile_versions,
    source_drafts,
    source_versions,
    tenant_settings,
)
from smart_reporting.management.scopes import ScopeService
from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
from smart_reporting.tests.management_fixtures import physical_catalog
from smart_reporting.tests.test_management_catalog_sync import metadata_client as metadata_client
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def import_context(auth_context, tmp_path, metadata_client, monkeypatch):
    auth, repository, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    token = (await auth.login("admin", OLD_PASSWORD, "127.0.0.1")).raw_token
    scopes = ScopeService(auth)
    scope = ManagementScope("warehouse", "100")
    await scopes.register(token, scope, "公司")
    vault = CredentialVault(f"test:{Fernet.generate_key().decode()}")
    importer = ConfigurationImporter(scopes, vault, metadata_client=metadata_client)
    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", lambda adapter: physical_catalog())
    source = {"id": "operations", "type": "starrocks", "name": "数仓",
        "dsnEnv": "REPORTING_DSN", "database": "warehouse", "maxRows": 100,
        "statementTimeoutSeconds": 9}
    document = {"version": "1", "defaultSourceIds": ["operations"], "sources": [source]}
    path = tmp_path / "report-data-sources.json"
    path.write_text(json.dumps(document))
    # 留存旧文件不构成新规则来源；无加载、继承或转换。
    (tmp_path / "reporting_profiles").mkdir()
    (tmp_path / "reporting_profiles" / "base.json").write_text("invalid archived document")
    return dict(repository=repository, scopes=scopes, scope=scope, token=token, vault=vault,
        importer=importer, directory=tmp_path, path=path, document=document, source=source,
        environ={"REPORTING_DSN": "starrocks://reporter:synthetic-only@localhost:9030/warehouse"})


async def _import(ctx, dry_run=False):
    return await ctx["importer"].import_configuration(ctx["token"], ctx["scope"],
        ctx["directory"], dry_run, ctx["environ"])


async def test_new_config_import_dry_run_and_idempotent_commit_without_profiles(import_context):
    ctx = import_context
    preview = await _import(ctx, True)
    assert preview["dryRun"] and preview["createdSources"] == 1
    assert preview["credentials"] == "redacted"
    async with ctx["repository"].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(source_versions)) == 0
    assert (await _import(ctx))["changed"]
    assert not (await _import(ctx))["changed"]
    async with ctx["repository"].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(profile_versions)) == 0
        assert await connection.scalar(select(func.count()).select_from(catalog_versions)) == 1
        row = (await connection.execute(select(source_versions))).mappings().one()
        assert row["profile_version_id"] is None and row["metadata_version_id"] == "operations:1"
        assert await connection.scalar(select(tenant_settings.c.default_source_ids)) == ["operations"]
    service = SourceService(ctx["scopes"], ctx["vault"])
    detail = await service.detail(ctx["token"], ctx["scope"], "operations")
    assert "reportingProfileVersionId" not in detail["published"]
    assert not (await service.release_check(ctx["token"], ctx["scope"], "operations", 1))["issues"]


async def test_import_preserves_exact_limits_and_credentials_across_new_versions_and_edits(import_context):
    ctx = import_context
    await _import(ctx)
    ctx["source"]["maxRows"] = 200
    ctx["path"].write_text(json.dumps(ctx["document"]))
    ctx["environ"]["REPORTING_DSN"] = "starrocks://reporter:replacement@localhost:9030/warehouse"
    assert (await _import(ctx))["changed"]
    service = SourceService(ctx["scopes"], ctx["vault"])
    detail = await service.detail(ctx["token"], ctx["scope"], "operations")
    payload = SourceDraftInput(name="改名", database="warehouse",
        metadataVersionId=detail["draft"]["metadata_version_id"])
    draft = await service.save_draft(ctx["token"], ctx["scope"], "operations", payload, 2)
    await service.publish(ctx["token"], ctx["scope"], "operations", draft["version"])
    async with ctx["repository"].engine.connect() as connection:
        rows = (await connection.execute(select(source_versions).order_by(source_versions.c.revision))).mappings().all()
        assert [row["execution_parameters"]["maxRows"] for row in rows] == [100, 200, 200]
        assert [row["credential_revision"] for row in rows] == [1, 2, 2]
        assert all(row["profile_version_id"] is None for row in rows)
        catalogs = (await connection.execute(select(catalog_versions.c.catalog))).scalars().all()
        assert len(catalogs) == 2
        assert {body["connectionIdentity"]["credentialRevision"] for body in catalogs} == {1, 2}
    assert "reporter:synthetic-only@" in await service.resolve_credentials(ctx["scope"], "operations", 1)
    assert "reporter:replacement@" in await service.resolve_credentials(ctx["scope"], "operations", 3)


async def test_import_rejects_old_profile_fields_before_warehouse_io(import_context, monkeypatch):
    ctx = import_context
    def forbidden(adapter):
        pytest.fail("旧契约不得触发数仓读取")
    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", forbidden)
    for value in (None, "base"):
        ctx["source"]["reportingProfile"] = value
        ctx["path"].write_text(json.dumps(ctx["document"]))
        with pytest.raises(ManagementError) as error:
            await _import(ctx)
        assert error.value.code == "management_import_invalid" and error.value.status == 422
    async with ctx["repository"].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(source_versions)) == 0


async def test_import_faults_do_not_leave_partial_publication(import_context, monkeypatch):
    ctx = import_context
    with pytest.raises(AdminSessionInvalid):
        await ctx["importer"].import_configuration("invalid", ctx["scope"], ctx["directory"], True, ctx["environ"])
    def fail(adapter):
        raise RuntimeError("warehouse unavailable")
    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", fail)
    with pytest.raises(ManagementError, match="management_catalog_sync_failed"):
        await _import(ctx)
    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", lambda adapter: physical_catalog())
    async def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr(ctx["scopes"], "audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await _import(ctx)
    async with ctx["repository"].engine.connect() as connection:
        for table in (source_versions, profile_versions, catalog_versions):
            assert await connection.scalar(select(func.count()).select_from(table)) == 0
        assert await connection.scalar(select(tenant_settings.c.default_source_ids)) == []


async def test_import_does_not_convert_archived_source_binding(import_context):
    ctx = import_context
    await _import(ctx)
    async with ctx["repository"].transaction() as connection:
        await connection.execute(update(source_drafts).values(profile_version_id="base:1"))
    with pytest.raises(ManagementError) as error:
        await _import(ctx)
    assert error.value.code == "management_source_contract_retired"
    async with ctx["repository"].engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(source_versions)) == 1
        assert await connection.scalar(select(source_drafts.c.profile_version_id)) == "base:1"
