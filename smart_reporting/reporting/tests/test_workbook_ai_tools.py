"""XLSX AI 真工具：冻结授权、引擎预览、显式采纳；不访问真实 provider。"""
from __future__ import annotations

import asyncio
import hashlib
import json
from io import BytesIO

import pytest
from agno.agent import Agent
from agno.models.response import ModelResponse
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font
from openpyxl.utils.datetime import CALENDAR_MAC_1904
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table

from smart_reporting.report_editor.native_models import NativeEditorContext
from smart_reporting.report_editor.native_office import inspect_office, patch_office
from smart_reporting.report_editor.workbook_ai import AgnoWorkbookProposalPlanner
from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit
from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel
from smart_reporting.reporting.tests.test_workbook_native_ai import Editor


@pytest.mark.anyio
async def test_source_conditional_formats_append_all_kinds_and_clear_only_target_sheet():
    book = Workbook()
    book.active.conditional_formatting.add('A1', FormulaRule(formula=['A1>0'], stopIfTrue=True))
    book.create_sheet('Other').conditional_formatting.add('A1', FormulaRule(formula=['A1<0']))
    stream = BytesIO()
    book.save(stream)
    original = stream.getvalue()
    written = None

    async def preview(operations):
        nonlocal written
        written = await asyncio.to_thread(patch_office, 'xlsx', original, operations)
        return {'draftSha256': hashlib.sha256(written).hexdigest()}

    model = {'sheets': [{'name': 'Sheet'}, {'name': 'Other'}]}
    tools = WorkbookAIToolkit(model=model, scope='workbook', selection={}, preview=preview)
    style = {'fillColor': '#ABCDEF', 'fontColor': '#112233', 'bold': True, 'italic': True}
    rules = [
        {'kind': 'number', 'operator': 'between', 'value': 1, 'value2': 5, 'format': style},
        {'kind': 'text', 'operator': 'notContains', 'text': '草稿', 'format': style},
        {'kind': 'blank', 'blank': False, 'format': style},
        {'kind': 'duplicate', 'unique': True, 'format': style},
        {'kind': 'top10', 'rank': 15, 'percent': True, 'bottom': True, 'format': style},
        {'kind': 'formula', 'formula': '=B7>0', 'format': style},
        {'kind': 'colorScale', 'minColor': '#FF0000', 'midColor': '#FFFF00', 'maxColor': '#00FF00'},
        {'kind': 'dataBar'},
    ]
    await tools.propose_operations([
        {'op': 'add_conditional_format', 'sheetId': 'Sheet', 'range': f'B{index}:D{index}', 'rule': rule}
        for index, rule in enumerate(rules, 2)
    ], '添加各类条件格式')
    formats = load_workbook(BytesIO(written))['Sheet'].conditional_formatting
    assert formats['A1'][0].stopIfTrue and formats['A1'][0].priority == 1
    expected = ['cellIs', 'notContainsText', 'notContainsBlanks', 'uniqueValues',
                'top10', 'expression', 'colorScale', 'dataBar']
    appended = [formats[f'B{i}:D{i}'][0] for i in range(2, 10)]
    assert [rule.type for rule in appended] == expected
    assert [rule.priority for rule in appended] == list(range(2, 10))
    assert appended[0].formula == ['1', '5'] and appended[0].dxf.font.b and appended[0].dxf.font.i
    assert appended[4].percent and appended[4].bottom and appended[4].rank == 15
    assert appended[5].formula == ['B7>0']
    assert appended[6].colorScale.cfvo[1].val == 50
    assert appended[7].dataBar.color.rgb == 'FF638EC6'

    original = written
    tools = WorkbookAIToolkit(model=model, scope='workbook', selection={}, preview=preview)
    await tools.propose_operations([{'op': 'clear_conditional_formats', 'sheetId': 'Sheet'}], '清除条件格式')
    book = load_workbook(BytesIO(written))
    assert not book['Sheet'].conditional_formatting
    assert book['Other'].conditional_formatting['A1'][0].formula == ['A1<0']


@pytest.mark.anyio
@pytest.mark.parametrize(('date1904', 'dates'), [
    (False, ('46023', '46053')), (True, ('44561', '44591')),
])
async def test_source_data_validation_keeps_other_cells_and_rebases_remaining_formula(date1904, dates):
    book = Workbook()
    if date1904:
        book.epoch = CALENDAR_MAC_1904
    sheet = book.active
    existing = DataValidation(type='custom', formula1='A1>$H$1', showErrorMessage=True)
    existing.add('B1:B5')
    sheet.add_data_validation(existing)
    sheet['B1'] = '原值'
    source = BytesIO()
    book.save(source)
    written = None

    async def preview(operations):
        nonlocal written
        written = await asyncio.to_thread(patch_office, 'xlsx', source.getvalue(), operations)
        return {'draftSha256': hashlib.sha256(written).hexdigest()}

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope='workbook',
                              selection={}, preview=preview)
    await tools.propose_operations([
        {'op': 'set_data_validation', 'sheetId': 'Sheet', 'range': target, 'validation': rule}
        for target, rule in [
            ('B1:B2', {'kind': 'list', 'values': ['通过', '待复核']}),
            ('B4', None),
            ('C1:C2', {'kind': 'listRef', 'range': 'G1:G3'}),
            ('D1', {'kind': 'numberBetween', 'min': 0.5, 'max': 9}),
            ('E1', {'kind': 'dateBetween', 'start': '2026-01-01', 'end': '2026-01-31'}),
            ('F1', {'kind': 'checkbox'}),
            ('I1', {'kind': 'formula', 'formula': '=ISNUMBER(I1)'}),
        ]
    ], '设置输入限制')
    sheet = load_workbook(BytesIO(written)).active
    rules = {str(rule.sqref): rule for rule in sheet.data_validations.dataValidation}
    assert rules['B1:B2'].formula1 == '"通过,待复核"'
    assert rules['B3 B5'].formula1 == 'A3>$H$1' and rules['B3 B5'].showErrorMessage
    assert rules['C1:C2'].formula1 == '$G$1:$G$3'
    assert (rules['D1'].type, rules['D1'].formula1, rules['D1'].formula2) == ('decimal', '0.5', '9')
    assert rules['E1'].type == 'date'
    assert (rules['E1'].formula1, rules['E1'].formula2) == dates
    assert rules['I1'].formula1 == 'ISNUMBER(I1)'
    model = inspect_office('xlsx', written)
    assert any(item['rule']['type'] == 'checkbox' for item in model['sheets'][0]['dataValidations']['rules'])
    assert sheet['B1'].value == '原值'


