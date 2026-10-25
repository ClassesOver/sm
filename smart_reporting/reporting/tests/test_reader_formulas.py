"""来源卡片的可验算算式：派生值与对比值写出操作数的指标名、期间、带单位的登记原值与结果。"""

import re
from decimal import Decimal

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.numeric_text import frozen_number_catalog
from smart_reporting.reporting.trace.semantic_bindings import resolve_number_references

from .test_calc_references import _bundle_content
from .test_deterministic_analysis import analysis, context, semantic
from .test_number_selection import source

B, D = 'fact-' + 'b' * 16, 'fact-' + 'd' * 16


def _explain(token, contents):
    return resolve_number_references([token], contents)[token]['explanation']


def _yoy_bundle():
    def dataset(name):
        return context(name, semantics=(semantic('amount', unit='元'),)).model_copy(
            update={'period_granularities': {'month': 'month'}})

    bundle = build_deterministic_analysis_bundle(analysis(), (
        ('current', b'month,department,amount\n2025-01,A,120\n2025-02,A,150\n', dataset('current'), ('current',)),
        ('baseline', b'month,department,amount\n2024-01,A,100\n2024-02,A,100\n', dataset('baseline'), ('yoy',)),
    ))
    return bundle.model_dump_json(by_alias=True), bundle.comparisons[0].fact_id


@pytest.mark.parametrize(('selector', 'unit', 'expected'), [
    ('periodChanges.1', '元', '2025年2月 60元 − 2025年1月 40元 = 20元'),
    ('periodChangeRates.1', '%', '(2025年2月 60元 − 2025年1月 40元) ÷ 40元 × 100% = 50%'),
    ('periodTotals.0-1', '元', '1月 40元 + 2月 60元 = 100元'),
    ('periodAverages.0-1', '元', '2025年1—2月合计 100元 ÷ 2个月 = 50元'),
    ('monthlyAverage', '元', '2025年1—2月合计 100元 ÷ 2个月 = 50元'),
    ('monthlyMaximum', '元', '2025年1—2月逐月比较，最高为2025年2月 60元'),
    ('monthlyMinimum', '元', '2025年1—2月逐月比较，最低为2025年1月 40元'),
    (f'budgetComparison.{D}.2025-01..2025-02.percentage', '%',
     '实际总医疗收入（2025年1—2月）100元 ÷ 预算总医疗收入（2025年1—2月）140元 × 100% = 71.43%'),
    (f'budgetComparison.{D}.2025-02.difference', '元',
     '实际总医疗收入（2025年2月）60元 − 预算总医疗收入（2025年2月）70元 = −10元'),
    # 直接登记的合计与单月值沿用原口径。
    ('total', '元', None),
    ('periodValues.0', '元', None),
])
def test_derived_values_read_as_arithmetic_on_registered_values(selector, unit, expected):
    assert _explain(f'{{{{value:{B}:{selector}:{unit}}}}}', source()) == expected


def test_comparison_amounts_and_totals_describe_the_number_shown():
    # 变化额、本期与基期合计不再沿用变化率公式。
    content, comparison = _yoy_bundle()

    def explain(field, unit='元'):
        return _explain(f'{{{{value:{comparison}:{field}:{unit}}}}}', [content])

    assert explain('change') == '本期合计（2025年1—2月）270元 − 基期合计（2024年1—2月）200元 = 70元'
    assert explain('changeRate', '%') == ('(本期合计（2025年1—2月）270元 − 基期合计（2024年1—2月）200元)'
                                          ' ÷ 200元 × 100% = 35%')
    assert explain('currentTotal').endswith('本期合计（2025年1—2月）')
    assert explain('baselineTotal').endswith('基期合计（2024年1—2月）')
    assert '变化率' not in explain('currentTotal')


def test_row_statistics_and_groups_are_named_for_what_they_are():
    content = _bundle_content()
    catalog = frozen_number_catalog([content])
    tokens = {token.split(':')[2]: token for token in catalog}
    # 单条记录的最小值不是求和。
    assert _explain(tokens['minimum'], [content]).endswith('各条记录中的最小值')
    group = _explain(tokens['topGroups.0'], [content])
    assert group.startswith('A：') and group.endswith('求和')
    share = _explain(next(token for key, token in tokens.items() if key.startswith('groupShares.topGroups.')), [content])
    assert share.startswith('A ') and ' ÷ 总体 ' in share and share.endswith('%')


_AMOUNT = r'−?[\d,]+(?:\.\d+)?'


def _amounts(text):
    # 只取“数值+单位”中的数值：去掉期间、括号内说明与“× 100%”。
    cleaned = re.sub(r'\d{4}年\d{1,2}(?:—\d{1,2})?月|\d{4}年|\d{1,2}月|（[^）]*）|× 100%', '', text)
    return [Decimal(item.replace(',', '').replace('−', '-')) for item in re.findall(_AMOUNT, cleaned)]


def _recomputed(explanation):
    left, right = explanation.rsplit(' = ', 1)
    if '个月' in left:
        total = _amounts(left.split('÷')[0])[-1]
        return total / Decimal(re.search(r'÷ (\d+)个月', left)[1])
    if left.startswith('('):
        a, b = _amounts(left.split(')')[0])[-2:]
        return (a - b) / abs(_amounts(left.split('÷')[1])[0]) * 100
    if '× 100%' in left:
        a, b = _amounts(left)[-2:]
        return a / b * 100
    if left.startswith('|'):
        a, b = _amounts(left)[-2:]
        return abs(a - b)
    if ' − ' in left:
        a, b = _amounts(left)[-2:]
        return a - b
    return sum(_amounts(left))


def test_every_formula_recomputes_to_the_result_it_shows():
    # 读者按卡片上的数字手算，必须得到卡片写出的结果（按两位小数显示允许舍入误差）。
    content, _ = _yoy_bundle()
    checked = 0
    for contents in (source(), [_bundle_content()], [content]):
        tokens = list(frozen_number_catalog(contents))
        for token, selected in resolve_number_references(tokens, contents).items():
            explanation = (selected or {}).get('explanation') or ''
            if ' = ' not in explanation:
                continue
            [shown] = _amounts(explanation.rsplit(' = ', 1)[1])[:1]
            assert abs(_recomputed(explanation) - shown) <= Decimal('0.01'), (token, explanation)
            checked += 1
    assert checked > 50


def test_table_cells_resolve_by_their_registered_unit():
    # 表格单元格只登记事实与选择器：按目录登记的单位取引用，不猜单位（变化率为“%”，金额为“元”）。
    content, comparison = _yoy_bundle()
    results = resolve_number_references(
        (), [content], selectors=[(comparison, 'changeRate'), (comparison, 'change'), (comparison, 'missing')],
    )
    rate, change = results[f'{comparison}:changeRate'], results[f'{comparison}:change']
    assert rate['unit'] == '%' and rate['explanation'].endswith('= 35%')
    assert change['value'] == 70 and change['explanation'].endswith('= 70元')
    assert results[f'{comparison}:missing'] is None
