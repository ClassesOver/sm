"""冻结数值引用贯通生成、绑定、编辑校验，不以同值替代事实身份。"""
import json
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    render_bound_numbers,
    resolve_number_reference,
    statement_fingerprint,
)
from smart_reporting.reporting.trace.subject_builder import build_claim_subject_bindings


def contents():
    metrics = []
    for key, field, values in [('a', 'actual_equipment', (10, 20)), ('b', 'budget_equipment', (20, 100))]:
        metrics.append(dict(factId='fact-' + key * 16, datasetId='ds', datasetSha256='c' * 64,
                            periodRoles=['current'], field=field, fieldRef='source.db.table.' + field,
                            aggregation='sum', unit='元', formula=f'SUM({field})', scope={},
                            total=sum(values), missingCount=0, zeroCount=0, negativeCount=0,
                            periodGranularity='month', periodStart='2025-01', periodEnd='2025-02',
                            periodValues=[{'period': f'2025-0{i+1}', 'value': value} for i, value in enumerate(values)]))
    return [json.dumps({'analysisId': 'analysis_001', 'metrics': metrics})]


@pytest.mark.parametrize(('selector', 'value', 'unit', 'periods'), [
    ('periodValues.1:元', 20, '元', ('2025-02',)),
    ('periodTotals.0-0:元', 10, '元', ('2025-01',)),
    ('budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-02.percentage:%', 20, '%', ('2025-02',)),
])
def test_resolves_exact_selector_instead_of_first_fact_total(selector, value, unit, periods):
    token = '{{value:fact-aaaaaaaaaaaaaaaa:' + selector + '}}'
    result = resolve_number_reference(token, contents())
    assert result['value'] == value
    assert result['unit'] == unit
    assert result['periods'] == periods


def test_number_anchors_keep_repeated_values_distinct_and_bind_both_operands():
    first = '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:元}}'
    second = '{{value:fact-aaaaaaaaaaaaaaaa:budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-02.percentage:%}}'
    markdown, references, notices = render_bound_numbers('租赁' + first + '，执行率' + second + '。', contents(), key='s:b')
    markdown = anchor_bound_numbers(markdown, references, notices)
    assert len(references) == 2 and references[0].claim_id != references[1].claim_id
    assert all(markdown.count('[[claim:' + ref.claim_id + ']]') == 1 for ref in references)
    block = SimpleNamespace(number_references=references)
    artifact = SimpleNamespace(section_code='s', blocks=[block], claims=[])
    bindings = build_claim_subject_bindings([artifact],
        {'fact-' + c * 16: ('analysis_001', '/metrics/' + str(i)) for i, c in enumerate('ab')},
        {'analysis_001': derive_resource_id('facts.json')})
    assert len(bindings) == 2
    assert len(bindings[1].fact_refs) == 2
    assert not notices
    assert statement_fingerprint(markdown.replace('租赁', '销售'), references[0].claim_id) != references[0].statement_sha256


def test_missing_operand_or_conflicting_identity_never_falls_back_to_total():
    token = '{{value:fact-aaaaaaaaaaaaaaaa:budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-02.percentage:%}}'
    doc = json.loads(contents()[0])
    doc['metrics'] = doc['metrics'][:1]
    assert resolve_number_reference(token, [json.dumps(doc)]) is None
    conflicting = json.loads(contents()[0])
    conflicting['metrics'][0]['periodValues'][1]['value'] = 999
    assert resolve_number_reference('{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:元}}',
                                    [*contents(), json.dumps(conflicting)]) is None


def test_same_fact_described_differently_by_two_analyses_is_not_an_identity_conflict():
    # 未声明序列粒度的分析把月初标签记为 day，声明按月的分析记为 month；冻结数值完全一致。
    from smart_reporting.reporting.trace.number_selection import align_number_selections

    daily = json.loads(contents()[0])
    for metric in daily['metrics']:
        metric.update(periodGranularity='day', displayName='设备支出，也称设备金额', warnings=['期间索引存在重复'])
    daily['analysisId'] = 'analysis_002'
    sources = [json.dumps(daily), *contents()]
    token = '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:元}}'
    resolved = resolve_number_reference(token, sources)
    assert resolved is not None and resolved['value'] == 20 and resolved['periods'] == ('2025-02',)
    assert resolved['entry']['periodGranularity'] == 'month'
    markdown, warnings = align_number_selections('设备支出合计为{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。', sources)
    assert markdown == '设备支出合计为{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。'
    assert not warnings
    conflicting = json.loads(json.dumps(daily))
    conflicting['metrics'][0]['total'] = 31
    markdown, warnings = align_number_selections('设备支出合计为{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。',
                                                 [json.dumps(conflicting), *contents()],
                                                 {'actual_equipment': '设备支出'})
    assert ':unverified:' in markdown and warnings


