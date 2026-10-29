"""可信标准源码使用真实工具回执，但不借用独立模型视觉结论。"""
# ruff: noqa: F811

import asyncio
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image, ImageDraw

from smart_reporting.reporting.code_agent.context import ReportingCodingTaskBinding
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_agent.toolkit import ReportingCodeModeToolkit
from smart_reporting.reporting.code_mode import ScriptProcessResult
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    _visualization_task_context,
    workspace,  # noqa: F401
)
from smart_reporting.reporting.tests.test_standard_chart_routing import setup
from smart_reporting.reporting.workflow.runtime.code_generation import ReportingCodeGenerationRunner
from smart_reporting.reporting.workflow.runtime.standard_chart_routing import (
    run_standard_chart_routes,
)

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]


def image_bytes(*, blank=False, size=(120, 80)):
    image = Image.new("RGB", size, "white")
    if not blank:
        ImageDraw.Draw(image).rectangle(
            (0, 0, min(50, size[0] - 1), min(50, size[1] - 1)), fill="navy"
        )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class StaticRuntime:
    def __init__(self, outputs, *, failure=None, cleanup_failure=False):
        self.outputs = outputs
        self.failure = failure
        self.cleanup_failure = cleanup_failure
        self.closed = []
        self.drained = []

    async def execute_script_process(self, session_id, workspace, script_path, **kwargs):
        if self.failure is not None:
            raise self.failure
        for path, raw in self.outputs.items():
            await workspace.awrite_bytes("task-1", path, raw, overwrite=True)
        return ScriptProcessResult(SimpleNamespace(status="ok", stdout="", stderr=""), 0)

    async def shutdown(self, session_id):
        self.closed.append(session_id)
        if self.cleanup_failure:
            raise RuntimeError("cleanup failed")

    def drain_execution_spans(self, session_id):
        self.drained.append(session_id)
        return {"scriptProcess": [12], "shutdown": [1]}


def runner_for(runtime):
    def forbidden_model(*args, **kwargs):
        raise AssertionError("deterministic execution called a model")

    return ReportingCodeGenerationRunner(
        forbidden_model,
        runtime,
        ReportingLspProcessManager(),
        vision_reviewer=SimpleNamespace(review=AsyncMock(side_effect=forbidden_model)),
    )


def source_for(paths):
    return "import matplotlib.pyplot as plt\n" + "".join(
        f"plt.figure()\nplt.plot([1, 2], [2, 3])\nplt.savefig({path!r})\nplt.close()\n"
        for path in paths
    )


async def test_trusted_static_execution_retains_real_receipt_without_visual_review(workspace):
    context = _visualization_task_context(workspace)
    paths = ("charts/chart.png", "charts/chart-page-2.png")
    context = replace(
        context, authorized_write_paths=(context.script_path, *paths), declared_output_paths=paths
    )
    runtime = StaticRuntime(dict.fromkeys(paths, image_bytes()))
    runner = runner_for(runtime)
    result = await runner.run_standard_visualization(
        context, workspace, source_for(paths), {}, deterministic=True
    )
    assert {item.path for item in result.execution_receipt.output_files} == set(paths)
    assert (
        result.script_file.sha256
        == (await workspace.ahash_file(context.task_id, context.script_path))["sha256"]
    )
    assert result.visual_inspection_receipts == ()
    assert result.reviewed is False
    assert [
        (item["width"], item["height"], item["reviewed"])
        for item in result.deterministic_image_checks
    ] == [(120, 80, False)] * 2
    assert runtime.closed == runtime.drained == [context.code_mode_session_id]
    assert result.execution_spans["scriptProcess"] == [12]
    assert runner.registry.active_count == 0
    runner.vision_reviewer.review.assert_not_called()


@pytest.mark.parametrize(
    "fault,code",
    [
        ("corrupt", "report_chart_source_invalid"),
        ("blank", "report_chart_blank"),
        ("tiny", "report_standard_image_dimensions_invalid"),
    ],
)
async def test_every_static_page_requires_decodable_nonblank_pixels(workspace, fault, code):
    context = _visualization_task_context(workspace)
    paths = ("charts/chart.png", "charts/chart-page-2.png")
    context = replace(
        context, authorized_write_paths=(context.script_path, *paths), declared_output_paths=paths
    )
    bad = (
        b"not png"
        if fault == "corrupt"
        else image_bytes(blank=fault == "blank", size=(1, 80) if fault == "tiny" else (120, 80))
    )
    runtime = StaticRuntime({paths[0]: image_bytes(), paths[1]: bad})
    with pytest.raises(ReportingError) as caught:
        await runner_for(runtime).run_standard_visualization(
            context, workspace, source_for(paths), {}, deterministic=True
        )
    assert code in str(caught.value.details)
    assert paths[1] in str(caught.value.details)
    assert runtime.closed == runtime.drained == [context.code_mode_session_id]


