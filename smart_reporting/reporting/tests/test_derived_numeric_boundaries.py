"""派生差额的来源范围、完整期间和正文数量边界。"""

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

from .test_deterministic_analysis import analysis, context, semantic
from .test_deterministic_reconciliation_edges import dataset
from .test_trace_lineage_regressions import _daily_bundle


def share_table():
    return json.dumps({'findings': [{'name': '院区分布', 'columns': ['院区', '占比'],
        'columnMeta': {'占比': {'unit': '%', 'isPercent': True}},
        'rows': [['总部', 40], ['北部', 30], ['南部', 20], ['东部', 10]]}]})


@pytest.mark.parametrize('text,supported', [
    ('前2项合计占比70%。', True),
    ('前三项合计占比90%。', True),
    ('前两项合计占比70%。', True),
    ('前二项合计占比70%。', True),
    ('前3项合计占比90%。', True),
    ('前二项合计占比90%。', False),
    ('前20项合计占比70%。', False),
    ('前十二项合计占比70%。', False),
])
def test_chinese_top_count_means_its_actual_number(text, supported):
    rendered = replace_unregistered_numbers(text, [share_table()])
    assert ('待核实' not in rendered) is supported, rendered


@pytest.mark.parametrize('mode,supported', [('daily', True), ('monthly_single', False), ('monthly_multi', False)])
def test_only_a_real_daily_bucket_supports_an_exact_day(mode, supported):
    rows = '2025-01-01,A,100\n' if mode == 'daily' else '2025-01,A,100\n'
    if mode == 'monthly_multi':
        rows += '2025-02,A,200\n'
    bundle = _daily_bundle(rows, monthly=mode != 'daily')
    token = '{{value:' + bundle.metrics[0].fact_id + ':periodValues.0:元}}'
    rendered, refs, notices = render_bound_numbers('2025年1月1日收入为' + token,
        [bundle.model_dump_json(by_alias=True)], key='single-day', field_definitions={'amount': '收入'})
    assert (len(refs) == 1 and not notices) is supported, (rendered, refs, notices)


def amounts_bundle(rows, *, cost_department='A'):
    fields = ('month', 'department', 'income', 'cost')
    ctx = context('current', fields=fields, semantics=(
        semantic('income', scope={'department': 'A'}, unit='元'),
        semantic('cost', scope={'department': cost_department}, unit='元'),
    )).model_copy(update={'period_granularities': {'month': 'month'}})
    metrics = tuple({'code': field, 'aggregation': 'sum', 'fieldRef': semantic(field)['fieldRef'], 'description': label}
                    for field, label in (('income', '收入'), ('cost', '成本')))
    return build_deterministic_analysis_bundle(analysis(fields=('income', 'cost')),
        (dataset('current', ('month,department,income,cost\n' + rows).encode(), ctx),), profile_metrics=metrics)


@pytest.mark.parametrize('scope,supported', [('A', True), ('B', False)])
def test_derived_difference_requires_comparable_fixed_scopes(scope, supported):
    bundle = amounts_bundle('2025-01,A,100,70\n2025-01,B,999,40\n', cost_department=scope)
    assert [fact.display_name for fact in bundle.metrics] == ['收入', '成本']
    frozen = [bundle.model_dump_json(by_alias=True)]
    amount = 30 if scope == 'A' else 60
    assert f'{amount}元' not in frozen_number_catalog(frozen).values()
    rendered = replace_unregistered_numbers(f'A科收入高于成本{amount}元。', frozen)
    assert ('待核实' not in rendered) is supported, (rendered, [fact.scope for fact in bundle.metrics])


@pytest.mark.parametrize('text,supported', [
    ('2025年1月收入高于成本30元。', True),
    ('2025年2月收入高于成本30元。', False),
    ('2025年1月收入高于成本180元。', False),
    ('1月收入高于成本180元。', False),
    ('2025年1—2月收入高于成本180元。', True),
    ('2025年1月—2月收入高于成本180元。', True),
    ('1—2月收入高于成本180元。', True),
    ('截至2025年2月累计收入高于成本180元。', True),
    ('截至1月累计收入高于成本180元。', False),
    ('2026年1—2月收入高于成本180元。', False),
    ('2025/01收入高于成本180元。', False),
    ('2025-01收入高于成本30元。', True),
    ('2025年，1月收入高于成本30元。', True),
    ('2025年收入高于成本180元。', True),
    ('2025年1月收入高于成本30元。收入高于成本180元。', True),
])
def test_derived_difference_is_constrained_by_the_stated_month(text, supported):
    bundle = amounts_bundle('2025-01,A,100,70\n2025-02,A,200,50\n')
    frozen = [bundle.model_dump_json(by_alias=True)]
    assert '180元' not in frozen_number_catalog(frozen).values()
    rendered = replace_unregistered_numbers(text, frozen)
    assert ('待核实' not in rendered) is supported, rendered


@pytest.mark.parametrize('difference,supported', [('aggregation', False), ('grain', False), ('stock', False), ('none', True)])
def test_derivations_require_matching_aggregation_and_time_semantics(difference, supported):
    bundle = amounts_bundle('2025-01,A,100,70\n')
    income, cost = bundle.metrics
    changes = {'aggregation': {'aggregation': 'max'}, 'grain': {'period_granularity': 'day'},
               'stock': {'period_aggregation': 'last'}, 'none': {}}[difference]
    bundle = bundle.model_copy(update={'metrics': (income, cost.model_copy(update=changes))})
    rendered = replace_unregistered_numbers('收入高于成本30元。', [bundle.model_dump_json(by_alias=True)])
    assert ('待核实' not in rendered) is supported
