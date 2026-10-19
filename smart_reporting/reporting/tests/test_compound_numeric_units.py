"""复合单位必须整体核对，不能把单价误认成金额。"""

import json

import pytest

from smart_reporting.reporting.tests.test_semantic_bindings import contents
from smart_reporting.reporting.trace.content_review import review_content
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import claim_status


def compound_contents(unit):
    bundle = json.loads(contents()[0])
    bundle['metrics'] = bundle['metrics'][:1]
    bundle['metrics'][0]['unit'] = unit
    return [json.dumps(bundle)]


@pytest.mark.parametrize('unit', ['元/人次', '元/床日', '元/人', '万元/人次'])
def test_registered_compound_number_survives_render_and_review(unit):
    sources = compound_contents(unit)
    token = '{{value:fact-aaaaaaaaaaaaaaaa:total:' + unit + '}}'
    resolved = resolve_number_reference(token, sources)
    assert resolved is not None and resolved['value'] == 30
    markdown, refs, notices = render_bound_numbers('次均费用为' + token + '。', sources, key='compound')
    assert markdown == '次均费用为30' + unit + '。'
    assert len(refs) == 1 and not notices
    anchored = anchor_bound_numbers(markdown, refs, notices)
    assert claim_status(anchored, refs[0].claim_id, 30, expected_unit=unit) == {
        'status': 'valid', 'warnings': [],
    }
    assert not any('数值缺少' in warning for warning in review_content(anchored, sources))


@pytest.mark.parametrize('unit', ['元/人次', '元/床日'])
def test_unregistered_compound_number_keeps_complete_original(unit):
    markdown, refs, notices = render_bound_numbers(
        '次均费用为999' + unit + '。', compound_contents(unit), key='unknown-compound',
    )
    assert markdown == '次均费用为待核实。'
    assert not refs and len(notices) == 1
    assert notices[0].original_text == '999' + unit
    assert any('999' + unit in warning for warning in review_content(
        '次均费用为999' + unit + '。', compound_contents(unit),
    ))


def test_amount_cannot_borrow_same_number_from_a_compound_unit():
    markdown, refs, notices = render_bound_numbers(
        '收入30元。', compound_contents('元/人次'), key='different-dimension',
    )
    assert markdown == '收入待核实。'
    assert not refs and notices[0].original_text == '30元'


def test_table_header_uses_complete_compound_unit():
    sources = compound_contents('元/人次')
    text = '| 指标 | 次均费用（元/人次） |\n| --- | ---: |\n| 门诊 | 30 |\n| 住院 | 999 |'
    markdown, refs, notices = render_bound_numbers(text, sources, key='compound-table')
    assert '| 门诊 | 30 |' in markdown and '| 住院 | 待核实 |' in markdown
    assert not refs and len(notices) == 1
    assert notices[0].original_text == '999元/人次'
