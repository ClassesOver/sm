from io import BytesIO
import re
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from smart_reporting.report_editor.native_office import patch_office


def _source(field, formula):
    book = Workbook()
    book.active.title = 'Source'
    book.active['A1'] = 7
    other = book.create_sheet('Other')
    other['A1'] = 2
    other['B2'] = '保留内容'
    other['B2'].font = Font(bold=True, color='FF112233')
    other['B2'].fill = PatternFill('solid', fgColor='FFEECC88')
    validation = DataValidation(type='whole', operator='between', formula1='0', formula2='100')
    setattr(validation, field, formula)
    validation.add('B1:B4')
    other.add_data_validation(validation)
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def _removal():
    return {'kind': 'applySheetEdits', 'plan': {
        'renames': [], 'additions': [], 'removals': ['Source'], 'order': ['Other'],
    }}


def _assert_survivor(source, changed, replaced=False):
    output = load_workbook(BytesIO(changed))
    assert output.sheetnames == ['Other']
    assert output['Other']['A1'].value == 2
    assert output['Other']['B2'].value == '保留内容'
    assert output['Other']['B2'].font.bold is True
    assert output['Other']['B2'].font.color.rgb == 'FF112233'
    assert output['Other']['B2'].fill.fgColor.rgb == 'FFEECC88'
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(changed)) as after:
        assert after.read('xl/styles.xml') == before.read('xl/styles.xml')
        old_xml, new_xml = (archive.read('xl/worksheets/sheet2.xml') for archive in (before, after))
        if replaced:
            # 替换只允许改变 DV 区域，其余实际工作表 XML 必须完整保留。
            pattern = rb'<dataValidations\b[^>]*(?:/>|>[\s\S]*?</dataValidations>)'
            assert re.sub(pattern, b'', new_xml) == re.sub(pattern, b'', old_xml)
        else:
            assert new_xml == old_xml
        assert 'xl/worksheets/sheet1.xml' not in after.namelist()
    return output['Other']


@pytest.mark.parametrize('field', ['formula1', 'formula2'])
@pytest.mark.parametrize('formula', ['Source!A1', 'source!a1', "'SOURCE'!$a$1"])
def test_native_dv_sheet_removal_refuses_local_reference(field, formula):
    source = _source(field, formula)
    original = load_workbook(BytesIO(source))['Other'].data_validations.dataValidation[0]
    assert getattr(original, field) == formula
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        patch_office('xlsx', source, [_removal()])


@pytest.mark.parametrize('field', ['formula1', 'formula2'])
@pytest.mark.parametrize('formula', [
    'Other!A1', 'IF("Source!A1"="Source!A1",0,1)',
    '[book.xlsx]Source!A1', "'[book.xlsx]Source'!A1",
])
def test_native_dv_sheet_removal_allows_unrelated_and_external_reference(field, formula):
    source = _source(field, formula)
    changed = patch_office('xlsx', source, [_removal()])
    other = _assert_survivor(source, changed)
    assert getattr(other.data_validations.dataValidation[0], field) == formula


@pytest.mark.parametrize('field', ['formula1', 'formula2'])
@pytest.mark.parametrize('clear', [False, True])
def test_native_dv_replacement_removes_dependency_before_sheet_removal(field, clear):
    source = _source(field, 'Source!A1')
    replacement = {'ranges': [{'startRow': 0, 'endRow': 3, 'startColumn': 1, 'endColumn': 1}],
                   'rule': {'type': 'whole', 'operator': 'between', 'formula1': '0', 'formula2': '100'}}
    changed = patch_office('xlsx', source, [
        {'kind': 'replaceSheetDataValidations', 'sheetName': 'Other',
         'rules': [] if clear else [replacement]},
        _removal(),
    ])
    other = _assert_survivor(source, changed, replaced=True)
    rules = other.data_validations.dataValidation
    assert len(rules) == (0 if clear else 1)
    if not clear:
        assert (rules[0].formula1, rules[0].formula2, str(rules[0].sqref)) == ('0', '100', 'B1:B4')
