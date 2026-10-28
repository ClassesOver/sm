"""冻结事实到正文数值及溯源期间的端到端口径回归。"""

import json
from datetime import date, timedelta

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.fact_index import (
    comparison_fact_identity,
    derived_fact_identity,
    metric_fact_identity,
    reconciliation_fact_identity,
)
from smart_reporting.reporting.trace.numeric_text import frozen_number_catalog, frozen_number_guide
from smart_reporting.reporting.trace.semantic_bindings import (
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import unit_period_warnings

from .test_deterministic_analysis import analysis, context, semantic
from .test_deterministic_stock import stock_context


def stock_bundle():
    ctx = context('current', fields=('month', 'department', 'balance'), semantics=(
        {**semantic('balance', unit='元'), 'additiveAcross': ['department']},
    )).model_copy(update={'period_granularities': {'month': 'month'}})
    return build_deterministic_analysis_bundle(analysis(fields=('balance',)), (
        ('current', b'month,department,balance\n2025-01,A,100\n2025-01,B,200\n2025-02,A,110\n2025-02,B,230\n', ctx, ('current',)),
    ))


@pytest.mark.parametrize('aliases', [
    ('2025-01', '2025-02', '2025-03'),
    ('2025/1', '2025/2', '2025/3'),
    ('202501', '202502', '202503'),
])
def test_flow_metric_additive_across_sibling_period_column_sums_all_periods(aliases):
    """回放中实际收入声明可沿 period_code 相加，事实却按 data_date 统计：不能当作时点取期末值。"""
    ctx = context('current', fields=('data_date', 'period_code', 'area', 'income'), semantics=(
        {**semantic('income', unit='元'), 'additiveAcross': ['period_code', 'area']},
    )).model_copy(update={'period_granularities': {'data_date': 'date'}})
    rows = ''.join(f'2025-0{i}-01,{alias},A,{value}\n'
                   for i, (alias, value) in enumerate(zip(aliases, (100, 200, 0)), 1))
    bundle = build_deterministic_analysis_bundle(analysis(fields=('income',)), (
        ('current', ('data_date,period_code,area,income\n' + rows).encode(), ctx, ('current',)),
    ))
    fact = bundle.metrics[0]
    assert fact.period_aggregation == 'sum'
    assert fact.total == 300


@pytest.mark.parametrize('declared_birth_year', [False, True])
@pytest.mark.parametrize('additive_axis,expected,period_aggregation', [
    ('birth_year', 340, 'last'), ('data_date', 640, 'sum'),
])
def test_unrelated_birth_year_does_not_change_reporting_axis_aggregation(
    declared_birth_year, additive_axis, expected, period_aggregation,
):
    grains = {'data_date': 'date'}
    if declared_birth_year:
        grains['birth_year'] = 'year'
    ctx = context('current', fields=('data_date', 'birth_year', 'department', 'balance'), semantics=(
        {**semantic('balance', unit='元'), 'additiveAcross': [additive_axis, 'department']},
    )).model_copy(update={'period_granularities': grains, 'time_series_sort_field': 'data_date'})
    content = (b'data_date,birth_year,department,balance\n'
               b'2025-01-01,1980,A,100\n2025-01-01,1990,B,200\n'
               b'2025-02-01,1980,A,110\n2025-02-01,1990,B,230\n')
    bundle = build_deterministic_analysis_bundle(analysis(fields=('balance',)), (
        ('current', content, ctx, ('current',)),
    ))
    fact = bundle.metrics[0]
    assert fact.period_field == 'data_date'
    assert [item.value for item in fact.period_values] == [300, 340]
    assert fact.total == expected
    assert fact.period_aggregation == period_aggregation
    contents = [bundle.model_dump_json(by_alias=True)]
    token = '{{value:' + fact.fact_id + ':total:元}}'
    assert resolve_number_reference(token, contents)['value'] == expected


@pytest.mark.parametrize('alias_values', [
    ('2024-01', '2024-02', '2024-03'),
    ('2025-01', '', '2025-03'),
    ('2025-01', 'not-a-period', '2025-03'),
    ('2025-01', '2025-03', '2025-02'),
])
def test_period_named_column_requires_complete_rowwise_axis_agreement(alias_values):
    ctx = context('current', fields=('data_date', 'period_code', 'area', 'income'), semantics=(
        {**semantic('income', unit='元'), 'additiveAcross': ['period_code', 'area']},
    )).model_copy(update={'period_granularities': {'data_date': 'date', 'period_code': 'month'}})
    rows = ''.join(f'2025-0{i}-01,{alias},A,{value}\n'
                   for i, (alias, value) in enumerate(zip(alias_values, (100, 200, 0)), 1))
    bundle = build_deterministic_analysis_bundle(analysis(fields=('income',)), (
        ('current', ('data_date,period_code,area,income\n' + rows).encode(), ctx, ('current',)),
    ))
    assert bundle.metrics[0].period_aggregation == 'last'
    assert bundle.metrics[0].total == 0


@pytest.mark.parametrize('declared_grain', [False, True])
@pytest.mark.parametrize('other_values', [
    ('1980', '1980'), ('2025-02', '2025-01'), ('2025-01', ''),
    ('not-a-period', '2025-02'),
])
def test_unrelated_period_dimension_does_not_make_stock_additive(other_values, declared_grain):
    ctx = context('current', fields=('data_date', 'birth_year', 'balance'), semantics=(
        {**semantic('balance'), 'additiveAcross': ['birth_year']},
    )).model_copy(update={
        'time_series_sort_field': 'data_date',
        'period_granularities': {'data_date': 'date', **({'birth_year': 'year'} if declared_grain else {})},
    })
    content = (f'data_date,birth_year,balance\n2025-01-01,{other_values[0]},100\n'
               f'2025-02-01,{other_values[1]},200\n').encode()
    bundle = build_deterministic_analysis_bundle(analysis(fields=('balance',)), (
        ('current', content, ctx, ('current',)),
    ))
    fact = bundle.metrics[0]
    assert fact.period_field == 'data_date'
    assert [item.value for item in fact.period_values] == [100, 200]
    assert fact.total == 200
    assert fact.period_aggregation == 'last'


def test_stock_number_selection_must_preserve_endpoint_total():
    bundle = stock_bundle()
    fact = bundle.metrics[0]
    assert fact.total == 340 and fact.period_aggregation == 'last'
    contents = [bundle.model_dump_json(by_alias=True)]
    token = '{{value:' + fact.fact_id + ':total:元}}'
    text, refs, notices = render_bound_numbers('2025年1—2月资金余额为' + token + '。', contents,
                                              key='stock', field_definitions={'balance': '资金余额'})
    catalog = frozen_number_catalog(contents)
    guide = frozen_number_guide(contents, catalog)[0]
    selected = resolve_number_reference(refs[0].token, contents)
    assert text == '2025年1—2月资金余额为340元。'
    assert not notices and selected['value'] == 340
    assert selected['periods'] == ('2025-02',)
    assert '不能跨期相加' in guide['total']['meaning'] and '不得称为期末余额' in guide['total']['meaning']
    assert guide['total']['periods'] == ['2025-02']
    assert guide['total']['periodStart'] == guide['total']['periodEnd'] == '2025-02'
    assert guide['monthlyStatistics']['prefixTotals'] == []
    assert not any(':periodTotals.' in token for token in catalog)
    assert resolve_number_reference('{{value:' + fact.fact_id + ':periodTotals.0-1:元}}', contents) is None
    assert guide['monthlyStatistics']['average'] in catalog
    assert resolve_number_reference('{{value:' + fact.fact_id + ':periodChanges.1:元}}', contents)['value'] == 40


@pytest.mark.parametrize('jan,feb', [
    ('2025-01', '2025-02'), ('2025-1', '2025-2'), ('2025/01', '2025/02'),
    ('2025-1-1', '2025-2-1'),
])
@pytest.mark.parametrize('window,selector,expected', [
    ('1月', 'periodValues.0', '40元'), ('1—2月', 'total', '100元'),
])
def test_valid_alternative_month_labels_keep_their_number_reference(jan, feb, window, selector, expected):
    ctx = context('current').model_copy(update={'period_granularities': {'month': 'month'}})
    bundle = build_deterministic_analysis_bundle(analysis(), (
        ('current', f'month,department,amount\n{jan},A,40\n{feb},A,60\n'.encode(), ctx, ('current',)),
    ))
    fact = bundle.metrics[0]
    contents = [bundle.model_dump_json(by_alias=True)]
    token = '{{value:' + fact.fact_id + ':' + selector + ':元}}'
    statement = f'2025年{window}收入为'
    text, refs, notices = render_bound_numbers(statement + token + '。', contents,
                                              key='month', field_definitions={'amount': '收入'})
    assert text == statement + expected + '。' and len(refs) == 1 and not notices
    selected = resolve_number_reference(refs[0].token, contents)
    assert selected['periods'] == (('2025-01',) if window == '1月' else ('2025-01', '2025-02'))


def daily_bundle():
    fields = ('amount', 'visits')
    metrics = tuple({'code': field, 'aggregation': 'sum', 'fieldRef': semantic(field)['fieldRef']}
                    for field in fields) + ({'code': 'ratio', 'aggregation': 'ratio',
                                            'numeratorMetric': 'amount', 'denominatorMetric': 'visits'},)
    datasets = []
    for key, year, role in [('current', 2025, 'current'), ('baseline', 2024, 'yoy')]:
        ctx = context(key, fields=('month', 'department', *fields), semantics=tuple(
            semantic(field, unit='元') for field in fields
        )).model_copy(update={'period_granularities': {'month': 'date'}})
        start = date(year, 1, 1)
        rows = ''.join(f'{start + timedelta(days=i)},A,2,1\n' for i in range(32))
        datasets.append((key, ('month,department,amount,visits\n' + rows).encode(), ctx, (role,)))
    return build_deterministic_analysis_bundle(
        analysis(fields=fields).model_copy(update={'series_granularity': 'day'}), tuple(datasets),
        profile_metrics=metrics,
    )


@pytest.mark.parametrize('kind', ['comparison', 'derived'])
def test_derived_and_comparison_references_keep_daily_granularity(kind):
    bundle = daily_bundle()
    assert bundle.metrics[0].period_granularity == 'day'
    fact = bundle.comparisons[0] if kind == 'comparison' else bundle.derived_metrics[0]
    assert (fact.period_start, fact.period_end) == ('2025-01-01', '2025-02-01')
    selector = 'currentTotal:元' if kind == 'comparison' else 'value:'
    contents = [bundle.model_dump_json(by_alias=True)]
    token = '{{value:' + fact.fact_id + ':' + selector + '}}'
    selected = resolve_number_reference(token, contents)
    warnings = unit_period_warnings('2025年1月15日', expected_periods=selected['periods'])
    assert len(selected['periods']) == 32 and '2025-01-15' in selected['periods']
    assert warnings == []
    assert unit_period_warnings('2025年2月2日', expected_periods=selected['periods'])
    assert fact.period_granularity == 'day'
    loaded = DeterministicAnalysisBundle.model_validate_json(contents[0])
    restored = loaded.comparisons[0] if kind == 'comparison' else loaded.derived_metrics[0]
    assert restored.period_granularity == 'day'


@pytest.mark.parametrize('selector,unit', [
    ('total', '元'), ('average', '元'), ('minimum', '元'), ('maximum', '元'),
    ('topGroups.0', '元'), ('bottomGroups.0', '元'),
    ('groupShares.topGroups.0', '%'), ('groupGaps.0-1', '元'),
])
def test_stock_summary_selectors_reference_only_the_endpoint(selector, unit):
    bundle = stock_bundle()
    fact = bundle.metrics[0]
    token = '{{value:' + fact.fact_id + ':' + selector + ':' + unit + '}}'
    result = resolve_number_reference(token, [bundle.model_dump_json(by_alias=True)])
    assert result is not None and result['periods'] == ('2025-02',)


@pytest.mark.parametrize('stock', [False, True])
@pytest.mark.parametrize('labels', [('2025-01', '2025-02'), ('2025-1', '2025/02')])
def test_budget_windows_respect_stock_semantics_and_calendar_labels(stock, labels):
    fields = ('actual_balance', 'budget_balance')
    ctx = context('current', fields=('month', 'department', *fields), semantics=tuple(
        {**semantic(field, unit='元'), 'additiveAcross': ['department'] if stock else ['month', 'department']}
        for field in fields
    )).model_copy(update={'period_granularities': {'month': 'month'}})
    content = f'month,department,actual_balance,budget_balance\n{labels[0]},A,100,100\n{labels[1]},A,200,100\n'.encode()
    bundle = build_deterministic_analysis_bundle(analysis(fields=fields), (('current', content, ctx, ('current',)),))
    contents = [bundle.model_dump_json(by_alias=True)]
    catalog = frozen_number_catalog(contents)
    actual, budget = bundle.metrics
    monthly = '{{value:' + actual.fact_id + ':budgetComparison.' + budget.fact_id + '.2025-02.percentage:%}}'
    cumulative = '{{value:' + actual.fact_id + ':budgetComparison.' + budget.fact_id + '.2025-01..2025-02.percentage:%}}'
    selected = resolve_number_reference(monthly, contents)
    assert selected['value'] == 200 and selected['formula'] == '(200) / (100) * 100'
    if stock:
        assert cumulative not in catalog and resolve_number_reference(cumulative, contents) is None
    else:
        assert resolve_number_reference(cumulative, contents)['value'] == 150


@pytest.mark.parametrize('kind,identity', [
    ('metrics', metric_fact_identity), ('comparisons', comparison_fact_identity),
    ('derived_metrics', derived_fact_identity),
])
def test_fact_identity_distinguishes_frozen_time_granularity(kind, identity):
    fact = getattr(daily_bundle(), kind)[0]
    day = fact.model_copy(update={'period_granularity': 'day'})
    month = fact.model_copy(update={'period_granularity': 'month'})
    assert identity(day) != identity(month)
    legacy = fact.model_copy(update={'period_granularity': None})
    assert 'periodGranularity=' not in identity(legacy)


def test_stock_reconciliation_freezes_time_granularity_and_identity():
    fields = ('balance', 'ledger')
    ctx = stock_context('current', fields).model_copy(update={'period_granularities': {'month': 'month'}})
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=fields),
        (('current', b'month,department,balance,ledger\n2025-01-01,A,100,100\n', ctx, ('current',)),),
        profile_metrics=tuple({'code': field, 'aggregation': 'sum', 'fieldRef': semantic(field)['fieldRef']}
                              for field in fields),
        profile_reconciliations=({'code': 'check', 'leftMetric': 'balance', 'rightMetric': 'ledger',
                                  'grain': ['department']},),
    )
    fact = bundle.reconciliations[0]
    assert fact.period_granularity == 'month'
    contents = [bundle.model_dump_json(by_alias=True)]
    token = '{{value:' + fact.fact_id + ':difference:}}'
    assert resolve_number_reference(token, contents)['periods'] == ('2025-01',)
    assert reconciliation_fact_identity(fact) != reconciliation_fact_identity(
        fact.model_copy(update={'period_granularity': 'day'}))


