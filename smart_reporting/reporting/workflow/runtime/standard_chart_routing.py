"""Isolate chart fallbacks while issuing one current, fully reviewed final receipt."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import is_dataclass, replace
from pathlib import PurePosixPath
from time import perf_counter

from loguru import logger

from ...models import ReportingError
from .chart_inputs import ChartInputMaterialization
from .phase_models import StandardChartCanvas
from .standard_chart_proof import create_standard_render_proofs
from .standard_visualization import standard_visualization_preflight


async def run_standard_chart_routes(
    runner, context, workspace, plan, inputs, facts, run_context, *, deterministic=False
):
    """记录完整路由边界，包括首次编译及失败/取消，不改变原异常。"""
    started = perf_counter()
    route_state = {"initialCompileMs": 0, "initialCompileStatus": "not_started"}
    try:
        result = await _run_standard_chart_routes(
            runner, context, workspace, plan, inputs, facts, run_context,
            deterministic=deterministic, route_state=route_state,
        )
    except BaseException as error:
        attempts = getattr(error, "standard_execution_attempts", ())
        observations = attempts or (getattr(error, "standard_execution", {}),)
        timings = {}
        spans = {}
        for observation in observations:
            for name, elapsed in observation.get("stageTimings", {}).items():
                timings[name] = timings.get(name, 0) + elapsed
            observed_spans = observation.get("executionSpans")
            if isinstance(observed_spans, Mapping):
                for name, values in observed_spans.items():
                    spans.setdefault(name, []).extend(values)
        timings["compile"] = timings.get("compile", 0) + route_state["initialCompileMs"]
        total = max(0, round((perf_counter() - started) * 1000))
        observation = {
            **route_state, "status": "cancelled" if isinstance(error, asyncio.CancelledError) else "failed",
            "stageTimings": timings, "executionSpans": spans or None, "routeTotalMs": total,
        }
        error.standard_route_total_ms = total
        error.standard_route_execution = observation
        if isinstance(error, ReportingError):
            details = (dict(error.details) if isinstance(error.details, Mapping) else
                       {} if error.details is None else {"originalDetails": error.details})
            error.details = {**details, "standardRouteExecution": observation, "standardRouteTotalMs": total}
        logger.bind(standard_route_execution=observation).info(
            "report_standard_route_finished status={} route_total_ms={} initial_compile_ms={}",
            observation["status"], total, route_state["initialCompileMs"],
        )
        raise
    total = max(0, round((perf_counter() - started) * 1000))
    if is_dataclass(result) and not isinstance(result, type):
        return replace(result, route_total_ms=total)
    result.route_total_ms = total
    return result


async def _run_standard_chart_routes(
    runner, context, workspace, plan, inputs, facts, run_context, *, deterministic, route_state
):
    """Fast path for a supported group; mixed groups isolate compilation and Coding.

    The final script rechecks all signed component sources, executes them in isolated
    namespaces and goes through the normal run/view/submit/current-receipt gates.
    Component image reviews never substitute for this final review.
    """
    route_started = perf_counter()
    if deterministic:
        # 只接服务端编译源码；任何诊断或执行异常均不得进入模型回退。
        try:
            compile_started = perf_counter()
            route_state["initialCompileStatus"] = "failed"
            try:
                complete = standard_visualization_preflight(plan, inputs)
            finally:
                compile_ms = max(0, round((perf_counter() - compile_started) * 1000))
                route_state["initialCompileMs"] = compile_ms
        except Exception as error:
            raise ReportingError(
                "report_standard_preflight_failed",
                "标准预检未能完成，原图保持不变。",
                details={"errorType": type(error).__name__, "reason": str(error)[:512]},
            ) from error
        if complete.source is None:
            raise ReportingError(
                "report_standard_preflight_rejected",
                "该参数不适用于确定性模板，原图保持不变。",
                details={"standardDiagnostic": complete.diagnostic},
            )
        route_state["initialCompileStatus"] = "succeeded"
        if len(plan.charts) == 1:
            result = await _run_standard_with_layout_retry(
                runner, context, workspace, plan, inputs, facts, deterministic=True
            )
        else:
            result = await runner.run_standard_visualization(
                context, workspace, complete.source, facts, deterministic=True
            )
            result = _with_standard_proofs(result, plan, inputs)
        result = _with_compile_timing(result, compile_ms, route_started)
        return _with_routes(result, [
            dict(chartId=chart.chart_id, route="standard", diagnostic=None,
                 warnings=_chart_warnings(complete, chart.chart_id))
            for chart in plan.charts
        ])
    compile_started = perf_counter()
    route_state["initialCompileStatus"] = "failed"
    try:
        complete = standard_visualization_preflight(plan, inputs)
    finally:
        compile_ms = max(0, round((perf_counter() - compile_started) * 1000))
        route_state["initialCompileMs"] = compile_ms
    route_state["initialCompileStatus"] = "succeeded" if complete.source is not None else "failed"
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
                result = _with_standard_proofs(result, plan, inputs)
            return _with_routes(
                _with_compile_timing(result, compile_ms, route_started),
                [
                    dict(chartId=chart.chart_id, route="standard", diagnostic=None,
                         warnings=_chart_warnings(complete, chart.chart_id))
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
    component_proofs = {}
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
        outputs = (chart.source_path,)
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
                        errorMessage=str(error)[:500],
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
        if route == 'standard':
            component_proofs[chart.chart_id] = getattr(result, 'standard_render_proofs', ())
        routes.append(
            dict(
                chartId=chart.chart_id,
                route=route,
                diagnostic=diagnostic if route == "coding" else None,
                warnings=_chart_warnings(preflight, chart.chart_id) if route == "standard" else [],
            )
        )
        logger.info(
            "report_visualization_chart_route chart={} route={} diagnostic={} details={}",
            chart.chart_id,
            route,
            (diagnostic or {}).get("code"),
            json.dumps(diagnostic, ensure_ascii=False, default=str)[:2000] if diagnostic else "-",
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
                _composite_source(components, inputs, routes, context.declared_output_paths),
                {**facts, "standardChartRoutes": routes},
            )
            # 组合脚本会重画所有组件。只在最终图片仍与真实标准执行逐字节一致时保留证明。
            receipt = getattr(result, 'execution_receipt', None)
            outputs = {item.path: item.sha256 for item in getattr(receipt, 'output_files', ())}
            proofs = tuple(record for chart in plan.charts
                           for record in component_proofs.get(chart.chart_id, ())
                           if record['proof'].image_sha256 == outputs.get(chart.source_path))
            return _with_routes(_with_standard_proofs(result, plan, inputs, proofs=proofs), routes)
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
            component_proofs.pop(plan.charts[index].chart_id, None)
            routes[index] = dict(
                chartId=plan.charts[index].chart_id, route="coding", diagnostic=diagnostic
            )
    raise AssertionError("Unreachable composite retry")


def _composite_source(components, inputs, routes, output_paths):
    source = 'import hashlib\nfrom pathlib import Path\nimport matplotlib\nmatplotlib.use("Agg")\nimport matplotlib.pyplot as plt\n'
    # Preflight every dependency before executing any component.
    source += "COMPONENTS = " + repr(components) + "\n"
    source += "CHART_ROUTES = " + repr(routes) + "\n"
    source += "OUTPUT_PATHS = " + repr(tuple(output_paths)) + "\n"
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
for path in OUTPUT_PATHS:
    Path(path).unlink(missing_ok=True)
# rc_context在每个组件后恢复进入前的项目主题（matplotlibrc及启动引导），
# 使组件与其单独执行、视觉验收时的状态一致；不能rcdefaults回到库内置默认。
for path, raw in sources:
    with plt.rc_context():
        exec(compile(raw, path, "exec"), {"__name__": "__main__", "__file__": path})
    plt.close("all")
for path in OUTPUT_PATHS:
    if not Path(path).is_file():
        raise ValueError("chart component output missing: " + path)
"""
    return source