@pytest.mark.anyio
async def test_source_data_validation_rejects_range_scope():
    async def preview(_):
        pytest.fail('Unapproved data validation reached preview')

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope='range',
                              selection={'sheetName': 'Sheet'}, preview=preview)
    with pytest.raises(ValueError, match='selection_mismatch'):
        await tools.propose_operations([{
            'op': 'set_data_validation', 'sheetId': 'Sheet', 'range': 'A1', 'validation': None,
        }], '清除输入限制')


@pytest.mark.anyio
async def test_source_find_replace_uses_replayed_text_and_preserves_other_cell_types():
    book = Workbook()
    book.active.append(['OLD.old.', '= "old."', 42, '#N/A', ' old. ', 'OLDz', 'outside old.'])
    book.active['A1'].font = Font(bold=True)
    book.active['C1'].number_format = '"old."0'
    source = BytesIO()
    book.save(source)
    written = None

    async def preview(operations):
        nonlocal written
        written = await asyncio.to_thread(patch_office, 'xlsx', source.getvalue(), operations)
        return {'draftSha256': hashlib.sha256(written).hexdigest()}

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope='workbook',
                              selection={}, preview=preview)
    await tools.propose_operations([
        {'op': 'set_cell', 'sheetId': 'Sheet', 'address': 'A2', 'value': 'old.'},
        {'op': 'find_replace', 'sheetId': 'Sheet', 'range': 'A1:F2', 'find': '#N/A', 'replace': 'error'},
        {'op': 'find_replace', 'sheetId': 'Sheet', 'range': 'A1:F2', 'find': 'OLD.',
         'replace': '$&', 'wholeCell': True},
        {'op': 'find_replace', 'sheetId': 'Sheet', 'range': 'A1:F33333', 'find': 'old.', 'replace': 'new'},
    ], '替换文本')
    sheet = load_workbook(BytesIO(written)).active
    assert [cell.value for cell in sheet[1]] == ['newnew', '= "old."', 42, '#N/A', '$&', 'OLDz', 'outside old.']
    assert sheet['A2'].value == '$&' and sheet['A1'].font.bold and sheet['D1'].data_type == 'e'


@pytest.mark.anyio
async def test_source_find_replace_rejects_a_range_outside_the_authorized_selection():
    async def preview(_):
        pytest.fail('Out-of-scope replacement reached preview')

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope='range', preview=preview,
                              selection={'sheetName': 'Sheet', 'startRow': 0, 'endRow': 1,
                                         'startColumn': 0, 'endColumn': 0})
    with pytest.raises(ValueError, match='selection_mismatch'):
        await tools.propose_operations([
            {'op': 'find_replace', 'sheetId': 'Sheet', 'range': 'A1:B2', 'find': 'old', 'replace': 'new'},
        ], '替换选区文本')


@pytest.mark.anyio
async def test_source_axis_dimensions_round_trip_through_xlsx():
    book = Workbook()
    book.active['A1'] = '=2+3'
    book.create_sheet('Other').row_dimensions[3].height = 12
    source = BytesIO()
    book.save(source)
    written = None

    async def preview(operations):
        nonlocal written
        written = await asyncio.to_thread(patch_office, 'xlsx', source.getvalue(), operations)
        return {'draftSha256': hashlib.sha256(written).hexdigest()}

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}, {'name': 'Other'}]},
                              scope='workbook', selection={}, preview=preview)
    await tools.propose_operations([
        {'op': 'set_row_height', 'sheetId': 'Sheet', 'row': 3, 'count': 2, 'heightPoints': 30.3},
        {'op': 'set_col_width', 'sheetId': 'Sheet', 'column': 'B', 'widthPx': 124.5},
    ], '调整表格尺寸')
    saved = load_workbook(BytesIO(written))
    sheet = saved['Sheet']
    assert [sheet.row_dimensions[row].height for row in (3, 4)] == [30, 30]
    assert 'A' not in sheet.column_dimensions and 'C' not in sheet.column_dimensions
    assert round(sheet.column_dimensions['B'].width * 7 + 5) == 125
    assert sheet['A1'].value == '=2+3' and saved['Other'].row_dimensions[3].height == 12


