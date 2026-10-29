import copy
import math
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.tests.test_standard_chart_presentation import (  # noqa: F401
    build,
    render,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    StandardChartAxes,
    StandardChartDerivation,
    StandardChartSource,
    StandardChartStep,
    StandardChartView,
)
from smart_reporting.reporting.workflow.runtime.standard_chart_transform import (
    apply_standard_chart_steps,
    transform_chart_document,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def table(rows):
    return {
        "columns": ["月份", "院区", "收入", "预算", "权重"],
        "rows": rows,
        "columnMeta": {"收入": {"unit": "元"}, "预算": {"unit": "元"}, "权重": {"unit": "人次"}},
    }


def derive(source, kind, **options):
    specification = StandardChartDerivation(
        kind=kind, name="计算值", numerator="收入", labelField="月份", groupBy=["院区"], **options
    )
    result = transform_chart_document(source, None, [specification])
    return {(row[0], row[1]): row[-1] for row in result["rows"]}


def test_multidimensional_groups_preserve_distinct_tuple_keys():
    source = table([["a | b", "c", 10, 20, 1], ["a", "b | c", 30, 40, 2], ["a | b", "c", 5, 7, 3]])
    result = transform_chart_document(
        source,
        StandardChartView(
            kind="group", labelField="月份", groupBy=["院区"], valueFields=["收入", "预算"]
        ),
        [],
    )
    assert result["columns"] == ["月份", "院区", "收入", "预算"]
    assert result["rows"] == [["a | b", "c", 15, 27], ["a", "b | c", 30, 40]]
    assert source["rows"][0] == ["a | b", "c", 10, 20, 1]


@pytest.mark.parametrize("weight_scale,value_scale", [(1, 1), (1e307, 1e300), (1e-300, 1e-200)])
def test_weighted_average_handles_extreme_weights_without_overflow(weight_scale, value_scale):
    source = table(
        [
            ["2026-01", "甲", 10 * value_scale, 0, 9 * weight_scale],
            ["2026-01", "甲", 100 * value_scale, 0, weight_scale],
            ["2026-01", "乙", 20 * value_scale, 0, 0],
        ]
    )
    result = transform_chart_document(
        source,
        StandardChartView(
            kind="group",
            labelField="月份",
            groupBy=["院区"],
            valueFields=["收入"],
            aggregation="weighted_mean",
            weightField="权重",
        ),
        [],
    )
    assert result["rows"][0][2] == pytest.approx(19 * value_scale, rel=1e-12, abs=0)
    assert result["rows"][1][2] is None
    assert result["columnMeta"]["收入"] == {"unit": "元"}


@pytest.mark.parametrize("weight", [-1, None, True, float("inf"), float("nan")])
def test_invalid_weights_do_not_become_zero(weight):
    with pytest.raises(ValueError):
        transform_chart_document(
            table([["2026-01", "甲", 10, 20, weight]]),
            StandardChartView(
                kind="group",
                labelField="院区",
                valueFields=["收入"],
                aggregation="weighted_mean",
                weightField="权重",
            ),
            [],
        )


def test_mean_does_not_overflow_intermediate_sum():
    result = transform_chart_document(
        table([["2026-01", "甲", 1e308, 0, 1], ["2026-01", "甲", 1e308, 0, 1]]),
        StandardChartView(
            kind="group", labelField="院区", valueFields=["收入"], aggregation="mean"
        ),
        [],
    )
    assert result["rows"] == [["甲", 1e308]]


def test_yoy_matches_calendar_month_and_group_in_sparse_shuffled_data():
    source = table(
        [
            ["2026-01", "甲", 30, 0, 1],
            ["2025-01", "乙", 200, 0, 1],
            ["2025-02", "甲", 999, 0, 1],
            ["2026-01", "乙", 300, 0, 1],
            ["2025-01", "甲", 10, 0, 1],
            ["2026-02", "丙", 30, 0, 1],
        ]
    )
    result = derive(source, "yoy_percent")
    assert result["2026-01", "甲"] == 200
    assert result["2026-01", "乙"] == 50
    assert result["2026-02", "丙"] is None
    assert result["2025-02", "甲"] is None


@pytest.mark.parametrize("baseline", [0, -10, None])
def test_yoy_nonpositive_or_missing_base_preserves_unknown(baseline):
    result = derive(
        table([["2025-01", "甲", baseline, 0, 1], ["2026-01", "甲", 10, 0, 1]]), "yoy_percent"
    )
    assert result["2026-01", "甲"] is None


def test_cumulative_missing_value_poison_and_explicit_year_reset():
    source = table(
        [
            ["2025-11", "甲", None, 0, 1],
            ["2025-12", "甲", 10, 0, 1],
            ["2026-01", "甲", 20, 0, 1],
            ["2026-02", "甲", 30, 0, 1],
        ]
    )
    assert list(derive(source, "cumulative_sum").values()) == [None, None, None, None]
    assert list(derive(source, "cumulative_sum", reset="year").values()) == [None, None, 20, 50]


@pytest.mark.parametrize("kind", ["mom_percent", "cumulative_sum", "rolling_sum", "rolling_mean"])
def test_operations_requiring_consecutive_months_reject_gaps(kind):
    with pytest.raises(ValueError, match="missing months"):
        derive(
            table([["2026-01", "甲", 10, 0, 1], ["2026-03", "甲", 20, 0, 1]]),
            kind,
            **({"window": 2} if kind.startswith("rolling") else {}),
        )


def test_rolling_default_full_window_and_explicit_valid_sample_minimum():
    source = table(
        [[f"2026-{i:02}", "甲", value, 0, 1] for i, value in enumerate([10, None, 30, 40, 50], 1)]
    )
    assert list(derive(source, "rolling_sum", window=3).values()) == [None, None, None, None, 120]
    assert list(derive(source, "rolling_mean", window=3).values()) == [None, None, None, None, 40]
    assert list(derive(source, "rolling_mean", window=3, minPeriods=2).values()) == [
        None,
        None,
        20,
        35,
        40,
    ]


def pipeline():
    return [
        StandardChartStep.model_validate(step)
        for step in [
            {
                "view": {
                    "kind": "group",
                    "labelField": "月份",
                    "groupBy": ["院区"],
                    "valueFields": ["收入", "预算"],
                }
            },
            {
                "derivation": {
                    "kind": "ratio_percent",
                    "name": "完成率",
                    "numerator": "收入",
                    "denominator": "预算",
                }
            },
            {
                "derivation": {
                    "kind": "rolling_mean",
                    "name": "平滑完成率",
                    "numerator": "完成率",
                    "labelField": "月份",
                    "groupBy": ["院区"],
                    "window": 2,
                }
            },
            {
                "view": {
                    "kind": "pivot",
                    "labelField": "月份",
                    "seriesField": "院区",
                    "seriesValues": ["东院", "西院"],
                    "valueFields": ["平滑完成率"],
                }
            },
        ]
    ]


@pytest.mark.parametrize("seed,scale", [(3, 1), (17, 1e-12), (51, 1e12)])
def test_shuffled_replacement_data_pipeline_matches_independent_oracle(seed, scale):
    rng = random.Random(seed)
    rows = [
        [f"2026-{month:02}", branch, rng.uniform(-10, 100) * scale, rng.uniform(50, 100) * scale, 1]
        for month in range(1, 5)
        for branch in ["东院", "西院"]
        for _ in range(3)
    ]
    rng.shuffle(rows)
    source = table(rows)
    original = copy.deepcopy(source)
    result = apply_standard_chart_steps(source, pipeline())
    for row in result["rows"]:
        month = int(row[0][-2:])
        for index, branch in enumerate(["东院", "西院"], 1):
            if month == 1:
                assert row[index] is None
                continue
            ratios = []
            for selected in [month - 1, month]:
                members = [r for r in rows if r[0] == f"2026-{selected:02}" and r[1] == branch]
                ratios.append(
                    math.fsum(r[2] for r in members) / math.fsum(r[3] for r in members) * 100
                )
            assert row[index] == pytest.approx(math.fsum(ratios) / 2, rel=1e-12)
    assert len(result["standardTransformations"]) == 4
    assert all(
        item["scope"] == "bound_input_rows_only" for item in result["standardTransformations"]
    )
    assert source == original


def test_pipeline_renders_nullable_percentage_series_and_rechecks_original_input(render):  # noqa: F811
    source = table(
        [
            [f"2026-{month:02}", branch, month * 10, 100, 1]
            for month in range(1, 4)
            for branch in ["东院", "西院"]
        ]
    )
    plan, inputs = build(source, form="line", selected=("东院", "西院"))
    chart = plan.charts[0]
    chart.standard_label_field = "月份"
    chart.standard_steps = pipeline()
    chart.standard_axes = StandardChartAxes(allowNulls=True)
    figure = render(plan, inputs)
    assert math.isnan(figure.axes[0].lines[0].get_ydata()[0])
    assert list(figure.axes[0].lines[0].get_ydata()[1:]) == [15, 25]
    assert figure.axes[0].get_ylabel() == "%"
    chart.standard_view = StandardChartView(kind="group", labelField="院区", valueFields=["收入"])
    result = standard_visualization_preflight(plan, inputs)
    assert (
        result.source is None and result.diagnostic["code"] == "standard_pipeline_order_ambiguous"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "rolling_mean"},
        {"kind": "rolling_sum", "window": 2, "minPeriods": 3},
        {"kind": "cumulative_sum", "window": 2},
        {"kind": "mom_percent", "reset": "year"},
        {"kind": "yoy_percent", "groupBy": ["院区", "院区"]},
        {"kind": "yoy_percent", "groupBy": ["月份"]},
    ],
)
def test_invalid_temporal_parameters_are_schema_rejected(payload):
    with pytest.raises(ValidationError):
        StandardChartDerivation.model_validate(
            {"name": "结果", "numerator": "收入", "labelField": "月份", **payload}
        )


