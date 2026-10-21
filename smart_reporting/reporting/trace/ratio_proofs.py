"""Registered ratio of aligned totals; no inferred subset or average-of-ratios."""

from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import Decimal, localcontext
from typing import Any

from ..hospital_operation.deterministic_analysis import (
    DeterministicDerivedMetricFact,
    DeterministicMetricFact,
    _aligned_period_totals,
    _parsed_period_values,
)
from ..units import MONEY_UNITS, VISIT_UNITS, unit_conversion_scale
from .comparison_proofs import _period_label, period_window_label
from .subject_builder import fact_periods

_COUNT_UNITS = {"人次", "人", "次", "床日", "床"}


def _base_unit(unit):
    if unit in MONEY_UNITS:
        return "元", MONEY_UNITS[unit]
    if unit in VISIT_UNITS:
        return "人次", VISIT_UNITS[unit]
    if unit in _COUNT_UNITS:
        return unit, Decimal(1)
    return None


def registered_ratio(
    entry: Mapping[str, Any],
    entries: Mapping[str, Any],
    *,
    profile_hash: str,
    fact_warnings: Mapping[str, Any],
) -> tuple[dict | None, tuple[str, ...]]:
    """Use exact registered dependency IDs and metadata, never metric name matching."""
    try:
        ratio = DeterministicDerivedMetricFact.model_validate(entry)
    except (ValueError, TypeError):
        return None, ("ratio_record_invalid",)
    ids = ratio.input_fact_ids
    if len(ids) != 2 or len(set(ids)) != 2 or any(key not in entries for key in ids):
        return None, ("ratio_inputs_unavailable",)
    try:
        numerator, denominator = (
            DeterministicMetricFact.model_validate(entries[key]) for key in ids
        )
    except (ValueError, TypeError):
        return None, ("ratio_input_invalid",)
    if (
        ratio.profile_hash != profile_hash
        or numerator.profile_hash != profile_hash
        or denominator.profile_hash != profile_hash
        or ratio.numerator_metric not in numerator.metric_codes
        or ratio.denominator_metric not in denominator.metric_codes
        or any(ratio.period_role not in metric.period_roles for metric in (numerator, denominator))
    ):
        return None, ("ratio_registration_identity_unproven",)
    if (
        not numerator.scope
        or numerator.scope != denominator.scope
        or ratio.scope != numerator.scope
    ):
        return None, ("ratio_scope_unproven",)
    if ratio.dataset_ids != tuple(
        dict.fromkeys(metric.dataset_id for metric in (numerator, denominator))
    ) or ratio.dataset_sha256s != tuple(
        dict.fromkeys(metric.dataset_sha256 for metric in (numerator, denominator))
    ):
        return None, ("ratio_source_identity_mismatch",)
    if ratio.fact_id is None or any(
        metric.fact_id != key for metric, key in zip((numerator, denominator), ids, strict=True)
    ):
        return None, ("ratio_registration_identity_unproven",)
    if any(metric.warnings for metric in (ratio, numerator, denominator)) or any(
        fact_warnings.get(key) for key in (*ids, ratio.fact_id)
    ):
        return None, ("ratio_input_warning",)
    if any(
        metric.missing_count != 0
        or metric.period_missing_count != 0
        or metric.series_missing_count != 0
        for metric in (numerator, denominator)
    ):
        return None, ("ratio_completeness_unproven",)
    grain = numerator.period_granularity
    if (
        grain is None
        or denominator.period_granularity != grain
        or ratio.period_granularity != grain
        or numerator.period_aggregation not in {"sum", "last"}
        or numerator.period_aggregation != denominator.period_aggregation
        or any(metric.aggregation not in {"sum", "count"} for metric in (numerator, denominator))
    ):
        return None, ("ratio_aggregation_policy_unproven",)
    if numerator.period_aggregation == "last" and any(
        metric.aggregation != "sum" for metric in (numerator, denominator)
    ):
        return None, ("ratio_aggregation_policy_unproven",)
    base_num, base_den = _base_unit(numerator.unit), _base_unit(denominator.unit)
    if base_num is None or base_den is None:
        return None, ("ratio_unit_unproven",)
    conversion = unit_conversion_scale(denominator.unit, numerator.unit)
    if conversion is None and (
        base_den[0] not in _COUNT_UNITS or base_num[0] not in {"元", "人次", "床日"}
    ):
        return None, ("ratio_compound_unit_not_supported",)
    used_values = [
        ratio.numerator,
        ratio.denominator,
        ratio.denominator_scale,
        ratio.value,
        ratio.percentage,
        ratio.difference,
    ]
    used_values.extend(metric.total for metric in (numerator, denominator))
    used_values.extend(
        item.value for metric in (numerator, denominator) for item in metric.period_values
    )
    if any(not math.isfinite(value) for value in used_values if value is not None):
        return None, ("ratio_nonfinite_input",)
    try:
        aligned = _aligned_period_totals(numerator, denominator)
    except (ValueError, TypeError, ArithmeticError):
        return None, ("ratio_window_unproven",)
    if aligned is None or aligned[4]:
        return None, ("ratio_window_unproven",)
    periods = fact_periods(entry)
    expected_periods = fact_periods(
        {"periodStart": aligned[2], "periodEnd": aligned[3], "periodGranularity": grain}
    )
    if not periods or periods != expected_periods:
        return None, ("ratio_window_mismatch",)
    for metric in (numerator, denominator):
        parsed = _parsed_period_values(metric)
        labels = tuple(_period_label(period.value, grain) for period, _ in parsed or ())
        selected = tuple(label for label in labels if periods[0] <= label <= periods[-1])
        if selected != periods:
            return None, ("ratio_calendar_completeness_unproven",)
    scale = conversion if conversion is not None else Decimal(1)
    recorded_denominator = float(Decimal(str(aligned[1])) * scale)
    if aligned[0] < 0 or recorded_denominator <= 0:
        return None, ("ratio_positive_denominator_required",)
    if not math.isfinite(recorded_denominator):
        return None, ("ratio_unit_conversion_overflow",)
    value = aligned[0] / recorded_denominator
    percentage = value * 100 if conversion is not None else None
    expected_difference = aligned[0] - recorded_denominator if conversion is not None else None
    if (
        ratio.numerator != aligned[0]
        or ratio.denominator != recorded_denominator
        or ratio.denominator_scale != float(scale)
        or ratio.value != value
        or ratio.percentage != percentage
        or ratio.difference != expected_difference
        or ratio.unit != (numerator.unit if conversion is not None else None)
    ):
        return None, ("ratio_record_value_mismatch",)
    with localcontext() as ctx:
        ctx.prec = 64
        # Percent records preserve the registered producer's arithmetic. Compound
        # quotients use explicitly confirmed base-unit scales, never a unit label
        # change without applying its multiplier to the value.
        result = (
            Decimal(str(percentage))
            if conversion is not None
            else Decimal(str(aligned[0])) * base_num[1] / (Decimal(str(aligned[1])) * base_den[1])
        )
    if not math.isfinite(float(result)) or (result != 0 and float(result) == 0):
        return None, ("ratio_unit_conversion_overflow",)
    return {
        "value": result,
        "unit": "%" if conversion is not None else f"{base_num[0]}/{base_den[0]}",
        "periods": periods,
        "policy": numerator.period_aggregation,
        "numeratorLabel": numerator.display_name or numerator.field,
        "denominatorLabel": denominator.display_name or denominator.field,
        "numeratorValue": str(Decimal(str(aligned[0])) * base_num[1]),
        "denominatorValue": str(Decimal(str(aligned[1])) * base_den[1]),
    }, ()


