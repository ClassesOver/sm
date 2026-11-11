"""配色及样式预设字段通过协议，并写入原生图表而非静态图片。"""
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


@pytest.mark.parametrize('patch', [
    {'colorScheme': 'default'}, {'colorScheme': 'colorful'}, {'colorScheme': 'colorful2'},
    *[{'colorScheme': f'mono-accent{i}'} for i in range(1, 7)],
    *[{'colorScheme': key} for key in ['blue', 'warm', 'cool', 'mono']],
    {'gapWidthPct': 0}, {'gapWidthPct': 50}, {'gapWidthPct': 500},
])
def test_native_chart_design_protocol_accepts_fixed_palette_and_gap(patch):
    record = {'slideIndex': 0, 'elementId': 'chart', **patch}
    assert _pptx_arguments({'kind': 'editSlides', 'chartEdits': [record]})['chart_edits'] == [record]


@pytest.mark.parametrize('patch', [
    {'colorScheme': None}, {'colorScheme': []}, {'colorScheme': '#123456'},
    {'colorScheme': ''}, {'colorScheme': 'mono-accent7'},
    {'gapWidthPct': None}, {'gapWidthPct': True}, {'gapWidthPct': -1},
    {'gapWidthPct': 501}, {'gapWidthPct': 50.5}, {'gapWidthPct': '50'},
])
def test_native_chart_design_protocol_rejects_invalid_values(patch):
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', 'chartEdits': [
            {'slideIndex': 0, 'elementId': 'chart', **patch},
        ]})


def test_chart_design_file_roundtrip_preserves_data_and_unrelated_parts(tmp_path):
    deck = Presentation()
    deck.slides.add_slide(deck.slide_layouts[6])
    stream = BytesIO()
    deck.save(stream)
    source = patch_office('pptx', stream.getvalue(), [{'kind': 'editSlides', 'charts': [{
        'slideIndex': 0, 'kind': 'barH', 'categories': ['甲', '乙'],
        'series': [{'name': '收入', 'values': [1, 2]}, {'name': '成本', 'values': [3, 4]}],
    }]}])
    target = next(e for e in inspect_office('pptx', source)['slides'][0]['elements'] if e['type'] == 'chart')
    edited = patch_office('pptx', source, [{'kind': 'editSlides', 'chartEdits': [{
        'slideIndex': 0, 'elementId': target['id'], 'colorScheme': 'warm', 'gapWidthPct': 50,
        'legendPos': 'b', 'dataLabels': True, 'gridlines': True, 'title': '收入与成本',
    }]}])
    state = next(e for e in inspect_office('pptx', edited)['slides'][0]['elements'] if e['type'] == 'chart')
    assert state['chartKind'] == 'barH'
    assert state['chartCategories'] == ['甲', '乙']
    assert state['chartSeries'] == target['chartSeries']
    assert state['chartGapWidthPct'] == 50
    native = next(s.chart for s in Presentation(BytesIO(edited)).slides[0].shapes if s.has_chart)
    assert native.chart_title.text_frame.text == '收入与成本'
    assert [str(s.format.fill.fore_color.rgb) for s in native.series] == ['ED7D31', 'FFC000']
    assert native.plots[0].gap_width == 50
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(edited)) as after:
        changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
        assert changed and all(name.startswith(('ppt/charts/', 'ppt/embeddings/')) for name in changed)
    # Theme Default clears explicit series colors; it is not a no-op that retains warm.
    reset = patch_office('pptx', edited, [{'kind': 'editSlides', 'chartEdits': [{
        'slideIndex': 0, 'elementId': state['id'], 'colorScheme': 'default',
    }]}])
    with ZipFile(BytesIO(reset)) as archive:
        path = next(name for name in archive.namelist() if name.startswith('ppt/charts/chart') and name.endswith('.xml'))
        xml = etree.fromstring(archive.read(path))
        ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
        assert not xml.xpath('//c:ser/c:spPr', namespaces=ns)
    (tmp_path / 'source.pptx').write_bytes(source)
    (tmp_path / 'warm.pptx').write_bytes(edited)
    (tmp_path / 'default.pptx').write_bytes(reset)
