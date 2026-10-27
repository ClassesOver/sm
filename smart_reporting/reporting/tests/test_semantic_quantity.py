"""结构化数量关系使用源身份，不能以算术可重算代替正文业务归属。"""
import json

import pytest

from smart_reporting.reporting.tests.test_semantic_bindings import contents
from smart_reporting.reporting.trace.semantic_quantity import build_quantity_catalog


def _catalog(rows=None):
    frozen = contents()
    document = {'periods': ['2025-01', '2025-02'], 'scope': {}, 'findings': [{
        'name': '科室收入', 'columns': ['科室', '金额', '占比'],
        'columnMeta': {'金额': {'unit': '元'}, '占比': {'unit': '%', 'isPercent': True}},
        'rows': rows or [['甲科', 60, 60], ['乙科', 30, 30], ['丙科', 10, 10]],
    }]}
    fact = json.loads(frozen[0])
    fact['metrics'][0]['total'] = 100
    fact['metrics'][0]['periodValues'] = [{'period': '2025-01', 'value': 40}, {'period': '2025-02', 'value': 60}]
    frozen = [json.dumps(fact)]
    raw = json.dumps(document, ensure_ascii=False).encode()
    return build_quantity_catalog([*frozen, raw.decode()], {'trf-' + 'a' * 20: raw}, table_contexts={
        'trf-' + 'a' * 20: {'populationFactId': 'fact-aaaaaaaaaaaaaaaa', 'scope': {},
                              'periods': ['2025-01', '2025-02'], 'completePopulation': True}})


def _source(catalog, **criteria):
    return next(item['sourceId'] for item in catalog.prompt if all(item.get(k) == v for k,v in criteria.items()))


def test_top_set_uses_complete_table_and_not_monthly_average():
    catalog = _catalog()
    amount = _source(catalog, kind='table_column', column='金额')
    binding = catalog.resolve({'operation': 'top_sum', 'left': [amount], 'limit': 2,
        'selection': 'items', 'evidence': ['前两项收入合计']}, '前两项收入合计90元。')
    assert binding is not None
    assert binding.view['value'] == 90
    assert binding.table_derivation is not None
    assert len(binding.table_derivation.operands) == 2
    assert binding.display_text == '90元'


def test_department_share_selects_exact_percentage_cell():
    catalog = _catalog()
    share = _source(catalog, kind='table_column', column='占比')
    binding = catalog.resolve({'operation': 'value', 'left': [share], 'rowLabel': '甲科',
        'evidence': ['甲科占全院收入']}, '甲科占全院收入60%。')
    assert binding is not None
    assert binding.view['value'] == 60
    assert binding.display_text == '60.00%'
    assert len(binding.table_derivation.operands) == 1


def test_top_share_orders_by_amount_and_preserves_all_selected_members():
    catalog = _catalog()
    share = _source(catalog, kind='table_column', column='占比')
    amount = _source(catalog, kind='table_column', column='金额')
    binding = catalog.resolve({'operation': 'top_share', 'left': [share], 'limit': 2,
        'selection': 'items', 'orderBySourceId': amount, 'evidence': ['前两项收入占比']},
        '前两项收入占比90%。')
    assert binding is not None and binding.view['value'] == 90
    assert [op.row_index for op in binding.table_derivation.operands] == [0, 1]


@pytest.mark.parametrize('patch', [
    {'evidence': []}, {'evidence': ['不存在']}, {'selection': 'unknown'},
    {'left': ['invented']}, {'limit': 9},
])
def test_unknown_or_ungrounded_top_set_does_not_mint_a_proof(patch):
    catalog = _catalog()
    amount = _source(catalog, kind='table_column', column='金额')
    quantity = {'operation': 'top_sum', 'left': [amount], 'limit': 2,
        'selection': 'items', 'evidence': ['前两项收入合计'], **patch}
    assert catalog.resolve(quantity, '前两项收入合计90元。') is None