def ratio_fragment_prefix(
    *, periods, scope, subject, numerator_label, denominator_label, policy
) -> str:
    from .assertions import _label

    scope_text = "、".join(f"{_label(key)}={_label(value)}" for key, value in sorted(scope.items()))
    basis = "共同期末分子值除以分母值" if policy == "last" else "同期分子总量除以同期分母总量"
    return (
        f"{period_window_label(periods)}，范围（{scope_text}），指标{_label(subject)}，"
        f"分子（{_label(numerator_label)}）、分母（{_label(denominator_label)}），"
        f"按{basis}计算（不是各期比率的平均，不表示总体隶属关系），比率为"
    )


def ratio_wording_warnings(text, reference) -> tuple[list[str], str]:
    if reference["selector"] != "registeredRatio":
        return [], text
    proof = reference.get("_registered_ratio_proof")
    if proof is None:
        return ["比率口径需复核：同期分子、分母和计算政策尚未核验。"], text
    entry = reference["entry"]
    expected = ratio_fragment_prefix(
        periods=proof["periods"],
        scope=entry["scope"],
        subject=entry["code"],
        numerator_label=proof["numeratorLabel"],
        denominator_label=proof["denominatorLabel"],
        policy=proof["policy"],
    )
    if expected not in text:
        return ["比率口径需复核：分子、分母、期间或总量之比政策与冻结证据不一致。"], text
    remaining = text.replace(expected, " ", 1)
    import re

    from .business_semantics import _NEGATION

    for match in re.finditer(
        r"平均比率|平均比例|(?:各期)?比率(?:的)?平均|占比|构成比|份额|(?:同比|环比)(?:增长率|变化率)?|增长率|贡献率|(?:完成|执行|达成|转化|利用)率|累计|累加|全年|年均|月均|年初至今",
        remaining,
    ):
        if not _NEGATION.search(remaining[: match.start()]):
            return [
                "比率口径需复核：同期总量之比不能替代各期平均、变化率、累计政策或总体隶属证明。"
            ], remaining
    return [], remaining
