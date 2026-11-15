"""Conservative spreadsheet candidate operation checks.

This is a preflight guard, not a workbook evaluator. The editing engine must
still verify formula dependencies and source identity against the actual file.
"""
from __future__ import annotations

from typing import Any

from .document_candidate_xlsx_targets import validate_xlsx_selection


def validate_xlsx_operations(
    selection: tuple[dict[str, Any], ...],
    operations: tuple[dict[str, Any], ...],
) -> None:
    validate_xlsx_selection(selection)
    if not operations or len(operations) > 100:
        raise ValueError("xlsx_operations_invalid")
    allowed = {(item["sheet"], item["range"]) for item in selection}
    seen: set[tuple[str, str]] = set()
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) != {"sheet", "range", "value"}:
            raise ValueError("xlsx_operation_invalid")
        target = (operation["sheet"], operation["range"])
        if target not in allowed or target in seen:
            raise ValueError("xlsx_operation_target_unapproved")
        seen.add(target)
        value = operation["value"]
        # Formula edits and formulas disguised as strings require a separate
        # dependency-aware engine. No untrusted formula is accepted here.
        if not isinstance(value, (str, int, float, bool)) or isinstance(value, str) and (
            value.lstrip().startswith(("=", "+", "-", "@")) or
            any(ord(char) < 32 for char in value)
        ):
            raise ValueError("xlsx_formula_or_value_unsafe")
        if isinstance(value, str) and len(value) > 32767:
            raise ValueError("xlsx_value_too_long")
        if isinstance(value, float):
            import math
            if not math.isfinite(value):
                raise ValueError("xlsx_value_non_finite")
