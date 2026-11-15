"""Source structural DSL through actual engine previews and independent XLSX reads."""
from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from openpyxl import Workbook, load_workbook

from smart_reporting.report_editor.native_office import inspect_office, patch_office
from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit


def source_book():
    book = Workbook()
    sheet = book.active
    sheet.title = 'Source'
    for row in [(1, 10), (2, 20), (3, 30)]:
        sheet.append(row)
    sheet['C1'] = '=B3+1'
    sheet['E5'] = 'merge kept'
    sheet.merge_cells('E5:F5')
    book.create_sheet('Other')['A1'] = '=Source!B3'
    book['Other']['B1'] = 'untouched'
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


async def real_tools(source, *, scope='workbook'):
    previews = []

    async def preview(operations):
        output = await asyncio.to_thread(patch_office, 'xlsx', source, operations)
        previews.append(output)
        return {'draftSha256': hashlib.sha256(output).hexdigest()}

    tools = WorkbookAIToolkit(model=await asyncio.to_thread(inspect_office, 'xlsx', source),
        scope=scope, selection={'sheetName': 'Source', 'startRow': 0, 'endRow': 0,
            'startColumn': 0, 'endColumn': 0}, preview=preview)
    return tools, previews


@pytest.mark.anyio
@pytest.mark.parametrize(('op', 'position', 'value_address', 'value', 'formula', 'merge', 'same_address', 'same_formula'), [
    ('insert_rows', {'row': 2}, 'B3', 20, '=Source!B4', 'E6:F6', 'C1', '=B4+1'),
    ('delete_rows', {'row': 2}, 'B2', 30, '=Source!B2', 'E4:F4', 'C1', '=B2+1'),
    ('insert_cols', {'column': 'B'}, 'C2', 20, '=Source!C3', 'F5:G5', 'D1', '=C3+1'),
    ('delete_cols', {'column': 'A'}, 'A2', 20, '=Source!A3', 'D5:E5', 'B1', '=A3+1'),
])
async def test_source_row_column_dsl_previews_real_values_references_and_merges(
    op, position, value_address, value, formula, merge, same_address, same_formula,
):
    source = source_book()
    tools, previews = await real_tools(source)
    result = await tools.propose_operations([
        {'op': op, 'sheetId': 'Source', **position, 'count': 1},
    ], '调整来源行列')
    assert result['status'] == 'previewed' and result['requiresAcceptance'] is True
    assert len(previews) == 1
    edited = load_workbook(BytesIO(previews[0]))
    assert edited['Source'][value_address].value == value
    assert edited['Other']['A1'].value == formula
    assert edited['Source'][same_address].value == same_formula
    assert edited['Other']['B1'].value == 'untouched'
    assert str(edited['Source'].merged_cells) == merge
    assert load_workbook(BytesIO(source))['Source']['B2'].value == 20
    assert tools.proposal.engine_operations()[0]['kind'] == 'applyRowColumnOps'


@pytest.mark.anyio
async def test_source_multiple_structural_operations_use_current_engine_coordinates():
    source = source_book()
    tools, previews = await real_tools(source)
    await tools.propose_operations([
        {'op': 'insert_rows', 'sheetId': 'Source', 'row': 2, 'count': 1},
        {'op': 'delete_rows', 'sheetId': 'Source', 'row': 3, 'count': 1},
    ], '插入后删除原第二行')
    edited = load_workbook(BytesIO(previews[0]))
    assert edited['Source']['B2'].value is None
    assert edited['Source']['B3'].value == 30
    assert edited['Other']['A1'].value == '=Source!B3'
    assert str(edited['Source'].merged_cells) == 'E5:F5'


