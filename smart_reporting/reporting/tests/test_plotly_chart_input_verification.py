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


@pytest.mark.parametrize(
    "values", [[], [None, None, None], [10, "错误", 30], [10, float("inf"), 30]]
)
def test_correct_axis_cannot_hide_missing_or_invalid_values(values):
    inputs = [{"columns": ["month", "amount"], "rows": [[1, 10], [2, 20], [3, 30]]}]
    assert not plotly_trace_matches_chart_inputs({"data": [{"x": [1, 2, 3], "y": values}]}, inputs)


def test_plotly_accepts_category_labels_with_complete_values():
    inputs = [{"columns": ["label", "amount"], "rows": [["门诊", 10], ["住院", 20]]}]
    assert plotly_trace_matches_chart_inputs(
        {"data": [{"x": ["门诊", "住院"], "y": [10, 20]}]},
        inputs,
    )


@pytest.mark.parametrize("values", [[1.23456, 2.34567], [1.23, 2.35]])
def test_plotly_preserves_exact_and_decimal_rounded_values(values):
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
        {"data": [{"y": [999]}]},
        [{"columns": ["label"], "rows": [["收入"]]}],
    )


@pytest.mark.anyio
async def test_plotly_mismatch_emits_warning_and_continues():
    content = json.dumps(
        {"chartId": "income", "columns": ["value"], "rows": [[1], [2], [3]]}
    ).encode()
    materialized = ChartInputMaterialization(files=(ChartInputFile("inputs.json", content),))
    plan = SimpleNamespace(
        charts=[SimpleNamespace(chart_id="income", interactive_path="income.plotly.json")]
    )
    workspace = SimpleNamespace(
        afile_bytes=AsyncMock(return_value=(b'{"data":[{"y":[1,2]}]}', "application/json"))
    )
    messages = []
    sink = logger.add(lambda message: messages.append(str(message)))
    try:
        await verify_plotly_chart_inputs(plan, materialized, workspace, thread_id="thread")
    finally:
        logger.remove(sink)
    assert any("report_visualization_chart_data_unverified" in message for message in messages)


@pytest.mark.parametrize(
    "trace",
    [
        {"x": ["住院", "门诊"], "y": [10, 20]},
        {"orientation": "h", "y": ["住院", "门诊"], "x": [10, 20]},
        {"labels": ["住院", "门诊"], "values": [10, 20]},
        {"theta": ["住院", "门诊"], "r": [10, 20]},
        {"y": [10, 20]},
    ],
)
def test_correct_numbers_do_not_authorize_swapped_or_missing_categories(trace):
    inputs = [{"columns": ["label", "amount"], "rows": [["门诊", 10], ["住院", 20]]}]
    assert not plotly_trace_matches_chart_inputs({"data": [trace]}, inputs)


@pytest.mark.parametrize(
    "trace",
    [
        {"orientation": "h", "y": ["门诊", "住院"], "x": [10, 20]},
        {"labels": ["门诊", "住院"], "values": [10, 20]},
        {"theta": ["门诊", "住院"], "r": [10, 20]},
    ],
)
def test_horizontal_pie_and_polar_pairs_preserve_registered_row_identity(trace):
    assert plotly_trace_matches_chart_inputs(
        {"data": [trace]},
        [
            {"columns": ["label", "amount"], "rows": [["门诊", 10], ["住院", 20]]},
        ],
    )


def test_labels_and_values_cannot_be_borrowed_from_different_tables():
    inputs = [
        {"columns": ["label", "amount"], "rows": [["门诊", 10], ["住院", 20]]},
        {"columns": ["label", "amount"], "rows": [["急诊", 30], ["体检", 40]]},
    ]
    assert not plotly_trace_matches_chart_inputs(
        {"data": [{"x": ["门诊", "住院"], "y": [30, 40]}]}, inputs
    )


def test_numeric_period_axis_cannot_masquerade_as_the_value_axis():
    inputs = [{"columns": ["month", "amount"], "rows": [[1, 10], [2, 20], [3, 30]]}]
    assert not plotly_trace_matches_chart_inputs(
        {"data": [{"x": [1, 2, 3], "y": [1, 2, 3]}]}, inputs
    )
    assert plotly_trace_matches_chart_inputs(
        {"data": [{"x": [1, 2, 3], "y": [10, 20, 30]}]}, inputs
    )


