"""未保存根便签由真实append回执归属，AI候选不改变原草稿或来源。"""

import hashlib
import asyncio
import json
import os
from pathlib import Path
from copy import deepcopy
from copy import copy
from io import BytesIO

import pytest
from pypdf import PdfReader
from agno.models.response import ModelResponse

from smart_reporting.report_editor.native_pdf_review_ai import (
    NativePDFReviewReader,
    NativePDFReviewTools,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests import test_native_ai
from smart_reporting.reporting.tests.test_native_pdf_review_ai_tasks import payload, service
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel

pdf_sample = test_native_ai.pdf_sample


@pytest.mark.anyio
async def test_pending_note_actual_review_accept_keeps_base_and_exact_duplicate_parent(pdf_sample):
    editor, context, session, model, source = pdf_sample
    page_id = model["pages"][0]["pageId"]
    root = {
        "kind": "addTextAnnotation",
        "pageId": page_id,
        "rect": [30, 210, 50, 228],
        "text": "Change Amount due 500 to Amount due 700.",
        "createdMs": 0,
    }
    base = [deepcopy(root), deepcopy(root)]
    frozen = deepcopy(base)

    async def planner(*, reader, **kwargs):
        from smart_reporting.report_editor.native_pdf_review_ai import AgnoNativePDFReviewPlanner

        first, second = reader.pages[0]["notes"]
        calls = [
            ("read_annotations", {}),
            ("read_pages", {}),
            (
                "skip_note",
                {"annotation_id": first["annotationId"], "reason": "仅处理第二条重复外观批注"},
            ),
            (
                "propose_replace_text",
                {
                    "annotation_id": second["annotationId"],
                    "page_number": 1,
                    "old_text": "Amount due 500",
                    "new_text": "Amount due 700",
                    "reason": "按第二条批注更正",
                },
            ),
            (
                "propose_reply",
                {"annotation_id": second["annotationId"], "contents": "已将金额改为700。"},
            ),
        ]
        responses = [
            ModelResponse(
                tool_calls=[
                    {
                        "id": str(i),
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(args, ensure_ascii=False),
                        },
                    }
                ]
            )
            for i, (name, args) in enumerate(calls)
        ]
        responses.append(
            ModelResponse(content=json.dumps({"answer": "第二条批注修改候选待采纳。"}))
        )
        return await AgnoNativePDFReviewPlanner(
            ScriptedModel(id="pending-review", responses=responses)
        )(reader=reader, **kwargs)

    ai = service(editor, planner)
    try:
        started = await ai.start(session, **payload(context, operations=base))
        status = await ai.status(session, started["editId"], wait_ms=20000)
        assert status["status"] == "succeeded", status
        proposal = status["proposal"]
        assert [op["kind"] for op in proposal["operations"]] == [
            "addTextAnnotation",
            "addTextAnnotation",
            "replaceText",
            "replyPendingNote",
        ]
        assert base == frozen
        assert proposal["operations"][0] == frozen[0]
        generated_root = proposal["operations"][1]
        assert {k: v for k, v in generated_root.items() if k != "localId"} == frozen[1]
        assert proposal["operations"][3]["parentLocalId"] == generated_root["localId"]
        with pytest.raises(ReportingError, match="草稿"):
            await ai.accept(
                session,
                started["editId"],
                expected_sha256=context.source_file.sha256,
                operations=base[:1],
                snapshot_sha256=status["snapshotSha256"],
            )
        accepted = await ai.accept(
            session,
            started["editId"],
            expected_sha256=context.source_file.sha256,
            operations=base,
            snapshot_sha256=status["snapshotSha256"],
        )
        preview = await editor.preview_file(
            context, expected_sha256=context.source_file.sha256, operations=accepted["operations"]
        )
        pdf = PdfReader(BytesIO(preview["content"]))
        assert "Amount due 700" in pdf.pages[0].extract_text()
        annots = pdf.pages[0]["/Annots"]
        assert len(annots) == 3
        reply = annots[2].get_object()
        assert reply["/T"] == "AI Assistant"
        assert reply.raw_get("/IRT") == annots[1] and reply.raw_get("/IRT") != annots[0]
        assert reply["/Contents"] == "已将金额改为700。"
        assert await editor.read_file(context) == source
        assert hashlib.sha256(source).hexdigest() == context.source_file.sha256
        if evidence := os.environ.get("PDF_REVIEW_PENDING_EVIDENCE_DIR"):
            directory = Path(evidence)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "source.pdf").write_bytes(source)
            (directory / "preview.pdf").write_bytes(preview["content"])
            (directory / "actual-evidence.json").write_text(
                json.dumps(
                    {
                        "provider": "ScriptedModel through real Agno; not a real provider",
                        "sourceSha256": context.source_file.sha256,
                        "base": frozen,
                        "proposal": proposal,
                        "accepted": accepted,
                        "previewSha256": preview["sha256"],
                        "previewDigest": preview["previewDigest"],
                        "pendingNoteMapping": preview["pendingNoteMapping"],
                        "text": pdf.pages[0].extract_text(),
                        "replyAuthor": reply["/T"],
                        "replyParentRef": f"{reply.raw_get('/IRT').idnum}R{reply.raw_get('/IRT').generation or ''}",
                        "exactSecondRootRef": f"{annots[1].idnum}R{annots[1].generation or ''}",
                        "otherRootRef": f"{annots[0].idnum}R{annots[0].generation or ''}",
                        "sourceUnchanged": True,
                        "baseUnchanged": base == frozen,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_pending_projection_rejects_unexecuted_foreign_duplicate_and_stale_references(
    pdf_sample,
):
    editor, context, _, model, source = pdf_sample
    root = {
        "kind": "addTextAnnotation",
        "pageId": model["pages"][0]["pageId"],
        "rect": [30, 210, 50, 228],
        "text": "Change amount",
        "localId": "a" * 32,
    }
    receipt = await editor.preview_file(
        context, expected_sha256=context.source_file.sha256, operations=[root]
    )
    reader = await NativePDFReviewReader.from_bytes(
        context, source, operations=[root], draft_receipt=receipt
    )
    assert len(reader.projection["pendingNoteMapping"]) == 1
    mapping = receipt["pendingNoteMapping"][0]
    for changes in (
        {"operationIndex": -1},
        {"operationIndex": True},
        {"localId": "b" * 32},
        {"sourceRef": "999999R"},
        {"effectivePageId": "foreign"},
        {"pageId": "foreign"},
        {"expectedAnnotationSha256": "0" * 64},
        {"annotationId": "0" * 64},
    ):
        broken = {**receipt, "pendingNoteMapping": [{**mapping, **changes}]}
        with pytest.raises(ReportingError):
            copy(reader)._bind_projection(broken)
    with pytest.raises(ReportingError, match="未执行"):
        copy(reader)._bind_projection(
            {
                **receipt,
                "appliedOperationIndices": [],
                "skippedOperations": [{"operationIndex": 0, "reason": "not executed"}],
            }
        )
    with pytest.raises(ReportingError):
        copy(reader)._bind_projection({**receipt, "pendingNoteMapping": [mapping, mapping]})
    missing = copy(reader)
    missing._bind_projection({k: v for k, v in receipt.items() if k != "pendingNoteMapping"})
    tools = NativePDFReviewTools(missing)
    note = tools.read_annotations()["annotations"][0]
    tools.read_pages()
    with pytest.raises(ReportingError, match="重绑"):
        tools.propose_reply(note["annotationId"], "请确认。", intent="clarify")


@pytest.mark.anyio
async def test_pending_actual_text_skip_restores_original_root_and_omits_success_reply(pdf_sample):
    editor, context, session, model, source = pdf_sample
    root = {
        "kind": "addTextAnnotation",
        "pageId": model["pages"][0]["pageId"],
        "rect": [30, 210, 50, 228],
        "text": "Change amount",
        "createdMs": 0,
    }

    async def planner(*, reader, **kwargs):
        tools = NativePDFReviewTools(reader)
        note = tools.read_annotations()["annotations"][0]
        tools.read_pages()
        tools.propose_replace_text(
            note["annotationId"], 1, "Amount due 500", "Cannot fit this line. " * 100, "过长修改"
        )
        tools.propose_reply(note["annotationId"], "已修改成功。")
        return tools.result("候选由真实引擎判断。")

    ai = service(editor, planner)
    try:
        start = await ai.start(session, **payload(context, operations=[root]))
        status = await ai.status(session, start["editId"], wait_ms=20000)
        assert status["status"] == "succeeded", status
        proposal = status["proposal"]
        assert proposal["operations"][0] == root
        assert [o["kind"] for o in proposal["operations"]] == ["addTextAnnotation", "replaceText"]
        assert proposal["notes"][0]["replyOmittedReason"]
        preview = await editor.preview_file(
            context, expected_sha256=context.source_file.sha256, operations=proposal["operations"]
        )
        pdf = PdfReader(BytesIO(preview["content"]))
        assert "Amount due 500" in pdf.pages[0].extract_text()
        assert len(pdf.pages[0]["/Annots"]) == 1
        assert pdf.pages[0]["/Annots"][0].get_object().get("/IRT") is None
        assert await editor.read_file(context) == source
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_pending_cancel_cannot_revive_candidate_or_mutate_original_base(pdf_sample):
    editor, context, session, model, source = pdf_sample
    root = {
        "kind": "addTextAnnotation",
        "pageId": model["pages"][0]["pageId"],
        "rect": [30, 210, 50, 228],
        "text": "Change amount",
        "createdMs": 0,
    }
    frozen, entered = deepcopy(root), asyncio.Event()

    async def planner(*, reader, **kwargs):
        tools = NativePDFReviewTools(reader)
        note = tools.read_annotations()["annotations"][0]
        tools.read_pages()
        tools.propose_replace_text(
            note["annotationId"], 1, "Amount due 500", "Amount due 700", "更正"
        )
        tools.propose_reply(note["annotationId"], "更正为700。")
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return tools.result("吞取消后迟到的结果")

    ai = service(editor, planner)
    try:
        start = await ai.start(session, **payload(context, operations=[root]))
        await asyncio.wait_for(entered.wait(), timeout=20)
        await ai.cancel_request(session, "review-1")
        status = await ai.status(session, start["editId"], wait_ms=20000)
        assert status["status"] == "cancelled" and "proposal" not in status
        assert root == frozen and await editor.read_file(context) == source
        with pytest.raises(ReportingError):
            await ai.accept(
                session,
                start["editId"],
                expected_sha256=context.source_file.sha256,
                operations=[root],
                snapshot_sha256=status["snapshotSha256"],
            )
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_pending_review_keeps_unrelated_manual_text_and_rejects_same_object_conflict(
    pdf_sample,
):
    editor, context, session, model, source = pdf_sample
    page = model["pages"][0]
    manual = page["textObjects"][1]
    base = [
        {
            "kind": "replaceText",
            "pageId": page["pageId"],
            "objectId": manual["objectId"],
            "expectedTextSha256": manual["expectedTextSha256"],
            "newText": "MANUAL DRAFT",
        },
        {
            "kind": "addTextAnnotation",
            "pageId": page["pageId"],
            "localId": "f" * 32,
            "rect": [30, 210, 50, 228],
            "text": "Change amount",
            "createdMs": 0,
        },
    ]
    frozen = deepcopy(base)

    async def planner(*, reader, **kwargs):
        tools = NativePDFReviewTools(reader)
        note = tools.read_annotations()["annotations"][0]
        tools.read_pages()
        with pytest.raises(ReportingError, match="已修改|重绑"):
            tools.propose_replace_text(
                note["annotationId"], 1, "MANUAL DRAFT", "OVERWRITE", "不应覆盖人工草稿"
            )
        tools.propose_replace_text(
            note["annotationId"], 1, "Amount due 500", "Amount due 700", "仅修改批注目标"
        )
        tools.propose_reply(note["annotationId"], "金额更正为700。")
        return tools.result("保留人工草稿。")

    ai = service(editor, planner)
    try:
        start = await ai.start(session, **payload(context, operations=base))
        status = await ai.status(session, start["editId"], wait_ms=20000)
        assert status["status"] == "succeeded", status
        assert status["proposal"]["operations"][:2] == frozen
        assert base == frozen
        preview = await editor.preview_file(
            context,
            expected_sha256=context.source_file.sha256,
            operations=status["proposal"]["operations"],
        )
        text = PdfReader(BytesIO(preview["content"])).pages[0].extract_text()
        assert "Amount due 700" in text and "MANUAL DRAFT" in text and "OVERWRITE" not in text
        assert await editor.read_file(context) == source
    finally:
        await ai.aclose()
