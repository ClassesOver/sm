"""PPTX AI 表格/图表原生协议与真实工具预览。"""
import json
from importlib import import_module, util
from io import BytesIO

import pytest
from agno.agent import Agent
from agno.models.response import ModelResponse
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.report_editor.native_office import inspect_office, patch_office
from smart_reporting.report_editor.slides_ai import (
    AgnoSlidesProposalPlanner,
    SlidesAIProposal,
)
from smart_reporting.report_editor.slides_ai_tools import SlidesAIToolkit
from smart_reporting.reporting.tests.pptx_ai_fixture import ScriptedModel


def module():
    name = 'smart_reporting.report_editor.slides_ai_native_operations'
    assert util.find_spec(name), '缺少独立原生PPTX候选协议'
    return import_module(name)


@pytest.fixture
def actual():
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    table = slide.shapes.add_table(2, 2, Inches(1), Inches(1), Inches(5), Inches(2)).table
    for row, values in enumerate([['收入', '42'], ['成本', '17']]):
        for col, text in enumerate(values):
            table.cell(row, col).text = text
    slide.shapes.add_textbox(Inches(1), Inches(4), Inches(4), Inches(1)).text = '未授权秘密对象'
    stream = BytesIO()
    deck.save(stream)
    content = patch_office('pptx', stream.getvalue(), [{'kind': 'editSlides', 'charts': [{
        'slideIndex': 0, 'kind': 'bar', 'categories': ['本期'],
        'series': [{'name': '收入', 'values': [42]}, {'name': '成本', 'values': [17]}]}]}])
    model = inspect_office('pptx', content)
    for element in model['slides'][0]['elements']:
        element['editable'] = element['type'] in {'table', 'chart'}
    table = next(e for e in model['slides'][0]['elements'] if e['type'] == 'table')
    chart = next(e for e in model['slides'][0]['elements'] if e['type'] == 'chart')
    return content, model, table, chart


def candidate(table, chart):
    return {'summary': '更新实际表格和图表', 'edits': [], 'order': [0],
        'tableCells': [{'slideIndex': 0, 'elementId': table['id'], 'row': 0, 'col': 1, 'text': '43'}],
        'chartEdits': [{'slideIndex': 0, 'elementId': chart['id'], 'kind': 'line',
            'categories': ['本期'], 'series': [{'name': '收入', 'values': [43]}, {'name': '成本', 'values': [17]}]}]}


def test_actual_inspection_native_fields_validate_and_patch_without_legacy_schema_expansion(actual):
    content, deck, table, chart = actual
    assert table['tableCells'] == [['收入', '42'], ['成本', '17']]
    assert chart['chartEditSafe'] is True
    parsed = module().NativeSlidesAIProposal.model_validate(candidate(table, chart))
    clean = module().validate_native_proposal(parsed.model_dump(by_alias=True, mode='json', exclude_none=True), {}, deck)
    changed = patch_office('pptx', content, [{'kind': 'editSlides', **{k:v for k,v in clean.items() if k != 'summary'}}])
    reopened = inspect_office('pptx', changed)['slides'][0]['elements']
    assert next(e for e in reopened if e['type'] == 'table')['tableCells'][0][1] == '43'
    assert next(e for e in reopened if e['type'] == 'chart')['chartSeries'][0]['values'] == [43]
    with pytest.raises(ValueError):
        SlidesAIProposal.model_validate(candidate(table, chart))


@pytest.mark.parametrize('mutation', ['foreign', 'outOfRange', 'merged', 'tableDenied', 'chartDenied',
    'unequal', 'nan', 'bool', 'badKind', 'missingSeries', 'duplicate', 'control', 'scatter', 'combo'])
def test_native_candidates_reject_unauthorized_cells_charts_and_bad_values(actual, mutation):
    _, deck, table, chart = actual
    raw = candidate(table, chart)
    if mutation == 'foreign':
        raw['tableCells'][0]['elementId'] = 'foreign'
    elif mutation == 'outOfRange':
        raw['tableCells'][0]['col'] = 2
    elif mutation == 'merged':
        table['tableCells'][0][1] = None
    elif mutation == 'tableDenied':
        table['editable'] = False
    elif mutation == 'chartDenied':
        chart['chartEditSafe'] = False
    elif mutation == 'unequal':
        raw['chartEdits'][0]['series'][0]['values'] = [1,2]
    elif mutation == 'nan':
        raw['chartEdits'][0]['series'][0]['values'] = [float('nan')]
    elif mutation == 'bool':
        raw['tableCells'][0]['row'] = False
    elif mutation == 'badKind':
        raw['chartEdits'][0]['kind'] = 'plotly'
    elif mutation == 'missingSeries':
        del raw['chartEdits'][0]['series']
    elif mutation == 'duplicate':
        raw['tableCells'] *= 2
    elif mutation == 'control':
        raw['tableCells'][0]['text'] = 'x\x00'
    elif mutation == 'scatter':
        raw['chartEdits'][0]['kind'] = 'scatter'
    elif mutation == 'combo':
        raw['chartEdits'][0].update(kind='comboBarLine', series=[{'name':'a','values':[1]}])
    with pytest.raises(ValueError):
        module().validate_native_proposal(raw, {}, deck)


