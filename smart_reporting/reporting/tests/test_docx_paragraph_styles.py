from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def make_doc():
    doc = Document()
    style = doc.styles.add_style("NativeCustom", WD_STYLE_TYPE.PARAGRAPH)
    style.font.size = Pt(14)
    p = doc.add_paragraph()
    p.paragraph_format.alignment = 1
    p._p.get_or_add_pPr().append(OxmlElement("w:keepNext"))
    r = p.add_run("target")
    r.bold = True
    r.font.color.rgb = RGBColor(0x12, 0x34, 0x56)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(
        qn("r:id"), doc.part.relate_to("https://example.test", RT.HYPERLINK, is_external=True)
    )
    run, text = OxmlElement("w:r"), OxmlElement("w:t")
    text.text = " linked"
    run.append(text)
    hyperlink.append(run)
    p._p.append(hyperlink)
    bookmark = OxmlElement("w:bookmarkStart")
    bookmark.set(qn("w:id"), "9")
    bookmark.set(qn("w:name"), "KeepMe")
    p._p.append(bookmark)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), "9")
    p._p.append(end)
    doc.add_paragraph("untouched")
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def op(data, style="NativeCustom", **extra):
    block = inspect_docx(data)["blocks"][0]
    return {
        "kind": "setParagraphStyle",
        "blockId": block["blockId"],
        "expectedObjectSha256": block["expectedObjectSha256"],
        "styleId": style,
        **extra,
    }


def test_style_patch_changes_only_pstyle_and_preserves_runs_links_properties_and_other_parts():
    source = make_doc()
    changed = patch_docx(source, [op(source)])
    before, after = (
        Document(BytesIO(source)).paragraphs[0]._p,
        Document(BytesIO(changed)).paragraphs[0]._p,
    )
    assert before.find(qn("w:pPr")).find(qn("w:jc")).get(qn("w:val")) == "center"
    assert after.find(qn("w:pPr")).find(qn("w:pStyle")).get(qn("w:val")) == "NativeCustom"
    for name in ("w:jc", "w:keepNext"):
        assert etree.tostring(before.find(qn("w:pPr")).find(qn(name))) == etree.tostring(
            after.find(qn("w:pPr")).find(qn(name))
        )
    assert [t.text for t in after.findall(".//" + qn("w:t"))] == ["target", " linked"]
    assert Document(BytesIO(changed)).paragraphs[0].runs[0].bold is True
    assert Document(BytesIO(changed)).paragraphs[0].runs[0].font.color.rgb == RGBColor(
        0x12, 0x34, 0x56
    )
    with ZipFile(BytesIO(source)) as a, ZipFile(BytesIO(changed)) as b:
        names = {n for n in a.namelist() if not n.endswith("/")}
        assert names == {n for n in b.namelist() if not n.endswith("/")}
        assert all(a.read(n) == b.read(n) for n in names - {"word/document.xml"})
    assert etree.tostring(before.find(qn("w:bookmarkStart"))) == etree.tostring(
        after.find(qn("w:bookmarkStart"))
    )
    assert etree.tostring(before.find(qn("w:bookmarkEnd"))) == etree.tostring(
        after.find(qn("w:bookmarkEnd"))
    )
    assert (
        Document(BytesIO(changed))
        .part.rels[after.find(qn("w:hyperlink")).get(qn("r:id"))]
        .target_ref
        == "https://example.test"
    )


@pytest.mark.parametrize("kind", ["character", "table"])
def test_rejects_non_paragraph_styles(kind):
    from docx.enum.style import WD_STYLE_TYPE

    data = make_doc()
    doc = Document(BytesIO(data))
    doc.styles.add_style(
        "WrongType", WD_STYLE_TYPE.CHARACTER if kind == "character" else WD_STYLE_TYPE.TABLE
    )
    out = BytesIO()
    doc.save(out)
    data = out.getvalue()
    with pytest.raises(ValueError):
        patch_docx(data, [op(data, "WrongType")])


