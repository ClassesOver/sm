"""跨年选择、多维分组和自定义表格行键的完整溯源回归。"""

import hashlib
import json

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.fact_index import metric_fact_identity
from smart_reporting.reporting.trace.numeric_text import frozen_number_catalog
from smart_reporting.reporting.trace.semantic_bindings import (
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.table_builder import build_table_trace

from .test_deterministic_analysis import analysis, context, semantic
from .test_trace_subject_validate import _make_editor_with_subject


@pytest.mark.parametrize('prefix,expected', [
    ('2024年11月至2025年2月收入为', 1000),
    ('2024年11月—2025年2月收入合计', 1000),
    ('2024年11月到2025年2月收入为', 1000),
    ('2025年2月收入为', 400),
    ('收入为', 1000),
])
@pytest.mark.parametrize('legacy', [False, True])
def test_cross_year_window_must_not_be_replaced_with_the_last_month(prefix, expected, legacy):
    ctx = context('current').model_copy(update={'period_granularities': {'month': 'month'}})
    bundle = build_deterministic_analysis_bundle(analysis(), (
        ('current', b'month,department,amount\n2024-11,A,100\n2024-12,A,200\n2025-01,A,300\n2025-02,A,400\n', ctx, ('current',)),
    ))
    token = '{{value:' + bundle.metrics[0].fact_id + ':total:元}}'
    payload = bundle.model_dump(mode='json', by_alias=True)
    if legacy:
        payload['metrics'][0].pop('periodMissingCount')
    contents = [json.dumps(payload)]
    rendered, refs, notices = render_bound_numbers(prefix + token + '。', contents, key='cross-year',
                                                  field_definitions={'amount': '收入'})
    selected = resolve_number_reference(refs[0].token, contents)
    assert selected['value'] == expected and not notices
    assert f'{expected:,}元' in rendered


@pytest.mark.parametrize('collision', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
def test_distinct_multidimensional_groups_keep_distinct_lineage_scope(collision, reverse):
    rows = ['A / B,C,100', 'A,B / C,200'] if collision else ['A,C,100', 'B,C,200']
    if reverse:
        rows.reverse()
    content = ('month,department,ward,amount\n' + ''.join('2025-01,' + row + '\n' for row in rows)).encode()
    ctx = context('current', fields=('month', 'department', 'ward', 'amount'), semantics=(
        {**semantic('amount', unit='元'), 'additiveAcross': ['month', 'department', 'ward']},
    )).model_copy(
        update={'organization_grain': ('department', 'ward')})
    item = analysis().model_copy(update={'organization_grain': ('department', 'ward')})
    bundle = build_deterministic_analysis_bundle(item, (('current', content, ctx, ('current',)),))
    fact = bundle.metrics[0]
    assert len(fact.top_groups) == 2
    contents = [bundle.model_dump_json(by_alias=True)]
    resolved = [resolve_number_reference('{{value:' + fact.fact_id + ':topGroups.' + str(i) + ':元}}', contents)
                for i in (0, 1)]
    gap = resolve_number_reference('{{value:' + fact.fact_id + ':groupGaps.0-1:元}}', contents)
    assert resolved[0]['scope'] != resolved[1]['scope']
    assert len({group.group for group in fact.top_groups}) == 2
    assert resolved[0]['scope']['department'] == 'A' if collision else resolved[0]['scope']['department'] == 'B'
    assert gap['scope']['leftGroup.department'] != gap['scope']['rightGroup.department']
    loaded = DeterministicAnalysisBundle.model_validate_json(contents[0])
    assert loaded.metrics[0].top_groups[0].group_values == fact.top_groups[0].group_values


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('custom_key', [False, True, 'period-prefix', 'comparison-prefix', 'selector-prefix'])
async def test_generated_period_table_with_custom_row_keys_validates_its_own_values(tmp_path, monkeypatch, custom_key):
    editor, grants, ctx = await _make_editor_with_subject(tmp_path, period_table=True)
    index = await editor.trace.require_index(ctx)
    original = index.tables[0].cells[0].fact_refs[0]
    file_ref = next(file for file in index.files if file.resource_id == original.file_resource_id)
    content = await editor.trace._read_registered_file(ctx, file_ref, max_bytes=16 * 1024 * 1024)
    bundle = DeterministicAnalysisBundle.model_validate_json(content)
    keys = {
        False: ['period:2025-09', 'period:2025-10'], True: ['row-0', 'row-1'],
        'period-prefix': ['period:wrong', 'period:other'],
        'comparison-prefix': ['comparison:0:change', 'comparison:0:baselineTotal'],
        'selector-prefix': ['total', 'periodValues.999'],
    }[custom_key]
    trace, markdown = build_table_trace(bundle, {
        'tableId': 'tbl-1', 'metricCodes': ['income_total'],
        'rows': [{'key': keys[i], 'period': period, 'label': period}
                 for i, period in enumerate(('2025-09', '2025-10'))],
    }, fact_file_resource_id=file_ref.resource_id)
    trace = trace.model_copy(update={'origin_markdown': markdown})
    # 模拟正常装配阶段冻结的 TableTrace；文件内容仍从原授权快照读取并校验 hash。
    frozen_index = index.model_copy(update={'tables': (trace,)})
    async def require_index(_ctx):
        return frozen_index
    monkeypatch.setattr(editor.trace, 'require_index', require_index)
    raw, _ = await grants.issue(ctx)
    _token, session = await grants.exchange(raw)
    result = await editor.trace_validate(ctx, session, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert result['tableSummary']['valid'] == 2 and result['tableSummary']['stale'] == 0
    assert [cell.value_selector for cell in trace.cells] == ['periodValues.0', 'periodValues.1']
    reordered = markdown.replace('| 2025-09 | 1,200 |\n| 2025-10 | 2,400 |',
                                 '| 2025-10 | 2,400 |\n| 2025-09 | 1,200 |')
    assert reordered != markdown
    reordered_result = await editor.trace_validate(ctx, session, reordered, hashlib.sha256(reordered.encode()).hexdigest())
    assert reordered_result['tableSummary']['valid'] == 2
    changed = markdown.replace('1,200', '3,600')
    changed_result = await editor.trace_validate(ctx, session, changed, hashlib.sha256(changed.encode()).hexdigest())
    assert changed_result['tableSummary']['stale'] == 1


@pytest.mark.parametrize('window,expected', [
    ('2024年11月至2025年1月', 600), ('2024年11月～2025年2月', 1000),
    ('2024年11月—2025年1月', 600),
])
def test_cross_year_prefixes_keep_the_complete_requested_window(window, expected):
    ctx = context('current').model_copy(update={'period_granularities': {'month': 'month'}})
    bundle = build_deterministic_analysis_bundle(analysis(), (
        ('current', b'month,department,amount\n2024-11,A,100\n2024-12,A,200\n2025-01,A,300\n2025-02,A,400\n', ctx, ('current',)),
    ))
    contents = [bundle.model_dump_json(by_alias=True)]
    token = '{{value:' + bundle.metrics[0].fact_id + ':total:元}}'
    _text, refs, notices = render_bound_numbers(window + '收入为' + token, contents, key='prefix',
                                               field_definitions={'amount': '收入'})
    assert len(refs) == 1 and not notices
    selected = resolve_number_reference(refs[0].token, contents)
    assert selected['value'] == expected and selected['periods'][0] == '2024-11'
    assert selected['periods'][-1] == ('2025-01' if expected == 600 else '2025-02')


@pytest.mark.parametrize('missing', ['2024-12', '2025-01'])
def test_cross_year_windows_with_a_missing_month_do_not_borrow_the_final_month(missing):
    rows = [('2024-11', 100), ('2024-12', 200), ('2025-01', 300), ('2025-02', 400)]
    body = ''.join(f'{period},A,{value}\n' for period, value in rows if period != missing)
    ctx = context('current').model_copy(update={'period_granularities': {'month': 'month'}})
    bundle = build_deterministic_analysis_bundle(analysis(), (
        ('current', ('month,department,amount\n' + body).encode(), ctx, ('current',)),
    ))
    token = '{{value:' + bundle.metrics[0].fact_id + ':total:元}}'
    _text, refs, notices = render_bound_numbers('2024年11月至2025年2月收入为' + token,
        [bundle.model_dump_json(by_alias=True)], key='missing', field_definitions={'amount': '收入'})
    assert not refs and notices


def test_stock_cross_year_window_uses_the_registered_endpoint():
    ctx = context('current', semantics=({**semantic('amount', unit='元'), 'additiveAcross': ['department']},)).model_copy(
        update={'period_granularities': {'month': 'month'}})
    bundle = build_deterministic_analysis_bundle(analysis(), (
        ('current', b'month,department,amount\n2024-12,A,100\n2025-01,A,300\n', ctx, ('current',)),
    ))
    token = '{{value:' + bundle.metrics[0].fact_id + ':total:元}}'
    contents = [bundle.model_dump_json(by_alias=True)]
    text, refs, notices = render_bound_numbers('2024年12月至2025年1月资金余额为' + token, contents, key='stock',
                                              field_definitions={'amount': '资金余额'})
    assert text.endswith('300元') and not notices
    assert resolve_number_reference(refs[0].token, contents)['periods'] == ('2025-01',)


@pytest.mark.parametrize('rows', [
    ['', 'None'],
    ['A / B,C', 'A,B / C'],
    ['a' * 240 + ' / B,C', 'a' * 240 + ',B / C'],
])
def test_group_values_preserve_nulls_delimiters_and_bounded_display(rows):
    if len(rows[0].split(',')) == 1:
        content = ('month,department,amount\n' + ''.join(f'2025-01,{value},{100 + i}\n' for i, value in enumerate(rows))).encode()
        fields, grain = ('month', 'department', 'amount'), ('department',)
    else:
        content = ('month,department,ward,amount\n' + ''.join(f'2025-01,{value},{100 + i}\n' for i, value in enumerate(rows))).encode()
        fields, grain = ('month', 'department', 'ward', 'amount'), ('department', 'ward')
    ctx = context('current', fields=fields).model_copy(update={'organization_grain': grain})
    item = analysis().model_copy(update={'organization_grain': grain})
    bundle = build_deterministic_analysis_bundle(item, (('current', content, ctx, ('current',)),))
    loaded = DeterministicAnalysisBundle.model_validate_json(bundle.model_dump_json(by_alias=True))
    fact = loaded.metrics[0]
    assert len({group.group for group in fact.top_groups}) == 2
    assert all(len(group.group) <= 512 for group in fact.top_groups)
    first, second = fact.top_groups
    assert first.group_values != second.group_values
    swapped = fact.model_copy(update={'top_groups': (first.model_copy(update={'group_values': second.group_values}), second)})
    assert metric_fact_identity(fact) != metric_fact_identity(swapped)


def test_legacy_ambiguous_group_numbers_are_unverified_without_raw_dimension_values():
    ctx = context('current')
    bundle = build_deterministic_analysis_bundle(analysis(), (
        ('current', b'month,department,amount\n2025-01,A,100\n2025-01,B,200\n2025-01,C,50\n', ctx, ('current',)),
    ))
    payload = bundle.model_dump(mode='json', by_alias=True)
    fact = payload['metrics'][0]
    for side in ('topGroups', 'bottomGroups'):
        for group in fact[side]:
            group.pop('groupValues')
            if group['group'] in {'A', 'B'}:
                group['group'] = 'legacy-duplicate'
    contents = [json.dumps(payload)]
    catalog = frozen_number_catalog(contents)
    for selector in ('topGroups.0', 'topGroups.1', 'groupShares.topGroups.0', 'groupGaps.0-1'):
        unit = '%' if selector.startswith('groupShares') else '元'
        token = '{{value:' + fact['factId'] + ':' + selector + ':' + unit + '}}'
        assert token not in catalog and resolve_number_reference(token, contents) is None
    # 未歧义条目保留原始索引；不能因过滤前两项而把第三项重编号。
    token = '{{value:' + fact['factId'] + ':topGroups.2:元}}'
    assert resolve_number_reference(token, contents)['value'] == 50


def test_disambiguated_group_display_stays_bounded_without_losing_raw_identity():
    department, ward = 'department_' + 'x' * 110, 'ward_' + 'y' * 115
    label = 'A' * 260
    content = (f'month,{department},{ward},amount\n2025-01,{label} / B,C,100\n'
               f'2025-01,{label},B / C,200\n').encode()
    grain = (department, ward)
    ctx = context('current', fields=('month', *grain, 'amount'), semantics=(
        {**semantic('amount', unit='元'), 'additiveAcross': ['month', *grain]},
    )).model_copy(update={'organization_grain': grain})
    bundle = build_deterministic_analysis_bundle(analysis().model_copy(update={'organization_grain': grain}),
                                                 (('current', content, ctx, ('current',)),))
    loaded = DeterministicAnalysisBundle.model_validate_json(bundle.model_dump_json(by_alias=True))
    groups = loaded.metrics[0].top_groups
    assert len({group.group for group in groups}) == 2
    assert all(len(group.group) <= 512 for group in groups)
    assert {group.group_values[department] for group in groups} == {label, label + ' / B'}


@pytest.mark.parametrize('month_count', [13, 25])
def test_full_multi_year_window_uses_the_frozen_complete_total(month_count):
    periods = [f'{2024 + index // 12}-{index % 12 + 1:02d}' for index in range(month_count)]
    content = ('month,department,amount\n' + ''.join(f'{period},A,1\n' for period in periods)).encode()
    ctx = context('current').model_copy(update={'period_granularities': {'month': 'month'}})
    bundle = build_deterministic_analysis_bundle(analysis(), (('current', content, ctx, ('current',)),))
    token = '{{value:' + bundle.metrics[0].fact_id + ':total:元}}'
    text, refs, notices = render_bound_numbers(
        f'2024年1月至{periods[-1][:4]}年1月收入为' + token, [bundle.model_dump_json(by_alias=True)],
        key='multi-year', field_definitions={'amount': '收入'})
    assert text.endswith(f'{month_count}元') and len(refs) == 1 and not notices
