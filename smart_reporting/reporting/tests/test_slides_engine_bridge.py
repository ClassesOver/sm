from __future__ import annotations

import base64
import json
import re
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


def test_slides_bridge_slide_size_rescales_objects_and_independently_reopens(tmp_path: Path):
    source = tmp_path / 'source.pptx'
    output = tmp_path / 'resized.pptx'
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = '尺寸回读'
    presentation.save(source)

    _invoke({'action': 'edit', 'input': str(source), 'output': str(output),
             'slideSize': {'cx': 12192000, 'cy': 6858000}}, tmp_path)

    model = _invoke({'action': 'inspect', 'input': str(output)}, tmp_path)
    assert model['size'] == {'cx': 12192000, 'cy': 6858000}
    assert model['slides'][0]['elements'][0]['geometry'] == {'x': 128, 'y': 96, 'width': 384, 'height': 96}
    reopened = Presentation(output)
    assert reopened.slide_width == 12192000 and reopened.slide_height == 6858000
    assert reopened.slides[0].shapes[0].left == Inches(4 / 3)


@pytest.mark.parametrize('size', [
    {'cx': 10692000, 'cy': 7560000}, {'cx': 7560000, 'cy': 10692000},
    {'cx': 15120000, 'cy': 10692000}, {'cx': 10692000, 'cy': 15120000},
])
def test_slides_bridge_paper_size_presets_scale_geometry_and_independently_reopen(tmp_path: Path, size):
    source = tmp_path / 'source.pptx'
    output = tmp_path / 'paper.pptx'
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = '纸张尺寸'
    presentation.save(source)

    _invoke({'action': 'edit', 'input': str(source), 'output': str(output), 'slideSize': size}, tmp_path)

    reopened = Presentation(output)
    assert (reopened.slide_width, reopened.slide_height) == (size['cx'], size['cy'])
    shape = reopened.slides[0].shapes[0]
    assert shape.left == round(914400 * size['cx'] / 9144000)
    assert shape.top == round(914400 * size['cy'] / 6858000)
    assert shape.width == round(2743200 * size['cx'] / 9144000)
    assert shape.height == round(914400 * size['cy'] / 6858000)
    assert shape.text == '纸张尺寸'


@pytest.mark.parametrize('size', [{'cx': 1, 'cy': 1}, {'cx': 51206401, 'cy': 914400}, {'cx': True, 'cy': 914400}, {'cx': 9000000.5, 'cy': 7200000}, {'cx': 12192000, 'cy': 6858000, 'extra': True}])
def test_slides_bridge_rejects_unadvertised_slide_size_fields_without_output(tmp_path: Path, size):
    source = tmp_path / 'source.pptx'
    output = tmp_path / 'invalid.pptx'
    source.write_bytes(FIXTURE.read_bytes())

    with pytest.raises(subprocess.CalledProcessError) as error:
        _invoke({'action': 'edit', 'input': str(source), 'output': str(output), 'slideSize': size}, tmp_path)

    assert 'slide_size_invalid' in error.value.stderr
    assert not output.exists()


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


def test_slides_bridge_appends_same_target_animations_in_request_order(tmp_path: Path):
    source = tmp_path / "source.pptx"
    animated = tmp_path / "animated.pptx"
    output = tmp_path / "with-more-animations.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    inspected = _invoke({"action": "inspect", "input": str(source)}, tmp_path)
    slide_index, element = next(
        (slide["slideIndex"], element)
        for slide in inspected["slides"]
        for element in slide["elements"]
        if element["editable"] and element["text"].strip()
    )
    target = {"slideIndex": slide_index, "elementId": element["id"]}
    first = {**target, "effect": "fade", "trigger": "onClick", "durationMs": 500, "delayMs": 0}
    _invoke({"action": "edit", "input": str(source), "output": str(animated), "animations": [first]}, tmp_path)
    appended = [
        {**target, "effect": "fade", "trigger": "withPrev", "durationMs": 700, "delayMs": 50, "append": True},
        {**target, "effect": "pulse", "trigger": "afterPrev", "durationMs": 900, "delayMs": 100, "append": True},
    ]
    _invoke({"action": "edit", "input": str(animated), "output": str(output), "animations": appended}, tmp_path)

    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)
    animations = [
        item for item in reopened["slides"][slide_index]["animations"]
        if item["elementId"] == element["id"]
    ]
    assert [(item["effect"], item["trigger"], item["durationMs"], item["delayMs"]) for item in animations] == [
        ("fade", "onClick", 500, 0),
        ("fade", "withPrev", 700, 50),
        ("pulse", "afterPrev", 900, 100),
    ]


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
    # 只替换 edit-pptx.ts；其余桥接模块（如 pptx-transition.ts）原样链接，避免新增依赖时隔离副本缺件。
    for sibling in (ENGINE / 'bridge').iterdir():
        if sibling.name != 'edit-pptx.ts':
            (isolated / 'bridge' / sibling.name).symlink_to(sibling)
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


def test_slides_bridge_sets_background_adds_watermark_and_deletes_object(tmp_path: Path):
    """移植 #182：页面背景、新增文本框/水印与删除对象；重排和主题后仍落在原指定页面。"""
    source = tmp_path / "source.pptx"
    output = tmp_path / "structured.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    inspected = _invoke({"action": "inspect", "input": str(source)}, tmp_path)
    slides = inspected["slides"]
    assert len(slides) >= 2
    target = slides[1]
    victim = next(item for item in target["elements"] if item["deletable"] and item["text"].strip())
    order = [1, 0, *range(2, len(slides))]

    _invoke({
        "action": "edit",
        "input": str(source),
        "output": str(output),
        "edits": [],
        "order": order,
        "theme": "modern",
        "backgrounds": [{"slideIndex": 1, "color": "#12ab34"}],
        "textBoxes": [
            {"slideIndex": 1, "text": "内部资料", "geometry": {"x": 200, "y": 240, "width": 560, "height": 120},
             "fontSize": 64, "fontFamily": "Microsoft YaHei", "color": "#DCE3EB", "rotation": -25},
            {"slideIndex": 1, "text": "第一行\n第二行", "geometry": {"x": 40, "y": 40, "width": 300, "height": 80},
             "bold": True},
        ],
        "deletions": [{"slideIndex": 1, "elementId": victim["id"]}],
    }, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)
    moved = reopened["slides"][0]

    assert moved["background"] == "#12AB34"
    texts = [item["text"] for item in moved["elements"]]
    assert "内部资料" in texts and "第一行\n第二行" in texts
    assert victim["text"] not in texts
    presentation = Presentation(str(output))
    watermark = next(shape for shape in presentation.slides[0].shapes if shape.has_text_frame and shape.text_frame.text == "内部资料")
    assert round(watermark.rotation) == 335
    run = watermark.text_frame.paragraphs[0].runs[0]
    assert run.font.size == Pt(64)
    assert str(run.font.color.rgb) == "DCE3EB"
    assert len(presentation.slides) == len(slides)


