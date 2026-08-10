from __future__ import annotations

import hashlib
import logging
import re
import secrets
import stat
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol, cast
from urllib.parse import quote

import anyio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    exists,
    insert,
    literal,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine

from ....workspace import (
    MAX_ASYNC_DOWNLOAD_TIMEOUT,
    MAX_DOWNLOAD_BYTES,
    WorkspaceService,
)
from ..models import ReportingError

DOWNLOAD_GRANT_TTL = timedelta(hours=24)
_DOWNLOAD_ACCESS_PATH = re.compile(r"/reports/v1/download/[^?\s]+(?:\?[^\s]*)?")

_metadata = MetaData()
report_download_grants_v1 = Table(
    "report_download_grants_v1",
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
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Index(
        "ix_report_download_grants_v1_report_scope",
        "report_id",
        "database_name",
        "user_id",
        "company_id",
    ),
)
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
    # 由 v1 幂等迁入的旧 grant 只允许继续下载 PDF；新签发记录必须写入全部 Word 字段。
    Column("word_path", Text, nullable=True),
    Column("word_size", BigInteger, nullable=True),
    Column("word_sha256", String(64), nullable=True),
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


@dataclass(frozen=True)
class ReportDownloadScope:
    database: str
    user_id: str
    company_id: str
    session_id: str
    thread_id: str
    workflow_run_id: str


@dataclass(frozen=True)
class ReportDownloadCallerScope:
    database: str
    user_id: str
    company_id: str
    session_id: str
    thread_id: str


@dataclass(frozen=True)
class ReportDownloadGrant:
    grant_hash: str
    scope: ReportDownloadScope
    report_id: str
    revision: int
    pdf_path: str
    pdf_size: int
    pdf_sha256: str
    expires_at: datetime
    word_path: str | None = None
    word_size: int | None = None
    word_sha256: str | None = None
    revoked_at: datetime | None = None


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


class InMemoryDownloadGrantRepository:
    """测试仓；与生产仓相同，只保存 grant hash。"""

    def __init__(self) -> None:
        self.records: dict[str, ReportDownloadGrant] = {}

    async def put(self, grant: ReportDownloadGrant) -> None:
        self.records[grant.grant_hash] = grant

    async def get(self, grant_hash: str) -> ReportDownloadGrant | None:
        return self.records.get(grant_hash)

    async def revoke_report(
        self,
        report_id: str,
        *,
        scope: ReportDownloadScope,
        before_revision: int | None = None,
    ) -> None:
        now = datetime.now(UTC)
        for key, grant in tuple(self.records.items()):
            if (
                grant.report_id == report_id
                and grant.scope == scope
                and (before_revision is None or grant.revision < before_revision)
            ):
                self.records[key] = replace(grant, revoked_at=now)


