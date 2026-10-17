import pytest

from smart_reporting.reporting.workflow.runtime.analysis_coverage import one_sided_gap_warnings


@pytest.mark.parametrize(
    ("period", "warning", "expected_count"),
    [
        ("2025-01-01", "2025-01无授权上月数据，环比为null。", 0),
        ("2025-01-01", "2025-01-01无授权上月数据，环比为null。", 0),
        ("2025-01-01", "2025-02无授权上月数据，环比为null。", 1),
        ("2025-01-01", "2025-01-02无比较基准。", 1),
        ("2025-01-02", "2025-01无授权上月数据，环比为null。", 1),
        ("2025-01-01", "2024-01无授权上月数据，环比为null。", 1),
    ],
)
def test_monthly_gap_disclosure_matches_month_without_hiding_other_dates(
    period, warning, expected_count
):
    finding = {
        "name": "全院月度成本及环比对账",
        "columns": ["period", "current_numerator", "prior_denominator"],
        "rows": [[period, 100, None]],
    }

    assert len(one_sided_gap_warnings([finding], [warning])) == expected_count


@pytest.mark.parametrize("direction", ["currentOnly", "priorOnly"])
@pytest.mark.parametrize("disclose_all", [False, True])
def test_partial_disclosure_keeps_only_undisclosed_gaps(direction, disclose_all):
    values = [100, None] if direction == "currentOnly" else [None, 100]
    finding = {
        "name": "科室收入",
        "columns": ["科室", "current_income", "prior_income"],
        "rows": [["内科", *values], ["外科", *values]],
    }
    warning = "内科、外科缺少比较数据" if disclose_all else "内科缺少比较数据"
    result = one_sided_gap_warnings([finding], [warning])
    if disclose_all:
        assert result == []
    else:
        assert len(result) == 1
        assert result[0]["direction"] == direction
        assert result[0]["count"] == 1
        assert result[0]["samples"] == ["外科"]
