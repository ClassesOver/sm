"""Recompute bounded table derivations from caller-verified, immutable source bytes."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from loguru import logger

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
    result: list[str] = []
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
        grain = node.get('periodGranularity', node.get('period_granularity'))
        if grain is not None:
            width = {'year': 4, 'month': 7, 'day': 10}.get(grain)
            if width is None or any(len(value) < width for value in values):
                return ()
            values = [value[:width] for value in values]
        return tuple(dict.fromkeys(values))
    return None


def table_semantics(
    document: Any, table: Any, column: str | None = None, *, row_index: int | None = None,
) -> dict[str, Any]:
    """Read period/scope only from the verified table and its document, never a claim.

    Structured periods take precedence over names. Missing, invalid or ambiguous
    periods remain empty; there is no inferred year or implicit current role.
    显式逐行期间绑定无效时保持未知，不退回整列窗口。
    """
    empty: dict[str, Any] = {"periods": (), "period_roles": {}, "scope": {}}
    try:
        nodes = [node for node in (table, document) if isinstance(node, Mapping)]
        metadata = table.get("columnMeta", {}) if isinstance(table, Mapping) else {}
        meta = metadata.get(column) if isinstance(metadata, Mapping) and column is not None else None
        if isinstance(meta, Mapping):
            grain = next((node.get("periodGranularity", node.get("period_granularity"))
                          for node in nodes if "periodGranularity" in node or "period_granularity" in node), None)
            nodes.insert(0, {"periodGranularity": grain, **meta})
        periods: tuple[str, ...] | None = None
        if row_index is not None and isinstance(meta, Mapping) and 'periodsByRowPeriod' in meta:
            periods = ()
            period_column = table.get('rowPeriodColumn')
            columns, rows = table.get('columns'), table.get('rows')
            period_map = meta['periodsByRowPeriod']
            if (type(row_index) is int and isinstance(columns, list) and isinstance(rows, list)
                    and 0 <= row_index < len(rows) and isinstance(period_column, str)
                    and columns.count(period_column) == 1 and isinstance(period_map, Mapping)):
                row = rows[row_index]
                if isinstance(row, list) and len(row) == len(columns):
                    row_period = row[columns.index(period_column)]
                    if isinstance(row_period, str) and row_period:
                        periods = _structured_periods({
                            'periodGranularity': grain, 'periods': period_map.get(row_period),
                        }) or ()
        if periods is None:
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
        scope: Any = next((node["scope"] for node in nodes if "scope" in node), {})
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
    if len(operands) == 1:
        return Decimal(operands[0].coefficient) > 0 and unit != '个百分点'
    positive = {(op.row_index, op.column_index) for op in operands if Decimal(op.coefficient) > 0}
    negative = {(op.row_index, op.column_index) for op in operands if Decimal(op.coefficient) < 0}
    if len(operands) == 2 and len(positive) == len(negative) == 1:
        left, right = next(iter(positive)), next(iter(negative))
        return left[0] == right[0] or left[1] == right[1]
    columns = {op.column_index for op in operands}
    if len(columns) == 1 and not positive and len(operands) >= 2 and unit not in {"%", "个百分点", "‰"}:
        # 负向差额前 N 项的减少幅度：-sum(负值)，保留原值和显式负系数。
        column = operands[0].column_index
        ranked = [(index, _number(row[column])) for index, row in enumerate(rows)
                  if not any(isinstance(cell, str) and _TOTAL.fullmatch(cell.strip()) for cell in row)]
        if any(value is None for _, value in ranked) or len(ranked) < len(operands):
            return False
        threshold = sorted(value for _, value in ranked)[len(operands) - 1]
        chosen = {op.row_index for op in operands}
        return (threshold < 0 and chosen <= {index for index, value in ranked if value <= threshold}
                and {index for index, value in ranked if value < threshold} <= chosen)
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


_SOURCE_CACHE: ContextVar[dict[tuple[str, bytes], Any] | None] = ContextVar(
    "table_source_cache", default=None
)


@contextmanager
def table_source_cache_scope() -> Iterator[None]:
    """一次质量评估内复用来源字节的 Decimal 解析与摘要；解析结果只读，不跨请求保留。"""
    if _SOURCE_CACHE.get() is not None:
        yield
        return
    token = _SOURCE_CACHE.set({})
    try:
        yield
    finally:
        _SOURCE_CACHE.reset(token)


def _decimal_document(raw: bytes) -> Any:
    cache = _SOURCE_CACHE.get()
    if cache is None:
        return json.loads(raw, parse_float=Decimal, object_pairs_hook=_object)
    key = ("decimal", raw)
    if key not in cache:
        cache[key] = json.loads(raw, parse_float=Decimal, object_pairs_hook=_object)
    return cache[key]


def _source_sha256(raw: bytes) -> str:
    cache = _SOURCE_CACHE.get()
    if cache is None:
        return hashlib.sha256(raw).hexdigest()
    key = ("sha256", raw)
    if key not in cache:
        cache[key] = hashlib.sha256(raw).hexdigest()
    return cache[key]


def _resolve(derivation: TableDerivationV1, sources: Mapping[str, bytes]) -> tuple[str, dict] | None:
    from ..units import unit_conversion_scale

    # Revalidate model_construct/copy inputs too; bool coordinates must never become indices.
    raw_derivation = derivation.model_dump(mode="json", by_alias=True)
    for operand in derivation.operands:
        if (type(operand.row_index) is not int or type(operand.column_index) is not int
                or operand.row_index < 0 or operand.column_index < 0):
            return None
    derivation = TableDerivationV1.model_validate(raw_derivation)
    if any((derivation.population_fact, derivation.population_proof_sha256,
            derivation.top_selection, derivation.top_limit)):
        return _resolve_population(derivation, sources)
    if derivation.denominator_fact is not None:
        return _resolve_share(derivation, sources)
    operands = derivation.operands
    identities = {(op.file_resource_id, op.table_pointer) for op in operands}
    if len(identities) != 1 or len({(op.row_index, op.column_index) for op in operands}) != len(operands):
        return None
    resource_id, pointer = next(iter(identities))
    raw = sources[resource_id]
    if not isinstance(raw, bytes):
        return None
    document = _decimal_document(raw)
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
        column = columns[op.column_index]
        source_unit = _column_unit(table, column)
        meta = table.get("columnMeta", {})
        meta = meta.get(column, {}) if isinstance(meta, dict) else {}
        fraction = (column == "contribution" and isinstance(meta, dict)
                    and meta.get("unit") == "%" and meta.get("isPercent") is False)
        if fraction:
            source_unit = "%"
        if value is None or source_unit is None:
            return None
        target = "%" if derivation.unit == "个百分点" else derivation.unit
        scale = unit_conversion_scale(source_unit, target)
        if scale is not None and fraction:
            scale *= 100
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
                       + abs(int(value.as_tuple().exponent))
                       + abs(int(coefficient.as_tuple().exponent))
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
    digest = _source_sha256(raw)
    token = "{{tableDerived:v2:" + canonical_sha256({
        "ruleVersion": "table-linear/2",
        "unit": derivation.unit,
        "operands": [
            {**{key: value for key, value in operand.items() if key != "fileResourceId"},
             "sourceSha256": digest}
            for operand in raw_derivation["operands"]
        ],
    }) + "}}"
    operand_semantics = [table_semantics(document, table, columns[op.column_index], row_index=op.row_index)
                         for op in operands]
    if any(item["scope"] != operand_semantics[0]["scope"] for item in operand_semantics):
        return None
    roles: dict[str, tuple[str, ...]] = {}
    for item in operand_semantics:
        for role, periods in item["period_roles"].items():
            roles[role] = tuple(dict.fromkeys((*roles.get(role, ()), *periods)))
    semantics = {"scope": operand_semantics[0]["scope"],
                 "periods": tuple(dict.fromkeys(period for item in operand_semantics for period in item["periods"])),
                 "period_roles": roles}
    names = [table.get(key) for key in ("title", "name", "displayName") if table.get(key)]
    formula = " + ".join(f"({number}) * ({coefficient})" for number, coefficient
                         in zip(values, coefficients, strict=True))
    return token, {
        "value": result, "unit": derivation.unit, **semantics, "formula": formula,
        "entry": {"displayName": names[0] if names else None, "aliases": (),
                  "scope": semantics["scope"]},
        "selector": "tableDerived",
        "operandViews": tuple({
            **{key: value for key, value in operand.items() if key != 'fileResourceId'},
            'sourceSha256': digest,
        } for operand in raw_derivation['operands']),
    }


def derivation_resource_ids(derivation: TableDerivationV1) -> tuple[str, ...]:
    """完整来源依赖；分母事实也是必须核验与保留的原始文件。"""
    return tuple(dict.fromkeys((
        *(operand.file_resource_id for operand in derivation.operands),
        *((derivation.denominator_fact.file_resource_id,) if derivation.denominator_fact else ()),
        *((derivation.population_fact.file_resource_id,) if derivation.population_fact else ()),
    )))


def _resolve_population(derivation: TableDerivationV1, sources: Mapping[str, bytes]) -> tuple[str, dict] | None:
    """重读冻结表及父事实，完整总体证明随导出/编辑继续可核验。"""
    from .subject_builder import fact_periods

    ref = derivation.population_fact
    if (ref is None or not derivation.population_proof_sha256
            or not derivation.top_selection or not derivation.top_limit
            or ref.fact_kind != 'metric' or not ref.fact_key):
        return None
    identities = {(op.file_resource_id, op.table_pointer) for op in derivation.operands}
    if len(identities) != 1:
        return None
    resource, pointer = next(iter(identities))
    document = _decimal_document(sources[resource])
    table = _pointer(document, pointer)
    proof = table.get('populationProof') if isinstance(table, dict) else None
    if not isinstance(proof, dict) or canonical_sha256(proof) != derivation.population_proof_sha256:
        return None
    parent_raw = sources[ref.file_resource_id]
    parent_document = _decimal_document(parent_raw)
    parent = _pointer(parent_document, ref.json_pointer)
    if (not isinstance(parent, dict) or parent_document.get('analysisId') != ref.analysis_id
            or parent.get('factId') != ref.fact_key or proof.get('populationFactId') != ref.fact_key
            or proof.get('version') != 'standard-population-v1'
            or proof.get('completePopulation') is not True or proof.get('invalidRowCount') != 0
            or proof.get('tablePointer') != pointer or parent.get('aggregation') != 'sum'
            or parent.get('periodAggregation') not in {None, 'sum'}
            or parent.get('cumulativePolicy') is not None
            or proof.get('datasetSha256') != parent.get('datasetSha256')
            or proof.get('datasetId') != parent.get('datasetId')
            or proof.get('measureField') != parent.get('field')
            or proof.get('unit') != parent.get('unit') or proof.get('scope') != parent.get('scope')
            or _structured_periods({**proof, 'periodGranularity': parent.get('periodGranularity')})
            != tuple(fact_periods(parent))):
        return None
    semantics = table_semantics(document, table)
    if (not isinstance(table.get('scope', document.get('scope')), dict)
            or semantics['scope'] != parent.get('scope')
            or tuple(semantics['periods']) != tuple(fact_periods(parent))):
        return None
    columns, rows = table.get('columns'), table.get('rows')
    if not isinstance(columns, list) or not isinstance(rows, list) or not rows:
        return None
    dimension = proof.get('dimensionField')
    measure = proof.get('measureField') if proof.get('measureField') in columns else 'value'
    if (not isinstance(dimension, str) or not isinstance(measure, str)
            or dimension not in columns or measure not in columns):
        return None
    dimension_index, measure_index = columns.index(dimension), columns.index(measure)
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        return None
    labels = [row[dimension_index] for row in rows]
    if (any(not isinstance(label, str) or not label for label in labels)
            or len(set(labels)) != len(labels) or sorted(labels) != proof.get('members')
            or len(labels) != proof.get('memberCount')
            or hashlib.sha256(json.dumps(sorted(labels), ensure_ascii=False,
                separators=(',', ':')).encode()).hexdigest() != proof.get('membersSha256')
            or _column_unit(table, measure) != proof.get('unit')):
        return None
    raw_values = [_number(row[measure_index]) for row in rows]
    total = _number(parent.get('total'))
    if any(value is None for value in raw_values) or total is None:
        return None
    values = [value for value in raw_values if value is not None]
    if (abs(sum(values, Decimal(0)) - total)
            > max(Decimal('1e-9'), abs(total) * Decimal('1e-12'))
            or derivation.top_limit > len(rows)):
        return None
    ordered = sorted(range(len(rows)), key=lambda index: (-values[index], labels[index]))
    selected = ordered[:derivation.top_limit]
    if derivation.top_selection == 'rank':
        threshold = values[selected[-1]]
        selected = [index for index in ordered if values[index] >= threshold]
    if (set(selected) != {op.row_index for op in derivation.operands}
            or any(op.column_index != measure_index for op in derivation.operands)):
        return None
    linear = derivation.model_copy(update={'population_fact': None,
        'population_proof_sha256': None, 'top_selection': None, 'top_limit': None})
    resolved = _resolve(linear, sources)
    if resolved is None:
        return None
    token, view = resolved
    return '{{tableDerived:v2:' + canonical_sha256({
        'ruleVersion': 'table-population/1', 'valueToken': token,
        'populationProofSha256': derivation.population_proof_sha256,
        'populationSourceSha256': _source_sha256(parent_raw),
        'topSelection': derivation.top_selection, 'topLimit': derivation.top_limit,
    }) + '}}', {**view, 'populationProof': proof, 'topSelection': derivation.top_selection,
               'topLimit': derivation.top_limit}


def _resolve_share(derivation: TableDerivationV1, sources: Mapping[str, bytes]) -> tuple[str, dict] | None:
    """表格分子 / 精确冻结事实total；不从金额相等推断对象或期间。"""
    from .subject_builder import fact_periods

    ref = derivation.denominator_fact
    if ref is None or derivation.unit != '%' or ref.fact_kind != 'metric' or not ref.fact_key:
        return None
    raw = sources[ref.file_resource_id]
    document = _decimal_document(raw)
    entry = _pointer(document, ref.json_pointer)
    if (not isinstance(entry, dict) or document.get('analysisId') != ref.analysis_id
            or entry.get('factId') != ref.fact_key or entry.get('aggregation') != 'sum'
            or entry.get('periodAggregation') not in {None, 'sum'}
            or entry.get('cumulativePolicy') is not None):
        return None
    total = _number(entry.get('total'))
    unit = entry.get('unit')
    if total is None or total == 0 or unit not in _UNITS or unit in {'%', '‰'}:
        return None
    numerator = derivation.model_copy(update={'unit': unit, 'denominator_fact': None})
    for operand in derivation.operands:
        table_document = _decimal_document(sources[operand.file_resource_id])
        table = _pointer(table_document, operand.table_pointer)
        if not isinstance(table.get('scope', table_document.get('scope')), dict):
            return None
    resolved = _resolve(numerator, sources)
    if resolved is None:
        return None
    numerator_token, view = resolved
    periods = tuple(fact_periods(entry))
    if (not periods or not view['periods'] or tuple(view['periods']) != periods
            or not isinstance(entry.get('scope'), dict) or view['scope'] != entry['scope']):
        return None
    with localcontext() as context:
        context.prec = 64
        # Recompute from source decimals rather than a rounded percentage cell.
        numerator_value = Decimal(0)
        for operand in derivation.operands:
            table = _pointer(_decimal_document(sources[operand.file_resource_id]),
                             operand.table_pointer)
            operand_value = _number(table['rows'][operand.row_index][operand.column_index])
            if operand_value is None:
                return None
            numerator_value += operand_value * Decimal(operand.coefficient)
        value = float(numerator_value / total * 100)
    if not math.isfinite(value):
        return None
    token = '{{tableDerived:v2:' + canonical_sha256({
        'ruleVersion': 'table-fact-share/1', 'numeratorToken': numerator_token,
        'denominatorFact': {key: value for key, value in ref.model_dump(mode='json', by_alias=True).items()
                            if key != 'fileResourceId'},
        'denominatorSha256': _source_sha256(raw),
    }) + '}}'
    return token, {**view, 'value': value, 'unit': '%', 'selector': 'tableDerived',
                   'formula': f'({view["formula"]}) / ({total}) * 100',
                   'denominatorFact': ref.model_dump(mode='json', by_alias=True)}


def table_derivation_token(
    derivation: TableDerivationV1, sources: Mapping[str, bytes],
) -> str | None:
    """Bind a supported derivation to the exact bytes of every referenced source."""
    try:
        resolved = _resolve(derivation, sources)
        return resolved[0] if resolved else None
    except Exception as error:
        # 绑定失败会使该数字按未核实处理；记录原因便于排查，不中断正文生成。
        logger.debug("report_table_derivation_unbound reason={}", type(error).__name__)
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
        if not token.startswith("{{tableDerived:v2:") and not any((
            derivation.denominator_fact,
            derivation.population_fact,
            derivation.population_proof_sha256,
            derivation.top_selection,
            derivation.top_limit,
        )):
            source_hashes = {operand.file_resource_id: hashlib.sha256(
                sources[operand.file_resource_id]
            ).hexdigest() for operand in derivation.operands}
            # Two historical serializers existed: one omitted optional nulls,
            # while the earlier revision snapshot included them. Both hashes
            # remain bound to the same verified source bytes and are upgraded
            # to v2 during the copy.
            legacy_tokens = {
                "{{tableDerived:" + canonical_sha256({
                    "derivation": derivation.model_dump(
                        mode="json", by_alias=True, exclude_none=exclude_none,
                    ),
                    "sources": source_hashes,
                }) + "}}"
                for exclude_none in (False, True)
            }
            if token in legacy_tokens:
                return resolved[1]
        return None
    except Exception as error:
        logger.debug("report_table_derivation_unresolved reason={}", type(error).__name__)
        return None


def resolve_source_cell(operand: Any, sources: Mapping[str, bytes]) -> dict[str, Any] | None:
    """读取调用方已核验身份的原始单元格。"""
    try:
        document = json.loads(sources[operand.file_resource_id], object_pairs_hook=_object)
        return source_cell_view(operand, document)
    except (KeyError, TypeError, ValueError):
        return None


def source_cell_view(operand: Any, document: Any) -> dict[str, Any] | None:
    """已核验来源的直接视图；不猜维度、单位、期间或排名算法。"""
    try:
        if operand.coefficient != '1':
            return None
        table = _pointer(document, operand.table_pointer)
        if not isinstance(table, dict):
            return None
        columns, rows = table.get('columns'), table.get('rows')
        if (not isinstance(columns, list) or not isinstance(rows, list)
                or not all(isinstance(column, str) and column for column in columns)
                or len(columns) != len(set(columns))):
            return None
        row = rows[operand.row_index]
        if not isinstance(row, list) or len(row) != len(columns):
            return None
        value = row[operand.column_index]
        if not (value is None or isinstance(value, (str, bool, int, float))):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        metadata = table.get('columnMeta', {})
        meta = metadata.get(columns[operand.column_index], {}) if isinstance(metadata, dict) else {}
        # 原表展示不从标题里的年份猜统计窗口；缺少结构化范围就如实未知。
        semantic_keys = {'periodStart', 'periodEnd', 'period_start', 'period_end',
                         'periodGranularity', 'period_granularity', 'periods',
                         'periodRoles', 'period_roles', 'scope'}
        semantic_document = {key: item for key, item in document.items() if key in semantic_keys}
        semantic_table = {key: item for key, item in table.items()
                          if key in semantic_keys or key in {'rowPeriodColumn', 'columns', 'rows'}}
        return {'value': value, 'unit': meta.get('unit') if isinstance(meta, dict) else None,
                'isPercent': meta.get('isPercent') if isinstance(meta, dict) else None,
                'column': columns[operand.column_index], **table_semantics(semantic_document, {**semantic_table, "columnMeta": metadata},
                                  columns[operand.column_index], row_index=operand.row_index)}
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def source_cell_text(value: Any) -> str:
    """原样展示冻结值，单位只保留来源显式元数据。"""
    return '—' if value is None else str(value)


def source_cell_display(selected: Mapping[str, Any], column_key: str, *, display_format: str = 'raw') -> str:
    """仅按显式登记的展示契约格式化；不从历史表头猜测格式。"""
    from ..units import unit_conversion_scale
    from .numeric_text import format_fact_value

    value = selected['value']
    if display_format != 'unit_formatted':
        return source_cell_text(value)
    number = _number(value)
    target = re.search(r'（([^（）]+)）$', column_key)
    if number is None or target is None:
        return source_cell_text(value)
    unit = selected.get('unit')
    display_unit = target[1]
    if display_unit == '单位未提供' and unit is None:
        return format_fact_value(value, None)
    scale = unit_conversion_scale(unit, display_unit)
    if scale is None:
        return source_cell_text(value)
    if unit == '%':
        if selected.get('isPercent') is False:
            number *= 100
        from decimal import ROUND_HALF_UP

        rounded = number.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return f'{abs(rounded) if rounded == 0 else rounded:,.2f}'
    return format_fact_value(value, unit, display_unit).removesuffix(display_unit)
