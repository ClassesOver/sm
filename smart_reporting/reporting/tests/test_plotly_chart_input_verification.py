"""图表数值核对必须覆盖完整序列；核对失败仅告警。"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import plotly.graph_objects as go
import pytest
from loguru import logger

from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
    plotly_trace_matches_chart_inputs,
    verify_plotly_chart_inputs,
)


@pytest.mark.parametrize("values", [[], [1, 2], [2, 1], [1, 3], [1, 1, 2, 3], [2, 1, 3]])
def test_plotly_rejects_incomplete_reordered_or_duplicated_values(values):
    inputs = [{"columns": ["value"], "rows": [[1], [2], [3]]}]
    assert not plotly_trace_matches_chart_inputs({"data": [{"y": values}]}, inputs)


def test_correct_axis_or_trace_cannot_hide_incorrect_values():
    inputs = [{"columns": ["month", "amount"], "rows": [[1, 10], [2, 20], [3, 30]]}]
    figure = {"data": [{"x": [1, 2, 3], "y": [999, 998, 997]}]}
    assert not plotly_trace_matches_chart_inputs(figure, inputs)
    figure["data"].insert(0, {"y": [10, 20, 30]})
    assert not plotly_trace_matches_chart_inputs(figure, inputs)


@pytest.mark.parametrize("values", [[], [None, None, None], [10, "错误", 30], [10, float("inf"), 30]])
def test_correct_axis_cannot_hide_missing_or_invalid_values(values):
    inputs = [{"columns": ["month", "amount"], "rows": [[1, 10], [2, 20], [3, 30]]}]
    assert not plotly_trace_matches_chart_inputs({"data": [{"x": [1, 2, 3], "y": values}]}, inputs)


def test_plotly_accepts_category_labels_with_complete_values():
    inputs = [{"columns": ["label", "amount"], "rows": [["门诊", 10], ["住院", 20]]}]
    assert plotly_trace_matches_chart_inputs(
        {"data": [{"x": ["门诊", "住院"], "y": [10, 20]}]}, inputs,
    )


@pytest.mark.parametrize("values", [[1.23456, 2.34567], [1.23, 2.35], [123.456, 234.567], [0.0123456, 0.0234567]])
def test_plotly_preserves_rounding_and_percentage_scale_support(values):
    inputs = [{"columns": ["value"], "rows": [[1.23456], [2.34567]]}]
    assert plotly_trace_matches_chart_inputs({"data": [{"y": values}]}, inputs)


@pytest.mark.parametrize("typed", [False, True])
def test_plotly_preserves_missing_value_positions(typed):
    inputs = [{"columns": ["value"], "rows": [[1], [None], [3]]}]

    def figure(values):
        if typed:
            return json.loads(go.Figure(go.Bar(y=np.array(values, dtype=float))).to_json())
        return {"data": [{"y": values}]}

    assert plotly_trace_matches_chart_inputs(figure([1, None, 3]), inputs)
    assert not plotly_trace_matches_chart_inputs(figure([1, 3, None]), inputs)
    assert not plotly_trace_matches_chart_inputs(figure([1, 3]), inputs)


def test_plotly_without_numeric_evidence_is_not_verified():
    assert not plotly_trace_matches_chart_inputs(
        {"data": [{"y": [999]}]}, [{"columns": ["label"], "rows": [["收入"]]}],
    )


@pytest.mark.anyio
async def test_plotly_mismatch_emits_warning_and_continues():
    content = json.dumps({"chartId": "income", "columns": ["value"], "rows": [[1], [2], [3]]}).encode()
    materialized = ChartInputMaterialization(files=(ChartInputFile("inputs.json", content),))
    plan = SimpleNamespace(charts=[SimpleNamespace(chart_id="income", interactive_path="income.plotly.json")])
    workspace = SimpleNamespace(afile_bytes=AsyncMock(return_value=(b'{"data":[{"y":[1,2]}]}', "application/json")))
    messages = []
    sink = logger.add(lambda message: messages.append(str(message)))
    try:
        await verify_plotly_chart_inputs(plan, materialized, workspace, thread_id="thread")
    finally:
        logger.remove(sink)
    assert any("report_visualization_chart_data_unverified" in message for message in messages)
