"""数量语义复核使用逐操作数身份，不能把算术有效当作业务角色一致。"""

import pytest

from smart_reporting.reporting.tests.test_semantic_bindings import contents
from smart_reporting.reporting.trace.semantic_bindings import NumberReferenceResolver


def test_calc_semantic_view_keeps_each_operand_selector_and_tree_position():
    resolver = NumberReferenceResolver(contents())
    token = ('{{calc:diff(sum(fact-aaaaaaaaaaaaaaaa:periodValues.0,'
             'fact-aaaaaaaaaaaaaaaa:periodValues.1),fact-bbbbbbbbbbbbbbbb:total):元}}')
    result = resolver.resolve(token)
    assert result['expressionTree'] == ('diff', [
        ('sum', [('ref', 'fact-aaaaaaaaaaaaaaaa', 'periodValues.0'),
                 ('ref', 'fact-aaaaaaaaaaaaaaaa', 'periodValues.1')]),
        ('ref', 'fact-bbbbbbbbbbbbbbbb', 'total'),
    ])
    assert [operand['selector'] for operand in result['operandViews']] == [
        'periodValues.0', 'periodValues.1', 'total',
    ]
    assert result['operandViews'][0]['periods'] == ('2025-01',)
    assert result['operandViews'][2]['periods'] == ('2025-01', '2025-02')


async def _review_ratio(monkeypatch, *, invalid_quantity=False, altered_display=False, whole_statement_evidence=False):
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers
    from smart_reporting.reporting.workflow.runtime import sections
    from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview

    frozen = contents()
    original = '{{calc:ratio(fact-bbbbbbbbbbbbbbbb:total,fact-aaaaaaaaaaaaaaaa:total):%}}'
    markdown, refs, notices = render_bound_numbers(
        '2025年1—2月设备实际金额占预算金额' + original + '。', frozen, key='quantity-role',
    )
    if altered_display:
        markdown = markdown.replace('400.00%', '999.00%')
    blocks = (ReportDraftBlock(blockId='b', markdown=markdown, numberReferences=refs, reviewNotices=notices),)

    async def review(agent, schema, stage, payload, **kwargs):
        assert 'quantitySources' in payload
        assert payload['references'][0]['operandViews'][0]['factId'] == 'fact-bbbbbbbbbbbbbbbb'
        assert payload['references'][0]['expressionTree'][0] == 'ratio'
        assert all('value' not in source for source in payload['quantitySources'])
        sources = {source['factId']: source['sourceId'] for source in payload['quantitySources']
                   if source.get('selector') == 'total'}
        return SectionSemanticReview.model_validate({'interpretations': [{
            'claimId': refs[0].claim_id, 'scope': [],
            'quantity': {'operation': 'share', 'left': ['unknown'] if invalid_quantity else [sources['fact-aaaaaaaaaaaaaaaa']],
                         'right': [sources['fact-bbbbbbbbbbbbbbbb']],
                         'evidence': [markdown if whole_statement_evidence else '设备实际金额占预算金额']},
        }]})

    monkeypatch.setattr(sections, '_run_section_stage', review)
    result = await sections._disambiguate_section_claims(
        object(), blocks, frozen, section_code='s', scope=SimpleNamespace(), run_context=SimpleNamespace(),
        thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'),
    )
    return result[0], refs[0], markdown, frozen




@pytest.mark.anyio
async def test_semantic_quantity_corrects_reversed_operands_without_model_amount(monkeypatch):
    from smart_reporting.reporting.trace.claim_semantics import semantic_warnings
    from smart_reporting.reporting.trace.semantic_bindings import (
        anchor_bound_numbers,
        resolve_number_reference,
    )

    block, original, markdown, frozen = await _review_ratio(monkeypatch)
    number = block.number_references[0]
    assert number.token == '{{calc:ratio(fact-aaaaaaaaaaaaaaaa:total,fact-bbbbbbbbbbbbbbbb:total):%}}'
    assert block.markdown != markdown and '25.00%' in block.markdown
    assert number.semantic_receipt.quantity_binding_sha256
    selected = resolve_number_reference(number.token, frozen)
    anchored = anchor_bound_numbers(block.markdown, block.number_references)
    assert not any('数量关系' in warning for warning in semantic_warnings(
        anchored, number.claim_id, number.semantic_receipt, {}, selected['periods'], [], reference=selected,
    ))
    wrong = resolve_number_reference(original.token, frozen)
    assert any('数量关系' in warning for warning in semantic_warnings(
        anchored, number.claim_id, number.semantic_receipt, {}, wrong['periods'], [], reference=wrong,
    ))


