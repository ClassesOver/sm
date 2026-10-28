"""Isolate chart fallbacks while issuing one current, fully reviewed final receipt."""

from __future__ import annotations

import hashlib
import json
from dataclasses import is_dataclass, replace
from pathlib import PurePosixPath

from loguru import logger

from ...models import ReportingError
from .chart_inputs import ChartInputMaterialization
from .phase_models import StandardChartCanvas
from .standard_visualization import standard_visualization_preflight


async def run_standard_chart_routes(runner, context, workspace, plan, inputs, facts, run_context):
    """Fast path for a supported group; mixed groups isolate compilation and Coding.

    The final script rechecks all signed component sources, executes them in isolated
    namespaces and goes through the normal run/view/submit/current-receipt gates.
    Component image reviews never substitute for this final review.
    """
    if any(chart.renderer != "matplotlib" or chart.interactive_path for chart in plan.charts):
        # Keep the legacy delivery contract on its existing path. The new compositor
        # only accepts static charts; JSON companions must never enter image review.
        result = await runner.run(
            context, workspace, facts, run_context=run_context, diagnostic=None
        )
        return _with_routes(
            result,
            [
                dict(
                    chartId=chart.chart_id,
                    route="coding",
                    diagnostic=dict(
                        code="standard_static_group_required", message="旧交互计划保留原执行路径。"
                    ),
                )
                for chart in plan.charts
            ],
        )
    complete = standard_visualization_preflight(plan, inputs)
    if complete.source is not None:
        try:
            if len(plan.charts) == 1:
                result = await _run_standard_with_layout_retry(
                    runner, context, workspace, plan, inputs, facts
                )
            else:
                result = await runner.run_standard_visualization(
                    context, workspace, complete.source, facts
                )
            return _with_routes(
                result,
                [
                    dict(chartId=chart.chart_id, route="standard", diagnostic=None)
                    for chart in plan.charts
                ],
            )
        except Exception as error:
            if len(plan.charts) == 1:
                raise
            logger.warning("report_standard_group_retry_per_chart error={}", type(error).__name__)

    if len(plan.charts) == 1:
        diagnostic = _diagnostic(plan.charts[0].chart_id, complete.diagnostic)
        result = await runner.run(
            context,
            workspace,
            {**facts, "standardChartPreflight": diagnostic},
            run_context=run_context,
            diagnostic=None,
        )
        return _with_routes(
            result, [dict(chartId=plan.charts[0].chart_id, route="coding", diagnostic=diagnostic)]
        )

    components = []
    routes = []
    child_tasks = []
    for index, chart in enumerate(plan.charts):
        single = plan.model_copy(update={"charts": (chart,)})
        entries = tuple(entry for entry in inputs.entries if entry["chartId"] == chart.chart_id)
        paths = {entry["path"] for entry in entries}
        bound = ChartInputMaterialization(
            files=tuple(file for file in inputs.files if file.path in paths),
            entries=entries,
            fallback_chart_ids=inputs.fallback_chart_ids & {chart.chart_id},
        )
        preflight = standard_visualization_preflight(single, bound)
        path = str(
            PurePosixPath(context.script_path).with_name(
                PurePosixPath(context.script_path).stem + f"-chart-{index + 1:03}.py"
            )
        )
        outputs = tuple(path for path in (chart.source_path, chart.interactive_path) if path)
        child = replace(
            context,
            script_path=path,
            code_mode_session_id=context.code_mode_session_id + f":chart:{index + 1}",
            authorized_write_paths=(path, *outputs),
            declared_output_paths=outputs,
        )
        payload = {
            **facts,
            "visualizationPlan": single.model_dump(mode="json", by_alias=True),
            "chartInputs": list(entries),
            "visualizationWorkspace": {
                **facts.get("visualizationWorkspace", {}),
                "scriptPath": path,
            },
        }
        child_tasks.append((child, payload))
        diagnostic = _diagnostic(chart.chart_id, preflight.diagnostic)
        result = None
        route = "coding"
        if preflight.source is not None:
            try:
                result = await _run_standard_with_layout_retry(
                    runner, child, workspace, single, bound, payload
                )
                route = "standard"
            except Exception as error:
                details = error.details if isinstance(error, ReportingError) else {}
                review = details.get("standardDiagnostic") if isinstance(details, dict) else None
                diagnostic = review or _diagnostic(
                    chart.chart_id,
                    dict(
                        code="standard_execution_or_review_failed",
                        parameter="standardChart",
                        message="该图标准执行或独立视觉验收失败。",
                        suggestion="按该图诊断修复，保留其他图的标准方案。",
                        errorType=type(error).__name__,
                    ),
                )
        if result is None:
            if preflight.source is None:
                payload["standardChartPreflight"] = diagnostic
            result = await runner.run(
                child,
                workspace,
                payload,
                run_context=run_context,
                diagnostic=diagnostic if preflight.source is not None else None,
            )
        identity = result.script_file
        raw, _mime = await workspace.afile_bytes(context.task_id, identity.path)
        if hashlib.sha256(raw).hexdigest() != identity.sha256:
            raise ReportingError(
                "report_chart_component_identity_changed", "图表组件脚本身份已变化。"
            )
        components.append((identity.path, identity.sha256))
        routes.append(
            dict(
                chartId=chart.chart_id,
                route=route,
                diagnostic=diagnostic if route == "coding" else None,
            )
        )
        logger.info(
            "report_visualization_chart_route chart={} route={} diagnostic={}",
            chart.chart_id,
            route,
            (diagnostic or {}).get("code"),
        )

    final_context = replace(
        context,
        authorized_read_paths=tuple(
            sorted(
                {
                    *context.authorized_read_paths,
                    *(path for path, _digest in components),
                }
            )
        ),
    )
    for attempt in range(2):
        try:
            result = await runner.run_standard_visualization(
                final_context,
                workspace,
                _composite_source(components, inputs, routes),
                {**facts, "standardChartRoutes": routes},
            )
            return _with_routes(result, routes)
        except ReportingError as error:
            details = error.details if isinstance(error.details, dict) else {}
            diagnostic = details.get("standardDiagnostic")
            if not isinstance(diagnostic, dict):
                raise
            review_details = diagnostic.get("details", {})
            failed_path = review_details.get("path") if isinstance(review_details, dict) else None
            failed = [i for i, chart in enumerate(plan.charts) if chart.source_path == failed_path]
            if attempt or len(failed) != 1:
                raise
            index = failed[0]
            child, payload = child_tasks[index]
            # The previous signed component exists, so this is a repair request.
            result = await runner.run(
                child, workspace, payload, run_context=run_context, diagnostic=diagnostic
            )
            identity = result.script_file
            raw, _mime = await workspace.afile_bytes(context.task_id, identity.path)
            if hashlib.sha256(raw).hexdigest() != identity.sha256:
                raise ReportingError(
                    "report_chart_component_identity_changed", "修复组件身份已变化。"
                ) from error
            components[index] = (identity.path, identity.sha256)
            routes[index] = dict(
                chartId=plan.charts[index].chart_id, route="coding", diagnostic=diagnostic
            )
    raise AssertionError("Unreachable composite retry")


