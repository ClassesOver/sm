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
    rejected = tmp_path / "rejected.pptx"
    with pytest.raises(subprocess.CalledProcessError):
        _invoke({"action": "edit", "input": str(source), "output": str(rejected), "edits": [],
                 "newSlides": [{"duplicateOf": 1}], "order": [*range(count + 1)],
                 "transitions": [{"slideIndex": 1, "kind": "fade"}]}, tmp_path)
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
