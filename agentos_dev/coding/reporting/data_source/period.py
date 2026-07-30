from __future__ import annotations

from datetime import date
from typing import Literal

PeriodGranularity = Literal["date", "month", "year"]


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
