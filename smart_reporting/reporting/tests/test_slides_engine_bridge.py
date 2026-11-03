from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from zipfile import ZipFile

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


def test_slides_bridge_roundtrips_transition_and_adds_fade_animation(tmp_path: Path):
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
            "effect": "fade",
            "trigger": "onClick",
        }],
    }, tmp_path)
    reopened = _invoke({"action": "inspect", "input": str(output)}, tmp_path)

    slide = reopened["slides"][slide_index]
    assert slide["transition"] == "fade"
    assert any(item["effect"] == "fade" and item["trigger"] == "onClick" for item in slide["animations"])
