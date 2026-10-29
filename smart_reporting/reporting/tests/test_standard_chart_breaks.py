import pytest
from pydantic import ValidationError

from smart_reporting.reporting.tests.test_standard_chart_presentation import (  # noqa: F401
    build,
    render,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    StandardChartAnnotation,
    StandardChartAxes,
    StandardChartAxisBreak,
    StandardChartCanvas,
    StandardChartDomains,
    StandardChartStyle,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def broken_plan(form="line", rows=None, **options):
    source = {
        "columns": ["label", "actual", "budget"],
        "rows": rows or [["一月", 10, 20], ["二月", 1000, 1100]],
        "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "元"}},
    }
    plan, inputs = build(source, form=form, selected=("actual", "budget"))
    chart = plan.charts[0]
    chart.standard_annotations = ()
    chart.standard_break = StandardChartAxisBreak(
        lower={"min": 0, "max": 50, "ticks": [0, 25, 50]},
        upper={"min": 900, "max": 1200, "ticks": [900, 1050, 1200]},
        **options,
    )
    return plan, inputs


def test_broken_line_preserves_full_coordinates_on_both_intervals_and_marks_omission(render):  # noqa: F811
    plan, inputs = broken_plan()
    figure = render(plan, inputs)
    assert [axis.get_ylim() for axis in figure.axes] == [(900, 1200), (0, 50)]
    for axis in figure.axes:
        assert list(axis.lines[0].get_ydata()) == [10, 1000]
        assert list(axis.lines[1].get_ydata()) == [20, 1100]
        assert (
            len([line for line in axis.lines if getattr(line, "_standard_axis_break_mark", False)])
            == 2
        )
    assert figure.axes[1].get_position().y1 < figure.axes[0].get_position().y0
    assert any("省略开区间(50.0, 900.0)" in text.get_text() for text in figure.texts)


@pytest.mark.parametrize("layout", ["tight", "constrained", "manual"])
def test_break_layout_preserves_height_ratio_gap_and_fixed_canvas(render, layout):  # noqa: F811
    plan, inputs = broken_plan(lowerFraction=0.3, gap=0.15)
    plan.charts[0].standard_canvas = StandardChartCanvas(
        sizeMode="fixed", width=14, height=9, dpi=100, layout=layout
    )
    figure = render(plan, inputs)
    upper, lower = [axis.get_position() for axis in figure.axes]
    assert lower.height / upper.height == pytest.approx(0.3 / 0.7, rel=1e-6)
    assert lower.y1 < upper.y0 and figure.bbox.width == 1400 and figure.bbox.height == 900


def test_broken_bar_preserves_signed_heights_baseline_and_point_colors(render):  # noqa: F811
    from matplotlib.colors import to_hex

    plan, inputs = broken_plan("bar")
    plan.charts[0].standard_style = StandardChartStyle(
        points=[{"series": "actual", "label": "二月", "color": "#ff0000"}]
    )
    figure = render(plan, inputs)
    for axis in figure.axes:
        bars = axis.containers[0]
        assert [bar.get_height() for bar in bars] == [10, 1000]
        assert [bar.get_y() for bar in bars] == [0, 0]
        assert to_hex(bars[1].get_facecolor()) == "#ff0000"


@pytest.mark.parametrize("form", ["stacked-bar", "stacked-area", "stacked-total"])
def test_broken_stack_uses_cumulative_geometry_and_frozen_total(render, form):  # noqa: F811
    plan, inputs = broken_plan(form, rows=[["一月", 10, 20], ["二月", 950, 50]])
    # A boundary at950 and total1000 are both in the upper interval.
    figure = render(plan, inputs)
    for axis in figure.axes:
        if form != "stacked-area":
            assert [bar.get_y() for bar in axis.containers[1]] == [10, 950]
            assert [bar.get_height() for bar in axis.containers[1]] == [20, 50]
        if form == "stacked-total":
            total = next(line for line in axis.lines if "分项合计" in line.get_label())
            assert list(total.get_ydata()) == [30, 1000]


def test_broken_mixed_geometry_matches_bound_values(render):  # noqa: F811
    plan, inputs = broken_plan("line")
    plan.charts[0].standard_style = StandardChartStyle(
        series=[{"series": "actual", "geometry": "bar"}, {"series": "budget", "geometry": "line"}]
    )
    figure = render(plan, inputs)
    assert [bar.get_height() for bar in figure.axes[0].containers[0]] == [10, 1000]
    assert list(figure.axes[0].lines[0].get_ydata()) == [20, 1100]


def test_break_display_units_and_percentage_scale_are_not_raw_axis_values(render):  # noqa: F811
    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartBand

    source = {
        "columns": ["label", "actual", "low", "high"],
        "rows": [["一月", 1e8, 0.8e8, 1.2e8], ["二月", 1e10, 0.95e10, 1.05e10]],
        "columnMeta": {field: {"unit": "元"} for field in ["actual", "low", "high"]},
    }
    plan, inputs = build(source, form="line", selected=("actual",))
    chart = plan.charts[0]
    chart.standard_display_unit = "亿元"
    chart.standard_bands = (
        StandardChartBand(series="actual", lowerField="low", upperField="high"),
    )
    chart.standard_break = StandardChartAxisBreak(
        lower={"min": 0, "max": 2}, upper={"min": 90, "max": 110}
    )
    figure = render(plan, inputs)
    for axis in figure.axes:
        assert list(axis.lines[0].get_ydata()) == [1, 100]
        vertices = [point for path in axis.collections[0].get_paths() for point in path.vertices]
        assert min(y for x, y in vertices) == pytest.approx(0.8) and max(
            y for x, y in vertices
        ) == pytest.approx(105)


def test_omitted_points_require_explicit_disclosure_and_do_not_change_source_arrays(render):  # noqa: F811
    plan, inputs = broken_plan(rows=[["一月", 10, 20], ["二月", 500, 600], ["三月", 1000, 1100]])
    assert (
        standard_visualization_preflight(plan, inputs).diagnostic["code"]
        == "standard_break_hides_values"
    )
    chart = plan.charts[0]
    chart.standard_break = chart.standard_break.model_copy(update={"omitted_values": "annotate"})
    chart.standard_annotations = (StandardChartAnnotation(kind="values", series="actual"),)
    figure = render(plan, inputs)
    assert [list(axis.lines[0].get_ydata()) for axis in figure.axes] == [[10, 500, 1000]] * 2
    assert [text.xy[1] for axis in figure.axes for text in axis.texts] == [1000, 10]
    assert any(
        "数据/边界值2项未显示" in text.get_text() and "原值未改" in text.get_text()
        for text in figure.texts
    )


@pytest.mark.parametrize(
    "fault,code",
    [
        ("outer", "standard_break_clips_data"),
        ("zero", "standard_break_zero_conflict"),
        ("empty", "standard_break_empty_interval"),
        ("dual", "standard_break_combination_unsupported"),
        ("log", "standard_break_combination_unsupported"),
        ("domains", "standard_break_combination_unsupported"),
        ("horizontal-panels", "standard_break_combination_unsupported"),
    ],
)
def test_break_unsupported_or_hidden_data_returns_actionable_fallback(fault, code):
    plan, inputs = broken_plan()
    chart = plan.charts[0]
    if fault == "outer":
        chart.standard_break = StandardChartAxisBreak(
            lower={"min": 0, "max": 50}, upper={"min": 900, "max": 1050}
        )
    elif fault == "zero":
        chart.standard_axes = StandardChartAxes(zeroBaseline=True)
        chart.standard_break = StandardChartAxisBreak(
            lower={"min": 5, "max": 50}, upper={"min": 900, "max": 1200}
        )
    elif fault == "empty":
        chart.standard_break = StandardChartAxisBreak(
            lower={"min": -200, "max": -100}, upper={"min": 900, "max": 1200}, outOfRange="annotate"
        )
    elif fault == "dual":
        chart.standard_axes = StandardChartAxes(mode="dual", rightFields=["budget"])
    elif fault == "log":
        chart.standard_axes = StandardChartAxes(scale="log")
    elif fault == "domains":
        chart.standard_domains = StandardChartDomains(left={"min": 0, "max": 1200})
    else:
        chart.visual_form = "barh"
        chart.standard_axes = StandardChartAxes(mode="panels")
    assert standard_visualization_preflight(plan, inputs).diagnostic["code"] == code


@pytest.mark.parametrize(
    "lower,upper",
    [
        ({"min": 0}, {"min": 100, "max": 200}),
        ({"min": 0, "max": 100}, {"min": 50, "max": 200}),
        ({"min": 0, "max": 100}, {"min": 100, "max": 200}),
        ({"min": True, "max": 50}, {"min": 100, "max": 200}),
        ({"min": 0, "max": 50, "outOfRange": "annotate"}, {"min": 100, "max": 200}),
    ],
)
def test_break_schema_requires_complete_disjoint_explicit_intervals(lower, upper):
    with pytest.raises(ValidationError):
        StandardChartAxisBreak(lower=lower, upper=upper)


def test_broken_percentage_uses_normalized_percent_values(render):  # noqa: F811
    source = {
        "columns": ["label", "actual"],
        "rows": [["一月", 0.001], ["二月", 0.95]],
        "columnMeta": {"actual": {"unit": "%", "isPercent": False}},
    }
    plan, inputs = build(source, form="line", selected=("actual",))
    plan.charts[0].standard_break = StandardChartAxisBreak(
        lower={"min": 0, "max": 1}, upper={"min": 90, "max": 100}
    )
    figure = render(plan, inputs)
    assert [list(axis.lines[0].get_ydata()) for axis in figure.axes] == [[0.1, 95]] * 2
    assert all("%" in axis.get_ylabel() for axis in figure.axes)


def test_break_missing_points_are_distinct_from_omitted_interval(render):  # noqa: F811
    import math

    plan, inputs = broken_plan(rows=[["一月", None, 20], ["二月", 1000, 1100]])
    plan.charts[0].standard_axes = StandardChartAxes(allowNulls=True)
    figure = render(plan, inputs)
    assert all(math.isnan(axis.lines[0].get_ydata()[0]) for axis in figure.axes)
    assert any(
        "actual 缺失1点" in text.get_text() and "未补零" in text.get_text() for text in figure.texts
    )


def test_outer_clipping_requires_disclosure_without_clamping_coordinates(render):  # noqa: F811
    plan, inputs = broken_plan(rows=[["一月", 10, 20], ["二月", 1300, 1100]], outOfRange="annotate")
    figure = render(plan, inputs)
    assert [list(axis.lines[0].get_ydata()) for axis in figure.axes] == [[10, 1300]] * 2
    assert any("整体范围外低于0、高于1项" in text.get_text() for text in figure.texts)


@pytest.mark.parametrize("form", ["line", "stacked-total", "barh"])
def test_breaks_pass_formal_source_gate_and_preserve_original_identity(tmp_path, monkeypatch, form):
    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
    from smart_reporting.reporting.code_agent.toolkit import validate_script_source

    plan, inputs = broken_plan(form, rows=[["一月", 10, 20], ["二月", 950, 50]])
    source = standard_visualization_preflight(plan, inputs).source
    assert source
    context = ReportingCodingTaskContext(
        task_id="test",
        task_kind="visualization",
        code_mode_session_id="test",
        workspace_key="test",
        workspace_root=tmp_path,
        script_path="chart.py",
        authorized_read_paths=("input.json",),
        authorized_write_paths=("chart.py", "chart.png"),
        declared_output_paths=("chart.png",),
        max_source_bytes=128 * 1024,
    )
    validate_script_source(context, source)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input.json").write_text("{}")
    with pytest.raises(ValueError, match="identity changed"):
        exec(source, {})


@pytest.mark.parametrize("form", ["line", "barh"])
def test_break_real_plan_roundtrip_and_field_materialization(render, form):  # noqa: F811
    import json

    from smart_reporting.reporting.workflow.runtime.chart_inputs import materialize_chart_inputs
    from smart_reporting.reporting.workflow.runtime.phase_models import (
        ChartDraft,
        VisualizationPlanDraft,
    )

    base, original = broken_plan()
    document = json.loads(original.files[0].content)
    chart = ChartDraft(
        chartId="chart",
        sourcePath="chart.png",
        title="冻结输入断轴",
        altText="双区间显示原始数据",
        citationIds=["citation"],
        metricCodes=["metric"],
        currentPeriod="2026-10",
        sourceDatasetId="dataset",
        aggregationGrain="month",
        visualForm=form,
        standardValueFields=["actual", "budget"],
        standardBreak=base.charts[0].standard_break,
        dataBindings=[
            {
                "analysisId": "a",
                "factPath": "facts.json",
                "dataPath": "findings[0].rows",
                "fields": document["columns"],
                "role": "断轴图",
            }
        ],
    )
    plan = VisualizationPlanDraft.model_validate_json(
        VisualizationPlanDraft(charts=(chart,)).model_dump_json(by_alias=True)
    )
    facts = [
        {
            "analysisId": "a",
            "factFile": {"path": "facts.json", "sha256": "f" * 64},
            "dataDescriptors": [{"dataPath": "findings[0].rows", "fields": document["columns"]}],
        }
    ]
    inputs = materialize_chart_inputs(
        plan, facts, {"facts.json": {"findings": [document]}}, output_root="."
    )
    figure = render(plan, inputs)
    if form == "barh":
        assert [axis.get_xlim() for axis in figure.axes] == [(0, 50), (900, 1200)]
        assert [bar.get_width() for bar in figure.axes[0].containers[0]] == [10, 1000]
    else:
        assert [axis.get_ylim() for axis in figure.axes] == [(900, 1200), (0, 50)]
        assert list(figure.axes[0].lines[0].get_ydata()) == [10, 1000]


@pytest.mark.parametrize(
    "fault", ["limits", "marks", "ratio", "values", "baseline", "area", "band"]
)
def test_independent_break_auditor_detects_wrong_panels_geometry_and_coordinates(tmp_path, fault):
    import copy

    from scripts.replay_standard_visualization_variants import run_case
    from scripts.standard_visualization_break_cases import break_cases

    mode = {"baseline": "bar", "area": "stacked-area", "band": "band"}.get(fault, "line")
    case = copy.deepcopy(next(item for item in break_cases() if item["id"] == f"breaks-{mode}-3-1"))
    if fault == "limits":
        case["assertions"]["breaks"][0]["upper"][1] += 1
    elif fault == "marks":
        case["assertions"]["breaks"][0]["marksPerPanel"] = 3
    elif fault == "ratio":
        case["assertions"]["breaks"][0]["lowerFraction"] = 0.5
    elif fault == "values":
        case["assertions"]["series"][0]["values"][0] += 1
    elif fault == "baseline":
        case["assertions"]["series"][0]["bottoms"][0] += 1
    elif fault == "area":
        case["assertions"]["areas"][0]["upper"][0] += 1
    else:
        case["assertions"]["bands"][0]["upper"][0] += 1
    result = run_case(case, tmp_path)
    assert result["status"] == "semantic_mismatch" and result["audit"]["semanticMismatches"]


def test_breaks_and_explicit_domains_can_coexist_in_different_batch_charts(render):  # noqa: F811
    import copy
    from pathlib import Path
    from types import SimpleNamespace

    from smart_reporting.reporting.tests.test_standard_chart_domains import attach, plan_for
    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )

    native = plan_for()
    bounded = plan_for()
    attach(bounded[0], left={"min": 0, "max": 50})
    charts, files, entries = [], [], []
    for index, (plan, inputs) in enumerate([broken_plan(), native, bounded]):
        chart = copy.deepcopy(plan.charts[0])
        chart.chart_id = f"chart-{index}"
        chart.source_path = "chart.png" if index == 2 else f"chart-{index}.png"
        charts.append(chart)
        source = ChartInputFile(f"input-{index}.json", inputs.files[0].content)
        files.append(source)
        entries.append({"chartId": chart.chart_id, "path": source.path, "sha256": source.sha256})
    render(
        SimpleNamespace(charts=charts),
        ChartInputMaterialization(files=tuple(files), entries=tuple(entries)),
    )
    assert all(Path(chart.source_path).read_bytes().startswith(b"\x89PNG") for chart in charts)


