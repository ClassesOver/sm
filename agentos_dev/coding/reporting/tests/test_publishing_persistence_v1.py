from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from agentos_dev.coding.reporting.delivery.publishing import (
    InMemoryDownloadGrantRepository,
    ReportDownloadCallerScope,
    ReportDownloadGrantService,
    ReportDownloadScope,
    WorkspaceReportDownloadHttpService,
    create_workspace_report_download_router,
    install_report_download_access_log_filter,
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
    filename = "收入分析报告_2025-01-01至2025-12-31.pdf"
    sandbox.fs.upload_file(content, f"{WORKSPACE_ROOT}/reports/{filename}")
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
        pdf_path=f"reports/{filename}",
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
    assert response.headers["content-disposition"] == (
        'attachment; filename="report.pdf"; '
        "filename*=UTF-8''%E6%94%B6%E5%85%A5%E5%88%86%E6%9E%90%E6%8A%A5%E5%91%8A_"
        "2025-01-01%E8%87%B32025-12-31.pdf"
    )
    assert "reports/收入分析报告_2025-01-01至2025-12-31.pdf" not in response.text


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
            await sandbox.fs.upload_file(
                b"changed",
                f"{WORKSPACE_ROOT}/reports/收入分析报告_2025-01-01至2025-12-31.pdf",
            )
    if failure == "revoked":
        await grants.cancel("report-1", scope=_scope())
    try:
        response = await client.get(f"/reports/v1/download/{raw_grant}")
    finally:
        await client.aclose()

    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    assert "reports/收入分析报告_2025-01-01至2025-12-31.pdf" not in response.text


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