def test_old_snapshot_without_derived_time_granularity_remains_readable():
    payload = daily_bundle().model_dump(mode='json', by_alias=True)
    for entry in payload['comparisons'] + payload['derivedMetrics']:
        entry.pop('periodGranularity')
    loaded = DeterministicAnalysisBundle.model_validate(payload)
    assert loaded.comparisons[0].period_granularity is None
    assert loaded.derived_metrics[0].period_granularity is None
    token = '{{value:' + loaded.comparisons[0].fact_id + ':currentTotal:元}}'
    assert resolve_number_reference(token, [json.dumps(payload)]) is not None


def test_invalid_calendar_year_does_not_abort_month_reference_review():
    payload = stock_bundle().model_dump(mode='json', by_alias=True)
    metric = payload['metrics'][0]
    metric['periodValues'][0]['period'] = '0000'
    contents = [json.dumps(payload)]
    token = '{{value:' + metric['factId'] + ':periodValues.0:元}}'
    _text, refs, notices = render_bound_numbers('2025年1月资金余额为' + token, contents,
                                               key='invalid', field_definitions={'balance': '资金余额'})
    assert not refs and notices


@pytest.mark.parametrize('statement,warns', [
    ('本期2025-01至2025-02、基期2024-01至2024-02，同比差额', False),
    ('本期2024-01至2024-02、基期2025-01至2025-02，同比差额', True),
    ('本期2025年1月至2月，基期2024年1月至2月，同比差额', False),
    ('基期2024-01和2024-02，本期2025-01和2025-02，同比变化率', False),
    ('2025-01至2025-02为本期，2024-01至2024-02为基期，同比变化率', False),
    ('本期2025-01至2025-02，与2024-01至2024-02相比的变化率', False),
    ('本期2025-01至2025-02，较2025-01至2025-02的变化率', True),
    ('本期2025-01至2024-02、基期2024-01至2025-02，同比差额', True),
])
def test_explicit_comparison_window_roles_apply_to_both_range_endpoints(statement, warns):
    warnings = unit_period_warnings(statement, expected_periods=('2025-01', '2025-02', '2024-01', '2024-02'),
        expected_period_roles={'current': ('2025-01', '2025-02'), 'baseline': ('2024-01', '2024-02')})
    assert bool(warnings) is warns


