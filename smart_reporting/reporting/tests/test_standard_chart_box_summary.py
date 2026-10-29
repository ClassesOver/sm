import copy
import json

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.tests.test_standard_chart_presentation import (  # noqa: F401
    build,
    render,
)
from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    StandardChartAxes,
    StandardChartBoxSummary,
    StandardChartDomains,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def summary_table():
    return {
        "columns": ["group", "q1", "median", "q3", "low", "high", "n"],
        "rows": [["东院", 10, 20, 30, 5, 40, 100], ["西院", 100, 200, 300, 50, 400, 80]],
        "columnMeta": {
            **{
                name: {"unit": "元", "periods": ["2026-10"]}
                for name in ["q1", "median", "q3", "low", "high"]
            },
            "n": {"unit": "个", "periods": ["2026-10"]},
        },
    }


def outlier_table():
    return {
        "columns": ["group", "value"],
        "rows": [["东院", 1], ["西院", 500], ["东院", 1]],
        "columnMeta": {"value": {"unit": "元", "periods": ["2026-10"]}},
    }


def summary_plan(document=None, outliers=None, with_outliers=True, with_count=True, **options):
    document = summary_table() if document is None else document
    plan, original = build(document, form="boxplot", selected=("median",))
    chart = plan.charts[0]
    chart.standard_annotations = ()
    chart.standard_box_summary = StandardChartBoxSummary(
        groupField="group",
        q1Field="q1",
        medianField="median",
        q3Field="q3",
        lowerWhiskerField="low",
        upperWhiskerField="high",
        countField="n" if with_count else None,
        outlierSource={"sourceIndex": 1, "groupField": "group", "valueField": "value"}
        if with_outliers
        else None,
        **options,
    )
    if not with_outliers:
        return plan, original
    source = ChartInputFile(
        "outliers.json",
        json.dumps(outlier_table() if outliers is None else outliers, ensure_ascii=False).encode(),
    )
    inputs = ChartInputMaterialization(
        files=(*original.files, source),
        entries=(
            *original.entries,
            {"chartId": "chart", "path": source.path, "sha256": source.sha256},
        ),
    )
    return plan, inputs


@pytest.mark.parametrize("orientation", ["vertical", "horizontal"])
def test_summary_box_uses_registered_quartiles_whiskers_outliers_and_count(render, orientation):  # noqa: F811
    plan, inputs = summary_plan(orientation=orientation, groupLabels=["西院", "东院"])
    figure = render(plan, inputs)
    axis = figure.axes[0]
    med = next(
        line
        for line in axis.lines
        if getattr(line, "_standard_box_part", None) == ("东院", "medians")
    )
    assert list(med.get_xdata() if orientation == "horizontal" else med.get_ydata()) == [20, 20]
    fliers = next(
        line
        for line in axis.lines
        if getattr(line, "_standard_box_part", None) == ("东院", "fliers")
    )
    assert list(fliers.get_xdata() if orientation == "horizontal" else fliers.get_ydata()) == [1, 1]
    box = next(
        patch for patch in axis.patches if getattr(patch, "_standard_box_group", None) == "东院"
    )
    coordinates = box.get_path().vertices[:, 0 if orientation == "horizontal" else 1]
    assert min(coordinates) == 10 and max(coordinates) == 30
    ticks = axis.get_yticklabels() if orientation == "horizontal" else axis.get_xticklabels()
    assert [tick.get_text() for tick in ticks] == ["西院 (n=80)", "东院 (n=100)"]
    assert any("未从原始样本重算" in text.get_text() for text in figure.texts)


def test_summary_without_counts_and_outliers_does_not_invent_n_or_absence(render):  # noqa: F811
    plan, inputs = summary_plan(with_count=False, with_outliers=False)
    figure = render(plan, inputs)
    assert [tick.get_text() for tick in figure.axes[0].get_xticklabels()] == [
        "东院 (n未提供)",
        "西院 (n未提供)",
    ]
    assert any(
        "异常点未提供" in text.get_text() and "不能据此判断无异常点" in text.get_text()
        for text in figure.texts
    )


