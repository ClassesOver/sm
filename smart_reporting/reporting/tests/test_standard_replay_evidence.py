import hashlib
from types import SimpleNamespace as NS

import pytest

from scripts.standard_visualization_replay_evidence import (
    collect_standard_replay_evidence,
    standard_replay_readiness,
)


@pytest.mark.parametrize("env,default,configured", [({}, True, False), ({"OPENAI_API_KEY": "   "}, True, False),
    ({"OPENAI_API_KEY": "secret-marker"}, True, True), ({"OPENAI_API_KEY": "secret-marker"}, False, False),
    ({"OPENAI_API_KEY": "secret-marker", "OPENAI_BASE_URL": "endpoint-marker"}, False, True)])
def test_readiness_uses_application_endpoint_default_and_never_outputs_values(env, default, configured):
    evidence = standard_replay_readiness(env, default_base_url_available=default)
    assert (evidence["status"] == "configured_not_probed") is configured
    assert evidence["modelRequestsExecuted"] == 0 and not evidence["onlinePlannerValidated"]
    assert "secret-marker" not in str(evidence) and "endpoint-marker" not in str(evidence)


@pytest.fixture
def evidence_case():
    content = {"input.json": b'{"rows":[["A",10],["B",1000]]}', "render.py": b"plot frozen input"}
    # Real static image bytes, not a filename/receipt-only success.
    from io import BytesIO

    from matplotlib.figure import Figure

    figure = Figure(figsize=(4, 3))
    figure.subplots().bar(["A", "B"], [10, 1000])
    buffer = BytesIO()
    figure.savefig(buffer, format="png")
    content["a.png"] = content["b.png"] = buffer.getvalue()

    def identity(path):
        return NS(path=path, size=len(content[path]), sha256=hashlib.sha256(content[path]).hexdigest())

    async def read(task_id, path):
        return content[path], "application/octet-stream"

    script = identity("render.py")
    outputs = [identity("a.png"), identity("b.png")]
    plan = NS(charts=[NS(chart_id="a", source_path="a.png"), NS(chart_id="b", source_path="b.png")],
              model_dump=lambda **kwargs: {"charts": [{"chartId": "a"}, {"chartId": "b"}]})
    source = NS(path="input.json", content=content["input.json"], sha256=identity("input.json").sha256)
    result = NS(script_file=script, execution_receipt=NS(run_id="current", source_file=script, output_files=outputs),
                standard_chart_routes=[{"chartId": "a", "route": "standard"}, {"chartId": "b", "route": "coding"}],
                visual_inspection_receipts=[NS(source_path=output.path, sha256=output.sha256, inspection_mode="vision",
                    visual_review_status="passed", reviewed=True, requires_revision=False, model_id="independent-test") for output in outputs])
    args = dict(plan=plan, inputs=NS(files=[source], entries=[{"chartId": "a", "path": "input.json", "sha256": source.sha256}]),
                result=result, workspace=NS(afile_bytes=read), task_id="task", planner_origin="live_model",
                planner_request_metrics=[{"status": "completed"}])
    return args, content


@pytest.mark.anyio
async def test_live_evidence_uses_whole_plan_denominator_and_current_bytes(evidence_case):
    args, _ = evidence_case
    evidence = await collect_standard_replay_evidence(**args)
    assert evidence["status"] == "complete"
    assert evidence["plannedCharts"] == 2
    assert evidence["onlineAcceptedStandardFraction"] == .5
    assert evidence["onlineEndToEndValidated"]
    assert len(evidence["identities"]) == 4 and all(item["verified"] for item in evidence["identities"])
    assert not evidence["independentNumericGeometryValidated"]


@pytest.mark.anyio
@pytest.mark.parametrize("origin", ["persisted_plan", "coding_only"])
async def test_saved_or_manual_plan_never_counts_as_online_model_planning(evidence_case, origin):
    args, _ = evidence_case
    args["planner_origin"] = origin
    evidence = await collect_standard_replay_evidence(**args)
    assert evidence["observedStandardRouteFraction"] == .5
    assert evidence["onlineAcceptedStandardFraction"] is None
    assert not evidence["onlinePlannerValidated"] and not evidence["onlineEndToEndValidated"]


