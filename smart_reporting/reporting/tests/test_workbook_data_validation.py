from io import BytesIO

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.datavalidation import DataValidation

from smart_reporting.reporting.delivery.xlsx import inspect_workbook, patch_workbook
from smart_reporting.report_editor.native_office import patch_office


def test_declarative_validation_replaces_rules_and_preserves_messages():
    book = Workbook()
    sheet = book.active
    sheet.title = '明细'
    sheet['A1'] = '数量'
    old = DataValidation(type='list', formula1='"是,否"')
    old.add('B2:B5')
    sheet.add_data_validation(old)
    source = BytesIO()
    book.save(source)
    operation = {
        'kind': 'replaceSheetDataValidations', 'sheetName': '明细',
        'rules': [{'ranges': [{'startRow': 1, 'endRow': 9, 'startColumn': 0, 'endColumn': 0}],
                   'rule': {'type': 'whole', 'operator': 'greaterThan', 'formula1': '0',
                            'allowBlank': False, 'showInputMessage': True, 'promptTitle': '数量',
                            'prompt': '填写正整数', 'showErrorMessage': True, 'errorStyle': 2,
                            'errorTitle': '数量无效', 'error': '请输入大于零的整数'}}],
    }
    edited = patch_office('xlsx', source.getvalue(), [operation])
    output = load_workbook(BytesIO(edited))['明细']
    assert output['A1'].value == '数量'
    rules = output.data_validations.dataValidation
    assert len(rules) == 1
    rule = rules[0]
    assert str(rule.sqref) == 'A2:A10'
    assert (rule.type, rule.operator, rule.formula1) == ('whole', 'greaterThan', '0')
    assert rule.allowBlank is False
    assert rule.showInputMessage and rule.showErrorMessage
    assert (rule.promptTitle, rule.prompt, rule.errorTitle, rule.error, rule.errorStyle) == (
        '数量', '填写正整数', '数量无效', '请输入大于零的整数', 'warning')
    model = inspect_workbook(edited)['sheets'][0]['dataValidations']
    assert 'readOnlyReason' not in model
    assert model['rules'][0]['rule']['error'] == '请输入大于零的整数'
    cleared = patch_workbook(edited, [{**operation, 'rules': []}])
    assert not load_workbook(BytesIO(cleared))['明细'].data_validations.dataValidation


def test_declarative_validation_rejects_invalid_range():
    book = Workbook()
    source = BytesIO()
    book.save(source)
    with pytest.raises(ValueError):
        patch_workbook(source.getvalue(), [{'kind': 'replaceSheetDataValidations', 'sheetName': 'Sheet',
            'rules': [{'ranges': [{'startRow': -1, 'endRow': 1, 'startColumn': 0, 'endColumn': 0}],
                       'rule': {'type': 'whole'}}]}])
