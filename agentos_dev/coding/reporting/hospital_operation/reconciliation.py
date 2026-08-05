from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from ..models import ReportingError
from .factset import CoverageStatus, HospitalOperationFact, OperationModel


class ReconciliationPoint(OperationModel):
    period: str = Field(min_length=1, max_length=32)
    left: Decimal
    right: Decimal
    difference: Decimal
    status: Literal["complete", "conflict"]


class ReconciliationResult(OperationModel):
    code: str = Field(min_length=1, max_length=128)
    status: Literal["complete", "conflict", "unavailable"]
    points: tuple[ReconciliationPoint, ...] = Field(default=(), max_length=1_200)
    issues: tuple[str, ...] = Field(default=(), max_length=100)


class DuplicateConflict(OperationModel):
    identity: tuple[str, ...] = Field(min_length=1, max_length=20)
    values: tuple[Decimal, ...] = Field(min_length=2, max_length=100)


def reconcile_series(
    code: str,
    left: Mapping[str, Decimal | int | str],
    right: Mapping[str, Decimal | int | str],
    *,
    absolute_tolerance: Decimal = Decimal("0"),
) -> ReconciliationResult:
    if absolute_tolerance < 0:
        raise ValueError("对账容差不能为负")
    periods = sorted(set(left) | set(right))
    points: list[ReconciliationPoint] = []
    issues: list[str] = []
    for period in periods:
        if period not in left or period not in right:
            issues.append(f"{period} 缺少一侧数据")
            continue
        left_value = Decimal(str(left[period]))
        right_value = Decimal(str(right[period]))
        difference = left_value - right_value
        status: Literal["complete", "conflict"] = (
            "complete" if abs(difference) <= absolute_tolerance else "conflict"
        )
        points.append(
            ReconciliationPoint(
                period=period,
                left=left_value,
                right=right_value,
                difference=difference,
                status=status,
            )
        )
        if status == "conflict":
            issues.append(f"{period} 差异 {difference} 超过容差 {absolute_tolerance}")
    if not points:
        return ReconciliationResult(code=code, status="unavailable", issues=tuple(issues))
    return ReconciliationResult(
        code=code,
        status="conflict" if issues else "complete",
        points=tuple(points),
        issues=tuple(issues),
    )


def reject_double_counting(facts: Iterable[HospitalOperationFact]) -> None:
    """总额和其组成子集不能进入同一加总，防止医疗收入重复累计药品、材料。"""
    selected = tuple(facts)
    metrics = {item.metric for item in selected}
    conflicting = sorted(
        {
            item.parent_metric
            for item in selected
            if item.is_subset and item.parent_metric in metrics
        }
    )
    if conflicting:
        raise ReportingError(
            "hospital_operation_double_counting",
            f"总额与组成子集不能重复累计: {', '.join(conflicting)}",
        )


def coverage_status(
    expected_periods: Iterable[str],
    observed_periods: Iterable[str],
    *,
    explicit_zero_placeholders: Iterable[str] = (),
    confirmed_partial: bool = False,
    has_conflict: bool = False,
    unconfirmed: bool = False,
) -> CoverageStatus:
    """覆盖只依据行/显式状态判断，绝不把低值月份自动推断为 partial。"""
    if has_conflict:
        return "conflict"
    if unconfirmed:
        return "unconfirmed"
    expected = set(expected_periods)
    observed = set(observed_periods)
    placeholders = set(explicit_zero_placeholders)
    if placeholders - expected or observed - expected:
        raise ValueError("覆盖期间超出请求范围")
    if expected and placeholders == expected:
        return "zero_placeholder"
    if expected.issubset(observed | placeholders):
        return "zero_placeholder" if placeholders else "complete"
    if observed or placeholders:
        return "partial" if confirmed_partial else "missing"
    return "missing"


def detect_duplicate_conflicts(
    rows: Sequence[Mapping[str, Any]],
    *,
    identity_fields: tuple[str, ...],
    value_field: str,
) -> tuple[DuplicateConflict, ...]:
    """只报告重复冲突；没有版本字段时禁止以 SUM、MAX 或任意行自行去重。"""
    grouped: dict[tuple[str, ...], list[Decimal]] = {}
    for row in rows:
        identity = tuple(str(row.get(field, "")) for field in identity_fields)
        grouped.setdefault(identity, []).append(Decimal(str(row[value_field])))
    return tuple(
        DuplicateConflict(identity=identity, values=tuple(values))
        for identity, values in sorted(grouped.items())
        if len(values) > 1 and len(set(values)) > 1
    )
