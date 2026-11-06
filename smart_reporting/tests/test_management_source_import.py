from __future__ import annotations

from pathlib import Path

import pytest

from smart_reporting.tests.test_management_persistence import OLD_PASSWORD, auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def test_config_import_dry_run_and_idempotent_commit(auth_context, tmp_path: Path):
    from cryptography.fernet import Fernet
    from smart_reporting.management.importer import ConfigurationImporter
    from smart_reporting.management.data_sources.secrets import CredentialVault
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
    )
    environ = {"REPORTING_DSN": "starrocks://reporter:secret@localhost:9030/warehouse"}
    preview = await importer.import_configuration(login.raw_token, scope, tmp_path, True, environ)
    assert preview["dryRun"] is True
    assert preview["createdSources"] == 1
    assert preview["credentials"] == "redacted"
    committed = await importer.import_configuration(login.raw_token, scope, tmp_path, False, environ)
    assert committed["changed"] is True
    repeated = await importer.import_configuration(login.raw_token, scope, tmp_path, False, environ)
    assert repeated["changed"] is False

