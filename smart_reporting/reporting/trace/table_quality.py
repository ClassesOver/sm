"""Conservative checks of frozen table cells; never a business completeness claim."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from ..contract import StrictModel
from ..units import unit_conversion_scale
from .contracts_v1 import RevisionTraceIndexV1
from .fact_index import fact_entry_from_pointer
from .markdown_body import trace_body
from .subject_builder import (
    _NUMBER_UNIT_RE,
    _UNIT_PATTERN,
    _mask_calendar_values,
    fact_periods,
    formatted_value_matches,
    unit_period_warnings,
)

_TABLE_HEADER_UNIT = re.compile(
    rf"[（(]((?:{_UNIT_PATTERN})(?:[/／][^()（）\s/／]+)*)[）)](?:\s*·\s*[\w.-]+)?$"
)


def table_value_matches(
    text: str, value: Any, unit: str | None, column_key: str | None = None
) -> bool:
    from .subject_builder import value_matches

    # 等值换算优先；裸数命中不能掩盖显式单位不一致，stale 仅提示复核。
    # 大额列按表头单位（“收入（万元）”）显示，单元格只写数字：补上表头单位再核对。
    header_unit = _TABLE_HEADER_UNIT.search(column_key or "")
    bare = text.replace("−", "-").replace("－", "-").strip()
    numeric_text = re.sub(
        r"\[\^?\d+\]", lambda match: " " * len(match[0]), _mask_calendar_values(bare)
    )
    # 只核对第一个实际金额/计数；备注里的另一个数字不能替代主值。
    primary = re.search(
        r"(?<![\d.,+\-a-zA-Z_])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d.,eE])",
        numeric_text,
    )
    if primary is None:
        return False
    explicit = _NUMBER_UNIT_RE.match(numeric_text, primary.start())
    suffix = re.match(
        r"\s*[A-Za-z\u4e00-\u9fff%‰]+(?:[/／][A-Za-z\u4e00-\u9fff%‰]+)*",
        numeric_text[primary.end() :],
    )
    if suffix is not None and (explicit is None or explicit.end() < primary.end() + suffix.end()):
        return False  # 整个单位必须可识别，不能只接受金额/百分号前缀。
    if explicit is not None:
        if numeric_text[explicit.end() :].lstrip().startswith(("/", "／", "%", "‰")):
            return False
        if not unit or unit_conversion_scale(unit, explicit["unit"]) is None:
            return False
        if (
            header_unit is not None
            and unit_conversion_scale(header_unit[1], explicit["unit"]) is None
        ):
            return False
    if header_unit is not None:
        display_unit = explicit["unit"] if explicit is not None else header_unit[1]
        scale = unit_conversion_scale(unit, display_unit)
        if scale is None:
            return False
        converted = Decimal(str(value)) * scale
        return value_matches(numeric_text[: primary.end()], converted)
    primary_text = numeric_text[: explicit.end() if explicit is not None else primary.end()]
    return formatted_value_matches(primary_text, value, unit) or (
        value_matches(primary_text, value)
        and not unit_period_warnings(primary_text, expected_unit=unit, fact_value=value)
    )


class TableQualityCheck(StrictModel):
    status: Literal["verified", "unknown"]
    scope: Literal["frozen_cells"] = "frozen_cells"
    reasons: tuple[str, ...] = ()
    checked_cells: int = Field(default=0, alias="checkedCells")


def uncovered_table_lines(markdown: str, registered_ids: set[str]) -> tuple[int, ...]:
    """Find rendered tables without a unique, registered protocol wrapper.

    Locations are diagnostics only; they never create table or fact identities.
    Parse actual Markdown tables so fenced examples and comments do not count.
    """
    from markdown_it import MarkdownIt

    from ..delivery.artifacts_v1 import _TABLE_BLOCK

    body = trace_body(markdown, mask_inline_code=False)
    offsets = [0]
    for line in body.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    tables = [
        (token.map[0] + 1, offsets[token.map[0]], offsets[token.map[1]])
        for token in MarkdownIt().enable("table").parse(body)
        if token.type == "table_open" and token.map is not None
    ]
    # Inline-code marker examples must not claim an adjacent real table.
    wrappers = list(_TABLE_BLOCK.finditer(trace_body(markdown)))
    counts = Counter(match[1] for match in wrappers)
    covered: set[int] = set()
    for match in wrappers:
        if match[1] not in registered_ids or counts[match[1]] != 1:
            continue
        if re.search(r"\[\[/?table:", match[2]):
            continue  # Nested/malformed wrappers cannot hide extra tables.
        # 旧格式结束标记紧跟末行（无空行）时，markdown-it 会把结束标记行并入表格；
        # 表格终点按整个包裹块（含结束标记）判断，否则已登记的旧表会被误报未覆盖。
        contained = [
            line for line, start, end in tables
            if match.start(2) <= start and end <= match.end() + 1
        ]
        if len(contained) == 1:
            covered.add(contained[0])
    return tuple(line for line, _, _ in tables if line not in covered)


def _blocks(markdown: str) -> dict[str, str]:
    from ..delivery.artifacts_v1 import _TABLE_BLOCK

    matches = list(_TABLE_BLOCK.finditer(trace_body(markdown, mask_inline_code=False)))
    counts = Counter(match[1] for match in matches)
    return {match[1]: match[2] for match in matches if counts[match[1]] == 1}


def _grid(body: str) -> list[list[str]]:
    from markdown_it import MarkdownIt

    rows: list[list[str]] = []
    tables = 0
    for token in MarkdownIt().enable("table").parse(body):
        if token.type == "table_open":
            tables += 1
        elif token.type == "tr_open":
            rows.append([])
        elif token.type == "inline" and rows:
            rows[-1].append(
                "".join(
                    child.content
                    for child in (token.children or ())
                    if child.type in {"text", "code_inline"}
                ).strip()
            )
    return rows if tables == 1 else []


def _selected(entry: Mapping[str, Any], selector: str) -> tuple[Any, str | None]:
    from .numeric_text import PERCENT_POINT, percent_point_field

    unit = entry.get("unit")
    if selector == "total":
        return entry.get("total"), unit
    if selector.startswith("period:") or re.fullmatch(r"periodValues\.\d+", selector):
        series = entry.get("periodValues") or ()
        if selector.startswith("period:"):
            values = [item for item in series if item.get("period") == selector[7:]]
        else:
            position = int(selector.split(".")[1])
            values = list(series[position : position + 1])
        return (values[0].get("value"), unit) if len(values) == 1 else (None, unit)
    field = selector.rsplit(":", 1)[-1]
    if field in {"currentTotal", "baselineTotal", "change", "changeRate"} and field in entry:
        unit = (
            "%"
            if field == "changeRate"
            else (PERCENT_POINT if percent_point_field(field, unit) else unit)
        )
        return entry[field] if entry[field] is not None else "—", unit
    return None, unit


def table_selector_matches(entry: Mapping[str, Any], row_key: str, selector: str) -> bool:
    """Reserved row roles cannot be redirected to another equal-valued field."""
    if row_key == "total":
        return selector == "total"
    if row_key.startswith("comparison:"):
        match = re.fullmatch(
            r"comparison:\d+:(currentTotal|baselineTotal|change|changeRate)", row_key
        )
        return match is not None and selector in {row_key, match[1]}
    if row_key.startswith("period:"):
        period = row_key[7:]
        series = entry.get("periodValues") or ()
        matching = [
            position for position, item in enumerate(series) if item.get("period") == period
        ]
        if len(matching) != 1:
            return False
        return selector in {row_key, f"periodValues.{matching[0]}"}
    # Custom structural keys have no implied business role.
    return True


def evaluate_table_quality(
    index: RevisionTraceIndexV1,
    markdown: str,
    documents: Mapping[str, Mapping[str, Any]],
    *,
    original_markdown: str | None = None,
) -> dict[str, TableQualityCheck]:
    """Recheck frozen presentation and selected values; edits remain soft unknown.

    Matching raw labels preserves their frozen period/scope identity. This does
    not prove that those original labels correctly describe business semantics.
    """
    from loguru import logger

    current = _blocks(markdown) if index.tables else {}
    originals = _blocks(original_markdown or "") if index.tables else {}
    checks = {}
    registered = {item.file_resource_id: item.analysis_id for item in index.fact_files}
    for table in index.tables:
        column_offset = int(table.row_label_column)
        reasons: list[str] = []
        checked = 0
        try:
            origin = (
                _blocks(table.origin_markdown).get(table.table_id)
                if table.origin_markdown is not None
                else originals.get(table.table_id)
            )
            frozen = _grid(origin or "")
            draft = _grid(current.get(table.table_id, ""))
            if not frozen or not draft:
                reasons.append("table_identity_unavailable")
            elif (
                len(frozen) != len(table.row_keys) + 1
                or tuple(frozen[0][column_offset:]) != table.column_keys
                or (table.row_label_column and len({row[0] for row in frozen[1:]}) != len(frozen) - 1)
                or any(len(row) != len(table.column_keys) + column_offset for row in frozen)
            ):
                reasons.append("frozen_structure_ambiguous")
            elif (
                draft[0] != frozen[0]
                or len(draft) != len(frozen)
                or Counter(tuple(row) for row in draft[1:])
                != Counter(tuple(row) for row in frozen[1:])
            ):
                reasons.append("table_presentation_changed")
            else:
                bound = {(cell.row_key, cell.column_key) for cell in table.cells}
                if len(bound) != len(table.row_keys) * len(table.column_keys):
                    reasons.append("table_cells_unbound")
                rows = dict(zip(table.row_keys, frozen[1:], strict=True))
                for cell in table.cells:
                    text = rows[cell.row_key][table.column_keys.index(cell.column_key) + column_offset]
                    if cell.source_cell is not None:
                        from .table_sources import source_cell_text, source_cell_view

                        source = documents.get(cell.source_cell.file_resource_id)
                        if source is None:
                            reasons.append("cell_source_unavailable")
                            continue
                        selected = source_cell_view(cell.source_cell, source)
                        if selected is None or text != source_cell_text(selected['value']):
                            reasons.append("cell_value_or_unit_unverified")
                        else:
                            checked += 1
                        continue
                    if len(cell.fact_refs) != 1:
                        reasons.append("cell_fact_binding_unavailable")
                        continue
                    ref = cell.fact_refs[0]
                    document = documents.get(ref.file_resource_id)
                    if document is None or registered.get(ref.file_resource_id) != ref.analysis_id:
                        reasons.append("cell_source_unavailable")
                        continue
                    kind, entry = fact_entry_from_pointer(document, ref.json_pointer)
                    if (
                        document.get("analysisId") != ref.analysis_id
                        or kind != ref.fact_kind
                        or entry.get("factId") != ref.fact_key
                    ):
                        reasons.append("cell_fact_binding_mismatch")
                        continue
                    selector = cell.value_selector or cell.row_key
                    if not table_selector_matches(entry, cell.row_key, selector):
                        reasons.append("cell_selector_binding_mismatch")
                        continue
                    if cell.row_key.startswith("period:"):
                        periods = fact_periods({
                            "periodGranularity": entry.get("periodGranularity"),
                            "periodValues": [{"period": cell.row_key[7:]}],
                        })
                        if not periods:
                            reasons.append("cell_period_identity_unavailable")
                            continue
                        if unit_period_warnings(rows[cell.row_key][0], expected_periods=periods):
                            reasons.append("cell_period_label_mismatch")
                            continue
                    value, unit = _selected(entry, selector)
                    if value is None or not (
                        text == "—"
                        if value == "—"
                        else table_value_matches(text, value, unit, cell.column_key)
                    ):
                        reasons.append("cell_value_or_unit_unverified")
                    else:
                        checked += 1
        except Exception as error:
            logger.warning(
                "table_quality_unavailable table_id={} reason={}",
                table.table_id,
                type(error).__name__,
            )
            reasons.append("table_check_failed")
        checks[table.table_id] = TableQualityCheck(
            status="unknown" if reasons else "verified",
            reasons=tuple(dict.fromkeys(reasons)),
            checkedCells=checked,
        )
    return checks
