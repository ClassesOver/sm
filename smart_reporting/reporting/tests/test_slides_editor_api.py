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
        self.saved_chart_replacements = []

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

    async def save_revision(self, session, payload, *, images=None, chart_replacements=None):
        assert session.capabilities.get("pptx_editor") is True
        assert payload["expectedSha256"] == "a" * 64
        self.saved_images = images or []
        self.saved_chart_replacements = chart_replacements or []
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
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "unified-main.js").write_text("console.log('slides')", encoding="utf-8")
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
        asset = await client.get("/reports/v1/slides/assets/unified-main.js")
        traversal = await client.get("/reports/v1/slides/assets/../slides.html")

    assert opened.status_code == 303
    assert opened.headers["location"] == "/reports/v1/slides/slides-1/4"
    assert "Path=/reports/v1/slides/slides-1/4" in opened.headers["set-cookie"]
    assert "HttpOnly" in opened.headers["set-cookie"]
    assert page.status_code == 200
    assert page.text == "<main>slides</main>"
    assert asset.status_code == 200
    assert asset.text == "console.log('slides')"
    assert traversal.status_code == 404


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
@pytest.mark.parametrize(
    ("pptx_path", "ascii_name", "encoded_name"),
    [
        ("reports/report.pptx", "report.pptx", "report.pptx"),
        # 报告标题通常含中文：响应头只能是 latin-1，曾因此返回 500。
        ("报表/智能分析/run-1/revision-1/医院运营分析报告_2025.pptx", "report.pptx",
         "%E5%8C%BB%E9%99%A2%E8%BF%90%E8%90%A5%E5%88%86%E6%9E%90%E6%8A%A5%E5%91%8A_2025.pptx"),
    ],
)
async def test_pptx_download_uses_a_separate_capability_grant(pptx_path, ascii_name, encoded_name):
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _expires = await grants.issue(_context(), capabilities={"pptx_download": True})

    class NamedSlidesService(SlidesService):
        async def download_for_session(self, session):
            context, content = await super().download_for_session(session)
            return context.model_copy(update={"pptx_path": pptx_path}), content

    app = FastAPI()
    app.include_router(create_report_slides_editor_router(
        grants, slides=NamedSlidesService(), static_dir=Path("."), cookie_secure=False,
    ))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        response = await client.get(f"/reports/v1/slides/download/{raw}")

    assert response.status_code == 200
    assert response.content == b"PPTX-bytes"
    assert response.headers["content-disposition"] == (
        f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"
    )


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


@pytest.mark.anyio
async def test_slides_chart_candidates_require_csrf_and_are_applied_only_on_save(tmp_path):
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _expires = await grants.issue(_context(), capabilities={'pptx_editor': True})
    slides = SlidesService()
    target = {'slideIndex': 0, 'elementId': 'picture-1', 'chartId': 'chart_001'}

    class Charts:
        discarded = []

        async def list_charts(self, session):
            assert session.capabilities == {'pptx_editor': True}
            return {'charts': [{**target, 'available': True}]}

        async def start_edit(self, session, slide_index, element_id, instruction):
            assert (slide_index, element_id, instruction) == (0, 'picture-1', '调整颜色')
            return {'candidateId': 'chart-edit-1', 'status': 'running'}

        async def edit_status(self, session, candidate_id, *, wait_ms):
            assert candidate_id == 'chart-edit-1' and wait_ms == 5
            return {'status': 'succeeded', 'previewDataUrl': 'data:image/png;base64,cG5n'}

        async def resolve_for_session(self, session, edits):
            assert edits == [{'candidateId': 'chart-edit-1'}]
            return [{**target, 'candidateId': 'chart-edit-1', 'bytes': b'chart-png'}]

        async def discard_candidates(self, session, candidates):
            self.discarded.extend(candidates)

    charts = Charts()
    app = FastAPI()
    app.include_router(create_report_slides_editor_router(
        grants, slides=slides, slides_charts=charts, static_dir=tmp_path, cookie_secure=False,
    ))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        opened = await client.get(f'/reports/v1/slides/open/{raw}', follow_redirects=False)
        path = opened.headers['location']
        listing = await client.get(f'{path}/api/charts')
        assert listing.json()['charts'][0]['chartId'] == 'chart_001'
        payload = {'slideIndex': 0, 'elementId': 'picture-1', 'instruction': '调整颜色'}
        rejected = await client.post(f'{path}/api/charts/start', json=payload)
        assert rejected.status_code == 403
        csrf = grants.csrf_token(client.cookies.get('report_slides_session') or '')
        headers = {'X-CSRF-Token': csrf}
        started = await client.post(f'{path}/api/charts/start', json=payload, headers=headers)
        assert started.json()['candidateId'] == 'chart-edit-1'
        status = await client.get(f'{path}/api/charts/chart-edit-1?wait_ms=5')
        assert status.json()['previewDataUrl'].startswith('data:image/png;')
        invalid_wait = await client.get(f'{path}/api/charts/chart-edit-1?wait_ms=1501')
        assert invalid_wait.status_code == 422
        assert not slides.saved_chart_replacements
        save = {'expectedSha256': 'a' * 64, 'chartEdits': [{'candidateId': 'chart-edit-1'}]}
        rejected = await client.post(f'{path}/api/save', json=save)
        assert rejected.status_code == 403
        saved = await client.post(f'{path}/api/save', json=save, headers=headers)
        assert saved.status_code == 200
        foreign = await client.get('/reports/v1/slides/foreign/4/api/charts')
        assert foreign.status_code == 404
    assert slides.saved_chart_replacements[0]['bytes'] == b'chart-png'
    assert charts.discarded == ['chart-edit-1']


@pytest.mark.anyio
async def test_slides_render_preview_requires_csrf_and_scoped_session(tmp_path: Path):
    class RenderSlidesService(SlidesService):
        async def render_tree_for_session(self, session, preview=None):
            await self.context_for_session(session)
            return {"revision": session.revision, "preview": preview, "slides": []}

    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _expires = await grants.issue(_context(), capabilities={"pptx_editor": True})
    app = FastAPI()
    app.include_router(create_report_slides_editor_router(
        grants, slides=RenderSlidesService(), static_dir=tmp_path, cookie_secure=False,
    ))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        opened = await client.get(f"/reports/v1/slides/open/{raw}", follow_redirects=False)
        path = opened.headers["location"]
        tree = await client.get(f"{path}/api/render-tree")
        denied = await client.post(f"{path}/api/render-tree", json={"edits": []})
        csrf = grants.csrf_token(client.cookies.get("report_slides_session") or "")
        preview = await client.post(f"{path}/api/render-tree", json={"edits": []}, headers={"X-CSRF-Token": csrf})
        outside = await client.get("/reports/v1/slides/other-report/4/api/render-tree")
    assert tree.status_code == 200
    assert tree.json()["revision"] == 4
    assert denied.status_code == 403
    assert preview.status_code == 200
    assert preview.json()["preview"] == {"edits": []}
    assert outside.status_code in {403, 404}
