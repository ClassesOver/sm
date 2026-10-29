import ast
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_standard_chart_presentation import (  # noqa: F401
    build,
    render,
)
from smart_reporting.reporting.tests.test_standard_chart_routing import setup
from smart_reporting.reporting.workflow.runtime.phase_models import (
    StandardChartAxes,
    StandardChartCanvas,
)
from smart_reporting.reporting.workflow.runtime.standard_chart_routing import (
    _run_standard_with_layout_retry,
)


@pytest.mark.parametrize("mode", ["single", "dual", "panels", "zoom"])
def test_mixed_geometry_combines_with_axes_and_zoom_without_changing_data(render, mode):  # noqa: F811
    doc = {
        "columns": ["label", "actual", "budget"],
        "rows": [["一月", 10, 20], ["二月", 30, 40]],
        "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "元"}},
    }
    plan, inputs = build(
        doc,
        form="bar",
        selected=("actual", "budget"),
        style={"series": [{"series": "budget", "geometry": "line"}]},
    )
    plan.charts[0].standard_axes = StandardChartAxes(
        mode=mode,
        rightFields=["budget"] if mode == "dual" else [],
        zoomStart="一月" if mode == "zoom" else None,
        zoomEnd="二月" if mode == "zoom" else None,
    )
    figure = render(plan, inputs)
    axes = figure.axes
    assert [bar.get_height() for bar in axes[0].containers[0]] == [10, 30]
    target = axes[1] if mode in ["dual", "panels"] else axes[0]
    assert list(target.lines[0].get_ydata()) == [20, 40]
    if mode == "zoom":
        inset = axes[0].child_axes[0]
        assert [bar.get_height() for bar in inset.containers[0]] == [10, 30]
        assert list(inset.lines[0].get_ydata()) == [20, 40]
        assert [bar.get_x() + bar.get_width() / 2 for bar in inset.containers[0]] == [0, 1]


def test_symmetric_log_preserves_zero_negative_and_extreme_values(render):  # noqa: F811
    values = [-1e12, 0, 1e-8, 1e12]
    doc = {
        "columns": ["label", "actual"],
        "rows": [[str(i), value] for i, value in enumerate(values)],
        "columnMeta": {"actual": {"unit": "元"}},
    }
    plan, inputs = build(doc, form="line")
    plan.charts[0].standard_annotations = ()
    plan.charts[0].standard_axes = StandardChartAxes(scale="symlog", linearThreshold=0.1)
    figure = render(plan, inputs)
    assert figure.axes[0].get_yscale() == "symlog"
    assert list(figure.axes[0].lines[0].get_ydata()) == values
    assert "对称对数" in figure.axes[0].get_ylabel()
    assert all("\n" not in tick.get_text() for tick in figure.axes[0].get_yticklabels())


def test_zoom_keeps_complete_edge_bars_and_point_color_bound_to_selected_window(render):  # noqa: F811
    doc = {
        "columns": ["label", "actual", "budget"],
        "rows": [["一月", 10, 20], ["二月", 30, 40], ["三月", 25, 35]],
        "columnMeta": {"actual": {"unit": "元"}, "budget": {"unit": "元"}},
    }
    plan, inputs = build(
        doc,
        form="bar",
        selected=("actual", "budget"),
        style={
            "series": [{"series": "budget", "geometry": "line"}],
            "points": [
                {"series": "budget", "label": "一月", "color": "#00ff00"},
                {"series": "budget", "label": "二月", "color": "#ff0000"},
            ],
        },
    )
    plan.charts[0].standard_annotations = ()
    plan.charts[0].standard_axes = StandardChartAxes(mode="zoom", zoomStart="二月", zoomEnd="三月")
    figure = render(plan, inputs)
    inset = figure.axes[0].child_axes[0]
    assert list(inset.lines[0].get_ydata()) == [40, 35]
    assert [bar.get_height() for bar in inset.containers[0]] == [30, 25]
    assert list(inset.collections[0].get_offsets()[0]) == [1, 40]
    low, high = inset.get_xlim()
    assert all(
        low <= bar.get_x() and bar.get_x() + bar.get_width() <= high for bar in inset.containers[0]
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "size_mode,error_code,attempts",
    [
        ("auto", "standard_chart_layout_unresolved", 2),
        ("fixed", "standard_chart_layout_unresolved", 1),
        ("auto", "chart input identity changed", 1),
    ],
)
async def test_layout_retry_is_bounded_and_only_changes_automatic_canvas(
    tmp_path, size_mode, error_code, attempts
):
    plan, inputs, context = setup(tmp_path, ["line"])
    chart = plan.charts[0]
    chart.standard_canvas = StandardChartCanvas(sizeMode=size_mode)
    chart.model_copy = lambda update: SimpleNamespace(**{**vars(chart), **update})
    widths = []

    async def standard(ctx, workspace, source, facts):
        config = ast.literal_eval(source.splitlines()[0].split(" = ", 1)[1])
        widths.append(config[0][-1]["width"])
        if len(widths) == 1:
            raise ReportingError("execution_failed", "failure", details={"stderr": error_code})
        return "current-reviewed-receipt"

    runner = SimpleNamespace(run_standard_visualization=standard)
    if attempts == 1:
        with pytest.raises(ReportingError):
            await _run_standard_with_layout_retry(runner, context, object(), plan, inputs, {})
    else:
        result = await _run_standard_with_layout_retry(runner, context, object(), plan, inputs, {})
        assert result == "current-reviewed-receipt"
        assert widths[1] > widths[0]
    assert len(widths) == attempts


def test_opt_in_online_planner_uses_production_standard_instructions(monkeypatch):
    from smart_reporting.reporting.workflow import benchmark_execution as module
    from smart_reporting.reporting.workflow.benchmark_variants import BenchmarkVariant

    captured = []
    monkeypatch.setattr(
        module, "create_reporting_generator_agent", lambda **kwargs: captured.append(kwargs)
    )
    for variant in [BenchmarkVariant.CANDIDATE, BenchmarkVariant.LEGACY]:
        module.build_benchmark_planner_agent(
            model=object(), task_kind="visualization", variant=variant, standard_visualization=True
        )
    assert "standardView" in "".join(captured[0]["stage_instructions"])
    assert "standardView" not in "".join(captured[1]["stage_instructions"])


def test_online_readiness_missing_configuration_is_not_reported_as_passed(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    root = Path(__file__).resolve().parents[3]
    output = tmp_path / "readiness.json"
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/replay_visualization_task.py"),
            "--check-standard-readiness",
            "--output",
            str(output),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    readiness = json.loads(output.read_text())
    assert readiness["status"] == "blocked_missing_model_configuration"
    assert readiness["modelRequestsExecuted"] == 0
    assert readiness["onlinePlannerValidated"] is False