@pytest.mark.parametrize("hidden", [False, True])
def test_hidden_or_empty_registered_outliers_are_disclosed(render, hidden):  # noqa: F811
    extra = outlier_table()
    if not hidden:
        extra["rows"] = []
    plan, inputs = summary_plan(outliers=extra, showFliers=not hidden)
    figure = render(plan, inputs)
    assert any(
        ("已按参数隐藏" if hidden else "绑定异常点记录0项") in text.get_text()
        for text in figure.texts
    )
    if hidden:
        assert not any(
            getattr(line, "_standard_box_part", ("", ""))[1] == "fliers"
            for line in figure.axes[0].lines
        )


def test_summary_converts_each_registered_unit_without_recomputing_quartiles(render):  # noqa: F811
    doc = summary_table()
    for row in doc["rows"]:
        row[1] /= 1e4
        row[5] /= 1e8
    doc["columnMeta"]["q1"]["unit"] = "万元"
    doc["columnMeta"]["high"]["unit"] = "亿元"
    extra = outlier_table()
    for row in extra["rows"]:
        row[1] /= 1e4
    extra["columnMeta"]["value"]["unit"] = "万元"
    plan, inputs = summary_plan(doc, extra)
    plan.charts[0].standard_display_unit = "万元"
    figure = render(plan, inputs)
    med = next(
        line
        for line in figure.axes[0].lines
        if getattr(line, "_standard_box_part", None) == ("西院", "medians")
    )
    assert list(med.get_ydata()) == pytest.approx([0.02, 0.02])
    points = next(
        line
        for line in figure.axes[0].lines
        if getattr(line, "_standard_box_part", None) == ("西院", "fliers")
    )
    assert list(points.get_ydata()) == pytest.approx([0.05])


@pytest.mark.parametrize(
    "fault,code",
    [
        ("ordering", "standard_box_summary_ordering_invalid"),
        ("count_zero", "standard_box_summary_count_invalid"),
        ("count_ratio", "standard_box_summary_count_invalid"),
        ("count_money", "standard_box_summary_count_invalid"),
        ("duplicate", "standard_box_summary_group_invalid"),
        ("period", "standard_box_summary_units_invalid"),
        ("null", "standard_encoding_values_invalid"),
        ("bool", "standard_encoding_values_invalid"),
        ("unknown_group", "standard_box_summary_outlier_invalid"),
        ("inside", "standard_box_summary_outlier_invalid"),
        ("excess_outliers", "standard_box_summary_count_invalid"),
    ],
)
def test_invalid_frozen_summaries_return_actionable_fallback_without_repairing_values(fault, code):
    doc, extra = summary_table(), outlier_table()
    if fault == "ordering":
        doc["rows"][0][1] = 25
    elif fault == "count_zero":
        doc["rows"][0][-1] = 0
    elif fault == "count_ratio":
        doc["rows"][0][-1] = 1.5
    elif fault == "count_money":
        doc["columnMeta"]["n"]["unit"] = "千元"
    elif fault == "duplicate":
        doc["rows"].append(copy.deepcopy(doc["rows"][0]))
    elif fault == "period":
        doc["columnMeta"]["q1"]["periods"] = ["2025-10"]
    elif fault == "null":
        doc["rows"][0][2] = None
    elif fault == "bool":
        doc["rows"][0][3] = True
    elif fault == "unknown_group":
        extra["rows"][0][0] = "不存在"
    elif fault == "inside":
        extra["rows"][0][1] = 15
    else:
        doc["rows"][0][-1] = 1
    plan, inputs = summary_plan(doc, extra)
    result = standard_visualization_preflight(plan, inputs)
    assert result.source is None and result.diagnostic["code"] == code


