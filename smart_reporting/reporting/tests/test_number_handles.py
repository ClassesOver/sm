"""短编号引用：提示边界编码、模型输出入口解码，服务端内部始终使用完整引用。"""

import json
from types import SimpleNamespace

import pytest
from agno.agent import Agent
from pydantic import ValidationError

from smart_reporting.reporting.agent import ReportingPhaseOpenAIChat
from smart_reporting.reporting.model_policy import ThinkingRequest
from smart_reporting.reporting.structured_output.execution import _validation_issues
from smart_reporting.reporting.tests.test_number_selection import source
from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import _context
from smart_reporting.reporting.trace.calc_references import CalcEvaluator
from smart_reporting.reporting.trace.number_handles import NumberHandles, compact_catalog
from smart_reporting.reporting.trace.numeric_text import (
    frozen_number_catalog,
    prompt_number_catalog,
)
from smart_reporting.reporting.trace.semantic_bindings import expand_assertion_placeholders
from smart_reporting.reporting.trace.value_references import value_reference_failure
from smart_reporting.reporting.workflow.runtime import sections
from smart_reporting.reporting.workflow.runtime.phase_models import SectionBlockContent
from smart_reporting.task_execution import TaskExecutionScope

TOTAL = '{{value:fact-bbbbbbbbbbbbbbbb:total:元}}'
SHARE = '{{value:fact-bbbbbbbbbbbbbbbb:metricShare.fact-dddddddddddddddd.2025-01..2025-02:%}}'
ASSERTION = '{{assert:assert-' + 'a' * 64 + '}}'


def test_round_trip_shares_one_handle_across_display_units():
    handles = NumberHandles()
    text = (f'合计{TOTAL}，即{{{{value:fact-bbbbbbbbbbbbbbbb:total:亿元}}}}；占比{SHARE}；{ASSERTION}；'
            '累计{{calc:ratio(fact-bbbbbbbbbbbbbbbb:periodTotals.0-1,fact-dddddddddddddddd:total):%}}。')
    encoded = handles.encode(text)
    assert encoded == ('合计{{N1:元}}，即{{N1:亿元}}；占比{{N2:%}}；{{A1}}；'
                       '累计{{calc:ratio(N3,N4):%}}。')
    assert handles.decode(encoded) == text


def test_revoked_reference_is_shown_to_the_model_as_its_own_handle():
    handles = NumberHandles()
    assert handles.encode('{{value:fact-bbbbbbbbbbbbbbbb:unverified.periodValues.0:元}}') == '{{N1:元}}'
    assert handles.decode('{{N1:元}}') == '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.0:元}}'


@pytest.mark.parametrize('written', ['{{ N1 ： 元 }}', '{{n1:元}}'])
def test_handle_spelling_is_tolerated(written):
    handles = NumberHandles()
    handles.encode(TOTAL)
    assert handles.decode(written) == TOTAL


def test_unknown_handles_never_leak_and_explain_themselves():
    handles = NumberHandles()
    handles.encode(TOTAL)
    decoded = handles.decode('合计{{N99:亿元}}，完成率{{calc:ratio({{N1:元}},N99):%}}，{{A7}}。')
    assert '{{N99' not in decoded and '{{A7}}' not in decoded
    value = decoded[decoded.index('{{value:'):decoded.index('}}') + 2]
    reason, _shown, candidates = value_reference_failure(value, frozen_number_catalog(source()))
    assert '编号不存在' in reason and candidates == []
    calc = decoded[decoded.index('{{calc:'):decoded.index(':%}}') + 4]
    assert calc == '{{calc:ratio(fact-bbbbbbbbbbbbbbbb:total,N99):%}}'
    assert CalcEvaluator(source()).failure(calc) == '引用编号不存在于本章数值目录'
    assert '证据不足' in expand_assertion_placeholders(decoded, {})
    # 纠错时回到模型原写法。
    assert handles.encode(decoded) == '合计{{N99:亿元}}，完成率{{calc:ratio(N1,N99):%}}，{{A7}}。'


def test_only_registered_identities_get_handles():
    handles = NumberHandles(frozen_number_catalog(source()))
    bogus = '{{value:fact-bbbbbbbbbbbbbbbb:bogus:元}}'
    # 未登记的完整写法原样保留，纠错事实引用的就是模型写下的原文。
    assert handles.encode(f'{bogus}{TOTAL}') == bogus + '{{N1:元}}'
    assert handles.encode('{{calc:ratio(fact-bbbbbbbbbbbbbbbb:bogus,fact-bbbbbbbbbbbbbbbb:total):%}}') == (
        '{{calc:ratio(fact-bbbbbbbbbbbbbbbb:bogus,N1):%}}')