_NINE_MONTH_ROLES = {
    'current': tuple(f'2025-{month:02d}' for month in range(1, 10)),
    'baseline': tuple(f'2024-{month:02d}' for month in range(1, 10)),
}


@pytest.mark.parametrize('statement,warns', [
    # 回放：未加标签的“2025年1—9月”是本期累计窗口，不是“从1月到9月”的变化。
    ('2025年1—9月医疗收入累计95.14亿元，较2024年1—9月的84.93亿元增加10.21亿元', False),
    # “2024年同期”指与本期相同的月份，不是2024全年；年份写错仍告警。
    ('2025年1—9月全院成本累计99.12亿元，较2024年同期增加10.56亿元', False),
    ('2025年1—9月全院成本累计99.12亿元，较2023年同期增加10.56亿元', True),
    ('2024年1—9月医疗收入累计95.14亿元，较2023年1—9月增加10.21亿元', True),
])
def test_cumulative_window_and_same_period_wording_keep_comparison_roles(statement, warns):
    warnings = unit_period_warnings(
        statement, expected_periods=(*_NINE_MONTH_ROLES['current'], *_NINE_MONTH_ROLES['baseline']),
        expected_period_roles=_NINE_MONTH_ROLES,
    )
    assert bool(warnings) is warns, warnings


