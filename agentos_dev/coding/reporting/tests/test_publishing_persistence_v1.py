from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from agentos_dev.coding.reporting.publishing import (
    InMemoryDownloadGrantRepository,
    ReportDownloadCallerScope,
    ReportDownloadFileState,
    ReportDownloadGrantService,
    ReportDownloadHttpService,
    ReportDownloadScope,
    SqlAlchemyDownloadGrantRepository,
    WorkspaceReportDownloadHttpService,
    create_report_download_router,
    create_workspace_report_download_router,
    install_report_download_access_log_filter,
    report_download_grants,
)
from agentos_dev.coding.reporting.tests.workspace_fakes import (
    AsyncFakeClient,
    AsyncMemoryRegistry,
)
from agentos_dev.coding.reporting.tests.workspace_fakes import (
    service as workspace_service,
)
from agentos_dev.workspace import WORKSPACE_ROOT, WorkspaceService


def _scope(*, user_id: str = "user-1") -> ReportDownloadScope:
    return ReportDownloadScope(
        database="odoo-db",
        user_id=user_id,
        company_id="company-1",
        session_id="session-1",
        thread_id="thread-1",
        workflow_run_id="workflow-run-1",
    )


@pytest.mark.anyio
async def test_sqlalchemy仓库持久化全部scope且数据库不保存raw_grant(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'grants.db'}")
    repository = SqlAlchemyDownloadGrantRepository(engine)
    await repository.create_schema()
    service = ReportDownloadGrantService(repository)
    now = datetime(2026, 7, 28, 8, tzinfo=UTC)

    raw_grant, issued = await service.issue(
        scope=_scope(),
        report_id="report-1",
        revision=3,
        pdf_path="/srv/reports/report-1-r3.pdf",
        pdf_size=123,
        pdf_sha256="a" * 64,
        now=now,
    )

    restored = await SqlAlchemyDownloadGrantRepository(engine).get(issued.grant_hash)
    async with engine.connect() as connection:
        row = (await connection.execute(select(report_download_grants))).mappings().one()
    await engine.dispose()

    assert restored == issued
    assert row["database_name"] == "odoo-db"
    assert row["user_id"] == "user-1"
    assert row["company_id"] == "company-1"
    assert row["session_id"] == "session-1"
    assert row["thread_id"] == "thread-1"
    assert row["workflow_run_id"] == "workflow-run-1"
    assert raw_grant not in repr(dict(row))
    assert row["grant_hash"] == hashlib.sha256(raw_grant.encode()).hexdigest()


@pytest.mark.anyio
async def test_sqlalchemy撤销只影响相同report和scope(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'grants.db'}")
    repository = SqlAlchemyDownloadGrantRepository(engine)
    await repository.create_schema()
    service = ReportDownloadGrantService(repository)
    now = datetime(2026, 7, 28, 8, tzinfo=UTC)

    _raw_old, old = await service.issue(
        scope=_scope(),
        report_id="report-1",
        revision=1,
        pdf_path="/srv/reports/r1.pdf",
        pdf_size=1,
        pdf_sha256="a" * 64,
        now=now,
    )
    _raw_other, other = await service.issue(
        scope=_scope(user_id="user-2"),
        report_id="report-1",
        revision=1,
        pdf_path="/srv/reports/other.pdf",
        pdf_size=1,
        pdf_sha256="b" * 64,
        now=now,
    )
    await service.issue(
        scope=_scope(),
        report_id="report-1",
        revision=2,
        pdf_path="/srv/reports/r2.pdf",
        pdf_size=1,
        pdf_sha256="c" * 64,
        now=now,
    )

    assert (await repository.get(old.grant_hash)).revoked_at is not None  # type: ignore[union-attr]
    assert (await repository.get(other.grant_hash)).revoked_at is None  # type: ignore[union-attr]
    await engine.dispose()


