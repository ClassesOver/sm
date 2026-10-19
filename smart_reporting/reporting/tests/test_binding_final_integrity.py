"""最终显示文本与冻结引用一致；后置规范化失配只留下真实待核实事件。"""

import json

import pytest

from smart_reporting.reporting.tests.test_semantic_bindings import contents
from smart_reporting.reporting.trace import semantic_bindings
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import claim_status


def _source(value, unit='元'):
    bundle = json.loads(contents()[0])
    bundle['metrics'] = bundle['metrics'][:1]
    bundle['metrics'][0].update(total=value, unit=unit)
    return [json.dumps(bundle)]


def _assert_current_binding(markdown, references, notices, source, expected_display):
    assert not notices and len(references) == 1
    reference = references[0]
    assert reference.display_text == expected_display
    assert reference.model_dump(by_alias=True)['displayText'] == expected_display
    assert expected_display in markdown
    selected = resolve_number_reference(reference.token, source)
    assert selected is not None
    assert claim_status(
        anchor_bound_numbers(markdown, references), reference.claim_id, selected['value'],
        expected_unit=selected['unit'], expected_periods=selected['periods'],
        expected_period_roles=selected['period_roles'], expected_scope=selected['scope'],
        expected_reference=selected,
    ) == {'status': 'valid', 'warnings': []}


@pytest.mark.parametrize(('value', 'unit', 'display'), [
    (1.005, '元', '1.01元'),
    (1.005, '元/人次', '1.01元/人次'),
    (-0.004, '元', '0.00元'),
    (12, '台', '12台'),
])
def test_final_reference_preserves_real_display_precision_and_unit(value, unit, display):
    source = _source(value, unit)
    statement = '登记值{{value:fact-aaaaaaaaaaaaaaaa:total:' + unit + '}}。'
    rendered = render_bound_numbers(statement, source, key='precision')
    _assert_current_binding(*rendered, source, display)


@pytest.mark.parametrize('wrong_value', ['999', '20'])
def test_post_normalization_value_fault_revokes_the_old_reference_and_retains_the_original(monkeypatch, wrong_value):
    # 20也登记在另一个事实的期间值中，不能借该全局同值为当前total=30背书。
    source = contents()
    monkeypatch.setattr(semantic_bindings, 'correct_constant_monthly_totals',
                        lambda markdown, _contents: markdown.replace('30元', wrong_value + '元'))
    markdown, references, notices = render_bound_numbers(
        '收入{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。', source, key='normalization-fault',
    )
    assert markdown == '收入待核实。'
    assert references == ()
    assert len(notices) == 1
    assert notices[0].kind == 'numeric_unverified'
    assert notices[0].original_text == wrong_value + '元'
    assert wrong_value + '元' not in anchor_bound_numbers(markdown, references, notices)


@pytest.mark.parametrize(('value', 'target', 'prefix', 'display'), [
    (1168326928, '亿元', '收入', '11.68亿元'),
    (6543200, '亿元', '收入', '654.32万元'),
    (-10, '元', '收入下降', '10元'),
    (-1168326928, '亿元', '收入下降', '11.68亿元'),
])
def test_normal_unit_conversion_and_negative_decline_are_not_revoked(value, target, prefix, display):
    source = _source(value)
    statement = prefix + '{{value:fact-aaaaaaaaaaaaaaaa:total:' + target + '}}。'
    rendered = render_bound_numbers(statement, source, key='normal-display')
    _assert_current_binding(*rendered, source, display)
