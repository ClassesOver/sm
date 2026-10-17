"""同比日历身份、下钻完整范围与表格所选指标的端到端回归。"""

import hashlib

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.dataset_service import (
    TraceDatasetFile,
    verified_dataset_snapshot,
)
from smart_reporting.reporting.trace.drilldown_builder import build_drilldown_metrics
from smart_reporting.reporting.trace.drilldown_service import TraceDrilldownService
from smart_reporting.reporting.trace.table_builder import build_analysis_table, build_table_trace

from .test_deterministic_analysis import analysis, context, semantic


def make_dataset(name, content, fields=('amount',), role='current', aggregation='sum'):
    ctx = context(name, fields=('month', 'department', *fields),
                  semantics=tuple(semantic(field, aggregation) for field in fields),
                  sha256=hashlib.sha256(content).hexdigest())
    return name, content, ctx, (role,)


@pytest.mark.parametrize('aggregation', ['sum', 'average', 'count', 'count_distinct'])
@pytest.mark.parametrize('missing_period', [False, True])
@pytest.mark.parametrize('legacy', [False, True])
def test_base_drilldown_scope_matches_the_frozen_fact(tmp_path, aggregation, missing_period, legacy):
    content = ('month,department,amount\n2025-01,A,100\n'
               + (',B,900\n' if missing_period else '2025-02,B,900\n')).encode()
    dataset_id = 'dataset-current01'
    dataset = make_dataset(dataset_id, content, aggregation=aggregation)
    ctx = dataset[2]
    metrics = ({'code': 'income', 'aggregation': aggregation, 'fieldRef': semantic('amount')['fieldRef']},)
    bundle = build_deterministic_analysis_bundle(analysis(), (dataset,), profile_metrics=metrics)
    fact = bundle.metrics[0]
    path = tmp_path / 'snapshot.csv'
    path.write_bytes(content)
    file = TraceDatasetFile(dataset_id, path, len(content), ctx.sha256, 2)
    payload = bundle.model_dump(mode='json', by_alias=True)
    if legacy:
        payload['metrics'][0].pop('periodMissingCount')
    declarations = build_drilldown_metrics(
        bundles=(payload,),
        dataset_columns={dataset_id: ctx.fields}, profile_metrics=metrics,
        profile_dimensions=({'code': 'department', 'fieldRefs': [semantic('department')['fieldRef']]},),
        measure_semantics=ctx.metric_semantics, row_preserving_dataset_ids=(dataset_id,),
    )
    assert len(declarations) == 1
    if legacy or missing_period:
        assert declarations[0].period_start is declarations[0].period_end is None
    else:
        assert (declarations[0].period_start, declarations[0].period_end) == ('2025-01', '2025-02')
    with verified_dataset_snapshot(file) as snapshot:
        page = TraceDrilldownService(secret=b'audit').drilldown(
            snapshot, declarations[0], dimension_code='department', report_id='report', revision=1,
        )
    assert page.observed_value == fact.total and page.reconciled is True


@pytest.mark.parametrize('grain,label', [('year', '{year}'), ('month', '{year}-01'), ('day', '{year}-01-15')])
@pytest.mark.parametrize('baseline_year', [2023, 2024, 2025, 2026])
def test_yoy_requires_the_actual_previous_calendar_year(grain, label, baseline_year):
    datasets = tuple(make_dataset(name,
        f'month,department,amount\n{label.format(year=year)},A,{value}\n'.encode(), role=role)
        for name, year, value, role in [('current', 2025, 100, 'current'),
                                      ('baseline', baseline_year, 50, 'yoy')])
    bundle = build_deterministic_analysis_bundle(analysis(), datasets)
    if baseline_year == 2024:
        assert len(bundle.comparisons) == 1 and bundle.comparisons[0].change_rate == 100
    else:
        assert not bundle.comparisons
        assert any('上一年相同期间' in warning and '未生成比较' in warning for warning in bundle.warnings)
    assert len(bundle.metrics) == 2  # 错期只软告警，仍保留基础事实。


