"""Source DSL cell preconditions must never be silently dropped before preview."""
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit


def toolkit(value=1, formula=None, *, scope='workbook'):
    cell = {'value': value, **({'formula': formula} if formula is not None else {})}
    model = {'sheets': [{'name': 'Sheet', 'cells': {'A1': cell, 'B1': {'value': 7}}}]}
    preview = AsyncMock(return_value={'draftSha256': 'a' * 64})
    tools = WorkbookAIToolkit(model=model, scope=scope, selection={
        'sheetName': 'Sheet', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0,
    }, preview=preview)
    return tools, preview, model


def operation(**fields):
    return {'op': 'set_cell', 'sheetId': 'Sheet', 'address': 'A1', 'value': 2, **fields}


@pytest.mark.anyio
@pytest.mark.parametrize(('before', 'expected'), [(1, 9), (True, 1), (1, True), (None, ''), ('1', 1)])
async def test_mismatched_scalar_rejects_before_preview_and_can_retry(before, expected):
    tools, preview, _ = toolkit(before)
    with pytest.raises(ValueError, match='precondition'):
        await tools.propose_operations([operation(expectedValue=expected)], 'conditional edit')
    preview.assert_not_awaited()
    assert tools.proposal is None
    await tools.propose_operations([operation(expectedValue=before)], 'retry with actual value')
    preview.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize('expected', [float('nan'), float('inf'), [], {}, object()])
async def test_invalid_expected_scalar_cannot_be_ignored(expected):
    tools, preview, _ = toolkit()
    with pytest.raises(ValueError, match='precondition'):
        await tools.propose_operations([operation(expectedValue=expected)], 'invalid expected')
    preview.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('expected', ['=sum(A1:B1)', 'SUM(A1:B1)', '', None, 1])
async def test_formula_expectation_is_exact_and_typed(expected):
    tools, preview, _ = toolkit(None, '=SUM(A1:B1)')
    with pytest.raises(ValueError, match='precondition'):
        await tools.propose_operations([operation(op='set_formula', formula='=3', expectedFormula=expected)], 'formula guard')
    preview.assert_not_awaited()


@pytest.mark.anyio
async def test_sequential_guards_use_prior_cell_dsl_writes_without_mutating_frozen_input():
    tools, preview, original = toolkit()
    before = deepcopy(original)
    await tools.propose_operations([
        operation(expectedValue=1),
        operation(value=3, expectedValue=2),
        operation(op='set_formula', formula='=A2'),
        operation(op='set_formula', formula='=A3', expectedFormula='=A2'),
    ], 'sequential conditional writes')
    assert original == before
    assert tools.read_cells(['A1'])['cells']['A1']['value'] == 1
    assert [op['edits'][0]['cell'] for op in tools.proposal.engine_operations()] == [
        {'value': 2}, {'value': 3}, {'value': None, 'formula': 'A2'}, {'value': None, 'formula': 'A3'},
    ]
    preview.assert_awaited_once()


@pytest.mark.anyio
async def test_later_mismatch_rejects_entire_batch_before_preview():
    tools, preview, _ = toolkit()
    with pytest.raises(ValueError, match='precondition'):
        await tools.propose_operations([operation(), operation(value=3, expectedValue=1)], 'stale second write')
    preview.assert_not_awaited()
    assert tools.proposal is None


@pytest.mark.anyio
async def test_clear_updates_later_null_precondition_and_absent_cell_matches_null():
    tools, preview, _ = toolkit()
    await tools.propose_operations([
        operation(op='clear_cell'), operation(expectedValue=None),
        operation(address='C1', expectedValue=None),
    ], 'null and missing')
    preview.assert_awaited_once()


@pytest.mark.anyio
async def test_uncertain_prefix_never_checks_conditional_write_against_stale_base():
    tools, preview, _ = toolkit()
    native = {'kind': 'applyCellEdits', 'arguments': {'edits': [
        {'sheetName': 'Sheet', 'row': 0, 'column': 0, 'writeValue': True, 'cell': {'value': 10}},
    ]}}
    with pytest.raises(ValueError, match='precondition'):
        await tools.propose_operations([native, operation(expectedValue=1)], 'unknown native prefix')
    preview.assert_not_awaited()


@pytest.mark.anyio
async def test_out_of_scope_precondition_does_not_disclose_snapshot_value():
    tools, preview, _ = toolkit(scope='range')
    with pytest.raises(ValueError, match='selection_mismatch'):
        await tools.propose_operations([operation(address='B1', expectedValue=999)], 'outside')
    preview.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('fields', [
    {'op': 'set_cell', 'expectedValue': 99},
    {'expectedValue': 99}, {'expectedFormula': '=99'},
])
async def test_native_shape_cannot_silently_discard_dsl_preconditions(fields):
    tools, preview, _ = toolkit()
    native = {'kind': 'applyCellEdits', 'arguments': {'edits': [
        {'sheetName': 'Sheet', 'row': 0, 'column': 0, 'writeValue': True, 'cell': {'value': 2}},
    ]}, **fields}
    with pytest.raises(ValueError, match='precondition|operation_invalid'):
        await tools.propose_operations([native], 'mixed wire fields')
    preview.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('fields', [
    {'expectedFormula': '=1'}, {'op': 'set_formula', 'formula': '=2', 'expectedValue': 1},
    {'op': 'clear_cell', 'expectedValue': 1},
])
async def test_wrong_cell_condition_field_is_not_silently_ignored(fields):
    tools, preview, _ = toolkit()
    with pytest.raises(ValueError, match='precondition'):
        await tools.propose_operations([operation(**fields)], 'wrong condition field')
    preview.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('scope', ['range', 'workbook'])
async def test_conditional_batch_real_engine_readback_preserves_frozen_source(scope):
    import asyncio
    import hashlib
    from io import BytesIO

    from openpyxl import Workbook, load_workbook

    from smart_reporting.report_editor.native_office import inspect_office, patch_office

    workbook = Workbook()
    workbook.active.append([42, 17, 25, 'preserve'])
    stream = BytesIO()
    workbook.save(stream)
    source = stream.getvalue()
    outputs = []

    async def preview(operations):
        edited = await asyncio.to_thread(patch_office, 'xlsx', source, operations)
        outputs.append(edited)
        return {'draftSha256': hashlib.sha256(edited).hexdigest()}

    tools = WorkbookAIToolkit(
        model=await asyncio.to_thread(inspect_office, 'xlsx', source), scope=scope,
        selection={'sheetName': 'Sheet', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0},
        preview=preview,
    )
    with pytest.raises(ValueError, match='precondition_mismatch'):
        await tools.propose_operations([operation(expectedValue=99)], 'wrong source')
    assert not outputs
    await tools.propose_operations([
        operation(value=43, expectedValue=42),
        operation(value=44, expectedValue=43),
        operation(op='set_formula', formula='=SUM(B1:C1)'),
        operation(op='set_formula', formula='=B1', expectedFormula='=SUM(B1:C1)'),
    ], 'correct sequential source checks')
    assert len(outputs) == 1
    edited = load_workbook(BytesIO(outputs[0])).active
    assert edited['A1'].value == '=B1'
    assert [edited.cell(1, c).value for c in (2, 3, 4)] == [17, 25, 'preserve']
    assert load_workbook(BytesIO(source)).active['A1'].value == 42
    assert tools.read_cells(['A1'])['cells']['A1']['value'] == 42
