from pathlib import Path

import pytest

from smart_reporting.reporting.tests.test_standard_chart_presentation import (  # noqa: F401
    build,
    render,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    StandardChartAnnotation,
    StandardChartAxes,
    StandardChartBand,
    StandardChartEncoding,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def point_table():
    return {
        "columns": ["label", "group", "x", "y", "size", "color"],
        "rows": [
            ["甲", "门诊", 1e4, 10, 100, 0.2],
            ["乙", "住院", 2e4, 20, 200, 0.4],
            ["丙", "门诊", 3e4, 30, 400, 0.8],
        ],
        "columnMeta": {
            "x": {"unit": "人次"},
            "y": {"unit": "元"},
            "size": {"unit": "人次"},
            "color": {"unit": "%", "isPercent": False},
        },
    }


def point_plan(source=None, form="scatter", **encoding):
    plan, inputs = build(source or point_table(), form=form, selected=("y",))
    chart = plan.charts[0]
    chart.standard_label_field = "label"
    chart.standard_annotations = ()
    chart.standard_encoding = StandardChartEncoding(xField="x", yField="y", **encoding)
    return plan, inputs


def test_scatter_uses_numeric_x_and_registered_axis_units(render):  # noqa: F811
    plan, inputs = point_plan(xDisplayUnit="万人次")
    figure = render(plan, inputs)
    assert figure.axes[0].collections[0].get_offsets().tolist() == [[1, 10], [2, 20], [3, 30]]
    assert figure.axes[0].get_xlabel() == "x · 万人次"
    assert figure.axes[0].get_ylabel() == "y · 元"


def test_scatter_groups_and_point_overrides_keep_frozen_identity_after_sort(render):  # noqa: F811
    from matplotlib.colors import to_hex

    from smart_reporting.reporting.workflow.runtime.phase_models import (
        StandardChartPresentation,
        StandardChartStyle,
    )

    plan, inputs = point_plan(groupField="group")
    chart = plan.charts[0]
    chart.standard_presentation = StandardChartPresentation(order={"mode": "reverse"})
    chart.standard_style = StandardChartStyle(
        points=[{"series": "门诊", "label": "甲", "color": "#ff0000"}]
    )
    figure = render(plan, inputs)
    points = next(
        collection for collection in figure.axes[0].collections if collection.get_label() == "门诊"
    )
    assert points.get_offsets().tolist() == [[3e4, 30], [1e4, 10]]
    assert to_hex(points.get_facecolors()[1]) == "#ff0000"


def test_continuous_color_is_not_overwritten_by_report_palette(render):  # noqa: F811
    plan, inputs = point_plan(colorField="color", colorMap="cividis")
    figure = render(plan, inputs)
    points = figure.axes[0].collections[0]
    assert list(points.get_array()) == [20, 40, 80]
    assert len({tuple(color) for color in points.get_facecolors()}) == 3
    assert "color · %" == figure.axes[1].get_ylabel()


def test_bubble_area_is_proportional_to_frozen_size(render):  # noqa: F811
    plan, inputs = point_plan(form="bubble", sizeField="size", maxArea=800)
    figure = render(plan, inputs)
    assert list(figure.axes[0].collections[0].get_sizes()) == [200, 400, 800]
    assert any("最大值 400.00人次" in text.get_text() for text in figure.texts)


def test_missing_scatter_observations_are_masked_and_not_zero_filled(render):  # noqa: F811
    source = point_table()
    source["rows"][1][2] = None
    plan, inputs = point_plan(source)
    plan.charts[0].standard_axes = StandardChartAxes(allowNulls=True)
    figure = render(plan, inputs)
    offsets = figure.axes[0].collections[0].get_offsets()
    assert offsets.mask[1].all()
    assert offsets[0].tolist() == [1e4, 10]
    assert any("缺失观测保留，未补零：1行" in text.get_text() for text in figure.texts)


def heatmap_plan(source=None, **encoding):
    source = source or {
        "columns": ["月份", "院区", "amount"],
        "rows": [
            ["一月", "东院", 1],
            ["一月", "西院", 2],
            ["二月", "东院", 3],
            ["二月", "西院", 4],
        ],
        "columnMeta": {"amount": {"unit": "元"}},
    }
    plan, inputs = build(source, form="heatmap", selected=("amount",))
    chart = plan.charts[0]
    chart.standard_annotations = ()
    chart.standard_encoding = StandardChartEncoding(
        xField="月份", yField="院区", valueField="amount", **encoding
    )
    return plan, inputs


def test_heatmap_keeps_axes_orientation_and_values(render):  # noqa: F811
    plan, inputs = heatmap_plan(showValues=True)
    figure = render(plan, inputs)
    assert figure.axes[0].images[0].get_array().tolist() == [[1, 3], [2, 4]]
    assert [tick.get_text() for tick in figure.axes[0].get_yticklabels()] == ["东院", "西院"]
    assert sorted(text.get_text() for text in figure.axes[0].texts) == [
        "1.00",
        "2.00",
        "3.00",
        "4.00",
    ]


def test_sparse_heatmap_masks_missing_cells_without_zero_filling(render):  # noqa: F811
    source = {
        "columns": ["月份", "院区", "amount"],
        "rows": [["一月", "东院", 0], ["一月", "西院", 2], ["二月", "东院", 3]],
        "columnMeta": {"amount": {"unit": "元"}},
    }
    plan, inputs = heatmap_plan(source)
    assert (
        standard_visualization_preflight(plan, inputs).diagnostic["code"]
        == "standard_heatmap_missing_cell"
    )
    plan.charts[0].standard_axes = StandardChartAxes(allowNulls=True)
    figure = render(plan, inputs)
    data = figure.axes[0].images[0].get_array()
    assert data[0, 0] == 0 and data.mask[1, 1]


def test_heatmap_point_and_rectangle_bind_both_frozen_dimensions(render):  # noqa: F811
    plan, inputs = heatmap_plan()
    plan.charts[0].standard_annotations = (
        StandardChartAnnotation(kind="point", label="二月", rowLabel="东院"),
        StandardChartAnnotation(
            kind="range", label="一月", endLabel="二月", rowLabel="东院", endRowLabel="西院"
        ),
    )
    figure = render(plan, inputs)
    assert figure.axes[0].texts[0].xy == (1, 0)
    assert "3.00元" in figure.axes[0].texts[0].get_text()
    assert figure.axes[0].patches[0].get_width() == 2


@pytest.mark.parametrize(
    "fault,code",
    [
        ("duplicate", "standard_heatmap_duplicate_cell"),
        ("bool", "standard_encoding_values_invalid"),
        ("logzero", "standard_color_log_domain_invalid"),
        ("unit", "standard_encoding_unit_missing"),
    ],
)
def test_heatmap_rejects_ambiguous_or_invalid_data(fault, code):
    source = {
        "columns": ["月份", "院区", "amount"],
        "rows": [["一月", "东院", 0]],
        "columnMeta": {"amount": {"unit": "元"}},
    }
    if fault == "duplicate":
        source["rows"] *= 2
    if fault == "bool":
        source["rows"][0][2] = True
    if fault == "unit":
        source["columnMeta"] = {}
    plan, inputs = heatmap_plan(source, **({"colorScale": "log"} if fault == "logzero" else {}))
    assert standard_visualization_preflight(plan, inputs).diagnostic["code"] == code


def band_plan(source=None, **axes):
    source = source or {
        "columns": ["label", "actual", "lower", "upper"],
        "rows": [["一月", 1e8, 0.8e8, 1.2e8], ["二月", 2e8, 1.8e8, 2.2e8]],
        "columnMeta": {field: {"unit": "元"} for field in ["actual", "lower", "upper"]},
    }
    plan, inputs = build(source, form="line")
    plan.charts[0].standard_annotations = ()
    plan.charts[0].standard_bands = (
        StandardChartBand(series="actual", lowerField="lower", upperField="upper"),
    )
    plan.charts[0].standard_axes = StandardChartAxes(**axes)
    return plan, inputs


@pytest.mark.parametrize("mode", ["single", "dual", "panels", "zoom"])
def test_frozen_range_bands_preserve_values_units_and_center_line(render, mode):  # noqa: F811
    source = None
    if mode == "dual":
        source = {
            "columns": ["label", "actual", "lower", "upper", "budget"],
            "rows": [["一月", 1e8, 0.8e8, 1.2e8, 5e8], ["二月", 2e8, 1.8e8, 2.2e8, 6e8]],
            "columnMeta": {
                field: {"unit": "元"} for field in ["actual", "lower", "upper", "budget"]
            },
        }
    plan, inputs = band_plan(
        source,
        mode=mode,
        **({"rightFields": ["actual"]} if mode == "dual" else {}),
        **({"zoomStart": "一月", "zoomEnd": "二月"} if mode == "zoom" else {}),
    )
    plan.charts[0].standard_display_unit = "亿元"
    if mode == "dual":
        plan.charts[0].standard_value_fields = ("budget", "actual")
    figure = render(plan, inputs)
    target = figure.axes[1] if mode == "dual" else figure.axes[0]
    center = target.lines[0]
    assert list(center.get_ydata()) == [1, 2]
    band = target.collections[0]
    ys = [vertex[1] for path in band.get_paths() for vertex in path.vertices]
    assert min(ys) == pytest.approx(0.8) and max(ys) == pytest.approx(2.2)
    assert band.get_alpha() == 0.18
    if mode == "zoom":
        inset = figure.axes[0].child_axes[0]
        assert len(inset.collections) == 1
        assert inset.get_ylim()[0] <= 0.8 and inset.get_ylim()[1] >= 2.2


@pytest.mark.parametrize(
    "fault,code",
    [
        ("bounds", "standard_band_bounds_invalid"),
        ("unit", "standard_band_units_incompatible"),
        ("percent", "standard_band_units_incompatible"),
    ],
)
def test_invalid_ranges_are_not_estimated_or_repaired_with_fake_values(fault, code):
    source = {
        "columns": ["label", "actual", "lower", "upper"],
        "rows": [["一月", 10, 8, 12]],
        "columnMeta": {field: {"unit": "元"} for field in ["actual", "lower", "upper"]},
    }
    if fault == "bounds":
        source["rows"][0][3] = 9
    if fault == "unit":
        source["columnMeta"]["upper"]["unit"] = "人次"
    if fault == "percent":
        source["columnMeta"]["lower"]["isPercent"] = True
    plan, inputs = band_plan(source)
    assert standard_visualization_preflight(plan, inputs).diagnostic["code"] == code


def test_unlabelled_numeric_scatter_does_not_invent_business_labels(render):  # noqa: F811
    source = {
        "columns": ["x", "y"],
        "rows": [[100, 2], [200, 3]],
        "columnMeta": {"x": {"unit": "人次"}, "y": {"unit": "元"}},
    }
    plan, inputs = build(source, form="scatter", selected=("y",))
    plan.charts[0].standard_annotations = ()
    plan.charts[0].standard_encoding = StandardChartEncoding(xField="x", yField="y")
    figure = render(plan, inputs)
    assert figure.axes[0].collections[0].get_offsets().tolist() == [[100, 2], [200, 3]]
    assert not figure.axes[0].texts
    plan.charts[0].standard_annotations = (
        StandardChartAnnotation(kind="point", series="y", label="0"),
    )
    assert (
        standard_visualization_preflight(plan, inputs).diagnostic["code"]
        == "standard_scatter_label_required"
    )


def test_heatmap_explicit_dimension_order_and_diverging_center(render):  # noqa: F811
    source = {
        "columns": ["月份", "院区", "amount"],
        "rows": [
            ["一月", "东院", -10],
            ["一月", "西院", 2],
            ["二月", "东院", 3],
            ["二月", "西院", 30],
        ],
        "columnMeta": {"amount": {"unit": "元"}},
    }
    plan, inputs = heatmap_plan(
        source, xLabels=["二月", "一月"], yLabels=["西院", "东院"], colorMap="RdBu_r", colorCenter=0
    )
    figure = render(plan, inputs)
    image = figure.axes[0].images[0]
    assert image.get_array().tolist() == [[30, 2], [3, -10]]
    assert image.norm(0) == 0.5


@pytest.mark.parametrize("form", ["scatter", "bubble", "heatmap", "line"])
def test_new_forms_recheck_original_input_identity(tmp_path, monkeypatch, form):
    if form == "heatmap":
        plan, inputs = heatmap_plan()
    elif form == "line":
        plan, inputs = band_plan()
    else:
        plan, inputs = point_plan(form=form, **({"sizeField": "size"} if form == "bubble" else {}))
    script = standard_visualization_preflight(plan, inputs).source
    assert script is not None
    monkeypatch.chdir(tmp_path)
    Path("input.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="identity changed"):
        exec(script, {})


def test_point_annotation_uses_frozen_xy_after_order_and_unit_conversion(render):  # noqa: F811
    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartPresentation

    plan, inputs = point_plan(xDisplayUnit="万人次")
    plan.charts[0].standard_presentation = StandardChartPresentation(order={"mode": "reverse"})
    plan.charts[0].standard_annotations = (
        StandardChartAnnotation(kind="point", series="y", label="乙"),
    )
    figure = render(plan, inputs)
    assert figure.axes[0].texts[0].xy == (2, 20)
    assert "20.00元" in figure.axes[0].texts[0].get_text()


@pytest.mark.parametrize(
    "fault,code",
    [
        ("negative", "standard_bubble_size_invalid"),
        ("spread", "standard_bubble_area_unreadable"),
        ("zero", "standard_bubble_area_unreadable"),
        ("log", "standard_encoding_log_domain_invalid"),
        ("duplicate", "standard_scatter_labels_duplicate"),
    ],
)
def test_scatter_and_bubble_reject_misleading_inputs(fault, code):
    source = point_table()
    if fault == "negative":
        source["rows"][0][4] = -1
    if fault == "spread":
        source["rows"][0][4] = 1e-20
    if fault == "zero":
        for row in source["rows"]:
            row[4] = 0
    if fault == "log":
        source["rows"][0][2] = 0
    if fault == "duplicate":
        source["rows"][1][0] = source["rows"][0][0]
    plan, inputs = point_plan(
        source, form="bubble", sizeField="size", **({"xScale": "log"} if fault == "log" else {})
    )
    assert standard_visualization_preflight(plan, inputs).diagnostic["code"] == code


def test_band_converts_registered_boundary_units_without_changing_center(render):  # noqa: F811
    source = {
        "columns": ["label", "actual", "lower", "upper"],
        "rows": [["一月", 100, 0.008, 0.012]],
        "columnMeta": {
            "actual": {"unit": "元"},
            "lower": {"unit": "万元"},
            "upper": {"unit": "万元"},
        },
    }
    plan, inputs = band_plan(source)
    figure = render(plan, inputs)
    assert list(figure.axes[0].lines[0].get_ydata()) == [100]
    bounds = figure.axes[0].collections[0].get_paths()[0].vertices[:, 1]
    assert min(bounds) == 80 and max(bounds) == 120


def test_band_normalizes_fractions_and_percentage_bounds(render):  # noqa: F811
    source = {
        "columns": ["label", "actual", "lower", "upper"],
        "rows": [["一月", 0.2, 10, 30]],
        "columnMeta": {
            "actual": {"unit": "%", "isPercent": False},
            "lower": {"unit": "%", "isPercent": True},
            "upper": {"unit": "%", "isPercent": True},
        },
    }
    plan, inputs = band_plan(source)
    figure = render(plan, inputs)
    assert list(figure.axes[0].lines[0].get_ydata()) == [20]
    bounds = figure.axes[0].collections[0].get_paths()[0].vertices[:, 1]
    assert min(bounds) == 10 and max(bounds) == 30


def test_band_missing_intervals_create_gaps_instead_of_zero_ranges(render):  # noqa: F811
    source = {
        "columns": ["label", "actual", "lower", "upper"],
        "rows": [["一月", 10, 8, 12], ["二月", 20, None, None], ["三月", 30, 28, 32]],
        "columnMeta": {field: {"unit": "元"} for field in ["actual", "lower", "upper"]},
    }
    plan, inputs = band_plan(source, allowNulls=True)
    figure = render(plan, inputs)
    paths = figure.axes[0].collections[0].get_paths()
    assert len(paths) == 2
    assert min(v[1] for path in paths for v in path.vertices) == 8
    assert any("1行范围缺失，未补零" in text.get_text() for text in figure.texts)


def test_all_missing_ranges_keep_center_without_misleading_band_legend(render):  # noqa: F811
    source = {
        "columns": ["label", "actual", "lower", "upper"],
        "rows": [["一月", 10, None, None], ["二月", 20, None, None]],
        "columnMeta": {field: {"unit": "元"} for field in ["actual", "lower", "upper"]},
    }
    plan, inputs = band_plan(source, allowNulls=True)
    figure = render(plan, inputs)
    assert list(figure.axes[0].lines[0].get_ydata()) == [10, 20]
    assert not figure.axes[0].collections
    assert any("2行范围缺失，未补零" in text.get_text() for text in figure.texts)


def test_480_numeric_observations_pass_formal_source_gate_without_embedding_rows(tmp_path):
    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
    from smart_reporting.reporting.code_agent.toolkit import validate_script_source

    source = {
        "columns": ["x", "y"],
        "rows": [[i, i * 2] for i in range(480)],
        "columnMeta": {"x": {"unit": "人次"}, "y": {"unit": "元"}},
    }
    plan, inputs = build(source, form="scatter", selected=("y",))
    plan.charts[0].standard_annotations = ()
    plan.charts[0].standard_encoding = StandardChartEncoding(xField="x", yField="y")
    script = standard_visualization_preflight(plan, inputs).source
    assert script is not None
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


def test_bound_bubble_fields_survive_real_plan_materialization_and_render(render):  # noqa: F811
    from smart_reporting.reporting.workflow.runtime.chart_inputs import materialize_chart_inputs
    from smart_reporting.reporting.workflow.runtime.phase_models import (
        ChartDraft,
        VisualizationPlanDraft,
    )

    source = point_table()
    chart = ChartDraft(
        chartId="chart",
        sourcePath="chart.png",
        title="科室收入与工作量",
        altText="气泡面积表示样本量",
        citationIds=["citation"],
        metricCodes=["income"],
        currentPeriod="2026-10",
        sourceDatasetId="dataset",
        aggregationGrain="department",
        visualForm="bubble",
        standardLabelField="label",
        standardValueFields=["y"],
        standardEncoding={"xField": "x", "yField": "y", "sizeField": "size", "groupField": "group"},
        dataBindings=[
            {
                "analysisId": "a",
                "factPath": "facts.json",
                "dataPath": "findings[0].rows",
                "fields": source["columns"],
                "role": "科室对比",
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
            "dataDescriptors": [{"dataPath": "findings[0].rows", "fields": source["columns"]}],
        }
    ]
    inputs = materialize_chart_inputs(
        plan, facts, {"facts.json": {"findings": [source]}}, output_root="."
    )
    assert not inputs.fallback_chart_ids
    figure = render(plan, inputs)
    assert figure.axes[0].collections[0].get_offsets().tolist() == [[1e4, 10], [3e4, 30]]
    assert list(figure.axes[0].collections[0].get_sizes()) == [150, 600]


def test_multisource_scatter_can_align_more_than_sixty_observations(render):  # noqa: F811
    import json

    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )
    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartSource

    first = {
        "columns": ["label", "actual"],
        "rows": [[f"观测{i}", i + 1] for i in range(100)],
        "columnMeta": {"actual": {"unit": "元"}},
    }
    plan, original = build(first, form="scatter", selected=("y",))
    chart = plan.charts[0]
    chart.standard_annotations = ()
    chart.standard_encoding = StandardChartEncoding(xField="x", yField="y")
    chart.standard_sources = (
        StandardChartSource(sourceIndex=0, labelField="label", valueField="actual", seriesName="x"),
        StandardChartSource(sourceIndex=1, labelField="label", valueField="actual", seriesName="y"),
    )
    second = {**first, "rows": [[f"观测{i}", (i + 1) * 2] for i in reversed(range(100))]}
    extra = ChartInputFile("second.json", json.dumps(second).encode())
    inputs = ChartInputMaterialization(
        files=(*original.files, extra),
        entries=(
            *original.entries,
            {"chartId": "chart", "path": extra.path, "sha256": extra.sha256},
        ),
    )
    figure = render(plan, inputs)
    assert figure.axes[0].collections[0].get_offsets().tolist() == [
        [i + 1, 2 * (i + 1)] for i in range(100)
    ]


def test_highlight_does_not_distort_bubble_area_or_continuous_colors(render):  # noqa: F811
    plan, inputs = point_plan(form="bubble", sizeField="size", colorField="color")
    plan.charts[0].standard_annotations = (
        StandardChartAnnotation(kind="point", series="y", label="乙", highlight=True),
    )
    figure = render(plan, inputs)
    assert len(figure.axes[0].collections) == 1
    assert list(figure.axes[0].collections[0].get_sizes()) == [150, 300, 600]
    assert figure.axes[0].texts[0].get_bbox_patch() is not None


@pytest.mark.parametrize("form", ["scatter", "heatmap"])
def test_special_views_have_current_script_gate_for_small_inputs(tmp_path, form):
    from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
    from smart_reporting.reporting.code_agent.toolkit import validate_script_source

    plan, inputs = point_plan() if form == "scatter" else heatmap_plan()
    source = standard_visualization_preflight(plan, inputs).source
    assert source is not None
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


@pytest.mark.parametrize(
    "fault", ["coordinates", "areas", "matrix", "missing_cell", "band", "color"]
)
def test_independent_auditor_rejects_wrong_statistical_expectations(tmp_path, fault):
    from scripts.replay_standard_visualization_variants import run_case
    from scripts.standard_visualization_geometry_cases import case, parameters

    doc = {
        "columns": ["label", "x", "y", "size", "color"],
        "rows": [["甲", 1, 10, 100, 0.2], ["乙", 2, 20, 400, 0.8]],
        "columnMeta": {
            "x": {"unit": "人次"},
            "y": {"unit": "元"},
            "size": {"unit": "人次"},
            "color": {"unit": "%", "isPercent": False},
        },
    }
    params = parameters("scatter", standard_encoding={"xField": "x", "yField": "y"})
    assertion = {"observations": [{"name": "y", "offsets": [[1, 10], [2, 21]]}]}
    if fault == "areas":
        params = parameters(
            "bubble",
            standard_encoding={"xField": "x", "yField": "y", "sizeField": "size", "maxArea": 800},
        )
        assertion = {
            "observations": [{"name": "y", "offsets": [[1, 10], [2, 20]], "sizes": [201, 800]}]
        }
    elif fault == "color":
        params = parameters(
            "scatter",
            standard_encoding={
                "xField": "x",
                "yField": "y",
                "colorField": "color",
                "colorMap": "cividis",
            },
        )
        assertion = {
            "observations": [
                {
                    "name": "y",
                    "offsets": [[1, 10], [2, 20]],
                    "colorValues": [20, 80],
                    "colorMap": "viridis",
                }
            ]
        }
    elif fault in {"matrix", "missing_cell"}:
        doc = {
            "columns": ["x", "y", "v"],
            "rows": [["一月", "东", 0], ["一月", "西", 2], ["二月", "东", 3]],
            "columnMeta": {"v": {"unit": "元"}},
        }
        params = parameters(
            "heatmap",
            standard_encoding={"xField": "x", "yField": "y", "valueField": "v"},
            standard_axes={"allowNulls": True},
        )
        values = [[0, 2], [3, None]] if fault == "matrix" else [[0, 3], [2, 0]]
        assertion = {"matrices": [{"name": "v", "values": values}]}
    elif fault == "band":
        doc = {
            "columns": ["label", "actual", "low", "high"],
            "rows": [["甲", 10, 8, 12], ["乙", 20, 18, 22]],
            "columnMeta": {field: {"unit": "元"} for field in ["actual", "low", "high"]},
        }
        params = parameters(
            "line",
            standard_value_fields=["actual"],
            standard_bands=[{"series": "actual", "lowerField": "low", "upperField": "high"}],
        )
        assertion = {"bands": [{"name": "actual 范围", "lower": [7, 18], "upper": [12, 22]}]}
    result = run_case(case("negative-control-" + fault, params, doc, **assertion), tmp_path)
    assert result["status"] == "semantic_mismatch"
