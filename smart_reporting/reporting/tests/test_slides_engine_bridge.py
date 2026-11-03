from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest
from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

ENGINE = Path(__file__).parents[1] / "slides_engine"
FIXTURE = ENGINE / "packages/pptx-engine/tests/fixtures/01_standard_business.pptx"


def _invoke(request: dict[str, object], root: Path) -> dict[str, object]:
    request_path = root / "request.json"
    request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        ["node_modules/.bin/tsx", "bridge/edit-pptx.ts", str(request_path)],
        cwd=ENGINE,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        env=os.environ.copy(),
    )
    return json.loads(result.stdout)


def test_slides_bridge_edits_text_and_preserves_other_slide_xml(tmp_path: Path):
    source = tmp_path / "source.pptx"
    output = tmp_path / "edited.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    inspected = _invoke({"action": "inspect", "input": str(source)}, tmp_path)
    slides = inspected["slides"]
    slide_index, element = next(
        (slide["slideIndex"], element)
        for slide in slides
        for element in slide["elements"]
        if element["editable"] and element["text"].strip()
    )
    original_text = element["text"]
    untouched_path = "ppt/slides/slide2.xml"
    with ZipFile(source) as archive:
        untouched_xml = archive.read(untouched_path)

    _invoke({
        "action": "edit",
        "input": str(source),
        "output": str(output),
        "edits": [{"slideIndex": slide_index, "elementId": element["id"], "text": "编辑验证"}],
        "order": list(range(len(slides))),
    }, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)
    edited = next(
        item
        for item in reopened["slides"][slide_index]["elements"]
        if item["id"] == element["id"]
    )

    assert original_text != edited["text"]
    assert edited["text"].splitlines()[0] == "编辑验证"
    with ZipFile(output) as archive:
        assert archive.read(untouched_path) == untouched_xml


def test_slides_bridge_applies_business_theme_and_keeps_all_slides(tmp_path: Path):
    source = tmp_path / "source.pptx"
    output = tmp_path / "themed.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    inspected = _invoke({"action": "inspect", "input": str(source)}, tmp_path)
    source_slide_count = len(inspected["slides"])
    with ZipFile(source) as archive:
        original_theme = archive.read("ppt/theme/theme1.xml")

    _invoke({
        "action": "edit",
        "input": str(source),
        "output": str(output),
        "edits": [],
        "order": list(range(source_slide_count)),
        "theme": "modern",
    }, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)

    assert len(reopened["slides"]) == source_slide_count
    with ZipFile(output) as archive:
        themed_xml = archive.read("ppt/theme/theme1.xml")
        assert themed_xml != original_theme
        assert b"C45A3C" in themed_xml


def test_slides_bridge_inserts_picture_asset_and_reopens_it(tmp_path: Path):
    source = tmp_path / "source.pptx"
    output = tmp_path / "pictured.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    inspected = _invoke({"action": "inspect", "input": str(source)}, tmp_path)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p1sAAAAASUVORK5CYII="
    )

    _invoke({
        "action": "edit",
        "input": str(source),
        "output": str(output),
        "edits": [],
        "order": list(range(len(inspected["slides"]))),
        "images": [{
            "slideIndex": 0,
            "bytesBase64": base64.b64encode(png).decode("ascii"),
            "extension": "png",
            "geometry": {"x": 24, "y": 24, "width": 120, "height": 80},
            "descr": "AI 配图",
        }],
    }, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)

    assert any(item["type"] == "picture" for item in reopened["slides"][0]["elements"])
    with ZipFile(output) as archive:
        assert any(path.startswith("ppt/media/image") and path.endswith(".png") for path in archive.namelist())


