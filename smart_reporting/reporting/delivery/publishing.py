from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine

from ...workspace import (
    MAX_ASYNC_DOWNLOAD_TIMEOUT,
    MAX_DOWNLOAD_BYTES,
    WorkspaceService,
)
from ..models import ReportingError

DOWNLOAD_GRANT_TTL = timedelta(days=30)
REPORT_ARTIFACT_CHUNK_BYTES = 1024 * 1024
_DOWNLOAD_ACCESS_PATH = re.compile(r"/reports/v1/download/[^?\s]+(?:\?[^\s]*)?")

_metadata = MetaData()
report_download_grants_v2 = Table(
    "report_download_grants_v2",
    _metadata,
    Column("grant_hash", String(64), primary_key=True),
    Column("database_name", String(256), nullable=False),
    Column("user_id", String(256), nullable=False),
    Column("company_id", String(256), nullable=False),
    Column("session_id", String(256), nullable=False),
    Column("thread_id", String(256), nullable=False),
    Column("workflow_run_id", String(256), nullable=False),
    Column("report_id", String(256), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("pdf_path", Text, nullable=False),
    Column("pdf_size", BigInteger, nullable=False),
    Column("pdf_sha256", String(64), nullable=False),
    Column("word_path", Text, nullable=False),
    Column("word_size", BigInteger, nullable=False),
    Column("word_sha256", String(64), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Index(
        "ix_report_download_grants_v2_report_scope",
        "report_id",
        "database_name",
        "user_id",
        "company_id",
    ),
)
report_artifact_files_v1 = Table(
    "report_artifact_files_v1",
    _metadata,
    Column("artifact_key", String(64), primary_key=True),
    Column("database_name", String(256), nullable=False),
    Column("user_id", String(256), nullable=False),
    Column("company_id", String(256), nullable=False),
    Column("session_id", String(256), nullable=False),
    Column("thread_id", String(256), nullable=False),
    Column("workflow_run_id", String(256), nullable=False),
    Column("report_id", String(256), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("artifact", String(8), nullable=False),
    Column("path", Text, nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index(
        "ix_report_artifact_files_v1_scope",
        "report_id",
        "revision",
        "database_name",
        "user_id",
        "company_id",
        "session_id",
        "thread_id",
        "workflow_run_id",
    ),
)
report_artifact_chunks_v1 = Table(
    "report_artifact_chunks_v1",
    _metadata,
    Column(
        "artifact_key",
        ForeignKey("report_artifact_files_v1.artifact_key", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("chunk_index", Integer, primary_key=True),
    Column("content", LargeBinary, nullable=False),
)


@dataclass(frozen=True)
class ReportDownloadScope:
    database: str
    user_id: str
    company_id: str
    session_id: str
    thread_id: str
    workflow_run_id: str


@dataclass(frozen=True)
class ReportDownloadGrant:
    grant_hash: str
    scope: ReportDownloadScope
    report_id: str
    revision: int
    pdf_path: str
    pdf_size: int
    pdf_sha256: str
    word_path: str
    word_size: int
    word_sha256: str
    expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class ReportArtifactSpec:
    artifact: Literal["pdf", "word"]
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class StoredReportArtifact:
    artifact_key: str
    scope: ReportDownloadScope
    report_id: str
    revision: int
    artifact: Literal["pdf", "word"]
    path: str
    size: int
    sha256: str
    created_at: datetime


class DownloadGrantRepository(Protocol):
    async def put(self, grant: ReportDownloadGrant) -> None: ...

    async def get(self, grant_hash: str) -> ReportDownloadGrant | None: ...

    async def revoke_report(
        self,
        report_id: str,
        *,
        scope: ReportDownloadScope,
        before_revision: int | None = None,
    ) -> None: ...


class ReportArtifactRepository(Protocol):
    async def put(
        self,
        artifact: StoredReportArtifact,
        chunks: AsyncIterator[bytes],
    ) -> None: ...

    async def get(self, artifact_key: str) -> StoredReportArtifact | None: ...

    def stream(self, artifact_key: str) -> AsyncIterator[bytes]: ...


class SqlAlchemyDownloadGrantRepository:
    """基于 AgentOS AsyncEngine 的生产持久化仓，只保存 grant SHA-256。"""

    def __init__(self, engine: AsyncEngine):
        self.engine = engine

    async def create_schema(self) -> None:
        """创建当前下载授权和 PostgreSQL 报告产物表。"""

        async with self.engine.begin() as connection:
            await connection.run_sync(_metadata.create_all)

    async def put(self, grant: ReportDownloadGrant) -> None:
        values = {
            "grant_hash": grant.grant_hash,
            "database_name": grant.scope.database,
            "user_id": grant.scope.user_id,
            "company_id": grant.scope.company_id,
            "session_id": grant.scope.session_id,
            "thread_id": grant.scope.thread_id,
            "workflow_run_id": grant.scope.workflow_run_id,
            "report_id": grant.report_id,
            "revision": grant.revision,
            "pdf_path": grant.pdf_path,
            "pdf_size": grant.pdf_size,
            "pdf_sha256": grant.pdf_sha256,
            "word_path": grant.word_path,
            "word_size": grant.word_size,
            "word_sha256": grant.word_sha256,
            "expires_at": grant.expires_at,
            "revoked_at": grant.revoked_at,
        }
        async with self.engine.begin() as connection:
            await connection.execute(insert(report_download_grants_v2).values(**values))

    async def get(self, grant_hash: str) -> ReportDownloadGrant | None:
        statement = select(report_download_grants_v2).where(
            report_download_grants_v2.c.grant_hash == grant_hash
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        return ReportDownloadGrant(
            grant_hash=cast(str, row["grant_hash"]),
            scope=ReportDownloadScope(
                database=cast(str, row["database_name"]),
                user_id=cast(str, row["user_id"]),
                company_id=cast(str, row["company_id"]),
                session_id=cast(str, row["session_id"]),
                thread_id=cast(str, row["thread_id"]),
                workflow_run_id=cast(str, row["workflow_run_id"]),
            ),
            report_id=cast(str, row["report_id"]),
            revision=cast(int, row["revision"]),
            pdf_path=cast(str, row["pdf_path"]),
            pdf_size=cast(int, row["pdf_size"]),
            pdf_sha256=cast(str, row["pdf_sha256"]),
            word_path=cast(str, row["word_path"]),
            word_size=cast(int, row["word_size"]),
            word_sha256=cast(str, row["word_sha256"]),
            expires_at=_utc_datetime(cast(datetime, row["expires_at"])),
            revoked_at=(
                _utc_datetime(cast(datetime, row["revoked_at"]))
                if row["revoked_at"] is not None
                else None
            ),
        )

    async def revoke_report(
        self,
        report_id: str,
        *,
        scope: ReportDownloadScope,
        before_revision: int | None = None,
    ) -> None:
        conditions = [
            report_download_grants_v2.c.report_id == report_id,
            report_download_grants_v2.c.database_name == scope.database,
            report_download_grants_v2.c.user_id == scope.user_id,
            report_download_grants_v2.c.company_id == scope.company_id,
            report_download_grants_v2.c.session_id == scope.session_id,
            report_download_grants_v2.c.thread_id == scope.thread_id,
            report_download_grants_v2.c.workflow_run_id == scope.workflow_run_id,
            report_download_grants_v2.c.revoked_at.is_(None),
        ]
        if before_revision is not None:
            conditions.append(report_download_grants_v2.c.revision < before_revision)
        statement = (
            update(report_download_grants_v2)
            .where(*conditions)
            .values(revoked_at=datetime.now(UTC))
        )
        async with self.engine.begin() as connection:
            await connection.execute(statement)


class SqlAlchemyReportArtifactRepository:
    """在 PostgreSQL 中分块保存正式 PDF/Word，避免将大文件整体载入服务内存。"""

    def __init__(self, engine: AsyncEngine):
        self.engine = engine

    async def put(
        self,
        artifact: StoredReportArtifact,
        chunks: AsyncIterator[bytes],
    ) -> None:
        values = {
            "artifact_key": artifact.artifact_key,
            "database_name": artifact.scope.database,
            "user_id": artifact.scope.user_id,
            "company_id": artifact.scope.company_id,
            "session_id": artifact.scope.session_id,
            "thread_id": artifact.scope.thread_id,
            "workflow_run_id": artifact.scope.workflow_run_id,
            "report_id": artifact.report_id,
            "revision": artifact.revision,
            "artifact": artifact.artifact,
            "path": artifact.path,
            "size": artifact.size,
            "sha256": artifact.sha256,
            "created_at": artifact.created_at,
        }
        digest = hashlib.sha256()
        total = 0
        chunk_index = 0
        async with self.engine.begin() as connection:
            await connection.execute(
                delete(report_artifact_chunks_v1).where(
                    report_artifact_chunks_v1.c.artifact_key == artifact.artifact_key
                )
            )
            await connection.execute(
                delete(report_artifact_files_v1).where(
                    report_artifact_files_v1.c.artifact_key == artifact.artifact_key
                )
            )
            await connection.execute(insert(report_artifact_files_v1).values(**values))
            async for chunk in chunks:
                _validate_artifact_chunk(chunk)
                if not chunk:
                    continue
                total += len(chunk)
                if total > artifact.size or total > MAX_DOWNLOAD_BYTES:
                    raise ReportingError("report_artifact_changed", "报告文件已变化。")
                digest.update(chunk)
                await connection.execute(
                    insert(report_artifact_chunks_v1).values(
                        artifact_key=artifact.artifact_key,
                        chunk_index=chunk_index,
                        content=chunk,
                    )
                )
                chunk_index += 1
            _validate_stored_artifact(artifact, total=total, digest=digest.hexdigest())

    async def get(self, artifact_key: str) -> StoredReportArtifact | None:
        statement = select(report_artifact_files_v1).where(
            report_artifact_files_v1.c.artifact_key == artifact_key
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        artifact = cast(str, row["artifact"])
        if artifact not in {"pdf", "word"}:
            raise ReportingError("report_artifact_invalid", "持久化报告产物无效。")
        return StoredReportArtifact(
            artifact_key=cast(str, row["artifact_key"]),
            scope=ReportDownloadScope(
                database=cast(str, row["database_name"]),
                user_id=cast(str, row["user_id"]),
                company_id=cast(str, row["company_id"]),
                session_id=cast(str, row["session_id"]),
                thread_id=cast(str, row["thread_id"]),
                workflow_run_id=cast(str, row["workflow_run_id"]),
            ),
            report_id=cast(str, row["report_id"]),
            revision=cast(int, row["revision"]),
            artifact=cast(Literal["pdf", "word"], artifact),
            path=cast(str, row["path"]),
            size=cast(int, row["size"]),
            sha256=cast(str, row["sha256"]),
            created_at=_utc_datetime(cast(datetime, row["created_at"])),
        )

    async def stream(self, artifact_key: str) -> AsyncIterator[bytes]:
        statement = (
            select(report_artifact_chunks_v1.c.content)
            .where(report_artifact_chunks_v1.c.artifact_key == artifact_key)
            .order_by(report_artifact_chunks_v1.c.chunk_index)
        )
        async with self.engine.connect() as connection:
            result = await connection.stream(statement)
            async for row in result:
                yield cast(bytes, row[0])


class ReportDownloadGrantService:
    def __init__(self, repository: DownloadGrantRepository):
        self.repository = repository

    async def issue(
        self,
        *,
        scope: ReportDownloadScope,
        report_id: str,
        revision: int,
        pdf_path: str,
        pdf_size: int,
        pdf_sha256: str,
        word_path: str,
        word_size: int,
        word_sha256: str,
        now: datetime | None = None,
    ) -> tuple[str, ReportDownloadGrant]:
        current = _utc_datetime(now or datetime.now(UTC))
        await self.repository.revoke_report(report_id, scope=scope, before_revision=revision)
        raw = secrets.token_urlsafe(32)
        grant = ReportDownloadGrant(
            grant_hash=_grant_hash(raw),
            scope=scope,
            report_id=report_id,
            revision=revision,
            pdf_path=pdf_path,
            pdf_size=pdf_size,
            pdf_sha256=pdf_sha256,
            expires_at=current + DOWNLOAD_GRANT_TTL,
            word_path=word_path,
            word_size=word_size,
            word_sha256=word_sha256,
        )
        await self.repository.put(grant)
        return raw, grant

    async def lookup(self, raw_grant: str, *, now: datetime | None = None) -> ReportDownloadGrant:
        if not isinstance(raw_grant, str) or len(raw_grant) > 128:
            raise ReportingError("report_download_grant_invalid", "下载授权无效。")
        grant = await self.repository.get(_grant_hash(raw_grant))
        current = _utc_datetime(now or datetime.now(UTC))
        if grant is None or grant.revoked_at is not None:
            raise ReportingError("report_download_grant_invalid", "下载授权无效。")
        if grant.expires_at <= current:
            raise ReportingError("report_download_grant_expired", "下载授权已过期。")
        return grant


class ReportArtifactPersistenceService:
    """将正式产物从 Daytona 流式固化到 PostgreSQL，完成后才允许删除 sandbox。"""

    def __init__(
        self,
        repository: ReportArtifactRepository,
        workspace_service: WorkspaceService,
    ) -> None:
        self.repository = repository
        self.workspace_service = workspace_service

    async def persist(
        self,
        *,
        scope: ReportDownloadScope,
        report_id: str,
        revision: int,
        artifacts: tuple[ReportArtifactSpec, ...],
    ) -> None:
        if len(artifacts) != 2 or {item.artifact for item in artifacts} != {"pdf", "word"}:
            raise ReportingError("report_artifact_invalid", "必须同时持久化 PDF 和 Word。")
        for spec in artifacts:
            if (
                spec.size <= 0
                or spec.size > MAX_DOWNLOAD_BYTES
                or re.fullmatch(r"[0-9a-f]{64}", spec.sha256) is None
            ):
                raise ReportingError("report_artifact_invalid", "报告产物身份无效。")
            relative, remote = self.workspace_service.normalize_path(spec.path, allow_root=False)
            if relative != spec.path:
                raise ReportingError("report_artifact_changed", "报告文件路径已变化。")
            artifact = StoredReportArtifact(
                artifact_key=_artifact_key(scope, report_id, revision, spec),
                scope=scope,
                report_id=report_id,
                revision=revision,
                artifact=spec.artifact,
                path=relative,
                size=spec.size,
                sha256=spec.sha256,
                created_at=datetime.now(UTC),
            )
            existing = await self.repository.get(artifact.artifact_key)
            if existing is not None and _same_artifact_identity(existing, artifact):
                continue
            await self.repository.put(
                artifact,
                self._workspace_chunks(scope.thread_id, remote, expected_size=spec.size),
            )

    async def _workspace_chunks(
        self,
        thread_id: str,
        remote: str,
        *,
        expected_size: int,
    ) -> AsyncIterator[bytes]:
        try:
            async with self.workspace_service._async_client() as client:
                sandbox = await self.workspace_service._asandbox_for(
                    client, thread_id, create=False
                )
                if sandbox is None:
                    raise ReportingError("report_artifact_missing", "报告工作区不存在。")
                stream = await sandbox.fs.download_file_stream(
                    remote,
                    timeout=MAX_ASYNC_DOWNLOAD_TIMEOUT,
                )
                buffered = bytearray()
                total = 0
                async for chunk in stream:
                    _validate_artifact_chunk(chunk)
                    total += len(chunk)
                    if total > expected_size or total > MAX_DOWNLOAD_BYTES:
                        raise ReportingError("report_artifact_changed", "报告文件已变化。")
                    buffered.extend(chunk)
                    while len(buffered) >= REPORT_ARTIFACT_CHUNK_BYTES:
                        yield bytes(buffered[:REPORT_ARTIFACT_CHUNK_BYTES])
                        del buffered[:REPORT_ARTIFACT_CHUNK_BYTES]
                if buffered:
                    yield bytes(buffered)
        except ReportingError:
            raise
        except Exception as error:
            raise ReportingError("report_artifact_changed", "报告文件已变化。") from error


class ReportDownloadHttpService:
    """从 PostgreSQL 流式读取已授权的正式报告产物。"""

    def __init__(
        self,
        grants: ReportDownloadGrantService,
        artifacts: ReportArtifactRepository,
    ):
        self.grants = grants
        self.artifacts = artifacts

    async def stream(
        self,
        raw_grant: str,
        *,
        artifact: Literal["pdf", "word"] = "pdf",
    ) -> tuple[ReportDownloadGrant, AsyncIterator[bytes]]:
        grant = await self.grants.lookup(raw_grant)
        path, size, sha256 = _grant_artifact(grant, artifact)
        if size <= 0 or size > MAX_DOWNLOAD_BYTES:
            raise ReportingError("report_download_file_changed", "报告文件已变化。")
        spec = ReportArtifactSpec(artifact=artifact, path=path, size=size, sha256=sha256)
        artifact_key = _artifact_key(grant.scope, grant.report_id, grant.revision, spec)
        stored = await self.artifacts.get(artifact_key)
        if (
            stored is None
            or stored.scope != grant.scope
            or stored.report_id != grant.report_id
            or stored.revision != grant.revision
            or stored.artifact != artifact
            or stored.path != path
            or stored.size != size
            or not secrets.compare_digest(stored.sha256, sha256)
        ):
            raise ReportingError("report_download_file_changed", "报告文件已变化。")
        return grant, self._stream_verified_file(
            artifact_key,
            expected_size=size,
            expected_sha256=sha256,
        )

    async def _stream_verified_file(
        self,
        artifact_key: str,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> AsyncIterator[bytes]:
        digest = hashlib.sha256()
        total = 0
        try:
            async for chunk in self.artifacts.stream(artifact_key):
                _validate_artifact_chunk(chunk)
                total += len(chunk)
                if total > expected_size:
                    raise ReportingError("report_download_file_changed", "报告文件已变化。")
                digest.update(chunk)
                yield chunk
        except ReportingError:
            raise
        except Exception as error:
            raise ReportingError("report_download_file_changed", "报告文件已变化。") from error

        if total != expected_size or not secrets.compare_digest(
            digest.hexdigest(), expected_sha256
        ):
            raise ReportingError("report_download_file_changed", "报告文件已变化。")


def create_report_download_router(
    service: ReportDownloadHttpService,
) -> APIRouter:
    router = APIRouter()

    @router.get("/reports/v1/download/{opaque_grant}", name="download_report_pdf")
    async def download_report_pdf(
        opaque_grant: str,
    ) -> StreamingResponse:
        try:
            grant, content = await service.stream(opaque_grant)
        except ReportingError as error:
            raise HTTPException(
                status_code=_download_error_status(error.code),
                detail={"code": error.code, "message": error.message},
            ) from None
        return StreamingResponse(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": _content_disposition(grant.pdf_path, artifact="pdf"),
                "Content-Length": str(grant.pdf_size),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/reports/v1/download/{opaque_grant}/word", name="download_report_word")
    async def download_report_word(
        opaque_grant: str,
    ) -> StreamingResponse:
        try:
            grant, content = await service.stream(opaque_grant, artifact="word")
        except ReportingError as error:
            raise HTTPException(
                status_code=_download_error_status(error.code),
                detail={"code": error.code, "message": error.message},
            ) from None
        _path, word_size, _sha256 = _grant_artifact(grant, "word")
        return StreamingResponse(
            content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": _content_disposition(grant.word_path, artifact="word"),
                "Content-Length": str(word_size),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Accel-Buffering": "no",
            },
        )

    return router


def _content_disposition(path: str, *, artifact: Literal["pdf", "word"]) -> str:
    filename = Path(path).name
    suffix = ".pdf" if artifact == "pdf" else ".docx"
    if Path(filename).suffix.lower() != suffix:
        filename = f"report{suffix}"
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode()
    if ascii_name != filename or not ascii_name:
        ascii_name = f"report{suffix}"
    encoded_name = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"


def publication_result(
    *,
    report_id: str,
    revision: int,
    raw_grant: str,
    grant: ReportDownloadGrant,
    source_warnings: list[dict[str, object]] | None = None,
    coding_receipts: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "reportId": report_id,
        "revision": revision,
        "pdf": {
            "downloadUrl": f"/reports/v1/download/{raw_grant}",
            "expiresAt": grant.expires_at.isoformat(),
            "size": grant.pdf_size,
            "sha256": grant.pdf_sha256,
        },
        "word": {
            "downloadUrl": f"/reports/v1/download/{raw_grant}/word",
            "expiresAt": grant.expires_at.isoformat(),
            "size": grant.word_size,
            "sha256": grant.word_sha256,
        },
        "sourceWarnings": list(source_warnings or ()),
        "codingReceipts": list(coding_receipts or ()),
    }


def cli_result(
    *,
    path: str,
    size: int,
    sha256: str,
    word_path: str,
    word_size: int,
    word_sha256: str,
    source_warnings: list[dict[str, object]] | None = None,
    coding_receipts: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "path": path,
        "size": size,
        "sha256": sha256,
        "word": {"path": word_path, "size": word_size, "sha256": word_sha256},
        "sourceWarnings": list(source_warnings or ()),
        "codingReceipts": list(coding_receipts or ()),
    }


class ReportDownloadAccessLogFilter(logging.Filter):
    """从 Uvicorn access log 参数中移除原始下载 grant。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _redact_download_path(value) if isinstance(value, str) else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: _redact_download_path(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        if isinstance(record.msg, str):
            record.msg = _redact_download_path(record.msg)
        return True


def install_report_download_access_log_filter(
    logger: logging.Logger | None = None,
) -> None:
    target = logger or logging.getLogger("uvicorn.access")
    if not any(isinstance(item, ReportDownloadAccessLogFilter) for item in target.filters):
        target.addFilter(ReportDownloadAccessLogFilter())


def _grant_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _redact_download_path(value: str) -> str:
    return _DOWNLOAD_ACCESS_PATH.sub("/reports/v1/download/<redacted>", value)


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _artifact_key(
    scope: ReportDownloadScope,
    report_id: str,
    revision: int,
    artifact: ReportArtifactSpec,
) -> str:
    payload = {
        "artifact": artifact.artifact,
        "companyId": scope.company_id,
        "database": scope.database,
        "path": artifact.path,
        "reportId": report_id,
        "revision": revision,
        "sessionId": scope.session_id,
        "sha256": artifact.sha256,
        "size": artifact.size,
        "threadId": scope.thread_id,
        "userId": scope.user_id,
        "workflowRunId": scope.workflow_run_id,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _validate_artifact_chunk(chunk: object) -> None:
    if not isinstance(chunk, bytes):
        raise ReportingError("report_artifact_changed", "报告文件已变化。")


def _same_artifact_identity(
    left: StoredReportArtifact,
    right: StoredReportArtifact,
) -> bool:
    return (
        left.artifact_key == right.artifact_key
        and left.scope == right.scope
        and left.report_id == right.report_id
        and left.revision == right.revision
        and left.artifact == right.artifact
        and left.path == right.path
        and left.size == right.size
        and secrets.compare_digest(left.sha256, right.sha256)
    )


def _validate_stored_artifact(
    artifact: StoredReportArtifact,
    *,
    total: int,
    digest: str,
) -> None:
    if (
        artifact.size <= 0
        or artifact.size > MAX_DOWNLOAD_BYTES
        or total != artifact.size
        or not secrets.compare_digest(digest, artifact.sha256)
    ):
        raise ReportingError("report_artifact_changed", "报告文件已变化。")


def _grant_artifact(
    grant: ReportDownloadGrant,
    artifact: Literal["pdf", "word"],
) -> tuple[str, int, str]:
    if artifact == "pdf":
        return grant.pdf_path, grant.pdf_size, grant.pdf_sha256
    return grant.word_path, grant.word_size, grant.word_sha256


def _download_error_status(code: str) -> int:
    return {
        "report_download_grant_expired": 410,
        "report_download_file_changed": 409,
    }.get(code, 404)
