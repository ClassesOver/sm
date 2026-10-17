"""派生数值的比较方向、句内对象和原始期间粒度回归。"""

import json

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.numeric_text import (
    frozen_number_catalog,
    replace_unregistered_numbers,
)
from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers

from .test_derived_numeric_boundaries import share_table
from .test_deterministic_analysis import analysis, context, semantic
from .test_deterministic_reconciliation_edges import dataset


def money_table():
    return json.dumps({'findings': [{'name': '院区收入', 'columns': ['院区', '收入'],
        'columnMeta': {'收入': {'unit': '元'}},
        'rows': [['总部', 101], ['北部', 41], ['远洋', 10]]}]})


@pytest.mark.parametrize('text,supported', [
    ('总部比北部多60元。', True),
    ('总部比北部多60元，总部比远洋多91元。', True),
    ('总部比远洋多91元，总部比北部多60元。', True),
    ('总部比北部多60元，总部比远洋多60元。', False),
    ('总部比北部少60元。', False),
    ('北部比总部少60元。', True),
    ('北部比总部多60元。', False),
    ('总部比北部高60元。', True),
    ('总部比北部低60元。', False),
    ('北部比总部低60元。', True),
    ('总部高于北部60元。', True),
    ('北部低于总部60元。', True),
    ('总部低于北部60元。', False),
    ('总部与北部相差60元。', True),
    ('北部与总部相差60元。', True),
    ('总部与北部相差-60元。', False),
    ('总部与北部差额为60元。', True),
    ('北部与总部差额为-60元。', True),
    ('北部与总部差额为60元。', False),
    ('前两项合计占比70%。', True),
    ('前两项合计占比-70%。', False),
])
def test_derived_values_must_obey_comparison_direction_and_sum_sign(text, supported):
    rendered = replace_unregistered_numbers(text, [money_table(), share_table()])
    assert ('待核实' not in rendered) is supported, rendered


@pytest.mark.parametrize('text,supported', [
    ('总部比远洋多60元。', False),
    ('总部与北部已核对。总部比远洋多60元。', False),
    ('总部与北部已核对。\n\n总部比远洋多60元。', False),
    ('总部与北部已核对，总部比远洋多60元。', False),
    ('总部与北部已核对；总部比远洋多60元。', False),
    ('总部比北部多60元。', True),
])
def test_operand_names_must_belong_to_the_actual_comparison(text, supported):
    rendered = replace_unregistered_numbers(text, [money_table()])
    assert ('待核实' not in rendered) is supported, rendered


def daily_bundle(rows=b'2025-01-01,A,100,70\n2025-01-02,A,200,50\n'):
    fields = ('month', 'department', 'income', 'cost')
    ctx = context('current', fields=fields, semantics=(semantic('income', unit='元'), semantic('cost', unit='元'))).model_copy(
        update={'period_granularities': {'month': 'date'}})
    metrics = tuple({'code': field, 'aggregation': 'sum', 'fieldRef': semantic(field)['fieldRef'], 'description': label}
        for field, label in (('income', '收入'), ('cost', '成本')))
    return build_deterministic_analysis_bundle(analysis(fields=('income', 'cost')).model_copy(update={'series_granularity': 'day'}),
        (dataset('current', b'month,department,income,cost\n' + rows, ctx),),
        profile_metrics=metrics)


@pytest.mark.parametrize('text,supported', [
    ('2025年1月1日至2日收入高于成本180元。', True),
    ('2025年1月1日收入高于成本30元。', True),
    ('2025年1月收入高于成本30元。', False),
    ('2025-01-01收入高于成本30元。', True),
    ('2025年1月3日收入高于成本30元。', False),
])
def test_a_day_at_month_start_must_not_be_registered_as_a_month(text, supported):
    bundle = daily_bundle()
    assert all(fact.period_granularity == 'day' for fact in bundle.metrics)
    frozen = [bundle.model_dump_json(by_alias=True)]
    assert '30元' not in frozen_number_catalog(frozen).values()
    rendered = replace_unregistered_numbers(text, frozen)
    assert ('待核实' not in rendered) is supported, rendered


@pytest.mark.parametrize('text,supported', [
    ('2025年2月16日收入高于成本152元。', True),
    ('2月16日收入高于成本152元。', True),
    ('2025年2月收入高于成本152元。', False),
    ('2025年2月15日收入高于成本152元。', False),
    ('2025年2月15日收入高于成本63元。', True),
    ('2月15—16日收入高于成本215元。', True),
])
def test_non_month_start_days_keep_their_actual_bucket(text, supported):
    bundle = daily_bundle(b'2025-02-15,A,103,40\n2025-02-16,A,209,57\n')
    frozen = [bundle.model_dump_json(by_alias=True)]
    assert '152元' not in frozen_number_catalog(frozen).values()
    assert ('待核实' not in replace_unregistered_numbers(text, frozen)) is supported


@pytest.mark.parametrize('text', ['总部比北部少60元。', '总部比北部多-60元。',
                                '总部与北部已核对。总部比远洋多60元。'])
def test_wrong_derived_claims_receive_review_notices_at_render_time(text):
    rendered, refs, notices = render_bound_numbers(text, [money_table()], key='wrong-derived')
    assert '待核实' in rendered and not refs and notices


@pytest.mark.parametrize('text,supported', [
    ('前两项合计占比70%。', True), ('前两项合计占比-70%。', False),
    ('总部与北部合计占比70%。', True), ('总部与北部合计占比-70%。', False),
    ('总部北部南部前两项合计占比90%。', False),
])
def test_ranked_sums_keep_the_actual_sign_and_explicit_count(text, supported):
    assert ('待核实' not in replace_unregistered_numbers(text, [share_table()])) is supported


@pytest.mark.parametrize('text,supported', [('总部比北部多60万元。', True), ('总部比北部少60万元。', False),
                                         ('北部比总部少60万元。', True)])
def test_converted_difference_keeps_comparison_direction(text, supported):
    table = json.loads(money_table())
    for row in table['findings'][0]['rows']:
        row[1] *= 10000
    assert ('待核实' not in replace_unregistered_numbers(text, [json.dumps(table)])) is supported


@pytest.mark.parametrize('text', ['总部本期收入与同比收入相差60元。', '总部同比收入与本期收入之差为-60元。'])
def test_comparison_words_inside_metric_names_are_not_operators(text):
    table = json.dumps({'findings': [{'columns': ['院区', '本期收入', '同比收入'],
        'columnMeta': {'本期收入': {'unit': '元'}, '同比收入': {'unit': '元'}}, 'rows': [['总部', 101, 41]]}]})
    assert replace_unregistered_numbers(text, [table]) == text


@pytest.mark.parametrize('text,supported', [('前两项合计-50元。', True), ('前两项合计50元。', False)])
def test_negative_source_rows_preserve_the_real_negative_sum(text, supported):
    table = json.loads(money_table())
    for row, value in zip(table['findings'][0]['rows'], [-10, -40, -60], strict=True):
        row[1] = value
    assert ('待核实' not in replace_unregistered_numbers(text, [json.dumps(table)])) is supported
