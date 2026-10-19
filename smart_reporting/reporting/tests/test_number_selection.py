import json

import pytest

from smart_reporting.reporting.trace.number_selection import align_number_selections
from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers


def source():
    metrics = []
    for key, field, label, year, values in (
        ('a', 'actual_income', '实际总医疗收入', 2024, (9, 11)),
        ('b', 'actual_income', '实际总医疗收入', 2025, (40, 60)),
        ('c', 'cost', '成本金额', 2025, (45, 65)),
        ('d', 'budget_income', '预算总医疗收入', 2025, (70, 70)),
    ):
        metrics.append({
            'factId': 'fact-' + key * 16, 'datasetId': f'ds-{year}',
            'datasetSha256': 'e' * 64, 'field': field, 'fieldRef': 'db.table.' + field,
            'displayName': label, 'metricCodes': [field], 'aggregation': 'sum',
            'unit': '元', 'formula': f'SUM({field})', 'scope': {},
            'periodRoles': ['current' if year == 2025 else 'yoy'],
            'periodGranularity': 'month', 'periodStart': f'{year}-01',
            'periodEnd': f'{year}-02', 'total': sum(values),
            'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
            'periodValues': [{'period': f'{year}-0{i+1}', 'value': v}
                             for i, v in enumerate(values)],
        })
    return [json.dumps({'analysisId': 'analysis_001', 'metrics': metrics})]


@pytest.mark.parametrize('before,after', [
    ('实际总医疗收入为', '，随后波动。'),
    ('实际总医疗收入区间为', '。'),
    ('实际总医疗收入为', '，至此完成。'),
    ('实际总医疗收入介于', '，之间存在差异。'),
    ('实际总医疗收入为', '。3月继续分析。'),
    ('实际总医疗收入为', '；3月继续分析。'),
    ('实际总医疗收入月份记录为', '。'),
    ('实际总医疗收入季度记录为', '。'),
    ('实际总医疗收入为', '（99月）。'),
    ('实际总医疗收入为', '（2025年2月30日）。'),
])
def test_generic_prose_and_next_sentence_cannot_supply_a_period(before, after):
    token = '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.0:元}}'
    markdown = before + token + after
    aligned, warnings = align_number_selections(markdown, source())
    assert ':unverified:' in aligned
    assert any('期间缺失' in warning for warning in warnings)
    text, refs, notices = render_bound_numbers(markdown, source(), key='periodless')
    assert '40元' not in text and '待核实' in text
    assert not refs and any(notice.kind == 'numeric_unverified' for notice in notices)


def test_valid_multi_value_interval_can_describe_monthly_range_without_calendar_labels():
    first = '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.0:元}}'
    last = '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.1:元}}'
    markdown = '实际总医疗收入介于' + first + '至' + last + '之间。'
    assert align_number_selections(markdown, source()) == (markdown, [])


@pytest.mark.parametrize('last', [
    '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.0:元}}',
    '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.99:元}}',
    '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.1:万元}}',
    '{{value:fact-cccccccccccccccc:periodValues.1:元}}',
    '{{value:fact-bbbbbbbbbbbbbbbb:total:元}}',
])
def test_unvalidated_interval_does_not_exempt_periodless_value(last):
    first = '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.0:元}}'
    aligned, warnings = align_number_selections('实际总医疗收入介于' + first + '至' + last + '。', source())
    assert first not in aligned
    assert any('期间缺失' in warning for warning in warnings)


@pytest.mark.parametrize(('statement', 'selected', 'expected', 'value'), [
    ('2025年1—2月实际总医疗收入为', 'a:periodValues.0', 'b:periodTotals.0-1', '100元'),
    ('2025年1—2月，成本金额合计', 'b:periodTotals.0-1', 'c:periodTotals.0-1', '110元'),
    ('2025年1月成本金额为', 'b:periodValues.0', 'c:periodValues.0', '45元'),
    ('2025年预算总医疗收入合计', 'b:budgetComparison.fact-dddddddddddddddd.2025-01..2025-02.difference', 'd:total', '140元'),
])
def test_explicit_metric_and_period_select_matching_frozen_value(statement, selected, expected, value):
    key, selector = selected.split(':', 1)
    token = '{{value:fact-' + key * 16 + ':' + selector + ':元}}'
    text, references, notices = render_bound_numbers(statement + token + '。', source(), key='s:b')
    expected_key, expected_selector = expected.split(':', 1)
    assert text == statement + value + '。'
    assert len(references) == 1
    assert references[0].token == '{{value:fact-' + expected_key * 16 + ':' + expected_selector + ':元}}'
    assert not notices


def test_unavailable_period_never_borrows_another_year_or_invents_value():
    token = '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.0:元}}'
    text, refs, notices = render_bound_numbers('2026年1—2月实际总医疗收入为' + token, source(), key='s:b')
    assert '9元' not in text
    assert not refs and notices


def test_directional_change_does_not_become_metric_total():
    token = '{{value:fact-bbbbbbbbbbbbbbbb:budgetComparison.fact-dddddddddddddddd.2025-01..2025-02.difference:元}}'
    text, refs, notices = render_bound_numbers('2025年1—2月实际总医疗收入较预算差额为' + token, source(), key='s:b')
    assert '-40元' in text and not notices
    assert refs[0].token == token


