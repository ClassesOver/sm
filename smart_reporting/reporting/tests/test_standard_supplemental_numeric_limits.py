"""有限浮点输入的独立极限样本，不放宽生产容差。"""
import json
from decimal import Decimal

import pytest

from smart_reporting.reporting.tests.test_standard_supplemental_independent import (
    HEADER,
    _run,
    _table,
)


@pytest.mark.parametrize('amounts,expected', [
    (['10000000000000000', '1', '-10000000000000000'], '1'),
    (['1e300', '-1e300', '2'], '2'),
    (['1e-300', '2e-300'], '3e-300'),
])
def test_large_small_and_cancellation_group_sums(amounts, expected):
    # 精确期望使用足够精度的 Decimal，不能让默认28位截掉极大数后的2。
    from decimal import localcontext

    with localcontext() as context:
        context.prec = 650
        assert sum(map(Decimal, amounts)) == Decimal(expected)
    _, payload = _run(HEADER + ''.join(f'2025-01,A,{value}\n' for value in amounts),
                      total=float(expected))
    row, = _table(payload)
    assert row['value'] == float(expected)
    assert row['share'] == 1
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize('numerator,denominator,ratio,difference', [
    ('1e-300', '1e-300', 1, 0),
    ('1e308', '1e-308', None, 1e308),
    ('1e308', '-1e308', -1, None),
])
def test_unrepresentable_derived_ratio_or_difference_keeps_finite_operands(
    numerator, denominator, ratio, difference,
):
    _, payload = _run(f'period,department,amount,budget\n2025-01,A,{numerator},{denominator}\n',
        'group_ratio', total=float(numerator), denominatorField='budget',
        denominatorParentTotal=float(denominator), denominatorScale=1, ratioFactId='ratio')
    row, = _table(payload)
    assert row['numerator'] == float(numerator)
    assert row['denominator'] == float(denominator)
    assert row['difference'] == difference
    assert row['ratio'] == ratio
    if ratio is None or difference is None:
        assert payload['warnings']
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize('denominator', ['1e308', '-1e308'])
def test_overflowed_scaled_denominator_cannot_authorize_a_finite_zero_ratio(denominator):
    _, payload = _run(f'period,department,amount,budget\n2025-01,A,1e308,{denominator}\n',
        'group_ratio', total=1e308, denominatorField='budget',
        denominatorParentTotal=float(denominator), denominatorScale=10000, ratioFactId='ratio')
    row, = _table(payload)
    assert row['numerator'] == 1e308
    assert row['denominator'] is None
    assert row['difference'] is None
    assert row['ratio'] is None
    assert payload['warnings']
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize('value', ['NaN', 'inf', '-inf', '1e999'])
def test_nonfinite_source_values_warn_and_are_not_serialized(value):
    _, payload = _run(HEADER + f'2025-01,A,100\n2025-01,B,{value}\n')
    assert _table(payload)[0]['value'] == 100
    assert payload['warnings']
    assert payload['findings'][0]['issues'][0]['code'] == 'invalid_numeric'
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize('operation', ['group_summary', 'group_period_series',
                                      'cross_group_summary', 'group_concentration'])
def test_tiny_cancelled_total_cannot_emit_infinite_shares(operation):
    content = ('period,department,site,amount\n2025-01,A,X,1e308\n'
               '2025-01,B,X,-1e308\n2025-01,C,X,1e-308\n'
               '2025-01,D,X,0\n2025-01,E,X,0\n2025-01,F,X,0\n')
    options = {'secondaryDimensionField': 'site', 'includeMarginalShares': True} if (
        operation == 'cross_group_summary') else {'parentPeriodTotals': [1e-308]} if (
        operation == 'group_period_series') else {}
    _, payload = _run(content, operation, total=1e-308, **options)
    assert payload['warnings']
    json.dumps(payload, allow_nan=False)
    if operation in {'group_summary', 'group_period_series', 'cross_group_summary'}:
        row = _table(payload)[0]
        assert row['value'] == 1e308
        assert row['share'] is None
    else:
        assert _table(payload)[0]['cr5'] is None
