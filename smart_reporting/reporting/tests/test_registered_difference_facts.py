"""Registered differences require their exact reference, not reconstructable operands."""

import json
from decimal import Decimal

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
)
from smart_reporting.reporting.trace.content_review import review_content
from smart_reporting.reporting.trace.numeric_text import (
    derived_number_values,
    format_fact_value,
    frozen_number_catalog,
    replace_unregistered_numbers,
)
from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers

FACT_ID = 'fact-' + 'a' * 16


def reconciliation_only(difference):
    # No metric facts, inputFactIds, or supplemental table operands are available.
    document = {'analysisId': 'analysis_001', 'reconciliations': [{
        'factId': FACT_ID, 'code': 'ledger_check', 'periodRole': 'current',
        'leftMetric': 'actual', 'rightMetric': 'ledger', 'grain': ['month'],
        'leftTotal': 100000 + difference, 'rightTotal': 100000,
        'unit': '元', 'difference': difference,
        'absoluteTolerance': 0, 'relativeTolerance': 0,
        'checkedGroupCount': 1, 'failedGroupCount': int(difference != 0),
        'passed': difference == 0, 'formula': 'actual-ledger',
        'datasetIds': ['current'], 'datasetSha256s': ['b' * 64],
    }]}
    return DeterministicAnalysisBundle.model_validate(document).model_dump_json(by_alias=True)


@pytest.mark.parametrize('difference', [0, 60000, -60000])
@pytest.mark.parametrize('unit', ['元', '万元'])
@pytest.mark.parametrize('word', ['对账差额为', '对账两端相差', '对账差距约'])
def test_registered_difference_without_operands_requires_exact_reference(difference, unit, word):
    contents = [reconciliation_only(difference)]
    number = Decimal(difference) / (10000 if unit == '万元' else 1)
    quantum = Decimal('0.01') if unit == '万元' else Decimal(1)
    assert not derived_number_values(contents).supports(number, unit, quantum, word)

    # A bare equal value has lost its identity and cannot borrow this difference.
    for value in {difference, abs(difference)}:
        text = word + format_fact_value(value, '元', unit) + '。'
        assert replace_unregistered_numbers(text, contents) == word + '待核实。'
        assert any('冻结依据' in warning for warning in review_content(text, contents))

    # The signed registered difference remains usable without rebuilding operands.
    token = '{{value:' + FACT_ID + ':difference:' + unit + '}}'
    source = word + token + '。'
    rendered, references, notices = render_bound_numbers(source, contents, key='without-operands')
    assert rendered == word + format_fact_value(difference, '元', unit) + '。'
    assert len(references) == 1 and references[0].token == token
    assert not notices
    assert not any('冻结依据' in warning for warning in review_content(source, contents))


@pytest.mark.parametrize('difference', [0, 60000, -60000])
@pytest.mark.parametrize('unit', ['元', '万元'])
def test_registered_difference_reference_survives_bound_rendering(difference, unit):
    contents = [reconciliation_only(difference)]
    token = '{{value:' + FACT_ID + ':difference:' + unit + '}}'
    expected = '对账差额为' + format_fact_value(difference, '元', unit) + '。'
    source = '对账差额为' + token + '。'
    text, references, notices = render_bound_numbers(
        source, contents, key='registered-difference',
    )
    assert text == expected
    assert len(references) == 1 and references[0].token == token
    assert not notices
    # Generic review receives the token-bearing source; editor validation uses the index.
    assert not any('冻结依据' in warning for warning in review_content(source, contents))


@pytest.mark.parametrize('text', ['对账差额为61,000元。', '对账差距约6.00%。'])
def test_unmatched_difference_still_requires_operands(text):
    contents = [reconciliation_only(60000)]
    assert '待核实' in replace_unregistered_numbers(text, contents)
    assert any('冻结依据' in warning for warning in review_content(text, contents))


def test_conflicting_registered_difference_cannot_bypass_derivation():
    contents = [reconciliation_only(60000), reconciliation_only(61000)]
    token = '{{value:' + FACT_ID + ':difference:元}}'
    assert frozen_number_catalog(contents)[token] == '数值待核实'
    text = '对账差额为60,000元。'
    assert replace_unregistered_numbers(text, contents) == '对账差额为待核实。'
    assert any('冻结依据' in warning for warning in review_content(text, contents))


def test_unidentified_difference_cannot_bypass_derivation():
    document = json.loads(reconciliation_only(60000))
    document['reconciliations'][0].pop('factId')
    contents = [json.dumps(document)]
    assert not frozen_number_catalog(contents)
    # Keep a valid ordinary amount so the numeric verifier has a catalog to check.
    contents.append(json.dumps({'findings': [{
        'columns': ['金额'], 'columnMeta': {'金额': {'unit': '元'}}, 'rows': [[60000]],
    }]}))
    text = '对账差额为60,000元。'
    assert replace_unregistered_numbers(text, contents) == '对账差额为待核实。'
    assert any('冻结依据' in warning for warning in review_content(text, contents))
