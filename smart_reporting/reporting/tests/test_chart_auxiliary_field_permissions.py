"""主辅输入中的通用列名不能隐藏分母、尺度及节点表的原始字段。"""

import hashlib
import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor import create_report_editor_router
from smart_reporting.report_editor.chart_ai import ChartAIEditService
from smart_reporting.reporting.trace.contracts_v1 import TraceFileRefV1, derive_resource_id
from smart_reporting.reporting.trace.index_builder import encode_trace_index

from .lineage_fixtures.manifest import register_trace_manifest
from .test_trace_chart_field_permissions import chart_fixture, request_chart

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]


@pytest.mark.parametrize("auxiliary_first", [False, True])
@pytest.mark.parametrize("source_pointer", ["metrics[1].periodValues", "metrics[999].periodValues"])
async def test_every_auxiliary_source_requires_original_field_permission(
    tmp_path, auxiliary_first, source_pointer,
):
    """漏检任一辅助输入或只检查当前预览页均会泄露visits字段。"""
    editor, grants, ctx = await chart_fixture(tmp_path, "metric")
    try:
        index = await editor.trace.load_index(ctx)
        trace = index.chart_traces[0]
        main_ref = next(ref for ref in index.files if ref.resource_id == trace.plot_data_file_resource_ids[0])
        raw, _ = await editor.workspace.afile_bytes(ctx.scope["threadId"], main_ref.path)
        auxiliary = json.loads(raw)
        auxiliary["source"]["dataPath"] = source_pointer
        auxiliary["columns"] = ["label", "value"]
        auxiliary["rows"] = [["冻结端点", 1]]
        auxiliary["rowCount"] = 1
        content = json.dumps(auxiliary, ensure_ascii=False).encode()
        path = "reports/revision-1/plot-inputs/auxiliary.json"
        await editor.workspace.awrite_bytes(ctx.scope["threadId"], path, content)
        auxiliary_ref = TraceFileRefV1(
            resourceId=derive_resource_id(path), path=path, mediaType="application/json",
            size=len(content), sha256=hashlib.sha256(content).hexdigest(),
        )
        ordered = (auxiliary_ref.resource_id, main_ref.resource_id) if auxiliary_first else (
            main_ref.resource_id, auxiliary_ref.resource_id,
        )
        index = index.model_copy(update={
            "files": (*index.files, auxiliary_ref),
            "chart_traces": (trace.model_copy(update={"plot_data_file_resource_ids": ordered}),),
        })
        await editor.workspace.awrite_bytes(
            ctx.scope["threadId"], "reports/revision-1/trace-index-v1.json",
            encode_trace_index(index), overwrite=True,
        )
        manifest = await register_trace_manifest(editor.workspace, ctx.scope["threadId"], index, overwrite=True)
        ctx = ctx.model_copy(update={"artifact_manifest": manifest})
        state = await editor.state_repository.get(ctx.workflow_run_id)
        state.payload["reportEditorContexts"]["1"] = ctx.model_dump(mode="json", by_alias=True)

        # 全权限可查看；字段受限时必须在返回任何一页之前核验全部输入。
        assert all(response.status_code == 200 for response in await request_chart(editor, grants, ctx, None))
        responses = await request_chart(editor, grants, ctx, ["visits"])
        assert all(response.status_code == 403 for response in responses)
        assert all(response.json()["detail"]["code"] == "dataset_access_denied" for response in responses)
        unrelated = await request_chart(editor, grants, ctx, ["unrelated"])
        expected = 200 if source_pointer == "metrics[1].periodValues" else 403
        assert all(response.status_code == expected for response in unrelated)
    finally:
        await editor.aclose()


