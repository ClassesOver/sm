"""只按登记日期类型格式化，不凭外观猜测日期或编号。"""
from datetime import datetime

import pytest
from openpyxl import load_workbook

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.xlsx import build_workbook, inspect_workbook
from smart_reporting.reporting.workflow.runtime.workbook import workbook_dataset_rows


def test_registered_date_columns_preserve_invalid_ambiguous_and_text_values():
    columns, rows, issues = workbook_dataset_rows(
        b'day,code,ambiguous\n2026-11-12,2026-11-12,2026-11-12\n2026-02-30,001,2026-11-13\n',
        dataset_id='d1', measures=set(), schema={'tables': [{'columns': [
            {'name': 'day', 'dataType': 'DATE'}, {'name': 'code', 'dataType': 'VARCHAR'},
            {'name': 'ambiguous', 'dataType': 'DATE'}]}, {'columns': [
                {'name': 'ambiguous', 'dataType': 'VARCHAR'}]}]})
    assert columns == ['day', 'code', 'ambiguous']
    assert rows[0] == [{'value': '2026-11-12', 'valueType': 'date'}, '2026-11-12', '2026-11-12']
    assert rows[1] == ['2026-02-30', '001', '2026-11-13']
    assert [issue['code'] for issue in issues] == ['xlsx_date_value_invalid']


@pytest.mark.parametrize('date_format,expected', [('iso', 'yyyy-mm-dd'), ('slash', 'yyyy/mm/dd'), ('chinese', 'yyyy"年"m"月"d"日"')])
def test_actual_date_preferences_preserve_day_and_task_override(tmp_path, date_format, expected):
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '编制'},
        'xlsx': {'numbers': {'dateFormat': date_format}}}), 'xlsx')
    path = tmp_path / 'dates.xlsx'
    build_workbook(output_path=path, title='日期', period='2026', sheets=({'name': '数据', 'rows': [
        ['类型', '日期'], ['登记日期', {'value': '2026-11-12', 'valueType': 'date'}],
        ['普通文本', '2026-11-12'], ['任务样式', {'value': '2026-11-12', 'valueType': 'date', 'style': {'numberFormat': 'dd/mm/yyyy'}}],
        ['边界日期', {'value': '1900-01-01', 'valueType': 'date'}],
    ]},), preferences=prefs, generated_date='2026-11-12')
    sheet = load_workbook(path)['数据']
    assert sheet['B2'].value == datetime(2026, 11, 12)
    assert sheet['B2'].number_format == expected
    assert sheet['B3'].value == '2026-11-12' and sheet['B3'].data_type == 's'
    assert sheet['B4'].value == datetime(2026, 11, 12) and sheet['B4'].number_format == 'dd/mm/yyyy'
    assert sheet['B5'].value == datetime(1900, 1, 1)
    assert inspect_workbook(path.read_bytes())['sheets'][0]['cells']['B2']['value'] == 46338


def test_registered_dates_reach_actual_workflow_and_frozen_validation(tmp_path):
    from types import SimpleNamespace

    from smart_reporting.preferences.workbook_adapter import prepare_workbook
    from smart_reporting.reporting.workflow.runtime.workbook import (
        build_workbook_sheets,
        validate_workbook_snapshot,
    )

    columns, rows, issues = workbook_dataset_rows(b'day,code\n2026-11-12,001\n', dataset_id='dated',
        measures=set(), schema={'tables': [{'columns': [{'name': 'day', 'dataType': 'DATE'},
            {'name': 'code', 'dataType': 'VARCHAR'}]}]})
    assert not issues
    sheets, sources = build_workbook_sheets(manifest=SimpleNamespace(evidence=()),
        outline=SimpleNamespace(sections=()), fact_documents={},
        datasets={'dated': {'columns': columns, 'rows': rows}}, period='2026')
    prefs = resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '编制'},
        'xlsx': {'numbers': {'dateFormat': 'chinese'}}}), 'xlsx')
    path = tmp_path / 'workflow-dates.xlsx'
    expected, _ = prepare_workbook(sheets, prefs, title='日期', period='2026', generated_date='2026-11-12', filename=path.name)
    build_workbook(output_path=path, title='日期', period='2026', sheets=sheets, source_mapping=sources,
        preferences=prefs, generated_date='2026-11-12')
    content = path.read_bytes()
    assert validate_workbook_snapshot(inspect_workbook(content), expected, sources, content) == []
    sheet = load_workbook(path)['明细1_dated']
    assert sheet['A2'].value == datetime(2026, 11, 12)
    assert sheet['B2'].value == '001'
