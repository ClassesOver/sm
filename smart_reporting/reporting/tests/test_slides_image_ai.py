from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from smart_reporting.report_editor.service import ReportEditorContext, ReportEditorSession
from smart_reporting.report_editor.slides_image_ai import ReportSlidesImageService
from smart_reporting.reporting.models import ReportingError


def _context() -> ReportEditorContext:
    return ReportEditorContext(
        reportId="image-report",
        revision=3,
        jobId="job-image",
        workflowRunId="run-image",
        markdownPath="reports/report.md",
        job={"jobId": "job-image"},
        scope={"database": "db", "companyId": "company", "userId": "user", "sessionId": "session", "threadId": "thread"},
        deliveryFormat="pptx",
        pptxPath="reports/report.pptx",
        pptxSize=10,
        pptxSha256="a" * 64,
    )


def _session(context: ReportEditorContext | None = None) -> ReportEditorSession:
    context = context or _context()
    return ReportEditorSession(
        report_id=context.report_id,
        revision=context.revision,
        workflow_run_id=context.workflow_run_id,
        context_sha256=context.digest(),
        expires_at=datetime.now(UTC),
        capabilities={"pptx_editor": True},
    )


class FakeSlides:
    def __init__(self, context: ReportEditorContext | None = None):
        self.context = context or _context()

    async def context_for_session(self, _session):
        return self.context

    async def deck_for_session(self, _session):
        return {"slides": [{"slideIndex": 0}, {"slideIndex": 1}], "size": {"cx": 9144000, "cy": 5143500}}


@pytest.mark.anyio
async def test_image_generation_returns_reviewable_scoped_candidate():
    png = b"\x89PNG\r\n\x1a\nimage"
    calls = []

    async def handler(request: httpx.Request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"data": [{"url": "https://dashscope-result.oss-cn-hangzhou.aliyuncs.com/image.png"}]})
        return httpx.Response(200, headers={"content-type": "image/png"}, content=png)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = ReportSlidesImageService(
        FakeSlides(), api_key="test-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-image-plus", client=client,
    )
    result = await service.generate_candidate(_session(), "医疗服务大厅的抽象插画")
    resolved = await service.resolve_for_session(_session(), [{
        "candidateId": result["candidateId"], "slideIndex": 1,
        "geometry": {"x": 20, "y": 30, "width": 400, "height": 220},
    }])

    assert result["mediaType"] == "image/png"
    assert result["previewDataUrl"].startswith("data:image/png;base64,")
    assert calls[0].url.path.endswith("/images/generations")
    assert calls[0].headers["authorization"] == "Bearer test-key"
    assert resolved[0]["slideIndex"] == 1
    assert resolved[0]["bytes"] == png
    await client.aclose()


@pytest.mark.anyio
async def test_image_generation_rejects_provider_urls_outside_dashscope_storage():
    async def handler(request: httpx.Request):
        return httpx.Response(200, json={"data": [{"url": "http://127.0.0.1/private"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = ReportSlidesImageService(
        FakeSlides(), api_key="test-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-image-plus", client=client,
    )

    with pytest.raises(ReportingError, match="配图生成失败"):
        await service.generate_candidate(_session(), "插画")
    await client.aclose()


@pytest.mark.anyio
async def test_image_candidates_are_bound_to_report_revision_and_geometry():
    async def handler(request: httpx.Request):
        if request.method == "POST":
            return httpx.Response(200, json={"data": [{"url": "https://images.aliyuncs.com/a.png"}]})
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"\x89PNG\r\n\x1a\nimg")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = ReportSlidesImageService(
        FakeSlides(), api_key="test-key", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-image-plus", client=client,
    )
    result = await service.generate_candidate(_session(), "插画")
    other_context = _context().model_copy(update={"revision": 4})
    service.slides = FakeSlides(other_context)
    other = _session(other_context)

    with pytest.raises(ReportingError, match="候选已失效"):
        await service.resolve_for_session(other, [{
            "candidateId": result["candidateId"], "slideIndex": 0,
            "geometry": {"x": 0, "y": 0, "width": 100, "height": 100},
        }])
    service.slides = FakeSlides()
    with pytest.raises(ReportingError, match="位置或大小无效"):
        await service.resolve_for_session(_session(), [{
            "candidateId": result["candidateId"], "slideIndex": 0,
            "geometry": {"x": 0, "y": 0, "width": 2000, "height": 100},
        }])
    await client.aclose()
