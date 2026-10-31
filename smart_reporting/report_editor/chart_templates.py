"""Checked-in deterministic Matplotlib chart templates over frozen facts."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..reporting.hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
from ..reporting.trace.fact_index import breakdown_partitions, shareable_partition
from ..reporting.trace.numeric_text import budget_comparison_values, primary_display_name

TEMPLATE_IDS = ("composition-bars", "monthly-trend", "yoy-comparison", "budget-progress")
TEMPLATE_CATALOG = (
    {"templateId": "composition-bars", "name": "构成排序条形图"},
    {"templateId": "monthly-trend", "name": "月度趋势折线图"},
    {"templateId": "yoy-comparison", "name": "同比对比柱状图"},
    {"templateId": "budget-progress", "name": "预算执行进度条"},
)


@dataclass(frozen=True)
class ChartTemplateMaterialization:
    """A single deterministic template selection reused by availability and serialization."""

    rows: tuple[dict[str, Any], ...]
    source_pointers: tuple[str, ...]
    reason: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.rows) and self.reason is None


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _month_label(value: str) -> str | None:
    text = str(value).strip()
    if len(text) == 7 and text[4] == "-" and text[:4].isdigit() and text[5:].isdigit():
        year, month = int(text[:4]), int(text[5:])
        return text if year > 0 and 1 <= month <= 12 else None
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        year, month, day = text[:4], text[5:7], text[8:]
        if (
            year.isdigit()
            and month.isdigit()
            and day.isdigit()
            and 1 <= int(month) <= 12
            and 1 <= int(day) <= 31
        ):
            return f"{year}-{month}"
    return None


def _reference_matches(refs: Sequence[Any], kind: str, index: int, fact_id: str | None) -> bool:
    pointer = f"/{kind}/{index}"
    return any(
        ref.fact_kind == ("metric" if kind in {"metrics", "breakdowns"} else "comparison")
        and (ref.json_pointer == pointer or (fact_id is not None and ref.fact_key == fact_id))
        for ref in refs
    )


def _select_unique(candidates: list[Any], refs: Sequence[Any]) -> Any | None:
    if refs:
        selected = [item for item in candidates if item["referenced"]]
        if len(selected) == 1:
            return selected[0]
        if len(selected) > 1:
            return None
    return candidates[0] if len(candidates) == 1 else None


def _composition_rows(
    bundle: DeterministicAnalysisBundle, refs: Sequence[Any]
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    metrics = {
        fact.fact_id: (index, fact) for index, fact in enumerate(bundle.metrics) if fact.fact_id
    }
    partitions = breakdown_partitions(bundle)
    candidates = []
    for (parent_id, field), groups in partitions.items():
        parent_item = metrics.get(parent_id)
        if parent_item is None or not groups or not shareable_partition(parent_item[1], groups):
            continue
        parent_index, parent = parent_item
        if any(group.unit != parent.unit for group in groups):
            continue
        group_indexes = {id(group): index for index, group in enumerate(bundle.breakdowns)}
        indexes = [group_indexes[id(group)] for group in groups]
        group_referenced = any(
            _reference_matches(refs, "breakdowns", idx, bundle.breakdowns[idx].fact_id)
            for idx in indexes
        )
        candidates.append(
            {
                "parent": parent,
                "parentIndex": parent_index,
                "field": field,
                "groups": groups,
                "indexes": indexes,
                "referenced": group_referenced or _reference_matches(
                    refs, "metrics", parent_index, parent.fact_id
                ),
                "groupReferenced": group_referenced,
            }
        )
    eligible = [item for item in candidates if item["referenced"]] if refs else candidates
    explicit = [item for item in eligible if item["groupReferenced"]]
    if explicit:
        eligible = explicit
    elif any(ref.fact_kind == "supplemental_finding" for ref in refs):
        # 补证父指标只能证明指标归属，不能证明原图的分组维度。
        return [], [], "原图补证未绑定可核验的同维度构成事实，不能替换为其他维度。"
    if len(eligible) > 1:
        # 只在同一指标、范围、维度的期间候选之间优先本期；不跨指标或维度猜选。
        first = eligible[0]
        same_measure = all(
            item["field"] == first["field"]
            and item["parent"].field_ref == first["parent"].field_ref
            and item["parent"].metric_codes == first["parent"].metric_codes
            and item["parent"].scope == first["parent"].scope
            and primary_display_name(item["parent"].display_name or "")
            == primary_display_name(first["parent"].display_name or "")
            for item in eligible
        )
        if same_measure:
            current = [item for item in eligible if "current" in item["parent"].period_roles]
            if len(current) == 1:
                eligible = current
    selected = eligible[0] if len(eligible) == 1 else None
    if selected is None:
        reason = (
            "没有登记构成数据。"
            if not candidates
            else "该图未唯一绑定一个维度构成，无法无歧义地选择分组。"
        )
        return [], [], reason
    parent = selected["parent"]
    rows = []
    for group, index in zip(selected["groups"], selected["indexes"], strict=True):
        rows.append(
            {
                "label": str(
                    group.breakdown_value
                    or group.scope.get(selected["field"])
                    or group.display_name
                    or group.field
                ),
                "value": float(group.total),
                "share": float(group.total / parent.total * 100),
                "factId": group.fact_id,
                "jsonPointer": f"/breakdowns/{index}",
            }
        )
    rows.sort(key=lambda item: (-item["value"], item["label"]))
    pointers = [f"/metrics/{selected['parentIndex']}", *(row["jsonPointer"] for row in rows)]
    return rows, pointers, None


def _monthly_candidates(
    bundle: DeterministicAnalysisBundle, refs: Sequence[Any]
) -> list[dict[str, Any]]:
    candidates = []
    for index, fact in enumerate(bundle.metrics):
        if fact.period_granularity != "month":
            continue
        month_values: dict[str, float] = {}
        duplicate = False
        for item in fact.period_values:
            label = _month_label(item.period)
            if label is None or not _finite(item.value):
                continue
            if label in month_values:
                duplicate = True
                break
            month_values[label] = float(item.value)
        if duplicate or len(month_values) < 3:
            continue
        candidates.append(
            {
                "fact": fact,
                "index": index,
                "values": month_values,
                "referenced": _reference_matches(refs, "metrics", index, fact.fact_id),
            }
        )
    return candidates


def _monthly_rows(
    bundle: DeterministicAnalysisBundle, refs: Sequence[Any]
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    candidates = _monthly_candidates(bundle, refs)
    selected = _select_unique(candidates, refs)
    if selected is None:
        reason = (
            "缺少至少 3 个不同实际月份的 periodValues。"
            if not candidates
            else "该图未唯一绑定一个月度指标，无法无歧义地选择趋势。"
        )
        return [], [], reason
    rows = [
        {"label": label, "value": value, "factId": selected["fact"].fact_id}
        for label, value in sorted(selected["values"].items())
    ]
    low = min(row["value"] for row in rows)
    high = max(row["value"] for row in rows)
    for row in rows:
        row["extremum"] = "min" if row["value"] == low else "max" if row["value"] == high else None
    return rows, [f"/metrics/{selected['index']}"], None


def _yoy_rows(
    bundle: DeterministicAnalysisBundle, refs: Sequence[Any]
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    candidates = [
        {
            "item": item,
            "index": index,
            "referenced": _reference_matches(refs, "comparisons", index, item.fact_id),
        }
        for index, item in enumerate(bundle.comparisons)
        if item.comparison_type == "yoy"
        and _finite(item.current_total)
        and _finite(item.baseline_total)
    ]
    if not candidates:
        return [], [], "缺少同比数据。"
    selected = [item for item in candidates if item["referenced"]] if refs else candidates
    if not selected:
        return [], [], "该图没有明确绑定同比事实。"
    units = {entry["item"].unit for entry in selected}
    if len(units) != 1:
        return [], [], "同比事实包含不同单位，无法共用同一数值轴。"
    rows = []
    pointers = []
    metric_names = {fact.fact_id: primary_display_name(fact.display_name)
                    for fact in (*bundle.metrics, *bundle.breakdowns) if fact.fact_id and fact.display_name}
    for entry in selected:
        item, index = entry["item"], entry["index"]
        names = {metric_names[fact_id] for fact_id in item.input_fact_ids if metric_names.get(fact_id)}
        name = next(iter(names)) if len(names) == 1 else item.field
        label = f"{name}（{item.period_end}）" if item.period_end else name
        if any(row["label"] == label for row in rows):
            return [], [], "同比事实缺少可唯一识别的指标与期间标签，无法无歧义地展示。"
        rows.append(
            {
                "label": label,
                "current": float(item.current_total),
                "baseline": float(item.baseline_total),
                "factId": item.fact_id,
            }
        )
        pointers.append(f"/comparisons/{index}")
    return rows, pointers, None


def _budget_rows(
    bundle: DeterministicAnalysisBundle, refs: Sequence[Any]
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    values = [
        item
        for item in budget_comparison_values(bundle)
        if item.get("percentage") is not None and _finite(item["percentage"])
    ]
    if not values:
        return [], [], "缺少预算对比完成率数据。"
    facts = (*bundle.metrics, *bundle.breakdowns)
    lookup = {
        fact.fact_id: (
            "metrics" if index < len(bundle.metrics) else "breakdowns",
            index if index < len(bundle.metrics) else index - len(bundle.metrics),
            fact,
        )
        for index, fact in enumerate(facts)
        if fact.fact_id
    }
    units: set[str | None] = set()
    pointers = []
    rows = []
    seen_periods: set[str] = set()
    for item in values:
        actual = lookup.get(item["actualFactId"])
        budget = lookup.get(item["budgetFactId"])
        if actual is None or budget is None:
            continue
        if refs and not any(
            _reference_matches(refs, kind, index, fact.fact_id)
            for kind, index, fact in (actual, budget)
        ):
            continue
        units.add(actual[2].unit)
        for kind, index, _fact in (actual, budget):
            pointer = f"/{kind}/{index}"
            if pointer not in pointers:
                pointers.append(pointer)
        period = str(item["period"])
        if period in seen_periods:
            return [], [], "预算事实产生重复期间，无法无歧义地展示进度。"
        seen_periods.add(period)
        rows.append(
            {
                "label": period,
                "completion": float(item["percentage"]),
                "difference": float(item["difference"]),
                "actualFactId": item["actualFactId"],
                "budgetFactId": item["budgetFactId"],
            }
        )
    if len(units) != 1:
        return [], [], "预算事实包含不同单位，无法共用同一数值轴。"
    if not rows:
        return [], [], "预算事实缺少可读取的登记来源。"
    rows.sort(key=lambda row: row["label"])
    return rows[-12:], pointers, None


def template_rows(
    template_id: str, bundle: DeterministicAnalysisBundle, fact_refs: Sequence[Any] = ()
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    if template_id == "composition-bars":
        return _composition_rows(bundle, fact_refs)
    if template_id == "monthly-trend":
        return _monthly_rows(bundle, fact_refs)
    if template_id == "yoy-comparison":
        return _yoy_rows(bundle, fact_refs)
    if template_id == "budget-progress":
        return _budget_rows(bundle, fact_refs)
    return [], [], "模板不存在。"


def template_availability(
    template_id: str, bundle: DeterministicAnalysisBundle, fact_refs: Sequence[Any] = ()
) -> tuple[bool, str | None]:
    materialized = materialize_chart_template(template_id, bundle, fact_refs)
    return materialized.available, materialized.reason


_RECOMMENDATION_REASONS = {
    "composition-bars": "与该图绑定的构成数据一致",
    "monthly-trend": "与该图绑定的月度指标一致",
    "yoy-comparison": "与该图绑定的同比数据一致",
    "budget-progress": "与该图绑定的预算数据一致",
}


def matched_pointer_count(pointers: Sequence[str], fact_refs: Sequence[Any]) -> int:
    """物化来源指针中有多少条正指向该图绑定的事实；推荐只认绑定，不认库存里存在。"""

    count = 0
    for pointer in pointers:
        parts = pointer.strip("/").split("/")
        if len(parts) != 2 or not parts[1].isdigit():
            continue
        if _reference_matches(fact_refs, parts[0], int(parts[1]), None):
            count += 1
    return count


def recommendation_reason(template_id: str) -> str | None:
    return _RECOMMENDATION_REASONS.get(template_id)


def matched_fact_name(
    pointers: Sequence[str], fact_refs: Sequence[Any], bundle: DeterministicAnalysisBundle
) -> str | None:
    """沿绑定和 inputFactIds 获取唯一业务名称；缺失或歧义时使用通用推荐理由。"""

    metric_names = {fact.fact_id: primary_display_name(fact.display_name)
                    for fact in (*bundle.metrics, *bundle.breakdowns)
                    if fact.fact_id and fact.display_name}
    names = set()
    for pointer in pointers:
        parts = pointer.strip("/").split("/")
        if len(parts) != 2 or not parts[1].isdigit():
            continue
        kind, index = parts[0], int(parts[1])
        if not _reference_matches(fact_refs, kind, index, None):
            continue
        facts = {
            "metrics": bundle.metrics,
            "breakdowns": bundle.breakdowns,
            "comparisons": bundle.comparisons,
        }.get(kind)
        if facts is None or index >= len(facts):
            continue
        fact = facts[index]
        if kind == "comparisons":
            parent_names = {metric_names[fact_id] for fact_id in fact.input_fact_ids
                            if metric_names.get(fact_id)}
            if len(parent_names) != 1:
                return None
            names.update(parent_names)
        else:
            name = primary_display_name(fact.display_name) if fact.display_name else None
            if not name:
                return None
            names.add(name)
    return next(iter(names)) if len(names) == 1 else None


def materialize_chart_template(
    template_id: str,
    bundle: DeterministicAnalysisBundle,
    fact_refs: Sequence[Any] = (),
) -> ChartTemplateMaterialization:
    rows, pointers, reason = template_rows(template_id, bundle, fact_refs)
    return ChartTemplateMaterialization(tuple(rows), tuple(pointers), reason)


def build_chart_input(
    template_id: str,
    bundle: DeterministicAnalysisBundle,
    *,
    chart_id: str,
    source_path: str,
    source_resource_id: str,
    fact_file_path: str,
    fact_file_sha256: str,
    materialization: ChartTemplateMaterialization,
) -> bytes:
    if not materialization.available:
        raise ValueError(materialization.reason or "template has no rows")
    rows = materialization.rows
    pointers = materialization.source_pointers
    columns = sorted({key for row in rows for key in row})
    payload = {
        "schema": "chart-input/v1",
        "chartId": chart_id,
        "role": f"template:{template_id}",
        "source": {
            "analysisId": bundle.analysis_id,
            "path": source_path,
            "dataPath": pointers[0] if len(pointers) == 1 else "",
            "dataPaths": pointers,
            "factFileResourceId": source_resource_id,
            "factFilePath": fact_file_path,
            "factFileSha256": fact_file_sha256,
        },
        "columns": columns,
        "rows": [[row.get(column) for column in columns] for row in rows],
        "rowCount": len(rows),
        "templateId": template_id,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


_SCRIPT_BODY = r"""import json
import matplotlib.pyplot as plt

