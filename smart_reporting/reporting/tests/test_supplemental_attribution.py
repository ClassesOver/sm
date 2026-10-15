import json

import pytest

from smart_reporting.reporting.trace.content_review import review_content_result


def table(columns, rows, metadata):
    return json.dumps({'findings': [{'columns': columns, 'rows': rows, 'columnMeta': metadata}]}, ensure_ascii=False)


@pytest.mark.parametrize(('text', 'expected'), [
    ('非专项经费4,204.02万元，占97.69%。', True),
    ('非专项经费96.82亿元，占97.69%。', False),
    ('财政基本补助经费2.29亿元。', False),
])
def test_group_amount_checked_against_registered_aggregate(text, expected):
    data = table(['经费性质', '成本金额', '占比'],
                 [['非专项经费', 9682073881, 97.69], ['财政基本补助经费', 229446263, 2.31]],
                 {'成本金额': {'unit': '元'}, '占比': {'unit': '%', 'isPercent': True}})
    result = review_content_result(text, [data])
    assert any('补证分组数值' in w for w in result.warnings) is expected
    if expected:
        assert result.accuracy_count > 0


def test_workload_group_selection_uses_metric_and_unit():
    data = table(['dept', 'open_beds', 'occupied_beds', 'discharges'],
                 [['普通外科', 260255, 230919, 32108]],
                 {'open_beds': {'unit': '床日'}, 'occupied_beds': {'unit': '床日'},
                  'discharges': {'unit': '人次'}})
    fields = {'open_beds': '实际开放床日', 'occupied_beds': '出院者占用床日', 'discharges': '出院人次'}
    text = '实际开放床日数最高的单元为普通外科，为3,968床日；出院人次最高的单元为普通外科，为582人次。'
    warnings = review_content_result(text, [data], field_definitions=fields).warnings
    assert sum('补证分组数值' in w for w in warnings) == 2
    assert not any('补证分组数值' in w for w in review_content_result(
        text.replace('3,968', '260,255').replace('582', '32,108'), [data], field_definitions=fields).warnings)


def test_conflicting_group_windows_are_not_guessed():
    first = table(['院区', '收入'], [['甲院区', 100]], {'收入': {'unit': '元'}})
    second = table(['院区', '收入'], [['甲院区', 200]], {'收入': {'unit': '元'}})
    assert not any('补证分组数值' in w for w in review_content_result('甲院区收入150元。', [first, second]).warnings)


def test_zero_budget_claim_checks_registered_budget_and_difference():
    data = table(['budget_type', 'budget_expenditure', 'actual_expenditure', 'difference'],
                 [['其他收入', 55310000, 588079118.9, 532769118.9]],
                 {key: {'unit': '元'} for key in ['budget_expenditure', 'actual_expenditure', 'difference']})
    result = review_content_result('正向超支全部来自预算侧为0的预算类型：药品费45.85亿元；其他收入5.88亿元、占总体差额11.29%。', [data])
    assert any('零预算断言' in w for w in result.warnings)
    assert any('偏差金额' in w for w in result.warnings)


@pytest.mark.parametrize('text', [
    '相关系数为0.981，两套口径反映同一工作量，宜择一解读。',
    '两项指标高度相关，因此口径等价。',
])
def test_correlation_does_not_establish_scope_equivalence(text):
    assert any('相关性不能证明口径等价' in w for w in review_content_result(text, []).warnings)


def test_bound_chart_cannot_be_described_as_omitted():
    result = review_content_result('支出偏差图未纳入引用。', [], bound_chart_ids=('chart_a',))
    assert any('图表引用状态矛盾' in w for w in result.warnings)
    assert not review_content_result('支出偏差图未纳入引用。', []).warnings


def test_group_value_does_not_capture_following_metric_or_totals():
    data = table(['类型', '金额'], [['药品收入', 100], ['合计', 200]], {'金额': {'unit': '元'}})
    for text in ['药品收入100元，材料收入50元。', '全院合计300元。', '药品收入中某月记录50元。']:
        assert not any('补证分组数值' in w for w in review_content_result(text, [data]).warnings)


def test_assembled_multianalysis_document_does_not_borrow_unscoped_supplement():
    data = table(['院区', '成本'], [['甲院区', 100]], {'成本': {'unit': '元'}})
    assert not any('补证分组数值' in w for w in review_content_result(
        '[[analysis:analysis_001]]甲院区收入200元。', [data]).warnings)


def test_partial_month_and_cross_dimension_values_do_not_use_whole_period_totals():
    data = table(['成本类型', '金额'], [['卫生材料成本', 2704226392]], {'金额': {'unit': '元'}})
    for text in ['8月卫生材料成本3.47亿元。', '2025年7月九舍手术室卫生材料成本-1,494.23万元。',
                 '交叉下钻显示，卫生材料成本3亿元。']:
        assert not any('补证分组数值' in w for w in review_content_result(text, [data]).warnings)


def test_zero_budget_statement_does_not_apply_to_following_savings_sentence():
    data = table(['budget_type', 'budget_expenditure', 'actual_expenditure', 'difference'],
                 [['其他收入', 100, 200, 100], ['人员经费', 300, 200, -100]],
                 {key: {'unit': '元'} for key in ['budget_expenditure', 'actual_expenditure', 'difference']})
    warnings = review_content_result('正向超支全部来自预算为0的类型：其他收入100元。负向节约为人员经费100元。', [data]).warnings
    assert any('其他收入' in w and '零预算断言' in w for w in warnings)
    assert not any('人员经费' in w and ('零预算断言' in w or '偏差金额' in w) for w in warnings)
