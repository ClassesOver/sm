"""处理批注任务终态、快照和实际预览边界。"""

import asyncio
import hashlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests import test_native_ai

pdf_sample = test_native_ai.pdf_sample


@pytest.fixture
async def review_sample(pdf_sample):
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import Text
    from pypdf.generic import NameObject, TextStringObject
    from smart_reporting.report_editor.native import bind_native_workspace

    editor, context, _, _, original = pdf_sample
    writer = PdfWriter(clone_from=PdfReader(BytesIO(original)))
    note = Text(rect=(30, 210, 50, 230), text="Change Amount due 500 to Amount due 700.")
    note[NameObject("/T")] = TextStringObject("Reviewer")
    writer.add_annotation(0, note)
    stream = BytesIO()
    writer.write(stream)
    source = stream.getvalue()
    context = context.model_copy(
        update={
            "source_file": context.source_file.model_copy(
                update={
                    "path": "native/review-source.pdf",
                    "size": len(source),
                    "sha256": hashlib.sha256(source).hexdigest(),
                }
            )
        }
    )
    key = bind_native_workspace(editor.workspace, context.scope)
    await editor.workspace.awrite_bytes(key, context.source_file.path, source)
    editor.repository.get_revision.return_value = SimpleNamespace(status="saved", context=context)
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    token, session = await editor.grants.exchange(raw)
    return editor, context, session, token, source


async def actual_candidates(*, reader, **kwargs):
    from smart_reporting.report_editor.native_pdf_review_ai import NativePDFReviewTools

    tools = NativePDFReviewTools(reader)
    note = tools.read_annotations()["annotations"][0]
    tools.read_pages()
    tools.propose_replace_text(
        note["annotationId"], 1, "Amount due 500", "Amount due 700", "按批注更正"
    )
    tools.propose_reply(note["annotationId"], "已将应付金额由500改为700。")
    return tools.result("已提出原位改字及 AI 身份回复候选，待采纳。")


async def actual_markup_candidate(*, reader, **kwargs):
    from smart_reporting.report_editor.native_pdf_review_ai import NativePDFReviewTools

    tools = NativePDFReviewTools(reader)
    note = tools.read_annotations()["annotations"][0]
    tools.read_pages(start_page=1)
    text = next(
        obj["text"] for obj in reader.pages[0]["textObjects"] if "Amount due 500" in obj["text"]
    )
    tools.propose_markup(note["annotationId"], 1, text, "highlight", "重点核对金额")
    return tools.result("已提出文字高亮候选，待采纳。")


def service(editor, planner):
    from smart_reporting.report_editor.native_pdf_review_ai_tasks import NativePDFReviewService

    return NativePDFReviewService(editor, planner=planner, enabled=True)


def payload(context, **kwargs):
    return {
        "client_request_id": "review-1",
        "expected_sha256": context.source_file.sha256,
        "operations": [],
        "instruction": "处理批注",
        **kwargs,
    }


@pytest.mark.anyio
async def test_review_cancel_before_start_never_calls_provider(pdf_sample):
    editor, context, session, _, _ = pdf_sample
    planner = AsyncMock()
    ai = service(editor, planner)
    await ai.cancel_request(session, "review-1")
    result = await ai.start(session, **payload(context))
    assert result["status"] == "cancelled"
    planner.assert_not_awaited()
    await ai.aclose()


