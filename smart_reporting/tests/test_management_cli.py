from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from smart_reporting.management import cli
from smart_reporting.management.repository import sessions, source_versions
from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
from smart_reporting.tests.management_fixtures import physical_catalog
from smart_reporting.tests.test_management_catalog_sync import metadata_client as metadata_client
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


async def test_cli_import_authenticates_previews_publishes_and_revokes_own_session(
    auth_context, metadata_client, tmp_path, monkeypatch
):
    auth, repo, now = auth_context
    now[0] = datetime.now(UTC)
    await auth.bootstrap(OLD_PASSWORD)
    await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    (tmp_path / "report-data-sources.json").write_text(
        '{"version":"1","defaultSourceIds":["operations"],"sources":[{"id":"operations","type":"starrocks","name":"经营数仓","dsnEnv":"REPORTING_DSN","database":"warehouse"}]}'
    )
    monkeypatch.setenv("AGENT_DB_URL", os.environ["REPORTING_MANAGEMENT_TEST_DB_URL"])
    monkeypatch.setenv("AGENT_MANAGEMENT_CREDENTIAL_KEYS", f"test:{Fernet.generate_key().decode()}")
    monkeypatch.setenv("AGENT_REPORT_METADATA_URL", "https://metadata.test")
    monkeypatch.setenv(
        "REPORTING_DSN", "starrocks://reporter:private-secret@localhost:9030/warehouse"
    )
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: OLD_PASSWORD)
    monkeypatch.setattr(StarRocksDataSourceAdapter, "_catalog", lambda adapter: physical_catalog())
    # 保留 CLI 的真实 metadata 构造调用与导入服务；仅替换远端 HTTP transport。
    # 使用 factory 支持受控 HTTP，同时仍校验 CLI 读取了部署配置。
    original = metadata_client.__class__.__init__

    def configured(self, base_url, **kwargs):
        assert base_url == "https://metadata.test"
        original(self, base_url, client_factory=metadata_client.client_factory, **kwargs)

    monkeypatch.setattr(metadata_client.__class__, "__init__", configured)
    preview = await cli.run("import-config", directory=tmp_path, dry_run=True)
    assert preview["dryRun"] is True
    async with repo.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(source_versions)) == 0
    committed = await cli.run("import-config", directory=tmp_path, dry_run=False)
    assert committed["createdSources"] == 1
    assert "private-secret" not in str(committed)
    async with repo.engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(source_versions)) == 1
        # 原页面会话保留；两次 CLI 会话都已撤销。
        assert await connection.scalar(select(func.count()).select_from(sessions)) == 1
