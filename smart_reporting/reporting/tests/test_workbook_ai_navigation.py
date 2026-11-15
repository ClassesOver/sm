"""Authorized select_range requests are distinct from reading and UI success."""
import json

import pytest
from agno.models.response import ModelResponse
from pydantic import ValidationError

from smart_reporting.report_editor.native_workbook_read_ai import (
    AgnoNativeWorkbookReadPlanner,
    NativeWorkbookReadAnswer,
    NativeWorkbookReadTools,
)
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel

VIEW = {'sheetName': 'Active', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0}


def reader(selection=None, view=VIEW):
    return NativeWorkbookReadTools({'sheets': [
        {'name': 'First', 'cells': {'A1': {'value': 'first'}}},
        {'name': 'Active', 'cells': {'A1': {'value': 42}, 'B2': {'value': 84}}},
    ]}, selection, view_selection=view)


def test_view_selection_defaults_to_actual_sheet_without_reading_coverage():
    tools = reader()
    assert json.loads(tools.read_range('A1')['content'])['cells']['A1']['value'] == 42
    assert tools.get_workbook_context()['activeSheetId'] == 'Active'


@pytest.mark.parametrize('range_', [' a1 : b2 ', '$A$1:$B$2', 'B2:A1'])
def test_select_range_owns_canonical_pending_target_and_does_not_read_cells(range_):
    tools = reader()
    receipt = tools.select_range(range_)
    assert receipt['status'] == 'navigation_requested'
    assert receipt['mutated'] is False
    result = tools.result('已请求定位', [])
    assert result['navigation'] == {'sheetName': 'Active', 'range': 'A1:B2',
        'startRow': 0, 'endRow': 1, 'startColumn': 0, 'endColumn': 1}
    assert result['coverage']['fullyReadBlockIds'] == []
    assert result['citations'] == []
    assert result['toolEvents'][-1]['tool'] == 'select_range'
    receipt['range'] = 'XFD1'
    result['navigation']['range'] = 'XFD1'
    assert tools.result('再次读取回执', [])['navigation']['range'] == 'A1:B2'


def test_last_navigation_controls_default_sheet_and_does_not_retarget_authority():
    tools = reader()
    tools.select_range('B2')
    tools.select_range('A1', 'First')
    assert tools.result('请求定位', [])['navigation']['sheetName'] == 'First'
    assert json.loads(tools.read_cells(['A1'])['content'])['cells']['A1']['value'] == 'first'
    assert tools.get_workbook_context()['activeSheetId'] == 'First'


@pytest.mark.parametrize(('range_', 'sheet'), [('A1', 'Unknown'), ('XFE1', None), ('A1048577', None)])
def test_invalid_navigation_never_records_target(range_, sheet):
    tools = reader()
    with pytest.raises(ValueError):
        tools.select_range(range_, sheet)
    assert 'navigation' not in tools.result('无定位', [])


def test_frozen_range_authority_cannot_be_changed_by_navigation():
    tools = reader(selection=VIEW)
    tools.select_range('$a$1')
    with pytest.raises(ValueError, match='selection_mismatch'):
        tools.select_range('B2')
    with pytest.raises(ValueError, match='selection_mismatch'):
        tools.select_range('A1', 'First')
    assert tools.result('保留授权目标', [])['navigation']['range'] == 'A1'
    with pytest.raises(ValueError):
        reader(selection=VIEW, view={**VIEW, 'sheetName': 'First'})


def test_headless_reader_does_not_advertise_or_request_navigation():
    tools = reader(view=None)
    with pytest.raises(ValueError, match='navigation_unavailable'):
        tools.select_range('A1')
    assert not tools.navigation_enabled
    with pytest.raises(ValidationError):
        NativeWorkbookReadAnswer.model_validate({'answer': 'fake', 'navigation': {'sheetName': 'First'}})


@pytest.mark.anyio
async def test_real_agno_select_range_receipt_is_pending_and_server_owns_final_target():
    model = ScriptedModel(id='navigation', expected_tool_text='navigation_requested', responses=[
        ModelResponse(tool_calls=[{'id': 'select', 'type': 'function', 'function': {
            'name': 'select_range', 'arguments': json.dumps({'range': 'b2:a1'})}}]),
        ModelResponse(content=json.dumps({'answer': '已请求定位到目标区域', 'citations': []})),
    ])
    result = await AgnoNativeWorkbookReadPlanner(model)(reader=reader(), action='ask',
        instruction='定位到A1:B2', session_id='navigate', user_id='u')
    assert result['navigation']['range'] == 'A1:B2'
    assert result['coverage']['fullyReadBlockIds'] == []


@pytest.mark.parametrize('patch', [{'startRow': -1}, {'startRow': True}, {'endColumn': 16384}, {'unknown': 1}])
def test_api_view_payload_keeps_strict_coordinate_contract(patch):
    from smart_reporting.report_editor.native_ai_api import NativeOfficeReadPayload
    with pytest.raises(ValidationError):
        NativeOfficeReadPayload.model_validate({'clientRequestId': 'nav', 'expectedSha256': 'a' * 64,
            'instruction': '定位', 'viewSelection': {**VIEW, **patch}})


def test_api_captured_view_does_not_implicitly_authorize_range_reading():
    from smart_reporting.report_editor.native_ai_api import NativeOfficeReadPayload
    payload = NativeOfficeReadPayload.model_validate({'clientRequestId': 'nav',
        'expectedSha256': 'a' * 64, 'instruction': '定位', 'selection': None, 'viewSelection': VIEW})
    assert payload.selection is None
    assert payload.view_selection.model_dump() == VIEW
