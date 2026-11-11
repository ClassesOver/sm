"""草稿标注撤销只移除真实回执绑定的操作，预览及采纳均不改来源。"""

from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader

from smart_reporting.report_editor.native_pdf_review_ai import NativePDFReviewTools
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
from smart_reporting.reporting.tests.test_native_pdf_review_ai_tasks import payload, service
from smart_reporting.reporting.tests.test_native_pdf_review_ai_tasks import (
    pdf_sample as pdf_sample,
)
from smart_reporting.reporting.tests.test_native_pdf_review_ai_tasks import (
    review_sample as review_sample,
)
from smart_reporting.reporting.tests.test_native_pdf_review_delete_markup_tasks import (
    saved_markup_review_sample as saved_markup_review_sample,
)


def markup(page_id):
    return {
        "kind": "addMarkup", "pageId": page_id, "markupType": "highlight",
        "quads": [[30, 240, 140, 240, 30, 225, 140, 225]],
        "color": [1, 0.87, 0.35],
    }


async def accept_preview(ai, editor, context, session, started, status, base):
    accepted = await ai.accept(
        session, started["editId"], expected_sha256=context.source_file.sha256,
        operations=base, snapshot_sha256=status["snapshotSha256"],
    )
    assert accepted["operations"] == status["proposal"]["operations"]
    return await editor.preview_file(
        context, expected_sha256=context.source_file.sha256, operations=accepted["operations"]
    )


