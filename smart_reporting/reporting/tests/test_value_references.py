"""数值引用失败只诊断不改写：给出原因、所在语句与可用引用，由模型纠正。"""

import pytest

from smart_reporting.reporting.tests.test_number_selection import source
from smart_reporting.reporting.trace.value_references import (
    number_reference_failures,
    reference_failure_message,
    value_reference_failure,
)

_SHARE = '{{value:fact-0123456789abcdef:metricShare.fact-fedcba9876543210.2025-01..2025-09:%}}'
CATALOG = {
    '{{value:fact-0123456789abcdef:total:元}}': '2,713,908,213元',
    '{{value:fact-0123456789abcdef:total:亿元}}': '27.14亿元',
    '{{value:fact-0123456789abcdef:periodValues.0:亿元}}': '3.02亿元',
    _SHARE: '27.47%',
}


@pytest.mark.parametrize('written,expected', [
    ('{{value:0123456789ABCDEF:total:亿}}', '{{value:fact-0123456789abcdef:total:亿元}}'),
    ('{{value:fact-0123456789abcdef:metricShare.fedcba9876543210.2025-1—2025-9:百分比}}', _SHARE),
])
def test_spelling_variants_are_suggested_not_rewritten(written, expected):
    reason, shown, candidates = value_reference_failure(written, CATALOG)
    assert '写法不规范' in reason and shown is None and candidates == [expected]


@pytest.mark.parametrize('written,reason_part,first', [
    ('{{value:fact-0123456789abcdef:periodTotals.0-8:亿元}}', '取值方式', '{{value:fact-0123456789abcdef:total:亿元}}'),
    ('{{value:fact-0123456789abcdef:total:人次}}', '显示单位', '{{value:fact-0123456789abcdef:total:元}}'),
])
def test_unregistered_selection_lists_same_fact_alternatives(written, reason_part, first):
    reason, _shown, candidates = value_reference_failure(written, CATALOG)
    assert reason_part in reason and 'fact-' not in reason
    assert candidates[0] == first


def test_unknown_fact_and_revoked_reference():
    reason, _shown, candidates = value_reference_failure('{{value:fact-ffffffffffffffff:total:亿元}}', CATALOG)
    assert '不在' in reason and candidates == []
    reason, shown, _ = value_reference_failure(
        '{{value:fact-0123456789abcdef:unverified.periodValues.0:亿元}}', CATALOG)
    assert shown == '3.02亿元' and '不一致' in reason


def test_failures_quote_the_model_wording_and_statement():
    markdown = (
        '实际总医疗收入为{{value:fact-bbbbbbbbbbbbbbbb:unverified.periodValues.0:元}}，随后波动。'
        '本期合计{{value:fact-bbbbbbbbbbbbbbbb:bogus:元}}。'
        '完成率{{calc:ratio(fact-bbbbbbbbbbbbbbbb:total,fact-ffffffffffffffff:total):%}}。'
        '有效{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。'
    )
    revoked, unregistered, calc = number_reference_failures(markdown, source())
    # 交回模型时还原为模型自己的写法，不暴露服务端撤销标记。
    assert revoked['reference'] == '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.0:元}}'
    assert 'unverified' not in revoked['statement'] and revoked['currentValue'] == '40元'
    assert unregistered['candidates'][0] == {'reference': '{{value:fact-bbbbbbbbbbbbbbbb:total:元}}', 'value': '100元'}
    assert calc['reason'].startswith('计算引用无法求值') and '登记数值' in calc['reason']
    message = reference_failure_message(unregistered)
    assert unregistered['reference'] in message and '{{value:fact-bbbbbbbbbbbbbbbb:total:元}}=100元' in message
    assert '不得写待核实' in message
    assert '对齐提示：口径不符' in reference_failure_message(revoked, ['口径不符'])


def test_valid_references_produce_no_failures():
    assert number_reference_failures('合计{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。', source()) == []