def test_date_range_is_not_read_as_its_first_month_when_aligning_selections():
    from smart_reporting.reporting.trace.number_selection import align_number_selections

    definitions = {'actual_equipment': '设备支出'}
    markdown = '2025年1月1日至2月1日，设备支出合计为{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。'
    assert align_number_selections(markdown, contents(), definitions) == (markdown, [])
    aligned, warnings = align_number_selections(
        '2025年1月设备支出合计为{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。', contents(), definitions)
    assert 'periodValues.0' in aligned and warnings


def test_missing_numbers_are_typed_at_replacement_not_guessed_from_prose():
    markdown, refs, notices = render_bound_numbers(
        '供应商答复待核实。租赁999999元。无效引用{{value:fact-cccccccccccccccc:total:元}}。', contents(), key='s:b')
    markdown = anchor_bound_numbers(markdown, refs, notices)
    assert not refs
    assert [notice.kind for notice in notices].count('numeric_unverified') == 2
    assert [notice.kind for notice in notices].count('source_review') == 1
    assert all('[[claim:' + notice.claim_id + ']]' in markdown for notice in notices)


def test_assembly_preserves_bindings_through_punctuation_and_date_formatting():
    from smart_reporting.reporting.delivery.draft_v1 import (
        ReportDraftBlock,
        validate_report_draft_blocks,
    )

    from .test_reporting_heading_numbers import _assemble_charts
    markdown, refs, notices = render_bound_numbers(
        '2025-02收入: {{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:元}}。答复待核实。',
        contents(), key='section_001:b',
    )
    block = ReportDraftBlock(blockId='b', markdown=markdown, numberReferences=refs,
                             reviewNotices=notices, chartPlacement='explicit')
    validate_report_draft_blocks((block,))
    rendered = _assemble_charts((block,), ()).markdown
    assert statement_fingerprint(rendered, refs[0].claim_id) == refs[0].statement_sha256
    assert '[[citation:sub-' in rendered
    assert all('[[claim:' + notice.claim_id + ']]' in rendered for notice in notices)


def test_bound_references_do_not_allow_model_protocol_injection():
    from smart_reporting.reporting.delivery.draft_v1 import (
        ReportDraftBlock,
        validate_report_draft_blocks,
    )
    from smart_reporting.reporting.models import ReportingError
    markdown, refs, notices = render_bound_numbers('{{value:fact-aaaaaaaaaaaaaaaa:total:元}}', contents(), key='s:b')
    block = ReportDraftBlock(blockId='b', markdown=markdown + '[[claim:forged]]', numberReferences=refs,
                             reviewNotices=notices)
    with pytest.raises(ReportingError, match='正文不得'):
        validate_report_draft_blocks((block,))


def test_merging_blocks_retains_annotation_offsets():
    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.tools.sections import RuntimeSectionsMixin
    first, refs1, notes1 = render_bound_numbers('甲{{value:fact-aaaaaaaaaaaaaaaa:total:元}}。', contents(), key='s:a')
    second, refs2, notes2 = render_bound_numbers('乙{{value:fact-bbbbbbbbbbbbbbbb:total:元}}。', contents(), key='s:b')
    blocks = [ReportDraftBlock(blockId='a', markdown=first, numberReferences=refs1, reviewNotices=notes1, claimIds=('c',)),
              ReportDraftBlock(blockId='b', markdown=second, numberReferences=refs2, reviewNotices=notes2)]
    merged, _ = RuntimeSectionsMixin._merge_claimless_blocks('s', blocks)
    assert len(merged) == 1
    anchored = anchor_bound_numbers(merged[0].markdown, merged[0].number_references, merged[0].review_notices)
    assert len(merged[0].number_references) == 2
    for ref in (*refs1, *refs2):
        assert statement_fingerprint(anchored, ref.claim_id) == ref.statement_sha256


