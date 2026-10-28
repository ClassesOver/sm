"""Bound-row chart views and arithmetic with explicit, auditable semantics."""

from __future__ import annotations

import json
import math
from datetime import date
from fractions import Fraction
from statistics import mean

from .standard_chart_presentation import valid_standard_metadata


class StandardChartTransformationError(ValueError):
    def __init__(self, step_index, reason):
        self.step_index = step_index
        self.reason = reason
        super().__init__(f"Step {step_index}: {reason}")


def month_label(label):
    if not isinstance(label, str) or len(label) not in {7, 10}:
        raise ValueError("Expected ISO month or day")
    parsed = date.fromisoformat(label + "-01" if len(label) == 7 else label)
    if parsed.isoformat() != (label + "-01" if len(label) == 7 else label):
        raise ValueError("Noncanonical date")
    return parsed.strftime("%Y-%m")


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _measure(metadata, field):
    meta = metadata.get(field, {})
    if not valid_standard_metadata(meta) or not meta.get("unit"):
        raise ValueError("Transformation requires registered units")
    return meta


def _percentage(meta):
    return meta["unit"] == "%" or meta.get("isPercent") is True


def _groups(rows, indexes):
    groups: dict[tuple[str, ...], list[int]] = {}
    for index, row in enumerate(rows):
        key = tuple(row[position] for position in indexes)
        if any(not isinstance(value, str) or not value for value in key):
            raise ValueError("Invalid group")
        groups.setdefault(key, []).append(index)
    return groups


def _view(document, view):
    columns, rows = document["columns"], document["rows"]
    metadata = document.get("columnMeta") or {}
    fields = list(view.value_fields)
    dimensions = [view.label_field, *view.group_by]
    if len(set(fields)) != len(fields) or set(fields) & set(dimensions):
        raise ValueError("Duplicate view fields")
    indexes = [columns.index(field) for field in fields]
    metas = [_measure(metadata, field) for field in fields]
    li = columns.index(view.label_field)
    if view.kind == "pivot":
        if len(fields) != 1 or not view.series_field or not view.series_values:
            raise ValueError("Pivot needs one measure and explicit series")
        si = columns.index(view.series_field)
        if si == li or view.series_field in fields:
            raise ValueError("Pivot dimensions and measure must differ")
        names = list(view.series_values)
        if len(set(names)) != len(names) or view.label_field in names:
            raise ValueError("Duplicate pivot names")
        cells, labels = {}, []
        for row in rows:
            if row[si] not in names:
                continue
            label = row[li]
            if not isinstance(label, str) or not label or (label, row[si]) in cells:
                raise ValueError("Ambiguous pivot cell")
            if label not in labels:
                labels.append(label)
            cells[label, row[si]] = row[indexes[0]]
        if not labels or any((label, name) not in cells for label in labels for name in names):
            raise ValueError("Incomplete pivot, no zero filling")
        return {
            "columns": [view.label_field, *names],
            "rows": [[label, *(cells[label, name] for name in names)] for label in labels],
            "columnMeta": {name: dict(metas[0]) for name in names},
        }
    if view.series_field or view.series_values:
        raise ValueError("Group cannot select pivot series")
    if view.aggregation == "sum" and any(_percentage(meta) for meta in metas):
        raise ValueError("Percentages are not additive")
    if any(not _finite(row[index]) for row in rows for index in indexes):
        raise ValueError("Cannot aggregate missing or nonfinite values")
    groups = _groups(rows, [columns.index(field) for field in dimensions])
    totals = []
    if view.aggregation == "sum":
        import polars as pl

        from ...hospital_operation.deterministic_analysis import additive_group_totals

        # JSON tuple encoding is reversible; business dimensions remain separate columns.
        keys = [
            json.dumps([row[columns.index(field)] for field in dimensions], ensure_ascii=False)
            for row in rows
        ]
        totals = [
            additive_group_totals(
                pl.DataFrame(
                    {
                        "group": keys,
                        "value": [row[index] for row in rows],
                    }
                ),
                "value",
                "group",
            )[0]
            for index in indexes
        ]
    weight_index = None
    if view.aggregation == "weighted_mean":
        weight_index = columns.index(view.weight_field)
        _measure(metadata, view.weight_field)
        if view.weight_field in dimensions or any(
            not _finite(row[weight_index]) or row[weight_index] < 0 for row in rows
        ):
            raise ValueError("Weights must be finite, nonnegative registered measures")
    result = []
    for key, positions in groups.items():
        values: list[float | None]
        if view.aggregation == "sum":
            values = [total[json.dumps(key, ensure_ascii=False)] for total in totals]
        elif view.aggregation == "mean":
            values = [mean(rows[position][index] for position in positions) for index in indexes]
        else:
            # Exact binary-float ratios avoid both product overflow and losing a
            # tiny weight whose large value still makes a material contribution.
            weights = [Fraction(rows[position][weight_index]) for position in positions]
            denominator = sum(weights, Fraction(0))
            values = [
                float(
                    sum(
                        (
                            Fraction(rows[position][index]) * weight
                            for position, weight in zip(positions, weights, strict=True)
                        ),
                        Fraction(0),
                    )
                    / denominator
                )
                if denominator
                else None
                for index in indexes
            ]
        if any(value is not None and not _finite(value) for value in values):
            raise ValueError("Nonfinite group result")
        result.append([*key, *values])
    return {
        "columns": [*dimensions, *fields],
        "rows": result,
        "columnMeta": {field: dict(meta) for field, meta in zip(fields, metas, strict=True)},
    }


