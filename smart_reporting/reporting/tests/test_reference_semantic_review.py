"""按精确选择器与当前引用的表述复核口径，不用同值或背景日期替引用背书。"""

import hashlib
import json

import pytest

from smart_reporting.reporting.tests.test_semantic_bindings import contents
from smart_reporting.reporting.tests.test_trace_subject_validate import _make_editor_with_subject
from smart_reporting.reporting.trace.content_review import review_content, review_content_result
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import claim_status, unit_period_warnings


@pytest.mark.parametrize('wording', ['2025年1—9月', '2025年1月至9月', '2025年1月到2025年9月'])
def test_cumulative_range_start_is_not_its_endpoint(wording):
    assert unit_period_warnings(
        wording + '累计531.65万人次',
        expected_periods=tuple(f'2025-{month:02d}' for month in range(1, 10)),
        expected_period_roles={'endpoint': ('2025-09',)},
    ) == []


@pytest.mark.parametrize(('wording', 'warns'), [
    ('2025年1—9月收入中，9月收入11.68亿元为最高', False),
    ('2025年1—9月收入中，8月收入11.68亿元为最高', True),
    ('2025年1—9月累计收入11.68亿元', True),
    ('2025年1—9月收入中，含8月的收入11.68亿元', True),
])
def test_current_value_period_is_distinct_from_background(wording, warns):
    warnings = unit_period_warnings(wording, expected_unit='元', fact_value=1168326928,
                                    expected_periods=('2025-09',))
    assert bool(warnings) is warns


@pytest.mark.parametrize(('selector', 'wording', 'warning'), [
    ('monthlyAverage', '累计支出', '统计口径'),
    ('periodAverages.0-1', '截至2025年2月支出总额', '统计口径'),
    ('monthlyAverage', '月均支出', None),
    ('monthlyAverage', '累计支出30元（月均', None),
    ('total', '月均支出', '统计口径'),
    ('total', '全院收入', None),
    ('total', '普通外科收入', '业务范围'),
    ('total', '普通外科占全院收入', None),
])
def test_exact_reference_semantics_are_checked_in_generation_and_editor(selector, wording, warning):
    token = '{{value:fact-aaaaaaaaaaaaaaaa:' + selector + ':元}}'
    frozen = contents()
    selected = resolve_number_reference(token, frozen)
    markdown, refs, notices = render_bound_numbers(wording + token + '。', frozen, key='semantics')
    assert len(refs) == 1 and not notices
    result = claim_status(
        anchor_bound_numbers(markdown, refs), refs[0].claim_id, selected['value'],
        expected_unit=selected['unit'], expected_periods=selected['periods'],
        expected_scope=selected['scope'], expected_reference=selected,
    )
    assert result['status'] == 'valid'
    if warning:
        assert any(warning in item for item in result['warnings'])
        assert any(warning in item for item in review_content(wording + token + '。', frozen))
    else:
        assert result['warnings'] == []


def test_registered_department_reference_is_not_mistaken_for_unscoped_total():
    bundle = json.loads(contents()[0])
    bundle['metrics'][0]['topGroups'] = [{'group': '普通外科', 'value': 20}]
    frozen = [json.dumps(bundle)]
    token = '{{value:fact-aaaaaaaaaaaaaaaa:topGroups.0:元}}'
    selected = resolve_number_reference(token, frozen)
    assert selected['scope'] == {'group': '普通外科'}
    result = claim_status('普通外科收入20元[[claim:department]]。', 'department', 20,
                          expected_unit='元', expected_scope=selected['scope'], expected_reference=selected)
    assert result == {'status': 'valid', 'warnings': []}