@pytest.mark.anyio
async def test_native_toolkit_reads_only_authorized_actual_data_before_real_preview(actual):
    content, deck, table, chart = actual
    previews = []
    async def preview(clean):
        previews.append(clean)
        output = patch_office('pptx', content, [{'kind':'editSlides', **{k:v for k,v in clean.items() if k!='summary'}}])
        import hashlib
        return {'draftSha256': hashlib.sha256(output).hexdigest()}
    tools = SlidesAIToolkit(deck=deck, scope='selection', current_order=[0], preview=preview)
    with pytest.raises(ValueError, match='read_required'):
        await tools.propose_operations(candidate(table, chart))
    page = tools.read_slide(0)
    assert '未授权秘密对象' not in page['content']
    assert 'chartSeries' in page['content'] and 'tableCells' in page['content']
    await tools.propose_operations(candidate(table, chart))
    assert len(previews) == 1
    assert tools.proposal.table_cells[0].text == '43'


@pytest.mark.anyio
async def test_real_agno_native_table_chart_candidate_is_registered_after_preview(actual):
    content, deck, table, chart = actual
    def call(name, args, identity):
        return ModelResponse(tool_calls=[{'id': identity, 'type':'function','function':{
            'name':name,'arguments':json.dumps(args,ensure_ascii=False)}}])
    model = ScriptedModel(id='scripted-native-chart', expected_tool_text='chartSeries', responses=[
        call('get_presentation_context',{},'context'), call('read_slide',{'slide_index':0},'read'),
        call('propose_operations',{'proposal':candidate(table,chart)},'propose'), ModelResponse(content='候选待采纳')])
    async def preview(clean):
        import hashlib
        changed = patch_office('pptx',content,[{'kind':'editSlides',**{k:v for k,v in clean.items() if k!='summary'}}])
        return {'draftSha256':hashlib.sha256(changed).hexdigest()}
    planned = await AgnoSlidesProposalPlanner(Agent(model=model)).plan_slides('按要求更新表图',
        deck=deck,scope='selection',current_order=[0],preview=preview,session_id='native-chart',user_id='user')
    assert planned.chart_edits[0].kind == 'line'
    assert '未授权秘密对象' not in str(model.seen)


@pytest.mark.anyio
async def test_denied_native_object_is_not_exposed_as_an_editable_text_fallback():
    deck = {'size': {'cx': 9525000, 'cy': 5715000}, 'slides': [{'slideIndex': 0, 'elements': [
        {'id': 'unsafe', 'type': 'chart', 'editable': True, 'chartEditSafe': False,
         'text': '不可用图表数据', 'chartSeries': [{'name': '机密', 'values': [42]}],
         'geometry': {'x': 1, 'y': 1, 'width': 20, 'height': 20}},
        {'id': 'safe', 'type': 'table', 'editable': True, 'tableCells': [['公开']],
         'text': '', 'geometry': {'x': 1, 'y': 1, 'width': 20, 'height': 20}},
    ]}]}
    async def preview(_):
        return {'draftSha256': 'a' * 64}
    tools = SlidesAIToolkit(deck=deck, scope='selection', current_order=[0], preview=preview)
    assert 'unsafe' not in json.dumps(tools.get_presentation_context())
    assert '机密' not in tools.read_slide(0)['content']


def test_native_tool_context_lists_protocol_capabilities_and_chart_kinds():
    from typing import get_args
    deck = {'size': {'cx': 9525000, 'cy': 5715000}, 'slides': [{'slideIndex': 0, 'elements': []}]}
    tools = SlidesAIToolkit(deck=deck, scope='deck', current_order=[0], preview=None)
    context = tools.get_presentation_context()
    assert context['nativeOperations'] == ['tableCells', 'chartEdits']
    assert context['supportedChartKinds'] == list(get_args(module().NativeChartKind))
    assert len(context['supportedChartKinds']) == 13
    assert 'chartEditSafe' in context['nativeCapabilityRules']