@pytest.mark.parametrize(
    "columns,rows,pointer,blocked",
    [
        (["total"], [[3]], "metrics[1]", "visits"),
        (["minimum", "maximum"], [[0, 3]], "metrics[1]", "visits"),
        (["id", "label", "stage"], [["A", "原始节点", 0]],
         "supplementalTables[0].rows", "node_id"),
    ],
    ids=["composition-denominator", "radar-endpoints", "unresolved-node-table"],
)
async def test_published_read_only_sources_check_scalar_and_node_auxiliary_inputs(
    tmp_path, columns, rows, pointer, blocked,
):
    """已发布快照的只读会话：辅助原列受限时首末页都不可旁路。"""
    editor, grants, ctx = await chart_fixture(tmp_path, "metric")
    try:
        index = await editor.trace.load_index(ctx)
        trace = index.chart_traces[0]
        main = next(ref for ref in index.files if ref.resource_id == trace.plot_data_file_resource_ids[0])
        image = next(ref for ref in index.files if ref.resource_id == trace.image_file_resource_id)
        content, _ = await editor.workspace.afile_bytes(ctx.scope["threadId"], main.path)
        original = json.loads(content)
        payload = {**original, "role": "frozen-auxiliary", "columns": columns, "rows": rows,
                   "rowCount": len(rows), "source": {**original["source"], "dataPath": pointer}}
        raw = json.dumps(payload, ensure_ascii=False).encode()
        path = "reports/revision-1/plot-inputs/family-auxiliary.json"
        await editor.workspace.awrite_bytes(ctx.scope["threadId"], path, raw)
        auxiliary = TraceFileRefV1(
            resourceId=derive_resource_id(path), path=path, mediaType="application/json",
            size=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
        )
        index = index.model_copy(update={
            "files": (*index.files, auxiliary),
            "chart_traces": (trace.model_copy(update={
                "plot_data_file_resource_ids": (*trace.plot_data_file_resource_ids, auxiliary.resource_id),
            }),),
        })
        await editor.workspace.awrite_bytes(
            ctx.scope["threadId"], "reports/revision-1/trace-index-v1.json",
            encode_trace_index(index), overwrite=True,
        )
        manifest = await register_trace_manifest(editor.workspace, ctx.scope["threadId"], index, overwrite=True)
        ctx = ctx.model_copy(update={"artifact_manifest": manifest})
        state = await editor.state_repository.get(ctx.workflow_run_id)
        state.payload["reportEditorContexts"]["1"] = ctx.model_dump(mode="json", by_alias=True)
        app = FastAPI()
        service = ChartAIEditService(editor=editor, workspace_registry=editor.workspace_registry,
                                     planner=None, runner=None)
        app.include_router(create_report_editor_router(grants, editor=editor, chart_ai=service,
                                                       cookie_secure=False))
        for blocked_columns, expected in (([], 200), ([blocked], 403)):
            grant, _ = await grants.issue(ctx, capabilities={"blocked_columns": blocked_columns})
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
                assert (await client.get(f"/reports/v1/editor/open/{grant}", follow_redirects=False)).status_code == 303
                for offset in (0, 1, 100):
                    response = await client.get(
                        "/reports/v1/editor/report-1/1/api/charts/chart_001/source",
                        params={"offset": offset, "limit": 1},
                    )
                    assert response.status_code == expected, response.text
                    if expected == 403:
                        assert response.json()["detail"]["code"] == "dataset_access_denied"
                # 同一受限会话可以读授权快照，但不能通过写接口创建改图任务。
                token = client.cookies.get("report_editor_session")
                response = await client.post(
                    "/reports/v1/editor/report-1/1/api/charts/chart_001/standard-edits",
                    json={"standard": {"standardForm": "pie"},
                          "baseImagePath": image.path, "expectedSha256": image.sha256},
                    headers={"Origin": "http://reports.test", "X-CSRF-Token": grants.csrf_token(token)},
                )
                assert response.status_code == 400, response.text
                assert response.json()["detail"]["code"] == "report_editor_chart_ai_unavailable"
                assert "只读" in response.json()["detail"]["message"]
                assert service._jobs == {}
    finally:
        await editor.aclose()
