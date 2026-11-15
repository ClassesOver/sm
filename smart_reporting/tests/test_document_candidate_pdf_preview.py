import hashlib

import fitz
import pytest

from smart_reporting.document_candidate_contract import (
    DocumentCandidateRequest, DocumentFormat, DocumentScope,
)
from smart_reporting.document_candidate_pdf_preview import PdfAnnotationPreviewEngine


def sample_pdf():
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    page.insert_text((50, 60), "Important evidence")
    content = document.tobytes()
    document.close()
    return content


@pytest.mark.anyio
async def test_pdf_annotation_preview_reads_page_without_writing():
    original = sample_pdf()
    scope = DocumentScope(
        "channel", "grant", "pdf", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.PDF,
    )
    selection = ({"page": 0, "rect": [0.05, 0.1, 0.8, 0.3]},)

    async def source(_):
        return original

    async def propose(_):
        return ({"page": 0, "rect": [0.05, 0.1, 0.8, 0.3], "note": "Verify"},)

    request = DocumentCandidateRequest(scope, "one", "Add review note", selection)
    engine = PdfAnnotationPreviewEngine(source, propose)
    task_id = await engine.prepare(request)
    result = await engine.status(scope, task_id)
    assert result["status"] == "preview_ready"
    assert result["accepted"] is False
    assert "Important" in result["changes"][0]["context"]
    with fitz.open(stream=original, filetype="pdf") as document:
        assert document[0].first_annot is None


@pytest.mark.anyio
async def test_pdf_annotation_preview_rejects_unapproved_page():
    original = sample_pdf()
    scope = DocumentScope(
        "channel", "grant", "pdf", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.PDF,
    )

    async def source(_):
        return original

    async def propose(_):
        return ({"page": 1, "rect": [0, 0, 1, 1], "note": "Wrong page"},)

    request = DocumentCandidateRequest(
        scope, "one", "Add note", ({"page": 0, "rect": [0, 0, 1, 1]},),
    )
    with pytest.raises(ValueError, match="pdf_annotation_target_unapproved"):
        await PdfAnnotationPreviewEngine(source, propose).prepare(request)


@pytest.mark.anyio
async def test_pdf_preview_task_is_idempotent_and_grant_scoped():
    original = sample_pdf()
    scope = DocumentScope(
        "channel", "grant", "pdf", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.PDF,
    )
    calls = 0

    async def source(_):
        return original

    async def propose(_):
        nonlocal calls
        calls += 1
        return ({"page": 0, "rect": [0, 0, 1, 1], "note": "Verify"},)

    engine = PdfAnnotationPreviewEngine(source, propose)
    request = DocumentCandidateRequest(
        scope, "same", "Annotate", ({"page": 0, "rect": [0, 0, 1, 1]},),
    )
    task = await engine.prepare(request)
    assert await engine.prepare(request) == task
    assert calls == 1
    with pytest.raises(ValueError, match="document_request_id_conflict"):
        await engine.prepare(DocumentCandidateRequest(
            scope, "same", "Different", ({"page": 0, "rect": [0, 0, 1, 1]},),
        ))
    with pytest.raises(PermissionError):
        await engine.status(DocumentScope(
            "channel", "another-grant", "pdf", "1", scope.source_sha256,
            DocumentFormat.PDF,
        ), task)


@pytest.mark.anyio
async def test_pdf_preview_rejects_source_changed_during_page_extraction():
    original = sample_pdf()
    changed = original + b"new revision"
    scope = DocumentScope(
        "channel", "grant", "pdf", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.PDF,
    )
    reads = 0

    async def source(_):
        nonlocal reads
        reads += 1
        return changed if reads >= 3 else original

    async def propose(_):
        return ({"page": 0, "rect": [0, 0, 1, 1], "note": "Verify"},)

    engine = PdfAnnotationPreviewEngine(source, propose)
    request = DocumentCandidateRequest(
        scope, "one", "Annotate", ({"page": 0, "rect": [0, 0, 1, 1]},),
    )
    with pytest.raises(PermissionError, match="document_source_changed"):
        await engine.prepare(request)
    assert reads == 3


@pytest.mark.anyio
async def test_pdf_preview_maps_rotated_page_selection_into_text_coordinates():
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    page.insert_text((50, 60), "ROTATED_EVIDENCE")
    page.set_rotation(90)
    original = document.tobytes()
    document.close()
    scope = DocumentScope(
        "channel", "grant", "rotated", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.PDF,
    )
    selection = ({"page": 0, "rect": [0.76, 0.1, 0.9, 0.5]},)

    async def source(_):
        return original

    async def propose(_):
        return ({"page": 0, "rect": [0.76, 0.1, 0.9, 0.5], "note": "Review"},)

    engine = PdfAnnotationPreviewEngine(source, propose)
    request = DocumentCandidateRequest(scope, "rotated-one", "Annotate", selection)
    task_id = await engine.prepare(request)
    preview = await engine.status(scope, task_id)
    assert preview["accepted"] is False
    assert "ROTATED_EVIDENCE" in preview["changes"][0]["context"]


@pytest.mark.anyio
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("cropped", [False, True])
async def test_pdf_preview_resolves_rendered_selection_for_rotated_cropped_page(rotation, cropped):
    document = fitz.open()
    page = document.new_page(width=500, height=400)
    page.insert_text((140, 140), "ROTATED_EVIDENCE")
    if cropped:
        page.set_cropbox(fitz.Rect(60, 60, 460, 360))
    page.set_rotation(rotation)
    word = page.get_text("words")[0]
    rendered = fitz.Rect(word[:4]) * page.rotation_matrix
    bounds = page.rect
    padding = 5
    normalized = [
        (rendered.x0 - padding - bounds.x0) / bounds.width,
        (rendered.y0 - padding - bounds.y0) / bounds.height,
        (rendered.x1 + padding - bounds.x0) / bounds.width,
        (rendered.y1 + padding - bounds.y0) / bounds.height,
    ]
    assert all(0 <= value <= 1 for value in normalized)
    original = document.tobytes()
    document.close()
    scope = DocumentScope(
        "channel", "grant", "rotated-cropped", "1",
        hashlib.sha256(original).hexdigest(), DocumentFormat.PDF,
    )

    async def source(_):
        return original

    async def propose(_):
        return ({"page": 0, "rect": normalized, "note": "Review"},)

    engine = PdfAnnotationPreviewEngine(source, propose)
    request = DocumentCandidateRequest(
        scope, "rotation-test", "Annotate",
        ({"page": 0, "rect": normalized},),
    )
    task = await engine.prepare(request)
    preview = await engine.status(scope, task)
    assert "ROTATED_EVIDENCE" in preview["changes"][0]["context"]