def test_two_point_change_still_reads_first_date_as_baseline():
    roles = {'current': ('2025-09',), 'baseline': ('2024-09',)}
    assert not unit_period_warnings('2024年9月至2025年9月增加1.2亿元', expected_periods=('2025-09', '2024-09'),
                                    expected_period_roles=roles)
    assert unit_period_warnings('2025年9月至2024年9月增加1.2亿元', expected_periods=('2025-09', '2024-09'),
                                expected_period_roles=roles)


def test_month_followed_by_value_is_not_a_day():
    # “1月17,088人次”的 17 是数值，不是 1 月 17 日。
    assert not unit_period_warnings('2024年同月对照为：1月17,088人次', expected_periods=('2024-01',),
                                    fact_value=17088)


@pytest.mark.parametrize('before,inherited', [
    # 后项未写期间时继承前文本期，不继承“较…”引出的基期日期组。
    ('实际收入较2024年1—9月的84.93亿元[[claim:a]]增长12.06%', None),
    ('与2024年同期相比增加10.56亿元[[claim:a]]，增幅11.93%', None),
    ('2025年1—9月收入95.14亿元[[claim:a]]，增幅12.02%', '2025年1月至2025年9月'),
])
def test_parallel_reference_does_not_inherit_baseline_calendar(before, inherited):
    from smart_reporting.reporting.trace.subject_builder import _reference_local_window

    local = _reference_local_window(before, '')
    assert (local.split(' ', 1)[0] if inherited else local.startswith('2024')) == (inherited or False)


