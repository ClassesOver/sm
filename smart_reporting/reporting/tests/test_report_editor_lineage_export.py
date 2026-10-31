"""Service export integration with real workspace, durable reducer, and frozen lineage.

Rendering and artifact persistence are mocked; PDF/Word visual output is not tested.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pytest
from agno.run import RunContext

from smart_reporting.report_editor import ReportEditorContext
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile, ChartArtifact
from smart_reporting.reporting.delivery.publishing import ReportDownloadGrant
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
@pytest.mark.parametrize("failure", [
    None,
    "render",
    "commit",
    "download_grant",
    "download_grant_missing_pdf",
    "download_grant_missing_word",
    "download_grant_changed_pdf",
    "download_grant_persistence_pdf",
    "download_grant_persistence_word",
    "editor_grant",
])
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
    download_attempts: list[set[str]] = []
    persistence_calls = 0
    download_failures = 1 if failure and failure.startswith("download_grant") else 0
    retry_unavailable_label = {
        "download_grant_missing_pdf": "pdf",
        "download_grant_missing_word": "word",
        "download_grant_changed_pdf": "pdf",
    }.get(failure)
    retry_persistence_label = {
        "download_grant_persistence_pdf": "pdf",
        "download_grant_persistence_word": "word",
    }.get(failure)

    class ReportTools:
        async def _render_report_pair(
            self,
            actual_job_id: str,
            markdown_path: str,
            output_path: str,
            *,
            artifact_manifest,
            management_overview=None,
            run_context: RunContext,
        ):
            assert actual_job_id == context.job_id
            assert markdown_path.startswith("reports/revision-1/.export-")
            snapshot_paths.append(markdown_path)
            snapshot, _ = await workspace.afile_bytes(thread_id, markdown_path)
            assert snapshot.decode() == edited_markdown
            # 未启用回答审核：质量记录里的总览未评估，导出沿用各章核心结论而不是缺项说明。
            assert management_overview is None
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
            trace_sources = render_job.pop("_traceSourcePresentations", None)
            if failure is None:
                assert render_job.pop("_editorExportSettings") == {"sources": False}
            else:
                assert render_job.pop("_editorExportSettings") == {"sources": True}
            assert render_job == job
            # B8：数据来源附录载荷与渲染同一次快照装配——claim 摘要来自冻结事实，
            # 状态来自草稿校验（3800 改值 → stale），在线定位指向 N+1 revision。
            subject_id = "sub-" + "0" * 16
            if failure is None:
                assert trace_sources is None
            else:
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
                        # 图表未改动；静态图未做数组比对属“未评估”，不能降为待复核。
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
                # 真实渲染器负责清理本次发布的产物；外层尚未接管目录所有权。
                await editor._cleanup_export_revision(
                    workspace, thread_id, "reports/revision-2"
                )
                raise RuntimeError("renderer failed")
            run_context.session_state[REPORT_JOBS_STATE_KEY][context.job_id]["render"] = {
                "pdf": _identity(output_path, b"new-pdf"),
                "word": _identity("reports/revision-2/report.docx", b"new-word"),
                "markdown": _identity(markdown_path, snapshot),
                "images": [_identity(chart_path, chart_bytes)],
            }
            return {"status": "validated", "validation": {"ok": True}}

    class Persistence:
        async def persist_available(self, **values):
            nonlocal persistence_calls
            persistence_calls += 1
            stored = tuple(
                artifact
                for artifact in values["artifacts"]
                if not (
                    persistence_calls > 1
                    and artifact.artifact == retry_persistence_label
                )
            )
            persisted.extend(stored)
            return stored

    class DownloadGrants:
        async def issue(self, **values):
            nonlocal download_failures
            download_attempts.append({
                label
                for label in ("pdf", "word")
                if values.get(f"{label}_path")
            })
            assert "2" in repository.durable.payload["reportEditorContexts"]
            if download_failures:
                download_failures -= 1
                raise RuntimeError("download grant store unavailable")
            empty = {
                f"{label}_{field}": (0 if field == "size" else "")
                for label in ("pdf", "word")
                for field in ("path", "size", "sha256")
            }
            return "download-raw", ReportDownloadGrant(
                grant_hash="d" * 64,
                expires_at=datetime(2026, 10, 15, tzinfo=UTC),
                **{**empty, **values},
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
    if failure and failure != "editor_grant":
        message = {
            "render": "renderer failed",
            "commit": "durable commit failed",
            "download_grant": "download grant store unavailable",
            "download_grant_missing_pdf": "download grant store unavailable",
            "download_grant_missing_word": "download grant store unavailable",
            "download_grant_changed_pdf": "download grant store unavailable",
            "download_grant_persistence_pdf": "download grant store unavailable",
            "download_grant_persistence_word": "download grant store unavailable",
        }[failure]
        with pytest.raises(RuntimeError, match=message):
            await editor.export_revision(context, expected_sha256=expected_sha, settings={"sources": True})
    else:
        result = await editor.export_revision(context, expected_sha256=expected_sha, settings={"sources": True})
        assert result["revision"] == 2
        assert result["pdf"]["downloadUrl"].endswith("/reports/v1/download/download-raw")
        if failure == "editor_grant":
            assert "editor" not in result
            assert result["validation"]["ok"] is False
            assert result["validation"]["issues"][-1]["code"] == "report_editor_grant_unavailable"
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
    if failure and failure.startswith("download_grant"):
        # 已提交 revision 的下载签发失败后，相同请求重试该 revision，不生成 revision-3。
        await workspace.awrite_text(thread_id, draft_path, edited_markdown, overwrite=True)
        if failure == "download_grant_changed_pdf":
            await workspace.awrite_bytes(
                thread_id, "reports/revision-2/report.pdf", b"changed-pdf", overwrite=True
            )
        elif retry_unavailable_label is not None:
            suffix = "pdf" if retry_unavailable_label == "pdf" else "docx"
            await workspace.adelete_file(thread_id, f"reports/revision-2/report.{suffix}")
        retried = await editor.export_revision(
            context, expected_sha256=expected_sha, settings={"sources": True}
        )
        expected_formats = {"pdf", "word"} - {
            label
            for label in (retry_unavailable_label, retry_persistence_label)
            if label is not None
        }
        assert retried["revision"] == 2
        assert {label for label in ("pdf", "word") if label in retried} == expected_formats
        assert download_attempts[-1] == expected_formats
        if retry_unavailable_label is not None:
            assert retried["validation"]["ok"] is False
            assert any(
                issue["code"] == f"report_{retry_unavailable_label}_artifact_unavailable"
                for issue in retried["validation"]["issues"]
            )
        if retry_persistence_label is not None:
            assert retried["validation"]["ok"] is False
            assert any(
                issue["code"] == f"report_{retry_persistence_label}_persistence_failed"
                for issue in retried["validation"]["issues"]
            )
        if failure == "download_grant":
            assert all(
                issue["code"] != "report_artifact_persistence_failed"
                for issue in retried["validation"]["issues"]
            )
        assert not await workspace.apath_exists(thread_id, "reports/revision-3")
        assert len(snapshot_paths) == 1
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
        label = "pdf" if suffix == "pdf" else "word"
        if label == retry_unavailable_label:
            continue
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
@pytest.mark.parametrize("fault", ["missing_source", "snapshot", "appendix", "appendix_disabled", "overview"])
async def test_export_revision_drops_lineage_but_still_issues_links_when_source_file_missing(
    tmp_path: Path, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """故障注入：来源缺失、快照失败、附录失败、关闭附录及经营总览投影失败。

    AGENTS：追溯数据不可用只拒绝使用该数据，PDF/Word 照常签发并返回原因。
    附录构建失败只降级展示，仍登记有效追溯；关闭附录不应调用构建器。
    经营总览投影失败只显示缺项说明，不连带丢弃已核验的追溯。
    """
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
    if fault == "missing_source":
        await workspace.adelete_file(thread_id, csv_path)
    elif fault == "snapshot":
        from smart_reporting.report_editor import service as service_module

        async def broken_snapshot(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(service_module, "snapshot_revision_lineage", broken_snapshot)
    elif fault == "overview":
        from smart_reporting.report_editor import service as service_module

        validate = editor.trace.validate

        async def validate_with_overview(*args, **kwargs):
            result = await validate(*args, **kwargs)
            result.setdefault("quality", {})["managementOverview"] = {"status": "evaluated"}
            return result

        def broken_projection(*_args, **_kwargs):
            raise ValueError("overview does not belong to the rendered Markdown")

        monkeypatch.setattr(editor.trace, "validate", validate_with_overview)
        monkeypatch.setattr(service_module.ManagementOverview, "model_validate", staticmethod(lambda value: value))
        monkeypatch.setattr(service_module, "management_overview_projection", broken_projection)
    else:
        from smart_reporting.report_editor import service as service_module

        def oversized_appendix(*_args, **_kwargs):
            assert fault != "appendix_disabled", "关闭附录时不应构建附录"
            raise ValueError("appendix too large")

        monkeypatch.setattr(service_module, "_build_export_trace_sources", oversized_appendix)

    if fault in {"appendix", "appendix_disabled", "overview"}:
        # 本用例的冻结正文就是当前文本，避免夹具原文身份变更干扰附录故障。
        index = index.model_copy(update={"files": tuple(
            item.model_copy(update={"size": len(edited_markdown.encode()), "sha256": _sha(edited_markdown.encode())})
            if item.resource_id == index.markdown_file_resource_id else item for item in index.files
        )})
        from smart_reporting.reporting.trace.contracts_v1 import canonical_json_bytes
        await workspace.awrite_bytes(thread_id, "reports/revision-1/trace-index-v1.json",
                                     canonical_json_bytes(index.model_dump(mode="json", by_alias=True)), overwrite=True)
    await workspace.adelete_file(thread_id, original.artifact_manifest.path)
    manifest_identity = await register_trace_manifest(workspace, thread_id, index)
    for suffix, content in (("pdf", b"old-pdf"), ("docx", b"old-word")):
        await workspace.awrite_bytes(thread_id, f"reports/revision-1/report.{suffix}", content)
    job = {
        **original.job,
        "render": {
            "pdf": _identity("reports/revision-1/report.pdf", b"old-pdf"),
            "word": _identity("reports/revision-1/report.docx", b"old-word"),
            "markdown": _identity(original.markdown_path, edited_markdown.encode()),
            "images": [],
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
    repository = _StateRepository(durable, failure=None)
    editor.state_repository = repository
    rendered_manifests: list[object] = []
    rendered_overviews: list[object] = []

    class ReportTools:
        async def _render_report_pair(
            self, actual_job_id, markdown_path, output_path, *, artifact_manifest, management_overview=None, run_context
        ):
            rendered_manifests.append(artifact_manifest)
            rendered_overviews.append(management_overview)
            render_job = run_context.session_state[REPORT_JOBS_STATE_KEY][actual_job_id]
            assert ("_traceSourcePresentations" in render_job) is (fault in {"snapshot", "overview"})
            snapshot, _ = await workspace.afile_bytes(thread_id, markdown_path)
            await workspace.awrite_bytes(thread_id, output_path, b"new-pdf")
            await workspace.awrite_bytes(thread_id, "reports/revision-2/report.docx", b"new-word")
            render_job["render"] = {
                "pdf": _identity(output_path, b"new-pdf"),
                "word": _identity("reports/revision-2/report.docx", b"new-word"),
                "markdown": _identity(markdown_path, snapshot),
                "images": [],
            }
            return {"status": "validated", "validation": {"ok": True}}

    class Persistence:
        async def persist(self, **_values):
            return None

    class DownloadGrants:
        async def issue(self, **values):
            return "download-raw", ReportDownloadGrant(
                grant_hash="d" * 64, expires_at=datetime(2026, 10, 15, tzinfo=UTC), **values
            )

    class EditorGrants:
        async def issue(self, issued_context):
            return "editor-raw", datetime(2026, 10, 15, tzinfo=UTC)

    editor.report_tools = ReportTools()
    editor.artifact_persistence = Persistence()
    editor.download_grants = DownloadGrants()
    editor.editor_grants = EditorGrants()
    editor.public_base_url = "https://reports.example.com"

    result = await editor.export_revision(context, expected_sha256=_sha(edited_markdown.encode()),
                                          settings={"sources": fault != "appendix_disabled"})

    if fault == "missing_source":
        # 渲染前即发现来源文件缺失：放弃追溯后渲染，成品不带指向无索引 revision 的附录。
        assert rendered_manifests == [None]
    else:
        assert rendered_manifests[0] is not None
    assert result["revision"] == 2
    assert result["pdf"]["downloadUrl"] and result["word"]["downloadUrl"]
    if fault in {"appendix", "appendix_disabled", "overview"}:
        assert result["validation"]["ok"] is (fault == "appendix_disabled")
        if fault == "appendix":
            assert result["validation"]["issues"][0]["code"] == "report_editor_source_appendix_unavailable"
        if fault == "overview":
            assert rendered_overviews[0]["status"] == "unavailable"
            assert [issue["code"] for issue in result["validation"]["issues"]] == [
                "report_editor_management_overview_unavailable"
            ]
        committed = ReportEditorContext.model_validate(
            repository.durable.payload["reportEditorContexts"]["2"]
        )
        assert committed.artifact_manifest is not None
        assert await editor.trace.load_index(committed) is not None
        return
    assert result["validation"]["ok"] is False
    assert [issue["code"] for issue in result["validation"]["issues"]] == [
        "report_editor_lineage_unavailable"
    ]
    message = result["validation"]["issues"][0]["message"]
    assert "数据来源追溯不可用" in message
    assert (csv_path in message) is (fault == "missing_source")
    assert ("成品已生成" in message) is (fault == "snapshot")
    committed = ReportEditorContext.model_validate(
        repository.durable.payload["reportEditorContexts"]["2"]
    )
    assert committed.artifact_manifest is None
    assert await workspace.aread_text(thread_id, committed.markdown_path) == edited_markdown


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", [None, "registry_corrupt", "image_identity_changed", "pages", "page_changed", "page_missing", "page_partial"])
async def test_export_revision_registers_ai_chart_edit_and_still_issues_links(
    tmp_path: Path, fault: str | None
) -> None:
    """编辑器 AI 改图导出登记（设计稿 §7）与非阻断故障注入。

    AGENTS：改图登记读取失败、哈希变化只降级对应追溯数据并返回原因，
    已核验身份的 PDF/Word 照常签发，不得阻断下载链接。
    成功路径：改图进入新 manifest（未登记图片通道）与 ChartTraceV1
    （含作图脚本与改图说明），作图数据与数据集随原图追溯。
    """
    import asyncio
    from types import SimpleNamespace

    from smart_reporting.report_editor.chart_ai import (
        ChartAIEditRequest,
        ChartAIEditService,
    )
    from smart_reporting.report_editor.chart_edits import (
        ChartEditPage,
        chart_edit_page_src,
        chart_edits_registry_path,
        load_chart_edit_records,
    )
    from smart_reporting.reporting.tests.test_report_editor_chart_ai import (
        FakeRunner,
        _make_editor_with_chart,
        _planner,
    )

    fixture = await _make_editor_with_chart(tmp_path)
    editor = fixture.editor
    workspace = fixture.workspace
    thread_id = fixture.thread_id
    context = fixture.context
    session = SimpleNamespace(capabilities=None)
    service = ChartAIEditService(
        editor=editor,
        workspace_registry=editor.workspace_registry,
        planner=_planner(),
        runner=FakeRunner(fixture.chart_bytes),
    )
    started = await service.start_edit(
        context,
        session,
        "chart_001",
        ChartAIEditRequest(
            instruction="改成横向条形图并按金额降序",
            baseImagePath=fixture.chart_path,
            baseTitle="收入",
            baseAltText="收入对比",
            expectedSha256=fixture.chart.sha256,
        ),
    )
    for _ in range(400):
        status = service.edit_status(context, "chart_001", started["editId"])
        if status["status"] in {"succeeded", "failed"}:
            break
        await asyncio.sleep(0.02)
    assert status["status"] == "succeeded", status
    await service.aclose()
    records = await load_chart_edit_records(workspace, thread_id, context.markdown_path)
    assert [record.edit_id for record in records] == [started["editId"]]
    record = records[0]
    new_src = f"chart-edits/{record.edit_id}/chart.png"
    successful = fault in {None, "pages"}
    paginated = bool(fault and fault.startswith("page"))
    if paginated:
        second_image = record.image.model_copy(update={"path": record.image.path.replace("chart.png", "chart--page-2.png")})
        await workspace.awrite_bytes(thread_id, second_image.path, fixture.chart_bytes)
        record = record.model_copy(update={"pages": (
            ChartEditPage(pageNumber=1, image=record.image, chart=record.chart),
            ChartEditPage(pageNumber=2, image=second_image,
                chart=record.chart.model_copy(update={"title": "收入（第2/2页）", "alt_text": "第二页收入"})),
        )})
        registry = {"version": 1, "records": [record.model_dump(mode="json", by_alias=True)]}
        import json

        await workspace.awrite_bytes(thread_id, chart_edits_registry_path(context.markdown_path), json.dumps(registry).encode(), overwrite=True)

    header = (
        '# Revenue report\n\n<a id="report-section-section_002"></a>\n'
        "## 1 Report\n\n[[section:section_002]]\n[[analysis:analysis_001]]\n\n"
    )
    edited_markdown = (
        header
        + "Revenue 3600 [[claim:claim-1]]"
        + f"\n\n![Revenue]({new_src}) [[citation:citation_001]]\n"
    )
    if paginated and fault != "page_partial":
        edited_markdown += f"\n\n![第二页]({chart_edit_page_src(context.markdown_path, record.edit_id, 2)}) [[citation:citation_001]]\n"
    await workspace.awrite_text(thread_id, "reports/revision-1/draft/report.md", edited_markdown)
    if fault == "registry_corrupt":
        await workspace.awrite_bytes(
            thread_id,
            chart_edits_registry_path(context.markdown_path),
            b'{"version":1,"records":[broken',
            overwrite=True,
        )
    elif fault == "image_identity_changed":
        await workspace.awrite_bytes(
            thread_id, record.image.path, fixture.chart_bytes + b"tampered", overwrite=True
        )
    elif fault == "page_changed":
        await workspace.awrite_bytes(thread_id, record.pages[1].image.path, b"tampered", overwrite=True)
    elif fault == "page_missing":
        await workspace.adelete_file(thread_id, record.pages[1].image.path)
    for suffix, content in (("pdf", b"old-pdf"), ("docx", b"old-word")):
        await workspace.awrite_bytes(thread_id, f"reports/revision-1/report.{suffix}", content)
    # 导出契约要求 job.render 登记当前 PDF/Word 产物（_next_pdf_path 依据）。
    context = context.model_copy(update={"job": {
        **context.job,
        "render": {
            **context.job["render"],
            "pdf": _identity("reports/revision-1/report.pdf", b"old-pdf"),
            "word": _identity("reports/revision-1/report.docx", b"old-word"),
        },
    }})
    editor.state_repository.durable.payload["reportEditorContexts"]["1"] = (
        context.model_dump(mode="json", by_alias=True)
    )

    rendered_manifests: list[object] = []

    class ReportTools:
        async def _render_report_pair(
            self, actual_job_id, markdown_path, output_path, *, artifact_manifest,
            management_overview=None, run_context,
        ):
            rendered_manifests.append(artifact_manifest)
            snapshot, _ = await workspace.afile_bytes(thread_id, markdown_path)
            await workspace.awrite_bytes(thread_id, output_path, b"new-pdf")
            await workspace.awrite_bytes(thread_id, "reports/revision-2/report.docx", b"new-word")
            images = []
            if successful:
                images = [image.as_identity() for image in (
                    tuple(page.image for page in record.pages) if record.pages else (record.image,)
                )]
            run_context.session_state[REPORT_JOBS_STATE_KEY][actual_job_id]["render"] = {
                "pdf": _identity(output_path, b"new-pdf"),
                "word": _identity("reports/revision-2/report.docx", b"new-word"),
                "markdown": _identity(markdown_path, snapshot),
                "images": images,
            }
            return {"status": "validated", "validation": {"ok": True}}

    class Persistence:
        async def persist_available(self, **values):
            return values["artifacts"]

    class DownloadGrants:
        async def issue(self, **values):
            return "download-raw", ReportDownloadGrant(
                grant_hash="d" * 64, expires_at=datetime(2026, 10, 15, tzinfo=UTC), **values
            )

    class EditorGrants:
        async def issue(self, issued_context):
            return "editor-raw", datetime(2026, 10, 15, tzinfo=UTC)

    editor.report_tools = ReportTools()
    editor.artifact_persistence = Persistence()
    editor.download_grants = DownloadGrants()
    editor.editor_grants = EditorGrants()
    editor.public_base_url = "https://reports.example.com"

    result = await editor.export_revision(
        context, expected_sha256=_sha(edited_markdown.encode())
    )

    assert result["revision"] == 2
    assert result["pdf"]["downloadUrl"] and result["word"]["downloadUrl"]
    committed = ReportEditorContext.model_validate(
        editor.state_repository.durable.payload["reportEditorContexts"]["2"]
    )
    assert await workspace.aread_text(thread_id, committed.markdown_path) == edited_markdown
    if not successful:
        # 非阻断：改图登记损坏/身份变化只降级追溯并返回原因，产物照常签发。
        assert result["validation"]["ok"] is False
        codes = [issue["code"] for issue in result["validation"]["issues"]]
        assert "report_editor_chart_edit_lineage_unavailable" in codes
        assert "report_editor_lineage_unavailable" in codes
        assert committed.artifact_manifest is None
        assert rendered_manifests == [None]
        return
    assert result["validation"]["ok"] is True
    assert rendered_manifests[0] is not None
    rendered_chart = next(chart for chart in rendered_manifests[0]["charts"] if chart["chartId"] == "chart_001")
    assert rendered_chart["path"] == record.image.path
    assert rendered_chart["chartId"] == "chart_001"
    assert rendered_chart["datasetIds"] == ["dataset-url-abc0001"]
    # 图表产物只有 Matplotlib 静态图，清单不再携带 renderer/interactiveSpec。
    assert "renderer" not in rendered_chart and "interactiveSpec" not in rendered_chart
    raw, _ = await fixture.grants.issue(committed)
    _, session = await fixture.grants.exchange(raw)
    next_manifest = await editor.trace.load_manifest(committed)
    assert next_manifest is not None
    primary_chart = next(chart for chart in next_manifest.charts if chart.chart_id == "chart_001")
    assert primary_chart.path == f"reports/revision-2/{new_src}"
    if paginated:
        assert len(next_manifest.charts) == 2
        assert len({chart.chart_id for chart in next_manifest.charts}) == 2
        assert any(chart.path.endswith("chart--page-2.png") for chart in next_manifest.charts)
    next_index = await editor.trace.load_index(committed)
    assert next_index is not None
    new_trace = next_index.chart_traces[0]
    assert new_trace.chart_id == "chart_001"
    assert new_trace.image_file_resource_id == derive_resource_id(
        f"reports/revision-2/{new_src}"
    )
    assert new_trace.script_file_resource_id == derive_resource_id(
        f"reports/revision-2/chart-edits/{record.edit_id}/chart_edit.py"
    )
    assert new_trace.transform_notes[0].startswith("编辑器 AI 改图：")
    assert new_trace.plot_data_file_resource_ids == (
        derive_resource_id("reports/revision-2/chart-001.chart-input.json"),
    )
    files = {item.resource_id: item for item in next_index.files}
    assert files[new_trace.script_file_resource_id].media_type == "text/x-python"
    # 新图与脚本已随迁至 revision-2；来源面板可按 chartId 解析作图数据。
    assert await workspace.apath_exists(thread_id, f"reports/revision-2/{new_src}")
    assert await workspace.apath_exists(
        thread_id, f"reports/revision-2/chart-edits/{record.edit_id}/chart_edit.py"
    )
    chart_source = await editor.trace_chart_source(committed, session, "chart_001")
    assert chart_source["plotData"][0]["columns"] == ["period", "revenue"]
    assert chart_source["plotData"][0]["rows"] == [["2025-09", 3600]]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", [None, "registry_corrupt", "body_changed"])
async def test_export_revision_registers_table_edit_and_still_issues_links(
    tmp_path: Path, fault: str | None
) -> None:
    """AI 改表导出登记与非阻断故障注入（AGENTS 契约：登记损坏/表体变化照常签发）。

    成功路径：新表块进入新 manifest（按正文重算哈希）与 TableTraceV1
    （含 originMarkdown），原表 trace 不再保留。故障路径：追溯降级为
    issue，已核验身份的 PDF/Word 照常签发下载链接。
    """
    from smart_reporting.report_editor.chart_edits import (
        TableEditRecord,
        append_table_edit_record,
        chart_edits_registry_path,
    )
    from smart_reporting.reporting.trace.table_builder import build_table_trace

    editor, grants, original = await _make_editor_with_subject(tmp_path)
    thread_id = original.scope["threadId"]
    workspace = editor.workspace
    fact_path = "报表/智能分析/report-1/facts/revision-1/analysis_001.json"
    fact_ref = derive_resource_id(fact_path)

    trace, new_markdown = build_table_trace(
        # 直接复用冻结 bundle 装配新表：期间行 + 合计行，列绑定指标事实。
        __import__("smart_reporting.reporting.hospital_operation.deterministic_analysis", fromlist=["DeterministicAnalysisBundle"]).DeterministicAnalysisBundle.model_validate_json(
            (await workspace.afile_bytes(thread_id, fact_path))[0]
        ),
        {
            "tableId": "tbl-1-e0000001",
            "metricCodes": ["income_total"],
            "columnLabels": {"income_total": "收入（万元）"},
            "factIds": {"income_total": "fact-" + "a" * 16},
            "rows": [
                {"key": "period:2025-09", "label": "2025年9月", "period": "2025-09"},
                {"key": "total", "label": "合计"},
            ],
            "caption": "改表后的分期间收入",
        },
        fact_file_resource_id=fact_ref,
    )
    from smart_reporting.reporting.delivery.artifacts_v1 import _TABLE_BLOCK

    body_match = _TABLE_BLOCK.search(new_markdown)
    assert body_match is not None
    body_sha256 = hashlib.sha256(body_match.group(2).encode("utf-8")).hexdigest()
    record = TableEditRecord(
        editId="tedit-" + "0" * 16,
        tableId="tbl-1",
        analysisId="analysis_001",
        newTableId="tbl-1-e0000001",
        instruction="改成期间加合计的明细表",
        bodySha256=body_sha256,
        markdown=new_markdown,
        tableTrace=trace.model_copy(
            update={"origin_markdown": new_markdown}
        ).model_dump(mode="json", by_alias=True),
        createdAt=datetime.now(UTC).isoformat(),
        userId="user-1",
    )
    await append_table_edit_record(workspace, thread_id, original.markdown_path, record)

    original_markdown = await workspace.aread_text(thread_id, original.markdown_path)
    old_block = _TABLE_BLOCK.search(original_markdown)
    assert old_block is not None
    draft_markdown = original_markdown[: old_block.start()] + new_markdown + original_markdown[old_block.end():]
    if fault == "body_changed":
        # 接受后正文表体被手工改值：登记哈希不再匹配，追溯按契约降级。
        draft_markdown = draft_markdown.replace("3,600", "9,999", 1)
        draft_markdown = draft_markdown.replace("3600", "9999", 1)
    await workspace.awrite_text(thread_id, "reports/revision-1/draft/report.md", draft_markdown)
    if fault == "registry_corrupt":
        await workspace.awrite_bytes(
            thread_id,
            chart_edits_registry_path(original.markdown_path),
            b'{"version":1,"records":[broken',
            overwrite=True,
        )
    for suffix, content in (("pdf", b"old-pdf"), ("docx", b"old-word")):
        await workspace.awrite_bytes(thread_id, f"reports/revision-1/report.{suffix}", content)
    markdown_identity = _identity(original.markdown_path, original_markdown.encode())
    context = original.model_copy(update={"job": {
        **original.job,
        "render": {
            "pdf": _identity("reports/revision-1/report.pdf", b"old-pdf"),
            "word": _identity("reports/revision-1/report.docx", b"old-word"),
            "markdown": markdown_identity,
        },
    }})
    durable = ReportingRunState.initial(
        report_run_id=context.workflow_run_id,
        external_run_id="external-1",
        thread_id="caller-thread",
        owner_user_id="user-1",
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}},
    )
    editor.state_repository = _StateRepository(durable, failure=None)

    class ReportTools:
        async def _render_report_pair(
            self, actual_job_id, markdown_path, output_path, *, artifact_manifest,
            management_overview=None, run_context,
        ):
            snapshot, _ = await workspace.afile_bytes(thread_id, markdown_path)
            await workspace.awrite_bytes(thread_id, output_path, b"new-pdf")
            await workspace.awrite_bytes(thread_id, "reports/revision-2/report.docx", b"new-word")
            run_context.session_state[REPORT_JOBS_STATE_KEY][actual_job_id]["render"] = {
                "pdf": _identity(output_path, b"new-pdf"),
                "word": _identity("reports/revision-2/report.docx", b"new-word"),
                "markdown": _identity(markdown_path, snapshot),
                "images": [],
            }
            return {"status": "validated", "validation": {"ok": True}}

    class Persistence:
        async def persist_available(self, **values):
            return values["artifacts"]

    class DownloadGrants:
        async def issue(self, **values):
            return "download-raw", ReportDownloadGrant(
                grant_hash="d" * 64, expires_at=datetime(2026, 10, 15, tzinfo=UTC), **values
            )

    class EditorGrants:
        async def issue(self, issued_context):
            return "editor-raw", datetime(2026, 10, 15, tzinfo=UTC)

    editor.report_tools = ReportTools()
    editor.artifact_persistence = Persistence()
    editor.download_grants = DownloadGrants()
    editor.editor_grants = EditorGrants()
    editor.public_base_url = "https://reports.example.com"

    result = await editor.export_revision(
        context, expected_sha256=_sha(draft_markdown.encode())
    )

    assert result["revision"] == 2
    assert result["pdf"]["downloadUrl"] and result["word"]["downloadUrl"]
    committed = ReportEditorContext.model_validate(
        editor.state_repository.durable.payload["reportEditorContexts"]["2"]
    )
    if fault is not None:
        # 非阻断：改表登记损坏/表体变化只丢弃改表追溯并返回原因。表格在
        # manifest 中按正文内容寻址，不需要登记通道，产物与索引照常签发。
        assert result["validation"]["ok"] is False
        codes = [issue["code"] for issue in result["validation"]["issues"]]
        assert "report_editor_table_edit_lineage_unavailable" in codes
        degraded_index = await editor.trace.load_index(committed)
        assert degraded_index is not None
        assert "tbl-1-e0000001" not in {item.table_id for item in degraded_index.tables}
        return
    assert result["validation"]["ok"] is True
    next_index = await editor.trace.load_index(committed)
    assert next_index is not None
    table_ids = {item.table_id for item in next_index.tables}
    assert "tbl-1-e0000001" in table_ids
    # 原表 trace 保留（subject 绑定仍指向它，正文块缺失按软性 unbound 评估）。
    assert "tbl-1" in table_ids
    new_table = next(item for item in next_index.tables if item.table_id == "tbl-1-e0000001")
    assert new_table.origin_markdown is not None
    assert new_table.origin_markdown.startswith("改表后的分期间收入")
    next_manifest = await editor.trace.load_manifest(committed)
    assert next_manifest is not None
    assert {item.table_id for item in next_manifest.tables} == {"tbl-1-e0000001"}


@pytest.fixture
async def native_chart_cleanup():
    """断言失败或超时也先取消任务，再回收真实LSP和CodeMode。"""
    resources = []
    try:
        yield resources
    finally:
        for service, lsp, runtime in reversed(resources):
            try:
                await service.aclose()
            finally:
                try:
                    await lsp.aclose()
                finally:
                    await runtime.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("scenario,fault", [
    (scenario, fault)
    for scenario in ("single", "reedit", "paginated_reedit", "revision_reedit")
    for fault in (None, "l2_plot_changed")
] + [pytest.param("native_revision_reedit", fault, marks=pytest.mark.integration)
     for fault in (None, "l2_plot_changed")]
  + [("revision_grow", None), ("revision_single", None),
     ("legacy_template", None), ("legacy_template", "template_binding_failed")])
async def test_export_revision_registers_l2_chart_edit_plot_data(
    tmp_path: Path, fault: str | None, scenario: str, native_chart_cleanup,
) -> None:
    """L2 换绑导出：新物化作图数据进入新 revision 追溯，ChartTraceV1 指向新文件。

    故障注入（AGENTS 契约）：换绑作图数据身份变化时追溯降级为 issue，
    已核验身份的 PDF/Word 照常签发下载链接。
    """
    import asyncio
    from types import SimpleNamespace

    from smart_reporting.report_editor.chart_ai import (
        ChartAIEditRequest,
        ChartAIEditService,
        ChartEditPlan,
    )
    from smart_reporting.report_editor.chart_edits import load_chart_edit_records
    from smart_reporting.reporting.tests.test_report_editor_chart_ai import (
        FakeRunner,
        _make_editor_with_chart,
        _planner,
    )
    from smart_reporting.reporting.tests.test_report_editor_standard_charts import StandardRunner
    from smart_reporting.reporting.workflow.runtime.phase_models import ChartDataBinding

    native = scenario == "native_revision_reedit"
    if native and fault is not None:
        pytest.skip("原故障契约已覆盖；此新增场景只核验真实CodeMode续改")
    revision_scenarios = {"revision_reedit", "revision_grow", "revision_single", "native_revision_reedit"}
    paginated = scenario in {"paginated_reedit", *revision_scenarios}
    initial_page_size = 2 if scenario == "revision_grow" else 1
    initial_page_count = (3 + initial_page_size - 1) // initial_page_size
    target_page_size = {"revision_grow": 1, "revision_single": 3}.get(scenario, 2)
    target_page_count = (3 + target_page_size - 1) // target_page_size
    legacy_template = scenario == "legacy_template"
    fixture = await _make_editor_with_chart(tmp_path, template_ready=paginated or legacy_template,
        legacy_unbound=legacy_template)
    editor = fixture.editor
    workspace = fixture.workspace
    thread_id = fixture.thread_id
    context = fixture.context
    session = SimpleNamespace(capabilities=None)
    binding = ChartDataBinding(
        analysisId="analysis_001",
        factPath="报表/智能分析/report-1/facts/revision-1/analysis_001.json",
        dataPath="metrics[0].periodValues",
        fields=("period", "value"),
        role="main",
    )
    initial_planner = _planner(level=("L2",), data_bindings=(binding,))
    plan_calls = 0

    async def planner(request):
        nonlocal plan_calls
        plan_calls += 1
        if plan_calls > 1:
            standard = {"standardStyle": {"palette": "viridis"}} if paginated else None
            if scenario in revision_scenarios and plan_calls == 3:
                standard["standardPagination"] = {"pageSize": target_page_size}
            return ChartEditPlan(
                level=["L1"], drawInstruction="保持全部数据，只调整颜色",
                standard=standard,
            )
        plan = await initial_planner(request)
        if paginated:
            plan = plan.model_copy(update={
                "visual_form": "barh",
                "standard": ChartEditPlan.model_validate({
                    "level": ["L2"], "drawInstruction": "完整分页",
                    "standard": {"standardValueFields": ["value"], "standardPagination": {"pageSize": initial_page_size},
                                 **({"standardForm": "barh"} if native else {})},
                }).standard,
            })
        return plan

    service = ChartAIEditService(
        editor=editor,
        workspace_registry=editor.workspace_registry,
        planner=planner,
        runner=StandardRunner(fixture.chart_bytes) if paginated else FakeRunner(fixture.chart_bytes),
    )
    if legacy_template:
        from smart_reporting.report_editor.chart_ai import ChartTemplateApplyRequest

        started = await service.start_template(context, session, "chart_001",
            ChartTemplateApplyRequest(templateId="monthly-trend", instruction="保留模板并标注",
                expectedSha256=fixture.chart.sha256))
    else:
        started = await service.start_edit(
            context, session, "chart_001",
            ChartAIEditRequest(
                instruction="换成按期间的月度趋势",
                baseImagePath=fixture.chart_path,
                baseTitle="收入",
                baseAltText="收入对比",
                expectedSha256=fixture.chart.sha256,
            ),
        )
    for _ in range(400):
        status = service.edit_status(context, "chart_001", started["editId"])
        if status["status"] in {"succeeded", "failed"}:
            break
        await asyncio.sleep(0.02)
    assert status["status"] == "succeeded", status
    records = await load_chart_edit_records(workspace, thread_id, context.markdown_path)
    record = records[0]
    assert record.level == (("L1",) if legacy_template else ("L2",))
    if scenario != "single" and not legacy_template:
        previous_record = record
        base = record.pages[1].image if paginated else record.image
        if native:
            from agno.tools.code import CodeMode

            from smart_reporting.report_editor.chart_ai import ChartStandardEditRequest
            from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
            from smart_reporting.reporting.code_mode import ReportingCodeModeRuntime
            from smart_reporting.reporting.workflow.runtime.code_generation import (
                ReportingCodeGenerationRunner,
            )

            identity = editor.workspace_registry.get(thread_id)
            runtime = ReportingCodeModeRuntime(CodeMode(
                snapshot=False, allow_shell=True, cwd=str(identity.root), timeout=45, max_kernels=1,
            ))
            lsp = ReportingLspProcessManager()

            def forbid_model(*_args, **_kwargs):
                raise AssertionError("直接模板续改不能调用模型")

            native_runner = ReportingCodeGenerationRunner(forbid_model, runtime, lsp, vision_reviewer=None)
            service.runner = native_runner
            native_chart_cleanup.append((service, lsp, runtime))
            started = await service.start_standard_edit(context, session, "chart_001", ChartStandardEditRequest(
                standard={"standardStyle": {"palette": "viridis"}}, previousEditId=record.edit_id,
                baseImagePath=base.path, expectedSha256=base.sha256,
            ))
        else:
            started = await service.start_edit(context, session, "chart_001", ChartAIEditRequest(
                instruction="只改颜色，保留全部分页和数据", previousEditId=record.edit_id,
                baseImagePath=base.path, expectedSha256=base.sha256,
            ))
        from smart_reporting.reporting.tests.test_report_editor_chart_ai import _await_edit
        status = await _await_edit(service, context, "chart_001", started["editId"])
        assert status["status"] == "succeeded", status
        if native:
            assert status["planningRoute"] == "direct"
            assert status["visualInspection"]["reviewed"] is False
            assert len(status["deterministicImageChecks"]) == 3
            assert native_runner.registry.active_count == 0 and not runtime._logged_connections
            await lsp.aclose()
            await runtime.aclose()
        records = await load_chart_edit_records(workspace, thread_id, context.markdown_path)
        record = records[-1]
        assert record.level == ("L1",) and record.data_origin == "rebound"
        assert record.chart.title == previous_record.chart.title
        assert record.chart.alt_text == previous_record.chart.alt_text
        assert record.plot_data_files[0].sha256 == previous_record.plot_data_files[0].sha256
        assert record.plot_data_files[0].path != previous_record.plot_data_files[0].path
        if fault is None:
            # 新一轮的独立快照不依赖旧改图目录继续存在。
            await workspace.adelete_file(thread_id, previous_record.plot_data_files[0].path)
        if paginated:
            assert len(record.pages) == initial_page_count
    await service.aclose()
    new_plot = record.plot_data_files[0]
    assert new_plot.path != fixture.plot_path
    from smart_reporting.report_editor.chart_edits import chart_edit_page_src, chart_edit_pages
    pages = chart_edit_pages(record)

    header = (
        '# Revenue report\n\n<a id="report-section-section_002"></a>\n'
        "## 1 Report\n\n[[section:section_002]]\n[[analysis:analysis_001]]\n\n"
    )
    edited_markdown = (
        header
        + "Revenue 3600 [[claim:claim-1]]"
        + "".join(f"\n\n![Revenue]({chart_edit_page_src(context.markdown_path, record.edit_id, page.page_number)}) [[citation:citation_001]]\n" for page in pages)
    )
    await workspace.awrite_text(thread_id, "reports/revision-1/draft/report.md", edited_markdown)
    if fault == "l2_plot_changed":
        # 换绑作图数据在登记后被篡改：导出按契约降级追溯，不阻断签发。
        content, _ = await workspace.afile_bytes(thread_id, new_plot.path)
        await workspace.awrite_bytes(thread_id, new_plot.path, content + b"tampered", overwrite=True)
    for suffix, content in (("pdf", b"old-pdf"), ("docx", b"old-word")):
        await workspace.awrite_bytes(thread_id, f"reports/revision-1/report.{suffix}", content)
    context = context.model_copy(update={"job": {
        **context.job,
        "render": {
            **context.job["render"],
            "pdf": _identity("reports/revision-1/report.pdf", b"old-pdf"),
            "word": _identity("reports/revision-1/report.docx", b"old-word"),
        },
    }})
    editor.state_repository.durable.payload["reportEditorContexts"]["1"] = (
        context.model_dump(mode="json", by_alias=True)
    )

    class ReportTools:
        async def _render_report_pair(
            self, actual_job_id, markdown_path, output_path, *, artifact_manifest,
            management_overview=None, run_context,
        ):
            snapshot, _ = await workspace.afile_bytes(thread_id, markdown_path)
            await workspace.awrite_bytes(thread_id, output_path, b"new-pdf")
            word_path = PurePosixPath(output_path).with_suffix(".docx").as_posix()
            await workspace.awrite_bytes(thread_id, word_path, b"new-word")
            run_context.session_state[REPORT_JOBS_STATE_KEY][actual_job_id]["render"] = {
                "pdf": _identity(output_path, b"new-pdf"),
                "word": _identity(word_path, b"new-word"),
                "markdown": _identity(markdown_path, snapshot),
                "images": [{"path": page.image.path, "size": page.image.size, "sha256": page.image.sha256} for page in pages],
            }
            return {"status": "validated", "validation": {"ok": True}}

    class Persistence:
        async def persist_available(self, **values):
            return values["artifacts"]

    class DownloadGrants:
        async def issue(self, **values):
            return "download-raw", ReportDownloadGrant(
                grant_hash="d" * 64, expires_at=datetime(2026, 10, 15, tzinfo=UTC), **values
            )

    class EditorGrants:
        async def issue(self, issued_context):
            return "editor-raw", datetime(2026, 10, 15, tzinfo=UTC)

    editor.report_tools = ReportTools()
    editor.artifact_persistence = Persistence()
    editor.download_grants = DownloadGrants()
    editor.editor_grants = EditorGrants()
    editor.public_base_url = "https://reports.example.com"

    if fault == "template_binding_failed":
        from unittest.mock import AsyncMock

        from smart_reporting.reporting.trace import chart_facts

        fail = AsyncMock(side_effect=ValueError("injected template fact recovery failure"))
        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(chart_facts, "recover_chart_fact_refs", fail)
            result = await editor.export_revision(context, expected_sha256=_sha(edited_markdown.encode()))
        fail.assert_awaited_once()
    elif fault == "continuation_failed":
        import smart_reporting.report_editor.service as service_module

        async def fail_continuation(*args, **kwargs):
            raise OSError("fixture continuation write failed")

        with pytest.MonkeyPatch.context() as patcher:
            patcher.setattr(service_module, "migrate_chart_edit_records", fail_continuation)
            result = await editor.export_revision(context, expected_sha256=_sha(edited_markdown.encode()))
    else:
        result = await editor.export_revision(context, expected_sha256=_sha(edited_markdown.encode()))
    assert result["revision"] == 2
    assert result["pdf"]["downloadUrl"] and result["word"]["downloadUrl"]
    committed = ReportEditorContext.model_validate(
        editor.state_repository.durable.payload["reportEditorContexts"]["2"]
    )
    if fault == "continuation_failed":
        assert result["validation"]["ok"] is False
        assert "report_editor_chart_continuation_unavailable" in {
            issue["code"] for issue in result["validation"]["issues"]
        }
        assert committed.artifact_manifest is not None
        assert await editor.trace.load_index(committed) is not None
        return
    if fault in {"l2_plot_changed", "template_binding_failed"}:
        assert result["validation"]["ok"] is False
        codes = [issue["code"] for issue in result["validation"]["issues"]]
        assert "report_editor_chart_edit_lineage_unavailable" in codes
        assert committed.artifact_manifest is None
        return
    assert result["validation"]["ok"] is True
    next_index = await editor.trace.load_index(committed)
    assert next_index is not None
    migrated_plot_path = (
        "reports/revision-2/"
        + PurePosixPath(new_plot.path).relative_to("reports/revision-1").as_posix()
    )
    expected_resource = derive_resource_id(migrated_plot_path)
    assert len(next_index.chart_traces) == len(pages)
    for new_trace in next_index.chart_traces:
        assert new_trace.plot_data_file_resource_ids == (expected_resource,)
        assert any(note.startswith("预制模板：" if legacy_template else "换绑数据：") for note in new_trace.transform_notes)
        if paginated:
            assert any(note.startswith("完整分页：") for note in new_trace.transform_notes)
    # 新作图数据文件已随迁至新 revision，内容与登记身份一致。
    assert await workspace.apath_exists(thread_id, migrated_plot_path)
    migrated, _ = await workspace.afile_bytes(thread_id, migrated_plot_path)
    import json as _json
    payload = _json.loads(migrated)
    if legacy_template:
        assert payload["templateId"] == "monthly-trend"
        assert next_index.chart_traces[0].fact_refs
        assert next_index.chart_traces[0].fact_refs[0].json_pointer == "/metrics/0"
        return
    assert payload["source"]["dataPath"] == "metrics[0].periodValues"
    assert payload["rows"] == ([["2025-07", 1200.0], ["2025-08", 1500.0], ["2025-09", 1800.0]] if paginated else [["2025-09", 3600.0]])
    if scenario not in revision_scenarios:
        return

    migrated_records = await load_chart_edit_records(workspace, thread_id, committed.markdown_path)
    assert len(migrated_records) == 1
    baseline = migrated_records[0]
    assert baseline.edit_id == record.edit_id and baseline.data_origin == "original"
    assert baseline.standard_parameters == record.standard_parameters
    assert len(baseline.pages) == initial_page_count
    baseline_manifest = await editor.trace.load_manifest(committed)
    assert baseline_manifest is not None
    assert await editor._chart_edit_lineage(
        committed, markdown=edited_markdown, markdown_path=committed.markdown_path,
        manifest=baseline_manifest, index=next_index,
    ) == ({}, None)
    service = ChartAIEditService(
        editor=editor, workspace_registry=editor.workspace_registry,
        planner=planner, runner=StandardRunner(fixture.chart_bytes),
    )
    if native:
        runtime = ReportingCodeModeRuntime(CodeMode(
            snapshot=False, allow_shell=True, cwd=str(identity.root), timeout=45, max_kernels=1,
        ))
        lsp = ReportingLspProcessManager()
        service.runner = native_runner = ReportingCodeGenerationRunner(forbid_model, runtime, lsp, vision_reviewer=None)
        native_chart_cleanup.append((service, lsp, runtime))
    recovered = await service.edit_record(committed, baseline.edit_id)
    assert len(recovered["pages"]) == initial_page_count
    assert recovered["pages"][1]["imagePath"] == baseline.pages[1].image.path
    base = baseline.pages[1].image
    if native:
        started = await service.start_standard_edit(committed, session, "chart_001", ChartStandardEditRequest(
            standard={"standardPagination": {"pageSize": target_page_size}}, previousEditId=baseline.edit_id,
            baseImagePath=base.path, expectedSha256=base.sha256,
        ))
    else:
        started = await service.start_edit(committed, session, "chart_001", ChartAIEditRequest(
            instruction=f"保持全部数据，调整配色并改为每页{target_page_size}条", previousEditId=baseline.edit_id,
            baseImagePath=base.path, expectedSha256=base.sha256,
        ))
    status = await _await_edit(service, committed, "chart_001", started["editId"])
    assert status["status"] == "succeeded", status
    if native:
        assert status["planningRoute"] == "direct" and len(status["deterministicImageChecks"]) == 2
        assert native_runner.registry.active_count == 0 and not runtime._logged_connections
        assert plan_calls == 1, "直接模板和跨revision续改均不能进入planner"
        await lsp.aclose()
        await runtime.aclose()
    await service.aclose()
    current_records = await load_chart_edit_records(workspace, thread_id, committed.markdown_path)
    record = current_records[-1]
    assert record.data_origin == "original" and len(chart_edit_pages(record)) == target_page_count
    assert record.standard_parameters["standardPagination"]["pageSize"] == target_page_size
    assert record.plot_data_files == baseline.plot_data_files
    pages = chart_edit_pages(record)
    edited_markdown = header + "Revenue 3600 [[claim:claim-1]]" + "".join(
        f"\n\n![Revenue]({chart_edit_page_src(committed.markdown_path, record.edit_id, page.page_number)}) [[citation:citation_001]]\n"
        for page in pages
    )
    await workspace.awrite_text(thread_id, "reports/revision-2/draft/report.md", edited_markdown)
    next_result = await editor.export_revision(committed, expected_sha256=_sha(edited_markdown.encode()))
    assert next_result["revision"] == 3
    assert next_result["validation"]["ok"] is True, next_result
    assert next_result["pdf"]["downloadUrl"] and next_result["word"]["downloadUrl"]
    third = ReportEditorContext.model_validate(editor.state_repository.durable.payload["reportEditorContexts"]["3"])
    third_index = await editor.trace.load_index(third)
    third_manifest = await editor.trace.load_manifest(third)
    assert third_index is not None and third_manifest is not None
    assert len(third_index.chart_traces) == len(third_manifest.charts) == target_page_count
    assert {trace.chart_id for trace in third_index.chart_traces} == {chart.chart_id for chart in third_manifest.charts}
    assert len(await load_chart_edit_records(workspace, thread_id, third.markdown_path)) == 1


@pytest.mark.integration
@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_multi_input_composition_source_index_survives_two_exports(
    tmp_path: Path, native_chart_cleanup,
) -> None:
    """两输入构成图的sourceIndex=1在revision迁移及direct续改后仍指向冻结分母。"""
    import json
    from types import SimpleNamespace

    from agno.tools.code import CodeMode

    from smart_reporting.report_editor.chart_ai import (
        ChartAIEditService,
        ChartStandardEditRequest,
    )
    from smart_reporting.report_editor.chart_edits import (
        chart_edit_page_src,
        load_chart_edit_records,
    )
    from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
    from smart_reporting.reporting.code_mode import ReportingCodeModeRuntime
    from smart_reporting.reporting.tests.test_report_editor_chart_ai import _make_editor_with_chart
    from smart_reporting.reporting.workflow.runtime.code_generation import (
        ReportingCodeGenerationRunner,
    )

    fixture = await _make_editor_with_chart(tmp_path, template_ready=True)
    editor, context = fixture.editor, fixture.context
    workspace, thread_id = fixture.workspace, fixture.thread_id
    index = await editor.trace.load_index(context)
    assert index is not None
    original_fact_bytes = {
        item.path: (await workspace.afile_bytes(thread_id, item.path))[0]
        for item in index.files
        if item.resource_id in {fact.file_resource_id for fact in index.fact_files}
    }
    documents = [
        {"columns": ["period", "value"], "rows": [["甲", 30], ["乙", 20]],
         "columnMeta": {"value": {"unit": "元", "measureSemantic": {
             "aggregation": "sum", "additiveAcross": ["period"]}}}},
        {"columns": ["total"], "rows": [[100]], "columnMeta": {"total": {"unit": "元"}}},
    ]
    refs, contents = [], []
    for position, document in enumerate(documents):
        document.update(
            schema="chart-input/v1", chartId="chart_001", role="measure",
            source={"analysisId": "analysis_001", "path": "synthetic/facts.json",
                    "dataPath": f"metrics[{position}]"},
            rowCount=len(document["rows"]),
        )
        content = json.dumps(document, ensure_ascii=False).encode()
        path = f"reports/revision-1/native-input-{position}.json"
        await workspace.awrite_bytes(thread_id, path, content)
        contents.append(content)
        refs.append(TraceFileRefV1(
            resourceId=derive_resource_id(path), path=path, mediaType="application/json",
            size=len(content), sha256=hashlib.sha256(content).hexdigest(),
        ))
    trace = index.chart_traces[0].model_copy(update={
        "plot_data_file_resource_ids": tuple(ref.resource_id for ref in refs),
    })
    index = index.model_copy(update={"files": (*index.files, *refs), "chart_traces": (trace,)})
    await workspace.awrite_bytes(thread_id, "reports/revision-1/trace-index-v1.json",
        encode_trace_index(index), overwrite=True)
    manifest_ref = await register_trace_manifest(workspace, thread_id, index, overwrite=True)
    manifest = await editor.trace.load_manifest(context.model_copy(update={"artifact_manifest": manifest_ref}))
    assert manifest is not None
    manifest = manifest.model_copy(update={"charts": (fixture.chart,)})
    manifest_bytes = manifest.model_dump_json(by_alias=True).encode()
    await workspace.awrite_bytes(thread_id, manifest_ref.path, manifest_bytes, overwrite=True)
    manifest_ref = manifest_ref.model_copy(update={"size": len(manifest_bytes), "sha256": _sha(manifest_bytes)})
    context = context.model_copy(update={"artifact_manifest": manifest_ref})
    editor.state_repository.durable.payload["reportEditorContexts"]["1"] = context.model_dump(
        mode="json", by_alias=True
    )

    identity = editor.workspace_registry.get(thread_id)
    runtime = ReportingCodeModeRuntime(CodeMode(
        snapshot=False, allow_shell=True, cwd=str(identity.root), timeout=45, max_kernels=1,
    ))
    lsp = ReportingLspProcessManager()

    def forbid_model(*_args, **_kwargs):
        raise AssertionError("构成图直接续改不得调用模型")

    runner = ReportingCodeGenerationRunner(forbid_model, runtime, lsp, vision_reviewer=None)
    service = ChartAIEditService(editor=editor, workspace_registry=editor.workspace_registry,
        planner=None, runner=runner, timeout_seconds=45)
    native_chart_cleanup.append((service, lsp, runtime))
    session = SimpleNamespace(capabilities=None)
    standard = {
        "standardForm": "pie", "standardValueFields": ["value"],
        "standardLabelField": "period",
        "standardComposition": {"denominator": {"mode": "reference",
            "ref": {"sourceIndex": 1, "field": "total"}}},
    }
    original_chart_bytes = fixture.chart_bytes
    original_markdown = fixture.markdown

    async def edit_and_assert(base_context, base_image_path, base_sha, previous_edit_id=None):
        request = ChartStandardEditRequest(
            standard=standard, previousEditId=previous_edit_id,
            baseImagePath=base_image_path, expectedSha256=base_sha,
        )
        started = await service.start_standard_edit(base_context, session, "chart_001", request)
        from smart_reporting.reporting.tests.test_report_editor_chart_ai import _await_edit
        status = await _await_edit(service, base_context, "chart_001", started["editId"])
        assert status["status"] == "succeeded", status
        assert status["planningRoute"] == "direct" and status["renderingRoute"] == "standard"
        assert status["visualInspection"]["reviewed"] is False
        assert status["deterministicImageChecks"]
        assert runner.registry.active_count == 0 and not runtime._logged_connections
        records = await load_chart_edit_records(workspace, thread_id, base_context.markdown_path)
        record = records[-1]
        assert [ref.sha256 for ref in record.plot_data_files] == [ref.sha256 for ref in refs]
        assert [ref.size for ref in record.plot_data_files] == [ref.size for ref in refs]
        assert [await workspace.afile_bytes(thread_id, ref.path) for ref in record.plot_data_files] == [
            (content, "application/json") for content in contents
        ]
        assert tuple(record.data_bindings) == tuple({
            "analysisId": "analysis_001", "factPath": "synthetic/facts.json",
            "dataPath": f"metrics[{position}]", "fields": document["columns"], "role": "measure",
        } for position, document in enumerate(documents))
        assert record.chart.dataset_ids == fixture.chart.dataset_ids
        denominator = record.standard_parameters["standardComposition"]["denominator"]
        assert denominator["mode"] == "reference"
        assert denominator["ref"]["sourceIndex"] == 1 and denominator["ref"]["field"] == "total"
        scalar_input, _ = await workspace.afile_bytes(thread_id, record.plot_data_files[1].path)
        assert json.loads(scalar_input)["rows"] == [[100]]
        return record

    try:
        first = await edit_and_assert(context, fixture.chart_path, fixture.chart.sha256)
        header = (
            '# Revenue report\n\n<a id="report-section-section_002"></a>\n'
            "## 1 Report\n\n[[section:section_002]]\n[[analysis:analysis_001]]\n\n"
        )
        pages = tuple(first.pages) or (SimpleNamespace(image=first.image, page_number=1),)
        markdown2 = header + "Revenue 3600 [[claim:claim-1]]" + "".join(
            f"\n\n![Revenue]({chart_edit_page_src(context.markdown_path, first.edit_id, page.page_number)}) [[citation:citation_001]]\n"
            for page in pages
        )
        for suffix, content in (("pdf", b"old-pdf"), ("docx", b"old-word")):
            await workspace.awrite_bytes(thread_id, f"reports/revision-1/report.{suffix}", content)
        context = context.model_copy(update={"job": {
            **context.job, "render": {**context.job["render"],
                "pdf": _identity("reports/revision-1/report.pdf", b"old-pdf"),
                "word": _identity("reports/revision-1/report.docx", b"old-word")},
        }})
        editor.state_repository.durable.payload["reportEditorContexts"]["1"] = context.model_dump(
            mode="json", by_alias=True
        )

        current_pages = pages
        class ReportTools:
            async def _render_report_pair(self, actual_job_id, markdown_path, output_path, *,
                    artifact_manifest, management_overview=None, run_context):
                snapshot, _ = await workspace.afile_bytes(thread_id, markdown_path)
                pdf_path = output_path
                word_path = PurePosixPath(output_path).with_suffix(".docx").as_posix()
                await workspace.awrite_bytes(thread_id, pdf_path, b"rendered-pdf")
                await workspace.awrite_bytes(thread_id, word_path, b"rendered-word")
                run_context.session_state[REPORT_JOBS_STATE_KEY][actual_job_id]["render"] = {
                    "pdf": _identity(pdf_path, b"rendered-pdf"),
                    "word": _identity(word_path, b"rendered-word"),
                    "markdown": _identity(markdown_path, snapshot),
                    "images": [{"path": page.image.path, "size": page.image.size,
                                "sha256": page.image.sha256} for page in current_pages],
                }
                return {"status": "validated", "validation": {"ok": True}}

        class Persistence:
            async def persist_available(self, **values):
                return values["artifacts"]

        class DownloadGrants:
            async def issue(self, **values):
                return "download-raw", ReportDownloadGrant(
                    grant_hash="d" * 64, expires_at=datetime(2026, 10, 15, tzinfo=UTC), **values
                )

        class EditorGrants:
            async def issue(self, issued_context):
                return "editor-raw", datetime(2026, 10, 15, tzinfo=UTC)

        editor.report_tools = ReportTools()
        editor.artifact_persistence = Persistence()
        editor.download_grants = DownloadGrants()
        editor.editor_grants = EditorGrants()
        editor.public_base_url = "https://reports.example.com"

        async def export(base_context, markdown, revision):
            target = f"reports/revision-{revision}/draft/report.md"
            await workspace.awrite_text(thread_id, target, markdown)
            result = await editor.export_revision(base_context, expected_sha256=_sha(markdown.encode()))
            assert result["revision"] == revision + 1
            assert result["validation"]["ok"] is True, result
            assert result["pdf"]["downloadUrl"] and result["word"]["downloadUrl"]
            return ReportEditorContext.model_validate(
                editor.state_repository.durable.payload["reportEditorContexts"][str(revision + 1)]
            )

        context2 = await export(context, markdown2, 1)
        assert await workspace.afile_bytes(thread_id, fixture.chart_path) == (original_chart_bytes, "image/png")
        assert await workspace.aread_text(thread_id, fixture.context.markdown_path) == original_markdown
        index2 = await editor.trace.load_index(context2)
        manifest2 = await editor.trace.load_manifest(context2)
        assert index2 is not None and manifest2 is not None
        trace2 = next(item for item in index2.chart_traces if item.chart_id == "chart_001")
        assert trace2.plot_data_file_resource_ids == tuple(derive_resource_id(
            f"reports/revision-2/{PurePosixPath(ref.path).relative_to('reports/revision-1').as_posix()}"
        ) for ref in refs)
        assert trace2.dataset_ids == fixture.chart.dataset_ids
        assert [(ref.analysis_id, ref.json_pointer, ref.fact_kind, ref.fact_key) for ref in trace2.fact_refs] == [
            (ref.analysis_id, ref.json_pointer, ref.fact_kind, ref.fact_key) for ref in trace.fact_refs
        ]
        migrated_refs = [next(item for item in index2.files if item.resource_id == resource_id)
                         for resource_id in trace2.plot_data_file_resource_ids]
        assert [item.size for item in migrated_refs] == [ref.size for ref in refs]
        assert [item.path for item in migrated_refs] == [
            f"reports/revision-2/{PurePosixPath(ref.path).relative_to('reports/revision-1').as_posix()}"
            for ref in refs
        ]
        assert [await workspace.afile_bytes(thread_id, item.path) for item in migrated_refs] == [
            (content, "application/json") for content in contents
        ]
        baseline = (await load_chart_edit_records(workspace, thread_id, context2.markdown_path))[0]
        assert baseline.data_origin == "original" and baseline.level == ("L1",)
        assert baseline.standard_parameters == first.standard_parameters
        assert baseline.chart.dataset_ids == fixture.chart.dataset_ids

        second = await edit_and_assert(context2, baseline.image.path, baseline.image.sha256,
            previous_edit_id=baseline.edit_id)
        current_pages = tuple(second.pages) or (SimpleNamespace(image=second.image, page_number=1),)
        markdown3 = header + "Revenue 3600 [[claim:claim-1]]" + "".join(
            f"\n\n![Revenue]({chart_edit_page_src(context2.markdown_path, second.edit_id, page.page_number)}) [[citation:citation_001]]\n"
            for page in current_pages
        )
        context3 = await export(context2, markdown3, 2)
        index3 = await editor.trace.load_index(context3)
        manifest3 = await editor.trace.load_manifest(context3)
        assert index3 is not None and manifest3 is not None
        trace3 = next(item for item in index3.chart_traces if item.chart_id == "chart_001")
        trace3_refs = [next(item for item in index3.files if item.resource_id == resource_id)
                       for resource_id in trace3.plot_data_file_resource_ids]
        assert [item.sha256 for item in trace3_refs] == [ref.sha256 for ref in refs]
        assert [item.size for item in trace3_refs] == [ref.size for ref in refs]
        assert [item.path for item in trace3_refs] == [
            f"reports/revision-3/{PurePosixPath(ref.path).relative_to('reports/revision-1').as_posix()}"
            for ref in refs
        ]
        assert [await workspace.afile_bytes(thread_id, item.path) for item in trace3_refs] == [
            (content, "application/json") for content in contents
        ]
        assert trace3.dataset_ids == fixture.chart.dataset_ids
        assert [(ref.analysis_id, ref.json_pointer, ref.fact_kind, ref.fact_key) for ref in trace3.fact_refs] == [
            (ref.analysis_id, ref.json_pointer, ref.fact_kind, ref.fact_key) for ref in trace.fact_refs
        ]
        third_record = (await load_chart_edit_records(workspace, thread_id, context3.markdown_path))[0]
        assert third_record.standard_parameters == first.standard_parameters
        assert [item.sha256 for item in third_record.plot_data_files] == [item.sha256 for item in refs]
        assert [item.size for item in third_record.plot_data_files] == [item.size for item in refs]
        assert [item.path for item in third_record.plot_data_files] == [
            f"reports/revision-3/{PurePosixPath(ref.path).relative_to('reports/revision-1').as_posix()}"
            for ref in refs
        ]
        assert len(index3.chart_traces) == len(manifest3.charts) == 1
        assert await workspace.afile_bytes(thread_id, fixture.chart_path) == (original_chart_bytes, "image/png")
        assert await workspace.aread_text(thread_id, fixture.context.markdown_path) == original_markdown
        for path, content in original_fact_bytes.items():
            assert (await workspace.afile_bytes(thread_id, path))[0] == content
        assert runner.registry.active_count == 0 and not runtime._logged_connections
    finally:
        await service.aclose()
        await lsp.aclose()
        await runtime.aclose()
        await editor.aclose()


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


def test_edited_export_keeps_registered_chart_binding_when_citation_moves() -> None:
    """编辑把 citation 标记与图片拆到不同段落时，已登记图表沿用登记的 Dataset 绑定。

    首次发布仍要求同段 citation；未登记图片不能借此获得绑定。
    """
    import pytest as _pytest

    from smart_reporting.reporting.delivery.artifacts_v1 import _markdown_image_bindings
    from smart_reporting.reporting.models import ReportingError

    markdown = "![收入](chart-001.png)\n\n[[citation:citation_001]]\n"
    citations = {"citation_001": "dataset-url-abc0001"}
    registered = {"reports/revision-1/chart-001.png": ("dataset-url-abc0001",)}

    with _pytest.raises(ReportingError, match="report_artifact_chart_citation_invalid"):
        _markdown_image_bindings(markdown, "reports/revision-1/report.md", citations)
    assert _markdown_image_bindings(
        markdown, "reports/revision-1/report.md", citations, registered_datasets=registered
    ) == {"reports/revision-1/chart-001.png": ("dataset-url-abc0001",)}
    with _pytest.raises(ReportingError, match="report_artifact_chart_citation_invalid"):
        _markdown_image_bindings(
            "![其他](other.png)\n", "reports/revision-1/report.md", citations,
            registered_datasets=registered,
        )
