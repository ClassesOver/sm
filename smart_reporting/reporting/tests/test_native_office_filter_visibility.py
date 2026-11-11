"""筛选条件与实际行可见性沿原生保存入口一起落盘。"""
from io import BytesIO
from unittest.mock import Mock

import pytest
from openpyxl import Workbook, load_workbook


def test_native_filter_visibility_roundtrips_and_clear_preserves_manual_hidden_row():
    from smart_reporting.report_editor.native_office import patch_office

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '数据'
    for row in [['标题', '值'], ['甲', 5], ['乙', 15], ['丙', 25]]:
        sheet.append(row)
    sheet.row_dimensions[4].hidden = True
    stream = BytesIO()
    workbook.save(stream)
    original = stream.getvalue()
    span = {'startRow': 0, 'endRow': 3, 'startColumn': 0, 'endColumn': 1}
    edited = patch_office('xlsx', original, [{
        'kind': 'applySheetFilter', 'sheetName': '数据',
        'filter': {'range': span, 'columns': [{'colId': 1, 'customs': {
            'filters': [{'val': '10', 'operator': 'greaterThan'}],
        }}]}, 'hiddenRows': [1, 3],
    }])
    result = load_workbook(BytesIO(edited)).active
    assert result.auto_filter.ref == 'A1:B4'
    assert result.auto_filter.filterColumn[0].customFilters.customFilter[0].val == '10'
    assert [result.row_dimensions[row].hidden for row in range(2, 5)] == [True, False, True]
    cleared = patch_office('xlsx', edited, [{
        'kind': 'applySheetFilter', 'sheetName': '数据', 'filter': None,
        'hiddenRows': [3], 'visibilityRange': span,
    }])
    result = load_workbook(BytesIO(cleared)).active
    assert result.auto_filter.ref is None
    assert [result.row_dimensions[row].hidden for row in range(2, 5)] == [False, False, True]
    assert list(result.values) == list(sheet.values)
    assert load_workbook(BytesIO(original)).active.auto_filter.ref is None


@pytest.mark.parametrize('operation', [
    {'kind': 'applySheetFilter', 'sheetName': '数据', 'hiddenRows': []},
    {'kind': 'applySheetFilter', 'filter': None},
    {'kind': 'applySheetFilter', 'sheetName': '数据', 'filter': None, 'unknown': []},
])
def test_native_filter_visibility_still_requires_known_fields_before_engine(monkeypatch, operation):
    from smart_reporting.report_editor import native_office

    engine = Mock(side_effect=AssertionError('invalid fields reached engine'))
    monkeypatch.setattr(native_office, 'patch_workbook', engine)
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        native_office.patch_office('xlsx', b'source', [operation])
    engine.assert_not_called()