@pytest.mark.parametrize("failure", [None, RuntimeError("draw failed"), asyncio.CancelledError()])
async def test_static_cleanup_never_overwrites_result_error_or_cancellation(workspace, failure):
    context = _visualization_task_context(workspace)
    runtime = StaticRuntime(
        {"charts/chart.png": image_bytes()}, failure=failure, cleanup_failure=True
    )
    runner = runner_for(runtime)
    if failure is None:
        result = await runner.run_standard_visualization(
            context, workspace, source_for(context.declared_output_paths), {}, deterministic=True
        )
        assert result.execution_receipt.output_files
    else:
        with pytest.raises(type(failure)) as caught:
            await runner.run_standard_visualization(
                context,
                workspace,
                source_for(context.declared_output_paths),
                {},
                deterministic=True,
            )
        assert caught.value is failure
    assert runtime.closed == runtime.drained == [context.code_mode_session_id]
    assert runner.registry.active_count == 0


async def test_ai_standard_execution_still_requires_independent_visual_review(workspace):
    context = _visualization_task_context(workspace)
    runtime = StaticRuntime({"charts/chart.png": image_bytes()})
    runner = runner_for(runtime)
    runner.vision_reviewer = None
    with pytest.raises(ReportingError) as caught:
        await runner.run_standard_visualization(
            context, workspace, source_for(context.declared_output_paths), {}
        )
    assert "visual_review_unavailable" in str(caught.value.details)


async def test_standard_submission_requires_current_pixel_check_and_rejects_output_tampering(
    workspace,
):
    context = _visualization_task_context(workspace)
    runtime = StaticRuntime({"charts/chart.png": image_bytes()})
    binding = ReportingCodingTaskBinding(context, workspace)
    toolkit = ReportingCodeModeToolkit(
        binding, runtime, ReportingLspProcessManager(), deterministic_standard=True
    )
    assert (await toolkit.write_script(source_for(context.declared_output_paths)))["ok"]
    assert (await toolkit.run_script())["ok"]
    assert (await toolkit.submit_script())["code"] == "report_standard_image_inspection_required"
    assert (await toolkit.inspect_standard_images())["ok"]
    assert (await toolkit.submit_script())["ok"]
    assert not binding.visual_inspection_receipts
    await workspace.awrite_bytes(
        context.task_id, "charts/chart.png", image_bytes(size=(150, 90)), overwrite=True
    )
    assert (await toolkit.submit_script())["code"] == "report_code_output_modified_after_execution"
    with pytest.raises(ReportingError) as caught:
        await toolkit.require_current_receipt(binding.execution_receipt)
    assert caught.value.code == "report_phase_artifact_changed"


async def test_standard_pixel_check_is_not_an_ai_visual_review(workspace):
    context = _visualization_task_context(workspace)
    binding = ReportingCodingTaskBinding(context, workspace)
    toolkit = ReportingCodeModeToolkit(
        binding, StaticRuntime({"charts/chart.png": image_bytes()}), ReportingLspProcessManager()
    )
    assert (await toolkit.write_script(source_for(context.declared_output_paths)))["ok"]
    assert (await toolkit.run_script())["ok"]
    assert (await toolkit.inspect_standard_images())[
        "code"
    ] == "report_standard_inspection_forbidden"
    assert (await toolkit.submit_script())["code"] == "report_code_visual_review_required"
    assert not binding.visual_inspection_receipts


async def test_cancellation_during_standard_shutdown_remains_cancellation(workspace):
    entered = asyncio.Event()
    release = asyncio.Event()
    context = _visualization_task_context(workspace)
    runtime = StaticRuntime({"charts/chart.png": image_bytes()})

    async def shutdown(session_id):
        runtime.closed.append(session_id)
        entered.set()
        await release.wait()

    runtime.shutdown = shutdown
    runner = runner_for(runtime)
    task = asyncio.create_task(
        runner.run_standard_visualization(
            context, workspace, source_for(context.declared_output_paths), {}, deterministic=True
        )
    )
    await entered.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert runtime.closed == runtime.drained == [context.code_mode_session_id]
    assert runner.registry.active_count == 0


