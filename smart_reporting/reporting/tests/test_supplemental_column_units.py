"""列名单位不能被业务关键词改变量纲或倍率。"""

import json
from decimal import Decimal

import pytest

from smart_reporting.reporting.trace.content_review import review_content
from smart_reporting.reporting.trace.numeric_text import (
    _unit_from_column_name,
    replace_unregistered_numbers,
    supplemental_number_values,
)


@pytest.mark.parametrize(('column', 'unit'), [
    ('收入增长率（%）', '%'), ('收入占比(单位：%)', '%'),
    ('门诊量（万人次）', '万人次'), ('门诊量万人次', '万人次'),
    ('收入占比（万元）', '万元'), ('收入金额（亿元）', '亿元'),
    ('工作量（床日）', '床日'), ('收入增长率（‰）', '‰'),
    ('收入（美元）', None), ('门诊人数（人）', None),
    ('均次收入（元/人次）', None), ('人均收入', None),
    ('收入增长率', None), ('门诊人数', None),
    ('药耗占比差额（个百分点）', None), ('药耗占比差额', None),
    ('科室单元', None), ('工作量', None),
    ('收入金额', '元'), ('药耗占比', '%'), ('门诊人次', '人次'),
])
def test_explicit_column_units_precede_business_keywords(column, unit):
    assert _unit_from_column_name(column) == unit


def column_contents(column, rows, *, metadata=None):
    return [json.dumps({'findings': [{
        'columns': ['项目', column, '基准金额'],
        'columnMeta': {'基准金额': {'unit': '元'}, **(metadata or {})},
        'rows': [[name, value, 777] for name, value in rows],
    }]})]


@pytest.mark.parametrize(('column', 'correct', 'wrong'), [
    ('收入增长率（%）', '甲项目收入增长率为12.5%。', '甲项目收入增长率为12.5元。'),
    ('门诊量（万人次）', '甲项目门诊量为12.5万人次。', '甲项目门诊量为12.5人次。'),
])
def test_inferred_values_keep_explicit_unit_in_replacement_and_review(column, correct, wrong):
    contents = column_contents(column, [('甲项目', 12.5)])
    assert replace_unregistered_numbers(correct, contents) == correct
    assert not any('冻结依据' in warning for warning in review_content(correct, contents))
    assert '待核实' in replace_unregistered_numbers(wrong, contents)
    assert any('冻结依据' in warning for warning in review_content(wrong, contents))


@pytest.mark.parametrize('column', [
    '药耗占比差额（个百分点）', '药耗占比差额', '均次收入（元/人次）',
    '人均收入', '收入（美元）', '门诊人数（人）', '收入增长率',
])
def test_ambiguous_or_unsupported_units_do_not_authorize_other_dimensions(column):
    contents = column_contents(column, [('甲项目', 12.5)])
    known = supplemental_number_values(contents)
    assert all(Decimal('12.5') not in values for values in known.values())
    for unit in ('元', '%', '人次'):
        text = f'甲项目数值为12.5{unit}。'
        assert '待核实' in replace_unregistered_numbers(text, contents)
        assert any('冻结依据' in warning for warning in review_content(text, contents))


@pytest.mark.parametrize(('column', 'correct', 'wrong'), [
    ('收入增长率（%）', '甲项目与乙项目收入增长率相差4个百分点。',
     '甲项目与乙项目收入增长率相差4元。'),
    ('门诊量（万人次）', '甲项目与乙项目门诊量相差4万人次。',
     '甲项目与乙项目门诊量相差4人次。'),
])
def test_derived_differences_use_the_same_column_unit(column, correct, wrong):
    contents = column_contents(column, [('甲项目', 12.5), ('乙项目', 8.5)])
    assert replace_unregistered_numbers(correct, contents) == correct
    assert not any('冻结依据' in warning for warning in review_content(correct, contents))
    assert '待核实' in replace_unregistered_numbers(wrong, contents)
    assert any('冻结依据' in warning for warning in review_content(wrong, contents))


def test_inference_preserves_explicit_non_percent_metadata():
    column = '收入占比（%）'
    contents = column_contents(column, [('甲项目', 12.5), ('乙项目', 8.5)],
                               metadata={column: {'isPercent': False}})
    assert '%' not in supplemental_number_values(contents)
    assert '待核实' in replace_unregistered_numbers('甲项目占比为12.5%。', contents)
    assert '待核实' in replace_unregistered_numbers('甲项目与乙项目相差4个百分点。', contents)


def test_column_metadata_remains_authoritative_over_the_name():
    column = '收入金额（元）'
    contents = column_contents(column, [('甲项目', 12.5)], metadata={column: {'unit': '万元'}})
    assert Decimal('125000') in supplemental_number_values(contents)['元']
    assert replace_unregistered_numbers('甲项目收入为12.5万元。', contents) == '甲项目收入为12.5万元。'
