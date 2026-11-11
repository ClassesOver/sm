"""Word 纯阅读授权、分页证据与真实 Agno 工具循环。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import import_module, util
from io import BytesIO

import pytest
from agno.models.base import Model
from agno.models.response import ModelResponse
from docx import Document

from smart_reporting.reporting.delivery.docx_native import inspect_docx
from smart_reporting.reporting.models import ReportingError


def adapter():
    name = 'smart_reporting.report_editor.native_word_read_ai'
    assert util.find_spec(name) is not None, '缺少独立 Word 纯阅读工具'
    return import_module(name)


def document():
    return {'blocks': [
        {'blockId': 'p1', 'type': 'paragraph', 'text': '本期收入42', 'editable': False},
        {'blockId': 't1', 'type': 'table', 'text': '不能泄露的整表摘要', 'cells': [[
            {'cellId': 'c1', 'text': '授权单元格'}, {'cellId': 'c2', 'text': '秘密邻格'},
        ]]},
    ]}


def test_cell_scope_freezes_and_never_exposes_neighbours():
    source = document()
    reader = adapter().NativeWordReadTools(source, [{'blockId': 't1', 'cellId': 'c1'}])
    source['blocks'][1]['cells'][0][0]['text'] = '外部修改'
    context = reader.get_document_context()
    page = reader.read_blocks(['t1'])
    assert '授权单元格' in page['content']
    assert all(secret not in json.dumps([context, page], ensure_ascii=False)
               for secret in ['秘密邻格', 'c2', '不能泄露的整表摘要', '外部修改'])
    assert reader.search_text('秘密邻格')['matches'] == []
    assert reader.coverage()['fullyReadBlockIds'] == ['t1']
    assert not hasattr(reader, 'propose_operations')
    with pytest.raises(ReportingError):
        reader.read_blocks(['p1'])


@pytest.mark.parametrize('selection', [
    [{'blockId': 'missing'}], [{'blockId': 'p1', 'cellId': 'c1'}],
    [{'blockId': 't1', 'cellId': 'c2', 'text': '伪造'}],
    [{'blockId': 'p1'}, {'blockId': 'p1'}],
    [{'blockId': 't1'}, {'blockId': 't1', 'cellId': 'c1'}],
])
def test_invalid_selection_is_rejected(selection):
    module = adapter()
    with pytest.raises(ReportingError):
        module.NativeWordReadTools(document(), selection)


def test_actual_inspected_read_only_docx_needs_no_edit_capability():
    document = Document()
    document.add_paragraph('实际Word正文')
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = '授权实际单元格'
    table.cell(0, 1).text = '实际保密邻格'
    buffer = BytesIO()
    document.save(buffer)
    model = inspect_docx(buffer.getvalue())
    block = next(item for item in model['blocks'] if item['type'] == 'table')
    cell = block['cells'][0][0]
    cell['editable'] = False
    reader = adapter().NativeWordReadTools(model, [{'blockId': block['blockId'],
                                                  'cellId': cell['cellId']}])
    page = reader.read_blocks([block['blockId']])
    assert '授权实际单元格' in page['content']
    assert '实际保密邻格' not in page['content']
    result = reader.result('实际单元格', [block['blockId']])
    assert result['citations'] == [{'blockId': block['blockId'], 'cellId': cell['cellId'],
                                    'blockNumber': model['blocks'].index(block) + 1}]


def test_tail_page_search_and_changed_request_cannot_forge_complete_read():
    source = document()
    source['blocks'][0]['text'] = '长' * 60000
    reader = adapter().NativeWordReadTools(source)
    reader.search_text('长')
    tail = reader.read_blocks(['p1'], offset=48000)
    assert tail['nextOffset'] is None
    assert not reader.coverage()['scopeReadComplete']
    assert reader.coverage()['fullyReadBlockIds'] == []
    first = reader.read_blocks(['p1'])
    assert len(first['content']) == 24000
    reader.read_blocks(['p1', 't1'], offset=24000)
    assert reader.coverage()['fullyReadBlockIds'] == []
    reader.read_blocks(['p1'], offset=first['nextOffset'])
    assert reader.coverage()['fullyReadBlockIds'] == ['p1']
    reader.read_blocks(['t1'])
    assert reader.coverage()['scopeReadComplete']


@dataclass
class ScriptedModel(Model):
    responses: list[ModelResponse] = field(default_factory=list)

    def invoke(self, *args, **kwargs):
        messages = kwargs.get('messages', args[0] if args else [])
        if len(self.responses) == 1 and len(messages) > 2:
            assert any(m.role == 'tool' and '本期收入42' in str(m.content) for m in messages)
        return self.responses.pop(0)

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response, **kwargs):
        return response


@pytest.mark.anyio
async def test_real_agno_reads_and_server_rebuilds_citations():
    module = adapter()
    model = ScriptedModel(id='scripted', responses=[
        ModelResponse(tool_calls=[{'id': 'read', 'type': 'function', 'function': {
            'name': 'read_blocks', 'arguments': '{"block_ids":["p1"]}'}}]),
        ModelResponse(content=json.dumps({'answer': '收入42', 'citations': ['p1', 't1', 'forged']})),
    ])
    reader = module.NativeWordReadTools(document())
    result = await module.AgnoNativeWordReadPlanner(model)(reader=reader, action='summary',
        instruction='总结全文', session_id='task', user_id='user')
    assert result['answer'] == '收入42'
    assert result['citations'] == [{'blockId': 'p1', 'blockNumber': 1}]
    assert result['coverage']['fullyReadBlockIds'] == ['p1']
    assert {i['code'] for i in result['issues']} >= {
        'native_word_ai_unread_citation', 'native_word_ai_incomplete_coverage'}
    assert [event['tool'] for event in result['toolEvents']] == ['read_blocks']
    assert len(model.responses) == 2
    assert 'operations' not in result


@pytest.mark.anyio
async def test_cell_citations_are_reconstructed_and_no_read_is_soft_warning():
    module = adapter()
    reader = module.NativeWordReadTools(document(), [{'blockId': 't1', 'cellId': 'c1'}])
    reader.read_blocks(['t1'])
    model = ScriptedModel(id='scripted', responses=[ModelResponse(content=json.dumps({
        'answer': '授权单元格', 'citations': ['t1']}))])
    result = await module.AgnoNativeWordReadPlanner(model)(reader=reader, action='keyPoints',
        instruction='提取要点', session_id='task', user_id='user')
    assert result['citations'] == [{'blockId': 't1', 'cellId': 'c1', 'blockNumber': 2}]
    assert result['coverage']['scopeReadComplete']
    empty = module.NativeWordReadTools(document())
    result = await module.AgnoNativeWordReadPlanner(model)(reader=empty, action='keyPoints',
        instruction='提取要点', session_id='task2', user_id='user')
    assert result['citations'] == []
    assert 'native_word_ai_incomplete_coverage' in {i['code'] for i in result['issues']}
