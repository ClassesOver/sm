"""明确的月度口径在签发引用前收敛，不能把正确月均改成合计。"""

import json

import pytest

from smart_reporting.reporting.tests.test_semantic_bindings import contents
from smart_reporting.reporting.trace.content_review import review_content
from smart_reporting.reporting.trace.number_selection import align_number_selections
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import claim_status

FACT = 'fact-' + 'a' * 16


def _sources(values=(10, 20), **updates):
    bundle = json.loads(contents()[0])
    metric = bundle['metrics'][0]
    metric.update(displayName='设备支出', periodMissingCount=0, total=sum(values),
                  periodValues=[{'period': f'2025-{index + 1:02d}', 'value': value}
                                for index, value in enumerate(values)], periodEnd=f'2025-{len(values):02d}')
    metric.update(updates)
    return [json.dumps(bundle)]


@pytest.mark.parametrize('wording', ['月均设备支出为', '设备支出月均为', '平均每月设备支出为'])
@pytest.mark.parametrize('selector', ['total', 'monthlyAverage', 'periodTotals.0-1'])
def test_explicit_monthly_average_converges_before_reference_signing(wording, selector):
    raw = '2025年1—2月' + wording + '{{value:' + FACT + ':' + selector + ':元}}。'
    frozen = _sources()
    aligned, _ = align_number_selections(raw, frozen)
    expected = '{{value:' + FACT + ':monthlyAverage:元}}'
    assert expected in aligned
    assert align_number_selections(aligned, frozen) == (aligned, [])
    assert review_content(aligned, frozen) == []
    markdown, refs, notices = render_bound_numbers(aligned, frozen, key='monthly-convergence')
    assert len(refs) == 1 and not notices and refs[0].token == expected
    assert '15元' in markdown and '30元' not in markdown
    selected = resolve_number_reference(refs[0].token, frozen)
    checked = claim_status(anchor_bound_numbers(markdown, refs), refs[0].claim_id, selected['value'],
                           expected_unit=selected['unit'], expected_periods=selected['periods'],
                           expected_period_roles=selected['period_roles'], expected_scope=selected['scope'],
                           expected_reference=selected)
    assert checked == {'status': 'valid', 'warnings': []}


def test_explicit_prefix_window_selects_the_registered_period_average():
    frozen = _sources((10, 20, 90))
    raw = '2025年1—2月设备支出月均为{{value:' + FACT + ':total:元}}。'
    aligned, _ = align_number_selections(raw, frozen)
    assert '{{value:' + FACT + ':periodAverages.0-1:元}}' in aligned
    assert align_number_selections(aligned, frozen) == (aligned, [])
    assert review_content(aligned, frozen) == []


@pytest.mark.parametrize('wording', ['各月设备支出均为', '设备支出每月为', '逐月设备支出为'])
def test_constant_monthly_amount_is_selected_before_it_is_rendered(wording):
    frozen = _sources((10, 10))
    raw = wording + '{{value:' + FACT + ':total:元}}。'
    aligned, _ = align_number_selections(raw, frozen)
    assert '{{value:' + FACT + ':monthlyAverage:元}}' in aligned
    assert align_number_selections(aligned, frozen) == (aligned, [])
    markdown, refs, notices = render_bound_numbers(aligned, frozen, key='constant-months')
    assert refs and not notices and '10元' in markdown
    selected = resolve_number_reference(refs[0].token, frozen)
    assert selected['value'] == 10


@pytest.mark.parametrize('updates', [
    {'aggregation': 'average'}, {'periodAggregation': 'last'}, {'unit': '元/人次'},
    {'periodMissingCount': 1},
    {'periodValues': [{'period': '2025-01', 'value': 10}, {'period': '2025-03', 'value': 20}]},
])
def test_uncertain_monthly_windows_and_nonadditive_measures_are_not_reselected(updates):
    frozen = _sources(**updates)
    raw = '2025年1—2月月均设备支出为{{value:' + FACT + ':total:元}}。'
    assert align_number_selections(raw, frozen)[0] == raw


@pytest.mark.parametrize('prefix', ['不是月均', '月均与累计', '月均同比增长'])
def test_negation_conflicting_wording_and_derived_operations_are_not_guessed(prefix):
    raw = '2025年1—2月' + prefix + '设备支出为{{value:' + FACT + ':total:元}}。'
    assert align_number_selections(raw, _sources())[0] == raw


@pytest.mark.parametrize('prefix', ['各月设备支出均为', '每月均为', '各月均为'])
def test_nonconstant_months_cannot_be_described_as_the_same_monthly_amount(prefix):
    raw = prefix + '{{value:' + FACT + ':total:元}}。'
    frozen = _sources()
    assert align_number_selections(raw, frozen)[0] == raw
    assert any('逐月数值' in warning for warning in review_content(raw, frozen))
    selected = resolve_number_reference('{{value:' + FACT + ':total:元}}', frozen)
    checked = claim_status(prefix + '30元[[claim:each-month]]。', 'each-month', 30,
                           expected_unit='元', expected_reference=selected)
    assert checked['status'] == 'valid' and any('逐月数值' in warning for warning in checked['warnings'])


def test_unregistered_subwindow_average_is_not_invented():
    raw = '2025年2—3月月均设备支出为{{value:' + FACT + ':total:元}}。'
    assert align_number_selections(raw, _sources((10, 20, 90)))[0] == raw


@pytest.mark.parametrize('selector', ['total', 'monthlyAverage'])
def test_monthly_wording_without_a_window_preserves_the_existing_selection(selector):
    raw = '月均设备支出为{{value:' + FACT + ':' + selector + ':元}}。'
    assert align_number_selections(raw, _sources()) == (raw, [])


def test_resolved_monthly_average_preserves_scope_and_target_unit():
    frozen = _sources((10_000, 20_000), scope={'院区': '总部'})
    raw = '2025年1—2月总部月均设备支出为{{value:' + FACT + ':total:万元}}。'
    aligned, _ = align_number_selections(raw, frozen)
    selected = resolve_number_reference('{{value:' + FACT + ':monthlyAverage:万元}}', frozen)
    assert ':monthlyAverage:万元}}' in aligned and selected['scope'] == {'院区': '总部'}
    assert align_number_selections(aligned, frozen) == (aligned, [])
    markdown, refs, notices = render_bound_numbers(aligned, frozen, key='scaled-monthly')
    assert len(refs) == 1 and not notices and '1.50万元' in markdown


def test_remaining_period_total_mislabel_is_reported_in_the_editor():
    selected = resolve_number_reference('{{value:' + FACT + ':periodTotals.0-1:元}}', _sources())
    checked = claim_status('2025年1—2月月均设备支出30元[[claim:legacy-mean]]。', 'legacy-mean', 30,
                           expected_unit='元', expected_reference=selected)
    assert checked['status'] == 'valid' and any('统计口径' in warning for warning in checked['warnings'])


def test_each_month_cumulative_total_does_not_assert_identical_monthly_values():
    raw = '各月设备支出合计为{{value:' + FACT + ':total:元}}。'
    assert not any('逐月数值' in warning for warning in review_content(raw, _sources()))


@pytest.mark.parametrize('prefix', ['设备支出并非每月均为', '各月设备支出并非均为'])
def test_negated_uniform_monthly_assertion_is_not_a_same_value_claim(prefix):
    raw = prefix + '{{value:' + FACT + ':total:元}}。'
    assert not any('逐月数值' in warning for warning in review_content(raw, _sources()))
