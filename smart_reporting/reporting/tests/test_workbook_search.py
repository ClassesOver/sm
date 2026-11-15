"""GenOffice find_cells behavior, including JavaScript regex semantics."""
import pytest

from smart_reporting.report_editor.native_workbook_read_ai import NativeWorkbookReadTools
from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit


def workbook():
    return {'sheets': [{'name': 'Sheet', 'cells': {
        'A1': {'value': 'Revenue 42', 'formula': 'SUM(B1:B2)'},
        'A2': {'value': True}, 'A3': {'value': False},
        'A4': {'value': None}, 'A5': {'value': '#SPILL!'},
        'A6': {'value': 'Straße'}, 'A7': {'value': '#GETTING_DATA'},
        'A8': {'value': 'Secret'},
    }}]}


def tools():
    return WorkbookAIToolkit(model=workbook(), scope='workbook', selection={}, preview=None)


def addresses(result):
    return [item['address'] for item in result['matches']]


@pytest.mark.parametrize('query, expected', [
    ('^revenue [0-9]+$', ['A1']),
    (r'(?<amount>42)$', ['A1']),
    ('^1$', ['A2']),
    ('^0$', ['A3']),
])
def test_regex_matches_source_javascript_patterns(query, expected):
    assert addresses(tools().find_cells(query, regex=True)) == expected


def test_literal_search_uses_source_value_text_and_field_boundaries():
    instance = tools()
    assert addresses(instance.find_cells('1', look_in='values')) == ['A2']
    assert addresses(instance.find_cells('none')) == []
    assert addresses(instance.find_cells('strasse')) == []
    assert addresses(instance.find_cells('42 SUM')) == []
    assert addresses(instance.find_cells(' revenue ')) == ['A1']


def test_errors_only_ignores_query_and_regex_and_includes_modern_excel_errors():
    assert addresses(tools().find_cells('does not match', errors_only=True)) == ['A5', 'A7']
    assert addresses(tools().find_cells('[', regex=True, errors_only=True)) == ['A5', 'A7']


def test_invalid_regex_fails_even_when_frozen_sheet_is_empty():
    instance = WorkbookAIToolkit(model={'sheets': [{'name': 'Empty', 'cells': {}}]},
                               scope='workbook', selection={}, preview=None)
    with pytest.raises(ValueError, match='workbook_ai_search_invalid'):
        instance.find_cells('[', regex=True)


def test_regex_reader_only_searches_frozen_selection_and_never_marks_it_read():
    reader = NativeWorkbookReadTools(workbook(), {'sheetName': 'Sheet',
        'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0})
    assert addresses(reader.find_cells('.*', regex=True)) == ['A1']
    assert reader.coverage()['fullyReadBlockIds'] == []
    assert reader.tool_events[-1]['tool'] == 'find_cells'


def test_search_truncation_means_an_additional_match_exists():
    instance = tools()
    exact = instance.find_cells('Revenue', regex=True, max_results=1)
    assert addresses(exact) == ['A1'] and exact['truncated'] is False
    capped = instance.find_cells('.*', regex=True, max_results=1)
    assert addresses(capped) == ['A1'] and capped['truncated'] is True


def test_regex_parameter_is_exposed_in_agno_registered_schema():
    function = tools().functions['find_cells']
    function.process_entrypoint()
    assert function.parameters['properties']['regex']['type'] == 'boolean'
    assert 'regex' not in function.parameters.get('required', [])


@pytest.mark.parametrize('limit, count, truncated', [(0, 50, True), (-2, 50, True), (999, 200, True)])
def test_source_result_limit_defaults_and_clamps(limit, count, truncated):
    instance = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet', 'cells': {
        f'A{index}': {'value': 'match'} for index in range(1, 202)
    }}]}, scope='workbook', selection={}, preview=None)
    result = instance.find_cells('match', max_results=limit)
    assert len(result['matches']) == count
    assert result['truncated'] is truncated


def test_runaway_javascript_regex_returns_explicit_timeout():
    instance = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet', 'cells': {
        'A1': {'value': 'a' * 20000 + '!'},
    }}]}, scope='workbook', selection={}, preview=None)
    with pytest.raises(ValueError, match='workbook_ai_search_timeout'):
        instance.find_cells('(a+)+$', regex=True)


@pytest.mark.anyio
async def test_real_agno_reader_executes_regex_and_sees_actual_tool_receipt():
    import json

    from agno.models.response import ModelResponse

    from smart_reporting.report_editor.native_workbook_read_ai import AgnoNativeWorkbookReadPlanner
    from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel

    model = ScriptedModel(id='source-search', expected_tool_text='Revenue 42', responses=[
        ModelResponse(tool_calls=[{'id': 'find', 'type': 'function', 'function': {
            'name': 'find_cells', 'arguments': json.dumps({
                'query': r'^revenue (?<amount>42)$', 'regex': True,
            })}}]),
        ModelResponse(content=json.dumps({'answer': 'Revenue 42', 'citations': []})),
    ])
    reader = NativeWorkbookReadTools(workbook())
    result = await AgnoNativeWorkbookReadPlanner(model)(reader=reader, action='ask',
        instruction='查找收入', session_id='regex-reader', user_id='user')
    assert result['answer'] == 'Revenue 42'
    assert result['toolEvents'] == [{'tool': 'find_cells'}]
    assert result['coverage']['fullyReadBlockIds'] == []
    assert len(model.responses) == 2


@pytest.mark.parametrize('regex', [False, True])
def test_source_query_trim_removes_bom(regex):
    assert addresses(tools().find_cells('\ufeffRevenue\ufeff', regex=regex)) == ['A1']


def test_source_query_trim_keeps_non_ecmascript_nel():
    assert addresses(tools().find_cells('\x85Revenue\x85')) == []


def test_source_query_rejects_bom_only_input():
    with pytest.raises(ValueError, match='workbook_ai_search_invalid'):
        tools().find_cells('\ufeff')
