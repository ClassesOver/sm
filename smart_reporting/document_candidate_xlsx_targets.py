"""Validate spreadsheet edit targets before any XLSX engine is invoked.

Validation is deliberately conservative: only explicit cell/range coordinates
are accepted. No workbook writes, formula evaluation or candidate acceptance.
"""
from __future__ import annotations

import re
from typing import Any

_CELL = re.compile(r"^\$?([A-Z]{1,3})\$?([1-9][0-9]{0,6})$")
_SHEET_FORBIDDEN = set("[]:*?/\\")
_MAX_ROW = 1048576
_MAX_COL = 16384


def _cell(value: Any) -> tuple[int, int]:
    if not isinstance(value, str):
        raise ValueError("xlsx_target_invalid")
    match = _CELL.fullmatch(value)
    if match is None:
        raise ValueError("xlsx_target_invalid")
    col = 0
    for letter in match.group(1):
        col = col * 26 + ord(letter) - ord("A") + 1
    row = int(match.group(2))
    if col > _MAX_COL or row > _MAX_ROW:
        raise ValueError("xlsx_target_out_of_bounds")
    return row, col


def validate_xlsx_selection(selection: tuple[dict[str, Any], ...]) -> None:
    if not selection:
        raise ValueError("xlsx_selection_required")
    for target in selection:
        if not isinstance(target, dict) or set(target) != {"sheet", "range"}:
            raise ValueError("xlsx_target_invalid")
        sheet = target["sheet"]
        if (not isinstance(sheet, str) or not sheet or len(sheet) > 31
                or sheet.startswith("'") or sheet.endswith("'")
                or any(c in _SHEET_FORBIDDEN or ord(c) < 32 for c in sheet)):
            raise ValueError("xlsx_sheet_invalid")
        value = target["range"]
        if not isinstance(value, str):
            raise ValueError("xlsx_target_invalid")
        parts = value.split(":")
        if len(parts) not in (1, 2):
            raise ValueError("xlsx_target_invalid")
        start = _cell(parts[0])
        if len(parts) == 2:
            end = _cell(parts[1])
            if start[0] > end[0] or start[1] > end[1]:
                raise ValueError("xlsx_range_reversed")