def test_breaks_keep_auxiliary_frozen_percentage_labels(render):  # noqa: F811
    source = {
        "columns": ["label", "actual", "ratio"],
        "rows": [["一月", 10, 0.1], ["二月", 1000, 0.3]],
        "columnMeta": {"actual": {"unit": "元"}, "ratio": {"unit": "%", "isPercent": False}},
    }
    plan, inputs = build(source, form="line", selected=("actual",))
    chart = plan.charts[0]
    chart.standard_label_fields = ("ratio",)
    chart.standard_break = StandardChartAxisBreak(
        lower={"min": 0, "max": 50}, upper={"min": 900, "max": 1200}
    )
    figure = render(plan, inputs)
    assert "ratio: 30.00%" in figure.axes[0].texts[0].get_text()
    assert "ratio: 10.00%" in figure.axes[1].texts[0].get_text()


def test_break_peak_reference_and_range_annotations_bind_correct_intervals(render):  # noqa: F811
    plan, inputs = broken_plan()
    plan.charts[0].standard_annotations = (
        StandardChartAnnotation(kind="peak", series="actual"),
        StandardChartAnnotation(kind="reference", series="actual", label="一月"),
        StandardChartAnnotation(kind="range", label="一月", endLabel="二月"),
    )
    figure = render(plan, inputs)
    assert any("峰值 1,000.00元" in text.get_text() for text in figure.axes[0].texts)
    assert any("参考 一月: 10.00元" in text.get_text() for text in figure.axes[1].texts)
    assert all(len(axis.patches) == 1 for axis in figure.axes)