def table_bundle(duplicate_unused):
    datasets = [make_dataset('first', b'month,department,amount,visits\n2025-01,A,100,10\n',
                             fields=('amount', 'visits'))]
    if duplicate_unused:
        datasets.append(make_dataset('second', b'month,department,visits\n2025-01,B,20\n', fields=('visits',)))
    metrics = tuple({'code': field, 'aggregation': 'sum', 'fieldRef': semantic(field)['fieldRef']}
                    for field in ('amount', 'visits'))
    return build_deterministic_analysis_bundle(analysis(fields=('amount', 'visits')), tuple(datasets),
                                              profile_metrics=metrics)


@pytest.mark.parametrize('duplicate_unused', [False, True])
@pytest.mark.parametrize('mode', ['auto', 'explicit'])
def test_unselected_ambiguous_metric_does_not_remove_an_unambiguous_table(duplicate_unused, mode):
    bundle = table_bundle(duplicate_unused)
    if mode == 'auto':
        trace, markdown = build_analysis_table(bundle, fact_file_resource_id='trf-' + '0' * 20)
    else:
        trace, markdown = build_table_trace(bundle, {
            'tableId': 'income-only', 'metricCodes': ['amount'],
            'rows': [{'key': 'jan', 'period': '2025-01', 'label': '1月'}],
        }, fact_file_resource_id='trf-' + '0' * 20)
    assert '100' in markdown
    if duplicate_unused or mode == 'explicit':
        assert len(trace.column_keys) == 1


@pytest.mark.parametrize('selected_id', [None, 'first', 'second'])
def test_requested_ambiguous_metric_still_requires_an_exact_fact(selected_id):
    bundle = table_bundle(True)
    selected = next((fact for fact in bundle.metrics
                     if fact.dataset_id == selected_id and 'visits' in fact.metric_codes), None)
    spec = {'tableId': 'visits', 'metricCodes': ['visits'],
            'rows': [{'key': 'jan', 'period': '2025-01', 'label': '1月'}]}
    if selected is None:
        with pytest.raises(ReportingError, match='多条事实'):
            build_table_trace(bundle, spec, fact_file_resource_id='trf-' + '0' * 20)
    else:
        spec['factIds'] = {'visits': selected.fact_id}
        trace, _markdown = build_table_trace(bundle, spec, fact_file_resource_id='trf-' + '0' * 20)
        assert {ref.fact_key for cell in trace.cells for ref in cell.fact_refs} == {selected.fact_id}


@pytest.mark.parametrize('current,baseline', [
    (('2024', '2025'), ('2023', '2024')),
    (('2024-12', '2025-01'), ('2023-12', '2024-01')),
    (('2024-12-31', '2025-01-01'), ('2023-12-31', '2024-01-01')),
    (('0002',), ('0001',)),
])
def test_yoy_aligns_actual_previous_year_across_year_boundaries(current, baseline):
    datasets = tuple(make_dataset(name,
        ('month,department,amount\n' + ''.join(f'{label},A,{value}\n' for label in labels)).encode(), role=role)
        for name, labels, value, role in [('current', current, 100, 'current'),
                                        ('baseline', baseline, 50, 'yoy')])
    bundle = build_deterministic_analysis_bundle(analysis(), datasets)
    (comparison,) = bundle.comparisons
    assert comparison.current_total == 100 * len(current)
    assert comparison.baseline_total == 50 * len(baseline)
    assert comparison.change_rate == 100
    assert (comparison.period_start, comparison.period_end) == (current[0], current[-1])


def test_yoy_never_borrows_the_same_month_from_another_year_for_a_partial_window():
    bundle = build_deterministic_analysis_bundle(analysis(), (
        make_dataset('current', b'month,department,amount\n2025-01,A,100\n2025-02,A,200\n'),
        make_dataset('baseline', b'month,department,amount\n2024-01,A,50\n2023-02,A,10\n', role='yoy'),
    ))
    (comparison,) = bundle.comparisons
    assert (comparison.current_total, comparison.baseline_total) == (100, 50)
    assert comparison.period_start == comparison.period_end == '2025-01'
    assert any('共同连续窗口' in warning for warning in comparison.warnings)


