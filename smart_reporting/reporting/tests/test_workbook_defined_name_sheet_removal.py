from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.workbook.defined_name import DefinedName

from smart_reporting.report_editor.native_office import patch_office


def _source(scope, formula):
    book = Workbook()
    book.active.title = 'Source'
    other = book.create_sheet('Other')
    other['B2'] = '保留内容'
    other['B2'].font = Font(bold=True, color='FF112233')
    other['B2'].fill = PatternFill('solid', fgColor='FFEECC88')
    name = DefinedName('Dependency', attr_text=formula)
    (book.defined_names if scope is None else book[scope].defined_names).add(name)
    # 同名但不同 scope 的安全名称不得被另一个 scope 的更新/移除误删。
    safe_scope = 'Other' if scope is None else None
    (book.defined_names if safe_scope is None else book[safe_scope].defined_names).add(
        DefinedName('Dependency', attr_text='42'))
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def _removal():
    return {'kind': 'applySheetEdits', 'plan': {
        'renames': [], 'additions': [], 'removals': ['Source'], 'order': ['Other'],
    }}


def _assert_survivor(source, changed):
    book = load_workbook(BytesIO(changed))
    assert book.sheetnames == ['Other']
    assert book['Other']['B2'].value == '保留内容'
    assert book['Other']['B2'].font.bold is True
    assert book['Other']['B2'].font.color.rgb == 'FF112233'
    assert book['Other']['B2'].fill.fgColor.rgb == 'FFEECC88'
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(changed)) as after:
        for path in ['xl/worksheets/sheet2.xml', 'xl/styles.xml']:
            assert after.read(path) == before.read(path)
    return book


@pytest.mark.parametrize('scope', [None, 'Other'])
@pytest.mark.parametrize('formula', ['Source!$A$1', 'source!a1', "'SOURCE'!$a$1"])
def test_native_defined_name_surviving_scope_refuses_sheet_removal(scope, formula):
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        patch_office('xlsx', _source(scope, formula), [_removal()])


def test_native_defined_name_removed_scope_is_discarded_with_sheet():
    source = _source('Source', 'Source!$A$1')
    changed = patch_office('xlsx', source, [_removal()])
    book = _assert_survivor(source, changed)
    assert book.defined_names['Dependency'].attr_text == '42'
    assert not book['Other'].defined_names
    with ZipFile(BytesIO(changed)) as archive:
        assert b'localSheetId=' not in archive.read('xl/workbook.xml')


@pytest.mark.parametrize('scope', [None, 'Other'])
@pytest.mark.parametrize('formula', [
    'Other!$B$2', '"Source!A1"', '[book.xlsx]Source!A1', "'[book.xlsx]Source'!A1",
])
def test_native_defined_name_literal_external_and_unrelated_allow_sheet_removal(scope, formula):
    source = _source(scope, formula)
    book = _assert_survivor(source, patch_office('xlsx', source, [_removal()]))
    target = book.defined_names if scope is None else book[scope].defined_names
    safe = book['Other'].defined_names if scope is None else book.defined_names
    assert target['Dependency'].attr_text == formula
    assert safe['Dependency'].attr_text == '42'


@pytest.mark.parametrize('scope', [None, 'Other'])
@pytest.mark.parametrize('clear', [False, True])
def test_native_defined_name_change_precedes_sheet_removal_without_cross_scope_loss(scope, clear):
    source = _source(scope, 'Source!$A$1')
    entry = {'name': 'Dependency', **({'scopeSheetName': scope} if scope else {})}
    plan = {'removes': [entry if scope else 'Dependency']} if clear else {
        'sets': [{**entry, 'refersTo': 'Other!$B$2'}]}
    changed = patch_office('xlsx', source, [
        {'kind': 'applyDefinedNames', 'plan': plan}, _removal(),
    ])
    book = _assert_survivor(source, changed)
    target = book.defined_names if scope is None else book[scope].defined_names
    safe = book['Other'].defined_names if scope is None else book.defined_names
    assert safe['Dependency'].attr_text == '42'
    if clear:
        assert 'Dependency' not in target
    else:
        assert target['Dependency'].attr_text == 'Other!$B$2'
