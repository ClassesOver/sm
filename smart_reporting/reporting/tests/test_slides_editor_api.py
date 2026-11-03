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
from smart_reporting.report_editor.slides_api import (
    SLIDES_CSRF_COOKIE,
    create_report_slides_editor_router,
)
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
        self.saved_images = []

    async def context_for_session(self, session):
        if not session.capabilities or session.capabilities.get("pptx_editor") is not True:
            raise ReportingError("report_slides_permission_denied", "该会话没有幻灯片编辑权限。")
        return _context()

    async def deck_for_session(self, session):
        assert session.capabilities.get("pptx_editor") is True
        return {"revision": session.revision, "slides": [{"title": "经营概览"}]}

    async def preview_pdf(self, session):
        assert session.capabilities.get("pptx_editor") is True
        return b"%PDF-test"

    async def save_revision(self, session, payload, *, images=None):
        assert session.capabilities.get("pptx_editor") is True
        assert payload["expectedSha256"] == "a" * 64
        self.saved_images = images or []
        return {"revision": session.revision + 1, "pptx": {"downloadUrl": "/download"}}

    async def download_for_session(self, session):
        if not session.capabilities or session.capabilities.get("pptx_download") is not True:
            raise ReportingError("report_slides_permission_denied", "该会话没有下载权限。")
        return _context(), b"PPTX-bytes"


class SlidesAIService:
    async def start_edit(self, session, instruction):
        assert session.capabilities.get("pptx_editor") is True
        return {"editId": "edit-1", "status": "running", "instruction": instruction}

    async def wait_edit_status(self, session, edit_id, *, wait_ms=20_000):
        assert session.capabilities.get("pptx_editor") is True
        return {"editId": edit_id, "status": "succeeded", "proposal": {"summary": "调整标题"}}

    async def cancel_edit(self, session, edit_id):
        assert session.capabilities.get("pptx_editor") is True
        return {"editId": edit_id, "status": "cancelled"}

    async def mark_accepted(self, session, edit_id):
        assert session.capabilities.get("pptx_editor") is True
        return {"editId": edit_id, "accepted": True}


class SlidesImageService:
    def __init__(self):
        self.discarded = []

    async def generate_candidate(self, session, prompt):
        assert session.capabilities.get("pptx_editor") is True
        return {"candidateId": "image-1", "mediaType": "image/png", "previewDataUrl": "data:image/png;base64,AA==", "prompt": prompt}

    async def resolve_for_session(self, session, edits):
        assert session.capabilities.get("pptx_editor") is True
        assert edits[0]["candidateId"] == "image-1"
        return [{"candidateId": "image-1", "slideIndex": 0, "bytes": b"png", "extension": "png"}]

    async def discard_candidates(self, _session, candidate_ids):
        self.discarded.extend(candidate_ids)


@pytest.mark.anyio
async def test_slides_editor_has_its_own_capability_and_cookie_path(tmp_path: Path):
    index = tmp_path / "slides.html"
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
async def test_slides_api_reads_deck_previews_and_saves_only_inside_slides_session(tmp_path: Path):
    index = tmp_path / "slides.html"
    index.write_text("<main>slides</main>", encoding="utf-8")
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _expires = await grants.issue(_context(), capabilities={"pptx_editor": True})
    app = FastAPI()
    app.include_router(create_report_slides_editor_router(
        grants, slides=SlidesService(), static_dir=tmp_path, cookie_secure=False,
    ))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        opened = await client.get(f"/reports/v1/slides/open/{raw}", follow_redirects=False)
        path = opened.headers["location"]
        await client.get(path)
        deck = await client.get(f"{path}/api/deck")
        preview = await client.get(f"{path}/api/preview.pdf")
        rejected_save = await client.post(
            f"{path}/api/save", json={"expectedSha256": "a" * 64}
        )
        raw_session = client.cookies.get("report_slides_session") or ""
        csrf = grants.csrf_token(raw_session)
        saved = await client.post(
            f"{path}/api/save",
            json={"expectedSha256": "a" * 64},
            headers={"X-CSRF-Token": csrf},
        )

    assert deck.status_code == 200
    assert SLIDES_CSRF_COOKIE in opened.headers["set-cookie"]
    assert deck.json() == {"revision": 4, "slides": [{"title": "经营概览"}]}
    assert preview.status_code == 200
    assert preview.content == b"%PDF-test"
    assert rejected_save.status_code == 403
    assert saved.status_code == 200
    assert saved.json()["revision"] == 5