def test_slides_bridge_roundtrips_transition_and_animation_timing(tmp_path: Path):
    source = tmp_path / "source.pptx"
    output = tmp_path / "animated.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    inspected = _invoke({"action": "inspect", "input": str(source)}, tmp_path)
    slide_index, element = next(
        (slide["slideIndex"], element)
        for slide in inspected["slides"]
        for element in slide["elements"]
        if element["editable"] and element["text"].strip()
    )

    _invoke({
        "action": "edit",
        "input": str(source),
        "output": str(output),
        "edits": [],
        "order": list(range(len(inspected["slides"]))),
        "transitions": [{"slideIndex": slide_index, "kind": "fade"}],
        "animations": [{
            "slideIndex": slide_index,
            "elementId": element["id"],
            "effect": "flyIn",
            "trigger": "afterPrev",
            "durationMs": 1250,
            "delayMs": 300,
        }],
    }, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)

    slide = reopened["slides"][slide_index]
    assert slide["transition"] == "fade"
    assert any(
        item["effect"] == "flyIn"
        and item["trigger"] == "afterPrev"
        and item["durationMs"] == 1250
        and item["delayMs"] == 300
        for item in slide["animations"]
    )


def test_slides_bridge_inspects_master_layout_chain_and_switches_layout(tmp_path: Path):
    source = tmp_path / "source.pptx"
    output = tmp_path / "layout-switched.pptx"
    source.write_bytes(FIXTURE.read_bytes())

    inspected = _invoke({"action": "inspect", "input": str(source)}, tmp_path)
    assert inspected["masterParts"]
    assert inspected["layouts"]
    current = inspected["slides"][0].get("layoutPath")
    target = next(layout["path"] for layout in inspected["layouts"] if layout["path"] != current)
    slide_index = 0

    _invoke({
        "action": "edit",
        "input": str(source),
        "output": str(output),
        "edits": [],
        "order": list(range(len(inspected["slides"]))),
        "slideLayouts": [{"slideIndex": slide_index, "layoutPath": target}],
    }, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)
    assert reopened["slides"][slide_index]["layoutPath"] == target


def test_slides_bridge_updates_existing_animation_timing_and_preserves_other_effects(tmp_path: Path):
    source = tmp_path / "source.pptx"
    animated = tmp_path / "animated.pptx"
    output = tmp_path / "updated.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    inspected = _invoke({"action": "inspect", "input": str(source)}, tmp_path)
    slide_index, element = next(
        (slide["slideIndex"], element)
        for slide in inspected["slides"]
        for element in slide["elements"]
        if element["editable"] and element["text"].strip()
    )
    target = {"slideIndex": slide_index, "elementId": element["id"]}
    _invoke({
        "action": "edit", "input": str(source), "output": str(animated),
        "animations": [
            {**target, "effect": "fade", "trigger": "onClick", "durationMs": 500, "delayMs": 0},
            {**target, "effect": "pulse", "trigger": "withPrev", "durationMs": 800, "delayMs": 100},
        ],
    }, tmp_path)
    _invoke({
        "action": "edit", "input": str(animated), "output": str(output),
        "animations": [{
            **target, "effect": "fade", "trigger": "afterPrev",
            "durationMs": 1500, "delayMs": 300,
        }],
    }, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)
    animations = reopened["slides"][slide_index]["animations"]
    fades = [item for item in animations if item["elementId"] == element["id"] and item["effect"] == "fade"]
    assert len(fades) == 1
    assert fades[0]["trigger"] == "afterPrev"
    assert fades[0]["durationMs"] == 1500
    assert fades[0]["delayMs"] == 300
    assert any(
        item["elementId"] == element["id"]
        and item["effect"] == "pulse"
        and item["durationMs"] == 800
        and item["delayMs"] == 100
        for item in animations
    )


