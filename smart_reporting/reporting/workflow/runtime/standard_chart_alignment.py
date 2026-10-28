"""Exact-label alignment of frozen, explicitly selected chart inputs."""
import json
import math


def align_chart_sources(entries, files, selections):
    if len(entries) < 2 or not selections or len(selections) > 8:
        return None
    names = [selection.series_name for selection in selections]
    if len(names) != len(set(names)) or 'period' in names:
        return None
    labels = None
    columns = ['period', *names]
    series = []
    metadata = {}
    identities = []
    used_sources = set()
    for selection in selections:
        if selection.source_index >= len(entries):
            return None
        entry = entries[selection.source_index]
        source = next((item for item in files if item.path == entry['path']), None)
        if source is None or source.sha256 != entry['sha256']:
            return None
        document = json.loads(source.content)
        source_columns = document.get('columns', [])
        rows = document.get('rows', [])
        if (len(set(source_columns)) != len(source_columns)
                or selection.label_field not in source_columns
                or selection.value_field not in source_columns or not 1 <= len(rows) <= 480
                or any(not isinstance(row, list) or len(row) != len(source_columns) for row in rows)):
            return None
        category_field = getattr(selection, 'category_field', None)
        category_value = getattr(selection, 'category_value', None)
        if (category_field is None) != (category_value is None):
            return None
        if category_field is not None:
            if category_field not in source_columns:
                return None
            rows = [row for row in rows if row[source_columns.index(category_field)] == category_value]
        if not 1 <= len(rows) <= 60:
            return None
        label_index = source_columns.index(selection.label_field)
        value_index = source_columns.index(selection.value_field)
        current_labels = [row[label_index] for row in rows]
        values = [row[value_index] for row in rows]
        if (any(not isinstance(label, str) or not label for label in current_labels)
                or len(set(current_labels)) != len(current_labels)
                or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                       or not math.isfinite(value) for value in values)):
            return None
        if labels is None:
            labels = current_labels
        elif set(labels) != set(current_labels):
            return None
        meta = document.get('columnMeta', {}).get(selection.value_field, {})
        if not isinstance(meta, dict) or not meta.get('unit'):
            return None
        lookup = dict(zip(current_labels, values, strict=True))
        series.append([lookup[label] for label in labels])
        metadata[selection.series_name] = meta
        identities.append((source.path, source.sha256))
        used_sources.add(selection.source_index)
    if used_sources != set(range(len(entries))):
        return None
    return {'columns': columns, 'rows': [[label, *(values[index] for values in series)]
                                        for index, label in enumerate(labels or [])],
            'columnMeta': metadata}, identities
