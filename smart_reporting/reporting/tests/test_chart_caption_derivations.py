"""图注按同一冻结贡献表重算，不因模型手写正确派生值而遗留占位。"""

import json
from decimal import Decimal

import pytest

from smart_reporting.reporting.trace.numeric_text import replace_unregistered_numbers
from smart_reporting.reporting.workflow.runtime.sections import _verified_caption


def _contents():
    return (json.dumps({
        'schema': 'chart-input/v1',
        'columns': ['indicator_name', 'current', 'baseline', 'change', 'changeRate', 'contribution'],
        'columnMeta': {
            'current': {'unit': '元'}, 'baseline': {'unit': '元'}, 'change': {'unit': '元'},
            'changeRate': {'unit': '%', 'isPercent': False},
            'contribution': {'unit': '%', 'isPercent': False},
        },
        'rows': [
            ['卫生材料收入', 730000, 1000000, -270000, -0.27, 0.675],
            ['检验收入', 910000, 1000000, -90000, -0.09, 0.225],
            ['检查收入', 920000, 1000000, -80000, -0.08, 0.2],
            ['药品收入', 1040000, 1000000, 40000, 0.04, -0.1],
        ],
    }, ensure_ascii=False),)

@pytest.mark.parametrize('verb', ['减少', '减收'])
def test_caption_recomputes_signed_sum_and_net_contribution(verb):
    text = f'卫生材料、检验、检查三类合计{verb}44.00万元，占全院同比减收额的110.0%'
    assert _verified_caption(text, _contents()) == text


@pytest.mark.parametrize('text', [
    '卫生材料、检验、检查三类合计增加44.00万元',
    '卫生材料、检验、药品三类合计减少44.00万元',
    '卫生材料、检验、检查、药品四类合计减少44.00万元',
    '卫生材料、检验、检查三类合计减少45.00万元',
    '卫生材料、检验、检查三类合计减少44.00万元，占全院收入的110.0%',
    '卫生材料、检验、检查三类合计减少44.00万元，同比下降110.0%',
])
def test_caption_derivation_does_not_approve_wrong_operands_or_meaning(text):
    assert '待核实' in replace_unregistered_numbers(text, _contents())


def test_caption_contribution_rejects_inconsistent_registered_denominator():
    document = json.loads(_contents()[0])
    document['rows'][0][-1] = 0.7
    text = '卫生材料、检验、检查三类合计减少44.00万元，占全院同比减收额的110.0%'
    assert '110.0%' not in _verified_caption(text, (json.dumps(document),))


@pytest.mark.parametrize(('number', 'unit', 'text'), [
    ('44.00', '万元', '卫生材料、检验、检查三类合计减少44.00万元'),
    ('110.0', '%', '卫生材料、检验、检查三类合计减少44.00万元，占全院同比减收额的110.0%'),
])
def test_caption_derivations_recompute_from_identified_source_cells(number, unit, text):
    from smart_reporting.reporting.trace.numeric_text import derived_number_values
    from smart_reporting.reporting.trace.table_sources import resolve_table_derivation

    contents = _contents()
    sources = {'trf-' + '1' * 20: contents[0].encode()}
    derived = derived_number_values(contents, table_sources=sources)
    entry = derived.match(Decimal(number), unit,
                          Decimal(1).scaleb(Decimal(number).as_tuple().exponent),
                          text, statement=text, claim=text)
    assert entry is not None and entry.table_derivation is not None
    resolved = resolve_table_derivation(entry.table_token, entry.table_derivation, sources)
    assert resolved is not None
    assert Decimal(str(resolved['value'])).quantize(Decimal('0.01')) == Decimal(number)


def test_unverifiable_caption_returns_readable_fallback_with_warning():
    warnings = []
    rendered = _verified_caption(
        '卫生材料、检验、检查三类合计减少999.00万元，占全院收入的99.9%',
        _contents(), warnings=warnings, chart_id='chart_001',
    )
    assert '待核实' not in rendered and '999' not in rendered and '99.9' not in rendered
    assert rendered
    assert warnings[0]['code'] == 'chart_caption_numeric_review'
    assert warnings[0]['chartId'] == 'chart_001'


def test_partly_verified_caption_keeps_supported_clause_and_discloses_removal():
    warnings = []
    rendered = _verified_caption(
        '卫生材料、检验、检查三类合计减少44.00万元，占全院收入的110.0%',
        _contents(), warnings=warnings, chart_id='chart_001',
    )
    assert rendered == '卫生材料、检验、检查三类合计减少44.00万元'
    assert warnings[0]['code'] == 'chart_caption_numeric_review'


@pytest.mark.parametrize('mutation', ['truncated', 'duplicate', 'missing', 'zero_net'])
def test_unproven_contribution_population_is_not_used(mutation):
    document = json.loads(_contents()[0])
    if mutation == 'truncated':
        document['rows'].pop()
    elif mutation == 'duplicate':
        document['rows'][-1][0] = '卫生材料收入'
    elif mutation == 'missing':
        document['rows'][0][3] = None
    else:
        document['rows'][-1][1:4] = [1440000, 1000000, 440000]
    text = '卫生材料、检验、检查三类合计减少44.00万元，占全院同比减收额的110.0%'
    rendered = replace_unregistered_numbers(text, (json.dumps(document),))
    assert '110.0%' not in rendered
