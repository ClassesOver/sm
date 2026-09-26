from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    delete,
    insert,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine

from .service import ReportEditorSession

_metadata = MetaData()
report_editor_grants_v1 = Table(
    "report_editor_grants_v1",
    _metadata,
    Column("grant_hash", String(64), primary_key=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    # 历史一次性授权的消费时间；授权改为可重复打开后仅为兼容既有表结构保留。
    Column("consumed_at", DateTime(timezone=True), nullable=True),
)
report_editor_sessions_v1 = Table(
    "report_editor_sessions_v1",
    _metadata,
    Column("session_hash", String(64), primary_key=True),
    Column("report_id", String(256), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("workflow_run_id", String(256), nullable=False),
    Column("context_sha256", String(64), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)


class SqlAlchemyReportEditorRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("Reporting 编辑授权持久化只支持 PostgreSQL。")
        self.engine = engine

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(_metadata.create_all)
            now = datetime.now(UTC)
            await connection.execute(
                delete(report_editor_grants_v1).where(report_editor_grants_v1.c.expires_at <= now)
            )
            await connection.execute(
                delete(report_editor_sessions_v1).where(
                    report_editor_sessions_v1.c.expires_at <= now
                )
            )

    async def put_grant(self, jti: str, *, expires_at: datetime) -> None:
        async with self.engine.begin() as connection:
            await connection.execute(
                insert(report_editor_grants_v1).values(
                    grant_hash=_hash(jti), expires_at=expires_at, consumed_at=None
                )
            )

    async def grant_active(self, jti: str, *, now: datetime) -> bool:
        async with self.engine.connect() as connection:
            row = (
                await connection.execute(
                    select(report_editor_grants_v1.c.grant_hash).where(
                        report_editor_grants_v1.c.grant_hash == _hash(jti),
                        report_editor_grants_v1.c.expires_at > now,
                    )
                )
            ).first()
        return row is not None

    async def put_session(self, session_hash: str, session: ReportEditorSession) -> None:
        async with self.engine.begin() as connection:
            # 授权可重复打开，每次兑换都会新增会话；顺带清理过期会话，避免长期运行时
            # 会话表只在进程启动时才收缩。
            await connection.execute(
                delete(report_editor_sessions_v1).where(
                    report_editor_sessions_v1.c.expires_at <= datetime.now(UTC)
                )
            )
            await connection.execute(
                insert(report_editor_sessions_v1).values(
                    session_hash=session_hash,
                    report_id=session.report_id,
                    revision=session.revision,
                    workflow_run_id=session.workflow_run_id,
                    context_sha256=session.context_sha256,
                    expires_at=session.expires_at,
                )
            )

    async def get_session(self, session_hash: str) -> ReportEditorSession | None:
        async with self.engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(report_editor_sessions_v1).where(
                            report_editor_sessions_v1.c.session_hash == session_hash
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        expires_at = cast(datetime, row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return ReportEditorSession(
            report_id=cast(str, row["report_id"]),
            revision=cast(int, row["revision"]),
            workflow_run_id=cast(str, row["workflow_run_id"]),
            context_sha256=cast(str, row["context_sha256"]),
            expires_at=expires_at,
        )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
