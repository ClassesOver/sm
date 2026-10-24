"""读者可验算的算式：派生值与对比值写出操作数的指标名、期间、带单位的登记原值与结果。

解析器给出的 formula 供服务端核对，写的是不带单位与期间的原始数（“(137989) - (153269)”），
对比值的变化额、本期与基期合计还沿用变化率公式，单条记录的最小值也只写“求和”，不能直接给读者看。
这里按同一组登记原值写成“2025年2月 137,989床日 − 2025年1月 153,269床日 = −15,280床日”，
读者可在来源卡片中自行验算。只描述已解析的数值，不参与核对与放行；写不出时返回 None，由调用方退回原口径。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from .comparison_proofs import period_list_text
from .numeric_text import _canonical_month_label, primary_display_name

_ROW_STATISTICS = {"average": "平均值", "minimum": "最小值", "maximum": "最大值"}
_AGGREGATION_WORDS = {"sum": "合计", "average": "平均值", "min": "最小值", "max": "最大值",
                      "count": "计数", "count_distinct": "去重计数"}


def _amount(value: Any, unit: str | None) -> str:
    from ..delivery.report_runtime.markdown import _readable_fact_value

    text = _readable_fact_value(float(Decimal(str(value))), unit)
    # 负数写减号“−”，与算式中的运算符一致。
    return "−" + text[1:] if text.startswith("-") else text


def _divisor(value: Any, unit: str | None) -> str:
    """变化率的分母按绝对值计算，与求值一致。"""
    return f"|{_amount(value, unit)}|" if Decimal(str(value)) < 0 else _amount(value, unit)


def _month(period: Any) -> str:
    from .table_builder import _period_display_label

    label = _canonical_month_label(str(period))
    return _period_display_label(label, "month") if label else str(period)


def _span(periods: Sequence[Any], granularity: str | None) -> str:
    """期间写成读者习惯的“2025年1—9月”；非逐月期间写首末两端。"""
    from .table_builder import _period_display_label

    values = [str(period) for period in periods]
    if not values:
        return ""
    if all(re.fullmatch(r"\d{4}-\d{2}", value) for value in values):
        return period_list_text(values)
    ends = dict.fromkeys((values[0], values[-1]))
    return "至".join(_period_display_label(value, granularity) for value in ends)


def _months(items: Sequence[Mapping[str, Any]]) -> list[str]:
    """逐月列出时同一年只写月份（期间一行已写明年份）。"""
    labels = [_canonical_month_label(str(item["period"])) for item in items]
    if all(labels) and len({label[:4] for label in labels if label}) == 1:
        return [f"{int(label[5:7])}月" for label in labels if label]
    return [_month(item["period"]) for item in items]


def _name(entry: Mapping[str, Any], entries: Mapping[str, Mapping[str, Any]]) -> str:
    # 比较事实没有自己的显示名，取输入指标的首个名称。
    for candidate in (entry, *(entries.get(key) or {} for key in entry.get("inputFactIds") or ())):
        if name := primary_display_name(candidate.get("displayName")):
            return name
    return str(entry.get("field") or entry.get("code") or "登记值")


def _labelled(label: str, amount: str) -> str:
    """标签与数值之间空一格；以全角括号结尾时不再空格。"""
    return f"{label}{amount}" if label.endswith("）") else f"{label} {amount}"


def _identity(parts: Sequence[Any]) -> str:
    """分组身份按登记的维度顺序列出，去掉空值与重复值，月初日期写成“2025年7月”。"""
    readable: list[str] = []
    for part in parts:
        text = str(part)
        if part is None or text in {"", "None", "null"}:
            continue
        text = _month(text) if _canonical_month_label(text) else text
        if text not in readable:
            readable.append(text)
    return " / ".join(readable)


def _group(group: Mapping[str, Any]) -> str:
    label = group.get("group")
    # 分组名按“ / ”连接各维度值；含分隔符时登记为 JSON，此时改用结构化维度值。
    if isinstance(label, str) and label and not label.startswith(("{", "[")):
        return _identity(label.split(" / ")) or label
    return _identity(list((group.get("groupValues") or {}).values())) or str(label or "")


def _window_sum(entry: Mapping[str, Any], window: Sequence[str]) -> Decimal:
    return sum(
        (
            Decimal(str(item["value"]))
            for item in entry.get("periodValues") or ()
            if window[0] <= (_canonical_month_label(str(item["period"])) or "") <= window[-1]
        ),
        Decimal(0),
    )


def reader_formula(
    resolved: Mapping[str, Any], ids: Sequence[str], entries: Mapping[str, Mapping[str, Any]],
) -> str | None:
    """已解析数值引用的读者算式；直接登记的合计与单月值沿用原口径（返回 None）。"""
    try:
        return _reader_formula(resolved, ids, entries)
    except (KeyError, IndexError, TypeError, ValueError, ArithmeticError):
        # 登记结构异常时不猜算式，卡片退回原口径。
        return None


def _reader_formula(
    resolved: Mapping[str, Any], ids: Sequence[str], entries: Mapping[str, Mapping[str, Any]],
) -> str | None:
    selector = resolved["selector"]
    entry = resolved["entry"]
    unit = entry.get("unit")
    result = f" = {_amount(resolved['value'], resolved['unit'])}"
    name = _name(entry, entries)
    granularity = entry.get("periodGranularity")
    values = entry.get("periodValues") or ()
    roles = resolved.get("period_roles") or {}

    if selector in _ROW_STATISTICS and entry.get("aggregation"):
        rows = "最新登记期间各条记录" if entry.get("periodAggregation") == "last" else "各条记录"
        return f"{name}{rows}中的{_ROW_STATISTICS[selector]}"
    if selector.startswith(("periodChanges.", "periodChangeRates.")):
        index = int(selector.split(".")[1])
        base, current = values[index - 1], values[index]
        difference = (f"{_month(current['period'])} {_amount(current['value'], unit)} − "
                      f"{_month(base['period'])} {_amount(base['value'], unit)}")
        if selector.startswith("periodChanges."):
            return difference + result
        return f"({difference}) ÷ {_divisor(base['value'], unit)} × 100%" + result
    if selector.startswith("periodTotals."):
        start, end = (int(index) for index in selector.split(".")[1].split("-"))
        window = values[start : end + 1]
        return " + ".join(
            f"{label} {_amount(item['value'], unit)}" for label, item in zip(_months(window), window, strict=True)
        ) + result
    if selector.startswith("periodAverages.") or selector == "monthlyAverage":
        if selector == "monthlyAverage":
            window = values
        else:
            start, end = (int(index) for index in selector.split(".")[1].split("-"))
            window = values[start : end + 1]
        total = sum((Decimal(str(item["value"])) for item in window), Decimal(0))
        span = _span([_canonical_month_label(str(item["period"])) or item["period"] for item in window], granularity)
        return f"{span}合计 {_amount(total, unit)} ÷ {len(window)}个月" + result
    if selector in {"monthlyMinimum", "monthlyMaximum"}:
        amounts = [Decimal(str(item["value"])) for item in values]
        extreme = min(amounts) if selector == "monthlyMinimum" else max(amounts)
        months = "、".join(_month(item["period"]) for item, amount in zip(values, amounts, strict=True)
                          if amount == extreme)
        span = _span([_canonical_month_label(str(item["period"])) or item["period"] for item in values], granularity)
        word = "最低" if selector == "monthlyMinimum" else "最高"
        return f"{span}逐月比较，{word}为{months} {_amount(extreme, unit)}"
    if selector == "monthlyTrend":
        return "逐月：" + " → ".join(
            f"{label} {_amount(item['value'], unit)}" for label, item in zip(_months(values), values, strict=True)
        )
    if selector.startswith(("topGroups.", "bottomGroups.")):
        from ..delivery.report_runtime.markdown import readable_formula

        key, index = selector.split(".")
        formula = entry.get("formula")
        method = readable_formula(formula, {str(entry.get("field")): name}) if formula else name
        return f"{_group(entry[key][int(index)])}：{method}"
    if selector.startswith("groupShares."):
        _, key, index = selector.split(".")
        group = entry[key][int(index)]
        return (f"{_group(group)} {_amount(group['value'], unit)} ÷ 总体 {_amount(entry['total'], unit)} × 100%"
                + result)
    if selector.startswith("groupGaps."):
        left, right = (entry["topGroups"][int(index)] for index in selector.split(".")[1].split("-"))
        return (f"|{_group(left)} {_amount(left['value'], unit)} − {_group(right)} {_amount(right['value'], unit)}|"
                + result)
    if entry.get("comparisonType") and selector in {"change", "changeRate", "currentTotal", "baselineTotal"}:
        inputs = [entries.get(key) or {} for key in entry.get("inputFactIds") or ()]
        word = next((_AGGREGATION_WORDS[item["aggregation"]] for item in inputs
                     if item.get("aggregation") in _AGGREGATION_WORDS), "值")
        current_span = _span(roles.get("current") or (), granularity)
        baseline_span = _span(roles.get("baseline") or (), granularity)
        scale = Decimal(str(entry.get("baselineScale") or 1))
        # 基期按登记的换算系数折算为本期单位后再比较。
        scaled = "" if scale == 1 else f"（基期已按 ×{format(scale.normalize(), 'f')} 换算为{unit}）"
        if selector == "currentTotal":
            return f"{name}本期{word}" + (f"（{current_span}）" if current_span else "")
        if selector == "baselineTotal":
            return f"{name}基期{word}" + (f"（{baseline_span}）" if baseline_span else "") + scaled
        current = _labelled(f"本期{word}" + (f"（{current_span}）" if current_span else ""),
                            _amount(entry["currentTotal"], unit))
        baseline = _labelled(f"基期{word}" + (f"（{baseline_span}）" if baseline_span else ""),
                             _amount(entry["baselineTotal"], unit))
        if selector == "change":
            return f"{current} − {baseline}{scaled}" + result
        return (f"({current} − {baseline}) ÷ {_divisor(entry['baselineTotal'], unit)} × 100%{scaled}"
                + result)
    if selector.startswith(("budgetComparison.", "metricShare.", "projectRatio.")):
        other = entries[ids[1]]
        other_name = _name(other, entries)
        span = _span(resolved.get("periods") or (), granularity)
        rest = selector.split(".", 1)[1][len(ids[1]):]
        if selector.startswith("budgetComparison."):
            window = rest[1:].rsplit(".", 1)[0].split("..")
            left, right = _window_sum(entry, window), _window_sum(other, window)
        elif selector.startswith("metricShare.") and rest.startswith("."):
            window = rest[1:].split("..")
            left, right = _window_sum(entry, window), _window_sum(other, window)
        else:
            left, right = Decimal(str(entry["total"])), Decimal(str(other["total"]))
        within = f"（{span}）" if span else ""
        operands = (_labelled(f"{name}{within}", _amount(left, unit)),
                    _labelled(f"{other_name}{within}", _amount(right, other.get("unit"))))
        if selector.endswith(".difference"):
            return f"{operands[0]} − {operands[1]}" + result
        return f"{operands[0]} ÷ {operands[1]} × 100%" + result
    if proof := resolved.get("_cumulative_change_proof"):
        current = f"{_month(proof['current_period'])}累计 {_amount(proof['current_value'], unit)}"
        if proof["reset"]:
            return f"{current} − 0（自然年首月从零起算）" + result
        return (f"{current} − {_month(proof['baseline_period'])}累计 {_amount(proof['baseline_value'], unit)}"
                + result)
    if selector.startswith("groupContributions.") and (proof := resolved.get("_group_contribution_proof")):
        index = int(selector.split(".")[1])
        member = _identity(list(proof["members"][index].values()))
        return (f"{member}变化 {_amount(proof['deltas'][index], unit)} ÷ "
                f"总体净变化 {_amount(proof['netChange'], unit)} × 100%" + result)
    return None


__all__ = ["reader_formula"]
