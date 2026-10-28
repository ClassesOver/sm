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
        form = {'line': 'line', '折线图': 'line', 'bar': 'bar', '柱状图': 'bar',
                'barh': 'barh', '横向条形图': 'barh'}.get(chart.visual_form)
        entries = [entry for entry in inputs.entries if entry['chartId'] == chart.chart_id]
        if form is None or len(entries) != 1:
            return None
        entry = entries[0]
        source = next((item for item in inputs.files if item.path == entry['path']), None)
        if source is None or source.sha256 != entry['sha256']:
            return None
        document = json.loads(source.content)
        columns, rows = document['columns'], document['rows']
        label = 'period' if 'period' in columns else 'label' if 'label' in columns else None
        if label is None or set(columns) != {label, 'value'} or not 1 <= len(rows) <= 60:
            return None
        label_index, value_index = columns.index(label), columns.index('value')
        labels = [row[label_index] for row in rows]
        if any(not isinstance(value, str) or not value for value in labels) or len(set(labels)) != len(labels):
            return None
        if any(not isinstance(row[value_index], (int, float))
               or isinstance(row[value_index], bool) or not math.isfinite(row[value_index]) for row in rows):
            return None
        configs.append((source.path, source.sha256, chart.source_path, chart.title, form, label))
    return 'CONFIGS = ' + repr(configs) + '\n' + _BODY


_BODY = '''import hashlib
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
for input_path, digest, output_path, title, form, label_column in CONFIGS:
    with open(input_path, "rb") as handle:
        raw = handle.read()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("chart input identity changed")
    payload = json.loads(raw)
    columns = payload["columns"]
    labels = [row[columns.index(label_column)] for row in payload["rows"]]
    values = [row[columns.index("value")] for row in payload["rows"]]
    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)
    if form == "line":
        ax.plot(labels, values, marker="o", color="#2563eb")
    elif form == "barh":
        ax.barh(labels[::-1], values[::-1], color="#2563eb")
    else:
        ax.bar(labels, values, color="#2563eb")
    if form != "barh":
        ax.tick_params(axis="x", rotation=45)
    ax.set_title(title)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
'''
