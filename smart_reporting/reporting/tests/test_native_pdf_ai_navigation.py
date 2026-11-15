"""PDF navigation is a trusted, authorized view request, never read evidence."""
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from agno.models.response import ModelResponse
from pydantic import ValidationError

from smart_reporting.report_editor.native_pdf_ai import (
    AgnoNativePDFTaskPlanner,
    NativePDFReadAnswer,
    NativePDFTaskReader,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests import test_native_pdf_ai_tasks as task_fixtures
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel, sample
from smart_reporting.reporting.tests.test_native_pdf_ai_tasks import payload, service

pdf_sample = task_fixtures.pdf_sample


def reader():
    context, content, model = sample()
    return NativePDFTaskReader(context, content, model)


def test_navigation_owned_target_last_request_and_no_read_or_content_mutation():
    tools = reader()
    before = deepcopy(tools.pages)
    tools.enable_navigation(tools.pages[0]['pageId'])
    receipt = tools.goto_page(2)
    assert receipt['status'] == 'navigation_requested' and receipt['mutated'] is False
    assert tools.navigation == {'page': 2, 'pageId': tools.pages[1]['pageId']}
    receipt['page'] = 100
    returned = tools.navigation
    returned['page'] = 100
    assert tools.navigation['page'] == 2
    tools.goto_page(1)
    assert tools.navigation['page'] == 1
    assert tools.pages == before and tools.coverage()['fullyReadPages'] == []
    assert tools._citation_pages == set()


@pytest.mark.parametrize('page', [True, False, 0, -1, 3, 1.5, '2', None])
def test_invalid_page_does_not_record_navigation(page):
    tools = reader()
    tools.enable_navigation(tools.pages[0]['pageId'])
    with pytest.raises(ReportingError):
        tools.goto_page(page)
    assert tools.navigation is None


def test_headless_and_selected_reader_do_not_gain_extra_authority():
    tools = reader()
    with pytest.raises(ReportingError):
        tools.goto_page(1)
    with pytest.raises(ReportingError):
        tools.enable_navigation('foreign-page')
    tools.bind_selection([{'pageId': tools.pages[0]['pageId'], 'objectId': 'object-0'}])
    tools.enable_navigation(tools.pages[0]['pageId'])
    with pytest.raises(ReportingError):
        tools.goto_page(2)
    assert tools.navigation is None
    with pytest.raises(ValidationError):
        NativePDFReadAnswer.model_validate({'answer': 'fake', 'navigation': {'page': 2}})


@pytest.mark.anyio
async def test_actual_agno_pending_navigation_has_no_body_evidence(monkeypatch):
    from smart_reporting.report_editor import native_pdf_ai as module
    context, content, material = sample()
    monkeypatch.setattr(module, 'inspect_pdf', lambda data, **kwargs: material)
    model = ScriptedModel(id='pdf-navigation', expected_tool_text='navigation_requested', responses=[
        ModelResponse(tool_calls=[{'id': 'nav', 'type': 'function', 'function': {
            'name': 'goto_page', 'arguments': json.dumps({'page': 2})}}]),
        ModelResponse(content=json.dumps({'answer': '已请求跳转', 'citations': []})),
    ])
    result = await AgnoNativePDFTaskPlanner(model)(context=context, content=content, operations=[],
        action='ask', instruction='跳到第2页', selection=[], view_page_id=material['pages'][0]['pageId'],
        session_id='navigation', user_id='u')
    assert result['navigation'] == {'page': 2, 'pageId': material['pages'][1]['pageId']}
    assert result['citations'] == [] and result['coverage']['fullyReadPages'] == []
    assert any(i['code'] == 'native_pdf_ai_no_evidence' for i in result['issues'])


@pytest.mark.anyio
async def test_view_is_passed_and_bound_to_request_identity_without_legacy_kwargs(pdf_sample):
    editor, context, session, _, _ = pdf_sample
    planner = AsyncMock(return_value={'answer': 'pending'})
    ai = service(editor, planner)
    try:
        started = await ai.start(session, **payload(context, view_page_id='page-current'))
        assert (await ai.status(session, started['taskId'], wait_ms=20000))['status'] == 'completed'
        assert planner.call_args.kwargs['view_page_id'] == 'page-current'
        with pytest.raises(ReportingError):
            await ai.start(session, **payload(context, view_page_id='other-page'))
        legacy = await ai.start(session, **payload(context, client_request_id='legacy'))
        await ai.status(session, legacy['taskId'], wait_ms=20000)
        assert 'view_page_id' not in planner.call_args.kwargs
    finally:
        await ai.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize('change', ['reorder', 'delete', 'blank'])
async def test_real_projection_navigates_effective_page_to_host_identity(pdf_sample, change):
    editor, context, session, material, source = pdf_sample
    editor.pdf_enabled = editor.pdf_text_enabled = True
    first, second = [p['pageId'] for p in material['pages']]
    if change == 'reorder':
        operations, target = [{'kind': 'reorderPages', 'pageIds': [second, first]}], second
    elif change == 'delete':
        operations, target = [{'kind': 'deletePage', 'pageId': first}], second
    else:
        operations, target = [{'kind': 'insertBlankPage', 'pageId': 'blank:navigation', 'width': 400, 'height': 300}], 'blank:navigation'
    page = 3 if change == 'blank' else 1
    model = ScriptedModel(id='projected-navigation', responses=[
        ModelResponse(tool_calls=[{'id': 'nav', 'type': 'function', 'function': {
            'name': 'goto_page', 'arguments': json.dumps({'page': page})}}]),
        ModelResponse(content=json.dumps({'answer': '已请求跳转', 'citations': []})),
    ])
    ai = service(editor, AgnoNativePDFTaskPlanner(model))
    try:
        started = await ai.start(session, **payload(context, action='ask', instruction='定位目标',
            operations=operations, view_page_id=second))
        job = await ai.status(session, started['taskId'], wait_ms=20000)
        assert job['status'] == 'completed', job
        assert job['result']['navigation'] == {'page': page, 'pageId': target}
        assert job['result']['coverage']['fullyReadPages'] == []
        assert await editor.read_file(context) == source
    finally:
        await ai.aclose()


def test_api_view_binding_is_optional_and_strict():
    from smart_reporting.report_editor.native_ai_api import NativePDFReadPayload
    data = {'clientRequestId': 'navigation', 'expectedSha256': 'a' * 64, 'operations': []}
    assert NativePDFReadPayload.model_validate(data).view_page_id is None
    for invalid in ['', True, 3, 'p' * 257]:
        with pytest.raises(ValidationError):
            NativePDFReadPayload.model_validate({**data, 'viewPageId': invalid})

@pytest.mark.anyio
@pytest.mark.parametrize('invalid', [True, '2', 2.0])
async def test_actual_agno_does_not_coerce_noninteger_navigation_arguments(monkeypatch, invalid):
    from smart_reporting.report_editor import native_pdf_ai as module
    context, content, material = sample()
    monkeypatch.setattr(module, 'inspect_pdf', lambda data, **kwargs: material)
    model = ScriptedModel(id='strict-pdf-navigation', responses=[
        ModelResponse(tool_calls=[{'id': 'invalid-nav', 'type': 'function', 'function': {
            'name': 'goto_page', 'arguments': json.dumps({'page': invalid})}}]),
        ModelResponse(content=json.dumps({'answer': '定位参数无效', 'citations': []})),
    ])
    result = await AgnoNativePDFTaskPlanner(model)(context=context, content=content, operations=[],
        action='ask', instruction='检查定位参数', selection=[], view_page_id=material['pages'][0]['pageId'],
        session_id='strict-navigation', user_id='u')
    assert 'navigation' not in result
    assert not any(event['tool'] == 'goto_page' for event in result['toolEvents'])

@pytest.mark.anyio
async def test_view_change_keeps_followup_context_for_the_same_authorized_document(pdf_sample):
    editor, context, session, _, _ = pdf_sample
    planner = AsyncMock(return_value={'answer': '第一轮已经说明目标页'})
    ai = service(editor, planner)
    try:
        first = await ai.start(session, **payload(context, action='ask', instruction='第一轮问题', view_page_id='page-one'))
        await ai.status(session, first['taskId'], wait_ms=20000)
        second = await ai.start(session, **payload(context, client_request_id='followup', action='ask',
            instruction='继续说明那一页', view_page_id='page-two', previous_task_id=first['taskId']))
        await ai.status(session, second['taskId'], wait_ms=20000)
        assert '第一轮问题' in planner.call_args.kwargs['instruction']
        assert '第一轮已经说明目标页' in planner.call_args.kwargs['instruction']
    finally:
        await ai.aclose()