async def test_standard_result_checks_identity_after_session_shutdown(workspace):
    context = _visualization_task_context(workspace)
    runtime = StaticRuntime({"charts/chart.png": image_bytes()})

    async def shutdown(session_id):
        runtime.closed.append(session_id)
        await workspace.awrite_bytes(
            context.task_id, "charts/chart.png", image_bytes(size=(130, 90)), overwrite=True
        )

    runtime.shutdown = shutdown
    with pytest.raises(ReportingError) as caught:
        await runner_for(runtime).run_standard_visualization(
            context, workspace, source_for(context.declared_output_paths), {}, deterministic=True
        )
    assert caught.value.code == "report_phase_artifact_changed"
    assert runtime.closed == runtime.drained == [context.code_mode_session_id]


async def test_standard_span_drain_failure_keeps_successful_execution_receipt(workspace):
    context = _visualization_task_context(workspace)
    runtime = StaticRuntime({"charts/chart.png": image_bytes()})

    def drain(session_id):
        runtime.drained.append(session_id)
        raise RuntimeError("drain failed")

    runtime.drain_execution_spans = drain
    result = await runner_for(runtime).run_standard_visualization(
        context, workspace, source_for(context.declared_output_paths), {}, deterministic=True
    )
    assert result.execution_receipt.output_files
    assert result.execution_spans is None
    assert runtime.closed == runtime.drained == [context.code_mode_session_id]


@pytest.mark.parametrize("forms", [["line"], ["line", "bar"]])
async def test_direct_route_propagates_internal_policy_and_soft_warnings(
    tmp_path, monkeypatch, forms
):
    from smart_reporting.reporting.workflow.runtime import standard_chart_routing as routing

    plan, inputs, context = setup(tmp_path, forms)
    monkeypatch.setattr(
        routing,
        "standard_visualization_preflight",
        lambda *_: SimpleNamespace(
            source="trusted", diagnostic=None, warnings=({"code": "semantic_warning"},)
        ),
    )
    standard = AsyncMock(return_value=SimpleNamespace())
    coding = AsyncMock(side_effect=AssertionError("direct route called Coding"))
    result = await run_standard_chart_routes(
        SimpleNamespace(run_standard_visualization=standard, run=coding),
        context,
        object(),
        plan,
        inputs,
        {},
        object(),
        deterministic=True,
    )
    assert len(result.standard_chart_routes) == len(forms)
    assert all(
        route["warnings"] == [{"code": "semantic_warning"}]
        for route in result.standard_chart_routes
    )
    assert standard.await_args.kwargs == {"deterministic": True}
    coding.assert_not_called()


@pytest.mark.parametrize("fault", ["preflight", "execution", "layout", "pagination", "interactive"])
async def test_direct_route_failures_never_fall_back_to_any_model(tmp_path, monkeypatch, fault):
    from smart_reporting.reporting.workflow.runtime import standard_chart_routing as routing

    plan, inputs, context = setup(tmp_path, ["line", "bar"])
    if fault == "interactive":
        plan.charts[0].interactive_path = "legacy.plotly.json"
    diagnostic = {"code": "unsupported_parameter", "message": "不支持该参数"}

    def preflight(*_):
        if fault == "pagination":
            raise RuntimeError("pagination failed")
        return SimpleNamespace(
            source=None if fault == "preflight" else "trusted", diagnostic=diagnostic, warnings=()
        )

    monkeypatch.setattr(routing, "standard_visualization_preflight", preflight)
    error = ReportingError(
        "execution_failed",
        "draw failed",
        details={"standardDiagnostic": {"code": "standard_chart_layout_unresolved"}},
    )
    standard = AsyncMock(side_effect=error)
    coding = AsyncMock(side_effect=AssertionError("direct route called Coding"))
    with pytest.raises((ReportingError, RuntimeError)):
        await run_standard_chart_routes(
            SimpleNamespace(run_standard_visualization=standard, run=coding),
            context,
            object(),
            plan,
            inputs,
            {},
            object(),
            deterministic=True,
        )
    coding.assert_not_called()
    assert standard.await_count <= 1
