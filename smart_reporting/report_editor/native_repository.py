"""PostgreSQL 原生文档仓储；预约事务在引擎运行前结束。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ..reporting.models import ReportingError
from .native_models import (
    NATIVE_ARTIFACT_KEYS,
    NativeArtifacts,
    NativeDocument,
    NativeEditorContext,
    NativeIssue,
    NativeRevision,
    NativeScope,
    NativeSource,
    NativeValidation,
    native_digest,
)

_metadata = MetaData()
_documents = Table(
    "report_native_documents_v1",
    _metadata,
    Column("document_id", String(256), primary_key=True),
    Column("create_key", String(64), nullable=False, unique=True),
    Column("database", String(256), nullable=False),
    Column("company_id", String(256), nullable=False),
    Column("user_id", String(256), nullable=False),
    Column("thread_id", String(256), nullable=False),
    Column("format", String(16), nullable=False),
    Column("owner_id", String(256), nullable=False),
    Column("source", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("next_revision", Integer, nullable=False),
    Column("event_sequence", BigInteger, nullable=False, server_default="0"),
)
_revisions = Table(
    "report_native_revisions_v1",
    _metadata,
    Column("document_id", String(256), ForeignKey(_documents.c.document_id), primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("request_id", String(256), nullable=False),
    Column("scope", JSONB, nullable=False),
    Column("parent_revision", Integer, nullable=True),
    Column("request_sha256", String(64), nullable=False),
    Column("note", String(200), nullable=False, server_default=""),
    Column("status", String(16), nullable=False),
    Column("context", JSONB, nullable=True),
    Column("artifacts", JSONB, nullable=False),
    Column("validation", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("failure_code", String(128), nullable=True),
    UniqueConstraint("document_id", "request_id"),
)

_events = Table(
    "report_native_revision_events_v1",
    _metadata,
    Column("document_id", String(256), ForeignKey(_documents.c.document_id), primary_key=True),
    Column("sequence", BigInteger, primary_key=True),
    Column("event_id", String(32), nullable=False, unique=True),
    Column("revision", Integer, nullable=False),
    Column("request_id", String(256), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


class NativeRepositoryConflict(ReportingError):
    def __init__(self, message: str = "原生修订请求与已登记状态不一致"):
        super().__init__("native_revision_conflict", message)


class NativeRepositoryNotFound(ReportingError):
    def __init__(self):
        super().__init__("native_document_not_found", "原生文档或修订不存在")


def _scope_clause(scope: NativeScope):
    return tuple(_documents.c[key] == value for key, value in scope.model_dump().items())


def _document(row: Any) -> NativeDocument:
    return NativeDocument(
        documentId=row["document_id"],
        scope=NativeScope(**{key: row[key] for key in NativeScope.model_fields}),
        ownerId=row["owner_id"],
        source=NativeSource.model_validate(row["source"]),
        createdAt=row["created_at"],
        nextRevision=row["next_revision"],
    )


def _revision_values(revision: NativeRevision) -> dict[str, Any]:
    values = revision.model_dump(mode="json")
    values["created_at"] = revision.created_at
    return values


class NativeDocumentRepository:
    def __init__(self, engine: AsyncEngine):
        if engine.dialect.name != "postgresql":
            raise ValueError("原生文档持久化只支持 PostgreSQL。")
        self.engine = engine

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            # create_all's existence checks are not atomic across worker startup.
            # Serialize this schema's DDL before checking/creating any native table.
            await connection.execute(text(
                "SELECT pg_advisory_xact_lock(hashtext('native_document_schema_v1'), "
                "hashtext(current_schema()))"
            ))
            await connection.run_sync(_metadata.create_all)
            await connection.execute(text(
                "ALTER TABLE report_native_documents_v1 "
                "ADD COLUMN IF NOT EXISTS event_sequence BIGINT NOT NULL DEFAULT 0"
            ))
            await connection.execute(text(
                "ALTER TABLE report_native_revisions_v1 "
                "ADD COLUMN IF NOT EXISTS note VARCHAR(200) NOT NULL DEFAULT ''"
            ))

    async def _append_revision_event(
        self, connection: AsyncConnection, revision: NativeRevision,
    ) -> None:
        """Called with the document row locked, inside the revision transaction.

        Events describe committed metadata, not token progress or a document snapshot.
        Consumers must still reauthorize and read the revision before using its content.
        """
        sequence = (await connection.execute(
            update(_documents)
            .where(_documents.c.document_id == revision.document_id)
            .values(event_sequence=_documents.c.event_sequence + 1)
            .returning(_documents.c.event_sequence)
        )).scalar_one()
        await connection.execute(insert(_events).values(
            document_id=revision.document_id, sequence=sequence, event_id=uuid4().hex,
            revision=revision.revision, request_id=revision.request_id,
            status=revision.status, created_at=datetime.now(UTC),
        ))

    async def revision_events_after(
        self, document_id: str, *, scope: NativeScope, after: int = 0, limit: int = 100,
    ) -> dict[str, Any]:
        """Read a bounded durable page. nextSequence, not latestSequence, is the cursor.

        Legacy documents start at sequence zero; their historical revisions are not
        backfilled. No event retention/pruning is enabled in this first slice.
        """
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("事件游标或批量大小无效")
        async with self.engine.connect() as connection:
            latest = (await connection.execute(
                select(_documents.c.event_sequence).where(
                    _documents.c.document_id == document_id, *_scope_clause(scope),
                )
            )).scalar_one_or_none()
            if latest is None:
                raise NativeRepositoryNotFound()
            if after > latest:
                raise NativeRepositoryConflict("事件游标超过当前文档，请重新读取修订状态")
            # Bound by the sequence read above so concurrent commits cannot create a
            # page whose events exceed latestSequence. The caller can resume safely.
            rows = (await connection.execute(
                select(_events).where(
                    _events.c.document_id == document_id,
                    _events.c.sequence > after, _events.c.sequence <= latest,
                ).order_by(_events.c.sequence).limit(limit)
            )).mappings().all()
            events = [dict(row) for row in rows]
            return {"events": events, "nextSequence": events[-1]["sequence"] if events else after,
                    "latestSequence": latest}

    async def create_from_source(
        self, source: NativeSource, *, scope: NativeScope, request_id: str
    ) -> NativeDocument:
        # 来源与 scope 共同绑定重试身份，不能靠客户端 requestId 跨来源复用文档。
        if not request_id or len(request_id) > 256:
            raise ValueError("requestId 长度无效")
        key = native_digest(
            {
                "scope": scope.model_dump(mode="json"),
                "source": source.model_dump(mode="json"),
                "requestId": request_id,
            }
        )
        document_id, now = uuid4().hex, datetime.now(UTC)
        async with self.engine.begin() as connection:
            result = await connection.execute(
                pg_insert(_documents)
                .values(
                    document_id=document_id,
                    create_key=key,
                    **scope.model_dump(),
                    format=source.format,
                    owner_id=scope.user_id,
                    source=source.model_dump(mode="json"),
                    created_at=now,
                    next_revision=2,
                )
                .on_conflict_do_nothing(index_elements=["create_key"])
                .returning(_documents.c.document_id)
            )
            if result.scalar_one_or_none() is not None:
                context = NativeEditorContext(
                    documentId=document_id,
                    format=source.format,
                    revision=1,
                    scope=scope,
                    sourceFile=source.source_file,
                    origin=source.origin,
                )
                initial = NativeRevision(
                    documentId=document_id,
                    revision=1,
                    scope=scope,
                    requestId=request_id,
                    requestSha256=native_digest(source.model_dump(mode="json")),
                    status="saved",
                    context=context,
                    artifacts=NativeArtifacts(
                        **{NATIVE_ARTIFACT_KEYS[source.format]: source.source_file}
                    ),
                    validation=NativeValidation(
                        ok=False,
                        issues=(
                            NativeIssue(
                                code="native_validation_pending",
                                message="仅登记来源文件身份，尚未重新执行业务和版式验收",
                            ),
                        ),
                    ),
                    createdAt=now,
                )
                await self._insert_revision(connection, initial)
                await self._append_revision_event(connection, initial)
            row = (
                (await connection.execute(select(_documents).where(_documents.c.create_key == key)))
                .mappings()
                .one()
            )
            return _document(row)

    async def get_document(self, document_id: str, *, scope: NativeScope) -> NativeDocument | None:
        async with self.engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(_documents).where(
                            _documents.c.document_id == document_id, *_scope_clause(scope)
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            return _document(row) if row is not None else None

    async def get_revision(
        self, document_id: str, revision: int, *, scope: NativeScope
    ) -> NativeRevision | None:
        async with self.engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        select(_revisions)
                        .join(_documents)
                        .where(
                            _revisions.c.document_id == document_id,
                            _revisions.c.revision == revision,
                            *_scope_clause(scope),
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            return NativeRevision.model_validate(row) if row is not None else None

    async def reserve_revision(
        self,
        document_id: str,
        *,
        parent_revision: int,
        request_id: str,
        request_sha256: str,
        scope: NativeScope,
        note: str = "",
    ) -> NativeRevision:
        async with self.engine.begin() as connection:
            row = (
                (
                    await connection.execute(
                        select(_documents)
                        .where(_documents.c.document_id == document_id, *_scope_clause(scope))
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise NativeRepositoryNotFound()
            existing = (
                (
                    await connection.execute(
                        select(_revisions).where(
                            _revisions.c.document_id == document_id,
                            _revisions.c.request_id == request_id,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                reserved = NativeRevision.model_validate(existing)
                if (
                    reserved.request_sha256 != request_sha256
                    or reserved.parent_revision != parent_revision
                    or reserved.note != note
                ):
                    raise NativeRepositoryConflict()
                return reserved
            parent = (
                (
                    await connection.execute(
                        select(_revisions).where(
                            _revisions.c.document_id == document_id,
                            _revisions.c.revision == parent_revision,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if parent is None:
                raise NativeRepositoryNotFound()
            if NativeRevision.model_validate(parent).status != "saved":
                raise NativeRepositoryConflict("父修订尚未保存")
            reserved = NativeRevision(
                documentId=document_id,
                revision=row["next_revision"],
                scope=scope,
                parentRevision=parent_revision,
                requestId=request_id,
                requestSha256=request_sha256,
                note=note,
                status="reserved",
                createdAt=datetime.now(UTC),
            )
            await self._insert_revision(connection, reserved)
            await connection.execute(
                update(_documents)
                .where(_documents.c.document_id == document_id)
                .values(next_revision=reserved.revision + 1)
            )
            return reserved

    async def _insert_revision(self, connection: AsyncConnection, revision: NativeRevision) -> None:
        await connection.execute(insert(_revisions).values(**_revision_values(revision)))

    async def complete_revision(
        self,
        reservation: NativeRevision,
        *,
        context: NativeEditorContext,
        artifacts: NativeArtifacts,
        validation: NativeValidation,
    ) -> NativeRevision:
        # failed 可在服务层重读并核验实际文件后恢复；此层只核对元数据，saved 始终不可覆盖。
        return await self._finish(
            reservation, context=context, artifacts=artifacts, validation=validation
        )

    async def fail_revision(self, reservation: NativeRevision, *, code: str) -> NativeRevision:
        if not code or len(code) > 128:
            raise ValueError("失败代码无效")
        return await self._finish(reservation, code=code)

    async def _finish(
        self,
        reservation: NativeRevision,
        *,
        context: NativeEditorContext | None = None,
        artifacts: NativeArtifacts | None = None,
        validation: NativeValidation | None = None,
        code: str | None = None,
    ) -> NativeRevision:
        async with self.engine.begin() as connection:
            docrow = (
                (
                    await connection.execute(
                        select(_documents)
                        .where(
                            _documents.c.document_id == reservation.document_id,
                            *_scope_clause(reservation.scope),
                        )
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if docrow is None:
                raise NativeRepositoryNotFound()
            payload = (
                (
                    await connection.execute(
                        select(_revisions).where(
                            _revisions.c.document_id == reservation.document_id,
                            _revisions.c.revision == reservation.revision,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if payload is None:
                raise NativeRepositoryNotFound()
            current = NativeRevision.model_validate(payload)
            if (
                current.request_id,
                current.request_sha256,
                current.parent_revision,
                current.scope,
                current.note,
            ) != (
                reservation.request_id,
                reservation.request_sha256,
                reservation.parent_revision,
                reservation.scope,
                reservation.note,
            ):
                raise NativeRepositoryConflict()
            if context is not None:
                assert artifacts is not None and validation is not None
                if (
                    context.document_id,
                    context.revision,
                    context.scope,
                    context.parent_revision,
                    context.format,
                    context.origin,
                ) != (
                    current.document_id,
                    current.revision,
                    current.scope,
                    current.parent_revision,
                    docrow["format"],
                    docrow["source"]["origin"],
                ):
                    raise NativeRepositoryConflict("修订上下文与预约身份不一致")
                primary = getattr(artifacts, NATIVE_ARTIFACT_KEYS[context.format])
                if primary != context.source_file:
                    raise NativeRepositoryConflict("修订上下文与实际产物身份不一致")
                updated = current.model_copy(
                    update={
                        "status": "saved",
                        "context": context,
                        "artifacts": artifacts,
                        "validation": validation,
                        "failure_code": None,
                    }
                )
            else:
                updated = current.model_copy(update={"status": "failed", "failure_code": code})
            if current.status == "saved":
                if current != updated:
                    raise NativeRepositoryConflict("已保存修订不可覆盖")
                return current
            if current.status == "failed" and context is None and current != updated:
                raise NativeRepositoryConflict()
            await connection.execute(
                update(_revisions)
                .where(
                    _revisions.c.document_id == current.document_id,
                    _revisions.c.revision == current.revision,
                )
                .values(**_revision_values(updated))
            )
            if current != updated:
                await self._append_revision_event(connection, updated)
            return updated
