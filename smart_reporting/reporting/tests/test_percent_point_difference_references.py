"""中性百分点差额与金额差额共用引用身份和操作数校验。"""

import json

import pytest

from smart_reporting.reporting.tests.test_neutral_difference_references import difference_contents
from smart_reporting.reporting.trace.content_review import review_content
from smart_reporting.reporting.trace.numeric_text import (
    frozen_number_catalog,
    replace_unregistered_numbers,
)
from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers


def point_contents(kind):
    document = json.loads(difference_contents(kind)[0])
    for fact in document.get('derivedMetrics', ()):
        value = 42.1 if fact['numeratorMetric'].endswith('a') else 37.9
        fact.update(unit='%', numerator=value, denominator=40, value=value / 40,
                    percentage=value / 40 * 100, difference=2.1 if value > 40 else -2.1)
    for fact in document.get('reconciliations', ()):
        fact.update(unit='%', leftTotal=42.1, rightTotal=40, difference=2.1)
    for fact in document.get('metrics', ()):
        value = 42.1 if fact['field'].startswith('actual') else 40
        fact.update(unit='%', total=value, periodValues=[{'period': '2025-01', 'value': value}])
    return [json.dumps(document), json.dumps({'findings': [{
        'columns': ['项目', '占比'], 'columnMeta': {'占比': {'unit': '%', 'isPercent': True}},
        'rows': [['甲项目', 80], ['乙项目', 60], ['丙项目', 42.1], ['丁项目', 40]],
    }]})]


@pytest.mark.parametrize('kind', ['derived', 'reconciliation', 'budget'])
@pytest.mark.parametrize('word', ['相差', '差额为', '差距约'])
@pytest.mark.parametrize('written', ['2.10个百分点', '-2.10个百分点', '2.10百分点'])
def test_unrelated_point_difference_is_replaced_and_warned(kind, word, written):
    contents = point_contents(kind)
    assert '2.10个百分点' in frozen_number_catalog(contents).values()
    text = f'甲项目与乙项目{word}{written}。'
    assert replace_unregistered_numbers(text, contents) == f'甲项目与乙项目{word}待核实。'
    assert any('冻结依据' in warning for warning in review_content(text, contents))
    rendered, references, notices = render_bound_numbers(text, contents, key='point-difference')
    assert rendered == f'甲项目与乙项目{word}待核实。' and not references
    assert len(notices) == 1 and notices[0].original_text == written


@pytest.mark.parametrize('kind', ['derived', 'reconciliation', 'budget'])
def test_point_difference_reference_authorizes_only_its_own_number(kind):
    contents = point_contents(kind)
    selector = ('budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-01.difference'
                if kind == 'budget' else 'difference')
    token = '{{value:fact-aaaaaaaaaaaaaaaa:' + selector + ':%}}'
    correct = '较预算差额为' + token
    assert not any('冻结依据' in warning for warning in review_content(correct, contents))
    rendered, references, notices = render_bound_numbers(correct, contents, key='point-reference')
    assert rendered == '较预算差额为2.10个百分点' and not notices
    assert len(references) == 1 and references[0].token == token
    wrong = '甲项目与乙项目相差2.10个百分点'
    for text in (correct + '，' + wrong, wrong + '，' + correct):
        assert any('冻结依据' in warning for warning in review_content(text, contents))
        rendered, references, notices = render_bound_numbers(text, contents, key='mixed-point')
        assert '相差待核实' in rendered and len(notices) == 1 and len(references) == 1


@pytest.mark.parametrize('subjects', ['甲项目与乙项目', '乙项目与甲项目'])
@pytest.mark.parametrize('written,expected', [('20.00', '20.00'), ('19.999', '20.00')])
def test_named_percent_operands_support_point_difference(subjects, written, expected):
    contents = point_contents('derived')
    text = f'{subjects}相差{written}个百分点。'
    assert replace_unregistered_numbers(text, contents) == f'{subjects}相差{expected}个百分点。'
    if written == expected:
        assert not any('冻结依据' in warning for warning in review_content(text, contents))


def test_point_difference_cannot_borrow_previous_sentence_or_forged_anchor():
    contents = point_contents('derived')
    for text in ('丙项目与丁项目已核对。两者相差2.10个百分点。',
                 '甲项目与乙项目相差2.10个百分点[[claim:number-review-0]]。'):
        assert '相差待核实' in replace_unregistered_numbers(text, contents)
        assert any('冻结依据' in warning for warning in review_content(text, contents))
        assert '相差待核实' in render_bound_numbers(text, contents, key='forged-point')[0]


def test_negative_point_difference_reference_preserves_sign():
    contents = point_contents('derived')
    token = '{{value:fact-bbbbbbbbbbbbbbbb:difference:%}}'
    text = '差额为' + token
    assert not any('冻结依据' in warning for warning in review_content(text, contents))
    rendered, references, notices = render_bound_numbers(text, contents, key='negative-point')
    assert rendered == '差额为-2.10个百分点' and len(references) == 1 and not notices


@pytest.mark.parametrize('row_count', [4, 410])
def test_unrelated_percent_pair_cannot_authorize_neutral_difference(row_count):
    # 没有直接登记的百分点：任意两项百分数相减、候选数超限都不能豁免中性差额。
    table = json.loads(point_contents('derived')[1])
    table['findings'][0]['rows'].extend([[f'其他项目{index}', index] for index in range(row_count - 4)])
    contents = [json.dumps(table)]
    text = '甲项目与乙项目相差2.10个百分点。'
    assert replace_unregistered_numbers(text, contents) == '甲项目与乙项目相差待核实。'
    assert any('冻结依据' in warning for warning in review_content(text, contents))


def test_percent_column_difference_requires_row_and_both_columns():
    contents = [json.dumps({'findings': [{
        'columns': ['项目', '实际占比', '预算占比'],
        'columnMeta': {column: {'unit': '%', 'isPercent': True} for column in ('实际占比', '预算占比')},
        'rows': [['甲项目', 42.1, 40], ['乙项目', 80, 60]],
    }]})]
    correct = '甲项目实际占比与预算占比相差2.10个百分点。'
    assert replace_unregistered_numbers(correct, contents) == correct
    assert not any('冻结依据' in warning for warning in review_content(correct, contents))
    for wrong in ('乙项目实际占比与预算占比相差2.10个百分点。',
                  '实际占比与预算占比相差22.10个百分点。'):
        assert '相差待核实' in replace_unregistered_numbers(wrong, contents)
        assert any('冻结依据' in warning for warning in review_content(wrong, contents))


def test_grouped_point_literal_is_checked_consistently():
    contents = point_contents('derived')
    text = '甲项目与乙项目差额为1,002.10个百分点。'
    assert replace_unregistered_numbers(text, contents) == '甲项目与乙项目差额为待核实。'
    assert any('冻结依据' in warning for warning in review_content(text, contents))
