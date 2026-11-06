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
        for _ in range(2):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "alembic",
                "-c",
                "alembic-management.ini",
                "upgrade",
                "head",
                cwd=root,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            assert process.returncode == 0, (stdout + stderr).decode()
        async with engine.connect() as connection:
            revision = await connection.scalar(
                text("SELECT version_num FROM reporting_management.alembic_version")
            )
            assert revision == "0004_profiles"
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
    finally:
        await engine.dispose()
