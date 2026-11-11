from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from smart_reporting.reporting.delivery.pdf_native import extract_pdf_pages


def source_pdf() -> bytes:
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(300, 400))
    for text in ("source page one", "source page two", "source page three"):
        canvas.drawString(24, 350, text)
        canvas.showPage()
    canvas.save()
    return stream.getvalue()


def test_extract_pages_returns_separately_identified_pdf_without_changing_source():
    source = source_pdf()
    source_sha256 = hashlib.sha256(source).hexdigest()

    receipt = extract_pdf_pages(source, [2, 0])
    extracted = PdfReader(BytesIO(receipt["content"]))

    assert receipt["sourceSha256"] == source_sha256
    assert receipt["sha256"] == hashlib.sha256(receipt["content"]).hexdigest()
    assert receipt["size"] == len(receipt["content"])
    assert receipt["pageCount"] == len(extracted.pages) == 2
    assert [page.extract_text().strip() for page in extracted.pages] == [
        "source page three",
        "source page one",
    ]
    assert len(PdfReader(BytesIO(source)).pages) == 3
    assert hashlib.sha256(source).hexdigest() == source_sha256


@pytest.mark.parametrize("pages", [[], [0, 0], [-1], [3]])
def test_extract_pages_rejects_empty_duplicate_and_out_of_range_selections(pages):
    with pytest.raises(ValueError):
        extract_pdf_pages(source_pdf(), pages)
