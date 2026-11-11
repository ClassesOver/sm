"""已有安全图表的格式字段通过原生协议，并在真实文件中保留数据。"""
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

STYLE = {
    'title': '收入与成本😀 <&>',
    'catAxisTitle': '月份',
    'valAxisTitle': '万元',
    'legendPos': 'r',
    'dataLabels': True,
    'gridlines': False,
}


def test_chart_style_only_patch_uses_existing_native_operation():
    record = {'slideIndex': 0, 'elementId': 'chart-1', **STYLE}
    assert _pptx_arguments({'kind': 'editSlides', 'chartEdits': [record]})['chart_edits'] == [record]


@pytest.mark.parametrize('patch', [
    {'title': None}, {'title': 3}, {'title': '字' * 1001}, {'title': '\x00'},
    {'title': '\ud800'}, {'catAxisTitle': []}, {'valAxisTitle': '\ufffe'},
    {'legendPos': 'tr'}, {'legendPos': None}, {'dataLabels': 1},
    {'gridlines': 'false'}, {'gridlines': None}, {'unknownStyle': True},
])
def test_invalid_chart_style_rejected_before_engine(patch):
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', 'chartEdits': [
            {'slideIndex': 0, 'elementId': 'chart-1', **patch},
        ]})


def test_false_empty_and_unicode_style_values_are_explicit():
    for patch in [{'title': '', 'catAxisTitle': '', 'valAxisTitle': ''},
                  {'legendPos': 'none', 'dataLabels': False, 'gridlines': False},
                  {'title': '😀' * 1000}]:
        record = {'slideIndex': 0, 'elementId': 'chart-1', **patch}
        assert _pptx_arguments({'kind': 'editSlides', 'chartEdits': [record]})['chart_edits'] == [record]


def test_chart_style_save_reopen_preserves_data_and_unrelated_parts(tmp_path):
    deck = Presentation()
    deck.slides.add_slide(deck.slide_layouts[6])
    stream = BytesIO()
    deck.save(stream)
    source = patch_office('pptx', stream.getvalue(), [{'kind': 'editSlides', 'charts': [{
        'slideIndex': 0, 'kind': 'barH', 'categories': ['一月', '二月'],
        'series': [{'name': '收入', 'values': [42, 17]}],
    }]}])
    target = next(e for e in inspect_office('pptx', source)['slides'][0]['elements'] if e['type'] == 'chart')
    edited = patch_office('pptx', source, [{'kind': 'editSlides', 'chartEdits': [
        {'slideIndex': 0, 'elementId': target['id'], **STYLE},
    ]}])
    state = next(e for e in inspect_office('pptx', edited)['slides'][0]['elements'] if e['type'] == 'chart')
    assert state['chartStyle'] == STYLE
    assert state['chartKind'] == 'barH'
    assert state['chartCategories'] == ['一月', '二月']
    assert state['chartSeries'] == [{'name': '收入', 'values': [42, 17]}]
    native = next(s.chart for s in Presentation(BytesIO(edited)).slides[0].shapes if s.has_chart)
    assert native.chart_title.text_frame.text == STYLE['title']
    assert native.category_axis.axis_title.text_frame.text == '月份'
    assert native.value_axis.axis_title.text_frame.text == '万元'
    assert native.has_legend and native.plots[0].has_data_labels
    assert not native.value_axis.has_major_gridlines
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(edited)) as after:
        changed = [p for p in before.namelist() if before.read(p) != after.read(p)]
        assert changed and all(p.startswith(('ppt/charts/', 'ppt/embeddings/')) for p in changed)
        chart_path = next(p for p in after.namelist() if p.startswith('ppt/charts/chart') and p.endswith('.xml'))
        xml = etree.fromstring(after.read(chart_path))
        ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
        assert xml.xpath('string(//c:legendPos/@val)', namespaces=ns) == 'r'
    cleared = patch_office('pptx', edited, [{'kind': 'editSlides', 'chartEdits': [{
        'slideIndex': 0, 'elementId': state['id'], 'title': '', 'catAxisTitle': '',
        'valAxisTitle': '', 'legendPos': 'none', 'dataLabels': False, 'gridlines': True,
    }]}])
    native = next(s.chart for s in Presentation(BytesIO(cleared)).slides[0].shapes if s.has_chart)
    assert not native.has_title and not native.has_legend
    assert not native.category_axis.has_title and not native.value_axis.has_title
    assert not native.plots[0].has_data_labels and native.value_axis.has_major_gridlines
    (tmp_path / 'source.pptx').write_bytes(source)
    (tmp_path / 'styled.pptx').write_bytes(edited)
    (tmp_path / 'cleared.pptx').write_bytes(cleared)
