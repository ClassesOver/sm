import json
import math
import random

import pytest

from smart_reporting.reporting.tests.test_standard_chart_presentation import (  # noqa: F401
    build,
    render,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    StandardChartAnnotation,
    StandardChartAxes,
    StandardChartDerivation,
    StandardChartOrder,
    StandardChartSource,
    StandardChartView,
)
from smart_reporting.reporting.workflow.runtime.standard_chart_alignment import align_chart_sources
from smart_reporting.reporting.workflow.runtime.standard_chart_presentation import (
    order_standard_rows,
)
from smart_reporting.reporting.workflow.runtime.standard_chart_transform import (
    transform_chart_document,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_script,
)


def document(rows=None):
    return {
        "columns": ["科室", "预算", "合同", "备注"],
        "rows": rows
        or [["甲", 100, 20, "项目1"], ["甲", 50, 40, "项目2"], ["乙", 200, 80, "项目3"]],
        "columnMeta": {"预算": {"unit": "元"}, "合同": {"unit": "元"}},
    }


def test_group_ratio_uses_summed_operands_and_preserves_original():
    source = document()
    view = StandardChartView(kind="group", labelField="科室", valueFields=["预算", "合同"])
    ratio = StandardChartDerivation(
        kind="ratio_percent", name="签约率", numerator="合同", denominator="预算"
    )
    result = transform_chart_document(source, view, [ratio])
    assert result["rows"] == [["甲", 150, 60, 40], ["乙", 200, 80, 40]]
    assert result["columnMeta"]["签约率"] == {"unit": "%", "isPercent": True}
    assert result["standardTransformations"][0]["scope"] == "bound_input_rows_only"
    assert source == document()


@pytest.mark.parametrize("bad", [None, True, float("inf"), float("nan")])
def test_group_rejects_unknown_or_nonfinite_operands(bad):
    source = document([["甲", bad, 20, "项目1"]])
    with pytest.raises(ValueError):
        transform_chart_document(
            source, StandardChartView(kind="group", labelField="科室", valueFields=["预算"]), []
        )


def test_pivot_and_max_abs_sort_do_not_sum_duplicate_cells():
    source = {
        "columns": ["period", "type", "change"],
        "rows": [
            ["三月", "甲", -100],
            ["十一月", "乙", 20],
            ["十一月", "甲", 5],
            ["三月", "乙", 30],
        ],
        "columnMeta": {"change": {"unit": "元"}},
    }
    view = StandardChartView(
        kind="pivot",
        labelField="type",
        valueFields=["change"],
        seriesField="period",
        seriesValues=["三月", "十一月"],
    )
    result = transform_chart_document(source, view, [])
    ordered = order_standard_rows(
        result,
        "type",
        StandardChartOrder(mode="max_abs", fields=["三月", "十一月"], descending=True),
    )
    assert ordered["rows"] == [["甲", -100, 5], ["乙", 30, 20]]
    source["rows"].append(["三月", "甲", 1])
    with pytest.raises(ValueError, match="Ambiguous"):
        transform_chart_document(source, view, [])


def test_mom_sorts_contiguous_months_and_preserves_missing_base():
    source = {
        "columns": ["月份", "收入"],
        "rows": [["2025-03", 0], ["2025-01", 100], ["2025-02", 110], ["2025-04", 20]],
        "columnMeta": {"收入": {"unit": "元"}},
    }
    spec = StandardChartDerivation(
        kind="mom_percent", name="环比", numerator="收入", labelField="月份"
    )
    result = transform_chart_document(source, None, [spec])
    assert [row[0] for row in result["rows"]] == ["2025-01", "2025-02", "2025-03", "2025-04"]
    assert [row[-1] for row in result["rows"]] == pytest.approx([None, 10, -100, None])
    source["rows"] = source["rows"][:-1]
    source["rows"][0][0] = "2025-05"
    with pytest.raises(ValueError, match="missing months"):
        transform_chart_document(source, None, [spec])


def test_nullable_dual_axis_scales_without_zero_filling(render):  # noqa: F811
    source = {
        "columns": ["月份", "收入", "环比", "备注"],
        "rows": [["一月", 1e8, None, "无基数"], ["二月", 2e8, 100, "正常"]],
        "columnMeta": {"收入": {"unit": "元"}, "环比": {"unit": "%", "isPercent": True}},
    }
    plan, inputs = build(source, form="bar", selected=("收入", "环比"))
    chart = plan.charts[0]
    chart.standard_label_field = "月份"
    chart.standard_axes = StandardChartAxes(
        mode="dual", rightFields=["环比"], allowNulls=True, leftDisplayUnit="亿元"
    )
    figure = render(plan, inputs)
    assert [bar.get_height() for bar in figure.axes[0].containers[0]] == [1, 2]
    values = figure.axes[1].lines[0].get_ydata()
    assert math.isnan(values[0]) and values[1] == 100
    assert figure.axes[0].get_ylabel() == "左轴 · 亿元"
    chart.standard_axes = StandardChartAxes(mode="dual", rightFields=["环比"])
    assert standard_visualization_script(plan, inputs) is None


