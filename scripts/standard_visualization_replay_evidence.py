"""Separate actual online planning evidence from persisted-plan route replays.

This is a replay diagnostic, not a publication gate or a numerical/visual oracle.
Only current workspace bytes and current execution/review receipts count.
"""

import hashlib
import json


def standard_replay_readiness(environment, *, default_base_url_available=True):
    """Presence only: no endpoints, credential values, files, or network requests."""
    key = bool((environment.get("OPENAI_API_KEY") or "").strip())
    endpoint = bool((environment.get("OPENAI_BASE_URL") or "").strip())
    configured = key and (endpoint or default_base_url_available)
    return {
        "status": "configured_not_probed" if configured else "blocked_missing_model_configuration",
        "configurationPresence": {"OPENAI_API_KEY": key, "OPENAI_BASE_URL": endpoint},
        "baseUrlSource": "environment" if endpoint else "application_default" if default_base_url_available else "missing",
        "modelRequestsExecuted": 0,
        "onlinePlannerValidated": False,
        "codingRepairValidated": False,
        "independentVisualReviewValidated": False,
        "onlineAcceptedStandardFraction": None,
    }


async def collect_standard_replay_evidence(
    *, plan, inputs, result, workspace, task_id, planner_origin, planner_request_metrics
):
    charts = list(plan.charts)
    ids = [chart.chart_id for chart in charts]
    paths = [chart.source_path for chart in charts]
    issues = []
    routes = list(getattr(result, "standard_chart_routes", ()))
    route_ids = [route.get("chartId") for route in routes]
    if not charts or len(set(ids)) != len(ids) or len(set(paths)) != len(paths):
        issues.append("planned_charts_empty_or_duplicated")
    if sorted(map(str, route_ids)) != sorted(map(str, ids)) or len(set(route_ids)) != len(route_ids):
        issues.append("routes_do_not_cover_exact_plan")
    if any(route.get("route") not in {"standard", "coding"} for route in routes):
        issues.append("unknown_route")
    bound = {entry["chartId"] for entry in inputs.entries}
    if any(route.get("route") == "standard" and route.get("chartId") not in bound for route in routes):
        issues.append("standard_route_without_bound_input")
    receipt = result.execution_receipt
    outputs = list(receipt.output_files)
    output_paths = [item.path for item in outputs]
    if sorted(output_paths) != sorted(paths) or len(set(output_paths)) != len(output_paths):
        issues.append("execution_outputs_do_not_cover_exact_plan")
    if not receipt.run_id or receipt.source_file != result.script_file:
        issues.append("execution_receipt_not_current_script")
    identities = []

    async def verify(path, expected_sha, expected_size, role):
        try:
            content, _ = await workspace.afile_bytes(task_id, path)
        except Exception as error:
            issues.append(f"{role}_unreadable:{type(error).__name__}")
            return
        digest = hashlib.sha256(content).hexdigest()
        matches = digest == expected_sha and (expected_size is None or len(content) == expected_size)
        identities.append(dict(path=path, role=role, sha256=digest, size=len(content), verified=matches))
        if not matches:
            issues.append(f"{role}_identity_changed")

    for source in inputs.files:
        await verify(source.path, source.sha256, len(source.content), "chart_input")
    file_hashes = {source.path: source.sha256 for source in inputs.files}
    for entry in inputs.entries:
        if entry["chartId"] not in ids or file_hashes.get(entry["path"]) != entry["sha256"]:
            issues.append("binding_identity_mismatch")
    for item in [receipt.source_file, *outputs]:
        await verify(item.path, item.sha256, item.size, "script" if item is receipt.source_file else "image")
    reviews = list(result.visual_inspection_receipts)
    vision_validated = bool(outputs) and all(
        any(review.source_path == output.path and review.sha256 == output.sha256
            and review.inspection_mode == "vision" and review.visual_review_status == "passed"
            and review.reviewed and not review.requires_revision and bool(review.model_id)
            for review in reviews)
        for output in outputs
    )
    model_planned = planner_origin == "live_model" and bool(planner_request_metrics) and all(
        metric.get("status") == "completed" for metric in planner_request_metrics
    )
    standard_count = sum(route.get("route") == "standard" for route in routes)
    complete = not issues
    observed_fraction = standard_count / len(charts) if complete and charts else None
    online_validated = complete and model_planned and vision_validated
    return {
        "schemaVersion": 1,
        "status": "complete" if complete else "incomplete",
        "plannerOrigin": planner_origin,
        "plannerProviderRequests": len(planner_request_metrics),
        "onlinePlannerValidated": model_planned,
        "inputAndOutputIdentitiesValidated": complete,
        "independentVisualReviewValidated": vision_validated,
        "independentNumericGeometryValidated": False,
        "numericGeometryStatus": "not_evaluated_by_route_replay",
        "plannedCharts": len(charts),
        "standardCharts": standard_count,
        "codingCharts": sum(route.get("route") == "coding" for route in routes),
        "observedStandardRouteFraction": observed_fraction,
        "onlineAcceptedStandardFraction": observed_fraction if online_validated else None,
        "onlineEndToEndValidated": online_validated,
        "planSha256": hashlib.sha256(json.dumps(
            plan.model_dump(mode="json", by_alias=True), ensure_ascii=False, sort_keys=True,
        ).encode()).hexdigest(),
        "executionRunId": receipt.run_id,
        "identities": identities,
        "issues": sorted(set(issues)),
    }
