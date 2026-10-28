"""缺失归属占比必须来自同范围绝对金额，不得借用院区占比或告警文字。"""

import hashlib
import json

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.fact_index import metric_fact_identity
from smart_reporting.reporting.trace.numeric_text import frozen_number_catalog, frozen_number_guide
from smart_reporting.reporting.trace.semantic_bindings import (
    reference_computation,
    resolve_number_references,
)
from smart_reporting.reporting.trace.semantic_quantity import QuantityCatalog

from .test_deterministic_analysis import analysis, context, semantic


def _bundle(rows, *, stock=False):
    raw = ('month,campus,department,amount\n' + rows).encode()
    measure = semantic('amount', scope={'campus': '北院'}, unit='元')
    if stock:
        measure['additiveAcross'] = ['department']
    ctx = context('current', fields=('month', 'campus', 'department', 'amount'),
                  semantics=(measure,), sha256=hashlib.sha256(raw).hexdigest()).model_copy(
                      update={'period_granularities': {'month': 'month'}})
    return build_deterministic_analysis_bundle(
        analysis(), (('current', raw, ctx, ('current',)),), profile_hash='a' * 64)


def test_missing_share_uses_scoped_absolute_amounts_and_preserves_source_roles():
    bundle = _bundle('2025-01,北院,,60\n2025-01,北院,  ,-30\n'
                     '2025-01,北院,甲科,30\n2025-01,南院,,900\n')
    fact = bundle.metrics[0]
    assert fact.total == 60
    token = '{{value:' + fact.fact_id + ':groupMissingShares.department:%}}'
    content = bundle.model_dump_json(by_alias=True)
    view = resolve_number_references([token], [content])[token]

    assert view is not None
    assert view['value'] == 75
    assert view['scope'] == {'campus': '北院'}
    assert view['periods'] == ('2025-01',)
    assert view['formula'] == '(90) / (120) * 100'
    assert '归属缺失' in view['explanation']
    assert '90元' in view['explanation'] and '120元' in view['explanation']
    assert reference_computation(token, view['selector'], entry=view['entry']) == 'derived'
    assert fact.group_missingness['department'].missing_row_count == 2
    guide = frozen_number_guide([content], frozen_number_catalog([content]), field_definitions={'department': '科室'})
    assert token in json.dumps(guide, ensure_ascii=False)
    catalog = QuantityCatalog([content], {}, field_definitions={'department': '科室'})
    source = next(item for item in catalog.prompt if item.get('selector') == 'groupMissingShares.department')
    assert source['groupingField'] == 'department'
    assert source['groupingLabel'] == '科室'
    assert source['quantityRole'] == 'group_missing_absolute_share'
    binding = catalog.resolve({'operation': 'value', 'left': [source['sourceId']],
                               'evidence': ['科室归属缺失金额占比']},
                              '科室归属缺失金额占比2.64%。', display_unit='%')
    assert binding is not None and binding.display_text == '75.00%'
    assert binding.token == token


def test_stock_missing_share_covers_only_latest_registered_period():
    bundle = _bundle('2025-01,北院,,900\n2025-02,北院,,10\n2025-02,北院,甲科,30\n', stock=True)
    fact = bundle.metrics[0]
    token = '{{value:' + fact.fact_id + ':groupMissingShares.department:%}}'
    view = resolve_number_references([token], [bundle.model_dump_json(by_alias=True)])[token]

    assert view is not None and view['value'] == 25
    assert view['periods'] == ('2025-02',)
    series_token = '{{value:' + fact.fact_id + ':seriesGroupMissingShares.department:%}}'
    series = resolve_number_references([series_token], [bundle.model_dump_json(by_alias=True)])[series_token]
    assert series is not None
    assert series['value'] == pytest.approx(910 / 940 * 100)
    assert series['periods'] == ('2025-01', '2025-02')
    catalog = QuantityCatalog([bundle.model_dump_json(by_alias=True)], {})
    assert any(item.get('selector') == 'seriesGroupMissingShares.department' for item in catalog.prompt)


@pytest.mark.parametrize('rows', [
    '2025-01,北院,,0\n2025-01,北院,甲科,0\n',
    '2025-01,北院,,10\n2025-01,北院,甲科,\n',
    '2025-01,北院,,10\n2025-01,北院,甲科,NaN\n',
])
def test_zero_or_incomplete_amounts_do_not_register_missing_share(rows):
    bundle = _bundle(rows)
    catalog = QuantityCatalog([bundle.model_dump_json(by_alias=True)], {})
    assert not any(item.get('selector', '').startswith('groupMissingShares.') for item in catalog.prompt)


@pytest.mark.parametrize('period', ['', '   ', 'not-a-date'])
def test_rows_without_valid_period_cannot_be_registered_as_known_period_missing_share(period):
    bundle = _bundle('2025-01,北院,,10\n' + period + ',北院,甲科,30\n')
    catalog = QuantityCatalog([bundle.model_dump_json(by_alias=True)], {})
    assert not any(item.get('selector', '').startswith('groupMissingShares.') for item in catalog.prompt)


