"""Strict PDF annotation targets, expressed in page coordinates.

Coordinates are normalized to the rendered page (0..1); the PDF engine must
resolve page rotation and crop boxes before producing a real annotation.
"""
from __future__ import annotations

import math
from typing import Any


def validate_pdf_selection(selection: tuple[dict[str, Any], ...]) -> None:
    if not selection or len(selection) > 100:
        raise ValueError("pdf_selection_invalid")
    for target in selection:
        if not isinstance(target, dict) or set(target) != {"page", "rect"}:
            raise ValueError("pdf_target_invalid")
        page, rect = target["page"], target["rect"]
        if type(page) is not int or not 0 <= page < 100000:
            raise ValueError("pdf_page_invalid")
        if not isinstance(rect, (list, tuple)) or len(rect) != 4 or any(
            type(v) not in (int, float) or not math.isfinite(v) for v in rect
        ):
            raise ValueError("pdf_rect_invalid")
        x0, y0, x1, y1 = rect
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError("pdf_rect_invalid")
