"""PPTX 原生 AI 复用结构化 planner，候选必须先经过真实引擎。"""
from copy import deepcopy
from uuid import uuid4

import pytest

from smart_reporting.report_editor.native_models import NativeEditorContext, NATIVE_MEDIA
from smart_reporting.report_editor.slides_ai import SlidesAIProposal
from smart_reporting.reporting.models import ReportingError


def test_native_pptx_ai_accepts_bounded_text_style_fields_and_rejects_invalid_color():
    from smart_reporting.report_editor.slides_ai import _validate_proposal

    deck = {
        "size": {"cx": 9525000, "cy": 5400000},
        "slides": [{"slideIndex": 0, "elements": [{
            "id": "title", "editable": True, "text": "标题", "geometry": {"x": 0, "y": 0, "width": 100, "height": 40}
        }]}],
    }
    result = _validate_proposal({
        "summary": "调整标题样式", "order": [0], "edits": [{
            "slideIndex": 0, "elementId": "title", "fontSizePt": 24,
            "fontFamily": "Microsoft YaHei", "color": "#123456", "bold": True,
        }],
    }, {(0, "title"): deck["slides"][0]["elements"][0]}, deck)
    assert result["edits"][0]["fontSizePt"] == 24
    assert result["edits"][0]["bold"] is True
    with pytest.raises(ValueError, match="color"):
        _validate_proposal({
            "summary": "坏颜色", "order": [0], "edits":[{
                "slideIndex": 0, "elementId": "title", "color": "red"
            }]
        }, {(0, "title"): deck["slides"][0]["elements"][0]}, deck)


def test_native_pptx_style_candidate_merges_without_losing_manual_styles():
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService

    base = [{"kind": "editSlides", "textFormatting": [
        {"slideIndex": 0, "elementId": "title", "fontFamily": "Microsoft YaHei", "bold": True},
        {"slideIndex": 1, "elementId": "other", "italic": True},
    ]}]
    candidate = [{"kind": "editSlides", "edits": [], "textFormatting": [
        {"slideIndex": 0, "elementId": "title", "bold": False, "color": "#123456"},
    ]}]
    combined = NativeSlidesAIService._combined_operations(context(), base, candidate)
    assert combined[0]["textFormatting"] == [
        {"slideIndex": 0, "elementId": "title", "fontFamily": "Microsoft YaHei", "bold": False, "color": "#123456"},
        {"slideIndex": 1, "elementId": "other", "italic": True},
    ]
    assert base[0]["textFormatting"][0]["bold"] is True


def context():
    return NativeEditorContext(documentId="slides", revision=1, format="pptx", origin="upload",
        scope={"database": "db", "companyId": "co", "userId": "user", "threadId": "thread"},
        sourceFile={"path": "native/source.pptx", "size": 10, "sha256": "a" * 64, "mediaType": NATIVE_MEDIA["pptx"]})


class Editor:
    def __init__(self):
        self.context = context()
        self.previews = []

    async def context_for_session(self, _session):
        return self.context

    def require_enabled(self, format):
        assert format == "pptx"

    async def preview(self, _context, *, expected_sha256, operations):
        assert expected_sha256 == "a" * 64
        self.previews.append(deepcopy(operations))
        return {"draftSha256": "b" * 64, "model": {"size": {"cx": 9144000, "cy": 5143500},
            "slides": [{"slideIndex": i, "elements": [{"id": "title", "text": text, "editable": True,
                "geometry": {"x": 10, "y": 10, "width": 100, "height": 30}}]}
                for i, text in enumerate(["原文", "未选择的机密文字"])]}}


