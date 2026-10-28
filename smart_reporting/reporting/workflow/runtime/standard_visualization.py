"""Conservative static templates over identity-checked chart inputs."""
from __future__ import annotations

import json
import math

from ...units import unit_conversion_scale
from .chart_inputs import ChartInputMaterialization
from .phase_models import (
    StandardChartAxes,
    StandardChartCanvas,
    StandardChartPresentation,
    StandardChartStyle,
    VisualizationPlanDraft,
)
from .standard_chart_alignment import align_chart_sources
from .standard_chart_presentation import (
    PRESENTATION_SCRIPT,
    order_standard_rows,
    prepare_standard_presentation,
)


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
        canvas = getattr(chart, 'standard_canvas', StandardChartCanvas())
        style = getattr(chart, 'standard_style', StandardChartStyle())
        presentation = getattr(chart, 'standard_presentation', StandardChartPresentation())
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
        original_document = document
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
        ordered = order_standard_rows(document, label, presentation.order)
        if ordered is None:
            return None
        if ordered['rows'] != rows:
            document, rows = ordered, ordered['rows']
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
            if axes.zero_baseline and axes.scale == 'log':
                return None
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
        if any(item.series not in annotation_names for item in style.series):
            return None
        if any(item.series not in annotation_names or item.label not in annotation_labels for item in style.points):
            return None
        if category and any((item.label, item.series) not in keys for item in style.points):
            return None
        prepared = prepare_standard_presentation(presentation, document, original_document,
                                                 label, annotation_names, annotation_labels, category)
        if prepared is None:
            return None
        canvas_policy = canvas.model_dump()
        canvas_policy['style'] = style.model_dump()
        canvas_policy['presentation'] = prepared
        canvas_policy['annotation_specs'] = [item.model_dump() for item in getattr(chart, 'standard_annotations', ())]
        canvas_policy['series_names'] = annotation_names
        canvas_policy['labels'] = annotation_labels
        canvas_policy['zero_baseline'] = axes.zero_baseline
        canvas_policy['total_field'] = total_field
        configs.append((source.path, source.sha256, chart.source_path, chart.title,
                        form, label, values, category, metas[0].get('unit'),
                        metas[0].get('isPercent'), annotations,
                        axes.model_dump(), metas, total_field, canvas_policy))
    return ('CONFIGS = ' + repr(configs) + '\nALIGNED = ' + repr(aligned)
            + '\nAUXILIARY = ' + repr(auxiliary) + '\nDISPLAYS = ' + repr(displays)
            + '\n' + PRESENTATION_SCRIPT + _LAYOUT + _ADVANCED + _BODY)