def test_correlation_reference_preserves_scalar_fact_identity():
    doc = json.loads(contents()[0])
    doc['correlationDetails'] = [{
        'factId': 'fact-cccccccccccccccc', 'datasetId': 'ds', 'datasetSha256': 'c' * 64,
        'leftField': 'x', 'rightField': 'y',
        'method': 'pearson', 'sampleCount': 12, 'value': 0.82,
    }]
    token = '{{value:fact-cccccccccccccccc:value:}}'
    selected = resolve_number_reference(token, [json.dumps(doc)])
    assert selected is not None and selected['value'] == 0.82
    markdown, refs, notices = render_bound_numbers('关联系数' + token + '。', [json.dumps(doc)], key='s:b')
    artifact = SimpleNamespace(section_code='s', blocks=[SimpleNamespace(number_references=refs)], claims=[])
    bindings = build_claim_subject_bindings([artifact],
        {'fact-cccccccccccccccc': ('analysis_001', '/correlationDetails/0')},
        {'analysis_001': derive_resource_id('facts.json')})
    assert '0.82' in markdown and not notices
    assert bindings[0].fact_refs[0].fact_kind == 'correlation'


def test_heading_promotion_retains_exact_number_binding():
    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.runtime.sections import _promoted_heading_block
    markdown, refs, notices = render_bound_numbers(
        '#### 租赁\n\n2月回款{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:元}}。', contents(), key='s:b')
    block = ReportDraftBlock(blockId='b', markdown=markdown, numberReferences=refs, reviewNotices=notices)
    promoted = _promoted_heading_block(ReportingError('report_draft_heading_parent_missing', 'x'),
                                      block, [], SimpleNamespace(title='经营', section_code='s'))
    assert promoted is not None and promoted.markdown.startswith('### ')
    assert len(promoted.number_references) == 1
    anchored = anchor_bound_numbers(promoted.markdown, promoted.number_references, promoted.review_notices)
    assert statement_fingerprint(anchored, refs[0].claim_id) == refs[0].statement_sha256


@pytest.mark.parametrize(('selector', 'periods', 'statement'), [
    ('periodValues.1:元', ('2025-02',), '2025年2月收入'),
    ('periodTotals.0-2:元', ('2025-01', '2025-02', '2025-03'), '截至2025年3月，含2025年2月的累计收入'),
    ('periodAverages.0-2:元', ('2025-01', '2025-02', '2025-03'), '含2025年2月的期间月均收入'),
    ('periodChanges.2:元', ('2025-02', '2025-03'), '2025年3月较2025年2月增加'),
    ('periodChangeRates.2:%', ('2025-02', '2025-03'), '2025年3月较2025年2月增长'),
])
def test_selected_periods_preserve_month_grain_and_all_input_buckets(selector, periods, statement):
    from smart_reporting.reporting.trace.subject_builder import claim_status

    document = json.loads(contents()[0])
    for metric in document['metrics']:
        metric['periodEnd'] = '2025-03'
        metric['periodValues'].append({'period': '2025-03', 'value': 30})
        metric['total'] += 30
        for bucket in metric['periodValues']:
            bucket['period'] += '-01'
    frozen = [json.dumps(document)]
    token = '{{value:fact-aaaaaaaaaaaaaaaa:' + selector + '}}'
    selected = resolve_number_reference(token, frozen)
    assert selected['periods'] == periods
    markdown, refs, notices = render_bound_numbers(statement + token + '。', frozen, key='periods')
    assert len(refs) == 1 and not notices
    anchored = anchor_bound_numbers(markdown, refs, notices)
    status = claim_status(anchored, refs[0].claim_id, selected['value'],
                          expected_unit=selected['unit'], expected_periods=selected['periods'])
    assert status == {'status': 'valid', 'warnings': []}


def test_selected_daily_bucket_keeps_day_precision():
    document = json.loads(contents()[0])
    metric = document['metrics'][0]
    metric['periodGranularity'] = 'day'
    metric['periodValues'] = [{'period': '2025-02-01', 'value': 10},
                              {'period': '2025-02-02', 'value': 20}]
    token = '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:元}}'
    selected = resolve_number_reference(token, [json.dumps(document)])
    assert selected['periods'] == ('2025-02-02',)


@pytest.mark.parametrize('field', ['difference', 'percentage'])
def test_cumulative_budget_reference_preserves_middle_month(field):
    from smart_reporting.reporting.trace.subject_builder import unit_period_warnings

    document = json.loads(contents()[0])
    for metric in document['metrics']:
        metric['periodValues'].append({'period': '2025-03-01', 'value': 30})
        metric['total'] += 30
    unit = '%' if field == 'percentage' else '元'
    token = ('{{value:fact-aaaaaaaaaaaaaaaa:budgetComparison.fact-bbbbbbbbbbbbbbbb.'
             '2025-01..2025-03.' + field + ':' + unit + '}}')
    selected = resolve_number_reference(token, [json.dumps(document)])
    assert selected['periods'] == ('2025-01', '2025-02', '2025-03')
    assert unit_period_warnings('包含2025年2月', expected_periods=selected['periods']) == []
    assert unit_period_warnings('包含2025年4月', expected_periods=selected['periods'])


