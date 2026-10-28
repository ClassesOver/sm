"""Conservative static templates over identity-checked chart inputs."""
from __future__ import annotations

import json
import math

from ...units import unit_conversion_scale
from .chart_inputs import ChartInputMaterialization
from .phase_models import StandardChartAxes, VisualizationPlanDraft
from .standard_chart_alignment import align_chart_sources


def standard_visualization_script(
    plan: VisualizationPlanDraft, inputs: ChartInputMaterialization,
) -> str | None:
    if inputs.fallback_chart_ids or not plan.charts:
        return None
    configs = []
    aligned = {}
    auxiliary = {}
    displays = {}
    for chart in plan.charts:
        if chart.renderer != 'matplotlib' or chart.interactive_path:
            return None
        form = {'line': 'line', '折线图': 'line', '多系列折线图': 'line',
                'bar': 'bar', '柱状图': 'bar', '分组柱状图': 'bar',
                'barh': 'barh', '横向条形图': 'barh',
                'stacked-bar': 'stacked-bar', '堆叠柱状图': 'stacked-bar',
                'stacked-area': 'stacked-area', '堆叠面积图': 'stacked-area',
                'stacked-total': 'stacked-total', '堆叠柱合计折线图': 'stacked-total',
                'summary-bars': 'summary-bars', '单行指标对比图': 'summary-bars'}.get(chart.visual_form)
        entries = [entry for entry in inputs.entries if entry['chartId'] == chart.chart_id]
        if form is None or not entries:
            return None
        entry = entries[0]
        source = next((item for item in inputs.files if item.path == entry['path']), None)
        if source is None or source.sha256 != entry['sha256']:
            return None
        document = json.loads(source.content)
        selected = tuple(getattr(chart, 'standard_value_fields', ()))
        if form == 'summary-bars':
            original_columns = document.get('columns', [])
            original_rows = document.get('rows', [])
            original_meta = document.get('columnMeta', {})
            if (len(original_rows) != 1 or len(selected) < 2
                    or len(set(selected)) != len(selected) or not set(selected).issubset(original_columns)):
                return None
            selected_meta = [original_meta.get(column, {}) for column in selected]
            if (any(not meta.get('unit') for meta in selected_meta)
                    or any(meta != selected_meta[0] for meta in selected_meta)):
                return None
            document = {'columns': ['label', 'value'],
                        'rows': [[column, original_rows[0][original_columns.index(column)]] for column in selected],
                        'columnMeta': {'value': selected_meta[0]}}
            aligned[source.path] = (document, [(source.path, source.sha256)])
            selected = ('value',)
            form = 'bar'
        selections = getattr(chart, 'standard_sources', ())
        if len(entries) > 1:
            alignment = align_chart_sources(entries, inputs.files, selections)
            if alignment is None:
                return None
            document, identities = alignment
            aligned[source.path] = (document, identities)
        elif selections:
            return None
        columns, rows = document['columns'], document['rows']
        if (not isinstance(columns, list) or not columns
                or any(not isinstance(column, str) or not column for column in columns)
                or len(set(columns)) != len(columns)
                or not 1 <= len(rows) <= 480
                or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)):
            return None
        label = 'period' if 'period' in columns else 'label' if 'label' in columns else None
        if label is None:
            text_columns = [column for column in columns
                            if all(isinstance(row[columns.index(column)], str) for row in rows)]
            if len(text_columns) == 1:
                label = text_columns[0]
        if label is None:
            return None
        label_index = columns.index(label)
        selected_labels = tuple(getattr(chart, 'standard_labels', ()))
        if selected_labels:
            if (len(set(selected_labels)) != len(selected_labels)
                    or not set(selected_labels).issubset(row[label_index] for row in rows)):
                return None
            rows = [row for row in rows if row[label_index] in selected_labels]
            document = {**document, 'rows': rows}
            dependencies = aligned.get(source.path, (None, [(source.path, source.sha256)]))[1]
            aligned[source.path] = (document, dependencies)
        labels = [row[label_index] for row in rows]
        if any(not isinstance(value, str) or not value for value in labels):
            return None
        other_columns = [column for column in columns if column != label]
        category_columns = [column for column in other_columns
                            if all(isinstance(row[columns.index(column)], str) for row in rows)]
        category = category_columns[0] if len(category_columns) == 1 else None
        values = [column for column in other_columns if column != category]
        if selected:
            if len(set(selected)) != len(selected) or not set(selected).issubset(values):
                return None
            values = list(selected)
        if not 1 <= len(values) <= 8 or (category and (label != 'period' or len(values) != 1)):
            return None
        if any(not isinstance(row[columns.index(column)], (int, float))
               or isinstance(row[columns.index(column)], bool)
               or not math.isfinite(row[columns.index(column)]) for row in rows for column in values):
            return None
        metadata = document.get('columnMeta') or {}
        if not isinstance(metadata, dict):
            return None
        metas = [metadata.get(column, {}) for column in values]
        if any(not isinstance(meta, dict) for meta in metas):
            return None
        axes = getattr(chart, 'standard_axes', StandardChartAxes())
        advanced = axes.mode != 'single' or axes.scale != 'linear'
        display_unit = getattr(chart, 'standard_display_unit', None)
        if display_unit:
            scales = [unit_conversion_scale(meta.get('unit'), display_unit) for meta in metas]
            if advanced or None in scales or len(set(scales)) != 1:
                return None
            scale = scales[0]
            assert scale is not None
            displays[source.path] = (float(scale), display_unit)
        auxiliary_fields = tuple(getattr(chart, 'standard_label_fields', ()))
        if auxiliary_fields:
            if (advanced or len(auxiliary_fields) != len(set(auxiliary_fields))
                    or not set(auxiliary_fields).issubset(columns)):
                return None
            for field in auxiliary_fields:
                meta = metadata.get(field, {})
                if not isinstance(meta, dict) or not meta.get('unit') or any(
                    not isinstance(row[columns.index(field)], (int, float))
                    or isinstance(row[columns.index(field)], bool)
                    or not math.isfinite(row[columns.index(field)]) for row in rows
                ):
                    return None
            auxiliary[source.path] = auxiliary_fields
        right = tuple(axes.right_fields)
        if (axes.mode != 'dual' and right) or (axes.mode != 'zoom' and (axes.zoom_start or axes.zoom_end)):
            return None
        if advanced:
            if category or form not in {'line', 'bar'} or any(not meta.get('unit') for meta in metas):
                return None
            if axes.mode == 'dual' and (
                not right or len(right) != len(set(right))
                or not set(right) < set(values)
            ):
                return None
            groups = ([list(range(len(values)))] if axes.mode in {'single', 'zoom'} else
                      [[index for index, value in enumerate(values) if value not in right],
                       [values.index(value) for value in right]] if axes.mode == 'dual' else
                      [[index] for index in range(len(values))])
            if any(len({(metas[index].get('unit'), metas[index].get('isPercent'))
                        for index in group}) != 1 for group in groups):
                return None
            windows = [meta.get('periods') for meta in metas]
            if any(window != windows[0] for window in windows):
                return None
            if axes.scale == 'log' and (form != 'line' or any(
                row[columns.index(column)] <= 0 for row in rows for column in values
            )):
                return None
            if axes.mode == 'zoom' and (
                axes.zoom_start not in labels or axes.zoom_end not in labels
                or labels.index(axes.zoom_start) > labels.index(axes.zoom_end)
            ):
                return None
        # 同轴系列必须有明确且完全一致的单位、比例显示尺度；不推断换算。
        if not advanced and len(values) > 1 and (
            any(not meta.get('unit') for meta in metas)
            or len({(meta.get('unit'), meta.get('isPercent')) for meta in metas}) != 1
        ):
            return None
        if form in {'line', 'stacked-bar', 'stacked-area', 'stacked-total'} and len(values) > 1:
            windows = [meta.get('periods') for meta in metas]
            if any(window != windows[0] for window in windows):
                return None
        if category:
            category_index = columns.index(category)
            keys = [(row[label_index], row[category_index]) for row in rows]
            categories = list(dict.fromkeys(row[category_index] for row in rows))
            if (any(not value for value in categories) or len(categories) > 8
                    or len(set(keys)) != len(keys)):
                return None
            # 长表缺失组合只允许折线断点；构成图和柱图不补零。
            if form != 'line' and len(keys) != len(set(labels)) * len(categories):
                return None
        elif len(set(labels)) != len(labels):
            return None
        if len(set(labels)) > 60:
            return None
        if form in {'stacked-bar', 'stacked-area', 'stacked-total'} and any(
            row[columns.index(column)] < 0 for row in rows for column in values
        ):
            return None
        total_field = getattr(chart, 'standard_total_field', None)
        if total_field is not None:
            if form != 'stacked-total' or category or total_field not in values or len(values) < 2:
                return None
            if any(not math.isclose(
                math.fsum(row[columns.index(column)] for column in values if column != total_field),
                row[columns.index(total_field)], rel_tol=1e-12, abs_tol=1e-9,
            ) for row in rows):
                return None
        annotation_names = categories if category else values
        annotation_labels = list(dict.fromkeys(labels))
        annotations: list[tuple[str, int | None, int | None, int | None]] = []
        first: int | None
        for specification in getattr(chart, 'standard_annotations', ()):
            kind = specification.kind
            if kind == 'range':
                if (specification.series is not None or specification.label not in annotation_labels
                        or specification.end_label not in annotation_labels):
                    return None
                first = annotation_labels.index(specification.label)
                last = annotation_labels.index(specification.end_label)
                if first > last:
                    return None
                annotations.append((kind, None, first, last))
                continue
            name = specification.series
            if name is None and len(annotation_names) == 1:
                name = annotation_names[0]
            if name not in annotation_names or specification.end_label is not None:
                return None
            if kind in {'point', 'reference'}:
                if specification.label not in annotation_labels:
                    return None
                first = annotation_labels.index(specification.label)
                if category and (specification.label, name) not in keys:
                    return None
            elif kind in {'values', 'peak', 'trough'} and specification.label is None:
                first = None
            else:
                return None
            annotations.append((kind, annotation_names.index(name), first, None))
        if sum(len(annotation_labels) if item[0] in {'values', 'peak', 'trough'} else 1
               for item in annotations) > 60:
            return None
        configs.append((source.path, source.sha256, chart.source_path, chart.title,
                        form, label, values, category, metas[0].get('unit'),
                        metas[0].get('isPercent'), annotations,
                        axes.model_dump(), metas, total_field))
    return ('CONFIGS = ' + repr(configs) + '\nALIGNED = ' + repr(aligned)
            + '\nAUXILIARY = ' + repr(auxiliary) + '\nDISPLAYS = ' + repr(displays)
            + '\n' + _LAYOUT + _ADVANCED + _BODY)