@pytest.mark.anyio
async def test_delete_exact_second_pending_duplicate_reindexes_pending_reply(review_sample):
    editor, context, session, _, source = review_sample
    page_id = inspect_pdf(source)["pages"][0]["pageId"]
    base = [
        markup(page_id),
        {"kind": "rotatePage", "pageId": page_id, "delta": 90},
        markup(page_id),
        {"kind": "addTextAnnotation", "pageId": page_id, "rect": [30, 100, 50, 118],
         "text": "只删除第二个未保存高亮。", "createdMs": 0},
    ]
    frozen = deepcopy(base)
    selected_note = []

    async def planner(*, reader, **kwargs):
        tools = NativePDFReviewTools(reader)
        annotations = tools.read_annotations()["annotations"]
        markups = [item for item in annotations if item["kind"] == "markup"]
        assert len(markups) == 2 and markups[0]["quads"] == markups[1]["quads"]
        assert markups[0]["annotationId"] != markups[1]["annotationId"]
        note = next(item for item in annotations if item.get("contents") == base[3]["text"])
        selected_note.append(note["annotationId"])
        deletion = tools.delete_markup(
            note["annotationId"], 1, "只撤销第二个重复高亮",
            markup_ids=[markups[1]["annotationId"]],
        )
        assert deletion["removedBaseOperationIndices"] == [2]
        tools.propose_reply(note["annotationId"], "已提出撤销第二个草稿高亮的候选。")
        result = tools.result("第二个高亮撤销候选待采纳。")
        assert result["removedBaseOperationIndices"] == [2]
        return result

    ai = service(editor, planner)
    try:
        started = await ai.start(session, **payload(context, operations=base))
        status = await ai.status(session, started["editId"], wait_ms=20000)
        assert status["status"] == "succeeded", status.get("error", status)
        proposal = status["proposal"]
        assert [op["kind"] for op in proposal["operations"]] == [
            "addMarkup", "rotatePage", "addTextAnnotation", "replyPendingNote",
        ]
        assert proposal["operations"][:2] == frozen[:2]
        root = proposal["operations"][2]
        assert {key: value for key, value in root.items() if key != "localId"} == frozen[3]
        assert proposal["operations"][3]["parentLocalId"] == root["localId"]
        note = next(item for item in proposal["notes"] if item["annotationId"] == selected_note[0])
        assert note["removedBaseOperationIndices"] == [2]
        assert note["operationIndices"] == [] and note["replyOperationIndex"] == 3
        assert note["status"] == "previewApplied"
        assert proposal["appliedOperationIndices"] == [0, 1, 2, 3]
        assert proposal["skippedOperations"] == []
        assert base == frozen and await editor.read_file(context) == source
        preview = await accept_preview(ai, editor, context, session, started, status, base)
        assert len(inspect_pdf(preview["content"])["pages"][0]["markups"]) == 1
        pdf = PdfReader(BytesIO(preview["content"]))
        annots = pdf.pages[0]["/Annots"]
        pending_root = next(raw for raw in annots if raw.get_object().get("/Contents") == base[3]["text"])
        replies = [raw.get_object() for raw in annots if raw.get_object().get("/IRT") is not None]
        assert len(replies) == 1 and replies[0].raw_get("/IRT") == pending_root
        assert replies[0]["/T"] == "AI Assistant"
        assert pdf.pages[0].rotation == 90
        assert base == frozen and await editor.read_file(context) == source
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_delete_saved_and_pending_markup_together_uses_original_saved_identity(saved_markup_review_sample):
    editor, context, session, source = saved_markup_review_sample
    original = inspect_pdf(source)["pages"][0]
    base = [markup(original["pageId"])]
    saved_target, survivor = original["markups"]

    async def planner(*, reader, **kwargs):
        tools = NativePDFReviewTools(reader)
        annotations = tools.read_annotations()["annotations"]
        note = next(item for item in annotations if item["kind"] == "note")
        marks = [item for item in annotations if item["kind"] == "markup"]
        assert len(marks) == 3
        tools.delete_markup(
            note["annotationId"], 1, "同时删除已保存及草稿高亮",
            markup_ids=[marks[0]["annotationId"], marks[-1]["annotationId"]],
        )
        tools.propose_reply(note["annotationId"], "已提出删除两处高亮的候选，保留下划线。")
        return tools.result("混合来源标注删除候选待采纳。")

    ai = service(editor, planner)
    try:
        started = await ai.start(session, **payload(context, operations=base))
        status = await ai.status(session, started["editId"], wait_ms=20000)
        assert status["status"] == "succeeded", status.get("error", status)
        proposal = status["proposal"]
        assert [op["kind"] for op in proposal["operations"]] == ["removeMarkup", "replyNote"]
        assert proposal["operations"][0]["annotationId"] == saved_target["annotationId"]
        assert proposal["operations"][0]["expectedAnnotationSha256"] == saved_target["expectedAnnotationSha256"]
        assert proposal["notes"][0]["removedBaseOperationIndices"] == [0]
        assert proposal["notes"][0]["operationIndices"] == [0]
        assert proposal["notes"][0]["replyOperationIndex"] == 1
        assert proposal["appliedOperationIndices"] == [0, 1]
        preview = await accept_preview(ai, editor, context, session, started, status, base)
        remaining = inspect_pdf(preview["content"])["pages"][0]["markups"]
        assert len(remaining) == 1
        assert remaining[0]["markupType"] == survivor["markupType"]
        assert remaining[0]["quads"] == survivor["quads"]
        assert base == [markup(original["pageId"])] and await editor.read_file(context) == source
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_delete_all_pending_markup_without_reply_accepts_empty_real_preview(review_sample):
    editor, context, session, _, source = review_sample
    base = [markup(inspect_pdf(source)["pages"][0]["pageId"])]

    async def planner(*, reader, **kwargs):
        tools = NativePDFReviewTools(reader)
        annotations = tools.read_annotations()["annotations"]
        note = next(item for item in annotations if item["kind"] == "note")
        target = next(item for item in annotations if item["kind"] == "markup")
        tools.delete_markup(
            note["annotationId"], 1, "只撤销未保存高亮，不追加回复",
            markup_ids=[target["annotationId"]],
        )
        return tools.result("草稿高亮撤销候选待采纳。")

    ai = service(editor, planner)
    try:
        started = await ai.start(session, **payload(context, operations=base))
        status = await ai.status(session, started["editId"], wait_ms=20000)
        assert status["status"] == "succeeded", status.get("error", status)
        proposal = status["proposal"]
        assert proposal["operations"] == [] and proposal["appliedOperationIndices"] == []
        assert proposal["skippedOperations"] == []
        note = proposal["notes"][0]
        assert note["removedBaseOperationIndices"] == [0] and note["operationIndices"] == []
        assert note["status"] == "previewApplied" and "replyOperationIndex" not in note
        preview = await accept_preview(ai, editor, context, session, started, status, base)
        assert inspect_pdf(preview["content"])["pages"][0]["markups"] == []
        assert PdfReader(BytesIO(preview["content"])).pages[0].extract_text() == PdfReader(BytesIO(source)).pages[0].extract_text()
        assert base == [markup(inspect_pdf(source)["pages"][0]["pageId"])]
        assert await editor.read_file(context) == source
    finally:
        await ai.aclose()
