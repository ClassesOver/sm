import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
from smart_reporting.reporting.code_agent.toolkit import validate_script_source
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
)
from smart_reporting.reporting.workflow.runtime.standard_chart_routing import (
    run_standard_chart_routes,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


class Plan:
    def __init__(self, charts):
        self.charts = charts

    def model_copy(self, update):
        return Plan(update["charts"])

    def model_dump(self, **kwargs):
        return {"charts": [vars(chart) for chart in self.charts]}


def setup(tmp_path, forms):
    charts = tuple(
        SimpleNamespace(
            chart_id=str(i),
            title="测试图",
            visual_form=form,
            renderer="matplotlib",
            source_path=f"chart-{i}.png",
            interactive_path=None,
        )
        for i, form in enumerate(forms)
    )
    files = tuple(
        ChartInputFile(
            f"input-{i}.json",
            json.dumps(
                {
                    "chartId": str(i),
                    "columns": ["label", "value"],
                    "rows": [["甲", 10], ["乙", 20]],
                    "columnMeta": {"value": {"unit": "元"}},
                }
            ).encode(),
        )
        for i in range(len(forms))
    )
    inputs = ChartInputMaterialization(
        files=files,
        entries=tuple(
            dict(chartId=str(i), path=f.path, sha256=f.sha256) for i, f in enumerate(files)
        ),
    )
    for file in files:
        (tmp_path / file.path).write_bytes(file.content)
    context = ReportingCodingTaskContext(
        task_id="task",
        task_kind="visualization",
        code_mode_session_id="session",
        workspace_key="workspace",
        workspace_root=tmp_path,
        script_path="charts.py",
        authorized_read_paths=inputs.read_paths,
        authorized_write_paths=("charts.py", *(chart.source_path for chart in charts)),
        declared_output_paths=tuple(chart.source_path for chart in charts),
        max_source_bytes=256000,
    )
    return Plan(charts), inputs, context


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("failure", [None, "review", "tamper", "final_review"])
async def test_mixed_routes_keep_good_charts_standard_and_sign_final_execution(
    tmp_path, monkeypatch, failure
):
    monkeypatch.chdir(tmp_path)
    plan, inputs, context = setup(tmp_path, ["line", "violin", "bar"])
    calls = []

    async def execute(ctx, source):
        validate_script_source(ctx, source)
        Path(ctx.script_path).write_text(source)
        exec(source, {})
        identity = SimpleNamespace(
            path=ctx.script_path, sha256=hashlib.sha256(source.encode()).hexdigest()
        )
        return SimpleNamespace(script_file=identity, execution_receipt=ctx.script_path)

    async def standard(ctx, workspace, source, facts):
        calls.append(("standard", ctx.declared_output_paths))
        if (
            failure == "final_review"
            and ctx.script_path == "charts.py"
            and sum(
                call[0] == "standard" and call[1] == context.declared_output_paths for call in calls
            )
            == 1
        ):
            raise ReportingError(
                "review_failed",
                "bad final image",
                details={
                    "standardDiagnostic": {
                        "code": "specific_review",
                        "details": {"path": "chart-0.png", "issueSummary": "overlap"},
                    }
                },
            )
        if failure == "review" and ctx.declared_output_paths == ("chart-0.png",):
            raise ReportingError(
                "review_failed",
                "bad image",
                details={
                    "standardDiagnostic": {
                        "code": "specific_review",
                        "details": {"issueSummary": "overlap"},
                    }
                },
            )
        if failure == "tamper" and ctx.script_path == "charts.py":
            Path("charts-chart-001.py").write_text('raise RuntimeError("tampered")')
        return await execute(ctx, source)

    async def coding(ctx, workspace, facts, **kwargs):
        calls.append(
            (
                "coding",
                ctx.declared_output_paths,
                kwargs["diagnostic"] or facts.get("standardChartPreflight"),
            )
        )
        assert facts["visualizationWorkspace"]["scriptPath"] == ctx.script_path
        assert len(facts["visualizationPlan"]["charts"]) == 1
        # Test double for generated code; production keeps the real Coding runner.
        source = (
            "import matplotlib.pyplot as plt\nplt.figure()\nplt.plot([1, 2], [10, 20])\n"
            f"plt.savefig({ctx.declared_output_paths[0]!r})\nplt.close()\n"
        )
        return await execute(ctx, source)

    async def read(task_id, path):
        return Path(path).read_bytes(), "text/x-python"

    runner = SimpleNamespace(run_standard_visualization=standard, run=coding)
    workspace = SimpleNamespace(afile_bytes=read)
    if failure == "tamper":
        with pytest.raises(ValueError, match="component identity changed"):
            await run_standard_chart_routes(runner, context, workspace, plan, inputs, {}, object())
        return
    result = await run_standard_chart_routes(runner, context, workspace, plan, inputs, {}, object())
    assert result.execution_receipt == "charts.py"
    assert calls[-1] == ("standard", context.declared_output_paths)
    coded = [call for call in calls if call[0] == "coding"]
    assert {call[1] for call in coded} == (
        {("chart-0.png",), ("chart-1.png",)} if failure else {("chart-1.png",)}
    )
    assert (
        next(call[2]["code"] for call in coded if call[1] == ("chart-1.png",))
        == "standard_form_unsupported"
    )
    assert sum(call[1] == ("chart-1.png",) for call in coded) == 1
    if failure:
        assert (
            next(call[2]["code"] for call in coded if call[1] == ("chart-0.png",))
            == "specific_review"
        )
    for chart in plan.charts:
        assert Path(chart.source_path).read_bytes().startswith(b"\x89PNG")
    assert [item["route"] for item in result.standard_chart_routes] == (
        ["coding", "coding", "standard"] if failure else ["standard", "coding", "standard"]
    )


@pytest.mark.parametrize(
    "fault,code",
    [
        ("form", "standard_form_unsupported"),
        ("identity", "standard_input_identity_mismatch"),
        ("label", "standard_label_ambiguous"),
        ("null", "standard_values_invalid"),
    ],
)
def test_preflight_provides_actionable_diagnostic(tmp_path, fault, code):
    plan, inputs, _ = setup(tmp_path, ["line"])
    if fault == "form":
        plan.charts[0].visual_form = "violin"
    elif fault == "identity":
        inputs.entries[0]["sha256"] = "0" * 64
    else:
        doc = json.loads(inputs.files[0].content)
        if fault == "label":
            doc["columns"] = ["甲列", "乙列", "value"]
            doc["rows"] = [["甲", "备注甲", 1], ["乙", "备注乙", 2]]
        else:
            doc["rows"][0][1] = None
        file = ChartInputFile("input-0.json", json.dumps(doc).encode())
        inputs = ChartInputMaterialization(
            files=(file,), entries=(dict(chartId="0", path=file.path, sha256=file.sha256),)
        )
    result = standard_visualization_preflight(plan, inputs)
    assert result.source is None
    assert result.diagnostic["code"] == code
    assert result.diagnostic["parameter"] and result.diagnostic["suggestion"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("initial_failure", [False, True])
async def test_supported_group_fast_path_and_group_failure_isolation(
    tmp_path, monkeypatch, initial_failure
):
    monkeypatch.chdir(tmp_path)
    plan, inputs, context = setup(tmp_path, ["line", "bar"])
    calls = []

    async def standard(ctx, workspace, source, facts):
        calls.append(ctx.script_path)
        if initial_failure and len(calls) == 1:
            raise ReportingError("execution_failed", "failed group")
        validate_script_source(ctx, source)
        Path(ctx.script_path).write_text(source)
        exec(source, {})
        return SimpleNamespace(
            script_file=SimpleNamespace(
                path=ctx.script_path, sha256=hashlib.sha256(source.encode()).hexdigest()
            )
        )

    async def read(task_id, path):
        return Path(path).read_bytes(), "text/x-python"

    coding = AsyncMock(side_effect=AssertionError("supported charts must remain standard"))
    result = await run_standard_chart_routes(
        SimpleNamespace(run_standard_visualization=standard, run=coding),
        context,
        SimpleNamespace(afile_bytes=read),
        plan,
        inputs,
        {},
        object(),
    )
    assert len(calls) == (4 if initial_failure else 1)
    assert all(item["route"] == "standard" for item in result.standard_chart_routes)
    coding.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_legacy_interactive_delivery_keeps_existing_route(tmp_path):
    plan, inputs, context = setup(tmp_path, ["line"])
    plan.charts[0].interactive_path = "legacy.plotly.json"
    runner = SimpleNamespace(
        run=AsyncMock(return_value=SimpleNamespace()),
        run_standard_visualization=AsyncMock(side_effect=AssertionError("JSON is not an image")),
    )
    result = await run_standard_chart_routes(runner, context, object(), plan, inputs, {}, object())
    assert result.standard_chart_routes[0]["route"] == "coding"
    runner.run.assert_awaited_once()
    runner.run_standard_visualization.assert_not_called()