@pytest.mark.anyio
@pytest.mark.parametrize('operation', [
    {'op': 'insert_rows', 'row': 0, 'count': 1},
    {'op': 'insert_rows', 'row': True, 'count': 1},
    {'op': 'insert_rows', 'row': 1, 'count': True},
    {'op': 'delete_rows', 'row': 1, 'count': 1.5},
    {'op': 'insert_rows', 'row': 1},
    {'op': 'delete_rows', 'row': 1, 'count': 501},
    {'op': 'insert_rows', 'row': 1048576, 'count': 2},
    {'op': 'insert_cols', 'column': 'A', 'count': 0},
    {'op': 'delete_cols', 'column': 'XFE', 'count': 1},
    {'op': 'insert_cols', 'column': 'XFD', 'count': 2},
    {'op': 'insert_cols', 'column': 'A', 'count': 101},
    {'op': 'delete_cols', 'column': 'a', 'count': 1},
])
async def test_invalid_source_structural_input_rejected_before_preview(operation):
    preview = AsyncMock()
    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Source', 'cells': {}}]},
        scope='workbook', selection={}, preview=preview)
    with pytest.raises(ValueError, match='workbook_ai_structure_invalid'):
        await tools.propose_operations([{**operation, 'sheetId': 'Source'}], 'invalid')
    assert tools.proposal is None
    preview.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('other', [
    {'op': 'set_cell', 'sheetId': 'Source', 'address': 'A1', 'value': 9},
    {'op': 'merge_cells', 'sheetId': 'Source', 'range': 'A1:B1'},
    {'op': 'set_range', 'sheetId': 'Source', 'start': 'A1', 'values': [[9]]},
    {'op': 'clear_range', 'sheetId': 'Source', 'range': 'A1:B2'},
    {'kind': 'applyCellEdits', 'arguments': {'edits': []}},
])
@pytest.mark.parametrize('structural_first', [True, False])
async def test_source_structural_batch_cannot_mix_content_or_layout(other, structural_first):
    preview = AsyncMock()
    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Source', 'cells': {}}]},
        scope='workbook', selection={}, preview=preview)
    structural = {'op': 'insert_rows', 'sheetId': 'Source', 'row': 1, 'count': 1}
    operations = [structural, other] if structural_first else [other, structural]
    with pytest.raises(ValueError, match='workbook_ai_structure_batch_invalid'):
        await tools.propose_operations(operations, 'invalid mix')
    assert tools.proposal is None
    preview.assert_not_awaited()


@pytest.mark.anyio
async def test_selected_range_cannot_authorize_structural_operations():
    source = source_book()
    tools, previews = await real_tools(source, scope='range')
    with pytest.raises(ValueError, match='selection_mismatch'):
        await tools.propose_operations([
            {'op': 'insert_rows', 'sheetId': 'Source', 'row': 1, 'count': 1},
        ], 'scope rejected')
    assert not previews and tools.proposal is None


@pytest.mark.anyio
@pytest.mark.parametrize('range_', ['a1:b3', '$A$1:$B$3', ' B3 : a1 '])
async def test_sort_range_normalizes_actual_engine_input_and_preserves_other_content(range_):
    book = Workbook()
    for row in [(3, 'c'), (1, 'a'), (2, 'b')]:
        book.active.append(row)
    book.active.title = 'Source'
    book.active['D1'] = 'preserved'
    stream = BytesIO()
    book.save(stream)
    tools, previews = await real_tools(stream.getvalue())
    await tools.propose_operations([{'op': 'sort_range', 'sheetId': 'Source',
        'range': range_, 'byColumn': 'A', 'order': 'asc'}], 'sort')
    edited = load_workbook(BytesIO(previews[0])).active
    assert [edited.cell(row, 1).value for row in (1, 2, 3)] == [1, 2, 3]
    assert [edited.cell(row, 2).value for row in (1, 2, 3)] == ['a', 'b', 'c']
    assert edited['D1'].value == 'preserved'


@pytest.mark.anyio
@pytest.mark.parametrize('range_', ['a1:b1', '$A$1:$B$1', ' B1 : a1 '])
async def test_merge_range_normalization_retains_unrelated_existing_merges(range_):
    tools, previews = await real_tools(source_book())
    await tools.propose_operations([{'op': 'merge_cells', 'sheetId': 'Source',
        'range': range_}], 'merge')
    edited = load_workbook(BytesIO(previews[0]))
    assert {str(area) for area in edited['Source'].merged_cells.ranges} == {'A1:B1', 'E5:F5'}
    assert edited['Source']['E5'].value == 'merge kept'
    assert edited['Other']['B1'].value == 'untouched'


