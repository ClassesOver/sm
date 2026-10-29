import pytest

from smart_reporting.reporting.tests.test_standard_chart_presentation import (  # noqa: F401
    build,
    render,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    StandardChartAnnotation,
    StandardChartAxes,
    StandardChartDomains,
    StandardChartStyle,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def dual_plan(form="stacked-bar", rows=None, total=False):
    document = {"columns": ["label", "actual", "budget", "ratio"],
        "rows": rows or [["一月", 1e4, 2, .2], ["二月", 3e4, 4, .4]],
        "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "万元"}, "ratio": {"unit": "%", "isPercent": False}}}
    if total:
        document["columns"].append("total")
        document["columnMeta"]["total"] = {"unit": "元"}
        for row in document["rows"]:
            row.append(row[1]+row[2]*1e4)
    fields = tuple(document["columns"][1:])
    plan, inputs = build(document, form=form, selected=fields)
    chart = plan.charts[0]
    chart.standard_annotations = ()
    chart.standard_axes = StandardChartAxes(mode="dual", rightFields=["ratio"], leftDisplayUnit="万元")
    if total:
        chart.standard_total_field = "total"
    return plan, inputs


def test_dual_stack_keeps_separate_units_starts_and_right_fraction_scale(render):  # noqa: F811
    plan, inputs = dual_plan()
    figure = render(plan, inputs)
    left, right = figure.axes
    assert [bar.get_height() for bar in left.containers[0]] == [1, 3]
    assert [bar.get_height() for bar in left.containers[1]] == [2, 4]
    assert [bar.get_y() for bar in left.containers[1]] == [1, 3]
    assert list(right.lines[0].get_ydata()) == [20, 40]
    assert left.get_ylabel() == "左轴 · 万元" and right.get_ylabel() == "右轴 · %"
    assert any("未计入分项合计" in text.get_text() for text in figure.texts)


@pytest.mark.parametrize("frozen", [False, True])
def test_dual_stack_total_is_left_net_and_not_stacked_or_right_sum(render, frozen):  # noqa: F811
    plan, inputs = dual_plan("stacked-total", total=frozen)
    figure = render(plan, inputs)
    left, right = figure.axes
    assert len(left.containers) == 2
    assert list(left.lines[0].get_ydata()) == [3, 7]
    assert list(right.lines[0].get_ydata()) == [20, 40]


def test_dual_stack_signed_parts_use_separate_positive_negative_baselines_and_net_total(render):  # noqa: F811
    plan, inputs = dual_plan("stacked-total", rows=[["一月", -1e4, 2, .2], ["二月", 3e4, -4, .4]], total=True)
    figure = render(plan, inputs)
    left = figure.axes[0]
    assert [bar.get_y() for bar in left.containers[0]] == [0, 0]
    assert [bar.get_y() for bar in left.containers[1]] == [0, 0]
    assert [bar.get_height() for bar in left.containers[0]] == [-1, 3]
    assert [bar.get_height() for bar in left.containers[1]] == [2, -4]
    assert list(left.lines[0].get_ydata()) == [1, -1]
    assert any("净和，非正负外包络" in text.get_text() for text in figure.texts)


def test_dual_stack_values_annotate_cumulative_end_but_display_part_height(render):  # noqa: F811
    plan, inputs = dual_plan()
    chart = plan.charts[0]
    chart.standard_annotations = (StandardChartAnnotation(kind="values", series="budget"),)
    figure = render(plan, inputs)
    assert [text.xy for text in figure.axes[0].texts] == [(0, 3), (1, 7)]
    assert [text.get_text() for text in figure.axes[0].texts] == ["budget: 2.00万元", "budget: 4.00万元"]


def test_dual_stack_complex_labels_keep_frozen_auxiliary_percentage(render):  # noqa: F811
    plan, inputs = dual_plan()
    plan.charts[0].standard_label_fields = ("ratio",)
    plan.charts[0].standard_annotations = (StandardChartAnnotation(kind="values", series="budget"),)
    figure = render(plan, inputs)
    assert [text.get_text() for text in figure.axes[0].texts] == ["budget: 2.00万元 · ratio: 20.00%", "budget: 4.00万元 · ratio: 40.00%"]


def test_dual_stack_annotations_keep_visible_contrast_over_same_series_fill(render):  # noqa: F811
    plan, inputs = dual_plan()
    plan.charts[0].standard_annotations = (StandardChartAnnotation(kind="peak", series="ratio", highlight=True),)
    figure = render(plan, inputs)
    text = figure.axes[1].texts[0]
    assert text.xy == (1, 40)
    assert text.get_bbox_patch().get_facecolor() == (1, 1, 1, .94)


@pytest.mark.parametrize("side,maximum,code", [("left", 6, "standard_domain_clips_data"), ("right", 30, "standard_domain_clips_data")])
def test_dual_stack_domains_check_real_cumulative_and_right_coordinates(side, maximum, code):
    plan, inputs = dual_plan()
    plan.charts[0].standard_domains = StandardChartDomains(**{side: {"min": 0, "max": maximum}})
    result = standard_visualization_preflight(plan, inputs)
    assert result.source is None and result.diagnostic["code"] == code


def test_dual_stack_domains_are_independent_and_explicit_clip_preserves_values_and_hides_labels(render):  # noqa: F811
    plan, inputs = dual_plan()
    chart = plan.charts[0]
    chart.standard_domains = StandardChartDomains(left={"min": 0, "max": 6, "outOfRange": "annotate"}, right={"min": 0, "max": 100})
    chart.standard_annotations = (StandardChartAnnotation(kind="values", series="budget"), StandardChartAnnotation(kind="values", series="ratio"))
    figure = render(plan, inputs)
    left, right = figure.axes
    assert left.get_ylim() == (0, 6) and right.get_ylim() == (0, 100)
    assert [bar.get_y()+bar.get_height() for bar in left.containers[1]] == [3, 7]
    assert [text.get_visible() for text in left.texts] == [True, False]
    assert [text.get_visible() for text in right.texts] == [True, True]


def test_dual_stack_right_nulls_require_allow_nulls_and_preserve_nan_not_zero(render):  # noqa: F811
    import math

    plan, inputs = dual_plan(rows=[["一月", 1e4, 2, None], ["二月", 3e4, 4, .4]])
    assert standard_visualization_preflight(plan, inputs).source is None
    plan.charts[0].standard_axes = plan.charts[0].standard_axes.model_copy(update={"allow_nulls": True})
    figure = render(plan, inputs)
    assert math.isnan(figure.axes[1].lines[0].get_ydata()[0])
    assert any("ratio 缺失1点，保留断点，未补零" in text.get_text() for text in figure.texts)


def test_dual_stack_left_null_never_creates_incomplete_stack():
    plan, inputs = dual_plan(rows=[["一月", None, 2, .2], ["二月", 3e4, 4, .4]])
    plan.charts[0].standard_axes = plan.charts[0].standard_axes.model_copy(update={"allow_nulls": True})
    assert standard_visualization_preflight(plan, inputs).diagnostic["code"] == "standard_dual_stack_component_missing"


def test_dual_stack_points_series_alias_hatch_and_line_colors_remain_bound(render):  # noqa: F811
    from matplotlib.colors import to_hex

    plan, inputs = dual_plan()
    plan.charts[0].standard_style = StandardChartStyle(series=[{"series": "budget", "color": "#36856b", "hatch": "//"}, {"series": "ratio", "color": "#b55d68", "label": "完成率"}],
        points=[{"series": "actual", "label": "二月", "color": "#ff0000"}])
    figure = render(plan, inputs)
    assert to_hex(figure.axes[0].containers[0][1].get_facecolor()) == "#ff0000"
    assert figure.axes[0].containers[1][0].get_hatch() == "//"
    assert to_hex(figure.axes[1].lines[0].get_color()) == "#b55d68"
    assert figure.axes[1].get_legend().get_texts()[0].get_text() == "完成率 · 右轴"


def test_dual_stack_reference_point_peak_and_category_span_use_correct_axes(render):  # noqa: F811
    plan, inputs = dual_plan()
    plan.charts[0].standard_annotations = (
        StandardChartAnnotation(kind="point", series="budget", label="二月", highlight=True),
        StandardChartAnnotation(kind="peak", series="ratio"),
        StandardChartAnnotation(kind="reference", series="ratio", label="一月"),
        StandardChartAnnotation(kind="range", label="一月", endLabel="二月"),
    )
    figure = render(plan, inputs)
    assert figure.axes[0].texts[0].xy == (1, 7)
    assert any("峰值 ratio: 40.00%" == text.get_text() for text in figure.axes[1].texts)
    assert list(figure.axes[1].lines[1].get_ydata()) == [20, 20]


@pytest.mark.parametrize("fault", ["left_line", "right_bar", "nonlinear", "total_right"])
def test_dual_stack_unsupported_combinations_fallback_per_chart(fault):
    plan, inputs = dual_plan("stacked-total", total=True)
    chart = plan.charts[0]
    if fault in {"left_line", "right_bar"}:
        chart.standard_style = StandardChartStyle(series=[{"series": "actual" if fault=="left_line" else "ratio", "geometry": "line" if fault=="left_line" else "bar"}])
    elif fault == "nonlinear":
        chart.standard_axes = chart.standard_axes.model_copy(update={"scale": "symlog"})
    else:
        chart.standard_axes = chart.standard_axes.model_copy(update={"right_fields": ("ratio", "total")})
    assert standard_visualization_preflight(plan, inputs).source is None


def test_compiler_does_not_ignore_unexpanded_pagination():
    plan, inputs = dual_plan()
    plan.charts[0].standard_pagination = object()
    assert standard_visualization_preflight(plan, inputs).diagnostic["code"] == "standard_pagination_not_expanded"


@pytest.mark.parametrize("name_on_right", [False, True])
def test_computed_total_profile_cannot_collide_with_frozen_field_named_total(name_on_right):
    names = ["amount", "分项合计"] if name_on_right else ["分项合计", "ratio"]
    doc = {"columns": ["label", *names], "rows": [["A", 10, 10], ["B", 10, 20]],
        "columnMeta": {names[0]: {"unit": "元"}, names[1]: {"unit": "%", "isPercent": True}}}
    plan, inputs = build(doc, form="stacked-total", selected=tuple(names))
    chart = plan.charts[0]
    chart.standard_annotations = ()
    chart.standard_axes = StandardChartAxes(mode="dual", rightFields=[names[1]])
    chart.standard_domains = StandardChartDomains(**({"right": {"min": 0, "max": 15}} if name_on_right else {"left": {"min": 5, "max": 15}}))
    assert standard_visualization_preflight(plan, inputs).diagnostic["code"] == "standard_domain_clips_data"


def test_dual_stack_multiple_signed_components_have_separate_frozen_boundaries(render):  # noqa: F811
    doc = {"columns": ["label", "a", "b", "c", "d", "ratio"], "rows": [["一月", 10, -20, 30, -40, 25]],
        "columnMeta": {**{name: {"unit": "元"} for name in ("a", "b", "c", "d")}, "ratio": {"unit": "%", "isPercent": True}}}
    plan, inputs = build(doc, form="stacked-total", selected=("a", "b", "c", "d", "ratio"))
    chart = plan.charts[0]
    chart.standard_annotations = ()
    chart.standard_axes = StandardChartAxes(mode="dual", rightFields=["ratio"])
    chart.standard_domains = StandardChartDomains(left={"min": -60, "max": 40}, right={"min": 0, "max": 100})
    figure = render(plan, inputs)
    assert [container[0].get_y() for container in figure.axes[0].containers] == [0, 0, 10, -20]
    assert [container[0].get_height() for container in figure.axes[0].containers] == [10, -20, 30, -40]
    assert list(figure.axes[0].lines[0].get_ydata()) == [-20]
    chart.standard_domains = StandardChartDomains(left={"min": -59, "max": 40})
    assert standard_visualization_preflight(plan, inputs).diagnostic["code"] == "standard_domain_clips_data"


def test_dual_stack_auto_legend_with_three_components_and_total_stays_on_canvas(render):  # noqa: F811
    import json

    from scripts.replay_standard_visualization_variants import plan_from_saved
    from scripts.standard_visualization_dual_stack_cases import dual_stack_cases
    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )

    case = next(item for item in dual_stack_cases() if item["id"]=="dual-stack-signed-51-1")
    plan = plan_from_saved(case["parameters"])
    plan.charts[0].source_path = "chart.png"
    source = ChartInputFile("input.json", json.dumps(case["documents"][0]).encode())
    inputs = ChartInputMaterialization(files=(source,), entries=({"chartId": plan.charts[0].chart_id, "path": source.path, "sha256": source.sha256},))
    figure = render(plan, inputs)
    for axis in figure.axes:
        box = axis.get_legend().get_window_extent(figure.canvas.get_renderer())
        assert box.x0>=0 and box.y0>=0 and box.x1<=figure.bbox.width and box.y1<=figure.bbox.height


@pytest.mark.parametrize("fault", ["total", "percent", "tiny", "overflow", "period"])
def test_dual_stack_rejects_false_additivity_or_unrepresentable_stack(fault):
    import json

    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )

    plan, original = dual_plan("stacked-total", total=True)
    doc = json.loads(original.files[0].content)
    if fault == "total":
        doc["rows"][0][-1] += 1
    elif fault == "percent":
        doc["columnMeta"]["actual"] = {"unit": "%", "isPercent": True}
        doc["columnMeta"]["budget"] = {"unit": "%", "isPercent": True}
        plan.charts[0].standard_axes = StandardChartAxes(mode="dual", rightFields=["ratio"])
        plan.charts[0].standard_total_field = None
        plan.charts[0].standard_value_fields = ("actual", "budget", "ratio")
    elif fault == "tiny":
        doc["rows"][0][1:3] = [1e24, 1]
    elif fault == "overflow":
        doc["rows"][0][1:3] = [1e308, 1e308]
    else:
        doc["columnMeta"]["actual"]["periods"] = ["2026-10"]
    source = ChartInputFile("input.json", json.dumps(doc).encode())
    inputs = ChartInputMaterialization(files=(source,), entries=({"chartId": "chart", "path": source.path, "sha256": source.sha256},))
    result = standard_visualization_preflight(plan, inputs)
    assert result.source is None


