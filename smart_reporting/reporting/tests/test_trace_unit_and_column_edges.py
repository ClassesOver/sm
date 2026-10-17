"""对账单位、不可解析期间下钻和同单位多列派生值的端到端回归。"""

import json

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.dataset_service import (
    TraceDatasetFile,
    verified_dataset_snapshot,
)
from smart_reporting.reporting.trace.drilldown_builder import build_drilldown_metrics
from smart_reporting.reporting.trace.drilldown_service import TraceDrilldownService
from smart_reporting.reporting.trace.fact_index import assign_fact_ids
from smart_reporting.reporting.trace.numeric_text import replace_unregistered_numbers

from .test_deterministic_analysis import analysis, context, semantic
from .test_deterministic_reconciliation_edges import dataset, metrics, reconcile
from .test_trace_scope_edges import make_dataset


@pytest.mark.parametrize('left,right,right_unit,expected', [
    (100, 100, '元', True), (100, 100, '万元', False), (10000, 1, '万元', True),
])
def test_reconciliation_respects_confirmed_amount_units(left, right, right_unit, expected):
    entries = []
    for field, value, unit in (('actual', left, '元'), ('ledger', right, right_unit)):
        ctx = context(field, fields=('month', 'department', field), semantics=(semantic(field, unit=unit),))
        entries.append(dataset(field, f'month,department,{field}\n2025-01,A,{value}\n'.encode(), ctx))
    check = reconcile(tuple(entries)).reconciliations[0]
    assert check.passed is expected, check.model_dump(by_alias=True)
    assert check.unit == '元'
    assert check.right_scale == (10000 if right_unit == '万元' else 1)
    assert check.right_total == right * check.right_scale
    assert check.difference == left - check.right_total


@pytest.mark.parametrize('label', ['2025-01', '2025-1', '2025-01-bad', '2025-02-30', '2025-13', ''])
@pytest.mark.parametrize('aggregation', ['sum', 'average', 'count', 'count_distinct'])
def test_generated_total_drilldown_does_not_drop_non_null_unparseable_period(tmp_path, label, aggregation):
    content = f'month,department,amount\n2025-01,A,100\n{label},B,200\n2025-02,A,300\n'.encode()
    entry = make_dataset('dataset-current', content, aggregation=aggregation)
    dataset_id, _, ctx, _ = entry
    definitions = ({'code': 'income', 'aggregation': aggregation, 'fieldRef': semantic('amount')['fieldRef']},)
    bundle = build_deterministic_analysis_bundle(analysis(), (entry,), profile_metrics=definitions)
    fact = bundle.metrics[0]
    assert fact.period_missing_count == (0 if label else 1)
    declarations = build_drilldown_metrics(
        bundles=(bundle.model_dump(mode='json', by_alias=True),),
        dataset_columns={dataset_id: ctx.fields}, profile_metrics=definitions,
        profile_dimensions=({'code': 'department', 'fieldRefs': [semantic('department')['fieldRef']]},),
        measure_semantics=ctx.metric_semantics, row_preserving_dataset_ids=(dataset_id,),
    )
    assert len(declarations) == 1
    path = tmp_path / 'snapshot.csv'
    path.write_bytes(content)
    file = TraceDatasetFile(dataset_id, path, len(content), ctx.sha256, 3)
    with verified_dataset_snapshot(file) as snapshot:
        page = TraceDrilldownService(secret=b'audit').drilldown(snapshot, declarations[0],
            dimension_code='department', report_id='report', revision=1)
    assert page.observed_value == fact.total and page.reconciled is True, page.to_payload()


def table():
    return json.dumps({'findings': [{'columns': ['院区', '收入', '成本'],
        'columnMeta': {'收入': {'unit': '元'}, '成本': {'unit': '元'}},
        'rows': [['总部', 101, 20], ['北部', 41, 10], ['远洋', 7, 5]]}]})


@pytest.mark.parametrize('text,supported', [
    ('总部收入比北部多60元。', True),
    ('总部成本比北部多10元。', True),
    ('总部成本比北部多60元。', False),
    ('总部与北部收入合计142元。', True),
    ('总部与北部成本合计142元。', False),
    ('收入与成本已核对，总部收入比北部多60元。', True),
    ('收入已核对，总部成本比北部多60元。', False),
])
def test_same_unit_columns_do_not_share_derived_values(text, supported):
    result = replace_unregistered_numbers(text, [table()])
    assert ('待核实' not in result) is supported, result


@pytest.mark.parametrize('left_unit,right_unit,left,right,scale', [
    ('万元', '元', 1, 10000, .0001), ('亿元', '万元', 1, 10000, .0001),
    ('人次', '万人次', 10000, 1, 10000), (None, None, 100, 100, 1),
])
def test_reconciliation_freezes_converted_values_and_factors(left_unit, right_unit, left, right, scale):
    entries = []
    for field, value, unit in (('actual', left, left_unit), ('ledger', right, right_unit)):
        ctx = context(field, fields=('month', 'department', field), semantics=(semantic(field, unit=unit),))
        entries.append(dataset(field, f'month,department,{field}\n2025-01,A,{value}\n'.encode(), ctx))
    bundle = reconcile(tuple(entries))
    check = bundle.reconciliations[0]
    assert check.passed and check.left_total == check.right_total == left
    assert check.right_scale == scale and check.unit == left_unit
    original = check.fact_id
    changed = check.model_copy(update={'right_scale': scale * 2})
    assert assign_fact_ids(bundle.model_copy(update={'reconciliations': (changed,)})).reconciliations[0].fact_id != original
    frozen = type(bundle).model_validate_json(bundle.model_dump_json(by_alias=True))
    assert frozen.reconciliations[0] == check


