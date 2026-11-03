from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.reporting.delivery.pptx import build_editable_pptx


@pytest.fixture(scope="module")
def generated_pptx(tmp_path_factory):
    directory = tmp_path_factory.mktemp("slides-editing")
    chart = directory / "chart.png"
    Image.new("RGB", (64, 32), "#147D75").save(chart)
    destination = directory / "source.pptx"
    build_editable_pptx(
        output_path=destination,
        title="运营分析",
        period="2025年",
        theme="executive",
        slides=({"title": "收入变化", "bullets": ["收入增长 5.2%"],
                 "evidenceIds": ["analysis_001"], "chartPath": str(chart)},),
    )
    return destination


def test_generated_pptx_edit_reopen_preserves_media_notes_and_source(generated_pptx):
    from smart_reporting.reporting.delivery.slides_editing import edit_pptx, inspect_pptx

    original = generated_pptx.read_bytes()
    inspected = inspect_pptx(original)
    assert inspected["width"] == 1280
    assert inspected["height"] == pytest.approx(720)
    page = inspected["slides"][1]
    title = next(element for element in page["elements"] if element.get("text") == "收入变化")
    image = next(element for element in page["elements"] if element["kind"] == "image")
    assert image["imageDataUrl"].startswith("data:image/png;base64,")

    edited, validation = edit_pptx(original, [
        {"op": "update", "slide": 1, "id": title["id"], "text": "收入复核", "x": 120,
         "width": 980, "fontSize": 28, "fontFamily": "Arial", "color": "#112233",
         "bold": False, "lineSpacing": 1.5, "rotation": 3},
        {"op": "update", "slide": 1, "id": image["id"], "x": 710, "height": 300},
        {"op": "background", "slide": 1, "color": "#FFFFFF"},
        {"op": "addText", "slide": 1, "text": "已复核", "x": 100, "y": 580,
         "width": 300, "height": 40, "fontSize": 18, "lineSpacing": 1.25},
    ])

    reopened = inspect_pptx(edited)["slides"][1]
    changed = next(element for element in reopened["elements"] if element.get("text") == "收入复核")
    assert changed["x"] == pytest.approx(120)
    assert changed["width"] == pytest.approx(980)
    assert changed["fontSize"] == 28
    assert changed["fontFamily"] == "Arial"
    assert changed["color"].upper() == "#112233"
    assert changed["bold"] is False
    assert changed["lineSpacing"] == 1.5
    assert changed["rotation"] == 3
    assert reopened["background"] == "#FFFFFF"
    assert any(element.get("text") == "已复核" for element in reopened["elements"])
    moved_image = next(element for element in reopened["elements"] if element["kind"] == "image")
    assert moved_image["x"] == pytest.approx(710)
    assert moved_image["height"] == pytest.approx(300)
    assert isinstance(validation["issues"], list)
    assert validation["ok"] is (not validation["issues"])
    presentation = Presentation(BytesIO(edited))
    assert "analysis_001" in presentation.slides[1].notes_slide.notes_text_frame.text
    assert generated_pptx.read_bytes() == original
    with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(edited)) as after:
        for name in before.namelist():
            if name.startswith(("ppt/media/", "ppt/notesSlides/")):
                assert after.read(name) == before.read(name)

    added = next(element for element in reopened["elements"] if element.get("text") == "已复核")
    deleted, _ = edit_pptx(edited, [{"op": "delete", "slide": 1, "id": added["id"]}])
    assert not any(element.get("text") == "已复核" for element in inspect_pptx(deleted)["slides"][1]["elements"])


def test_inspect_uses_real_slide_aspect_ratio_and_keeps_unsupported_table():
    from smart_reporting.reporting.delivery.slides_editing import edit_pptx, inspect_pptx

    presentation = Presentation()
    presentation.slide_width = Inches(10)
    presentation.slide_height = Inches(7.5)
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text = "标题"
    table = slide.shapes.add_table(1, 1, Inches(1), Inches(3), Inches(3), Inches(1)).table
    table.cell(0, 0).text = "保留表格"
    stream = BytesIO()
    presentation.save(stream)
    inspected = inspect_pptx(stream.getvalue())
    assert inspected["height"] == 960
    assert inspected["fontScale"] == pytest.approx(12700 * 1280 / presentation.slide_width)
    protected = next(element for element in inspected["slides"][0]["elements"] if element.get("editable") is False)
    assert protected["kind"] == "shape"
    title = next(element for element in inspected["slides"][0]["elements"] if element.get("text") == "标题")
    edited, _ = edit_pptx(stream.getvalue(), [{"op": "update", "slide": 0, "id": title["id"], "text": "新标题"}])
    restored = Presentation(BytesIO(edited))
    assert next(shape for shape in restored.slides[0].shapes if shape.has_table).table.cell(0, 0).text == "保留表格"
    with pytest.raises(ValueError, match="pptx_element_invalid"):
        edit_pptx(stream.getvalue(), [{"op": "delete", "slide": 0, "id": protected["id"]}])


