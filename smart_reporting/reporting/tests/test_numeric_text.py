from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from smart_reporting.reporting.trace.numeric_text import (
    correct_constant_monthly_totals,
    correct_period_extrema,
    format_fact_value,
    frozen_number_catalog,
    money_text_warnings,
    plain_period_wording,
    render_frozen_numbers,
    replace_unregistered_numbers,
)


@pytest.mark.parametrize(('value', 'unit', 'target', 'expected'), [
    (11123541503, '元', '元', '11,123,541,503元'),
    (11123541503, '元', '亿元', '111.24亿元'),
    (10475201732, '元', '亿元', '104.75亿元'),
    (-648339771, '元', '亿元', '-6.48亿元'),
    (6.1892819593, '%', '%', '6.19%'),
    (1.005, '元', '元', '1.01元'),
    (111.24, '亿元', '元', '11,124,000,000元'),
])
def test_format_frozen_value(value, unit, target, expected):
    assert format_fact_value(value, unit, target) == expected


@pytest.mark.parametrize(('text', 'count'), [
    ('111.24亿元（11,123,541,503元）', 0),
    ('104.75亿元（10,475,201,732元）', 0),
    ('**111.24亿元**（111,235,415,003元）', 1),
    ('104.75亿元（104,752,017,320元）', 1),
    ('1.20万元（12,000元）', 0),
    ('-6.48亿元（-648,339,771元）', 0),
    ('收入111.24亿元，支出2亿元。', 0),
    (',亿元（,元）', 0),
    ('1.24万元（12,450元）', 1),
    ('1.25万元（12,450元）', 0),
])
def test_money_equivalent_text_respects_rounding(text, count):
    assert len(money_text_warnings(text)) == count


def test_catalog_and_render_use_frozen_totals_and_months():
    document = {
        'analysisId': 'analysis_001',
        'metrics': [{
            'factId': 'fact-' + 'a' * 16, 'datasetId': 'current', 'datasetSha256': 'b' * 64,
            'periodRoles': ['current'], 'field': 'amount', 'fieldRef': 'hospital.revenue.amount',
            'aggregation': 'sum', 'unit': '元', 'formula': 'sum(amount)', 'total': 11123541503,
            'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
            'periodValues': [{'period': '2025-01', 'value': 889688670}],
        }],
    }
    catalog = frozen_number_catalog([json.dumps(document), '{"summary":"模型摘要"}'])
    text = '收入{{value:fact-aaaaaaaaaaaaaaaa:total:亿元}}（{{value:fact-aaaaaaaaaaaaaaaa:total:元}}），1月{{value:fact-aaaaaaaaaaaaaaaa:periodValues.0:元}}。'
    assert render_frozen_numbers(text, catalog) == '收入111.24亿元（11,123,541,503元），1月889,688,670元。'
    assert render_frozen_numbers('{{value:fact-unknown:total:元}}', catalog) == '数值待核实'
    document['metrics'][0]['total'] = 100
    conflict = frozen_number_catalog([json.dumps(document), json.dumps({**document, 'metrics': [{**document['metrics'][0], 'total': 200}]})])
    assert render_frozen_numbers('{{value:fact-aaaaaaaaaaaaaaaa:total:元}}', conflict) == '数值待核实'


@pytest.mark.parametrize(('text', 'expected'), [
    # 显示值已带单位：占位后重复书写的同一量纲单位去掉（含显示单位与占位单位不同的情形）。
    ('收入{{value:a:total:亿元}}亿元', '收入1.37亿元'),
    ('增加{{value:a:change:亿元}}亿元', '增加654.32万元'),
    ('同比增长{{value:a:changeRate:%}}%，', '同比增长5.03%，'),
    ('门诊{{value:a:visits:人次}} 人次', '门诊35.30万人次'),
    ('提高{{value:a:share:%}}个百分点', '提高2.10个百分点'),
    # 其后不是单位、量纲不同、显示值不带单位或占位无法解析时不动。
    ('收入{{value:a:total:亿元}}以上，次均{{value:a:visits:人次}}次均', '收入1.37亿元以上，次均35.30万人次次均'),
    ('增长{{value:a:changeRate:%}}元', '增长5.03%元'),
    ('金额{{value:b:total}}元（单位待核实）', '金额136,543,211元（单位待核实）'),
])
def test_unit_written_again_after_placeholder_is_not_duplicated(text, expected):
    catalog = {
        '{{value:a:total:亿元}}': '1.37亿元', '{{value:a:change:亿元}}': '654.32万元',
        '{{value:a:changeRate:%}}': '5.03%', '{{value:a:visits:人次}}': '35.30万人次',
        '{{value:a:share:%}}': '2.10个百分点', '{{value:b:total}}': '136,543,211',
    }
    assert render_frozen_numbers(text, catalog) == expected


def test_unregistered_derived_numbers_are_replaced_before_publishing():
    document = {
        'analysisId': 'analysis_001',
        'metrics': [{
            'factId': 'fact-' + 'a' * 16, 'datasetId': 'current', 'datasetSha256': 'b' * 64,
            'periodRoles': ['current'], 'field': 'amount', 'fieldRef': 'hospital.amount',
            'aggregation': 'sum', 'unit': '元', 'formula': 'sum(amount)', 'total': 100,
            'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
            'periodGranularity': 'month',
            'periodValues': [{'period': '2025-01', 'value': 100}],
        }],
    }
    content = json.dumps(document)
    assert replace_unregistered_numbers('总额100元，派生比例12.3%。', [content]) == '总额100元，派生比例待核实。'


def test_typed_supplement_numbers_keep_units_and_unrounded_precision():
    from smart_reporting.reporting.trace.content_review import review_content

    frozen = json.dumps({'analysisId': 'analysis_001', 'metrics': [{
        'factId': 'fact-' + 'a' * 16, 'datasetId': 'current', 'datasetSha256': 'b' * 64,
        'periodRoles': ['current'], 'field': 'amount', 'fieldRef': 'hospital.amount',
        'aggregation': 'sum', 'unit': '元', 'formula': 'sum(amount)', 'total': 100,
        'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
    }]})
    supplement = json.dumps({'analysisId': 'analysis_001', 'datasetIds': ['current'],
        'findings': [{'name': '完整收入构成', 'columns': ['amount', 'share', 'untyped'],
            'columnMeta': {'amount': {'unit': '元'}, 'share': {'unit': '%', 'isPercent': True}},
            'rows': [[5829976285, 61.27835359022789, 777], [None, None, None]]}],
        'reconciliations': [{'name': '同期间对账', 'passed': True}], 'warnings': []})
    contents = [frozen, supplement]
    correct = '金额58.30亿元（5,829,976,285元），占比61.28%或61.3%。'
    assert replace_unregistered_numbers(correct, contents) == correct
    assert not any('冻结依据' in warning for warning in review_content(correct, contents))
    incorrect = '金额61.27835359022789元，占比5829976285%，未标单位777元。'
    assert replace_unregistered_numbers(incorrect, contents) == '金额待核实，占比待核实，未标单位待核实。'
    assert len([warning for warning in review_content(incorrect, contents) if '冻结依据' in warning]) == 3


def test_percent_metadata_does_not_treat_fraction_as_display_percent():
    from smart_reporting.reporting.trace.content_review import review_content

    supplement = json.dumps({'findings': [{'columns': ['fraction'], 'rows': [[0.6128]],
        'columnMeta': {'fraction': {'unit': '%', 'isPercent': False}}}]})
    assert any('冻结依据' in warning for warning in review_content('占比0.6128%。', [supplement]))


def test_nested_supplement_numbers_require_metadata_at_the_same_table():
    from smart_reporting.reporting.trace.content_review import review_content
    from smart_reporting.reporting.trace.numeric_text import supplemental_number_values

    supplement = json.dumps({'findings': [{'name': '分组', 'sections': [
        {'columns': ['amount', 'share'], 'rows': [[123456, 12.345]],
         'columnMeta': {'amount': {'unit': '元'}, 'share': {'unit': '%', 'isPercent': True}}},
        {'columns': ['untyped'], 'rows': [[777]]},
    ]}]})
    values = supplemental_number_values([supplement])
    assert Decimal('123456') in values['元']
    correct = '金额123,456元，占比12.35%。'
    assert replace_unregistered_numbers(correct, [supplement]) == correct
    assert review_content(correct, [supplement]) == []
    assert any('冻结依据' in w for w in review_content('未标单位777元。', [supplement]))


@pytest.mark.parametrize(('text', 'supported'), [
    ('2月环比下降18.38%。', True),
    ('2月降幅为18.38%。', True),
    ('2月环比增长18.38%。', False),
    ('2月占比18.38%。', False),
    ('2月环比下降18.39%。', False),
])
def test_negative_percent_supports_only_explicit_decline_magnitude(text, supported):
    from smart_reporting.reporting.trace.content_review import review_content

    content = json.dumps({'findings': [{'columns': ['change'], 'rows': [[-18.376]],
                         'columnMeta': {'change': {'unit': '%', 'isPercent': True}}}]})
    assert (replace_unregistered_numbers(text, [content]) == text) is supported
    assert (review_content(text, [content]) == []) is supported


def test_conflicting_monthly_extrema_are_rewritten_to_frozen_month():
    document = {
        'analysisId': 'analysis_001',
        'metrics': [{
            'factId': 'fact-' + 'a' * 16, 'datasetId': 'current', 'datasetSha256': 'b' * 64,
            'periodRoles': ['current'], 'field': 'amount', 'fieldRef': 'hospital.amount',
            'aggregation': 'sum', 'unit': '元', 'formula': 'sum(amount)', 'total': 150,
            'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
            'periodGranularity': 'month',
            'periodValues': [
                {'period': '2025-01', 'value': 100},
                {'period': '2025-02', 'value': 50},
            ],
        }],
    }
    content = json.dumps(document)
    corrected = correct_period_extrema(
        '[[analysis:analysis_001]]2月金额为最高值50元。', [content]
    )
    assert corrected == '[[analysis:analysis_001]]金额最高月份为1月。'