@pytest.mark.parametrize(
    "step",
    [
        {},
        {
            "view": {"kind": "group", "labelField": "月份", "valueFields": ["收入"]},
            "derivation": {
                "kind": "difference",
                "name": "结果",
                "numerator": "收入",
                "denominator": "预算",
            },
        },
    ],
)
def test_pipeline_steps_require_exactly_one_operation(step):
    with pytest.raises(ValidationError):
        StandardChartStep.model_validate(step)


def test_pipeline_execution_capacity_is_enforced_even_without_chart_schema():
    with pytest.raises(ValueError, match="1..8"):
        apply_standard_chart_steps(table([]), pipeline() * 3)


def test_pipeline_cannot_reuse_dropped_frozen_field_names():
    steps = [
        StandardChartStep(
            view=StandardChartView(kind="group", labelField="院区", valueFields=["收入"])
        ),
        StandardChartStep(
            derivation=StandardChartDerivation(
                kind="difference", name="预算", numerator="收入", denominator="收入"
            )
        ),
    ]
    with pytest.raises(ValueError, match="cannot overwrite"):
        apply_standard_chart_steps(table([["2026-01", "甲", 10, 20, 1]]), steps)


def test_pipeline_failure_diagnostic_identifies_the_step():
    plan, inputs = build(table([["2026-01", "甲", 10, 20, 1]]), form="line", selected=("结果",))
    plan.charts[0].standard_steps = [
        StandardChartStep(
            view=StandardChartView(kind="group", labelField="院区", valueFields=["收入"])
        ),
        StandardChartStep(
            derivation=StandardChartDerivation(
                kind="difference", name="结果", numerator="收入", denominator="预算"
            )
        ),
    ]
    result = standard_visualization_preflight(plan, inputs)
    assert result.source is None
    assert result.diagnostic["code"] == "standard_transformation_failed"
    assert result.diagnostic["parameter"] == "standardSteps[1]"