@pytest.mark.anyio
async def test_pptx_download_uses_a_separate_capability_grant():
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _expires = await grants.issue(_context(), capabilities={"pptx_download": True})
    app = FastAPI()
    app.include_router(create_report_slides_editor_router(
        grants, slides=SlidesService(), static_dir=Path("."), cookie_secure=False,
    ))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        response = await client.get(f"/reports/v1/slides/download/{raw}")

    assert response.status_code == 200
    assert response.content == b"PPTX-bytes"
    assert response.headers["content-disposition"].endswith('filename="report.pptx"')


@pytest.mark.anyio
async def test_slides_ai_requires_csrf_and_is_scoped_to_ppt_editor_session(tmp_path: Path):
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _expires = await grants.issue(_context(), capabilities={"pptx_editor": True})
    app = FastAPI()
    app.include_router(create_report_slides_editor_router(
        grants,
        slides=SlidesService(),
        slides_ai=SlidesAIService(),
        static_dir=tmp_path,
        cookie_secure=False,
    ))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        opened = await client.get(f"/reports/v1/slides/open/{raw}", follow_redirects=False)
        path = opened.headers["location"]
        await client.get(path)
        rejected = await client.post(f"{path}/api/ai/start", json={"instruction": "改标题"})
        csrf = grants.csrf_token(client.cookies.get("report_slides_session") or "")
        started = await client.post(
            f"{path}/api/ai/start",
            json={"instruction": "改标题"},
            headers={"X-CSRF-Token": csrf},
        )
        status = await client.get(f"{path}/api/ai/edit-1?wait_ms=5")
        accepted = await client.post(
            f"{path}/api/ai/edit-1/accept", headers={"X-CSRF-Token": csrf}
        )

    assert rejected.status_code == 403
    assert started.status_code == 200
    assert started.json()["editId"] == "edit-1"
    assert status.json()["proposal"]["summary"] == "调整标题"
    assert accepted.json()["accepted"] is True


@pytest.mark.anyio
async def test_slides_image_candidates_require_csrf_and_are_added_only_on_revision_save(tmp_path: Path):
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _expires = await grants.issue(_context(), capabilities={"pptx_editor": True})
    slides = SlidesService()
    images = SlidesImageService()
    app = FastAPI()
    app.include_router(create_report_slides_editor_router(
        grants,
        slides=slides,
        slides_images=images,
        static_dir=tmp_path,
        cookie_secure=False,
    ))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        opened = await client.get(f"/reports/v1/slides/open/{raw}", follow_redirects=False)
        path = opened.headers["location"]
        await client.get(path)
        rejected = await client.post(f"{path}/api/ai/image", json={"prompt": "插画"})
        csrf = grants.csrf_token(client.cookies.get("report_slides_session") or "")
        generated = await client.post(
            f"{path}/api/ai/image",
            json={"prompt": "医疗空间"},
            headers={"X-CSRF-Token": csrf},
        )
        saved = await client.post(
            f"{path}/api/save",
            json={"expectedSha256": "a" * 64, "edits": [], "order": [0], "imageEdits": [
                {"candidateId": "image-1", "slideIndex": 0, "geometry": {"x": 0, "y": 0, "width": 100, "height": 80}}
            ]},
            headers={"X-CSRF-Token": csrf},
        )

    assert rejected.status_code == 403
    assert generated.status_code == 200
    assert generated.json()["candidateId"] == "image-1"
    assert saved.status_code == 200
    assert slides.saved_images[0]["bytes"] == b"png"
    assert images.discarded == ["image-1"]
