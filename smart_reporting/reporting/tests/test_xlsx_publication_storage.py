from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportArtifactSpec,
    ReportDownloadGrantService,
    ReportDownloadHttpService,
    ReportDownloadScope,
    create_report_download_router,
)
from smart_reporting.reporting.tests.delivery_fakes import (
    InMemoryDownloadGrantRepository,
    InMemoryReportArtifactRepository,
)
from smart_reporting.workspace import normalize_workspace_path


class _Workspace:
    normalize_path = staticmethod(normalize_workspace_path)

    def __init__(self, files):
        self.files = files

    async def read_limited_regular_file(self, thread_id, path, *, max_bytes):
        content = self.files[path]
        if len(content) > max_bytes:
            raise ValueError("file too large")
        return content

    async def aiter_regular_file_chunks(self, thread_id, path, *, max_bytes, chunk_size):
        content = await self.read_limited_regular_file(thread_id, path, max_bytes=max_bytes)
        yield content

    def remove_files(self):
        self.files.clear()


def _scope() -> ReportDownloadScope:
    return ReportDownloadScope("database", "7", "3", "session", "thread", "run")


@pytest.mark.anyio
async def test_xlsx_download_remains_available_after_workspace_cleanup() -> None:
    content = b"xlsx-package-identity"
    digest = hashlib.sha256(content).hexdigest()
    workspace = _Workspace({"reports/经营分析.xlsx": content})
    artifacts = InMemoryReportArtifactRepository()
    grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
    await ReportArtifactPersistenceService(artifacts, workspace).persist(
        scope=_scope(), report_id="report", revision=1,
        artifacts=(ReportArtifactSpec("xlsx", "reports/经营分析.xlsx", len(content), digest),),
    )
    raw, grant = await grants.issue(
        scope=_scope(), report_id="report", revision=1,
        xlsx_path="reports/经营分析.xlsx", xlsx_size=len(content), xlsx_sha256=digest,
    )
    workspace.remove_files()
    assert grant.xlsx_sha256 == digest
    assert not (grant.pdf_path or grant.word_path or grant.pptx_path)
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(grants, artifacts)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/reports/v1/download/{raw}/xlsx")
        absent = await client.get(f"/reports/v1/download/{raw}")
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert ".xlsx" in response.headers["content-disposition"]
    assert absent.status_code == 404


@pytest.mark.anyio
async def test_verified_xlsx_can_download_from_retained_workspace_when_storage_is_down() -> None:
    content = b"retained-workbook"
    workspace = _Workspace({"reports/report.xlsx": content})
    grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
    raw, _ = await grants.issue(
        scope=_scope(), report_id="report", revision=1,
        xlsx_path="reports/report.xlsx", xlsx_size=len(content),
        xlsx_sha256=hashlib.sha256(content).hexdigest(),
    )
    service = ReportDownloadHttpService(
        grants, InMemoryReportArtifactRepository(), workspace_service=workspace,
    )
    app = FastAPI()
    app.include_router(create_report_download_router(service))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/reports/v1/download/{raw}/xlsx")
        assert response.status_code == 200
        assert response.content == content
        workspace.files["reports/report.xlsx"] = b"changed-workbook"
        changed = await client.get(f"/reports/v1/download/{raw}/xlsx")
        assert changed.status_code == 409


@pytest.mark.anyio
async def test_workspace_fallback_handles_unavailable_artifact_metadata() -> None:
    content = b"verified-workbook"
    grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
    raw, _ = await grants.issue(
        scope=_scope(), report_id="report", revision=1,
        xlsx_path="reports/report.xlsx", xlsx_size=len(content),
        xlsx_sha256=hashlib.sha256(content).hexdigest(),
    )

    class UnavailableArtifacts(InMemoryReportArtifactRepository):
        async def get(self, artifact_key):
            raise OSError("artifact metadata unavailable")

    service = ReportDownloadHttpService(
        grants, UnavailableArtifacts(),
        workspace_service=_Workspace({"reports/report.xlsx": content}),
    )
    _, stream = await service.stream(raw, artifact="xlsx")
    assert b"".join([chunk async for chunk in stream]) == content
