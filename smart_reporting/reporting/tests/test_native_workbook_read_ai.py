"""XLSX 独立只读范围、分页覆盖及 Agno 真实工具循环。"""
import json
from importlib import import_module, util
from io import BytesIO

import pytest
from agno.models.response import ModelResponse
from openpyxl import Workbook

from smart_reporting.report_editor.native_office import inspect_office
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel


def adapter():
    name = 'smart_reporting.report_editor.native_workbook_read_ai'
    assert util.find_spec(name), '缺少 XLSX 独立只读工具'
    return import_module(name)


def document():
    return {'definedNames': [{'name': '秘密名称'}], 'sheets': [
        {'name': '收入', 'cells': {'A1': {'value': 42}, 'B1': {'value': '秘密邻格'}},
         'notes': ['秘密批注']},
        {'name': '秘密表', 'cells': {'A1': {'value': '另一秘密'}}},
    ]}


def test_selection_freezes_only_authorized_cells_and_never_registers_writes():
    source = document()
    reader = adapter().NativeWorkbookReadTools(source, {
        'sheetName': '收入', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0})
    source['sheets'][0]['cells']['A1']['value'] = '外部修改'
    data = [reader.get_workbook_context(), reader.read_range('A1'), reader.find_cells('秘密')]
    assert '42' in json.dumps(data, ensure_ascii=False)
    assert all(secret not in json.dumps([data, reader._tools._model], ensure_ascii=False)
               for secret in ['秘密', '外部修改'])
    assert not hasattr(reader, 'propose_operations')
    assert 'propose_operations' not in reader._tools.functions
    with pytest.raises(ValueError):
        reader.read_range('A1:B1')
    with pytest.raises(ValueError):
        reader.read_cells(['A1'], '秘密表')
    assert reader.coverage() == {'scope': 'selection', 'totalBlocks': 1,
        'fullyReadBlockIds': ['收入!A1'], 'scopeReadComplete': True}


def test_real_engine_model_is_readable_and_empty_sheet_is_complete():
    book = Workbook()
    book.active.title = '实际'
    book.active['A1'] = 42
    book.active['B1'] = '=A1*2'
    book.create_sheet('空表')
    stream = BytesIO()
    book.save(stream)
    model = inspect_office('xlsx', stream.getvalue())
    reader = adapter().NativeWorkbookReadTools(model)
    data = json.loads(reader.read_range('A1:B1', '实际')['content'])
    assert data['cells']['A1']['value'] == 42
    assert 'A1*2' in data['cells']['B1']['formula']
    assert reader.coverage()['scopeReadComplete']
    empty = adapter().NativeWorkbookReadTools({'sheets': [{'name': '空表', 'cells': {}}]})
    assert empty.coverage() == {'scope': 'document', 'totalBlocks': 0,
        'fullyReadBlockIds': [], 'scopeReadComplete': True}


def test_pagination_search_aggregate_tail_and_changed_requests_do_not_forge_coverage():
    source = {'sheets': [{'name': 'Sheet', 'cells': {
        'A1': {'value': '长' * 60000}, 'B1': {'value': 2}}}]}
    reader = adapter().NativeWorkbookReadTools(source)
    assert reader.tool_call_budget() >= 15
    reader.find_cells('长')
    reader.aggregate_range('A1:B1')
    tail = reader.read_cells(['A1'], offset=48000)
    assert tail['nextOffset'] is None
    assert reader.coverage()['fullyReadBlockIds'] == []
    first = reader.read_cells(['A1'])
    reader.read_range('A1:B1', offset=24000)
    assert reader.coverage()['fullyReadBlockIds'] == []
    reader.read_cells(['A1'], offset=first['nextOffset'])
    assert reader.coverage()['fullyReadBlockIds'] == ['Sheet!A1']
    result = reader.result('部分总结', ['Sheet!A1', 'Sheet!B1', '伪造'], action='summary')
    assert result['citations'] == [{'sheetName': 'Sheet', 'address': 'A1', 'label': 'Sheet!A1'}]
    assert {i['code'] for i in result['issues']} >= {
        'native_workbook_ai_unread_citation', 'native_workbook_ai_incomplete_coverage'}
    reader.read_range('B1')
    assert reader.coverage()['scopeReadComplete']