def test_slides_bridge_rejects_deleting_object_with_pending_edit_without_output(tmp_path: Path):
    source = tmp_path / "source.pptx"
    output = tmp_path / "rejected.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    inspected = _invoke({"action": "inspect", "input": str(source)}, tmp_path)
    slide_index, element = next(
        (slide["slideIndex"], element)
        for slide in inspected["slides"]
        for element in slide["elements"]
        if element["editable"] and element["text"].strip()
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps({
        "action": "edit",
        "input": str(source),
        "output": str(output),
        "edits": [{"slideIndex": slide_index, "elementId": element["id"], "text": "改写"}],
        "deletions": [{"slideIndex": slide_index, "elementId": element["id"]}],
    }, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        ["node_modules/.bin/tsx", "bridge/edit-pptx.ts", str(request_path)],
        cwd=ENGINE, check=False, capture_output=True, text=True, timeout=120,
    )

    assert result.returncode != 0
    assert "delete_target_has_pending_edits" in result.stderr
    assert not output.exists()


def test_slides_bridge_adds_blank_slides_with_source_layout_at_ordered_positions(tmp_path: Path):
    """固定源 onAddSlide → addBlankSlide：新页沿用来源页版式、无内容，由 order 放到目标位置，来源页不变。"""
    source = tmp_path / "source.pptx"
    output = tmp_path / "new-slides.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    inspected = _invoke({"action": "inspect", "input": str(source)}, tmp_path)
    slides = inspected["slides"]
    count = len(slides)
    assert count >= 3
    # 新页 count+0 插在第 1 页之后，沿用第 3 页（索引 2）的版式；新页 count+1 放在最前，沿用第 1 页版式
    order = [count + 1, 0, count, *range(1, count)]
    _invoke({
        "action": "edit", "input": str(source), "output": str(output), "edits": [],
        "order": order, "newSlides": [{"layoutFrom": 2}, {"layoutFrom": 0}],
        "transitions": [{"slideIndex": 1, "kind": "fade"}],
    }, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)["slides"]
    assert len(reopened) == count + 2
    assert reopened[0]["layoutPath"] == slides[0]["layoutPath"]
    assert reopened[2]["layoutPath"] == slides[2]["layoutPath"]
    assert reopened[0]["elements"] == [] and reopened[2]["elements"] == []
    # 来源页按顺序保留，且索引寻址的转场作用于原第 2 页
    kept = [reopened[1], *reopened[3:]]
    assert [slide["layoutPath"] for slide in kept] == [slide["layoutPath"] for slide in slides]
    assert [len(slide["elements"]) for slide in kept] == [len(slide["elements"]) for slide in slides]
    assert reopened[3].get("transition") == "fade"
    with ZipFile(output) as archive:
        assert len([name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")]) == count + 2
    assert len(Presentation(str(output)).slides) == count + 2


@pytest.mark.parametrize("request_patch", [
    {"newSlides": [{"layoutFrom": 99}]},
    {"newSlides": [{"layoutFrom": 0, "extra": 1}]},
    {"newSlides": [{"layoutFrom": 0}], "order": None},
    {"newSlides": [{"layoutFrom": 0}], "order": "short"},
])
def test_slides_bridge_rejects_invalid_new_slides_without_output(tmp_path: Path, request_patch: dict[str, object]):
    source = tmp_path / "source.pptx"
    output = tmp_path / "rejected.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    count = len(_invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"])
    request: dict[str, object] = {"action": "edit", "input": str(source), "output": str(output), "edits": [], "order": [*range(count), count]}
    request.update(request_patch)
    if request.get("order") is None:
        request.pop("order")
    elif request["order"] == "short":
        request["order"] = list(range(count))
    with pytest.raises(subprocess.CalledProcessError):
        _invoke(request, tmp_path)
    assert not output.exists()


def test_slides_bridge_deletes_source_slides_with_new_slides_and_order(tmp_path: Path):
    """固定源 deleteSlide：删除来源页后 order 只列保留页（含新建页），其余页内容与按索引的修改保持正确。"""
    source = tmp_path / "source.pptx"
    output = tmp_path / "deleted.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    slides = _invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"]
    count = len(slides)
    kept = [index for index in range(count) if index != 1]
    _invoke({
        "action": "edit", "input": str(source), "output": str(output), "edits": [],
        "deletedSlides": [1], "newSlides": [{"layoutFrom": 0}],
        "order": [count, *reversed(kept)], "transitions": [{"slideIndex": 0, "kind": "fade"}],
    }, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)["slides"]
    assert len(reopened) == count
    assert reopened[0]["elements"] == []
    expected = [slides[index] for index in reversed(kept)]
    assert [len(slide["elements"]) for slide in reopened[1:]] == [len(slide["elements"]) for slide in expected]
    assert reopened[-1].get("transition") == "fade"
    with ZipFile(output) as archive:
        assert len([name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")]) == count
    assert len(Presentation(str(output)).slides) == count


@pytest.mark.parametrize("request_patch", [
    {"deletedSlides": [1], "order": "keep-deleted"},
    {"deletedSlides": [1, 1]},
    {"deletedSlides": [99]},
    {"deletedSlides": [1], "transitions": [{"slideIndex": 1, "kind": "fade"}]},
    {"deletedSlides": [0], "newSlides": [{"layoutFrom": 0}]},
    {"deletedSlides": "all"},
])
def test_slides_bridge_rejects_invalid_slide_deletions_without_output(tmp_path: Path, request_patch: dict[str, object]):
    source = tmp_path / "source.pptx"
    output = tmp_path / "rejected.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    count = len(_invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"])
    request: dict[str, object] = {"action": "edit", "input": str(source), "output": str(output), "edits": []}
    request.update(request_patch)
    if request.get("order") == "keep-deleted":
        request["order"] = list(range(count - 1))
    elif request["deletedSlides"] == "all":
        request["deletedSlides"], request["order"] = list(range(count)), []
    else:
        removed = set(request["deletedSlides"]) if isinstance(request["deletedSlides"], list) else set()
        extra = len(request.get("newSlides", []))
        request["order"] = [index for index in range(count + extra) if index not in removed]
    with pytest.raises(subprocess.CalledProcessError):
        _invoke(request, tmp_path)
    assert not output.exists()


def test_slides_bridge_duplicates_saved_slide_content_and_rejects_pending_edits_on_source(tmp_path: Path):
    """固定源 duplicateSlide：副本复制已保存内容并由 order 落位；被复制页同批有修改时拒绝且不产生输出。"""
    source = tmp_path / "source.pptx"
    output = tmp_path / "duplicated.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    slides = _invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"]
    count = len(slides)
    _invoke({"action": "edit", "input": str(source), "output": str(output), "edits": [],
             "newSlides": [{"duplicateOf": 1}], "order": [0, 1, count, *range(2, count)]}, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)["slides"]
    assert len(reopened) == count + 1
    texts = lambda slide: [element.get("text") for element in slide["elements"]]
    assert texts(reopened[2]) == texts(slides[1]) and texts(reopened[1]) == texts(slides[1])
    assert reopened[2]["layoutPath"] == slides[1]["layoutPath"]
    # 副本复制已保存内容：同批对来源页的修改（转场、表格）只作用于来源页
    edited = tmp_path / "edited-source.pptx"
    _invoke({"action": "edit", "input": str(source), "output": str(edited), "edits": [],
             "newSlides": [{"duplicateOf": 1}], "order": [*range(count + 1)],
             "transitions": [{"slideIndex": 1, "kind": "fade"}], "tables": [{"slideIndex": 1, "rows": 2, "cols": 2}]}, tmp_path)
    after = _invoke({"action": "inspect", "input": str(edited)}, tmp_path)["slides"]
    assert after[1].get("transition") == "fade" and after[count].get("transition") != "fade"
    assert sum(shape.has_table for shape in Presentation(str(edited)).slides[1].shapes) == 1
    assert sum(shape.has_table for shape in Presentation(str(edited)).slides[count].shapes) == 0
    rejected = tmp_path / "rejected.pptx"
    with pytest.raises(subprocess.CalledProcessError):
        _invoke({"action": "edit", "input": str(source), "output": str(rejected), "edits": [],
                 "newSlides": [{"duplicateOf": 1, "layoutFrom": 1}], "order": [*range(count + 1)]}, tmp_path)
    assert not rejected.exists()


def test_slides_bridge_adds_slide_with_chosen_layout_placeholders(tmp_path: Path):
    """固定源 onAddSlideWithLayout：新页使用所选版式并带版式占位符；非法版式拒绝且不产生输出。"""
    source = tmp_path / "source.pptx"
    output = tmp_path / "with-layout.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    inspected = _invoke({"action": "inspect", "input": str(source)}, tmp_path)
    count = len(inspected["slides"])
    layout = next(item for item in inspected["layouts"] if item["placeholders"])
    _invoke({"action": "edit", "input": str(source), "output": str(output), "edits": [],
             "newSlides": [{"withLayout": layout["path"]}], "order": [count, *range(count)]}, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)["slides"]
    assert len(reopened) == count + 1
    assert reopened[0]["layoutPath"] == layout["path"]
    assert len(Presentation(str(output)).slides[0].placeholders) >= 1
    rejected = tmp_path / "rejected.pptx"
    with pytest.raises(subprocess.CalledProcessError):
        _invoke({"action": "edit", "input": str(source), "output": str(rejected), "edits": [],
                 "newSlides": [{"withLayout": "ppt/slideLayouts/missing.xml"}], "order": [*range(count + 1)]}, tmp_path)
    assert not rejected.exists()


def test_slides_bridge_reset_layout_restores_inherited_placeholder_geometry(tmp_path: Path):
    """固定源 onResetLayout：占位符移位后重置回版式继承位置；同批对其他对象的修改照常叠加。"""
    from pptx.util import Emu
    source = tmp_path / "source.pptx"
    moved = tmp_path / "moved.pptx"
    output = tmp_path / "reset.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    title = slide.shapes.title
    title.text = "标题"
    inherited = (title.left, title.top, title.width, title.height)
    presentation.save(source)
    shifted = Presentation(source)
    shape = shifted.slides[0].shapes.title
    shape.left, shape.top = Emu(inherited[0] + 914400), Emu(inherited[1] + 914400)
    shifted.save(moved)
    assert Presentation(moved).slides[0].shapes.title.left == inherited[0] + 914400
    _invoke({"action": "edit", "input": str(moved), "output": str(output), "edits": [], "resetLayouts": [0]}, tmp_path)
    reset = Presentation(output).slides[0].shapes.title
    assert (reset.left, reset.top, reset.width, reset.height) == inherited
    assert reset.text == "标题"
    for bad in ([0, 0], [5], ["0"]):
        with pytest.raises(subprocess.CalledProcessError):
            _invoke({"action": "edit", "input": str(moved), "output": str(tmp_path / "bad.pptx"), "edits": [], "resetLayouts": bad}, tmp_path)
    assert not (tmp_path / "bad.pptx").exists()


