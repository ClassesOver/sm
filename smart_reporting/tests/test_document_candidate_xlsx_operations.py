import math

import pytest

from smart_reporting.document_candidate_xlsx_operations import validate_xlsx_operations


_SELECTION = ({"sheet": "Sheet1", "range": "A1"},)


@pytest.mark.parametrize("value", ["hello", 123, 3.5, True, ""])
def test_safe_literal_xlsx_operation(value):
    validate_xlsx_operations(
        _SELECTION, ({"sheet": "Sheet1", "range": "A1", "value": value},)
    )


@pytest.mark.parametrize("value", [
    "=SUM(B1:B2)", " =1+1", "+cmd", "-1+2", "@SUM(A1)", "\t=1+1",
    "hello\nworld", math.inf, -math.inf, math.nan, None, [],
])
def test_formula_and_unsafe_xlsx_values_rejected(value):
    with pytest.raises(ValueError, match="xlsx_formula_or_value_unsafe|xlsx_value_non_finite"):
        validate_xlsx_operations(
            _SELECTION, ({"sheet": "Sheet1", "range": "A1", "value": value},)
        )


def test_xlsx_operation_cannot_target_unapproved_cell():
    with pytest.raises(ValueError, match="xlsx_operation_target_unapproved"):
        validate_xlsx_operations(
            _SELECTION, ({"sheet": "Sheet1", "range": "B1", "value": 1},)
        )


def test_xlsx_operation_rejects_duplicate_targets():
    with pytest.raises(ValueError, match="xlsx_operation_target_unapproved"):
        validate_xlsx_operations(
            _SELECTION,
            ({"sheet": "Sheet1", "range": "A1", "value": 1},
             {"sheet": "Sheet1", "range": "A1", "value": 2}),
        )
