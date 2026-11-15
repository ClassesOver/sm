"""Conservative spreadsheet candidate operation checks.

This is a preflight guard, not a workbook evaluator. The editing engine must
still verify formula dependencies and source identity against the actual file.
"""
from __future__ import annotations

from typing import Any
import math
import unicodedata

from .document_candidate_xlsx_targets import canonical_xlsx_target, validate_xlsx_selection


def validate_xlsx_operations(
    selection: tuple[dict[str, Any], ...],
    operations: tuple[dict[str, Any], ...],
) -> None:
    validate_xlsx_selection(selection)
    if not operations or len(operations) > 100:
        raise ValueError("xlsx_operations_invalid")
    allowed = {canonical_xlsx_target(item) for item in selection}
    seen: set[tuple[str, tuple[int, int], tuple[int, int]]] = set()
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) != {"sheet", "range", "value"}:
            raise ValueError("xlsx_operation_invalid")
        # Validate shape before using target values as dictionary/set keys.
        validate_xlsx_selection(({
            "sheet": operation["sheet"], "range": operation["range"],
        },))
        target = canonical_xlsx_target(operation)
        if target not in allowed or target in seen:
            raise ValueError("xlsx_operation_target_unapproved")
        seen.add(target)
        value = operation["value"]
        # Formula edits and formulas disguised as strings require a separate
        # dependency-aware engine. No untrusted formula is accepted here.
        if not isinstance(value, (str, int, float, bool)) or isinstance(value, str) and (
            unicodedata.normalize("NFKC", value).lstrip().startswith(("=", "+", "-", "@")) or
            any(unicodedata.category(char) in {"Cc", "Cf"} for char in value)
        ):
            raise ValueError("xlsx_formula_or_value_unsafe")
        if isinstance(value, str) and len(value) > 32767:
            raise ValueError("xlsx_value_too_long")
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("xlsx_value_non_finite")
