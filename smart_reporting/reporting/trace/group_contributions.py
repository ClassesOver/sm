"""Signed arithmetic contributions over two complete frozen group partitions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, localcontext
from typing import Any

from .comparison_proofs import comparison_word, period_window_label, registered_comparison_reasons
from .top_sets import display_members, registered_top_sets


def registered_group_contributions(
    entry: Mapping[str, Any],
    entries: Mapping[str, Any],
    *,
    profile_hash: str,
    fact_warnings: Mapping[str, Any],
) -> tuple[dict | None, tuple[str, ...]]:
    """No absent group is silently zero-filled; no trimmed window uses full totals."""
    from ..units import unit_conversion_scale
    from .subject_builder import fact_periods

    if entry.get("warnings"):
        return None, ("contribution_comparison_warning",)
    ids = entry.get("inputFactIds", ())
    if len(ids) != 2 or any(key not in entries for key in ids):
        return None, ("contribution_inputs_unavailable",)
    current, baseline = (entries[key] for key in ids)
    windows = []
    for metric in (current, baseline):
        periods = fact_periods(metric)
        if metric.get("periodAggregation") == "last":
            periods = periods[-1:]
        windows.append(tuple(periods))
    view = {
        "entry": entry,
        "selector": "change",
        "scope": entry.get("scope", {}),
        "period_roles": dict(zip(("current", "baseline"), windows, strict=True)),
    }
    try:
        reasons = registered_comparison_reasons(
            "difference",
            str(entry.get("comparisonType")),
            view,
            entries,
            profile_hash=profile_hash,
            fact_warnings=fact_warnings,
        )
    except (ValueError, TypeError, ArithmeticError, KeyError):
        return None, ("contribution_comparison_invalid",)
    if reasons:
        return None, tuple(reasons)
    # The comparison proof above requires the registered aligned window to equal
    # both full partition windows. It rejects a current/baseline partial overlap.
    for metric in (current, baseline):
        _, partition_reasons = registered_top_sets(
            metric,
            profile_hash=profile_hash,
            warnings=tuple(fact_warnings.get(metric.get("factId"), ())),
        )
        if partition_reasons:
            return None, partition_reasons

    def identity(group):
        return tuple(sorted(group["groupValues"].items()))

    left = {identity(group): group for group in current["groupPopulation"]}
    right = {identity(group): group for group in baseline["groupPopulation"]}
    if left.keys() != right.keys():
        return None, ("contribution_group_membership_mismatch",)
    scale = unit_conversion_scale(baseline.get("unit"), current.get("unit"))
    if scale is None:
        return None, ("contribution_units_unproven",)
    with localcontext() as ctx:
        ctx.prec = 64
        members = []
        deltas = []
        for key in sorted(left):
            members.append(dict(left[key]["groupValues"]))
            deltas.append(
                Decimal(str(left[key]["value"])) - Decimal(str(right[key]["value"])) * scale
            )
        net = sum(deltas, Decimal(0))
        # Exact closure in registered decimal values is deliberate. A rounded
        # or floating aggregate must never become a different hidden denominator.
        expected = Decimal(str(entry["currentTotal"])) - Decimal(str(entry["baselineTotal"]))
        if net != expected or Decimal(str(entry["change"])) != net:
            return None, ("contribution_partition_closure_unproven",)
        if net == 0:
            return None, ("contribution_net_change_zero",)
        values = tuple(delta / net * 100 for delta in deltas)
    return {
        "members": tuple(members),
        "deltas": tuple(deltas),
        "values": values,
        "netChange": net,
        "currentPeriods": windows[0],
        "baselinePeriods": windows[1],
    }, ()


def contribution_fragment_prefix(
    *,
    members: Sequence[Mapping[str, str]],
    group: Mapping[str, str],
    scope: Mapping[str, str],
    subject: str,
    periods: Sequence[str],
    baseline_periods: Sequence[str],
    comparison: str,
) -> str:
    from .assertions import _label

    scope_text = "、".join(f"{_label(key)}={_label(value)}" for key, value in sorted(scope.items()))
    kind = comparison_word(comparison, periods)
    return (
        f"{scope_text}，{_label(subject)}，本期{period_window_label(periods)}、基期{period_window_label(baseline_periods)}，"
        f"{kind}完整分组对照清单：{display_members(members)}，"
        "按分组差额除以总体有符号净差额计算（允许负贡献及贡献超过百分之百，不代表因果），"
        f"分组{display_members((group,))}的算术贡献率为"
    )


def contribution_wording_warnings(text: str, reference: Mapping[str, Any]) -> tuple[list[str], str]:
    """Only the exact registered fragment consumes the contribution qualifier."""
    if not reference["selector"].startswith("groupContributions."):
        return [], text
    proof = reference.get("_group_contribution_proof")
    if proof is None:
        return ["贡献分解需复核：完整同期分组对照证明不可用。"], text
    try:
        index = int(reference["selector"].split(".")[1])
        entry = reference["entry"]
        expected = contribution_fragment_prefix(
            members=proof["members"],
            group=proof["members"][index],
            scope=entry["scope"],
            subject=entry.get("displayName") or entry.get("field") or "指标",
            periods=proof["currentPeriods"],
            baseline_periods=proof["baselinePeriods"],
            comparison=entry["comparisonType"],
        )
        if expected not in text:
            return ["贡献分解需复核：成员、期间、分母口径或所选分组与冻结证明不一致。"], text
        return [], text.replace(expected, " ", 1)
    except (KeyError, IndexError, TypeError, ValueError):
        return ["贡献分解需复核：当前分组选择器不可解析。"], text