def test_mixed_shared_axis_and_alias_keep_original_series_identity(render):  # noqa: F811
    source = {
        "columns": ["label", "actual", "budget"],
        "rows": [["一月", 1e8, 2e8], ["二月", 3e8, 2e8]],
        "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "元"}},
    }
    plan, inputs = build(
        source,
        form="bar",
        selected=("actual", "budget"),
        style={
            "series": [
                {"series": "actual", "label": "实际"},
                {"series": "budget", "label": "预算", "geometry": "line"},
            ]
        },
    )
    plan.charts[0].standard_display_unit = "亿元"
    figure = render(plan, inputs)
    assert len(figure.axes) == 1
    ax = figure.axes[0]
    assert [bar.get_height() for bar in ax.containers[0]] == [1, 3]
    assert list(ax.lines[0].get_ydata()) == [2, 2]
    assert ax.lines[0].get_label() == "budget"
    assert [text.get_text() for text in ax.get_legend().get_texts()] == ["预算", "实际"]


def test_panels_sort_independently_and_bind_colors_to_visible_label(render):  # noqa: F811
    import matplotlib.colors as colors

    source = {
        "columns": ["label", "actual", "budget"],
        "rows": [["甲", 10, 30], ["乙", 50, 10], ["丙", 30, 50]],
        "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "元"}},
    }
    plan, inputs = build(
        source,
        selected=("actual", "budget"),
        style={
            "points": [
                {"series": "actual", "label": "乙", "color": "#ff0000"},
                {"series": "budget", "label": "乙", "color": "#ff0000"},
            ]
        },
    )
    plan.charts[0].standard_axes = StandardChartAxes(mode="panels", panelLimit=2)
    figure = render(plan, inputs)
    assert [tick.get_text() for tick in figure.axes[0].get_yticklabels()] == ["乙", "丙"]
    assert [tick.get_text() for tick in figure.axes[1].get_yticklabels()] == ["丙", "甲"]
    assert [bar.get_width() for bar in figure.axes[0].containers[0]] == [50, 30]
    assert colors.to_hex(figure.axes[0].containers[0][0].get_facecolor()) == "#ff0000"


def test_derived_document_runtime_still_rejects_original_identity_tamper(tmp_path, monkeypatch):
    plan, inputs = build(document(), selected=("预算", "合同"))
    plan.charts[0].standard_view = StandardChartView(
        kind="group", labelField="科室", valueFields=["预算", "合同"]
    )
    plan.charts[0].standard_label_field = "科室"
    script = standard_visualization_script(plan, inputs)
    assert script is not None
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="identity changed"):
        exec(script, {})


def test_month_alignment_requires_explicit_total_exclusion_and_preserves_nulls():
    from smart_reporting.reporting.workflow.runtime.chart_inputs import ChartInputFile

    docs = [
        {
            "columns": ["date", "value"],
            "rows": [["2025-01-01", 10], ["2025-02-01", 0]],
            "columnMeta": {"value": {"unit": "人次"}},
        },
        {
            "columns": ["month", "value"],
            "rows": [["2025-02", None], ["2025-01", 100], ["全年累计", 100]],
            "columnMeta": {"value": {"unit": "元"}},
        },
    ]
    files = tuple(ChartInputFile(str(i), json.dumps(doc).encode()) for i, doc in enumerate(docs))
    entries = [{"path": file.path, "sha256": file.sha256} for file in files]
    selections = [
        StandardChartSource(
            sourceIndex=0,
            labelField="date",
            valueField="value",
            seriesName="人次",
            labelMode="month",
        ),
        StandardChartSource(
            sourceIndex=1,
            labelField="month",
            valueField="value",
            seriesName="单价",
            labelMode="month",
            excludedLabels=["全年累计"],
        ),
    ]
    assert align_chart_sources(entries, files, selections) is None
    aligned = align_chart_sources(entries, files, selections, allow_nulls=True)
    assert aligned[0]["rows"] == [["2025-01", 10, 100], ["2025-02", 0, None]]
    assert set(aligned[1]) == {(file.path, file.sha256) for file in files}
    selections[1] = selections[1].model_copy(update={"excluded_labels": ()})
    assert align_chart_sources(entries, files, selections, allow_nulls=True) is None