def test_conflicting_fact_identity_cannot_be_resolved_by_input_order():
    original = source()
    conflict = json.loads(original[0])
    conflict['metrics'][1]['total'] = 999
    conflict['metrics'][1]['periodValues'][0]['value'] = 939
    token = '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.0:元}}'
    for contents in (original + [json.dumps(conflict)], [json.dumps(conflict)] + original):
        text, refs, notices = render_bound_numbers('2025年1—2月实际总医疗收入为' + token, contents, key='s:b')
        assert not refs
        assert notices and notices[0].kind == 'numeric_unverified'
        assert '待核实' in text


def test_missing_period_selection_is_a_numeric_notice():
    token = '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.0:元}}'
    _, refs, notices = render_bound_numbers('2026年1月实际总医疗收入为' + token, source(), key='s:b')
    assert not refs
    assert notices[0].kind == 'numeric_unverified'


@pytest.mark.parametrize(('total', 'resolved'), [(110, True), (111, False)])
def test_identical_duplicate_facts_resolve_instead_of_revoking(total, resolved):
    # 回放：成本金额在多个分析中各自登记且原值相同，“1—9月成本金额合计”因候选不唯一被撤销为待核实。
    document = json.loads(source()[0])
    duplicate = {**document['metrics'][2], 'factId': 'fact-' + 'e' * 16, 'total': total,
                 'periodValues': [{'period': '2025-01', 'value': 45}, {'period': '2025-02', 'value': total - 45}]}
    document['metrics'].append(duplicate)
    token = '{{value:fact-bbbbbbbbbbbbbbbb:periodTotals.0-1:元}}'
    text, refs, _ = render_bound_numbers('2025年1—2月，成本金额合计' + token + '。', [json.dumps(document)], key='s:b')
    assert ('110元' in text and len(refs) == 1) is resolved, text


@pytest.mark.parametrize('template', [
    '实际总医疗收入为{token}，随后波动。',
    '实际总医疗收入区间为{token}。',
    '实际总医疗收入至少为{token}。',
    '实际总医疗收入介于{token}之间。',
    '实际总医疗收入为{token}。3月另行分析。',
    '实际总医疗收入月度值为{token}。',
    '实际总医疗收入当月为{token}。',
    '2025年13月实际总医疗收入为{token}。',
    '2025-13实际总医疗收入为{token}。',
])
def test_single_period_value_requires_real_period_context(template):
    token = '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.0:元}}'
    markdown = template.format(token=token)
    aligned, warnings = align_number_selections(markdown, source())
    assert ':unverified:' in aligned
    assert any('期间缺失' in warning for warning in warnings)
    text, refs, notices = render_bound_numbers(markdown, source(), key='period')
    assert '40元' not in text and '待核实' in text
    assert not refs and notices[0].kind == 'numeric_unverified'


def test_missing_display_names_does_not_skip_period_validation():
    document = json.loads(source()[0])
    for metric in document['metrics']:
        metric.pop('displayName')
    token = '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.0:元}}'
    aligned, warnings = align_number_selections('收入为' + token + '，随后波动。', [json.dumps(document)])
    assert ':unverified:' in aligned and warnings


@pytest.mark.parametrize('period', ['2025年1月', '1月', '2025-01', '2025/01'])
def test_explicit_calendar_period_is_kept(period):
    token = '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.0:元}}'
    markdown = period + '实际总医疗收入为' + token + '。'
    aligned, warnings = align_number_selections(markdown, source())
    assert aligned == markdown and not warnings


def test_explicit_daily_period_is_kept():
    document = json.loads(source()[0])
    for metric in document['metrics']:
        metric['periodGranularity'] = 'day'
        for value in metric['periodValues']:
            value['period'] += '-01'
    token = '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.0:元}}'
    markdown = '2025年1月1日实际总医疗收入为' + token + '。'
    assert align_number_selections(markdown, [json.dumps(document)]) == (markdown, [])


@pytest.mark.parametrize('other,kept', [
    ('fact-bbbbbbbbbbbbbbbb:periodValues.1', True),
    ('fact-bbbbbbbbbbbbbbbb:periodValues.0', False),
    ('fact-cccccccccccccccc:periodValues.1', False),
    ('fact-bbbbbbbbbbbbbbbb:periodValues.99', False),
])
def test_periodless_value_interval_requires_valid_endpoints_of_same_fact(other, kept):
    token = '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.0:元}}'
    markdown = '实际总医疗收入各月介于' + token + '至{{value:' + other + ':元}}。'
    aligned, warnings = align_number_selections(markdown, source())
    assert (aligned == markdown) is kept
    assert bool(warnings) is not kept


def test_later_valid_interval_does_not_exempt_an_earlier_copy_of_its_endpoint():
    first = '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.0:元}}'
    last = '{{value:fact-bbbbbbbbbbbbbbbb:periodValues.1:元}}'
    markdown = '实际总医疗收入为' + first + '，各月介于' + first + '至' + last + '。'
    aligned, warnings = align_number_selections(markdown, source())
    assert aligned.count(':unverified:') == 1
    assert '各月介于' + first + '至' + last in aligned
    assert warnings