def test_break_independent_frozen_total_is_not_recounted_in_stack(render):  # noqa: F811
    source = {
        'columns': ['label', 'actual', 'budget', 'total'],
        'rows': [['一月', 10, 20, 30], ['二月', 950, 50, 1000]],
        'columnMeta': {name: {'unit': '元'} for name in ['actual', 'budget', 'total']},
    }
    plan, inputs = build(source, form='stacked-total', selected=('actual', 'budget', 'total'))
    chart = plan.charts[0]
    chart.standard_total_field = 'total'
    chart.standard_break = StandardChartAxisBreak(lower={'min': 0, 'max': 50}, upper={'min': 900, 'max': 1200})
    figure = render(plan, inputs)
    for axis in figure.axes:
        assert len(axis.containers) == 2
        assert [bar.get_y() for bar in axis.containers[1]] == [10, 950]
        total = next(line for line in axis.lines if line.get_label().startswith('total（独立冻结'))
        assert list(total.get_ydata()) == [30, 1000]


def test_negative_bars_cross_omitted_interval_without_changing_signed_height(render):  # noqa: F811
    plan, inputs = broken_plan('bar', rows=[['一月', -1000, 10], ['二月', -950, 20]])
    plan.charts[0].standard_break = StandardChartAxisBreak(lower={'min': -1200, 'max': -900}, upper={'min': 0, 'max': 50})
    figure = render(plan, inputs)
    assert [axis.get_ylim() for axis in figure.axes] == [(0, 50), (-1200, -900)]
    for axis in figure.axes:
        assert [bar.get_height() for bar in axis.containers[0]] == [-1000, -950]
        assert [bar.get_y() for bar in axis.containers[0]] == [0, 0]
