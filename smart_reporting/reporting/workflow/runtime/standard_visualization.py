"""Conservative static templates over identity-checked chart inputs."""
from __future__ import annotations

import json
import math

from .chart_inputs import ChartInputMaterialization
from .phase_models import VisualizationPlanDraft


def standard_visualization_script(
    plan: VisualizationPlanDraft, inputs: ChartInputMaterialization,
) -> str | None:
    if inputs.fallback_chart_ids or not plan.charts:
        return None
    configs = []
    for chart in plan.charts:
        if chart.renderer != 'matplotlib' or chart.interactive_path:
            return None
        form = {'line': 'line', '折线图': 'line', '多系列折线图': 'line',
                'bar': 'bar', '柱状图': 'bar', '分组柱状图': 'bar',
                'barh': 'barh', '横向条形图': 'barh',
                'stacked-bar': 'stacked-bar', '堆叠柱状图': 'stacked-bar',
                'stacked-area': 'stacked-area', '堆叠面积图': 'stacked-area'}.get(chart.visual_form)
        entries = [entry for entry in inputs.entries if entry['chartId'] == chart.chart_id]
        if form is None or len(entries) != 1:
            return None
        entry = entries[0]
        source = next((item for item in inputs.files if item.path == entry['path']), None)
        if source is None or source.sha256 != entry['sha256']:
            return None
        document = json.loads(source.content)
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
        labels = [row[label_index] for row in rows]
        if any(not isinstance(value, str) or not value for value in labels):
            return None
        other_columns = [column for column in columns if column != label]
        category_columns = [column for column in other_columns
                            if all(isinstance(row[columns.index(column)], str) for row in rows)]
        category = category_columns[0] if len(category_columns) == 1 else None
        values = [column for column in other_columns if column != category]
        selected = tuple(getattr(chart, 'standard_value_fields', ()))
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
        # 同轴系列必须有明确且完全一致的单位、比例显示尺度；不推断换算。
        if len(values) > 1 and (
            any(not meta.get('unit') for meta in metas)
            or len({(meta.get('unit'), meta.get('isPercent')) for meta in metas}) != 1
        ):
            return None
        if form in {'line', 'stacked-bar', 'stacked-area'} and len(values) > 1:
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
        if form in {'stacked-bar', 'stacked-area'} and any(
            row[columns.index(column)] < 0 for row in rows for column in values
        ):
            return None
        configs.append((source.path, source.sha256, chart.source_path, chart.title,
                        form, label, values, category, metas[0].get('unit'),
                        metas[0].get('isPercent')))
    return 'CONFIGS = ' + repr(configs) + '\n' + _BODY


_BODY = '''import hashlib
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
for input_path, digest, output_path, title, form, label_column, value_columns, category_column, unit, is_percent in CONFIGS:
    with open(input_path, "rb") as handle:
        raw = handle.read()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("chart input identity changed")
    payload = json.loads(raw)
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
    if unit == "%" and is_percent is False:
        series = [[value * 100 for value in values] for values in series]
    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
    positions = list(range(len(labels)))
    if form == "stacked-area":
        ax.stackplot(positions, *series, labels=names)
    else:
        bottom = [0.0] * len(labels)
        width = 0.8 / len(series)
        for index, (name, values) in enumerate(zip(names, series, strict=True)):
            if form == "line":
                ax.plot(positions, values, marker="o", label=name)
            elif form == "stacked-bar":
                ax.bar(positions, values, bottom=bottom, label=name)
                bottom = [left + right for left, right in zip(bottom, values, strict=True)]
            else:
                offsets = [position - 0.4 + width / 2 + index * width for position in positions]
                if form == "barh":
                    ax.barh(offsets, values, height=width, label=name)
                else:
                    ax.bar(offsets, values, width=width, label=name)
    if form == "barh":
        ax.set_yticks(positions, labels)
        ax.invert_yaxis()
        ax.set_xlabel(unit or "")
    else:
        ax.set_xticks(positions, labels, rotation=45, ha="right")
        ax.set_ylabel(unit or "")
    if len(series) > 1:
        ax.legend(frameon=False)
    ax.set_title(title)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
'''
