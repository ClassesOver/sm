import pytest
from pydantic import ValidationError

from smart_reporting.reporting.tests.test_standard_chart_presentation import (  # noqa: F401
    build,
    render,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    StandardChartAxes,
    StandardChartDomains,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def plan_for(form="line", rows=None, **axes):
    document = {
        "columns": ["label", "actual", "budget"],
        "rows": rows or [["一月", 10, 20], ["二月", 30, 40]],
        "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "元"}},
    }
    plan, inputs = build(document, form=form, selected=("actual", "budget"))
    plan.charts[0].standard_axes = StandardChartAxes(**axes)
    plan.charts[0].standard_annotations = ()
    return plan, inputs


def attach(plan, **domains):
    plan.charts[0].standard_domains = StandardChartDomains.model_validate(domains)


def test_explicit_range_ticks_and_number_format_keep_frozen_line_values(render):  # noqa: F811
    plan, inputs = plan_for()
    attach(
        plan,
        left={"min": 0, "max": 50, "ticks": [0, 25, 50], "tickFormat": "number", "decimals": 1},
    )
    figure = render(plan, inputs)
    assert figure.axes[0].get_ylim() == (0, 50)
    assert list(figure.axes[0].get_yticks()) == [0, 25, 50]
    assert [tick.get_text() for tick in figure.axes[0].get_yticklabels()] == ["0.0", "25.0", "50.0"]
    assert list(figure.axes[0].lines[0].get_ydata()) == [10, 30]


def test_horizontal_bar_uses_numeric_x_domain_and_keeps_category_axis(render):  # noqa: F811
    plan, inputs = plan_for("barh")
    attach(plan, left={"min": 0, "max": 50, "ticks": [0, 10, 50]})
    figure = render(plan, inputs)
    assert figure.axes[0].get_xlim() == (0, 50)
    assert [tick.get_text() for tick in figure.axes[0].get_yticklabels()] == ["一月", "二月"]


def test_dual_domains_use_each_registered_display_unit_independently(render):  # noqa: F811
    source = {
        "columns": ["label", "actual", "ratio"],
        "rows": [["一月", 1e8, 0.2], ["二月", 2e8, 0.4]],
        "columnMeta": {"actual": {"unit": "元"}, "ratio": {"unit": "%", "isPercent": False}},
    }
    plan, inputs = build(source, form="line", selected=("actual", "ratio"))
    plan.charts[0].standard_axes = StandardChartAxes(
        mode="dual", rightFields=["ratio"], leftDisplayUnit="亿元"
    )
    plan.charts[0].standard_annotations = ()
    attach(
        plan,
        left={"min": 0, "max": 3, "ticks": [0, 1, 2, 3]},
        right={"min": 0, "max": 100, "ticks": [0, 50, 100]},
    )
    figure = render(plan, inputs)
    assert figure.axes[0].get_ylim() == (0, 3) and figure.axes[1].get_ylim() == (0, 100)
    assert list(figure.axes[0].lines[0].get_ydata()) == [1, 2]
    assert list(figure.axes[1].lines[0].get_ydata()) == [20, 40]


def test_panels_override_by_frozen_series_name(render):  # noqa: F811
    plan, inputs = plan_for(mode="panels")
    attach(
        plan,
        left={"min": 0, "max": 50},
        panels=[{"series": "actual", "domain": {"min": 0, "max": 35}}],
    )
    figure = render(plan, inputs)
    assert [axis.get_ylim() for axis in figure.axes] == [(0, 35), (0, 50)]


def test_zoom_domain_checks_only_visible_window_and_keeps_main_graph(render):  # noqa: F811
    plan, inputs = plan_for(
        rows=[["一月", 1000, 2000], ["二月", 10, 20], ["三月", 20, 30]],
        mode="zoom",
        zoomStart="二月",
        zoomEnd="三月",
    )
    attach(plan, left={"min": 0, "max": 2100}, zoom={"min": 0, "max": 40, "ticks": [0, 20, 40]})
    figure = render(plan, inputs)
    assert figure.axes[0].get_ylim() == (0, 2100)
    assert figure.axes[0].child_axes[0].get_ylim() == (0, 40)


@pytest.mark.parametrize("form", ["bar", "stacked-bar", "stacked-area", "stacked-total"])
def test_domain_validation_covers_bar_baseline_and_cumulative_stack(form):
    plan, inputs = plan_for(form)
    attach(plan, left={"min": 1 if form == "bar" else 0, "max": 50})
    result = standard_visualization_preflight(plan, inputs)
    assert result.source is None and result.diagnostic["code"] == "standard_domain_clips_data"


def test_frozen_band_edges_must_fit_domain_even_if_center_line_fits():
    from smart_reporting.reporting.tests.test_standard_chart_encoding import band_plan

    plan, inputs = band_plan()
    attach(plan, left={"min": 0, "max": 2e8})
    assert (
        standard_visualization_preflight(plan, inputs).diagnostic["code"]
        == "standard_domain_clips_data"
    )


def test_annotated_clipping_retains_data_and_hides_only_outside_value_labels(render):  # noqa: F811
    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartAnnotation

    plan, inputs = plan_for()
    plan.charts[0].standard_annotations = (StandardChartAnnotation(kind="values", series="actual"),)
    attach(plan, left={"min": 0, "max": 25, "outOfRange": "annotate"})
    figure = render(plan, inputs)
    assert list(figure.axes[0].lines[0].get_ydata()) == [10, 30]
    assert figure.axes[0].get_ylim() == (0, 25)
    assert [text.get_visible() for text in figure.axes[0].texts] == [True, False]
    assert any(
        "高于2" in text.get_text() and "原值未改" in text.get_text() for text in figure.texts
    )


def test_scatter_domains_do_not_modify_numeric_coordinates_or_continuous_colors(render):  # noqa: F811
    from smart_reporting.reporting.tests.test_standard_chart_encoding import point_plan

    plan, inputs = point_plan(colorField="color", xDisplayUnit="万人次")
    attach(plan, x={"min": 0, "max": 4, "ticks": [0, 2, 4]}, left={"min": 0, "max": 40})
    figure = render(plan, inputs)
    assert figure.axes[0].get_xlim() == (0, 4) and figure.axes[0].get_ylim() == (0, 40)
    assert figure.axes[0].collections[0].get_offsets().tolist() == [[1, 10], [2, 20], [3, 30]]
    assert list(figure.axes[1].get_ylim()) == [20, 80]


def test_joint_scatter_window_must_contain_real_observations():
    from smart_reporting.reporting.tests.test_standard_chart_encoding import point_plan

    plan, inputs = point_plan()
    attach(
        plan,
        x={"min": 5000, "max": 15000, "outOfRange": "annotate"},
        left={"min": 15, "max": 35, "outOfRange": "annotate"},
    )
    assert (
        standard_visualization_preflight(plan, inputs).diagnostic["code"]
        == "standard_domain_empty_view"
    )


@pytest.mark.parametrize("form", ["waterfall", "boxplot"])
def test_statistical_charts_keep_data_with_explicit_domains(render, form):  # noqa: F811
    from smart_reporting.reporting.tests.test_standard_chart_statistics import (
        distribution_plan,
        waterfall_plan,
    )

    plan, inputs = (
        waterfall_plan() if form == "waterfall" else distribution_plan(orientation="horizontal")
    )
    attach(
        plan,
        left={
            "min": -30 if form == "waterfall" else 0,
            "max": 150,
            "ticks": [-30, 0, 150] if form == "waterfall" else [0, 50, 150],
        },
    )
    figure = render(plan, inputs)
    assert (figure.axes[0].get_ylim() if form == "waterfall" else figure.axes[0].get_xlim()) == (
        -30 if form == "waterfall" else 0,
        150,
    )


@pytest.mark.parametrize(
    "domain",
    [
        {"min": 3, "max": 1},
        {"ticks": [1, 1]},
        {"ticks": [2, 1]},
        {"min": 0, "max": 1, "ticks": [2]},
        {"min": True},
        {"max": float("inf")},
        {},
    ],
)
def test_invalid_domain_schema_never_reaches_rendering(domain):
    with pytest.raises(ValidationError):
        StandardChartDomains(left=domain)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("right", "standard_domain_target_invalid"),
        ("x", "standard_domain_target_invalid"),
        ("zoom", "standard_domain_target_invalid"),
        ("panel", "standard_domain_target_invalid"),
        ("zero", "standard_domain_zero_conflict"),
        ("log", "standard_domain_log_invalid"),
        ("empty", "standard_domain_empty_view"),
    ],
)
def test_domain_target_and_scale_failures_are_actionable(fault, code):
    plan, inputs = plan_for(
        scale="log" if fault == "log" else "linear", zeroBaseline=fault == "zero"
    )
    if fault in {"right", "x", "zoom"}:
        attach(plan, **{fault: {"min": 0, "max": 50}})
    elif fault == "panel":
        attach(plan, panels=[{"series": "actual", "domain": {"min": 0, "max": 50}}])
    else:
        attach(
            plan,
            left={
                "min": 1 if fault == "zero" else 60 if fault == "empty" else 0,
                "max": 100,
                "outOfRange": "annotate",
            },
        )
    assert standard_visualization_preflight(plan, inputs).diagnostic["code"] == code