def test_slides_bridge_inserts_gallery_shapes_with_pinned_default_styles(tmp_path: Path):
    """固定源 Insert ▸ Shapes：预设形状写入 prstGeom；普通形状出厂填充 #C43E1C，线条为 1pt 黑色；未知预设拒绝。"""
    source = tmp_path / "source.pptx"
    output = tmp_path / "shapes.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    count = len(_invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"])
    before = len(Presentation(source).slides[0].shapes)
    _invoke({"action": "edit", "input": str(source), "output": str(output), "edits": [], "order": list(range(count)), "shapes": [
        {"slideIndex": 0, "kind": "roundRect", "geometry": {"x": 100, "y": 100, "width": 200, "height": 120}},
        {"slideIndex": 0, "kind": "lineArrow", "geometry": {"x": 100, "y": 300, "width": 200, "height": 1}},
    ]}, tmp_path)
    with ZipFile(output) as archive:
        xml = archive.read("ppt/slides/slide1.xml").decode()
    assert 'prst="roundRect"' in xml and 'srgbClr val="C43E1C"' in xml
    assert 'prst="straightConnector1"' in xml and '<a:ln w="12700"' in xml
    assert len(Presentation(output).slides[0].shapes) == before + 2
    for bad in ({"slideIndex": 0, "kind": "notAShape", "geometry": {"x": 1, "y": 1, "width": 10, "height": 10}},
                {"slideIndex": 0, "kind": "rect", "geometry": {"x": 1, "y": 1, "width": 10, "height": 10}, "fill": "#000000"},
                {"slideIndex": 0, "kind": "rect", "geometry": {"x": 1, "y": 1, "width": 0, "height": 10}}):
        with pytest.raises(subprocess.CalledProcessError):
            _invoke({"action": "edit", "input": str(source), "output": str(tmp_path / "bad.pptx"), "edits": [], "shapes": [bad]}, tmp_path)
    assert not (tmp_path / "bad.pptx").exists()


def test_bridge_shape_allow_list_matches_frontend_gallery():
    import re
    frontend = Path(__file__).parents[2] / "report_editor/frontend/src/vendor/genoffice-slides/components/shape-gallery-data.ts"
    presets = json.loads((ENGINE / "bridge/shape-presets.json").read_text(encoding="utf-8"))["presets"]
    assert presets == re.findall(r'prst: "([^"]+)"', frontend.read_text(encoding="utf-8"))
    assert len(presets) == 109


def test_slides_bridge_inserts_table_with_pinned_geometry_alongside_other_edits(tmp_path: Path):
    """固定源 Insert ▸ Table：rows×cols、宽 2/3 居中、顶部 10.5%、行高 29.2pt；同页其他修改不丢失；越界拒绝。"""
    source = tmp_path / "source.pptx"
    output = tmp_path / "table.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    inspected = _invoke({"action": "inspect", "input": str(source)}, tmp_path)
    count = len(inspected["slides"])
    _invoke({"action": "edit", "input": str(source), "output": str(output), "edits": [], "order": list(range(count)),
             "tables": [{"slideIndex": 0, "rows": 2, "cols": 5}],
             "textBoxes": [{"slideIndex": 0, "text": "表格旁说明", "geometry": {"x": 10, "y": 10, "width": 200, "height": 40}}]}, tmp_path)
    presentation = Presentation(str(output))
    frame = next(shape for shape in presentation.slides[0].shapes if shape.has_table)
    assert (len(frame.table.rows), len(frame.table.columns)) == (2, 5)
    cx, cy = presentation.slide_width, presentation.slide_height
    assert abs(frame.width - round(cx * 2 / 3)) <= 5 and abs(frame.left - round((cx - frame.width) / 2)) <= 5
    assert abs(frame.top - round(cy * 0.105)) <= 5
    assert all(row.height == round(29.2 * 12700) for row in frame.table.rows)
    assert any(shape.has_text_frame and shape.text == "表格旁说明" for shape in presentation.slides[0].shapes)
    for bad in ({"slideIndex": 0, "rows": 0, "cols": 5}, {"slideIndex": 0, "rows": 2, "cols": 76}, {"slideIndex": 99, "rows": 2, "cols": 2}, {"slideIndex": 0, "rows": 2, "cols": 2, "style": "x"}):
        with pytest.raises(subprocess.CalledProcessError):
            _invoke({"action": "edit", "input": str(source), "output": str(tmp_path / "bad.pptx"), "edits": [], "tables": [bad]}, tmp_path)
    assert not (tmp_path / "bad.pptx").exists()


def test_slides_bridge_inserts_slide_number_and_date_fields(tmp_path: Path):
    """固定源 insertField：文本框中的 <a:fld type="slidenum|datetime1">，缓存文字保留；未知字段拒绝。"""
    source = tmp_path / "source.pptx"
    output = tmp_path / "fields.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    count = len(_invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"])
    _invoke({"action": "edit", "input": str(source), "output": str(output), "edits": [], "order": list(range(count)), "textBoxes": [
        {"slideIndex": 0, "text": "1", "field": "slidenum", "fontSize": 18, "geometry": {"x": 430, "y": 248, "width": 100, "height": 44}},
        {"slideIndex": 0, "text": "2026/11/9", "field": "datetime1", "fontSize": 18, "geometry": {"x": 360, "y": 300, "width": 240, "height": 44}},
    ]}, tmp_path)
    with ZipFile(output) as archive:
        xml = archive.read("ppt/slides/slide1.xml").decode()
    assert re.search(r'<a:fld id="\{[0-9A-F-]+\}" type="slidenum">.*?<a:t>1</a:t></a:fld>', xml)
    assert re.search(r'<a:fld id="\{[0-9A-F-]+\}" type="datetime1">.*?<a:t>2026/11/9</a:t></a:fld>', xml)
    with pytest.raises(subprocess.CalledProcessError):
        _invoke({"action": "edit", "input": str(source), "output": str(tmp_path / "bad.pptx"), "edits": [], "textBoxes": [
            {"slideIndex": 0, "text": "x", "field": "author", "geometry": {"x": 1, "y": 1, "width": 10, "height": 10}}]}, tmp_path)
    assert not (tmp_path / "bad.pptx").exists()


def test_slides_bridge_sets_shape_fill_and_outline(tmp_path: Path):
    """固定源 Shape Format ▸ 填充/轮廓：纯色、无填充、描边颜色与线宽、无轮廓；非法颜色与目标拒绝。"""
    from pptx.util import Inches
    from pptx.enum.shapes import MSO_SHAPE
    source = tmp_path / "source.pptx"
    output = tmp_path / "styled.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1), Inches(1), Inches(3), Inches(2))
    slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(5), Inches(1), Inches(2), Inches(2))
    presentation.save(source)
    elements = _invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"][0]["elements"]
    first, second = elements[0]["id"], elements[1]["id"]
    _invoke({"action": "edit", "input": str(source), "output": str(output), "edits": [], "shapeStyles": [
        {"slideIndex": 0, "elementId": first, "fill": "#2E7D32", "stroke": {"color": "#1B2A41", "widthPt": 3}},
        {"slideIndex": 0, "elementId": second, "fill": "none", "stroke": None},
    ]}, tmp_path)
    with ZipFile(output) as archive:
        xml = archive.read("ppt/slides/slide1.xml").decode()
    shapes = re.findall(r"<p:sp>.*?</p:sp>", xml, re.S)
    assert 'srgbClr val="2E7D32"' in shapes[0] and '<a:ln w="38100"' in shapes[0] and 'srgbClr val="1B2A41"' in shapes[0]
    assert "<a:noFill/>" in shapes[1]
    for bad in ({"slideIndex": 0, "elementId": first, "fill": "green"},
                {"slideIndex": 0, "elementId": first},
                {"slideIndex": 0, "elementId": "missing", "fill": "#000000"},
                {"slideIndex": 0, "elementId": first, "stroke": {"color": "#000000", "widthPt": 0}}):
        with pytest.raises(subprocess.CalledProcessError):
            _invoke({"action": "edit", "input": str(source), "output": str(tmp_path / "bad.pptx"), "edits": [], "shapeStyles": [bad]}, tmp_path)
    assert not (tmp_path / "bad.pptx").exists()