def test_summary_domains_include_all_whiskers_and_outliers_not_only_median(render):  # noqa: F811
    plan, inputs = summary_plan()
    chart = plan.charts[0]
    chart.standard_domains = StandardChartDomains(left={"min": 0, "max": 250})
    assert (
        standard_visualization_preflight(plan, inputs).diagnostic["code"]
        == "standard_domain_clips_data"
    )
    chart.standard_domains = StandardChartDomains(
        left={"min": 0, "max": 250, "outOfRange": "annotate"}
    )
    figure = render(plan, inputs)
    assert figure.axes[0].get_ylim() == (0, 250)
    points = next(
        line
        for line in figure.axes[0].lines
        if getattr(line, "_standard_box_part", None) == ("西院", "fliers")
    )
    assert list(points.get_ydata()) == [500]
    assert any("高于3" in text.get_text() for text in figure.texts)


@pytest.mark.parametrize("scale", ["log", "symlog"])
def test_summary_supports_log_and_symlog_registered_values(render, scale):  # noqa: F811
    plan, inputs = summary_plan()
    plan.charts[0].standard_axes = StandardChartAxes(scale=scale)
    figure = render(plan, inputs)
    assert figure.axes[0].get_yscale() == scale


@pytest.mark.parametrize("tamper", [0, 1])
def test_summary_source_gate_and_both_file_identities_are_checked_even_if_outliers_hidden(
    tmp_path, monkeypatch, tamper
):
    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
    from smart_reporting.reporting.code_agent.toolkit import validate_script_source

    plan, inputs = summary_plan(showFliers=False)
    source = standard_visualization_preflight(plan, inputs).source
    assert source
    context = ReportingCodingTaskContext(
        task_id="test",
        task_kind="visualization",
        code_mode_session_id="test",
        workspace_key="test",
        workspace_root=tmp_path,
        script_path="chart.py",
        authorized_read_paths=("input.json", "outliers.json"),
        authorized_write_paths=("chart.py", "chart.png"),
        declared_output_paths=("chart.png",),
        max_source_bytes=128 * 1024,
    )
    validate_script_source(context, source)
    monkeypatch.chdir(tmp_path)
    for file in inputs.files:
        (tmp_path / file.path).write_bytes(file.content)
    (tmp_path / inputs.files[tamper].path).write_text("{}")
    with pytest.raises(ValueError, match="identity changed"):
        exec(source, {})


def test_summary_outlier_registration_identity_is_checked_before_compile():
    plan, inputs = summary_plan()
    inputs.entries[1]["sha256"] = "0" * 64
    assert (
        standard_visualization_preflight(plan, inputs).diagnostic["code"]
        == "standard_box_summary_outlier_identity_mismatch"
    )


def test_summary_parameter_fields_cannot_reuse_median_as_a_quartile():
    data = dict(
        groupField="group",
        q1Field="median",
        medianField="median",
        q3Field="q3",
        lowerWhiskerField="low",
        upperWhiskerField="high",
    )
    with pytest.raises(ValidationError):
        StandardChartBoxSummary(**data)


def test_summary_does_not_call_sample_quartile_calculation(render, monkeypatch):  # noqa: F811
    import matplotlib.cbook

    def forbidden(*args, **kwargs):
        raise AssertionError("summary must not recompute quartiles")

    monkeypatch.setattr(matplotlib.cbook, "boxplot_stats", forbidden)
    plan, inputs = summary_plan()
    figure = render(plan, inputs)
    assert any(
        getattr(line, "_standard_box_part", None) == ("东院", "medians")
        for line in figure.axes[0].lines
    )


def test_cross_unit_tie_does_not_fallback_or_snap_supplied_statistics(render):  # noqa: F811
    doc = summary_table()
    doc["columnMeta"]["q1"]["unit"] = "万元"
    doc["rows"] = [["东院", 0.0051, 51, 100, 40, 120, 100], ["西院", 0.01, 200, 300, 50, 400, 80]]
    plan, inputs = summary_plan(doc)
    figure = render(plan, inputs)
    box = next(
        patch
        for patch in figure.axes[0].patches
        if getattr(patch, "_standard_box_group", None) == "东院"
    )
    assert min(box.get_path().vertices[:, 1]) == 0.0051 * 10000
    assert min(box.get_path().vertices[:, 1]) > 51
    assert any(
        "浮点相对容差" in text.get_text() and "原值未改" in text.get_text() for text in figure.texts
    )


