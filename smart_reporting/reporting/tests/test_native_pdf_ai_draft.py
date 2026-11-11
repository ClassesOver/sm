"""未保存 PDF 草稿只读投影：真实引擎与任务快照边界。"""

from __future__ import annotations

import asyncio
import json

import pytest
from agno.models.response import ModelResponse

from smart_reporting.report_editor.native_pdf_ai import create_native_pdf_read_planner
from smart_reporting.reporting.tests import test_native_ai
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel
from smart_reporting.reporting.tests.test_native_pdf_ai_tasks import payload, service

pdf_sample = test_native_ai.pdf_sample


def replacement(model, **changes):
    page = model["pages"][0]
    obj = page["textObjects"][0]
    return {
        "kind": "replaceText",
        "pageId": page["pageId"],
        "objectId": obj["objectId"],
        "expectedTextSha256": obj["expectedTextSha256"],
        "newText": "Amount due 700",
        **changes,
    }


def planner(text):
    return create_native_pdf_read_planner(
        ScriptedModel(
            id="scripted",
            expected_tool_text=text if text.startswith("Amount due") else None,
            responses=[
                ModelResponse(
                    tool_calls=[
                        {
                            "id": "read",
                            "type": "function",
                            "function": {
                                "name": "read_pages",
                                "arguments": '{"start_page":1,"page_count":2}',
                            },
                        }
                    ]
                ),
                ModelResponse(content=json.dumps({"answer": text, "citations": [1]})),
            ],
        )
    )


async def run_draft(pdf_sample, operations, *, selected=None, text="Amount due 700"):
    editor, context, session, _, source = pdf_sample
    ai = service(editor, planner(text))
    try:
        started = await ai.start(
            session, **payload(context, operations=operations, selection=selected or [])
        )
        result = await ai.status(session, started["taskId"], wait_ms=20000)
        assert await editor.read_file(context) == source
        return result
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_draft_text_uses_real_projection_and_preserves_original_identity(
    pdf_sample,
):
    _, context, _, model, _ = pdf_sample
    result = await run_draft(pdf_sample, [replacement(model)])
    assert result["status"] == "completed", result
    answer = result["result"]
    identity = answer["projection"]
    assert identity["originalSourceSha256"] == context.source_file.sha256
    assert identity["effectiveSha256"] != context.source_file.sha256
    assert len(identity["previewDigest"]) == len(identity["draftSnapshotSha256"]) == 64
    assert identity["appliedOperationIndices"] == [0]
    assert identity["skippedOperations"] == []
    citation = answer["citations"][0]
    assert citation["originalPageNumber"] == citation["effectivePageNumber"] == 1
    assert citation["pageId"] == model["pages"][0]["pageId"]
    assert citation["effectivePageId"] != citation["pageId"]
    assert citation["effectiveSha256"] == identity["effectiveSha256"]


@pytest.mark.anyio
async def test_draft_replacement_rebinds_selected_object_without_leaking_other_text(
    pdf_sample,
):
    _, _, _, model, _ = pdf_sample
    op = replacement(model)
    result = await run_draft(
        pdf_sample, [op], selected=[{k: op[k] for k in ("pageId", "objectId")}]
    )
    assert result["status"] == "completed", result
    assert result["result"]["coverage"]["scope"] == "selection"
    assert (
        result["result"]["projection"]["selectionMapping"][0]["effectiveObjectId"]
        != op["objectId"]
    )


@pytest.mark.anyio
@pytest.mark.parametrize("deleted", [False, True])
async def test_draft_page_mapping_follows_applied_order_and_deletion(
    pdf_sample, deleted
):
    _, _, _, model, _ = pdf_sample
    p1, p2 = [p["pageId"] for p in model["pages"]]
    ops = ([{"kind": "deletePage", "pageId": p1}] if deleted else []) + [
        {"kind": "reorderPages", "pageIds": [p2] if deleted else [p2, p1]}
    ]
    result = await run_draft(pdf_sample, ops, text="Read projected pages")
    assert result["status"] == "completed", result
    mapping = result["result"]["projection"]["pageMapping"]
    assert mapping[0]["originalPageNumber"] == 2
    assert mapping[0]["effectivePageNumber"] == 1
    assert result["result"]["citations"][0]["pageNumber"] == 2
    assert len(mapping) == (1 if deleted else 2)