def _temporal_values(rows, columns, specification, ni):
    if not specification.label_field or specification.denominator:
        raise ValueError("Monthly operation needs explicit period field")
    li = columns.index(specification.label_field)
    group_indexes = [columns.index(field) for field in specification.group_by]
    groups = _groups(rows, group_indexes)
    values = [None] * len(rows)
    for positions in groups.values():
        months = [month_label(rows[index][li]) for index in positions]
        if len(set(months)) != len(months):
            raise ValueError("Duplicate months")
        ordered = [index for _month, index in sorted(zip(months, positions, strict=True))]
        serials = [int(month[:4]) * 12 + int(month[5:]) for month in sorted(months)]
        if specification.kind != "yoy_percent" and any(
            right != left + 1 for left, right in zip(serials, serials[1:])
        ):
            raise ValueError("Monthly operation cannot span missing months")
        measures = [rows[index][ni] for index in ordered]
        if any(value is not None and not _finite(value) for value in measures):
            raise ValueError("Nonfinite monthly measure")
        lookup = dict(zip(serials, measures, strict=True))
        accumulated: list[float] = []
        poisoned = False
        prior_year = None
        for offset, (index, serial, value) in enumerate(
            zip(ordered, serials, measures, strict=True)
        ):
            kind = specification.kind
            if kind in {"mom_percent", "yoy_percent"}:
                baseline = lookup.get(serial - (12 if kind == "yoy_percent" else 1))
                result = (
                    (value / baseline - 1) * 100
                    if value is not None and baseline is not None and baseline > 0
                    else None
                )
            elif kind == "cumulative_sum":
                year = (serial - 1) // 12
                if specification.reset == "year" and year != prior_year:
                    accumulated, poisoned = [], False
                prior_year = year
                if value is None:
                    poisoned = True
                else:
                    accumulated.append(value)
                result = None if poisoned else math.fsum(accumulated)
            else:
                window = specification.window
                if window is None:
                    raise ValueError("Rolling operation needs explicit window")
                sample = [
                    item
                    for item in measures[max(0, offset - window + 1) : offset + 1]
                    if item is not None
                ]
                minimum = specification.min_periods or window
                if len(sample) < minimum:
                    result = None
                elif kind == "rolling_mean":
                    result = mean(sample)
                else:
                    result = math.fsum(sample)
            values[index] = result
    # Preserve all rows and original indices while presenting groups chronologically.
    order = [
        index
        for positions in groups.values()
        for index in sorted(positions, key=lambda i: month_label(rows[i][li]))
    ]
    return [rows[index] for index in order], [values[index] for index in order]