def test_stated_month_count_satisfies_monthly_average_window():
    from smart_reporting.reporting.trace.reference_semantics import number_reference_warnings

    ctx = context('current', fields=('month', 'amount'), semantics=(semantic('amount', unit='元'),)).model_copy(
        update={'period_granularities': {'month': 'month'}})
    bundle = build_deterministic_analysis_bundle(analysis(), (
        ('current', b'month,amount\n2025-01,10\n2025-02,15\n2025-03,21\n', ctx, ('current',)),
    ))
    source = bundle.model_dump_json(by_alias=True)
    token = '{{value:' + bundle.metrics[0].fact_id + ':monthlyAverage:元}}'
    reference = resolve_number_reference(token, [source])
    # 极值月份不是统计窗口；紧邻数值写明的月数与完整窗口一致时不告警。
    assert not number_reference_warnings('2025年各月区间为1月10元至3月21元，3个月月均15.33元', reference)
    assert number_reference_warnings('2025年1月至2月月均15.33元', reference)


def test_unlabeled_dates_take_the_role_of_their_registered_window():
    # 回放：“2025年9月…，2024年9月为30.26亿元，变化额为-12.83亿元”中基期未写“较”。
    roles = {'current': ('2025-09',), 'baseline': ('2024-09',)}
    statement = '2025年9月预算支出记录值为17.43亿元，2024年9月为30.26亿元，变化额为-12.83亿元'
    assert not unit_period_warnings(statement, expected_periods=('2025-09', '2024-09'),
                                    expected_period_roles=roles)
    # 写明“较”时仍按基期核对。
    assert unit_period_warnings('2024年9月较2025年9月减少12.83亿元', expected_periods=('2025-09', '2024-09'),
                                expected_period_roles=roles)


