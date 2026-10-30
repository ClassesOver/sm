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
        (date(2025, 2, 28), date(2025, 2, 28), (date(2024, 2, 28), date(2024, 2, 28))),
        (date(2025, 1, 15), date(2025, 2, 28), (date(2024, 1, 15), date(2024, 2, 28))),
        (date(2024, 2, 29), date(2024, 2, 29), (date(2023, 2, 28), date(2023, 2, 28))),
    ],
)
def test_yoy_window_keeps_month_ends_aligned(
    start: date, end: date, expected: tuple[date, date]
) -> None:
    assert _yoy(start, end) == expected


def test_month_granularity_still_compares_complete_february():
    windows = build_period_windows(date(2025, 2, 28), date(2025, 2, 28), granularity="month")
    yoy = next(window for window in windows.windows if window.role == "yoy")
    assert (yoy.start, yoy.end) == (date(2024, 2, 1), date(2024, 2, 29))


@pytest.mark.parametrize("granularity", ["date", "month", "year"])
@pytest.mark.parametrize(
    ("data_type", "values"),
    [
        ("DATE", ["2024-12-31", "2025-01-01", "2025-02-15", "2025-02-28", "2025-03-01", "2026-01-01", None]),
        (
            "DATETIME",
            [
                "2024-12-31 23:59:59",
                "2025-01-01 00:00:00",
                "2025-02-28 23:59:59",
                "2025-03-01 00:00:00",
                "2025-12-31 12:00:00",
                "2026-01-01 00:00:00",
                None,
            ],
        ),
    ],
)
def test_temporal_period_filter_matches_normalized_text_filter(granularity, data_type, values) -> None:
    """日期列走可裁剪的范围谓词，命中集合必须与规范化文本谓词完全一致。"""
    import sqlite3

    from smart_reporting.reporting.data_source.period import period_filter_sql

    start, end = date(2025, 1, 10), date(2025, 2, 28)
    sargable = period_filter_sql("value", granularity, start, end, data_type=data_type)
    normalized = period_filter_sql("value", granularity, start, end)
    assert "SUBSTRING" not in sargable
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE sample (value TEXT)")
    connection.executemany("INSERT INTO sample VALUES (?)", [(value,) for value in values])

    def matched(predicate: str) -> list[str]:
        return [row[0] for row in connection.execute(f"SELECT value FROM sample WHERE {predicate}")]

    assert matched(sargable) == matched(normalized)
