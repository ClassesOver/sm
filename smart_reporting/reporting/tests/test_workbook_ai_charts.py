"""Existing-chart AI candidates: trusted draft identities and independent OOXML reads."""
from __future__ import annotations

import asyncio
import hashlib
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import pytest
from agno.agent import Agent
from agno.models.response import ModelResponse
from lxml import etree
from openpyxl import Workbook, load_workbook

from smart_reporting.report_editor.native_models import NativeEditorContext
from smart_reporting.report_editor.native_office import inspect_office, patch_office
from smart_reporting.report_editor.workbook_ai import (
    AgnoWorkbookProposalPlanner,
    WorkbookAIProposal,
)
from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit
from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel
from smart_reporting.reporting.tests.test_workbook_ai_tools import call
from smart_reporting.reporting.tests.test_workbook_native_ai import Editor

PATH = 'xl/charts/chart1.xml'


def edit(**fields):
    return {'kind': 'applyChartEdits', 'arguments': {'edits': [{'chartPath': PATH, **fields}]}}


def deletion(sheet='Sheet'):
    return {'kind': 'applyChartDeletions', 'arguments': {'deletions': [{'sheetName': sheet, 'chartPath': PATH}]}}


def chart_model():
    return {'sheets': [{'name': 'Sheet', 'cells': {}, 'charts': [
        {'chartPath': PATH, 'title': 'Same', 'kind': 'column'},
        {'chartPath': 'xl/charts/chart2.xml', 'title': 'Same', 'kind': 'column'},
    ]}]}


@pytest.mark.anyio
@pytest.mark.parametrize('operation', [edit(title='New'), deletion()])
async def test_chart_candidate_requires_explicit_acceptance(operation):
    from unittest.mock import AsyncMock

    preview = AsyncMock(return_value={'draftSha256': 'f' * 64})
    tools = WorkbookAIToolkit(model=chart_model(), scope='workbook', selection={}, preview=preview)
    assert 'chart1.xml' in str(tools.read_sheet_features())
    assert 'applyChartEdits' in str(tools.load_guide(['charts']))
    result = await tools.propose_operations([operation], 'Change the explicitly named chart')
    assert result['requiresAcceptance'] is True
    assert tools.proposal.engine_operations() == [{
        'kind': operation['kind'], **operation['arguments']}]
    preview.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize(('operation', 'model'), [
    (edit(title='New', chartPath='xl/charts/chart999.xml'), chart_model()),
    (edit(title='New', chartPath='../chart1.xml'), chart_model()),
    (edit(title='New', chartPath=None), chart_model()),
    (deletion('Other'), chart_model()),
    (edit(), chart_model()),
    (edit(seriesSet=[{'name': 'Invented', 'values': [999]}]), chart_model()),
    (edit(title='New', ignoredField=True), chart_model()),
    ({'kind': 'applyChartEdits', 'arguments': {'edits': []}}, chart_model()),
    (edit(title='New'), {'sheets': chart_model()['sheets'] * 2}),
])
async def test_untrusted_or_unsupported_chart_candidate_never_reaches_preview(operation, model):
    from unittest.mock import AsyncMock

    preview = AsyncMock()
    tools = WorkbookAIToolkit(model=model, scope='workbook', selection={}, preview=preview)
    with pytest.raises(ValueError, match='chart'):
        await tools.propose_operations([operation], 'Invalid')
    preview.assert_not_awaited()
    assert tools.proposal is None


@pytest.mark.anyio
@pytest.mark.parametrize('operation', [edit(title='New'), deletion()])
async def test_cell_range_authorization_neither_reads_nor_modifies_charts(operation):
    from unittest.mock import AsyncMock

    preview = AsyncMock()
    tools = WorkbookAIToolkit(model=chart_model(), scope='range', selection={
        'sheetName': 'Sheet', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0,
    }, preview=preview)
    assert 'chart1.xml' not in str(tools.read_sheet_features())
    with pytest.raises(ValueError, match='selection'):
        await tools.propose_operations([operation], 'Denied')
    preview.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('following', [deletion(), edit(title='Deleted target')])
