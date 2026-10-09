from __future__ import annotations

import json
from decimal import Decimal

import pytest

from smart_reporting.reporting.trace.numeric_text import (
    correct_period_extrema,
    format_fact_value,
    frozen_number_catalog,
    money_text_warnings,
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