@pytest.mark.parametrize('rows', [
    [['甲科', 60, 60], ['甲科', 30, 30]],
    [['甲科', 60, 60], ['乙科', None, 30]],
    [['甲科', 60, 60], [None, 30, 30]],
])
def test_incomplete_or_ambiguous_table_never_becomes_complete_top_set(rows):
    catalog = _catalog(rows)
    matches = [item for item in catalog.prompt if item.get('column') == '金额']
    if matches:
        assert catalog.resolve({'operation': 'top_sum', 'left': [matches[0]['sourceId']],
            'limit': 1, 'selection': 'items', 'evidence': ['第一项收入']}, '第一项收入60元。') is None


def test_fact_difference_and_share_use_ordered_source_identity():
    catalog = _catalog()
    total = _source(catalog, kind='fact', selector='total')
    january = _source(catalog, kind='fact', selector='periodValues.0')
    february = _source(catalog, kind='fact', selector='periodValues.1')
    binding = catalog.resolve({'operation': 'difference', 'left': [january, february], 'right': [total],
        'evidence': ['两个月加总与全期差额']}, '两个月加总与全期差额0元。')
    assert binding is not None and binding.view['value'] == 0
    assert 'diff(sum(' in binding.token
    share = catalog.resolve({'operation': 'share', 'left': [february], 'right': [total],
        'evidence': ['二月占全期比重']}, '二月占全期比重66.67%。')
    assert share is not None and share.view['value'] == pytest.approx(60.00)


def test_prompt_never_contains_source_amounts():
    entries = [{key: value for key, value in entry.items() if key not in {'sourceId', 'factId'}}
               for entry in _catalog().prompt]
    assert 'value' not in {key for entry in entries for key in entry}
    assert all(type(value) not in (float, int) for entry in entries for value in entry.values())


def test_top_subset_that_does_not_reconcile_to_registered_population_is_rejected():
    catalog = _catalog([['甲科', 60, 60], ['乙科', 30, 30]])
    amount = _source(catalog, kind='table_column', column='金额')
    assert catalog.resolve({'operation': 'top_sum', 'left': [amount], 'limit': 1,
        'selection': 'items', 'evidence': ['第一项收入']}, '第一项收入60元。') is None


def test_top_share_cannot_be_selected_from_unregistered_percentage_population():
    catalog = _catalog([['甲科', 60, 30], ['乙科', 30, 15], ['丙科', 10, 5]])
    share = _source(catalog, kind='table_column', column='占比')
    amount = _source(catalog, kind='table_column', column='金额')
    assert catalog.resolve({'operation': 'top_share', 'left': [share], 'limit': 2,
        'selection': 'items', 'orderBySourceId': amount, 'evidence': ['前两项占全院']},
        '前两项占全院45%。') is None


def test_table_without_complete_population_proof_cannot_supply_top_set():
    catalog = _catalog()
    amount = _source(catalog, kind='table_column', column='金额')
    catalog._sources[amount]['population'] = {}
    assert catalog.resolve({'operation': 'top_sum', 'left': [amount], 'limit': 2,
        'selection': 'items', 'evidence': ['前两项收入合计']}, '前两项收入合计90元。') is None


@pytest.mark.parametrize(('selection', 'expected'), [('items', 80), ('rank', 100)])
def test_top_boundary_ties_use_explicit_selection_rule(selection, expected):
    catalog = _catalog([['甲科', 60, 60], ['乙科', 20, 20], ['丙科', 20, 20]])
    amount = _source(catalog, kind='table_column', column='金额')
    binding = catalog.resolve({'operation': 'top_sum', 'left': [amount], 'limit': 2,
        'selection': selection, 'evidence': ['前两项收入合计']}, '前两项收入合计。')
    assert binding is not None and binding.view['value'] == expected


def test_explicit_display_conversion_keeps_table_source_binding():
    catalog = _catalog()
    amount = _source(catalog, kind='table_column', column='金额')
    binding = catalog.resolve({'operation': 'value', 'left': [amount], 'rowLabel': '甲科',
        'evidence': ['甲科收入']}, '甲科收入。', display_unit='万元')
    assert binding is not None
    assert binding.view['value'] == pytest.approx(.006)
    assert binding.table_derivation.operands[0].coefficient == '0.0001'


