from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from dateutil.relativedelta import relativedelta

PeriodGranularity = Literal["date", "month", "year"]
PeriodRole = Literal["current", "yoy", "mom"]
ComparisonRole = Literal["yoy", "mom"]


@dataclass(frozen=True)
class PeriodWindow:
    """一个查询期间及其业务角色；角色不能由展示章节反推。"""

    role: PeriodRole
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("期间窗口开始日期不能晚于结束日期")

    def public_dict(self) -> dict[str, str]:
        return {"role": self.role, "start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True)
class PeriodWindowSet:
    """当前、同比和环比窗口；同一角色最多一个窗口。"""

    windows: tuple[PeriodWindow, ...]

    def __post_init__(self) -> None:
        roles = tuple(item.role for item in self.windows)
        if len(roles) != len(set(roles)):
            raise ValueError("期间角色不能重复")
        if "current" not in roles:
            raise ValueError("期间窗口必须包含 current 角色")

    def public_dict(self) -> list[dict[str, str]]:
        return [item.public_dict() for item in self.windows]


def _same_month_day_previous_year(value: date) -> date:
    """同比保持月日；闰日不存在时使用当年二月最后一天。"""
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        # 只有 2 月 29 日在非闰年会进入这里。
        return value.replace(year=value.year - 1, month=2, day=28)


def build_period_windows(
    period_start: date,
    period_end: date,
    *,
    include_yoy: bool = True,
    include_mom: bool = False,
    granularity: PeriodGranularity = "date",
) -> PeriodWindowSet:
    """生成比较窗口，所有边界均为按物理期间粒度规范化后的闭区间。"""
    if period_start > period_end:
        raise ValueError("分析期间无效")
    period_start, period_end = normalize_period_bounds(period_start, period_end, granularity)
    windows = [PeriodWindow("current", period_start, period_end)]
    if include_yoy:
        windows.append(
            PeriodWindow(
                "yoy",
                _same_month_day_previous_year(period_start),
                _same_month_day_previous_year(period_end),
            )
        )
    if include_mom:
        if granularity == "year":
            raise ValueError("year 粒度不支持 mom")
        if _is_complete_calendar_month(period_start, period_end):
            previous_start = period_start - relativedelta(months=1)
            previous_end = previous_start + relativedelta(months=1, days=-1)
            windows.append(PeriodWindow("mom", previous_start, previous_end))
        elif not _is_complete_month_sequence(period_start, period_end):
            raise ValueError("mom 只支持单一完整日历月")
        # 多个完整月份的环比由 current 月序列相邻计算，不签发额外历史查询窗口。
    return PeriodWindowSet(tuple(windows))


def normalize_period_bounds(
    period_start: date,
    period_end: date,
    granularity: PeriodGranularity,
) -> tuple[date, date]:
    """把业务期间规范为物理谓词真正使用的边界。"""
    if period_start > period_end:
        raise ValueError("分析期间无效")
    if granularity == "date":
        return period_start, period_end
    if granularity == "month":
        start = period_start.replace(day=1)
        end = period_end.replace(day=1) + relativedelta(months=1, days=-1)
        return start, end
    return date(period_start.year, 1, 1), date(period_end.year, 12, 31)


def _is_complete_calendar_month(period_start: date, period_end: date) -> bool:
    return period_start.day == 1 and period_end == period_start + relativedelta(months=1, days=-1)


def _is_complete_month_sequence(period_start: date, period_end: date) -> bool:
    return period_start.day == 1 and period_end == period_end.replace(day=1) + relativedelta(
        months=1, days=-1
    )


def normalized_period_sql(identifier: str, granularity: PeriodGranularity) -> str:
    width = {"date": 8, "month": 6, "year": 4}[granularity]
    compact = f"REPLACE(REPLACE(CAST({identifier} AS CHAR), '/', ''), '-', '')"
    return f"SUBSTRING({compact}, 1, {width})"


def period_filter_sql(
    identifier: str,
    granularity: PeriodGranularity,
    period_start: date,
    period_end: date,
) -> str:
    normalized = normalized_period_sql(identifier, granularity)
    if granularity == "year":
        start, end = f"{period_start:%Y}", f"{period_end:%Y}"
    elif granularity == "month":
        start, end = f"{period_start:%Y%m}", f"{period_end:%Y%m}"
    else:
        start, end = f"{period_start:%Y%m%d}", f"{period_end:%Y%m%d}"
    return f"{normalized} >= '{start}' AND {normalized} <= '{end}'"


__all__ = [
    "PeriodGranularity",
    "ComparisonRole",
    "PeriodRole",
    "PeriodWindow",
    "PeriodWindowSet",
    "build_period_windows",
    "normalize_period_bounds",
    "normalized_period_sql",
    "period_filter_sql",
]
