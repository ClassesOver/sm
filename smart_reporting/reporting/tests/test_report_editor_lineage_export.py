"""Service export integration with real workspace, durable reducer, and frozen lineage.

Rendering and artifact persistence are mocked; PDF/Word visual output is not tested.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agno.run import RunContext

from smart_reporting.report_editor import ReportEditorContext
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile, ChartArtifact
from smart_reporting.reporting.delivery.publishing import ReportDownloadGrant
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
from smart_reporting.reporting.tests.test_trace_subject_validate import _make_editor_with_subject
from smart_reporting.reporting.trace.contracts_v1 import (
    ChartTraceV1,
    DrilldownDimensionV1,
    DrilldownMetricV1,
    TraceFileRefV1,
    derive_resource_id,
)
from smart_reporting.reporting.trace.index_builder import encode_trace_index
from smart_reporting.reporting.workflow.state import ReportingCommand, ReportingRunState, apply
from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [None, "render", "commit", "download_grant", "editor_grant"])
async def test_export_revision_rebinds_registered_lineage_and_preserves_transactional_files(
    tmp_path: Path, failure: str | None
) -> None:
    editor, grants, original = await _make_editor_with_subject(tmp_path)
    thread_id = original.scope["threadId"]
    workspace = editor.workspace
    index = await editor.trace.load_index(original)
    assert index is not None
    chart_path = "reports/revision-1/chart-001.png"
    chart_bytes = b"registered-chart-image"
    chart = ChartArtifact(
        path=chart_path,
        mediaType="image/png",
        size=len(chart_bytes),
        sha256=hashlib.sha256(chart_bytes).hexdigest(),
        chartId="chart_001",
        datasetIds=("dataset-url-abc0001",),
    )
    await workspace.awrite_bytes(thread_id, chart_path, chart_bytes)
    plot_path = "reports/revision-1/chart-001.chart-input.json"
    plot_bytes = (
        b'{"schema":"chart-input/v1","chartId":"chart_001","role":"measure",'
        b'"columns":["period","revenue"],"rows":[["2025-09",3600]],"rowCount":1}'
    )
    await workspace.awrite_bytes(thread_id, plot_path, plot_bytes)
    header = (
        '# Revenue report\n\n<a id="report-section-section_002"></a>\n'
        "## 1 Report\n\n[[section:section_002]]\n[[analysis:analysis_001]]\n\n"
    )
    footer = "\n\n![Revenue](chart-001.png) [[citation:citation_001]]\n"
    original_markdown = header + "Revenue 3600 [[claim:claim-1]]" + footer
    edited_markdown = header + "Revenue 3800 [[claim:claim-1]]" + footer
    original_file = ArtifactFile(
        path=original.markdown_path,
        mediaType="text/markdown",
        size=len(original_markdown.encode()),
        sha256=_sha(original_markdown.encode()),
    )
    await workspace.awrite_text(
        thread_id, original.markdown_path, original_markdown, overwrite=True
    )
    files = tuple(
        item.model_copy(update={"size": original_file.size, "sha256": original_file.sha256})
        if item.resource_id == index.markdown_file_resource_id
        else item
        for item in index.files
    )
    index = index.model_copy(
        update={
            "files": (
                *files,
                TraceFileRefV1(
                    resourceId=derive_resource_id(chart_path),
                    path=chart_path,
                    mediaType="image/png",
                    size=chart.size,
                    sha256=chart.sha256,
                ),
                TraceFileRefV1(
                    resourceId=derive_resource_id(plot_path),
                    path=plot_path,
                    mediaType="application/json",
                    size=len(plot_bytes),
                    sha256=_sha(plot_bytes),
                ),
            ),
            "chart_traces": (
                ChartTraceV1(
                    chartId="chart_001",
                    imageFileResourceId=derive_resource_id(chart_path),
                    plotDataFileResourceIds=(derive_resource_id(plot_path),),
                    datasetIds=chart.dataset_ids,
                ),
            ),
            "drilldown_metrics": (
                DrilldownMetricV1(
                    metricCode="income_total",
                    datasetId="dataset-url-abc0001",
                    aggregation="sum",
                    valueField="revenue",
                    dimensions=(
                        DrilldownDimensionV1(
                            code="period", field="period", label="期间"
                        ),
                    ),
                    expectedValue=3600.0,
                    unit="万元",
                    factKeys=("fact-" + "a" * 16,),
                ),
            ),
        }
    )
    await workspace.awrite_bytes(
        thread_id,
        "reports/revision-1/trace-index-v1.json",
        encode_trace_index(index),
        overwrite=True,
    )
    await workspace.adelete_file(thread_id, original.artifact_manifest.path)
    manifest_identity = await register_trace_manifest(workspace, thread_id, index)
    original = original.model_copy(update={"artifact_manifest": manifest_identity})
    manifest = await editor.trace.load_manifest(original)
    assert manifest is not None
    manifest = manifest.model_copy(update={"charts": (chart,), "analysis_ids": ("analysis_001",)})
    manifest_bytes = manifest.model_dump_json(by_alias=True).encode()
    await workspace.awrite_bytes(thread_id, manifest_identity.path, manifest_bytes, overwrite=True)
    manifest_identity = manifest_identity.model_copy(
        update={
            "size": len(manifest_bytes),
            "sha256": _sha(manifest_bytes),
        }
    )
    source_evidence = {
        file.path: (await workspace.afile_bytes(thread_id, file.path))[0] for file in index.files
    }
    draft_path = "reports/revision-1/draft/report.md"
    await workspace.awrite_text(thread_id, draft_path, edited_markdown)
    for suffix, content in (("pdf", b"old-pdf"), ("docx", b"old-word")):
        await workspace.awrite_bytes(thread_id, f"reports/revision-1/report.{suffix}", content)
    original_csv_path = "报表/数据集/report-1/dataset-url-abc0001.csv"
    original_csv = (await workspace.afile_bytes(thread_id, original_csv_path))[0]
    job = {
        **original.job,
        "render": {
            "pdf": _identity("reports/revision-1/report.pdf", b"old-pdf"),
            "word": _identity("reports/revision-1/report.docx", b"old-word"),
            "markdown": _identity(original.markdown_path, original_markdown.encode()),
            "images": [_identity(chart_path, chart_bytes)],
        },
    }
    context = original.model_copy(update={"job": job, "artifact_manifest": manifest_identity})
    durable = ReportingRunState.initial(
        report_run_id=context.workflow_run_id,
        external_run_id="external-1",
        thread_id="caller-thread",
        owner_user_id="user-1",
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}},
    )
    repository = _StateRepository(durable, failure=failure)
    editor.state_repository = repository
    snapshot_paths: list[str] = []
    persisted: list[object] = []

    class ReportTools:
        async def _render_report_pair(
            self,
            actual_job_id: str,
            markdown_path: str,
            output_path: str,
            *,
            artifact_manifest,
            run_context: RunContext,
        ):
            assert actual_job_id == context.job_id
            assert markdown_path.startswith("reports/revision-1/.export-")
            snapshot_paths.append(markdown_path)
            snapshot, _ = await workspace.afile_bytes(thread_id, markdown_path)
            assert snapshot.decode() == edited_markdown
            assert artifact_manifest is not None
            assert artifact_manifest["revision"] == 2
            assert artifact_manifest["markdown"] == {
                **_identity(markdown_path, snapshot),
                "mediaType": "text/markdown",
            }
            assert artifact_manifest["charts"][0]["path"] == chart_path
            assert artifact_manifest["charts"][0]["chartId"] == "chart_001"
            assert artifact_manifest["analysisIds"] == ["analysis_001"]
            render_job = run_context.session_state[REPORT_JOBS_STATE_KEY][context.job_id]
            trace_sources = render_job.pop("_traceSourcePresentations")
            if failure is None:
                assert render_job.pop("_editorExportSettings") == {"sources": False}
            assert render_job == job
            # B8：数据来源附录载荷与渲染同一次快照装配——claim 摘要来自冻结事实，
            # 状态来自草稿校验（3800 改值 → stale），在线定位指向 N+1 revision。
            subject_id = "sub-" + "0" * 16
            assert trace_sources["claims"] == [
                {
                    "claimId": "claim-1",
                    "subjectIds": [subject_id],
                    "links": [
                        {
                            "subjectId": subject_id,
                            "url": (
                                "https://reports.example.com/reports/v1/editor/"
                                f"report-1/2?subject={subject_id}"
                            ),
                        }
                    ],
                    "status": "stale",
                    "factValue": 3600.0,
                    "unit": "万元",
                    "periods": ["2025-09"],
                    "formula": "sum(revenue)",
                    "scope": {},
                    "datasetIds": ["dataset-url-abc0001"],
                }
            ]
            assert trace_sources["charts"] == [
                {
                    "chartId": "chart_001",
                    "subjectIds": [],
                    "status": "valid",
                    "imagePath": chart_path,
                    "datasetIds": ["dataset-url-abc0001"],
                    "methods": [],
                    "transformNotes": [],
                    "unit": None,
                    "links": [],
                }
            ]
            assert trace_sources["tables"][0]["tableId"] == "tbl-1"
            assert trace_sources["tables"][0]["datasetIds"] == ["dataset-url-abc0001"]
            assert trace_sources["datasets"]["dataset-url-abc0001"] == {
                "filename": "收入明细.csv",
                "businessLabel": None,
                "periodRoles": ["current"],
            }
            # Autosave after the validated snapshot must not change the exported revision.
            await workspace.awrite_text(thread_id, draft_path, "Concurrent edit\n", overwrite=True)
            await workspace.awrite_bytes(thread_id, output_path, b"new-pdf")
            await workspace.awrite_bytes(thread_id, "reports/revision-2/report.docx", b"new-word")
            if failure == "render":
                raise RuntimeError("renderer failed")
            run_context.session_state[REPORT_JOBS_STATE_KEY][context.job_id]["render"] = {
                "pdf": _identity(output_path, b"new-pdf"),
                "word": _identity("reports/revision-2/report.docx", b"new-word"),
                "markdown": _identity(markdown_path, snapshot),
                "images": [_identity(chart_path, chart_bytes)],
            }
            return {"status": "validated", "validation": {"ok": True}}

    class Persistence:
        async def persist(self, **values):
            persisted.extend(values["artifacts"])

    class DownloadGrants:
        async def issue(self, **values):
            assert "2" in repository.durable.payload["reportEditorContexts"]
            if failure == "download_grant":
                raise RuntimeError("download grant store unavailable")
            return "download-raw", ReportDownloadGrant(
                grant_hash="d" * 64,
                expires_at=datetime(2026, 10, 15, tzinfo=UTC),
                **values,
            )

    class EditorGrants:
        async def issue(self, issued_context):
            assert issued_context.revision == 2
            if failure == "editor_grant":
                raise RuntimeError("editor grant store unavailable")
            return "editor-raw", datetime(2026, 10, 15, tzinfo=UTC)

    editor.report_tools = ReportTools()
    editor.artifact_persistence = Persistence()
    editor.download_grants = DownloadGrants()
    editor.editor_grants = EditorGrants()
    editor.public_base_url = "https://reports.example.com"
    if failure is None:
        editor._lineage_features["exportSources"] = False
    expected_sha = _sha(edited_markdown.encode())
    if failure:
        message = {
            "render": "renderer failed",
            "commit": "durable commit failed",
            "download_grant": "download grant store unavailable",
            "editor_grant": "editor grant store unavailable",
        }[failure]
        with pytest.raises(RuntimeError, match=message):
            await editor.export_revision(context, expected_sha256=expected_sha)
    else:
        result = await editor.export_revision(context, expected_sha256=expected_sha)
        assert result["revision"] == 2
        assert result["pdf"]["downloadUrl"].endswith("/reports/v1/download/download-raw")
    assert snapshot_paths
    for path in snapshot_paths:
        assert not await workspace.apath_exists(thread_id, path)
    assert await workspace.aread_text(thread_id, context.markdown_path) == original_markdown
    assert (await workspace.afile_bytes(thread_id, original_csv_path))[0] == original_csv
    for path, content in source_evidence.items():
        assert (await workspace.afile_bytes(thread_id, path))[0] == content
    if failure in {"render", "commit"}:
        assert "2" not in repository.durable.payload["reportEditorContexts"]
        assert not await workspace.apath_exists(thread_id, "reports/revision-2")
        return

    assert {item.artifact for item in persisted} == {"pdf", "word"}
    next_context = ReportEditorContext.model_validate(
        repository.durable.payload["reportEditorContexts"]["2"]
    )
    assert next_context.artifact_manifest is not None
    assert await workspace.aread_text(thread_id, next_context.markdown_path) == edited_markdown
    next_manifest = await editor.trace.load_manifest(next_context)
    next_index = await editor.trace.load_index(next_context)
    assert next_manifest is not None and next_index is not None
    assert next_manifest.markdown.path == next_context.markdown_path
    assert next_manifest.markdown.sha256 == expected_sha
    assert next_manifest.charts[0].path == "reports/revision-2/chart-001.png"
    assert (await editor.read_asset(next_context, "chart-001.png"))[0] == chart_bytes
    for suffix, content in (("pdf", b"new-pdf"), ("docx", b"new-word")):
        assert (await workspace.afile_bytes(thread_id, f"reports/revision-2/report.{suffix}"))[
            0
        ] == content
    raw, _ = await grants.issue(next_context)
    _, session = await grants.exchange(raw)
    assert (await editor.context_for_session(session)) == next_context
    next_sources = await editor.trace_sources(next_context, session)
    assert next_sources["revision"] == 2
    assert next_sources["datasets"][0]["datasetId"] == "dataset-url-abc0001"
    assert next_index.drilldown_metrics == index.drilldown_metrics
    drilldown = await editor.trace_drilldown_metric(
        next_context,
        session,
        "income_total",
        dataset_id="dataset-url-abc0001",
        dimension_code="period",
    )
    assert drilldown["rows"] == [{"group": "2025-09", "value": 3600.0}]
    assert drilldown["reconciliation"]["passed"] is True
    download_path, _, size = await editor.trace_dataset_download(
        next_context,
        session,
        "dataset-url-abc0001",
    )
    assert Path(download_path).read_bytes() == original_csv
    assert size == len(original_csv)
    assert next_manifest.charts[0].chart_id == "chart_001"
    chart_source = await editor.trace_chart_source(next_context, session, "chart_001")
    assert chart_source["chartId"] == "chart_001"
    assert chart_source["plotData"][0]["columns"] == ["period", "revenue"]
    assert chart_source["plotData"][0]["rows"] == [["2025-09", 3600]]
    assert chart_source["plotData"][0]["fileResourceId"] == derive_resource_id(
        "reports/revision-2/chart-001.chart-input.json"
    )
    assert chart_source["plotData"][0]["sha256"] == _sha(plot_bytes)
    facts = await editor.trace_facts(next_context, session)
    assert [item["analysisId"] for item in facts["analyses"]] == ["analysis_001"]
    detail = await editor.trace_fact_detail(
        next_context, session, "analysis_001", "fact-" + "a" * 16
    )
    assert detail["displayValue"] == 3600.0
    assert next_index.subject_bindings[0].subject_sha256 == index.subject_bindings[0].subject_sha256
    validation = await editor.trace_validate(next_context, session, edited_markdown, expected_sha)
    assert validation["summary"] == {"valid": 0, "stale": 1, "unbound": 0}
    # Distinct index revision identity catches accidentally using the current context for history.
    historical = await editor.read_history_revision(next_context, 1)
    assert historical["sources"]["revision"] == 1
    assert historical["sources"] == await editor.trace.sources(context)
    assert (await editor.read_history_revision(context, 2))["sources"]["revision"] == 2


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_export_revision_fails_cleanly_when_lineage_source_file_missing(tmp_path: Path) -> None:
    """故障注入：导出期间来源 CSV 被删除，应失败且不留半成品的 revision-2。"""
    editor, grants, original = await _make_editor_with_subject(tmp_path)
    thread_id = original.scope["threadId"]
    workspace = editor.workspace
    index = await editor.trace.load_index(original)
    assert index is not None
    csv_path = "报表/数据集/report-1/dataset-url-abc0001.csv"
    assert await workspace.apath_exists(thread_id, csv_path)

    header = (
        '# Revenue report\n\n<a id="report-section-section_002"></a>\n'
        "## 1 Report\n\n[[section:section_002]]\n[[analysis:analysis_001]]\n\n"
    )
    footer = "\n\n[[citation:citation_001]]\n"
    edited_markdown = header + "Revenue 3800 [[claim:claim-1]]" + footer
    await workspace.awrite_text(thread_id, original.markdown_path, edited_markdown, overwrite=True)
    await workspace.awrite_text(thread_id, "reports/revision-1/draft/report.md", edited_markdown)
    await workspace.adelete_file(thread_id, csv_path)

    await workspace.adelete_file(thread_id, original.artifact_manifest.path)
    manifest_identity = await register_trace_manifest(workspace, thread_id, index)
    context = original.model_copy(update={"artifact_manifest": manifest_identity})
    durable = ReportingRunState.initial(
        report_run_id=context.workflow_run_id,
        external_run_id="external-1",
        thread_id="caller-thread",
        owner_user_id="user-1",
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}},
    )
    repository = _StateRepository(durable, failure=None)
    editor.state_repository = repository

    class ReportTools:
        async def _render_report_pair(self, *_args, **_kwargs):
            raise AssertionError("渲染不应在来源文件缺失时被调用")

    class Persistence:
        async def persist(self, **_values): return None

    class Grants:
        async def issue(self, **_values):
            raise AssertionError("授权不应在来源文件缺失时被调用")

    editor.report_tools = ReportTools()
    editor.artifact_persistence = Persistence()
    editor.download_grants = Grants()
    editor.editor_grants = Grants()
    editor.public_base_url = "https://reports.example.com"

    with pytest.raises((OSError, ReportingError)):
        await editor.export_revision(context, expected_sha256=_sha(edited_markdown.encode()))

    # 不留下 revision-2 半成品；原 revision-1 草稿保留。
    assert "2" not in repository.durable.payload["reportEditorContexts"]
    assert not await workspace.apath_exists(thread_id, "reports/revision-2")
    assert await workspace.aread_text(thread_id, "reports/revision-1/draft/report.md") == edited_markdown


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _identity(path: str, content: bytes) -> dict[str, object]:
    return {"path": path, "size": len(content), "sha256": _sha(content)}


class _StateRepository:
    def __init__(self, durable: ReportingRunState, *, failure: str | None) -> None:
        self.durable = durable
        self.failure = failure

    async def get(self, _run_id: str):
        return self.durable

    async def apply(self, _run_id: str, command: ReportingCommand, *, expected_version: int):
        assert expected_version == self.durable.state_version
        if self.failure == "commit":
            raise RuntimeError("durable commit failed")
        self.durable = apply(self.durable, command, expected_version=expected_version).state
