"""Adapt the existing data source services to verified Office administrators."""
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import insert, select

from ..management.models import AdminAccount, ManagementActor, ManagementScope
from .repository import Identity, OfficeError, _token_hash
from .schema import companies, sessions


class OfficeSourceScopes:
    def __init__(self, office):
        self.office = office
        self.repository = self
        self.auth = self

    @staticmethod
    def clock():
        return datetime.now(UTC)

    @asynccontextmanager
    async def transaction(self):
        async with self.office.engine.begin() as connection:
            yield connection

    async def identity(self, connection, raw):
        row = (await connection.execute(select(
            sessions, companies.c.database, companies.c.company.label("company_id"),
        ).join(companies, companies.c.id == sessions.c.company).where(
            sessions.c.token == _token_hash(raw),
            sessions.c.expires > int(self.office.clock()),
        ))).mappings().first()
        if row is None:
            raise OfficeError("office_session_invalid", "Office 会话已失效。", 401)
        identity = Identity(row["database"], row["company_id"], row["user"],
                            row["version"], row["token"])
        await connection.execute(select(companies).where(
            companies.c.id == identity.tenant).with_for_update())
        account = await self.office._user(connection, identity, admin=True)
        return identity, account

    async def authenticate_in_transaction(self, connection, raw, now):
        identity, account = await self.identity(connection, raw)
        return AdminAccount(identity.user, identity.user, "", account["version"])

    async def authenticate(self, raw):
        async with self.transaction() as connection:
            return await self.authenticate_in_transaction(connection, raw, self.clock())

    async def actor(self, raw, scope):
        async with self.transaction() as connection:
            identity, account = await self.identity(connection, raw)
            if scope != ManagementScope(identity.database, identity.company):
                raise OfficeError("office_source_scope_denied", "数据源与当前公司不一致。")
            return ManagementActor(identity.user, identity.user, scope, account["version"], raw)

    @asynccontextmanager
    async def write_transaction(self, actor):
        async with self.transaction() as connection:
            identity, account = await self.identity(connection, actor.raw_session)
            if (actor.auth_version != account["version"]
                    or actor.scope != ManagementScope(identity.database, identity.company)):
                raise OfficeError("office_source_scope_denied", "数据源权限已变化。")
            yield connection

    async def audit(self, connection, actor, action, details):
        identity, _ = await self.identity(connection, actor.raw_session)
        if actor.scope != ManagementScope(identity.database, identity.company):
            raise OfficeError("office_source_scope_denied", "数据源与当前公司不一致。")
        await self.office._audit(connection, identity, action, **details)

    async def ensure_registered(self, identity):
        async with self.office.transaction(identity) as connection:
            await self.office._user(connection, identity, admin=True)
            await self.scope_id(connection, identity, create=True)
        return ManagementScope(identity.database, identity.company)

    @staticmethod
    async def scope_id(connection, identity, *, create=False):
        from ..management.repository import tenant_settings

        scope_id = await connection.scalar(select(tenant_settings.c.id).where(
            tenant_settings.c.database == identity.database,
            tenant_settings.c.company_id == identity.company))
        if scope_id is None and create:
            scope_id = str(uuid4())
            await connection.execute(insert(tenant_settings).values(
                id=scope_id, database=identity.database, company_id=identity.company,
                name=identity.company, version=1,
                default_source_ids=[], default_knowledge_base_ids=[],
            ))
        return scope_id