@pytest.mark.parametrize('aggregation', ['sum', 'average', 'count', 'count_distinct'])
def test_unbounded_base_periods_keep_the_frozen_fixed_scope(tmp_path, aggregation):
    content = b'month,department,amount\n2025-01,A,100\n,A,900\n2025-01,X,9000\n'
    dataset_id = 'dataset-scoped01'
    name, raw, ctx, roles = make_dataset(dataset_id, content, aggregation=aggregation)
    ctx = ctx.model_copy(update={'metric_semantics': (semantic('amount', aggregation, scope={'department': 'A'}),)})
    metrics = ({'code': 'income', 'aggregation': aggregation, 'fieldRef': semantic('amount')['fieldRef']},)
    bundle = build_deterministic_analysis_bundle(analysis(), ((name, raw, ctx, roles),), profile_metrics=metrics)
    (declaration,) = build_drilldown_metrics(
        bundles=(bundle.model_dump(mode='json', by_alias=True),),
        dataset_columns={dataset_id: ctx.fields}, profile_metrics=metrics,
        profile_dimensions=({'code': 'department', 'fieldRefs': [semantic('department')['fieldRef']]},),
        measure_semantics=ctx.metric_semantics, row_preserving_dataset_ids=(dataset_id,),
    )
    path = tmp_path / 'scoped.csv'
    path.write_bytes(content)
    file = TraceDatasetFile(dataset_id, path, len(content), ctx.sha256, 3)
    with verified_dataset_snapshot(file) as snapshot:
        page = TraceDrilldownService(secret=b'audit').drilldown(
            snapshot, declaration, dimension_code='department', report_id='report', revision=1,
        )
    assert page.observed_value == bundle.metrics[0].total and page.reconciled is True
    assert page.fixed_scope == (('department', 'A'),)
    assert {group for group, _value in page.rows} == {'A'}


def test_ratio_drilldown_still_uses_only_its_registered_comparable_window(tmp_path):
    dataset_id = 'dataset-ratioperiod'
    content = b'month,department,amount,visits\n2025-01,A,100,10\n,A,900,1\n'
    dataset = make_dataset(dataset_id, content, fields=('amount', 'visits'))
    ctx = dataset[2]
    metrics = tuple({'code': field, 'aggregation': 'sum', 'fieldRef': semantic(field)['fieldRef']}
                    for field in ('amount', 'visits')) + ({
                        'code': 'ratio', 'aggregation': 'ratio',
                        'numeratorMetric': 'amount', 'denominatorMetric': 'visits',
                    },)
    bundle = build_deterministic_analysis_bundle(analysis(fields=('amount', 'visits')), (dataset,),
                                                 profile_metrics=metrics)
    declarations = build_drilldown_metrics(
        bundles=(bundle.model_dump(mode='json', by_alias=True),),
        dataset_columns={dataset_id: ctx.fields}, profile_metrics=metrics,
        profile_dimensions=({'code': 'department', 'fieldRefs': [semantic('department')['fieldRef']]},),
        measure_semantics=ctx.metric_semantics,
    )
    declaration = next(item for item in declarations if item.metric_code == 'ratio')
    assert declaration.period_start == declaration.period_end == '2025-01'
    path = tmp_path / 'ratio.csv'
    path.write_bytes(content)
    file = TraceDatasetFile(dataset_id, path, len(content), ctx.sha256, 2)
    with verified_dataset_snapshot(file) as snapshot:
        page = TraceDrilldownService(secret=b'audit').drilldown(
            snapshot, declaration, dimension_code='department', report_id='report', revision=1,
        )
    assert page.observed_value == bundle.derived_metrics[0].value == 10
    assert page.reconciled is True
