from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from sqlalchemy import insert, select

from .auth import AdminAuthService
from .models import INSTANCE_SCOPE, INSTANCE_SCOPE_ID, AdminSessionInvalid, ManagementActor, ManagementError, ManagementScope
from .repository import audit_events, tenant_settings


class ScopeService:
    def __init__(self, auth: AdminAuthService):
        self.auth = auth
        self.repository = auth.repository

    @staticmethod
    async def require_registered(connection, scope: ManagementScope):
        row = (await connection.execute(select(tenant_settings).where(
            tenant_settings.c.database == scope.database,
            tenant_settings.c.company_id == scope.company_id,
        ))).mappings().first()
        if row is None and scope == INSTANCE_SCOPE:
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            await connection.execute(pg_insert(tenant_settings).values(
                id=INSTANCE_SCOPE_ID, database=scope.database, company_id=scope.company_id,
                name="应用配置", version=1, default_source_ids=[], default_knowledge_base_ids=[],
            ).on_conflict_do_nothing(index_elements=[tenant_settings.c.id]))
            row = (await connection.execute(select(tenant_settings).where(tenant_settings.c.id == INSTANCE_SCOPE_ID))).mappings().one()
        if row is None:
            raise ManagementError('management_scope_not_found', '配置记录不存在。', 404)
        return row

    async def actor(self, raw_session: str, scope: ManagementScope) -> ManagementActor:
        async with self.repository.transaction() as connection:
            account = await self.repository.authenticate_in_transaction(
                connection, raw_session, self.auth.clock()
            )
            await self.require_registered(connection, scope)
            return ManagementActor(account.account_id, account.username, scope,
                                   account.auth_version, raw_session)

    @asynccontextmanager
    async def write_transaction(self, actor: ManagementActor):
        # 复用账号事务锁：退出/改密与资源写入有明确提交顺序。
        # 外部网络或解析工作必须在调用此短事务之前完成。
        async with self.repository.transaction() as connection:
            account = await self.repository.authenticate_in_transaction(
                connection, actor.raw_session, self.auth.clock()
            )
            if account.auth_version != actor.auth_version or account.account_id != actor.account_id:
                raise AdminSessionInvalid()
            await self.require_registered(connection, actor.scope)
            yield connection

    async def audit(self, connection, actor: ManagementActor, action: str, details: dict):
        await connection.execute(insert(audit_events).values(
            id=str(uuid4()), occurred_at=self.auth.clock(), actor=actor.username,
            action=action, details={**details, 'database': actor.scope.database,
                                    'companyId': actor.scope.company_id},
        ))

    async def register(self, raw_session: str, scope: ManagementScope, name: str) -> dict:
        if not name.strip() or len(name) > 200:
            raise ManagementError('management_input_invalid', '组织名称须为 1–200 个字符。', 422)
        async with self.repository.transaction() as connection:
            account = await self.repository.authenticate_in_transaction(
                connection, raw_session, self.auth.clock()
            )
            existing = await connection.scalar(select(tenant_settings.c.id).where(
                tenant_settings.c.database == scope.database,
                tenant_settings.c.company_id == scope.company_id,
            ))
            if existing:
                raise ManagementError('management_scope_exists', '该组织已登记。', 409)
            row = (await connection.execute(insert(tenant_settings).values(
                id=str(uuid4()), database=scope.database, company_id=scope.company_id,
                name=name.strip(), version=1, default_source_ids=[], default_knowledge_base_ids=[],
            ).returning(tenant_settings))).mappings().one()
            actor = ManagementActor(account.account_id, account.username, scope,
                                    account.auth_version, raw_session)
            await self.audit(connection, actor, 'scope_created', {'id': row['id']})
            return self.public(row)

    @staticmethod
    def public(row) -> dict:
        return {'id': row['id'], 'database': row['database'], 'companyId': row['company_id'],
                'name': row['name'], 'version': row['version'],
                'defaultSourceIds': row['default_source_ids'],
                'defaultKnowledgeBaseIds': row['default_knowledge_base_ids']}

    async def list(self, raw_session: str, limit: int = 50, after: str | None = None) -> dict:
        async with self.repository.transaction() as connection:
            await self.repository.authenticate_in_transaction(connection, raw_session, self.auth.clock())
            query = select(tenant_settings).order_by(tenant_settings.c.id)
            if after is not None:
                query = query.where(tenant_settings.c.id > after)
            rows = (await connection.execute(query.limit(limit + 1))).mappings().all()
            return {'items': [self.public(row) for row in rows[:limit]],
                    'nextCursor': rows[limit - 1]['id'] if len(rows) > limit else None}
