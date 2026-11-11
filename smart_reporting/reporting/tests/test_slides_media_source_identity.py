"""来源对象 ID 在版式重置、媒体编辑和复制同批操作中保持可寻址。"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

ENGINE = Path(__file__).parents[1] / 'slides_engine'


def _invoke(root: Path, **request):
    path = root / 'request.json'
    path.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
    result = subprocess.run(
        ['node', '--import', 'tsx', 'bridge/edit-pptx.ts', str(path)],
        cwd=ENGINE, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _png(color: str) -> bytes:
    stream = io.BytesIO()
    Image.new('RGB', (12, 8), color).save(stream, format='PNG')
    return stream.getvalue()


def _source(root: Path):
    source, charted = root / 'source.pptx', root / 'charted.pptx'
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    title = slide.shapes.title
    inherited_left = title.left
    title.text = '来源对象身份'
    title.left += Inches(1)
    slide.shapes.add_picture(io.BytesIO(_png('red')), Inches(1), Inches(3), width=Inches(2))
    presentation.save(source)
    _invoke(root, action='edit', input=str(source), output=str(charted), charts=[{
        'slideIndex': 0, 'kind': 'bar', 'categories': ['甲', '乙'],
        'series': [{'name': '原系列', 'values': [1, 2]}],
    }])
    elements = _invoke(root, action='inspect', input=str(charted))['slides'][0]['elements']
    picture = next(item for item in elements if item['type'] == 'picture')
    chart = next(item for item in elements if item['type'] == 'chart')
    assert picture['pictureReplaceable']
    assert chart['chartEditSafe']
    return charted, picture, chart, inherited_left


@pytest.mark.parametrize('media', ['picture', 'chart', 'both'])
def test_reset_layout_keeps_source_media_element_ids_usable(tmp_path: Path, media: str):
    source, picture, chart, inherited_left = _source(tmp_path)
    output = tmp_path / 'reset-and-edited.pptx'
    replacement = _png('blue')
    request = {'action': 'edit', 'input': str(source), 'output': str(output), 'resetLayouts': [0]}
    if media in ('picture', 'both'):
        request['pictureReplacements'] = [{
            'slideIndex': 0, 'elementId': picture['id'], 'expectedSha256': picture['pictureSha256'],
            'expectedSize': picture['pictureSize'], 'extension': 'png',
            'bytesBase64': base64.b64encode(replacement).decode('ascii'),
        }]
    if media in ('chart', 'both'):
        request['chartEdits'] = [{
            'slideIndex': 0, 'elementId': chart['id'], 'kind': 'line',
            'categories': ['一月', '二月'], 'series': [{'name': '新系列', 'values': [9, 12]}],
        }]
    _invoke(tmp_path, **request)
    reopened = Presentation(output)
    assert reopened.slides[0].shapes.title.left == inherited_left
    if media in ('picture', 'both'):
        image = next(shape for shape in reopened.slides[0].shapes if shape.shape_type == 13)
        assert hashlib.sha256(image.image.blob).digest() == hashlib.sha256(replacement).digest()
    if media in ('chart', 'both'):
        edited = next(shape.chart for shape in reopened.slides[0].shapes if shape.has_chart)
        assert [item.label for item in edited.plots[0].categories] == ['一月', '二月']
        assert list(edited.series[0].values) == [9, 12]
        assert edited.series[0].name == '新系列'
        assert int(edited.chart_type) == 65  # LINE_MARKERS，固定源 line writer。


def test_chart_edit_and_duplicate_in_one_batch_preserve_edited_chart_data(tmp_path: Path):
    source, _, chart, _ = _source(tmp_path)
    output = tmp_path / 'chart-edit-and-duplicate.pptx'
    _invoke(tmp_path, action='edit', input=str(source), output=str(output),
            chartEdits=[{'slideIndex': 0, 'elementId': chart['id'], 'categories': ['新类别'],
                         'series': [{'name': '新系列', 'values': [42]}]}],
            newSlides=[{'duplicateOf': 0}], order=[0, 1])
    reopened = Presentation(output)
    assert len(reopened.slides) == 2
    for slide in reopened.slides:
        edited = next(shape.chart for shape in slide.shapes if shape.has_chart)
        assert list(edited.series[0].values) == [42]
        assert [item.label for item in edited.plots[0].categories] == ['新类别']