_LAYOUT = '''def finish_standard_layout(fig):
    import textwrap
    from matplotlib.text import Annotation
    for ax in fig.axes:
        for axis, ticks, setter in ((ax.xaxis, ax.get_xticks(), ax.set_xticks),
                                    (ax.yaxis, ax.get_yticks(), ax.set_yticks)):
            texts = [tick.get_text() for tick in axis.get_ticklabels()]
            if any(len(text) > 14 for text in texts):
                setter(ticks, [textwrap.fill(text, width=14, break_long_words=True) for text in texts])
            for tick in axis.get_ticklabels():
                tick.set_fontsize(9)
        legend = ax.get_legend()
        if legend is not None and len(legend.get_texts()) > 3:
            legend.set_bbox_to_anchor((1.01, 1))
            legend.set_loc("upper left")
    fig.tight_layout()
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    annotations = [text for ax in fig.axes for text in ax.texts if isinstance(text, Annotation)]
    placed = []
    for annotation in annotations:
        for attempt in range(16):
            # Exclude the leader line: only text glyph bounds define collisions.
            from matplotlib.text import Text
            bounds = Text.get_window_extent(annotation, renderer).expanded(1.04, 1.12)
            if not any(bounds.overlaps(previous) for previous in placed):
                placed.append(bounds)
                break
            x, y = annotation.get_position()
            annotation.set_position((x, y + 12))
            annotation.update_positions(renderer)
        else:
            raise ValueError("standard_chart_layout_unresolved: 标注重叠，请减少密度或调整布局")

'''


