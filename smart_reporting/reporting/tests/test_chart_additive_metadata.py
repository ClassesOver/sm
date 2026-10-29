"""图族可加性只取冻结计算口径，不能由单位或字段名称推断。"""

import pytest

from smart_reporting.reporting.workflow.runtime.chart_inputs import _table_for_binding
from smart_reporting.reporting.workflow.runtime.phase_models import ChartDataBinding

from .test_standard_supplemental_generic import compute


@pytest.mark.parametrize("aggregation,period_aggregation,cumulative,expected", [
    ("sum", "sum", None, {"aggregation": "sum", "additiveAcross": ["period"]}),
    ("count", "sum", None, {"aggregation": "count", "additiveAcross": ["period"]}),
    ("average", "sum", None, None),
    ("sum", "last", None, None),
    ("sum", None, None, None),
    ("sum", "sum", {"kind": "snapshot"}, None),
])
def test_period_projection_carries_only_frozen_time_additivity(
    aggregation, period_aggregation, cumulative, expected,
):
    binding = ChartDataBinding(analysisId="analysis", factPath="facts.json",
        dataPath="metrics[0].periodValues", fields=["period", "value"], role="时间序列")
    metric = {"unit": "元", "aggregation": aggregation,
        "periodAggregation": period_aggregation, "cumulativePolicy": cumulative,
        "periodValues": [{"period": "2025-01", "value": 42}]}
    _, rows, metadata = _table_for_binding({"metrics": [metric]}, binding)
    assert rows == [["2025-01", 42]]
    assert metadata["value"].get("measureSemantic") == expected


@pytest.mark.parametrize("dimension,expected_column", [("group", "group"), ("value", "dimension_value")])
def test_standard_sum_freezes_output_dimension_not_generic_alias(dimension, expected_column):
    payload, _ = compute(f"period,{dimension},amount\n2025-01,A,10\n2025-01,B,30\n",
        operation="group_summary", dimension=dimension, currentPeriods=("2025-01",),
        parentTotal=40, measureUnit="元")
    metadata = payload["findings"][0]["columnMeta"]
    assert metadata["value"]["measureSemantic"] == {
        "aggregation": "sum", "additiveAcross": [expected_column],
    }
    assert "measureSemantic" not in metadata["share"]
    assert "measureSemantic" not in metadata["rank"]


def test_cross_summary_freezes_both_dimensions_but_not_repeated_marginal_totals():
    payload, _ = compute("period,group,type,amount\n2025-01,A,X,10\n2025-01,B,Y,30\n",
        operation="cross_group_summary", secondaryDimensionField="type",
        currentPeriods=("2025-01",), parentTotal=40, measureUnit="元", includeMarginalShares=True)
    metadata = payload["findings"][0]["columnMeta"]
    assert metadata["value"]["measureSemantic"]["additiveAcross"] == ["group", "type"]
    for field in ("primaryTotal", "secondaryTotal", "primaryShare", "secondaryShare"):
        assert "measureSemantic" not in metadata[field]


@pytest.mark.parametrize("collection", ["metrics", "breakdowns"])
def test_frozen_metric_scalar_preserves_units_for_denominator_and_radar_endpoints(collection):
    binding = ChartDataBinding(analysisId="analysis", factPath="facts.json",
        dataPath=f"{collection}[0]", fields=["total", "minimum", "maximum", "missingCount"], role="冻结端点")
    metric = {"unit": "元", "total": 50, "minimum": -10, "maximum": 100, "missingCount": 2}
    columns, rows, metadata = _table_for_binding({collection: [metric]}, binding)
    assert columns == ["total", "minimum", "maximum", "missingCount"]
    assert rows == [[50, -10, 100, 2]]
    assert metadata == {name: {"unit": "元"} for name in ("total", "minimum", "maximum")}