@pytest.mark.anyio
@pytest.mark.parametrize(('scope', 'fields', 'error'), [
    ('workbook', {'row': 1048576, 'count': 2, 'heightPoints': 20}, 'axis_size_invalid'),
    ('workbook', {'column': 'XFD', 'count': 2, 'widthPx': 100}, 'axis_size_invalid'),
    ('workbook', {'column': 'A', 'widthPx': True}, 'axis_size_invalid'),
    ('workbook', {'column': 'A', 'widthPx': 2000}, 'column_width_exceeds_xlsx_limit'),
    ('range', {'row': 1, 'heightPoints': 20}, 'selection_mismatch'),
])
async def test_source_axis_dimensions_reject_invalid_arguments_or_scope(scope, fields, error):
    async def preview(_):
        pytest.fail('Invalid axis size proposal reached preview')

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope=scope,
                              selection={'sheetName': 'Sheet'}, preview=preview)
    with pytest.raises(ValueError, match=error):
        await tools.propose_operations([{
            'op': 'set_row_height' if 'row' in fields else 'set_col_width',
            'sheetId': 'Sheet', **fields,
        }], '调整表格尺寸')


@pytest.mark.anyio
async def test_source_refresh_pivot_uses_current_data_for_the_named_host():
    book = Workbook()
    book.active.title = 'Data'
    book.active.append(['Region', 'Sales'])
    book.active.append(['East', 10])
    book.active.append(['West', 20])
    book.create_sheet('Pivot')
    source = BytesIO()
    book.save(source)
    content = patch_office('xlsx', source.getvalue(), [{'kind': 'addPivot', 'addition': {
        'worksheetSheetName': 'Pivot', 'sourceSheetName': 'Data',
        'sourceArea': {'startRow': 0, 'startColumn': 0, 'endRow': 2, 'endColumn': 1},
        'location': {'startRow': 0, 'startColumn': 0, 'endRow': 3, 'endColumn': 1}, 'name': 'Sales',
        'fieldNames': ['Region', 'Sales'], 'rowFieldIndices': [0],
        'rowLevelItems': [['East', 'West']], 'rowLines': [{'t': 'data', 'members': [0]}, {'t': 'data', 'members': [1]}],
        'values': [{'fieldIndex': 1, 'agg': 'sum'}],
    }}])
    written = None

    async def preview(operations):
        nonlocal written
        written = await asyncio.to_thread(patch_office, 'xlsx', content, operations)
        return {'draftSha256': hashlib.sha256(written).hexdigest()}

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Data'}, {'name': 'Pivot'}]}, scope='workbook',
                              selection={}, preview=preview)
    await tools.propose_operations([
        {'op': 'set_cell', 'sheetId': 'Data', 'address': 'B2', 'value': 123},
        {'op': 'refresh_pivot', 'sheetId': 'Pivot'},
    ], '刷新销售透视表')
    assert tools.proposal.engine_operations()[-1] == {'kind': 'refreshPivotCaches', 'sheetName': 'Pivot'}
    sheet = load_workbook(BytesIO(written))['Pivot']
    assert sheet['A2'].value == 'East' and sheet['B2'].value == 123


@pytest.mark.anyio
async def test_source_set_note_replays_added_replaced_and_removed_notes():
    book = Workbook()
    book.active['A1'] = '=2+3'
    book.active['A1'].comment = Comment('旧备注', '原作者')
    book.active['A2'].comment = Comment('待移除', '原作者')
    book.active['A3'].comment = Comment('保留', '同事')
    source = BytesIO()
    book.save(source)
    written = None

    async def preview(operations):
        nonlocal written
        written = await asyncio.to_thread(patch_office, 'xlsx', source.getvalue(), operations)
        return {'draftSha256': hashlib.sha256(written).hexdigest()}

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope='workbook',
                              selection={}, preview=preview)
    await tools.propose_operations([
        {'op': 'set_note', 'sheetId': 'Sheet', 'address': address, 'text': text}
        for address, text in [('A1', '更新备注'), ('A2', None), ('B1', '新增备注')]
    ], '整理备注')
    sheet = load_workbook(BytesIO(written)).active
    assert sheet['A1'].value == '=2+3'
    assert (sheet['A1'].comment.text, sheet['A1'].comment.author) == ('更新备注', '原作者')
    assert sheet['A2'].comment is None
    assert (sheet['A3'].comment.text, sheet['A3'].comment.author) == ('保留', '同事')
    assert sheet['B1'].comment.text == '新增备注'


@pytest.mark.anyio
@pytest.mark.parametrize(('scope', 'fields', 'error'), [
    ('workbook', {'text': ''}, 'note_invalid'),
    ('workbook', {'text': '内容', 'author': '管理员'}, 'note_invalid'),
    ('range', {'text': None}, 'selection_mismatch'),
])
async def test_source_set_note_rejects_invalid_arguments_or_scope(scope, fields, error):
    async def preview(_):
        pytest.fail('Invalid note proposal reached preview')

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope=scope,
        selection={'sheetName': 'Sheet', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0},
        preview=preview)
    with pytest.raises(ValueError, match=error):
        await tools.propose_operations([
            {'op': 'set_note', 'sheetId': 'Sheet', 'address': 'A1', **fields},
        ], '更新备注')