@pytest.mark.parametrize('selection', [{}, {'sheetName': '不存在'},
    {'sheetName': '收入', 'startRow': -1, 'endRow': 0, 'startColumn': 0, 'endColumn': 0},
    {'sheetName': '收入', 'startRow': False, 'endRow': 0, 'startColumn': 0, 'endColumn': 0}])
def test_invalid_selections_are_rejected(selection):
    with pytest.raises(ValueError):
        adapter().NativeWorkbookReadTools(document(), selection)


@pytest.mark.anyio
async def test_real_agno_reads_cells_and_rebuilds_references_without_mutating_model():
    module = adapter()
    model = ScriptedModel(id='scripted', expected_tool_text='42', responses=[
        ModelResponse(tool_calls=[{'id': 'read', 'type': 'function', 'function': {
            'name': 'read_cells', 'arguments': json.dumps({'addresses': ['A1'], 'sheetId': '收入'})}}]),
        ModelResponse(content=json.dumps({'answer': '收入42', 'citations': ['收入!A1', '收入!B1']})),
    ])
    reader = module.NativeWorkbookReadTools(document())
    result = await module.AgnoNativeWorkbookReadPlanner(model)(reader=reader, action='keyPoints',
        instruction='总结收入', session_id='xlsx-read', user_id='user')
    assert result['answer'] == '收入42'
    assert result['citations'] == [{'sheetName': '收入', 'address': 'A1', 'label': '收入!A1'}]
    assert result['coverage']['fullyReadBlockIds'] == ['收入!A1']
    assert result['toolEvents'][0]['tool'] == 'read_cells'
    assert len(model.responses) == 2
    assert 'operations' not in result


def test_context_address_pagination_and_formula_tools_are_not_read_coverage():
    reader = adapter().NativeWorkbookReadTools({'sheets': [{'name': 'Sheet', 'cells': {
        **{f'A{i}': {'value': i} for i in range(1, 251)},
        'B1': {'formula': 'A1*2', 'value': 2},
    }}]})
    first = reader.get_workbook_context()
    assert first['nextOffset'] == 200
    assert len(first['sheets'][0]['knownAddresses']) == 200
    second = reader.get_workbook_context(offset=first['nextOffset'])
    assert second['nextOffset'] is None
    assert len(second['sheets'][0]['knownAddresses']) == 51
    assert reader.trace_precedents('B1')['precedents'][0]['address'] == 'A1'
    assert reader.trace_dependents('A1')['dependents'][0]['address'] == 'B1'
    assert reader.coverage()['fullyReadBlockIds'] == []
    assert 'native_workbook_ai_no_evidence' in {
        item['code'] for item in reader.result('尚无完整依据', [])['issues']}


def test_empty_workbook_summary_has_no_evidence_warning_and_no_fabricated_citations():
    reader = adapter().NativeWorkbookReadTools({'sheets': [{'name': '空表', 'cells': {}}]})
    result = reader.result('空表没有可总结的数据。', ['空表!A1'], action='summarize')
    assert result['coverage']['scopeReadComplete']
    assert result['coverage']['fullyReadBlockIds'] == []
    assert result['citations'] == []
    assert 'native_workbook_ai_no_evidence' in {item['code'] for item in result['issues']}


def test_verified_citation_includes_display_label():
    reader = adapter().NativeWorkbookReadTools(document())
    reader.read_cells(['A1'], '收入')
    assert reader.result('收入42', ['收入!A1'])['citations'] == [
        {'sheetName': '收入', 'address': 'A1', 'label': '收入!A1'}]