def _monthly_document(analysis_id='analysis_001', values=(100, 50, 80, 120)):
    return json.dumps({
        'analysisId': analysis_id,
        'metrics': [{
            'factId': 'fact-' + 'a' * 16, 'datasetId': 'current', 'datasetSha256': 'b' * 64,
            'periodRoles': ['current'], 'field': 'amount', 'fieldRef': 'hospital.amount',
            'aggregation': 'sum', 'unit': '元', 'formula': 'sum(amount)', 'total': sum(values),
            'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0, 'periodGranularity': 'month',
            'periodValues': [{'period': f'2025-{index + 1:02d}', 'value': value}
                             for index, value in enumerate(values)],
        }],
    })


@pytest.mark.parametrize(('text', 'expected'), [
    # 章节 block 不含协议标记：唯一分析事实包即其作用域。
    ('2月金额为最高值50元。', '金额最高月份为4月。'),
    ('门诊收入在3月达到峰值80元，2月为全年低点50元。', '门诊收入最高月份为4月，2月为全年低点50元。'),
    ('从月度走势看，2月收入达到全年最高，为50元；4月次之。', '从月度走势看，收入最高月份为4月；4月次之。'),
    ('**2月**收入最高，需关注。', '收入最高月份为4月，需关注。'),
    # 占比等豁免陈述保持原文，只改写对应的金额极值句。
    ('2月门诊占比最高；2月金额为最高值50元。', '2月门诊占比最高；金额最高月份为4月。'),
])
def test_extrema_correction_rewrites_unmarked_block_readably(text, expected):
    assert correct_period_extrema(text, [_monthly_document()]) == expected


@pytest.mark.parametrize('text', [
    '1—3月中，3月收入最高。',  # 子期间范围：改写会丢失范围语义
    '2024年2月收入最高。',  # 其他年份不属于该序列
    '4月收入最高，2月最低。',  # 与冻结序列一致
    '2月金额为最高值；2月收入也最高。',  # 无法唯一定位，留给软告警
])
def test_extrema_correction_keeps_text_it_cannot_safely_rewrite(text):
    assert correct_period_extrema(text, [_monthly_document()]) == text


def test_extrema_correction_needs_a_unique_bundle_for_unmarked_text():
    documents = [_monthly_document(), _monthly_document('analysis_002')]
    assert correct_period_extrema('2月金额为最高值50元。', documents) == '2月金额为最高值50元。'


_FLAT_BUDGET = (1097718506,) * 12


@pytest.mark.parametrize(('text', 'expected'), [
    # 回放原文：全年合计 131.73 亿元被写成各月取值。
    ('预算总医疗收入各月均为常量131.73亿元（13,172,622,072元）。',
     '预算总医疗收入各月均为常量10.98亿元（1097718506元）。'),
    ('每月预算为13172622072元。', '每月预算为1097718506元。'),
])
def test_constant_monthly_total_written_as_each_month_is_rewritten(text, expected):
    assert correct_constant_monthly_totals(text, [_monthly_document(values=_FLAT_BUDGET)]) == expected


@pytest.mark.parametrize(('text', 'values'), [
    ('各月合计131.73亿元。', _FLAT_BUDGET),  # 明写合计
    ('全年预算131.73亿元，各月均为10.98亿元。', _FLAT_BUDGET),  # 已是单月值
    ('预算各月均为350元。', (100, 50, 80, 120)),  # 各月取值不同，合计不能均摊
])
def test_constant_monthly_total_keeps_text_it_cannot_safely_rewrite(text, values):
    assert correct_constant_monthly_totals(text, [_monthly_document(values=values)]) == text


def test_budget_ratio_catalog_preserves_amounts_and_dimensionless_value():
    from smart_reporting.reporting.trace.fact_service import fact_display_unit, fact_display_value

    fact = {"factId": "fact-" + "a" * 16, "code": "budget_rate", "kind": "ratio",
            "periodRole": "current", "numeratorMetric": "actual", "denominatorMetric": "budget",
            "numerator": 12000, "denominator": 10000, "value": 1.2, "percentage": 120,
            "difference": 2000, "unit": "元", "formula": "actual/budget",
            "datasetIds": ["current"], "datasetSha256s": ["b" * 64]}
    catalog = frozen_number_catalog([json.dumps({"analysisId": "analysis_001", "derivedMetrics": [fact]})])
    assert catalog["{{value:fact-aaaaaaaaaaaaaaaa:percentage:%}}"] == "120.00%"
    assert catalog["{{value:fact-aaaaaaaaaaaaaaaa:value:}}"] == "1.20"
    assert "{{value:fact-aaaaaaaaaaaaaaaa:value:元}}" not in catalog
    assert catalog["{{value:fact-aaaaaaaaaaaaaaaa:difference:元}}"] == "2,000元"
    assert catalog["{{value:fact-aaaaaaaaaaaaaaaa:numerator:万元}}"] == "1.20万元"
    assert fact_display_value(fact) == 120
    assert fact_display_unit(fact) == "%"
    assert fact_display_unit({**fact, "percentage": None}) is None
    assert fact_display_unit({"total": 12, "unit": "人次"}) == "人次"


def test_period_extrema_warning_uses_frozen_series_and_analysis_scope():
    from smart_reporting.reporting.trace.numeric_text import period_extrema_warnings

    bundles = [{"analysisId": "analysis_001", "metrics": [{"periodRoles": ["current"],
        "periodGranularity": "month", "periodValues": [{"period": "2025-01-01", "value": 1191933469},
        {"period": "2025-02-01", "value": 972805980}, {"period": "2025-07-01", "value": 1190778379}]}]}]
    assert len(period_extrema_warnings("[[analysis:analysis_001]]2月成本为最低月份，7月成本为期间内最高月份。", bundles)) == 1
    assert period_extrema_warnings("[[analysis:analysis_001]]1月成本为期间最高值，2月成本最低。", bundles) == []
    assert period_extrema_warnings("[[analysis:analysis_002]]7月成本为期间最高值。", bundles) == []
    assert period_extrema_warnings("[[analysis:analysis_001]]7月可能较高，需要核实。", bundles) == []
    assert period_extrema_warnings("[[analysis:analysis_001]]1月成本为1—7月单月最高值。", bundles) == []


@pytest.mark.parametrize("text", [
    "月度最低值为50（出现在11月），月度最高值为100（出现在9月）。",
    "11月为50，较10月减少30，为9—11月的最低值。",
])
def test_extrema_does_not_assign_the_previous_clause_month_to_the_next_extreme(text):
    from smart_reporting.reporting.trace.numeric_text import period_extrema_warnings

    bundle = {"analysisId": "analysis_001", "metrics": [{"periodRoles": ["current"],
        "periodGranularity": "month", "periodValues": [
            {"period": "2025-09", "value": 100}, {"period": "2025-10", "value": 80},
            {"period": "2025-11", "value": 50}]}]}
    assert period_extrema_warnings("[[analysis:analysis_001]]" + text, [bundle]) == []
    assert period_extrema_warnings("[[analysis:analysis_001]]10月为最低值80。", [bundle])


def test_ratio_guide_exposes_period_and_denominator_rules_without_inventing_monthly_rates():
    from smart_reporting.reporting.trace.numeric_text import frozen_number_guide

    fact = {'factId': 'fact-' + 'a' * 16, 'code': 'budget_rate', 'kind': 'ratio',
            'periodRole': 'current', 'numeratorMetric': 'actual', 'denominatorMetric': 'budget',
            'numerator': 0, 'denominator': 10000, 'value': 0, 'percentage': 0,
            'difference': -10000, 'unit': '人次', 'formula': 'actual/budget',
            'periodStart': '2025-01-01', 'periodEnd': '2025-12-01',
            'datasetIds': ['current'], 'datasetSha256s': ['b' * 64]}
    content = json.dumps({'analysisId': 'analysis_001', 'derivedMetrics': [fact]})
    catalog = frozen_number_catalog([content])
    guide = frozen_number_guide([content], catalog)[0]
    assert guide['denominatorMetric'] == 'budget'
    assert guide['periodEnd'] == '2025-12-01'
    assert catalog[guide['references']['percentage']] == '0.00%'
    assert 'monthlyStatistics' not in guide
    zero_denominator = json.dumps({'analysisId': 'analysis_001', 'derivedMetrics': [{
        **fact, 'denominator': 0, 'value': None, 'percentage': None,
    }]})
    guide = frozen_number_guide([zero_denominator], frozen_number_catalog([zero_denominator]))[0]
    assert guide['references']['percentage'] is None


def test_extrema_correction_only_rewrites_the_analysis_that_produced_the_warning():
    def bundle(analysis_id, values):
        return json.dumps({
            'analysisId': analysis_id,
            'metrics': [{
                'factId': 'fact-' + analysis_id[-1] * 16, 'datasetId': 'current', 'datasetSha256': 'b' * 64,
                'periodRoles': ['current'], 'field': 'amount', 'fieldRef': 'hospital.amount',
                'aggregation': 'sum', 'unit': '元', 'formula': 'sum(amount)', 'total': sum(values),
                'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0, 'periodGranularity': 'month',
                'periodValues': [{'period': f'2025-{month:02d}', 'value': value}
                                 for month, value in enumerate(values, 1)],
            }],
        })

    # 分析 1 的“5月最高”正确；分析 2 的“5月最高”与冻结序列（6月最高）冲突。
    contents = [bundle('analysis_001', [1, 2, 3, 4, 9, 5]), bundle('analysis_002', [1, 2, 3, 4, 5, 9])]
    markdown = '[[analysis:analysis_001]]5月门诊人次最高。\n\n[[analysis:analysis_002]]5月收入最高。'
    corrected = correct_period_extrema(markdown, contents)
    assert '[[analysis:analysis_001]]5月门诊人次最高。' in corrected
    assert '5月收入最高' not in corrected
    assert '[[analysis:analysis_002]]收入最高月份为6月。' in corrected


