import json

import pytest

from smart_reporting.reporting.tests.test_standard_chart_presentation import (  # noqa: F401
    build,
    render,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    StandardChartAxes,
    StandardChartDistribution,
    StandardChartPresentation,
    StandardChartStyle,
    StandardChartWaterfall,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def waterfall_plan(rows=None, **options):
    document = {
        "columns": ["label", "value"],
        "rows": rows
        or [
            ["期初", 100],
            ["增加", 30],
            ["减少", -50],
            ["小计", 80],
            ["调整", -100],
            ["期末", -20],
        ],
        "columnMeta": {"value": {"unit": "元"}},
    }
    plan, inputs = build(document, form="waterfall", selected=("value",))
    plan.charts[0].standard_waterfall = StandardChartWaterfall(
        valueField="value", absoluteLabels=["期初", "小计", "期末"], **options
    )
    return plan, inputs


def distribution_plan(rows=None, **options):
    document = {
        "columns": ["group", "value"],
        "rows": rows or [["甲", value] for value in [1, 2, 3, 4, 100]] + [["乙", 10], ["乙", 10]],
        "columnMeta": {"value": {"unit": "元"}},
    }
    plan, inputs = build(document, form="boxplot", selected=("value",))
    plan.charts[0].standard_distribution = StandardChartDistribution(
        groupField="group", valueField="value", **options
    )
    return plan, inputs


def test_waterfall_keeps_signed_contributions_checkpoints_and_negative_final(render):  # noqa: F811
    plan, inputs = waterfall_plan()
    figure = render(plan, inputs)
    bars = figure.axes[0].containers[0]
    assert [bar.get_y() for bar in bars] == [0, 100, 130, 0, 80, 0]
    assert [bar.get_height() for bar in bars] == [100, 30, -50, 80, -100, -20]
    assert [
        line.get_ydata().tolist()
        for line in figure.axes[0].lines
        if getattr(line, "_standard_connector", False)
    ] == [[100, 100], [130, 130], [80, 80], [80, 80], [-20, -20]]
    assert any(
        "变动 -50.00元" in text.get_text() and text.xy == (2, 80) for text in figure.axes[0].texts
    )


def test_waterfall_role_colors_and_frozen_point_override_survive_theme(render):  # noqa: F811
    from matplotlib.colors import to_hex

    plan, inputs = waterfall_plan(increaseColor="#00aa00")
    plan.charts[0].standard_style = StandardChartStyle(
        points=[{"series": "value", "label": "减少", "color": "#222222"}]
    )
    figure = render(plan, inputs)
    assert [to_hex(bar.get_facecolor()) for bar in figure.axes[0].containers[0]][:3] == [
        "#3066a3",
        "#00aa00",
        "#222222",
    ]


@pytest.mark.parametrize(
    "fault,code",
    [
        ("mismatch", "standard_waterfall_total_mismatch"),
        ("tiny", "standard_waterfall_increment_unrepresentable"),
        ("missing", "standard_encoding_values_invalid"),
        ("role", "standard_waterfall_roles_invalid"),
        ("sort", "standard_statistics_order_unsupported"),
        ("percent", "standard_waterfall_semantics_unsupported"),
        ("log", "standard_waterfall_semantics_unsupported"),
    ],
)
def test_waterfall_rejects_broken_or_ambiguous_contribution_chains(fault, code):
    rows = [["期初", 100], ["增加", 30], ["小计", 130], ["期末", 130]]
    if fault == "mismatch":
        rows[-1][1] = 129
    if fault == "tiny":
        rows = [["期初", 1e20], ["增加", 1], ["小计", 1e20], ["期末", 1e20]]
    if fault == "missing":
        rows[1][1] = None
    plan, inputs = waterfall_plan(rows)
    chart = plan.charts[0]
    if fault == "role":
        chart.standard_waterfall = chart.standard_waterfall.model_copy(
            update={"absolute_labels": ("小计", "期末")}
        )
    if fault == "sort":
        chart.standard_presentation = StandardChartPresentation(order={"mode": "reverse"})
    if fault == "log":
        chart.standard_axes = StandardChartAxes(scale="log")
    if fault == "percent":
        from smart_reporting.reporting.workflow.runtime.chart_inputs import (
            ChartInputFile,
            ChartInputMaterialization,
        )

        doc = json.loads(inputs.files[0].content)
        doc["columnMeta"]["value"] = {"unit": "%", "isPercent": True}
        source = ChartInputFile("input.json", json.dumps(doc).encode())
        inputs = ChartInputMaterialization(
            files=(source,),
            entries=({"chartId": "chart", "path": source.path, "sha256": source.sha256},),
        )
    assert standard_visualization_preflight(plan, inputs).diagnostic["code"] == code


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_boxplot_uses_actual_linear_quartiles_whiskers_outliers_and_group_order(
    render, orientation  # noqa: F811
):  # noqa: F811
    plan, inputs = distribution_plan(orientation=orientation, groupLabels=["乙", "甲"])
    figure = render(plan, inputs)
    axis = figure.axes[0]
    lines = {getattr(line, "_standard_box_part", None): line for line in axis.lines}
    def values(line):
        return list(line.get_xdata() if orientation == "horizontal" else line.get_ydata())
    assert values(lines["甲", "medians"]) == [3, 3]
    assert values(lines["甲", "fliers"]) == [100]
    whiskers = [
        line
        for line in axis.lines
        if getattr(line, "_standard_box_part", None) == ("甲", "whiskers")
    ]
    assert [values(line) for line in whiskers] == [[2, 1], [4, 4]]
    ticks = axis.get_yticklabels() if orientation == "horizontal" else axis.get_xticklabels()
    assert [tick.get_text() for tick in ticks] == ["乙 (n=2)", "甲 (n=5)"]
    assert any("中位数 3.00元" in text.get_text() for text in axis.texts)


def test_boxplot_hidden_fliers_keep_all_samples_and_explicit_note(render):  # noqa: F811
    plan, inputs = distribution_plan(showFliers=False)
    figure = render(plan, inputs)
    assert not any(
        getattr(line, "_standard_box_part", ("", ""))[1] == "fliers"
        for line in figure.axes[0].lines
    )
    assert any("异常点已按参数隐藏" in text.get_text() for text in figure.texts)
    assert any("n=5" in tick.get_text() for tick in figure.axes[0].get_xticklabels())


def test_boxplot_missing_values_require_explicit_policy_and_keep_valid_sample_counts(render):  # noqa: F811
    plan, inputs = distribution_plan([["甲", 1], ["甲", None], ["甲", 3], ["乙", 2]])
    assert standard_visualization_preflight(plan, inputs).source is None
    plan.charts[0].standard_axes = StandardChartAxes(allowNulls=True)
    figure = render(plan, inputs)
    assert figure.axes[0].get_xticklabels()[0].get_text() == "甲 (n=2)"
    assert any("缺失的样本值1项" in text.get_text() for text in figure.texts)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("empty", "standard_distribution_empty_group"),
        ("logzero", "standard_distribution_log_domain_invalid"),
        ("order", "standard_distribution_order_invalid"),
        ("sort", "standard_statistics_order_unsupported"),
        ("overflow", "standard_distribution_statistics_overflow"),
    ],
)
def test_boxplot_rejects_invented_or_unrepresentable_samples(fault, code):
    rows = [["甲", 1], ["甲", 3], ["乙", 2]]
    if fault == "empty":
        rows[-1][1] = None
    if fault == "logzero":
        rows[0][1] = 0
    if fault == "overflow":
        rows = [["甲", -1.7e308], ["甲", 1.7e308]]
    plan, inputs = distribution_plan(rows)
    chart = plan.charts[0]
    chart.standard_axes = StandardChartAxes(
        allowNulls=True, scale="log" if fault == "logzero" else "linear"
    )
    if fault == "order":
        chart.standard_distribution = chart.standard_distribution.model_copy(
            update={"group_labels": ("甲",)}
        )
    if fault == "sort":
        chart.standard_presentation = StandardChartPresentation(order={"mode": "reverse"})
    assert standard_visualization_preflight(plan, inputs).diagnostic["code"] == code