def test_fact_quantity_preserves_explicit_display_unit_without_changing_source_value():
    catalog = _catalog()
    fact = _source(catalog, kind='fact', factId='fact-aaaaaaaaaaaaaaaa', selector='total')
    binding = catalog.resolve({'operation': 'value', 'left': [fact], 'evidence': ['收入合计']},
                              '收入合计0.01万元。', display_unit='万元')
    assert binding is not None
    assert binding.token == '{{value:fact-aaaaaaaaaaaaaaaa:total:万元}}'
    assert binding.view['value'] == 100
    assert binding.view['unit'] == '元'
    assert binding.display_text == '0.01万元'


def test_period_average_sources_include_registered_subwindows():
    catalog = _catalog()
    source = _source(catalog, kind='fact', factId='fact-aaaaaaaaaaaaaaaa', selector='periodAverages.0-0')
    binding = catalog.resolve({'operation': 'value', 'left': [source], 'evidence': ['一月月均收入']},
                              '一月月均收入40元。')
    assert binding is not None
    assert binding.view['value'] == 40
    assert binding.view['periods'] == ('2025-01',)


def test_repeated_quantity_evidence_is_grounded_at_current_claim_instead_of_global_uniqueness():
    catalog = _catalog()
    source = _source(catalog, kind='fact', factId='fact-aaaaaaaaaaaaaaaa', selector='total')
    quantity = {'operation': 'value', 'left': [source], 'evidence': ['收入合计100元']}
    context = '收入合计100元。另一段收入合计100元【当前数值引用】。'
    assert catalog.resolve(quantity, context) is not None
    assert catalog.resolve(quantity, '收入合计100元。收入合计100元。另项30元【当前数值引用】。') is None


