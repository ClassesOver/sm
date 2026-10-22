"""Shared deterministic comparison proof for arithmetic and decomposition consumers."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal


def registered_comparison_reasons(
    operation: str,
    comparison: str,
    view: Mapping[str, Any],
    entries: Mapping[str, Any],
    *,
    profile_hash: str,
    fact_warnings: Mapping[str, Any],
) -> list[str]:
    from ..hospital_operation.deterministic_analysis import (
        DeterministicMetricFact,
        _aligned_comparison_values,
    )
    from ..units import unit_conversion_scale
    from .subject_builder import fact_periods

    entry = view["entry"]
    # “value” 只用于比较事实两侧登记合计（currentTotal/baselineTotal），同样须重算窗口与合计。
    selector = {"difference": "change", "relative_change": "changeRate"}.get(
        operation, view["selector"] if operation == "value" else ""
    )
    if (
        view["selector"] != selector
        or operation == "value" and selector not in {"currentTotal", "baselineTotal"}
        or comparison not in {"yoy", "mom"}
        or comparison != entry.get("comparisonType")
    ):
        return ["comparison_selector_mismatch"]
    ids = entry.get("inputFactIds", ())
    if len(ids) != 2 or len(set(ids)) != 2 or any(key not in entries for key in ids):
        return ["comparison_inputs_unavailable"]
    try:
        current, baseline = (DeterministicMetricFact.model_validate(entries[key]) for key in ids)
    except ValueError:
        return ["comparison_inputs_invalid"]
    for role, metric in (("current", current), ("baseline", baseline)):
        if metric.cumulative_policy is not None:
            return ["comparison_cumulative_snapshot_requires_dedicated_rule"]
        expected_role = "current" if role == "current" else comparison
        if (
            metric.dataset_id != entry.get(role + "DatasetId")
            or metric.dataset_sha256 != entry.get(role + "DatasetSha256")
            or metric.field_ref != entry.get("fieldRef")
            or metric.scope != view["scope"]
            or metric.profile_hash != profile_hash
            or expected_role not in metric.period_roles
        ):
            return ["comparison_input_identity_mismatch"]
    if any(
        metric.missing_count != 0
        or metric.period_missing_count != 0
        or metric.series_missing_count not in {None, 0}
        for metric in (current, baseline)
    ):
        return ["comparison_completeness_unproven"]
    if (
        current.aggregation != baseline.aggregation
        or current.period_aggregation != baseline.period_aggregation
        or any(fact_warnings.get(key) for key in (*ids, entry.get("factId")))
    ):
        return ["comparison_definition_unproven"]
    grain = current.period_granularity
    if (
        grain is None
        or baseline.period_granularity != grain
        or entry.get("periodGranularity") != grain
    ):
        return ["comparison_granularity_unproven"]
    if grain in {"day", "year"} and any(
        metric.series_missing_count != 0 for metric in (current, baseline)
    ):
        return ["comparison_numeric_series_completeness_unproven"]
    if comparison == "same_period":
        return ["comparison_selector_mismatch"]
    aligned = _aligned_comparison_values(current, baseline, "yoy" if comparison == "yoy" else "mom")
    scale = unit_conversion_scale(baseline.unit, current.unit)
    if aligned is None or scale is None or entry.get("unit") != current.unit or aligned[6]:
        return ["comparison_window_unproven"]
    current_periods = fact_periods(
        {
            "periodStart": aligned[2],
            "periodEnd": aligned[3],
            "periodGranularity": current.period_granularity,
        }
    )
    baseline_periods = fact_periods(
        {
            "periodStart": aligned[4],
            "periodEnd": aligned[5],
            "periodGranularity": baseline.period_granularity,
        }
    )
    roles = view["period_roles"]
    if (
        not _comparable_periods(current_periods, baseline_periods, comparison, grain=grain)
        or selector != "baselineTotal" and tuple(roles.get("current", ())) != current_periods
        or selector != "currentTotal" and tuple(roles.get("baseline", ())) != baseline_periods
    ):
        return ["comparison_window_mismatch"]
    # Metadata endpoints cannot fill an absent leap day or any other bucket.
    # Recheck the actual registered input series inside each aligned window.
    from ..hospital_operation.deterministic_analysis import _parsed_period_values

    for metric, window in ((current, current_periods), (baseline, baseline_periods)):
        parsed = _parsed_period_values(metric)
        labels = tuple(_period_label(period.value, grain) for period, _ in parsed or ())
        selected = tuple(label for label in labels if window[0] <= label <= window[-1])
        if selected != window:
            return ["comparison_calendar_completeness_unproven"]
    if (len(current_periods) > 1 or len(baseline_periods) > 1) and any(
        metric.period_aggregation != "sum" or metric.aggregation not in {"sum", "count"}
        for metric in (current, baseline)
    ):
        # Historical empty metadata remains unknown; a row aggregation
        # alone never establishes additivity across the reporting axis.
        return ["time_additivity_unproven"]
    current_total, baseline_total = aligned[0], float(Decimal(str(aligned[1])) * scale)
    delta = current_total - baseline_total
    if operation == "relative_change" and baseline_total <= 0:
        return ["positive_baseline_required"]
    expected = {
        "change": delta,
        "currentTotal": current_total,
        "baselineTotal": baseline_total,
    }.get(selector) if selector != "changeRate" else delta / baseline_total * 100
    recorded = entry.get(selector)
    # Inputs and the registered record were computed with the same server
    # arithmetic. Never use a relative tolerance that admits a changed
    # currency amount merely because the total is large.
    if (
        recorded is None
        or float(recorded) != expected
        or float(entry.get("currentTotal")) != current_total
        or float(entry.get("baselineTotal")) != baseline_total
        or float(entry.get("baselineScale", 1)) != float(scale)
    ):
        return ["comparison_value_mismatch"]
    return []


def _period_label(value, grain: str) -> str:
    return value.isoformat()[: {"year": 4, "month": 7, "day": 10}[grain]]


def _comparable_periods(
    current: tuple[str, ...],
    baseline: tuple[str, ...],
    kind: str,
    *,
    grain: Literal["day", "month", "year"] = "month",
) -> bool:
    """Calendar windows, with explicit daily/yearly policies for registered facts.

    Daily YoY covers whole calendar windows, including an internal leap day on
    its actual side. Daily/annual prior-period comparisons are single buckets.
    The default remains monthly for older callers without a declared grain.
    """
    if kind == "same_period":
        return bool(current) and current == baseline
    if kind not in {"yoy", "mom"} or grain not in {"day", "month", "year"}:
        return False
    from ..hospital_operation.deterministic_analysis import _next_period, _parse_fact_period

    def calendar(values):
        parsed = [_parse_fact_period(value, grain) for value in values]
        if not values or any(period is None for period in parsed):
            return None
        periods = [period for period in parsed if period is not None]
        if any(
            _period_label(period.value, grain) != label
            for period, label in zip(periods, values, strict=True)
        ):
            return None
        if any(_next_period(left) != right.value for left, right in zip(periods, periods[1:])):
            return None
        return periods

    try:
        left, right = calendar(current), calendar(baseline)
        if not left or not right:
            return False
        if grain == "day":
            if kind == "mom":
                return len(left) == len(right) == 1 and _next_period(right[0]) == left[0].value
            return (
                left[0].value.replace(year=left[0].value.year - 1) == right[0].value
                and left[-1].value.replace(year=left[-1].value.year - 1) == right[-1].value
            )
        if len(left) != len(right):
            return False
        if grain == "year":
            return (kind != "mom" or len(left) == 1) and all(
                a.value.year == b.value.year + 1 for a, b in zip(left, right, strict=True)
            )
        offset = 12 if kind == "yoy" else 1
        return all(
            (a.value.year - b.value.year) * 12 + a.value.month - b.value.month == offset
            for a, b in zip(left, right, strict=True)
        )
    except (ValueError, OverflowError, KeyError):
        return False


def period_window_label(periods) -> str:
    def label(value):
        return value + "年" if len(value) == 4 and value.isdigit() else value

    return label(periods[0]) if len(periods) == 1 else f"{label(periods[0])}至{label(periods[-1])}"


def comparison_word(kind: str, periods) -> str:
    if kind == "same_period":
        return "同期间比较"
    if kind == "yoy":
        return "同比"
    if all(len(value) == 10 for value in periods):
        return "较前一日"
    if all(len(value) == 4 for value in periods):
        return "较上一年"
    return "环比"


def comparison_wording_warnings(text, reference) -> list[str]:
    """A right amount cannot change its YoY/prior-period role or calendar grain."""
    import re

    selector = reference["selector"]
    entry = reference["entry"]
    if selector not in {"change", "changeRate"} and not selector.startswith(
        ("periodChanges.", "periodChangeRates.")
    ):
        return []
    kind = entry.get("comparisonType") or (
        "mom" if selector.startswith(("periodChanges.", "periodChangeRates.")) else None
    )
    if kind not in {"yoy", "mom"}:
        return []
    from .assertions import _label

    # Canonical source names and scope values are data, not a calendar assertion.
    for key, value in reference.get("scope", {}).items():
        text = text.replace(f"{_label(key)}={_label(value)}", "")
    for name in (entry.get("displayName"), entry.get("field"), *(entry.get("aliases") or ()), *reference.get("_comparison_subjects", ())):
        if isinstance(name, str) and name:
            text = text.replace(f"，{_label(name)}，本期", "，指标，本期")
    grain = entry.get("periodGranularity")
    if kind == "yoy" and grain != "year" and re.search(r"环比|较前一日|较上(?:一)?期", text):
        return ["比较口径需复核：当前同比证明不能用于前一统计期比较。"]
    if kind == "mom" and grain != "year" and "同比" in text:
        return ["比较口径需复核：当前前期比较证明不能用于同比。"]
    if grain == "day" and re.search(
        r"月环比|月度环比|较上月|较前一月|月度同比|月同比|年环比", text
    ):
        return ["比较粒度需复核：日度证据不能替代月度或年度比较。"]
    if grain == "year" and re.search(
        r"月环比|月度环比|日环比|日度环比|月度同比|日度同比|较上月|较前一日", text
    ):
        return ["比较粒度需复核：年度证据不能替代日度或月度比较。"]
    if grain == "month" and re.search(r"日环比|日度环比|较前一日|日度同比|年度同比", text):
        return ["比较粒度需复核：月度证据不能替代日度或年度比较。"]
    return []
