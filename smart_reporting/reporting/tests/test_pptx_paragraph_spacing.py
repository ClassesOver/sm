"""Paragraph spacing uses the pinned engine; verify output with independent readers."""

import json
import subprocess
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from lxml import etree
from pptx import Presentation
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from smart_reporting.report_editor.native_office import inspect_office, patch_office

ENGINE = Path(__file__).parents[1] / "slides_engine"
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def source_bytes():
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(2))
    for index, paragraph in enumerate(
        [box.text_frame.paragraphs[0], box.text_frame.add_paragraph()]
    ):
        paragraph.text = ["First bullet", "Second bullet"][index]
        paragraph.line_spacing = Pt(18 + index)
        paragraph.space_before = Pt(3 + index)
        paragraph.space_after = Pt(5 + index)
        paragraph.runs[0].font.name = "Arial"
        paragraph.runs[0].font.size = Pt(21)
        paragraph.runs[0].font.bold = True
        ppr = paragraph._p.get_or_add_pPr()
        ppr.set("rtl", "1")
        bullet = OxmlElement("a:buChar")
        bullet.set("char", "•")
        ppr.append(bullet)
    # Alternate spacing units must remain visible and survive unrelated patches.
    ppr = box.text_frame.paragraphs[1]._p.get_or_add_pPr()
    for name, value in [("spcBef", "120000"), ("spcAft", "80000")]:
        node = ppr.find("a:" + name, NS)
        node.remove(node[0])
        child = OxmlElement("a:spcPct")
        child.set("val", value)
        node.append(child)
    slide.shapes.add_textbox(Inches(5), Inches(1), Inches(2), Inches(1)).text = "Untouched object"
    deck.slides.add_slide(deck.slide_layouts[6]).shapes.add_textbox(
        Inches(1), Inches(1), Inches(2), Inches(1)
    ).text = "Untouched slide"
    stream = BytesIO()
    deck.save(stream)
    return stream.getvalue()


def xml(content, path="ppt/slides/slide1.xml"):
    with ZipFile(BytesIO(content)) as archive:
        return etree.fromstring(archive.read(path))


def target(content):
    return inspect_office("pptx", content)["slides"][0]["elements"][0]


def apply(content, **fields):
    return patch_office(
        "pptx",
        content,
        [
            {
                "kind": "editSlides",
                "paragraphFormatting": [
                    {"slideIndex": 0, "elementId": target(content)["id"], **fields},
                ],
            }
        ],
    )


def assert_preserved(source, edited, changed):
    before, after = xml(source), xml(edited)
    assert etree.tostring(before.xpath("//p:sp", namespaces=NS)[1]) == etree.tostring(
        after.xpath("//p:sp", namespaces=NS)[1]
    )
    for tree in (before, after):
        # The pinned engine stamps a creationId on the edited shape. Compare
        # all remaining XML, including bullet/RTL/run/font properties exactly.
        for node in tree.xpath("//p:sp[1]/p:nvSpPr/p:cNvPr/a:extLst", namespaces=NS):
            assert len(node) == 1 and node[0].get("uri") == "{FF2B5EF4-FFF2-40B4-BE49-F238E27FC236}"
            node.getparent().remove(node)
        for ppr in tree.xpath("//p:sp[1]//a:pPr", namespaces=NS):
            for name in changed:
                if name == "algn":
                    ppr.attrib.pop(name, None)
                else:
                    for node in ppr.findall("a:" + name, NS):
                        ppr.remove(node)
    assert etree.tostring(before) == etree.tostring(after)
    with ZipFile(BytesIO(source)) as original, ZipFile(BytesIO(edited)) as output:
        for name in original.namelist():
            if name != "ppt/slides/slide1.xml":
                assert original.read(name) == output.read(name), name


def test_inspect_exposes_actual_units_and_unset_values_without_defaults():
    source = source_bytes()
    styles = target(source)["paragraphFormatting"]
    assert styles[0] == {
        "align": "left",
        "lineSpacingPct": None,
        "lineSpacingPt": 18,
        "spaceBeforePt": 3,
        "spaceAfterPt": 5,
        "spaceBeforePct": None,
        "spaceAfterPct": None,
    }
    assert styles[1]["lineSpacingPt"] == 19
    assert styles[1]["spaceBeforePt"] is None and styles[1]["spaceBeforePct"] == 120
    assert styles[1]["spaceAfterPt"] is None and styles[1]["spaceAfterPct"] == 80
    untouched = inspect_office("pptx", source)["slides"][0]["elements"][1]["paragraphFormatting"][0]
    assert all(untouched[key] is None for key in untouched if key != "align")


def test_alignment_only_preserves_exact_lines_and_percentage_paragraph_spacing():
    source = source_bytes()
    edited = apply(source, align="right")
    expected = [{**style, "align": "right"} for style in target(source)["paragraphFormatting"]]
    assert target(edited)["paragraphFormatting"] == expected
    assert_preserved(source, edited, ["algn"])


