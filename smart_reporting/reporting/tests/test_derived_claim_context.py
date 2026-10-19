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
    # 中性“差额”后接幅度（PR #62）：两种操作数顺序都写正数，负号不认可。
    ('北部与总部差额为-60元。', False),
    ('北部与总部差额为60元。', True),
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


def monthly_bundle():
    fields = ('month', 'department', 'income', 'cost')
    ctx = context('current', fields=fields, semantics=(semantic('income', unit='元'), semantic('cost', unit='元')))
    metrics = tuple({'code': field, 'aggregation': 'sum', 'fieldRef': semantic(field)['fieldRef'], 'description': label}
        for field, label in (('income', '实际收入'), ('cost', '预算收入')))
    rows = b'2025-01-01,A,300,100\n2025-02-01,A,90,100\n2025-03-01,A,60,100\n'
    item = analysis(fields=('income', 'cost')).model_copy(update={'series_granularity': 'month'})
    return build_deterministic_analysis_bundle(
        item, (dataset('current', b'month,department,income,cost\n' + rows, ctx),), profile_metrics=metrics)


@pytest.mark.parametrize('text,supported', [
    # 回放：“实际支出相当于预算支出的X%”因服务端不补算比值被替换为待核实。
    ('2025年1—3月实际收入相当于预算收入的150.00%。', True),
    ('2025年1—3月预算收入相当于实际收入的66.67%。', True),
    ('2025年1—3月预算收入相当于实际收入的150.00%。', False),
    ('2025年1月实际收入相当于同月预算收入的300.00%。', True),
    ('2025年2月实际收入相当于同月预算收入的300.00%。', False),
    ('1—2月累计实际收入相当于累计预算收入的195.00%。', True),
    ('1—2月累计实际收入相当于累计预算收入的150.00%。', False),
    ('2025年1—3月实际收入较预算收入增长150.00%。', False),
])
def test_ratios_of_same_scope_metrics_follow_numerator_and_window(text, supported):
    frozen = [monthly_bundle().model_dump_json(by_alias=True)]
    assert ('待核实' not in replace_unregistered_numbers(text, frozen)) is supported


@pytest.mark.parametrize('text,supported', [
    ('总部40%、北部30%为主，两类合计约70%。', True),
    ('总部40%、北部30%为主，两类合计约60%。', False),
    ('甲40%、乙20%为主，两类合计约70%。', False),
    ('两类合计约70%。', False),
    ('甲40%；乙30%。上述两类合计约70%。', True),
    ('甲40%；乙30%。上述三类合计约70%。', False),
])
def test_sum_of_listed_shares_is_supported_without_full_row_names(text, supported):
    assert ('待核实' not in replace_unregistered_numbers(text, [share_table()])) is supported


@pytest.mark.parametrize('text,supported', [
    # 回放：补证表列名是字段编码，“资产管理处预算与合同之间相差…”因找不到比较对象被替换。
    ('总部实际收入与预算收入之间相差380元。', True),
    ('总部实际与预算相差380元。', True),
    ('总部预算比实际少380元。', True),
    ('总部预算比实际多380元。', False),
    ('总部实际与预算相差379元。', False),
])
def test_field_code_columns_use_fact_display_names(text, supported):
    table = json.dumps({'findings': [{'columns': ['院区', 'income', 'cost'],
        'columnMeta': {'income': {'unit': '元'}, 'cost': {'unit': '元'}},
        'rows': [['总部', 500, 120], ['北部', 90, 100]]}]})
    frozen = [monthly_bundle().model_dump_json(by_alias=True), table]
    assert ('待核实' not in replace_unregistered_numbers(text, frozen)) is supported


@pytest.mark.parametrize('text,supported', [
    # 中性“相差”须由当前句操作数补算（PR #62），差额列里的负值不能借给“预算与实际相差”。
    ('总部超支60元。', True), ('总部预算与实际相差约60元。', False), ('总部缺口60元。', True),
    ('总部超支61元。', False), ('总部增长60元。', False),
])
def test_negative_registered_gaps_read_as_magnitudes_after_gap_words(text, supported):
    table = json.dumps({'findings': [{'columns': ['院区', '差额'], 'columnMeta': {'差额': {'unit': '元'}},
        'rows': [['总部', -60], ['北部', 41]]}]})
    assert ('待核实' not in replace_unregistered_numbers(text, [table])) is supported


@pytest.mark.parametrize('text,expected', [
    # 回放：“三项合计占88.99%”实为88.9987%；“相差约6.51亿元”实为6.5164亿元。模型用已舍入的
    # 显示值手算，末位差一个单位：改写为服务端补算值。
    ('总部、北部合计占69.9%。', '总部、北部合计占70.0%。'),
    ('总部比北部多59.9元。', '总部比北部多60.0元。'),
    ('总部、北部合计占69.8%。', '总部、北部合计占待核实。'),
    ('总部比北部多59元。', '总部比北部多待核实。'),
    ('总部比北部少59.9元。', '总部比北部少待核实。'),
])
def test_last_digit_drift_on_named_derived_values_is_corrected(text, expected):
    assert replace_unregistered_numbers(text, [money_table(), share_table()]) == expected
