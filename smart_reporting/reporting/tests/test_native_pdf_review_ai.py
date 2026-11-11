"""批注处理候选必须由真实读取证据产生，不能直接修改来源。"""

import json
from io import BytesIO

import pytest
from agno.models.response import ModelResponse
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text

from smart_reporting.report_editor.native_pdf_ai import NativePDFTaskReader
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel, sample


def review_tools():
    from smart_reporting.report_editor.native_pdf_review_ai import NativePDFReviewTools

    context, content, model = sample()
    page = model["pages"][1]
    page["notes"][0].update(
        annotationId="a" * 64,
        parentAnnotationId=None,
        expectedAnnotationSha256="b" * 64,
        replyable=True,
    )
    page["textObjects"][0].update(expectedTextSha256="c" * 64, editable=True)
    return NativePDFReviewTools(NativePDFTaskReader(context, content, model))


def test_candidates_require_read_note_and_full_body_evidence():
    tools = review_tools()
    with pytest.raises(ReportingError, match="批注"):
        tools.propose_replace_text("a" * 64, 2, "Revenue is 42.", "Revenue is 43.", "更正金额")
    tools.read_annotations()
    with pytest.raises(ReportingError, match="正文"):
        tools.propose_replace_text("a" * 64, 2, "Revenue is 42.", "Revenue is 43.", "更正金额")
    tools.reader.read_pages(start_page=2)
    proposed = tools.propose_replace_text(
        "a" * 64, 2, "Revenue is 42.", "Revenue is 43.", "更正金额"
    )
    assert proposed["status"] == "proposed"
    assert tools.operations[0]["newText"] == "Revenue is 43."
    assert tools.reader.pages[1]["textObjects"][0]["text"] == "Revenue is 42."


def test_ambiguous_or_unread_object_is_not_silently_replaced():
    tools = review_tools()
    tools.read_annotations()
    tools.reader.read_pages(start_page=2)
    with pytest.raises(ReportingError, match="唯一"):
        tools.propose_replace_text("a" * 64, 2, "Revenue", "Sales", "更名")
    with pytest.raises(ReportingError, match="批注"):
        tools.propose_reply("x" * 64, "已修改")


def test_markup_candidate_uses_unique_read_pdf_object_geometry():
    tools = review_tools()
    with pytest.raises(ReportingError, match="批注"):
        tools.propose_markup("a" * 64, 2, "Revenue is 42.", "highlight", "重点核对")
    tools.read_annotations()
    obj = tools.reader.pages[1]["textObjects"][0]
    obj["rect"] = [10, 20, 90, 40]
    duplicate = dict(obj)
    tools.reader.pages[1]["textObjects"].append(duplicate)
    tools.reader.read_pages(start_page=2)
    with pytest.raises(ReportingError, match="唯一"):
        tools.propose_markup("a" * 64, 2, "Revenue is 42.", "underline", "重点核对")
    tools.reader.pages[1]["textObjects"].pop()
    tools.reader._spans.clear()
    tools.reader.read_pages(start_page=2)
    proposed = tools.propose_markup(
        "a" * 64, 2, "Revenue is 42.", "highlight", "重点核对"
    )
    assert proposed["status"] == "proposed"
    assert tools.operations[0] == {
        "kind": "addMarkup", "pageId": tools.reader.pages[1]["pageId"], "markupType": "highlight",
        "quads": [[10, 40, 90, 40, 10, 20, 90, 20]], "color": [1, 0.87, 0.35],
    }


def test_reply_is_pending_and_discussion_has_specific_skip_reason():
    tools = review_tools()
    tools.read_annotations()
    reply = tools.propose_reply("a" * 64, "请确认应改为多少？", intent="clarify")
    assert reply["status"] == "proposed"
    assert tools.replies[0]["author"] == "AI Assistant"
    assert tools.operations == []
    assert tools.replies[0]["intent"] == "clarify"
    with pytest.raises(ReportingError):
        tools.skip_note("a" * 64, "")


def test_actual_pdf_author_prevents_reprocessing_ai_comment():
    from smart_reporting.report_editor.native_pdf_review_ai import NativePDFReviewTools

    tools = review_tools()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    annotation = Text(rect=(10, 10, 30, 30), text="Please change revenue")
    from pypdf.generic import NameObject, TextStringObject

    annotation[NameObject("/T")] = TextStringObject("AI Assistant")
    writer.add_annotation(1, annotation)
    stream = BytesIO()
    writer.write(stream)
    content = stream.getvalue()
    raw = PdfReader(BytesIO(content)).pages[1]["/Annots"][0]
    tools.reader._content = content
    tools.reader.pages[1]["notes"][0]["sourceRef"] = f"{raw.idnum}R{raw.generation or ''}"
    actual = NativePDFReviewTools(tools.reader)
    read = actual.read_annotations()
    assert read["annotations"][0]["author"] == "AI Assistant"
    actual.read_pages(start_page=2)
    with pytest.raises(ReportingError, match="AI"):
        actual.propose_replace_text("a" * 64, 2, "Revenue is 42.", "Revenue is 43.", "更正")
    actual.skip_note("a" * 64, "AI 自身批注，不重复处理。")