@pytest.mark.parametrize(("text", "expected"), [
    ("收入同比下降-5.20%。", "收入同比下降5.20%。"),
    ("门诊量减少了-1,200人次。", "门诊量减少了1,200人次。"),
    ("收入同比增长-5.20%。", "收入同比下降5.20%。"),
    ("费用增加-1,200元，增幅为-3.00%。", "费用减少1,200元，降幅为3.00%。"),
    ("收入下滑-2.10%。", "收入下滑2.10%。"),
    ("收入变化率为-5.20%，增长率-1.00%。", "收入变化率为-5.20%，增长率-1.00%。"),
    ("2024-2025年收入增长5.20%。", "2024-2025年收入增长5.20%。"),
    ("1月实际较预算少-4.34万人次，2月多-6.37万人次。", "1月实际较预算少4.34万人次，2月少6.37万人次。"),
    ("实际比预算多-1,200人次。", "实际比预算少1,200人次。"),
    ("至少-3天内无登记，最多-2次。", "至少-3天内无登记，最多-2次。"),
    ("9月实际支出较预算支出低-13.47亿元，1月高-2.00亿元。", "9月实际支出较预算支出低13.47亿元，1月低2.00亿元。"),
    ("月度最低-5.20%，降低-3.00%，提高-1.00%。", "月度最低-5.20%，降低3.00%，降低1.00%。"),
])
def test_signed_direction_wording_is_normalized_from_frozen_sign(text, expected):
    from smart_reporting.reporting.trace.numeric_text import normalize_signed_wording

    assert normalize_signed_wording(text) == expected


def test_decline_magnitude_after_xiahua_stays_supported():
    content = json.dumps({'findings': [{'columns': ['change'], 'rows': [[-2.1]],
                         'columnMeta': {'change': {'unit': '%', 'isPercent': True}}}]})
    assert replace_unregistered_numbers('收入下滑2.10%。', [content]) == '收入下滑2.10%。'


def test_visit_counts_have_wan_display_and_verified_conversion():
    """人次与金额一样可按固定倍率显示为万人次；正确换算不被替换为待核实。"""
    document = json.dumps({
        'analysisId': 'analysis_001',
        'metrics': [{
            'factId': 'fact-' + 'a' * 16, 'datasetId': 'current', 'datasetSha256': 'b' * 64,
            'periodRoles': ['current'], 'field': 'visits', 'fieldRef': 'hospital.visits',
            'aggregation': 'sum', 'unit': '人次', 'formula': 'sum(visits)', 'total': 1234567,
            'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
        }],
    })
    catalog = frozen_number_catalog([document])
    assert catalog['{{value:fact-aaaaaaaaaaaaaaaa:total:万人次}}'] == '123.46万人次'
    assert catalog['{{value:fact-aaaaaaaaaaaaaaaa:total:人次}}'] == '1,234,567人次'
    text = '门诊量123.46万人次，约123.5万人次。'
    assert replace_unregistered_numbers(text, [document]) == text
    assert replace_unregistered_numbers('门诊量123.47万人次。', [document]) == '门诊量待核实。'


def test_signed_amount_decline_survives_post_processing_chain():
    """“减少{负变化额}”经符号规范化为正幅度后，仍应认定为已登记数值，不能变成待核实。"""
    from smart_reporting.reporting.trace.numeric_text import normalize_signed_wording

    document = json.dumps({
        'analysisId': 'analysis_001',
        'comparisons': [{
            'factId': 'fact-' + 'c' * 16, 'comparisonType': 'yoy', 'field': 'revenue',
            'fieldRef': 'hospital.revenue', 'currentDatasetId': 'current', 'baselineDatasetId': 'base',
            'currentDatasetSha256': 'b' * 64, 'baselineDatasetSha256': 'c' * 64,
            'currentTotal': 123456789, 'baselineTotal': 130000000, 'change': -6543211,
            'changeRate': -5.0332, 'formula': 'x', 'unit': '元',
        }],
    })
    catalog = frozen_number_catalog([document])
    rendered = render_frozen_numbers('收入减少{{value:fact-cccccccccccccccc:change:万元}}。', catalog)
    assert rendered == '收入减少-654.32万元。'
    normalized = normalize_signed_wording(rendered)
    assert replace_unregistered_numbers(normalized, [document]) == '收入减少654.32万元。'
    # 方向写反或脱离下降措辞的正数仍无依据。
    assert replace_unregistered_numbers('收入增加654.32万元。', [document]) == '收入增加待核实。'


def _comparison_document(change, rate, total=130000000):
    return json.dumps({
        'analysisId': 'analysis_001',
        'metrics': [{
            'factId': 'fact-' + 'a' * 16, 'datasetId': 'current', 'datasetSha256': 'b' * 64,
            'periodRoles': ['current'], 'field': 'revenue', 'fieldRef': 'hospital.revenue',
            'aggregation': 'sum', 'unit': '元', 'formula': 'sum(revenue)', 'total': total,
            'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
        }],
        'comparisons': [{
            'factId': 'fact-' + 'c' * 16, 'comparisonType': 'yoy', 'field': 'revenue',
            'fieldRef': 'hospital.revenue', 'currentDatasetId': 'current', 'baselineDatasetId': 'base',
            'currentDatasetSha256': 'b' * 64, 'baselineDatasetSha256': 'c' * 64,
            'currentTotal': 130000000 + change, 'baselineTotal': 130000000, 'change': change,
            'changeRate': rate, 'formula': 'x', 'unit': '元',
        }],
    })


@pytest.mark.parametrize(('change', 'rate', 'text', 'expected'), [
    # 登记为正的变化写成下降词：渲染前改为增长词。
    (6543211, 5.0332, '收入同比下降{{value:fact-cccccccccccccccc:changeRate:%}}。', '收入同比增长5.03%。'),
    (6543211, 5.0332, '收入较上年减少了{{value:fact-cccccccccccccccc:change:万元}}。', '收入较上年增加了654.32万元。'),
    (6543211, 5.0332, '降幅为{{value:fact-cccccccccccccccc:changeRate:%}}。', '增幅为5.03%。'),
    # 登记为负的变化：下降词保留并去负号；增长词改为下降词（既有符号规范化）。
    (-6543211, -5.0332, '收入较上年减少{{value:fact-cccccccccccccccc:change:万元}}。', '收入较上年减少654.32万元。'),
    (-6543211, -5.0332, '收入同比增长{{value:fact-cccccccccccccccc:changeRate:%}}。', '收入同比下降5.03%。'),
    # 合计等非变化字段不带方向语义，不改写。
    (6543211, 5.0332, '收入下降{{value:fact-aaaaaaaaaaaaaaaa:total:亿元}}。', '收入下降1.30亿元。'),
])
def test_direction_wording_follows_frozen_sign(change, rate, text, expected):
    from smart_reporting.reporting.trace.numeric_text import (
        align_placeholder_direction,
        normalize_signed_wording,
    )

    document = _comparison_document(change, rate)
    catalog = frozen_number_catalog([document])
    rendered = render_frozen_numbers(align_placeholder_direction(text, [document]), catalog)
    assert replace_unregistered_numbers(normalize_signed_wording(rendered), [document]) == expected


@pytest.mark.parametrize(('change', 'rate', 'verb', 'field', 'expected'), [
    (6543211, 5.0332, '减幅', 'changeRate', '增幅5.03%'),
    (6543211, 5.0332, '跌幅', 'changeRate', '涨幅5.03%'),
    (6543211, 5.0332, '下跌', 'change', '上涨654.32万元'),
    (6543211, 5.0332, '缩减', 'change', '增加654.32万元'),
    (-6543211, -5.0332, '减幅', 'changeRate', '减幅5.03%'),
    (-6543211, -5.0332, '跌幅', 'changeRate', '跌幅5.03%'),
    (-6543211, -5.0332, '涨幅', 'changeRate', '跌幅5.03%'),
    (-6543211, -5.0332, '上涨', 'change', '下跌654.32万元'),
    (-6543211, -5.0332, '回升', 'change', '回落654.32万元'),
])
def test_direction_wording_covers_common_synonyms(change, rate, verb, field, expected):
    """涨幅/跌幅/减幅/上涨/下跌/回升/缩减与增长/下降同等按冻结符号处理。"""
    from smart_reporting.reporting.trace.numeric_text import (
        align_placeholder_direction,
        normalize_signed_wording,
    )

    unit = '%' if field == 'changeRate' else '万元'
    document = _comparison_document(change, rate)
    text = f'收入较上年{verb}{{{{value:fact-cccccccccccccccc:{field}:{unit}}}}}。'
    rendered = render_frozen_numbers(
        align_placeholder_direction(text, [document]), frozen_number_catalog([document])
    )
    final = replace_unregistered_numbers(normalize_signed_wording(rendered), [document])
    assert final == f'收入较上年{expected}。'


def _budget_document():
    def metric(letter, field, values):
        return {
            'factId': 'fact-' + letter * 16, 'datasetId': 'current', 'datasetSha256': 'b' * 64,
            'periodRoles': ['current'], 'field': field, 'fieldRef': 'hospital.' + field,
            'aggregation': 'sum', 'unit': '元', 'formula': 'sum', 'total': sum(values),
            'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0, 'periodGranularity': 'month',
            'periodValues': [{'period': f'2025-{index + 1:02d}', 'value': value}
                             for index, value in enumerate(values)],
        }
    return json.dumps({'analysisId': 'analysis_001', 'metrics': [
        metric('a', 'actual_revenue', [900000, 1000000, 1200000]),
        metric('b', 'budget_revenue', [1000000, 1000000, 1000000]),
    ]})