@pytest.mark.anyio
async def test_source_print_setup_writes_repeated_rows_columns_and_manual_breaks():
    book = Workbook()
    book.active['A1'] = 'Printed'
    book.active.freeze_panes = 'A2'
    source = BytesIO()
    book.save(source)
    written = None

    async def preview(operations):
        nonlocal written
        written = await asyncio.to_thread(patch_office, 'xlsx', source.getvalue(), operations)
        return {'draftSha256': hashlib.sha256(written).hexdigest()}

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope='workbook',
                              selection={}, preview=preview)
    await tools.propose_operations([
        {'op': 'set_page_setup', 'sheetId': 'Sheet', 'orientation': 'landscape',
         'paperSize': 9, 'fitToWidth': 2, 'fitToHeight': 3, 'margins': 'narrow',
         'printGridlines': True, 'printTitles': '1:2,A:B', 'printArea': 'A1:D10',
         'footer': {'center': 'Page &P/&N'}, 'rowBreaks': [5], 'colBreaks': [2]},
        {'op': 'set_page_setup', 'sheetId': 'Sheet', 'fitToWidth': 4},
    ], '调整打印设置')
    sheet = load_workbook(BytesIO(written)).active
    assert sheet.page_setup.orientation == 'landscape' and sheet.page_setup.paperSize == 9
    assert (sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight) == (4, 3)
    assert sheet.sheet_properties.pageSetUpPr.fitToPage is True
    assert (sheet.print_title_rows, sheet.print_title_cols) == ('$1:$2', '$A:$B')
    assert '$A$1:$D$10' in sheet.print_area
    assert sheet.oddFooter.center.text == 'Page &P/&N'
    assert [item.id for item in sheet.row_breaks.brk] == [5]
    assert [item.id for item in sheet.col_breaks.brk] == [2]
    assert sheet.page_margins.left == 0.25 and sheet.print_options.gridLines is True
    assert sheet.freeze_panes == 'A2' and sheet['A1'].value == 'Printed'


@pytest.mark.anyio
@pytest.mark.parametrize('invalid', [
    {}, {'scale': 100, 'fitToWidth': 1}, {'printTitles': 'A:C,B:D'},
    {'printArea': 'XFE1:XFE4'}, {'rowBreaks': [0]}, {'printHeadings': 1},
])
async def test_source_print_setup_rejects_invalid_settings_before_preview(invalid):
    async def preview(_):
        pytest.fail('Invalid page settings reached preview')

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope='workbook',
                              selection={}, preview=preview)
    with pytest.raises(ValueError, match='range_invalid|page_setup_invalid'):
        await tools.propose_operations([
            {'op': 'set_page_setup', 'sheetId': 'Sheet', **invalid},
        ], '调整打印设置')


@pytest.mark.anyio
@pytest.mark.parametrize(('rows', 'columns', 'expected'), [(2, 1, 'B3'), (1, 0, 'A2'), (0, 2, 'C1'), (0, 0, None)])
async def test_source_set_freeze_updates_native_sheet_view(rows, columns, expected):
    book = Workbook()
    book.active['A1'] = '保留内容'
    book.active.freeze_panes = 'D4'
    book.active.sheet_view.showGridLines = False
    source = BytesIO()
    book.save(source)
    written = None

    async def preview(operations):
        nonlocal written
        written = await asyncio.to_thread(patch_office, 'xlsx', source.getvalue(), operations)
        return {'draftSha256': hashlib.sha256(written).hexdigest()}

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope='workbook',
                              selection={}, preview=preview)
    await tools.propose_operations([
        {'op': 'set_freeze', 'sheetId': 'Sheet', 'rows': rows, 'columns': columns},
    ], '调整冻结窗格')
    sheet = load_workbook(BytesIO(written)).active
    assert sheet.freeze_panes == expected
    assert sheet['A1'].value == '保留内容' and sheet.sheet_view.showGridLines is False


@pytest.mark.anyio
@pytest.mark.parametrize(('scope', 'rows', 'error'), [
    ('workbook', True, 'freeze_invalid'), ('workbook', 101, 'freeze_invalid'),
    ('range', 1, 'selection_mismatch'),
])
async def test_source_set_freeze_rejects_invalid_counts_and_selection_scope(scope, rows, error):
    async def preview(_):
        pytest.fail('Invalid freeze operation reached preview')

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope=scope,
        selection={'sheetName': 'Sheet', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0},
        preview=preview)
    with pytest.raises(ValueError, match=error):
        await tools.propose_operations([
            {'op': 'set_freeze', 'sheetId': 'Sheet', 'rows': rows, 'columns': 0},
        ], '调整冻结窗格')


@pytest.mark.anyio
@pytest.mark.parametrize('target', ['example.com/sales', 'Sheet!B2', None])
async def test_source_hyperlink_replays_without_overwriting_cell_content(target):
    book = Workbook()
    book.active['A1'] = '=B2'
    book.active['A1'].hyperlink = 'https://example.org/original'
    book.active['A1'].font = Font(bold=True, color='FF112233', underline='single')
    original = BytesIO()
    book.save(original)
    written = None

    async def preview(operations):
        nonlocal written
        written = await asyncio.to_thread(patch_office, 'xlsx', original.getvalue(), operations)
        return {'draftSha256': hashlib.sha256(written).hexdigest()}

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope='workbook',
                              selection={}, preview=preview)
    await tools.propose_operations([
        {'op': 'set_hyperlink', 'sheetId': 'Sheet', 'address': '$a$1', 'target': target},
    ], '更新链接')
    cell = load_workbook(BytesIO(written)).active['A1']
    assert cell.value == '=B2' and cell.font.bold
    if target is None:
        assert cell.hyperlink is None and cell.font.underline is None and cell.font.color is None
    else:
        assert cell.font.underline == 'single' and cell.font.color.rgb[-6:] == '0563C1'
        if target.startswith('Sheet!'):
            assert cell.hyperlink.location == target and cell.hyperlink.target is None
        else:
            assert cell.hyperlink.target == 'https://' + target


@pytest.mark.anyio
async def test_source_hyperlink_requires_workbook_scope():
    async def preview(_):
        pytest.fail('Hyperlink proposal in range scope reached preview')

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope='range',
        selection={'sheetName': 'Sheet', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0},
        preview=preview)
    with pytest.raises(ValueError, match='selection_mismatch'):
        await tools.propose_operations([
            {'op': 'set_hyperlink', 'sheetId': 'Sheet', 'address': 'A1', 'target': 'https://example.com'},
        ], '插入链接')