@pytest.mark.parametrize("values", [[123.456, 234.567], [0.0123456, 0.0234567]])
def test_unitless_values_cannot_borrow_an_arbitrary_percentage_scale(values):
    assert not plotly_trace_matches_chart_inputs(
        {"data": [{"y": values}]},
        [
            {"columns": ["amount"], "rows": [[1.23456], [2.34567]]},
        ],
    )


@pytest.mark.parametrize(
    "unit,axis,values",
    [
        ("元", {"title": {"text": "收入（万元）"}}, [1, 2]),
        ("%", {"tickformat": ".0%"}, [0.1, 0.2]),
        ("1", {"title": {"text": "占比（%）"}}, [1000000, 2000000]),
    ],
)
def test_explicit_source_and_axis_units_allow_registered_conversions(unit, axis, values):
    assert plotly_trace_matches_chart_inputs(
        {"data": [{"y": values}], "layout": {"yaxis": axis}},
        [
            {
                "columns": ["value"],
                "rows": [[10000], [20000]],
                "columnMeta": {"value": {"unit": unit}},
            }
            if unit != "%"
            else {
                "columns": ["value"],
                "rows": [[10], [20]],
                "columnMeta": {"value": {"unit": "%"}},
            },
        ],
    )


@pytest.mark.parametrize("metadata", [{}, {"value": {"unit": "元"}}])
def test_percent_axis_cannot_relabel_unknown_or_money_values(metadata):
    assert not plotly_trace_matches_chart_inputs(
        {"data": [{"y": [10, 20]}], "layout": {"yaxis": {"tickformat": ".0%"}}},
        [
            {"columns": ["value"], "rows": [[10], [20]], "columnMeta": metadata},
        ],
    )


def test_large_values_do_not_get_a_relative_error_allowance():
    assert not plotly_trace_matches_chart_inputs(
        {"data": [{"y": [100500, 200500]}]},
        [
            {"columns": ["value"], "rows": [[100000], [200000]]},
        ],
    )


@pytest.mark.parametrize("trace", [{"y": [[1, 2], [3]]}, {"z": [[1, 2, 3]]}])
def test_flattening_does_not_prove_unregistered_grid_or_point_shapes(trace):
    assert not plotly_trace_matches_chart_inputs(
        {"data": [trace]}, [{"columns": ["value"], "rows": [[1], [2], [3]]}]
    )


@pytest.mark.anyio
@pytest.mark.parametrize("content", [b"not-json", b"[]", b'{"data":[{"y":[3,2,1]}]}'])
async def test_unreadable_or_invalid_chart_returns_unknown_without_raising(content):
    materialized = ChartInputMaterialization(
        files=(
            ChartInputFile(
                "inputs.json", b'{"chartId":"income","columns":["value"],"rows":[[1],[2],[3]]}'
            ),
        )
    )
    plan = SimpleNamespace(
        charts=[SimpleNamespace(chart_id="income", interactive_path="income.json")]
    )
    workspace = SimpleNamespace(afile_bytes=AsyncMock(return_value=(content, "application/json")))
    result = await verify_plotly_chart_inputs(plan, materialized, workspace, thread_id="thread")
    assert result["income"]["status"] == "unknown"


def test_finite_period_axis_does_not_verify_an_entirely_missing_measure():
    assert not plotly_trace_matches_chart_inputs(
        {"data": [{"x": [1, 2], "y": [None, None]}]},
        [
            {"columns": ["month", "amount"], "rows": [[1, None], [2, None]]},
        ],
    )


def test_declared_axis_unit_requires_a_known_source_unit():
    assert not plotly_trace_matches_chart_inputs(
        {"data": [{"y": [10, 20]}], "layout": {"yaxis": {"title": "收入（万元）"}}},
        [
            {"columns": ["amount"], "rows": [[10], [20]]},
        ],
    )


def test_conversion_uses_the_trace_axis_instead_of_another_subplots_axis():
    inputs = [
        {
            "columns": ["amount"],
            "rows": [[10000], [20000]],
            "columnMeta": {"amount": {"unit": "元"}},
        }
    ]
    figure = {
        "data": [{"y": [1, 2], "yaxis": "y2"}],
        "layout": {"yaxis": {"title": "金额（元）"}, "yaxis2": {"title": "金额（万元）"}},
    }
    assert plotly_trace_matches_chart_inputs(figure, inputs)
    figure["data"][0]["yaxis"] = "y"
    assert not plotly_trace_matches_chart_inputs(figure, inputs)