@pytest.mark.anyio
async def test_native_pptx_ai_uses_unsaved_selection_and_accepts_combined_snapshot():
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    editor = Editor()
    prompts = []

    async def planner(prompt, **_kwargs):
        prompts.append(prompt)
        return SlidesAIProposal(summary="润色标题", edits=[{"slideIndex": 0, "elementId": "title", "text": "候选标题"}], order=[0, 1])

    ai = NativeSlidesAIService(editor, planner=planner, enabled=True)
    base = [{"kind": "editSlides", "edits": [{"slideIndex": 0, "elementId": "title", "text": "人工未保存文字",
        "geometry": {"x": 20, "y": 10, "width": 100, "height": 30}}], "backgrounds": [{"slideIndex": 0, "color": "#123456"}]}]
    started = await ai.start_edit(None, client_request_id=uuid4().hex, instruction="润色", expected_sha256="a" * 64, operations=base, selection=[{"slideIndex": 0, "elementId": "title"}])
    result = await ai.wait_edit_status(None, started["editId"])
    assert result["status"] == "succeeded", result
    assert "人工未保存文字" in prompts[0] and "未选择的机密文字" not in prompts[0]
    assert result["accepted"] is False
    assert base[0]["edits"][0]["text"] == "人工未保存文字"
    accepted = await ai.accept_edit(None, started["editId"], expected_sha256="a" * 64, operations=base, snapshot_sha256=result["snapshotSha256"])
    assert accepted["operations"][0]["backgrounds"] == base[0]["backgrounds"]
    assert accepted["operations"][0]["edits"][0] == {**base[0]["edits"][0], "text": "候选标题"}
    assert len(accepted["operations"]) == 1
    changed = deepcopy(base); changed[0]["backgrounds"][0]["color"] = "#ffffff"
    with pytest.raises(ReportingError, match="完整草稿已变化"):
        await ai.accept_edit(None, started["editId"], expected_sha256="a" * 64, operations=changed, snapshot_sha256=result["snapshotSha256"])


@pytest.mark.anyio
@pytest.mark.parametrize("proposal", [
    {"summary": "越界", "edits": [{"slideIndex": 1, "elementId": "title", "text": "越界"}], "order": [0, 1]},
    {"summary": "越界页序", "edits": [], "order": [1, 0]},
    {"summary": "越界主题", "edits": [], "order": [0, 1], "theme": "modern"},
])
async def test_native_pptx_ai_rejects_changes_outside_selection(proposal):
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    async def planner(_prompt, **_kwargs):
        return SlidesAIProposal.model_validate(proposal)
    ai = NativeSlidesAIService(Editor(), planner=planner, enabled=True)
    started = await ai.start_edit(None, client_request_id=uuid4().hex, instruction="润色", expected_sha256="a" * 64, operations=[], selection=[{"slideIndex": 0, "elementId": "title"}])
    result = await ai.wait_edit_status(None, started["editId"])
    assert result["status"] == "failed"
    assert "proposal" not in result


@pytest.mark.anyio
async def test_native_pptx_ai_real_engine_previews_deck_candidate_and_independent_readback():
    import asyncio
    import hashlib
    from io import BytesIO
    from pptx import Presentation
    from pptx.util import Inches
    from smart_reporting.report_editor.native_office import inspect_office, patch_office
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    presentation = Presentation()
    for text in ["第一张", "第二张"]:
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = text
    stream = BytesIO(); presentation.save(stream); content = stream.getvalue()
    model = await asyncio.to_thread(inspect_office, "pptx", content)
    target = model["slides"][0]["elements"][0]["id"]

    class RealEditor(Editor):
        def __init__(self):
            super().__init__()
            raw = self.context.model_dump(by_alias=True)
            raw["sourceFile"].update(sha256=hashlib.sha256(content).hexdigest(), size=len(content))
            self.context = NativeEditorContext.model_validate(raw)

        async def preview(self, _context, *, expected_sha256, operations):
            assert expected_sha256 == self.context.source_file.sha256
            edited = await asyncio.to_thread(patch_office, "pptx", content, operations)
            self.previews.append(deepcopy(operations))
            return {"draftSha256": hashlib.sha256(edited).hexdigest(), "model": await asyncio.to_thread(inspect_office, "pptx", edited)}

    async def planner(prompt, **_kwargs):
        assert "人工标题" in prompt and "第二张" in prompt
        return SlidesAIProposal(summary="整稿调整", edits=[{"slideIndex": 0, "elementId": target, "text": "候选标题", "fontSizePt": 24, "color": "#123456", "bold": True}], order=[1, 0], theme="modern")

    editor = RealEditor(); ai = NativeSlidesAIService(editor, planner=planner, enabled=True)
    base = [{"kind": "editSlides", "edits": [{"slideIndex": 0, "elementId": target, "text": "人工标题"}], "backgrounds": [{"slideIndex": 0, "color": "#123456"}]}]
    started = await ai.start_edit(None, client_request_id=uuid4().hex, instruction="调整整稿并换主题", expected_sha256=editor.context.source_file.sha256, operations=base, selection=[], scope="deck")
    result = await ai.wait_edit_status(None, started["editId"])
    assert result["status"] == "succeeded", result
    accepted = await ai.accept_edit(None, started["editId"], expected_sha256=editor.context.source_file.sha256, operations=base, snapshot_sha256=result["snapshotSha256"])
    edited = await asyncio.to_thread(patch_office, "pptx", content, accepted["operations"])
    reopened = Presentation(BytesIO(edited))
    assert reopened.slides[0].shapes[0].text == "第二张"
    assert reopened.slides[1].shapes[0].text == "候选标题"
    run = reopened.slides[1].shapes[0].text_frame.paragraphs[0].runs[0]
    assert run.font.size.pt == 24
    assert run.font.bold is True
    assert str(run.font.color.rgb) == "123456"
    assert str(reopened.slides[1].background.fill.fore_color.rgb) == "123456"
    assert Presentation(BytesIO(content)).slides[0].shapes[0].text == "第一张"
    assert editor.previews[-1] == accepted["operations"]