def _with_routes(result, routes):
    if is_dataclass(result) and not isinstance(result, type):
        return replace(result, standard_chart_routes=tuple(routes))
    result.standard_chart_routes = tuple(routes)
    return result


def _with_standard_proofs(result, plan, inputs, *, proofs=None):
    if proofs is None:
        proofs = create_standard_render_proofs(result, plan, inputs)
    if is_dataclass(result) and not isinstance(result, type):
        return replace(result, standard_render_proofs=proofs)
    result.standard_render_proofs = proofs
    return result


def _chart_warnings(preflight, chart_id):
    return [item for item in getattr(preflight, "warnings", ())
            if not isinstance(item, dict) or not item.get("chartId") or item["chartId"] == chart_id]


def _with_compile_timing(result, elapsed_ms, route_started=None):
    timings = dict(getattr(result, "stage_timings", {}) or {})
    timings["compile"] = timings.get("compile", 0) + elapsed_ms
    updates = {"stage_timings": timings}
    if route_started is not None:
        updates["route_total_ms"] = max(0, round((perf_counter() - route_started) * 1000))
    if is_dataclass(result) and not isinstance(result, type):
        return replace(result, **updates)
    for key, value in updates.items():
        setattr(result, key, value)
    return result


def _diagnostic(chart_id, diagnostic):
    if diagnostic is None:
        return None
    return {**diagnostic, "details": {"chartId": chart_id, **diagnostic}}