@pytest.mark.anyio
async def test_review_shutdown_stamps_terminal_before_swallowed_cancellation(pdf_sample):
    editor, context, session, _, _ = pdf_sample
    entered = asyncio.Event()

    async def planner(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return {"answer": "迟到", "operations": [], "replies": [], "notes": []}

    ai = service(editor, planner)
    started = await ai.start(session, **payload(context))
    await entered.wait()
    await ai.aclose()
    status = await ai.status(session, started["editId"], wait_ms=0)
    assert status["status"] == "cancelled" and "proposal" not in status
    with pytest.raises(ReportingError):
        await ai.start(session, **payload(context, client_request_id="review-2"))


@pytest.mark.anyio
async def test_review_same_request_id_cannot_change_complete_base(pdf_sample):
    editor, context, session, _, _ = pdf_sample
    ai = service(
        editor,
        AsyncMock(return_value={"answer": "无批注", "operations": [], "replies": [], "notes": []}),
    )
    await ai.start(session, **payload(context))
    with pytest.raises(ReportingError, match="请求"):
        await ai.start(session, **{**payload(context), "instruction": "改要求"})
    await ai.cancel_request(session, "review-1")
    await ai.aclose()


@pytest.mark.anyio
async def test_review_real_preview_and_accept_preserve_source(review_sample):
    from pypdf import PdfReader

    editor, context, session, _, source = review_sample
    ai = service(editor, actual_candidates)
    started = await ai.start(session, **payload(context))
    status = await ai.status(session, started["editId"], wait_ms=20000)
    assert status["status"] == "succeeded", status.get("error", status)
    proposal = status["proposal"]
    assert [op["kind"] for op in proposal["operations"]] == ["replaceText", "replyNote"]
    assert proposal["appliedOperationIndices"] == [0, 1] and proposal["skippedOperations"] == []
    assert proposal["notes"][0]["status"] == "previewApplied"
    with pytest.raises(ReportingError, match="草稿"):
        await ai.accept(
            session,
            started["editId"],
            expected_sha256=context.source_file.sha256,
            operations=[{"kind": "rotatePage", "pageId": "changed", "delta": 90}],
            snapshot_sha256=status["snapshotSha256"],
        )
    accepted = await ai.accept(
        session,
        started["editId"],
        expected_sha256=context.source_file.sha256,
        operations=[],
        snapshot_sha256=status["snapshotSha256"],
    )
    preview = await editor.preview_file(
        context, expected_sha256=context.source_file.sha256, operations=accepted["operations"]
    )
    pdf = PdfReader(BytesIO(preview["content"]))
    assert "Amount due 700" in pdf.pages[0].extract_text()
    replies = [
        raw.get_object()
        for raw in pdf.pages[0]["/Annots"]
        if raw.get_object().get("/IRT") is not None
    ]
    assert len(replies) == 1 and replies[0]["/T"] == "AI Assistant"
    assert await editor.read_file(context) == source
    await ai.aclose()


@pytest.mark.anyio
async def test_review_markup_candidate_uses_real_preview_and_accept(review_sample):
    from pypdf import PdfReader

    editor, context, session, _, source = review_sample
    ai = service(editor, actual_markup_candidate)
    started = await ai.start(session, **payload(context))
    status = await ai.status(session, started["editId"], wait_ms=20000)
    assert status["status"] == "succeeded", status.get("error", status)
    proposal = status["proposal"]
    assert [op["kind"] for op in proposal["operations"]] == ["addMarkup"]
    assert proposal["appliedOperationIndices"] == [0]
    assert proposal["notes"][0]["status"] == "previewApplied"
    accepted = await ai.accept(
        session,
        started["editId"],
        expected_sha256=context.source_file.sha256,
        operations=[],
        snapshot_sha256=status["snapshotSha256"],
    )
    preview = await editor.preview_file(
        context, expected_sha256=context.source_file.sha256, operations=accepted["operations"]
    )
    result = PdfReader(BytesIO(preview["content"]))
    markups = [
        raw.get_object() for raw in result.pages[0]["/Annots"]
        if raw.get_object().get("/Subtype") == "/Highlight"
    ]
    assert len(markups) == 1
    assert await editor.read_file(context) == source
    await ai.aclose()


@pytest.mark.anyio
async def test_review_http_auth_csrf_and_pre_cancel(review_sample):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from smart_reporting.report_editor.native_pdf_review_ai_api import (
        create_native_pdf_review_ai_router,
    )
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE

    editor, context, _, token, _ = review_sample
    planner = AsyncMock()
    ai = service(editor, planner)
    app = FastAPI()
    app.include_router(
        create_native_pdf_review_ai_router(
            editor.grants, editor=editor, review=ai, allowed_origin="http://test"
        )
    )
    base = f"/reports/v1/native/{context.document_id}/1/api/ai/review"
    headers = {"Origin": "http://test", "X-CSRF-Token": editor.grants.csrf_token(token)}
    body = {
        "clientRequestId": "http-1",
        "expectedSha256": context.source_file.sha256,
        "operations": [],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post(base + "/start", json=body)).status_code == 403
        client.cookies.set(NATIVE_SESSION_COOKIE, token)
        assert (await client.post(base + "/start", json=body)).status_code == 403
        assert (
            await client.post(
                base + "/start", json=body, headers={**headers, "Origin": "http://foreign"}
            )
        ).status_code == 403
        cancelled = await client.post(
            base + "/cancel", json={"clientRequestId": "http-1"}, headers=headers
        )
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        start = await client.post(base + "/start", json=body, headers=headers)
        assert start.json()["status"] == "cancelled"
        edit_id = start.json()["editId"]
        assert (await client.get(base.replace("/1/", "/2/") + f"/{edit_id}")).status_code == 403
        assert (await client.get(base + f"/{edit_id}?waitMs=0")).json()["status"] == "cancelled"
        assert (
            await client.post(base + "/start", json={**body, "selection": []}, headers=headers)
        ).status_code == 422
    planner.assert_not_awaited()
    await ai.aclose()


@pytest.mark.anyio
async def test_review_poll_keepalive_and_cancelled_accept_cannot_revive(pdf_sample, monkeypatch):
    editor, context, session, _, source = pdf_sample
    entered, release = asyncio.Event(), asyncio.Event()

    async def planner(**kwargs):
        entered.set()
        await release.wait()
        return {"answer": "未发现批注", "operations": [], "replies": [], "notes": []}

    ai = service(editor, planner)
    started = await ai.start(session, **payload(context))
    await entered.wait()
    assert (await ai.status(session, started["editId"], wait_ms=1))["status"] == "running"
    release.set()
    status = await ai.status(session, started["editId"], wait_ms=20000)
    assert status["status"] == "succeeded", status.get("error")
    preview_entered, preview_release = asyncio.Event(), asyncio.Event()
    original_preview = type(editor).preview_file

    async def delayed_preview(self, *args, **kwargs):
        result = await original_preview(self, *args, **kwargs)
        preview_entered.set()
        await preview_release.wait()
        return result

    monkeypatch.setattr(type(editor), "preview_file", delayed_preview)
    acceptance = asyncio.create_task(
        ai.accept(
            session,
            started["editId"],
            expected_sha256=context.source_file.sha256,
            operations=[],
            snapshot_sha256=status["snapshotSha256"],
        )
    )
    await preview_entered.wait()
    await ai.cancel_request(session, "review-1")
    preview_release.set()
    with pytest.raises(ReportingError, match="取消"):
        await acceptance
    assert (await ai.status(session, started["editId"], wait_ms=0))["status"] == "cancelled"
    assert await editor.read_file(context) == source
    await ai.aclose()


@pytest.mark.anyio
async def test_review_skipped_actual_text_drops_success_reply(review_sample):
    from pypdf import PdfReader
    from smart_reporting.report_editor.native_pdf_review_ai import NativePDFReviewTools

    editor, context, session, _, source = review_sample

    async def overflow(*, reader, **kwargs):
        tools = NativePDFReviewTools(reader)
        note = tools.read_annotations()["annotations"][0]
        tools.read_pages()
        tools.propose_replace_text(
            note["annotationId"],
            1,
            "Amount due 500",
            "This replacement cannot fit on the page. " * 50,
            "按批注尝试修改",
        )
        tools.propose_reply(note["annotationId"], "已完成改字。")
        return tools.result("待实际预览确认。")

    ai = service(editor, overflow)
    started = await ai.start(session, **payload(context))
    status = await ai.status(session, started["editId"], wait_ms=20000)
    assert status["status"] == "succeeded", status.get("error")
    proposal = status["proposal"]
    assert [op["kind"] for op in proposal["operations"]] == ["replaceText"]
    assert proposal["appliedOperationIndices"] == []
    assert proposal["notes"][0]["status"] == "skipped"
    assert "replyOmittedReason" in proposal["notes"][0]
    preview = await editor.preview_file(
        context, expected_sha256=context.source_file.sha256, operations=proposal["operations"]
    )
    notes = PdfReader(BytesIO(preview["content"])).pages[0]["/Annots"]
    assert len(notes) == 1 and notes[0].get_object().get("/IRT") is None
    assert await editor.read_file(context) == source
    await ai.aclose()


@pytest.mark.anyio
async def test_review_disabled_text_never_calls_provider(pdf_sample):
    editor, context, session, _, _ = pdf_sample
    editor.pdf_text_enabled = False
    planner = AsyncMock()
    ai = service(editor, planner)
    with pytest.raises(ReportingError) as failure:
        await ai.start(session, **payload(context))
    assert failure.value.code == "native_ai_pdf_text_disabled"
    planner.assert_not_awaited()
    await ai.aclose()


@pytest.mark.anyio
async def test_review_swallowed_timeout_never_becomes_succeeded(pdf_sample, monkeypatch):
    from smart_reporting.report_editor.native_pdf_ai import NativePDFTaskReader

    editor, context, session, _, source = pdf_sample
    reader = await NativePDFTaskReader.from_bytes(context, source)
    monkeypatch.setattr(NativePDFTaskReader, "from_bytes", AsyncMock(return_value=reader))

    async def planner(**kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return {"answer": "超时后迟到内容", "operations": [], "replies": [], "notes": []}

    ai = service(editor, planner)
    ai.timeout_seconds = 0.1
    started = await ai.start(session, **payload(context))
    status = await ai.status(session, started["editId"], wait_ms=2000)
    assert status["status"] == "failed" and status["error"]["code"] == "native_ai_timeout"
    assert "proposal" not in status
    await ai.aclose()


@pytest.mark.anyio
async def test_review_keeps_actual_unsaved_body_and_rebinds_new_candidates(review_sample):
    from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
    from pypdf import PdfReader

    editor, context, session, _, source = review_sample
    model = inspect_pdf(source, include_text=True)
    page = model["pages"][0]
    other = next(obj for obj in page["textObjects"] if obj["text"] == "UNSELECTED SECRET")
    base = [
        {
            "kind": "replaceText",
            "pageId": page["pageId"],
            "objectId": other["objectId"],
            "expectedTextSha256": other["expectedTextSha256"],
            "newText": "MANUAL DRAFT",
        }
    ]
    seen = []

    async def projected(**kwargs):
        seen.append(kwargs["reader"]._text(0))
        return await actual_candidates(**kwargs)

    ai = service(editor, projected)
    start = await ai.start(session, **{**payload(context), "operations": base})
    status = await ai.status(session, start["editId"], wait_ms=20000)
    assert status["status"] == "succeeded", status.get("error")
    assert "MANUAL DRAFT" in seen[0] and "UNSELECTED SECRET" not in seen[0]
    proposal = status["proposal"]
    assert proposal["operations"][:1] == base
    assert [op["kind"] for op in proposal["operations"]] == [
        "replaceText",
        "replaceText",
        "replyNote",
    ]
    assert proposal["projection"]["originalSourceSha256"] == context.source_file.sha256
    accepted = await ai.accept(
        session,
        start["editId"],
        expected_sha256=context.source_file.sha256,
        operations=base,
        snapshot_sha256=status["snapshotSha256"],
    )
    receipt = await editor.preview_file(
        context, expected_sha256=context.source_file.sha256, operations=accepted["operations"]
    )
    text = PdfReader(BytesIO(receipt["content"])).pages[0].extract_text()
    assert "MANUAL DRAFT" in text and "Amount due 700" in text
    assert await editor.read_file(context) == source
    await ai.aclose()


@pytest.mark.anyio
async def test_review_actual_ai_reply_thread_is_not_processed_again(review_sample):
    from smart_reporting.report_editor.native_pdf_ai import NativePDFTaskReader
    from smart_reporting.report_editor.native_pdf_review_ai import NativePDFReviewTools

    editor, context, session, _, source = review_sample
    ai = service(editor, actual_candidates)
    started = await ai.start(session, **payload(context))
    status = await ai.status(session, started["editId"], wait_ms=20000)
    assert status["status"] == "succeeded", status.get("error")
    operations = status["proposal"]["operations"]
    receipt = await editor.preview_file(
        context, expected_sha256=context.source_file.sha256, operations=operations
    )
    reader = await NativePDFTaskReader.from_bytes(
        context, source, operations=operations, draft_receipt=receipt
    )
    tools = NativePDFReviewTools(reader)
    annotations = tools.read_annotations()["annotations"]
    root = next(n for n in annotations if not n.get("parentAnnotationId"))
    reply = next(n for n in annotations if n.get("parentAnnotationId"))
    assert reply["author"] == "AI Assistant"
    tools.read_pages()
    with pytest.raises(ReportingError, match="最后回复来自 AI"):
        tools.propose_replace_text(
            root["annotationId"], 1, "Amount due 700", "Amount due 900", "不得重复执行"
        )
    tools.skip_note(root["annotationId"], "线程已由 AI 回复，不重复执行。")
    assert tools.operations == [] and tools.replies == []
    await ai.aclose()


@pytest.mark.anyio
async def test_review_orphan_body_operation_is_rejected_before_preview(pdf_sample, monkeypatch):
    editor, context, session, model, _ = pdf_sample
    page, obj = model["pages"][0], model["pages"][0]["textObjects"][0]
    operation = {
        "kind": "replaceText",
        "pageId": page["pageId"],
        "objectId": obj["objectId"],
        "expectedTextSha256": obj["expectedTextSha256"],
        "newText": "Amount due 700",
    }
    preview = AsyncMock()
    monkeypatch.setattr(type(editor), "preview_file", preview)
    ai = service(
        editor,
        AsyncMock(
            return_value={
                "answer": "未绑定批注的改字",
                "operations": [operation],
                "notes": [],
                "replies": [],
            }
        ),
    )
    start = await ai.start(session, **payload(context))
    status = await ai.status(session, start["editId"], wait_ms=20000)
    assert status["status"] == "failed" and status["error"]["code"] == "native_ai_schema_invalid"
    preview.assert_not_awaited()
    await ai.aclose()