def test_slides_bridge_table_coexists_with_element_edits_on_the_same_slide(tmp_path: Path):
    """表格插入会重建页面模型：须在按对象身份的修改（改字、样式、删除）之后执行，二者同批均生效。"""
    from pptx.util import Inches
    source = tmp_path / "source.pptx"
    output = tmp_path / "combined.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(4), Inches(3), Inches(1)).text = "原文字"
    slide.shapes.add_textbox(Inches(5), Inches(4), Inches(3), Inches(1)).text = "待删除"
    presentation.save(source)
    elements = _invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"][0]["elements"]
    keep = next(item["id"] for item in elements if item["text"] == "原文字")
    drop = next(item["id"] for item in elements if item["text"] == "待删除")
    _invoke({"action": "edit", "input": str(source), "output": str(output), "order": [0],
             "edits": [{"slideIndex": 0, "elementId": keep, "text": "改后文字"}],
             "shapeStyles": [{"slideIndex": 0, "elementId": keep, "fill": "#2E7D32"}],
             "deletions": [{"slideIndex": 0, "elementId": drop}],
             "tables": [{"slideIndex": 0, "rows": 2, "cols": 2}]}, tmp_path)
    shapes = Presentation(str(output)).slides[0].shapes
    texts = [shape.text for shape in shapes if shape.has_text_frame]
    assert "改后文字" in texts and "待删除" not in texts
    assert sum(shape.has_table for shape in shapes) == 1
    with ZipFile(output) as archive:
        assert 'srgbClr val="2E7D32"' in archive.read("ppt/slides/slide1.xml").decode()


def test_slides_bridge_changes_shape_preset_keeping_text_and_style(tmp_path: Path):
    """固定源 Change Shape：只换 prstGeom，保留位置、文字与同批样式；线条/未知预设/文本框拒绝。"""
    from pptx.util import Inches
    from pptx.enum.shapes import MSO_SHAPE
    source = tmp_path / "source.pptx"
    output = tmp_path / "reshaped.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1), Inches(1), Inches(3), Inches(2))
    shape.text = "形状文字"
    slide.shapes.add_textbox(Inches(5), Inches(1), Inches(3), Inches(1)).text = "文本框"
    presentation.save(source)
    elements = _invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"][0]["elements"]
    target = next(item for item in elements if item["text"] == "形状文字")
    textbox = next(item for item in elements if item["text"] == "文本框")
    _invoke({"action": "edit", "input": str(source), "output": str(output), "edits": [],
             "shapeKinds": [{"slideIndex": 0, "elementId": target["id"], "kind": "hexagon"}],
             "shapeStyles": [{"slideIndex": 0, "elementId": target["id"], "fill": "#2E7D32"}]}, tmp_path)
    with ZipFile(output) as archive:
        sp = next(item for item in re.findall(r"<p:sp>.*?</p:sp>", archive.read("ppt/slides/slide1.xml").decode(), re.S) if "形状文字" in item)
    assert 'prst="hexagon"' in sp and 'prst="roundRect"' not in sp and "2E7D32" in sp
    reopened = Presentation(str(output)).slides[0].shapes[0]
    assert (reopened.left, reopened.top, reopened.width, reopened.height) == (shape.left, shape.top, shape.width, shape.height)
    for bad in ({"slideIndex": 0, "elementId": target["id"], "kind": "lineArrow"},
                {"slideIndex": 0, "elementId": target["id"], "kind": "notAShape"},
                {"slideIndex": 0, "elementId": textbox["id"], "kind": "hexagon"}):
        with pytest.raises(subprocess.CalledProcessError):
            _invoke({"action": "edit", "input": str(source), "output": str(tmp_path / "bad.pptx"), "edits": [], "shapeKinds": [bad]}, tmp_path)
    assert not (tmp_path / "bad.pptx").exists()


def test_slides_bridge_adds_sections_at_final_positions(tmp_path: Path):
    """固定源 onAddSection：按重排后的最终位置在目标页前分节；无分节时前面的页归入默认节；非法名称拒绝。"""
    source = tmp_path / "source.pptx"
    output = tmp_path / "sections.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    count = len(_invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"])
    assert count >= 3
    order = [count - 1, *range(count - 1)]  # 末页移到最前
    _invoke({"action": "edit", "input": str(source), "output": str(output), "edits": [], "order": order,
             "sections": [{"slideIndex": 0, "name": "第二部分"}]}, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)
    assert reopened["sections"] == [
        {"name": "Default Section", "slideIndices": [0]},
        {"name": "第二部分", "slideIndices": list(range(1, count))},
    ]
    with ZipFile(output) as archive:
        assert '<p14:section name="第二部分"' in archive.read("ppt/presentation.xml").decode()
    for bad in ({"slideIndex": 0, "name": " "}, {"slideIndex": 0, "name": "a\nb"}, {"slideIndex": 99, "name": "x"}, {"slideIndex": 0, "name": "x", "extra": 1}):
        with pytest.raises(subprocess.CalledProcessError):
            _invoke({"action": "edit", "input": str(source), "output": str(tmp_path / "bad.pptx"), "edits": [], "sections": [bad]}, tmp_path)
    assert not (tmp_path / "bad.pptx").exists()


def test_slides_bridge_applies_header_footer_to_all_slides(tmp_path: Path):
    """固定源 HeaderFooterDialog：页脚、页码与日期占位符应用到全部页（含新建页），inspect 回读；同批改字不受影响。"""
    from pptx.util import Inches
    source = tmp_path / "source.pptx"
    output = tmp_path / "hf.pptx"
    presentation = Presentation()
    for text in ("第一页", "第二页"):
        presentation.slides.add_slide(presentation.slide_layouts[1]).shapes.title.text = text
    presentation.save(source)
    inspected = _invoke({"action": "inspect", "input": str(source)}, tmp_path)
    assert inspected["slides"][0]["headerFooter"] == {"footer": None, "slideNum": False, "date": None}
    title = next(item for item in inspected["slides"][0]["elements"] if item["text"] == "第一页")
    _invoke({"action": "edit", "input": str(source), "output": str(output), "order": [0, 1, 2],
             "edits": [{"slideIndex": 0, "elementId": title["id"], "text": "改后标题"}],
             "newSlides": [{"layoutFrom": 1}],
             "headerFooter": {"footer": "智能报告 · 内部", "slideNum": True, "date": "2026-11-10", "dateAuto": False}}, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)["slides"]
    assert len(reopened) == 3
    for slide in reopened:
        assert slide["headerFooter"]["footer"] == "智能报告 · 内部" and slide["headerFooter"]["slideNum"] is True
        assert slide["headerFooter"]["date"] == "2026-11-10"
    assert any(item["text"] == "改后标题" for item in reopened[0]["elements"])
    for bad in ({"footer": "x", "slideNum": True, "date": None}, {"footer": "a\u0001", "slideNum": True, "date": None, "dateAuto": True}, {"footer": None, "slideNum": "yes", "date": None, "dateAuto": True}):
        with pytest.raises(subprocess.CalledProcessError):
            _invoke({"action": "edit", "input": str(source), "output": str(tmp_path / "bad.pptx"), "edits": [], "headerFooter": bad}, tmp_path)
    assert not (tmp_path / "bad.pptx").exists()


def test_slides_bridge_inserts_wordart_presets(tmp_path: Path):
    """固定源 insertWordArt：54pt 居中、不换行随文字调整；填充/斜体/文字描边按预设写入；非法描边拒绝。"""
    source = tmp_path / "source.pptx"
    output = tmp_path / "wordart.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    count = len(_invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"])
    geometry = {"x": 244, "y": 312, "width": 473, "height": 97}
    _invoke({"action": "edit", "input": str(source), "output": str(output), "edits": [], "order": list(range(count)), "textBoxes": [
        {"slideIndex": 0, "text": "艺术字甲", "fontSize": 54, "color": "#70AD47", "bold": True, "italic": True, "wordArt": True, "geometry": geometry},
        {"slideIndex": 0, "text": "艺术字乙", "fontSize": 54, "color": "#FFFFFF", "bold": True, "outline": {"color": "#ED7D31", "widthEmu": 19050}, "wordArt": True, "geometry": geometry},
    ]}, tmp_path)
    with ZipFile(output) as archive:
        xml = archive.read("ppt/slides/slide1.xml").decode()
    first = next(sp for sp in re.findall(r"<p:sp>.*?</p:sp>", xml, re.S) if "艺术字甲" in sp)
    second = next(sp for sp in re.findall(r"<p:sp>.*?</p:sp>", xml, re.S) if "艺术字乙" in sp)
    assert 'wrap="none"' in first and "<a:spAutoFit/>" in first and 'algn="ctr"' in first
    assert re.search(r'<a:rPr[^>]*sz="5400"[^>]*b="1"[^>]*i="1"|<a:rPr[^>]*i="1"[^>]*sz="5400"|<a:rPr[^>]*sz="5400"[^>]*i="1"', first)
    assert '<a:ln w="19050"><a:solidFill><a:srgbClr val="ED7D31"/>' in second.replace(" ", " ")
    with pytest.raises(subprocess.CalledProcessError):
        _invoke({"action": "edit", "input": str(source), "output": str(tmp_path / "bad.pptx"), "edits": [], "textBoxes": [
            {"slideIndex": 0, "text": "x", "outline": {"color": "orange", "widthEmu": 19050}, "geometry": geometry}]}, tmp_path)
    assert not (tmp_path / "bad.pptx").exists()


