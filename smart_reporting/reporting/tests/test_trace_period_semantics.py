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


@pytest.mark.parametrize('periods', [
    ('2025-01', '2025-02', '2025-03'),
    ('2025/1', '2025/2', '2025/3'),
    ('202501', '202502', '202503'),
])
def test_flow_metric_additive_across_sibling_period_column_sums_all_periods(periods):
    """回放中实际收入声明可沿 period_code 相加，事实却按 data_date 统计：不能当作时点取期末值。"""
    ctx = context('current', fields=('data_date', 'period_code', 'area', 'income'), semantics=(
        {**semantic('income', unit='元'), 'additiveAcross': ['period_code', 'area']},
    )).model_copy(update={'period_granularities': {'data_date': 'date'}})
    bundle = build_deterministic_analysis_bundle(analysis(fields=('income',)), (
        ('current', (f'data_date,period_code,area,income\n2025-01-01,{periods[0]},A,100\n'
                     f'2025-02-01,{periods[1]},A,200\n2025-03-01,{periods[2]},A,0\n').encode(), ctx, ('current',)),
    ))
    fact = bundle.metrics[0]
    assert fact.period_aggregation is None
    assert fact.total == 300


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
    assert '期末余额' in guide['total']['meaning']
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
