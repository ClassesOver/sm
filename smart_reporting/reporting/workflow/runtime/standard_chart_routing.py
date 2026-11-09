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

from ....workspace import WorkspacePathConflict
from ...code_agent.context import ExecutionReceipt
from ...models import ReportingError
from .chart_inputs import ChartInputMaterialization
from .phase_models import StandardChartCanvas
from .standard_chart_proof import create_standard_render_proofs
from .standard_visualization import StandardVisualizationPreflight, standard_visualization_preflight


async def _observe_route_call(state, phase, chart_ids, operation):
    """保留每次真实调用，失败及取消不覆盖先前成功成本。"""
    started = perf_counter()
    result = error = None
    try:
        result = await operation
        return result
    except BaseException as caught:
        error = caught
        raise
    finally:
        attempts = (getattr(result, "execution_attempts", ()) if result is not None else
                    getattr(error, "standard_execution_attempts", ()))
        if not attempts:
            observation = (getattr(error, "standard_execution", None) if error is not None else None)
            attempts = (observation or {
                "stageTimings": dict(getattr(result, "stage_timings", None) or {}),
                "executionSpans": getattr(result, "execution_spans", None),
                "status": "cancelled" if isinstance(error, asyncio.CancelledError) else
                          "failed" if error is not None else "succeeded",
            },)
        elapsed = max(0, round((perf_counter() - started) * 1000))
        for item in attempts:
            state["executionAttempts"].append({**item, "routePhase": phase,
                "chartIds": list(chart_ids), "durationMs": item.get("durationMs", elapsed)})


def _merge_execution_spans(spans, observed):
    """任一尝试缺少阶段证据时保留unknown，不能把字符串展开成字符。"""
    if isinstance(observed, Mapping):
        for name, values in observed.items():
            if not isinstance(values, (list, tuple)):
                spans[name] = "unknown"
            elif spans.get(name) != "unknown":
                spans.setdefault(name, []).extend(values)


def _route_observation(state, total, status):
    timings, spans = {}, {}
    spans_complete = True
    for item in state["executionAttempts"]:
        for name, elapsed in item.get("stageTimings", {}).items():
            timings[name] = timings.get(name, 0) + elapsed
        observed = item.get("executionSpans")
        spans_complete = spans_complete and isinstance(observed, Mapping)
        _merge_execution_spans(spans, observed)
    timings["compile"] = timings.get("compile", 0) + state["initialCompileMs"] + state["componentCompileMs"]
    return {**state, "status": status, "stageTimings": timings,
            "executionSpans": (spans or None) if spans_complete else "unknown", "routeTotalMs": total}