class SqlAlchemyDownloadGrantRepository:
    """基于 AgentOS AsyncEngine 的生产持久化仓，只保存 grant SHA-256。"""

    def __init__(self, engine: AsyncEngine):
        self.engine = engine

    async def create_schema(self) -> None:
        """创建 v2 表并迁移仍有效的 v1 PDF grant；重复启动保持幂等。"""

        async with self.engine.begin() as connection:
            await connection.run_sync(_metadata.create_all)
            current = datetime.now(UTC)
            columns = (
                "grant_hash",
                "database_name",
                "user_id",
                "company_id",
                "session_id",
                "thread_id",
                "workflow_run_id",
                "report_id",
                "revision",
                "pdf_path",
                "pdf_size",
                "pdf_sha256",
                "word_path",
                "word_size",
                "word_sha256",
                "expires_at",
                "revoked_at",
            )
            legacy = select(
                report_download_grants_v1.c.grant_hash,
                report_download_grants_v1.c.database_name,
                report_download_grants_v1.c.user_id,
                report_download_grants_v1.c.company_id,
                report_download_grants_v1.c.session_id,
                report_download_grants_v1.c.thread_id,
                report_download_grants_v1.c.workflow_run_id,
                report_download_grants_v1.c.report_id,
                report_download_grants_v1.c.revision,
                report_download_grants_v1.c.pdf_path,
                report_download_grants_v1.c.pdf_size,
                report_download_grants_v1.c.pdf_sha256,
                literal(None),
                literal(None),
                literal(None),
                report_download_grants_v1.c.expires_at,
                report_download_grants_v1.c.revoked_at,
            ).where(
                report_download_grants_v1.c.expires_at > current,
                report_download_grants_v1.c.revoked_at.is_(None),
                ~exists(
                    select(1).where(
                        report_download_grants_v2.c.grant_hash
                        == report_download_grants_v1.c.grant_hash
                    )
                ),
            )
            await connection.execute(insert(report_download_grants_v2).from_select(columns, legacy))

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
            word_path=cast(str, row["word_path"]) if row["word_path"] is not None else None,
            word_size=cast(int, row["word_size"]) if row["word_size"] is not None else None,
            word_sha256=(cast(str, row["word_sha256"]) if row["word_sha256"] is not None else None),
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

    async def resolve(
        self,
        raw_grant: str,
        *,
        scope: ReportDownloadScope,
        current_pdf_sha256: str,
        current_revision: int,
        current_word_sha256: str | None = None,
        now: datetime | None = None,
    ) -> ReportDownloadGrant:
        grant = await self.inspect(raw_grant, scope=scope, now=now)
        if grant.revision != current_revision:
            raise ReportingError("report_download_revision_changed", "报告 revision 已变化。")
        if not secrets.compare_digest(grant.pdf_sha256, current_pdf_sha256):
            raise ReportingError("report_download_file_changed", "报告文件已变化。")
        if (
            current_word_sha256 is not None
            and grant.word_sha256 is not None
            and not secrets.compare_digest(grant.word_sha256, current_word_sha256)
        ):
            raise ReportingError("report_download_file_changed", "报告文件已变化。")
        return grant

    async def inspect(
        self,
        raw_grant: str,
        *,
        scope: ReportDownloadScope,
        now: datetime | None = None,
    ) -> ReportDownloadGrant:
        grant = await self.lookup(raw_grant, now=now)
        if grant.scope != scope:
            raise ReportingError("report_download_scope_mismatch", "下载授权不属于当前上下文。")
        return grant

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

    async def cancel(self, report_id: str, *, scope: ReportDownloadScope) -> None:
        await self.repository.revoke_report(report_id, scope=scope)


@dataclass(frozen=True)
class ReportDownloadFileState:
    revision: int
    pdf_path: str
    word_path: str | None = None


class CurrentReportFileProvider(Protocol):
    async def get_current(
        self, report_id: str, scope: ReportDownloadScope
    ) -> ReportDownloadFileState | None: ...


@dataclass(frozen=True)
class AuthorizedReportDownload:
    grant: ReportDownloadGrant
    path: Path
    artifact: Literal["pdf", "word"]


class ReportDownloadHttpService:
    """组合 grant、当前报告状态和实际文件校验，不依赖应用装配。"""

    def __init__(
        self,
        grants: ReportDownloadGrantService,
        current_reports: CurrentReportFileProvider,
    ):
        self.grants = grants
        self.current_reports = current_reports

    async def authorize(
        self,
        raw_grant: str,
        *,
        scope: ReportDownloadScope,
        artifact: Literal["pdf", "word"] = "pdf",
        now: datetime | None = None,
    ) -> AuthorizedReportDownload:
        grant = await self.grants.inspect(raw_grant, scope=scope, now=now)
        current = await self.current_reports.get_current(grant.report_id, scope)
        if current is None or current.revision != grant.revision:
            raise ReportingError("report_download_revision_changed", "报告 revision 已变化。")
        path_value, size_value, sha256_value = _grant_artifact(grant, artifact)
        current_path = current.pdf_path if artifact == "pdf" else current.word_path
        if current_path != path_value:
            raise ReportingError("report_download_file_changed", "报告文件已变化。")
        path = Path(path_value)
        size, digest = await anyio.to_thread.run_sync(_file_identity, path)
        if size != size_value or digest != sha256_value:
            raise ReportingError("report_download_file_changed", "报告文件已变化。")
        return AuthorizedReportDownload(grant=grant, path=path, artifact=artifact)