def test_slides_bridge_edits_existing_table_cells_keeping_formatting(tmp_path: Path):
    """表格单元格编辑：inspect 回报单元格文字；改字保留原文字格式；越界/重复拒绝。"""
    from pptx.util import Inches, Pt
    source = tmp_path / "source.pptx"
    output = tmp_path / "cells.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(4), Inches(1)).table
    for (r, c), text in {(0, 0): "项目", (0, 1): "金额", (1, 0): "收入", (1, 1): "100"}.items():
        table.cell(r, c).text = text
    run = table.cell(1, 1).text_frame.paragraphs[0].runs[0]
    run.font.size = Pt(20); run.font.bold = True
    presentation.save(source)
    element = next(item for item in _invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"][0]["elements"] if item["type"] == "table")
    assert element["tableCells"] == [["项目", "金额"], ["收入", "100"]]
    _invoke({"action": "edit", "input": str(source), "output": str(output), "edits": [], "tableCells": [
        {"slideIndex": 0, "elementId": element["id"], "row": 1, "col": 1, "text": "120"},
        {"slideIndex": 0, "elementId": element["id"], "row": 0, "col": 0, "text": "指标\n（万元）"},
    ]}, tmp_path)
    cells = Presentation(str(output)).slides[0].shapes[0].table
    assert cells.cell(1, 1).text == "120" and cells.cell(0, 0).text == "指标\n（万元）" and cells.cell(1, 0).text == "收入"
    edited = cells.cell(1, 1).text_frame.paragraphs[0].runs[0].font
    assert edited.size == Pt(20) and edited.bold is True
    for bad in ({"slideIndex": 0, "elementId": element["id"], "row": 5, "col": 0, "text": "x"},
                {"slideIndex": 0, "elementId": "missing", "row": 0, "col": 0, "text": "x"}):
        with pytest.raises(subprocess.CalledProcessError):
            _invoke({"action": "edit", "input": str(source), "output": str(tmp_path / "bad.pptx"), "edits": [], "tableCells": [bad]}, tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        _invoke({"action": "edit", "input": str(source), "output": str(tmp_path / "bad.pptx"), "edits": [], "tableCells": [
            {"slideIndex": 0, "elementId": element["id"], "row": 0, "col": 0, "text": "a"}, {"slideIndex": 0, "elementId": element["id"], "row": 0, "col": 0, "text": "b"}]}, tmp_path)
    assert not (tmp_path / "bad.pptx").exists()


@pytest.mark.parametrize("kind,xml_tag", [("bar", "c:barChart"), ("barH", 'c:barDir val="bar"'), ("pie3D", "c:pie3DChart"), ("comboBarLine", "c:lineChart"), ("scatter", "c:scatterChart")])
def test_slides_bridge_inserts_gallery_charts(tmp_path: Path, kind: str, xml_tag: str):
    """固定源 Insert ▸ Chart：图表部件、内嵌数据与 graphicFrame 写入；位置 2/3 宽 3:2 居中；同页对象修改不受影响。"""
    source = tmp_path / "source.pptx"
    output = tmp_path / f"{kind}.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    count = len(_invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"])
    categories = ["0.7", "1.8", "2.6", "3.2"] if kind == "scatter" else ["第一季度", "第二季度", "第三季度", "第四季度"]
    series = [{"name": "销售额", "values": [4.3, 2.5, 3.5, 4.5]}, {"name": "增长率", "values": [2.0, 1.2, 2.6, 3.4]}]
    _invoke({"action": "edit", "input": str(source), "output": str(output), "edits": [], "order": list(range(count)),
             "charts": [{"slideIndex": 0, "kind": kind, "categories": categories, "series": series}]}, tmp_path)
    with ZipFile(output) as archive:
        charts = [name for name in archive.namelist() if re.fullmatch(r"ppt/charts/chart\d+\.xml", name)]
        xml = "".join(archive.read(name).decode() for name in charts)
        assert xml_tag in xml and "销售额" in xml
        assert any(name.startswith("ppt/embeddings/") for name in archive.namelist())
    presentation = Presentation(str(output))
    frame = next(shape for shape in presentation.slides[0].shapes if shape.has_chart)
    assert abs(frame.width - round(presentation.slide_width * 2 / 3)) <= 5
    assert abs(frame.left - round((presentation.slide_width - frame.width) / 2)) <= 5


def test_slides_bridge_rejects_invalid_chart_data(tmp_path: Path):
    source = tmp_path / "source.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    base = {"slideIndex": 0, "kind": "bar", "categories": ["a", "b"], "series": [{"name": "s", "values": [1, 2]}]}
    for patch in ({"kind": "treemap"}, {"categories": []}, {"series": [{"name": "s", "values": [1]}]}, {"series": [{"name": "s", "values": [1, "x"]}]},
                  {"kind": "comboBarLine"}, {"kind": "scatter"}, {"extra": True}):
        with pytest.raises(subprocess.CalledProcessError):
            _invoke({"action": "edit", "input": str(source), "output": str(tmp_path / "bad.pptx"), "edits": [], "charts": [{**base, **patch}]}, tmp_path)
    assert not (tmp_path / "bad.pptx").exists()


def test_slides_bridge_inserts_multiple_tables_and_charts_on_one_slide(tmp_path: Path):
    """表格与图表插入都会重建页面：同页多个插入须依次生效。"""
    source = tmp_path / "source.pptx"
    output = tmp_path / "multi.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    count = len(_invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"])
    _invoke({"action": "edit", "input": str(source), "output": str(output), "edits": [], "order": list(range(count)),
             "tables": [{"slideIndex": 0, "rows": 2, "cols": 2}, {"slideIndex": 0, "rows": 3, "cols": 3}],
             "charts": [{"slideIndex": 0, "kind": "line", "categories": ["a", "b"], "series": [{"name": "s", "values": [1, 2]}]},
                        {"slideIndex": 0, "kind": "pie", "categories": ["a", "b"], "series": [{"name": "s", "values": [1, 2]}]}]}, tmp_path)
    shapes = Presentation(str(output)).slides[0].shapes
    assert sum(shape.has_table for shape in shapes) == 2 and sum(shape.has_chart for shape in shapes) == 2


@pytest.mark.parametrize("layout", ["list", "process", "cycle", "hierarchy", "pyramid", "matrix", "venn"])
def test_slides_bridge_inserts_smartart_layouts(tmp_path: Path, layout: str):
    """固定源 Insert ▸ SmartArt：7 种布局写入可编辑形状组合，节点文字保留；位置同图表。"""
    source = tmp_path / "source.pptx"
    output = tmp_path / f"{layout}.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    count = len(_invoke({"action": "inspect", "input": str(source)}, tmp_path)["slides"])
    before = len(Presentation(source).slides[0].shapes)
    _invoke({"action": "edit", "input": str(source), "output": str(output), "edits": [], "order": list(range(count)),
             "smartArts": [{"slideIndex": 0, "layout": layout, "items": ["计划", "执行", "检查"]}]}, tmp_path)
    with ZipFile(output) as archive:
        xml = archive.read("ppt/slides/slide1.xml").decode()
    assert all(text in xml for text in ("计划", "执行", "检查"))
    assert len(Presentation(str(output)).slides[0].shapes) == before + 1


def test_slides_bridge_rejects_invalid_smartart(tmp_path: Path):
    source = tmp_path / "source.pptx"
    source.write_bytes(FIXTURE.read_bytes())
    base = {"slideIndex": 0, "layout": "list", "items": ["a"]}
    for patch in ({"layout": "radial"}, {"items": []}, {"items": ["x"] * 9}, {"items": ["a\nb"]}, {"extra": 1}):
        with pytest.raises(subprocess.CalledProcessError):
            _invoke({"action": "edit", "input": str(source), "output": str(tmp_path / "bad.pptx"), "edits": [], "smartArts": [{**base, **patch}]}, tmp_path)
    assert not (tmp_path / "bad.pptx").exists()