@pytest.mark.anyio
@pytest.mark.parametrize("metrics", [[], [{"status": "failed"}], [{"status": "started"}], [{"status": "completed"}, {"status": "failed"}]])
async def test_unproven_planner_request_cannot_report_online_hit_rate(evidence_case, metrics):
    args, _ = evidence_case
    args["planner_request_metrics"] = metrics
    evidence = await collect_standard_replay_evidence(**args)
    assert evidence["onlineAcceptedStandardFraction"] is None
    assert not evidence["onlinePlannerValidated"]


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["input", "image", "script", "missing_file", "binding", "routes_missing", "routes_duplicate", "routes_foreign", "outputs", "current_script", "unbound"])
async def test_changed_or_incomplete_evidence_never_inflates_standard_hit_rate(evidence_case, fault):
    args, content = evidence_case
    result, inputs = args["result"], args["inputs"]
    if fault in {"input", "image", "script"}:
        content[{"input": "input.json", "image": "a.png", "script": "render.py"}[fault]] = b"changed"
    elif fault == "missing_file":
        content.pop("b.png")
    elif fault == "binding":
        inputs.entries[0]["sha256"] = "0"*64
    elif fault == "routes_missing":
        result.standard_chart_routes.pop()
    elif fault == "routes_duplicate":
        result.standard_chart_routes[1]["chartId"] = "a"
    elif fault == "routes_foreign":
        result.standard_chart_routes[1]["chartId"] = "foreign"
    elif fault == "outputs":
        result.execution_receipt.output_files.pop()
    elif fault == "current_script":
        result.script_file = NS(path="other.py", size=1, sha256="f"*64)
    else:
        inputs.entries.clear()
    evidence = await collect_standard_replay_evidence(**args)
    assert evidence["status"] == "incomplete" and evidence["issues"]
    assert evidence["onlineAcceptedStandardFraction"] is None
    assert evidence["observedStandardRouteFraction"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["deterministic", "stale_sha", "not_run", "requires_revision", "missing_model", "missing"])
async def test_independent_vision_needs_matching_real_model_review(evidence_case, fault):
    args, _ = evidence_case
    reviews = args["result"].visual_inspection_receipts
    if fault == "missing":
        reviews.clear()
    elif fault == "deterministic":
        reviews[0].inspection_mode = "deterministic"
    elif fault == "stale_sha":
        reviews[0].sha256 = "f"*64
    elif fault == "not_run":
        reviews[0].visual_review_status = "not_run"
    elif fault == "requires_revision":
        reviews[0].requires_revision = True
    else:
        reviews[0].model_id = None
    evidence = await collect_standard_replay_evidence(**args)
    assert evidence["observedStandardRouteFraction"] == .5
    assert not evidence["independentVisualReviewValidated"]
    assert evidence["onlineAcceptedStandardFraction"] is None


@pytest.mark.anyio
async def test_replay_materializes_every_host_derived_page_before_execution_authority(monkeypatch):
    import json

    from scripts import replay_visualization_task as replay
    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )
    from smart_reporting.reporting.workflow.runtime.phase_models import (
        ChartDraft,
        VisualizationPlanDraft,
    )

    chart = ChartDraft(chartId="a", sourcePath="a.png", title="分页", altText="完整输入", citationIds=["c"],
        metricCodes=["m"], currentPeriod="2026-10", sourceDatasetId="dataset", aggregationGrain="category",
        visualForm="barh", standardValueFields=["amount"], standardPagination={"pageSize": 2},
        dataBindings=[{"analysisId": "analysis_001", "factPath": "facts.json", "dataPath": "rows", "fields": ["label", "amount"], "role": "冻结数据"}])
    plan = VisualizationPlanDraft(charts=(chart,))
    source = ChartInputFile("input.json", json.dumps({"columns": ["label", "amount"],
        "rows": [["A", 1], ["B", 10], ["C", 100]], "columnMeta": {"amount": {"unit": "元"}}}).encode())
    seen = []

    async def prepare(bound_plan, *args, **kwargs):
        seen.append(bound_plan)
        return ChartInputMaterialization(files=(source,), entries=tuple(
            {"chartId": item.chart_id, "path": source.path, "sha256": source.sha256} for item in bound_plan.charts))

    monkeypatch.setattr(replay, "prepare_chart_inputs", prepare)
    payload = {"task": {"task_kind": "visualization", "script_path": "render.py", "authorized_write_paths": ["render.py", "a.png"],
                         "declared_output_paths": ["a.png"]},
        "facts": {"visualizationPlan": plan.model_dump(mode="json", by_alias=True), "visualizationFacts": []}}
    assert await replay.apply_replay_chart_inputs(payload, None)
    assert len(seen) == 2 and len(seen[1].charts) == 2
    assert [item["chartId"] for item in payload["facts"]["chartInputs"]] == ["a", "a__page_2"]
    assert payload["task"]["declared_output_paths"] == ["a--page-2.png", "a.png"]
    assert set(payload["task"]["declared_output_paths"]).issubset(payload["task"]["authorized_write_paths"])
    assert payload["facts"]["standardPaginationExpansion"]["expandedCharts"] == 2