@pytest.mark.anyio
@pytest.mark.parametrize(('address', 'operation'), [
    ('A1048576', {'op': 'insert_rows', 'row': 1, 'count': 1}),
    ('XFD1', {'op': 'insert_cols', 'column': 'A', 'count': 1}),
])
async def test_structural_preview_rejects_shifting_stored_cell_past_excel_grid(address, operation):
    book = Workbook()
    book.active.title = 'Source'
    book.active[address] = 'must remain readable'
    stream = BytesIO()
    book.save(stream)
    source = stream.getvalue()
    tools, _ = await real_tools(source)
    with pytest.raises(ValueError):
        await tools.propose_operations([{**operation, 'sheetId': 'Source'}], 'would overflow')
    assert tools.proposal is None
    assert load_workbook(BytesIO(source))['Source'][address].value == 'must remain readable'


@pytest.mark.anyio
async def test_real_agno_structural_tool_preserves_manual_draft_through_explicit_acceptance():
    import json

    from agno.agent import Agent
    from agno.models.response import ModelResponse

    from smart_reporting.report_editor.native_models import NativeEditorContext
    from smart_reporting.report_editor.workbook_ai import AgnoWorkbookProposalPlanner
    from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
    from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel
    from smart_reporting.reporting.tests.test_workbook_native_ai import Editor

    source = source_book()

    class RealEditor(Editor):
        def __init__(self):
            super().__init__()
            raw = self.context.model_dump(by_alias=True)
            raw['sourceFile'].update(sha256=hashlib.sha256(source).hexdigest(), size=len(source))
            self.context = NativeEditorContext.model_validate(raw)

        async def read_file(self, _context):
            return source

        async def preview(self, _context, *, expected_sha256, operations):
            assert expected_sha256 == self.context.source_file.sha256
            output = await asyncio.to_thread(patch_office, 'xlsx', source, operations)
            self.previews.append(operations)
            return {'draftSha256': hashlib.sha256(output).hexdigest(),
                    'model': await asyncio.to_thread(inspect_office, 'xlsx', output)}

    def call(name, arguments, identity):
        return ModelResponse(tool_calls=[{'id': identity, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments)}}])

    model = ScriptedModel(id='source-structural', responses=[
        call('get_workbook_context', {}, 'context'),
        call('load_guide', {'guides': ['structure']}, 'guide'),
        call('propose_operations', {'operations': [
            {'op': 'insert_rows', 'sheetId': 'Source', 'row': 2, 'count': 1},
        ], 'summary': '插入第二行'}, 'propose'),
        ModelResponse(content='候选待采纳'),
    ])
    editor = RealEditor()
    ai = NativeWorkbookAIService(editor, planner=AgnoWorkbookProposalPlanner(Agent(model=model)), enabled=True)
    base = [{'kind': 'applyCellEdits', 'edits': [{'sheetName': 'Source', 'row': 1,
        'column': 3, 'writeValue': True, 'cell': {'value': 'manual draft'}}]}]
    try:
        job = await ai.start_edit(None, client_request_id='structural-tool', instruction='第二行前插入一行',
            expected_sha256=editor.context.source_file.sha256, operations=base, selection={}, scope='workbook')
        result = await ai.wait_edit_status(None, job['editId'])
        assert result['status'] == 'succeeded', result
        assert result['accepted'] is False
        assert any('manual draft' in str(message.content) for turn in model.seen for message in turn)
        accepted = await ai.accept_edit(None, job['editId'],
            expected_sha256=editor.context.source_file.sha256, operations=base,
            snapshot_sha256=result['snapshotSha256'])
        assert accepted['operations'][0] == base[0]
        output = await asyncio.to_thread(patch_office, 'xlsx', source, accepted['operations'])
        edited = load_workbook(BytesIO(output))
        assert edited['Source']['D3'].value == 'manual draft'
        assert edited['Source']['D2'].value is None
        assert edited['Source']['B3'].value == 20
        assert edited['Other']['A1'].value == '=Source!B4'
        assert load_workbook(BytesIO(source))['Source']['D2'].value is None
    finally:
        await ai.aclose()