@pytest.mark.anyio
async def test_native_pptx_ai_http_requires_csrf_version_scope_and_strict_selection():
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from types import SimpleNamespace
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    from smart_reporting.report_editor.slides_native_ai_api import create_native_slides_ai_router

    class Grants:
        def csrf_token(self, _raw):
            return "csrf"

        async def lookup_session(self, raw):
            if raw != "session":
                raise ReportingError("native_permission_denied", "无原生编辑授权")
            return SimpleNamespace(report_id="slides", revision=1)

    async def planner(_prompt, **_kwargs):
        return SlidesAIProposal(summary="候选", edits=[{"slideIndex": 0, "elementId": "title", "text": "候选"}], order=[0, 1])

    editor = Editor(); ai = NativeSlidesAIService(editor, planner=planner, enabled=True)
    app = FastAPI(); app.include_router(create_native_slides_ai_router(Grants(), editor=editor, ai=ai))
    base = "/reports/v1/native/slides/1/api/slides-ai"
    payload = {"clientRequestId": "http-fixture", "instruction": "润色", "expectedSha256": "a" * 64, "operations": [], "selection": [{"slideIndex": 0, "elementId": "title"}]}
    headers = {"Origin": "http://test", "X-CSRF-Token": "csrf"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies={NATIVE_SESSION_COOKIE: "session"}) as client:
        assert (await client.post(base + "/start", json=payload)).status_code == 403
        assert (await client.post(base.replace("/slides/1/", "/slides/2/") + "/start", json=payload, headers=headers)).status_code == 403
        assert (await client.post(base + "/start", json={**payload, "selection": [{"slideIndex": True, "elementId": "title"}]}, headers=headers)).status_code == 422
        assert (await client.post(base + "/start", json={**payload, "path": "/tmp/foreign.pptx"}, headers=headers)).status_code == 422
        cancellation = {"clientRequestId": "early-http-cancel"}
        assert (await client.post(base + "/cancel-request", json=cancellation)).status_code == 403
        cancelled = await client.post(base + "/cancel-request", json=cancellation, headers=headers)
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        early = await client.post(base + "/start", json={**payload, **cancellation}, headers=headers)
        assert early.json()["status"] == "cancelled" and early.json()["editId"] == cancelled.json()["editId"]
        started = await client.post(base + "/start", json=payload, headers=headers)
        assert started.status_code == 200, started.text
        edit_id = started.json()["editId"]
        replay = await client.post(base + "/start", json=payload, headers=headers)
        assert replay.status_code == 200 and replay.json()["editId"] == edit_id
        status = await client.get(base + "/" + edit_id)
        assert status.json()["status"] == "succeeded"
        acceptance = {"expectedSha256": "a" * 64, "operations": [], "snapshotSha256": status.json()["snapshotSha256"]}
        assert (await client.post(base + "/" + edit_id + "/accept", json=acceptance)).status_code == 403
        assert (await client.post(base + "/" + edit_id + "/accept", json={**acceptance, "snapshotSha256": "f" * 64}, headers=headers)).status_code == 409
        accepted = await client.post(base + "/" + edit_id + "/accept", json=acceptance, headers=headers)
        assert accepted.status_code == 200 and accepted.json()["accepted"] is True
        assert accepted.json()["operations"][0]["edits"][0]["text"] == "候选"
        raw = editor.context.model_dump(by_alias=True); raw["scope"]["companyId"] = "other"
        editor.context = NativeEditorContext.model_validate(raw)
        assert (await client.get(base + "/" + edit_id)).status_code == 404
    await ai.aclose()


