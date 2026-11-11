"""PPTX 纯阅读冻结范围、分页证据与真实 Agno 执行。"""
from __future__ import annotations

import json
from importlib import import_module, util
from io import BytesIO

import pytest
from agno.models.response import ModelResponse
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.report_editor.native_office import inspect_office
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_word_read_ai import ScriptedModel


def adapter():
    name = 'smart_reporting.report_editor.native_slides_read_ai'
    assert util.find_spec(name) is not None, '缺少独立PPTX纯阅读工具'
    return import_module(name)


def document():
    return {'slides': [
        {'slideIndex': 0, 'notes': '保密备注', 'elements': [
            {'id': 'a', 'name': '收入', 'text': '本期收入42', 'editable': False},
            {'id': 'b', 'name': '秘密邻居', 'text': '未授权的秘密'},
            {'id': 'picture', 'type': 'picture', 'descr': '保密图片'},
        ]},
        {'slideIndex': 1, 'elements': [{'id': 'c', 'text': '第二页秘密'}]},
    ]}


def test_selection_freezes_and_reads_noneditable_text_without_leaking_neighbours():
    source = document()
    selection = [{'slideIndex': 0, 'elementId': 'a'}]
    reader = adapter().NativeSlidesReadTools(source, selection)
    source['slides'][0]['elements'][0]['text'] = '外部修改'
    selection[0]['elementId'] = 'b'
    context = reader.get_presentation_context()
    page = reader.read_slide(0)
    assert '本期收入42' in page['content']
    visible = json.dumps([context, page], ensure_ascii=False)
    assert all(secret not in visible for secret in [
        '保密备注', '秘密邻居', '未授权的秘密', '保密图片', '第二页秘密', '外部修改'])
    assert reader.coverage() == {'scope': 'selection', 'totalBlocks': 1,
        'fullyReadBlockIds': ['0'], 'scopeReadComplete': True}
    assert not hasattr(reader, 'propose_operations')
    with pytest.raises(ReportingError):
        reader.read_slide(1)
    result = reader.result('收入42', ['0', '1', 'forged'])
    assert result['citations'] == [{'slideIndex': 0, 'slideNumber': 1,
        'elements': [{'elementId': 'a', 'name': '收入'}], 'label': '第1页：收入'}]
    assert {issue['code'] for issue in result['issues']} == {'native_slides_ai_unread_citation'}


@pytest.mark.parametrize('selection', [
    'invalid', [{'slideIndex': True, 'elementId': 'a'}],
    [{'slideIndex': 0, 'elementId': 'missing'}],
    [{'slideIndex': 1, 'elementId': 'a'}],
    [{'slideIndex': 0, 'elementId': 'a', 'text': '伪造'}],
    [{'slideIndex': 0, 'elementId': 'a'}, {'slideIndex': 0, 'elementId': 'a'}],
])
def test_invalid_selection_rejected(selection):
    with pytest.raises(ReportingError):
        adapter().NativeSlidesReadTools(document(), selection)


def test_pagination_requires_contiguous_read_and_budget_scales():
    source = document()
    source['slides'][0]['elements'][0]['text'] = '长' * 60000
    reader = adapter().NativeSlidesReadTools(source)
    original_budget = reader.tool_call_budget()
    assert original_budget >= 4
    reader.get_presentation_context()
    tail = reader.read_slide(0, offset=48000)
    assert tail['nextOffset'] is None
    assert reader.coverage()['fullyReadBlockIds'] == []
    first = reader.read_slide(0)
    assert len(first['content']) == 24000
    assert reader.coverage()['fullyReadBlockIds'] == []
    reader.read_slide(0, offset=first['nextOffset'])
    assert reader.coverage()['fullyReadBlockIds'] == ['0']
    partial = reader.result('部分要点', ['0', '1'], action='keyPoints')
    assert 'native_slides_ai_incomplete_coverage' in {i['code'] for i in partial['issues']}
    reader.read_slide(1)
    assert reader.coverage()['scopeReadComplete']
    source['slides'][0]['elements'][0]['text'] *= 10
    assert adapter().NativeSlidesReadTools(source).tool_call_budget() > original_budget
    with pytest.raises(ValueError):
        reader.read_slide(0, offset=True)


def test_context_is_paginated_and_does_not_count_as_read():
    source = {'slides': [{'slideIndex': index, 'elements': [
        {'id': f'e{index}', 'text': f'正文{index}'}]} for index in range(120)]}
    reader = adapter().NativeSlidesReadTools(source, [])
    first = reader.get_presentation_context()
    assert len(first['slides']) == 100
    second = reader.get_presentation_context(offset=first['nextOffset'])
    assert len(second['slides']) == 20 and second['nextOffset'] is None
    assert reader.coverage()['fullyReadBlockIds'] == []
    assert reader.coverage()['scope'] == 'document'


def test_actual_pptx_engine_text_evidence_and_limitations():
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = '实际PPTX正文'
    slide.shapes.add_table(1, 1, Inches(1), Inches(3), Inches(3), Inches(1)).table.cell(0, 0).text = '实际表格'
    slide.notes_slide.notes_text_frame.text = '不应声称读取的备注'
    buffer = BytesIO()
    presentation.save(buffer)
    model = inspect_office('pptx', buffer.getvalue())
    reader = adapter().NativeSlidesReadTools(model)
    page = reader.read_slide(0)
    assert '实际PPTX正文' in page['content']
    assert '不应声称读取的备注' not in page['content']
    assert reader.get_presentation_context()['limitations']
    assert reader.result('实际正文', ['0'])['citations'][0]['slideNumber'] == 1


@pytest.mark.anyio
async def test_real_agno_reads_and_server_rebuilds_verified_citations():
    module = adapter()
    model = ScriptedModel(id='scripted', responses=[
        ModelResponse(tool_calls=[{'id': 'read', 'type': 'function', 'function': {
            'name': 'read_slide', 'arguments': '{"slide_index":0}'}}]),
        ModelResponse(content=json.dumps({'answer': '收入42', 'citations': ['0', '1', 'forged']})),
    ])
    reader = module.NativeSlidesReadTools(document(), [{'slideIndex': 0, 'elementId': 'a'}])
    result = await module.AgnoNativeSlidesReadPlanner(model)(reader=reader, action='summary',
        instruction='总结所选对象', session_id='task', user_id='user')
    assert result['answer'] == '收入42'
    assert result['coverage']['scopeReadComplete']
    assert result['citations'][0]['elements'] == [{'elementId': 'a', 'name': '收入'}]
    assert [event['tool'] for event in result['toolEvents']] == ['read_slide']
    assert len(model.responses) == 2
    assert 'operations' not in result


def test_nontext_selection_reports_no_evidence_and_never_claims_all_content():
    reader = adapter().NativeSlidesReadTools(document(), [{'slideIndex': 0, 'elementId': 'picture'}])
    result = reader.result('无文字依据', ['0'], action='summary')
    assert result['citations'] == []
    assert 'native_slides_ai_no_evidence' in {issue['code'] for issue in result['issues']}
    assert result['limitations']
