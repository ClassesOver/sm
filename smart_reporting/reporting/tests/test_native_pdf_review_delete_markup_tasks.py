"""批注删标注候选经真实预览与采纳后，只删除已核验的目标。"""

import hashlib
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.report_editor.native_pdf_review_ai import NativePDFReviewTools
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel
from smart_reporting.reporting.tests.test_native_pdf_review_ai_tasks import (
    payload,
    service,
)
from smart_reporting.reporting.tests.test_native_pdf_review_ai_tasks import (
    pdf_sample as pdf_sample,
)
from smart_reporting.reporting.tests.test_native_pdf_review_ai_tasks import (
    review_sample as review_sample,
)


@pytest.fixture
async def saved_markup_review_sample(review_sample, request):
    editor, context, _, _, source = review_sample
    page_id = inspect_pdf(source)["pages"][0]["pageId"]
    source = patch_pdf(
        source,
        [
            {
                "kind": "addMarkup",
                "pageId": page_id,
                "markupType": kind,
                "quads": [[30, top, 140, top, 30, top - 15, 140, top - 15]],
                "color": color,
            }
            for kind, top, color in [
                ("highlight", 240, [1, 0.87, 0.35]),
                (getattr(request, "param", "underline"), 190, [0.17, 0.4, 1]),
            ]
        ],
    )
    context = context.model_copy(
        update={
            "source_file": context.source_file.model_copy(
                update={
                    "path": "native/review-saved-markups.pdf",
                    "size": len(source),
                    "sha256": hashlib.sha256(source).hexdigest(),
                }
            )
        }
    )
    await editor.workspace.awrite_bytes(
        bind_native_workspace(editor.workspace, context.scope), context.source_file.path, source
    )
    editor.repository.get_revision.return_value = SimpleNamespace(status="saved", context=context)
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    _, session = await editor.grants.exchange(raw)
    return editor, context, session, source


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("target_type", "planner_mode", "has_draft"),
    [
        ("highlight", "tools", False),
        ("underline", "tools", False),
        ("highlight", "agno", False),
        ("underline", "agno", False),
        ("underline", "agno", True),
    ],
)
async def test_review_delete_saved_markup_real_preview_accept_preserves_source(
    saved_markup_review_sample, target_type, planner_mode, has_draft
):
    editor, context, session, source = saved_markup_review_sample
    original = inspect_pdf(source)["pages"][0]
    target = next(mark for mark in original["markups"] if mark["markupType"] == target_type)
    survivor = next(mark for mark in original["markups"] if mark["markupType"] != target_type)
    base = [{"kind": "rotatePage", "pageId": original["pageId"], "delta": 90}] if has_draft else []

    async def planner(*, reader, **kwargs):
        effective_note = reader.pages[0]["notes"][0]
        effective_mark = next(
            mark for mark in reader.pages[0]["markups"] if mark["markupType"] == target_type
        )
        if planner_mode == "agno":
            from agno.models.response import ModelResponse

            from smart_reporting.report_editor.native_pdf_review_ai import (
                AgnoNativePDFReviewPlanner,
            )

            calls = [
                ("read_annotations", {}),
                (
                    "delete_markup",
                    {
                        "annotation_id": effective_note["annotationId"],
                        "page_number": 1,
                        "reason": "按批注仅删除指定标注",
                        "markup_ids": [effective_mark["annotationId"]],
                    },
                ),
                (
                    "propose_reply",
                    {
                        "annotation_id": effective_note["annotationId"],
                        "contents": "已提出删除指定标注的候选，其余标注与正文保留。",
                    },
                ),
            ]
            responses = [
                ModelResponse(
                    tool_calls=[
                        {
                            "id": f"delete-markup-{index}",
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ]
                )
                for index, (name, arguments) in enumerate(calls)
            ]
            responses.append(ModelResponse(content=json.dumps({"answer": "已提出删除标注候选，待采纳。"})))
            return await AgnoNativePDFReviewPlanner(
                ScriptedModel(id="delete-markup-review", responses=responses)
            )(reader=reader, **kwargs)

        tools = NativePDFReviewTools(reader)
        annotations = tools.read_annotations()["annotations"]
        assert {item["kind"] for item in annotations} == {"note", "markup"}
        note = next(item for item in annotations if item["kind"] == "note")
        mark = next(item for item in annotations if item["annotationId"] == target["annotationId"])
        tools.delete_markup(
            note["annotationId"], mark["pageNumber"], "按批注仅删除指定标注",
            markup_ids=[mark["annotationId"]],
        )
        tools.propose_reply(note["annotationId"], "已提出删除指定标注的候选，其余标注与正文保留。")
        return tools.result("已提出删除指定标注及回复候选，待采纳。")

    ai = service(editor, planner)
    try:
        started = await ai.start(session, **payload(context, operations=base))
        status = await ai.status(session, started["editId"], wait_ms=20000)
        assert status["status"] == "succeeded", status.get("error", status)
        proposal = status["proposal"]
        assert [op["kind"] for op in proposal["operations"]] == [
            *(["rotatePage"] if has_draft else []), "removeMarkup", "replyNote"
        ]
        deletion = proposal["operations"][len(base)]
        assert deletion["annotationId"] == target["annotationId"]
        assert deletion["expectedAnnotationSha256"] == target["expectedAnnotationSha256"]
        assert deletion["pageId"] == original["pageId"]
        assert proposal["appliedOperationIndices"] == list(range(len(base) + 2))
        assert proposal["skippedOperations"] == []
        assert proposal["notes"][0]["status"] == "previewApplied"
        assert proposal["notes"][0]["operationIndices"] == [len(base)]
        assert await editor.read_file(context) == source

        accepted = await ai.accept(
            session, started["editId"], expected_sha256=context.source_file.sha256,
            operations=base, snapshot_sha256=status["snapshotSha256"],
        )
        preview = await editor.preview_file(
            context, expected_sha256=context.source_file.sha256, operations=accepted["operations"]
        )
        result = inspect_pdf(preview["content"])["pages"][0]
        assert len(result["markups"]) == 1
        retained = result["markups"][0]
        for key in ("markupType", "quads", "color"):
            assert retained[key] == survivor[key]
        before, after = PdfReader(BytesIO(source)), PdfReader(BytesIO(preview["content"]))
        assert after.pages[0].extract_text() == before.pages[0].extract_text()
        assert after.pages[0].get_contents().get_data() == before.pages[0].get_contents().get_data()
        notes = [raw.get_object() for raw in after.pages[0]["/Annots"]]
        replies = [note for note in notes if note.get("/IRT") is not None]
        assert len(replies) == 1 and replies[0]["/T"] == "AI Assistant"
        assert any(note.get("/Contents") == original["notes"][0]["contents"] for note in notes)
        assert await editor.read_file(context) == source
    finally:
        await ai.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("saved_markup_review_sample", ["highlight"], indirect=True)
async def test_review_same_type_markups_use_visible_geometry_to_select_delete(
    saved_markup_review_sample,
):
    from agno.models.response import ModelResponse

    from smart_reporting.report_editor.native_pdf_review_ai import AgnoNativePDFReviewPlanner

    editor, context, session, source = saved_markup_review_sample
    original = inspect_pdf(source)["pages"][0]
    assert [mark["markupType"] for mark in original["markups"]] == ["highlight", "highlight"]
    selected_ids = []

    async def planner(*, reader, **kwargs):
        evidence = NativePDFReviewTools(reader)
        annotations = evidence.read_annotations()["annotations"]
        markups = [item for item in annotations if item["kind"] == "markup"]
        assert len(markups) == 2
        assert markups[0]["quads"] != markups[1]["quads"]
        for visible, saved in zip(markups, original["markups"], strict=True):
            assert visible["quads"] == saved["quads"]
            assert visible["color"] == saved["color"]
        objects = evidence.read_pages()["pages"][0]["textObjects"]
        assert objects
        for obj in objects:
            actual = next(item for item in reader.pages[0]["textObjects"] if item["objectId"] == obj["objectId"])
            assert obj["rect"] == actual["rect"]
            assert len(obj["rect"]) == 4
        # 同类型标注只按已返回的实际坐标选定，不能从类型猜测目标。
        target = min(markups, key=lambda item: item["quads"][0][1])
        selected_ids.append(target["annotationId"])
        note = next(item for item in annotations if item["kind"] == "note")
        calls = [
            ("read_annotations", {}),
            ("read_pages", {}),
            ("delete_markup", {
                "annotation_id": note["annotationId"], "page_number": 1,
                "reason": "仅删除较低位置的高亮，保留较高位置的高亮",
                "markup_ids": [target["annotationId"]],
            }),
            ("propose_reply", {
                "annotation_id": note["annotationId"], "contents": "已提出删除较低位置高亮的候选。",
            }),
        ]
        responses = [
            ModelResponse(tool_calls=[{
                "id": f"geometry-{index}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }])
            for index, (name, arguments) in enumerate(calls)
        ]
        responses.append(ModelResponse(content=json.dumps({"answer": "按实际位置提出删除候选。"})))
        return await AgnoNativePDFReviewPlanner(
            ScriptedModel(id="geometry-review", responses=responses)
        )(reader=reader, **kwargs)

    ai = service(editor, planner)
    try:
        started = await ai.start(session, **payload(context))
        status = await ai.status(session, started["editId"], wait_ms=20000)
        assert status["status"] == "succeeded", status.get("error", status)
        assert status["proposal"]["operations"][0]["annotationId"] == selected_ids[0]
        assert await editor.read_file(context) == source
        accepted = await ai.accept(
            session, started["editId"], expected_sha256=context.source_file.sha256,
            operations=[], snapshot_sha256=status["snapshotSha256"],
        )
        preview = await editor.preview_file(
            context, expected_sha256=context.source_file.sha256, operations=accepted["operations"]
        )
        remaining = inspect_pdf(preview["content"])["pages"][0]["markups"]
        assert len(remaining) == 1
        assert remaining[0]["quads"] == max(original["markups"], key=lambda item: item["quads"][0][1])["quads"]
        assert PdfReader(BytesIO(preview["content"])).pages[0].get_contents().get_data() == PdfReader(BytesIO(source)).pages[0].get_contents().get_data()
        assert await editor.read_file(context) == source
    finally:
        await ai.aclose()