def test_typed_array_shape_cannot_be_flattened_to_reassign_point_identity():
    figure = json.loads(go.Figure(go.Bar(y=np.array([1, 2, 3], dtype=float))).to_json())
    figure["data"][0]["y"]["shape"] = "1, 3"
    assert not plotly_trace_matches_chart_inputs(
        figure, [{"columns": ["value"], "rows": [[1], [2], [3]]}]
    )


@pytest.mark.anyio
async def test_bad_chart_isolated_and_good_chart_returns_only_array_verification():
    def content(chart_id):
        return json.dumps(
            {"chartId": chart_id, "columns": ["value"], "rows": [[1], [2], [3]]}
        ).encode()

    materialized = ChartInputMaterialization(
        files=tuple(ChartInputFile(name + ".json", content(name)) for name in ("bad", "good"))
    )
    plan = SimpleNamespace(
        charts=[
            SimpleNamespace(chart_id=name, interactive_path=name + ".json")
            for name in ("bad", "good")
        ]
    )
    workspace = SimpleNamespace(
        afile_bytes=AsyncMock(
            side_effect=[OSError("missing"), (b'{"data":[{"y":[1,2,3]}]}', "application/json")]
        )
    )
    result = await verify_plotly_chart_inputs(plan, materialized, workspace, thread_id="thread")
    assert result["bad"]["status"] == "unknown"
    assert result["good"] == {"status": "verified", "reason": "registered_arrays_match"}


@pytest.mark.anyio
async def test_absent_input_or_static_image_is_never_reported_as_verified():
    plan = SimpleNamespace(
        charts=[
            SimpleNamespace(chart_id="static", interactive_path=None),
            SimpleNamespace(chart_id="missing", interactive_path="missing.json"),
        ]
    )
    workspace = SimpleNamespace(afile_bytes=AsyncMock())
    result = await verify_plotly_chart_inputs(
        plan, ChartInputMaterialization(), workspace, thread_id="thread"
    )
    assert result == {
        "static": {"status": "unknown", "reason": "static_image_not_evaluated"},
        "missing": {"status": "unknown", "reason": "chart_input_unavailable"},
    }
    workspace.afile_bytes.assert_not_called()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_source_is_not_treated_as_an_explicit_missing_value(bad):
    assert not plotly_trace_matches_chart_inputs(
        {"data": [{"y": [1, None, 3]}]},
        [
            {"columns": ["value"], "rows": [[1], [bad], [3]]},
        ],
    )


def test_unrepresentable_integer_is_unknown_without_crashing_the_checker():
    assert not plotly_trace_matches_chart_inputs(
        {"data": [{"y": [10**1000]}]},
        [
            {"columns": ["value"], "rows": [[1]]},
        ],
    )


def test_ranked_subset_cannot_be_verified_as_a_full_distribution_pie():
    inputs = [
        {
            "columns": ["label", "amount"],
            "rows": [["门诊", 10], ["住院", 20]],
            "dataScope": {"coverage": "ranked_subset", "canRepresentFullDistribution": False},
        }
    ]
    assert not plotly_trace_matches_chart_inputs(
        {"data": [{"type": "pie", "labels": ["门诊", "住院"], "values": [10, 20]}]}, inputs
    )
    assert plotly_trace_matches_chart_inputs(
        {"data": [{"type": "bar", "x": ["门诊", "住院"], "y": [10, 20]}]}, inputs
    )


@pytest.mark.parametrize(
    "figure",
    [
        {"data": [{"type": "histogram", "x": [10, 20]}]},
        {"data": [{"type": "bar", "y": [10, 20]}], "layout": {"barnorm": "percent"}},
        {"data": [{"type": "scatter", "y": [10, 20], "groupnorm": "fraction"}]},
    ],
)
def test_renderer_normalization_and_binning_need_their_own_registered_transform(figure):
    assert not plotly_trace_matches_chart_inputs(
        figure, [{"columns": ["value"], "rows": [[10], [20]]}]
    )