_ADVANCED = '''def render_advanced(labels, names, raw_series, metadata, policy, form, title, output_path, annotations):
    import math
    import matplotlib.pyplot as plt
    mode = policy["mode"]
    series = [[value * (100 if meta.get("unit") == "%" and meta.get("isPercent") is False else 1)
               for value in values] for values, meta in zip(raw_series, metadata, strict=True)]
    positions = list(range(len(labels)))
    if mode == "panels":
        fig, panels = plt.subplots(len(series), 1, sharex=True, squeeze=False,
                                   figsize=(10, max(6, 2.5 * len(series))), dpi=150)
        axes = [panel[0] for panel in panels]
        targets = axes
    else:
        fig, primary = plt.subplots(figsize=(11, 7), dpi=150)
        axes = [primary]
        secondary = primary.twinx() if mode == "dual" else None
        if secondary is not None:
            axes.append(secondary)
        targets = [secondary if name in policy["right_fields"] else primary for name in names]
    colors = plt.get_cmap("tab10")
    for index, (name, values, target, meta) in enumerate(zip(names, series, targets, metadata, strict=True)):
        side = "右轴" if mode == "dual" and name in policy["right_fields"] else "左轴"
        caption = f"{name} · {side}" if mode == "dual" else name
        if form == "bar" and not (mode == "dual" and side == "右轴"):
            members = [i for i, item in enumerate(targets) if item is target]
            width = 0.8 / len(members)
            offsets = [position - .4 + width / 2 + members.index(index) * width for position in positions]
            target.bar(offsets, values, width=width, color=colors(index), label=caption)
        else:
            target.plot(positions, values, marker="o", color=colors(index), label=caption)
        target.set_ylabel(f"{side} · {meta['unit']}" if mode == "dual" else meta["unit"])
        target.set_yscale(policy["scale"])
        target.set_xticks(positions, labels, rotation=45, ha="right")
        if mode == "panels":
            target.set_title(f"{name}（独立纵轴）", fontsize=10)
    for target in axes:
        target.legend(frameon=False, loc="upper left" if target is axes[0] else "upper right")
        target.grid(axis="y", linestyle="--", alpha=.2)
        if policy["scale"] == "log":
            target.set_ylabel(target.get_ylabel() + "（对数刻度）")
    for number, (kind, series_index, first, last) in enumerate(annotations):
        if kind == "range":
            for target in axes:
                target.axvspan(first - .4, last + .4, alpha=.12, color="#f59e0b")
            continue
        target = targets[series_index]
        values = series[series_index]
        unit = metadata[series_index]["unit"]
        if kind == "reference":
            target.axhline(values[first], color="#b45309", linestyle="--")
            target.text(.01, .98 - number * .05, f"参考 {labels[first]}: {values[first]:,.2f}{unit}",
                        transform=target.transAxes, va="top", fontsize=8)
            continue
        indexes = ([first] if kind == "point" else
                   [index for index, value in enumerate(values) if kind == "values" or
                    value == (max(values) if kind == "peak" else min(values))])
        for index in indexes:
            coordinate = index
            if form == "bar" and not (mode == "dual" and names[series_index] in policy["right_fields"]):
                members = [i for i, item in enumerate(targets) if item is target]
                width = .8 / len(members)
                coordinate = index - .4 + width / 2 + members.index(series_index) * width
            target.annotate(f"{names[series_index]}: {values[index]:,.2f}{unit}",
                            (coordinate, values[index]), xytext=(6, 8 + number * 6),
                            textcoords="offset points", fontsize=8,
                            arrowprops={"arrowstyle": "-"})
    if mode == "zoom":
        first = labels.index(policy["zoom_start"])
        last = labels.index(policy["zoom_end"])
        inset = axes[0].inset_axes([.56, .5, .4, .4])
        local_values = []
        for index, values in enumerate(series):
            if form == "bar":
                width = .8 / len(series)
                offsets = [position - .4 + width / 2 + index * width for position in positions]
                inset.bar(offsets, values, width=width, color=colors(index))
            else:
                inset.plot(positions, values, marker="o", color=colors(index))
            local_values.extend(values[first:last + 1])
        low, high = min(local_values), max(local_values)
        padding = (high - low) * .1 or abs(high) * .1 or 1
        inset.set_xlim(first - .2, last + .2)
        if policy["scale"] == "log":
            inset.set_yscale("log")
            inset.set_ylim(low / 1.2, high * 1.2)
        else:
            inset.set_ylim(low - padding, high + padding)
        inset.set_xticks(positions[first:last + 1], labels[first:last + 1], rotation=45, fontsize=7)
        inset.set_title("局部放大 · " + metadata[0]["unit"], fontsize=9)
        axes[0].axvspan(first - .2, last + .2, color="#f59e0b", alpha=.1)
    fig.suptitle(title)
    finish_standard_layout(fig)
    fig.savefig(output_path, bbox_inches="tight", pad_inches=.25)
    plt.close(fig)

'''


