"""真实 native Python → TS engine → ZIP/openpyxl 分组协议回归。"""
from io import BytesIO
import pytest
from openpyxl import Workbook, load_workbook

def test_native_outline_roundtrip_preserves_geometry_and_other_cells():
    from smart_reporting.report_editor.native_office import patch_office
    workbook = Workbook(); sheet = workbook.active
    sheet['A2'] = '=1+2'; sheet.row_dimensions[2].height = 28
    sheet.column_dimensions['B'].width = 22
    stream = BytesIO(); workbook.save(stream)
    operation = {'kind': 'applySheetOutline', 'sheetName': 'Sheet',
                 'rows': [{'index': 1, 'level': 2, 'collapsed': False, 'hidden': True}, {'index': 2, 'level': 0, 'collapsed': True}],
                 'columns': [{'index': 1, 'level': 1, 'collapsed': False, 'hidden': True}]}
    saved = patch_office('xlsx', stream.getvalue(), [operation])
    reopened = load_workbook(BytesIO(saved)).active
    assert reopened['A2'].value == '=1+2'
    assert reopened.row_dimensions[2].height == 28
    assert reopened.row_dimensions[2].outlineLevel == 2
    assert reopened.row_dimensions[2].hidden
    assert reopened.row_dimensions[3].collapsed
    assert reopened.column_dimensions['B'].width == 22
    assert reopened.column_dimensions['B'].outlineLevel == 1
    assert reopened.column_dimensions['B'].hidden
    operation['rows'] = [{'index': 1, 'level': 0, 'collapsed': False, 'hidden': False}]
    operation['columns'] = [{'index': 1, 'level': 0, 'collapsed': False, 'hidden': False}]
    reopened = load_workbook(BytesIO(patch_office('xlsx', saved, [operation]))).active
    assert not reopened.row_dimensions[2].hidden and reopened.row_dimensions[2].outlineLevel == 0
    assert not reopened.column_dimensions['B'].hidden and reopened.column_dimensions['B'].outlineLevel == 0

@pytest.mark.parametrize('entry', [{'index': -1, 'level': 1, 'collapsed': False}, {'index': 0, 'level': 8, 'collapsed': False}, {'index': 0, 'level': 1, 'collapsed': False, 'rawXml': '<row/>'}])
def test_outline_rejects_invalid_entry_at_real_engine(entry):
    from smart_reporting.report_editor.native_office import patch_office
    stream = BytesIO(); Workbook().save(stream)
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        patch_office('xlsx', stream.getvalue(), [{'kind': 'applySheetOutline', 'sheetName': 'Sheet', 'rows': [entry], 'columns': []}])

def test_native_outline_summary_directions_roundtrip_and_strict_boolean():
    from smart_reporting.report_editor.native_office import patch_office
    workbook = Workbook(); sheet = workbook.active
    sheet.sheet_properties.outlinePr.applyStyles = True
    sheet['B2'] = 'retained'
    stream = BytesIO(); workbook.save(stream)
    operation = {'kind': 'applySheetOutline', 'sheetName': 'Sheet',
                 'summaryBelow': False, 'summaryRight': False}
    saved = patch_office('xlsx', stream.getvalue(), [operation])
    reopened = load_workbook(BytesIO(saved)).active
    assert reopened.sheet_properties.outlinePr.summaryBelow is False
    assert reopened.sheet_properties.outlinePr.summaryRight is False
    assert reopened.sheet_properties.outlinePr.applyStyles is True
    assert reopened['B2'].value == 'retained'
    operation['summaryBelow'] = '0'
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        patch_office('xlsx', saved, [operation])
