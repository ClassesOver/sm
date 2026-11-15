"""Source page bounds coexist with native paging without widening read evidence."""
import json
from copy import deepcopy

import pytest
from agno.models.response import ModelResponse

from smart_reporting.report_editor.native_pdf_ai import (
    AgnoNativePDFTaskPlanner,
    NativePDFTaskReader,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel, sample


def reader():
    context, content, material = sample()
    return NativePDFTaskReader(context, content, material)


def test_source_page_bounds_single_default_inclusive_and_legacy_default():
    tools = reader()
    assert [p['pageNumber'] for p in tools.read_pages(start=2)['pages']] == [2]
    assert [p['pageNumber'] for p in tools.read_pages(start=1, end=2)['pages']] == [1]
    short = reader()
    short.pages[0]['textObjects'][0]['text'] = 'First page'
    assert [p['pageNumber'] for p in short.read_pages()['pages']] == [1, 2]
    assert [p['pageNumber'] for p in short.read_pages(start=1)['pages']] == [1]
    assert short.read_pages(start=1)['nextPage'] is None
    assert [p['pageNumber'] for p in short.read_pages(start=2, end=99)['pages']] == [2]


def test_source_pages_cap_and_continuation_preserves_requested_end():
    tools = reader()
    tools.pages = [{**deepcopy(tools.pages[1]), 'pageId': f'page-{i}'} for i in range(12)]
    assert len(tools.read_pages(start=1, end=100)['pages']) == 10
    assert tools.read_pages(start=1, end=100)['nextPage'] == 11
    tools = reader()
    first = tools.read_pages(start=1, end=1)
    assert first['next'] == {'start': 1, 'end': 1, 'text_offset': 24000}
    final = tools.read_pages(**first['next'])
    assert [p['pageNumber'] for p in final['pages']] == [1]
    assert final['next'] is None and final['nextPage'] is None
    assert tools.coverage()['fullyReadPages'] == [1]


@pytest.mark.parametrize('kwargs', [{'start': True}, {'start': '2'}, {'start': 1.5}, {'start': 0},
    {'start': 3}, {'start': 2, 'end': 1}, {'end': 2}, {'start': 1, 'end': True},
    {'start': 2, 'start_page': 1}, {'start': 1, 'page_count': 10}])
def test_invalid_and_mixed_page_bounds_reject_without_read_evidence(kwargs):
    tools = reader()
    with pytest.raises(ReportingError):
        tools.read_pages(**kwargs)
    assert tools.coverage()['fullyReadPages'] == [] and not tools.tool_events


def test_selected_read_cannot_use_source_aliases_to_read_outside_selection():
    tools = reader()
    tools.bind_selection([{'pageId': tools.pages[0]['pageId'], 'objectId': 'object-0'}])
    with pytest.raises(ReportingError):
        tools.read_pages(start=2, end=2)
    with pytest.raises(ReportingError):
        tools.read_annotations(start=1, end=1)


def test_annotation_filter_tracks_original_global_ordinals_and_exact_cursor():
    tools = reader()
    tools.pages[0]['notes'] = [{'annotationId': 'first-note', 'contents': 'not requested'}]
    tools.pages[1]['notes'][0]['contents'] = 'b' * 6500
    first = tools.read_annotations(start=2, end=2)
    assert first['total'] == 1 and first['annotations'][0]['pageNumber'] == 2
    assert first['next'] == {'offset': 0, 'text_offset': 6000, 'start': 2, 'end': 2}
    assert not tools._annotations_read
    final = tools.read_annotations(**first['next'])
    assert final['next'] is None and tools._annotations_read == {1}
    assert tools.coverage()['annotationsRead'] == 1
    assert tools.coverage()['annotationsReadComplete'] is False
    tools.read_annotations(start=1, end=1)
    assert tools.coverage()['annotationsReadComplete'] is True


@pytest.mark.parametrize('kwargs', [{'start': 0}, {'start': 2, 'end': 1}, {'end': False},
    {'start': '1'}, {'start': 1, 'end': 2.5}])
def test_annotation_bounds_fail_without_marking_requested(kwargs):
    tools = reader()
    with pytest.raises(ReportingError):
        tools.read_annotations(**kwargs)
    assert not tools._annotations_requested and not tools._annotations_read


@pytest.mark.anyio
@pytest.mark.parametrize('invalid', [True, '2', 2.0])
@pytest.mark.parametrize('tool', ['read_pages', 'read_annotations'])
async def test_actual_agno_strict_source_bounds_do_not_coerce(monkeypatch, invalid, tool):
    from smart_reporting.report_editor import native_pdf_ai as module
    context, content, material = sample()
    monkeypatch.setattr(module, 'inspect_pdf', lambda *_a, **_k: material)
    model = ScriptedModel(id='strict-source-range', responses=[
        ModelResponse(tool_calls=[{'id':'read', 'type':'function', 'function':{
            'name':tool,'arguments':json.dumps({'start':invalid})}}]),
        ModelResponse(content=json.dumps({'answer':'参数无效','citations':[]})),
    ])
    result = await AgnoNativePDFTaskPlanner(model)(context=context, content=content, operations=[],
        selection=[], action='ask', instruction='读取页面', session_id='source-range', user_id='u')
    assert result['coverage']['fullyReadPages'] == []
    assert not any(event['tool']==tool for event in result['toolEvents'])


@pytest.mark.anyio
async def test_actual_agno_uses_source_names_for_body_and_annotations(monkeypatch):
    from smart_reporting.report_editor import native_pdf_ai as module
    context, content, material = sample()
    material['pages'][0]['notes'] = [{'annotationId':'unrequested','contents':'outside annotation'}]
    monkeypatch.setattr(module, 'inspect_pdf', lambda *_a, **_k: material)
    def call(name,args):
        return ModelResponse(tool_calls=[{'id':name,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}])
    model = ScriptedModel(id='source-range', expected_tool_text='Please verify revenue', responses=[
        call('read_pages',{'start':2}),call('read_annotations',{'start':2,'end':2}),
        ModelResponse(content=json.dumps({'answer':'收入42','citations':[2]})),
    ])
    result = await AgnoNativePDFTaskPlanner(model)(context=context, content=content, operations=[],
        selection=[], action='ask', instruction='读取第2页', session_id='source-range', user_id='u')
    assert result['coverage']['fullyReadPages'] == [2]
    assert result['coverage']['annotationsRead'] == 1
    assert result['coverage']['annotationsReadComplete'] is False
    assert 'outside annotation' not in str(model.seen)


def test_review_wrappers_use_source_ranges_without_granting_unread_note_authority():
    from smart_reporting.report_editor.native_pdf_review_ai import NativePDFReviewTools
    from smart_reporting.reporting.tests.test_native_pdf_review_ai import review_tools
    tools = review_tools()
    tools.reader.pages[0]['notes'] = [{'annotationId':'unread-first','contents':'do not act'}]
    tools = NativePDFReviewTools(tools.reader)
    assert tools.read_annotations(start=2, end=2)['total'] == 1
    assert tools._read_notes == {'a' * 64}
    with pytest.raises(ReportingError):
        tools.propose_reply('unread-first', 'unauthorized')
    assert [p['pageNumber'] for p in tools.read_pages(start=2)['pages']] == [2]
    result = tools.propose_replace_text('a' * 64, 2, 'Revenue is 42.', 'Revenue is 43.', '核实金额')
    assert result['status'] == 'proposed'


def test_source_page_cap_returns_executable_cursor_that_stops_at_requested_end():
    tools = reader()
    tools.pages = [{**deepcopy(tools.pages[1]), 'pageId': f'page-{i}'} for i in range(20)]
    first = tools.read_pages(start=1, end=15)
    assert first['next'] == {'start': 11, 'end': 15, 'text_offset': 0}
    assert first['truncated'] is True and first['nextPage'] == 11
    last = tools.read_pages(**first['next'])
    assert [page['pageNumber'] for page in last['pages']] == [11, 12, 13, 14, 15]
    assert last['next'] is None and last['nextPage'] is None
    assert tools.coverage()['fullyReadPages'] == list(range(1, 16))
