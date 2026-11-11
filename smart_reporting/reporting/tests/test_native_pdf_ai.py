"""PDF 只读工具边界与真实 Agno 循环；脚本模型不代表真实 provider。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import pytest
from agno.models.base import Model
from agno.models.response import ModelResponse
from pypdf import PdfWriter

from smart_reporting.report_editor.native_models import NativeEditorContext, NativeScope
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.models import ReportingError


def sample():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    writer.add_outline_item("Chapter", 1)
    stream = BytesIO()
    writer.write(stream)
    content = stream.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    context = NativeEditorContext(
        documentId="pdf",
        revision=2,
        format="pdf",
        origin="upload",
        scope=NativeScope(
            database="db", companyId="co", userId="user", threadId="thread"
        ),
        sourceFile=ArtifactFile(
            path="native/source.pdf",
            size=len(content),
            sha256=digest,
            mediaType="application/pdf",
        ),
    )
    pages = [
        {
            "pageId": f"sha256:{digest}:page:{i}",
            "index": i,
            "textObjects": [{"objectId": f"object-{i}", "text": text}],
            "notesReadSafe": True,
            "markupReadSafe": True,
            "notes": [],
            "markups": [],
        }
        for i, text in enumerate(["A" * 24005, "Revenue is 42."])
    ]
    pages[1]["notes"] = [
        {
            "annotationId": "note-1",
            "contents": "Please verify revenue",
            "parentAnnotationId": "root",
        }
    ]
    return context, content, {"sourceSha256": digest, "pageCount": 2, "pages": pages}


async def reader(monkeypatch):
    from smart_reporting.report_editor import native_pdf_ai as module

    context, content, model = sample()
    monkeypatch.setattr(module, "inspect_pdf", lambda data, **kwargs: model)
    return (
        await module.NativePDFTaskReader.from_bytes(context, content),
        context,
        content,
    )


@pytest.mark.anyio
async def test_pdf_reader_tracks_partial_text_and_cursor_without_claiming_full_coverage(
    monkeypatch,
):
    r, _, _ = await reader(monkeypatch)
    first = r.read_pages(start_page=1, page_count=2)
    assert first["pages"][0]["text"] == "A" * 24000
    assert first["truncated"] is True
    assert first["next"] == {"start_page": 1, "text_offset": 24000}
    assert r.coverage()["fullyReadPages"] == []
    rest = r.read_pages(start_page=1, page_count=2, text_offset=24000)
    assert rest["pages"][0]["text"] == "AAAAA"
    assert rest["pages"][1]["text"] == "Revenue is 42."
    assert r.coverage()["fullyReadPages"] == [1, 2]
    assert r.coverage()["fullDocumentRead"] is True


@pytest.mark.anyio
async def test_pdf_tools_keep_unknown_annotation_metadata_and_source_bound_outline(
    monkeypatch,
):
    r, context, _ = await reader(monkeypatch)
    notes = r.read_annotations(limit=1)
    assert notes["annotations"][0]["author"] == "unknown"
    assert notes["annotations"][0]["state"] == "unknown"
    assert notes["annotations"][0]["createdAt"] == "unknown"
    assert notes["annotations"][0]["parentAnnotationId"] == "root"
    assert notes["sourceSha256"] == context.source_file.sha256
    assert r.get_outline()["items"] == [
        {"title": "Chapter", "pageNumber": 2, "level": 0}
    ]
    search = r.search_text("42", start_page=2)
    assert search["matches"][0]["pageNumber"] == 2
    assert search["matches"][0]["text"] == "Revenue is 42."
    assert r.coverage()["fullDocumentRead"] is False


@pytest.mark.anyio
async def test_pdf_reader_rejects_changed_source_draft_and_forged_selection(
    monkeypatch,
):
    from smart_reporting.report_editor import native_pdf_ai as module

    r, context, content = await reader(monkeypatch)
    with pytest.raises(ReportingError, match="来源"):
        await module.NativePDFTaskReader.from_bytes(context, content + b"changed")
    with pytest.raises(ReportingError, match="草稿"):
        await module.NativePDFTaskReader.from_bytes(
            context, content, operations=[{"kind": "rotatePage"}]
        )
    with pytest.raises(ReportingError, match="选区"):
        r.bind_selection(
            [{"pageId": context.source_file.sha256, "objectId": "object-1"}]
        )
    r.bind_selection([{"pageId": r.pages[1]["pageId"], "objectId": "object-1"}])
    assert r.read_pages(start_page=2)["pages"][0]["text"] == "Revenue is 42."
    with pytest.raises(ReportingError, match="选区"):
        r.read_pages(start_page=1)
    with pytest.raises(ReportingError, match="选区"):
        r.get_outline()


@pytest.mark.anyio
async def test_pdf_long_annotation_cursor_reads_remaining_text_without_false_completion(
    monkeypatch,
):
    from smart_reporting.report_editor import native_pdf_ai as module

    context, content, model = sample()
    full = "A" * 6000 + "B" * 6000 + "C" * 2000
    model["pages"][1]["notes"] = [{"annotationId": "long", "contents": full}]
    monkeypatch.setattr(module, "inspect_pdf", lambda *args, **kwargs: model)
    r = await module.NativePDFTaskReader.from_bytes(context, content)
    first = r.read_annotations()
    assert first["next"] == {"offset": 0, "text_offset": 6000}
    r.read_annotations()
    assert r.coverage()["annotationsReadComplete"] is False
    second = r.read_annotations(**first["next"])
    assert second["next"] == {"offset": 0, "text_offset": 12000}
    assert r.coverage()["annotationsReadComplete"] is False
    third = r.read_annotations(**second["next"])
    assert third["next"] is None
    assert (
        first["annotations"][0]["contents"]
        + second["annotations"][0]["contents"]
        + third["annotations"][0]["contents"]
        == full
    )
    assert r.coverage()["annotationsReadComplete"] is True


@dataclass
class ScriptedModel(Model):
    responses: list[ModelResponse] = field(default_factory=list)
    seen: list[list[Any]] = field(default_factory=list)
    expected_tool_text: str | None = None

    def invoke(self, *args, **kwargs):
        self.seen.append(list(kwargs.get("messages", args[0] if args else [])))
        if self.expected_tool_text and len(self.responses) == 1:
            assert any(
                m.role == "tool" and self.expected_tool_text in str(m.content)
                for m in self.seen[-1]
            )
        return self.responses.pop(0)

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response, **kwargs):
        return response


@pytest.mark.anyio
async def test_pdf_planner_uses_real_agno_tool_loop_and_does_not_trust_model_coverage(
    monkeypatch,
):
    from smart_reporting.report_editor.native_pdf_ai import (
        create_native_pdf_read_planner,
    )

    _, context, content = await reader(monkeypatch)
    model = ScriptedModel(
        id="scripted",
        expected_tool_text="Revenue is 42.",
        responses=[
            ModelResponse(
                tool_calls=[
                    {
                        "id": "call-read",
                        "type": "function",
                        "function": {
                            "name": "read_pages",
                            "arguments": '{"start_page":2,"page_count":1}',
                        },
                    }
                ]
            ),
            ModelResponse(
                content=json.dumps(
                    {"answer": "Revenue is 42 (page 2).", "citations": [2]}
                )
            ),
        ],
    )
    result = await create_native_pdf_read_planner(model)(
        context=context,
        content=content,
        operations=[],
        action="ask",
        instruction="What is the revenue?",
        selection=[],
        session_id="task",
        user_id="user",
    )
    assert result["answer"] == "Revenue is 42 (page 2)."
    assert result["coverage"]["fullyReadPages"] == [2]
    assert result["coverage"]["fullDocumentRead"] is False
    assert result["citations"][0]["pageNumber"] == 2
    assert [e["tool"] for e in result["toolEvents"]] == ["read_pages"]
    assert "operations" not in result


@pytest.mark.anyio
async def test_pdf_planner_drops_unread_page_citations_and_marks_incomplete_summary(
    monkeypatch,
):
    from smart_reporting.report_editor.native_pdf_ai import (
        create_native_pdf_read_planner,
    )

    _, context, content = await reader(monkeypatch)
    model = ScriptedModel(
        id="scripted",
        responses=[
            ModelResponse(
                content=json.dumps(
                    {"answer": "Unsupported complete summary.", "citations": [1]}
                )
            )
        ],
    )
    result = await create_native_pdf_read_planner(model)(
        context=context,
        content=content,
        operations=[],
        action="summarize",
        instruction="Summarize all pages",
        selection=[],
        session_id="task",
        user_id="user",
    )
    assert result["citations"] == []
    assert result["coverage"]["fullDocumentRead"] is False
    assert {"native_pdf_ai_unread_citation", "native_pdf_ai_incomplete_coverage"} <= {
        i["code"] for i in result["issues"]
    }


@pytest.mark.anyio
async def test_pdf_reader_separates_text_objects_and_does_not_treat_missing_text_as_empty(
    monkeypatch,
):
    from smart_reporting.report_editor import native_pdf_ai as module

    context, content, model = sample()
    model["pages"][1]["textObjects"].append(
        {"objectId": "second", "text": "Second line"}
    )
    monkeypatch.setattr(module, "inspect_pdf", lambda *args, **kwargs: model)
    r = await module.NativePDFTaskReader.from_bytes(context, content)
    assert (
        r.read_pages(start_page=2)["pages"][0]["text"]
        == "Revenue is 42." + chr(10) + "Second line"
    )
    del model["pages"][0]["textObjects"]
    with pytest.raises(ReportingError, match="文字"):
        await module.NativePDFTaskReader.from_bytes(context, content)


@pytest.mark.anyio
async def test_pdf_annotation_character_budget_reports_truncation_and_continuation(
    monkeypatch,
):
    from smart_reporting.report_editor import native_pdf_ai as module

    context, content, model = sample()
    model["pages"][1]["notes"] = [
        {"annotationId": str(i), "contents": "N" * 6000} for i in range(7)
    ]
    monkeypatch.setattr(module, "inspect_pdf", lambda *args, **kwargs: model)
    r = await module.NativePDFTaskReader.from_bytes(context, content)
    first = r.read_annotations(limit=50)
    assert sum(len(a["contents"]) for a in first["annotations"]) <= 24000
    assert first["truncated"] is True
    assert first["nextOffset"] == 4
    assert r.coverage()["annotationsReadComplete"] is False
    rest = r.read_annotations(offset=4)
    assert len(rest["annotations"]) == 3
    assert r.coverage()["annotationsReadComplete"] is True


@pytest.mark.anyio
async def test_pdf_selected_text_does_not_allow_reading_unselected_annotations(
    monkeypatch,
):
    r, _, _ = await reader(monkeypatch)
    r.bind_selection([{"pageId": r.pages[1]["pageId"], "objectId": "object-1"}])
    with pytest.raises(ReportingError, match="选区"):
        r.read_annotations()


@pytest.mark.anyio
async def test_pdf_reader_reads_real_engine_text_notes_outline_without_editing(
    tmp_path,
):
    from reportlab.pdfgen.canvas import Canvas

    from smart_reporting.report_editor.native_pdf_ai import NativePDFTaskReader

    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(300, 300))
    canvas.bookmarkPage("first")
    canvas.addOutlineEntry("Real chapter", "first", 0)
    canvas.drawString(30, 240, "Real revenue 42")
    canvas.drawString(30, 210, "Second line")
    canvas.textAnnotation("Verify this amount", (30, 100, 50, 120))
    canvas.showPage()
    canvas.drawString(30, 240, "Unchanged second page")
    canvas.save()
    content = stream.getvalue()
    context, _, _ = sample()
    context = context.model_copy(
        update={
            "source_file": ArtifactFile(
                path="native/real.pdf",
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                mediaType="application/pdf",
            )
        }
    )
    r = await NativePDFTaskReader.from_bytes(context, content)
    pages = r.read_pages()
    assert pages["pages"][0]["text"] == "Real revenue 42" + chr(10) + "Second line"
    assert pages["pages"][1]["text"] == "Unchanged second page"
    assert r.coverage()["fullDocumentRead"] is True
    notes = r.read_annotations()
    assert notes["annotations"][0]["contents"] == "Verify this amount"
    assert notes["annotations"][0]["author"] == "unknown"
    assert r.get_outline()["items"] == [
        {"title": "Real chapter", "pageNumber": 1, "level": 0}
    ]
    assert hashlib.sha256(content).hexdigest() == context.source_file.sha256


@pytest.mark.anyio
async def test_pdf_search_offsets_reference_original_unicode_text(monkeypatch):
    from smart_reporting.report_editor import native_pdf_ai as module

    context, content, model = sample()
    model["pages"][1]["textObjects"][0]["text"] = "ß REVENUE"
    monkeypatch.setattr(module, "inspect_pdf", lambda *args, **kwargs: model)
    r = await module.NativePDFTaskReader.from_bytes(context, content)
    assert r.search_text("revenue", start_page=2)["matches"][0]["offset"] == 2


@pytest.mark.anyio
async def test_pdf_annotations_require_actual_tool_read_even_when_empty(monkeypatch):
    from smart_reporting.report_editor import native_pdf_ai as module

    context, content, model = sample()
    model["pages"][1]["notes"] = []
    monkeypatch.setattr(module, "inspect_pdf", lambda *args, **kwargs: model)
    r = await module.NativePDFTaskReader.from_bytes(context, content)
    assert r.coverage()["annotationsReadComplete"] is False
    r.read_annotations()
    assert r.coverage()["annotationsReadComplete"] is True


@pytest.mark.anyio
async def test_pdf_planner_isolates_agno_model_state_between_concurrent_tasks(
    monkeypatch,
):
    import asyncio

    from smart_reporting.report_editor.native_pdf_ai import (
        create_native_pdf_read_planner,
    )

    _, context, content = await reader(monkeypatch)
    model = ScriptedModel(
        id="scripted",
        responses=[
            ModelResponse(
                tool_calls=[
                    {
                        "id": "read",
                        "type": "function",
                        "function": {
                            "name": "read_pages",
                            "arguments": '{"start_page":2}',
                        },
                    }
                ]
            ),
            ModelResponse(
                content=json.dumps({"answer": "Read page 2.", "citations": [2]})
            ),
        ],
    )
    planner = create_native_pdf_read_planner(model)

    async def task(name):
        return await planner(
            context=context,
            content=content,
            operations=[],
            action="ask",
            instruction="Read page 2",
            selection=[],
            session_id=name,
            user_id="user",
        )

    results = await asyncio.gather(
        task("first"), task("second"), return_exceptions=True
    )
    assert all(isinstance(result, dict) for result in results), results
    assert all(result["coverage"]["fullyReadPages"] == [2] for result in results)
    assert all(
        [event["tool"] for event in result["toolEvents"]] == ["read_pages"]
        for result in results
    )
    assert len(model.responses) == 2


@pytest.mark.anyio
async def test_pdf_selected_task_reports_only_authorized_page_scope(monkeypatch):
    from smart_reporting.report_editor.native_pdf_ai import (
        create_native_pdf_read_planner,
    )

    r, context, content = await reader(monkeypatch)
    r.pages[1]["textObjects"].append(
        {"objectId": "neighbor", "text": "Unselected secret"}
    )
    model = ScriptedModel(
        id="scripted",
        responses=[
            ModelResponse(
                tool_calls=[
                    {
                        "id": "read",
                        "type": "function",
                        "function": {
                            "name": "read_pages",
                            "arguments": '{"start_page":2}',
                        },
                    }
                ]
            ),
            ModelResponse(
                content=json.dumps(
                    {"answer": "Selected revenue is 42.", "citations": [2]}
                )
            ),
        ],
    )
    result = await create_native_pdf_read_planner(model)(
        context=context,
        content=content,
        operations=[],
        action="summarize",
        instruction="Summarize selection",
        selection=[{"pageId": r.pages[1]["pageId"], "objectId": "object-1"}],
        session_id="selected",
        user_id="user",
    )
    assert result["coverage"]["scopePages"] == [2]
    assert result["coverage"]["scopeReadComplete"] is True
    assert result["coverage"]["fullDocumentRead"] is False
    assert result["issues"] == []
    r.bind_selection([{"pageId": r.pages[1]["pageId"], "objectId": "object-1"}])
    assert r.read_pages(start_page=2)["pages"][0]["text"] == "Revenue is 42."


@pytest.mark.anyio
async def test_pdf_outline_tool_does_not_block_task_cancellation(monkeypatch):
    import asyncio
    import threading
    import time

    from smart_reporting.report_editor import native_pdf_ai as module

    _, context, content = await reader(monkeypatch)
    entered = threading.Event()
    original = module.PdfReader

    def slow_reader(*args, **kwargs):
        entered.set()
        time.sleep(0.3)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "PdfReader", slow_reader)
    model = ScriptedModel(
        id="scripted",
        responses=[
            ModelResponse(
                tool_calls=[
                    {
                        "id": "outline",
                        "type": "function",
                        "function": {"name": "get_outline", "arguments": "{}"},
                    }
                ]
            ),
            ModelResponse(
                content=json.dumps({"answer": "Read outline.", "citations": []})
            ),
        ],
    )
    planner = module.create_native_pdf_read_planner(model)
    task = asyncio.create_task(
        planner(
            context=context,
            content=content,
            operations=[],
            action="ask",
            instruction="Read outline",
            selection=[],
            session_id="outline",
            user_id="user",
        )
    )
    assert await asyncio.to_thread(entered.wait, 1)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(task, 0.02)


@pytest.mark.anyio
async def test_pdf_concurrent_page_tools_preserve_coverage_ledger(monkeypatch):
    import asyncio
    import threading

    r, _, _ = await reader(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    original = r._text

    def pause_coverage(index):
        if index == 0 and 0 in r._spans and not entered.is_set():
            entered.set()
            assert release.wait(1)
        return original(index)

    monkeypatch.setattr(r, "_text", pause_coverage)
    first = asyncio.create_task(asyncio.to_thread(r.read_pages, 1, 1))
    assert await asyncio.to_thread(entered.wait, 1)
    try:
        await asyncio.to_thread(r.read_pages, 2, 1)
    finally:
        release.set()
    await first
    assert r.coverage()["fullyReadPages"] == [2]