async def run_standard_chart_routes(
    runner, context, workspace, plan, inputs, facts, run_context, *, deterministic=False
):
    """墙钟与全尝试累计分别记录；观测不替代真实执行/视觉回执。"""
    started = perf_counter()
    state = {"initialCompileMs": 0, "initialCompileStatus": "not_started",
             "componentCompileMs": 0, "executionAttempts": [], "routes": []}
    try:
        result = await _run_standard_chart_routes(
            runner, context, workspace, plan, inputs, facts, run_context,
            deterministic=deterministic, route_state=state,
        )
    except BaseException as error:
        total = max(0, round((perf_counter() - started) * 1000))
        observation = _route_observation(state, total,
            "cancelled" if isinstance(error, asyncio.CancelledError) else "failed")
        error.standard_route_total_ms = total
        error.standard_route_execution = observation
        error.standard_execution_attempts = tuple(state["executionAttempts"])
        error.standard_chart_routes = tuple(state["routes"])
        if isinstance(error, ReportingError):
            details = (dict(error.details) if isinstance(error.details, Mapping) else
                       {} if error.details is None else {"originalDetails": error.details})
            error.details = {**details, "standardRouteExecution": observation, "standardRouteTotalMs": total}
        logger.bind(standard_route_execution=observation).info(
            "report_standard_route_finished status={} route_total_ms={} initial_compile_ms={}",
            observation["status"], total, state["initialCompileMs"],
        )
        raise
    total = max(0, round((perf_counter() - started) * 1000))
    observation = _route_observation(state, total, "succeeded")
    updates = dict(route_total_ms=total, stage_timings=observation["stageTimings"],
                   execution_spans=observation["executionSpans"],
                   execution_attempts=tuple(state["executionAttempts"]))
    if is_dataclass(result) and not isinstance(result, type):
        return replace(result, **updates)
    for name, value in updates.items():
        setattr(result, name, value)
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
            result = await _observe_route_call(route_state, 'group', [chart.chart_id for chart in plan.charts], _run_standard_with_layout_retry(
                runner, context, workspace, plan, inputs, facts, deterministic=True,
                initial_preflight=complete))
        else:
            result = await _observe_route_call(route_state, 'group', [chart.chart_id for chart in plan.charts], runner.run_standard_visualization(
                context, workspace, complete.source, facts, deterministic=True
            ))
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
                result = await _observe_route_call(route_state, 'group', [chart.chart_id for chart in plan.charts], _run_standard_with_layout_retry(
                    runner, context, workspace, plan, inputs, facts,
                    initial_preflight=complete))
            else:
                result = await _observe_route_call(route_state, 'group', [chart.chart_id for chart in plan.charts], runner.run_standard_visualization(
                    context, workspace, complete.source, facts
                ))
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
        result = await _observe_route_call(route_state, 'component_coding', [chart.chart_id for chart in plan.charts], runner.run(
            context,
            workspace,
            {**facts, "standardChartPreflight": diagnostic},
            run_context=run_context,
            diagnostic=None,
        ))
        return _with_routes(
            result, [dict(chartId=plan.charts[0].chart_id, route="coding", diagnostic=diagnostic)]
        )

    components = []
    snapshots = {}
    component_proofs = {}
    routes = route_state["routes"]
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
        compile_started = perf_counter()
        try:
            preflight = standard_visualization_preflight(single, bound)
        finally:
            route_state["componentCompileMs"] += max(0, round((perf_counter() - compile_started) * 1000))
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
                result = await _observe_route_call(route_state, 'component_standard', [chart.chart_id], _run_standard_with_layout_retry(
                    runner, child, workspace, single, bound, payload,
                    initial_preflight=preflight))
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
            result = await _observe_route_call(route_state, 'component_coding', [chart.chart_id], runner.run(
                child,
                workspace,
                payload,
                run_context=run_context,
                diagnostic=diagnostic if preflight.source is not None else None,
            ))
        identity = result.script_file
        raw, _mime = await workspace.afile_bytes(context.task_id, identity.path)
        if hashlib.sha256(raw).hexdigest() != identity.sha256:
            raise ReportingError(
                "report_chart_component_identity_changed", "图表组件脚本身份已变化。"
            )
        components.append((identity.path, identity.sha256))
        snapshot = await _snapshot_component(workspace, context, chart, result)
        if snapshot is not None:
            snapshots[identity.path] = snapshot
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

    for attempt in range(2):
        final_context = replace(context, authorized_read_paths=tuple(sorted({
            *context.authorized_read_paths, *(path for path, _digest in components),
            *(snapshot[1] for snapshot in snapshots.values()),
        })))
        try:
            result = await _observe_route_call(route_state, 'final', [chart.chart_id for chart in plan.charts], runner.run_standard_visualization(
                final_context,
                workspace,
                _composite_source(components, inputs, routes, context.declared_output_paths, snapshots=snapshots),
                {**facts, "standardChartRoutes": routes},
            ))
            # 复用和兼容重绘都须与最终新回执逐字节一致，不能沿用组件的视觉回执。
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
            failed_path = (review_details.get("sourcePath") or review_details.get("path")) if isinstance(review_details, dict) else None
            failed = [i for i, chart in enumerate(plan.charts) if chart.source_path == failed_path]
            if attempt or len(failed) != 1:
                raise
            index = failed[0]
            child, payload = child_tasks[index]
            # The previous signed component exists, so this is a repair request.
            result = await _observe_route_call(route_state, 'component_repair', [plan.charts[index].chart_id], runner.run(
                child, workspace, payload, run_context=run_context, diagnostic=diagnostic
            ))
            identity = result.script_file
            raw, _mime = await workspace.afile_bytes(context.task_id, identity.path)
            if hashlib.sha256(raw).hexdigest() != identity.sha256:
                raise ReportingError(
                    "report_chart_component_identity_changed", "修复组件身份已变化。"
                ) from error
            components[index] = (identity.path, identity.sha256)
            snapshot = await _snapshot_component(workspace, context, plan.charts[index], result)
            snapshots.pop(identity.path, None)
            if snapshot is not None:
                snapshots[identity.path] = snapshot
            component_proofs.pop(plan.charts[index].chart_id, None)
            routes[index] = dict(
                chartId=plan.charts[index].chart_id, route="coding", diagnostic=diagnostic
            )
    raise AssertionError("Unreachable composite retry")


