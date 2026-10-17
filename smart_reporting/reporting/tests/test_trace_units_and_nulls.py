"""跨单位计算、比较操作数期间和缺失观测的端到端回归。"""

import hashlib
import json

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.contracts_v1 import DrilldownMetricV1
from smart_reporting.reporting.trace.dataset_service import (
    TraceDatasetFile,
    verified_dataset_snapshot,
)
from smart_reporting.reporting.trace.drilldown_builder import build_drilldown_metrics
from smart_reporting.reporting.trace.drilldown_service import TraceDrilldownService
from smart_reporting.reporting.trace.fact_index import (
    comparison_fact_identity,
    derived_fact_identity,
)
from smart_reporting.reporting.trace.semantic_bindings import (
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import claim_status

from .test_deterministic_analysis import analysis, context, semantic


def base_metrics(*fields):
    return tuple({'code': field, 'aggregation': 'sum', 'fieldRef': semantic(field)['fieldRef']}
                 for field in fields)


@pytest.mark.parametrize('left_unit,right_unit,left,right', [
    ('万元', '元', 100, 1000000), ('元', '万元', 1000000, 100),
    ('人次', '万人次', 10000, 1), ('元', '元', 100, 100),
    ('亿元', '万元', 1, 10000), ('万人次', '人次', 1, 10000),
])
def test_derived_ratio_normalizes_compatible_units(tmp_path, left_unit, right_unit, left, right):
    fields = ('actual', 'budget')
    dataset_id = 'dataset-unitratio01'
    content = f'month,department,actual,budget\n2025-01,A,{left},{right}\n'.encode()
    ctx = context(dataset_id, fields=('month', 'department', *fields),
                  sha256=hashlib.sha256(content).hexdigest(), semantics=(
        semantic('actual', unit=left_unit), semantic('budget', unit=right_unit),
    ))
    metrics = base_metrics(*fields) + ({'code': 'execution', 'aggregation': 'ratio',
                                      'numeratorMetric': 'actual', 'denominatorMetric': 'budget'},)
    bundle = build_deterministic_analysis_bundle(analysis(fields=fields),
        ((dataset_id, content, ctx, ('current',)),), profile_metrics=metrics)
    ratio = bundle.derived_metrics[0]
    contents = [bundle.model_dump_json(by_alias=True)]
    token = '{{value:' + ratio.fact_id + ':percentage:%}}'
    rendered, refs, notices = render_bound_numbers('预算执行率为' + token + '。', contents, key='ratio')
    assert ratio.value == 1 and ratio.percentage == 100
    assert ratio.numerator == ratio.denominator and ratio.difference == 0
    assert ratio.unit == left_unit
    assert rendered == '预算执行率为100.00%。' and refs and not notices
    declarations = build_drilldown_metrics(
        bundles=(bundle.model_dump(mode='json', by_alias=True),),
        dataset_columns={dataset_id: ctx.fields}, profile_metrics=metrics,
        profile_dimensions=({'code': 'department', 'fieldRefs': [semantic('department')['fieldRef']]},),
        measure_semantics=ctx.metric_semantics,
    )
    declaration = next(item for item in declarations if item.metric_code == 'execution')
    assert declaration.denominator_scale == ratio.denominator_scale
    # 倍率随冻结声明持久化，重新读取后的分页及总体复算也必须一致。
    declaration = DrilldownMetricV1.model_validate_json(declaration.model_dump_json(by_alias=True))
    path = tmp_path / 'ratio.csv'
    path.write_bytes(content)
    file = TraceDatasetFile(dataset_id, path, len(content), ctx.sha256, 1)
    service = TraceDrilldownService(secret=b'unit-test')
    with verified_dataset_snapshot(file) as snapshot:
        page = service.drilldown(snapshot, declaration, dimension_code='department', report_id='r', revision=1)
        fallback = service._observed_value(service._fixed_scope(
            service._validated_scan(snapshot, declaration, 'department'), declaration), declaration)
    assert page.observed_value == fallback == 1 and page.reconciled is True
    assert page.rows == (('A', 1),)


@pytest.mark.parametrize('current_unit,baseline_unit,current_value,baseline_value', [
    ('万元', '元', 100, 1000000), ('元', '万元', 1000000, 100),
    ('人次', '万人次', 10000, 1), ('元', '元', 100, 100),
])
def test_yoy_normalizes_units_before_changes(current_unit, baseline_unit, current_value, baseline_value):
    datasets = tuple((name, f'month,department,amount\n{year}-01,A,{value}\n'.encode(),
                      context(name, semantics=(semantic('amount', unit=unit),)), (role,))
                     for name, year, value, unit, role in (
                         ('current', 2025, current_value, current_unit, 'current'),
                         ('baseline', 2024, baseline_value, baseline_unit, 'yoy'),
                     ))
    bundle = build_deterministic_analysis_bundle(analysis(), datasets)
    comparison = bundle.comparisons[0]
    assert comparison.change == comparison.change_rate == 0
    assert comparison.current_total == comparison.baseline_total == current_value
    assert comparison.unit == current_unit


@pytest.mark.parametrize('role,current_period,baseline_period', [
    ('yoy', '2025-01', '2024-01'), ('mom', '2025-02', '2025-01'),
])
@pytest.mark.parametrize('selector', ['currentTotal', 'baselineTotal'])
@pytest.mark.parametrize('legacy', [False, True])
def test_comparison_number_reference_keeps_the_operand_period(role, current_period, baseline_period, selector, legacy):
    datasets = tuple((name, f'month,department,amount\n{period},A,{value}\n'.encode(),
                      context(name, semantics=(semantic('amount', unit='元'),)), (period_role,))
                     for name, period, value, period_role in (
                         ('current', current_period, 100, 'current'),
                         ('baseline', baseline_period, 50, role),
                     ))
    bundle = build_deterministic_analysis_bundle(analysis(), datasets)
    comparison = bundle.comparisons[0]
    token = '{{value:' + comparison.fact_id + ':' + selector + ':元}}'
    payload = bundle.model_dump(mode='json', by_alias=True)
    if legacy:
        payload['comparisons'][0].pop('baselinePeriodStart')
        payload['comparisons'][0].pop('baselinePeriodEnd')
    contents = [json.dumps(payload)]
    selected = resolve_number_reference(token, contents)
    expected = current_period if selector == 'currentTotal' else baseline_period
    other = baseline_period if selector == 'currentTotal' else current_period
    def statement(period):
        year, month = period.split('-')
        return f'{year}年{int(month)}月收入{selected["value"]:g}元[[claim:period-test]]。'
    statuses = [claim_status(statement(period), 'period-test', selected['value'],
                             expected_unit=selected['unit'], expected_periods=selected['periods'])
                for period in (expected, other)]
    assert selected['periods'] == (expected,)
    assert statuses[0]['warnings'] == [] and statuses[1]['warnings']


@pytest.mark.parametrize('algorithm', ['sum', 'semi_additive_last', 'ratio'])
@pytest.mark.parametrize('missing_value', ['', 'not-recorded', '0'])
def test_all_missing_numeric_group_is_not_reported_as_a_verified_zero(tmp_path, algorithm, missing_value):
    dataset_id = 'dataset-nullgroups'
    fields = ('amount', 'visits') if algorithm == 'ratio' else ('amount',)
    semantics = tuple(semantic(field, unit='元') for field in fields)
    if algorithm == 'semi_additive_last':
        semantics = ({**semantics[0], 'additiveAcross': ['department']},)
    content = f'month,department,amount,visits\n2025-01,A,100,10\n2025-01,B,{missing_value},5\n'.encode()
    ctx = context(dataset_id, fields=('month', 'department', 'amount', 'visits'),
                  semantics=semantics, sha256=hashlib.sha256(content).hexdigest())
    metrics = base_metrics(*fields)
    if algorithm == 'ratio':
        metrics += ({'code': 'ratio', 'aggregation': 'ratio',
                     'numeratorMetric': 'amount', 'denominatorMetric': 'visits'},)
    bundle = build_deterministic_analysis_bundle(analysis(fields=fields),
        ((dataset_id, content, ctx, ('current',)),), profile_metrics=metrics)
    declarations = build_drilldown_metrics(
        bundles=(bundle.model_dump(mode='json', by_alias=True),),
        dataset_columns={dataset_id: ctx.fields}, profile_metrics=metrics,
        profile_dimensions=({'code': 'department', 'fieldRefs': [semantic('department')['fieldRef']]},),
        measure_semantics=semantics,
    )
    declaration = next(item for item in declarations if item.metric_code == ('ratio' if algorithm == 'ratio' else 'amount'))
    path = tmp_path / 'snapshot.csv'
    path.write_bytes(content)
    file = TraceDatasetFile(dataset_id, path, len(content), ctx.sha256, 2)
    with verified_dataset_snapshot(file) as snapshot:
        page = TraceDrilldownService(secret=b'audit').drilldown(
            snapshot, declaration, dimension_code='department', report_id='report', revision=1,
        )
    assert page.reconciled is True
    if missing_value == '0':
        assert dict(page.rows)['B'] == 0
    else:
        assert dict(page.rows).get('B') is None


@pytest.mark.parametrize('role,current_period,baseline_period', [
    ('yoy', '2025-01', '2024-01'), ('mom', '2025-01', '2024-12'),
    ('yoy', '2025-03-01', '2024-03-01'), ('mom', '2025-03-01', '2025-02-28'),
    ('yoy', '2025', '2024'),
])
def test_change_reference_distinguishes_current_and_baseline_roles(role, current_period, baseline_period):
    datasets = tuple((name, f'month,department,amount\n{period},A,{value}\n'.encode(),
                      context(name, semantics=(semantic('amount', unit='元'),)), (period_role,))
                     for name, period, value, period_role in (
                         ('current', current_period, 100, 'current'), ('baseline', baseline_period, 50, role),
                     ))
    bundle = build_deterministic_analysis_bundle(analysis(), datasets)
    comparison = bundle.comparisons[0]
    token = '{{value:' + comparison.fact_id + ':changeRate:%}}'
    selected = resolve_number_reference(token, [bundle.model_dump_json(by_alias=True)])
    assert selected['period_roles']['current'] == (current_period,)
    assert selected['period_roles']['baseline'] == (baseline_period,)
    assert selected['periods'] == (current_period, baseline_period)


@pytest.mark.parametrize('current_unit,baseline_unit', [('元', '人次'), ('元', None), ('未知单位', '元')])
def test_incompatible_comparison_units_are_softly_omitted(current_unit, baseline_unit):
    datasets = tuple((name, f'month,department,amount\n{year}-01,A,100\n'.encode(),
                      context(name, semantics=(semantic('amount', unit=unit),)), (role,))
                     for name, year, unit, role in (
                         ('current', 2025, current_unit, 'current'), ('baseline', 2024, baseline_unit, 'yoy'),
                     ))
    bundle = build_deterministic_analysis_bundle(analysis(), datasets)
    assert len(bundle.metrics) == 2 and not bundle.comparisons
    assert any('单位无法换算' in warning for warning in bundle.warnings)


@pytest.mark.parametrize('algorithm', ['sum', 'semi_additive_last', 'ratio'])
@pytest.mark.parametrize('raw', ['', 'invalid'])
def test_all_missing_snapshot_never_passes_as_zero(tmp_path, algorithm, raw):
    content = f'department,month,amount,visits\nA,2025-01,{raw},5\nB,2025-01,{raw},5\n'.encode()
    path = tmp_path / 'missing.csv'
    path.write_bytes(content)
    file = TraceDatasetFile('dataset-missing01', path, len(content), hashlib.sha256(content).hexdigest(), 2)
    declaration = DrilldownMetricV1.model_validate({
        'metricCode': 'amount', 'datasetId': file.dataset_id, 'aggregation': algorithm,
        'dimensions': [{'code': 'department', 'field': 'department'}], 'expectedValue': 0,
        **({'numeratorField': 'amount', 'denominatorField': 'visits'} if algorithm == 'ratio' else {'valueField': 'amount'}),
        **({'periodField': 'month'} if algorithm == 'semi_additive_last' else {}),
    })
    service = TraceDrilldownService(secret=b'missing-test')
    with verified_dataset_snapshot(file) as snapshot:
        page = service.drilldown(snapshot, declaration, dimension_code='department', report_id='r', revision=1)
        fallback = service._observed_value(service._fixed_scope(
            service._validated_scan(snapshot, declaration, 'department'), declaration), declaration)
    assert all(value is None for _group, value in page.rows)
    assert page.observed_value is fallback is None
    assert page.reconciled is None


@pytest.mark.parametrize('field,value', [('baseline_scale', 0.0001), ('baseline_period_start', '2023-01')])
def test_comparison_identity_includes_conversion_and_baseline_period(field, value):
    from .test_trace_fact_service import _bundle

    fact = _bundle(roles=('current', 'yoy')).comparisons[0]
    assert comparison_fact_identity(fact) != comparison_fact_identity(fact.model_copy(update={field: value}))


def test_ratio_identity_includes_conversion_scale():
    from .test_trace_fact_service import _bundle

    fact = _bundle().derived_metrics[0]
    assert derived_fact_identity(fact) != derived_fact_identity(fact.model_copy(update={'denominator_scale': 0.0001}))


@pytest.mark.parametrize('role,baseline_period', [('yoy', '2024-01'), ('mom', '2024-12')])
def test_converted_comparisons_keep_nonzero_changes_and_baseline_dates(role, baseline_period):
    bundle = build_deterministic_analysis_bundle(analysis(), tuple(
        (name, f'month,department,amount\n{period},A,{value}\n'.encode(),
         context(name, semantics=(semantic('amount', unit=unit),)), (period_role,))
        for name, period, value, unit, period_role in (
            ('current', '2025-01', 110, '万元', 'current'),
            ('baseline', baseline_period, 1000000, '元', role),
        )
    ))
    comparison = bundle.comparisons[0]
    assert (comparison.current_total, comparison.baseline_total, comparison.change, comparison.change_rate) == (110, 100, 10, 10)
    assert comparison.baseline_scale == 0.0001
    token = '{{value:' + comparison.fact_id + ':baselineTotal:万元}}'
    selected = resolve_number_reference(token, [bundle.model_dump_json(by_alias=True)])
    assert selected['value'] == 100 and selected['unit'] == '万元'
    assert selected['periods'] == (baseline_period,)


@pytest.mark.parametrize('zero_budget', [False, True])
def test_converted_ratio_group_values_and_weighted_total_match(tmp_path, zero_budget):
    content = (f'month,department,actual,budget\n2025-01,A,30,{0 if zero_budget else 400000}\n'
               f'2025-01,B,80,{0 if zero_budget else 600000}\n').encode()
    dataset_id = 'dataset-unitgroups'
    fields = ('actual', 'budget')
    ctx = context(dataset_id, fields=('month', 'department', *fields),
                  sha256=hashlib.sha256(content).hexdigest(), semantics=(
                      semantic('actual', unit='万元'), semantic('budget', unit='元'),
                  ))
    metrics = base_metrics(*fields) + ({'code': 'ratio', 'aggregation': 'ratio',
                                      'numeratorMetric': 'actual', 'denominatorMetric': 'budget'},)
    bundle = build_deterministic_analysis_bundle(analysis(fields=fields),
        ((dataset_id, content, ctx, ('current',)),), profile_metrics=metrics)
    ratio = bundle.derived_metrics[0]
    if zero_budget:
        assert ratio.value is ratio.percentage is None
        assert any('分母为零' in warning for warning in ratio.warnings)
        return
    assert ratio.value == 1.1 and ratio.percentage == pytest.approx(110)
    declarations = build_drilldown_metrics(
        bundles=(bundle.model_dump(mode='json', by_alias=True),),
        dataset_columns={dataset_id: ctx.fields}, profile_metrics=metrics,
        profile_dimensions=({'code': 'department', 'fieldRefs': [semantic('department')['fieldRef']]},),
        measure_semantics=ctx.metric_semantics,
    )
    declaration = next(item for item in declarations if item.metric_code == 'ratio')
    path = tmp_path / 'groups.csv'
    path.write_bytes(content)
    file = TraceDatasetFile(dataset_id, path, len(content), ctx.sha256, 2)
    service = TraceDrilldownService(secret=b'unit-groups')
    with verified_dataset_snapshot(file) as snapshot:
        page = service.drilldown(snapshot, declaration, dimension_code='department', report_id='r', revision=1, limit=1)
        next_page = service.drilldown(snapshot, declaration, dimension_code='department', report_id='r', revision=1,
                                      limit=1, cursor=page.next_cursor)
    assert dict(page.rows + next_page.rows) == {'A': 0.75, 'B': pytest.approx(4 / 3)}
    assert page.observed_value == next_page.observed_value == 1.1
    assert page.reconciled is next_page.reconciled is True


@pytest.mark.parametrize('missing_input', [True, False])
def test_legacy_unknown_or_conflicting_inputs_do_not_borrow_current_periods(missing_input):
    from .test_trace_fact_service import _bundle

    payload = _bundle(roles=('current', 'yoy')).model_dump(mode='json', by_alias=True)
    comparison = payload['comparisons'][0]
    comparison.pop('baselinePeriodStart')
    comparison.pop('baselinePeriodEnd')
    if missing_input:
        payload['metrics'] = []
        contents = [json.dumps(payload)]
    else:
        baseline = next(item for item in payload['metrics'] if item['datasetId'] == comparison['baselineDatasetId']
                        and item['fieldRef'] == comparison['fieldRef'])
        conflict = {**payload, 'metrics': [{**baseline, 'periodValues': [{'period': '2023-01', 'value': 100}]}]}
        contents = [json.dumps(payload), json.dumps(conflict)]
    token = '{{value:' + comparison['factId'] + ':baselineTotal:元}}'
    selected = resolve_number_reference(token, contents)
    assert selected is not None and selected['periods'] == ()
