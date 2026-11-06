from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from smart_reporting.tests.test_management_catalog_sync import metadata_client as metadata_client
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def test_import_keeps_execution_parameters_across_edits_and_pinned_versions(
    auth_context, tmp_path, metadata_client, monkeypatch
):
    import json

    from cryptography.fernet import Fernet

    from smart_reporting.management.data_sources.models import SourceDraftInput
    from smart_reporting.management.data_sources.secrets import CredentialVault
    from smart_reporting.management.data_sources.service import SourceService
    from smart_reporting.management.importer import ConfigurationImporter
    from smart_reporting.management.models import ManagementScope
    from smart_reporting.management.runtime import ManagedConfigurationProvider
    from smart_reporting.management.scopes import ScopeService
    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
    from smart_reporting.tests.management_fixtures import physical_catalog

    limits = {
        "statementTimeoutSeconds": 9,
        "maxRows": 100,
        "maxBytes": 2048,
        "exactDistinctMaxRows": 50,
        "statisticsColumnBatchSize": 3,
        "topValuesMaxColumns": 4,
        "topValuesLimit": 5,
        "profileConcurrency": 1,
        "queryConcurrency": 1,
    }
    source = {
        "id": "operations",
        "type": "starrocks",
        "name": " 数仓 ",
        "dsnEnv": "REPORTING_DSN",
        "database": "WAREHOUSE",
        "reportingProfile": "base",
        **limits,
    }
    config_path = tmp_path / "report-data-sources.json"
    document = {"version": "1", "defaultSourceIds": ["operations"], "sources": [source]}
    config_path.write_text(json.dumps(document))
    (tmp_path / "reporting_profiles").mkdir()
    (tmp_path / "reporting_profiles" / "base.json").write_text(
        '{"version":"1","profileId":"base","revision":"r1","dimensions":[]}'
    )
    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    token = (await auth.login("admin", OLD_PASSWORD, "127.0.0.1")).raw_token
    scopes = ScopeService(auth)
    scope = ManagementScope("warehouse", "100")
    await scopes.register(token, scope, "公司")
    vault = CredentialVault(f"test:{Fernet.generate_key().decode()}")
    importer = ConfigurationImporter(scopes, vault, metadata_client=metadata_client)
    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", lambda adapter: physical_catalog())
    environ = {"REPORTING_DSN": "starrocks://reporter:secret@localhost:9030/warehouse"}
    assert (await importer.import_configuration(token, scope, tmp_path, False, environ))["changed"]
    provider = ManagedConfigurationProvider(scopes, vault)
    await provider.register_run("old", scope, user_id="7", thread_id="old", entrypoint="cli")
    old = await provider.freeze("old", scope)
    assert old.sources["operations"].limits.public_dict() == limits
    assert not (await importer.import_configuration(token, scope, tmp_path, False, environ))[
        "changed"
    ]
    source["maxRows"] = 200
    config_path.write_text(json.dumps(document))
    assert (await importer.import_configuration(token, scope, tmp_path, False, environ))["changed"]
    await provider.register_run("new", scope, user_id="7", thread_id="new", entrypoint="cli")
    new = await provider.freeze("new", scope)
    assert new.source_versions == {"operations": 2}
    assert new.sources["operations"].limits.public_dict() == {**limits, "maxRows": 200}
    assert new.source_hashes != old.source_hashes
    restored = await ManagedConfigurationProvider(scopes, vault).load_pinned(scope, old.references)
    assert restored.sources["operations"].limits.public_dict() == limits
    # 管理页面只改名称时也必须保留导入的内部参数，不开放限额写入字段。
    service = SourceService(scopes, vault)
    payload = SourceDraftInput.model_validate(
        {
            "name": "改名",
            "database": "warehouse",
            "dsn": environ["REPORTING_DSN"],
            "reportingProfileVersionId": "base:1",
            "metadataVersionId": "operations:1",
        }
    )
    draft = await service.save_draft(token, scope, "operations", payload, 2)
    await service.publish(token, scope, "operations", draft["version"])
    await provider.register_run("edit", scope, user_id="7", thread_id="edit", entrypoint="cli")
    assert (await provider.freeze("edit", scope)).sources["operations"].limits.public_dict() == {
        **limits,
        "maxRows": 200,
    }


