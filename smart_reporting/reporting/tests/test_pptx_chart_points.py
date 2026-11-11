"""单点颜色使用最终可见行列，写入原生图表且支持清除覆盖。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from lxml import etree
from pptx import Presentation

from smart_reporting.report_editor.native_office import (
    _pptx_arguments,
    inspect_office,
    patch_office,
)


@pytest.mark.parametrize('points', [{'0': {'0': '#123aBc'}}, {'19': {'99': None}}])
def test_point_color_protocol_accepts_sparse_colors_and_explicit_reset(points):
    item = {'slideIndex': 0, 'elementId': 'chart', 'pointColors': points}
    assert _pptx_arguments({'kind': 'editSlides', 'chartEdits': [item]})['chart_edits'] == [item]


@pytest.mark.parametrize('points', [
    None, [], {}, {'0': {}}, {'0': []}, {'-1': {'0': '#123456'}},
    {'01': {'0': '#123456'}}, {'20': {'0': '#123456'}}, {'0': {'100': '#123456'}},
    {'0': {'0': 'red'}}, {'0': {'0': '#FFF'}}, {'0': {'0': True}}, {'0': {'0': 0}},
    {'1١': {'0': '#123456'}}, {'0': {'1١': '#123456'}},
])
def test_point_color_protocol_rejects_invalid_shape_indices_and_values(points):
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', 'chartEdits': [{
            'slideIndex': 0, 'elementId': 'chart', 'pointColors': points,
        }]})


def test_point_color_file_roundtrip_and_reset_after_swap():
    deck = Presentation()
    deck.slides.add_slide(deck.slide_layouts[6])
    stream = BytesIO()
    deck.save(stream)
    source = patch_office('pptx', stream.getvalue(), [{'kind': 'editSlides', 'charts': [{
        'slideIndex': 0, 'kind': 'barH', 'categories': ['甲', '乙'],
        'series': [{'name': '收入', 'values': [1, 2]}],
    }]}])
    chart = next(e for e in inspect_office('pptx', source)['slides'][0]['elements'] if e['type'] == 'chart')
    edited = patch_office('pptx', source, [{'kind': 'editSlides', 'chartEdits': [{
        'slideIndex': 0, 'elementId': chart['id'], 'switchRowCol': True,
        'pointColors': {'1': {'0': '#123ABC'}}, 'colorScheme': 'warm',
    }]}])
    state = next(e for e in inspect_office('pptx', edited)['slides'][0]['elements'] if e['type'] == 'chart')
    assert state['chartCategories'] == ['收入']
    assert state['chartSeries'] == [{'name': '甲', 'values': [1]}, {'name': '乙', 'values': [2]}]
    assert state['chartPointColors'] == [[None], ['#123ABC']]
    native = next(s.chart for s in Presentation(BytesIO(edited)).slides[0].shapes if s.has_chart)
    assert str(native.series[1].points[0].format.fill.fore_color.rgb) == '123ABC'
    reset = patch_office('pptx', edited, [{'kind': 'editSlides', 'chartEdits': [{
        'slideIndex': 0, 'elementId': state['id'], 'pointColors': {'1': {'0': None}},
    }]}])
    with ZipFile(BytesIO(edited)) as before, ZipFile(BytesIO(reset)) as after:
        changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
        assert changed and all(name.startswith(('ppt/charts/', 'ppt/embeddings/')) for name in changed)
        path = next(name for name in after.namelist() if name.startswith('ppt/charts/chart') and name.endswith('.xml'))
        xml = etree.fromstring(after.read(path))
        assert not xml.xpath('//*[local-name()="dPt"]')
    back = next(e for e in inspect_office('pptx', reset)['slides'][0]['elements'] if e['type'] == 'chart')
    assert back['chartPointColors'] == [[None], [None]]
    assert back['chartSeries'] == state['chartSeries']