@pytest.mark.anyio
async def test_unresolvable_semantic_quantity_retains_original_and_warns(monkeypatch):
    from smart_reporting.reporting.trace.claim_semantics import semantic_warnings
    from smart_reporting.reporting.trace.semantic_bindings import (
        anchor_bound_numbers,
        resolve_number_reference,
    )

    block, original, markdown, frozen = await _review_ratio(monkeypatch, invalid_quantity=True)
    number = block.number_references[0]
    assert number.token == original.token and block.markdown == markdown
    selected = resolve_number_reference(number.token, frozen)
    anchored = anchor_bound_numbers(block.markdown, block.number_references)
    assert any('数量关系' in warning for warning in semantic_warnings(
        anchored, number.claim_id, number.semantic_receipt, {}, selected['periods'], [], reference=selected,
    ))


@pytest.mark.anyio
async def test_quantity_receipt_never_attests_binding_when_original_number_failed_verification(monkeypatch):
    block, original, markdown, _frozen = await _review_ratio(monkeypatch, altered_display=True)
    number = block.number_references[0]
    assert number.token == original.token and block.markdown == markdown
    assert number.semantic_receipt is not None
    assert number.semantic_receipt.quantity_binding_sha256 is None


@pytest.mark.anyio
async def test_existing_table_derivation_is_semantically_reviewed_against_verified_sources(monkeypatch):
    import json
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.trace.contracts_v1 import NumberReferenceV1, TableDerivationV1
    from smart_reporting.reporting.trace.semantic_bindings import (
        statement_fingerprint,
        strip_bound_anchors,
    )
    from smart_reporting.reporting.trace.table_sources import table_derivation_token
    from smart_reporting.reporting.workflow.runtime import sections
    from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview

    raw = json.dumps({'findings': [{'columns': ['科室', '占比'],
        'columnMeta': {'占比': {'unit': '%', 'isPercent': True}},
        'rows': [['甲科', 60], ['乙科', 40]]}]}, ensure_ascii=False).encode()
    sources = {'trf-' + 'a' * 20: raw}
    derivation = TableDerivationV1(operands=[{'fileResourceId': next(iter(sources)),
        'tablePointer': '/findings/0', 'rowIndex': 1, 'columnIndex': 1, 'coefficient': '1'}], unit='%')
    token = table_derivation_token(derivation, sources)
    anchored = '甲科占全院收入40.00%[[claim:cell]]。'
    reference = NumberReferenceV1(claimId='cell', token=token, displayText='40.00%',
        statementSha256=statement_fingerprint(anchored, 'cell'), tableDerivation=derivation)
    markdown, refs, notices = strip_bound_anchors(anchored, (reference,), ())
    block = ReportDraftBlock(blockId='b', markdown=markdown, numberReferences=refs, reviewNotices=notices)

    async def review(agent, schema, stage, payload, **kwargs):
        source = next(item['sourceId'] for item in payload['quantitySources'] if item.get('column') == '占比')
        assert payload['references'][0]['selector'] == 'tableDerived'
        return SectionSemanticReview.model_validate({'interpretations': [{'claimId': 'cell',
            'quantity': {'operation': 'value', 'left': [source], 'rowLabel': '甲科',
                         'evidence': ['甲科占全院收入']}}]})

    monkeypatch.setattr(sections, '_run_section_stage', review)
    result = await sections._disambiguate_section_claims(object(), (block,), [raw.decode()],
        table_sources=sources, section_code='s', scope=SimpleNamespace(), run_context=SimpleNamespace(),
        thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'))
    assert result[0].markdown == '甲科占全院收入60.00%。'
    corrected = result[0].number_references[0]
    assert corrected.table_derivation.operands[0].row_index == 0
    assert corrected.semantic_receipt.quantity_binding_sha256


@pytest.mark.anyio
async def test_quantity_correction_accepts_original_excerpt_across_internal_locator(monkeypatch):
    block, _original, _markdown, _frozen = await _review_ratio(monkeypatch, whole_statement_evidence=True)
    assert '25.00%' in block.markdown
    assert block.number_references[0].semantic_receipt.quantity_binding_sha256
