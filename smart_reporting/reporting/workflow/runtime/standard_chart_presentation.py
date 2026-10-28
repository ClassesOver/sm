"""Deterministic report presentation derived from frozen table rows."""
from __future__ import annotations

import math
from datetime import date

from ...units import unit_conversion_scale


def order_standard_rows(document, label, policy):
    columns, rows = document['columns'], document['rows']
    position = columns.index(label)
    if any(not isinstance(row[position], str) or not row[position] for row in rows):
        return None
    labels = list(dict.fromkeys(row[position] for row in rows))
    if policy.mode == 'value':
        if policy.field not in columns or len(labels) != len(rows):
            return None
        index = columns.index(policy.field)
        if policy.exclude_missing:
            rows = [row for row in rows if row[index] is not None]
        if any(not _finite(row[index]) for row in rows):
            return None
        rows = sorted(rows, key=lambda row: row[index], reverse=policy.descending)
        labels = [row[position] for row in rows]
    elif policy.exclude_missing or policy.field is not None:
        return None
    elif policy.mode == 'explicit':
        if len(set(policy.labels)) != len(policy.labels) or set(policy.labels) != set(labels):
            return None
        labels = list(policy.labels)
    elif policy.labels:
        return None
    elif policy.mode == 'reverse':
        labels.reverse()
    elif policy.mode == 'label':
        labels = sorted(labels, reverse=policy.descending)
    if policy.limit is not None:
        labels = labels[:policy.limit]
    positions = {value: index for index, value in enumerate(labels)}
    rows = sorted((row for row in rows if row[position] in positions), key=lambda row: positions[row[position]])
    return {**document, 'rows': rows} if rows else None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def format_standard_number(value, precision=2, show_sign=False):
    # Never turn a nonzero frozen value into a displayed zero.
    scientific = value != 0 and (abs(value) < .5 * 10 ** -precision or abs(value) >= 1e12)
    return format(value, ('+' if show_sign else '') + (f'.{max(2, precision)}e' if scientific else f',.{precision}f'))


def frozen_label(spec, document, row):
    columns = document['columns']
    metadata = document.get('columnMeta') or {}
    if not isinstance(metadata, dict):
        return None
    if spec.field:
        if spec.field not in columns:
            return None
        meta = metadata.get(spec.field, {})
        if not isinstance(meta, dict):
            return None
        value = row[columns.index(spec.field)]
        unit = meta.get('unit')
        if not unit or not _finite(value):
            return None
        if unit == '%' and meta.get('isPercent') is False:
            value *= 100
        caption = spec.caption if spec.caption is not None else spec.field
    else:
        if spec.numerator not in columns or spec.denominator not in columns:
            return None
        numerator = row[columns.index(spec.numerator)]
        denominator = row[columns.index(spec.denominator)]
        left, right = metadata.get(spec.numerator, {}), metadata.get(spec.denominator, {})
        if not isinstance(left, dict) or not isinstance(right, dict):
            return None
        if (not _finite(numerator) or not _finite(denominator) or denominator <= 0
                or not left.get('unit') or left.get('unit') != right.get('unit')
                or left.get('isPercent') != right.get('isPercent')):
            return None
        value, unit = numerator / denominator * 100, '%'
        caption = spec.caption if spec.caption is not None else '比率'
    if spec.display_unit:
        scale = unit_conversion_scale(unit, spec.display_unit)
        if scale is None:
            return None
        value *= float(scale)
        unit = spec.display_unit
    if not _finite(value):
        return None
    number = format_standard_number(value, spec.decimals, spec.show_sign)
    return f'{caption} {number}{unit}' if caption else f'{number}{unit}'


def prepare_standard_presentation(policy, document, original, label, names, labels, category=None):
    result = policy.model_dump()
    result['extras'] = {}
    result['badges'] = []
    result['display_labels'] = labels
    if policy.label_mode == 'month':
        try:
            dates = [date.fromisoformat(value if len(value) == 10 else value + '-01') for value in labels]
        except (ValueError, TypeError):
            return None
        if len({value.year for value in dates}) != 1 or len({value.month for value in dates}) != len(dates):
            return None
        result['display_labels'] = [f'{value.month}月' for value in dates]
    for spec in policy.summaries:
        rows = original['rows']
        if spec.label is not None:
            columns = original['columns']
            text_columns = [i for i in range(len(columns)) if all(isinstance(row[i], str) for row in rows)]
            if len(text_columns) != 1:
                return None
            rows = [row for row in rows if row[text_columns[0]] == spec.label]
        if len(rows) != 1:
            return None
        value = frozen_label(spec, original, rows[0])
        if value is None:
            return None
        result['badges'].append((value, spec.color))
    if policy.label_formats:
        columns = document['columns']
        if any(not set(spec.series).issubset(names) for spec in policy.label_formats):
            return None
        for row in document['rows']:
            selected_names = [row[columns.index(category)]] if category else names
            for name in selected_names:
                text = [frozen_label(spec, document, row) for spec in policy.label_formats if not spec.series or name in spec.series]
                if any(value is None for value in text):
                    return None
                result['extras'][(row[columns.index(label)], name)] = ' / '.join(value for value in text if value is not None)
    return result


