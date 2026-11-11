"""预期值须明确单位、状态和比较精度，不能只声明case通过。"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.semantics.issue_regression import RegressionAssertion
from smart_reporting.reporting.semantics.models import MetricResult


def result(value=Decimal(190) / Decimal(300) * 100, **changes):
    return MetricResult.model_validate({'metricVersion': {'metricId': 'rate', 'revision': 2}, 'basisId': 'fixed-basis',
        'calculationId': 'fixed-calculation', 'factId': 'fact-rate', 'period': {'start': '2026-01-01', 'end': '2026-02-01'},
        'value': value, 'unit': '%', 'status': 'computed', 'datasetIds': ['actual', 'budget'], **changes})


def test_regression_decimal_comparison_uses_explicit_precision_and_preserves_large_values():
    check = RegressionAssertion(factId='fact-rate', expectedStatus='computed', expectedValue='63.33', unit='%', decimalPlaces=2)
    assert check.matches(result())
    assert not check.matches(result(Decimal(70)))
    assert not check.matches(result(unit='CNY'))
    large = '12345678901234567890123456789012345678.12'
    amount = RegressionAssertion(factId='fact-rate', expectedStatus='computed', expectedValue=large, unit='CNY', decimalPlaces=2)
    assert amount.matches(result(Decimal(large), unit='CNY'))


@pytest.mark.parametrize('changes', [
    {'expectedValue': 'NaN'}, {'expectedValue': 'Infinity'},
    {'expectedValue': '63.334', 'decimalPlaces': 2},
    {'expectedStatus': 'unavailable', 'expectedValue': None},
    {'expectedStatus': 'unavailable', 'expectedValue': '0', 'expectedIssueCodes': ['zero_denominator']},
])
def test_invalid_expectations_never_become_passing_receipts(changes):
    with pytest.raises(ValidationError):
        RegressionAssertion.model_validate({'factId': 'fact-rate', 'expectedStatus': 'computed',
            'expectedValue': '63.33', 'unit': '%', **changes})


def test_expected_unavailable_requires_specific_issue_but_keeps_soft_warnings():
    check = RegressionAssertion(factId='fact-rate', expectedStatus='unavailable', unit='%', expectedIssueCodes=['zero_denominator'])
    assert check.matches(result(None, status='unavailable', issueCodes=['zero_denominator', 'data_readiness_unknown']))
    assert not check.matches(result(None, status='unavailable', issueCodes=['missing_data']))
