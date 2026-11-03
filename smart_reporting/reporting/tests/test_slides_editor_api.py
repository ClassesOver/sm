from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorContext,
    ReportEditorGrantService,
)
from smart_reporting.report_editor.slides_api import create_report_slides_editor_router
from smart_reporting.reporting.models import ReportingError


def _context() -> ReportEditorContext:
    return ReportEditorContext(
        reportId="slides-1",
        revision=4,
        jobId="job-1",
        workflowRunId="run-1",
        markdownPath="reports/report.md",
        job={"jobId": "job-1"},
        scope={"database": "db", "companyId": "company", "userId": "user"},
        deliveryFormat="pptx",
        pptxPath="reports/report.pptx",
        pptxSize=12,
        pptxSha256="a" * 64,
    )


class SlidesService:
    def __init__(self):
        self.calls = []

    async def context_for_session(self, session):
        if not session.capabilities or session.capabilities.get("pptx_editor") is not True:
            raise ReportingError("report_slides_permission_denied", "该会话没有幻灯片编辑权限。")
        return _context()

    async def document_for_session(self, session):
        return {"reportId": session.report_id, "revision": session.revision,
                "sha256": "a" * 64, "width": 1280, "height": 720, "slides": []}

    async def save_draft_for_session(self, session, *, expected_sha256, operations):
        self.calls.append(("save", expected_sha256, operations))
        if expected_sha256 != "a" * 64:
            raise ReportingError("report_slides_conflict", "草稿已变化，请重新载入。")
        return {**await self.document_for_session(session), "sha256": "b" * 64}

    async def export_for_session(self, session, *, expected_sha256, base_url):
        self.calls.append(("export", expected_sha256, base_url))
        return {"pptx": {"downloadUrl": f"{base_url}/download/report.pptx"},
                "validation": {"ok": False, "issues": [{"message": "需复核排版"}]}}


@pytest.mark.anyio
async def test_slides_editor_has_its_own_capability_and_cookie_path(tmp_path: Path):
    index = tmp_path / "index.html"
    index.write_text("<main>slides</main>", encoding="utf-8")
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _expires = await grants.issue(
        _context(), capabilities={"pptx_editor": True}
    )
    app = FastAPI()
    app.include_router(create_report_slides_editor_router(
        grants, slides=SlidesService(), static_dir=tmp_path, cookie_secure=False,
    ))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        opened = await client.get(f"/reports/v1/slides/open/{raw}", follow_redirects=False)
        page = await client.get(opened.headers["location"])

    assert opened.status_code == 303
    assert opened.headers["location"] == "/reports/v1/slides/slides-1/4"
    assert "Path=/reports/v1/slides/slides-1/4" in opened.headers["set-cookie"]
    assert "HttpOnly" in opened.headers["set-cookie"]
    assert page.status_code == 200
    assert page.text == "<main>slides</main>"


@pytest.mark.anyio
async def test_slides_editor_does_not_exchange_document_only_grants(tmp_path: Path):
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _expires = await grants.issue(_context())
    app = FastAPI()
    app.include_router(create_report_slides_editor_router(
        grants, slides=SlidesService(), static_dir=tmp_path, cookie_secure=False,
    ))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        response = await client.get(f"/reports/v1/slides/open/{raw}", follow_redirects=False)

    assert response.status_code == 403


@pytest.mark.anyio
@pytest.mark.parametrize("allowed_origin", [None, "https://reports.public.example"])
async def test_slides_editor_document_save_and_export_use_same_session(tmp_path: Path, allowed_origin):
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _ = await grants.issue(_context(), capabilities={"pptx_editor": True})
    slides = SlidesService()
    app = FastAPI()
    app.include_router(create_report_slides_editor_router(
        grants, slides=slides, static_dir=tmp_path, cookie_secure=False, allowed_origin=allowed_origin,
    ))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        opened = await client.get(f"/reports/v1/slides/open/{raw}")
        path = opened.headers["location"]
        document = await client.get(f"{path}/document")
        assert document.status_code == 200
        assert document.headers["cache-control"] == "no-store"
        headers = {"origin": "http://reports.test", "x-csrf-token": document.json()["csrfToken"]}
        operations = [{"op": "update", "slide": 0, "id": "title", "text": "新标题"}]
        saved = await client.put(f"{path}/draft", headers=headers, json={
            "expectedSha256": "a" * 64, "operations": operations,
        })
        assert saved.status_code == 200
        assert saved.json()["sha256"] == "b" * 64
        assert saved.json()["csrfToken"] == document.json()["csrfToken"]
        exported = await client.post(f"{path}/export", headers=headers, json={"expectedSha256": "b" * 64})
        assert exported.status_code == 200
        assert exported.json()["pptx"]["downloadUrl"] == "http://reports.test/download/report.pptx"
        assert exported.json()["validation"]["ok"] is False
        conflict = await client.put(f"{path}/draft", headers=headers, json={
            "expectedSha256": "c" * 64, "operations": operations,
        })
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "report_slides_conflict"
    assert slides.calls[:2] == [
        ("save", "a" * 64, operations), ("export", "b" * 64, "http://reports.test"),
    ]


@pytest.mark.anyio
async def test_slides_editor_serves_built_assets_without_revision_route_shadowing(tmp_path: Path):
    (tmp_path / "entry.js").write_text("export {}", encoding="utf-8")
    app = FastAPI()
    app.include_router(create_report_slides_editor_router(
        ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32),
        slides=SlidesService(), static_dir=tmp_path,
    ))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        response = await client.get("/reports/v1/slides/assets/entry.js")
    assert response.status_code == 200
    assert response.text == "export {}"
