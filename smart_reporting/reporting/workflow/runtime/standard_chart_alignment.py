"""Exact-label alignment of frozen, explicitly selected chart inputs."""
import json
import math

from .standard_chart_presentation import valid_standard_metadata
from .standard_chart_transform import month_label


def align_chart_sources(entries, files, selections, *, selected_labels=(), allow_nulls=False,
                        max_labels=60, diagnostics=None):
    def unavailable(reason, source_index=None):
        if diagnostics is not None:
            diagnostics.append({'reason': reason, 'sourceIndex': source_index})
        return None

    if not entries or not selections or len(selections) > 8:
        return unavailable('source_selection_missing_or_excessive')
    names = [selection.series_name for selection in selections]
    if len(names) != len(set(names)) or 'period' in names:
        return unavailable('series_names_invalid')
    labels = None
    columns = ['period', *names]
    series = []
    metadata = {}
    identities = []
    used_sources = set()
    for selection in selections:
        if selection.source_index >= len(entries):
            return unavailable('source_index_invalid', selection.source_index)
        entry = entries[selection.source_index]
        source = next((item for item in files if item.path == entry['path']), None)
        if source is None or source.sha256 != entry['sha256']:
            return unavailable('source_identity_mismatch', selection.source_index)
        document = json.loads(source.content)
        if not isinstance(document, dict):
            return unavailable('source_document_invalid', selection.source_index)
        source_columns = document.get('columns', [])
        rows = document.get('rows', [])
        if (len(set(source_columns)) != len(source_columns)
                or selection.label_field not in source_columns
                or selection.value_field not in source_columns or not 1 <= len(rows) <= 480
                or any(not isinstance(row, list) or len(row) != len(source_columns) for row in rows)):
            return unavailable('source_table_or_fields_invalid', selection.source_index)
        category_field = getattr(selection, 'category_field', None)
        category_value = getattr(selection, 'category_value', None)
        if (category_field is None) != (category_value is None):
            return unavailable('source_category_selection_incomplete', selection.source_index)
        if category_field is not None:
            if category_field not in source_columns:
                return unavailable('source_category_field_missing', selection.source_index)
            rows = [row for row in rows if row[source_columns.index(category_field)] == category_value]
        label_index = source_columns.index(selection.label_field)
        value_index = source_columns.index(selection.value_field)
        rows = [row for row in rows if row[label_index] not in getattr(selection, 'excluded_labels', ())]
        current_labels = [row[label_index] for row in rows]
        values = [row[value_index] for row in rows]
        mode = getattr(selection, 'label_mode', 'exact')
        if mode in {'month', 'month_of_year'}:
            try:
                current_labels = [month_label(label) for label in current_labels]
            except ValueError:
                return unavailable('source_month_labels_invalid', selection.source_index)
            if mode == 'month_of_year':
                year = getattr(selection, 'period_year', None)
                if year is None or any(int(label[:4]) != year for label in current_labels):
                    return unavailable('source_period_year_mismatch', selection.source_index)
                source_periods = current_labels
                current_labels = [label[5:] for label in current_labels]
        if selected_labels:
            if len(set(selected_labels)) != len(selected_labels) or not set(selected_labels).issubset(current_labels):
                return unavailable('source_selected_labels_missing_or_duplicate', selection.source_index)
            pairs = [(label, value) for label, value in zip(current_labels, values, strict=True) if label in selected_labels]
            current_labels, values = map(list, zip(*pairs, strict=True))
        if len(set(current_labels)) != len(current_labels):
            return unavailable('source_labels_duplicate', selection.source_index)
        if (not 1 <= len(current_labels) <= max_labels
                or any(not isinstance(label, str) or not label for label in current_labels)
                or any(not (allow_nulls and value is None) and (
                    not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(value)) for value in values)):
            return unavailable('source_labels_or_values_invalid', selection.source_index)
        if labels is None:
            labels = current_labels
        elif set(labels) != set(current_labels):
            return unavailable('source_label_sets_differ', selection.source_index)
        column_meta = document.get('columnMeta') or {}
        if not isinstance(column_meta, dict):
            return unavailable('source_metadata_invalid', selection.source_index)
        meta = column_meta.get(selection.value_field, {})
        if not valid_standard_metadata(meta):
            return unavailable('source_metadata_invalid', selection.source_index)
        if not meta.get('unit'):
            return unavailable('source_unit_missing', selection.source_index)
        if mode == 'month_of_year':
            meta = {**meta, 'periods': [period for period in source_periods if period[5:] in current_labels]}
        lookup = dict(zip(current_labels, values, strict=True))
        series.append([lookup[label] for label in labels])
        metadata[selection.series_name] = meta
        identities.append((source.path, source.sha256))
        used_sources.add(selection.source_index)
    if used_sources != set(range(len(entries))):
        return unavailable('source_not_used')
    return {'columns': columns, 'rows': [[label, *(values[index] for values in series)]
                                        for index, label in enumerate(labels or [])],
            'columnMeta': metadata}, identities
