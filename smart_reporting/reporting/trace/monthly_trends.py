"""Finite monthly level trends; endpoint change is never a monotonicity proof."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from ..hospital_operation.deterministic_analysis import DeterministicMetricFact, _parse_fact_period

TrendDirection = Literal["increasing", "decreasing", "constant", "mixed"]


def registered_monthly_trend(
    entry: Mapping[str, Any],
    *,
    profile_hash: str | None = None,
    warnings: Sequence[str] = (),
) -> tuple[dict | None, tuple[str, ...]]:
    try:
        metric = DeterministicMetricFact.model_validate(entry)
    except (ValueError, TypeError):
        return None, ("trend_input_invalid",)
    if profile_hash is not None and metric.profile_hash != profile_hash:
        return None, ("trend_input_identity_mismatch",)
    if metric.cumulative_policy is not None:
        return None, ("trend_cumulative_snapshot_requires_dedicated_rule",)
    if not metric.scope or not metric.unit:
        return None, ("trend_context_unknown",)
    if (
        metric.aggregation != "sum"
        or metric.period_aggregation not in {"sum", "last"}
        or metric.unit in {"%", "个百分点"}
        or "/" in metric.unit
        or "／" in metric.unit
    ):
        return None, ("trend_measure_semantics_unproven",)
    if (
        metric.missing_count != 0
        or metric.series_missing_count != 0
        or metric.period_missing_count != 0
        or metric.warnings
        or warnings
    ):
        return None, ("trend_completeness_unproven",)
    if metric.period_granularity != "month" or len(metric.period_values) < 3:
        return None, ("trend_monthly_window_required",)
    months = []
    amounts = []
    for item in metric.period_values:
        parsed = _parse_fact_period(item.period, "month")
        if parsed is None or parsed.granularity != "month" or not math.isfinite(item.value):
            return None, ("trend_monthly_window_required",)
        months.append(parsed.value.year * 12 + parsed.value.month - 1)
        amounts.append(item.value)
    if months != list(range(months[0], months[0] + len(months))):
        return None, ("trend_window_incomplete",)
    first = _parse_fact_period(metric.period_start or "", "month")
    last = _parse_fact_period(metric.period_end or "", "month")
    if (
        first is None
        or last is None
        or (
            first.value.year * 12 + first.value.month - 1 != months[0]
            or last.value.year * 12 + last.value.month - 1 != months[-1]
        )
    ):
        return None, ("trend_window_identity_mismatch",)
    pairs = tuple(zip(amounts, amounts[1:]))
    direction: TrendDirection
    if all(right > left for left, right in pairs):
        direction = "increasing"
    elif all(right < left for left, right in pairs):
        direction = "decreasing"
    elif all(right == left for left, right in pairs):
        direction = "constant"
    else:
        direction = "mixed"
    return {
        "direction": direction,
        "comparisons": len(pairs),
        "periods": tuple(f"{month // 12:04d}-{month % 12 + 1:02d}" for month in months),
    }, ()


_TREND_WORDING = re.compile(
    r"(?:逐月|每月|月月|各月(?:均|都)?|连续|持续|一路|稳步)(?:严格)?(?:[一二三四五六七八九十两\d]+个?月)?(?:严格)?"
    r"(?P<direction>增长|上升|回升|增加|下降|减少|回落|下滑|持平|不变)|(?P<mixed>混合变化)"
)


def has_monthly_trend_wording(text: str) -> bool:
    return _TREND_WORDING.search(text) is not None


def monthly_trend_wording_warnings(text: str, reference: Mapping[str, Any]) -> list[str]:
    for key, value in reference.get("scope", {}).items():
        text = text.replace(f"{key}={value}", "")
    from .business_semantics import complex_monthly_semantics, mask_registered_display_data

    text = mask_registered_display_data(text, reference)
    warnings, text = complex_monthly_semantics(text, reference)
    if warnings:
        return warnings
    matches = list(_TREND_WORDING.finditer(text))
    if re.search(r"连增|连降|先升后降|先降后升|单调|震荡", text) or (
        (matches or reference["selector"] == "monthlyTrend")
        and re.search(r"加速|放缓|显著|大幅|急剧", text)
    ):
        return ["连续趋势需复核：该趋势规则或幅度限定尚未完成校验。"]
    if not matches:
        return []
    if re.search(
        r"同比|环比|增长率|增速|累计|累加|稳步|预计|预测|有望|目标|计划|并非|不是|未必|不能|不代表",
        text,
    ):
        return ["连续趋势需复核：比率、累计、平稳程度、预测或否定表述未由登记月值趋势证明。"]
    if reference["selector"] != "monthlyTrend":
        return ["连续趋势需复核：当前数值引用未登记完整的趋势窗口，端点或合计不能证明逐月趋势。"]
    proof, reasons = registered_monthly_trend(reference["entry"])
    if reasons or proof is None or tuple(reference["periods"]) != proof["periods"]:
        return ["连续趋势需复核：当前冻结来源不足以证明完整月度趋势。"]
    counts = re.findall(
        r"(?:连续|持续|上升|增长|回升|增加|下降|减少|回落|持平)\s*([一二三四五六七八九十两\d]+)个?月",
        text,
    )
    chinese = {word: index for index, word in enumerate("一二三四五六七八九十", 1)}
    chinese.update({"两": 2, "十一": 11, "十二": 12})
    if any(
        (int(count) if count.isdigit() else chinese.get(count)) != len(proof["periods"])
        for count in counts
    ):
        return ["连续趋势需复核：正文连续月份数与登记窗口不一致或计数规则未明确。"]
    expected = set()
    for match in matches:
        word = match["direction"]
        expected.add(
            "mixed"
            if match["mixed"]
            else "constant"
            if word in {"持平", "不变"}
            else "decreasing"
            if word in {"下降", "减少", "回落", "下滑"}
            else "increasing"
        )
    if expected != {proof["direction"]}:
        return ["连续趋势需复核：正文趋势与全部相邻登记月份的未舍入值不一致。"]
    return []
