from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule, DataBarRule

from smart_reporting.report_editor.native_office import patch_office
from smart_reporting.reporting.delivery.xlsx import inspect_workbook


def test_native_conditional_formatting_snapshot_replaces_and_clears_without_duplicates():
    book = Workbook()
    sheet = book.active
    sheet['A1'] = 2
    sheet['B1'] = '=A1*3'
    sheet.conditional_formatting.add('A1:A3', DataBarRule(
        start_type='min', end_type='max', color='112233'))
    source = BytesIO()
    book.save(source)
    operation = {
        'kind': 'replaceSheetConditionalFormats', 'sheetName': 'Sheet',
        'rules': [{'ranges': [{'startRow': 0, 'endRow': 2, 'startColumn': 0, 'endColumn': 0}],
                   'stopIfTrue': False,
                   'rule': {'type': 'dataBar', 'isShowValue': True, 'config': {
                       'min': {'type': 'min'}, 'max': {'type': 'max'},
                       'positiveColor': '#445566'}}}],
    }
    edited = patch_office('xlsx', source.getvalue(), [operation])
    output = load_workbook(BytesIO(edited)).active
    rules = [rule for area in output.conditional_formatting for rule in output.conditional_formatting[area]]
    assert len(rules) == 1
    assert rules[0].dataBar.color.rgb == 'FF445566'
    assert output['B1'].value == '=A1*3'
    model = inspect_workbook(edited)['sheets'][0]['conditionalFormatting']
    assert model['issues'] == []
    assert len(model['rules']) == 1
    assert model['rules'][0]['rule']['config']['positiveColor'] == '#445566'
    cleared = patch_office('xlsx', edited, [{**operation, 'rules': []}])
    assert not load_workbook(BytesIO(cleared)).active.conditional_formatting
    assert inspect_workbook(cleared)['sheets'][0]['conditionalFormatting']['rules'] == []


def test_native_conditional_formatting_without_styles_preserves_missing_part():
    book = Workbook()
    book.active['A1'] = '=1+2'
    book.active.conditional_formatting.add('A1:A3', DataBarRule(
        start_type='min', end_type='max', color='FF112233'))
    source = BytesIO()
    book.save(source)
    without_styles = BytesIO()
    with ZipFile(BytesIO(source.getvalue())) as original, ZipFile(without_styles, 'w', ZIP_DEFLATED) as output:
        for name in original.namelist():
            if name != 'xl/styles.xml':
                output.writestr(name, original.read(name))
    content = without_styles.getvalue()
    model = inspect_workbook(content)['sheets'][0]
    assert model['cells']['A1']['formula'] == '=1+2'
    assert len(model['conditionalFormatting']['rules']) == 1
    cleared = patch_office('xlsx', content, [{
        'kind': 'replaceSheetConditionalFormats', 'sheetName': 'Sheet', 'rules': [],
    }])
    with ZipFile(BytesIO(cleared)) as result:
        assert 'xl/styles.xml' not in result.namelist()
    assert inspect_workbook(cleared)['sheets'][0]['conditionalFormatting']['rules'] == []


def test_native_cell_reference_condition_retains_original_xml_until_condition_changes():
    book = Workbook()
    book.active['A1'] = 2
    book.active['B1'] = 3
    book.active.conditional_formatting.add('A1:A3', CellIsRule(
        operator='greaterThan', formula=['B1'], stopIfTrue=True))
    source = BytesIO()
    book.save(source)
    content = source.getvalue()
    model = inspect_workbook(content)['sheets'][0]['conditionalFormatting']
    assert model['issues'] == []
    assert model['rules'][0]['rule']['subType'] == 'formula'
    rules = [*model['rules'], {
        'ranges': [{'startRow': 0, 'endRow': 2, 'startColumn': 2, 'endColumn': 2}],
        'stopIfTrue': False, 'rule': {'type': 'dataBar', 'isShowValue': True,
            'config': {'min': {'type': 'min'}, 'max': {'type': 'max'}, 'positiveColor': '#445566'}},
    }]
    operation = {'kind': 'replaceSheetConditionalFormats', 'sheetName': 'Sheet', 'rules': rules}
    edited = patch_office('xlsx', content, [operation])
    formatted = load_workbook(BytesIO(edited)).active.conditional_formatting
    conditions = [rule for area in formatted for rule in formatted[area]]
    assert conditions[0].type == 'cellIs'
    assert conditions[0].formula == ['B1']
    assert conditions[0].stopIfTrue is True
    changed = {**rules[0], 'rule': {**rules[0]['rule'], 'value': 'A1>10'}}
    rewritten = patch_office('xlsx', edited, [{**operation, 'rules': [changed, rules[1]]}])
    output = load_workbook(BytesIO(rewritten)).active
    first = next(iter(output.conditional_formatting))
    assert output.conditional_formatting[first][0].type == 'expression'
    assert output.conditional_formatting[first][0].formula == ['A1>10']
    assert output['B1'].value == 3
