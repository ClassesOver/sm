from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.formatting.rule import DataBarRule
from openpyxl.formatting.rule import ColorScaleRule, IconSetRule
from openpyxl.styles import Font, PatternFill

from smart_reporting.report_editor.native_office import patch_office


def test_cross_sheet_conditional_formula_splits_without_moving_host_or_priority():
    book = Workbook()
    book.active.title = 'Source'
    book.active['A1'] = 1
    book.active['A2'] = 2
    other = book.create_sheet('Other')
    other['B1'] = 'keep'
    other.conditional_formatting.add('B1:B4', FormulaRule(formula=['TRUE'], stopIfTrue=True))
    other.conditional_formatting.add('B1:B4', FormulaRule(formula=['Source!A1>0']))
    stream = BytesIO()
    book.save(stream)
    changed = patch_office('xlsx', stream.getvalue(), [{
        'kind': 'applyRowColumnOps', 'sheetName': 'Source',
        'ops': [{'kind': 'insert-rows', 'index': 1, 'count': 1}],
    }])
    output = load_workbook(BytesIO(changed))
    rules = sorted((rule.priority, str(area.sqref), rule.formula, rule.stopIfTrue)
                   for area in output['Other'].conditional_formatting
                   for rule in output['Other'].conditional_formatting[area])
    assert rules == [
        (1, 'B1:B4', ['TRUE'], True),
        (2, 'B1', ['Source!A1>0'], None),
        (3, 'B2:B4', ['Source!A3>0'], None),
    ]
    assert output['Other']['B1'].value == 'keep'
    assert output['Source']['A2'].value is None
    assert output['Source']['A3'].value == 2


def test_cross_sheet_conditional_formula_deletion_retains_ref_error_partition():
    book = Workbook()
    book.active.title = 'Source'
    for row in range(1, 5):
        book.active.cell(row, 1, row)
    other = book.create_sheet('Other')
    other['B2'] = 'host stays'
    other.conditional_formatting.add('B1:B4', FormulaRule(formula=['Source!A1>0']))
    stream = BytesIO()
    book.save(stream)
    changed = patch_office('xlsx', stream.getvalue(), [{
        'kind': 'applyRowColumnOps', 'sheetName': 'Source',
        'ops': [{'kind': 'delete-rows', 'index': 1, 'count': 1}],
    }])
    output = load_workbook(BytesIO(changed))
    rules = sorted((rule.priority, str(area.sqref), rule.formula)
                   for area in output['Other'].conditional_formatting
                   for rule in output['Other'].conditional_formatting[area])
    assert rules == [
        (1, 'B1', ['Source!A1>0']),
        (2, 'B2', ['Source!#REF!>0']),
        (3, 'B3:B4', ['Source!A2>0']),
    ]
    assert output['Other']['B2'].value == 'host stays'
    assert output['Source']['A2'].value == 3


def _sheet_removal_threshold_book(kind, formula):
    book = Workbook()
    book.active.title = 'Source'
    book.active['A1'] = 7
    other = book.create_sheet('Other')
    other['A1'] = 2
    other['B2'] = 'host stays'
    other['B2'].font = Font(bold=True, color='FF112233')
    other['B2'].fill = PatternFill('solid', fgColor='FFEECC88')
    other.conditional_formatting.add('B1:B4', FormulaRule(
        formula=['TRUE'], stopIfTrue=True, fill=PatternFill('solid', fgColor='FFFF0000')))
    if kind == 'dataBar':
        rule = DataBarRule(start_type='formula', start_value=formula,
                           end_type='num', end_value=100, color='FF638EC6')
    elif kind == 'colorScale':
        rule = ColorScaleRule(start_type='formula', start_value=formula,
                              start_color='FFFF0000', end_type='max', end_color='FF00FF00')
    else:
        rule = IconSetRule('3TrafficLights1', 'formula', ['0', formula, '100'])
    other.conditional_formatting.add('C1:C4', rule)
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def _remove_source_operation():
    return {'kind': 'applySheetEdits', 'plan': {
        'renames': [], 'additions': [], 'removals': ['Source'], 'order': ['Other'],
    }}


@pytest.mark.parametrize('kind', ['dataBar', 'colorScale', 'iconSet'])
@pytest.mark.parametrize('formula', ['Source!A1', 'source!a1', "'SOURCE'!$a$1"])
def test_native_sheet_removal_refuses_conditional_formula_threshold(kind, formula):
    source = _sheet_removal_threshold_book(kind, formula)
    # 重新读取真实 openpyxl cfvo，确认原始文件确实包含待验证的阈值引用。
    original = load_workbook(BytesIO(source))
    rules = [rule for area in original['Other'].conditional_formatting
             for rule in original['Other'].conditional_formatting[area]]
    assert rules[1].type == kind
    assert formula in [value.val for value in getattr(rules[1], kind).cfvo]
    with pytest.raises(ValueError, match='native_office_operations_invalid'):
        patch_office('xlsx', source, [_remove_source_operation()])