@pytest.mark.parametrize('selector', [
    'periodTotals.0-2:元', 'periodAverages.0-2:元',
    'budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-01..2025-03.difference:元',
    'budgetComparison.fact-bbbbbbbbbbbbbbbb.2025-01..2025-03.percentage:%',
])
@pytest.mark.parametrize(('statement', 'warns'), [
    ('截至2025年2月累计', True),
    ('2025年2月累计', True),
    ('截至2025年2月，包含2025年3月的累计', True),
    ('截至2025年3月，含2025年2月的累计', False),
    ('包含2025年2月的累计', False),
    ('2025年1月至2025年3月累计', False),
    ('截至2025-03，含2025/02的累计', False),
    ('本期累计', False),
])
def test_cumulative_period_roles_distinguish_endpoint_from_context(selector, statement, warns):
    _assert_period_role_warning(selector, statement, warns, {'endpoint': ('2025-03',)})


@pytest.mark.parametrize('selector', ['periodChanges.2:元', 'periodChangeRates.2:%'])
@pytest.mark.parametrize(('statement', 'warns'), [
    ('2025年2月增长', True),
    ('2025年2月较2025年3月增长', True),
    ('较2025年3月增长', True),
    ('2025年3月较2025年2月增长', False),
    ('较2025年2月，2025年3月增长', False),
    ('以2025年2月为基期，2025年3月增长', False),
    ('基期2025年2月，2025年3月增长', False),
    ('以2025年3月为本期，较2025年2月增长', False),
    ('以2025年2月为本期，较2025年2月增长', True),
    ('2025年2月为基期，2025年3月增长', False),
    ('与2025年2月相比，2025年3月增长', False),
    ('2025年2月至2025年3月增长', False),
    ('2025-03较2025/02增长', False),
    ('环比增长', False),
])
def test_change_period_roles_distinguish_current_from_baseline(selector, statement, warns):
    _assert_period_role_warning(selector, statement, warns,
                                {'current': ('2025-03',), 'baseline': ('2025-02',)})


def _assert_period_role_warning(selector, statement, warns, roles):
    from smart_reporting.reporting.trace.subject_builder import (
        claim_status,
        prepare_claim_status,
        unit_period_warnings,
    )

    document = json.loads(contents()[0])
    for metric in document['metrics']:
        metric['periodEnd'] = '2025-03'
        metric['periodValues'].append({'period': '2025-03-01', 'value': 30})
        metric['total'] += 30
    frozen = [json.dumps(document)]
    token = '{{value:fact-aaaaaaaaaaaaaaaa:' + selector + '}}'
    selected = resolve_number_reference(token, frozen)
    # 使用与编辑器相同的调用链，值仍有效，错期只产生软告警。
    markdown, refs, notices = render_bound_numbers(statement + token + '。', frozen, key='roles')
    assert len(refs) == 1 and not notices
    options = dict(expected_unit=selected['unit'], expected_periods=selected['periods'],
                   expected_period_roles=selected.get('period_roles'))
    anchored = anchor_bound_numbers(markdown, refs)
    result = claim_status(anchored, refs[0].claim_id, selected['value'], **options)
    # prepare_claim_status 是编辑器校验入口，必须同样接收期间角色。
    prepared = prepare_claim_status(anchored)(refs[0].claim_id, selected['value'], **options)
    assert prepared == result
    assert result['status'] == 'valid'
    assert bool(result['warnings']) is warns
    assert bool(unit_period_warnings(statement, **options)) is warns
    assert selected['period_roles'] == roles