@pytest.mark.anyio
@pytest.mark.parametrize(('selector', 'wording', 'warns'), [
    ('monthlyAverage', '累计收入', True),
    ('monthlyAverage', '月均收入', False),
    ('total', '普通外科收入', True),
    ('total', '全院收入', False),
])
async def test_editor_exposes_semantic_warning_without_rejecting_numeric_binding(tmp_path, selector, wording, warns):
    editor, grants, context = await _make_editor_with_subject(
        tmp_path, period_table=True, number_reference=True,
        number_statement=wording + '{{value:fact-aaaaaaaaaaaaaaaa:' + selector + ':万元}}。',
    )
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    markdown = next(tmp_path.rglob('report.md')).read_text()
    result = await editor.trace_validate(context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    subject = result['subjects'][0]
    assert subject['status'] == 'valid'
    assert bool(subject['warnings']) is warns


def _review_exact_statement(wording, selector, scope=None, suffix=''):
    bundle = json.loads(contents()[0])
    bundle['metrics'][0]['scope'] = scope or {}
    frozen = [json.dumps(bundle)]
    raw = wording + '{{value:fact-aaaaaaaaaaaaaaaa:' + selector + ':元}}' + suffix + '。'
    markdown, refs, notices = render_bound_numbers(raw, frozen, key='local-semantics')
    assert len(refs) == 1 and not notices
    selected = resolve_number_reference(refs[0].token, frozen)
    result = claim_status(
        anchor_bound_numbers(markdown, refs), refs[0].claim_id, selected['value'],
        expected_unit=selected['unit'], expected_periods=selected['periods'],
        expected_period_roles=selected['period_roles'], expected_scope=selected['scope'], expected_reference=selected,
    )
    assert result['status'] == 'valid'
    return result['warnings'], review_content(raw, frozen)


@pytest.mark.parametrize('selector', ['total', 'periodTotals.0-1', 'monthlyAverage', 'periodAverages.0-1'])
@pytest.mark.parametrize('wording', ['2025年1—2月收入中，2月收入', '2025年2月收入'])
def test_multimonth_value_cannot_be_presented_as_a_single_month(selector, wording):
    for warnings in _review_exact_statement(wording, selector):
        assert any('统计期间' in warning for warning in warnings)


@pytest.mark.parametrize('wording', [
    '2025年1—2月累计收入', '1—2月收入', '截至2025年2月累计收入',
    '截至2025年2月，收入', '2月累计收入',
])
def test_explicit_window_and_cumulative_endpoint_remain_valid(wording):
    assert _review_exact_statement(wording, 'periodTotals.0-1') == ([], [])


def test_previous_cutoff_does_not_authorize_a_new_single_month_claim():
    for warnings in _review_exact_statement('截至2025年2月，2月收入', 'periodTotals.0-1'):
        assert any('统计期间' in warning for warning in warnings)


@pytest.mark.parametrize('qualifier', ['不是', '并非', '而非', '不同于', '不能称为'])
def test_negated_aggregation_word_does_not_change_the_declared_monthly_average(qualifier):
    assert _review_exact_statement(f'按月均口径（{qualifier}累计）支出', 'monthlyAverage') == ([], [])


def test_negation_does_not_hide_an_affirmative_aggregation_mismatch():
    for warnings in _review_exact_statement('不是月均，而是累计收入', 'monthlyAverage'):
        assert any('统计口径' in warning for warning in warnings)


@pytest.mark.parametrize('wording', [
    '普通外科为比较对象，血液内科收入',
    '普通外科为比较对象，血液内科的收入',
    '普通外科为比较对象，血液内科 收入',
])
def test_current_department_cannot_borrow_scope_from_another_clause(wording):
    for warnings in _review_exact_statement(wording, 'total', {'科室': '普通外科'}):
        assert any('业务范围' in warning for warning in warnings)


def test_different_comparison_department_does_not_invalidate_the_current_correct_scope():
    assert _review_exact_statement('血液内科为比较对象，普通外科收入', 'total', {'科室': '普通外科'}) == ([], [])


@pytest.mark.parametrize('scope', [{'科室': '内科'}, {'group': '院区 / 内科'}])
def test_department_names_must_match_completely(scope):
    for warnings in _review_exact_statement('血液内科收入', 'total', scope):
        assert any('业务范围' in warning for warning in warnings)


@pytest.mark.parametrize('prefix', ['本期', '目前', '2025年2月'])
def test_current_department_context_does_not_become_part_of_its_name(prefix):
    # 没写月份时使用全期总额，不能让科室对照用例绕过单月引用必须声明期间的约束。
    selector = 'periodValues.1' if prefix == '2025年2月' else 'total'
    assert _review_exact_statement(prefix + '普通外科收入', selector, {'科室': '普通外科'}) == ([], [])


def test_correction_reference_metadata_is_bounded_and_preserves_the_source_contract():
    token = '{{value:fact-aaaaaaaaaaaaaaaa:monthlyAverage:元}}'
    result = review_content_result(('累计收入' + token + '。') * 25, contents())
    assert result.accuracy_count > 0
    assert len(result.reference_issues) == 20
    assert all(issue['token'] == token and issue['selector'] == 'monthlyAverage'
               and issue['periods'] == ['2025-01', '2025-02'] and issue['scope'] == {}
               and len(issue['statement']) <= 240 for issue in result.reference_issues)
    assert review_content_result('按月均口径（不是累计）收入' + token, contents()).reference_issues == ()


@pytest.mark.anyio
@pytest.mark.parametrize(('selector', 'wording', 'scope', 'warning'), [
    ('periodTotals.0-1', '2025年9—10月收入中，10月收入', {}, '统计期间'),
    ('total', '普通外科为比较对象，血液内科收入', {'科室': '普通外科'}, '业务范围'),
    ('monthlyAverage', '按月均口径（不是累计）收入', {}, None),
])
async def test_editor_checks_the_current_claim_window_scope_and_negation(tmp_path, selector, wording, scope, warning):
    editor, grants, context = await _make_editor_with_subject(
        tmp_path, period_table=True, number_reference=True, metric_scope=scope,
        number_statement=wording + '{{value:fact-aaaaaaaaaaaaaaaa:' + selector + ':万元}}。',
    )
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    markdown = next(tmp_path.rglob('report.md')).read_text()
    result = await editor.trace_validate(context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    subject = result['subjects'][0]
    assert subject['status'] == 'valid'
    if warning:
        assert any(warning in item for item in subject['warnings'])
    else:
        assert subject['warnings'] == [] and result['warnings'] == []


@pytest.mark.parametrize('prefix', ['报告显示', '数据表明', '从统计结果可见', '本期登记'])
def test_narrative_context_is_not_part_of_the_registered_department(prefix):
    assert _review_exact_statement(prefix + '普通外科收入', 'total', {'科室': '普通外科'}) == ([], [])


def test_registered_department_name_itself_can_contain_narrative_characters():
    assert _review_exact_statement('卫生统计科收入', 'total', {'科室': '卫生统计科'}) == ([], [])


@pytest.mark.parametrize('suffix', ['位居全院第一为', '在全院收入中排名第一为', '占总体规模较大为'])
def test_global_ranking_does_not_authorize_an_unscoped_department(suffix):
    for warnings in _review_exact_statement('普通外科收入' + suffix, 'total'):
        assert any('业务范围' in item for item in warnings)


@pytest.mark.parametrize('wording', ['普通外科占全院收入', '普通外科收入占全院收入'])
def test_global_denominator_is_not_a_department_numerator(wording):
    assert _review_exact_statement(wording, 'total') == ([], [])


@pytest.mark.parametrize('wording', [
    '2025年2月收入（含1月调整额）',
    '2025年1—2月收入中，2月收入含1月调整额为',
    '2025年2月收入（包括2025年1月调整额）',
])
def test_component_month_does_not_hide_the_current_incompatible_window(wording):
    for warnings in _review_exact_statement(wording, 'periodTotals.0-1'):
        assert any('统计期间' in item for item in warnings)


@pytest.mark.parametrize('wording', [
    '2025年1—2月累计收入（含1月调整额）',
    '截至2025年2月累计收入（含1月调整额）',
])
def test_component_month_does_not_replace_the_valid_cumulative_window(wording):
    assert _review_exact_statement(wording, 'periodTotals.0-1') == ([], [])


@pytest.mark.parametrize(('prefix', 'selector', 'suffix', 'warning'), [
    ('收入', 'monthlyAverage', '（累计值）', '统计口径'),
    ('', 'total', '为普通外科收入', '业务范围'),
    ('收入', 'total', '（普通外科）', '业务范围'),
    ('收入', 'periodTotals.0-1', '（2025年2月）', '统计期间'),
])
def test_direct_postfix_is_checked_in_generation_and_editor(prefix, selector, suffix, warning):
    for warnings in _review_exact_statement(prefix, selector, suffix=suffix):
        assert any(warning in item for item in warnings)
    raw = prefix + '{{value:fact-aaaaaaaaaaaaaaaa:' + selector + ':元}}' + suffix + '。'
    issues = review_content_result(raw, contents()).reference_issues
    assert issues and suffix in issues[0]['statement']


@pytest.mark.parametrize('suffix', ['为普通外科收入', '（普通外科）'])
def test_registered_postfix_department_does_not_create_a_scope_mismatch(suffix):
    assert _review_exact_statement('收入', 'total', {'科室': '普通外科'}, suffix) == ([], [])


@pytest.mark.parametrize('suffix', [
    '（月均值）', '（不是累计值）',
    '，累计支出{{value:fact-aaaaaaaaaaaaaaaa:total:元}}',
    '（累计支出{{value:fact-aaaaaaaaaaaaaaaa:total:元}}）',
])
def test_postfix_never_borrows_the_next_reference_qualifiers(suffix):
    from smart_reporting.reporting.trace.reference_semantics import number_reference_warnings

    selected = resolve_number_reference('{{value:fact-aaaaaaaaaaaaaaaa:monthlyAverage:元}}', contents())
    assert number_reference_warnings('收入', selected, suffix) == []


@pytest.mark.parametrize('suffix', [
    '（累计值，含调整额）',
    '（统计口径（累计值））',
    '(统计口径(累计值)，含调整额)',
])
def test_complete_nested_postfix_and_its_internal_commas_are_not_dropped(suffix):
    for warnings in _review_exact_statement('收入', 'monthlyAverage', suffix=suffix):
        assert any('统计口径' in item for item in warnings)


@pytest.mark.parametrize('suffix', [
    '（月均值，不是累计）', '（统计口径（月均值））',
    '（月均值）及累计支出{{value:fact-aaaaaaaaaaaaaaaa:total:元}}',
])
def test_nested_postfix_keeps_negation_and_the_next_reference_boundary(suffix):
    from smart_reporting.reporting.trace.reference_semantics import number_reference_warnings

    selected = resolve_number_reference('{{value:fact-aaaaaaaaaaaaaaaa:monthlyAverage:元}}', contents())
    assert number_reference_warnings('收入', selected, suffix) == []


@pytest.mark.parametrize(('prefix', 'selector', 'suffix'), [
    ('累计收入', 'monthlyAverage', '（月均值）'),
    ('月均收入', 'total', '（累计值）'),
])
def test_postfix_does_not_erase_a_conflicting_current_value_assertion(prefix, selector, suffix):
    for warnings in _review_exact_statement(prefix, selector, suffix=suffix):
        assert any('统计口径' in item for item in warnings)


@pytest.mark.parametrize('citations', [
    '[[citation:sub-0000000000000000]]',
    ' [[citation:sub-0000000000000000]] [[citation:sub-1111111111111111]] ',
])
def test_current_value_citations_do_not_hide_its_postfix_during_generation(citations):
    for warnings in _review_exact_statement('收入', 'monthlyAverage', suffix=citations + '（累计值）'):
        assert any('统计口径' in item for item in warnings)


@pytest.mark.parametrize('prefix', ['报告显示', '从统计结果可见', '本期登记'])
def test_narrative_trimming_preserves_registered_words_inside_the_department(prefix):
    assert _review_exact_statement(prefix + '卫生统计科收入', 'total', {'科室': '卫生统计科'}) == ([], [])