async def test_config_import_dry_run_and_idempotent_commit(
    auth_context, tmp_path: Path, metadata_client, monkeypatch
):
    from cryptography.fernet import Fernet

    from smart_reporting.management.data_sources.secrets import CredentialVault
    from smart_reporting.management.importer import ConfigurationImporter
    from smart_reporting.management.models import ManagementScope
    from smart_reporting.management.scopes import ScopeService

    (tmp_path / "report-data-sources.json").write_text(
        '{"version":"1","defaultSourceIds":["operations"],"sources":[{"id":"operations","type":"starrocks","name":"生产数仓","dsnEnv":"REPORTING_DSN","database":"warehouse","reportingProfile":"base","statementTimeoutSeconds":9}]}'
    )
    (tmp_path / "reporting_profiles").mkdir()
    (tmp_path / "reporting_profiles" / "base.json").write_text(
        '{"version":"1","profileId":"base","revision":"r1","dimensions":[]}'
    )
    auth, repository, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    login = await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    scopes = ScopeService(auth)
    scope = ManagementScope("warehouse", "100")
    await scopes.register(login.raw_token, scope, "华东公司")
    importer = ConfigurationImporter(
        scopes,
        CredentialVault(f"key-a:{Fernet.generate_key().decode()}"),
        metadata_client=metadata_client,
    )
    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
    from smart_reporting.tests.management_fixtures import physical_catalog

    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", lambda adapter: physical_catalog())
    environ = {"REPORTING_DSN": "starrocks://reporter:secret@localhost:9030/warehouse"}
    preview = await importer.import_configuration(login.raw_token, scope, tmp_path, True, environ)
    assert preview["dryRun"] is True
    assert preview["createdSources"] == 1
    assert preview["credentials"] == "redacted"
    committed = await importer.import_configuration(
        login.raw_token, scope, tmp_path, False, environ
    )
    assert committed["changed"] is True
    repeated = await importer.import_configuration(login.raw_token, scope, tmp_path, False, environ)
    assert repeated["changed"] is False
    from smart_reporting.management.repository import (
        catalog_versions,
        profile_versions,
        source_versions,
        tenant_settings,
    )

    async with repository.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(source_versions)) == 1
        published = (await connection.execute(select(source_versions))).mappings().one()
        assert published["profile_version_id"] == "base:1"
        assert published["metadata_version_id"] == "operations:1"
        assert await connection.scalar(select(tenant_settings.c.default_source_ids)) == [
            "operations"
        ]
        assert await connection.scalar(select(func.count()).select_from(profile_versions)) == 1
        assert await connection.scalar(select(func.count()).select_from(catalog_versions)) == 1
    # 同名资源的正文与凭据变化必须形成新发布版本；旧配置保留可读。
    (tmp_path / "reporting_profiles" / "base.json").write_text(
        '{"version":"1","profileId":"base","revision":"r2","dimensions":[]}'
    )
    environ["REPORTING_DSN"] = "starrocks://reporter:new-secret@localhost:9030/warehouse"
    changed = await importer.import_configuration(login.raw_token, scope, tmp_path, False, environ)
    assert changed["changed"] is True
    async with repository.engine.connect() as connection:
        versions = (
            (await connection.execute(select(source_versions).order_by(source_versions.c.revision)))
            .mappings()
            .all()
        )
        assert [row["revision"] for row in versions] == [1, 2]
        assert [row["profile_version_id"] for row in versions] == ["base:1", "base:2"]
        assert [row["credential_revision"] for row in versions] == [1, 2]
    from smart_reporting.management.data_sources.service import SourceService

    service = SourceService(scopes, importer.vault)
    assert "reporter:secret@" in await service.resolve_credentials(scope, "operations", 1)
    assert "reporter:new-secret@" in await service.resolve_credentials(scope, "operations", 2)


async def test_import_preflight_and_database_faults_do_not_leave_partial_publication(
    auth_context, tmp_path, metadata_client, monkeypatch
):
    import json

    from cryptography.fernet import Fernet

    from smart_reporting.management.data_sources.secrets import CredentialVault
    from smart_reporting.management.importer import ConfigurationImporter
    from smart_reporting.management.models import (
        AdminSessionInvalid,
        ManagementError,
        ManagementScope,
    )
    from smart_reporting.management.repository import (
        catalog_versions,
        profile_versions,
        source_versions,
        tenant_settings,
    )
    from smart_reporting.management.scopes import ScopeService
    from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
    from smart_reporting.tests.management_fixtures import physical_catalog

    (tmp_path / "report-data-sources.json").write_text(
        json.dumps(
            {
                "version": "1",
                "defaultSourceIds": ["operations"],
                "sources": [
                    {
                        "id": "operations",
                        "type": "starrocks",
                        "name": "经营数仓",
                        "dsnEnv": "REPORTING_DSN",
                        "database": "warehouse",
                        "reportingProfile": "base",
                    }
                ],
            }
        )
    )
    (tmp_path / "reporting_profiles").mkdir()
    (tmp_path / "reporting_profiles" / "base.json").write_text(
        '{"version":"1","profileId":"base","revision":"r1","dimensions":[]}'
    )
    auth, repo, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    login = await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    scopes = ScopeService(auth)
    scope = ManagementScope("warehouse", "100")
    await scopes.register(login.raw_token, scope, "公司")
    importer = ConfigurationImporter(
        scopes,
        CredentialVault(f"test:{Fernet.generate_key().decode()}"),
        metadata_client=metadata_client,
    )
    environ = {"REPORTING_DSN": "starrocks://reporter:secret@localhost:9030/warehouse"}
    with pytest.raises(AdminSessionInvalid):
        await importer.import_configuration("invalid-session", scope, tmp_path, True, environ)

    def fail(adapter):
        raise RuntimeError("warehouse unavailable")

    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", fail)
    with pytest.raises(ManagementError, match="management_catalog_sync_failed"):
        await importer.import_configuration(login.raw_token, scope, tmp_path, False, environ)
    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", lambda adapter: physical_catalog())

    async def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(scopes, "audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await importer.import_configuration(login.raw_token, scope, tmp_path, False, environ)
    async with repo.engine.connect() as connection:
        for table in (source_versions, profile_versions, catalog_versions):
            assert await connection.scalar(select(func.count()).select_from(table)) == 0
        assert await connection.scalar(select(tenant_settings.c.default_source_ids)) == []
