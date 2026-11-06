from __future__ import annotations

import hashlib
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import uuid4

from loguru import logger
from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    delete,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from .models import (
    AdminAccount,
    AdminLogin,
    AdminSessionInvalid,
    ManagementError,
    invalid_credentials,
)

metadata = MetaData(schema="reporting_management")
accounts = Table(
    "admin_account",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(32), nullable=False),
    Column("password_hash", String(512), nullable=False),
    Column("auth_version", Integer, nullable=False),
    Column("failed_count", Integer, nullable=False, server_default="0"),
    Column("locked_until", DateTime(timezone=True)),
    CheckConstraint("id = 1 AND username = 'admin'", name="singleton_admin"),
)
sessions = Table(
    "admin_sessions",
    metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("auth_version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False, index=True),
)
login_attempts = Table(
    "login_attempts",
    metadata,
    Column("address", String(128), primary_key=True),
    Column("window_start", DateTime(timezone=True), nullable=False),
    Column("failures", Integer, nullable=False),
)
audit_events = Table(
    "audit_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False, index=True),
    Column("actor", String(32), nullable=False),
    Column("action", String(64), nullable=False),
    Column("details", JSON, nullable=False),
)


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _account(row) -> AdminAccount:
    return AdminAccount(row["id"], row["username"], row["password_hash"], row["auth_version"])


class AdminRepository:
    def __init__(self, engine: AsyncEngine):
        if engine.dialect.name != "postgresql":
            raise ValueError("管理后台要求 PostgreSQL。")
        self.engine = engine

    @asynccontextmanager
    async def transaction(self):
        try:
            async with self.engine.begin() as connection:
                # 单例 admin：认证写入与改密使用同一短事务锁，哈希计算在锁外。
                await connection.execute(text("SELECT pg_advisory_xact_lock(73219061)"))
                yield connection
        except SQLAlchemyError as error:
            logger.warning("management_database_unavailable error_type={}", type(error).__name__)
            raise ManagementError("management_unavailable", "管理存储暂时不可用。", 503) from error

    async def audit(self, connection: AsyncConnection, action: str, now: datetime) -> None:
        await connection.execute(
            insert(audit_events).values(
                id=str(uuid4()),
                occurred_at=now,
                actor="admin",
                action=action,
                details={},
            )
        )

    async def bootstrap(self, password_hash: str, now: datetime) -> None:
        async with self.transaction() as connection:
            if (await connection.execute(select(accounts.c.id))).first():
                raise ManagementError("management_admin_exists", "admin 已初始化。", 409)
            await connection.execute(
                insert(accounts).values(
                    id=1,
                    username="admin",
                    password_hash=password_hash,
                    auth_version=1,
                    failed_count=0,
                )
            )
            await self.audit(connection, "admin_initialized", now)

    async def _row(self, connection):
        return (
            (await connection.execute(select(accounts).where(accounts.c.id == 1)))
            .mappings()
            .first()
        )

    async def _check_throttle(self, connection, row, address: str, now: datetime):
        attempt = (
            (
                await connection.execute(
                    select(login_attempts).where(login_attempts.c.address == address)
                )
            )
            .mappings()
            .first()
        )
        if (row and row["locked_until"] and row["locked_until"] > now) or (
            attempt
            and attempt["window_start"] > now - timedelta(minutes=5)
            and attempt["failures"] >= 20
        ):
            raise ManagementError("management_login_throttled", "登录尝试过多，请稍后重试。", 429)

    async def login_account(self, address: str, now: datetime) -> AdminAccount | None:
        async with self.transaction() as connection:
            row = await self._row(connection)
            await self._check_throttle(connection, row, address, now)
            return _account(row) if row else None

    async def finish_login(
        self,
        *,
        expected_version: int | None,
        valid: bool,
        address: str,
        now: datetime,
    ) -> AdminLogin:
        denied = False
        async with self.transaction() as connection:
            row = await self._row(connection)
            await self._check_throttle(connection, row, address, now)
            if not valid or row is None or row["auth_version"] != expected_version:
                denied = True
                # 计数必须提交；不能在事务内抛认证错误导致失败计数回滚。
                attempt = (
                    (
                        await connection.execute(
                            select(login_attempts).where(login_attempts.c.address == address)
                        )
                    )
                    .mappings()
                    .first()
                )
                await connection.execute(
                    delete(login_attempts).where(
                        login_attempts.c.window_start <= now - timedelta(minutes=5)
                    )
                )
                current = attempt and attempt["window_start"] > now - timedelta(minutes=5)
                if current:
                    await connection.execute(
                        update(login_attempts)
                        .where(login_attempts.c.address == address)
                        .values(failures=attempt["failures"] + 1)
                    )
                else:
                    await connection.execute(
                        insert(login_attempts).values(
                            address=address,
                            window_start=now,
                            failures=1,
                        )
                    )
                if row:
                    previous = row["failed_count"]
                    if row["locked_until"] and row["locked_until"] <= now:
                        previous = 0
                    count = previous + 1
                    await connection.execute(
                        update(accounts)
                        .where(accounts.c.id == 1)
                        .values(
                            failed_count=count,
                            locked_until=now + timedelta(minutes=5) if count >= 5 else None,
                        )
                    )
                await self.audit(connection, "login_failed", now)
            else:
                raw = secrets.token_urlsafe(32)
                expiry = now + timedelta(hours=8)
                await connection.execute(delete(sessions).where(sessions.c.expires_at <= now))
                await connection.execute(
                    insert(sessions).values(
                        token_hash=token_hash(raw),
                        auth_version=row["auth_version"],
                        created_at=now,
                        last_seen_at=now,
                        expires_at=expiry,
                    )
                )
                await connection.execute(
                    update(accounts)
                    .where(accounts.c.id == 1)
                    .values(
                        failed_count=0,
                        locked_until=None,
                    )
                )
                await self.audit(connection, "login_succeeded", now)
        if denied:
            raise invalid_credentials()
        return AdminLogin(raw, expiry)

    async def authenticate_in_transaction(
        self, connection, raw: str, now: datetime
    ) -> AdminAccount:
        row = await self._row(connection)
        session = (
            (
                await connection.execute(
                    select(sessions).where(sessions.c.token_hash == token_hash(raw))
                )
            )
            .mappings()
            .first()
        )
        if (
            not row
            or not session
            or session["auth_version"] != row["auth_version"]
            or session["expires_at"] <= now
            or session["last_seen_at"] <= now - timedelta(minutes=30)
        ):
            raise AdminSessionInvalid()
        await connection.execute(
            update(sessions)
            .where(sessions.c.token_hash == token_hash(raw))
            .values(last_seen_at=now)
        )
        return _account(row)

    async def authenticate(self, raw: str, now: datetime) -> AdminAccount:
        if not raw or len(raw) > 128:
            raise AdminSessionInvalid()
        async with self.transaction() as connection:
            return await self.authenticate_in_transaction(connection, raw, now)

    async def logout(self, raw: str, now: datetime) -> None:
        async with self.transaction() as connection:
            result = await connection.execute(
                delete(sessions).where(sessions.c.token_hash == token_hash(raw))
            )
            if result.rowcount:
                await self.audit(connection, "logout", now)

    async def replace_password(
        self,
        encoded: str,
        now: datetime,
        *,
        raw: str | None = None,
        expected_version: int | None = None,
    ) -> None:
        async with self.transaction() as connection:
            row = await self._row(connection)
            if row is None:
                raise ManagementError("management_not_initialized", "请先初始化 admin。", 409)
            if raw is not None:
                current = await self.authenticate_in_transaction(connection, raw, now)
                if current.auth_version != expected_version:
                    raise AdminSessionInvalid()
            await connection.execute(
                update(accounts)
                .where(accounts.c.id == 1)
                .values(
                    password_hash=encoded,
                    auth_version=row["auth_version"] + 1,
                    failed_count=0,
                    locked_until=None,
                )
            )
            await connection.execute(delete(sessions))
            await connection.execute(delete(login_attempts))
            await self.audit(connection, "password_changed" if raw else "password_reset", now)