@pytest.mark.parametrize(('selector', 'scope', 'formula'), [
    ('groupShares.topGroups.0:%', {'group': '内科'}, '(20) / (30) * 100'),
    ('groupShares.bottomGroups.0:%', {'group': '外科'}, '(10) / (30) * 100'),
    ('groupGaps.0-1:元', {'leftGroup': '内科', 'rightGroup': '外科'}, 'abs((20) - (10))'),
])
def test_group_derived_reference_keeps_operand_scope_and_formula(selector, scope, formula):
    from smart_reporting.reporting.trace.subject_builder import claim_status

    document = json.loads(contents()[0])
    metric = document['metrics'][0]
    metric['scope'] = {'院区': '东院'}
    metric['topGroups'] = [{'group': '内科', 'value': 20}, {'group': '外科', 'value': 10}]
    metric['bottomGroups'] = [{'group': '外科', 'value': 10}]
    selected = resolve_number_reference('{{value:fact-aaaaaaaaaaaaaaaa:' + selector + '}}',
                                        [json.dumps(document)])
    assert selected['scope'] == {'院区': '东院', **scope}
    assert selected['formula'] == formula
    # Missing group names must generate a scope warning even though the number matches.
    from smart_reporting.reporting.trace.numeric_text import format_fact_value
    displayed = format_fact_value(selected['value'], selected['unit'])
    status = claim_status(f"东院{displayed}[[claim:c]]。", 'c',
                          selected['value'], expected_unit=selected['unit'],
                          expected_scope=selected['scope'])
    assert any('业务范围' in warning for warning in status['warnings'])


@pytest.mark.parametrize(('selector', 'value', 'formula'), [
    ('monthlyAverage:元', 15, '((10) + (20)) / 2'),
    ('monthlyMinimum:元', 10, 'min(10, 20)'),
    ('monthlyMaximum:元', 20, 'max(10, 20)'),
    ('periodTotals.0-0:元', 10, '(10)'),
    ('periodTotals.0-1:元', 30, '(10) + (20)'),
    ('periodAverages.0-1:元', 15, '((10) + (20)) / 2'),
    ('periodChanges.1:元', 10, '(20) - (10)'),
    ('periodChangeRates.1:%', 100, '((20) - (10)) / abs(10) * 100'),
])
def test_period_derived_formula_matches_selected_calculation(selector, value, formula):
    result = resolve_number_reference('{{value:fact-aaaaaaaaaaaaaaaa:' + selector + '}}', contents())
    assert result['value'] == value
    assert result['formula'] == formula


def test_period_average_uses_available_bucket_count_not_calendar_span():
    document = json.loads(contents()[0])
    metric = document['metrics'][0]
    metric['periodValues'][1]['period'] = '2025-03'
    metric['periodEnd'] = '2025-03'
    result = resolve_number_reference('{{value:fact-aaaaaaaaaaaaaaaa:monthlyAverage:元}}', [json.dumps(document)])
    assert result['value'] == 15
    assert result['formula'] == '((10) + (20)) / 2'
    assert result['periods'] == ('2025-01', '2025-03')


@pytest.mark.parametrize(('window', 'field', 'value', 'formula'), [
    ('2025-02', 'percentage', 20, '(20) / (100) * 100'),
    ('2025-02', 'difference', -80, '(20) - (100)'),
    ('2025-01..2025-02', 'percentage', 25, '(30) / (120) * 100'),
    ('2025-01..2025-02', 'difference', -90, '(30) - (120)'),
])
def test_budget_formula_uses_selected_monthly_operands(window, field, value, formula):
    unit = '%' if field == 'percentage' else '元'
    token = '{{value:fact-aaaaaaaaaaaaaaaa:budgetComparison.fact-bbbbbbbbbbbbbbbb.' + window + '.' + field + ':' + unit + '}}'
    selected = resolve_number_reference(token, contents())
    assert selected['value'] == value
    assert selected['formula'] == formula


@pytest.mark.parametrize('extra', ['not-json', '[]', 'null', '{"metrics": null}'])
def test_reference_resolution_ignores_non_bundle_content_like_catalog(extra):
    token = '{{value:fact-aaaaaaaaaaaaaaaa:total:元}}'
    markdown, refs, notices = render_bound_numbers('收入' + token + '。', [*contents(), extra], key='mixed')
    assert len(refs) == 1 and not notices
    selected = resolve_number_reference(token, [*contents(), extra])
    assert selected is not None and selected['value'] == 30


@pytest.mark.parametrize('include_alias_copy', [False, True])
def test_reference_resolution_accepts_schema_field_names_and_equivalent_defaults(include_alias_copy):
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )

    bundle = DeterministicAnalysisBundle.model_validate_json(contents()[0])
    documents = [bundle.model_dump_json(by_alias=False)]
    if include_alias_copy:
        documents.extend(contents())
    token = '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:元}}'
    selected = resolve_number_reference(token, documents)
    assert selected is not None
    assert selected['value'] == 20
    assert selected['periods'] == ('2025-02',)


