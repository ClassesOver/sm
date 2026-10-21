"""Finite signed differences of explicitly registered cumulative snapshots.

These differences can include retrospective corrections.  They are never a
proof of a month's business flow, even when a calendar-year reset is known.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext
from typing import Any

from ..hospital_operation.deterministic_analysis import DeterministicMetricFact, _parse_fact_period
from ..units import MONEY_UNITS, VISIT_UNITS

_SCALAR_UNITS = frozenset((*MONEY_UNITS, *VISIT_UNITS, "人", "次", "床日", "床"))


def _snapshot_month(label: str):
    normalized = re.sub(r'^(\d{4})年(\d{1,2})月$', r'\1-\2', label.strip())
    # A bare year is an annual observation, never a January snapshot.
    if re.fullmatch(r'\d{4}', normalized):
        return None
    return _parse_fact_period(normalized, "month")


def registered_cumulative_changes(
    entry: Mapping[str, Any],
    *,
    profile_hash: str | None = None,
    warnings: Sequence[str] = (),
) -> tuple[dict[str, dict], tuple[str, ...]]:
    """Read a frozen trusted policy; never infer reset semantics from a label."""
    try:
        metric = DeterministicMetricFact.model_validate(entry)
    except (ValueError, TypeError):
        return {}, ("cumulative_input_invalid",)
    if (
        metric.fact_id is None
        or metric.profile_hash is None
        or (profile_hash is not None and metric.profile_hash != profile_hash)
    ):
        return {}, ("cumulative_registration_identity_unproven",)
    if metric.cumulative_policy is None:
        return {}, ("cumulative_policy_unproven",)
    if not metric.scope or metric.unit not in _SCALAR_UNITS:
        return {}, ("cumulative_context_unproven",)
    if (
        metric.aggregation != "sum"
        or metric.period_aggregation != "last"
        or metric.period_granularity != "month"
        or not metric.period_field
    ):
        return {}, ("cumulative_measure_semantics_unproven",)
    if (
        metric.missing_count != 0
        or metric.series_missing_count != 0
        or metric.period_missing_count != 0
        or metric.warnings
        or warnings
    ):
        return {}, ("cumulative_completeness_unproven",)
    if not metric.period_values:
        return {}, ("cumulative_monthly_window_required",)
    months = []
    amounts = []
    for item in metric.period_values:
        parsed = _snapshot_month(item.period)
        if parsed is None or parsed.granularity != "month" or not math.isfinite(item.value):
            return {}, ("cumulative_monthly_window_required",)
        months.append(parsed.value.year * 12 + parsed.value.month - 1)
        amounts.append(Decimal(str(item.value)))
    if months != list(range(months[0], months[0] + len(months))):
        return {}, ("cumulative_window_incomplete",)
    first = _snapshot_month(metric.period_start or "")
    last = _snapshot_month(metric.period_end or "")
    if (
        first is None
        or last is None
        or first.value.year * 12 + first.value.month - 1 != months[0]
        or last.value.year * 12 + last.value.month - 1 != months[-1]
        or not math.isfinite(metric.total)
        or Decimal(str(metric.total)) != amounts[-1]
    ):
        return {}, ("cumulative_window_identity_mismatch",)

    proofs = {}
    # Exact differences across the full finite float range need up to 634
    # decimal places.  Default Decimal precision would silently round them.
    with localcontext() as ctx:
        ctx.prec = 700
        for index, (month, current) in enumerate(zip(months, amounts, strict=True)):
            reset = month % 12 == 0
            if not reset and index == 0:
                # A window beginning in (say) February has no January premise.
                # Missing snapshots are not implicit zero baselines.
                continue
            baseline = Decimal(0) if reset else amounts[index - 1]
            value = current - baseline
            converted = float(value)
            if not math.isfinite(converted) or (value != 0 and converted == 0):
                return {}, ("cumulative_difference_out_of_range",)
            proofs[f"cumulativeChanges.{index}"] = {
                "value": value,
                "current_period": _month_label(month),
                "baseline_period": None if reset else _month_label(months[index - 1]),
                "current_value": current,
                "baseline_value": baseline,
                "reset": reset,
                "unit": metric.unit,
            }
    return proofs, ()


def _month_label(month: int) -> str:
    return f"{month // 12:04d}-{month % 12 + 1:02d}"


def cumulative_change_template(proof: Mapping[str, Any], subject: str, number: str) -> str:
    """Canonical snapshot language: one bound value, no implicit flow premise."""
    baseline = (
        "按自然年重置零基线"
        if proof["reset"]
        else f"以{proof['baseline_period']}月末累计快照为基线"
    )
    return (
        f"{proof['current_period']}月末，{subject}，{baseline}，累计快照变化为{number}"
        "（累计快照变化，可能包含追溯调整，不等同当期业务流量）"
    )
