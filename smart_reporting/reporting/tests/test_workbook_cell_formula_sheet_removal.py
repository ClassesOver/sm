from io import BytesIO
import re
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from smart_reporting.report_editor.native_office import patch_office


def _source(formula, address='C1', hidden=False, shared=False):
    book = Workbook()
    book.active.title = 'Source'
    book.active['A1'] = 7
    other = book.create_sheet('Other')
    other.sheet_state = 'hidden' if hidden else 'visible'
    other['B2'] = '保留内容'
    other['B2'].font = Font(bold=True, color='FF112233')
    other['B2'].fill = PatternFill('solid', fgColor='FFEECC88')
    other[address] = '=' + formula
    if shared:
        other['C2'] = '=Source!A2'
    stream = BytesIO()
    book.save(stream)
    content = stream.getvalue()
    if not shared:
        return content
    output = BytesIO()
    with ZipFile(BytesIO(content)) as before, ZipFile(output, 'w', ZIP_DEFLATED) as after:
        for entry in before.infolist():
            data = before.read(entry.filename)
            if entry.filename == 'xl/worksheets/sheet2.xml':
                data = data.replace(b'<f>Source!A1</f>', b'<f t="shared" si="0" ref="C1:C2">Source!A1</f>')
                data = data.replace(b'<f>Source!A2</f>', b'<f t="shared" si="0"/>')
            after.writestr(entry, data)
    return output.getvalue()


def _removal():
    return {'kind': 'applySheetEdits', 'plan': {
        'renames': [], 'additions': [], 'removals': ['Source'], 'order': ['Other'],
    }}


@pytest.mark.parametrize('formula,address,hidden,shared', [
    ('Source!A1', 'C1', False, False),
    ('source!a1', 'C1', False, False),
    ("'SOURCE'!$a$1", 'C1', False, False),
    ('Source!A1', 'C1', True, False),
    ('Source!A1', 'XFD1048576', False, False),
    ('Source!A1', 'C1', False, True),
])
def test_native_cell_formula_reference_refuses_sheet_removal(formula, address, hidden, shared):
    source = _source(formula, address, hidden, shared)
    original = load_workbook(BytesIO(source))
    assert original['Other'][address].value == '=' + formula
    if shared:
        assert original['Other']['C2'].value == '=Source!A2'
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        patch_office('xlsx', source, [_removal()])


@pytest.mark.parametrize('formula', [
    'Other!A1', 'IF("Source!A1"="Source!A1",0,1)',
    '[book.xlsx]Source!A1', "'[book.xlsx]Source'!A1",
])
def test_native_cell_formula_unrelated_reference_allows_sheet_removal(formula):
    source = _source(formula)
    changed = patch_office('xlsx', source, [_removal()])
    output = load_workbook(BytesIO(changed))
    assert output.sheetnames == ['Other']
    assert output['Other']['C1'].value == '=' + formula
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(changed)) as after:
        for path in ['xl/styles.xml', 'xl/worksheets/sheet2.xml']:
            assert after.read(path) == before.read(path)


def test_native_cell_edit_removes_reference_before_sheet_removal():
    source = _source('Source!A1')
    changed = patch_office('xlsx', source, [
        {'kind': 'applyCellEdits', 'edits': [{'sheetName': 'Other', 'row': 0, 'column': 2,
          'writeValue': True, 'cell': {'value': '解除依赖'}}]},
        _removal(),
    ])
    output = load_workbook(BytesIO(changed))
    assert output.sheetnames == ['Other']
    assert output['Other']['C1'].value == '解除依赖'
    assert output['Other']['B2'].value == '保留内容'
    assert output['Other']['B2'].font.bold is True
    assert output['Other']['B2'].font.color.rgb == 'FF112233'
    assert output['Other']['B2'].fill.fgColor.rgb == 'FFEECC88'
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(changed)) as after:
        assert after.read('xl/styles.xml') == before.read('xl/styles.xml')
        pattern = rb'<c\b[^>]*\br="C1"[^>]*(?:/>|>[\s\S]*?</c>)'
        assert re.sub(pattern, b'', after.read('xl/worksheets/sheet2.xml')) == re.sub(
            pattern, b'', before.read('xl/worksheets/sheet2.xml'))
