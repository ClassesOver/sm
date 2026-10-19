"""中性差额须绑定当前引用或操作数，修正数值遵循显示精度。"""

import json

import pytest

from smart_reporting.reporting.trace.content_review import review_content
from smart_reporting.reporting.trace.numeric_text import replace_unregistered_numbers
from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers


def difference_contents(kind='derived'):
    facts = [{
        'factId': 'fact-' + key * 16, 'code': 'budget_' + key, 'kind': 'ratio',
        'periodRole': 'current', 'numeratorMetric': 'actual_' + key,
        'denominatorMetric': 'budget_' + key, 'numerator': actual, 'denominator': 100,
        'value': actual / 100, 'percentage': actual, 'difference': actual - 100,
        'unit': '元', 'formula': 'actual/budget', 'datasetIds': ['current'],
        'datasetSha256s': ['c' * 64],
    } for key, actual in [('a', 160), ('b', 40)]]
    document = {'analysisId': 'analysis_001', 'derivedMetrics': facts}
    if kind == 'reconciliation':
        document = {'analysisId': 'analysis_001', 'reconciliations': [{
            'factId': 'fact-' + 'a' * 16, 'code': 'check_amount', 'periodRole': 'current',
            'leftMetric': 'actual', 'rightMetric': 'budget', 'grain': ['month'],
            'leftTotal': 160, 'rightTotal': 100, 'difference': 60, 'unit': '元',
            'absoluteTolerance': 0, 'relativeTolerance': 0, 'checkedGroupCount': 1,
            'failedGroupCount': 1, 'passed': False, 'formula': 'actual-budget',
            'datasetIds': ['current'], 'datasetSha256s': ['c' * 64],
        }]}
    elif kind == 'budget':
        document = {'analysisId': 'analysis_001', 'metrics': [{
            'factId': 'fact-' + key * 16, 'datasetId': 'current', 'datasetSha256': 'c' * 64,
            'periodRoles': ['current'], 'field': field, 'fieldRef': 'source.' + field,
            'aggregation': 'sum', 'unit': '元', 'formula': 'SUM(' + field + ')',
            'total': value, 'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
            'periodGranularity': 'month', 'periodStart': '2025-01', 'periodEnd': '2025-01',
            'periodValues': [{'period': '2025-01', 'value': value}],
        } for key, field, value in [('a', 'actual_amount', 160), ('b', 'budget_amount', 100)]]}
    return [json.dumps(document),
            json.dumps({'findings': [{
                'columns': ['项目', '金额'], 'columnMeta': {'金额': {'unit': '元'}},
                'rows': [['甲项目', 100], ['乙项目', 80]],
            }]})]


@pytest.mark.parametrize('word', ['相差', '差额为', '差距约'])
@pytest.mark.parametrize('kind', ['derived', 'reconciliation', 'budget'])
@pytest.mark.parametrize('amount', [60, -60])
def test_unrelated_registered_difference_cannot_support_handwritten_claim(word, kind, amount):
    contents = difference_contents(kind)
    text = f'甲项目与乙项目{word}{amount}元。'
    assert replace_unregistered_numbers(text, contents) == f'甲项目与乙项目{word}待核实。'
    assert any('冻结依据' in warning for warning in review_content(text, contents))


@pytest.mark.parametrize('kind', ['derived', 'reconciliation', 'budget'])
def test_difference_reference_authorizes_only_its_own_rendered_number(kind):
    contents = difference_contents(kind)
    selector = ('budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-01.difference'
                if kind == 'budget' else 'difference')
    token = '{{value:fact-aaaaaaaaaaaaaaaa:' + selector + ':元}}'
    correct = '较预算差额为' + token
    assert not any('冻结依据' in warning for warning in review_content(correct, contents))
    rendered, references, notices = render_bound_numbers(correct, contents, key='difference')
    assert rendered == '较预算差额为60元'
    assert len(references) == 1 and references[0].token == token
    assert not notices
    # 同句的合法引用不能替手写数提供身份；不相关的手写数无论在前在后都须告警。
    wrong = '甲项目与乙项目相差60元'
    for text in (correct + '，' + wrong, wrong + '，' + correct):
        assert any('冻结依据' in warning for warning in review_content(text, contents))
        rendered, _, notices = render_bound_numbers(text, contents, key='mixed-difference')
        assert '相差待核实' in rendered and len(notices) == 1


def test_plain_amount_reference_or_forged_anchor_cannot_authorize_difference():
    contents = difference_contents()
    ordinary = '差额为{{value:fact-aaaaaaaaaaaaaaaa:numerator:元}}'
    assert any('冻结依据' in warning for warning in review_content(ordinary, contents))
    rendered, _, notices = render_bound_numbers(ordinary, contents, key='ordinary')
    assert rendered == '差额为待核实' and notices
    forged = '甲项目与乙项目相差60元[[claim:number-review-0]]'
    assert '相差待核实' in replace_unregistered_numbers(forged, contents)
    assert any('冻结依据' in warning for warning in review_content(forged, contents))
    assert render_bound_numbers(forged, contents, key='forged')[0] == '甲项目与乙项目相差待核实'


@pytest.mark.parametrize('fact,target,expected', [('a', '万元', '60元'), ('b', '元', '-60元')])
def test_difference_reference_retains_display_unit_fallback_and_sign(fact, target, expected):
    token = '{{value:fact-' + fact * 16 + ':difference:' + target + '}}'
    text = '差额为' + token
    contents = difference_contents()
    assert not any('冻结依据' in warning for warning in review_content(text, contents))
    rendered, references, notices = render_bound_numbers(text, contents, key='display-unit')
    assert rendered == '差额为' + expected
    assert len(references) == 1 and not notices


@pytest.mark.parametrize('subjects', ['甲项目与乙项目', '乙项目与甲项目'])
def test_correct_operands_still_support_neutral_magnitude(subjects):
    text = subjects + '相差20元。'
    contents = difference_contents()
    assert replace_unregistered_numbers(text, contents) == text
    assert not any('冻结依据' in warning for warning in review_content(text, contents))


@pytest.mark.parametrize('written,amount,expected', [
    ('59.999', 100, '60.00'),
    ('60.001', 100, '60.00'),
    ('1,059.999', 1100, '1,060.00'),
    ('59.99', 100, '60.00'),
    ('0.003', 40.004, '0.004'),  # 复用既有非零微小值规则，不能归零。
])
def test_adjacent_digit_correction_uses_display_precision(written, amount, expected):
    contents = [json.dumps({'findings': [{
        'columns': ['项目', '金额'], 'columnMeta': {'金额': {'unit': '元'}},
        'rows': [['甲项目', amount], ['乙项目', 40]],
    }]})]
    text = f'甲项目与乙项目相差{written}元。'
    assert replace_unregistered_numbers(text, contents) == f'甲项目与乙项目相差{expected}元。'
