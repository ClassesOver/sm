"""百分数显示必须保留百分点尺度和显式样式优先级。"""
import pytest
from openpyxl import load_workbook

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.xlsx import build_workbook


@pytest.mark.parametrize('places,negative,expected', [
    (0, 'minus', '0"%";-0"%"'),
    (3, 'parentheses', '0.000"%";(0.000"%")'),
    (1, 'red', '0.0"%";[Red]-0.0"%"'),
])
def test_actual_percent_points_keep_raw_values_and_explicit_format(tmp_path, places, negative, expected):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '编制'},
        'xlsx': {'numbers': {'percentPlaces': places, 'negativeStyle': negative}}}), 'xlsx')
    path = tmp_path / 'percent.xlsx'
    build_workbook(output_path=path, title='比例', period='2026', sheets=({'name': '数据', 'rows': [
        ['项目', '数值'], ['百分数', {'value': -12.5, 'valueType': 'percentPoints'}],
        ['未登记', 12.5], ['显式格式', {'value': .125, 'valueType': 'percentPoints', 'style': {'numberFormat': '0.0%'}}],
        ['精确文本', {'value': '12.500000000000000001', 'valueType': 'percentPoints'}],
    ]},), preferences=prefs, generated_date='2026-11-12')
    sheet = load_workbook(path)['数据']
    assert sheet['B2'].value == -12.5 and sheet['B2'].number_format == expected
    assert sheet['B3'].value == 12.5 and sheet['B3'].number_format == '#,##0.00;' + ('(#,##0.00)' if negative == 'parentheses' else ('[Red]-' if negative == 'red' else '-') + '#,##0.00')
    assert sheet['B4'].value == .125 and sheet['B4'].number_format == '0.0%'
    assert sheet['B5'].value == '12.500000000000000001'