def test_dual_stack_passes_formal_source_gate_and_rejects_input_tampering(tmp_path, monkeypatch):
    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
    from smart_reporting.reporting.code_agent.toolkit import validate_script_source

    plan, inputs = dual_plan("stacked-total", total=True)
    source = standard_visualization_preflight(plan, inputs).source
    assert source
    context = ReportingCodingTaskContext(task_id="test", task_kind="visualization", code_mode_session_id="test",
        workspace_key="test", workspace_root=tmp_path, script_path="chart.py", authorized_read_paths=("input.json",),
        authorized_write_paths=("chart.py", "chart.png"), declared_output_paths=("chart.png",), max_source_bytes=128*1024)
    validate_script_source(context, source)
    monkeypatch.chdir(tmp_path)
    (tmp_path/"input.json").write_text("{}")
    with pytest.raises(ValueError, match="identity changed"):
        exec(source, {})


def test_dual_stack_real_plan_roundtrip_materializes_all_component_right_and_total_fields(render):  # noqa: F811
    import json

    from smart_reporting.reporting.workflow.runtime.chart_inputs import materialize_chart_inputs
    from smart_reporting.reporting.workflow.runtime.phase_models import (
        ChartDraft,
        VisualizationPlanDraft,
    )

    base, original = dual_plan("stacked-total", total=True)
    document = json.loads(original.files[0].content)
    chart = ChartDraft(chartId="chart", sourcePath="chart.png", title="冻结堆叠双轴", altText="左右独立单位",
        citationIds=["citation"], metricCodes=["metric"], currentPeriod="2026-10", sourceDatasetId="dataset",
        aggregationGrain="month", visualForm="stacked-total", standardValueFields=base.charts[0].standard_value_fields,
        standardAxes=base.charts[0].standard_axes, standardTotalField="total",
        dataBindings=[{"analysisId": "a", "factPath": "facts.json", "dataPath": "findings[0].rows", "fields": document["columns"], "role": "堆叠双轴"}])
    plan = VisualizationPlanDraft.model_validate_json(VisualizationPlanDraft(charts=(chart,)).model_dump_json(by_alias=True))
    facts = [{"analysisId": "a", "factFile": {"path": "facts.json", "sha256": "f"*64},
        "dataDescriptors": [{"dataPath": "findings[0].rows", "fields": document["columns"]}]}]
    inputs = materialize_chart_inputs(plan, facts, {"facts.json": {"findings": [document]}}, output_root=".")
    figure = render(plan, inputs)
    assert list(figure.axes[0].lines[0].get_ydata()) == [3, 7]
    assert list(figure.axes[1].lines[0].get_ydata()) == [20, 40]