@pytest.mark.anyio
async def test_source_add_table_uses_replayed_headers_and_keeps_cell_styles():
    book = Workbook()
    book.active['A1'] = '旧表头'
    book.active['A1'].font = Font(bold=True)
    book.active['B2'] = 25
    source = BytesIO()
    book.save(source)
    written = None

    async def preview(operations):
        nonlocal written
        written = await asyncio.to_thread(patch_office, 'xlsx', source.getvalue(), operations)
        return {'draftSha256': hashlib.sha256(written).hexdigest()}

    model = {'sheets': [{'name': 'Sheet', 'cells': {'A1': {'value': '旧表头'}}}]}
    tools = WorkbookAIToolkit(model=model, scope='workbook', selection={}, preview=preview)
    await tools.propose_operations([
        {'op': 'set_cell', 'sheetId': 'Sheet', 'address': 'A1', 'value': '地区'},
        {'op': 'add_table', 'sheetId': 'Sheet', 'range': 'A1:B2', 'bandedRows': False},
    ], '更新表头并创建表格')
    sheet = load_workbook(BytesIO(written)).active
    table = sheet.tables['Table1']
    assert table.ref == 'A1:B2'
    assert [column.name for column in table.tableColumns] == ['地区', 'Column2']
    assert table.tableStyleInfo.showRowStripes is False
    assert [sheet[addr].value for addr in ('A1', 'B1', 'B2')] == ['地区', 'Column2', 25]
    assert sheet['A1'].font.bold


@pytest.mark.anyio
async def test_source_range_writes_formulas_and_clears_content_within_selection():
    book = Workbook()
    book.active['B3'] = '=1+2'
    book.active['B3'].font = Font(bold=True)
    book.active['C3'] = 'outside selection'
    original = BytesIO()
    book.save(original)
    source = original.getvalue()
    content = None

    async def preview(operations):
        nonlocal content
        content = await asyncio.to_thread(patch_office, 'xlsx', source, operations)
        return {'draftSha256': hashlib.sha256(content).hexdigest()}

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet', 'cells': {}}]}, scope='range',
        selection={'sheetName': 'Sheet', 'startRow': 1, 'endRow': 2, 'startColumn': 0, 'endColumn': 1},
        preview=preview)
    await tools.propose_operations([
        {'op': 'set_range', 'sheetId': 'Sheet', 'start': 'a2', 'range': 'A2:B3',
         'values': [[5, '=A2*2'], [True, None]]},
        {'op': 'clear_range', 'sheetId': 'Sheet', 'range': '$B$3'},
        {'op': 'set_formula', 'sheetId': 'Sheet', 'address': 'B2',
         'expectedFormula': '=A2*2', 'formula': '=A2*3'},
    ], '更新选区')
    sheet = load_workbook(BytesIO(content)).active
    assert [sheet[addr].value for addr in ('A2', 'B2', 'A3', 'B3', 'C3')] == [
        5, '=A2*3', True, None, 'outside selection',
    ]
    assert sheet['B3'].font.bold


@pytest.mark.anyio
@pytest.mark.parametrize(('operation', 'error'), [
    ({'op': 'set_range', 'start': 'A1', 'values': [[1, 2], [3]]}, 'range_invalid'),
    ({'op': 'set_range', 'start': 'B1', 'range': 'A1:B1', 'values': [[1, 2]]}, 'range_invalid'),
    ({'op': 'set_range', 'range': 'A1:A2', 'values': [[1, 2]]}, 'range_invalid'),
    ({'op': 'set_range', 'start': 'A1', 'values': [[1, 2, 3]]}, 'selection_mismatch'),
    ({'op': 'clear_range', 'range': 'A1:C2'}, 'selection_mismatch'),
])
async def test_source_range_rejects_invalid_geometry_before_preview(operation, error):
    async def preview(_):
        pytest.fail('Invalid range reached preview')

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope='range',
        selection={'sheetName': 'Sheet', 'startRow': 0, 'endRow': 1, 'startColumn': 0, 'endColumn': 1},
        preview=preview)
    with pytest.raises(ValueError, match=error):
        await tools.propose_operations([{**operation, 'sheetId': 'Sheet'}], '更新选区')


@pytest.mark.anyio
async def test_source_range_expansion_limit_covers_the_batch():
    async def preview(_):
        pytest.fail('Oversized range batch reached preview')

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet'}]}, scope='workbook',
                              selection={}, preview=preview)
    with pytest.raises(ValueError, match='range_too_large'):
        await tools.propose_operations([
            {'op': 'clear_range', 'sheetId': 'Sheet', 'range': 'A1:B1000'},
            {'op': 'set_range', 'sheetId': 'Sheet', 'start': 'D1', 'values': [[42]]},
        ], '清空旧数据并登记合计')