def transform_chart_document(document, view, derivations):
    """Return a derived document; callers retain and recheck every original SHA."""
    columns = list(document["columns"])
    reserved_columns = set(columns)
    rows = [list(row) for row in document["rows"]]
    metadata = dict(document.get("columnMeta") or {})
    if (
        len(set(columns)) != len(columns)
        or not 1 <= len(rows) <= 480
        or any(len(row) != len(columns) for row in rows)
    ):
        raise ValueError("Invalid frozen rows")
    provenance = []
    if view is not None:
        transformed = _view({"columns": columns, "rows": rows, "columnMeta": metadata}, view)
        columns, rows, metadata = (
            transformed["columns"],
            transformed["rows"],
            transformed["columnMeta"],
        )
        provenance.append({**view.model_dump(by_alias=True), "scope": "bound_input_rows_only"})
    for specification in derivations:
        if specification.name in reserved_columns:
            raise ValueError("Derived field cannot overwrite frozen data")
        ni = columns.index(specification.numerator)
        left = _measure(metadata, specification.numerator)
        if _percentage(left) and specification.kind != "rolling_mean":
            raise ValueError("Derivation requires a registered nonpercentage measure")
        if specification.kind not in {"ratio_percent", "difference"}:
            rows, values = _temporal_values(rows, columns, specification, ni)
            meta = (
                {**left, "unit": "%", "isPercent": True}
                if specification.kind in {"mom_percent", "yoy_percent"}
                else dict(left)
            )
        else:
            if not specification.denominator or specification.label_field:
                raise ValueError("Binary derivation needs denominator")
            di = columns.index(specification.denominator)
            right = _measure(metadata, specification.denominator)
            if left.get("unit") != right.get("unit") or left.get("isPercent") != right.get(
                "isPercent"
            ):
                raise ValueError("Incompatible derivation units")
            if any(
                row[index] is not None and not _finite(row[index])
                for row in rows
                for index in (ni, di)
            ):
                raise ValueError("Nonfinite derivation operands")
            values = []
            for row in rows:
                numerator, denominator = row[ni], row[di]
                if numerator is None or denominator is None:
                    values.append(None)
                elif specification.kind == "ratio_percent":
                    values.append(numerator / denominator * 100 if denominator > 0 else None)
                else:
                    values.append(numerator - denominator)
            meta = (
                {**left, "unit": "%", "isPercent": True}
                if specification.kind == "ratio_percent"
                else dict(left)
            )
        if any(value is not None and not _finite(value) for value in values):
            raise ValueError("Nonfinite derived result")
        for row, value in zip(rows, values, strict=True):
            row.append(value)
        columns.append(specification.name)
        reserved_columns.add(specification.name)
        metadata[specification.name] = meta
        provenance.append(
            {**specification.model_dump(by_alias=True), "scope": "bound_input_rows_only"}
        )
    return {
        **document,
        "columns": columns,
        "rows": rows,
        "columnMeta": metadata,
        "standardTransformations": provenance,
    }


def apply_standard_chart_steps(document, steps):
    """An ordered, bounded pipeline; retain only server-computed step provenance."""
    if not 1 <= len(steps) <= 8:
        raise ValueError("Pipeline requires 1..8 explicit steps")
    events = []
    reserved_columns = set(document["columns"])
    for index, step in enumerate(steps):
        try:
            if step.derivation and step.derivation.name in reserved_columns:
                raise ValueError("Derived field cannot overwrite frozen or previous fields")
            document = transform_chart_document(
                document, step.view, (step.derivation,) if step.derivation else ()
            )
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise StandardChartTransformationError(index, str(error)[:200]) from error
        reserved_columns.update(document["columns"])
        events.extend(document["standardTransformations"])
    return {**document, "standardTransformations": events}