def test_dual_stack_summary_and_native_can_share_batch_without_axis_or_style_leak(render, tmp_path):  # noqa: F811
    import copy
    from types import SimpleNamespace
    from unittest.mock import patch

    from matplotlib.figure import Figure

    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
    from smart_reporting.reporting.code_agent.toolkit import validate_script_source
    from smart_reporting.reporting.tests.test_standard_chart_box_summary import summary_plan
    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )

    native = build({"columns": ["label", "actual"], "rows": [["一月", 10], ["二月", 20]],
        "columnMeta": {"actual": {"unit": "元"}}}, form="line")
    charts, files, entries = [], [], []
    for index, (plan, inputs) in enumerate([dual_plan("stacked-total", total=True), summary_plan(), native]):
        chart = copy.deepcopy(plan.charts[0])
        chart.chart_id = f"chart-{index}"
        chart.source_path = "chart.png" if index==2 else f"chart-{index}.png"
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
        workspace_key="test", workspace_root=tmp_path, script_path="chart.py", authorized_read_paths=tuple(file.path for file in files),
        authorized_write_paths=("chart.py", *(chart.source_path for chart in charts)),
        declared_output_paths=tuple(chart.source_path for chart in charts), max_source_bytes=128*1024)
    validate_script_source(context, source)
    saved, original_save = [], Figure.savefig

    def capture(figure, *args, **kwargs):
        saved.append(figure)
        return original_save(figure, *args, **kwargs)

    with patch.object(Figure, "savefig", capture):
        render(plan, inputs)
    assert [len(figure.axes) for figure in saved] == [2, 1, 1]
    assert list(saved[0].axes[0].lines[0].get_ydata()) == [3, 7]
    assert list(saved[0].axes[1].lines[0].get_ydata()) == [20, 40]
    assert list(saved[2].axes[0].lines[0].get_ydata()) == [10, 20]


@pytest.mark.parametrize("fault", ["values", "starts", "centers", "colors", "right_values", "total", "left_domain", "right_domain"])
def test_independent_dual_stack_oracle_detects_wrong_geometry_total_units_and_ranges(tmp_path, fault):
    import copy

    from scripts.replay_standard_visualization_variants import run_case
    from scripts.standard_visualization_dual_stack_cases import dual_stack_cases

    case = copy.deepcopy(next(item for item in dual_stack_cases() if item["id"]=="dual-stack-total-3-1"))
    if fault == "colors":
        case["assertions"]["series"][0]["colors"][0] = "#ffffff"
    elif fault == "right_values":
        case["assertions"]["series"][2]["values"][0] += 1
    elif fault == "total":
        case["assertions"]["series"][3]["values"][0] += 1
    elif fault in {"left_domain", "right_domain"}:
        case["assertions"]["domains"][int(fault=="right_domain")]["limits"][1] += 1
    else:
        case["assertions"]["series"][0][fault][0] += 1
    result = run_case(case, tmp_path)
    assert result["status"] == "semantic_mismatch" and result["audit"]["semanticMismatches"]