@pytest.mark.anyio
async def test_source_large_clear_replays_on_workbook_with_no_blank_cell_expansion():
    book = Workbook()
    book.active['A1'] = 'old'
    book.active['B1200'] = '=1+2'
    book.active['B1200'].font = Font(bold=True)
    book.active['C1200'] = 'outside range'
    original = BytesIO()
    book.save(original)
    source = original.getvalue()
    content = None

    async def preview(operations):
        nonlocal content
        assert operations[1] == {'kind': 'clearCellRange', 'sheetName': 'Sheet', 'range': 'A1:B1200'}
        content = await asyncio.to_thread(patch_office, 'xlsx', source, operations)
        return {'draftSha256': hashlib.sha256(content).hexdigest()}

    model = {'sheets': [{'name': 'Sheet', 'cells': {'A1': {'value': 'old'}}}]}
    tools = WorkbookAIToolkit(model=model, scope='range',
        selection={'sheetName': 'Sheet', 'startRow': 0, 'endRow': 1199, 'startColumn': 0, 'endColumn': 1},
        preview=preview)
    await tools.propose_operations([
        {'op': 'set_cell', 'sheetId': 'Sheet', 'address': 'A2', 'value': 'staged'},
        {'op': 'clear_range', 'sheetId': 'Sheet', 'range': 'A1:B1200'},
        {'op': 'set_cell', 'sheetId': 'Sheet', 'address': 'A2',
         'expectedValue': None, 'value': 'added after clear'},
    ], '清空旧数据')
    sheet = load_workbook(BytesIO(content)).active
    assert sheet['A1'].value is None and sheet['B1200'].value is None
    assert sheet['A2'].value == 'added after clear'
    assert (sheet['B1200'].font.bold, sheet['C1200'].value) == (True, 'outside range')


def test_workbook_formula_trace_reports_precedents_and_rejects_unsupported_syntax():
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    tools = WorkbookAIToolkit(model={"sheets": [
        {"name": "Sheet", "cells": {
            "A1": {"value": 2}, "B1": {"value": 3},
            "C1": {"value": 5, "formula": "SUM(A1:B1)"},
        }},
    ]}, scope="workbook", selection={}, preview=None)
    result = tools.trace_precedents("C1", "Sheet")
    assert result["formula"] == "SUM(A1:B1)"
    assert {(item["sheetName"], item["address"], item["value"]) for item in result["precedents"]} == {
        ("Sheet", "A1", 2), ("Sheet", "B1", 3)
    }
    tools._sheets["Sheet"]["cells"]["C1"]["formula"] = "Other!A1+NamedTotal"
    with pytest.raises(ValueError, match="unsupported"):
        tools.trace_precedents("C1", "Sheet")


def test_workbook_formula_trace_dependents_is_bounded_and_cross_sheet():
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    tools = WorkbookAIToolkit(model={"sheets": [
        {"name": "Sheet", "cells": {"A1": {"value": 2}}},
        {"name": "Other", "cells": {
            "A1": {"value": 4, "formula": "Sheet!A1*2"},
            "B1": {"value": 6, "formula": "SUM(Sheet!A1,Other!A1)"},
        }},
    ]}, scope="workbook", selection={}, preview=None)
    result = tools.trace_dependents("A1", "Sheet")
    assert {(item["sheetName"], item["address"]) for item in result["dependents"]} == {
        ("Other", "A1"), ("Other", "B1")
    }


def test_formula_trace_tokenizes_strings_absolute_refs_and_escaped_sheet_names():
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    tools = WorkbookAIToolkit(model={"sheets": [
        {"name": "Sheet", "cells": {"A1": {"value": 2}, "C1": {
            "formula": 'IF($A$1="B2",LOG10(\'O\'\'Brien\'!$B$2),1)', "value": 3,
        }}},
        {"name": "O'Brien", "cells": {"B2": {"value": 1000}}},
    ]}, scope="workbook", selection={}, preview=None)
    refs = tools.trace_precedents("C1", "Sheet")["precedents"]
    assert [(item["sheetName"], item["address"]) for item in refs] == [("Sheet", "A1"), ("O'Brien", "B2")]


def test_formula_dependents_reports_unsupported_formulas_and_limited_scope():
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    model = {"sheets": [{"name": "Sheet", "cells": {
        "A1": {"value": 2}, "B1": {"formula": 'INDIRECT("A1")'},
        "C1": {"formula": "NamedTotal+A1"}, "D1": {"formula": 'IF(A1="B2",1,2)'},
    }}]}
    tools = WorkbookAIToolkit(model=model, scope="workbook", selection={}, preview=None)
    result = tools.trace_dependents("A1", "Sheet")
    assert result["complete"] is False
    assert result["unsupportedFormulaCount"] == 2
    assert [item["address"] for item in result["dependents"]] == ["D1"]
    with pytest.raises(ValueError, match="unsupported"):
        tools.trace_precedents("B1", "Sheet")
    scoped = WorkbookAIToolkit(model=model, scope="range", selection={
        "sheetName": "Sheet", "startRow": 0, "endRow": 0, "startColumn": 0, "endColumn": 0,
    }, preview=None)
    result = scoped.trace_dependents("A1", "Sheet")
    assert result["scope"] == "range" and result["complete"] is False
    assert result["dependents"] == []


@pytest.mark.parametrize("formula", [
    "NamedTotal+A1", "Table1[Amount]+A1", "'[book.xlsx]Sheet'!A1",
    "SUM(A1:A201)", 'OFFSET(A1,0,1)', "Sheet:Other!A1", "SUM(A1",
])
def test_formula_trace_rejects_unresolved_or_unbounded_references(formula):
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    tools = WorkbookAIToolkit(model={"sheets": [{"name": "Sheet", "cells": {
        "C1": {"formula": formula},
    }}]}, scope="workbook", selection={}, preview=None)
    with pytest.raises(ValueError, match="unsupported"):
        tools.trace_precedents("C1", "Sheet")


