"""B3 作图数据转换独立答案测试（chart_series.csv + chart_expected.json）。

答案 JSON 为手算常量；本测试逐值核对转换实现（分组排序、Top N/其他项、
缺值保持、单位换算、负数参与），答案不从被测实现反推（计划 B0-5）。
"""

from __future__ import annotations

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.lineage_fixtures import csv_path, expected
from smart_reporting.reporting.trace.chart_transform import transform_chart_series


def _rows():
    import csv

    with csv_path("chart_series.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _transform(**overrides):
    params = dict(
        category_field="branch",
        value_fields=("revenue", "expenses"),
        top_n=3,
        unit_scale=1.0,
        sort_field="revenue",
        sort_desc=True,
    )
    params.update(overrides)
    return transform_chart_series(_rows(), **params)


def test_category_order_and_topn_other_merge_match_manual_answer() -> None:
    manual = expected("chart_expected")
    result = _transform()
    assert result["categories"] == manual["category_order"]
    assert result["series"]["revenue"] == manual["revenue"]["yuan"]
    # 「其他」= E 300 + F 150 + D (-100) = 350（负数参与，不丢弃）。
    assert result["series"]["revenue"][3] == 350.0
    assert result["series"]["expenses"][3] == 270.0


def test_missing_value_kept_in_top_and_merged_in_other() -> None:
    manual = expected("chart_expected")
    result = _transform()
    # C 院区在 Top 内，expenses 缺值保持 None（不补 0）。
    assert result["series"]["expenses"][2] is None
    assert manual["expenses"]["missing_category"] == "C院区"


def test_unit_conversion_to_wan_matches_manual_answer() -> None:
    manual = expected("chart_expected")
    result = _transform(unit_scale=1 / 10000, unit_decimals=3)
    assert result["series"]["revenue"] == manual["revenue"]["wan"]
    assert result["series"]["expenses"] == manual["expenses"]["wan"]
    assert result["series"]["revenue"][3] == 0.035


def test_negative_values_sort_and_merge_like_manual_answer() -> None:
    manual = expected("chart_expected")
    result = _transform()
    # D 院区收入 -100 是最小值，必须落入「其他」而不是被丢弃。
    assert "D院区" not in result["categories"][:3]
    assert manual["revenue"]["other_sum_check"] == "300 + 150 + (-100) = 350"


def test_invalid_requests_are_rejected() -> None:
    with pytest.raises(ReportingError, match="至少需要一个数值列"):
        _transform(value_fields=())
    with pytest.raises(ReportingError, match="Top N"):
        _transform(top_n=0)
    with pytest.raises(ReportingError, match="缺少列"):
        _transform(category_field="no_such_column")


def test_chart_values_round_half_up_like_report_text() -> None:
    from smart_reporting.reporting.trace.chart_transform import transform_chart_series

    # 正文“2.68亿元”按十进制四舍五入；内置 round 的二进制/银行家舍入在图上标成 2.67。
    rows = [{"k": "a", "v": 267_500_000}, {"k": "b", "v": 0.1}, {"k": "c", "v": 0.2}]
    scaled = transform_chart_series(
        rows, category_field="k", value_fields=["v"], top_n=1, unit_scale=1e-8, unit_decimals=2
    )
    assert scaled["series"]["v"] == [2.68, 0.0]
    exact = transform_chart_series(rows, category_field="k", value_fields=["v"], top_n=1, unit_decimals=17)
    # 「其他」合计在十进制下求和，不带 0.30000000000000004 的二进制尾差。
    assert exact["series"]["v"][1] == 0.3
