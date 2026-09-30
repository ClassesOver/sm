"""静态图表作图数据的确定性转换规则（B3，计划 4.4-3）。

把 chart-input 表（类别 + 数值列）按冻结规则转换为最终作图数据：
排序、Top N/其他项合并、缺值保持、单位换算。规则由服务端声明，
不允许模型脚本自由发挥后另算来源表。

独立答案：``tests/lineage_fixtures/expected/chart_expected.json`` 是手算
常量，``test_trace_chart_transform.py`` 用它逐值核对（答案来源与被测
实现分离，计划 B0-5）。

缺值语义（与 B0 边界 fixtures 一致）：
- Top 类别的缺值保持 None（不补 0，如实缺值）；
- 「其他」组合并时缺值按 0 计入合计；组合并后无任何有效值则为 None；
- 负数参与排序并落入「其他」，不丢弃。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..models import ReportingError


def transform_chart_series(
    rows: Sequence[Mapping[str, Any]],
    *,
    category_field: str,
    value_fields: Sequence[str],
    top_n: int = 3,
    unit_scale: float = 1.0,
    unit_decimals: int = 3,
    sort_field: str | None = None,
    sort_desc: bool = True,
    other_label: str = "其他",
) -> dict[str, Any]:
    """从 chart-input 行集生成最终作图数据（类别顺序 + 各系列值）。

    行是 chart-input 的 ``rows``（列名 → 值）；类别取 ``category_field``
    列，排序按 ``sort_field``（缺省按第一个数值列）。
    """

    if not rows:
        return {"categories": [], "series": {field: [] for field in value_fields}}
    if not value_fields:
        raise ReportingError("request_invalid", "作图数据转换至少需要一个数值列。")
    if top_n < 1:
        raise ReportingError("request_invalid", "Top N 必须 ≥ 1。")
    sort_column = sort_field or value_fields[0]
    for row in rows:
        for field in (category_field, sort_column, *value_fields):
            if field not in row:
                raise ReportingError(
                    "request_invalid", f"作图数据缺少列: {field}"
                )

    def _sort_key(row: Mapping[str, Any]) -> float:
        value = row.get(sort_column)
        return float(value) if value is not None else float("-inf")

    ordered = sorted(rows, key=_sort_key, reverse=sort_desc)
    top = ordered[:top_n]
    others = ordered[top_n:]

    def _scale(value: float | None) -> float | None:
        if value is None:
            return None
        scaled = value * unit_scale
        return round(scaled, unit_decimals)

    categories: list[str] = [str(row[category_field]) for row in top]
    if others:
        categories.append(other_label)

    series: dict[str, list[float | None]] = {}
    for field in value_fields:
        values: list[float | None] = [_scale(_as_number(row[field])) for row in top]
        if others:
            other_values = [_as_number(row[field]) for row in others]
            if all(value is None for value in other_values):
                values.append(None)
            else:
                values.append(
                    _scale(sum(value for value in other_values if value is not None))
                )
        series[field] = values
    return {"categories": categories, "series": series}


def _as_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