async def test_deleted_chart_cannot_be_targeted_again_in_one_candidate(following):
    from unittest.mock import AsyncMock

    preview = AsyncMock()
    tools = WorkbookAIToolkit(model=chart_model(), scope='workbook', selection={}, preview=preview)
    with pytest.raises(ValueError, match='chart_target'):
        await tools.propose_operations([deletion(), following], 'Invalid repeated target')
    preview.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('fields', [
    {'legend': 'diagonal'}, {'legend': None}, {'chartType': 'invented'},
    {'dataLabels': 'invented'}, {'dataLabelPosition': 'invented'}, {'grouping': 'invented'},
    {'gridlines': 'false'}, {'gapWidthPct': True}, {'gapWidthPct': -1}, {'gapWidthPct': 501},
    {'holeSizePct': 9}, {'explosionPct': 401}, {'title': 'Bad\x00XML'},
    {'valueAxis': {'min': float('nan')}}, {'valueAxis': {'max': float('inf')}},
    {'valueAxis': {'min': True}}, {'valueAxis': {'min': 5, 'max': 2}},
    {'valueAxis': {'unknown': 2}}, {'axisTitles': {'category': 123}},
    {'seriesColors': {'0': 'red'}}, {'seriesColors': {'-1': '#112233'}},
    {'pointColors': {'0': {'NaN': '#112233'}}}, {'pointExplosions': {'0': '2'}},
    {'valueAxis': {}},
])
async def test_untyped_ai_arguments_cannot_reach_the_typescript_writer(fields):
    from unittest.mock import AsyncMock

    preview = AsyncMock()
    tools = WorkbookAIToolkit(model=chart_model(), scope='workbook', selection={}, preview=preview)
    with pytest.raises(ValueError, match='chart_format'):
        await tools.propose_operations([edit(**fields)], 'Invalid runtime value')
    preview.assert_not_awaited()


def test_chart_format_accepts_explicit_auto_axis_bounds_and_boolean_false():
    from smart_reporting.report_editor.workbook_ai_charts import validate_chart_candidates

    operation = edit(axisTitles={'category': None, 'value': 'Amount'},
        valueAxis={'min': None, 'max': 25}, gridlines=False, gapWidthPct=0,
        seriesColors={'0': '#112233'}, pointColors={'0': {'1': '#445566'}})
    validate_chart_candidates(chart_model(), [{'kind': operation['kind'], **operation['arguments']}])


