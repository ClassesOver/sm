"""图表通用列名不能掩盖冻结事实所使用的受限原始字段。"""

import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor import create_report_editor_router
from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.contracts_v1 import TraceFileRefV1, derive_resource_id
from smart_reporting.reporting.trace.index_builder import encode_trace_index
from smart_reporting.reporting.workflow.runtime.chart_inputs import materialize_chart_inputs
from smart_reporting.reporting.workflow.runtime.phase_models import ChartDataBinding

from .lineage_fixtures.manifest import register_trace_manifest
from .test_deterministic_analysis import analysis, context, semantic
from .test_report_editor_trace import CSV_BYTES, DATASET_ID, _context, _make_editor

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]


async def chart_fixture(tmp_path, kind, *, source_change=None):
    editor, grants, _ = await _make_editor(tmp_path, with_fact_file=True, with_chart_trace=True)
    ctx = await editor._source_context(_context())
    index = await editor.trace.load_index(ctx)
    fact_ref = next(item for item in index.files if item.resource_id == index.fact_files[0].file_resource_id)
    item = analysis(fields=("revenue", "visits")).model_copy(update={"organization_grain": ("branch",)})
    dataset = context(DATASET_ID, fields=("period", "branch", "revenue", "visits"),
                      semantics=(semantic("revenue"), semantic("visits")), sha256=hashlib.sha256(CSV_BYTES).hexdigest())
    bundle = build_deterministic_analysis_bundle(item, ((DATASET_ID, CSV_BYTES, dataset, ("current",)),),
        profile_metrics=(
            {"code": "income", "fieldRef": "dynamic_source.dynamic_db.dynamic_table.revenue", "aggregation": "sum"},
            {"code": "visits", "fieldRef": "dynamic_source.dynamic_db.dynamic_table.visits", "aggregation": "sum"},
            {"code": "average", "aggregation": "ratio", "numeratorMetric": "income", "denominatorMetric": "visits"},
        ))
    if source_change == "missing_operand":
        bundle = bundle.model_copy(update={"metrics": (bundle.metrics[0],)})
    raw = bundle.model_dump_json(by_alias=True).encode()
    await editor.workspace.awrite_bytes(ctx.scope["threadId"], fact_ref.path, raw, overwrite=True)
    fact_ref = fact_ref.model_copy(update={"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    data_path, fields = {
        "metric": ("metrics[0].periodValues", ("period", "value")),
        "derived": ("derivedMetrics[0]", ("value",)),
        "group": ("metrics[0].topGroups", ("group", "value")),
    }[kind]
    binding = ChartDataBinding(analysisId="analysis_001", factPath=fact_ref.path, dataPath=data_path, fields=fields, role="main")
    plan = SimpleNamespace(charts=(SimpleNamespace(chart_id="chart_001", data_bindings=(binding,)),))
    result = materialize_chart_inputs(plan, [{
        "analysisId": "analysis_001", "factFile": {"path": fact_ref.path, "sha256": fact_ref.sha256},
        "dataDescriptors": [{"dataPath": data_path, "fields": fields}],
    }], {fact_ref.path: bundle.model_dump(mode="json", by_alias=True)}, output_root="reports/revision-1/plot-inputs")
    assert len(result.files) == 1 and not result.fallback_chart_ids
    plot = result.files[0]
    document = json.loads(plot.content)
    if source_change == "missing":
        document.pop("source")
    elif source_change == "hash":
        document["source"]["sha256"] = "f" * 64
    elif source_change == "old_path":
        document["source"]["path"] = "old-revision/facts.json"
    elif source_change == "analysis":
        document["source"]["analysisId"] = "analysis_999"
    elif source_change == "pointer":
        document["source"]["dataPath"] = "metrics[999].periodValues"
    content = json.dumps(document).encode()
    await editor.workspace.awrite_bytes(ctx.scope["threadId"], plot.path, content)
    plot_ref = TraceFileRefV1(resourceId=derive_resource_id(plot.path), path=plot.path,
                            mediaType="application/json", size=len(content), sha256=hashlib.sha256(content).hexdigest())
    index = index.model_copy(update={
        "files": (*tuple(fact_ref if ref.resource_id == fact_ref.resource_id else ref for ref in index.files), plot_ref),
        "chart_traces": (index.chart_traces[0].model_copy(update={"plot_data_file_resource_ids": (plot_ref.resource_id,)}),),
    })
    await editor.workspace.awrite_bytes(ctx.scope["threadId"], "reports/revision-1/trace-index-v1.json", encode_trace_index(index), overwrite=True)
    manifest = await register_trace_manifest(editor.workspace, ctx.scope["threadId"], index, overwrite=True)
    ctx = ctx.model_copy(update={"artifact_manifest": manifest})
    state = await editor.state_repository.get(ctx.workflow_run_id)
    state.payload["reportEditorContexts"]["1"] = ctx.model_dump(mode="json", by_alias=True)
    return editor, grants, ctx


async def request_chart(editor, grants, ctx, blocked):
    raw, _ = await grants.issue(ctx, capabilities={"blocked_columns": blocked} if blocked is not None else None)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        return [await client.get("/reports/v1/editor/report-1/1/api/charts/chart_001/source", params={"offset": offset, "limit": 1})
                for offset in (0, 100)]


@pytest.mark.parametrize("kind", ["metric", "derived"])
@pytest.mark.parametrize("blocked", ["revenue", "visits", "period", "unrelated"])
async def test_chart_aliases_cannot_bypass_origin_field_permissions(tmp_path, kind, blocked):
    editor, grants, ctx = await chart_fixture(tmp_path, kind)
    try:
        owner = await request_chart(editor, grants, ctx, None)
        assert all(response.status_code == 200 for response in owner)
        allowed = blocked == "unrelated" or (blocked == "visits" and kind == "metric")
        responses = await request_chart(editor, grants, ctx, [blocked])
        assert all(response.status_code == (200 if allowed else 403) for response in responses)
        if not allowed:
            assert all(response.json()["detail"]["code"] == "dataset_access_denied" for response in responses)
    finally:
        await editor.aclose()


@pytest.mark.parametrize("source_change", ["missing", "hash", "old_path", "analysis", "pointer"])
async def test_chart_permission_uses_registered_identity_not_embedded_path(tmp_path, source_change):
    editor, grants, ctx = await chart_fixture(tmp_path, "metric", source_change=source_change)
    try:
        responses = await request_chart(editor, grants, ctx, ["unrelated"])
        assert all(response.status_code == (200 if source_change == "old_path" else 403) for response in responses)
    finally:
        await editor.aclose()


async def test_chart_with_unknown_group_fields_is_unavailable_to_column_restricted_sessions(tmp_path):
    editor, grants, ctx = await chart_fixture(tmp_path, "group")
    try:
        assert all(response.status_code == 200 for response in await request_chart(editor, grants, ctx, None))
        assert all(response.status_code == 403 for response in await request_chart(editor, grants, ctx, ["branch"]))
    finally:
        await editor.aclose()


async def test_derived_chart_requires_all_operands_before_authorizing_source_columns(tmp_path):
    editor, grants, ctx = await chart_fixture(tmp_path, "derived", source_change="missing_operand")
    try:
        assert all(response.status_code == 200 for response in await request_chart(editor, grants, ctx, None))
        assert all(response.status_code == 403 for response in await request_chart(editor, grants, ctx, ["visits"]))
    finally:
        await editor.aclose()
