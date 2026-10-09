"""B1 Editor 来源 API 端到端测试：索引恢复 → sources/preview/download/派生导出。

真实 Host workspace + 真实 revision 索引 + 真实 HTTP 路由（计划 B1 验证：
授权对象可定位并预览/下载；非法访问不泄露内容；分享会话按矩阵受限；
同名不同报告隔离、双期间数据集、空数据快照）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor import (
    InMemoryReportEditorRepository,
    ReportEditorContext,
    ReportEditorGrantService,
    ReportEditorService,
    create_report_editor_router,
)
from smart_reporting.report_editor.trace_revisions import snapshot_revision_lineage
from smart_reporting.reporting.data_sources import DatasetHandle
from smart_reporting.reporting.delivery.artifacts_v1 import (
    ArtifactFile,
    DatasetLineage,
    ReportArtifactManifest,
)
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.index_builder import (
    build_csv_trace_index,
    encode_trace_index,
)
from smart_reporting.reporting.workflow.runtime.publication import RuntimePublicationMixin
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope, reporting_scope_keys

CSV_PATH = "报表/数据集/report-1/dataset-url-abc0001.csv"
CSV_BYTES = (
    "period,branch,revenue,visits\n"
    "2025-08,A院区,1000,10\n"
    "2025-08,B院区,2000,20\n"
    "2025-09,A院区,1200,10\n"
    "2025-09,B院区,2400,20\n"
).encode("utf-8")
DATASET_ID = "dataset-url-abc0001"


def _scope(report_id: str = "report-1") -> ReportingWorkflowScope:
    keys = reporting_scope_keys(
        database="database-1",
        company_id="company-1",
        user_id="user-1",
        thread_id="caller-thread",
        run_id=report_id,
    )
    return ReportingWorkflowScope(
        run_id=report_id,
        external_run_id=f"external-{report_id}",
        session_id="workflow-session",
        caller_thread_id="caller-thread",
        user_id="user-1",
        database="database-1",
        company_id="company-1",
        thread_lease_key=keys.thread_lease_key,
        workspace_key=keys.workspace_key,
    )


_REGISTERED_MANIFESTS: dict[str, ArtifactFile] = {}


@pytest.fixture(autouse=True)
def _reset_registered_manifests():
    _REGISTERED_MANIFESTS.clear()
    yield
    _REGISTERED_MANIFESTS.clear()


def _context(report_id: str = "report-1", manifest: ArtifactFile | None = None) -> ReportEditorContext:
    return ReportEditorContext(
        artifactManifest=manifest or _REGISTERED_MANIFESTS.get(report_id),
        reportId=report_id,
        revision=1,
        jobId="job-1",
        workflowRunId=report_id,
        markdownPath="reports/revision-1/report.md",
        job={"jobId": "job-1", "status": "validated"},
        scope=_scope(report_id).as_state(),
    )


async def _write_revision_files(
    workspace: ReportingWorkspaceRouter,
    workspace_key: str,
    *,
    report_id: str = "report-1",
    with_index: bool = True,
    with_fact_file: bool = False,
    with_chart_trace: bool = False,
    with_computation: bool = False,
    with_drilldown: bool = False,
    legacy_fact_name: bool = False,
) -> None:
    markdown = "# 报告\n"
    if with_chart_trace:
        markdown += "\n![趋势](chart-001.png)\n\n*图表：收入趋势*\n"
    await workspace.awrite_text(workspace_key, "reports/revision-1/report.md", markdown)
    await workspace.awrite_bytes(workspace_key, CSV_PATH, CSV_BYTES)
    if not with_index:
        return
    csv_sha = hashlib.sha256(CSV_BYTES).hexdigest()
    handle = DatasetHandle(
        dataset_id=DATASET_ID,
        source_id="mcp-url",
        source_type="url_csv",
        path=CSV_PATH,
        row_count=4,
        size=len(CSV_BYTES),
        sha256=csv_sha,
        requirement_id="attachment-001",
        sql_hash=hashlib.sha256(f"url_csv:{csv_sha}".encode()).hexdigest(),
        filename="收入明细.csv",
        materialized_at="2026-09-29T08:00:00Z",
        query_sql="SELECT branch, revenue FROM finance.income WHERE patient_id = 'P001'",
    )
    lineage = DatasetLineage(
        datasetId=DATASET_ID,
        sourceId="mcp-url",
        sourceType="url_csv",
        requirementId="attachment-001",
        sqlHash=handle.sql_hash,
        rowCount=4,
        size=len(CSV_BYTES),
        sha256=csv_sha,
    )
    fact_files = None
    chart_trace_files: tuple = ()
    chart_traces: tuple = ()
    if with_chart_trace:
        # B3：归档图片 + chart-input 文件 + ChartTraceV1。
        from smart_reporting.reporting.trace.contracts_v1 import (
            ChartTraceV1,
            derive_resource_id,
        )
        from smart_reporting.reporting.workflow.checkpoint import FileIdentity

        chart_image = "reports/revision-1/chart-001.png"
        chart_plot = "reports/revision-1/chart-001--1.chart-input.json"
        image_bytes = b"\x89PNG\r\n\x1a\nfake"
        plot_rows = [["2025-09", 3600.0], ["2025-08", 3000.0]]
        plot_payload = json.dumps(
            {
                "schema": "chart-input/v1",
                "chartId": "chart_001",
                "role": "measure",
                "source": {"analysisId": "analysis_001"},
                "columns": ["period", "revenue"],
                "rows": plot_rows,
                "rowCount": 2,
            }
        ).encode("utf-8")
        await workspace.awrite_bytes(workspace_key, chart_image, image_bytes)
        await workspace.awrite_bytes(workspace_key, chart_plot, plot_payload)
        chart_trace_files = (
            FileIdentity(
                path=chart_image,
                size=len(image_bytes),
                sha256=hashlib.sha256(image_bytes).hexdigest(),
            ),
            FileIdentity(
                path=chart_plot,
                size=len(plot_payload),
                sha256=hashlib.sha256(plot_payload).hexdigest(),
            ),
        )
        chart_traces = (
            ChartTraceV1(
                chartId="chart_001",
                imageFileResourceId=derive_resource_id(chart_image),
                plotDataFileResourceIds=(derive_resource_id(chart_plot),),
                datasetIds=(DATASET_ID,),
                transformNotes=("作图数据由服务端 chart-input/v1 物化",),
            ),
        )
    if with_fact_file:
        fact_path = "报表/智能分析/report-1/facts/revision-1/analysis_001.json"
        fact_bytes = json.dumps(
            {
                "version": "1",
                "analysisId": "analysis_001",
                "analysisName": None if legacy_fact_name else "2025年收入汇总",
                "metrics": [
                    {
                        "factId": "fact-" + "a" * 16,
                        "datasetId": DATASET_ID,
                        "datasetSha256": csv_sha,
                        "periodRoles": ["current"],
                        "metricCodes": ["income_total"],
                        "field": "收入",
                        "fieldRef": "dynamic_source.dynamic_db.dynamic_table.revenue",
                        "aggregation": "sum",
                        "formula": "sum(revenue)",
                        "scope": {},
                        "total": 3600.0,
                        "missingCount": 0,
                        "zeroCount": 0,
                        "negativeCount": 0,
                        "warnings": [],
                    }
                ],
                "derivedMetrics": [
                    {
                        "factId": "fact-" + "b" * 16,
                        "code": "avg_per_visit",
                        "kind": "ratio",
                        "periodRole": "current",
                        "numeratorMetric": "income_total",
                        "denominatorMetric": "visits_total",
                        "numerator": 3600.0,
                        "denominator": 30.0,
                        "value": 120.0,
                        "difference": 3570.0,
                        "formula": "3600/30",
                        "datasetIds": [DATASET_ID],
                        "datasetSha256s": [csv_sha],
                        "warnings": [],
                    }
                ],
                "comparisons": [],
                "reconciliations": [],
                "correlations": {},
                "warnings": [],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        await workspace.awrite_bytes(workspace_key, fact_path, fact_bytes)
        fact_files = {
            "analysis_001": ArtifactFile(
                path=fact_path,
                mediaType="application/json",
                size=len(fact_bytes),
                sha256=hashlib.sha256(fact_bytes).hexdigest(),
            )
        }
    computation_files: tuple = ()
    computations: tuple = ()
    if with_computation:
        from smart_reporting.reporting.trace.computation_service import (
            build_supplemental_computation_record,
        )
        from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id

        script_path = "报表/智能分析/report-1/evidence/analysis_002/attempt-1/supplement.py"
        evidence_path = (
            "报表/智能分析/report-1/evidence/analysis_002/attempt-1/supplement.json"
        )
        script_bytes = b"print('supplement')\n"
        evidence_payload = json.dumps(
            {
                "schema": "supplemental-evidence/v1",
                "analysisId": "analysis_002",
                "findings": {"columns": ["name", "value"], "rows": [["净增量占比", 66.67]]},
            }
        ).encode("utf-8")
        await workspace.awrite_bytes(workspace_key, script_path, script_bytes)
        await workspace.awrite_bytes(workspace_key, evidence_path, evidence_payload)
        record = build_supplemental_computation_record(
            analysis_id="analysis_002",
            dataset_ids=(DATASET_ID,),
            script_file={
                "path": script_path,
                "size": len(script_bytes),
                "sha256": hashlib.sha256(script_bytes).hexdigest(),
            },
            evidence_file={
                "path": evidence_path,
                "size": len(evidence_payload),
                "sha256": hashlib.sha256(evidence_payload).hexdigest(),
            },
            execution={
                "runId": "exec-1",
                "environment": {"python": "3.12.0", "polars": "1.43.2"},
            },
            finding_count=1,
        )
        computation_files = (
            {
                "path": script_path,
                "size": len(script_bytes),
                "sha256": hashlib.sha256(script_bytes).hexdigest(),
            },
            {
                "path": evidence_path,
                "size": len(evidence_payload),
                "sha256": hashlib.sha256(evidence_payload).hexdigest(),
            },
        )
        computations = (record,)
    subject_bindings: tuple = ()
    drilldown_metrics: tuple = ()
    if with_drilldown:
        if not fact_files:
            raise AssertionError("drilldown fixture requires fact file")
        from smart_reporting.reporting.trace.contracts_v1 import (
            DrilldownMetricV1,
            FactRefV1,
            SubjectBindingV1,
            SubjectLocatorV1,
            derive_resource_id,
        )

        fact_path = fact_files["analysis_001"].path
        fact_ref = FactRefV1(
            analysisId="analysis_001",
            fileResourceId=derive_resource_id(fact_path),
            jsonPointer="/metrics/0",
            factKind="metric",
            factKey="fact-" + "a" * 16,
        )
        subject_bindings = (
            SubjectBindingV1(
                subjectId="sub-" + "c" * 16,
                subjectKind="text_claim",
                locator=SubjectLocatorV1(sectionId="section-1"),
                subjectSha256="d" * 64,
                claimId="claim-1",
                factRefs=(fact_ref,),
            ),
        )
        drilldown_metrics = (
            DrilldownMetricV1(
                metricCode="income_total",
                datasetId=DATASET_ID,
                aggregation="sum",
                valueField="revenue",
                periodField="period",
                periodStart="2025-09",
                periodEnd="2025-09",
                dimensions=(
                    {"code": "branch", "field": "branch", "label": "院区"},
                ),
                expectedValue=3600.0,
                factKeys=("fact-" + "a" * 16,),
                unit="元",
            ),
        )
    index = build_csv_trace_index(
        handles=(handle,),
        lineage=(lineage,),
        report_id=report_id,
        revision=1,
        workflow_run_id=report_id,
        markdown_file=ArtifactFile(
            path="reports/revision-1/report.md",
            mediaType="text/markdown",
            size=len(markdown.encode("utf-8")),
            sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        ),
        fact_files=fact_files,
        chart_trace_files=chart_trace_files,
        chart_traces=chart_traces,
        computation_files=computation_files,
        computations=computations,
        subject_bindings=subject_bindings,
        drilldown_metrics=drilldown_metrics,
    )
    await workspace.awrite_bytes(
        workspace_key,
        "reports/revision-1/trace-index-v1.json",
        encode_trace_index(index),
    )
    from .lineage_fixtures.manifest import register_trace_manifest

    manifest_identity = await register_trace_manifest(workspace, workspace_key, index)
    _REGISTERED_MANIFESTS[report_id] = manifest_identity
    return manifest_identity


async def _make_editor(
    tmp_path: Path,
    *,
    with_index: bool = True,
    report_id: str = "report-1",
    with_fact_file: bool = False,
    with_chart_trace: bool = False,
    with_computation: bool = False,
    with_drilldown: bool = False,
    legacy_fact_name: bool = False,
    **editor_options: bool,
) -> tuple[
    ReportEditorService, ReportEditorGrantService, ReportingWorkspaceRouter
]:
    scope = _scope(report_id)
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    manifest = await _write_revision_files(
        workspace,
        scope.workspace_key,
        report_id=report_id,
        with_index=with_index,
        with_fact_file=with_fact_file,
        with_chart_trace=with_chart_trace,
        with_computation=with_computation,
        with_drilldown=with_drilldown,
        legacy_fact_name=legacy_fact_name,
    )
    registry.release(scope.workspace_key)
    state = SimpleNamespace(
        payload={
            "reportEditorContexts": {
                "1": _context(report_id, manifest).model_dump(mode="json", by_alias=True)
            }
        }
    )
    editor = ReportEditorService(
        state_repository=SimpleNamespace(get=_async_return(state)),
        workspace_registry=registry,
        workspace=workspace,
        trace_cursor_secret=b"trace-cursor-secret-32-bytes-ok!",
        **editor_options,
    )
    grants = ReportEditorGrantService(
        InMemoryReportEditorRepository(), secret="s" * 32
    )
    return editor, grants, workspace


@pytest.mark.anyio
async def test_lineage_rollout_switches_disable_access_without_deleting_evidence(
    tmp_path: Path,
) -> None:
    editor, grants, workspace = await _make_editor(
        tmp_path,
        with_fact_file=True,
        with_drilldown=True,
        lineage_panel_enabled=False,
        lineage_download_enabled=False,
        lineage_drilldown_enabled=False,
    )
    raw, _ = await grants.issue(_context())
    _token, session = await grants.exchange(raw)

    sources = await editor.trace_sources(_context(), session)

    assert editor.lineage_features() == {
        "panel": False,
        "download": False,
        "drilldown": False,
        "exportSources": True,
    }
    assert sources == {
        "available": False,
        "reason": "feature_disabled",
        "datasets": [],
        "subjects": [],
        "drilldown": {"enabled": False, "metrics": [], "subjects": []},
    }
    for operation in (
        editor.trace_dataset_preview(_context(), session, DATASET_ID),
        editor.trace_dataset_download(_context(), session, DATASET_ID),
        editor.trace_drilldown_metric(
            _context(),
            session,
            "income_total",
            dataset_id=DATASET_ID,
            dimension_code="hospital",
        ),
    ):
        with pytest.raises(ReportingError):
            await operation
    registry = workspace.registry
    registry.resolve(_scope())
    assert await workspace.afile_bytes(
        _scope().workspace_key, "reports/revision-1/trace-index-v1.json"
    )


@pytest.mark.anyio
async def test_source_links_target_revision_subject_without_credentials(
    tmp_path: Path,
) -> None:
    scope = _scope()
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    manifest_identity = await _write_revision_files(
        workspace,
        scope.workspace_key,
        with_fact_file=True,
        with_drilldown=True,
    )
    manifest = ReportArtifactManifest.model_validate_json(
        await workspace.read_limited_regular_file(
            scope.workspace_key,
            manifest_identity.path,
            max_bytes=4 * 1024 * 1024,
        )
    )
    runtime = object.__new__(RuntimePublicationMixin)
    runtime.report_public_base_url = "https://reports.example.test"
    runtime.workspace_service = workspace
    runtime._scope = lambda _context: {"threadId": scope.workspace_key}

    links = await runtime._source_links_by_dataset(manifest, SimpleNamespace())

    assert links == {
        DATASET_ID: [
            {
                "subjectId": "sub-" + "c" * 16,
                "label": "正文结论",
                "url": (
                    "https://reports.example.test/reports/v1/editor/report-1/1"
                    "?subject=sub-cccccccccccccccc"
                ),
            }
        ]
    }
    assert "token" not in links[DATASET_ID][0]["url"]
    assert "session" not in links[DATASET_ID][0]["url"]


def _async_return(value):
    async def _get(*_args, **_kwargs):
        return value

    return _get


@pytest.mark.anyio
async def test_sources_reports_datasets_from_revision_index(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path)
    context = _context()
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)

    sources = await editor.trace_sources(context, session)
    assert sources["available"] is True
    assert sources["revision"] == 1
    dataset = sources["datasets"][0]
    assert dataset["datasetId"] == DATASET_ID
    assert dataset["sourceType"] == "url_csv"
    assert dataset["filename"] == "收入明细.csv"
    assert dataset["rowCount"] == 4
    assert dataset["materializedAt"] == "2026-09-29T08:00:00Z"


@pytest.mark.anyio
async def test_old_fact_names_use_matching_registered_analysis_plan(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path, with_fact_file=True, legacy_fact_name=True)
    context = _context()
    raw, _ = await grants.issue(context)
    _, session = await grants.exchange(raw)
    state = await editor.state_repository.get(context.workflow_run_id)
    state.payload["analysisPlans"] = {"analysis_001": {
        "step": "2025年收入汇总", "datasetIds": [DATASET_ID],
    }}
    sources = await editor.trace_sources(context, session)
    assert sources["facts"]
    assert all(fact["analysisName"] == "2025年收入汇总" for fact in sources["facts"] if fact["datasetIds"])
    state.payload["analysisPlans"]["analysis_001"]["datasetIds"] = ["other-dataset"]
    sources = await editor.trace_sources(context, session)
    assert all(not fact.get("analysisName") for fact in sources["facts"])


@pytest.mark.anyio
async def test_sources_without_index_reports_unavailable(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path, with_index=False)
    raw, _ = await grants.issue(_context())
    _token, session = await grants.exchange(raw)

    sources = await editor.trace_sources(_context(), session)
    assert sources["available"] is False
    assert sources["reason"] == "source_index_missing"
    with pytest.raises(ReportingError) as exc:
        await editor.trace_dataset_preview(_context(), session, DATASET_ID)
    assert exc.value.code == "source_missing"


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["preview", "columns"])
async def test_dataset_reads_verified_copy_when_source_changes_before_csv_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    from smart_reporting.reporting.trace import dataset_service

    editor, grants, workspace = await _make_editor(tmp_path)
    raw, _ = await grants.issue(_context())
    _token, session = await grants.exchange(raw)
    workspace.registry.resolve(_scope())
    original_path = workspace.workspace(_scope().workspace_key).paths.to_host_path(CSV_PATH)
    read_header = dataset_service.read_csv_header
    snapshots: list[Path] = []

    def change_original_before_scan(path: Path) -> list[str]:
        snapshots.append(path)
        original_path.write_bytes(CSV_BYTES.replace(b"revenue", b"secret!").replace(b"1000", b"9999"))
        return read_header(path)

    monkeypatch.setattr(dataset_service, "read_csv_header", change_original_before_scan)
    if operation == "preview":
        page = await editor.trace_dataset_preview(_context(), session, DATASET_ID)
        assert page["columns"] == ["period", "branch", "revenue", "visits"]
        assert page["rows"][0][2] == "1000"
    else:
        result = await editor.trace_dataset_columns(_context(), session, DATASET_ID)
        assert result["columns"] == ["period", "branch", "revenue", "visits"]
    assert snapshots and all(path != original_path and not path.exists() for path in snapshots)


@pytest.mark.anyio
async def test_owner_session_previews_paginated_rows(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path)
    raw, _ = await grants.issue(_context())
    _token, session = await grants.exchange(raw)  # capabilities=None → 完整会话

    page = await editor.trace_dataset_preview(_context(), session, DATASET_ID, limit=2)
    assert page["rowCountTotal"] == 4
    assert len(page["rows"]) == 2
    assert page["rows"][0][0] == "2025-08"
    assert page["nextCursor"]

    page2 = await editor.trace_dataset_preview(
        _context(), session, DATASET_ID, limit=2, cursor=page["nextCursor"]
    )
    assert page2["offset"] == 2
    assert page2["nextCursor"] is None

    column_page = await editor.trace_dataset_preview(
        _context(), session, DATASET_ID, columns=["period", "revenue"]
    )
    assert column_page["columns"] == ["period", "revenue"]


@pytest.mark.anyio
async def test_owner_downloads_original_snapshot(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path)
    raw, _ = await grants.issue(_context())
    _token, session = await grants.exchange(raw)

    path, filename, size = await editor.trace_dataset_download(
        _context(), session, DATASET_ID
    )
    assert Path(path).read_bytes() == CSV_BYTES  # 原始快照按原字节返回
    assert filename == "收入明细.csv"
    assert size == len(CSV_BYTES)


@pytest.mark.anyio
async def test_tampered_snapshot_is_rejected(tmp_path: Path) -> None:
    editor, grants, workspace = await _make_editor(tmp_path)
    scope = _scope()
    registry = workspace.registry
    registry.resolve(scope)
    await workspace.awrite_bytes(
        scope.workspace_key, CSV_PATH, b"period\n1\n", overwrite=True
    )
    registry.release(scope.workspace_key)

    raw, _ = await grants.issue(_context())
    _token, session = await grants.exchange(raw)
    with pytest.raises(ReportingError) as exc:
        await editor.trace_dataset_preview(_context(), session, DATASET_ID)
    assert exc.value.code == "snapshot_integrity_failed"


@pytest.mark.anyio
async def test_http_sources_preview_and_download(tmp_path: Path) -> None:
    # subjects 断言需要夹具登记 subject 绑定；drilldown 夹具同时写入
    # 事实文件，不改变 CSV 预览/下载的其余断言。
    editor, grants, _ = await _make_editor(
        tmp_path, with_fact_file=True, with_drilldown=True
    )
    owner_raw, _ = await grants.issue(_context())
    # 分享链接：受限能力（不可下载）。
    share_raw, _ = await grants.issue(
        _context(),
        capabilities={"download_original": False, "download_derived": False},
    )
    app = FastAPI()
    app.include_router(
        create_report_editor_router(grants, editor=editor, cookie_secure=False)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        await client.get(f"/reports/v1/editor/open/{owner_raw}", follow_redirects=False)
        sources = await client.get("/reports/v1/editor/report-1/1/api/sources")
        assert sources.status_code == 200
        assert sources.json()["available"] is True
        assert sources.json()["subjects"][0]["subjectId"].startswith("sub-")
        assert set(sources.json()["subjects"][0]["locator"]) == {
            "sectionId",
            "tableId",
            "rowKey",
            "columnKey",
            "chartId",
        }

        preview = await client.get(
            f"/reports/v1/editor/report-1/1/api/datasets/{DATASET_ID}/preview",
            params={"limit": 2},
        )
        assert preview.status_code == 200
        body = preview.json()
        assert body["rowCountTotal"] == 4 and len(body["rows"]) == 2

        invalid_limit = await client.get(
            f"/reports/v1/editor/report-1/1/api/datasets/{DATASET_ID}/preview",
            params={"limit": 0},
        )
        assert invalid_limit.status_code == 400
        assert invalid_limit.json()["detail"]["code"] == "request_invalid"

        unknown = await client.get(
            "/reports/v1/editor/report-1/1/api/datasets/dataset-url-none0000/preview"
        )
        assert unknown.status_code == 404
        assert unknown.json()["detail"]["code"] == "source_missing"

        download = await client.get(
            f"/reports/v1/editor/report-1/1/api/datasets/{DATASET_ID}/download"
        )
        assert download.status_code == 200
        assert download.content == CSV_BYTES
        # FileResponse 对中文文件名使用 RFC 5987 编码。
        assert "filename*=utf-8''" in download.headers["content-disposition"]
        assert quote("收入明细.csv") in download.headers["content-disposition"]

        # 分享会话：可预览、不可下载。
        await client.get(f"/reports/v1/editor/open/{share_raw}", follow_redirects=False)
        share_preview = await client.get(
            f"/reports/v1/editor/report-1/1/api/datasets/{DATASET_ID}/preview"
        )
        assert share_preview.status_code == 200
        share_download = await client.get(
            f"/reports/v1/editor/report-1/1/api/datasets/{DATASET_ID}/download"
        )
        assert share_download.status_code == 403
        assert share_download.json()["detail"]["code"] == "dataset_access_denied"


@pytest.mark.anyio
async def test_http_dataset_columns_supports_controlled_column_selection(
    tmp_path: Path,
) -> None:
    """受限列会话：整表预览被拒，但可取得可见列并按受控列选择分页预览。"""
    editor, grants, _ = await _make_editor(tmp_path)
    raw, _ = await grants.issue(_context(), capabilities={"blocked_columns": ["revenue"]})
    app = FastAPI()
    app.include_router(
        create_report_editor_router(grants, editor=editor, cookie_secure=False)
    )
    base = "/reports/v1/editor/report-1/1/api/datasets"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        whole = await client.get(f"{base}/{DATASET_ID}/preview")
        assert whole.status_code == 403
        listing = await client.get(f"{base}/{DATASET_ID}/columns")
        assert listing.status_code == 200
        body = listing.json()
        assert body == {
            "datasetId": DATASET_ID,
            "columns": ["period", "branch", "visits"],
            "restricted": True,
            "maxColumnsPerPage": 50,
        }
        columns = body["columns"]  # 每列一个 columns 参数
        first = await client.get(
            f"{base}/{DATASET_ID}/preview", params={"limit": 2, "columns": columns}
        )
        assert first.status_code == 200 and first.json()["nextCursor"]
        second = await client.get(
            f"{base}/{DATASET_ID}/preview",
            params={"limit": 2, "columns": columns, "cursor": first.json()["nextCursor"]},
        )
        assert second.status_code == 200 and second.json()["offset"] == 2
        missing = await client.get(f"{base}/dataset-url-none0000/columns")
        assert missing.status_code == 404

        # 列名可含逗号与首尾空格：路由按原文逐个传递，不拼接再拆分。
        received: list[object] = []
        original = editor.trace_dataset_preview

        async def capture(*args: object, **kwargs: object) -> dict:
            received.append(kwargs.get("columns"))
            return await original(*args, **{**kwargs, "columns": None})

        editor.trace_dataset_preview = capture  # type: ignore[method-assign]
        try:
            await client.get(
                f"{base}/{DATASET_ID}/preview",
                params={"columns": ["收入,万元", " 期间 "]},
            )
        finally:
            editor.trace_dataset_preview = original  # type: ignore[method-assign]
        assert received == [["收入,万元", " 期间 "]]


# ---------------------------------------------------------------------------
# 派生/脱敏导出（B1-7）
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_derived_export_masks_columns_with_independent_identity(
    tmp_path: Path,
) -> None:
    editor, grants, _ = await _make_editor(tmp_path)
    raw, _ = await grants.issue(_context())
    _token, session = await grants.exchange(raw)  # 完整会话：可派生导出

    started = await editor.trace_create_derived_export(
        _context(),
        session,
        DATASET_ID,
        policy="masked_columns",
        params={"columns": ["revenue", "visits"]},
    )
    assert started["status"] == "running"
    export_id = started["exportId"]

    status: dict = {}
    for _ in range(100):
        status = await editor.trace_derived_export_status(_context(), session, export_id)
        if status["status"] != "running":
            break
        await asyncio.sleep(0.05)
    assert status["status"] == "completed"
    assert status["derived"] is True
    assert status["sha256"] != hashlib.sha256(CSV_BYTES).hexdigest()  # 派生文件独立身份

    path, filename, size = await editor.trace_derived_export_download(
        _context(), session, export_id
    )
    content = Path(path).read_bytes()
    assert size == len(content)
    lines = content.decode("utf-8").splitlines()
    assert lines[0] == "period,branch,revenue,visits"
    first_data_row = lines[1].split(",")
    # 掩码列替换为 ***，其余列保持原值。
    assert first_data_row[2] == "***" and first_data_row[3] == "***"
    assert first_data_row[0] == "2025-08" and first_data_row[1] == "A院区"
    assert "derived" in filename


def test_derived_export_keeps_unmasked_cells_verbatim(tmp_path: Path) -> None:
    """派生导出只替换掩码列；其余列按原文写出，不因类型推断改写。"""
    from smart_reporting.report_editor.trace_exports import TraceDerivedExportService

    source = tmp_path / "codes.csv"
    source.write_text(
        "dept_code,amount,phone\n0012,1200.50,13800000000\n0300,980.00,13900000000\n",
        encoding="utf-8",
    )
    target = tmp_path / "derived.csv"
    TraceDerivedExportService._generate(source, target, ["phone"], "***")
    assert target.read_text(encoding="utf-8").splitlines() == [
        "dept_code,amount,phone",
        "0012,1200.50,***",
        "0300,980.00,***",
    ]


@pytest.mark.anyio
async def test_derived_export_guard_failure_marks_job_failed(tmp_path: Path) -> None:
    """来源守卫抛出非 ReportingError 时任务落为 failed，不停在 running 占用并发名额。"""
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from smart_reporting.report_editor.trace_exports import TraceDerivedExportService
    from smart_reporting.reporting.trace.dataset_service import TraceDatasetFile

    source = tmp_path / "data.csv"
    source.write_text("name,amount\na,1\n", encoding="utf-8")
    file = TraceDatasetFile(
        dataset_id="dataset-guard", local_path=source, size=source.stat().st_size,
        sha256="0" * 64, row_count=1,
    )
    context = SimpleNamespace(
        report_id="report-1", revision=1, scope={"threadId": "thread-1"},
        markdown_path="报表/report.md",
    )

    @asynccontextmanager
    async def broken_guard(_context):
        raise RuntimeError("state repository unavailable")
        yield

    service = TraceDerivedExportService(workspace=None)
    service.source_guard = broken_guard
    started = await service.create(
        context=context, file=file, policy="masked_columns", params={"columns": ["amount"]}
    )
    await service._jobs[started["exportId"]].task
    status = await service.status(context, started["exportId"])
    assert status["status"] == "failed"
    assert status["error"]["code"] == "report_editor_export_failed"
    assert "state repository" not in status["error"]["message"]


@pytest.mark.anyio
async def test_derived_export_expiry_cleanup_task_is_retained_until_done() -> None:
    """过期清理在后台删除文件；Task 被持有到完成，不会因只有弱引用而中途回收。"""
    import asyncio

    from smart_reporting.report_editor.trace_exports import (
        TraceDerivedExportService,
        TraceExportJob,
    )

    deleted: list[tuple[str, str]] = []
    release = asyncio.Event()

    class Workspace:
        async def adelete_file(self, thread_id: str, path: str) -> None:
            await release.wait()
            deleted.append((thread_id, path))

    service = TraceDerivedExportService(workspace=Workspace())
    job = TraceExportJob(
        export_id="export-old", report_id="report-1", revision=1, dataset_id="dataset-1",
        policy="masked_columns", params={}, source_dataset_id="dataset-1",
        source_sha256="0" * 64, workspace_path="报表/.exports/old.csv", thread_id="thread-1",
        created_at=0.0, status="completed", finished_at=0.0,
    )
    service._jobs[job.export_id] = job

    service._cleanup_expired()

    assert job.export_id not in service._jobs
    assert len(service._cleanup_tasks) == 1
    release.set()
    await asyncio.gather(*service._cleanup_tasks)
    assert deleted == [("thread-1", "报表/.exports/old.csv")]
    assert not service._cleanup_tasks


def test_derived_export_masks_duplicated_copies_of_blocked_columns(tmp_path: Path) -> None:
    """表头重复的受限列（polars 改名为 *_duplicated_n）同样强制掩码，不成为旁路。"""
    from smart_reporting.report_editor.trace_exports import _validate_masked_columns_policy
    from smart_reporting.reporting.trace.dataset_service import TraceDatasetFile

    source = tmp_path / "dup.csv"
    source.write_text("name,salary,salary\na,1,2\n", encoding="utf-8")
    file = TraceDatasetFile(
        dataset_id="dataset-dup", local_path=source, size=source.stat().st_size,
        sha256="0" * 64, row_count=1,
    )
    target, _mask = _validate_masked_columns_policy(
        file, {"columns": ["name"]}, frozenset({"salary"})
    )
    assert target == ["name", "salary", "salary_duplicated_0"]



@pytest.mark.anyio
async def test_derived_export_always_masks_blocked_columns(tmp_path: Path) -> None:
    """受限列会话的派生导出：即使请求只掩码其他列，受限列也被强制掩码。"""
    editor, grants, _ = await _make_editor(tmp_path)
    raw, _ = await grants.issue(
        _context(), capabilities={"blocked_columns": ["revenue"], "download_derived": True}
    )
    _token, session = await grants.exchange(raw)
    started = await editor.trace_create_derived_export(
        _context(), session, DATASET_ID, policy="masked_columns", params={"columns": ["visits"]}
    )
    assert "revenue" not in str(started)
    status: dict = {}
    for _ in range(100):
        status = await editor.trace_derived_export_status(_context(), session, started["exportId"])
        if status["status"] != "running":
            break
        await asyncio.sleep(0.05)
    assert status["status"] == "completed"
    path, _filename, _size = await editor.trace_derived_export_download(
        _context(), session, started["exportId"]
    )
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    assert lines[0] == "period,branch,revenue,visits"
    assert all(line.split(",")[2:] == ["***", "***"] for line in lines[1:])


@pytest.mark.anyio
async def test_derived_export_rejects_unknown_policy_and_bad_columns(
    tmp_path: Path,
) -> None:
    editor, grants, _ = await _make_editor(tmp_path)
    raw, _ = await grants.issue(_context())
    _token, session = await grants.exchange(raw)
    with pytest.raises(ReportingError) as exc:
        await editor.trace_create_derived_export(
            _context(), session, DATASET_ID, policy="raw_copy"
        )
    assert exc.value.code == "request_invalid"
    with pytest.raises(ReportingError) as exc:
        await editor.trace_create_derived_export(
            _context(),
            session,
            DATASET_ID,
            policy="masked_columns",
            params={"columns": ["no_such_column"]},
        )
    assert exc.value.code == "request_invalid"


@pytest.mark.anyio
async def test_derived_export_share_session_denied(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path)
    share_raw, _ = await grants.issue(
        _context(),
        capabilities={"download_original": False, "download_derived": False},
    )
    _token, session = await grants.exchange(share_raw)
    with pytest.raises(ReportingError) as exc:
        await editor.trace_create_derived_export(
            _context(),
            session,
            DATASET_ID,
            policy="masked_columns",
            params={"columns": ["revenue"]},
        )
    assert exc.value.code == "dataset_access_denied"


@pytest.mark.anyio
async def test_derived_export_job_isolation_between_reports(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path)
    raw, _ = await grants.issue(_context())
    _token, session = await grants.exchange(raw)
    started = await editor.trace_create_derived_export(
        _context(),
        session,
        DATASET_ID,
        policy="masked_columns",
        params={"columns": ["revenue"]},
    )
    export_id = started["exportId"]

    other_context = _context().model_copy(update={"report_id": "report-other"})
    with pytest.raises(ReportingError) as exc:
        await editor.trace_derived_export_status(other_context, session, export_id)
    # 伪造 reportId 先被作用域校验拦截；同报告内不存在任务才是 source_missing。
    assert exc.value.code == "report_editor_scope_mismatch"
    with pytest.raises(ReportingError) as exc:
        await editor.trace_derived_export_status(
            _context(), session, "export-not-exist00"
        )
    assert exc.value.code == "source_missing"  # 不泄露其他任务存在性


# ---------------------------------------------------------------------------
# B1-8 验证清单：游标跨报告重放、双期间双数据集、未登记数据集
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cursor_does_not_replay_across_reports(tmp_path: Path) -> None:
    """两个报告各自持有同名同内容文件：预览一致，但游标跨报告重放被拒绝。"""

    editor_a, grants_a, _ = await _make_editor(tmp_path / "a")
    editor_b, grants_b, _ = await _make_editor(tmp_path / "b", report_id="report-2")
    raw_a, _ = await grants_a.issue(_context("report-1"))
    raw_b, _ = await grants_b.issue(_context("report-2"))
    _t, session_a = await grants_a.exchange(raw_a)
    _t, session_b = await grants_b.exchange(raw_b)

    page_a = await editor_a.trace_dataset_preview(
        _context("report-1"), session_a, DATASET_ID, limit=2
    )
    page_b = await editor_b.trace_dataset_preview(
        _context("report-2"), session_b, DATASET_ID, limit=2
    )
    assert page_a["rows"] == page_b["rows"]  # 同名同内容：结果一致属正常
    assert page_a["nextCursor"], "limit=2 必须产生续翻游标"
    with pytest.raises(ReportingError) as exc:
        await editor_b.trace_dataset_preview(
            _context("report-2"), session_b, DATASET_ID, limit=2, cursor=page_a["nextCursor"]
        )
    assert exc.value.code == "cursor_invalid"  # 游标绑定 report/revision


async def _write_two_period_datasets(
    workspace: ReportingWorkspaceRouter, workspace_key: str
) -> None:
    """当期/同比两个期间的数据集 + 完整索引。"""

    contents = {
        "current": "period,branch,revenue\n2025-09,A院区,1200\n".encode("utf-8"),
        "baseline": "period,branch,revenue\n2025-08,A院区,1000\n".encode("utf-8"),
    }
    handles = []
    lineages = []
    markdown = "# 报告\n"
    await workspace.awrite_text(workspace_key, "reports/revision-1/report.md", markdown)
    for index, (name, content) in enumerate(contents.items(), start=1):
        dataset_id = f"dataset-url-{name}0000001"
        path = f"报表/数据集/report-1/{dataset_id}.csv"
        await workspace.awrite_bytes(workspace_key, path, content)
        sha = hashlib.sha256(content).hexdigest()
        handle = DatasetHandle(
            dataset_id=dataset_id,
            source_id="mcp-url",
            source_type="url_csv",
            path=path,
            row_count=1,
            size=len(content),
            sha256=sha,
            requirement_id=f"attachment-{index:03d}",
            sql_hash=hashlib.sha256(f"url_csv:{sha}".encode()).hexdigest(),
            filename=f"{name}.csv",
            materialized_at="2026-09-29T08:00:00Z",
            period_roles=("current",) if name == "current" else ("yoy",),
        )
        handles.append(handle)
        lineages.append(
            DatasetLineage(
                datasetId=dataset_id,
                sourceId="mcp-url",
                sourceType="url_csv",
                requirementId=handle.requirement_id,
                sqlHash=handle.sql_hash,
                rowCount=1,
                size=len(content),
                sha256=sha,
                periodRoles=handle.period_roles,
            )
        )
    built = build_csv_trace_index(
        handles=tuple(handles),
        lineage=tuple(lineages),
        report_id="report-1",
        revision=1,
        workflow_run_id="report-1",
        markdown_file=ArtifactFile(
            path="reports/revision-1/report.md",
            mediaType="text/markdown",
            size=len(markdown.encode("utf-8")),
            sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        ),
    )
    await workspace.awrite_bytes(
        workspace_key,
        "reports/revision-1/trace-index-v1.json",
        encode_trace_index(built),
    )
    from .lineage_fixtures.manifest import register_trace_manifest
    _REGISTERED_MANIFESTS["report-1"] = await register_trace_manifest(workspace, workspace_key, built)


@pytest.mark.anyio
async def test_two_period_datasets_with_roles_are_previewable(tmp_path: Path) -> None:
    scope = _scope()
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    await _write_two_period_datasets(workspace, scope.workspace_key)
    registry.release(scope.workspace_key)
    state = SimpleNamespace(
        payload={"reportEditorContexts": {"1": _context().model_dump(mode="json", by_alias=True)}}
    )
    editor = ReportEditorService(
        state_repository=SimpleNamespace(get=_async_return(state)),
        workspace_registry=registry,
        workspace=workspace,
        trace_cursor_secret=b"trace-cursor-secret-32-bytes-ok!",
    )
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _ = await grants.issue(_context())
    _t, session = await grants.exchange(raw)

    sources = await editor.trace_sources(_context(), session)
    assert sources["available"] is True
    datasets = {d["datasetId"]: d for d in sources["datasets"]}
    assert len(datasets) == 2
    roles = {tuple(d["periodRoles"]) for d in datasets.values()}
    assert roles == {("current",), ("yoy",)}
    for dataset_id, info in datasets.items():
        page = await editor.trace_dataset_preview(_context(), session, dataset_id)
        assert page["rowCountTotal"] == 1
        assert page["rows"][0][0] == ("2025-09" if info["periodRoles"] == ["current"] else "2025-08")


@pytest.mark.anyio
async def test_dataset_not_in_index_is_not_previewable(tmp_path: Path) -> None:
    """未登记进索引的数据集一律 source_missing，不因同名文件存在于磁盘而放行。"""

    editor, grants, workspace = await _make_editor(tmp_path)
    scope = _scope()
    registry = workspace.registry
    registry.resolve(scope)
    await workspace.awrite_bytes(
        scope.workspace_key,
        "报表/数据集/report-1/dataset-url-ghost0001.csv",
        b"period\n2025-09\n",
    )
    registry.release(scope.workspace_key)
    raw, _ = await grants.issue(_context())
    _t, session = await grants.exchange(raw)
    with pytest.raises(ReportingError) as exc:
        await editor.trace_dataset_preview(_context(), session, "dataset-url-ghost0001")
    assert exc.value.code == "source_missing"


# ---------------------------------------------------------------------------
# B2 fact 查询（索引登记事实文件 → facts 清单 → fact 详情含一层输入）
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("identity", ["valid", "other_snapshot", "changed_context"])
async def test_fact_names_use_only_frozen_schema_for_the_registered_snapshot(tmp_path: Path, identity: str) -> None:
    editor, grants, workspace = await _make_editor(tmp_path, with_fact_file=True)
    scope = _scope()
    document = {"datasetContexts": [{
        "datasetId": DATASET_ID,
        "sha256": hashlib.sha256(CSV_BYTES).hexdigest() if identity != "other_snapshot" else "0" * 64,
        "schema": {"sourceId": "dynamic_source", "tables": [{
            "database": "dynamic_db", "name": "dynamic_table",
            "columns": [{"name": "revenue", "description": "医疗业务收入金额"}],
        }]},
    }]}
    content = json.dumps(document, ensure_ascii=False).encode()
    path = "reports/detailed-analysis-context.json"
    workspace.registry.resolve(scope)
    await workspace.awrite_bytes(scope.workspace_key, path, content if identity != "changed_context" else b"{}")
    workspace.registry.release(scope.workspace_key)
    state = await editor.state_repository.get(_context().workflow_run_id)
    state.payload["workflowCheckpoint"] = {"files": [{
        "path": path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
    }]}
    raw, _ = await grants.issue(_context())
    _, session = await grants.exchange(raw)
    sources = await editor.trace_sources(_context(), session)
    metric = next(item for item in sources["facts"] if item["factKind"] == "metric")
    assert metric["name"] == ("医疗业务收入金额" if identity == "valid" else "收入")


@pytest.mark.anyio
async def test_facts_listing_and_fact_detail_with_inputs(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path, with_fact_file=True)
    raw, _ = await grants.issue(_context())
    _t, session = await grants.exchange(raw)

    listing = await editor.trace_facts(_context(), session)
    assert listing["available"] is True
    assert listing["analyses"][0]["analysisId"] == "analysis_001"
    assert listing["analyses"][0]["contentKind"] == "deterministic_bundle"

    sources = await editor.trace_sources(_context(), session)
    manifest = await editor.trace.load_manifest(_context())
    assert sources["citations"] == [
        {"citationId": item.citation_id, "datasetId": item.dataset_id}
        for item in manifest.citations
    ]
    source_facts = {fact["factId"]: fact for fact in sources["facts"]}
    assert source_facts["fact-" + "a" * 16]["label"].startswith("指标 · ")
    assert source_facts["fact-" + "b" * 16]["label"].startswith("派生指标 · ")
    assert source_facts["fact-" + "a" * 16]["name"]
    assert source_facts["fact-" + "b" * 16]["displayValue"] == 120.0
    assert source_facts["fact-" + "b" * 16]["datasetIds"]
    assert all(fact["analysisId"] == "analysis_001" for fact in source_facts.values())
    assert all(fact["analysisName"] == "2025年收入汇总" for fact in source_facts.values())

    derived = await editor.trace_fact_detail(
        _context(), session, "analysis_001", "fact-" + "b" * 16
    )
    assert derived["factKind"] == "derived"
    assert derived["displayValue"] == 120.0
    # 派生事实暴露一层输入（分子 income_total 对应 metric fact）。
    assert derived["inputFactRefs"]
    assert derived["inputFactRefs"][0]["factId"] == "fact-" + "a" * 16

    metric = await editor.trace_fact_detail(
        _context(), session, "analysis_001", "fact-" + "a" * 16
    )
    assert metric["factKind"] == "metric"
    assert metric["analysisName"] == "2025年收入汇总"
    assert source_facts["fact-" + "a" * 16]["displayValue"] == metric["displayValue"]
    assert metric["displayValue"] == 3600.0
    assert metric["inputFactRefs"] == ()  # metric 是叶子


@pytest.mark.anyio
async def test_fact_detail_rejects_unknown_analysis_and_fact(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path, with_fact_file=True)
    raw, _ = await grants.issue(_context())
    _t, session = await grants.exchange(raw)
    with pytest.raises(ReportingError) as exc:
        await editor.trace_fact_detail(_context(), session, "analysis_999", "fact-" + "a" * 16)
    assert exc.value.code == "source_missing"
    with pytest.raises(ReportingError) as exc:
        await editor.trace_fact_detail(_context(), session, "analysis_001", "fact-" + "e" * 16)
    assert exc.value.code == "fact_binding_unavailable"


def test_fact_detail_locates_correlation_facts() -> None:
    """相关性事实（correlationDetails）同样可被引用绑定，事实详情必须能定位与解析。"""
    from smart_reporting.report_editor.trace_sources import ReportEditorTraceService
    from smart_reporting.reporting.trace.contracts_v1 import FactRefV1
    from smart_reporting.reporting.trace.fact_service import resolve_fact

    fact_id = "fact-" + "c" * 16
    bundle = json.dumps({
        "analysisId": "analysis_001",
        "metrics": [],
        "correlationDetails": [{
            "factId": fact_id, "datasetId": DATASET_ID, "leftField": "visits",
            "rightField": "revenue", "method": "pearson", "sampleCount": 12, "value": 0.82,
        }],
    }).encode("utf-8")
    pointer = ReportEditorTraceService._locate_fact_pointer(bundle, fact_id)
    assert pointer == "/correlationDetails/0"
    kind = ReportEditorTraceService._pointer_kind(pointer)
    assert kind == "correlation"
    detail = resolve_fact(bundle, FactRefV1(
        analysisId="analysis_001", fileResourceId="trf-" + "0" * 20,
        jsonPointer=pointer, factKind=kind, factKey=fact_id,
    ))
    assert detail["factKind"] == "correlation"
    assert detail["displayValue"] == 0.82


@pytest.mark.anyio
async def test_http_facts_routes(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path, with_fact_file=True)
    raw, _ = await grants.issue(_context())
    app = FastAPI()
    app.include_router(
        create_report_editor_router(grants, editor=editor, cookie_secure=False)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        listing = await client.get("/reports/v1/editor/report-1/1/api/facts")
        assert listing.status_code == 200
        assert listing.json()["analyses"][0]["analysisId"] == "analysis_001"

        detail = await client.get(
            "/reports/v1/editor/report-1/1/api/facts/analysis_001/fact-" + "b" * 16
        )
        assert detail.status_code == 200
        body = detail.json()
        assert body["factKind"] == "derived" and body["displayValue"] == 120.0
        assert body["inputFactRefs"][0]["factId"] == "fact-" + "a" * 16

        missing = await client.get(
            "/reports/v1/editor/report-1/1/api/facts/analysis_001/fact-" + "f" * 16
        )
        assert missing.status_code == 409
        assert missing.json()["detail"]["code"] == "fact_binding_unavailable"


# ---------------------------------------------------------------------------
# B7：subject → 登记指标 → 冻结快照单维度下钻
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_subject_drilldown_lists_capability_and_reconciles(
    tmp_path: Path,
) -> None:
    editor, grants, _ = await _make_editor(
        tmp_path, with_fact_file=True, with_drilldown=True
    )
    raw, _ = await grants.issue(_context())
    _token, session = await grants.exchange(raw)

    sources = await editor.trace_sources(_context(), session)
    capability = sources["drilldown"]["subjects"][0]
    assert capability["subjectId"] == "sub-" + "c" * 16
    assert capability["metrics"][0]["dimensions"] == [
        {"code": "branch", "label": "院区"}
    ]

    page = await editor.trace_drilldown(
        _context(),
        session,
        "sub-" + "c" * 16,
        metric_code="income_total",
        dataset_id=DATASET_ID,
        dimension_code="branch",
    )
    assert page["rows"] == [
        {"group": "A院区", "value": 1200.0},
        {"group": "B院区", "value": 2400.0},
    ]
    assert page["reconciliation"] == {
        "expectedValue": 3600.0,
        "observedValue": 3600.0,
        "difference": 0.0,
        "passed": True,
    }


@pytest.mark.anyio
async def test_share_sessions_do_not_receive_raw_query_sql(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path)
    full = await editor.trace_sources(_context(), SimpleNamespace(capabilities=None))
    assert full["datasets"][0]["querySql"].startswith("SELECT branch, revenue")
    raw, _ = await grants.issue(_context(), capabilities={"blocked_columns": ["revenue"]})
    _token, session = await grants.exchange(raw)
    # 分享会话是受限视图：原始 SQL 会暴露库表结构、过滤字面值和被屏蔽列名，只保留哈希。
    shared = await editor.trace_sources(_context(), session)
    assert shared["datasets"][0]["querySql"] is None
    assert shared["datasets"][0]["sqlHash"] == full["datasets"][0]["sqlHash"]


@pytest.mark.anyio
async def test_blocked_drilldown_input_is_hidden_and_rejected(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(
        tmp_path, with_fact_file=True, with_drilldown=True
    )
    raw, _ = await grants.issue(
        _context(), capabilities={"drilldown": True, "blocked_columns": ["revenue"]}
    )
    _token, session = await grants.exchange(raw)

    sources = await editor.trace_sources(_context(), session)
    assert sources["drilldown"] == {"enabled": True, "metrics": [], "subjects": []}

    with pytest.raises(ReportingError) as denied:
        await editor.trace_drilldown_metric(
            _context(),
            session,
            "income_total",
            dataset_id=DATASET_ID,
            dimension_code="branch",
        )
    assert denied.value.code == "dataset_access_denied"


@pytest.mark.anyio
async def test_http_drilldown_rejects_share_and_cross_subject(
    tmp_path: Path,
) -> None:
    editor, grants, _ = await _make_editor(
        tmp_path, with_fact_file=True, with_drilldown=True
    )
    owner_raw, _ = await grants.issue(_context())
    share_raw, _ = await grants.issue(
        _context(), capabilities={"drilldown": False}
    )
    app = FastAPI()
    app.include_router(
        create_report_editor_router(grants, editor=editor, cookie_secure=False)
    )
    path = (
        "/reports/v1/editor/report-1/1/api/sources/"
        + "sub-"
        + "c" * 16
        + "/drilldown"
    )
    payload = {
        "metricCode": "income_total",
        "datasetId": DATASET_ID,
        "dimensionCode": "branch",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        await client.get(f"/reports/v1/editor/open/{owner_raw}", follow_redirects=False)
        response = await client.post(path, json=payload)
        assert response.status_code == 200
        assert response.json()["reconciliation"]["passed"] is True

        missing = await client.post(path.replace("c" * 16, "e" * 16), json=payload)
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "source_missing"

        await client.get(f"/reports/v1/editor/open/{share_raw}", follow_redirects=False)
        denied = await client.post(path, json=payload)
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "dataset_access_denied"


@pytest.mark.anyio
async def test_http_registered_metric_drilldown_is_not_limited_to_text_subjects(
    tmp_path: Path,
) -> None:
    editor, grants, _ = await _make_editor(
        tmp_path, with_fact_file=True, with_drilldown=True
    )
    owner_raw, _ = await grants.issue(_context())
    share_raw, _ = await grants.issue(_context(), capabilities={"drilldown": False})
    app = FastAPI()
    app.include_router(
        create_report_editor_router(grants, editor=editor, cookie_secure=False)
    )
    path = "/reports/v1/editor/report-1/1/api/drilldowns/income_total"
    payload = {
        "metricCode": "income_total",
        "datasetId": DATASET_ID,
        "dimensionCode": "branch",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        await client.get(f"/reports/v1/editor/open/{owner_raw}", follow_redirects=False)
        sources = await client.get("/reports/v1/editor/report-1/1/api/sources")
        assert sources.json()["drilldown"]["metrics"][0]["metricCode"] == "income_total"

        response = await client.post(path, json=payload)
        assert response.status_code == 200
        assert response.json()["rows"][1] == {"group": "B院区", "value": 2400.0}

        mismatch = await client.post(
            path, json={**payload, "metricCode": "another_metric"}
        )
        assert mismatch.status_code == 400
        assert mismatch.json()["detail"]["code"] == "request_invalid"

        await client.get(f"/reports/v1/editor/open/{share_raw}", follow_redirects=False)
        denied = await client.post(path, json=payload)
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == "dataset_access_denied"


@pytest.mark.anyio
async def test_drilldown_timeout_has_stable_resource_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from smart_reporting.report_editor import trace_sources

    editor, grants, _ = await _make_editor(
        tmp_path, with_fact_file=True, with_drilldown=True
    )
    raw, _ = await grants.issue(_context())
    _token, session = await grants.exchange(raw)
    monkeypatch.setattr(trace_sources, "_DRILLDOWN_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        editor.trace._drilldown,
        "drilldown",
        lambda *_args, **_kwargs: time.sleep(0.05),
    )

    with pytest.raises(ReportingError) as timeout:
        await editor.trace_drilldown(
            _context(),
            session,
            "sub-" + "c" * 16,
            metric_code="income_total",
            dataset_id=DATASET_ID,
            dimension_code="branch",
        )
    assert timeout.value.code == "resource_limit_exceeded"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("large_file_threshold", "expected_peak"),
    [(10**9, 4), (0, 1)],
    ids=("small-file", "large-file"),
)
async def test_drilldown_execution_is_capped_at_four_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    large_file_threshold: int,
    expected_peak: int,
) -> None:
    from smart_reporting.report_editor import trace_sources

    monkeypatch.setattr(
        trace_sources, "_DRILLDOWN_LARGE_FILE_BYTES", large_file_threshold
    )
    editor, grants, _ = await _make_editor(
        tmp_path, with_fact_file=True, with_drilldown=True
    )
    raw, _ = await grants.issue(_context())
    _token, session = await grants.exchange(raw)
    original = editor.trace._drilldown.drilldown
    guard = threading.Lock()
    active = 0
    peak = 0

    def tracked(*args, **kwargs):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.05)
            return original(*args, **kwargs)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(editor.trace._drilldown, "drilldown", tracked)
    requests = [
        editor.trace_drilldown_metric(
            _context(),
            session,
            "income_total",
            dataset_id=DATASET_ID,
            dimension_code="branch",
        )
        for _ in range(8)
    ]

    pages = await asyncio.gather(*requests)

    assert peak == expected_peak
    assert all(page["reconciliation"]["passed"] is True for page in pages)


@pytest.mark.anyio
async def test_revision_snapshot_preserves_drilldown_declaration_and_answer(
    tmp_path: Path,
) -> None:
    editor, _grants, _ = await _make_editor(
        tmp_path, with_fact_file=True, with_drilldown=True
    )
    context = await editor._source_context(_context())
    manifest = await editor.trace.load_manifest(context)
    index = await editor.trace.load_index(context)
    assert manifest is not None and index is not None
    thread_id = context.scope["threadId"]
    markdown = "# 报告\n"
    target_path = "reports/revision-2/report.md"
    await editor.workspace.awrite_text(thread_id, target_path, markdown)
    markdown_file = ArtifactFile(
        path=target_path,
        mediaType="text/markdown",
        size=len(markdown.encode()),
        sha256=hashlib.sha256(markdown.encode()).hexdigest(),
    )
    path_map = {
        file.path: f"reports/revision-2/resources/{file.path}"
        for file in index.files
        if file.resource_id != index.markdown_file_resource_id
    }
    _next_manifest, manifest_identity = await snapshot_revision_lineage(
        editor.workspace,
        thread_id,
        manifest=manifest,
        index=index,
        markdown_file=markdown_file,
        target_revision=2,
        path_map=path_map,
        manifest_path="reports/revision-2/report.manifest.json",
    )
    next_context = context.model_copy(
        update={
            "revision": 2,
            "markdown_path": target_path,
            "artifact_manifest": manifest_identity,
        }
    )
    next_index = await editor.trace.load_index(next_context)
    assert next_index is not None
    assert next_index.drilldown_metrics == index.drilldown_metrics
    assert next_index.datasets[0].file_resource_id != index.datasets[0].file_resource_id

    first = await editor.trace.drilldown_metric(
        context,
        None,
        "income_total",
        dataset_id=DATASET_ID,
        dimension_code="branch",
    )
    second = await editor.trace.drilldown_metric(
        next_context,
        None,
        "income_total",
        dataset_id=DATASET_ID,
        dimension_code="branch",
    )
    assert first["snapshot"]["sha256"] == second["snapshot"]["sha256"]
    assert first["reconciliation"] == second["reconciliation"] == {
        "expectedValue": 3600.0,
        "observedValue": 3600.0,
        "difference": 0.0,
        "passed": True,
    }


@pytest.mark.anyio
async def test_reanalysis_new_snapshot_does_not_change_old_revision_drilldown(
    tmp_path: Path,
) -> None:
    from smart_reporting.reporting.trace.contracts_v1 import (
        DrilldownDimensionV1,
        DrilldownMetricV1,
    )

    from .lineage_fixtures.manifest import register_trace_manifest

    editor, _grants, workspace = await _make_editor(
        tmp_path, with_fact_file=True, with_drilldown=True
    )
    first_context = await editor._source_context(_context())
    thread_id = first_context.scope["threadId"]
    second_csv = (
        b"period,branch,revenue,visits\n"
        b"2025-10,A\xe9\x99\xa2\xe5\x8c\xba,1500,10\n"
        b"2025-10,B\xe9\x99\xa2\xe5\x8c\xba,2500,20\n"
    )
    second_csv_path = "reports/revision-2/reanalysis.csv"
    second_markdown_path = "reports/revision-2/report.md"
    second_markdown = b"# Reanalysis\n"
    await workspace.awrite_bytes(thread_id, second_csv_path, second_csv)
    await workspace.awrite_bytes(thread_id, second_markdown_path, second_markdown)
    second_sha = hashlib.sha256(second_csv).hexdigest()
    second_handle = DatasetHandle(
        dataset_id="dataset-reanalysis02",
        source_id="mcp-url",
        source_type="url_csv",
        path=second_csv_path,
        row_count=2,
        size=len(second_csv),
        sha256=second_sha,
        requirement_id="attachment-002",
        sql_hash=hashlib.sha256(f"url_csv:{second_sha}".encode()).hexdigest(),
        filename="重新分析收入.csv",
    )
    second_lineage = DatasetLineage(
        datasetId=second_handle.dataset_id,
        sourceId=second_handle.source_id,
        sourceType=second_handle.source_type,
        requirementId=second_handle.requirement_id,
        sqlHash=second_handle.sql_hash,
        rowCount=second_handle.row_count,
        size=second_handle.size,
        sha256=second_handle.sha256,
    )
    second_index = build_csv_trace_index(
        handles=(second_handle,),
        lineage=(second_lineage,),
        report_id="report-1",
        revision=2,
        workflow_run_id="report-1",
        markdown_file=ArtifactFile(
            path=second_markdown_path,
            mediaType="text/markdown",
            size=len(second_markdown),
            sha256=hashlib.sha256(second_markdown).hexdigest(),
        ),
        drilldown_metrics=(
            DrilldownMetricV1(
                metricCode="income_total",
                datasetId=second_handle.dataset_id,
                aggregation="sum",
                valueField="revenue",
                dimensions=(
                    DrilldownDimensionV1(code="branch", field="branch", label="院区"),
                ),
                expectedValue=4000.0,
                unit="元",
            ),
        ),
    )
    await workspace.awrite_bytes(
        thread_id,
        "reports/revision-2/trace-index-v1.json",
        encode_trace_index(second_index),
    )
    second_manifest = await register_trace_manifest(
        workspace, thread_id, second_index
    )
    second_context = first_context.model_copy(
        update={
            "revision": 2,
            "markdown_path": second_markdown_path,
            "artifact_manifest": second_manifest,
        }
    )

    first = await editor.trace.drilldown_metric(
        first_context,
        None,
        "income_total",
        dataset_id=DATASET_ID,
        dimension_code="branch",
    )
    second = await editor.trace.drilldown_metric(
        second_context,
        None,
        "income_total",
        dataset_id=second_handle.dataset_id,
        dimension_code="branch",
    )
    replay_first = await editor.trace.drilldown_metric(
        first_context,
        None,
        "income_total",
        dataset_id=DATASET_ID,
        dimension_code="branch",
    )

    assert first == replay_first
    assert first["reconciliation"]["observedValue"] == 3600.0
    assert second["reconciliation"]["observedValue"] == 4000.0
    assert first["snapshot"]["sha256"] != second["snapshot"]["sha256"]


# ---------------------------------------------------------------------------
# B3 第二增量：图表来源清单/详情 + 作图表预览
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_charts_listing_and_source_with_plot_data_preview(
    tmp_path: Path,
) -> None:
    editor, grants, _ = await _make_editor(tmp_path, with_chart_trace=True)
    raw, _ = await grants.issue(_context())
    _t, session = await grants.exchange(raw)

    listing = await editor.trace_charts(_context(), session)
    assert listing["available"] is True
    assert listing["charts"][0]["chartId"] == "chart_001"
    assert listing["charts"][0]["datasetIds"] == [DATASET_ID]
    assert listing["charts"][0]["plotDataFileCount"] == 1

    source = await editor.trace_chart_source(_context(), session, "chart_001")
    assert source["available"] is True
    assert source["image"]["size"] > 0
    assert source["transformNotes"] == ["作图数据由服务端 chart-input/v1 物化"]
    plot = source["plotData"][0]
    assert plot["columns"] == ["period", "revenue"]
    assert plot["rowCount"] == 2
    assert plot["rows"][0] == ["2025-09", 3600.0]
    assert "path" not in plot  # 不泄露工作区路径
    # 分页：offset=1 只返回第二行。
    paged = await editor.trace_chart_source(
        _context(), session, "chart_001", preview_limit=1, preview_offset=1
    )
    assert paged["plotData"][0]["rows"] == [["2025-08", 3000.0]]
    assert paged["plotData"][0]["truncated"] is False
    # 负偏移在切片中会从尾部取行，必须作为非法请求拒绝。
    with pytest.raises(ReportingError) as negative:
        await editor.trace_chart_source(
            _context(), session, "chart_001", preview_limit=1, preview_offset=-1
        )
    assert negative.value.code == "request_invalid"


@pytest.mark.anyio
async def test_validate_marks_deleted_chart_unbound_and_keeps_present_chart(
    tmp_path: Path,
) -> None:
    """B8 图表重判：登记图仍在正文 → valid；草稿删图 → unbound。"""
    editor, grants, _ = await _make_editor(
        tmp_path, with_chart_trace=True, with_fact_file=True, with_drilldown=True
    )
    raw, _ = await grants.issue(_context())
    _t, session = await grants.exchange(raw)

    present = "![趋势](chart-001.png)\n\n*图表：收入趋势*\n\n收入 3600[[claim:claim-1]]"
    result = await editor.trace_validate(
        _context(), session, present, hashlib.sha256(present.encode()).hexdigest()
    )
    assert result["charts"] == [
        {
            "chartId": "chart_001",
            "imagePath": "reports/revision-1/chart-001.png",
            "locationSource": "chart-001.png",
            "status": "valid",
        }
    ]

    deleted = "图片已删除，只保留文字结论。[[claim:claim-1]]"
    deleted_result = await editor.trace_validate(
        _context(), session, deleted, hashlib.sha256(deleted.encode()).hexdigest()
    )
    assert deleted_result["charts"][0]["status"] == "unbound"


@pytest.mark.anyio
async def test_chart_source_unknown_chart_is_404_like(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path, with_chart_trace=True)
    raw, _ = await grants.issue(_context())
    _t, session = await grants.exchange(raw)
    with pytest.raises(ReportingError) as exc:
        await editor.trace_chart_source(_context(), session, "chart_999")
    assert exc.value.code == "source_missing"


@pytest.mark.anyio
async def test_http_charts_routes(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path, with_chart_trace=True)
    raw, _ = await grants.issue(_context())
    app = FastAPI()
    app.include_router(
        create_report_editor_router(grants, editor=editor, cookie_secure=False)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        listing = await client.get("/reports/v1/editor/report-1/1/api/charts")
        assert listing.status_code == 200
        assert listing.json()["charts"][0]["chartId"] == "chart_001"

        source = await client.get(
            "/reports/v1/editor/report-1/1/api/charts/chart_001/source",
            params={"limit": 1},
        )
        assert source.status_code == 200
        body = source.json()
        assert body["plotData"][0]["rowCount"] == 2
        assert len(body["plotData"][0]["rows"]) == 1
        assert body["plotData"][0]["truncated"] is True

        invalid = await client.get(
            "/reports/v1/editor/report-1/1/api/charts/chart_001/source",
            params={"limit": 0},
        )
        assert invalid.status_code == 400
        assert invalid.json()["detail"]["code"] == "request_invalid"

        missing = await client.get(
            "/reports/v1/editor/report-1/1/api/charts/chart_999/source"
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "source_missing"


# ---------------------------------------------------------------------------
# B4 第二增量：计算链清单/详情 + 展开
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_computations_listing_and_detail(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path, with_computation=True)
    raw, _ = await grants.issue(_context())
    _t, session = await grants.exchange(raw)

    listing = await editor.trace_computations(_context(), session)
    assert listing["available"] is True
    entry = listing["computations"][0]
    assert entry["method"] == "supplemental_analysis"
    assert entry["reproducibility"] == "reproducible"
    assert entry["verification"] == "not_checked"

    detail = await editor.trace_computation_detail(
        _context(), session, entry["computationId"]
    )
    assert detail["executionId"] == "exec-1"
    assert detail["environment"]["python"] == "3.12.0"
    assert detail["parameters"]["requirements"] == []  # 计划 requirements 未提供
    assert detail["outputFactRefs"][0]["jsonPointer"] == "/findings/rows/0"
    assert detail["scriptFile"]["size"] > 0
    assert "path" not in detail["scriptFile"]  # 不泄露工作区路径
    assert detail["chain"]["computationId"] == entry["computationId"]

    with pytest.raises(ReportingError) as exc:
        await editor.trace_computation_detail(_context(), session, "comp-" + "f" * 16)
    assert exc.value.code == "source_missing"


@pytest.mark.anyio
async def test_http_computation_routes(tmp_path: Path) -> None:
    editor, grants, _ = await _make_editor(tmp_path, with_computation=True)
    raw, _ = await grants.issue(_context())
    app = FastAPI()
    app.include_router(
        create_report_editor_router(grants, editor=editor, cookie_secure=False)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        listing = await client.get("/reports/v1/editor/report-1/1/api/computations")
        assert listing.status_code == 200
        computation_id = listing.json()["computations"][0]["computationId"]

        detail = await client.get(
            f"/reports/v1/editor/report-1/1/api/computations/{computation_id}"
        )
        assert detail.status_code == 200
        assert detail.json()["environment"]["polars"] == "1.43.2"

        missing = await client.get(
            "/reports/v1/editor/report-1/1/api/computations/comp-none000000000000000"
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "source_missing"


@pytest.mark.anyio
@pytest.mark.parametrize("change_stage", ["before_snapshot", "during_read"])
async def test_drilldown_reads_verified_request_snapshot(tmp_path, monkeypatch, change_stage):
    editor, grants, _ = await _make_editor(tmp_path, with_fact_file=True, with_drilldown=True)
    raw, _ = await grants.issue(_context())
    _, session = await grants.exchange(raw)
    resolve = editor.trace._resolve_dataset_file
    drilldown = editor.trace._drilldown.drilldown
    source_paths = []
    read_paths = []

    def replace_source(path):
        original = path.read_bytes()
        changed = original.replace(b",1200,", b",1300,").replace(b",2400,", b",2300,")
        assert original != changed and len(original) == len(changed)
        path.write_bytes(changed)

    async def resolve_and_change(*args, **kwargs):
        file = await resolve(*args, **kwargs)
        source_paths.append(file.local_path)
        if change_stage == "before_snapshot":
            replace_source(file.local_path)
        return file

    def read_and_change(file, *args, **kwargs):
        read_paths.append(file.local_path)
        if change_stage == "during_read":
            replace_source(source_paths[0])
        return drilldown(file, *args, **kwargs)

    monkeypatch.setattr(editor.trace, "_resolve_dataset_file", resolve_and_change)
    monkeypatch.setattr(editor.trace._drilldown, "drilldown", read_and_change)
    arguments = dict(metric_code="income_total", dataset_id=DATASET_ID, dimension_code="branch")
    if change_stage == "before_snapshot":
        with pytest.raises(ReportingError) as error:
            await editor.trace_drilldown(_context(), session, "sub-" + "c" * 16, **arguments)
        assert error.value.code == "snapshot_integrity_failed"
        assert not read_paths
    else:
        result = await editor.trace_drilldown(_context(), session, "sub-" + "c" * 16, **arguments)
        assert result["rows"] == [{"group": "A院区", "value": 1200.0}, {"group": "B院区", "value": 2400.0}]
        assert result["snapshot"]["sha256"] == hashlib.sha256(CSV_BYTES).hexdigest()
        assert read_paths[0] != source_paths[0]
        assert not read_paths[0].exists()