def _multi_paragraph_deck(path: Path) -> None:
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    body = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(2)).text_frame
    body.text = '第一段'
    for text in ('第二段', '第三段'):
        body.add_paragraph().text = text
    slide.shapes.add_textbox(Inches(1), Inches(4), Inches(5), Inches(1)).text_frame.text = '标题'
    deck.save(path)


def test_slides_bridge_animation_sequence_reorders_deletes_retimes_and_adds_paths_and_paragraphs(tmp_path: Path):
    source, animated, output = tmp_path / 'source.pptx', tmp_path / 'animated.pptx', tmp_path / 'sequenced.pptx'
    _multi_paragraph_deck(source)
    slide = _invoke({'action': 'inspect', 'input': str(source)}, tmp_path)['slides'][0]
    body, title = (element['id'] for element in slide['elements'][:2])
    _invoke({'action': 'edit', 'input': str(source), 'output': str(animated), 'animations': [
        {'slideIndex': 0, 'elementId': body, 'effect': 'fade', 'trigger': 'onClick', 'durationMs': 500, 'delayMs': 0},
        {'slideIndex': 0, 'elementId': title, 'effect': 'zoom', 'trigger': 'onClick', 'durationMs': 600, 'delayMs': 0, 'append': True},
        {'slideIndex': 0, 'elementId': title, 'effect': 'pulse', 'trigger': 'afterPrev', 'durationMs': 1000, 'delayMs': 0, 'append': True},
    ]}, tmp_path)
    existing = _invoke({'action': 'inspect', 'input': str(animated)}, tmp_path)['slides'][0]['animations']
    ref = lambda index, **patch: {'source': index, 'spid': existing[index]['spid'], 'effect': existing[index]['effect'], **patch}
    _invoke({'action': 'edit', 'input': str(animated), 'output': str(output), 'animationSequences': [{'slideIndex': 0, 'items': [
        ref(1, trigger='withPrev', durationMs=1200, delayMs=250),  # 上移并改计时
        ref(0),                                                    # 原第 1 条下移；原第 3 条（pulse）删除
        {'elementId': title, 'effect': 'motionPath', 'trigger': 'onClick', 'durationMs': 2000, 'delayMs': 0, 'motionPath': 'M 0 0 L 0.12 -0.12 L 0.24 0.12 L 0.36 0'},
        *({'elementId': body, 'effect': 'flyIn', 'trigger': 'onClick', 'durationMs': 500, 'delayMs': 0, 'direction': 'left', 'paragraph': index} for index in range(3)),
    ]}]}, tmp_path)
    animations = _invoke({'action': 'inspect', 'input': str(output)}, tmp_path)['slides'][0]['animations']
    assert [(item['elementId'], item['effect'], item['trigger'], item['durationMs'], item['delayMs'], item.get('paragraph'), item.get('direction')) for item in animations] == [
        (title, 'zoom', 'withPrev', 1200, 250, None, None),
        (body, 'fade', 'onClick', 500, 0, None, None),
        (title, 'motionPath', 'onClick', 2000, 0, None, None),
        (body, 'flyIn', 'onClick', 500, 0, 0, 'left'),
        (body, 'flyIn', 'onClick', 500, 0, 1, 'left'),
        (body, 'flyIn', 'onClick', 500, 0, 2, 'left'),
    ]
    assert animations[2]['motionPath'].startswith('M 0 0 L 0.12')
    with ZipFile(output) as archive:
        xml = archive.read('ppt/slides/slide1.xml').decode()
    assert all(f'<p:pgRg st="{index}" end="{index}"/>' in xml for index in range(3)) and 'build="p"' in xml and '<p:animMotion' in xml
    # 空列表 = “无”：移除本页全部动画
    cleared = tmp_path / 'cleared.pptx'
    _invoke({'action': 'edit', 'input': str(output), 'output': str(cleared), 'animationSequences': [{'slideIndex': 0, 'items': []}]}, tmp_path)
    assert _invoke({'action': 'inspect', 'input': str(cleared)}, tmp_path)['slides'][0]['animations'] == []


@pytest.mark.parametrize('items', [
    [{'source': 0, 'spid': 999, 'effect': 'fade'}],
    [{'source': 0, 'spid': None, 'effect': 'zoom'}],
    [{'source': 7, 'spid': 1, 'effect': 'fade'}],
    [{'source': 0, 'spid': None, 'effect': 'fade'}, {'source': 0, 'spid': None, 'effect': 'fade'}],
    [{'elementId': 'BODY', 'effect': 'motionPath', 'trigger': 'onClick', 'durationMs': 2000, 'delayMs': 0, 'motionPath': 'M 0 0 L 9 9'}],
    [{'elementId': 'BODY', 'effect': 'motionPath', 'trigger': 'onClick', 'durationMs': 2000, 'delayMs': 0}],
    [{'elementId': 'BODY', 'effect': 'fade', 'trigger': 'onClick', 'durationMs': 500, 'delayMs': 0, 'paragraph': 3}],
    [{'elementId': 'BODY', 'effect': 'fade', 'trigger': 'onClick', 'durationMs': 500, 'delayMs': 0, 'direction': 'left'}],
    [{'elementId': 'BODY', 'effect': 'mediaPlay', 'trigger': 'onClick', 'durationMs': 0, 'delayMs': 0}],
    [{'elementId': 'BODY', 'effect': 'fade', 'trigger': 'onHover', 'durationMs': 500, 'delayMs': 0}],
    [{'elementId': 'BODY', 'effect': 'fade', 'trigger': 'onClick', 'durationMs': -1, 'delayMs': 0}],
    [{'elementId': 'missing', 'effect': 'fade', 'trigger': 'onClick', 'durationMs': 500, 'delayMs': 0}],
])
def test_slides_bridge_rejects_invalid_animation_sequences_without_output(tmp_path: Path, items):
    source, animated, output = tmp_path / 'source.pptx', tmp_path / 'animated.pptx', tmp_path / 'never.pptx'
    _multi_paragraph_deck(source)
    body = _invoke({'action': 'inspect', 'input': str(source)}, tmp_path)['slides'][0]['elements'][0]['id']
    _invoke({'action': 'edit', 'input': str(source), 'output': str(animated), 'animations': [
        {'slideIndex': 0, 'elementId': body, 'effect': 'fade', 'trigger': 'onClick', 'durationMs': 500, 'delayMs': 0}]}, tmp_path)
    spid = _invoke({'action': 'inspect', 'input': str(animated)}, tmp_path)['slides'][0]['animations'][0]['spid']
    payload = json.loads(json.dumps(items).replace('"BODY"', json.dumps(body)).replace('"spid": null', f'"spid": {spid}'))
    with pytest.raises(subprocess.CalledProcessError):
        _invoke({'action': 'edit', 'input': str(animated), 'output': str(output), 'animationSequences': [{'slideIndex': 0, 'items': payload}]}, tmp_path)
    assert not output.exists()
    # 同页不能同时追加与覆盖；删除对象的动画不能保留
    with pytest.raises(subprocess.CalledProcessError):
        _invoke({'action': 'edit', 'input': str(animated), 'output': str(output), 'animationSequences': [{'slideIndex': 0, 'items': []}],
                 'animations': [{'slideIndex': 0, 'elementId': body, 'effect': 'fade', 'trigger': 'onClick', 'durationMs': 500, 'delayMs': 0, 'append': True}]}, tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        _invoke({'action': 'edit', 'input': str(animated), 'output': str(output), 'deletions': [{'slideIndex': 0, 'elementId': body}],
                 'animationSequences': [{'slideIndex': 0, 'items': [{'source': 0, 'spid': spid, 'effect': 'fade'}]}]}, tmp_path)
    assert not output.exists()


def test_animation_sequences_validate_effective_text_paragraphs(tmp_path):
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(2)).text = 'one\ntwo\nthree'
    source = tmp_path / 'paragraphs.pptx'
    presentation.save(source)
    element = _invoke({'action': 'inspect', 'input': str(source)}, tmp_path)['slides'][0]['elements'][0]
    item = {'elementId': element['id'], 'effect': 'fade', 'trigger': 'onClick', 'durationMs': 500, 'delayMs': 0, 'paragraph': 2}
    request = {'action': 'edit', 'input': str(source), 'output': str(tmp_path / 'bad.pptx'),
               'edits': [{'slideIndex': 0, 'elementId': element['id'], 'text': 'single'}],
               'animationSequences': [{'slideIndex': 0, 'items': [item]}]}
    with pytest.raises(subprocess.CalledProcessError):
        _invoke(request, tmp_path)
    assert not (tmp_path / 'bad.pptx').exists()
    request['output'] = str(tmp_path / 'expanded.pptx')
    request['edits'][0]['text'] = 'one\ntwo\nthree\nfour'
    item['paragraph'] = 3
    _invoke(request, tmp_path)
    from lxml import etree
    with ZipFile(request['output']) as archive:
        doc = etree.fromstring(archive.read('ppt/slides/slide1.xml'))
    ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main', 'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    assert doc.xpath('count(//p:sp/p:txBody/a:p)', namespaces=ns) == 4
    assert set(doc.xpath('//p:pgRg/@st', namespaces=ns)) == {'3'}