_LAYOUT = '''def standard_series_name(artist, policy):
    label = artist.get_label()
    for name in policy["series_names"]:
        if label in (name, name + " · 左轴", name + " · 右轴", name + "（独立冻结总额，已对账）"):
            return name
    return "分项合计" if label == "分项合计（服务端求和）" else None

def standard_series_color(name, policy):
    import matplotlib.pyplot as plt
    overrides = {item["series"]: item for item in policy["style"]["series"]}
    if overrides.get(name, {}).get("color"):
        return overrides[name]["color"]
    if name == policy["total_field"] or name == "分项合计":
        return "#1f2937"
    index = policy["series_names"].index(name)
    if policy["style"]["palette"] == "report":
        return ["#3066a3", "#dc884d", "#36856b", "#b55d68", "#8573a6", "#58a3ae", "#b49b53", "#718096"][index % 8]
    palette = plt.get_cmap(policy["style"]["palette"])
    return palette(index / max(1, len(policy["series_names"]) - 1) if palette.N > 20 else index)

def apply_standard_style(fig, policy):
    from matplotlib.container import BarContainer
    from matplotlib.text import Annotation
    import matplotlib.pyplot as plt
    style = policy["style"]
    overrides = {item["series"]: item for item in style["series"]}
    all_axes = list(fig.axes)
    for ax in fig.axes:
        all_axes.extend(ax.child_axes)
    fig.set_facecolor(style["background"])
    for ax in all_axes:
        ax.set_facecolor(style["background"])
        for artist in [*ax.lines, *ax.containers, *ax.collections]:
            name = standard_series_name(artist, policy)
            if name is None:
                continue
            item = overrides.get(name, {})
            color = standard_series_color(name, policy)
            targets = artist.patches if isinstance(artist, BarContainer) else [artist]
            for target in targets:
                target.set_color(color)
                target.set_alpha(item.get("alpha", 1))
                if isinstance(artist, BarContainer):
                    target.set_hatch(item.get("hatch", ""))
                    target.set_edgecolor(color)
                elif artist in ax.lines:
                    target.set_linewidth(item.get("line_width", 2))
                    target.set_linestyle(item.get("line_style", "-"))
                    target.set_marker(item.get("marker", "o"))
                    target.set_markersize(item.get("marker_size", 5))
                    if style["theme"] == "report":
                        target.set_markeredgecolor("white")
                        target.set_markeredgewidth(.8)
            for point in style["points"]:
                if point["series"] != name:
                    continue
                index = policy["labels"].index(point["label"])
                if isinstance(artist, BarContainer):
                    artist.patches[index].set_facecolor(point["color"])
                    artist.patches[index].set_edgecolor(point["color"])
                elif artist in ax.lines:
                    ax.scatter([artist.get_xdata()[index]], [artist.get_ydata()[index]],
                               s=point["marker_size"] ** 2, color=point["color"],
                               edgecolors="white", linewidths=1, zorder=6)
        ax.grid(False)
        if style["grid"] != "none":
            ax.grid(axis=style["grid"], alpha=style["grid_alpha"], linestyle="--", color="#94a3b8", linewidth=.7)
        ax.set_axisbelow(True)
        ax.title.set_fontsize(style["title_font_size"])
        if style["theme"] == "report":
            ax.title.set_fontweight("bold")
            ax.title.set_color("#1e293b")
            ax.tick_params(axis="both", length=0, pad=8, colors="#475569")
            for key, spine in ax.spines.items():
                spine.set_color("#cbd5e1")
                spine.set_linewidth(.7)
                if key == "top" or key == "right" and len(fig.axes) == 1:
                    spine.set_visible(False)
        ax.xaxis.label.set_fontsize(style["axis_font_size"])
        ax.yaxis.label.set_fontsize(style["axis_font_size"])
        for tick in ax.get_xticklabels():
            tick.set_rotation(style["label_rotation"])
            tick.set_ha("right" if style["label_rotation"] > 0 else "left" if style["label_rotation"] < 0 else "center")
        ax.margins(**({"x": style["value_margin"]} if policy["horizontal"] else {"y": style["value_margin"]}))
        if policy["zero_baseline"]:
            low, high = ax.get_xlim() if policy["horizontal"] else ax.get_ylim()
            (ax.set_xlim if policy["horizontal"] else ax.set_ylim)(min(low, 0), max(high, 0))
        if ax.get_legend() is not None:
            location = style["legend_location"]
            if location == "auto":
                location = ("upper left" if ax is fig.axes[0] else "upper right") if len(fig.axes) > 1 else "best"
            ax.legend(frameon=False, loc=location,
                      ncols=style["legend_columns"], fontsize=style["legend_font_size"])
        for text in ax.texts:
            text.set_fontsize(style["annotation_font_size"])
            if isinstance(text, Annotation) and not getattr(text, "_standard_custom_position", False):
                text.set_position((style["annotation_offset_x"], style["annotation_offset_y"]))
    if fig._suptitle is not None:
        fig._suptitle.set_fontsize(style["title_font_size"])

def create_standard_canvas(policy, labels, form, panels=1):
    policy["horizontal"] = form == "barh"
    width, height = policy["width"], policy["height"]
    if policy["size_mode"] == "auto":
        if form == "barh":
            height = min(24, max(height, len(labels) * .42))
        else:
            width = min(20, max(width, len(labels) * .45))
        height = min(24, max(height, panels * 2.5))
    if width * height * policy["dpi"] ** 2 > 24000000:
        raise ValueError("standard_canvas_pixel_budget_exceeded")
    return {"figsize": (width, height), "dpi": policy["dpi"],
            "layout": "constrained" if policy["layout"] == "constrained" else None}

def save_standard_canvas(fig, output_path, policy):
    fig.savefig(output_path, dpi=policy["dpi"],
                bbox_inches="tight" if policy["crop"] == "tight" else None,
                pad_inches=policy["padding"])

def finish_standard_layout(fig, policy):
    import textwrap
    from matplotlib.text import Annotation
    apply_standard_style(fig, policy)
    finish_standard_presentation(fig, policy)
    for ax in fig.axes:
        for axis, ticks, setter in ((ax.xaxis, ax.get_xticks(), ax.set_xticks),
                                    (ax.yaxis, ax.get_yticks(), ax.set_yticks)):
            texts = [tick.get_text() for tick in axis.get_ticklabels()]
            if any(len(text) > policy["label_wrap"] for text in texts):
                setter(ticks, [textwrap.fill(text, width=policy["label_wrap"], break_long_words=True) for text in texts])
            for tick in axis.get_ticklabels():
                tick.set_fontsize(policy["tick_font_size"])
        legend = ax.get_legend()
        if legend is not None and (policy["legend_position"] == "outside" or
                                  policy["legend_position"] == "auto" and len(legend.get_texts()) > 3):
            legend.set_bbox_to_anchor((1.01, 1))
            legend.set_loc("upper left")
    if policy["layout"] == "tight":
        reserved = policy["presentation"]
        top, bottom = reserved["header_bottom"], reserved["footer_top"]
        fig.tight_layout(pad=max(.7, policy["padding"]), rect=(.02, bottom, .98, top))
    elif policy["layout"] == "manual":
        fig.subplots_adjust(left=policy["left"], right=policy["right"],
                            bottom=policy["bottom"], top=policy["top"])
    elif policy["layout"] == "constrained":
        reserved = policy["presentation"]
        fig.get_layout_engine().set(rect=(.02, reserved["footer_top"], .96,
            reserved["header_bottom"] - reserved["footer_top"]))
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


_ADVANCED = '''def render_advanced(labels, names, raw_series, metadata, policy, form, title, output_path, annotations, canvas):
    import math
    import matplotlib.pyplot as plt
    mode = policy["mode"]
    precision = canvas["style"]["decimals"]
    series = [[value * (100 if meta.get("unit") == "%" and meta.get("isPercent") is False else 1)
               for value in values] for values, meta in zip(raw_series, metadata, strict=True)]
    positions = list(range(len(labels)))
    if mode == "panels":
        fig, panels = plt.subplots(len(series), 1, sharex=True, squeeze=False,
                                   **create_standard_canvas(canvas, labels, form, len(series)))
        axes = [panel[0] for panel in panels]
        targets = axes
    else:
        fig, primary = plt.subplots(**create_standard_canvas(canvas, labels, form))
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
            group_width = canvas["style"]["bar_group_width"]
            width = group_width / len(members)
            offsets = [position - group_width / 2 + width / 2 + members.index(index) * width for position in positions]
            target.bar(offsets, values, width=width, color=colors(index), label=caption)
        else:
            target.plot(positions, values, marker="o", color=colors(index), label=caption)
        target.set_ylabel(f"{side} · {meta['unit']}" if mode == "dual" else meta["unit"])
        target.set_yscale(policy["scale"])
        target.set_xticks(positions, standard_label_names(labels, canvas), rotation=45, ha="right")
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
                target.axvspan(first - .4, last + .4, alpha=.12, color=canvas["annotation_specs"][number]["color"] or "#e8ae53")
            continue
        target = targets[series_index]
        values = series[series_index]
        unit = metadata[series_index]["unit"]
        if kind == "reference":
            color = canvas["annotation_specs"][number]["color"] or "#b55d68"
            target.axhline(values[first], color=color, linestyle="--", linewidth=1.2)
            caption = canvas["annotation_specs"][number]["caption"] or f"参考 {labels[first]}"
            target.text(.99, values[first], f"{caption}: {values[first]:,.{precision}f}{unit}",
                        transform=target.get_yaxis_transform(), va="bottom", ha="right", fontsize=8, color=color,
                        bbox={"fc": "white", "ec": "none", "pad": 2})
            continue
        indexes = ([first] if kind == "point" else
                   [index for index, value in enumerate(values) if kind == "values" or
                    value == (max(values) if kind == "peak" else min(values))])
        for index in indexes:
            if kind == "values" and not standard_values_label_visible(index, series_index, annotations, series):
                continue
            coordinate = index
            if form == "bar" and not (mode == "dual" and names[series_index] in policy["right_fields"]):
                members = [i for i, item in enumerate(targets) if item is target]
                group_width = canvas["style"]["bar_group_width"]
                width = group_width / len(members)
                coordinate = index - group_width / 2 + width / 2 + members.index(series_index) * width
            extra = canvas["presentation"]["extras"].get((labels[index], names[series_index]), "")
            caption = canvas["annotation_specs"][number]["caption"] or names[series_index]
            text = f"{caption}: {values[index]:,.{precision}f}{unit}" + (" · " + extra if extra else "")
            standard_annotation(target, text, (coordinate, values[index]), canvas, number,
                                standard_series_color(names[series_index], canvas))
    if mode == "zoom":
        first = labels.index(policy["zoom_start"])
        last = labels.index(policy["zoom_end"])
        inset = axes[0].inset_axes(policy["zoom_bounds"])
        local_values = []
        for index, values in enumerate(series):
            if form == "bar":
                group_width = canvas["style"]["bar_group_width"]
                width = group_width / len(series)
                offsets = [position - group_width / 2 + width / 2 + index * width for position in positions]
                inset.bar(offsets, values, width=width, color=colors(index), label=names[index])
            else:
                inset.plot(positions, values, marker="o", color=colors(index), label=names[index])
            local_values.extend(values[first:last + 1])
        low, high = min(local_values), max(local_values)
        padding = (high - low) * .1 or abs(high) * .1 or 1
        inset.set_xlim(first - .2, last + .2)
        if policy["scale"] == "log":
            inset.set_yscale("log")
            inset.set_ylim(low / 1.2, high * 1.2)
        else:
            inset.set_ylim(low - padding, high + padding)
        inset.set_xticks(positions[first:last + 1], standard_label_names(labels, canvas)[first:last + 1], rotation=45, fontsize=7)
        inset.set_title("局部放大 · " + metadata[0]["unit"], fontsize=9)
        axes[0].axvspan(first - .2, last + .2, color="#f59e0b", alpha=.1)
    fig.suptitle(title)
    finish_standard_layout(fig, canvas)
    save_standard_canvas(fig, output_path, canvas)
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
for input_path, digest, output_path, title, form, label_column, value_columns, category_column, unit, is_percent, annotations, axes_policy, metadata, total_field, canvas in CONFIGS:
    precision = canvas["style"]["decimals"]
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
        render_advanced(labels, names, series, metadata, axes_policy, form, title, output_path, annotations, canvas)
        continue
    if unit == "%" and is_percent is False:
        series = [[value * 100 for value in values] for values in series]
    if input_path in DISPLAYS:
        factor, unit = DISPLAYS[input_path]
        series = [[value * factor for value in values] for values in series]
    fig, ax = plt.subplots(**create_standard_canvas(canvas, labels, form))
    positions = list(range(len(labels)))
    if form == "stacked-area":
        ax.stackplot(positions, *series, labels=names)
    else:
        bottom = [0.0] * len(labels)
        group_width = canvas["style"]["bar_group_width"]
        width = group_width / len(series)
        for index, (name, values) in enumerate(zip(names, series, strict=True)):
            if name == total_field:
                continue
            if form == "line":
                ax.plot(positions, values, marker="o", label=name)
            elif form in {"stacked-bar", "stacked-total"}:
                ax.bar(positions, values, width=group_width, bottom=bottom, label=name)
                bottom = [left + right for left, right in zip(bottom, values, strict=True)]
            else:
                offsets = [position - group_width / 2 + width / 2 + index * width for position in positions]
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
        ax.set_yticks(positions, standard_label_names(labels, canvas))
        ax.invert_yaxis()
        ax.set_xlabel(unit or "")
    else:
        ax.set_xticks(positions, standard_label_names(labels, canvas), rotation=45, ha="right")
        ax.set_ylabel(unit or "")
    if len(series) > 1 or form == "stacked-total":
        ax.legend(frameon=False)
    for annotation_index, (kind, series_index, first, last) in enumerate(annotations):
        if kind == "range":
            span = ax.axhspan if form == "barh" else ax.axvspan
            span(first - 0.4, last + 0.4, color=canvas["annotation_specs"][annotation_index]["color"] or "#e8ae53", alpha=0.12)
            continue
        values = series[series_index]
        finite = [value for value in values if math.isfinite(value)]
        if not finite:
            continue
        if kind == "reference":
            draw = ax.axvline if form == "barh" else ax.axhline
            color = canvas["annotation_specs"][annotation_index]["color"] or "#b55d68"
            draw(values[first], linestyle="--", color=color, alpha=0.8, linewidth=1.2)
            caption = canvas["annotation_specs"][annotation_index]["caption"] or f"参考 {labels[first]} · {names[series_index]}"
            text = f"{caption}: {values[first]:,.{precision}f}{unit or ''}"
            if form == "barh":
                ax.text(values[first], 1.02, text, transform=ax.get_xaxis_transform(),
                        va="bottom", fontsize=8, color=color, bbox={"fc": "white", "ec": "none", "pad": 2})
            else:
                ax.text(.99, values[first], text, transform=ax.get_yaxis_transform(),
                        va="bottom", ha="right", fontsize=8, color=color, bbox={"fc": "white", "ec": "none", "pad": 2})
            continue
        indexes = ([first] if kind == "point" else
                   [index for index, value in enumerate(values) if math.isfinite(value) and
                    (kind == "values" or value == (max(finite) if kind == "peak" else min(finite)))])
        for index in indexes:
            if kind == "values" and not standard_values_label_visible(index, series_index, annotations, series):
                continue
            value = values[index]
            coordinate = index
            height = value
            if form in {"stacked-bar", "stacked-area", "stacked-total"} and names[series_index] != total_field:
                height += sum(previous[index] for previous_name, previous in zip(names[:series_index], series[:series_index], strict=True)
                              if previous_name != total_field)
            elif form in {"bar", "barh"}:
                coordinate = index - group_width / 2 + group_width / (2 * len(series)) + series_index * group_width / len(series)
            xy = (height, coordinate) if form == "barh" else (coordinate, height)
            prefix = {"peak": "峰值 ", "trough": "谷值 ", "point": "重点 "}.get(kind, "")
            caption = canvas["annotation_specs"][annotation_index]["caption"]
            if caption:
                prefix = caption + " "
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
                auxiliary_text.append(f"{field}: {auxiliary_value:,.{precision}f}{meta['unit']}")
            suffix = " · " + " / ".join(auxiliary_text) if auxiliary_text else ""
            extra = canvas["presentation"]["extras"].get((labels[index], names[series_index]), "")
            if extra:
                suffix += " · " + extra
            color = standard_series_color(names[series_index], canvas) if canvas["style"]["annotation_color"] == "series" else "#475569"
            point = next((item for item in canvas["style"]["points"] if item["series"] == names[series_index] and item["label"] == labels[index]), None)
            if point is not None:
                color = point["color"]
            standard_annotation(ax, f"{prefix}{value:,.{precision}f}{unit or ''}{suffix}", xy,
                                canvas, annotation_index, color)
    ax.set_title(title)
    ax.spines[["top", "right"]].set_visible(False)
    finish_standard_layout(fig, canvas)
    save_standard_canvas(fig, output_path, canvas)
    plt.close(fig)
'''
