import hashlib
import io

import pytest
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.document_candidate_contract import (
    DocumentCandidateRequest, DocumentFormat, DocumentScope,
)
from smart_reporting.document_candidate_pptx_preview import PptxTextPreviewEngine


def sample_pptx():
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    shape = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    shape.text = "Original title"
    out = io.BytesIO()
    deck.save(out)
    return out.getvalue(), slide.slide_id, shape.shape_id


@pytest.mark.anyio
async def test_pptx_preview_reads_real_slide_without_saving():
    original, slide_id, shape_id = sample_pptx()
    scope = DocumentScope(
        "channel", "grant", "deck", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.PPTX,
    )

    async def load(_):
        return original

    async def propose(_):
        return ({"slide_id": slide_id, "shape_id": shape_id, "text": "Revised title"},)

    engine = PptxTextPreviewEngine(load, propose)
    request = DocumentCandidateRequest(
        scope, "one", "Rewrite title",
        ({"slide_id": slide_id, "shape_id": shape_id},),
    )
    result = await engine.prepare(request)
    assert result == {
        "status": "preview_ready", "accepted": False,
        "changes": [{
            "slide_id": slide_id, "shape_id": shape_id,
            "before": "Original title", "after": "Revised title",
        }],
    }
    assert Presentation(io.BytesIO(original)).slides[0].shapes[0].text == "Original title"


@pytest.mark.anyio
async def test_pptx_preview_rejects_unapproved_shape():
    original, slide_id, shape_id = sample_pptx()
    scope = DocumentScope(
        "channel", "grant", "deck", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.PPTX,
    )

    async def load(_):
        return original

    async def propose(_):
        return ({"slide_id": slide_id, "shape_id": shape_id + 1, "text": "Wrong shape"},)

    request = DocumentCandidateRequest(
        scope, "one", "Rewrite",
        ({"slide_id": slide_id, "shape_id": shape_id},),
    )
    with pytest.raises(ValueError, match="pptx_operation_target_unapproved"):
        await PptxTextPreviewEngine(load, propose).prepare(request)


@pytest.mark.anyio
async def test_pptx_preview_rejects_source_changed_during_text_extraction():
    original, slide_id, shape_id = sample_pptx()
    scope = DocumentScope(
        "channel", "grant", "deck", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.PPTX,
    )
    reads = 0

    async def load(_):
        nonlocal reads
        reads += 1
        return original if reads < 3 else original + b"changed"

    async def propose(_):
        return ({"slide_id": slide_id, "shape_id": shape_id, "text": "New"},)

    request = DocumentCandidateRequest(
        scope, "one", "Rewrite", ({"slide_id": slide_id, "shape_id": shape_id},),
    )
    with pytest.raises(PermissionError, match="document_source_changed"):
        await PptxTextPreviewEngine(load, propose).prepare(request)
    assert reads == 3