@pytest.mark.anyio
async def test_draft_removed_selected_page_is_rejected(pdf_sample):
    _, _, _, model, _ = pdf_sample
    op = replacement(model)
    result = await run_draft(
        pdf_sample,
        [{"kind": "deletePage", "pageId": op["pageId"]}],
        selected=[{k: op[k] for k in ("pageId", "objectId")}],
    )
    assert result["status"] == "failed", result
    assert result["error"]["code"] == "native_pdf_ai_selection_invalid"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "flags, code",
    [
        ((False, True), "native_feature_disabled"),
        ((True, False), "native_pdf_text_disabled"),
    ],
)
async def test_draft_cannot_bypass_edit_preview_flags(pdf_sample, flags, code):
    editor, _, _, model, _ = pdf_sample
    editor.pdf_enabled, editor.pdf_text_enabled = flags
    result = await run_draft(pdf_sample, [replacement(model)])
    assert result["status"] == "failed" and result["error"]["code"] == code, result


@pytest.mark.anyio
@pytest.mark.parametrize("partial", [False, True])
async def test_draft_skipped_edits_report_actual_receipt_and_original_text(
    pdf_sample, partial
):
    _, _, _, model, _ = pdf_sample
    bad = replacement(model, expectedTextSha256="0" * 64)
    ops = [bad] + (
        [{"kind": "rotatePage", "pageId": model["pages"][1]["pageId"], "delta": 90}]
        if partial
        else []
    )
    result = await run_draft(pdf_sample, ops, text="Amount due 500")
    assert result["status"] == "completed", result
    projection = result["result"]["projection"]
    assert projection["appliedOperationIndices"] == ([1] if partial else [])
    assert projection["skippedOperations"][0]["operationIndex"] == 0
    assert any(
        i["code"] == "native_pdf_ai_draft_operations_skipped"
        for i in result["result"]["issues"]
    )