def test_table_cell_replacement_preserves_corresponding_paragraph_formats(tmp_path):
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(5), Inches(2)).table
    cell = table.cell(0, 0)
    cell.text = 'first\nsecond'
    for index, paragraph in enumerate(cell.text_frame.paragraphs):
        paragraph.runs[0].font.size = Pt(12 + index * 8)
        paragraph.runs[0].font.bold = bool(index)
    table.cell(1, 1).text = 'unchanged'
    source, output = tmp_path / 'table.pptx', tmp_path / 'table-edit.pptx'
    presentation.save(source)
    target = next(el for el in _invoke({'action': 'inspect', 'input': str(source)}, tmp_path)['slides'][0]['elements'] if el['type'] == 'table')
    _invoke({'action': 'edit', 'input': str(source), 'output': str(output), 'edits': [],
             'tableCells': [{'slideIndex': 0, 'elementId': target['id'], 'row': 0, 'col': 0, 'text': 'new first\nnew second'}]}, tmp_path)
    saved = Presentation(output).slides[0].shapes[0].table
    assert [paragraph.runs[0].font.size for paragraph in saved.cell(0, 0).text_frame.paragraphs] == [Pt(12), Pt(20)]
    assert saved.cell(1, 1).text == 'unchanged'


def test_table_design_shading_and_borders_preserve_text_grid_and_merged_cells(tmp_path):
    from lxml import etree
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    table = slide.shapes.add_table(2, 3, Inches(1), Inches(1), Inches(6), Inches(2)).table
    for ri in range(2):
        for ci in range(3):
            table.cell(ri, ci).text = f'{ri}:{ci}'
    table.cell(0, 0).merge(table.cell(0, 1))
    source, output = tmp_path / 'style-source.pptx', tmp_path / 'style-output.pptx'
    presentation.save(source)
    target = next(el for el in _invoke({'action': 'inspect', 'input': str(source)}, tmp_path)['slides'][0]['elements'] if el['type'] == 'table')
    patch = {'slideIndex': 0, 'elementId': target['id'], 'shadingColor': '#FFF2CC', 'borderPreset': 'all'}
    _invoke({'action': 'edit', 'input': str(source), 'output': str(output), 'edits': [], 'tableStyles': [patch],
             'tableCells': [{'slideIndex': 0, 'elementId': target['id'], 'row': 1, 'col': 2, 'text': 'new text'}],
             'newSlides': [{'duplicateOf': 0}], 'order': [0, 1], 'tables': [{'slideIndex': 0, 'rows': 2, 'cols': 2}]}, tmp_path)
    saved = Presentation(output)
    changed, duplicate = saved.slides[0].shapes[0].table, saved.slides[1].shapes[0].table
    assert changed.cell(0, 0).is_merge_origin and changed.cell(0, 1).is_spanned
    assert changed.cell(1, 2).text == 'new text' and duplicate.cell(1, 2).text == '1:2'
    assert str(changed.cell(1, 1).fill.fore_color.rgb) == 'FFF2CC'
    assert len(saved.slides[0].shapes) == 2
    ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    with ZipFile(output) as archive:
        doc = etree.fromstring(archive.read('ppt/slides/slide1.xml'))
    first = doc.xpath('//a:tbl', namespaces=ns)[0]
    assert len(first.xpath('.//a:tcPr/a:lnL[@w="12700"]', namespaces=ns)) == 6
    # Clear only the selected table's direct fill and borders in a fresh revision.
    cleared = tmp_path / 'style-cleared.pptx'
    refreshed = next(el for el in _invoke({'action': 'inspect', 'input': str(output)}, tmp_path)['slides'][0]['elements'] if el['type'] == 'table')
    _invoke({'action': 'edit', 'input': str(output), 'output': str(cleared), 'edits': [], 'tableStyles': [{'slideIndex': 0, 'elementId': refreshed['id'], 'shadingColor': 'none', 'borderPreset': 'none'}]}, tmp_path)
    with ZipFile(cleared) as archive:
        clear_doc = etree.fromstring(archive.read('ppt/slides/slide1.xml'))
    first_clear = clear_doc.xpath('//a:tbl', namespaces=ns)[0]
    assert len(first_clear.xpath('.//a:tcPr/a:noFill', namespaces=ns)) == 6
    assert len(first_clear.xpath('.//a:tcPr/a:lnL/a:noFill', namespaces=ns)) == 6
    assert Presentation(cleared).slides[0].shapes[0].table.cell(1, 2).text == 'new text'
    # Original copied slide retains its saved source formatting.
    assert duplicate.cell(1, 1).fill.type is None
    for index, bad in enumerate([{**patch, 'shadingColor': '#123456'}, {**patch, 'elementId': 'foreign'}, {**patch, 'borderPreset': 'diagonal'}, {**patch, 'xml': '<a:tc/>'}]):
        with pytest.raises(subprocess.CalledProcessError):
            _invoke({'action': 'edit', 'input': str(source), 'output': str(tmp_path / f'bad-style-{index}.pptx'), 'edits': [], 'tableStyles': [bad]}, tmp_path)


def _table_structure_fixture(path, rows=3, cols=3):
    from pptx.dml.color import RGBColor
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(.2), Inches(.2), Inches(3), Inches(.4)).text = 'before table'
    frame = slide.shapes.add_table(rows, cols, Inches(1), Inches(1), Inches(5), Inches(2))
    frame.name = 'Structure Target'
    table = frame.table
    for ri, row in enumerate(table.rows):
        row.height = Inches(.4 + ri * .1)
    for ci, col in enumerate(table.columns):
        col.width = Inches(1 + ci * .1)
    for ri in range(rows):
        for ci in range(cols):
            cell = table.cell(ri, ci)
            cell.text = f'R{ri}C{ci}'
            cell.margin_left = Inches(.04 + ci * .01)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor.from_string('FFF2CC' if ri % 2 else 'D6E4F0')
            cell.text_frame.paragraphs[0].runs[0].font.size = Pt(14 + ri)
            cell.text_frame.paragraphs[0].runs[0].font.bold = True
    slide.shapes.add_textbox(Inches(.2), Inches(5), Inches(4), Inches(.4)).text = 'after table'
    other = slide.shapes.add_table(2, 2, Inches(6), Inches(1), Inches(2), Inches(1)).table
    other.cell(0, 0).text = 'other table'
    presentation.slides.add_slide(presentation.slide_layouts[6])
    presentation.save(path)


