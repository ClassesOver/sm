from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_doc(pbdr_xml: str | list[str] | None = None):
    doc = Document()
    p = doc.add_paragraph("target")
    r = p.add_run(" keep")
    r.bold = True
    p._p.get_or_add_pPr().append(OxmlKeepNext())
    for xml in [pbdr_xml] if isinstance(pbdr_xml, str) else (pbdr_xml or []):
        p._p.get_or_add_pPr().append(etree.fromstring(xml))
    doc.add_paragraph("untouched")
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def OxmlKeepNext():
    el = etree.SubElement(etree.Element(f"{{{W}}}pPr"), f"{{{W}}}keepNext")
    return el


def op(data, borders):
    block = inspect_docx(data)["blocks"][0]
    return {
        "kind": "setParagraphBorders",
        "blockId": block["blockId"],
        "expectedObjectSha256": block["expectedObjectSha256"],
        "borders": borders,
    }


def single(side, color=None, sz_pt=None, space_pt=None, val="single"):
    line = {"side": side, "val": val}
    if color is not None:
        line["color"] = color
    if sz_pt is not None:
        line["szPt"] = sz_pt
    if space_pt is not None:
        line["spacePt"] = space_pt
    return line


def pbdr_of(data):
    p = Document(BytesIO(data)).paragraphs[0]
    pPr = p._p.find(qn("w:pPr"))
    el = None if pPr is None else pPr.find(qn("w:pBdr"))
    if el is None:
        return None
    return {
        child.tag.split("}")[1]: {
            name.split("}")[1]: value for name, value in child.attrib.items()
        }
        for child in el
    }


def ppr_child_names(data):
    pPr = Document(BytesIO(data)).paragraphs[0]._p.find(qn("w:pPr"))
    return [child.tag.split("}")[1] for child in pPr]


def test_borders_insert_ordered_pbdr_and_preserve_direct_format_and_other_parts():
    data = make_doc()
    patched = patch_docx(data, [op(data, [single("bottom", color="edf5fc", sz_pt=1, space_pt=2)])])
    # 源 generate.ts pBdr 子序与笔画：val=single、sz 八分之一点、space 0-31、color auto。
    assert pbdr_of(patched) == {"bottom": {"val": "single", "sz": "8", "space": "2", "color": "EDF5FC"}}
    names = ppr_child_names(patched)
    assert names.index("keepNext") < names.index("pBdr")
    doc = Document(BytesIO(patched))
    assert doc.paragraphs[0].runs[1].bold is True
    assert doc.paragraphs[1].text == "untouched"
    assert pbdr_of(patched) is not None
    # 非目标段落不得出现 pBdr。
    second = Document(BytesIO(patched)).paragraphs[1]._p.find(qn("w:pPr"))
    assert second is None or second.find(qn("w:pBdr")) is None
    before, after = ZipFile(BytesIO(data)), ZipFile(BytesIO(patched))
    changed = {n for n in before.namelist() if before.read(n) != after.read(n)}
    # 边框-only 补丁沿用底纹/样式补丁的元数据保留规则。
    assert changed == {"word/document.xml"}


def test_borders_box_writes_source_side_order_and_defaults():
    data = make_doc()
    patched = patch_docx(
        data,
        [op(data, [single("right"), single("top"), single("bottom"), single("left")])],
    )
    # 源 generate.ts：pBdr 内部 schema 序 top, left, bottom, right；缺省 sz=4(0.5pt)、space=0、color=auto。
    assert list(pbdr_of(patched)) == ["top", "left", "bottom", "right"]
    assert pbdr_of(patched)["top"] == {"val": "single", "sz": "4", "space": "0", "color": "auto"}


def test_borders_replace_existing_single_pbdr_and_remove_it():
    data = make_doc(f'<w:pBdr xmlns:w="{W}"><w:top w:val="single" w:sz="8" w:space="4" w:color="FF0000"/></w:pBdr>')
    patched = patch_docx(data, [op(data, [single("bottom", color="00B050")])])
    assert pbdr_of(patched) == {"bottom": {"val": "single", "sz": "4", "space": "0", "color": "00B050"}}
    removed = patch_docx(patched, [op(patched, None)])
    assert pbdr_of(removed) is None
    names = ppr_child_names(removed)
    assert "pBdr" not in names and names.index("keepNext") >= 0
    # 既有直接格式与其他部件原样保留。
    assert Document(BytesIO(removed)).paragraphs[0].runs[1].bold is True
    with ZipFile(BytesIO(data)) as a, ZipFile(BytesIO(removed)) as b:
        assert {n for n in a.namelist() if a.read(n) != b.read(n)} == {"word/document.xml"}


