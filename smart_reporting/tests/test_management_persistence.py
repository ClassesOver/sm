from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = [pytest.mark.anyio, pytest.mark.integration]
OLD_PASSWORD = "old password with spaces"
NEW_PASSWORD = "new password with spaces"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def auth_context():
    from smart_reporting.management.auth import AdminAuthService
    from smart_reporting.management.repository import AdminRepository, metadata

    url = os.environ.get("REPORTING_MANAGEMENT_TEST_DB_URL")
    if not url:
        pytest.skip("需要独立 REPORTING_MANAGEMENT_TEST_DB_URL")
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS reporting_management"))
        await connection.run_sync(metadata.drop_all)
        await connection.run_sync(metadata.create_all)
    now = [datetime(2026, 11, 6, 0, 0, tzinfo=UTC)]
    repository = AdminRepository(engine)
    auth = AdminAuthService(repository, clock=lambda: now[0])
    try:
        yield auth, repository, now
    finally:
        await engine.dispose()


async def test_bootstrap_never_overwrites_account_and_stores_only_hashes(auth_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.repository import accounts, sessions

    auth, repo, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    with pytest.raises(ManagementError, match="management_admin_exists"):
        await auth.bootstrap(NEW_PASSWORD)
    login = await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    async with repo.engine.connect() as connection:
        account = (await connection.execute(select(accounts))).mappings().one()
        session = (await connection.execute(select(sessions))).mappings().one()
    assert account["password_hash"].startswith("$argon2id$")
    assert OLD_PASSWORD not in str(account)
    assert login.raw_token not in str(session)
    assert (await auth.authenticate(login.raw_token)).username == "admin"


async def test_password_change_and_cli_reset_invalidate_all_sessions(auth_context):
    from smart_reporting.management.models import AdminSessionInvalid, ManagementError

    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    first = await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    second = await auth.login("admin", OLD_PASSWORD, "127.0.0.2")
    await auth.change_password(first.raw_token, OLD_PASSWORD, NEW_PASSWORD)
    for token in (first.raw_token, second.raw_token):
        with pytest.raises(AdminSessionInvalid):
            await auth.authenticate(token)
    with pytest.raises(ManagementError, match="management_credentials_invalid"):
        await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    third = await auth.login("admin", NEW_PASSWORD, "127.0.0.1")
    await auth.reset_password(OLD_PASSWORD)
    with pytest.raises(AdminSessionInvalid):
        await auth.authenticate(third.raw_token)
    assert (await auth.login("admin", OLD_PASSWORD, "127.0.0.1")).raw_token


async def test_idle_and_absolute_expiry_and_logout(auth_context):
    from smart_reporting.management.models import AdminSessionInvalid

    auth, _, now = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    idle = await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    now[0] += timedelta(minutes=30)
    with pytest.raises(AdminSessionInvalid):
        await auth.authenticate(idle.raw_token)
    active = await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    for _ in range(23):
        now[0] += timedelta(minutes=20)
        await auth.authenticate(active.raw_token)
    now[0] += timedelta(minutes=20)
    with pytest.raises(AdminSessionInvalid):
        await auth.authenticate(active.raw_token)
    last = await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    await auth.logout(last.raw_token)
    await auth.logout(last.raw_token)
    with pytest.raises(AdminSessionInvalid):
        await auth.authenticate(last.raw_token)


async def test_account_lock_expires_and_reset_clears_it(auth_context):
    from smart_reporting.management.models import ManagementError

    auth, _, now = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    for _ in range(5):
        with pytest.raises(ManagementError, match="management_credentials_invalid"):
            await auth.login("admin", "incorrect password", "127.0.0.1")
    with pytest.raises(ManagementError, match="management_login_throttled"):
        await auth.login("admin", OLD_PASSWORD, "127.0.0.2")
    now[0] += timedelta(minutes=5)
    assert (await auth.login("admin", OLD_PASSWORD, "127.0.0.2")).raw_token
    for _ in range(5):
        with pytest.raises(ManagementError, match="management_credentials_invalid"):
            await auth.login("admin", "incorrect password", "127.0.0.1")
    await auth.reset_password(NEW_PASSWORD)
    assert (await auth.login("admin", NEW_PASSWORD, "127.0.0.1")).raw_token


async def test_old_password_verification_cannot_finish_login_after_reset(auth_context):
    from smart_reporting.management.models import ManagementError

    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    entered, release = asyncio.Event(), asyncio.Event()
    original = auth.verify_password

    async def delayed_verify(password, encoded):
        result = await original(password, encoded)
        entered.set()
        await release.wait()
        return result

    auth.verify_password = delayed_verify
    task = asyncio.create_task(auth.login("admin", OLD_PASSWORD, "127.0.0.1"))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        await auth.reset_password(NEW_PASSWORD)
    finally:
        release.set()
    with pytest.raises(ManagementError, match="management_credentials_invalid"):
        await task


async def test_restart_keeps_session_and_wrong_current_password_preserves_it(auth_context):
    from smart_reporting.management.auth import AdminAuthService
    from smart_reporting.management.models import ManagementError

    auth, repo, now = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    login = await auth.login("admin", OLD_PASSWORD, "127.0.0.1")
    restarted = AdminAuthService(repo, clock=lambda: now[0])
    with pytest.raises(ManagementError, match="management_credentials_invalid"):
        await restarted.change_password(login.raw_token, "wrong password", NEW_PASSWORD)
    assert (await restarted.authenticate(login.raw_token)).username == "admin"
