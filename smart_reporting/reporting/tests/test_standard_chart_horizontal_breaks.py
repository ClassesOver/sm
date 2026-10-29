import copy
import math

import pytest

from smart_reporting.reporting.tests.test_standard_chart_breaks import broken_plan
from smart_reporting.reporting.tests.test_standard_chart_presentation import (  # noqa: F401
    build,
    render,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    StandardChartAnnotation,
    StandardChartAxes,
    StandardChartAxisBreak,
    StandardChartCanvas,
    StandardChartStyle,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


@pytest.mark.parametrize("layout", ["tight", "constrained", "manual"])
def test_horizontal_break_retains_full_geometry_shared_categories_and_widths(render, layout):  # noqa: F811
    plan, inputs = broken_plan("barh", lowerFraction=.3, gap=.15)
    chart = plan.charts[0]
    chart.standard_canvas = StandardChartCanvas(sizeMode="fixed", width=16, height=8, dpi=100, layout=layout)
    chart.standard_style = StandardChartStyle(labelRotation=0, barGroupWidth=.8,
        points=[{"series": "actual", "label": "二月", "color": "#ff0000"}])
    figure = render(plan, inputs)
    from matplotlib.colors import to_hex

    left, right = figure.axes
    assert [axis.get_xlim() for axis in figure.axes] == [(0, 50), (900, 1200)]
    assert left.get_ylim() == right.get_ylim() and left.yaxis_inverted()
    assert [tick.get_text() for tick in left.get_yticklabels()] == ["一月", "二月"]
    assert not right.get_yticklabels()
    for axis in figure.axes:
        for index, values in enumerate([[10, 1000], [20, 1100]]):
            bars = axis.containers[index]
            assert [bar.get_width() for bar in bars] == values
            assert [bar.get_x() for bar in bars] == [0, 0]
            assert [bar.get_y()+bar.get_height()/2 for bar in bars] == pytest.approx([-.2+index*.4, .8+index*.4])
        assert to_hex(axis.containers[0][1].get_facecolor()) == "#ff0000"
        marks = [line for line in axis.lines if getattr(line, "_standard_axis_break_mark", False)]
        assert len(marks) == 2
        for i, mark in enumerate(marks):
            assert not mark.get_clip_on() and mark.get_transform() == axis.transAxes
            assert sum(mark.get_xdata())/2 == (1 if axis is left else 0)
            assert sum(mark.get_ydata())/2 == i
    a, b = left.get_position(), right.get_position()
    assert a.x1 < b.x0 and a.width/b.width == pytest.approx(.3/.7, rel=1e-6)
    assert figure.bbox.width == 1600 and figure.bbox.height == 800
    assert any("左右段分别线性显示" in text.get_text() for text in figure.texts)


def test_negative_horizontal_breaks_keep_zero_origin_signed_lengths_and_visible_zero(render):  # noqa: F811
    plan, inputs = broken_plan("barh", rows=[["一月", -1000, 10], ["二月", -950, 20]])
    plan.charts[0].standard_axes = StandardChartAxes(zeroBaseline=True)
    plan.charts[0].standard_break = StandardChartAxisBreak(lower={"min": -1200, "max": -900}, upper={"min": 0, "max": 50})
    plan.charts[0].standard_annotations = (StandardChartAnnotation(kind="values", series="actual"),)
    figure = render(plan, inputs)
    assert [axis.get_xlim() for axis in figure.axes] == [(-1200, -900), (0, 50)]
    for axis in figure.axes:
        assert [bar.get_width() for bar in axis.containers[0]] == [-1000, -950]
        assert [bar.get_x() for bar in axis.containers[0]] == [0, 0]
    assert all(text.get_ha()=="right" and text.get_position()[0]<0 for text in figure.axes[0].texts)


@pytest.mark.parametrize("policy", ["omitted", "outer"])
def test_horizontal_hidden_values_need_disclosure_and_preserve_bar_endpoints(render, policy):  # noqa: F811
    value = 500 if policy == "omitted" else 1300
    plan, inputs = broken_plan("barh", rows=[["一月", 10, 20], ["二月", value, 1100]])
    chart = plan.charts[0]
    assert standard_visualization_preflight(plan, inputs).diagnostic["code"] == ("standard_break_hides_values" if policy == "omitted" else "standard_break_clips_data")
    chart.standard_break = chart.standard_break.model_copy(update={"omitted_values" if policy == "omitted" else "out_of_range": "annotate"})
    chart.standard_annotations = (StandardChartAnnotation(kind="values", series="actual"),)
    figure = render(plan, inputs)
    assert all([bar.get_width() for bar in axis.containers[0]] == [10, value] for axis in figure.axes)
    assert [text.xy[0] for axis in figure.axes for text in axis.texts] == [10]
    assert any(("数据/边界值1项未显示" if policy == "omitted" else "整体范围外低于0、高于1项") in text.get_text() for text in figure.texts)


def test_horizontal_breaks_convert_units_and_auxiliary_percentage_from_frozen_input(render):  # noqa: F811
    doc = {"columns": ["label", "actual", "ratio"], "rows": [["一月", 1e8, .1], ["二月", 1e10, .3]],
        "columnMeta": {"actual": {"unit": "元"}, "ratio": {"unit": "%", "isPercent": False}}}
    plan, inputs = build(doc)
    chart = plan.charts[0]
    chart.standard_display_unit = "亿元"
    chart.standard_label_fields = ("ratio",)
    chart.standard_break = StandardChartAxisBreak(lower={"min": 0, "max": 2}, upper={"min": 90, "max": 110})
    figure = render(plan, inputs)
    assert all([bar.get_width() for bar in axis.containers[0]] == [1, 100] for axis in figure.axes)
    assert "ratio: 10.00%" in figure.axes[0].texts[0].get_text()
    assert "ratio: 30.00%" in figure.axes[1].texts[0].get_text()
    assert all("亿元" in axis.get_xlabel() for axis in figure.axes)


def test_horizontal_break_fraction_values_are_normalized_before_interval_checks(render):  # noqa: F811
    doc = {"columns": ["label", "actual"], "rows": [["一月", .001], ["二月", .95]],
        "columnMeta": {"actual": {"unit": "%", "isPercent": False}}}
    plan, inputs = build(doc)
    plan.charts[0].standard_break = StandardChartAxisBreak(lower={"min": 0, "max": 1}, upper={"min": 90, "max": 100})
    figure = render(plan, inputs)
    assert all([bar.get_width() for bar in axis.containers[0]] == [.1, 95] for axis in figure.axes)


def test_horizontal_cross_panel_numeric_tick_collision_requests_layout_repair(render):  # noqa: F811
    plan, inputs = broken_plan("barh", gap=.03)
    chart = plan.charts[0]
    chart.standard_style = StandardChartStyle(labelRotation=0)
    chart.standard_canvas = StandardChartCanvas(sizeMode="fixed", width=8, height=8, dpi=100, layout="manual")
    chart.standard_break = StandardChartAxisBreak(lower={"min": 0, "max": 50, "ticks": [50], "tickFormat": "scientific", "decimals": 6},
        upper={"min": 900, "max": 1200, "ticks": [900], "tickFormat": "scientific", "decimals": 6}, gap=.03)
    with pytest.raises(ValueError, match="跨段数值刻度重叠"):
        render(plan, inputs)


def test_horizontal_missing_values_remain_nan_and_are_disclosed(render):  # noqa: F811
    plan, inputs = broken_plan("barh", rows=[["一月", None, 20], ["二月", 1000, 1100]])
    plan.charts[0].standard_axes = StandardChartAxes(allowNulls=True)
    figure = render(plan, inputs)
    assert all(math.isnan(axis.containers[0][0].get_width()) for axis in figure.axes)
    assert any("actual 缺失1点，保留空位，未补零" in text.get_text() for text in figure.texts)


def test_horizontal_reference_peak_range_and_point_bind_real_bar_coordinates(render):  # noqa: F811
    plan, inputs = broken_plan("barh")
    plan.charts[0].standard_annotations = (
        StandardChartAnnotation(kind="values", series="actual"),
        StandardChartAnnotation(kind="peak", series="actual", highlight=True, position="right"),
        StandardChartAnnotation(kind="point", series="budget", label="一月", caption="预算", position="right"),
        StandardChartAnnotation(kind="reference", series="actual", label="一月"),
        StandardChartAnnotation(kind="range", label="一月", endLabel="二月"),
    )
    figure = render(plan, inputs)
    left, right = figure.axes
    assert any("峰值 1,000.00元" in text.get_text() and text.xy[0]==1000 for text in right.texts)
    assert any("参考 一月: 10.00元" in text.get_text() for text in left.texts)
    assert any(text.get_text()=="预算 20.00元" and text.xy[0]==20 for text in left.texts)
    assert not any(hasattr(text, "xy") and text.xy[0]==1000 for text in left.texts)
    assert len(left.patches)==len(right.patches)==5  # Four bars plus frozen category span.
    assert list(right.collections[0].get_offsets()[0]) == pytest.approx([1000, .84])


def test_horizontal_vertical_summary_and_native_charts_share_formal_batch_and_keep_axes_independent(render, tmp_path):  # noqa: F811
    from types import SimpleNamespace

    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
    from smart_reporting.reporting.code_agent.toolkit import validate_script_source
    from smart_reporting.reporting.tests.test_standard_chart_box_summary import summary_plan
    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )

    native, native_inputs = broken_plan()
    native.charts[0].standard_break = None
    charts, files, entries = [], [], []
    for index, (plan, inputs) in enumerate([broken_plan("barh"), broken_plan(), summary_plan(), (native, native_inputs)]):
        chart = copy.deepcopy(plan.charts[0])
        chart.chart_id = f"chart-{index}"
        chart.source_path = "chart.png" if index==3 else f"chart-{index}.png"
        charts.append(chart)
        for n, original in enumerate(inputs.files):
            source = ChartInputFile(f"input-{index}-{n}.json", original.content)
            files.append(source)
            entries.append({"chartId": chart.chart_id, "path": source.path, "sha256": source.sha256})
    plan = SimpleNamespace(charts=charts)
    inputs = ChartInputMaterialization(files=tuple(files), entries=tuple(entries))
    source = standard_visualization_preflight(plan, inputs).source
    assert source
    context = ReportingCodingTaskContext(task_id="test", task_kind="visualization", code_mode_session_id="test",
        workspace_key="test", workspace_root=tmp_path, script_path="chart.py",
        authorized_read_paths=tuple(file.path for file in files),
        authorized_write_paths=("chart.py", *(chart.source_path for chart in charts)),
        declared_output_paths=tuple(chart.source_path for chart in charts), max_source_bytes=128*1024)
    validate_script_source(context, source)
    import matplotlib.figure

    saved = []
    original_save = matplotlib.figure.Figure.savefig
    from unittest.mock import patch

    def capture(fig, *args, **kwargs):
        saved.append(fig)
        return original_save(fig, *args, **kwargs)

    with patch.object(matplotlib.figure.Figure, "savefig", capture):
        render(plan, inputs)
    assert [ax.get_xlim() for ax in saved[0].axes] == [(0, 50), (900, 1200)]
    assert [ax.get_ylim() for ax in saved[1].axes] == [(900, 1200), (0, 50)]
    assert len(saved[2].axes) == len(saved[3].axes) == 1
    assert list(saved[3].axes[0].lines[0].get_ydata()) == [10, 1000]


@pytest.mark.parametrize("fault", ["limits", "marks", "ratio", "values", "starts", "centers", "colors", "categories"])
def test_horizontal_independent_auditor_rejects_wrong_geometry_and_semantics(tmp_path, fault):
    from scripts.replay_standard_visualization_variants import run_case
    from scripts.standard_visualization_horizontal_break_cases import horizontal_break_cases

    case = copy.deepcopy(next(item for item in horizontal_break_cases() if item["id"]=="horizontal-breaks-positive-3-1"))
    if fault == "limits":
        case["assertions"]["breaks"][0]["upper"][1] += 1
    elif fault == "marks":
        case["assertions"]["breaks"][0]["marksPerPanel"] = 3
    elif fault == "ratio":
        case["assertions"]["breaks"][0]["lowerFraction"] = .5
    elif fault == "categories":
        case["assertions"]["breaks"][0]["categoryLabels"].reverse()
    elif fault == "colors":
        case["assertions"]["series"][0]["colors"][0] = "#ffffff"
    else:
        case["assertions"]["series"][0][fault][0] += 1
    result = run_case(case, tmp_path)
    assert result["status"] == "semantic_mismatch" and result["audit"]["semanticMismatches"]