@pytest.mark.parametrize(('kind', 'before'), [
    ('insert-row', True), ('insert-row', False), ('delete-row', None),
    ('insert-col', True), ('insert-col', False), ('delete-col', None),
])
def test_table_structure_six_actions_preserve_survivor_xml_and_frame_geometry(tmp_path, kind, before):
    from lxml import etree
    source, output = tmp_path / 'source.pptx', tmp_path / 'structure.pptx'
    _table_structure_fixture(source)
    inspected = _invoke({'action': 'inspect', 'input': str(source)}, tmp_path)
    target = next(el for el in inspected['slides'][0]['elements'] if el['name'] == 'Structure Target')
    assert target['tableStructureEditable'] is True
    patch = {'slideIndex': 0, 'elementId': target['id'], 'kind': kind, 'index': 1}
    if before is not None:
        patch['before'] = before
    _invoke({'action': 'edit', 'input': str(source), 'output': str(output), 'edits': [], 'tableStructures': [patch]}, tmp_path)
    original = Presentation(source).slides[0].shapes[1]
    saved = Presentation(output).slides[0].shapes[1]
    old_rows, old_cols = list(range(3)), list(range(3))
    positions = old_rows if kind.endswith('row') else old_cols
    if kind.startswith('insert-'):
        positions.insert(1 if before else 2, None)
    else:
        positions.pop(1)
    assert (len(saved.table.rows), len(saved.table.columns)) == (len(old_rows), len(old_cols))
    assert saved.shape_id == original.shape_id
    assert (saved.left, saved.top) == (original.left, original.top)
    expected_heights = [original.table.rows[i if i is not None else 1].height for i in old_rows]
    expected_widths = [original.table.columns[i if i is not None else 1].width for i in old_cols]
    assert [row.height for row in saved.table.rows] == expected_heights
    assert [col.width for col in saved.table.columns] == expected_widths
    assert saved.height == sum(expected_heights) and saved.width == sum(expected_widths)
    ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
    with ZipFile(source) as old_zip, ZipFile(output) as new_zip:
        assert {name for name in old_zip.namelist() if not name.endswith('/')} == {name for name in new_zip.namelist() if not name.endswith('/')}
        for name in old_zip.namelist():
            if name != 'ppt/slides/slide1.xml':
                assert old_zip.read(name) == new_zip.read(name), name
        old_table = etree.fromstring(old_zip.read('ppt/slides/slide1.xml')).xpath('//a:tbl', namespaces=ns)[0]
        new_table = etree.fromstring(new_zip.read('ppt/slides/slide1.xml')).xpath('//a:tbl', namespaces=ns)[0]
    for ri, source_row in enumerate(old_rows):
        for ci, source_col in enumerate(old_cols):
            actual = saved.table.cell(ri, ci)
            raw = new_table.findall('a:tr', ns)[ri].findall('a:tc', ns)[ci]
            expected_raw = old_table.findall('a:tr', ns)[source_row if source_row is not None else 1].findall('a:tc', ns)[source_col if source_col is not None else 1]
            if source_row is None or source_col is None:
                assert actual.text == ''
                assert etree.tostring(raw.find('a:tcPr', ns), method='c14n') == etree.tostring(expected_raw.find('a:tcPr', ns), method='c14n')
            else:
                assert actual.text == f'R{source_row}C{source_col}'
                assert etree.tostring(raw, method='c14n') == etree.tostring(expected_raw, method='c14n')


def test_table_structure_composes_with_copy_deletion_other_table_edits_and_insert(tmp_path):
    source, output = tmp_path / 'source.pptx', tmp_path / 'composed.pptx'
    _table_structure_fixture(source)
    model = _invoke({'action': 'inspect', 'input': str(source)}, tmp_path)
    elements = model['slides'][0]['elements']
    target = next(el for el in elements if el['name'] == 'Structure Target')
    other = [el for el in elements if el['type'] == 'table'][1]
    first = next(el for el in elements if el['text'] == 'before table')
    last = next(el for el in elements if el['text'] == 'after table')
    _invoke({'action': 'edit', 'input': str(source), 'output': str(output),
             'edits': [{'slideIndex': 0, 'elementId': last['id'], 'text': 'changed after table'}],
             'deletions': [{'slideIndex': 0, 'elementId': first['id']}],
             'tableCells': [{'slideIndex': 0, 'elementId': other['id'], 'row': 0, 'col': 0, 'text': 'other changed'}],
             'newSlides': [{'duplicateOf': 0}], 'order': [2, 0, 1],
             'tableStructures': [{'slideIndex': 0, 'elementId': target['id'], 'kind': 'insert-row', 'index': 1, 'before': False}],
             'tables': [{'slideIndex': 0, 'rows': 2, 'cols': 2}]}, tmp_path)
    result = Presentation(output)
    copied, changed = result.slides[0], result.slides[1]
    assert copied.shapes[0].text == 'before table'
    assert len(copied.shapes[1].table.rows) == 3
    assert copied.shapes[3].table.cell(0, 0).text == 'other table'
    assert changed.shapes[0].shape_id == copied.shapes[1].shape_id
    assert len(changed.shapes[0].table.rows) == 4
    assert changed.shapes[1].text == 'changed after table'
    assert changed.shapes[2].table.cell(0, 0).text == 'other changed'
    assert len(changed.shapes[3].table.rows) == 2
    fresh = _invoke({'action': 'inspect', 'input': str(output)}, tmp_path)
    assert fresh['slides'][1]['elements'][0]['tableStructureEditable'] is True


def test_table_structure_rejects_unsafe_sources_and_ambiguous_batches_without_output(tmp_path):
    from pptx.oxml.xmlchemy import OxmlElement
    from pptx.oxml.ns import qn
    source = tmp_path / 'source.pptx'
    _table_structure_fixture(source)
    model = _invoke({'action': 'inspect', 'input': str(source)}, tmp_path)
    target = next(el for el in model['slides'][0]['elements'] if el['name'] == 'Structure Target')
    op = {'slideIndex': 0, 'elementId': target['id'], 'kind': 'insert-row', 'index': 1, 'before': True}
    conflicts = [
        {'tableStructures': [op, {**op, 'kind': 'insert-col'}]},
        {'tableStructures': [op], 'tableCells': [{'slideIndex': 0, 'elementId': target['id'], 'row': 0, 'col': 0, 'text': 'ambiguous'}]},
        {'tableStructures': [op], 'tableStyles': [{'slideIndex': 0, 'elementId': target['id'], 'shadingColor': 'none'}]},
        {'tableStructures': [op], 'slideSize': {'cx': 9144000, 'cy': 6858000}},
        {'tableStructures': [op], 'resetLayouts': [0]},
        {'tableStructures': [op], 'slideLayouts': [{'slideIndex': 0, 'layoutPath': model['layouts'][0]['path']}]},
        {'tableStructures': [op], 'deletedSlides': [0], 'order': [1]},
        {'tableStructures': [{**op, 'elementId': model['slides'][0]['elements'][0]['id']}]},
        {'tableStructures': [{**op, 'index': True}]},
        {'tableStructures': [{**op, 'before': None}]},
        {'tableStructures': [{**op, 'kind': 'delete-row'}]},
        {'tableStructures': [{**op, 'extra': 1}]},
    ]
    for index, kwargs in enumerate(conflicts):
        output = tmp_path / f'rejected-{index}.pptx'
        with pytest.raises(subprocess.CalledProcessError):
            _invoke({'action': 'edit', 'input': str(source), 'output': str(output), 'edits': [], **kwargs}, tmp_path)
        assert not output.exists()
    for kind in ['merge', 'extension', 'geometry', 'zero-height', 'single-quotes']:
        original = Presentation(source)
        frame = original.slides[0].shapes[1]
        if kind == 'merge':
            frame.table.cell(0, 0).merge(frame.table.cell(0, 1))
        elif kind == 'extension':
            frame.table._tbl.append(OxmlElement('a:extLst'))
        elif kind == 'geometry':
            frame._element.xfrm.ext.set('cy', str(frame.height + 1))
        elif kind == 'zero-height':
            frame.table._tbl.findall(qn('a:tr'))[0].set('h', '0')
        path = tmp_path / f'{kind}.pptx'
        original.save(path)
        if kind == 'single-quotes':
            with ZipFile(path) as archive:
                files = {name: archive.read(name) for name in archive.namelist()}
            files['ppt/slides/slide1.xml'] = re.sub(rb'(<a:tr\s[^>]*\bh=)"(\d+)"', rb"\1'\2'", files['ppt/slides/slide1.xml'])
            with ZipFile(path, 'w') as archive:
                for name, content in files.items():
                    archive.writestr(name, content)
        inspected = _invoke({'action': 'inspect', 'input': str(path)}, tmp_path)
        unsafe = next(el for el in inspected['slides'][0]['elements'] if el['name'] == 'Structure Target')
        assert unsafe['tableStructureEditable'] is False, kind
        output = tmp_path / f'bad-{kind}.pptx'
        with pytest.raises(subprocess.CalledProcessError):
            _invoke({'action': 'edit', 'input': str(path), 'output': str(output), 'edits': [], 'tableStructures': [{**op, 'elementId': unsafe['id']}]}, tmp_path)
        assert not output.exists()


@pytest.mark.parametrize(('rows', 'cols', 'kind'), [(1, 3, 'delete-row'), (3, 1, 'delete-col'), (75, 2, 'insert-row'), (2, 75, 'insert-col')])
def test_table_structure_enforces_one_to_75_rows_and_columns(tmp_path, rows, cols, kind):
    source, output = tmp_path / 'source.pptx', tmp_path / 'bad.pptx'
    _table_structure_fixture(source, rows=rows, cols=cols)
    target = next(el for el in _invoke({'action': 'inspect', 'input': str(source)}, tmp_path)['slides'][0]['elements'] if el['name'] == 'Structure Target')
    patch = {'slideIndex': 0, 'elementId': target['id'], 'kind': kind, 'index': 0}
    if kind.startswith('insert-'):
        patch['before'] = False
    with pytest.raises(subprocess.CalledProcessError):
        _invoke({'action': 'edit', 'input': str(source), 'output': str(output), 'edits': [], 'tableStructures': [patch]}, tmp_path)
    assert not output.exists()
