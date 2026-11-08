from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_doc(shd_xml: str | None = None):
    doc = Document()
    p = doc.add_paragraph("target")
    r = p.add_run(" keep")
    r.bold = True
    p._p.get_or_add_pPr().append(OxmlKeepNext())
    if shd_xml:
        p._p.get_or_add_pPr().append(etree.fromstring(shd_xml))
    doc.add_paragraph("untouched")
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def OxmlKeepNext():
    el = etree.SubElement(etree.Element(f"{{{W}}}pPr"), f"{{{W}}}keepNext")
    return el


def op(data, fill=None, clear=False):
    block = inspect_docx(data)["blocks"][0]
    return {
        "kind": "setParagraphShading",
        "blockId": block["blockId"],
        "expectedObjectSha256": block["expectedObjectSha256"],
        "fill": fill,
        "clear": clear,
    }


def shd_of(data):
    p = Document(BytesIO(data)).paragraphs[0]
    pPr = p._p.find(qn("w:pPr"))
    el = None if pPr is None else pPr.find(qn("w:shd"))
    return (
        None if el is None else (el.get(qn("w:val")), el.get(qn("w:color")), el.get(qn("w:fill")))
    )


def ppr_child_names(data):
    pPr = Document(BytesIO(data)).paragraphs[0]._p.find(qn("w:pPr"))
    return [child.tag.split("}")[1] for child in pPr]


def test_shading_inserts_ordered_shd_and_preserves_direct_format_and_other_parts():
    data = make_doc()
    patched = patch_docx(data, [op(data, fill="edf5fc")])
    assert shd_of(patched) == ("clear", "auto", "edf5fc")
    names = ppr_child_names(patched)
    assert names.index("keepNext") < names.index("shd")
    doc = Document(BytesIO(patched))
    assert doc.paragraphs[0].runs[1].bold is True
    assert doc.paragraphs[1].text == "untouched"
    before, after = ZipFile(BytesIO(data)), ZipFile(BytesIO(patched))
    changed = {n for n in before.namelist() if before.read(n) != after.read(n)}
    # 底纹-only 补丁沿用样式补丁的元数据保留规则。
    assert changed == {"word/document.xml"}


def test_shading_replaces_existing_simple_fill_and_removes_it():
    data = make_doc(f'<w:shd xmlns:w="{W}" w:val="clear" w:color="auto" w:fill="fff2cc"/>')
    patched = patch_docx(data, [op(data, fill="edf5fc")])
    assert shd_of(patched) == ("clear", "auto", "edf5fc")
    removed = patch_docx(patched, [op(patched, fill=None, clear=False)])
    assert shd_of(removed) is None
    explicit_auto = patch_docx(data, [op(data, fill=None, clear=True)])
    assert shd_of(explicit_auto) == ("clear", "auto", "auto")


def test_shading_rejects_pattern_shd_bad_values_and_batch_conflicts():
    for bad in (
        f'<w:shd xmlns:w="{W}" w:val="pct15" w:fill="FFFFFF"/>',
        f'<w:shd xmlns:w="{W}" w:val="solid" w:color="FF0000" w:fill="FFFFFF"/>',
    ):
        data = make_doc(bad)
        with pytest.raises(ValueError):
            patch_docx(data, [op(data, fill="edf5fc")])
    data = make_doc()
    base = op(data, fill="edf5fc")
    for kwargs in ({"fill": "#edf5fc"}, {"fill": "edf5f"}, {"clear": "yes"}, {"fill": 7}):
        with pytest.raises(ValueError):
            patch_docx(data, [{**base, **kwargs}])
    with pytest.raises(ValueError):
        patch_docx(
            data,
            [
                base,
                {
                    "kind": "setParagraphAlignment",
                    "blockId": base["blockId"],
                    "expectedObjectSha256": base["expectedObjectSha256"],
                    "alignment": "center",
                },
            ],
        )