def test_pipeline_retains_original_sha_check_at_execution(tmp_path, monkeypatch):
    source = table(
        [
            [f"2026-{month:02}", branch, 10 * month, 100, 1]
            for month in range(1, 4)
            for branch in ["东院", "西院"]
        ]
    )
    plan, inputs = build(source, form="line", selected=("东院", "西院"))
    plan.charts[0].standard_label_field = "月份"
    plan.charts[0].standard_steps = pipeline()
    plan.charts[0].standard_axes = StandardChartAxes(allowNulls=True)
    compiled = standard_visualization_preflight(plan, inputs)
    assert compiled.source is not None
    monkeypatch.chdir(tmp_path)
    Path("input.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="identity changed"):
        exec(compiled.source, {})


@pytest.mark.parametrize("aggregation", ["mean", "weighted_mean"])
@pytest.mark.parametrize("fraction", [False, True])
def test_percentage_averages_preserve_registered_scale(aggregation, fraction):
    factor = 0.01 if fraction else 1
    source = table([["2026-01", "甲", 10 * factor, 0, 1], ["2026-01", "甲", 30 * factor, 0, 3]])
    source["columnMeta"]["收入"] = {"unit": "%", "isPercent": not fraction}
    view = StandardChartView(
        kind="group",
        labelField="院区",
        valueFields=["收入"],
        aggregation=aggregation,
        **({"weightField": "权重"} if aggregation == "weighted_mean" else {}),
    )
    result = transform_chart_document(source, view, [])
    assert result["rows"][0][1] == pytest.approx(
        (25 if aggregation == "weighted_mean" else 20) * factor
    )
    assert result["columnMeta"]["收入"] == source["columnMeta"]["收入"]


@pytest.mark.parametrize(
    "kind,expected", [("ratio_percent", [None, None, None]), ("difference", [None, None, 20])]
)
def test_binary_derivation_preserves_missing_operands(kind, expected):
    source = table(
        [
            ["2026-01", "甲", None, 10, 1],
            ["2026-02", "甲", 20, None, 1],
            ["2026-03", "甲", 20, 0, 1],
        ]
    )
    result = transform_chart_document(
        source,
        None,
        [StandardChartDerivation(kind=kind, name="结果", numerator="收入", denominator="预算")],
    )
    assert [row[-1] for row in result["rows"]] == expected


@pytest.mark.parametrize("kind", ["yoy_percent", "cumulative_sum"])
def test_multiple_days_in_same_group_month_cannot_be_treated_as_monthly_data(kind):
    with pytest.raises(ValueError, match="Duplicate months"):
        derive(table([["2026-01-01", "甲", 10, 0, 1], ["2026-01-31", "甲", 20, 0, 1]]), kind)


def test_three_dimensional_group_preserves_all_dimension_columns():
    source = {
        "columns": ["月份", "院区", "科室", "收入"],
        "rows": [
            ["2026-01", "甲", "内科", 10],
            ["2026-01", "甲", "外科", 20],
            ["2026-01", "甲", "内科", 5],
        ],
        "columnMeta": {"收入": {"unit": "元"}},
    }
    result = transform_chart_document(
        source,
        StandardChartView(
            kind="group", labelField="月份", groupBy=["院区", "科室"], valueFields=["收入"]
        ),
        [],
    )
    assert result["columns"] == source["columns"]
    assert result["rows"] == [["2026-01", "甲", "内科", 15], ["2026-01", "甲", "外科", 20]]


def test_multi_source_yoy_keeps_history_before_selecting_display_window(render):  # noqa: F811
    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )

    source = {
        "columns": ["label", "actual"],
        "rows": [["2025-01", 10], ["2026-01", 20]],
        "columnMeta": {"actual": {"unit": "元"}},
    }
    plan, original = build(source, form="line", selected=("同比",))
    chart = plan.charts[0]
    chart.standard_labels = ("2026-01",)
    chart.standard_axes = StandardChartAxes(allowNulls=True)
    chart.standard_sources = (
        StandardChartSource(
            sourceIndex=0, labelField="label", valueField="actual", seriesName="收入"
        ),
        StandardChartSource(
            sourceIndex=1, labelField="label", valueField="actual", seriesName="预算"
        ),
    )
    chart.standard_steps = (
        StandardChartStep(
            derivation=StandardChartDerivation(
                kind="yoy_percent", name="同比", numerator="收入", labelField="period"
            )
        ),
    )
    extra = ChartInputFile("budget.json", original.files[0].content)
    inputs = ChartInputMaterialization(
        files=(*original.files, extra),
        entries=(
            *original.entries,
            {"chartId": "chart", "path": extra.path, "sha256": extra.sha256},
        ),
    )
    figure = render(plan, inputs)
    assert list(figure.axes[0].lines[0].get_ydata()) == [100]
    chart.standard_source_labels = ("2026-01",)
    rejected = standard_visualization_preflight(plan, inputs)
    assert rejected.source is None and rejected.diagnostic["code"] == "standard_series_empty"


