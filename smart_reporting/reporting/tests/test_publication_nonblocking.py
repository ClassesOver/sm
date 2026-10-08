from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.workflow.runtime import publication


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["failed_receipt", "invalid_counts", "changed_hash"])
async def test_render_validation_failure_retains_actual_artifacts(monkeypatch, failure):
    manifest = {
        "reportId": "report-1", "revision": 1, "codingTaskKey": "task-1",
        "datasetSnapshotHash": "a" * 64, "effectiveProfileHash": "b" * 64,
        "markdown": {"path": "reports/report.md", "mediaType": "text/markdown",
                     "size": 1, "sha256": "c" * 64},
        "citations": [{"citationId": "citation_001", "datasetId": "dataset_001",
                       "requirementId": "requirement_001", "snapshotHash": "a" * 64}],
        "sections": ["section_001"], "sectionNumbers": ["1"],
        "headingNumbers": [{"level": 2, "number": "1", "title": "运营分析",
                           "sectionCode": "section_001", "anchor": "report-section-001"}],
    }
    validation = {
        "ok": failure != "failed_receipt", "pdfSha256": "a" * 64,
        "wordSha256": "b" * 64, "issues": [{"code": "layout_mismatch"}],
    }
    if failure == "changed_hash":
        validation["pdfSha256"] = "c" * 64
    state = {
        "report_artifacts": {"draft": manifest}, "report_dataset_lineage": [],
        "report_data_requirements": [], "report_analysis_plan": [],
        "report_workflow_result": {"jobId": "job-1", "revision": 0, "markdownPath": "reports/report.md"},
    }
    runtime = object.__new__(publication.RuntimePublicationMixin)
    runtime._state = lambda _context: state
    runtime._scope = lambda _context: {"threadId": "thread", "externalRunId": "external-1"}
    runtime._workflow_result = lambda current: current["report_workflow_result"]
    runtime._envelope = lambda _context: SimpleNamespace(period=None)
    runtime._tool_context = lambda context: context
    runtime._data_shapes = lambda _context: []
    runtime._snapshots = lambda _context: []
    runtime._source_links_by_dataset = AsyncMock(return_value={})
    runtime.report_tools = SimpleNamespace(
        bind_citation_presentations=AsyncMock(),
        _render_report_pair=AsyncMock(return_value={"wordPath": "reports/report.docx", "validation": validation}),
        discard_report_revision=AsyncMock(),
    )

    async def hash_file(_thread, path):
        return {"path": path, "size": 3, "sha256": ("a" if path.endswith("pdf") else "b") * 64}

    runtime.workspace_service = SimpleNamespace(ahash_file=hash_file)
    monkeypatch.setattr(publication, "_frozen_outline", lambda _state: SimpleNamespace(title="运营分析"))
    monkeypatch.setattr(publication, "_report_pdf_path", lambda *_args: "reports/report.pdf")
    monkeypatch.setattr(publication, "_citation_presentations", lambda **_kwargs: [])
    monkeypatch.setattr(publication, "_reporting_observed_data_facts", lambda *_args: [])
    monkeypatch.setattr(publication, "_source_warnings_from_state", lambda _state: [])

    result = await runtime._render_and_validate(RunContext(run_id="report-1", session_id="thread", session_state=state))

    assert result["status"] == "validation_failed"
    assert result["validation"]["ok"] is False
    assert result["validationIssues"]
    assert result["pdfSha256"] == "a" * 64
    assert result["wordSha256"] == "b" * 64
    assert result["pdfPath"] == "reports/report.pdf"
    assert result["wordPath"] == "reports/report.docx"
    runtime.report_tools.discard_report_revision.assert_not_awaited()
    assert state["report_workflow_result"] is result