ScopeDependency = Callable[..., ReportDownloadScope | Awaitable[ReportDownloadScope]]


def create_report_download_router(
    service: ReportDownloadHttpService,
    *,
    scope_dependency: ScopeDependency,
) -> APIRouter:
    router = APIRouter()

    @router.get("/reports/v1/download/{opaque_grant}", name="download_report_pdf")
    async def download_report_pdf(
        opaque_grant: str,
        scope: ReportDownloadScope = Depends(scope_dependency),
    ) -> FileResponse:
        try:
            authorized = await service.authorize(opaque_grant, scope=scope)
        except ReportingError as error:
            raise HTTPException(
                status_code=_download_error_status(error.code),
                detail={"code": error.code, "message": error.message},
            ) from None
        return FileResponse(
            authorized.path,
            media_type="application/pdf",
            headers={
                "Content-Disposition": _content_disposition(
                    authorized.grant.pdf_path, artifact="pdf"
                ),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/reports/v1/download/{opaque_grant}/word", name="download_report_word")
    async def download_report_word(
        opaque_grant: str,
        scope: ReportDownloadScope = Depends(scope_dependency),
    ) -> FileResponse:
        try:
            authorized = await service.authorize(opaque_grant, scope=scope, artifact="word")
        except ReportingError as error:
            raise HTTPException(
                status_code=_download_error_status(error.code),
                detail={"code": error.code, "message": error.message},
            ) from None
        return FileResponse(
            authorized.path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": _content_disposition(
                    authorized.grant.word_path or "report.docx", artifact="word"
                ),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router


class WorkspaceReportDownloadHttpService:
    """从绑定 thread 的 Daytona 工作区流式读取已授权报表产物。"""

    def __init__(
        self,
        grants: ReportDownloadGrantService,
        workspace_service: WorkspaceService,
    ):
        self.grants = grants
        self.workspace_service = workspace_service

    async def stream(
        self,
        raw_grant: str,
        *,
        caller: ReportDownloadCallerScope,
        artifact: Literal["pdf", "word"] = "pdf",
    ) -> tuple[ReportDownloadGrant, AsyncIterator[bytes]]:
        grant = await self.grants.lookup(raw_grant)
        expected = (
            grant.scope.database,
            grant.scope.user_id,
            grant.scope.company_id,
            grant.scope.session_id,
            grant.scope.thread_id,
        )
        actual = (
            caller.database,
            caller.user_id,
            caller.company_id,
            caller.session_id,
            caller.thread_id,
        )
        if actual != expected:
            raise ReportingError("report_download_scope_mismatch", "下载授权不属于当前上下文。")
        path, size, sha256 = _grant_artifact(grant, artifact)
        relative, remote = self.workspace_service.normalize_path(path, allow_root=False)
        if size < 0 or size > MAX_DOWNLOAD_BYTES:
            raise ReportingError("report_download_file_changed", "报告文件已变化。")

        # StreamingResponse 发送响应头后不能再改成结构化 409。先在 Daytona 内部计算
        # 当前文件身份，确保已签发的路径、大小和哈希在任何字节离开服务前仍然成立。
        try:
            current = await self.workspace_service.ahash_file(caller.thread_id, relative)
        except Exception as error:
            raise ReportingError("report_download_file_changed", "报告文件已变化。") from error
        current_sha256 = current.get("sha256")
        if (
            current.get("path") != relative
            or current.get("size") != size
            or not isinstance(current_sha256, str)
            or not secrets.compare_digest(current_sha256, sha256)
        ):
            raise ReportingError("report_download_file_changed", "报告文件已变化。")
        return grant, self._stream_verified_file(
            caller.thread_id,
            remote,
            expected_size=size,
            expected_sha256=sha256,
        )

    async def _stream_verified_file(
        self,
        thread_id: str,
        remote: str,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> AsyncIterator[bytes]:
        digest = hashlib.sha256()
        total = 0
        try:
            async with self.workspace_service._async_client() as client:
                sandbox = await self.workspace_service._asandbox_for(client, thread_id)
                stream = await sandbox.fs.download_file_stream(
                    remote,
                    timeout=MAX_ASYNC_DOWNLOAD_TIMEOUT,
                )
                async for chunk in stream:
                    if not isinstance(chunk, bytes):
                        raise ReportingError(
                            "report_download_file_changed", "报告文件已变化。"
                        )
                    total += len(chunk)
                    if total > expected_size:
                        raise ReportingError(
                            "report_download_file_changed", "报告文件已变化。"
                        )
                    digest.update(chunk)
                    yield chunk
        except ReportingError:
            raise
        except Exception as error:
            raise ReportingError("report_download_file_changed", "报告文件已变化。") from error

        # 预检与实际读取之间仍存在竞态窗口。传输过程中再次增量核验，不缓存完整
        # PDF/DOCX；发生漂移时终止响应，禁止把变化后的文件当成已签发产物交付。
        if total != expected_size or not secrets.compare_digest(
            digest.hexdigest(), expected_sha256
        ):
            raise ReportingError("report_download_file_changed", "报告文件已变化。")


CallerScopeDependency = Callable[
    ..., ReportDownloadCallerScope | Awaitable[ReportDownloadCallerScope]
]


def create_workspace_report_download_router(
    service: WorkspaceReportDownloadHttpService,
    *,
    scope_dependency: CallerScopeDependency,
) -> APIRouter:
    router = APIRouter()

    @router.get("/reports/v1/download/{opaque_grant}", name="download_workspace_report_pdf")
    async def download_workspace_report_pdf(
        opaque_grant: str,
        caller: ReportDownloadCallerScope = Depends(scope_dependency),
    ) -> StreamingResponse:
        try:
            grant, content = await service.stream(opaque_grant, caller=caller)
        except ReportingError as error:
            raise HTTPException(
                status_code=_download_error_status(error.code),
                detail={"code": error.code, "message": error.message},
            ) from None
        return StreamingResponse(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": _pdf_content_disposition(grant.pdf_path),
                "Content-Length": str(grant.pdf_size),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/reports/v1/download/{opaque_grant}/word", name="download_workspace_report_word")
    async def download_workspace_report_word(
        opaque_grant: str,
        caller: ReportDownloadCallerScope = Depends(scope_dependency),
    ) -> StreamingResponse:
        try:
            grant, content = await service.stream(opaque_grant, caller=caller, artifact="word")
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
                "Content-Disposition": _content_disposition(
                    grant.word_path or "report.docx", artifact="word"
                ),
                "Content-Length": str(word_size),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Accel-Buffering": "no",
            },
        )

    return router


def _pdf_content_disposition(pdf_path: str) -> str:
    return _content_disposition(pdf_path, artifact="pdf")


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


def _file_identity(path: Path) -> tuple[int, str]:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OSError
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        final_metadata = path.lstat()
    except OSError as error:
        raise ReportingError("report_download_file_changed", "报告文件已变化。") from error
    if (
        metadata.st_dev != final_metadata.st_dev
        or metadata.st_ino != final_metadata.st_ino
        or metadata.st_size != final_metadata.st_size
        or metadata.st_mtime_ns != final_metadata.st_mtime_ns
    ):
        raise ReportingError("report_download_file_changed", "报告文件已变化。")
    return metadata.st_size, digest.hexdigest()


def _grant_artifact(
    grant: ReportDownloadGrant,
    artifact: Literal["pdf", "word"],
) -> tuple[str, int, str]:
    if artifact == "pdf":
        return grant.pdf_path, grant.pdf_size, grant.pdf_sha256
    if grant.word_path is None or grant.word_size is None or grant.word_sha256 is None:
        raise ReportingError(
            "report_download_word_unavailable",
            "该旧版下载授权不包含 Word 产物。",
        )
    return grant.word_path, grant.word_size, grant.word_sha256


def _download_error_status(code: str) -> int:
    return {
        "report_download_scope_mismatch": 403,
        "report_download_grant_expired": 410,
        "report_download_revision_changed": 409,
        "report_download_file_changed": 409,
        "report_download_word_unavailable": 404,
    }.get(code, 404)