@pytest.mark.anyio
async def test_section_quantity_disambiguation_keeps_the_registered_display_unit(monkeypatch):
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers
    from smart_reporting.reporting.workflow.runtime import sections

    frozen = _catalog().resolver._contents
    markdown, refs, _ = render_bound_numbers(
        '收入合计{{value:fact-aaaaaaaaaaaaaaaa:total:万元}}。', frozen, key='quantity-unit')
    block = ReportDraftBlock(blockId='b', markdown=markdown, numberReferences=refs)

    async def review(agent, schema, stage, payload, **kwargs):
        source = next(item['sourceId'] for item in payload['quantitySources']
                      if item.get('factId') == 'fact-aaaaaaaaaaaaaaaa' and item.get('selector') == 'total')
        return schema.model_validate({'interpretations': [{'claimId': refs[0].claim_id,
            'quantity': {'operation': 'value', 'left': [source], 'evidence': ['收入合计']}}]})

    monkeypatch.setattr(sections, '_run_section_stage', review)
    result = await sections._interpret_section_claims(object(), (block,), frozen, section_code='section_001',
        scope=SimpleNamespace(), run_context=SimpleNamespace(),
        thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'))
    assert result[0].markdown == '收入合计0.01万元。'
    assert result[0].number_references[0].token == '{{value:fact-aaaaaaaaaaaaaaaa:total:万元}}'


@pytest.mark.anyio
async def test_model_quantity_from_wrong_window_cannot_overwrite_correct_subwindow(monkeypatch):
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers
    from smart_reporting.reporting.workflow.runtime import sections

    frozen = _catalog().resolver._contents
    markdown, refs, _ = render_bound_numbers(
        '2025年1月月均收入{{value:fact-aaaaaaaaaaaaaaaa:periodAverages.0-0:元}}。', frozen, key='window')
    block = ReportDraftBlock(blockId='b', markdown=markdown, numberReferences=refs)

    async def review(agent, schema, stage, payload, **kwargs):
        source = next(item['sourceId'] for item in payload['quantitySources']
                      if item.get('factId') == 'fact-aaaaaaaaaaaaaaaa' and item.get('selector') == 'monthlyAverage')
        return schema.model_validate({'interpretations': [{'claimId': refs[0].claim_id,
            'periods': ['2025-01'], 'periodEvidence': ['2025年1月月均收入'], 'statistic': 'period_average',
            'quantity': {'operation': 'value', 'left': [source], 'evidence': ['2025年1月月均收入']}}]})

    monkeypatch.setattr(sections, '_run_section_stage', review)
    result = await sections._interpret_section_claims(object(), (block,), frozen, section_code='section_001',
        scope=SimpleNamespace(), run_context=SimpleNamespace(),
        thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'))
    assert result[0].markdown == '2025年1月月均收入40元。'
    assert result[0].number_references[0].token == refs[0].token
    assert result[0].number_references[0].semantic_receipt.quantity_binding_sha256 is None


def test_nonunique_excerpt_is_not_an_unambiguous_current_quantity():
    catalog = _catalog()
    total = _source(catalog, kind='fact', selector='total')
    assert catalog.resolve({'operation': 'value', 'left': [total], 'evidence': ['收入']},
                           '收入100元；另一主体收入100元。') is None


def test_complete_table_sum_cannot_turn_a_stock_snapshot_into_flow_population():
    catalog = _catalog()
    total = _source(catalog, kind='fact', selector='total')
    catalog._sources[total]['view']['entry']['periodAggregation'] = 'last'
    amount = _source(catalog, kind='table_column', column='金额')
    assert catalog.resolve({'operation': 'top_sum', 'left': [amount], 'limit': 2,
        'selection': 'items', 'evidence': ['前两项收入合计']}, '前两项收入合计90元。') is None


def test_internal_claim_locator_does_not_break_verbatim_quantity_evidence():
    catalog = _catalog()
    total = _source(catalog, kind='fact', selector='total')
    binding = catalog.resolve({'operation': 'value', 'left': [total],
        'evidence': ['与全院同范围合计60元一致']},
        '与全院同范围合计60元【当前数值引用】一致。')
    assert binding is not None and binding.view['value'] == 100


def test_locator_removal_does_not_hide_ambiguous_duplicate_evidence():
    catalog = _catalog()
    total = _source(catalog, kind='fact', selector='total')
    assert catalog.resolve({'operation': 'value', 'left': [total],
        'evidence': ['与全院合计60元一致']},
        '与全院合计60元【当前数值引用】一致；与全院合计60元一致。') is None


def test_mixed_row_amount_share_recomputes_exact_ratio_not_registered_rounding():
    fact = json.loads(contents()[0])
    fact['metrics'][0].update(total=300, periodValues=[{'period': '2025-01', 'value': 100},
                                                     {'period': '2025-02', 'value': 200}])
    fact_raw = json.dumps(fact).encode()
    table = {'periods': ['2025-01', '2025-02'], 'scope': {}, 'findings': [{
        'columns': ['科室', '金额'], 'columnMeta': {'金额': {'unit': '元'}}, 'rows': [['甲科', 100], ['乙科', 200]]}]}
    table_raw = json.dumps(table).encode()
    sources = {'trf-' + 'a' * 20: fact_raw, 'trf-' + 'b' * 20: table_raw}
    catalog = build_quantity_catalog([fact_raw.decode(), table_raw.decode()], sources)
    amount = _source(catalog, kind='table_column', column='金额')
    total = _source(catalog, kind='fact', selector='total')
    binding = catalog.resolve({'operation': 'share', 'left': [amount], 'right': [total],
        'rowLabel': '甲科', 'evidence': ['甲科占全院']}, '甲科占全院。')
    assert binding is not None
    assert binding.view['value'] == pytest.approx(100 / 3)
    assert binding.table_derivation.denominator_fact.file_resource_id == 'trf-' + 'a' * 20
    assert binding.display_text == '33.33%'


def test_mixed_share_does_not_inherit_missing_table_period_from_parent():
    fact_raw = contents()[0].encode()
    table_raw = json.dumps({'scope': {}, 'findings': [{'columns': ['科室', '金额'],
        'columnMeta': {'金额': {'unit': '元'}}, 'rows': [['甲科', 10], ['乙科', 20]]}]}).encode()
    catalog = build_quantity_catalog([fact_raw.decode(), table_raw.decode()],
        {'trf-' + 'a' * 20: fact_raw, 'trf-' + 'b' * 20: table_raw},
        table_contexts={'trf-' + 'b' * 20: {'scope': {}, 'periods': ['2025-01', '2025-02']}})
    source = _source(catalog, kind='table_column', column='金额')
    total = _source(catalog, kind='fact', selector='total')
    assert catalog.resolve({'operation': 'share', 'left': [source], 'right': [total],
        'rowLabel': '甲科', 'evidence': ['甲科占全院']}, '甲科占全院。') is None


def _proven_catalog(*, trusted=True, dated_months=False):
    import hashlib
    fact = json.loads(contents()[0])
    parent = fact['metrics'][0]
    parent.update(total=100, periodValues=[{'period': '2025-01', 'value': 40},
                                          {'period': '2025-02', 'value': 60}])
    members = ['丙科', '乙科', '甲科']
    proof = {'version': 'standard-population-v1', 'tablePointer': '/findings/0',
        'datasetId': parent['datasetId'], 'datasetSha256': parent['datasetSha256'],
        'populationFactId': parent['factId'], 'scope': {}, 'periods': ['2025-01', '2025-02'],
        'dimensionField': '科室', 'measureField': parent['field'], 'unit': '元',
        'members': members, 'memberCount': 3, 'invalidRowCount': 0,
        'membersSha256': hashlib.sha256(json.dumps(members, ensure_ascii=False,
            separators=(',', ':')).encode()).hexdigest(), 'completePopulation': True}
    if dated_months:
        proof['periods'] = ['2025-01-01', '2025-02-01']
    document = {'scope': {}, 'periods': proof['periods'], 'periodGranularity': 'month', 'findings': [{
        'columns': ['科室', 'value'], 'columnMeta': {'value': {'unit': '元'}},
        'rows': [['甲科', 60], ['乙科', 30], ['丙科', 10]], 'populationProof': proof}]}
    sources = {'trf-' + 'a' * 20: json.dumps(fact).encode(),
               'trf-' + 'b' * 20: json.dumps(document).encode()}
    return build_quantity_catalog([raw.decode() for raw in sources.values()], sources,
        table_contexts={'trf-' + 'b' * 20: {'/findings/0': proof}} if trusted else {})


@pytest.mark.parametrize('operation,expected', [('top_sum', 90), ('top_share', 90)])
def test_proven_top_set_persists_parent_and_reverifies_after_source_change(operation, expected):
    from smart_reporting.reporting.trace.table_sources import resolve_table_derivation
    catalog = _proven_catalog()
    amount = _source(catalog, kind='table_column', column='value')
    total = _source(catalog, kind='fact', selector='total')
    binding = catalog.resolve({'operation': operation, 'left': [amount],
        'right': [total] if operation == 'top_share' else [], 'limit': 2,
        'selection': 'items', 'evidence': ['前两项']}, '前两项。')
    assert binding is not None
    assert binding.view['value'] == expected
    assert binding.table_derivation.population_fact is not None
    changed = dict(catalog.sources)
    changed['trf-' + 'a' * 20] += b' '
    assert resolve_table_derivation(binding.token, binding.table_derivation, changed) is None
    wrong_selection = binding.table_derivation.model_copy(update={'top_limit': 1})
    assert resolve_table_derivation(binding.token, wrong_selection, catalog.sources) is None


def test_model_declared_population_proof_without_server_context_does_not_authorize_top_set():
    catalog = _proven_catalog(trusted=False)
    amount = _source(catalog, kind='table_column', column='value')
    assert catalog.resolve({'operation': 'top_sum', 'left': [amount], 'limit': 2,
        'selection': 'items', 'evidence': ['前两项']}, '前两项。') is None


def test_explicit_month_grain_normalizes_real_standard_date_labels():
    catalog = _proven_catalog(dated_months=True)
    amount = _source(catalog, kind='table_column', column='value')
    total = _source(catalog, kind='fact', selector='total')
    binding = catalog.resolve({'operation': 'top_share', 'left': [amount], 'right': [total],
        'limit': 2, 'selection': 'items', 'evidence': ['前两项']}, '前两项。')
    assert binding is not None
    assert binding.view['value'] == 90
    assert binding.view['periods'] == ('2025-01', '2025-02')


@pytest.mark.parametrize('field,value', [('members', ['假科']), ('memberCount', 2),
    ('datasetSha256', 'f' * 64), ('scope', {'院区': '另一院区'}), ('periods', ['2025-01'])])
def test_persisted_population_rejects_rehashed_false_metadata(field, value):
    from smart_reporting.reporting.trace.contracts_v1 import canonical_sha256
    from smart_reporting.reporting.trace.table_sources import table_derivation_token
    catalog = _proven_catalog()
    amount = _source(catalog, kind='table_column', column='value')
    binding = catalog.resolve({'operation': 'top_sum', 'left': [amount], 'limit': 2,
        'selection': 'items', 'evidence': ['前两项']}, '前两项。')
    sources = dict(catalog.sources)
    document = json.loads(sources['trf-' + 'b' * 20])
    proof = document['findings'][0]['populationProof']
    proof[field] = value
    sources['trf-' + 'b' * 20] = json.dumps(document).encode()
    changed = binding.table_derivation.model_copy(update={'population_proof_sha256': canonical_sha256(proof)})
    assert table_derivation_token(changed, sources) is None


def test_equivalent_parent_copies_across_analyses_bind_in_stable_order():
    original = _proven_catalog()
    sources = dict(original.sources)
    duplicate = json.loads(sources['trf-' + 'a' * 20])
    duplicate['analysisId'] = 'analysis_002'
    duplicate['metrics'][0].update(displayName='另一分析的同一父指标', aliases=['本地名称'])
    sources['trf-' + '0' * 20] = json.dumps(duplicate).encode()
    refs = []
    for ordered in (sources, dict(reversed(list(sources.items())))):
        catalog = build_quantity_catalog([raw.decode() for raw in ordered.values()], ordered,
                                         table_contexts=original._table_contexts)
        amount = _source(catalog, kind='table_column', column='value')
        total = _source(catalog, kind='fact', selector='total')
        binding = catalog.resolve({'operation': 'share', 'left': [amount], 'right': [total],
            'rowLabel': '甲科', 'evidence': ['甲科占全院']}, '甲科占全院。')
        assert binding is not None
        refs.append(binding.table_derivation.denominator_fact)
    assert refs[0] == refs[1]
    assert refs[0].file_resource_id == 'trf-' + '0' * 20


def test_conflicting_parent_copy_is_rejected_even_when_one_source_matches():
    original = _proven_catalog()
    sources = dict(original.sources)
    duplicate = json.loads(sources['trf-' + 'a' * 20])
    duplicate['analysisId'] = 'analysis_002'
    duplicate['metrics'][0]['total'] = 101
    sources['trf-' + '0' * 20] = json.dumps(duplicate).encode()
    # 内容解析仍用原冻结事实：不可因某个副本吻合就忽略同身份冲突来源。
    catalog = build_quantity_catalog([raw.decode() for raw in original.sources.values()], sources,
                                     table_contexts=original._table_contexts)
    amount = _source(catalog, kind='table_column', column='value')
    total = _source(catalog, kind='fact', selector='total')
    assert catalog.resolve({'operation': 'share', 'left': [amount], 'right': [total],
        'rowLabel': '甲科', 'evidence': ['甲科占全院']}, '甲科占全院。') is None


def test_equal_table_values_in_different_rows_have_different_quantity_fingerprints():
    from smart_reporting.reporting.trace.claim_semantics import quantity_binding_fingerprint
    catalog = _catalog(rows=[['甲科', 50, 50], ['乙科', 50, 50]])
    amount = _source(catalog, kind='table_column', column='金额')
    bindings = [catalog.resolve({'operation': 'value', 'left': [amount], 'rowLabel': label,
        'evidence': [label + '收入']}, label + '收入。') for label in ('甲科', '乙科')]
    assert bindings[0].view['value'] == bindings[1].view['value']
    assert quantity_binding_fingerprint(bindings[0].view) != quantity_binding_fingerprint(bindings[1].view)