def test_breakdown_does_not_inherit_parent_missingness_statistics():
    from .test_dimension_breakdowns import _bundle as dimension_bundle

    bundle = dimension_bundle(
        'month,department,income_type,amount\n2025-01,,住院,10\n2025-01,A,门诊,30\n')
    assert bundle.metrics[0].group_missingness
    assert bundle.breakdowns
    assert all(not fact.group_missingness for fact in bundle.breakdowns)
    assert all(not fact.series_group_missingness for fact in bundle.breakdowns)


def test_legacy_warning_text_cannot_be_used_as_missing_share_source():
    bundle = _bundle('2025-01,北院,,10\n2025-01,北院,甲科,30\n')
    document = json.loads(bundle.model_dump_json(by_alias=True))
    document['metrics'][0].pop('groupMissingness', None)
    content = json.dumps(document)
    token = '{{value:' + bundle.metrics[0].fact_id + ':groupMissingShares.department:%}}'

    assert resolve_number_references([token], [content])[token] is None


def test_missingness_exact_operands_participate_in_fact_identity():
    first = _bundle('2025-01,北院,,10\n2025-01,北院,甲科,30\n').metrics[0]
    second = _bundle('2025-01,北院,,10.00001\n2025-01,北院,甲科,29.99999\n').metrics[0]
    # 固定其他旧身份字段，模拟显示告警均舍入到25.00%的两个不同精确操作数。
    changed = first.model_copy(update={'group_missingness': second.group_missingness})
    assert metric_fact_identity(changed) != metric_fact_identity(first)


@pytest.mark.anyio
@pytest.mark.parametrize('series', [False, True])
@pytest.mark.parametrize('period_proof', [True, False])
async def test_semantic_review_rebinds_wrong_share_to_missingness_with_verified_receipt(monkeypatch, series, period_proof):
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.trace.semantic_bindings import (
        anchor_bound_numbers,
        render_bound_numbers,
    )
    from smart_reporting.reporting.trace.subject_builder import prepare_claim_status
    from smart_reporting.reporting.workflow.runtime import sections
    from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview

    bundle = (_bundle('2025-01,北院,,900\n2025-02,北院,,10\n2025-02,北院,甲科,30\n', stock=True)
              if series else _bundle('2025-01,北院,,60\n2025-01,北院,  ,-30\n2025-01,北院,甲科,30\n'))
    selector = 'seriesGroupMissingShares.department' if series else 'groupMissingShares.department'
    period_text = '2025年1—2月' if series else '2025年1月'
    periods = ['2025-01', '2025-02'] if series else ['2025-01']
    frozen = [bundle.model_dump_json(by_alias=True)]
    fact_id = bundle.metrics[0].fact_id
    original = '{{calc:ratio(' + fact_id + ':total,' + fact_id + ':total):%}}'
    markdown, refs, notices = render_bound_numbers(
        period_text + '北院科室归属缺失的金额绝对值占比为' + original + '。', frozen, key='missing-share')
    blocks = (ReportDraftBlock(blockId='b', markdown=markdown, numberReferences=refs, reviewNotices=notices),)

    async def review(agent, schema, stage, payload, **kwargs):
        source = next(item for item in payload['quantitySources']
                      if item.get('selector') == selector)
        assert source['groupingLabel'] == '科室'
        return SectionSemanticReview.model_validate({'interpretations': [{
            'claimId': refs[0].claim_id, 'scope': [], 'periods': periods if period_proof else [],
            'periodEvidence': [period_text] if period_proof else [],
            'quantity': {'operation': 'value', 'left': [source['sourceId']],
                         'evidence': ['科室归属缺失的金额绝对值占比']},
        }]})

    monkeypatch.setattr(sections, '_run_section_stage', review)
    reviewed = await sections._disambiguate_section_claims(
        object(), blocks, frozen, section_code='s', scope=SimpleNamespace(), run_context=SimpleNamespace(),
        thinking_request=ThinkingRequest(operation='section_generation', complexity='standard'),
        field_definitions={'department': '科室'})
    block = reviewed[-1]
    number = block.number_references[0]
    if not period_proof:
        assert '100.00%' in block.markdown
        assert number.token == original
        assert not number.semantic_receipt.quantity_binding_sha256
        return
    assert ('96.81%' if series else '75.00%') in block.markdown and '100.00%' not in block.markdown
    assert number.token == '{{value:' + fact_id + ':' + selector + ':%}}'
    assert number.semantic_receipt.quantity_binding_sha256
    view = resolve_number_references([number.token], frozen)[number.token]
    anchored = anchor_bound_numbers(block.markdown, block.number_references)
    detail = prepare_claim_status(anchored)(
        number.claim_id, view['value'], expected_unit=view['unit'], expected_scope=view['scope'],
        expected_periods=view['periods'], expected_reference=view, semantic_receipt=number.semantic_receipt)
    assert detail['status'] == 'valid' and not detail.get('warnings')