@pytest.mark.anyio
async def test_native_pptx_ai_preserves_manual_order_for_selection_and_rejects_engine_failure():
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    async def planner(prompt, **_kwargs):
        assert "[1, 0]" in prompt
        return SlidesAIProposal(summary="保持人工页序", edits=[{"slideIndex": 0, "elementId": "title", "text": "候选"}], order=[1, 0])
    editor = Editor(); ai = NativeSlidesAIService(editor, planner=planner, enabled=True)
    base = [{"kind": "editSlides", "order": [1, 0]}]
    started = await ai.start_edit(None, client_request_id=uuid4().hex, instruction="润色所选对象", expected_sha256="a" * 64, operations=base, selection=[{"slideIndex": 0, "elementId": "title"}])
    result = await ai.wait_edit_status(None, started["editId"])
    assert result["status"] == "succeeded", result
    assert result["proposal"]["operations"][0]["order"] == [1, 0]
    original_preview = editor.preview
    async def failing_preview(context, *, expected_sha256, operations):
        if operations and operations[0].get("edits"):
            raise ValueError("real engine rejected layout")
        return await original_preview(context, expected_sha256=expected_sha256, operations=operations)
    editor.preview = failing_preview
    failed = await ai.start_edit(None, client_request_id=uuid4().hex, instruction="润色", expected_sha256="a" * 64, operations=base, selection=[{"slideIndex": 0, "elementId": "title"}])
    result = await ai.wait_edit_status(None, failed["editId"])
    assert result["status"] == "failed" and "proposal" not in result
    assert base == [{"kind": "editSlides", "order": [1, 0]}]


@pytest.mark.anyio
async def test_native_pptx_ai_cancel_stops_planner_without_adopting_candidate():
    import asyncio
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    entered = asyncio.Event()
    async def planner(_prompt, **_kwargs):
        entered.set()
        await asyncio.Event().wait()
    ai = NativeSlidesAIService(Editor(), planner=planner, enabled=True)
    started = await ai.start_edit(None, client_request_id=uuid4().hex, instruction="润色", expected_sha256="a" * 64, operations=[], selection=[{"slideIndex": 0, "elementId": "title"}])
    await entered.wait()
    result = await ai.cancel_edit(None, started["editId"])
    assert result["status"] == "cancelled" and result["accepted"] is False
    assert "proposal" not in result
    await ai.aclose()


@pytest.mark.anyio
async def test_native_pptx_ai_request_cancel_before_start_is_a_context_bound_tombstone():
    from unittest.mock import AsyncMock
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    planner = AsyncMock()
    editor = Editor(); ai = NativeSlidesAIService(editor, planner=planner, enabled=True)
    cancelled = await ai.cancel_request(None, "cancel-before-start")
    started = await ai.start_edit(None, client_request_id="cancel-before-start", instruction="润色", expected_sha256="a" * 64, operations=[], selection=[{"slideIndex": 0, "elementId": "title"}])
    assert started["status"] == "cancelled" and started["editId"] == cancelled["editId"]
    assert not editor.previews and not planner.called
    raw = editor.context.model_dump(by_alias=True); raw["scope"]["companyId"] = "different"
    editor.context = NativeEditorContext.model_validate(raw)
    other = await ai.cancel_request(None, "cancel-before-start")
    assert other["editId"] != cancelled["editId"]
    await ai.aclose()


@pytest.mark.anyio
async def test_native_pptx_ai_request_cancel_during_preflight_stops_planner_without_start_receipt():
    import asyncio
    from unittest.mock import AsyncMock
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    entered = asyncio.Event()
    class SlowEditor(Editor):
        async def preview(self, *args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
    planner = AsyncMock(); ai = NativeSlidesAIService(SlowEditor(), planner=planner, enabled=True)
    # 客户端丢失 start 回执，只凭请求身份仍须停止已在预览中的任务。
    await ai.start_edit(None, client_request_id="lost-receipt", instruction="润色", expected_sha256="a" * 64, operations=[], selection=[{"slideIndex": 0, "elementId": "title"}])
    await entered.wait()
    cancelled = await ai.cancel_request(None, "lost-receipt")
    assert cancelled["status"] == "cancelled" and not planner.called
    replay = await ai.start_edit(None, client_request_id="lost-receipt", instruction="润色", expected_sha256="a" * 64, operations=[], selection=[{"slideIndex": 0, "elementId": "title"}])
    assert replay["editId"] == cancelled["editId"] and replay["status"] == "cancelled"
    with pytest.raises(ReportingError, match="相同 AI 请求"):
        await ai.start_edit(None, client_request_id="lost-receipt", instruction="另一要求", expected_sha256="a" * 64, operations=[], selection=[{"slideIndex": 0, "elementId": "title"}])
    await ai.aclose()