async def _run_standard_with_layout_retry(
    runner, context, workspace, plan, inputs, facts, *, deterministic=False
):
    current = plan
    route_started = perf_counter()
    attempts = []
    for attempt in range(3):
        attempt_started = perf_counter()
        compile_started = perf_counter()
        compile_ms = 0
        compiled = False
        result = None
        attempt_error = None
        try:
            try:
                preflight = standard_visualization_preflight(current, inputs)
            finally:
                compile_ms = max(0, round((perf_counter() - compile_started) * 1000))
            if preflight.source is None:
                raise ReportingError(
                    "report_standard_layout_retry_invalid",
                    "布局候选未通过标准预检。",
                    details={"standardDiagnostic": preflight.diagnostic},
                )
            compiled = True
            result = await runner.run_standard_visualization(
                context, workspace, preflight.source, facts,
                **({"deterministic": True} if deterministic else {}),
            )
        except BaseException as error:
            attempt_error = error
        finally:
            recorded = (getattr(result, "execution_attempts", ()) or ()) if result is not None else ()
            observation = dict(recorded[-1] if recorded else getattr(attempt_error, "standard_execution", {}) or {})
            timings = dict(observation.get("stageTimings", {}))
            timings["compile"] = timings.get("compile", 0) + compile_ms
            statuses = dict(observation.get("stageStatuses", {}))
            statuses["compile"] = "succeeded" if compiled else "failed"
            observation.update(
                attempt=attempt + 1, stageTimings=timings, stageStatuses=statuses,
                durationMs=max(0, round((perf_counter() - attempt_started) * 1000)),
            )
            if not compiled:
                observation["failedStage"] = "compile"
            observation.setdefault("status", "cancelled" if isinstance(attempt_error, asyncio.CancelledError) else "failed" if attempt_error is not None else "succeeded")
            attempts.append(observation)
            route_total = max(0, round((perf_counter() - route_started) * 1000))
            if attempt_error is not None:
                attempt_error.standard_execution_attempts = tuple(attempts)
                attempt_error.standard_route_total_ms = route_total
                if isinstance(attempt_error, ReportingError):
                    details = (dict(attempt_error.details) if isinstance(attempt_error.details, Mapping) else
                               {} if attempt_error.details is None else {"originalDetails": attempt_error.details})
                    attempt_error.details = {**details, "standardExecutionAttempts": list(attempts), "standardRouteTotalMs": route_total}
            logger.bind(standard_execution_attempts=tuple(attempts), route_total_ms=route_total).info(
                "report_standard_layout_attempt chart={} attempt={} status={} duration_ms={} route_total_ms={}",
                current.charts[0].chart_id, attempt + 1, observation["status"], observation["durationMs"], route_total,
            )
        if result is not None:
            timings = {}
            spans = {}
            for observation in attempts:
                for name, elapsed in observation.get("stageTimings", {}).items():
                    timings[name] = timings.get(name, 0) + elapsed
                observed_spans = observation.get("executionSpans")
                if isinstance(observed_spans, dict):
                    for name, values in observed_spans.items():
                        spans.setdefault(name, []).extend(values)
            result = _with_standard_proofs(result, current, inputs)
            updates = dict(execution_attempts=tuple(attempts), route_total_ms=route_total,
                           stage_timings=timings, execution_spans=spans or None)
            if is_dataclass(result) and not isinstance(result, type):
                return replace(result, **updates)
            for key, value in updates.items():
                setattr(result, key, value)
            return result

        # 只有真实测量的布局失败才允许机械扩容；其他错误保持原异常。
        try:
            raise attempt_error
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