def test_borders_keep_existing_ppr_children_and_whitespace_shell():
    data = make_doc()
    with ZipFile(BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode()
        xml = xml.replace("<w:keepNext/>", '<w:keepNext/>\n  ', 1)
        out = BytesIO()
        with ZipFile(out, "w") as changed:
            for entry in archive.infolist():
                changed.writestr(
                    entry,
                    xml.encode() if entry.filename == "word/document.xml" else archive.read(entry.filename),
                )
    data = out.getvalue()
    result = patch_docx(data, [op(data, [single("top")])])
    # 与底纹补丁同规：子元素按 PPR_CHILD_ORDER 有序重排，元素间纯空白不保留。
    assert ppr_child_names(result) == ["keepNext", "pBdr"]
    before = Document(BytesIO(data)).paragraphs[0]._p.find(qn("w:pPr"))
    after = Document(BytesIO(result)).paragraphs[0]._p.find(qn("w:pPr"))
    assert etree.tostring(before.find(qn("w:keepNext"))) == etree.tostring(after.find(qn("w:keepNext")))
    assert pbdr_of(result) == {"top": {"val": "single", "sz": "4", "space": "0", "color": "auto"}}


def test_borders_reject_unsupported_source_pbdr():
    for bad in (
        f'<w:pBdr xmlns:w="{W}"><w:top w:val="nil"/></w:pBdr>',
        f'<w:pBdr xmlns:w="{W}"><w:top w:val="none"/></w:pBdr>',
        f'<w:pBdr xmlns:w="{W}"><w:top w:val="double" w:sz="4" w:space="0" w:color="auto"/></w:pBdr>',
        f'<w:pBdr xmlns:w="{W}"><w:top w:val="single" w:space="0" w:color="auto" w:themeColor="accent1"/></w:pBdr>',
        f'<w:pBdr xmlns:w="{W}"><w:between w:val="single" w:sz="4" w:space="0" w:color="auto"/></w:pBdr>',
        f'<w:pBdr xmlns:w="{W}"><w:bar w:val="single" w:sz="4" w:space="0" w:color="auto"/></w:pBdr>',
        [f'<w:pBdr xmlns:w="{W}"><w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/></w:pBdr>',
         f'<w:pBdr xmlns:w="{W}"><w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/></w:pBdr>'],
        f'<w:pBdr xmlns:w="{W}"><w:top w:val="single" w:sz="4" w:space="0"><w:evil/></w:top></w:pBdr>',
    ):
        data = make_doc(bad)
        with pytest.raises(ValueError, match="paragraph_borders"):
            patch_docx(data, [op(data, [single("bottom")])])


def test_borders_reject_bad_values_and_batch_conflicts():
    data = make_doc()
    base = op(data, [single("bottom")])
    for borders in (
        [single("between")],
        [single("bottom", val="double")],
        [single("bottom", sz_pt=0)],
        [single("bottom", sz_pt=0.3)],
        [single("bottom", sz_pt=13)],
        [single("bottom", space_pt=32)],
        [single("bottom", color="#edf5fc")],
        [single("bottom"), single("bottom")],
        [{"side": "bottom", "val": "single", "themeColor": "accent1"}],
        [{"side": "bottom", "val": "single", "raw": "<x/>"}],
        "bottom",
        {},
    ):
        with pytest.raises(ValueError):
            patch_docx(data, [op(data, borders)])
    for kwargs in ({"extra": 1},):
        with pytest.raises(ValueError):
            patch_docx(data, [{**base, **kwargs}])
    with pytest.raises(ValueError, match="paragraph_borders_batch_conflict"):
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
    with pytest.raises(ValueError):
        patch_docx(data, [op(data, [single("bottom")]) | {"expectedObjectSha256": "foreign"}])