def source_with_two_charts():
    book = Workbook()
    book.active.append(['Quarter', 'Amount'])
    book.active.append(['Q1', 10])
    book.active.append(['Q2', 20])
    stream = BytesIO()
    book.save(stream)
    additions = []
    for column in (3, 14):
        additions.append({'worksheetSheetName': 'Sheet', 'anchor': {
            'fromRow': 1, 'fromColumn': column, 'fromRowOffset': 0, 'fromColumnOffset': 0,
            'toRow': 15, 'toColumn': column + 8, 'toRowOffset': 0, 'toColumnOffset': 0,
        }, 'chart': {'chartType': 'column', 'title': 'Same', 'series': [{
            'name': 'Amount', 'categories': ['Q1', 'Q2'], 'values': [10, 20],
            'categoriesRef': "'Sheet'!$A$2:$A$3", 'valuesRef': "'Sheet'!$B$2:$B$3",
        }]}})
    return patch_office('xlsx', stream.getvalue(), [{'kind': 'applyChartAdditions', 'additions': additions}])


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['edit', 'delete'])
async def test_real_agno_chart_candidate_preserves_other_chart_and_manual_draft(mode):
    source = await asyncio.to_thread(source_with_two_charts)
    original_hash = hashlib.sha256(source).hexdigest()
    class RealEditor(Editor):
        def __init__(self):
            super().__init__()
            raw = self.context.model_dump(by_alias=True)
            raw['sourceFile'].update(sha256=original_hash, size=len(source))
            self.context = NativeEditorContext.model_validate(raw)

        async def preview(self, _context, *, expected_sha256, operations):
            assert expected_sha256 == original_hash
            self.previews.append(deepcopy(operations))
            output = await asyncio.to_thread(patch_office, 'xlsx', source, operations)
            return {'draftSha256': hashlib.sha256(output).hexdigest(),
                    'model': await asyncio.to_thread(inspect_office, 'xlsx', output)}

    operation = edit(title='Updated', legend='bottom', chartType='bar') if mode == 'edit' else deletion()
    model = ScriptedModel(id='scripted', responses=[
        call('read_sheet_features', {'sheetId': 'Sheet'}, 'features'),
        call('load_guide', {'guides': ['charts']}, 'guide'),
        call('propose_operations', {'operations': [operation], 'summary': 'Change chart1 only'}, 'proposal'),
        ModelResponse(content='The chart candidate awaits explicit acceptance.'),
    ])
    editor = RealEditor()
    ai = NativeWorkbookAIService(editor, planner=AgnoWorkbookProposalPlanner(Agent(model=model)), enabled=True)
    base = [{'kind': 'applyCellEdits', 'edits': [{'sheetName': 'Sheet', 'row': 4, 'column': 0,
             'writeValue': True, 'cell': {'value': 'Manual unsaved'}}]}]
    job = await ai.start_edit(None, client_request_id=mode, instruction='Change only chart1',
        expected_sha256=original_hash, operations=base, selection={}, scope='workbook')
    result = await ai.wait_edit_status(None, job['editId'])
    assert result['status'] == 'succeeded', result
    assert result['accepted'] is False
    assert any('chart2.xml' in str(m.content) for turn in model.seen for m in turn if m.role == 'tool')
    with pytest.raises(ReportingError):
        await ai.accept_edit(None, job['editId'], expected_sha256=original_hash,
            operations=[], snapshot_sha256=result['snapshotSha256'])
    accepted = await ai.accept_edit(None, job['editId'], expected_sha256=original_hash,
        operations=base, snapshot_sha256=result['snapshotSha256'])
    assert accepted['operations'][0] == base[0]
    output = await asyncio.to_thread(patch_office, 'xlsx', source, accepted['operations'])
    reopened = load_workbook(BytesIO(output))
    assert reopened.active['A5'].value == 'Manual unsaved'
    assert [reopened.active[f'B{row}'].value for row in (2, 3)] == [10, 20]
    assert len(reopened.active._charts) == (2 if mode == 'edit' else 1)
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(output)) as after:
        assert after.read('xl/charts/chart2.xml') == before.read('xl/charts/chart2.xml')
        if mode == 'edit':
            xml = etree.fromstring(after.read(PATH))
            ns = {'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
                  'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
            assert xml.xpath('//c:title//a:t/text()', namespaces=ns) == ['Updated']
            assert xml.xpath('//c:barDir/@val', namespaces=ns) == ['bar']
            assert xml.xpath('//c:legendPos/@val', namespaces=ns) == ['b']
            assert xml.xpath('//c:numCache/c:pt/c:v/text()', namespaces=ns) == ['10', '20']
        else:
            assert PATH not in after.namelist()
    assert hashlib.sha256(source).hexdigest() == original_hash
    await ai.aclose()


@pytest.mark.anyio
async def test_non_tool_planner_cannot_bypass_trusted_chart_validation():
    async def planner(*_args, **_kwargs):
        return WorkbookAIProposal.model_validate({'summary': 'Forged', 'operations': [edit(title='Fake')]})

    editor = Editor()  # Preview model contains no charts; a writable ZIP path is not authority.
    ai = NativeWorkbookAIService(editor, planner=planner, enabled=True)
    job = await ai.start_edit(None, client_request_id='forged', instruction='Edit',
        expected_sha256='a' * 64, operations=[], selection={}, scope='workbook')
    result = await ai.wait_edit_status(None, job['editId'])
    assert result['status'] == 'failed'
    assert len(editor.previews) == 1
    await ai.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize('trusted', [True, False])
async def test_report_workbook_planner_uses_the_same_frozen_chart_contract(trusted):
    from unittest.mock import AsyncMock

    from smart_reporting.report_editor.workbook_ai import ReportWorkbookAIService
    from smart_reporting.reporting.tests.test_workbook_editor import _bytes, _context, _session

    context = _context(_bytes())
    preview = AsyncMock(return_value={})

    class Workbooks:
        async def context_for_session(self, _session):
            return context

        async def snapshot_for_session(self, _session, _operations):
            return {'snapshotSha256': 'c' * 64, 'workbook': chart_model() if trusted else {'sheets': []}}

        preview_operations = preview

    async def planner(*_args, **_kwargs):
        return WorkbookAIProposal.model_validate({'summary': 'Format chart', 'operations': [edit(title='Updated')]})

    ai = ReportWorkbookAIService(Workbooks(), planner=planner)
    session = _session(context)
    job = await ai.start_edit(session, 'Format chart1', [])
    result = await ai.wait_edit_status(session, job['editId'])
    assert result['status'] == ('succeeded' if trusted else 'failed')
    assert result['accepted'] is False
    assert preview.await_count == int(trusted)