_BODY = '''import hashlib
import json
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
for input_path, digest, output_path, title, form, label_column, value_columns, category_column, unit, is_percent, annotations, axes_policy, metadata, total_field in CONFIGS:
    with open(input_path, "rb") as handle:
        raw = handle.read()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("chart input identity changed")
    payload = json.loads(raw)
    if input_path in ALIGNED:
        payload, dependencies = ALIGNED[input_path]
        for dependency_path, dependency_digest in dependencies:
            with open(dependency_path, "rb") as handle:
                dependency_raw = handle.read()
            if hashlib.sha256(dependency_raw).hexdigest() != dependency_digest:
                raise ValueError("aligned chart input identity changed")
    columns = payload["columns"]
    label_index = columns.index(label_column)
    labels = list(dict.fromkeys(row[label_index] for row in payload["rows"]))
    if category_column:
        category_index = columns.index(category_column)
        names = list(dict.fromkeys(row[category_index] for row in payload["rows"]))
        cells = {(row[label_index], row[category_index]): row[columns.index(value_columns[0])]
                 for row in payload["rows"]}
        series = [[cells.get((label, name), float("nan")) for label in labels] for name in names]
    else:
        names = value_columns
        series = [[row[columns.index(column)] for row in payload["rows"]] for column in names]
    if axes_policy["mode"] != "single" or axes_policy["scale"] != "linear":
        render_advanced(labels, names, series, metadata, axes_policy, form, title, output_path, annotations)
        continue
    if unit == "%" and is_percent is False:
        series = [[value * 100 for value in values] for values in series]
    if input_path in DISPLAYS:
        factor, unit = DISPLAYS[input_path]
        series = [[value * factor for value in values] for values in series]
    width = min(18, max(10, len(labels) * .45)) if form != "barh" else 12
    height = min(20, max(6, len(labels) * .42)) if form == "barh" else 7
    fig, ax = plt.subplots(figsize=(width, height), dpi=150)
    positions = list(range(len(labels)))
    if form == "stacked-area":
        ax.stackplot(positions, *series, labels=names)
    else:
        bottom = [0.0] * len(labels)
        width = 0.8 / len(series)
        for index, (name, values) in enumerate(zip(names, series, strict=True)):
            if name == total_field:
                continue
            if form == "line":
                ax.plot(positions, values, marker="o", label=name)
            elif form in {"stacked-bar", "stacked-total"}:
                ax.bar(positions, values, bottom=bottom, label=name)
                bottom = [left + right for left, right in zip(bottom, values, strict=True)]
            else:
                offsets = [position - 0.4 + width / 2 + index * width for position in positions]
                if form == "barh":
                    ax.barh(offsets, values, height=width, label=name)
                else:
                    ax.bar(offsets, values, width=width, label=name)
    if form == "stacked-total":
        totals = (series[names.index(total_field)] if total_field else
                  [math.fsum(values[index] for values in series) for index in positions])
        caption = total_field + "（独立冻结总额，已对账）" if total_field else "分项合计（服务端求和）"
        ax.plot(positions, totals, marker="o", color="black", label=caption)
    if form == "barh":
        ax.set_yticks(positions, labels)
        ax.invert_yaxis()
        ax.set_xlabel(unit or "")
    else:
        ax.set_xticks(positions, labels, rotation=45, ha="right")
        ax.set_ylabel(unit or "")
    if len(series) > 1 or form == "stacked-total":
        ax.legend(frameon=False)
    for annotation_index, (kind, series_index, first, last) in enumerate(annotations):
        if kind == "range":
            span = ax.axhspan if form == "barh" else ax.axvspan
            span(first - 0.4, last + 0.4, color="#f59e0b", alpha=0.12)
            continue
        values = series[series_index]
        finite = [value for value in values if math.isfinite(value)]
        if not finite:
            continue
        if kind == "reference":
            draw = ax.axvline if form == "barh" else ax.axhline
            draw(values[first], linestyle="--", color="#b45309", alpha=0.8)
            ax.text(0.01, 0.98 - annotation_index * 0.05,
                    f"参考 {labels[first]} · {names[series_index]}: {values[first]:,.2f}{unit or ''}",
                    transform=ax.transAxes, va="top", fontsize=8)
            continue
        indexes = ([first] if kind == "point" else
                   [index for index, value in enumerate(values) if math.isfinite(value) and
                    (kind == "values" or value == (max(finite) if kind == "peak" else min(finite)))])
        for index in indexes:
            value = values[index]
            coordinate = index
            height = value
            if form in {"stacked-bar", "stacked-area", "stacked-total"} and names[series_index] != total_field:
                height += sum(previous[index] for previous_name, previous in zip(names[:series_index], series[:series_index], strict=True)
                              if previous_name != total_field)
            elif form in {"bar", "barh"}:
                coordinate = index - 0.4 + 0.4 / len(series) + series_index * 0.8 / len(series)
            xy = (height, coordinate) if form == "barh" else (coordinate, height)
            prefix = {"peak": "峰值 ", "trough": "谷值 ", "point": "重点 "}.get(kind, "")
            auxiliary_text = []
            for field in AUXILIARY.get(input_path, ()):
                matching = [row for row in payload["rows"] if row[label_index] == labels[index]
                            and (not category_column or row[category_index] == names[series_index])]
                if len(matching) != 1:
                    raise ValueError("annotation row is ambiguous")
                meta = payload["columnMeta"][field]
                auxiliary_value = matching[0][columns.index(field)]
                if meta["unit"] == "%" and meta.get("isPercent") is False:
                    auxiliary_value *= 100
                auxiliary_text.append(f"{field}: {auxiliary_value:,.2f}{meta['unit']}")
            suffix = " · " + " / ".join(auxiliary_text) if auxiliary_text else ""
            ax.annotate(f"{prefix}{value:,.2f}{unit or ''}{suffix}", xy,
                        xytext=(8, 8 + annotation_index * 8), textcoords="offset points",
                        fontsize=8, arrowprops={"arrowstyle": "-", "color": "#64748b"})
    ax.set_title(title)
    ax.spines[["top", "right"]].set_visible(False)
    finish_standard_layout(fig)
    fig.savefig(output_path, bbox_inches="tight", pad_inches=.25)
    plt.close(fig)
'''