async def _snapshot_component(workspace, context, chart, result):
    """仅将当前真实执行回执指向的图片保存为不可覆盖、带SHA的宿主快照。"""
    receipt = getattr(result, 'execution_receipt', None)
    if not isinstance(receipt, ExecutionReceipt):
        return None  # 旧runner没有结构化回执，仍走原有组件重绘。
    outputs = [item for item in receipt.output_files if item.path == chart.source_path]
    if receipt.source_file != result.script_file or len(outputs) != 1:
        raise ReportingError('report_chart_component_receipt_invalid', '图表组件执行回执身份不一致。')
    output = outputs[0]
    raw, _mime = await workspace.afile_bytes(context.task_id, output.path)
    if len(raw) != output.size or hashlib.sha256(raw).hexdigest() != output.sha256:
        raise ReportingError('report_chart_component_image_changed', '图表组件图片在执行后发生变化。')
    path = str(PurePosixPath(result.script_file.path).with_name(
        f'{PurePosixPath(result.script_file.path).stem}-image-{output.sha256}{PurePosixPath(output.path).suffix}'))
    try:
        await workspace.awrite_bytes(context.task_id, path, raw, overwrite=False)
    except WorkspacePathConflict:
        existing, _mime = await workspace.afile_bytes(context.task_id, path)
        if existing != raw:
            raise ReportingError('report_chart_component_snapshot_changed', '已登记的图表图片快照身份已变化。')
    return output.path, path, output.sha256


def _composite_source(components, inputs, routes, output_paths, *, snapshots=None):
    snapshots = snapshots or {}
    source = 'import hashlib\nfrom pathlib import Path\nimport matplotlib\nmatplotlib.use("Agg")\nimport matplotlib.pyplot as plt\n'
    # Preflight every dependency before executing any component.
    source += "COMPONENTS = " + repr(components) + "\n"
    source += "CHART_ROUTES = " + repr(routes) + "\n"
    source += "OUTPUT_PATHS = " + repr(tuple(output_paths)) + "\n"
    source += "SNAPSHOTS = " + repr([(path, digest) for _output, path, digest in snapshots.values()]) + "\n"
    source += (
        "CHART_INPUTS = "
        + repr([(entry["path"], entry["sha256"]) for entry in inputs.entries])
        + "\n"
    )
    source += """sources = {}
for path, digest in CHART_INPUTS:
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
        raise ValueError("chart input identity changed")
for path, digest in COMPONENTS:
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("chart component identity changed")
    sources[path] = raw
images = {}
for path, digest in SNAPSHOTS:
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("chart image snapshot identity changed")
    images[path] = raw
for path in OUTPUT_PATHS:
    Path(path).unlink(missing_ok=True)
"""
    # rc_context在每个组件后恢复项目主题，与组件单独执行、视觉验收时一致。
    for path, _digest in components:
        if path in snapshots:
            output, snapshot, _digest = snapshots[path]
            source += f'Path({output!r}).write_bytes(images[{snapshot!r}])\n'
        else:
            source += f'path = {path!r}\n' + '''\
raw = sources[path]
with plt.rc_context():
    exec(compile(raw, path, "exec"), {"__name__": "__main__", "__file__": path})
plt.close("all")
'''
    source += """for path in OUTPUT_PATHS:
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
    runner, context, workspace, plan, inputs, facts, *, deterministic=False,
    initial_preflight: StandardVisualizationPreflight | None = None,
):
    """仅复用同次调用、同一计划/输入的预检；扩容候选与产物证明仍重新编译。"""
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
            if attempt == 0 and initial_preflight is not None:
                # 同次路由刚完成的预检；耗时由外层登记，不重复编译或累计。
                preflight = initial_preflight
            else:
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
                _merge_execution_spans(spans, observed_spans)
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