@pytest.mark.parametrize('right_unit', ['人次', None, '未知单位'])
def test_incompatible_reconciliation_units_only_warn(right_unit):
    entries = []
    for field, unit in (('actual', '元'), ('ledger', right_unit)):
        ctx = context(field, fields=('month', 'department', field), semantics=(semantic(field, unit=unit),))
        entries.append(dataset(field, f'month,department,{field}\n2025-01,A,100\n'.encode(), ctx))
    bundle = reconcile(tuple(entries))
    assert not bundle.reconciliations and len(bundle.metrics) == 2
    assert any('单位' in warning for warning in bundle.warnings)


@pytest.mark.parametrize('absolute_tolerance,passed', [(0, False), (1, True)])
def test_reconciliation_tolerance_is_applied_after_conversion(absolute_tolerance, passed):
    entries = []
    for field, value, unit in (('actual', 10001, '元'), ('ledger', 1, '万元')):
        ctx = context(field, fields=('month', 'department', field), semantics=(semantic(field, unit=unit),))
        entries.append(dataset(field, f'month,department,{field}\n2025-01,A,{value}\n'.encode(), ctx))
    bundle = build_deterministic_analysis_bundle(analysis(fields=('actual', 'ledger')), tuple(entries),
        profile_metrics=metrics('actual', 'ledger'),
        profile_reconciliations=({'code': 'check', 'leftMetric': 'actual', 'rightMetric': 'ledger',
            'grain': ['department'], 'absoluteTolerance': absolute_tolerance, 'relativeTolerance': 0},))
    check = bundle.reconciliations[0]
    assert check.passed is passed and check.difference == 1


@pytest.mark.parametrize('text,supported', [
    ('总部医疗收入比北部多60元。', True), ('总部收入比北部多60元。', False),
    ('总部收入比北部多11元。', True), ('总部医疗收入比北部多11元。', False),
    ('总部与北部收入合计142元。', False), ('总部与北部医疗收入合计142元。', True),
])
def test_nested_column_names_use_the_longest_matching_identity(text, supported):
    finding = {'columns': ['院区', '医疗收入', '收入'],
        'columnMeta': {'医疗收入': {'unit': '元'}, '收入': {'unit': '元'}},
        'rows': [['总部', 101, 20], ['北部', 41, 9], ['远洋', 7, 3]]}
    assert ('待核实' not in replace_unregistered_numbers(text, [json.dumps({'findings': [finding]})])) is supported


def test_stock_reconciliation_converts_the_shared_endpoint():
    entries = []
    for field, unit, rows in (
        ('actual', '元', '2025-01,A,10000\n2025-02,A,20000\n'),
        ('ledger', '万元', '2025-01,A,1\n'),
    ):
        measure = {**semantic(field, unit=unit), 'additiveAcross': ['department']}
        ctx = context(field, fields=('month', 'department', field), semantics=(measure,))
        entries.append(dataset(field, (f'month,department,{field}\n' + rows).encode(), ctx))
    check = reconcile(tuple(entries)).reconciliations[0]
    assert check.passed and check.period_start == check.period_end == '2025-01'
    assert check.left_total == check.right_total == 10000 and check.right_scale == 10000


def test_unit_conversion_does_not_turn_missing_groups_into_zero():
    entries = []
    for field, unit, rows in (
        ('actual', '元', '2025-01,A,\n2025-01,B,10000\n'),
        ('ledger', '万元', '2025-01,A,0\n2025-01,B,1\n'),
    ):
        ctx = context(field, fields=('month', 'department', field), semantics=(semantic(field, unit=unit),))
        entries.append(dataset(field, (f'month,department,{field}\n' + rows).encode(), ctx))
    check = reconcile(tuple(entries)).reconciliations[0]
    assert not check.passed and check.failed_group_count == 1 and check.checked_group_count == 2
    assert check.difference == 0 and check.warnings


@pytest.mark.parametrize('text,supported', [
    ('总部收入比北部多60元。', True), ('总部成本比北部多60元。', False),
    ('总部成本比北部多24元。', True), ('总部与北部成本合计142元。', False),
    ('总部与北部成本合计58元。', True),
])
def test_convertible_column_units_still_keep_their_measure_identity(text, supported):
    finding = {'columns': ['院区', '收入', '成本'],
        'columnMeta': {'收入': {'unit': '元'}, '成本': {'unit': '万元'}},
        'rows': [['总部', 101, .0041], ['北部', 41, .0017], ['远洋', 7, .0003]]}
    assert ('待核实' not in replace_unregistered_numbers(text, [json.dumps({'findings': [finding]})])) is supported