class _CurrentReports:
    def __init__(self, state: ReportDownloadFileState | None):
        self.state = state

    async def get_current(
        self, report_id: str, scope: ReportDownloadScope
    ) -> ReportDownloadFileState | None:
        assert report_id == "report-1"
        assert scope.database == "odoo-db"
        return self.state


async def _download_client(
    tmp_path: Path,
    *,
    scope: ReportDownloadScope | None = None,
    revision: int = 1,
    issued_at: datetime | None = None,
) -> tuple[httpx.AsyncClient, str, Path, ReportDownloadGrantService, _CurrentReports]:
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nreport\n%%EOF")
    pdf_sha256 = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'route.db'}")
    repository = SqlAlchemyDownloadGrantRepository(engine)
    await repository.create_schema()
    grants = ReportDownloadGrantService(repository)
    raw_grant, _grant = await grants.issue(
        scope=_scope(),
        report_id="report-1",
        revision=1,
        pdf_path=str(pdf_path),
        pdf_size=pdf_path.stat().st_size,
        pdf_sha256=pdf_sha256,
        now=issued_at or datetime.now(UTC),
    )
    current = _CurrentReports(ReportDownloadFileState(revision=revision, pdf_path=str(pdf_path)))
    downloads = ReportDownloadHttpService(grants, current)

    async def current_scope() -> ReportDownloadScope:
        return scope or _scope()

    application = FastAPI()
    application.include_router(
        create_report_download_router(downloads, scope_dependency=current_scope)
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://testserver"
    )
    client._report_engine = engine  # type: ignore[attr-defined]
    return client, raw_grant, pdf_path, grants, current


async def _close_download_client(client: httpx.AsyncClient) -> None:
    engine = client._report_engine  # type: ignore[attr-defined]
    await client.aclose()
    await engine.dispose()


@pytest.mark.anyio
async def test_download路由返回pdf附件和禁止缓存响应头(tmp_path: Path):
    client, raw_grant, pdf_path, _grants, _current = await _download_client(tmp_path)
    try:
        response = await client.get(f"/reports/v1/download/{raw_grant}")
    finally:
        await _close_download_client(client)

    assert response.status_code == 200
    assert response.content == pdf_path.read_bytes()
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert str(pdf_path) not in response.headers["content-disposition"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    [
        ("scope", 403, "report_download_scope_mismatch"),
        ("revision", 409, "report_download_revision_changed"),
        ("file", 409, "report_download_file_changed"),
        ("revoked", 404, "report_download_grant_invalid"),
    ],
)
async def test_download路由拒绝跨scope_revision撤销和文件变化(
    tmp_path: Path, failure: str, expected_status: int, expected_code: str
):
    client, raw_grant, pdf_path, grants, current = await _download_client(
        tmp_path,
        scope=_scope(user_id="other") if failure == "scope" else None,
        revision=2 if failure == "revision" else 1,
    )
    if failure == "file":
        pdf_path.write_bytes(b"changed")
    if failure == "revoked":
        await grants.cancel("report-1", scope=_scope())
    try:
        response = await client.get(f"/reports/v1/download/{raw_grant}")
    finally:
        await _close_download_client(client)

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    assert str(pdf_path) not in response.text
    assert current.state is not None


@pytest.mark.anyio
async def test_download路由拒绝过期grant(tmp_path: Path):
    client, raw_grant, pdf_path, _grants, _current = await _download_client(
        tmp_path,
        issued_at=datetime.now(UTC) - timedelta(hours=25),
    )
    try:
        response = await client.get(f"/reports/v1/download/{raw_grant}")
    finally:
        await _close_download_client(client)

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "report_download_grant_expired"


def _caller(*, user_id: str = "user-1") -> ReportDownloadCallerScope:
    return ReportDownloadCallerScope(
        database="odoo-db",
        user_id=user_id,
        company_id="company-1",
        session_id="session-1",
        thread_id="thread-1",
    )