def test_budget_ratio_is_available_when_both_amount_units_are_unknown():
    document = json.loads(_budget_document())
    for metric in document['metrics']:
        metric['unit'] = None
    content = json.dumps(document)
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )
    from smart_reporting.reporting.trace.numeric_text import (
        budget_comparison_values,
        frozen_number_guide,
    )

    comparisons = budget_comparison_values(DeterministicAnalysisBundle.model_validate(document))
    assert comparisons[-1]['percentage'] == Decimal('103.3333333333333333333333333')
    catalog = frozen_number_catalog([content])
    guide = frozen_number_guide([content], catalog)
    assert not any('.difference:' in token for token in catalog)
    assert '.difference:' not in json.dumps(guide)
    actual = next(item for item in guide if item['factId'] == 'fact-' + 'a' * 16)
    assert len(actual['budgetComparisons']) == len(comparisons) == 6
    # 单月及累计窗口的负数、零、正数差额均不登记，但每个窗口的百分比仍可引用。
    for comparison in actual['budgetComparisons']:
        token = ('{{value:fact-aaaaaaaaaaaaaaaa:budgetComparison.fact-bbbbbbbbbbbbbbbb.'
                 + comparison['period'] + '.percentage:%}}')
        assert comparison['references'] == {'difference': None, 'percentage': token}
        assert token in catalog
    assert catalog[token] == '103.33%'


def test_registered_chart_percent_is_accepted_without_treating_fraction_as_percent():
    from smart_reporting.reporting.trace.numeric_text import supplemental_number_values

    chart = json.dumps({
        'schema': 'chart-input/v1', 'chartId': 'chart-1', 'columns': ['name', 'share'],
        'rows': [['药品', 27.387028071755648]], 'rowCount': 1,
        'columnMeta': {'share': {'unit': '%', 'isPercent': True}},
    })
    assert supplemental_number_values([chart])['%'] == {Decimal('27.387028071755648')}


def test_project_rates_use_only_matching_frozen_budget_snapshot():
    def metric(letter, field, amount, dataset='project'):
        return {
            'factId': 'fact-' + letter * 16, 'datasetId': dataset, 'datasetSha256': 'b' * 64,
            'periodRoles': ['current'], 'field': field, 'fieldRef': 'hospital.projects.' + field,
            'aggregation': 'sum', 'unit': None, 'formula': 'sum', 'total': amount,
            'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
        }

    document = {'analysisId': 'analysis_001', 'metrics': [
        metric('a', 'budget_project_amount', 200),
        metric('b', 'contract_amount', 90),
        metric('c', 'payment_amount', 50),
    ]}
    catalog = frozen_number_catalog([json.dumps(document)])
    assert catalog['{{value:fact-bbbbbbbbbbbbbbbb:projectRatio.fact-aaaaaaaaaaaaaaaa.percentage:%}}'] == '45.00%'
    assert catalog['{{value:fact-cccccccccccccccc:projectRatio.fact-aaaaaaaaaaaaaaaa.percentage:%}}'] == '25.00%'
    document['metrics'][1]['datasetId'] = 'foreign'
    assert '{{value:fact-bbbbbbbbbbbbbbbb:projectRatio.fact-aaaaaaaaaaaaaaaa.percentage:%}}' not in frozen_number_catalog([json.dumps(document)])


def test_display_never_shows_negative_zero_or_hides_nonzero_amounts_as_zero():
    assert format_fact_value(-0.001, '%') == '0.00%'
    catalog = frozen_number_catalog([_budget_document()])
    prefix = '{{value:fact-aaaaaaaaaaaaaaaa:budgetComparison.fact-bbbbbbbbbbbbbbbb.'
    # 非零差额（-10万元）换算到亿元会显示为 0.00：亿元引用改按万元显示；真实的零差额仍可显示。
    assert catalog[prefix + '2025-01.difference:亿元}}'] == '-10.00万元'
    assert catalog[prefix + '2025-01.difference:万元}}'] == '-10.00万元'
    assert catalog[prefix + '2025-02.difference:亿元}}'] == '0亿元'
    # 非零差额舍入为 0.00亿元的原值不作为亿元依据，手写“0.00亿元”不能借它通过核对。
    from smart_reporting.reporting.trace.numeric_text import frozen_number_values

    assert Decimal('-0.001') not in frozen_number_values([_budget_document()], catalog)['亿元']


def test_budget_difference_direction_follows_frozen_sign():
    from smart_reporting.reporting.trace.numeric_text import (
        align_placeholder_direction,
        normalize_signed_wording,
    )

    document = _budget_document()
    token = '{{value:fact-aaaaaaaaaaaaaaaa:budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-01..2025-03.difference:万元}}'
    rendered = render_frozen_numbers(
        align_placeholder_direction(f'1—3月较预算减少{token}。', [document]),
        frozen_number_catalog([document]),
    )
    assert replace_unregistered_numbers(normalize_signed_wording(rendered), [document]) == '1—3月较预算增加10.00万元。'


@pytest.mark.parametrize(('rate', 'text', 'expected'), [
    # 比率主语 + 方向词描述比率本身升降到多少：不能改写动作词或去掉负号。
    (5.0332, '收入增速下降为{{value:fact-cccccccccccccccc:changeRate:%}}。', '收入增速下降为5.03%。'),
    (5.0332, '同比增幅回落为{{value:fact-cccccccccccccccc:changeRate:%}}。', '同比增幅回落为5.03%。'),
    (-5.0332, '收入增速下降为{{value:fact-cccccccccccccccc:changeRate:%}}。', '收入增速下降为-5.03%。'),
    (-5.0332, '增长率降低为{{value:fact-cccccccccccccccc:changeRate:%}}。', '增长率降低为-5.03%。'),
])
def test_rate_level_wording_is_not_treated_as_direction(rate, text, expected):
    from smart_reporting.reporting.trace.content_review import review_content
    from smart_reporting.reporting.trace.numeric_text import (
        align_placeholder_direction,
        normalize_signed_wording,
    )

    document = _comparison_document(5, rate)
    rendered = render_frozen_numbers(
        align_placeholder_direction(text, [document]), frozen_number_catalog([document])
    )
    assert replace_unregistered_numbers(normalize_signed_wording(rendered), [document]) == expected
    assert not [item for item in review_content(text, [document])
                if item.startswith(('方向', '符号重复'))]