def test_month_normalization_does_not_merge_two_days_in_same_month():
    from smart_reporting.reporting.workflow.runtime.chart_inputs import ChartInputFile

    source = ChartInputFile(
        "input",
        json.dumps(
            {
                "columns": ["date", "value"],
                "rows": [["2025-01-01", 1], ["2025-01-02", 2]],
                "columnMeta": {"value": {"unit": "元"}},
            }
        ).encode(),
    )
    selection = StandardChartSource(
        sourceIndex=0, labelField="date", valueField="value", seriesName="收入", labelMode="month"
    )
    assert (
        align_chart_sources([{"path": source.path, "sha256": source.sha256}], [source], [selection])
        is None
    )


@pytest.mark.parametrize("kind", ["ratio_percent", "difference"])
def test_derivation_rejects_incompatible_units(kind):
    source = document()
    source["columnMeta"]["合同"]["unit"] = "人次"
    spec = StandardChartDerivation(kind=kind, name="计算", numerator="合同", denominator="预算")
    with pytest.raises(ValueError, match="Incompatible"):
        transform_chart_document(source, None, [spec])


def test_percentage_group_and_incomplete_pivot_are_rejected():
    source = document()
    source["columnMeta"]["预算"] = {"unit": "%", "isPercent": True}
    with pytest.raises(ValueError, match="not additive"):
        transform_chart_document(
            source, StandardChartView(kind="group", labelField="科室", valueFields=["预算"]), []
        )
    with pytest.raises(ValueError, match="Incomplete pivot"):
        transform_chart_document(
            document(),
            StandardChartView(
                kind="pivot",
                labelField="科室",
                valueFields=["预算"],
                seriesField="备注",
                seriesValues=["项目1", "项目3"],
            ),
            [],
        )


@pytest.mark.parametrize("seed,scale", [(7, 1e-12), (13, 1), (41, 1e12), (67, 1e20)])
def test_group_replacement_data_matches_independent_sum(seed, scale):
    rng = random.Random(seed)
    rows = [
        [
            rng.choice(["新类别甲", "新类别乙", "新类别丙"]),
            rng.uniform(-100, 100) * scale,
            rng.uniform(0, 100) * scale,
            f"新项目{i}",
        ]
        for i in range(100)
    ]
    rng.shuffle(rows)
    result = transform_chart_document(
        document(rows),
        StandardChartView(kind="group", labelField="科室", valueFields=["预算", "合同"]),
        [],
    )
    for label, budget, contract in result["rows"]:
        assert budget == pytest.approx(
            math.fsum(row[1] for row in rows if row[0] == label), rel=1e-12
        )
        assert contract == pytest.approx(
            math.fsum(row[2] for row in rows if row[0] == label), rel=1e-12
        )


def test_explicit_source_window_is_applied_before_chart_capacity_check():
    from smart_reporting.reporting.workflow.runtime.chart_inputs import ChartInputFile

    source = ChartInputFile(
        "input",
        json.dumps(
            {
                "columns": ["label", "value"],
                "rows": [[f"类别{i}", i] for i in range(100)],
                "columnMeta": {"value": {"unit": "元"}},
            }
        ).encode(),
    )
    selection = StandardChartSource(
        sourceIndex=0, labelField="label", valueField="value", seriesName="金额"
    )
    entries = [{"path": source.path, "sha256": source.sha256}]
    assert align_chart_sources(entries, [source], [selection]) is None
    result = align_chart_sources(entries, [source], [selection], selected_labels=["类别5", "类别7"])
    assert result[0]["rows"] == [["类别5", 5], ["类别7", 7]]


def test_panel_peak_uses_visible_subset_and_avoids_duplicate_value_label(render):  # noqa: F811
    source = {
        "columns": ["label", "actual"],
        "rows": [["甲", 10], ["乙", 20], ["丙", 30]],
        "columnMeta": {"actual": {"unit": "元"}},
    }
    plan, inputs = build(
        source, style={"annotationOffsetX": 8, "annotationOffsetY": 0, "valueMargin": 0.5}
    )
    plan.charts[0].standard_axes = StandardChartAxes(
        mode="panels", panelLimit=2, panelDescending=False
    )
    plan.charts[0].standard_annotations = (
        StandardChartAnnotation(kind="values", series="actual"),
        StandardChartAnnotation(kind="peak", series="actual"),
    )
    figure = render(plan, inputs)
    texts = [text.get_text() for text in figure.axes[0].texts]
    assert len(texts) == 2
    assert sum("20.00元" in text for text in texts) == 1
