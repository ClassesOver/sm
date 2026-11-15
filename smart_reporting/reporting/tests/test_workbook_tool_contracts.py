"""Source tool contracts exercised against frozen, authorized workbook data."""
import asyncio

import pytest

from smart_reporting.report_editor.native_workbook_read_ai import NativeWorkbookReadTools
from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit


def toolkit(scope='workbook'):
    return WorkbookAIToolkit(model={'sheets': [
        {'name': 'First', 'cells': {'A1': {'value': 'wrong sheet'}}},
        {'name': 'Active', 'cells': {
            'A1': {'value': 7}, 'B2': {'value': 11}, 'C3': {'value': 'private'},
        }},
    ]}, scope=scope, selection={'sheetName': 'Active', 'startRow': 0, 'endRow': 1,
                               'startColumn': 0, 'endColumn': 1}, preview=None)


@pytest.mark.parametrize('address', ['a1:b2', '$A$1:$B$2', ' B2 : a1 '])
def test_read_range_accepts_source_a1_variants_and_actual_values(address):
    result = toolkit().read_range(address, 'Active')
    assert result['cells']['A1']['value'] == 7
    assert result['cells']['B2']['value'] == 11
    assert len(result['cells']) == 4


def test_omitted_sheet_uses_frozen_selection_instead_of_first_sheet():
    tools = toolkit()
    assert tools.read_range('A1')['cells']['A1']['value'] == 7
    assert tools.read_range('A1', 'First')['cells']['A1']['value'] == 'wrong sheet'
    with pytest.raises(ValueError, match='selection_mismatch'):
        tools.read_range('A1', 'Unknown')


def test_read_cells_normalizes_addresses_before_real_lookup():
    result = toolkit().read_cells([' a1 ', '$b$2'], 'Active')
    assert result['cells'] == {'A1': {'value': 7}, 'B2': {'value': 11}}


@pytest.mark.parametrize('address', ['c3:a1', '$A$1:$C$3'])
def test_normalized_range_cannot_escape_frozen_selection(address):
    with pytest.raises(ValueError, match='selection_mismatch'):
        toolkit('range').read_range(address)


def test_sparse_reader_accepts_source_range_without_leaking_other_cells():
    model = {'sheets': [{'name': 'Active', 'cells': {
        'A1': {'value': 7}, 'B2': {'value': 11}, 'C3': {'value': 'private'},
    }}]}
    reader = NativeWorkbookReadTools(model, {'sheetName': 'Active', 'startRow': 0,
        'endRow': 1, 'startColumn': 0, 'endColumn': 1})
    result = reader.read_range(' $b$2 : a1 ')
    assert 'private' not in str(result)
    assert '7' in str(result) and '11' in str(result)
    with pytest.raises(ValueError, match='selection_mismatch'):
        reader.read_range('c3:a1')


def test_alias_address_precondition_uses_actual_cell_before_preview():
    tools = toolkit()
    with pytest.raises(ValueError, match='precondition_mismatch'):
        asyncio.run(tools.propose_operations([{'op': 'set_cell', 'sheetId': 'Active',
            'address': '$a$1', 'value': 99, 'expectedValue': None}], 'replace'))
