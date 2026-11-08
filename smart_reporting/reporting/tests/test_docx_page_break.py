"""setParagraphPageBreakBefore / insertParagraph(pageBreakBefore) 原 XML 最小补丁回读。

固定源 GenOffice f8c17004 apps/docs/src/renderer/editor/page-break.ts：分页符 = 段落
pageBreakBefore（段首直接标记当前段，段中拆分后标记后半段）。
"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_doc(extra_ppr: list[str] | None = None) -> bytes:
    doc = Document()
    doc.add_paragraph("first")
    target = doc.add_paragraph("target", style="List Bullet")
    run = target.add_run(" keep")
    run.bold = True
    target.paragraph_format.space_after = 0
    for xml in extra_ppr or []:
        target._p.get_or_add_pPr().append(etree.fromstring(xml))
    doc.add_paragraph("untouched")
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def block(data: bytes, index: int) -> dict:
    return inspect_docx(data)["blocks"][index]


def page_break_op(data: bytes, value: bool, index: int = 1) -> dict:
    target = block(data, index)
    return {"kind": "setParagraphPageBreakBefore", "blockId": target["blockId"],
            "expectedObjectSha256": target["expectedObjectSha256"], "value": value}


def ppr_children(data: bytes, index: int = 1) -> list[str]:
    ppr = Document(BytesIO(data)).paragraphs[index]._p.find(qn("w:pPr"))
    return [child.tag.split("}")[1] for child in ppr]


def test_page_break_before_is_inserted_in_schema_order_and_preserves_everything_else():
    source = make_doc()
    patched = patch_docx(source, [page_break_op(source, True)])
    paragraphs = Document(BytesIO(patched)).paragraphs
    assert paragraphs[1].paragraph_format.page_break_before is True
    assert paragraphs[1].text == "target keep"
    assert paragraphs[1].runs[1].bold is True
    assert paragraphs[1].style.name == "List Bullet"
    assert paragraphs[1].paragraph_format.space_after == 0
    assert paragraphs[0].paragraph_format.page_break_before is None
    assert paragraphs[2].paragraph_format.page_break_before is None
    children = ppr_children(patched)
    # CT_PPr 顺序：pStyle < pageBreakBefore < spacing。
    assert children.index("pStyle") < children.index("pageBreakBefore") < children.index("spacing")
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(patched)) as after:
        for name in before.namelist():
            if name not in {"word/document.xml"}:
                assert after.read(name) == before.read(name), name
    # 再打开：模型读出分页，空操作不改变字节。
    assert patch_docx(patched, []) == patched


def test_page_break_before_off_removes_direct_setting_including_explicit_val():
    source = make_doc([f'<w:pageBreakBefore xmlns:w="{W}" w:val="1"/>'])
    assert Document(BytesIO(source)).paragraphs[1].paragraph_format.page_break_before is True
    patched = patch_docx(source, [page_break_op(source, False)])
    assert Document(BytesIO(patched)).paragraphs[1].paragraph_format.page_break_before is None
    assert "pageBreakBefore" not in ppr_children(patched)


def test_insert_paragraph_can_carry_the_split_page_break():
    source = make_doc()
    anchor = block(source, 1)
    patched = patch_docx(source, [{
        "kind": "insertParagraph", "blockId": anchor["blockId"], "expectedObjectSha256": anchor["expectedObjectSha256"],
        "position": "after", "text": "after break", "pageBreakBefore": True,
    }])
    paragraphs = Document(BytesIO(patched)).paragraphs
    assert [p.text for p in paragraphs] == ["first", "target keep", "after break", "untouched"]
    assert paragraphs[2].paragraph_format.page_break_before is True
    assert paragraphs[1].paragraph_format.page_break_before is None


@pytest.mark.parametrize("mutation", [
    {"value": "yes"},
    {"extra": 1},
])
def test_page_break_rejects_invalid_operations(mutation):
    source = make_doc()
    operation = {**page_break_op(source, True), **mutation}
    with pytest.raises(ValueError):
        patch_docx(source, [operation])


def test_page_break_rejects_insert_paragraph_false_flag_and_same_block_mixing():
    source = make_doc()
    anchor = block(source, 1)
    with pytest.raises(ValueError):
        patch_docx(source, [{"kind": "insertParagraph", "blockId": anchor["blockId"], "expectedObjectSha256": anchor["expectedObjectSha256"],
                             "position": "after", "text": "x", "pageBreakBefore": False}])
    with pytest.raises(ValueError, match="paragraph_page_break_batch_conflict"):
        patch_docx(source, [page_break_op(source, True), {"kind": "replaceParagraph", "blockId": anchor["blockId"],
                                                           "expectedObjectSha256": anchor["expectedObjectSha256"], "text": "changed"}])


def test_page_break_rejects_unsupported_source_markup_without_rewriting():
    source = make_doc([f'<w:pageBreakBefore xmlns:w="{W}" w:val="1" w:rsid="00AB"/>'])
    with pytest.raises(ValueError, match="paragraph_page_break_unsupported"):
        patch_docx(source, [page_break_op(source, False)])
