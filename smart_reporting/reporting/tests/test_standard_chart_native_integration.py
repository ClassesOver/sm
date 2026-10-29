"""真实Agno CodeMode执行五图；这是集成烟测，不是AI性能样本。"""

import json
from time import perf_counter

import pytest
from agno.tools.code import CodeMode

from smart_reporting.reporting.code_agent.context import ReportingCodingTaskContext
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_mode import ReportingCodeModeRuntime
from smart_reporting.reporting.workflow.runtime.code_generation import ReportingCodeGenerationRunner
from smart_reporting.reporting.workflow.runtime.standard_chart_routing import run_standard_chart_routes

from .test_reporting_interactive_code_agent import workspace  # noqa: F401
from .test_standard_chart_families import flow, make, radar_table


@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("form", ["pie", "donut", "radar", "funnel", "sankey"])
async def test_native_codemode_runs_compiled_family_with_real_receipt(workspace, form):
    if form == "sankey":
        plan, inputs = flow()
    elif form == "radar":
        plan, inputs = make(form, [radar_table()], standardValueFields=["a", "b", "c"])
    else:
        plan, inputs = make(form)
    chart = plan.charts[0]
    context = ReportingCodingTaskContext(
        task_id="native-family-test", task_kind="visualization",
        code_mode_session_id=f"native-family-{form}", workspace_key=workspace.identity.workspace_key,
        workspace_root=workspace.identity.root, script_path="charts.py",
        authorized_read_paths=inputs.read_paths,
        authorized_write_paths=("charts.py", chart.source_path),
        declared_output_paths=(chart.source_path,), max_source_bytes=256_000,
    )
    for file in inputs.files:
        await workspace.awrite_bytes(context.task_id, file.path, file.content)
    runtime = ReportingCodeModeRuntime(CodeMode(
        snapshot=False, allow_shell=True, cwd=str(workspace.identity.root), timeout=45, max_kernels=1,
    ))
    lsp = ReportingLspProcessManager()

    def forbidden_model(*_args, **_kwargs):
        raise AssertionError("直接模板不能调用模型")

    runner = ReportingCodeGenerationRunner(forbidden_model, runtime, lsp, vision_reviewer=None)
    started = perf_counter()
    try:
        result = await run_standard_chart_routes(
            runner, context, workspace, plan, inputs,
            {"visualizationPlan": plan.model_dump(mode="json", by_alias=True)}, object(),
            deterministic=True,
        )
        assert result.reviewed is False and result.visual_inspection_receipts == ()
        assert len(result.deterministic_image_checks) == 1
        image = result.execution_receipt.output_files[0]
        actual = await workspace.ahash_file(context.task_id, chart.source_path)
        assert image.sha256 == actual["sha256"]
        assert result.standard_chart_routes[0]["route"] == "standard"
        assert runner.registry.active_count == 0
        assert runtime.drain_execution_spans(context.code_mode_session_id) == "unknown"
        assert not runtime._logged_connections
        print(json.dumps({"mode": "native_no_model_smoke", "form": form,
            "elapsedMs": round((perf_counter()-started)*1000, 3),
            "stageTimingsMs": result.stage_timings, "executionSpans": result.execution_spans,
            "sha256": image.sha256}, ensure_ascii=False))
    finally:
        await lsp.aclose()
        await runtime.aclose()