def test_summary_normalizes_mixed_percent_scales_per_field_and_outlier(render):  # noqa: F811
    doc, extra = summary_table(), outlier_table()
    for field in ["q1", "median", "q3", "low", "high"]:
        doc["columnMeta"][field].update(unit="%", isPercent=field not in {"q1", "median"})
    for row in doc["rows"]:
        row[1] /= 100
        row[2] /= 100
    extra["columnMeta"]["value"].update(unit="%", isPercent=False)
    for row in extra["rows"]:
        row[1] /= 100
    plan, inputs = summary_plan(doc, extra)
    figure = render(plan, inputs)
    med = next(
        line
        for line in figure.axes[0].lines
        if getattr(line, "_standard_box_part", None) == ("西院", "medians")
    )
    assert list(med.get_ydata()) == [200, 200]
    points = next(
        line
        for line in figure.axes[0].lines
        if getattr(line, "_standard_box_part", None) == ("西院", "fliers")
    )
    assert list(points.get_ydata()) == [500]


def test_degenerate_summary_preserves_supplied_single_observation_count(render):  # noqa: F811
    doc = summary_table()
    doc["rows"] = [["东院", 20, 20, 20, 20, 20, 1]]
    plan, inputs = summary_plan(doc, with_outliers=False)
    figure = render(plan, inputs)
    assert figure.axes[0].get_xticklabels()[0].get_text() == "东院 (n=1)"
    box = figure.axes[0].patches[0].get_path().vertices[:, 1]
    assert min(box) == max(box) == 20


@pytest.mark.parametrize(
    "fault,code",
    [
        ("raw_mode", "standard_box_summary_combination_unsupported"),
        ("sort", "standard_box_summary_combination_unsupported"),
        ("extra_source", "standard_box_summary_sources_invalid"),
        ("log_zero", "standard_box_summary_log_invalid"),
    ],
)
def test_summary_rejects_mixed_input_modes_or_unsupported_scope(fault, code):
    from smart_reporting.reporting.workflow.runtime.phase_models import (
        StandardChartDistribution,
        StandardChartPresentation,
    )

    doc = summary_table()
    if fault == "log_zero":
        doc["rows"][0][4] = 0
    plan, inputs = summary_plan(doc, with_outliers=fault != "log_zero")
    chart = plan.charts[0]
    if fault == "raw_mode":
        chart.standard_distribution = StandardChartDistribution(
            groupField="group", valueField="median"
        )
    elif fault == "sort":
        chart.standard_presentation = StandardChartPresentation(order={"mode": "reverse"})
    elif fault == "extra_source":
        file = ChartInputFile("unused.json", inputs.files[0].content)
        inputs = ChartInputMaterialization(
            files=(*inputs.files, file),
            entries=(
                *inputs.entries,
                {"chartId": "chart", "path": file.path, "sha256": file.sha256},
            ),
        )
    else:
        chart.standard_axes = StandardChartAxes(scale="log")
    assert standard_visualization_preflight(plan, inputs).diagnostic["code"] == code