def test_one_sided_domain_and_ticks_only_preserve_auto_other_limit(render):  # noqa: F811
    plan, inputs = plan_for()
    attach(plan, left={"min": 0, "ticks": [0, 20, 40, 60]})
    figure = render(plan, inputs)
    assert figure.axes[0].get_ylim() == (0, 60)


def test_dense_numeric_ticks_trigger_measured_layout_repair(render):  # noqa: F811
    from smart_reporting.reporting.tests.test_standard_chart_encoding import point_plan

    plan, inputs = point_plan()
    attach(
        plan,
        x={
            "min": 9999,
            "max": 30001,
            "ticks": [10000 + i * 0.00001 for i in range(16)],
            "tickFormat": "number",
            "decimals": 6,
        },
    )
    with pytest.raises(ValueError, match="standard_chart_layout_unresolved"):
        render(plan, inputs)


def test_format_only_domain_preserves_configured_automatic_margin(render):  # noqa: F811
    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartStyle

    plan, inputs = plan_for()
    plan.charts[0].standard_style = StandardChartStyle(valueMargin=0.4)
    automatic = render(plan, inputs).axes[0].get_ylim()
    attach(plan, left={"tickFormat": "scientific", "decimals": 3})
    assert render(plan, inputs).axes[0].get_ylim() == automatic