@pytest.mark.anyio
async def test_draft_cancel_during_projection_discards_late_output_and_freezes_snapshot(
    pdf_sample, monkeypatch
):
    editor, context, session, model, source = pdf_sample
    entered = asyncio.Event()
    seen = []
    actual = editor.preview_file

    async def blocked(*args, **kwargs):
        seen.append(kwargs["operations"][0]["newText"])
        entered.set()
        await asyncio.Event().wait()
        return await actual(*args, **kwargs)

    monkeypatch.setattr(editor, "preview_file", blocked)
    ai = service(editor, planner("Amount due 700"))
    ops = [replacement(model)]
    try:
        start = await ai.start(session, **payload(context, operations=ops))
        ops[0]["newText"] = "mutated"
        await asyncio.wait_for(entered.wait(), 3)
        assert seen == ["Amount due 700"]
        await ai.cancel_request(session, "request-1")
        result = await ai.status(session, start["taskId"], wait_ms=0)
        assert result["status"] == "cancelled" and "result" not in result
        assert await editor.read_file(context) == source
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_draft_cancelled_projection_cannot_start_model_after_swallowed_cancel(
    pdf_sample, monkeypatch
):
    editor, context, session, model, _ = pdf_sample
    receipt = await editor.preview_file(
        context,
        expected_sha256=context.source_file.sha256,
        operations=[replacement(model)],
    )
    entered = asyncio.Event()
    calls = []

    async def blocked(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return receipt

    async def late_planner(**kwargs):
        calls.append("called")
        return {"answer": "late"}

    monkeypatch.setattr(editor, "preview_file", blocked)
    ai = service(editor, late_planner)
    try:
        started = await ai.start(
            session, **payload(context, operations=[replacement(model)])
        )
        await asyncio.wait_for(entered.wait(), 3)
        await ai.cancel_request(session, "request-1")
        result = await ai.status(session, started["taskId"], wait_ms=0)
        assert result["status"] == "cancelled" and "result" not in result
        assert calls == []
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_draft_inserted_blank_has_no_forged_original_navigation(pdf_sample):
    _, _, _, model, _ = pdf_sample
    ids = [page["pageId"] for page in model["pages"]]
    ops = [
        {
            "kind": "insertBlankPage",
            "pageId": "blank:read-test",
            "width": 400,
            "height": 300,
        },
        {"kind": "reorderPages", "pageIds": ["blank:read-test", *ids]},
    ]
    result = await run_draft(pdf_sample, ops, text="Read projected pages")
    assert result["status"] == "completed", result
    projection = result["result"]["projection"]
    page = projection["pageMapping"][0]
    assert page["originalPageId"] is page["originalPageNumber"] is None
    assert page["effectivePageNumber"] == 1
    assert page["effectivePageId"].startswith("sha256:" + projection["effectiveSha256"])
    citation = result["result"]["citations"][0]
    assert citation["pageNumber"] is citation["pageId"] is None
    assert citation["effectivePageNumber"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["mergePages", "splitPages"])
async def test_draft_layout_without_safe_one_to_one_mapping_is_explicitly_rejected(
    pdf_sample, kind
):
    operation = (
        {"kind": kind, "perSheet": 2, "direction": "horizontal", "separator": False}
        if kind == "mergePages"
        else {"kind": kind, "perPage": 2}
    )
    result = await run_draft(pdf_sample, [operation])
    assert result["status"] == "failed", result
    assert result["error"]["code"] == "native_pdf_ai_draft_mapping_unsupported"


@pytest.mark.anyio
@pytest.mark.parametrize("tamper", ["sha256", "appliedOperationIndices"])
async def test_draft_invalid_preview_identity_or_partition_never_reaches_model(
    pdf_sample, monkeypatch, tamper
):
    editor, _, _, model, _ = pdf_sample
    actual = editor.preview_file

    async def corrupt(*args, **kwargs):
        receipt = await actual(*args, **kwargs)
        receipt[tamper] = "0" * 64 if tamper == "sha256" else []
        return receipt

    monkeypatch.setattr(editor, "preview_file", corrupt)
    result = await run_draft(pdf_sample, [replacement(model)])
    assert result["status"] == "failed", result
    assert result["error"]["code"] == "native_pdf_ai_projection_invalid"


@pytest.mark.anyio
async def test_draft_changed_selected_geometry_is_rejected(pdf_sample):
    _, _, _, model, _ = pdf_sample
    op = replacement(model)
    result = await run_draft(
        pdf_sample,
        [{"kind": "rotatePage", "pageId": op["pageId"], "delta": 90}],
        selected=[{k: op[k] for k in ("pageId", "objectId")}],
    )
    assert result["status"] == "failed", result
    assert result["error"]["code"] == "native_pdf_ai_selection_invalid"


@pytest.mark.anyio
async def test_draft_http_uses_verified_projection_and_only_selected_effective_text(
    pdf_sample,
):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor.native_ai_api import create_native_ai_router
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE

    editor, context, _, model, source = pdf_sample
    operation = replacement(model)
    actual = planner("Amount due 700")
    evidence = []

    async def checked(**kwargs):
        result = await actual(**kwargs)
        reader = kwargs["draft_projection"]
        pages = reader.read_pages(start_page=1, page_count=2)
        assert [page["text"] for page in pages["pages"]] == ["Amount due 700"]
        assert pages["sourceSha256"] != context.source_file.sha256
        assert pages["sourceSha256"] == result["projection"]["effectiveSha256"]
        evidence.append(pages)
        return result

    ai = service(editor, checked)
    app = FastAPI()
    app.include_router(
        create_native_ai_router(
            editor.grants,
            editor=editor,
            ai=None,
            pdf_read=ai,
            allowed_origin="http://test",
        )
    )
    raw, _ = await editor.grants.issue(
        context, capabilities=editor.capabilities(context)
    )
    token, _ = await editor.grants.exchange(raw)
    base = f"/reports/v1/native/{context.document_id}/1/api/ai/read"
    body = {
        "clientRequestId": "draft-http",
        "expectedSha256": context.source_file.sha256,
        "operations": [operation],
        "selection": [{k: operation[k] for k in ("pageId", "objectId")}],
        "action": "ask",
        "instruction": "读取所选草稿金额",
    }
    headers = {"Origin": "http://test", "X-CSRF-Token": editor.grants.csrf_token(token)}
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            client.cookies.set(NATIVE_SESSION_COOKIE, token)
            started = await client.post(base + "/start", json=body, headers=headers)
            assert started.status_code == 200, started.text
            done = await client.get(
                base + "/" + started.json()["taskId"] + "?waitMs=20000"
            )
            result = done.json()
            assert result["status"] == "completed", result
            assert result["result"]["answer"] == "Amount due 700"
            assert result["result"]["projection"]["appliedOperationIndices"] == [0]
            assert len(evidence) == 1
            assert await editor.read_file(context) == source
    finally:
        await ai.aclose()
