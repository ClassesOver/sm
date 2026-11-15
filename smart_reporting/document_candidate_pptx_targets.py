"""Strict PPTX candidate target validation before any presentation engine call.

Targets identify existing slides and shapes by stable host-resolved identifiers.
No arbitrary XML, filesystem path, or save operation is accepted here.
"""
from __future__ import annotations

from typing import Any


def validate_pptx_selection(selection: tuple[dict[str, Any], ...]) -> None:
    if not selection or len(selection) > 100:
        raise ValueError("pptx_selection_invalid")
    seen: set[tuple[int, int]] = set()
    for target in selection:
        if not isinstance(target, dict) or set(target) != {"slide_id", "shape_id"}:
            raise ValueError("pptx_target_invalid")
        slide_id, shape_id = target["slide_id"], target["shape_id"]
        if (type(slide_id) is not int or type(shape_id) is not int
                or not 1 <= slide_id <= 2**31 - 1
                or not 1 <= shape_id <= 2**31 - 1):
            raise ValueError("pptx_target_invalid")
        key = (slide_id, shape_id)
        if key in seen:
            raise ValueError("pptx_target_duplicate")
        seen.add(key)
