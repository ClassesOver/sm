from __future__ import annotations

from datetime import date

import pytest

from smart_reporting.reporting.data_source.period import build_period_windows


def _yoy(start: date, end: date) -> tuple[date, date]:
    window = next(item for item in build_period_windows(start, end).windows if item.role == "yoy")
    return window.start, window.end


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        # 平年完整二月的同比必须包含闰年的 2 月 29 日。
        (date(2025, 2, 1), date(2025, 2, 28), (date(2024, 2, 1), date(2024, 2, 29))),
        (date(2025, 1, 1), date(2025, 2, 28), (date(2024, 1, 1), date(2024, 2, 29))),
        # 闰年完整二月映射到平年二月末。
        (date(2024, 2, 1), date(2024, 2, 29), (date(2023, 2, 1), date(2023, 2, 28))),
        (date(2025, 3, 1), date(2025, 3, 31), (date(2024, 3, 1), date(2024, 3, 31))),
        # 非月末的任意日期区间保持月日不变。
        (date(2025, 2, 10), date(2025, 2, 20), (date(2024, 2, 10), date(2024, 2, 20))),
    ],
)
def test_yoy_window_keeps_month_ends_aligned(
    start: date, end: date, expected: tuple[date, date]
) -> None:
    assert _yoy(start, end) == expected