@pytest.mark.parametrize("form,below,above", [("bar", 4, 0), ("stacked-bar", 4, 1)])
def test_clipping_notice_counts_drawn_bar_endpoints_and_actual_stack_positions(
    render, form, below, above  # noqa: F811
):  # noqa: F811
    plan, inputs = plan_for(form)
    attach(
        plan,
        left={
            "min": 5 if form == "bar" else 15,
            "max": 50 if form == "bar" else 65,
            "outOfRange": "annotate",
        },
    )
    figure = render(plan, inputs)
    assert any(f"低于{below}、高于{above}" in text.get_text() for text in figure.texts)


@pytest.mark.parametrize("fault", ["limits", "ticks", "format", "original_values"])
def test_independent_domain_auditor_catches_wrong_viewport_or_changed_data(tmp_path, fault):
    import copy

    from scripts.replay_standard_visualization_variants import run_case
    from scripts.standard_visualization_domain_cases import domain_cases

    case = copy.deepcopy(
        next(item for item in domain_cases() if item["id"] == "domains-single-3-1")
    )
    oracle = case["assertions"]["domains"][0]
    if fault == "limits":
        oracle["limits"][1] += 1
    elif fault == "ticks":
        oracle["ticks"][1] += 1
    elif fault == "format":
        oracle["tickLabels"][1] = "错误刻度"
    else:
        case["assertions"]["series"][0]["values"][0] += 1
    result = run_case(case, tmp_path)
    assert result["status"] == "semantic_mismatch" and result["audit"]["semanticMismatches"]


@pytest.mark.parametrize("form", ["line", "scatter", "boxplot"])
def test_domains_pass_formal_source_gate_with_statistics_and_encoding(tmp_path, monkeypatch, form):
    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
    from smart_reporting.reporting.code_agent.toolkit import validate_script_source

    if form == "scatter":
        from smart_reporting.reporting.tests.test_standard_chart_encoding import point_plan

        plan, inputs = point_plan()
    elif form == "boxplot":
        from smart_reporting.reporting.tests.test_standard_chart_statistics import distribution_plan

        plan, inputs = distribution_plan()
    else:
        plan, inputs = plan_for()
    attach(plan, left={"min": 0, "max": 150})
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


def test_domain_parameters_round_trip_through_real_plan_and_bound_input(render):  # noqa: F811
    from smart_reporting.reporting.workflow.runtime.chart_inputs import materialize_chart_inputs
    from smart_reporting.reporting.workflow.runtime.phase_models import (
        ChartDraft,
        VisualizationPlanDraft,
    )

    document = {
        "columns": ["label", "value"],
        "rows": [["一月", 1e8], ["二月", 2e8]],
        "columnMeta": {"value": {"unit": "元"}},
    }
    chart = ChartDraft(
        chartId="chart",
        sourcePath="chart.png",
        title="冻结输入轴域",
        altText="按显示单位设置轴域",
        citationIds=["citation"],
        metricCodes=["metric"],
        currentPeriod="2026-10",
        sourceDatasetId="dataset",
        aggregationGrain="month",
        visualForm="line",
        standardValueFields=["value"],
        standardDisplayUnit="亿元",
        standardDomains={"left": {"min": 0, "max": 3, "ticks": [0, 1, 2, 3]}},
        dataBindings=[
            {
                "analysisId": "a",
                "factPath": "facts.json",
                "dataPath": "findings[0].rows",
                "fields": document["columns"],
                "role": "数值轴",
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
    assert figure.axes[0].get_ylim() == (0, 3)
    assert list(figure.axes[0].lines[0].get_ydata()) == [1, 2]
