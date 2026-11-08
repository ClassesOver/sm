"""insertTable：固定源 insertTableAt + editor/new-table.ts 外观的新表格写回与独立回读。"""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def make_doc() -> bytes:
    doc = Document()
    doc.add_paragraph("first")
    doc.add_paragraph("second")
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def insert_op(data: bytes, index: int, position: str, rows: int, cols: int) -> dict:
    block = inspect_docx(data)["blocks"][index]
    return {"kind": "insertTable", "blockId": block["blockId"], "expectedObjectSha256": block["expectedObjectSha256"],
            "position": position, "rows": rows, "cols": cols}


def body_kinds(data: bytes) -> list[str]:
    body = Document(BytesIO(data)).element.body
    return [child.tag.split("}")[1] for child in body if child.tag.split("}")[1] in {"p", "tbl"}]


def test_insert_table_writes_word_style_grid_between_paragraphs():
    source = make_doc()
    patched = patch_docx(source, [insert_op(source, 1, "before", 2, 3)])
    assert body_kinds(patched) == ["p", "tbl", "p"]
    document = Document(BytesIO(patched))
    table = document.tables[0]
    assert (len(table.rows), len(table.columns)) == (2, 3)
    assert all(cell.text == "" for row in table.rows for cell in row.cells)
    tbl_pr = table._tbl.tblPr
    assert tbl_pr.find(qn("w:tblW")).get(qn("w:type")) == "pct"
    borders = tbl_pr.find(qn("w:tblBorders"))
    assert [b.get(qn("w:val")) for b in borders] == ["single"] * 6
    assert all(b.get(qn("w:sz")) == "4" for b in borders)
    first_cell = table.rows[0].cells[0]
    assert first_cell._tc.tcPr.find(qn("w:vAlign")).get(qn("w:val")) == "center"
    spacing = first_cell.paragraphs[0]._p.pPr.find(qn("w:spacing"))
    assert (spacing.get(qn("w:after")), spacing.get(qn("w:line"))) == ("0", "240")
    assert [p.text for p in document.paragraphs] == ["first", "second"]
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(patched)) as after:
        assert after.read("word/styles.xml") == before.read("word/styles.xml")
    assert patch_docx(patched, []) == patched


def test_insert_table_after_anchor_and_with_following_paragraph_in_one_batch():
    source = make_doc()
    anchor = inspect_docx(source)["blocks"][1]
    patched = patch_docx(source, [
        insert_op(source, 1, "after", 1, 2),
        {"kind": "insertParagraph", "blockId": anchor["blockId"], "expectedObjectSha256": anchor["expectedObjectSha256"],
         "position": "after", "text": ""},
    ])
    assert body_kinds(patched) == ["p", "p", "tbl", "p"]
    # 新表格成为可再检视的来源表格（后续 replaceCellText 路径可用）。
    blocks = inspect_docx(patched)["blocks"]
    assert [block["type"] for block in blocks][:3] == ["paragraph", "paragraph", "table"]


@pytest.mark.parametrize("rows,cols", [(0, 2), (2, 0), (101, 1), (1, 31), (40, 30), (1.5, 2), ("2", 2)])
def test_insert_table_rejects_out_of_budget_sizes(rows, cols):
    source = make_doc()
    with pytest.raises(ValueError):
        patch_docx(source, [insert_op(source, 0, "before", rows, cols)])


def test_insert_table_rejects_unknown_fields_and_positions():
    source = make_doc()
    with pytest.raises(ValueError):
        patch_docx(source, [{**insert_op(source, 0, "before", 2, 2), "style": "Grid"}])
    with pytest.raises(ValueError):
        patch_docx(source, [insert_op(source, 0, "inside", 2, 2)])
