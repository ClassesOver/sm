"""B0 fixtures 自洽性：手算答案与标准库独立重算互证（计划第 9 节）。

答案 JSON 是手算常量；本测试用与被测实现（polars 管线）不同的
csv 标准库 + 纯 Python 路径重算，保证 fixtures 自身正确，防止
后续批次"用被测实现反向生成预期值"。
"""

from __future__ import annotations

import pytest

from smart_reporting.reporting.tests.lineage_fixtures import (
    csv_path,
    expected,
    recompute_boundaries,
    recompute_chart_topn,
    recompute_contribution,
    recompute_edge,
    recompute_r1,
    recompute_r2,
    wide_csv_bytes,
)


def test_r1_manual_answer_matches_independent_recompute() -> None:
    manual = expected("r1_expected")
    recomputed = recompute_r1()
    assert recomputed["revenue_total"] == manual["revenue_total"] == 3600.0
    assert recomputed["visits_total"] == manual["visits_total"] == 30
    assert recomputed["revenue_per_visit"] == pytest.approx(120.0)
    assert recomputed["mom_change"] == 600.0
    assert recomputed["mom_rate_pct"] == pytest.approx(20.0)
    # 参与行清单与 CSV 内容一致（本期/基期各 2 行）。
    assert len(manual["input_rows"]["current"]) == 2
    assert len(manual["input_rows"]["baseline"]) == 2


def test_r2_scope_applies_to_both_periods() -> None:
    manual = expected("r2_expected")
    recomputed = recompute_r2()
    assert recomputed["revenue_total"] == 1200.0
    assert recomputed["baseline_revenue_total"] == 1000.0
    assert recomputed["revenue_per_visit"] == pytest.approx(120.0)
    assert recomputed["baseline_revenue_per_visit"] == pytest.approx(100.0)
    assert recomputed["mom_rate_pct"] == pytest.approx(20.0)
    assert manual["scope"] == {"branch": "A院区"}
    # 排除行不得进入任何一侧输入。
    assert {row[1] for row in manual["input_rows"]["excluded"]} == {"B院区"}


def test_r3_stale_rules_reference_frozen_fact() -> None:
    manual = expected("r3_stale_expected")
    assert manual["base_scenario"] == "R1"
    assert manual["edited_claim_value"] == 3800.0
    assert manual["frozen_fact_value"] == expected("r1_expected")["revenue_total"]
    assert manual["expected_binding_status"] == "stale"


def test_contribution_chain_matches_manual() -> None:
    manual = expected("contribution_expected")
    recomputed = recompute_contribution()
    assert recomputed["total"]["delta"] == manual["total"]["delta"] == 600.0
    for branch, values in manual["branch_deltas"].items():
        assert recomputed["branch_deltas"][branch]["delta"] == values["delta"]
        assert recomputed["branch_deltas"][branch]["share_pct"] == values["share_pct"]
    shares = [v["share_pct"] for v in manual["branch_deltas"].values()]
    assert sum(shares) == pytest.approx(100.00)


def test_chart_topn_order_missing_negative_and_unit_conversion() -> None:
    manual = expected("chart_expected")
    recomputed = recompute_chart_topn()
    assert recomputed["category_order"] == manual["category_order"]
    assert recomputed["revenue"]["yuan"] == manual["revenue"]["yuan"]
    assert recomputed["revenue"]["wan"] == manual["revenue"]["wan"]
    assert recomputed["expenses"]["yuan"][3] == manual["expenses"]["yuan"][3] == 270.0
    assert recomputed["expenses"]["yuan"][2] is None
    assert recomputed["expenses"]["missing_category"] == "C院区"
    # 负数进入「其他」而不是被丢弃。
    assert "D院区 -100" in manual["revenue"]["other_members"]
    assert manual["revenue"]["yuan"][3] == 350.0


def test_edge_zero_denominator_and_missing_baseline() -> None:
    manual = expected("edge_expected")
    recomputed = recompute_edge()
    assert recomputed["branch_d"]["mom_change"] == 100.0
    assert recomputed["branch_d"]["mom_rate_pct"] is None
    assert recomputed["branch_d"]["mom_rate_reason"] == "zero_denominator"
    assert recomputed["branch_e"]["mom_reason"] == "missing_baseline"
    assert recomputed["branch_e"]["current_revenue"] == 0.0
    assert recomputed["branch_e"]["current_revenue_missing_count"] == 1


def test_boundaries_quoting_newline_empty_and_escape() -> None:
    manual = expected("boundaries_expected")
    recomputed = recompute_boundaries()
    assert recomputed["record_count"] == manual["record_count"] == 5
    names = recomputed["names"]
    assert names[0] == "张三"
    assert names[1] == "李\n四"  # 引号内换行是一条记录
    assert names[2] == ""  # 空名称是空字段而非缺失记录
    assert names[4] == '引号"嵌套"'
    assert names[3] == "长" * 128  # 128 字符长字段
    assert recomputed["name_lengths"][3] == 128
    assert recomputed["amounts"] == [100, 200, 300, 400, 500]


def test_wide_csv_exceeds_preview_column_budget() -> None:
    from smart_reporting.reporting.trace import TRACE_BUDGETS_V1

    data = wide_csv_bytes(rows=3, columns=60)
    header = data.decode("utf-8").splitlines()[0].split(",")
    assert len(header) == 61
    assert len(header) - 1 > TRACE_BUDGETS_V1["preview_max_columns"]


def test_fixture_csv_files_exist() -> None:
    for name in (
        "hospital_revenue.csv",
        "chart_series.csv",
        "edge_cases.csv",
        "boundaries.csv",
    ):
        assert csv_path(name).is_file(), name