@pytest.mark.parametrize("spacing", [100, 115, 150, 200, 250, 300])
def test_all_source_line_spacing_options_roundtrip_and_preserve_other_formatting(spacing):
    source = source_bytes()
    snapshot = bytes(source)
    edited = apply(source, lineSpacingPct=spacing)
    paragraphs = Presentation(BytesIO(edited)).slides[0].shapes[0].text_frame.paragraphs
    assert [p.line_spacing for p in paragraphs] == [spacing / 100] * 2
    for paragraph in target(edited)["paragraphFormatting"]:
        assert paragraph["lineSpacingPct"] == spacing and paragraph["lineSpacingPt"] is None
    assert_preserved(source, edited, ["lnSpc"])
    assert source == snapshot
    assert Presentation(BytesIO(source)).slides[0].shapes[0].text_frame.paragraphs[
        0
    ].line_spacing == Pt(18)


def test_combined_align_and_point_spacing_roundtrip_engine_precision_and_bounds():
    source = source_bytes()
    operation = {
        "kind": "editSlides",
        "paragraphFormatting": [
            {
                "slideIndex": 0,
                "elementId": target(source)["id"],
                "align": "center",
                "lineSpacingPct": 150,
                "spaceBeforePt": 12.3456,
                "spaceAfterPt": 500,
            }
        ],
    }
    snapshot = deepcopy(operation)
    edited = patch_office("pptx", source, [operation])
    assert operation == snapshot
    for paragraph in Presentation(BytesIO(edited)).slides[0].shapes[0].text_frame.paragraphs:
        assert paragraph.space_before.pt == pytest.approx(12.35)
        assert paragraph.space_after.pt == 500
        assert paragraph.line_spacing == 1.5
        assert paragraph.runs[0].font.bold is True
    actual = target(edited)
    assert actual["paragraphAlignments"] == ["center", "center"]
    assert (
        actual["paragraphFormatting"]
        == [
            dict(
                align="center",
                lineSpacingPct=150,
                lineSpacingPt=None,
                spaceBeforePt=12.35,
                spaceAfterPt=500,
                spaceBeforePct=None,
                spaceAfterPct=None,
            )
        ]
        * 2
    )
    assert_preserved(source, edited, ["lnSpc", "spcBef", "spcAft", "algn"])
    zero = apply(source, spaceBeforePt=0, spaceAfterPt=0)
    assert [
        p.space_before.pt
        for p in Presentation(BytesIO(zero)).slides[0].shapes[0].text_frame.paragraphs
    ] == [0, 0]
    assert_preserved(source, zero, ["spcBef", "spcAft"])


INVALID = [
    {},
    {"unknown": 1},
    {"spaceBeforePt": 1, "unknown": 1},
    {"align": []},
    {"align": "distributed"},
    {"lineSpacingPct": 125},
    {"lineSpacingPct": True},
    {"lineSpacingPct": None},
    {"spaceBeforePt": True},
    {"spaceBeforePt": -0.01},
    {"spaceAfterPt": 500.01},
    {"spaceAfterPt": "12"},
    {"spaceAfterPt": None},
    {"lineSpacingPt": 18},
    {"spaceBeforePct": 100},
    {"spaceAfterPt": float("nan")},
    {"spaceAfterPt": float("inf")},
]


@pytest.mark.parametrize("fields", INVALID)
def test_invalid_native_spacing_never_calls_engine(monkeypatch, fields):
    from smart_reporting.report_editor.pptx_engine import PptxEngine

    engine = Mock(side_effect=AssertionError("invalid input reached engine"))
    monkeypatch.setattr(PptxEngine, "_run_engine", engine)
    with pytest.raises(ValueError, match="native_office_operations_invalid"):
        patch_office(
            "pptx",
            b"source",
            [
                {
                    "kind": "editSlides",
                    "paragraphFormatting": [{"slideIndex": 0, "elementId": "x", **fields}],
                }
            ],
        )
    engine.assert_not_called()


def test_direct_bridge_rejects_invalid_schema_and_missing_targets_without_output(tmp_path):
    original = source_bytes()
    source = tmp_path / "source.pptx"
    source.write_bytes(original)
    output = tmp_path / "output.pptx"
    for fields in [
        *INVALID,
        {"spaceBeforePt": 1, "slideIndex": True},
        {"spaceBeforePt": 1, "elementId": "missing"},
        {"spaceBeforePt": 1, "slideIndex": 99},
    ]:
        request = {
            "action": "edit",
            "input": str(source),
            "output": str(output),
            "paragraphFormatting": [{"slideIndex": 0, "elementId": "x", **fields}],
        }
        path = tmp_path / "request.json"
        path.write_text(json.dumps(request))
        result = subprocess.run(
            ["node", "dist/edit-pptx.mjs", str(path)], cwd=ENGINE, capture_output=True, timeout=30
        )
        assert result.returncode != 0, fields
        assert not output.exists(), fields
    with pytest.raises(ValueError):
        patch_office(
            "pptx",
            source.read_bytes(),
            [
                {
                    "kind": "editSlides",
                    "paragraphFormatting": [
                        {"slideIndex": 0, "elementId": "missing", "spaceBeforePt": 1}
                    ],
                }
            ],
        )
    assert source.read_bytes() == original
