"""只依据固定事实完成的分析项：由服务端从冻结事实写出引用式摘要，不再请求模型转述数字。

摘要中的每个数值都是已登记的数值引用（合计、月均与月度极值、维度构成与占比、同比、预算完成率），
下游渲染与核对按同一引用取值；有补充证据的分析项仍由模型总结脚本结果。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ...hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
from ...trace.comparison_proofs import period_list_text
from ...trace.fact_index import breakdown_partitions
from ...trace.numeric_text import (
    _canonical_month_label,
    budget_comparison_values,
    frozen_number_catalog,
    primary_display_name,
)
from ...units import unit_scales

# 每个维度在摘要中列出的分组数；完整分组仍在冻结事实与章节数值目录中。
_SUMMARY_GROUPS = 5
_MAX_SUMMARY_CHARS = 6_000


def deterministic_fact_summary(bundle: DeterministicAnalysisBundle) -> str:
    """按指标逐条写出引用式摘要；没有可引用的数值时返回空串。"""

    catalog = frozen_number_catalog([bundle.model_dump_json(by_alias=True)])

    def token(fact_id: str | None, selector: str, unit: str | None, value: Any = None) -> str | None:
        for target in _display_units(unit, value):
            candidate = f"{{{{value:{fact_id}:{selector}:{target}}}}}"
            if catalog.get(candidate) not in {None, "数值待核实"}:
                return candidate
        return None

    budgets = budget_comparison_values(bundle)
    lines = []
    for fact in bundle.metrics:
        if "current" not in fact.period_roles:
            continue
        total = token(fact.fact_id, "total", fact.unit, fact.total)
        if total is None:
            continue
        name = primary_display_name(fact.display_name) or fact.field
        periods = [item.period for item in fact.period_values]
        level_series = fact.period_aggregation == "last" or fact.cumulative_policy is not None
        span = _span(periods[-1:] if level_series else periods)
        word = "" if level_series else {"sum": "合计", "count": "计数"}.get(fact.aggregation, "")
        # 固定范围（如“全院”）写进每个分句：引用句核对按分句检查登记范围。
        scope = "、".join(fact.scope.values())
        parts = [f"{scope}{span}{name}{word}{total}"]
        average = (
            None
            if level_series
            else token(fact.fact_id, "monthlyAverage", fact.unit, fact.total / max(len(periods), 1))
        )
        if average and periods:
            values = [item.value for item in fact.period_values]
            if len(set(values)) == 1:
                # 各月相同（如预算按月均摊）时没有高低之分。
                parts.append(f"各月登记值相同，均为{average}")
            else:
                parts.append(f"月均{average}")
                # 极值月份用该月自身的登记值引用（期间即该月）；并列极值不挑选其中一个月。
                for word, extreme in (("最高", max(values)), ("最低", min(values))):
                    if values.count(extreme) != 1:
                        continue
                    index = values.index(extreme)
                    value = token(fact.fact_id, f"periodValues.{index}", fact.unit, extreme)
                    if value:
                        parts[-1] += f"，{word}为{_span([periods[index]])}{value}"
        for label, groups in _dimension_groups(bundle, fact.fact_id):
            listed = []
            for group in sorted(groups, key=lambda item: -item.total)[:_SUMMARY_GROUPS]:
                value = token(group.fact_id, "total", group.unit, group.total)
                if value is None:
                    continue
                share = token(group.fact_id, f"metricShare.{fact.fact_id}", "%")
                listed.append(f"{group.scope[group.breakdown_field]}{value}" + (f"（占{share}）" if share else ""))
            if listed:
                more = f"等{len(groups)}组" if len(groups) > len(listed) else ""
                parts.append(f"{scope}按{label}：" + "、".join(listed) + more)
        # 同比单独成句：与全期、单月极值同句时，完成校验会把不同长度的期间读成不可比的同比。
        comparisons = []
        for comparison in bundle.comparisons:
            if comparison.comparison_type != "yoy" or fact.fact_id not in comparison.input_fact_ids[:1]:
                continue
            change = token(comparison.fact_id, "change", comparison.unit, comparison.change)
            rate = token(comparison.fact_id, "changeRate", "%")
            if change:
                comparisons.append(f"{scope}{span}{name}较上年同期变化{change}" + (f"（{rate}）" if rate else "") + "。")
        for budget in budgets:
            if budget["actualFactId"] != fact.fact_id or not _full_window(budget["period"], periods):
                continue
            rate = token(fact.fact_id, f"budgetComparison.{budget['budgetFactId']}.{budget['period']}.percentage", "%")
            if rate:
                parts.append(f"预算完成率{rate}")
        lines.append("；".join(parts) + "。" + "".join(comparisons))
    # 告警随完成记录单独登记，摘要只写数值事实；超长时按整条指标截断，不截半句。
    kept: list[str] = []
    for line in lines:
        if sum(len(item) + 1 for item in (*kept, line)) > _MAX_SUMMARY_CHARS:
            kept.append(f"其余 {len(lines) - len(kept)} 项指标见冻结事实。")
            break
        kept.append(line)
    return "\n".join(kept)


def _display_units(unit: str | None, value: Any) -> tuple[str, ...]:
    """金额与人次按量级优先用亿/万单位，其次原单位；无单位时只有原写法。"""
    scales = unit_scales(unit)
    if not scales or value is None:
        return (unit or "",)
    base = scales.get(unit or "", Decimal(1))
    magnitude = abs(Decimal(str(value))) * base
    readable = [item for item in sorted(scales, key=scales.__getitem__, reverse=True)
                if scales[item] > base and magnitude >= scales[item]]
    return tuple(dict.fromkeys((*readable[:1], unit or "")))


def _span(periods: list[str]) -> str:
    months = [_canonical_month_label(period) for period in periods]
    if months and all(months):
        return period_list_text(months)
    if not periods:
        return ""
    return periods[0] if len(periods) == 1 else f"{periods[0]}至{periods[-1]}"


def _full_window(period: str, periods: list[str]) -> bool:
    months = [_canonical_month_label(item) for item in periods]
    if not months or not all(months):
        return False
    return period in {f"{months[0]}..{months[-1]}", months[-1]} and (len(months) == 1 or ".." in period)


def _dimension_groups(bundle: DeterministicAnalysisBundle, parent_id: str | None) -> list[tuple[str, list[Any]]]:
    """按分组字段归并；不同字段的维度主名称相同时补写字段名，不能把两套分组列在同一名下。"""
    groups = {field: items for (parent, field), items in breakdown_partitions(bundle).items() if parent == parent_id}
    labels = {field: items[0].breakdown_label or field for field, items in groups.items()}
    repeated = {label for label in labels.values() if list(labels.values()).count(label) > 1}
    return [(f"{labels[field]}（{field}）" if labels[field] in repeated else labels[field], items)
            for field, items in groups.items()]


__all__ = ["deterministic_fact_summary"]