@pytest.mark.parametrize('kind', ['dataBar', 'colorScale', 'iconSet'])
@pytest.mark.parametrize('formula', [
    'Other!A1', 'IF("Source!A1"="Source!A1",0,1)',
    '[book.xlsx]Source!A1', "'[book.xlsx]Source'!A1",
])
def test_native_sheet_removal_allows_unrelated_threshold_and_preserves_survivor(kind, formula):
    source = _sheet_removal_threshold_book(kind, formula)
    changed = patch_office('xlsx', source, [_remove_source_operation()])
    output = load_workbook(BytesIO(changed))
    assert output.sheetnames == ['Other']
    assert output['Other']['A1'].value == 2
    assert output['Other']['B2'].value == 'host stays'
    assert output['Other']['B2'].font.bold is True
    assert output['Other']['B2'].font.color.rgb == 'FF112233'
    assert output['Other']['B2'].fill.fgColor.rgb == 'FFEECC88'
    rules = sorted((rule.priority, rule) for area in output['Other'].conditional_formatting
                   for rule in output['Other'].conditional_formatting[area])
    assert [(priority, rule.type) for priority, rule in rules] == [(1, 'expression'), (2, kind)]
    assert rules[0][1].stopIfTrue is True
    assert formula in [value.val for value in getattr(rules[1][1], kind).cfvo]
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(changed)) as after:
        for path in ['xl/worksheets/sheet2.xml', 'xl/styles.xml']:
            assert after.read(path) == before.read(path)
        assert 'xl/worksheets/sheet1.xml' not in after.namelist()


def test_sheet_rename_updates_case_insensitive_cf_references_and_formula_thresholds():
    book = Workbook()
    book.active.title = 'Source'
    book.active['A1'] = 7
    other = book.create_sheet('Other')
    other.conditional_formatting.add('B1:B4', FormulaRule(formula=['TRUE'], stopIfTrue=True))
    other.conditional_formatting.add('B1:B4', FormulaRule(formula=['IF(source!a1>0,"Source!A1",0)>0']))
    other.conditional_formatting.add('C1:C4', DataBarRule(
        start_type='formula', start_value='SOURCE!a1', end_type='num', end_value=100, color='FF638EC6'))
    stream = BytesIO()
    book.save(stream)
    name = "财务 O'Brien"
    changed = patch_office('xlsx', stream.getvalue(), [{
        'kind': 'applySheetEdits', 'plan': {
            'renames': [{'sheetName': 'Source', 'newName': name}],
            'additions': [], 'removals': [], 'order': [name, 'Other'],
        },
    }])
    output = load_workbook(BytesIO(changed))
    rules = sorted((rule.priority, rule) for area in output['Other'].conditional_formatting
                   for rule in output['Other'].conditional_formatting[area])
    assert rules[0][1].stopIfTrue is True
    assert rules[1][1].formula == ['IF(\'财务 O\'\'Brien\'!a1>0,"Source!A1",0)>0']
    assert rules[2][1].dataBar.cfvo[0].val == "'财务 O''Brien'!a1"
    assert output[name]['A1'].value == 7


@pytest.mark.parametrize('shift,own_range,dependent', [
    ('down', 'A1 A3:A5', [('B1', 'Source!A1>0'), ('B2:B4', 'Source!A3>0')]),
    ('up', 'A1:A3', [('B1', 'Source!A1>0'), ('B2', 'Source!#REF!>0'),
                      ('B3:B4', 'Source!A2>0')]),
])
def test_cell_shift_preserves_own_scope_gap_and_cross_sheet_priority(shift, own_range, dependent):
    book = Workbook()
    source = book.active
    source.title = 'Source'
    for row in range(1, 5):
        source.cell(row, 1, row)
    source['B2'] = 'outside band'
    source.conditional_formatting.add('A1:A4', FormulaRule(formula=['TRUE']))
    other = book.create_sheet('Other')
    other['B2'] = 'host stays'
    other.conditional_formatting.add('B1:B4', FormulaRule(formula=['TRUE'], stopIfTrue=True))
    other.conditional_formatting.add('B1:B4', FormulaRule(formula=['Source!A1>0']))
    stream = BytesIO()
    book.save(stream)
    changed = patch_office('xlsx', stream.getvalue(), [{
        'kind': 'applyCellShift', 'sheetName': 'Source', 'range': 'A2', 'shift': shift,
    }])
    output = load_workbook(BytesIO(changed))
    assert [str(area.sqref) for area in output['Source'].conditional_formatting] == [own_range]
    rules = sorted((rule.priority, str(area.sqref), rule.formula[0], rule.stopIfTrue is True)
                   for area in output['Other'].conditional_formatting
                   for rule in output['Other'].conditional_formatting[area])
    assert rules == [(1, 'B1:B4', 'TRUE', True)] + [
        (index + 2, area, formula, False) for index, (area, formula) in enumerate(dependent)
    ]
    assert output['Source']['A2'].value == (None if shift == 'down' else 3)
    assert output['Source']['B2'].value == 'outside band'
    assert output['Other']['B2'].value == 'host stays'