async def _workspace_download_client(
    tmp_path: Path,
    *,
    caller: ReportDownloadCallerScope | None = None,
    issued_at: datetime | None = None,
) -> tuple[
    httpx.AsyncClient,
    str,
    ReportDownloadGrantService,
    WorkspaceService,
]:
    content = b"%PDF-1.4\nworkspace report\n%%EOF"
    current = workspace_service(tmp_path)
    sandbox = current.sandbox_for("thread-1")
    sandbox.fs.create_folder(f"{WORKSPACE_ROOT}/reports", "0755")
    sandbox.fs.upload_file(content, f"{WORKSPACE_ROOT}/reports/result.pdf")
    async_workspace = WorkspaceService(
        current.secret,
        client=current.client,
        registry=current.registry,
        async_client=AsyncFakeClient(current.client),
        async_registry=AsyncMemoryRegistry(current.registry.values),
    )
    grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
    raw_grant, _grant = await grants.issue(
        scope=_scope(),
        report_id="report-1",
        revision=1,
        pdf_path="reports/result.pdf",
        pdf_size=len(content),
        pdf_sha256=hashlib.sha256(content).hexdigest(),
        now=issued_at or datetime.now(UTC),
    )
    downloads = WorkspaceReportDownloadHttpService(grants, async_workspace)

    async def current_scope() -> ReportDownloadCallerScope:
        return caller or _caller()

    application = FastAPI()
    application.include_router(
        create_workspace_report_download_router(downloads, scope_dependency=current_scope)
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://testserver"
    )
    return client, raw_grant, grants, async_workspace


@pytest.mark.anyio
async def test_workspace_download路由返回已授权pdf且不泄露内部路径(tmp_path: Path):
    client, raw_grant, _grants, _workspace = await _workspace_download_client(tmp_path)
    try:
        response = await client.get(f"/reports/v1/download/{raw_grant}")
    finally:
        await client.aclose()

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4\nworkspace report\n%%EOF"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == 'attachment; filename="report-r1.pdf"'
    assert "reports/result.pdf" not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    [
        ("scope", 403, "report_download_scope_mismatch"),
        ("file", 409, "report_download_file_changed"),
        ("revoked", 404, "report_download_grant_invalid"),
        ("expired", 410, "report_download_grant_expired"),
    ],
)
async def test_workspace_download路由拒绝跨scope文件变化撤销和过期(
    tmp_path: Path,
    failure: str,
    expected_status: int,
    expected_code: str,
):
    issued_at = datetime.now(UTC) - timedelta(hours=25) if failure == "expired" else None
    client, raw_grant, grants, workspace = await _workspace_download_client(
        tmp_path,
        caller=_caller(user_id="other") if failure == "scope" else None,
        issued_at=issued_at,
    )
    if failure == "file":
        async with workspace._async_client() as current_client:
            sandbox = await workspace._asandbox_for(current_client, "thread-1")
            await sandbox.fs.upload_file(b"changed", f"{WORKSPACE_ROOT}/reports/result.pdf")
    if failure == "revoked":
        await grants.cancel("report-1", scope=_scope())
    try:
        response = await client.get(f"/reports/v1/download/{raw_grant}")
    finally:
        await client.aclose()

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    assert "reports/result.pdf" not in response.text


def test_download_access_log过滤器移除raw_grant且重复安装幂等():
    logger = logging.Logger("report-download-test")
    install_report_download_access_log_filter(logger)
    install_report_download_access_log_filter(logger)
    record = logging.LogRecord(
        logger.name,
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:1234",
            "GET",
            "/reports/v1/download/raw-secret-grant?download=1",
            "1.1",
            200,
        ),
        None,
    )

    assert len(logger.filters) == 1
    assert logger.filters[0].filter(record) is True
    rendered = record.getMessage()
    assert "raw-secret-grant" not in rendered
    assert rendered == ('127.0.0.1:1234 - "GET /reports/v1/download/<redacted> HTTP/1.1" 200')
