"""Native candidate navigation uses trusted tools, never model final JSON."""
import json
from copy import deepcopy

import pytest
from agno.agent import Agent
from agno.models.response import ModelResponse

from smart_reporting.report_editor.workbook_ai import AgnoWorkbookProposalPlanner
from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit
from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel
from smart_reporting.reporting.tests.test_workbook_native_ai import Editor, proposal, start

VIEW = {'sheetName': 'Sheet', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0}
MODEL = {'sheets': [{'name': 'First', 'cells': {'A1': {'value': 1}}},
                    {'name': 'Sheet', 'cells': {'A1': {'value': 42}}}]}


def toolkit(scope='workbook', enabled=True):
    return WorkbookAIToolkit(model=MODEL, selection=VIEW, scope=scope,
        preview=lambda _: None, navigation_enabled=enabled)


def call(name, arguments):
    return ModelResponse(tool_calls=[{'id': name, 'type': 'function', 'function': {
        'name': name, 'arguments': json.dumps(arguments)}}])


def test_tool_target_is_canonical_owned_and_changes_default_sheet():
    tools = toolkit()
    assert 'select_range' in tools.functions
    before = deepcopy(tools._model)
    receipt = tools.select_range(' $b$2 : a1 ')
    assert receipt['status'] == 'navigation_requested' and receipt['mutated'] is False
    receipt['range'] = 'XFD1'
    assert tools.navigation['range'] == 'A1:B2'
    tools.select_range('A1', 'First')
    assert tools.read_cells(['A1'])['sheetId'] == 'First'
    assert tools._model == before and tools.proposal is None


def test_legacy_and_frozen_authorization_do_not_gain_navigation_authority():
    legacy = toolkit(enabled=False)
    assert 'select_range' not in legacy.functions
    with pytest.raises(ValueError, match='navigation_unavailable'):
        legacy.select_range('A1')
    tools = toolkit(scope='range')
    tools.select_range('A1')
    for address, sheet in [('B2', None), ('A1', 'First'), ('XFE1', None)]:
        with pytest.raises(ValueError):
            tools.select_range(address, sheet)
    assert tools.navigation['range'] == 'A1'


@pytest.mark.anyio
@pytest.mark.parametrize('mixed', [False, True])
async def test_actual_agno_native_navigation_with_optional_edit_proposal(mixed):
    responses = [call('select_range', {'range': 'A1'})]
    if mixed:
        responses.append(call('propose_operations', {'operations': [
            proposal().model_dump()['operations'][0]], 'summary': '候选修改'}))
    responses.append(ModelResponse(content='已请求定位；候选尚未采纳。'))
    model = ScriptedModel(id='candidate-navigation', responses=responses)
    ai = NativeWorkbookAIService(Editor(), planner=AgnoWorkbookProposalPlanner(Agent(model=model)), enabled=True)
    try:
        job = await start(ai, navigation_enabled=True)
        result = await ai.wait_edit_status(None, job['editId'])
        assert result['status'] == 'succeeded', result
        target = result['proposal']['navigation']
        assert target == {**VIEW, 'range': 'A1'}
        assert bool(result['proposal']['operations']) is mixed
        assert not result['accepted']
        if not mixed:
            with pytest.raises(ReportingError, match='导航'):
                await ai.accept_edit(None, job['editId'], expected_sha256='a' * 64,
                    operations=[], snapshot_sha256=result['snapshotSha256'])
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_capability_is_bound_to_request_identity_without_changing_legacy_planners():
    async def planner(*args, **kwargs):
        return proposal()
    ai = NativeWorkbookAIService(Editor(), planner=planner, enabled=True)
    try:
        job = await start(ai)
        assert (await ai.wait_edit_status(None, job['editId']))['status'] == 'succeeded'
        with pytest.raises(ReportingError):
            await start(ai, navigation_enabled=True)
    finally:
        await ai.aclose()


def test_api_navigation_capability_is_strict_and_opt_in():
    from pydantic import ValidationError

    from smart_reporting.report_editor.workbook_native_ai_api import WorkbookNativeAIStartPayload
    payload = dict(clientRequestId='navigation', instruction='定位', expectedSha256='a' * 64, operations=[])
    assert WorkbookNativeAIStartPayload.model_validate(payload).navigation_enabled is False
    with pytest.raises(ValidationError):
        WorkbookNativeAIStartPayload.model_validate({**payload, 'navigationEnabled': 'true'})

@pytest.mark.anyio
async def test_workbook_navigation_view_can_span_a_full_row():
    async def planner(*args, **kwargs):
        return proposal()
    ai = NativeWorkbookAIService(Editor(), planner=planner, enabled=True)
    try:
        job = await ai.start_edit(None, client_request_id='full-row', instruction='定位并修改',
            expected_sha256='a' * 64, operations=[], selection={**VIEW, 'endColumn': 16383},
            scope='workbook', navigation_enabled=True)
        assert (await ai.wait_edit_status(None, job['editId']))['status'] == 'succeeded'
    finally:
        await ai.aclose()

@pytest.mark.anyio
async def test_model_final_json_cannot_forge_native_navigation():
    model = ScriptedModel(id='forged-navigation', responses=[ModelResponse(content=json.dumps({
        'navigation': {**VIEW, 'range': 'A1'}, 'summary': 'fake navigation'}))])
    ai = NativeWorkbookAIService(Editor(), planner=AgnoWorkbookProposalPlanner(Agent(model=model)), enabled=True)
    try:
        job = await start(ai, navigation_enabled=True)
        result = await ai.wait_edit_status(None, job['editId'])
        assert result['status'] == 'failed' and 'proposal' not in result
    finally:
        await ai.aclose()
