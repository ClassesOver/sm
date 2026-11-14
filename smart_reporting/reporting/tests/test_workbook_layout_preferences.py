"""实际工作簿排版不改变原值，任务明确样式继续优先。"""
from openpyxl import load_workbook

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.xlsx import build_workbook


def test_workbook_native_layout_styles_keep_values_formulas_and_signature(tmp_path):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '排版验证'}, 'xlsx': {
        'body': {'font': 'serif', 'size': 13, 'color': '#345678'},
        'header': {'font': 'sans', 'size': 15, 'bold': False},
        'alignment': 'right', 'wrapText': False, 'rowHeight': 32, 'columnWidth': 26,
    }}), 'xlsx')
    path = tmp_path / 'layout.xlsx'
    build_workbook(output_path=path, title='排版', period='2026', sheets=({'name': '数据', 'rows': [
        ['项目', '数值'], ['原值', 1234.56],
        ['显式', {'value': 2, 'formula': '=1+1', 'style': {'fontSize': 17, 'wrapText': True, 'horizontalAlignment': 'center'}}],
    ]},), preferences=prefs, generated_date='2026-11-12')
    book = load_workbook(path)
    sheet = book['数据']
    assert sheet['B2'].value == 1234.56
    assert sheet['B2'].font.name == 'Noto Serif CJK SC'
    assert sheet['B2'].font.sz == 13
    assert sheet['B2'].font.color.rgb == 'FF345678'
    assert sheet['B2'].alignment.horizontal == 'right'
    # OOXML省略wrapText即原生默认false。
    assert not sheet['B2'].alignment.wrap_text
    assert sheet['A1'].font.sz == 15 and sheet['A1'].font.bold is False
    assert sheet.row_dimensions[2].height == 32
    assert sheet.column_dimensions['A'].width == 26
    assert sheet['B3'].value == '=1+1'
    assert sheet['B3'].font.sz == 17 and sheet['B3'].alignment.wrap_text
    assert sheet['B3'].alignment.horizontal == 'center'
    assert book['说明']['A2'].value == '排版验证'
    assert book['说明']['A2'].alignment.horizontal == 'right'
    assert load_workbook(path, data_only=True)['数据']['B3'].value == 2
