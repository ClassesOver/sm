"""Bound-row chart views and arithmetic with explicit, auditable semantics."""
from __future__ import annotations

import math
from datetime import date

from .standard_chart_presentation import valid_standard_metadata


def month_label(label):
    if not isinstance(label, str) or len(label) not in {7, 10}:
        raise ValueError('Expected ISO month or day')
    parsed = date.fromisoformat(label + '-01' if len(label) == 7 else label)
    if parsed.isoformat() != (label + '-01' if len(label) == 7 else label):
        raise ValueError('Noncanonical date')
    return parsed.strftime('%Y-%m')


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def transform_chart_document(document, view, derivations):
    """Return a derived document; callers retain and recheck every original SHA."""
    columns = list(document['columns'])
    rows = [list(row) for row in document['rows']]
    metadata = dict(document.get('columnMeta') or {})
    if (len(set(columns)) != len(columns) or not 1 <= len(rows) <= 480
            or any(len(row) != len(columns) for row in rows)):
        raise ValueError('Invalid frozen rows')
    provenance = []
    if view is not None:
        li = columns.index(view.label_field)
        fields = list(view.value_fields)
        if len(set(fields)) != len(fields) or view.label_field in fields:
            raise ValueError('Duplicate view fields')
        indexes = [columns.index(field) for field in fields]
        if any(not valid_standard_metadata(metadata.get(field)) or not metadata[field].get('unit')
               for field in fields):
            raise ValueError('View requires registered units')
        if view.kind == 'group':
            if view.series_field or view.series_values:
                raise ValueError('Group cannot select pivot series')
            if any(metadata[field].get('isPercent') or metadata[field]['unit'] == '%' for field in fields):
                raise ValueError('Percentages are not additive')
            if any(not _finite(row[index]) for row in rows for index in indexes):
                raise ValueError('Cannot aggregate missing or nonfinite values')
            if any(not isinstance(row[li], str) or not row[li] for row in rows):
                raise ValueError('Invalid group')
            import polars as pl

            from ...hospital_operation.deterministic_analysis import additive_group_totals

            labels = list(dict.fromkeys(row[li] for row in rows))
            totals = [additive_group_totals(pl.DataFrame({
                'group': [row[li] for row in rows], 'value': [row[index] for row in rows],
            }), 'value', 'group')[0] for index in indexes]
            rows = [[label, *(total[label] for total in totals)] for label in labels]
            columns = [view.label_field, *fields]
            metadata = {field: metadata[field] for field in fields}
        else:
            if len(fields) != 1 or not view.series_field or not view.series_values:
                raise ValueError('Pivot needs one measure and explicit series')
            si = columns.index(view.series_field)
            names = list(view.series_values)
            if len(set(names)) != len(names) or view.label_field in names:
                raise ValueError('Duplicate pivot names')
            cells = {}
            labels = []
            for row in rows:
                if row[si] not in names:
                    continue
                label = row[li]
                if not isinstance(label, str) or not label or (label, row[si]) in cells:
                    raise ValueError('Ambiguous pivot cell')
                if label not in labels:
                    labels.append(label)
                cells[label, row[si]] = row[indexes[0]]
            if not labels or any((label, name) not in cells for label in labels for name in names):
                raise ValueError('Incomplete pivot, no zero filling')
            rows = [[label, *(cells[label, name] for name in names)] for label in labels]
            columns = [view.label_field, *names]
            metadata = {name: metadata[fields[0]] for name in names}
        provenance.append({**view.model_dump(by_alias=True), 'scope': 'bound_input_rows_only'})
    for specification in derivations:
        if specification.name in columns:
            raise ValueError('Derived field cannot overwrite frozen data')
        ni = columns.index(specification.numerator)
        left = metadata.get(specification.numerator, {})
        if not valid_standard_metadata(left) or not left.get('unit') or left.get('unit') == '%' or left.get('isPercent'):
            raise ValueError('Derivation requires a registered nonpercentage measure')
        if specification.kind == 'mom_percent':
            if not specification.label_field or specification.denominator:
                raise ValueError('Monthly change needs explicit period field')
            li = columns.index(specification.label_field)
            months = [month_label(row[li]) for row in rows]
            if len(set(months)) != len(months):
                raise ValueError('Duplicate months')
            rows = [row for _, row in sorted(zip(months, rows, strict=True))]
            months = sorted(months)
            serials = [int(value[:4]) * 12 + int(value[5:]) for value in months]
            if any(right != left + 1 for left, right in zip(serials, serials[1:])):
                raise ValueError('Monthly change cannot span missing months')
            if any(not _finite(row[ni]) for row in rows):
                raise ValueError('Missing monthly measure')
            values = [None] + [(row[ni] / previous[ni] - 1) * 100 if previous[ni] > 0 else None
                               for previous, row in zip(rows, rows[1:])]
            meta = {**left, 'unit': '%', 'isPercent': True}
        else:
            if not specification.denominator or specification.label_field:
                raise ValueError('Binary derivation needs denominator')
            di = columns.index(specification.denominator)
            right = metadata.get(specification.denominator, {})
            if (not valid_standard_metadata(right) or left.get('unit') != right.get('unit')
                    or left.get('isPercent') != right.get('isPercent')):
                raise ValueError('Incompatible derivation units')
            if any(not _finite(row[index]) for row in rows for index in (ni, di)):
                raise ValueError('Missing derivation operands')
            values = [(row[ni] / row[di] * 100 if row[di] > 0 else None)
                      if specification.kind == 'ratio_percent' else row[ni] - row[di] for row in rows]
            meta = {**left, 'unit': '%', 'isPercent': True} if specification.kind == 'ratio_percent' else left
        if any(value is not None and not _finite(value) for value in values):
            raise ValueError('Nonfinite derived result')
        for row, value in zip(rows, values, strict=True):
            row.append(value)
        columns.append(specification.name)
        metadata[specification.name] = meta
        provenance.append(specification.model_dump(by_alias=True))
    return {**document, 'columns': columns, 'rows': rows, 'columnMeta': metadata,
            'standardTransformations': provenance}