@pytest.mark.parametrize('replacement', ['新正文', '新第一段\n新第二段\n追加第三段'])
def test_slides_bridge_replaces_entire_multiline_text_without_old_paragraphs(tmp_path: Path, replacement: str):
    source = tmp_path / 'multiline.pptx'
    output = tmp_path / 'edited.pptx'
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(2))
    box.name = '多段正文'
    first = box.text_frame.paragraphs[0]
    first.alignment = PP_ALIGN.RIGHT
    first.add_run().text = '旧第一段'
    first.runs[0].font.size = Pt(18)
    first.runs[0].font.bold = True
    second = box.text_frame.add_paragraph()
    second.text = '旧第二段不能残留'
    second.alignment = PP_ALIGN.CENTER
    second.runs[0].font.size = Pt(16)
    untouched = slide.shapes.add_textbox(Inches(1), Inches(4), Inches(6), Inches(1))
    untouched.name = '保留对象'
    untouched.text = '不应修改的对象'
    untouched_xml = untouched.element.xml
    other_slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    other_slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1)).text = '不应修改的页面'
    presentation.save(source)
    with ZipFile(source) as archive:
        other_xml = archive.read('ppt/slides/slide2.xml')
    inspected = _invoke({'action': 'inspect', 'input': str(source)}, tmp_path)
    element = next(item for item in inspected['slides'][0]['elements'] if item['name'] == '多段正文')
    assert element['text'] == '旧第一段\n旧第二段不能残留'

    _invoke({
        'action': 'edit', 'input': str(source), 'output': str(output),
        'edits': [{'slideIndex': 0, 'elementId': element['id'], 'text': replacement}],
    }, tmp_path)

    reopened = _invoke({'action': 'inspect', 'input': str(output)}, tmp_path)
    actual = next(item for item in reopened['slides'][0]['elements'] if item['name'] == '多段正文')
    assert actual['text'] == replacement
    revised = Presentation(output)
    revised_box = next(shape for shape in revised.slides[0].shapes if shape.name == '多段正文')
    assert [paragraph.text for paragraph in revised_box.text_frame.paragraphs] == replacement.split('\n')
    assert revised_box.text_frame.paragraphs[0].alignment == PP_ALIGN.RIGHT
    assert revised_box.text_frame.paragraphs[0].runs[0].font.size == Pt(18)
    assert revised_box.text_frame.paragraphs[0].runs[0].font.bold is True
    if '\n' in replacement:
        assert revised_box.text_frame.paragraphs[1].alignment == PP_ALIGN.CENTER
        assert revised_box.text_frame.paragraphs[1].runs[0].font.size == Pt(16)
    assert next(shape for shape in revised.slides[0].shapes if shape.name == '保留对象').element.xml == untouched_xml
    with ZipFile(output) as archive:
        assert archive.read('ppt/slides/slide2.xml') == other_xml


def test_slides_bridge_audit_exception_retains_edited_pptx(tmp_path: Path):
    isolated = tmp_path / 'engine'
    (isolated / 'bridge').mkdir(parents=True)
    for name in ('node_modules', 'packages', 'package.json'):
        (isolated / name).symlink_to(ENGINE / name, target_is_directory=(ENGINE / name).is_dir())
    bridge = (ENGINE / 'bridge/edit-pptx.ts').read_text(encoding='utf-8').replace(
        "import { auditDeck } from '../packages/pipelines/src/slides/audit-deck.ts'",
        "const auditDeck = async (_bytes: Uint8Array): Promise<never> => { await readFile(request.output!); throw new Error('injected edit audit failure') }",
    )
    (isolated / 'bridge/edit-pptx.ts').write_text(bridge, encoding='utf-8')
    source, output = tmp_path / 'source.pptx', tmp_path / 'edited.pptx'
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1)).text = '待编辑正文'
    presentation.save(source)
    inspected = _invoke({'action': 'inspect', 'input': str(source)}, tmp_path)
    element = next(item for item in inspected['slides'][0]['elements'] if item['text'] == '待编辑正文')
    request = tmp_path / 'edit.json'
    request.write_text(json.dumps({
        'action': 'edit', 'input': str(source), 'output': str(output),
        'edits': [{'slideIndex': 0, 'elementId': element['id'], 'text': '已保存新正文'}],
    }), encoding='utf-8')

    result = subprocess.run(
        ['node_modules/.bin/tsx', 'bridge/edit-pptx.ts', str(request)],
        cwd=isolated, check=False, capture_output=True, text=True, timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert Presentation(output).slides[0].shapes[0].text == '已保存新正文'
    assert Presentation(source).slides[0].shapes[0].text == '待编辑正文'
    assert json.loads(result.stdout)['issues'] == [
        {'page': 0, 'message': 'PPTX layout audit failed: injected edit audit failure'},
    ]