@pytest.mark.parametrize(('text', 'expected'), [
    # 省略单位的登记值：核对通过并补全唯一单位。
    ('医院收入1.23亿，门诊量35.3万。', '医院收入1.23亿元，门诊量35.3万人次。'),
    ('收入12,345.68万。', '收入12,345.68万元。'),
    # 省略单位的手写数值同样无依据。
    ('收入约9.99亿，门诊量88万。', '收入约待核实，门诊量待核实。'),
    # 后接汉字的“2万多名”“上万”不是完整数量，不处理。
    ('约2万多名患者，上万人次。', '约2万多名患者，上万人次。'),
])
def test_numbers_with_omitted_units_are_verified(text, expected):
    document = json.dumps({'analysisId': 'analysis_001', 'metrics': [
        {'factId': 'fact-' + letter * 16, 'datasetId': 'current', 'datasetSha256': 'b' * 64,
         'periodRoles': ['current'], 'field': field, 'fieldRef': 'hospital.' + field,
         'aggregation': 'sum', 'unit': unit, 'formula': 'sum', 'total': total,
         'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0}
        for letter, field, unit, total in (('a', 'revenue', '元', 123456789), ('e', 'visits', '人次', 353000))
    ]})
    assert replace_unregistered_numbers(text, [document]) == expected


def _rate_comparison_document(change):
    return json.dumps({
        'analysisId': 'analysis_001',
        'metrics': [{
            'factId': 'fact-' + 'a' * 16, 'datasetId': 'current', 'datasetSha256': 'b' * 64,
            'periodRoles': ['current'], 'field': 'bed_rate', 'fieldRef': 'hospital.bed_rate',
            'aggregation': 'average', 'unit': '%', 'formula': 'avg(bed_rate)', 'total': 83.2 + change,
            'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
        }],
        'comparisons': [{
            'factId': 'fact-' + 'c' * 16, 'comparisonType': 'yoy', 'field': 'bed_rate',
            'fieldRef': 'hospital.bed_rate', 'currentDatasetId': 'current', 'baselineDatasetId': 'base',
            'currentDatasetSha256': 'b' * 64, 'baselineDatasetSha256': 'c' * 64,
            'currentTotal': 83.2 + change, 'baselineTotal': 83.2, 'change': change,
            'changeRate': change / 83.2 * 100, 'formula': 'x', 'unit': '%',
        }],
    })


@pytest.mark.parametrize(('change', 'text', 'expected'), [
    # 百分数指标的变化额是两项百分数之差，按百分点显示；数值引用名不变。
    (2.1, '床位使用率同比提高{{value:fact-cccccccccccccccc:change:%}}，由{{value:fact-cccccccccccccccc:baselineTotal:%}}升至{{value:fact-cccccccccccccccc:currentTotal:%}}。',
     '床位使用率同比提高2.10个百分点，由83.20%升至85.30%。'),
    (-2.1, '床位使用率同比下降{{value:fact-cccccccccccccccc:change:%}}。', '床位使用率同比下降2.10个百分点。'),
    (-2.1, '床位使用率同比提高{{value:fact-cccccccccccccccc:change:%}}。', '床位使用率同比降低2.10个百分点。'),
    # 相对变化率仍是百分数。
    (2.1, '床位使用率同比增长{{value:fact-cccccccccccccccc:changeRate:%}}。', '床位使用率同比增长2.52%。'),
    # 手写成百分数、但只对得上登记百分点差值的，改写单位；对不上的照常替换。
    (2.1, '床位使用率同比提高2.10%。', '床位使用率同比提高2.10个百分点。'),
    (-2.1, '床位使用率同比下降2.1%。', '床位使用率同比下降2.1个百分点。'),
    (2.1, '床位使用率同比提高3.40%。', '床位使用率同比提高待核实。'),
])
def test_percent_metric_change_is_published_in_percentage_points(change, text, expected):
    from smart_reporting.reporting.trace.numeric_text import (
        align_placeholder_direction,
        normalize_signed_wording,
    )

    document = _rate_comparison_document(change)
    catalog = frozen_number_catalog([document])
    rendered = render_frozen_numbers(align_placeholder_direction(text, [document]), catalog)
    assert replace_unregistered_numbers(normalize_signed_wording(rendered), [document]) == expected


def test_percent_metric_change_review_and_display_unit():
    from smart_reporting.reporting.trace.content_review import review_content
    from smart_reporting.reporting.trace.fact_service import fact_display_unit
    from smart_reporting.reporting.trace.subject_builder import formatted_value_matches

    document = _rate_comparison_document(2.1)
    contents = [document]
    assert not [warning for warning in review_content('床位使用率同比提高2.10个百分点。', contents)
                if '百分点' in warning or '冻结依据' in warning]
    warnings = review_content('床位使用率同比提高2.10%。', contents)
    assert any('应写为2.10个百分点' in warning for warning in warnings)
    assert not any('冻结依据' in warning for warning in warnings)

    comparison = json.loads(document)['comparisons'][0]
    assert fact_display_unit(comparison) == '个百分点'
    assert fact_display_unit(json.loads(document)['metrics'][0]) == '%'
    assert formatted_value_matches('同比提高2.10个百分点', 2.1, '个百分点')
    assert not formatted_value_matches('同比提高2.10%', 2.1, '个百分点')


@pytest.mark.parametrize(('text', 'expected'), [
    # 按书写精度核对通过的数值，超过两位小数时按数值目录的显示精度舍入。
    ('收入同比增长5.0332%。', '收入同比增长5.03%。'),
    ('本期收入1.3654亿元。', '本期收入1.37亿元。'),
    ('本期收入1.3654亿，', '本期收入1.37亿元，'),
    # 两位及以内小数、整数与千分位写法保持原样。
    ('收入同比增长5.03%，增长5.0%。', '收入同比增长5.03%，增长5.0%。'),
    ('收入为130,000,000元。', '收入为130,000,000元。'),
])
def test_verified_numbers_are_published_at_display_precision(text, expected):
    document = _comparison_document(6543211, 5.0332)
    assert replace_unregistered_numbers(text, [document]) == expected


def test_display_precision_keeps_tiny_values_readable():
    from smart_reporting.reporting.trace.numeric_text import _display_precision

    assert _display_precision('0.0042') == '0.0042'
    assert _display_precision('-5.0350') == '-5.04'
    assert _display_precision('1,234.5678') == '1,234.57'



@pytest.mark.parametrize(('token', 'expected'), [
    # 换算后不足 1 的非零值改用能写成不小于 1 的最大单位，引用名不变。
    ('{{value:fact-cccccccccccccccc:change:亿元}}', '654.32万元'),
    ('{{value:fact-cccccccccccccccc:change:万元}}', '654.32万元'),
    ('{{value:fact-cccccccccccccccc:currentTotal:亿元}}', '1.37亿元'),
])
def test_small_scaled_values_are_displayed_in_a_readable_unit(token, expected):
    document = _comparison_document(6543211, 5.0332)
    catalog = frozen_number_catalog([document])
    assert catalog[token] == expected
    # 手写的“0.07亿元”仍按书写精度核对通过，不被替换。
    assert replace_unregistered_numbers('同比增加0.07亿元。', [document]) == '同比增加0.07亿元。'


def test_model_table_cells_are_checked_against_the_header_unit():
    from smart_reporting.reporting.trace.numeric_text import table_unit_cells

    document = _comparison_document(6543211, 5.0332)
    table = (
        "| 项目 | 金额（万元） | 同比（%） | 排名 |\n| --- | ---: | ---: | ---: |\n"
        "| 本期收入 | 13,654.32 | 5.0332 | 1 |\n| 编造项目 | 9,999.99 | 7.77 | 2 |\n"
        "| 带单位 | 654.32万元 | — | 3 |"
    )
    # 只取表头带单位列的裸数字：排名列、已带单位与“—”单元格不在此列。
    assert [(number, unit) for _start, _end, number, unit in table_unit_cells(table)] == [
        ("13,654.32", "万元"), ("5.0332", "%"), ("9,999.99", "万元"), ("7.77", "%"),
    ]
    # 有依据的单元格按显示精度保留，编造的数字替换为待核实。
    assert replace_unregistered_numbers(table, [document]) == (
        "| 项目 | 金额（万元） | 同比（%） | 排名 |\n| --- | ---: | ---: | ---: |\n"
        "| 本期收入 | 13,654.32 | 5.03 | 1 |\n| 编造项目 | 待核实 | 待核实 | 2 |\n"
        "| 带单位 | 654.32万元 | — | 3 |"
    )


@pytest.mark.parametrize(('text', 'expected'), [
    # 倍数只能由登记的本期÷基期合计、变化率或比率得出；按书写精度核对并按显示精度保留。
    ('本期收入是上年同期的1.0503倍。', '本期收入是上年同期的1.05倍。'),
    ('收入增长0.05倍。', '收入增长0.05倍。'),
    ('本期收入是上年同期的3.2倍。', '本期收入是上年同期的待核实。'),
    # “倍数”一词与统计阈值不是事实倍数。
    ('倍数关系明显，超过均值3倍标准差。', '倍数关系明显，超过均值3倍标准差。'),
])
def test_multiples_need_a_registered_ratio(text, expected):
    document = _comparison_document(6543211, 5.0332)
    assert replace_unregistered_numbers(text, [document]) == expected



def test_pipe_less_model_tables_are_checked_too():
    document = _comparison_document(6543211, 5.0332)
    table = "项目 | 金额（万元）\n--- | ---:\n本期收入 | 13,654.32\n编造项目 | 9,999.99"
    assert replace_unregistered_numbers(table, [document]) == (
        "项目 | 金额（万元）\n--- | ---:\n本期收入 | 13,654.32\n编造项目 | 待核实"
    )
    # 分隔线与 setext 标题不是表格。
    text = "说明 | 金额（万元）\n\n---\n\n9,999.99"
    assert replace_unregistered_numbers(text, [document]) == text



def test_number_guide_explains_comparison_type_and_window():
    from smart_reporting.reporting.trace.numeric_text import frozen_number_guide

    document = json.loads(_comparison_document(6543211, 5.0332))
    document['comparisons'][0].update({'periodStart': '2025-01', 'periodEnd': '2025-09'})
    content = json.dumps(document)
    guide = frozen_number_guide([content], frozen_number_catalog([content]))
    comparison = next(item for item in guide if item.get('kind') == 'comparison')
    # 比较口径与累计窗口随引用一起给到模型，避免写成单月变化或混用同比环比。
    assert (comparison['comparisonType'], comparison['periodStart'], comparison['periodEnd']) == ('同比', '2025-01', '2025-09')
    assert comparison['references']['changeRate'] == '{{value:fact-cccccccccccccccc:changeRate:%}}'
    assert '累计窗口' in comparison['meaning']



@pytest.mark.parametrize(('aggregation', 'meaning'), [
    ('sum', '完整期间合计'),
    ('average', '完整期间平均值，不能称为合计、累计或总额'),
])
def test_number_guide_states_how_to_read_the_total(aggregation, meaning):
    from smart_reporting.reporting.trace.numeric_text import frozen_number_guide

    document = json.loads(_comparison_document(6543211, 5.0332))
    document['metrics'][0]['aggregation'] = aggregation
    content = json.dumps(document)
    guide = frozen_number_guide([content], frozen_number_catalog([content]))
    metric = next(item for item in guide if item['factId'] == 'fact-' + 'a' * 16)
    # 平均口径的 total 是均值：说明随引用一起给到模型，避免写成“合计”。
    assert (metric['total']['aggregation'], metric['total']['meaning']) == (aggregation, meaning)



def test_adjacent_month_changes_are_registered_from_frozen_monthly_values():
    # “2月环比增长20.00%”是按登记月度值计算的相邻两月变化：服务端登记后可引用，模型写对时不被替换为待核实。
    from smart_reporting.reporting.trace.numeric_text import frozen_number_guide

    metric = {
        'factId': 'fact-' + 'a' * 16, 'datasetId': 'current', 'datasetSha256': 'b' * 64,
        'periodRoles': ['current'], 'field': 'amount', 'fieldRef': 'hospital.amount',
        'aggregation': 'sum', 'unit': '元', 'formula': 'sum(amount)', 'total': 4280000,
        'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0, 'periodGranularity': 'month',
        'periodValues': [{'period': period, 'value': value} for period, value in
                         (('2025-01', 1000000), ('2025-02', 1200000), ('2025-03', 1080000), ('2025-05', 1000000))],
    }
    content = json.dumps({'analysisId': 'analysis_001', 'metrics': [metric]})
    catalog = frozen_number_catalog([content])
    assert catalog['{{value:fact-aaaaaaaaaaaaaaaa:periodChanges.1:万元}}'] == '20.00万元'
    assert catalog['{{value:fact-aaaaaaaaaaaaaaaa:periodChangeRates.1:%}}'] == '20.00%'
    assert catalog['{{value:fact-aaaaaaaaaaaaaaaa:periodChangeRates.2:%}}'] == '-10.00%'
    # 3月与5月不相邻：不登记“环比”。
    assert not [token for token in catalog if 'periodChange' in token and token.split(':')[2].endswith('.3')]
    # 数值说明给显示值（金额按万元）及可直接使用的服务端引用；引用不进模型可见目录，避免目录膨胀，
    # 但给出引用后模型不必照着键名自造 “monthOverMonth.N”。
    guide = frozen_number_guide([content], catalog)[0]['monthlyStatistics']['monthOverMonth']
    prefix = '{{value:fact-aaaaaaaaaaaaaaaa:'
    assert guide == [
        {'period': '2025-02', 'change': '20.00万元', 'changeRate': '20.00%',
         'reference': prefix + 'periodChanges.1:万元}}', 'rateReference': prefix + 'periodChangeRates.1:%}}'},
        {'period': '2025-03', 'change': '-12.00万元', 'changeRate': '-10.00%',
         'reference': prefix + 'periodChanges.2:万元}}', 'rateReference': prefix + 'periodChangeRates.2:%}}'},
    ]
    assert all(catalog[item['reference']] == item['change'] and catalog[item['rateReference']] == item['changeRate']
               for item in guide)
    from smart_reporting.reporting.trace.numeric_text import prompt_number_catalog
    prompt = prompt_number_catalog(catalog)
    assert not [token for token in prompt if 'periodChange' in token]
    assert set(catalog) - set(prompt) == {token for token in catalog if 'periodChange' in token}
    text = '2月收入环比增长20.00%，增加20.00万元；3月环比下降10.00%；5月环比增长7.41%。'
    assert replace_unregistered_numbers(text, [content]) == (
        '2月收入环比增长20.00%，增加20.00万元；3月环比下降10.00%；5月环比增长待核实。'
    )


def test_group_shares_are_registered_from_frozen_groups_and_total():
    # “心内科占全院门诊收入的23.85%”按登记分组值与合计计算：服务端登记后写对不被替换，写错仍替换。
    from smart_reporting.reporting.trace.numeric_text import prompt_number_catalog

    sample = (Path(__file__).parent / 'fixtures' / 'report_quality' / 'facts.json').read_text(encoding='utf-8')
    catalog = frozen_number_catalog([sample])
    assert catalog['{{value:fact-aaaaaaaaaaaaaaaa:groupShares.topGroups.0:%}}'] == '23.85%'
    assert catalog['{{value:fact-aaaaaaaaaaaaaaaa:groupShares.bottomGroups.0:%}}'] == '8.21%'
    # 只供服务端核对，不进模型可见目录。
    assert not [token for token in prompt_number_catalog(catalog) if 'groupShares' in token]
    text = '心内科门诊收入占全院门诊收入的23.85%，眼科占8.21%，骨科占25.00%。'
    assert replace_unregistered_numbers(text, [sample]) == '心内科门诊收入占全院门诊收入的23.85%，眼科占8.21%，骨科占待核实。'


def test_group_shares_are_not_registered_for_averages_or_negative_values():
    document = json.loads((Path(__file__).parent / 'fixtures' / 'report_quality' / 'facts.json').read_text(encoding='utf-8'))
    document['metrics'][0]['aggregation'] = 'average'
    document['metrics'][1]['negativeCount'] = 2
    catalog = frozen_number_catalog([json.dumps(document)])
    assert not [token for token in catalog if 'groupShares' in token]


@pytest.mark.parametrize(('text', 'expected'), [
    # 变化率写成百分点：数值对得上登记的同比/相邻月变化率、对不上百分点差值时改回“%”。
    ('门诊收入同比增长11个百分点，住院收入同比下降3.00个百分点。', '门诊收入同比增长11%，住院收入同比下降3.00%。'),
    ('2月门诊收入环比增长10.00个百分点。', '2月门诊收入环比增长10.00%。'),
    # 占比、比率、增速的变化本以百分点计；对不上任何变化率的百分点交给复核，均不改写。
    ('门诊收入占比同比提高11.00个百分点，增速提高11.00个百分点，增长7.77个百分点。',
     '门诊收入占比同比提高11.00个百分点，增速提高11.00个百分点，增长7.77个百分点。'),
])
def test_change_rates_written_as_percent_points_are_corrected(text, expected):
    sample = Path(__file__).parent / 'fixtures' / 'report_quality' / 'facts.json'
    assert replace_unregistered_numbers(text, [sample.read_text(encoding='utf-8')]) == expected


def test_unicode_minus_keeps_registered_negative_values():
    # 模型常用 Unicode 减号“−”写负值：入模清洗改为半角后，登记的负变化率与变化额不再被替换为待核实。
    from smart_reporting.reporting.workflow.runtime.phase_models import SectionBlockContent

    sample = (Path(__file__).parent / 'fixtures' / 'report_quality' / 'facts.json').read_text(encoding='utf-8')
    block = SectionBlockContent(markdown='### 住院收入\n\n住院收入同比−3.00%，变化额为−195.00万元。\n\n| 科室 | 同比 |\n| --- | ---: |\n| 住院 | −3.00% |')
    assert replace_unregistered_numbers(block.markdown, [sample]) == (
        '### 住院收入\n\n住院收入同比-3.00%，变化额为-195.00万元。\n\n| 科室 | 同比 |\n| --- | ---: |\n| 住院 | -3.00% |'
    )


def test_number_guide_spells_out_month_coverage():
    from smart_reporting.reporting.trace.numeric_text import _month_coverage

    assert _month_coverage([f'2025-{month:02d}' for month in range(1, 11)]) == '2025年1—10月（10个月），不是全年'
    assert _month_coverage([f'2025-{month:02d}-01' for month in range(1, 13)]) == '2025年1—12月（12个月）'
    assert _month_coverage(['2025-01', '2025-03']) == '2025年1月、3月（2个月），不是全年'
    # 跨年或非月度期间不给覆盖说明。
    assert _month_coverage(['2024-12', '2025-01']) is None
    assert _month_coverage(['2025']) is None


@pytest.mark.parametrize(('text', 'expected'), [
    # 人次（就诊次数）写成人数且数值对得上登记人次时改回人次。
    ('门诊量35.30万人。', '门诊量35.30万人次。'),
    ('门诊接诊353,000人。', '门诊接诊353,000人次。'),
    # 对不上人次的人数（职工、人口等）不改写。
    ('门诊量99.99万人，医生120人，服务人口35.3万人口。', '门诊量99.99万人，医生120人，服务人口35.3万人口。'),
])
def test_visit_counts_written_as_persons_are_corrected(text, expected):
    metric = {
        'factId': 'fact-' + 'a' * 16, 'datasetId': 'current', 'datasetSha256': 'b' * 64,
        'periodRoles': ['current'], 'field': 'visits', 'fieldRef': 'hospital.visits',
        'aggregation': 'sum', 'unit': '人次', 'formula': 'sum', 'total': 353000,
        'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
    }
    assert replace_unregistered_numbers(text, [json.dumps({'analysisId': 'analysis_001', 'metrics': [metric]})]) == expected


@pytest.mark.parametrize(('text', 'expected'), [
    # 整数界限由登记值支持（门诊收入 3,774.00 万元）：保留，不替换成“超过待核实”。
    ('门诊收入超过3,700万元。', '门诊收入超过3,700万元。'),
    ('门诊收入近4,000万元。', '门诊收入近4,000万元。'),
    ('门诊收入超过3,000万元。', '门诊收入超过3,000万元。'),
    # 界限须是登记值按 1～2 位有效数字朝界限方向取整的结果：方向相反、无登记值支持、带小数的仍替换。
    ('门诊收入超过3,800万元。', '门诊收入超过待核实。'),
    ('门诊收入不足3,700万元。', '门诊收入不足待核实。'),
    ('门诊收入超过5,000万元。', '门诊收入超过待核实。'),
    ('门诊收入超过3,700.50万元。', '门诊收入超过待核实。'),
])
def test_integer_bounds_supported_by_registered_values_are_kept(text, expected):
    sample = Path(__file__).parent / 'fixtures' / 'report_quality' / 'facts.json'
    assert replace_unregistered_numbers(text, [sample.read_text(encoding='utf-8')]) == expected


def test_group_gaps_are_registered_between_top_groups():
    # “心内科较骨科多140.00万元”：两个登记分组值之差，服务端登记后写对不被替换，写错仍替换。
    from smart_reporting.reporting.trace.numeric_text import prompt_number_catalog

    sample = (Path(__file__).parent / 'fixtures' / 'report_quality' / 'facts.json').read_text(encoding='utf-8')
    catalog = frozen_number_catalog([sample])
    assert catalog['{{value:fact-aaaaaaaaaaaaaaaa:groupGaps.0-1:万元}}'] == '140.00万元'
    assert not [token for token in prompt_number_catalog(catalog) if 'groupGaps' in token]
    text = '心内科门诊收入较骨科多140.00万元，骨科较儿科多240.00万元，较眼科多500.00万元。'
    assert replace_unregistered_numbers(text, [sample]) == '心内科门诊收入较骨科多140.00万元，骨科较儿科多240.00万元，较眼科多待核实。'


@pytest.mark.parametrize(('unit', 'difference'), [
    (None, None), ('', None), ('元', '-100,000元'), ('%', '-100,000.00个百分点'),
])
def test_budget_difference_catalog_and_guide_require_units(unit, difference):
    from smart_reporting.reporting.trace.numeric_text import frozen_number_guide

    document = json.loads(_budget_document())
    for metric in document['metrics']:
        metric['unit'] = unit
    contents = [json.dumps(document)]
    catalog = frozen_number_catalog(contents)
    guide = frozen_number_guide(contents, catalog)
    references = guide[0]['budgetComparisons'][0]['references']
    assert catalog[references['percentage']] == '90.00%'
    if difference is None:
        assert references['difference'] is None
        assert not any('budgetComparison.' in token and '.difference:' in token for token in catalog)
    else:
        assert catalog[references['difference']] == difference


@pytest.mark.parametrize('reverse', [False, True])
def test_same_display_does_not_hide_conflicting_unrounded_values(reverse):
    from smart_reporting.reporting.trace.numeric_text import frozen_number_values
    from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers

    first = json.loads(_comparison_document(5, 5, total=30.001))
    second = json.loads(json.dumps(first))
    second['metrics'][0]['total'] = 30.002
    documents = [second, first, second] if reverse else [first, second, first]
    contents = [json.dumps(document) for document in documents]
    token = '{{value:fact-aaaaaaaaaaaaaaaa:total:元}}'
    catalog = frozen_number_catalog(contents)
    assert catalog[token] == '数值待核实'
    assert Decimal('30.001') not in frozen_number_values(contents, catalog).get('元', ())
    markdown, references, notices = render_bound_numbers('收入' + token + '。', contents, key='conflict')
    assert markdown == '收入数值待核实。'
    assert not references
    assert len(notices) == 1 and notices[0].kind == 'numeric_unverified'
    identical = [json.dumps(first), json.dumps(first)]
    assert frozen_number_catalog(identical)[token] == '30.00元'


@pytest.mark.parametrize('chart', [False, True])
@pytest.mark.parametrize(('unit', 'value', 'text'), [
    ('万人次', 3.53, '接诊35,300人次。'),
    ('人次', 35300, '接诊3.53万人次。'),
])
def test_supplement_visit_unit_conversion_is_bidirectional(chart, unit, value, text):
    from smart_reporting.reporting.trace.content_review import review_content
    from smart_reporting.reporting.trace.numeric_text import supplemental_number_values

    table = {'columns': ['visits'], 'rows': [[value]], 'columnMeta': {'visits': {'unit': unit}}}
    document = {**table, 'schema': 'chart-input/v1'} if chart else {'findings': [table]}
    contents = [json.dumps(document)]
    numbers = supplemental_number_values(contents)
    assert numbers['人次'] == {Decimal('35300')}
    assert numbers['万人次'] == {Decimal('3.53')}
    assert replace_unregistered_numbers(text, contents) == text
    assert review_content(text, contents) == []
    assert replace_unregistered_numbers('金额35,300元。', contents) == '金额待核实。'


@pytest.mark.parametrize(('change', 'rate', 'text', 'expected'), [
    (6500000, 5, '收入增长1.05倍。', '收入增长待核实。'),
    (6500000, 5, '收入增长了约 1.05倍。', '收入增长了约 待核实。'),
    (6500000, 5, '收入是同期的0.05倍。', '收入是同期的待核实。'),
    (6500000, 5, '收入下降0.05倍。', '收入下降待核实。'),
    (6500000, 5, '收入是同期的-1.05倍。', '收入是同期的待核实。'),
    (6500000, 5, '收入增长至同期的1.05倍。', '收入增长至同期的1.05倍。'),
    (6500000, 5, '收入增长了0.05倍。', '收入增长了0.05倍。'),
    (-6500000, -5, '收入增长0.05倍。', '收入增长待核实。'),
    (-6500000, -5, '收入减少了0.05倍。', '收入减少了0.05倍。'),
    (-260000000, -200, '净收入是同期的1倍。', '净收入是同期的待核实。'),
    (-260000000, -200, '净收入是同期的-1倍。', '净收入是同期的-1倍。'),
])
def test_multiple_basis_preserves_kind_and_sign(change, rate, text, expected):
    assert replace_unregistered_numbers(text, [_comparison_document(change, rate)]) == expected


@pytest.mark.parametrize('reverse', [False, True])
def test_conflicting_totals_cannot_support_multiples(reverse):
    contents = [_comparison_document(6500000, 5), _comparison_document(26000000, 20)]
    if reverse:
        contents.reverse()
    assert replace_unregistered_numbers('本期是基期的1.05倍或1.2倍，增长0.2倍。', contents) == (
        '本期是基期的待核实或待核实，增长待核实。'
    )


@pytest.mark.parametrize(('value', 'unit', 'text', 'supported'), [
    (10, '元', '收入0.00万元', False),
    (-10, '元', '收入下降0.00万元', False),
    (10, '人次', '门诊量0.00万人次', False),
    (-10, '人次', '门诊量减少0.00万人次', False),
    (0, '元', '收入0.00万元', True),
    (0, '人次', '门诊量0.00万人次', True),
    (0, '人次', '门诊量0万人次', True),
    (0, '元', '收入0亿元', True),
    (100, '元', '收入0.01万元', True),
    (100, '人次', '门诊量0.01万人次', True),
])
def test_editor_match_does_not_turn_nonzero_values_into_zero(value, unit, text, supported):
    from smart_reporting.reporting.trace.subject_builder import (
        claim_status,
        formatted_value_matches,
    )

    assert formatted_value_matches(text, value, unit) is supported
    result = claim_status(text + '[[claim:test-zero]]。', 'test-zero', value, expected_unit=unit)
    assert (result['status'] == 'valid') is supported


@pytest.mark.parametrize('metrics', [
    42,
    'not-a-fact-list',
    [None],
    [{'periodRoles': None}],
    [{'periodRoles': ['current'], 'periodGranularity': 'month',
      'periodValues': [{'period': '2025-01'}]}],
    [{'periodRoles': ['current'], 'periodGranularity': 'month',
      'periodValues': [{'period': '2025-01', 'value': 'not-a-number'}]}],
    [{'periodRoles': ['current'], 'periodGranularity': 'month',
      'periodValues': [{'period': '2025-01', 'value': float('nan')}]}],
])
def test_extrema_review_skips_malformed_supplementary_metrics(metrics):
    from smart_reporting.reporting.trace.numeric_text import period_extrema_warnings

    bundle = {'analysisId': 'analysis_bad', 'metrics': metrics}
    text = '[[analysis:analysis_bad]]1月为收入最高。'
    assert period_extrema_warnings(text, [bundle]) == []
    assert correct_period_extrema(text, [json.dumps(bundle)]) == text


@pytest.mark.parametrize(('period', 'valid'), [
    ('2025-00', False), ('2025-13', False), ('2025-02-30', False), ('2025-02-15', False),
    ('2025-02', True), ('2025-02-01', True),
])
def test_monthly_derivations_require_real_month_start_labels(period, valid):
    from smart_reporting.reporting.trace.numeric_text import (
        _month_coverage,
        period_extrema_warnings,
    )

    document = json.loads(_monthly_document(values=(10,)))
    document['metrics'][0]['periodValues'][0]['period'] = period
    catalog = frozen_number_catalog([json.dumps(document)])
    token = '{{value:fact-aaaaaaaaaaaaaaaa:monthlyAverage:元}}'
    assert (token in catalog) is valid
    assert (_month_coverage([period]) is not None) is valid
    warnings = period_extrema_warnings('[[analysis:analysis_001]]1月收入最高。', [document])
    assert bool(warnings) is valid


@pytest.mark.parametrize('period', ['2025-00', '2025-13', '2025-02-30', '2025-02-15'])
def test_budget_derivations_skip_invalid_month_labels(period):
    document = json.loads(_monthly_document(values=(10,)))
    actual = document['metrics'][0]
    actual.update(field='actual_amount', fieldRef='hospital.actual_amount')
    actual['periodValues'][0]['period'] = period
    budget = {**actual, 'factId': 'fact-' + 'b' * 16, 'field': 'budget_amount',
              'fieldRef': 'hospital.budget_amount'}
    document['metrics'].append(budget)
    catalog = frozen_number_catalog([json.dumps(document)])
    assert not any('budgetComparison.' in token for token in catalog)


@pytest.mark.parametrize('months', [(1, 3, 2), (3, 1, 2)])
def test_prefix_totals_do_not_assign_later_months_to_an_earlier_end(months):
    from smart_reporting.reporting.trace.numeric_text import frozen_number_guide
    from smart_reporting.reporting.trace.semantic_bindings import resolve_number_reference

    document = json.loads(_monthly_document(values=(10, 20, 30)))
    for bucket, month in zip(document['metrics'][0]['periodValues'], months, strict=True):
        bucket['period'] = f'2025-{month:02d}'
    contents = [json.dumps(document)]
    catalog = frozen_number_catalog(contents)
    invalid = '{{value:fact-aaaaaaaaaaaaaaaa:periodTotals.0-2:元}}'
    assert invalid not in catalog
    assert resolve_number_reference(invalid, contents) is None
    guide = frozen_number_guide(contents, catalog)[0]['monthlyStatistics']
    assert all(row['reference'] is not None for row in guide['prefixTotals'])
    # 月均与极值不依赖月桶排列；原始序列和 token 索引保持不变。
    assert '{{value:fact-aaaaaaaaaaaaaaaa:monthlyAverage:元}}' in catalog
    assert catalog['{{value:fact-aaaaaaaaaaaaaaaa:periodValues.2:元}}'] == '30元'


@pytest.mark.parametrize("malformed", [None, 42, "invalid", {}, {"periodRoles": None}])
def test_extrema_rewrite_uses_valid_monthly_fact_amid_malformed_records(malformed):
    from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers

    bundle = {
        "analysisId": "analysis_001",
        "metrics": [malformed, {
            "periodRoles": ["current"], "periodGranularity": "month",
            "periodValues": [
                {"period": "2025-01", "value": 10},
                {"period": "2025-02", "value": 20},
            ],
        }],
    }
    text = "1月收入最高。"
    contents = [json.dumps(bundle)]
    assert correct_period_extrema(text, contents) == "收入最高月份为2月。"
    markdown, _references, _notices = render_bound_numbers(text, contents, key="mixed-metrics")
    assert markdown == "收入最高月份为2月。"


def test_server_derives_gaps_and_top_share_sums_only_for_operands_named_in_the_paragraph():
    from smart_reporting.reporting.trace.content_review import review_content

    supplement = json.dumps({'findings': [{'name': '院区分布', 'columns': ['院区', '门诊人次', '不含急诊门诊人次', '占比'],
        'columnMeta': {'门诊人次': {'unit': '人次'}, '不含急诊门诊人次': {'unit': '人次'},
                       '占比': {'unit': '%', 'isPercent': True}},
        'rows': [['总部', 5736882, 5312051, 76.68], ['北部', 1220000, 1100000, 16.37], ['远洋', 50000, 40000, 6.95]]}]})
    budget = json.loads(_budget_document())
    for metric, name in zip(budget['metrics'], ('实际收入', '预算收入'), strict=True):
        metric['displayName'] = name
    # 实际 90/95/133 万、预算各 100 万：3月差额 33 万，与环比变化额（38 万）区分。
    actual = budget['metrics'][0]
    actual['periodValues'] = [{'period': f'2025-{index + 1:02d}', 'value': value}
                              for index, value in enumerate((900000, 950000, 1330000))]
    actual['total'] = 3180000
    contents = [json.dumps(budget), supplement]
    # 同表两列逐行差额、降序前两项合计占比、同一分析同期间两项事实的月度差额（实际减预算）。
    derived = ('总部门诊人次与不含急诊门诊人次相差424,831人次。\n\n总部与北部合计占比93.05%。'
               '\n\n1月实际收入较预算收入少10.00万元。')
    assert replace_unregistered_numbers(derived, contents) == derived
    assert not any('冻结依据' in warning for warning in review_content(derived, contents))
    # 4,516,882 = 总部 − 北部，但正文写的是总部与远洋：操作数不符，仍替换。
    wrong_pair = '总部门诊人次比远洋多4,516,882人次。'
    assert replace_unregistered_numbers(wrong_pair, contents) == '总部门诊人次比远洋多待核实。'
    # 预算只登记到2月（窗口不同）：两边都有的月份仍可比，预算缺少的3月不补算。
    assert replace_unregistered_numbers('3月实际收入较预算收入多33.00万元。', contents) == '3月实际收入较预算收入多33.00万元。'
    budget['metrics'][1]['periodValues'] = budget['metrics'][1]['periodValues'][:2]
    shorter = [json.dumps(budget), supplement]
    assert replace_unregistered_numbers('1月实际收入较预算收入少10.00万元。', shorter) == '1月实际收入较预算收入少10.00万元。'
    assert replace_unregistered_numbers('3月实际收入较预算收入多33.00万元。', shorter) == '3月实际收入较预算收入多待核实。'
    # 百分数之差是百分点，不按百分数补算；无来源的数字仍替换。
    unrelated = '总部较北部高60.31%，另有123,457人次。'
    assert replace_unregistered_numbers(unrelated, contents) == '总部较北部高待核实，另有待核实。'


def test_top_share_sums_skip_total_rows_and_cover_long_two_sided_tables():
    # 回放：院区表带“合计”行；预算类型表有预算占比、实际占比两列；预算单元表 40 行且首列为编码。
    campus = {'name': '院区', 'columns': ['院区', '金额', '占比'],
              'columnMeta': {'金额': {'unit': '元'}, '占比': {'unit': '%', 'isPercent': True}},
              'rows': [['总部院区', 8529370395, 76.6786], ['北部院区', 1820767778, 16.3686],
                       ['转化', 357747450, 3.2161], ['合计', 11123541503, 100.0]]}
    types = {'name': '预算类型', 'columns': ['budget_type', '预算占比', '实际占比'],
             'columnMeta': {'预算占比': {'unit': '%', 'isPercent': True}, '实际占比': {'unit': '%', 'isPercent': True}},
             'rows': [['人员经费', 45.43, 30.75], ['卫生材料费', 33.58, 18.83], ['药品费', 0.0, 17.88],
                      ['支出预算-全院性', 12.54, 7.40], ['其他', 8.45, 2.00]]}
    units = {'name': '预算单元', 'columns': ['code', 'unit', '实际占比'],
             'columnMeta': {'实际占比': {'unit': '%', 'isPercent': True}},
             'rows': [['RJ008.01', '财务处', 38.26], ['RJ020.01', '资产管理处', 19.09], ['RJ301.01', '药剂科', 17.88]]
             + [[f'RJ9{index:02d}.01', f'单元{index}', 0.5] for index in range(40)]}
    contents = [json.dumps({'findings': [campus, types, units]})]
    accepted = ('总部院区85.29亿元与北部院区18.21亿元合计103.50亿元，占93.05%。',
                '预算端人员经费、卫生材料费两项合计79.01%。',
                # 分项名“支出预算-全院性”含“预算”，主语仍是先出现的“实际端”。
                '实际端人员经费、卫生材料费、药品费合计67.46%，支出预算-全院性另计。',
                '实际端前三为财务处、资产管理处、药剂科，合计75.23%。')
    for text in accepted:
        assert replace_unregistered_numbers(text, contents) == text
    # 长表只写“前三”不点名、或口径写反（预算端用实际占比之和），仍替换。
    assert replace_unregistered_numbers('前三位合计75.23%。', contents) == '前三位合计待核实。'
    assert replace_unregistered_numbers('预算端人员经费、卫生材料费、药品费合计67.46%。', contents) == (
        '预算端人员经费、卫生材料费、药品费合计待核实。')


def test_nested_summary_tables_and_income_cost_gaps_are_registered():
    # 回放：按科室合计挂在明细表的 tables 下；收入到11月、成本到9月。
    detail = {'name': '收入明细', 'columns': ['科室', 'amount'], 'columnMeta': {'amount': {'unit': '元'}},
              'rows': [['普通外科', 1], ['手术室', 2]],
              'tables': [{'name': '按科室合计', 'columns': ['科室', 'amount'], 'columnMeta': {'amount': {'unit': '元'}},
                          'rows': [['普通外科', 1482873737], ['手术室', 151211]]}]}
    def metric(fact, name, values):
        return {'factId': 'fact-' + fact * 16, 'datasetId': name, 'datasetSha256': fact * 64,
                'periodRoles': ['current'], 'field': 'amount', 'fieldRef': f'h.{name}.amount',
                'displayName': name, 'aggregation': 'sum', 'unit': '元', 'formula': 'sum(amount)',
                'total': sum(values), 'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
                'periodGranularity': 'month', 'periodField': 'data_date',
                'periodStart': '2025-01-01', 'periodEnd': f'2025-{len(values):02d}-01',
                'periodValues': [{'period': f'2025-{index + 1:02d}-01', 'value': value}
                                 for index, value in enumerate(values)]}
    bundle = {'analysisId': 'analysis_011', 'metrics': [
        metric('a', '收入金额', [889688670, 899035187, 500000000]),
        metric('b', '成本金额', [1191933469, 972805980]),
    ]}
    contents = [json.dumps({'findings': [detail]}), json.dumps(bundle)]
    accepted = ('普通外科收入1,482,873,737元，手术室收入151,211元。',
                # 没有比较词时，“高”的主语是紧邻其前的成本。
                '1月收入889,688,670元、成本1,191,933,469元，成本高302,244,799元。',
                # 窗口不同，按共同的1—2月累计差额核对，须写出期间。
                '2025年1—2月成本比收入多376,015,592元。')
    for text in accepted:
        assert replace_unregistered_numbers(text, contents) == text
    assert replace_unregistered_numbers('1月收入889,688,670元、成本1,191,933,469元，收入高302,244,799元。', contents) == (
        '1月收入889,688,670元、成本1,191,933,469元，收入高待核实。')
    assert replace_unregistered_numbers('成本比收入多376,015,592元。', contents) == '成本比收入多待核实。'


def test_single_character_decline_words_accept_registered_negative_magnitudes():
    document = json.loads(_budget_document())
    document['comparisons'] = [{
        'factId': 'fact-' + 'c' * 16, 'comparisonType': 'yoy', 'field': 'actual_revenue', 'fieldRef': 'h.actual_revenue',
        'currentDatasetId': 'current', 'baselineDatasetId': 'base', 'currentDatasetSha256': 'b' * 64,
        'baselineDatasetSha256': 'c' * 64, 'currentTotal': 104.43, 'baselineTotal': 115.82,
        'change': -11.39, 'changeRate': -9.83, 'formula': 'x', 'unit': '元'}]
    contents = [json.dumps(document)]
    assert replace_unregistered_numbers('实际降9.83%，较上年减11.39元。', contents) == '实际降9.83%，较上年减11.39元。'
    # “至少”不是下降：同样的数字仍按未登记替换；增长方向也不豁免。
    assert replace_unregistered_numbers('至少9.83%。', contents) == '至少待核实。'
    assert replace_unregistered_numbers('实际增9.83%。', contents) == '实际增待核实。'


def test_profile_missing_and_zero_rates_are_accepted_only_in_matching_paragraphs():
    from smart_reporting.reporting.trace.content_review import review_content

    document = json.loads(_budget_document())
    document['metrics'][0]['warnings'] = ['[rdlevel_analytic_unit] 23646 (78.7%) missing values',
                                          '[budget_medical_income] has 9673 (68.7%) zeros']
    contents = [json.dumps(document)]
    text = '四级科室字段缺失比例为78.7%，下钻受限；预算医疗收入零值行占68.7%。'
    assert replace_unregistered_numbers(text, contents) == text
    assert replace_unregistered_numbers('预算医疗收入缺失68.7%。', contents) == '预算医疗收入缺失待核实。'
    assert not any('冻结依据' in warning for warning in review_content(text, contents))
    assert replace_unregistered_numbers('收入完成率为78.7%。', contents) == '收入完成率为待核实。'
    # 含义词写在比例之后（回放：“预算支出有65.9%的行为零”）同样认可。
    after = '预算医疗收入有68.7%的行为零。'
    assert replace_unregistered_numbers(after, contents) == after


@pytest.mark.parametrize(('text', 'expected'), [
    ('覆盖2025年1月至11月共11个月度桶。', '覆盖2025年1月至11月共11个月。'),
    ('零值仅代表这两个月度桶的记录取值为零。', '零值仅代表这两个月的记录取值为零。'),
    ('月度标签为月度桶标签，不代表数据截止时点。', '月度标签为月份，不代表数据截止时点。'),
    ('均基于同一收入口径的月度桶数据。', '均基于同一收入口径的月度数据。'),
    ('11月与12月实际登记值均为0元。', '11月与12月实际记录值均为0元。'),
    ('相邻月变化额与变化贡献占比为null，不可用于比较。', '相邻月变化额与变化贡献占比为空，不可用于比较。'),
])
def test_plain_period_wording_drops_month_bucket_jargon(text, expected):
    assert plain_period_wording(text) == expected