@pytest.mark.anyio
async def test_real_agno_loop_uses_private_candidates_instead_of_summary():
    from smart_reporting.report_editor.native_pdf_review_ai import AgnoNativePDFReviewPlanner

    def call(name, arguments, identifier):
        return ModelResponse(
            tool_calls=[
                {
                    "id": identifier,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ]
        )

    tools = review_tools()
    model = ScriptedModel(
        id="scripted-review",
        responses=[
            call("read_annotations", {}, "read-notes"),
            call("read_pages", {"start_page": 2}, "read-body"),
            call(
                "propose_replace_text",
                {
                    "annotation_id": "a" * 64,
                    "page_number": 2,
                    "old_text": "Revenue is 42.",
                    "new_text": "Revenue is 43.",
                    "reason": "按批注意见更正",
                },
                "replace",
            ),
            call(
                "propose_reply",
                {
                    "annotation_id": "a" * 64,
                    "contents": "拟将金额改为43，待采纳。",
                    "intent": "change",
                },
                "reply",
            ),
            ModelResponse(content=json.dumps({"answer": "已提出一条改字及对应回复候选，待采纳。"})),
        ],
    )
    result = await AgnoNativePDFReviewPlanner(model)(
        reader=tools.reader, instruction="处理批注", session_id="test-review", user_id="user"
    )
    assert len(result["operations"]) == len(result["replies"]) == 1
    assert result["notes"][0]["operationIndices"] == [0]
    assert result["coverage"]["annotationsReadComplete"] is True
    assert result["coverage"]["fullyReadPages"] == [2]


def test_long_note_requires_all_cursors_before_proposing_and_change_reply_needs_edit():
    tools = review_tools()
    tools.reader.pages[1]["notes"][0]["contents"] = "A" * 7000
    first = tools.read_annotations()
    tools.read_pages(start_page=2)
    with pytest.raises(ReportingError, match="完整读取"):
        tools.propose_reply("a" * 64, "请确认？", intent="clarify")
    tools.read_annotations(**first["next"])
    with pytest.raises(ReportingError, match="尚无实际.*候选"):
        tools.propose_reply("a" * 64, "已改字。")
    result = tools.propose_reply("a" * 64, "请确认？", intent="clarify")
    assert result["intent"] == "clarify"


def test_unread_notes_are_explicitly_unhandled_instead_of_claimed_complete():
    tools = review_tools()
    result = tools.result("尚未完整读取。")
    assert result["notes"][0]["status"] == "skipped"
    assert "未完整读取" in result["notes"][0]["reason"]
    assert result["issues"][0]["code"] == "native_ai_review_incomplete_coverage"


def test_projected_note_rebind_requires_same_exact_ref_even_when_content_duplicates():
    from copy import deepcopy

    tools = review_tools()
    original = deepcopy(tools.reader.pages)
    note = tools.reader.pages[1]["notes"][0]
    original[1]["notes"][0]["sourceRef"] = "12R"
    duplicate = deepcopy(original[1]["notes"][0])
    duplicate.update(annotationId="d" * 64, sourceRef="13R")
    original[1]["notes"].append(duplicate)
    note.update(annotationId="e" * 64, sourceRef="13R", expectedAnnotationSha256="f" * 64)
    tools.reader._original_pages = original
    tools.reader._operations = [
        {"kind": "replaceText", "pageId": original[1]["pageId"], "objectId": "elsewhere"}
    ]
    tools.reader.projection = {
        "pageMapping": [
            {"originalPageId": original[0]["pageId"]},
            {"originalPageId": original[1]["pageId"]},
        ],
        "appliedOperationIndices": [0],
    }
    rebound = tools._original_note({**note, "pageNumber": 2})
    assert rebound["annotationId"] == "d" * 64
    assert rebound["expectedAnnotationSha256"] == "b" * 64
    note["sourceRef"] = "foreignR"
    with pytest.raises(ReportingError, match="重绑"):
        tools._original_note({**note, "pageNumber": 2})
