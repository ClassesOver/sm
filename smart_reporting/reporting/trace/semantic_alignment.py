"""Finite semantic identity checks, never inferred from equal values or labels.

These checks establish only an explicitly registered relation. They do not prove
arbitrary chart titles, natural-language conclusions, causality or image pixels.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal

from loguru import logger
from pydantic import Field

from ..contract import SHA256_PATTERN, StrictModel
from ..units import unit_conversion_scale
from ..workflow.runtime.chart_inputs import parse_data_path
from .chart_quality import ChartQualityCheck
from .contracts_v1 import RevisionTraceIndexV1
from .fact_index import fact_entry_from_pointer


class SemanticOperandIdentity(StrictModel):
    """Server-owned normal form of an exact, already verified selection.

    There is deliberately no model-facing registration endpoint. The identity
    must be constructed from frozen sources, not supplied by generated prose.
    Numeric values and display labels are absent: they do not establish identity.
    """

    source_sha256: str = Field(alias="sourceSha256", pattern=SHA256_PATTERN)
    profile_hash: str = Field(alias="profileHash", pattern=SHA256_PATTERN)
    analysis_id: str = Field(alias="analysisId")
    fact_id: str = Field(alias="factId")
    fact_kind: str = Field(alias="factKind")
    selector: str
    unit: str | None
    periods: tuple[str, ...]
    scope: dict[str, str]


class SemanticAlignmentCheck(StrictModel):
    status: Literal["verified", "unknown", "conflicting"] = "unknown"
    scope: Literal["registered_fact_projection", "registered_operand_identity"]
    reasons: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = Field(default=(), alias="factIds")


def compare_semantic_operands(
    expected: SemanticOperandIdentity,
    actual: SemanticOperandIdentity,
) -> SemanticAlignmentCheck:
    """Compare a server-registered relation; never search equal-valued candidates."""
    differences = tuple(
        f"{field}_mismatch"
        for field in (
            "source_sha256",
            "profile_hash",
            "analysis_id",
            "fact_id",
            "fact_kind",
            "selector",
            "unit",
            "periods",
            "scope",
        )
        if getattr(expected, field) != getattr(actual, field)
    )
    incomplete = not expected.unit or not actual.unit or not expected.periods or not actual.periods
    return SemanticAlignmentCheck(
        scope="registered_operand_identity",
        status="conflicting" if differences else "unknown" if incomplete else "verified",
        reasons=differences or (("operand_semantics_incomplete",) if incomplete else ()),
        factIds=tuple(dict.fromkeys((expected.fact_id, actual.fact_id))),
    )


def _projection_semantics(
    kind: str,
    entry: Mapping[str, Any],
    tokens: tuple[str | int, ...],
    columns: Any,
) -> tuple[str | None, tuple[str, ...] | None]:
    """Finite value-column roles; totals, relative rates and point differences differ."""
    from .numeric_text import PERCENT_POINT, percent_point_field

    if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
        raise ValueError("chart_projection_selector_unregistered")
    unit = entry.get("unit")
    nested = tokens[2:]
    if not nested:
        fields = (
            {"total", "average", "minimum", "maximum"}
            if kind == "metric"
            else {"currentTotal", "baselineTotal", "change", "changeRate"}
            if kind == "comparison"
            else set()
        )
        selected = fields.intersection(columns)
        if len(selected) != 1:
            raise ValueError("chart_projection_selector_unregistered")
        selected_field = selected.pop()
        if selected_field == "changeRate":
            unit = "%"
        elif percent_point_field(selected_field, unit):
            unit = PERCENT_POINT
        categories = (
            (str(entry["field"]),)
            if "field" in columns and isinstance(entry.get("field"), str)
            else None
        )
        return unit, categories
    if kind == "metric" and nested[0] in {"periodValues", "topGroups", "bottomGroups"}:
        if len(nested) > 2 or (len(nested) == 2 and not isinstance(nested[1], int)):
            raise ValueError("chart_projection_selector_unregistered")
        if "value" not in columns:
            raise ValueError("chart_projection_selector_unregistered")
        rows = entry.get(nested[0])
        if not isinstance(rows, list):
            raise ValueError("chart_projection_selector_unregistered")
        if len(nested) == 2:
            position = nested[1]
            if not isinstance(position, int):
                raise ValueError("chart_projection_selector_unregistered")
            rows = rows[position : position + 1]
        category = "period" if nested[0] == "periodValues" else "group"
        if category not in columns or any(
            not isinstance(row, Mapping) or not isinstance(row.get(category), str) for row in rows
        ):
            raise ValueError("chart_projection_category_unregistered")
        categories = tuple(row[category] for row in rows)
        if not categories or len(set(categories)) != len(categories):
            raise ValueError("chart_projection_category_ambiguous")
        return unit, categories
    raise ValueError("chart_projection_selector_unregistered")


def evaluate_semantic_alignment(
    index: RevisionTraceIndexV1,
    sources: Mapping[str, bytes],
    *,
    chart_checks: Mapping[str, ChartQualityCheck],
) -> dict[str, SemanticAlignmentCheck]:
    """Recheck declared chart facts against actual frozen chart-input projections.

    `registered_arrays` is a prerequisite, not sufficient for metric ownership.
    No declared fact binding, opaque custom table or unknown unit stays unknown.
    A failure affects only that chart. Sources are rechecked here so the helper
    cannot accidentally accept documents outside the registered revision.
    """
    files = {file.resource_id: file for file in index.files}
    documents: dict[str, Mapping[str, Any]] = {}
    fact_files = {file.file_resource_id: file.analysis_id for file in index.fact_files}
    checks = {}

    def document(resource_id: str) -> Mapping[str, Any]:
        if resource_id not in documents:
            file = files[resource_id]
            raw = sources.get(resource_id)
            if (
                raw is None
                or len(raw) != file.size
                or hashlib.sha256(raw).hexdigest() != file.sha256
            ):
                raise ValueError("alignment_source_unavailable")
            parsed = json.loads(raw)
            if not isinstance(parsed, Mapping):
                raise ValueError("alignment_source_invalid")
            documents[resource_id] = parsed
        return documents[resource_id]

    for chart in index.chart_traces:
        reasons = []
        bound: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
        projected: set[tuple[str, str, str, str]] = set()
        projection_units: list[str | None] = []
        projection_categories: list[tuple[str, ...] | None] = []
        try:
            if (
                chart_checks.get(chart.chart_id) is None
                or chart_checks[chart.chart_id].status != "verified"
            ):
                raise ValueError("chart_arrays_unverified")
            if (chart.standard_render_proof is not None
                    and chart_checks[chart.chart_id].reason == "standard_render_matches_frozen_inputs"):
                from .standard_chart_alignment import evaluate_standard_chart_alignment

                checks[chart.chart_id] = evaluate_standard_chart_alignment(index, chart, document)
                continue
            if not chart.fact_refs:
                raise ValueError("chart_fact_binding_unregistered")
            for ref in chart.fact_refs:
                source = document(ref.file_resource_id)
                kind, entry = fact_entry_from_pointer(source, ref.json_pointer)
                if (
                    fact_files.get(ref.file_resource_id) != ref.analysis_id
                    or source.get("analysisId") != ref.analysis_id
                    or kind != ref.fact_kind
                    or entry.get("factId") != ref.fact_key
                    or not ref.fact_key
                ):
                    raise ValueError("chart_fact_binding_mismatch")
                if (
                    entry.get("profileHash") is not None
                    and entry.get("profileHash") != index.profile_hash
                ):
                    raise ValueError("chart_fact_profile_mismatch")
                key = (ref.file_resource_id, ref.analysis_id, kind, ref.fact_key)
                if key in bound:
                    raise ValueError("chart_fact_binding_ambiguous")
                bound[key] = entry
            for resource_id in chart.plot_data_file_resource_ids:
                plot = document(resource_id)
                plot_source = plot.get("source")
                if (
                    plot.get("schema") != "chart-input/v1"
                    or plot.get("chartId") != chart.chart_id
                    or not isinstance(plot_source, Mapping)
                ):
                    raise ValueError("chart_input_identity_mismatch")
                matches = [
                    file_id
                    for file_id, analysis_id in fact_files.items()
                    if analysis_id == plot_source.get("analysisId")
                    and files[file_id].sha256 == plot_source.get("sha256")
                ]
                if len(matches) != 1:
                    raise ValueError("chart_input_fact_source_ambiguous")
                file_id = matches[0]
                source_document = document(file_id)
                tokens = parse_data_path(plot_source.get("dataPath", ""))
                # Only a known fact record path establishes fact ownership. A
                # custom `findings.rows` table has no safe implied metric link.
                if (
                    len(tokens) < 2
                    or not isinstance(tokens[0], str)
                    or not isinstance(tokens[1], int)
                ):
                    raise ValueError("chart_projection_fact_unregistered")
                kind, entry = fact_entry_from_pointer(source_document, f"/{tokens[0]}/{tokens[1]}")
                fact_id = entry.get("factId")
                if not isinstance(fact_id, str) or source_document.get(
                    "analysisId"
                ) != plot_source.get("analysisId"):
                    raise ValueError("chart_projection_fact_unregistered")
                projected.add((file_id, plot_source["analysisId"], kind, fact_id))
                projected_unit, categories = _projection_semantics(
                    kind, entry, tokens, plot.get("columns")
                )
                projection_units.append(projected_unit)
                projection_categories.append(categories)
            if projected != set(bound):
                raise ValueError("chart_projection_fact_mismatch")
            # This is a bound fact's raw unit; display conversion still needs
            # registered arrays and the finite unit families, not numeric fit.
            if not chart.axis_unit:
                raise ValueError("chart_axis_unit_unregistered")
            if any(
                not unit or unit_conversion_scale(unit, chart.axis_unit) is None
                for unit in projection_units
            ):
                raise ValueError("chart_axis_unit_mismatch")
            if any(unit != chart.axis_unit for unit in projection_units):
                # Same-family units permit a conversion, but this layer has no
                # proof that the actual figure axis/trace applied that scale.
                raise ValueError("chart_axis_conversion_unregistered")
            if chart.series:
                if any(series.series_kind != "observed" for series in chart.series):
                    raise ValueError("chart_series_kind_unproven")
                if any(
                    not series.unit or unit_conversion_scale(series.unit, chart.axis_unit) is None
                    for series in chart.series
                ):
                    raise ValueError("chart_series_unit_mismatch")
                if any(series.unit != chart.axis_unit for series in chart.series):
                    raise ValueError("chart_series_conversion_unregistered")
                if any(series.categories for series in chart.series):
                    if (
                        len(chart.series) != 1
                        or len(projection_categories) != 1
                        or projection_categories[0] != chart.series[0].categories
                    ):
                        raise ValueError("chart_series_categories_mismatch")
                if len(chart.series) > 1 or len(bound) > 1:
                    raise ValueError("chart_series_assignment_unregistered")
        except Exception as error:
            reason = (
                str(error)
                if isinstance(error, ValueError) and str(error).startswith(("chart_", "alignment_"))
                else "alignment_check_failed"
            )
            logger.warning(
                "chart_semantic_alignment_unknown chart_id={} reason={}", chart.chart_id, reason
            )
            reasons.append(reason)
        checks[chart.chart_id] = SemanticAlignmentCheck(
            scope="registered_fact_projection",
            status="unknown" if reasons else "verified",
            reasons=tuple(reasons),
            factIds=tuple(sorted({key[3] for key in bound})),
        )
    return checks