def _composite_source(components, inputs, routes):
    source = 'import hashlib\nfrom pathlib import Path\nimport matplotlib\nmatplotlib.use("Agg")\nimport matplotlib.pyplot as plt\n'
    # Preflight every dependency before executing any component.
    source += "COMPONENTS = " + repr(components) + "\n"
    source += "CHART_ROUTES = " + repr(routes) + "\n"
    source += (
        "CHART_INPUTS = "
        + repr([(entry["path"], entry["sha256"]) for entry in inputs.entries])
        + "\n"
    )
    source += """sources = []
for path, digest in CHART_INPUTS:
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
        raise ValueError("chart input identity changed")
for path, digest in COMPONENTS:
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("chart component identity changed")
    sources.append((path, raw))
for path, raw in sources:
    with plt.rc_context():
        plt.rcdefaults()
        exec(compile(raw, path, "exec"), {"__name__": "__main__", "__file__": path})
    plt.close("all")
"""
    return source


def _with_routes(result, routes):
    if is_dataclass(result) and not isinstance(result, type):
        return replace(result, standard_chart_routes=tuple(routes))
    result.standard_chart_routes = tuple(routes)
    return result


def _diagnostic(chart_id, diagnostic):
    if diagnostic is None:
        return None
    return {**diagnostic, "details": {"chartId": chart_id, **diagnostic}}


async def _run_standard_with_layout_retry(runner, context, workspace, plan, inputs, facts):
    current = plan
    for attempt in range(3):
        preflight = standard_visualization_preflight(current, inputs)
        if preflight.source is None:
            raise ReportingError(
                "report_standard_layout_retry_invalid",
                "布局候选未通过标准预检。",
                details={"standardDiagnostic": preflight.diagnostic},
            )
        try:
            return await runner.run_standard_visualization(
                context, workspace, preflight.source, facts
            )
        except Exception as error:
            # Only measured layout failures justify mechanical resizing. Semantic or
            # identity failures must retain their diagnosis and follow Coding repair.
            details = error.details if isinstance(error, ReportingError) else {}
            measured_layout_failure = "standard_chart_layout_unresolved" in json.dumps(
                details, ensure_ascii=False, default=str
            )
            chart = current.charts[0]
            canvas = getattr(chart, "standard_canvas", StandardChartCanvas())
            if attempt == 2 or not measured_layout_failure or canvas.size_mode != "auto":
                raise
            width, height = min(20, canvas.width * 1.2), min(24, canvas.height * 1.2)
            if (width, height) == (
                canvas.width,
                canvas.height,
            ) or width * height * canvas.dpi**2 > 24000000:
                raise
            updated_canvas = StandardChartCanvas.model_validate(
                {**canvas.model_dump(), "width": width, "height": height}
            )
            current = current.model_copy(
                update={"charts": (chart.model_copy(update={"standard_canvas": updated_canvas}),)}
            )
            logger.info(
                "report_standard_layout_retry chart={} attempt={} width={} height={}",
                chart.chart_id,
                attempt + 1,
                width,
                height,
            )
    raise AssertionError("Unreachable layout retry")