def test_prepared_number_resolver_reuses_catalog_without_cross_snapshot_cache(monkeypatch):
    import smart_reporting.reporting.trace.semantic_bindings as bindings

    tokens = ['{{value:fact-aaaaaaaaaaaaaaaa:total:元}}',
              '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.0:元}}']
    expected = [resolve_number_reference(token, contents()) for token in tokens]
    calls = 0
    original = bindings._frozen_number_entries

    def counted(values):
        nonlocal calls
        calls += 1
        return original(values)

    monkeypatch.setattr(bindings, '_frozen_number_entries', counted)
    resolver = bindings.NumberReferenceResolver(contents())
    assert [resolver.resolve(token) for token in tokens] == expected
    assert resolver.resolve('{{value:fact-cccccccccccccccc:total:元}}') is None
    assert calls == 1
    assert bindings.NumberReferenceResolver(()).resolve(tokens[0]) is None


def test_prepared_claim_check_preserves_hidden_and_duplicate_markers():
    from smart_reporting.reporting.trace.subject_builder import ClaimStatusChecker, claim_status

    markdown = ('[[section:s]]\n收入10元[[claim:a]]。\n\n'
                '`收入10元[[claim:hidden]]`\n\n'
                '收入10元[[claim:duplicate]][[claim:duplicate]]')
    checker = ClaimStatusChecker(markdown)
    for claim in ('a', 'hidden', 'duplicate', 'missing'):
        assert checker.check(claim, 10, expected_unit='元', section_id='s') == claim_status(
            markdown, claim, 10, expected_unit='元', section_id='s')


def test_batch_statement_fingerprints_preserve_normalization_and_duplicates():
    from smart_reporting.reporting.trace.semantic_bindings import statement_fingerprints

    markdown = '收入: 10元[[claim:a]]。\n\n2025-02成本20元[[claim:b]]。[[claim:dup]][[claim:dup]]'
    claims = ['a', 'b', 'dup', 'missing']
    assert statement_fingerprints(markdown, claims) == {
        key: statement_fingerprint(markdown, key) for key in claims
    }


def test_raw_large_amounts_get_thousands_separators_without_moving_anchors():
    from smart_reporting.reporting.trace.numeric_text import group_large_amounts

    assert group_large_amounts('每月均为1097718506元，差额-66724688元，人次6009877人次。') == (
        '每月均为1,097,718,506元，差额-66,724,688元，人次6,009,877人次。')
    # 年份、编号、万元与已分组数字不动。
    unchanged = '2025年RJ301012345元编号，12345万元，1,234,567元，1234元。'
    assert group_large_amounts(unchanged) == unchanged
    doc = json.loads(contents()[0])
    doc['metrics'][0]['periodValues'][1]['value'] = 1097718506
    doc['metrics'][0]['total'] = 1097718516
    markdown, refs, notices = render_bound_numbers(
        '另有1097718506元，全年{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:元}}。', [json.dumps(doc)], key='s:b')
    anchored = anchor_bound_numbers(markdown, refs, notices)
    assert anchored == f'另有1,097,718,506元，全年1,097,718,506元[[claim:{refs[0].claim_id}]]。'


def test_single_period_value_without_written_period_is_withdrawn():
    """回放：“普通住院业务预算减实际的差额为10.93亿元”引用的是3月实际收入，句中没有任何期间。"""
    import json

    from smart_reporting.reporting.trace.number_selection import align_number_selections

    fact = 'fact-' + 'a' * 16
    document = json.dumps({'analysisId': 'analysis_001', 'metrics': [{
        'factId': fact, 'datasetId': 'current', 'datasetSha256': 'b' * 64, 'periodRoles': ['current'],
        'field': 'amount', 'fieldRef': 'h.amount', 'displayName': '实际收入', 'aggregation': 'sum', 'unit': '元',
        'formula': 'sum(amount)', 'total': 600, 'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
        'periodGranularity': 'month',
        'periodValues': [{'period': f'2025-{index:02d}', 'value': value}
                         for index, value in ((1, 100), (2, 200), (3, 300))]}]})
    token = '{{value:' + fact + ':periodValues.2:元}}'
    wrong = '普通住院业务预算减实际的差额为' + token + '。'
    aligned, warnings = align_number_selections(wrong, [document])
    assert ':unverified:' in aligned and any('期间缺失' in item for item in warnings)
    for kept in ('3月实际收入为' + token + '。', '实际收入各月介于{{value:' + fact + ':periodValues.0:元}}至' + token + '。',
                 '当月实际收入为' + token + '。'):
        assert align_number_selections(kept, [document])[0] == kept