def test_added_text_has_zero_native_insets(generated_pptx):
    from smart_reporting.reporting.delivery.slides_editing import edit_pptx

    edited, _ = edit_pptx(generated_pptx.read_bytes(), [{
        "op": "addText", "slide": 0, "text": "零内边距文本", "x": 120, "y": 80,
        "width": 400, "height": 80, "fontSize": 24,
    }])

    presentation = Presentation(BytesIO(edited))
    added = next(shape for shape in presentation.slides[0].shapes if shape.has_text_frame and shape.text == "零内边距文本")
    assert added.left == pytest.approx(presentation.slide_width * 120 / 1280)
    assert added.top == pytest.approx(presentation.slide_width * 80 / 1280)
    assert added.text_frame.margin_left == 0
    assert added.text_frame.margin_top == 0
    assert added.text_frame.margin_right == 0
    assert added.text_frame.margin_bottom == 0


def test_line_color_edits_native_stroke_and_survives_reopen(generated_pptx):
    from smart_reporting.reporting.delivery.slides_editing import edit_pptx, inspect_pptx

    original = generated_pptx.read_bytes()
    line = next(element for element in inspect_pptx(original)["slides"][1]["elements"] if element.get("shape") == "line")
    assert line["editable"] is True
    assert line.get("fill") == "#D5DEDF"

    edited, _ = edit_pptx(original, [{"op": "update", "slide": 1, "id": line["id"], "fill": "#127ABC", "x": 110}])

    reopened = next(element for element in inspect_pptx(edited)["slides"][1]["elements"] if element.get("shape") == "line")
    assert reopened["fill"] == "#127ABC"
    assert reopened["x"] == pytest.approx(110)
    presentation = Presentation(BytesIO(edited))
    native_line = next(shape for shape in presentation.slides[1].shapes if shape.shape_type == 9)
    assert str(native_line.line.color.rgb) == "127ABC"
    assert native_line.line.width == 12700


def test_edit_returns_pptx_when_native_audit_raises(generated_pptx, tmp_path, monkeypatch):
    from pathlib import Path

    from smart_reporting.reporting.delivery import slides_editing

    engine = Path(slides_editing.__file__).parents[1] / "slides_engine"
    isolated = tmp_path / "engine"
    (isolated / "bridge").mkdir(parents=True)
    (isolated / "node_modules").symlink_to(engine / "node_modules", target_is_directory=True)
    (isolated / "bridge" / "audit-failure.ts").write_text(
        "export async function auditDeck() { throw new Error('audit unavailable') }", encoding="utf-8",
    )
    bridge = (engine / "bridge" / "edit-pptx.ts").read_text(encoding="utf-8")
    (isolated / "bridge" / "edit-pptx.ts").write_text(
        bridge.replace("../packages/pipelines/src/slides/audit-deck.ts", "./audit-failure.ts"),
        encoding="utf-8",
    )
    (isolated / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    monkeypatch.setenv("AGENT_REPORTING_SLIDES_ENGINE_DIR", str(isolated))

    edited, validation = slides_editing.edit_pptx(generated_pptx.read_bytes(), [])

    assert len(Presentation(BytesIO(edited)).slides) == 2
    assert validation == {"ok": False, "issues": [{
        "code": "pptx_audit_failed", "message": "幻灯片验收未完成，已保留可下载的 PPTX。",
    }]}


def test_edit_process_timeout_is_reported_and_temporary_files_are_removed(generated_pptx, monkeypatch):
    import subprocess
    from pathlib import Path

    from smart_reporting.reporting.delivery import slides_editing

    request_paths = []

    def timeout(command, **kwargs):
        request_paths.append(Path(command[-1]))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(slides_editing.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="pptx_engine_timeout"):
        slides_editing.inspect_pptx(generated_pptx.read_bytes())
    assert request_paths and not request_paths[0].parent.exists()


def test_edit_requires_an_operation_list(generated_pptx):
    from smart_reporting.reporting.delivery.slides_editing import edit_pptx

    with pytest.raises(ValueError, match="pptx_operations_invalid"):
        edit_pptx(generated_pptx.read_bytes(), None)


@pytest.mark.parametrize("operation", [
    {"op": "unknown", "slide": 0},
    {"op": "background", "slide": 100, "color": "#112233"},
    {"op": "background", "slide": -1, "color": "#112233"},
    {"op": "background", "slide": True, "color": "#112233"},
    {"op": "background", "slide": 0, "color": "red"},
    {"op": "background", "slide": 0, "color": "#112233", "extra": 1},
    {"op": "update", "slide": 0, "id": "missing", "text": "x"},
    {"op": "delete", "slide": 0, "id": "missing"},
    {"op": "addText", "slide": 0, "text": "x", "x": 0, "y": 0, "width": 30, "height": 30, "lineSpacing": 0.9},
])
def test_edit_rejects_invalid_operations(generated_pptx, operation):
    from smart_reporting.reporting.delivery.slides_editing import edit_pptx

    with pytest.raises(ValueError, match="pptx_"):
        edit_pptx(generated_pptx.read_bytes(), [operation])