@pytest.mark.parametrize("form", ["waterfall", "boxplot"])
def test_new_statistics_keep_input_identity_and_formal_source_gate(tmp_path, monkeypatch, form):
    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
    from smart_reporting.reporting.code_agent.toolkit import validate_script_source

    plan, inputs = waterfall_plan() if form == "waterfall" else distribution_plan()
    script = standard_visualization_preflight(plan, inputs).source
    assert script
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
    validate_script_source(context, script)
    (tmp_path / "input.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="identity changed"):
        exec(script, {})


@pytest.mark.parametrize(
    "fault", ["levels", "positions", "colors", "connectors", "quartiles", "fliers", "box_color"]
)
def test_independent_statistics_auditor_detects_wrong_expected_geometry(tmp_path, fault):
    import copy

    from scripts.replay_standard_visualization_variants import run_case
    from scripts.standard_visualization_statistics_cases import statistics_cases

    waterfall = fault in {"levels", "positions", "colors", "connectors"}
    identity = "statistics-waterfall-3-1-True" if waterfall else "statistics-boxplot-3-1-vertical"
    case = copy.deepcopy(next(item for item in statistics_cases() if item["id"] == identity))
    if waterfall:
        expected = case["assertions"]["waterfalls"][0]
        if fault == "levels":
            expected["starts"][1] += 1
        elif fault == "positions":
            expected["positions"][1] += 1
        elif fault == "colors":
            expected["colors"][1] = "#000000"
        else:
            expected["connectors"][0] += 1
    else:
        expected = next(item for item in case["assertions"]["boxes"] if item["name"] == "甲")
        if fault == "quartiles":
            expected["statistics"][1] += 1
        elif fault == "fliers":
            expected["fliers"][0] += 1
        else:
            expected["color"] = "#000000"
    record = run_case(case, tmp_path)
    assert record["status"] == "semantic_mismatch"
    assert record["audit"]["semanticMismatches"]


@pytest.mark.parametrize("form", ["waterfall", "boxplot"])
def test_statistics_real_plan_and_field_materialization(render, form):  # noqa: F811
    from smart_reporting.reporting.workflow.runtime.chart_inputs import materialize_chart_inputs
    from smart_reporting.reporting.workflow.runtime.phase_models import (
        ChartDraft,
        VisualizationPlanDraft,
    )

    base, original = waterfall_plan() if form == "waterfall" else distribution_plan()
    document = json.loads(original.files[0].content)
    chart = ChartDraft(
        chartId="chart",
        sourcePath="chart.png",
        title="冻结输入统计图",
        altText="原始样本或贡献链",
        citationIds=["citation"],
        metricCodes=["metric"],
        currentPeriod="2026-10",
        sourceDatasetId="dataset",
        aggregationGrain="group",
        visualForm=form,
        standardValueFields=["value"],
        standardWaterfall=base.charts[0].standard_waterfall if form == "waterfall" else None,
        standardDistribution=base.charts[0].standard_distribution if form == "boxplot" else None,
        dataBindings=[
            {
                "analysisId": "a",
                "factPath": "facts.json",
                "dataPath": "findings[0].rows",
                "fields": document["columns"],
                "role": "统计图",
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
    assert not inputs.fallback_chart_ids
    figure = render(plan, inputs)
    if form == "waterfall":
        assert [bar.get_height() for bar in figure.axes[0].containers[0]] == [
            100,
            30,
            -50,
            80,
            -100,
            -20,
        ]
    else:
        assert any(
            getattr(line, "_standard_box_part", None) == ("甲", "medians")
            and list(line.get_ydata()) == [3, 3]
            for line in figure.axes[0].lines
        )


def test_boxplot_percentage_scale_and_single_sample_are_preserved(render):  # noqa: F811
    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )

    plan, inputs = distribution_plan([["甲", 0.2], ["甲", 0.4], ["乙", 0.7]])
    document = json.loads(inputs.files[0].content)
    document["columnMeta"]["value"] = {"unit": "%", "isPercent": False}
    source = ChartInputFile("input.json", json.dumps(document).encode())
    inputs = ChartInputMaterialization(
        files=(source,),
        entries=({"chartId": "chart", "path": source.path, "sha256": source.sha256},),
    )
    figure = render(plan, inputs)
    medians = {
        line._standard_box_part[0]: list(line.get_ydata())
        for line in figure.axes[0].lines
        if getattr(line, "_standard_box_part", ("", ""))[1] == "medians"
    }
    assert medians == {"甲": [30, 30], "乙": [70, 70]}
    assert figure.axes[0].get_ylabel() == "%"


def test_mixed_legacy_and_statistics_batch_keeps_each_chart_input_and_output(render):  # noqa: F811
    import copy
    from types import SimpleNamespace

    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )

    first = waterfall_plan()
    second = build(
        {
            "columns": ["label", "actual"],
            "rows": [["一月", 10], ["二月", 20]],
            "columnMeta": {"actual": {"unit": "元"}},
        },
        form="line",
    )
    third = distribution_plan()
    charts, files, entries = [], [], []
    for index, (plan, inputs) in enumerate([first, second, third]):
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
    from pathlib import Path

    assert all(Path(chart.source_path).read_bytes().startswith(b"\x89PNG") for chart in charts)
