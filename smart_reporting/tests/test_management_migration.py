from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_management_migration_is_repeatable_and_preserves_account():
    url = os.environ.get("REPORTING_MANAGEMENT_TEST_DB_URL")
    if not url:
        pytest.skip("需要独立 REPORTING_MANAGEMENT_TEST_DB_URL")
    engine = create_async_engine(url)
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "AGENT_DB_URL": url}
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA IF EXISTS reporting_management CASCADE"))

        async def upgrade(target):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "alembic",
                "-c",
                "alembic-management.ini",
                "upgrade",
                target,
                cwd=root,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            assert process.returncode == 0, (stdout + stderr).decode()

        await upgrade("0005_catalog")
        from smart_reporting.management.auth import AdminAuthService
        from smart_reporting.management.repository import AdminRepository

        service = AdminAuthService(AdminRepository(engine))
        await service.bootstrap("migration test password")
        login = await service.login("admin", "migration test password", "127.0.0.1")
        assert (await service.authenticate(login.raw_token)).username == "admin"
        from smart_reporting.management.models import ManagementScope
        from smart_reporting.management.scopes import ScopeService

        scopes = ScopeService(service)
        await scopes.register(login.raw_token, ManagementScope("migration", "100"), "迁移组织")
        assert (await scopes.list(login.raw_token))["items"][0]["companyId"] == "100"
        from datetime import UTC, datetime

        from sqlalchemy import insert, select

        from smart_reporting.management.repository import (
            catalog_versions,
            runtime_snapshots,
            source_versions,
        )

        async with engine.begin() as connection:
            await connection.execute(
                insert(catalog_versions).values(
                    scope_id="old-scope",
                    source_id="old-source",
                    revision=1,
                    status="published",
                    catalog=[],
                    content_hash="a" * 64,
                    synced_at=datetime.now(UTC),
                )
            )
            await connection.execute(
                insert(source_versions).values(
                    scope_id="old-scope",
                    source_id="old-source",
                    revision=1,
                    name="旧源",
                    source_type="starrocks",
                    database="migration",
                    credential_ref="old-credential",
                    credential_revision=1,
                    content_hash="b" * 64,
                    published_at=datetime.now(UTC),
                )
            )
        async with engine.begin() as connection:
            await connection.execute(text("""INSERT INTO reporting_management.source_drafts
                (scope_id, source_id, version, name, source_type, database, credential_ref,
                 credential_revision, content_hash)
                VALUES ('old-scope', 'old-source', 1, '旧源', 'starrocks', 'migration',
                        'old-credential', 1, :digest)"""), {"digest": "b" * 64})
        await upgrade("0006_runtime_snapshots")
        references = {"runId": "old-run", "sources": [{"sourceId": "old-source", "revision": 1}]}
        async with engine.begin() as connection:
            await connection.execute(
                insert(runtime_snapshots).values(
                    scope_id="old-scope",
                    run_id="old-run",
                    user_id="7",
                    thread_id="t",
                    entrypoint="cli",
                    references=references,
                    reference_hash="c" * 64,
                    created_at=datetime.now(UTC),
                )
            )
        await upgrade("head")
        await upgrade("head")
        # 账号与会话在升级之前已存在；迁移不能重新初始化或丢弃旧业务版本。
        assert (await service.authenticate(login.raw_token)).username == "admin"
        assert (await scopes.list(login.raw_token))["items"][0]["companyId"] == "100"
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT version_num FROM reporting_management.alembic_version")
                )
                == "0009_semantic_assets"
            )
            from smart_reporting.management.repository import source_drafts, table_discoveries

            old_draft = (await connection.execute(select(source_drafts))).mappings().one()
            assert old_draft["requires_table_discovery"] == 0
            assert old_draft["content_hash"] == "b" * 64
            assert (await connection.execute(select(table_discoveries))).mappings().all() == []
            assert await connection.scalar(select(catalog_versions.c.source_id)) == "old-source"
            old_source = (await connection.execute(select(source_versions))).mappings().one()
            assert old_source["execution_parameters"] is None
            assert old_source["content_hash"] == "b" * 64
            old_run = (await connection.execute(select(runtime_snapshots))).mappings().one()
            assert old_run["references"] == references
            assert old_run["reference_hash"] == "c" * 64

            semantic_names = set((await connection.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname='reporting_management'"
            ))).scalars())
            assert {"metric_versions", "statistical_policy_versions", "business_document_revisions",
                    "business_ingestion_jobs", "business_evidence_releases", "report_bases",
                    "report_basis_receipts", "report_issue_reviews"}.issubset(semantic_names)
            assert await connection.scalar(text(
                "SELECT count(*) FROM pg_trigger WHERE tgname='immutable_metric_versions'"
            )) == 1

    finally:
        await engine.dispose()