def test_rejects_missing_style_foreign_hash_and_unknown_fields():
    data = make_doc()
    with pytest.raises(ValueError):
        patch_docx(data, [op(data, "Absent")])
    with pytest.raises(ValueError):
        patch_docx(data, [op(data) | {"expectedObjectSha256": "foreign"}])
    with pytest.raises(ValueError):
        patch_docx(data, [op(data) | {"rawPPr": "<evil/>"}])


def test_rejects_based_on_numbering_heading_missing_parent_and_cycles():
    data = make_doc()
    doc = Document(BytesIO(data))
    numbered = doc.styles.add_style("NumberedChild", WD_STYLE_TYPE.PARAGRAPH)
    numbered.base_style = doc.styles["List Bullet"]
    heading = doc.styles.add_style("InheritedHeading", WD_STYLE_TYPE.PARAGRAPH)
    heading.base_style = doc.styles["Heading 1"]
    missing = doc.styles.add_style("MissingParent", WD_STYLE_TYPE.PARAGRAPH)
    missing._element.append(OxmlElement("w:basedOn"))
    missing._element[-1].set(qn("w:val"), "NoSuchStyle")
    cycle = doc.styles.add_style("Cycle", WD_STYLE_TYPE.PARAGRAPH)
    cycle.base_style = cycle
    out = BytesIO()
    doc.save(out)
    data = out.getvalue()
    for style in ("NumberedChild", "InheritedHeading", "MissingParent", "Cycle"):
        with pytest.raises(ValueError):
            patch_docx(data, [op(data, style)])


@pytest.mark.parametrize(
    "shell",
    [
        "<w:pPr/>",
        '<w:pPr w:rsidR="12345678"/>',
        '<w:pPr>  <w:keepNext/>\n<w:pStyle w:val="Normal"/>  </w:pPr>',
    ],
)
def test_self_closing_and_existing_ppr_keep_original_attributes_and_whitespace(shell):
    data = make_doc()
    with ZipFile(BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode()
        import re

        xml = re.sub(r"<w:pPr>.*?</w:pPr>", shell, xml, count=1, flags=re.S)
        out = BytesIO()
        with ZipFile(out, "w") as changed:
            for entry in archive.infolist():
                changed.writestr(
                    entry,
                    xml.encode()
                    if entry.filename == "word/document.xml"
                    else archive.read(entry.filename),
                )
    data = out.getvalue()
    result = patch_docx(data, [op(data)])
    with ZipFile(BytesIO(result)) as archive:
        saved = archive.read("word/document.xml").decode()
    expected = shell.replace('<w:pStyle w:val="Normal"/>', '<w:pStyle w:val="NativeCustom"/>')
    if "w:pStyle" not in shell:
        expected = shell[:-2] + '><w:pStyle w:val="NativeCustom"/></w:pPr>'
    assert expected in saved
    assert Document(BytesIO(result)).paragraphs[0].style.style_id == "NativeCustom"


def test_document_protection_disables_paragraph_style_and_bridge_rejects_write():
    data = make_doc()
    doc = Document(BytesIO(data))
    protection = OxmlElement("w:documentProtection")
    protection.set(qn("w:edit"), "readOnly")
    protection.set(qn("w:enforcement"), "1")
    doc.settings.element.append(protection)
    out = BytesIO()
    doc.save(out)
    data = out.getvalue()
    assert inspect_docx(data)["blocks"][0]["paragraphStyleEditable"] is False
    with pytest.raises(ValueError):
        patch_docx(data, [op(data)])


def test_rejects_mixed_same_paragraph_operations_without_dropping_other_edit():
    doc = Document()
    doc.styles.add_style("NativeCustom", WD_STYLE_TYPE.PARAGRAPH)
    doc.add_paragraph("ordinary")
    out = BytesIO()
    doc.save(out)
    data = out.getvalue()
    operation = op(data)
    with pytest.raises(ValueError, match="paragraph_style_batch_conflict"):
        patch_docx(
            data,
            [
                operation,
                {key: value for key, value in operation.items() if key != "styleId"}
                | {"kind": "setParagraphAlignment", "alignment": "right"},
            ],
        )