def test_calc_accepts_selectors_with_hyphens():
    result = CalcEvaluator(source()).evaluate(
        '{{calc:ratio(fact-bbbbbbbbbbbbbbbb:periodTotals.0-1,fact-dddddddddddddddd:total):%}}')
    assert result is not None and result.text == '71.43%'


@pytest.mark.anyio
async def test_section_stage_speaks_handles_to_the_model_and_returns_full_references(monkeypatch):
    payload = {'frozenNumbers': prompt_number_catalog(frozen_number_catalog(source()))}
    instructions, issues = [], []

    class FakeExecutor:
        def __init__(self, agent):
            self.validate = getattr(agent.model, '_report_response_validator')

        async def execute(self, instruction, **_kwargs):
            instructions.append(instruction)
            catalog = json.loads(instruction)['frozenNumbers']
            # 紧凑目录：同一编号的各单位显示值以“｜”分隔，正文写 {{N编号:单位}}。
            key = next(key for key, value in catalog.items() if '100元' in value.split('｜'))
            handle = key[:-2] + ':元}}'
            # 模型先写了不存在的编号，按纠错事实改用目录中的编号。
            for markdown in ('本期合计{{N999:元}}。', f'本期合计{handle}。'):
                try:
                    return SimpleNamespace(content=self.validate({'markdown': markdown}))
                except ValidationError as error:
                    issues.append(_validation_issues(error))
            raise AssertionError('model never converged')

    monkeypatch.setattr(sections, 'ReportingStructuredOutputExecutor', FakeExecutor)
    handles = NumberHandles(frozen_number_catalog(source()))
    content = await sections._run_section_stage(
        Agent(model=ReportingPhaseOpenAIChat(id='test', api_key='test')), SectionBlockContent, 'block-1', payload,
        scope=TaskExecutionScope('task-1', 'user-1', 'thread-1', 'sandbox-1', 'section'),
        run_context=_context(),
        thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'),
        section_code='section_001',
        response_validator=sections._number_reference_validator(
            SectionBlockContent, number_contents=source(), field_definitions={}, assertions=None, handles=handles,
        ),
        number_handles=handles,
    )
    [instruction] = instructions
    assert '{{value:' not in instruction and '"{{N1}}":"' in instruction
    [[issue]] = issues
    assert '{{N999:元}}' in issue['message'] and '编号不存在' in issue['message']
    assert '{{value:' not in issue['message']
    assert content == SectionBlockContent(markdown=f'本期合计{TOTAL}。')


def test_compact_catalog_lists_each_identity_once_with_all_units():
    catalog = {
        '{{value:fact-bbbbbbbbbbbbbbbb:total:元}}': '100元',
        '{{value:fact-bbbbbbbbbbbbbbbb:total:万元}}': '0.01万元',
        '{{value:fact-bbbbbbbbbbbbbbbb:metricShare.fact-dddddddddddddddd:%}}': '71.43%',
    }
    compacted = compact_catalog(catalog)
    assert compacted == {
        '{{value:fact-bbbbbbbbbbbbbbbb:total:}}': '100元｜0.01万元',
        '{{value:fact-bbbbbbbbbbbbbbbb:metricShare.fact-dddddddddddddddd:}}': '71.43%',
    }
    handles = NumberHandles(catalog)
    assert handles.encode(json.dumps(compacted, ensure_ascii=False)) == (
        '{"{{N1}}": "100元｜0.01万元", "{{N2}}": "71.43%"}')
    # 模型按所列单位写占位符，解码回完整引用。
    assert handles.decode('{{N1:万元}}') == '{{value:fact-bbbbbbbbbbbbbbbb:total:万元}}'


def test_model_number_view_hoists_repeated_meanings_without_touching_the_payload():
    groups = [{'group': '北院', 'reference': 'r1', 'meaning': '完整分组组合'},
              {'group': '南院', 'reference': 'r2', 'meaning': '完整分组组合'}]
    shares = [{'totalFactId': 'fact-1', 'reference': 's1', 'meaning': '占比甲'},
              {'totalFactId': 'fact-2', 'reference': 's2', 'meaning': '占比乙'}]
    payload = {'numberGuide': [{'factId': 'fact-0', 'groups': groups, 'metricShares': shares}], 'other': 1}
    view = sections._model_number_view(payload)
    [item] = view['numberGuide']
    assert item['groups'] == [{'group': '北院', 'reference': 'r1'}, {'group': '南院', 'reference': 'r2'}]
    assert item['groupsMeaning'] == '完整分组组合'
    # 说明不同则保留逐项说明；服务端读取的列表字段不变。
    assert item['metricShares'] == shares and 'metricSharesMeaning' not in item
    assert payload['numberGuide'][0]['groups'] is groups and 'meaning' in groups[0]
    assert view['other'] == 1