with open(INPUT_PATH, "r", encoding="utf-8") as handle:
    payload = json.load(handle)
rows = payload["rows"]
columns = payload["columns"]
data = [dict(zip(columns, row, strict=False)) for row in rows]
labels = [str(row.get("label", "")) for row in data]
fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
if TEMPLATE_ID == "composition-bars":
    values = [float(row["value"]) for row in data]
    ax.barh(labels[::-1], values[::-1], color="#2563eb")
    for index, row in enumerate(data[::-1]):
        ax.text(float(row["value"]), index, f' {float(row["share"]):.1f}%', va="center", fontsize=8)
elif TEMPLATE_ID == "monthly-trend":
    values = [float(row["value"]) for row in data]
    ax.plot(labels, values, marker="o", color="#0f766e", linewidth=2)
    for index, row in enumerate(data):
        if row.get("extremum"):
            ax.annotate(row["extremum"], (index, float(row["value"])), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
    ax.tick_params(axis="x", rotation=35)
elif TEMPLATE_ID == "yoy-comparison":
    positions = list(range(len(data)))
    width = 0.38
    ax.bar([value - width / 2 for value in positions], [float(row["baseline"]) for row in data], width, label="同期", color="#94a3b8")
    ax.bar([value + width / 2 for value in positions], [float(row["current"]) for row in data], width, label="本期", color="#2563eb")
    ax.set_xticks(positions, labels, rotation=35, ha="right")
    ax.legend(frameon=False)
else:
    values = [float(row["completion"]) for row in data]
    ax.barh(labels[::-1], values[::-1], color="#16a34a")
    ax.axvline(100, color="#64748b", linewidth=1, linestyle="--")
    ax.set_xlabel("完成率（%）")
ax.set_title(TITLE)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(OUTPUT_PATH, format="png")
plt.close(fig)
"""


def render_template_script(
    template_id: str, *, input_path: str, output_path: str, title: str
) -> str:
    if template_id not in TEMPLATE_IDS:
        raise ValueError("unknown chart template")
    return (
        "INPUT_PATH = "
        + repr(input_path)
        + "\nOUTPUT_PATH = "
        + repr(output_path)
        + "\nTEMPLATE_ID = "
        + repr(template_id)
        + "\nTITLE = "
        + repr(title[:200])
        + "\n"
        + _SCRIPT_BODY
    )
