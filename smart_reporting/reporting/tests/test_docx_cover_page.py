"""insertCoverPage：固定源 editor/cover-pages.ts 封面段落写回与独立回读。"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

CLASSIC = [
    {"spaceBefore": 3600},
    {"text": "年度报告", "bold": True, "sizeHalfPoints": 72, "align": "center", "spaceAfter": 240},
    {"text": "副标题", "color": "595959", "sizeHalfPoints": 28, "align": "center", "borders": "t", "spaceAfter": 4800},
    {"text": "作者", "sizeHalfPoints": 24, "align": "center", "shadingFill": "1F3864"},
]


def make_doc() -> bytes:
    doc = Document()
    doc.add_paragraph("first body")
    doc.add_paragraph("second body")
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def cover_op(data: bytes, index: int, paras=CLASSIC) -> dict:
    block = inspect_docx(data)["blocks"][index]
    return {"kind": "insertCoverPage", "blockId": block["blockId"], "expectedObjectSha256": block["expectedObjectSha256"],
            "position": "before", "paras": paras}


def test_cover_page_writes_formatted_paragraphs_bookmarks_and_trailing_break_at_document_start():
    source = make_doc()
    patched = patch_docx(source, [cover_op(source, 0)])
    paragraphs = Document(BytesIO(patched)).paragraphs
    assert [p.text for p in paragraphs] == ["", "年度报告", "副标题", "作者", "", "first body", "second body"]
    assert paragraphs[0].paragraph_format.space_before.twips == 3600
    title = paragraphs[1]
    assert title.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert title.runs[0].bold is True and title.runs[0].font.size.pt == 36
    subtitle = paragraphs[2]
    assert str(subtitle.runs[0].font.color.rgb) == "595959"
    assert subtitle._p.pPr.find(qn("w:pBdr")).find(qn("w:top")).get(qn("w:val")) == "single"
    assert paragraphs[3]._p.pPr.find(qn("w:shd")).get(qn("w:fill")) == "1F3864"
    assert paragraphs[4].paragraph_format.page_break_before is True
    names = [el.get(qn("w:name")) for el in Document(BytesIO(patched)).element.body.iter(qn("w:bookmarkStart"))]
    assert names[:2] == ["_GenOfficeCoverPage", "_GenOfficeCoverPageEnd"]
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(patched)) as after:
        assert after.read("word/styles.xml") == before.read("word/styles.xml")


def test_cover_page_may_replace_deleted_leading_blocks_but_never_lands_mid_document():
    source = make_doc()
    first = inspect_docx(source)["blocks"][0]
    replaced = patch_docx(source, [
        {"kind": "deleteParagraph", "blockId": first["blockId"], "expectedObjectSha256": first["expectedObjectSha256"]},
        cover_op(source, 1),
    ])
    assert [p.text for p in Document(BytesIO(replaced)).paragraphs][-1] == "second body"
    assert "first body" not in [p.text for p in Document(BytesIO(replaced)).paragraphs]
    with pytest.raises(ValueError, match="cover_page_not_at_start"):
        patch_docx(source, [cover_op(source, 1)])
    with pytest.raises(ValueError, match="cover_page_batch_conflict"):
        patch_docx(source, [cover_op(source, 0), cover_op(source, 0)])


@pytest.mark.parametrize("paras", [
    [],
    [{"text": "x", "font": "Arial"}],
    [{"text": "x", "color": "#123456"}],
    [{"text": "x", "sizeHalfPoints": 1}],
    [{"text": "x", "borders": "tt"}],
    [{"text": "x", "align": "justify"}],
    [{"text": "x\x01"}],
    [{"text": "x"}] * 21,
])
def test_cover_page_rejects_specs_outside_the_bounded_schema(paras):
    source = make_doc()
    with pytest.raises(ValueError):
        patch_docx(source, [cover_op(source, 0, paras)])