@pytest.mark.parametrize('before,after,expected', [
    ('2025年1—9月为99.12亿元[[claim:a]]，较2024年同期的88.55亿元[[claim:b]]（8,855,158,732元',
     '）', '2024年1月至2024年9月 （8,855,158,732元）'),
    ('2025年9月为99.12亿元[[claim:a]]，较2024年9月的88.55亿元[[claim:b]]（8,855,158,732元',
     '）', '2024年9月 （8,855,158,732元）'),
    ('2025年1—9月为99.12亿元[[claim:a]]（9,912,000,000元',
     '）', '2025年1月至2025年9月 （9,912,000,000元）'),
    ('2025年1—9月为99.12亿元[[claim:a]]，较2024年同期增加10.57亿元[[claim:b]]（1,057,000,000元',
     '）', '2025年1月至2025年9月 （1,057,000,000元）'),
])
def test_parenthetical_restatement_inherits_the_previous_value_period(before, after, expected):
    from smart_reporting.reporting.trace.subject_builder import _reference_local_window

    assert _reference_local_window(before, after) == expected


def test_change_reference_inherits_both_periods_of_its_sentence():
    from smart_reporting.reporting.trace.subject_builder import _reference_local_window

    before = '2025年9月预算支出为17.43亿元[[claim:a]]，2024年9月为30.26亿元[[claim:b]]，变化额为-12.83亿元'
    assert _reference_local_window(before, '') == '2024年9月 ，变化额为-12.83亿元'
    assert _reference_local_window(before, '', comparison=True) == '2025年9月 2024年9月 ，变化额为-12.83亿元'


@pytest.mark.parametrize('period', ['2024年9月', '2025年8月'])
def test_parenthetical_explicit_period_overrides_previous_value_period(period):
    from smart_reporting.reporting.trace.subject_builder import _reference_local_window

    before = '2025年9月收入99.12亿元[[claim:a]]（' + period + '为88.55亿元'
    assert _reference_local_window(before, '）') == '（' + period + '为88.55亿元）'


def test_yoy_change_reference_inherits_both_complete_windows():
    from smart_reporting.reporting.trace.subject_builder import _reference_local_window

    before = '2025年1—9月收入99.12亿元[[claim:a]]，较2024年同期的88.55亿元[[claim:b]]增加10.57亿元'
    assert _reference_local_window(before, '', comparison=True) == (
        '2025年1月至2025年9月 2024年1月至2024年9月 增加10.57亿元'
    )
    assert _reference_local_window(before, '') == '2025年1月至2025年9月 增加10.57亿元'
