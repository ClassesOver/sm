from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

from .models import AnalysisMethodDecision, ReportingError


def comparison_decisions(
    months: Sequence[date], *, report_year: int
) -> tuple[AnalysisMethodDecision, AnalysisMethodDecision]:
    distinct = sorted({(value.year, value.month) for value in months})
    current = [(year, month) for year, month in distinct if year == report_year]
    previous = {(year, month) for year, month in distinct if year == report_year - 1}
    comparable = bool(current) and all((report_year - 1, month) in previous for _, month in current)
    yoy = AnalysisMethodDecision(
        method="year_over_year",
        decision="execute" if comparable else "not_applicable",
        rationale=(
            f"{report_year - 1} 年包含全部可比月份。"
            if comparable
            else f"{report_year - 1} 年缺少可比期间数据。"
        ),
    )
    continuous = len(current) >= 2 and all(
        (right_year * 12 + right_month) - (left_year * 12 + left_month) == 1
        for (left_year, left_month), (right_year, right_month) in zip(current, current[1:])
    )
    mom = AnalysisMethodDecision(
        method="month_over_month",
        decision="execute" if continuous else "not_applicable",
        rationale="月份连续，可与上一连续月份比较。" if continuous else "月份不连续。",
    )
    return yoy, mom


def validate_metric_aggregation(*, cumulative: bool, aggregation: str) -> None:
    if cumulative and aggregation.lower() == "sum":
        raise ReportingError("cumulative_sum_denied", "累计指标不能跨期间直接求和。")


def validate_fact_combination(grains: Mapping[str, Sequence[str]]) -> None:
    normalized = {name: tuple(columns) for name, columns in grains.items()}
    if len(set(normalized.values())) > 1:
        raise ReportingError(
            "fact_grain_mismatch", "不同粒度事实表必须先分别聚合，不能直接明细连接。"
        )


def reconcile_metric(parts: Sequence[Decimal], total: Decimal, *, tolerance: Decimal) -> None:
    if not parts:
        raise ReportingError("metric_empty", "指标数据为空。")
    if abs(sum(parts, Decimal(0)) - total) > tolerance:
        raise ReportingError("metric_reconciliation_failed", "指标分项与总计无法对账。")