@pytest.mark.parametrize("aggregation", ["mean", "weighted_mean"])
def test_average_preserves_smallest_representable_nonzero_value(aggregation):
    smallest = math.ulp(0.0)
    source = table([["2026-01", "甲", smallest, 0, 1], ["2026-01", "甲", smallest, 0, 1]])
    view = StandardChartView(
        kind="group",
        labelField="院区",
        valueFields=["收入"],
        aggregation=aggregation,
        **({"weightField": "权重"} if aggregation == "weighted_mean" else {}),
    )
    assert transform_chart_document(source, view, [])["rows"][0][1] == smallest


def test_tiny_weight_with_large_value_is_not_discarded_by_normalization():
    source = table([["2026-01", "甲", 1e308, 0, 1e-308], ["2026-01", "甲", 1e-308, 0, 1e308]])
    result = transform_chart_document(
        source,
        StandardChartView(
            kind="group",
            labelField="院区",
            valueFields=["收入"],
            aggregation="weighted_mean",
            weightField="权重",
        ),
        [],
    )
    assert result["rows"][0][1] == pytest.approx(2e-308, rel=1e-12, abs=0)


def test_rolling_mean_preserves_subnormal_input():
    smallest = math.ulp(0.0)
    result = derive(
        table([["2026-01", "甲", smallest, 0, 1], ["2026-02", "甲", smallest, 0, 1]]),
        "rolling_mean",
        window=2,
    )
    assert list(result.values()) == [None, smallest]