def test_formula_trace_enforces_range_authorization_and_ignores_literal_addresses():
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    tools = WorkbookAIToolkit(model={"sheets": [{"name": "Sheet", "cells": {
        "A1": {"formula": 'IF(TRUE,"B2","C3")'}, "B1": {"value": "private"},
    }}]}, scope="range", selection={
        "sheetName": "Sheet", "startRow": 0, "endRow": 0, "startColumn": 0, "endColumn": 0,
    }, preview=None)
    assert tools.trace_precedents("A1", "Sheet")["precedents"] == []
    tools._sheets["Sheet"]["cells"]["A1"]["formula"] = "B1+1"
    with pytest.raises(ValueError, match="selection"):
        tools.trace_precedents("A1", "Sheet")


@pytest.mark.anyio
async def test_agno_tool_loop_reads_formula_dependencies_before_submitting_proposal():
    from ast import literal_eval
    from unittest.mock import AsyncMock

    model = ScriptedModel(id='scripted-trace', responses=[
        call('trace_precedents', {'address': 'C1', 'sheetId': 'Sheet'}, 'precedents'),
        call('trace_dependents', {'address': 'A1', 'sheetId': 'Sheet'}, 'dependents'),
        call('propose_operations', {'operations': [{'op': 'set_cell', 'sheetId': 'Sheet', 'address': 'D1', 'value': 5}], 'summary': '保留公式并登记合计'}, 'propose'),
        ModelResponse(content='候选待采纳'),
    ])
    preview = AsyncMock(return_value={'draftSha256': 'a' * 64})
    proposal = await AgnoWorkbookProposalPlanner(Agent(model=model)).plan_workbook(
        '核对C1依赖并将合计写入D1', model={'sheets': [{'name': 'Sheet', 'cells': {
            'A1': {'value': 2}, 'B1': {'value': 3}, 'C1': {'value': 5, 'formula': 'SUM($A$1:B1)'},
        }}]}, scope='workbook', selection={}, preview=preview, session_id='trace', user_id='u',
    )
    replies = [literal_eval(message.content) for turn in model.seen for message in turn
               if message.role == 'tool' and isinstance(message.content, str) and message.content.startswith('{')]
    assert any([item['address'] for item in reply.get('precedents', [])] == ['A1', 'B1'] for reply in replies)
    assert any(reply.get('complete') is True and [item['address'] for item in reply.get('dependents', [])] == ['C1'] for reply in replies)
    assert proposal.summary == '保留公式并登记合计'
    preview.assert_awaited_once()


def call(name, arguments, identity):
    return ModelResponse(tool_calls=[{
        'id': identity, 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)},
    }])


@pytest.mark.anyio
@pytest.mark.parametrize('scope', ['range', 'workbook'])
@pytest.mark.parametrize(('operation', 'expected'), [
    ({'op': 'set_cell', 'value': 59}, 59),
    ({'op': 'set_formula', 'formula': '=SUM(B1:C1)'}, '=SUM(B1:C1)'),
    ({'op': 'clear_cell'}, None),
])
async def test_workbook_cell_dsl_previews_real_engine_in_both_scopes(scope, operation, expected):
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    workbook = Workbook()
    workbook.active.append([42, 17, 25, '保留未选内容'])
    stream = BytesIO()
    workbook.save(stream)
    source = stream.getvalue()
    previews = []

    async def preview(operations):
        edited = await asyncio.to_thread(patch_office, 'xlsx', source, operations)
        previews.append(edited)
        return {'draftSha256': hashlib.sha256(edited).hexdigest()}

    tools = WorkbookAIToolkit(
        model=await asyncio.to_thread(inspect_office, 'xlsx', source),
        scope=scope,
        selection={'sheetName': 'Sheet', 'startRow': 0, 'endRow': 0,
                   'startColumn': 0, 'endColumn': 0},
        preview=preview,
    )
    result = await tools.propose_operations(
        [{**operation, 'sheetId': 'Sheet', 'address': 'A1'}], '修改选中单元格',
    )
    assert result['requiresAcceptance'] is True
    assert len(previews) == 1
    reopened = load_workbook(BytesIO(previews[0])).active
    assert reopened['A1'].value == expected
    assert [reopened.cell(1, column).value for column in (2, 3, 4)] == [17, 25, '保留未选内容']
    assert load_workbook(BytesIO(source)).active['A1'].value == 42


@pytest.mark.anyio
async def test_workbook_tools_do_not_read_or_propose_outside_frozen_range():
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit
    selection = {'sheetName': 'Sheet', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0}
    async def preview(_operations):
        raise AssertionError('越权候选不得进入预览')
    tools = WorkbookAIToolkit(model={'sheets': [
        {'name': 'Sheet', 'cells': {'A1': {'value': 42}, 'B1': {'value': '秘密'}}, 'merges': ['B1:C1']},
        {'name': 'Private', 'cells': {'A1': {'value': '另一秘密'}}},
    ]}, scope='range', selection=selection, preview=preview)
    assert tools.read_range('A1')['cells']['A1']['value'] == 42
    with pytest.raises(ValueError, match='selection'):
        tools.read_range('A1:B1')
    with pytest.raises(ValueError, match='selection'):
        tools.read_cells(['A1'], sheetId='Private')
    assert '秘密' not in json.dumps(tools.find_cells('秘密'), ensure_ascii=False)
    assert 'B1:C1' not in json.dumps(tools.read_sheet_features(), ensure_ascii=False)
    assert 'Private' not in json.dumps(tools.get_workbook_context(), ensure_ascii=False)
    with pytest.raises(ValueError, match='selection'):
        await tools.propose_operations([{'op': 'sort_range', 'sheetId': 'Sheet', 'range': 'A1:A3', 'byColumn': 'A', 'order': 'asc'}], '排序')
    assert tools.proposal is None


