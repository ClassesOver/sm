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
    assert '冻结序列的最高月份为1月' in corrected
    assert '2月金额为最高' not in corrected


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
    assert '冻结序列的最高月份为6月' in corrected
