"""交换行列沿用原生图表引擎，保存后的数据缓存与工作簿一致。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from pptx import Presentation

from smart_reporting.report_editor.native_office import (
    _pptx_arguments,
    inspect_office,
    patch_office,
)


@pytest.mark.parametrize('value', [True, False])
def test_switch_row_col_is_an_explicit_boolean_native_patch(value):
    record = {'slideIndex': 0, 'elementId': 'chart', 'switchRowCol': value}
    assert _pptx_arguments({'kind': 'editSlides', 'chartEdits': [record]})['chart_edits'] == [record]


@pytest.mark.parametrize('value', [None, 0, 1, 'true', [], {}])
def test_switch_row_col_rejects_non_boolean(value):
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', 'chartEdits': [
            {'slideIndex': 0, 'elementId': 'chart', 'switchRowCol': value},
        ]})


def test_switch_row_col_save_reopen_and_followup_data_edit(tmp_path):
    presentation = Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[6])
    stream = BytesIO()
    presentation.save(stream)
    source = patch_office('pptx', stream.getvalue(), [{'kind': 'editSlides', 'charts': [{
        'slideIndex': 0, 'kind': 'barH', 'categories': ['一月', '二月', '三月'],
        'series': [{'name': '收入', 'values': [1, 2, 3]}, {'name': '成本', 'values': [4, 5, 6]}],
    }]}])
    target = next(e for e in inspect_office('pptx', source)['slides'][0]['elements'] if e['type'] == 'chart')
    # Explicit data in chartEdits is always the final, visible orientation.
    categories = ['收入', '成本']
    series = [{'name': '一月', 'values': [99, 4]}, {'name': '二月', 'values': [2, 5]}, {'name': '三月', 'values': [3, 6]}]
    edited = patch_office('pptx', source, [{'kind': 'editSlides', 'chartEdits': [{
        'slideIndex': 0, 'elementId': target['id'], 'switchRowCol': True,
        'categories': categories, 'series': series, 'title': '交换后的标题', 'legendPos': 't',
    }]}])
    state = next(e for e in inspect_office('pptx', edited)['slides'][0]['elements'] if e['type'] == 'chart')
    assert state['chartKind'] == 'barH'
    assert state['chartCategories'] == categories
    assert state['chartSeries'] == series
    native = next(s.chart for s in Presentation(BytesIO(edited)).slides[0].shapes if s.has_chart)
    assert native.chart_title.text_frame.text == '交换后的标题'
    assert [c.label for c in native.plots[0].categories] == categories
    assert [list(s.values) for s in native.series] == [[99, 4], [2, 5], [3, 6]]
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(edited)) as after:
        changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
        assert changed and all(name.startswith(('ppt/charts/', 'ppt/embeddings/')) for name in changed)
        workbook_path = next(name for name in after.namelist() if name.startswith('ppt/embeddings/') and name.endswith('.xlsx'))
        workbook = load_workbook(BytesIO(after.read(workbook_path)), data_only=True)
        assert list(workbook.active.values) == [
            ('', '一月', '二月', '三月'), ('收入', 99, 2, 3), ('成本', 4, 5, 6),
        ]
    swapped_back = patch_office('pptx', edited, [{'kind': 'editSlides', 'chartEdits': [{
        'slideIndex': 0, 'elementId': state['id'], 'switchRowCol': True,
    }]}])
    back = next(e for e in inspect_office('pptx', swapped_back)['slides'][0]['elements'] if e['type'] == 'chart')
    assert back['chartCategories'] == ['一月', '二月', '三月']
    assert back['chartSeries'] == [{'name': '收入', 'values': [99, 2, 3]}, {'name': '成本', 'values': [4, 5, 6]}]
    (tmp_path / 'source.pptx').write_bytes(source)
    (tmp_path / 'swapped.pptx').write_bytes(edited)