@pytest.mark.anyio
async def test_workbook_tools_real_agno_loop_previews_complex_engine_ops_and_accepts_complete_draft():
    workbook = Workbook()
    sheet = workbook.active
    for row in [['项目', '金额'], ['乙', 9], ['甲', 2]]:
        sheet.append(row)
    sheet['D1'] = '既有合并'
    sheet.merge_cells('D1:E1')
    sheet.add_table(Table(displayName='Items', ref='A1:B3'))
    stream = BytesIO()
    workbook.save(stream)
    content = stream.getvalue()
    class RealEditor(Editor):
        def __init__(self):
            super().__init__()
            raw = self.context.model_dump(by_alias=True)
            raw['sourceFile'].update(sha256=hashlib.sha256(content).hexdigest(), size=len(content))
            self.context = NativeEditorContext.model_validate(raw)
        async def preview(self, _context, *, expected_sha256, operations):
            assert expected_sha256 == self.context.source_file.sha256
            self.previews.append(operations)
            edited = await asyncio.to_thread(patch_office, 'xlsx', content, operations)
            return {'draftSha256': hashlib.sha256(edited).hexdigest(), 'model': await asyncio.to_thread(inspect_office, 'xlsx', edited)}
    operations = [
        {'op': 'sort_range', 'sheetId': 'Sheet', 'range': 'A1:B3', 'byColumn': 'B', 'order': 'asc', 'hasHeader': True},
        {'op': 'merge_cells', 'sheetId': 'Sheet', 'range': 'D2:E2'},
        {'op': 'set_filter', 'sheetId': 'Sheet', 'range': 'G1:H3'},
        {'op': 'add_defined_name', 'name': 'SalesAmounts', 'ref': 'Sheet!$B$2:$B$3'},
        {'kind': 'applyTableEdits', 'arguments': {'edits': [{'worksheetSheetName': 'Sheet', 'tableName': 'Items', 'style': 'TableStyleMedium2', 'totalsRow': True}]}},
    ]
    model = ScriptedModel(id='scripted', responses=[
        call('get_workbook_context', {}, 'ctx'),
        call('read_range', {'range': 'A1:B3', 'sheetId': 'Sheet'}, 'read'),
        call('read_sheet_features', {'sheetId': 'Sheet'}, 'features'),
        call('propose_operations', {'operations': operations, 'summary': '排序并调整表格结构'}, 'propose'),
        ModelResponse(content='候选已完成；这段正文不是可执行代码。'),
    ])
    editor = RealEditor()
    ai = NativeWorkbookAIService(editor, planner=AgnoWorkbookProposalPlanner(Agent(model=model)), enabled=True)
    base = [{'kind': 'applyCellEdits', 'edits': [{'sheetName': 'Sheet', 'row': 4, 'column': 0, 'writeValue': True, 'cell': {'value': '人工未保存'}}]}]
    job = await ai.start_edit(None, client_request_id='tools-real-engine', instruction='金额升序、保留既有合并并新增D2:E2合并，设置筛选和名称，把Items表改为中蓝色并开启汇总行', expected_sha256=editor.context.source_file.sha256, operations=base, selection={}, scope='workbook')
    result = await ai.wait_edit_status(None, job['editId'])
    assert result['status'] == 'succeeded', result
    assert result['accepted'] is False
    assert any('人工未保存' in str(m.content) for turn in model.seen for m in turn)
    accepted = await ai.accept_edit(None, job['editId'], expected_sha256=editor.context.source_file.sha256, operations=base, snapshot_sha256=result['snapshotSha256'])
    assert accepted['operations'][0] == base[0]
    edited = await asyncio.to_thread(patch_office, 'xlsx', content, accepted['operations'])
    reopened = load_workbook(BytesIO(edited))
    target = reopened.active
    assert [target['B2'].value, target['B3'].value] == [2, 9]
    assert [target['A2'].value, target['A3'].value] == ['甲', '乙']
    assert {str(area) for area in target.merged_cells.ranges} == {'D1:E1', 'D2:E2'}
    assert target.auto_filter.ref == 'G1:H3'
    assert reopened.defined_names['SalesAmounts'].attr_text == 'Sheet!$B$2:$B$3'
    assert target.tables['Items'].tableStyleInfo.name == 'TableStyleMedium2'
    assert target.tables['Items'].totalsRowShown is True
    assert target['A5'].value == '人工未保存'
    assert load_workbook(BytesIO(content)).active['B2'].value == 9
    with pytest.raises(Exception):
        await ai.accept_edit(None, job['editId'], expected_sha256=editor.context.source_file.sha256, operations=[], snapshot_sha256=result['snapshotSha256'])
    await ai.aclose()


@pytest.mark.anyio
async def test_workbook_tool_planner_never_executes_a_model_prose_proposal():
    model = ScriptedModel(id='scripted', responses=[ModelResponse(content=json.dumps({
        'summary': '不得执行正文', 'operations': [{'kind': 'applyCellEdits', 'arguments': {
            'edits': [{'sheetName': 'Sheet', 'row': 0, 'column': 0, 'writeValue': True, 'cell': {'value': '非法候选'}}],
        }}],
    }))])
    ai = NativeWorkbookAIService(Editor(), planner=AgnoWorkbookProposalPlanner(Agent(model=model)), enabled=True)
    job = await ai.start_edit(None, client_request_id='prose', instruction='修改A1', expected_sha256='a'*64, operations=[], selection={}, scope='workbook')
    result = await ai.wait_edit_status(None, job['editId'])
    assert result['status'] == 'failed' and 'proposal' not in result
    await ai.aclose()