@pytest.mark.parametrize("known", [False, True])
def test_summary_real_plan_projects_statistics_and_optional_outlier_source(render, known):  # noqa: F811
    from smart_reporting.reporting.workflow.runtime.chart_inputs import materialize_chart_inputs
    from smart_reporting.reporting.workflow.runtime.phase_models import (
        ChartDraft,
        VisualizationPlanDraft,
    )

    base, _ = summary_plan(with_count=known, with_outliers=known)
    docs = [summary_table(), outlier_table()] if known else [summary_table()]
    bindings = [
        {
            "analysisId": "a",
            "factPath": "facts.json",
            "dataPath": f"findings[{i}].rows",
            "fields": doc["columns"],
            "role": "统计汇总" if i == 0 else "异常点记录",
        }
        for i, doc in enumerate(docs)
    ]
    chart = ChartDraft(
        chartId="chart",
        sourcePath="chart.png",
        title="冻结分位数箱线图",
        altText="直接使用已登记统计汇总",
        citationIds=["citation"],
        metricCodes=["metric"],
        currentPeriod="2026-10",
        sourceDatasetId="dataset",
        aggregationGrain="group",
        visualForm="boxplot",
        standardValueFields=["median"],
        standardBoxSummary=base.charts[0].standard_box_summary,
        dataBindings=bindings,
    )
    plan = VisualizationPlanDraft.model_validate_json(
        VisualizationPlanDraft(charts=(chart,)).model_dump_json(by_alias=True)
    )
    facts = [
        {
            "analysisId": "a",
            "factFile": {"path": "facts.json", "sha256": "f" * 64},
            "dataDescriptors": [
                {"dataPath": binding["dataPath"], "fields": binding["fields"]}
                for binding in bindings
            ],
        }
    ]
    inputs = materialize_chart_inputs(
        plan, facts, {"facts.json": {"findings": docs}}, output_root="."
    )
    assert not inputs.fallback_chart_ids
    figure = render(plan, inputs)
    assert figure.axes[0].get_xticklabels()[0].get_text() == (
        "东院 (n=100)" if known else "东院 (n未提供)"
    )


@pytest.mark.parametrize("fault", ["q1", "median", "whisker", "outlier", "count", "color"])
def test_independent_summary_oracle_detects_wrong_source_statistics_and_labels(tmp_path, fault):
    from scripts.replay_standard_visualization_variants import run_case
    from scripts.standard_visualization_box_summary_cases import summary_cases

    case = copy.deepcopy(
        next(item for item in summary_cases() if item["id"] == "summaries-known-vertical-3-1")
    )
    box = case["assertions"]["boxes"][0]
    if fault in {"q1", "median", "whisker"}:
        box["statistics"][{"q1": 0, "median": 1, "whisker": 4}[fault]] += 1
    elif fault == "outlier":
        box["fliers"][0] += 1
    elif fault == "count":
        case["assertions"]["texts"][0] = "不存在的样本量 n=1"
    else:
        box["color"] = "#000000"
    result = run_case(case, tmp_path)
    assert result["status"] == "semantic_mismatch" and result["audit"]["semanticMismatches"]


def test_summary_raw_box_and_waterfall_share_batch_without_reinterpreting_input_modes(render):  # noqa: F811
    from pathlib import Path
    from types import SimpleNamespace

    from smart_reporting.reporting.tests.test_standard_chart_statistics import (
        distribution_plan,
        waterfall_plan,
    )

    summary = summary_plan()
    summary[0].charts[0].standard_domains = StandardChartDomains(left={"min": 0, "max": 600})
    charts, files, entries = [], [], []
    for i, (plan, inputs) in enumerate([distribution_plan(), waterfall_plan(), summary]):
        chart = copy.deepcopy(plan.charts[0])
        chart.chart_id = f"chart-{i}"
        chart.source_path = "chart.png" if i == 2 else f"chart-{i}.png"
        charts.append(chart)
        for j, original in enumerate(inputs.files):
            file = ChartInputFile(f"input-{i}-{j}.json", original.content)
            files.append(file)
            entries.append({"chartId": chart.chart_id, "path": file.path, "sha256": file.sha256})
    figure = render(
        SimpleNamespace(charts=charts),
        ChartInputMaterialization(files=tuple(files), entries=tuple(entries)),
    )
    assert all(Path(chart.source_path).read_bytes().startswith(b"\x89PNG") for chart in charts)
    assert figure.axes[0].get_ylim() == (0, 600)
