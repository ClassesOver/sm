"""Recompute bounded table derivations from caller-verified, immutable source bytes."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from .contracts_v1 import TableDerivationV1, canonical_sha256, validate_json_pointer

_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")
_PERIOD = re.compile(r"([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?")
_NAME_PERIOD = re.compile(
    r"(?<!\d)([0-9]{4})年(?:([0-9]{1,2})月?"
    r"(?:[—–至到~～-]([0-9]{1,2}))?月)?"
)
_TOTAL = re.compile(r"(?:全院|全部|总)?(?:合计|总计|小计|汇总|总额|总量)")
_UNITS = frozenset({"元", "万元", "亿元", "人次", "万人次", "床日", "%", "‰"})


def _period_key(value: Any) -> tuple[date, int] | None:
    match = _PERIOD.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    try:
        return (
            date(int(match[1]), int(match[2] or 1), int(match[3] or 1)),
            10 if match[3] else 7 if match[2] else 4,
        )
    except ValueError:
        return None


def _window(start: Any, end: Any, grain: Any = None) -> tuple[str, ...]:
    first, last = _period_key(start), _period_key(end)
    if first is None or last is None or first[1] != last[1] or first[0] > last[0]:
        return ()
    width = {"year": 4, "month": 7, "day": 10}.get(grain, first[1])
    if grain is not None and grain not in {"year", "month", "day"}:
        return ()
    # As with fact_periods, two month-start labels without declared grain are month buckets.
    if grain is None and width == 10 and first[0].day == last[0].day == 1:
        width = 7
    current, stop = first[0], last[0]
    if width <= 7:
        current, stop = current.replace(day=1), stop.replace(day=1)
    if width == 4:
        current, stop = current.replace(month=1), stop.replace(month=1)
    result = []
    while current <= stop and len(result) < 1200:
        result.append(current.isoformat()[:width])
        if current == stop:
            return tuple(result)
        if width == 10:
            current += timedelta(days=1)
        elif width == 7:
            current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
        else:
            current = date(current.year + 1, 1, 1)
    return ()


def _structured_periods(node: Mapping[str, Any]) -> tuple[str, ...] | None:
    if any(key in node for key in ("periodStart", "periodEnd", "period_start", "period_end")):
        return _window(
            node.get("periodStart", node.get("period_start")),
            node.get("periodEnd", node.get("period_end")),
            node.get("periodGranularity", node.get("period_granularity")),
        )
    if "periods" in node:
        values = node["periods"]
        if not isinstance(values, (list, tuple)) or len(values) > 1200:
            return ()
        if any(_period_key(value) is None for value in values):
            return ()
        return tuple(dict.fromkeys(values))
    return None


def table_semantics(document: Any, table: Any) -> dict[str, Any]:
    """Read period/scope only from the verified table and its document, never a claim.

    Structured periods take precedence over names. Missing, invalid or ambiguous
    periods remain empty; there is no inferred year or implicit current role.
    """
    empty = {"periods": (), "period_roles": {}, "scope": {}}
    try:
        nodes = [node for node in (table, document) if isinstance(node, Mapping)]
        periods = None
        for node in nodes:
            periods = _structured_periods(node)
            if periods is not None:
                break
        if periods is None:
            for node in nodes:
                names = [node[key] for key in ("title", "name", "displayName")
                         if isinstance(node.get(key), str)]
                candidates = set()
                for name in names:
                    matches = list(_NAME_PERIOD.finditer(name))
                    if len(matches) != 1:
                        continue
                    match = matches[0]
                    # Do not treat a day expression or an unsupported cross-year range as a year.
                    if re.match(r"\d|[—–至到~～-]", name[match.end():]):
                        continue
                    year, first, last = match.groups()
                    candidates.add(_window(
                        f"{year}-{int(first):02d}" if first else year,
                        f"{year}-{int(last or first):02d}" if first else year,
                    ))
                if candidates:
                    periods = next(iter(candidates)) if len(candidates) == 1 else ()
                    break
        periods = periods or ()
        scope = next((node["scope"] for node in nodes if "scope" in node), {})
        if not isinstance(scope, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in scope.items()
        ):
            scope = {}
        roles = next((node.get("periodRoles", node.get("period_roles")) for node in nodes
                      if "periodRoles" in node or "period_roles" in node), ())
        roles = roles if isinstance(roles, (list, tuple)) else ()
        return {
            "periods": periods,
            "period_roles": {role: periods for role in roles if isinstance(role, str) and periods},
            "scope": dict(scope),
        }
    except Exception:
        return empty


def _pointer(document: Any, pointer: str) -> Any:
    validate_json_pointer(pointer)
    node = document
    for part in pointer.split("/")[1:]:
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            node = node[key]
        elif isinstance(node, list) and re.fullmatch(r"0|[1-9][0-9]*", key):
            node = node[int(key)]
        else:
            return None
    return node


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Ambiguous duplicate JSON member")
    return result


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    number = Decimal(str(value))
    return number if number.is_finite() else None


def _column_unit(table: dict[str, Any], column: str) -> str | None:
    from .numeric_text import _unit_from_column_name

    metadata = table.get("columnMeta", {})
    if not isinstance(metadata, dict):
        return None
    meta = metadata.get(column, {})
    if not isinstance(meta, dict):
        return None
    unit = meta.get("unit") if "unit" in meta else _unit_from_column_name(column)
    if unit not in _UNITS or unit == "%" and meta.get("isPercent", True) is not True:
        return None
    return unit


def _shape(operands: tuple, rows: list, unit: str) -> bool:
    positive = {(op.row_index, op.column_index) for op in operands if Decimal(op.coefficient) > 0}
    negative = {(op.row_index, op.column_index) for op in operands if Decimal(op.coefficient) < 0}
    if len(operands) == 2 and len(positive) == len(negative) == 1:
        left, right = next(iter(positive)), next(iter(negative))
        return left[0] == right[0] or left[1] == right[1]
    columns = {op.column_index for op in operands}
    if len(columns) == 1 and not negative and len(operands) >= 2:
        if unit == "个百分点":
            return False
        column = operands[0].column_index
        ranked = []
        for index, row in enumerate(rows):
            if any(isinstance(cell, str) and _TOTAL.fullmatch(cell.strip()) for cell in row):
                continue
            number = _number(row[column])
            if number is None:
                return False
            ranked.append((index, number))
        count = len(operands)
        if len(ranked) < count:
            return False
        threshold = sorted((value for _, value in ranked), reverse=True)[count - 1]
        chosen = {op.row_index for op in operands}
        return (chosen <= {index for index, value in ranked if value >= threshold}
                and {index for index, value in ranked if value > threshold} <= chosen)
    if len(columns) == 2 and positive and negative and unit not in {"%", "个百分点", "‰"}:
        return (
            len({column for _, column in positive}) == 1
            and len({column for _, column in negative}) == 1
            and {column for _, column in positive} != {column for _, column in negative}
            and {row for row, _ in positive} == {row for row, _ in negative} == set(range(len(rows)))
        )
    return False


def _resolve(derivation: TableDerivationV1, sources: Mapping[str, bytes]) -> tuple[str, dict] | None:
    from ..units import unit_conversion_scale

    # Revalidate model_construct/copy inputs too; bool coordinates must never become indices.
    raw_derivation = derivation.model_dump(mode="json", by_alias=True)
    for operand in derivation.operands:
        if (type(operand.row_index) is not int or type(operand.column_index) is not int
                or operand.row_index < 0 or operand.column_index < 0):
            return None
    derivation = TableDerivationV1.model_validate(raw_derivation)
    operands = derivation.operands
    identities = {(op.file_resource_id, op.table_pointer) for op in operands}
    if len(identities) != 1 or len({(op.row_index, op.column_index) for op in operands}) != len(operands):
        return None
    resource_id, pointer = next(iter(identities))
    raw = sources[resource_id]
    if not isinstance(raw, bytes):
        return None
    document = json.loads(raw, parse_float=Decimal, object_pairs_hook=_object)
    table = _pointer(document, pointer)
    if not isinstance(table, dict):
        return None
    columns, rows = table.get("columns"), table.get("rows")
    if (not isinstance(columns, list) or not columns
            or any(not isinstance(column, str) or not column for column in columns)
            or len(set(columns)) != len(columns) or not isinstance(rows, list) or not rows):
        return None
    if any(op.row_index >= len(rows) or op.column_index >= len(columns) for op in operands):
        return None
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        return None
    coefficients, values, units = [], [], []
    for op in operands:
        if not _DECIMAL.fullmatch(op.coefficient):
            return None
        coefficient = Decimal(op.coefficient)
        if (not coefficient.is_finite() or not coefficient or abs(coefficient) > Decimal("1e9")
                or len(coefficient.as_tuple().digits) > 32):
            return None
        value = _number(rows[op.row_index][op.column_index])
        source_unit = _column_unit(table, columns[op.column_index])
        if value is None or source_unit is None:
            return None
        target = "%" if derivation.unit == "个百分点" else derivation.unit
        scale = unit_conversion_scale(source_unit, target)
        if scale is None or abs(coefficient) != scale:
            return None
        coefficients.append(coefficient)
        values.append(value)
        units.append(source_unit)
    if (len(set(map(abs, coefficients))) != 1 or len(set(units)) != 1
            or not _shape(operands, rows, derivation.unit)):
        return None
    difference = any(coefficient < 0 for coefficient in coefficients)
    if ("%" in units and difference and derivation.unit != "个百分点"
            or derivation.unit == "个百分点" and (set(units) != {"%"} or not difference)):
        return None
    # Precision covers all aligned products and their sum, independently of caller context.
    products_budget = [len(value.as_tuple().digits) + len(coefficient.as_tuple().digits)
                       + abs(value.as_tuple().exponent) + abs(coefficient.as_tuple().exponent)
                       for value, coefficient in zip(values, coefficients, strict=True)]
    with localcontext() as context:
        context.prec = max(64, max(products_budget) * 2 + 8)
        value = sum((number * coefficient for number, coefficient
                     in zip(values, coefficients, strict=True)), Decimal(0))
    result = float(value)
    if not math.isfinite(result):
        return None
    # A revision may move the authorized file without changing its evidence.
    # Resource IDs remain mandatory read capabilities, but are not proof identity.
    digest = hashlib.sha256(raw).hexdigest()
    token = "{{tableDerived:v2:" + canonical_sha256({
        "ruleVersion": "table-linear/2",
        "unit": derivation.unit,
        "operands": [
            {**{key: value for key, value in operand.items() if key != "fileResourceId"},
             "sourceSha256": digest}
            for operand in raw_derivation["operands"]
        ],
    }) + "}}"
    semantics = table_semantics(document, table)
    names = [table.get(key) for key in ("title", "name", "displayName") if table.get(key)]
    formula = " + ".join(f"({number}) * ({coefficient})" for number, coefficient
                         in zip(values, coefficients, strict=True))
    return token, {
        "value": result, "unit": derivation.unit, **semantics, "formula": formula,
        "entry": {"displayName": names[0] if names else None, "aliases": (),
                  "scope": semantics["scope"]},
        "selector": "tableDerived",
    }


def table_derivation_token(
    derivation: TableDerivationV1, sources: Mapping[str, bytes],
) -> str | None:
    """Bind a supported derivation to the exact bytes of every referenced source."""
    try:
        resolved = _resolve(derivation, sources)
        return resolved[0] if resolved else None
    except Exception:
        return None


def resolve_table_derivation(
    token: str, derivation: TableDerivationV1, sources: Mapping[str, bytes],
) -> dict[str, Any] | None:
    """Verify the binding, then return the same selected view as ordinary numbers."""
    try:
        resolved = _resolve(derivation, sources)
        if not resolved:
            return None
        if token == resolved[0]:
            return resolved[1]
        # Previously issued tokens bind resource IDs. Read them only against the
        # original identity; snapshot migration explicitly verifies then upgrades.
        if not token.startswith("{{tableDerived:v2:"):
            legacy = "{{tableDerived:" + canonical_sha256({
                "derivation": derivation.model_dump(mode="json", by_alias=True),
                "sources": {operand.file_resource_id: hashlib.sha256(
                    sources[operand.file_resource_id]
                ).hexdigest() for operand in derivation.operands},
            }) + "}}"
            if token == legacy:
                return resolved[1]
        return None
    except Exception:
        return None