PRESENTATION_SCRIPT = '''def format_standard_number(value, precision=2, show_sign=False):
    scientific = value != 0 and (abs(value) < .5 * 10 ** -precision or abs(value) >= 1e12)
    return format(value, ("+" if show_sign else "") + (f".{max(2, precision)}e" if scientific else f",.{precision}f"))

def standard_values_label_visible(index, series_index, annotations, series):
    import math
    values = series[series_index]
    finite = [value for value in values if math.isfinite(value)]
    for kind, selected, first, last in annotations:
        if selected != series_index:
            continue
        if kind == "point" and index == first:
            return False
        if kind in ("peak", "trough") and finite and values[index] == (max(finite) if kind == "peak" else min(finite)):
            return False
    return True

def standard_label_names(labels, canvas):
    return canvas["presentation"]["display_labels"]

def standard_annotation(ax, text, xy, canvas, number, color=None, highlight=False):
    from matplotlib.text import Annotation
    spec = canvas["annotation_specs"][number]
    style = canvas["style"]
    color = spec["color"] or color or "#475569"
    position = spec["position"]
    dx, dy = style["annotation_offset_x"], style["annotation_offset_y"]
    if position == "below":
        dy = -abs(dy) - 6
    elif position == "left":
        dx, dy = -abs(dx) - 8, 0
    elif position == "right":
        dx, dy = abs(dx) + 5, 0
    elif position == "above":
        dy = abs(dy) + 4
    annotation = ax.annotate(text, xy, xytext=(dx, dy), textcoords="offset points",
        fontsize=style["annotation_font_size"], color=color,
        ha="right" if position == "left" else "center" if dx == 0 else "left",
        va="top" if dy < 0 else "bottom" if dy > 0 else "center",
        arrowprops={"arrowstyle": "-", "color": color, "lw": .7} if style["annotation_leader"] else None)
    annotation._standard_custom_position = True
    if spec["highlight"] or highlight:
        ax.scatter([xy[0]], [xy[1]], s=85, color=color, edgecolors="white", linewidths=1.5, zorder=6)
    return annotation

def finish_standard_presentation(fig, canvas):
    import textwrap
    presentation = canvas["presentation"]
    width, height = fig.get_size_inches()
    title_size = canvas["style"]["title_font_size"]
    cursor = .982
    if fig._suptitle is None and len(fig.axes) == 1:
        heading = fig.axes[0].get_title()
        fig.axes[0].set_title("")
        fig.suptitle(heading)
    if fig._suptitle is not None:
        heading = textwrap.fill(fig._suptitle.get_text(), max(12, int(width * 72 * .87 / title_size)))
        fig._suptitle.set_text(heading)
        fig._suptitle.set_position((.065, .982))
        fig._suptitle.set_ha("left")
        fig._suptitle.set_fontsize(canvas["style"]["title_font_size"])
        fig._suptitle.set_fontweight("bold" if canvas["style"]["theme"] == "report" else "normal")
        fig._suptitle.set_color("#1e293b")
        cursor -= len(heading.splitlines()) * title_size / 72 / height * 1.35 + .025
    if presentation["subtitle"]:
        subtitle = textwrap.fill(presentation["subtitle"], max(16, int(width * 72 * .87 / 10)))
        fig.text(.065, cursor, subtitle,
                 ha="left", va="top", fontsize=10, color="#64748b")
        cursor -= len(subtitle.splitlines()) * 10 / 72 / height * 1.5 + .025
    footer_height = .02
    if presentation["source_note"]:
        source = textwrap.fill(presentation["source_note"], max(20, int(width * 72 * .87 / 8)))
        fig.text(.065, .022, source,
                 ha="left", va="bottom", fontsize=8, color="#64748b")
        footer_height = .055 + len(source.splitlines()) * 8 / 72 / height * 1.4
    badges = presentation["badges"]
    if badges:
        cursor -= .03
    for index, (text, color) in enumerate(badges):
        fig.text(.5 + (index - (len(badges) - 1) / 2) * .22, cursor, text,
                 ha="center", va="center", fontsize=11, color=color,
                 bbox={"boxstyle": "round,pad=.55", "fc": "#f8fafc", "ec": color, "lw": .7})
    presentation["header_bottom"] = cursor - (.06 if badges else .015)
    presentation["footer_top"] = footer_height
    if presentation["header_bottom"] - footer_height < .3:
        raise ValueError("standard_chart_layout_unresolved: 标题脚注占用过多，请扩大画布或简写")

'''
