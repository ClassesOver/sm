from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
from smart_reporting.reporting.data_sources import DatasetHandle
from smart_reporting.reporting.delivery.artifacts_v1 import (
    ArtifactFile,
    DatasetLineage,
    ReportArtifactManifest,
)
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportDownloadGrantService,
    ReportDownloadHttpService,
    create_report_download_router,
)
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.contracts_v1 import (
    RevisionTraceIndexV1,
    derive_resource_id,
)
from smart_reporting.reporting.trace.index_builder import build_csv_trace_index, encode_trace_index
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.runtime import publication as publication_module
from smart_reporting.reporting.workflow.scope import (
    REPORT_WORKFLOW_SCOPE_DEPENDENCY,
    resolve_reporting_workflow_scope,
)

from .delivery_fakes import InMemoryDownloadGrantRepository, InMemoryReportArtifactRepository
from .lineage_fixtures.manifest import register_trace_manifest


@pytest.mark.anyio
async def test_registration_switch_omits_new_trace_index_without_removing_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = resolve_reporting_workflow_scope(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        dependencies={
            REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                "externalRunId": "external-1",
                "threadId": "thread-1",
                "userId": "user-1",
                "database": "database-1",
                "companyId": "company-1",
            }
        },
    )
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    registry.resolve(scope)
    workspace = ReportingWorkspaceRouter(registry)
    markdown = b"# Report\n"
    markdown_path = "reports/report.md"
    manifest_path = "reports/report.manifest.json"
    await workspace.awrite_bytes(scope.workspace_key, markdown_path, markdown)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = workspace
    runtime.trace_registration_enabled = False
    runtime._scope = lambda _context: scope.as_state()
    runtime._profile = lambda _context: SimpleNamespace(effective_profile_hash="p" * 64)
    runtime._state = lambda _context: {}
    runtime._write_trace_index = AsyncMock()
    captured: dict[str, object] = {}

    def build_manifest(**values):
        captured.update(values)
        return SimpleNamespace(
            trace_index=values["trace_index"],
            model_dump=lambda **_options: {"traceIndex": values["trace_index"]},
        )

    monkeypatch.setattr(publication_module, "build_authoritative_manifest", build_manifest)
    monkeypatch.setattr(
        publication_module,
        "_frozen_outline",
        lambda _state: SimpleNamespace(sections=()),
    )
    accepted = [_identity(markdown_path, markdown, "text/markdown").model_dump(
        mode="json", by_alias=True
    )]

    manifest = await runtime._build_and_write_artifact_manifest(
        manifest_path,
        accepted_artifacts=accepted,
        markdown_path=markdown_path,
        lineage=(),
        revision=1,
        task_key="task-1",
        section_numbers=(),
        heading_numbers=(),
        run_context=SimpleNamespace(run_id="report-1"),
    )

    assert manifest.trace_index is None
    assert captured["trace_index"] is None
    runtime._write_trace_index.assert_not_awaited()
    assert await workspace.apath_exists(scope.workspace_key, manifest_path)
    assert not await workspace.apath_exists(
        scope.workspace_key, "reports/trace-index-v1.json"
    )


def _identity(path: str, content: bytes, media_type: str) -> ArtifactFile:
    return ArtifactFile(
        path=path,
        mediaType=media_type,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


async def _publication_fixture(tmp_path: Path, *, forged: str | None = None):
    dependencies = {
        REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
            "externalRunId": "external-1",
            "threadId": "caller-thread",
            "userId": "user-1",
            "database": "database-1",
            "companyId": "company-1",
        }
    }
    scope = resolve_reporting_workflow_scope(
        run_id="workflow-run",
        session_id="workflow-session",
        user_id="user-1",
        dependencies=dependencies,
    )
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    registry.resolve(scope)
    workspace = ReportingWorkspaceRouter(registry)
    markdown = b"# Report\n"
    csv = b"period,revenue\n2025-09,1200\n"
    files = {
        "reports/report.md": markdown,
        "datasets/input.csv": csv,
        "reports/report.pdf": b"%PDF-1.4 report",
        "reports/report.docx": b"PK report",
    }
    for path, content in files.items():
        await workspace.awrite_bytes(scope.workspace_key, path, content)
    handle = DatasetHandle(
        dataset_id="dataset-url-abc0001",
        source_id="mcp-url",
        source_type="url_csv",
        path="datasets/input.csv",
        row_count=1,
        size=len(csv),
        sha256=hashlib.sha256(csv).hexdigest(),
        requirement_id="attachment-001",
        sql_hash="a" * 64,
        filename="input.csv",
    )
    lineage = DatasetLineage(
        datasetId=handle.dataset_id,
        sourceId=handle.source_id,
        sourceType=handle.source_type,
        requirementId=handle.requirement_id,
        sqlHash=handle.sql_hash,
        rowCount=handle.row_count,
        size=handle.size,
        sha256=handle.sha256,
    )
    index = build_csv_trace_index(
        handles=(handle,),
        lineage=(lineage,),
        report_id="report-1",
        revision=1,
        workflow_run_id="workflow-run",
        markdown_file=_identity("reports/report.md", markdown, "text/markdown"),
    )
    if forged is not None:
        payload = index.model_dump(mode="json", by_alias=True)
        if forged in {"markdownSize", "markdownSha256"}:
            markdown_entry = next(
                file
                for file in payload["files"]
                if file["resourceId"] == payload["markdownFileResourceId"]
            )
            markdown_entry["size" if forged == "markdownSize" else "sha256"] = (
                len(markdown) + 1 if forged == "markdownSize" else "f" * 64
            )
        elif forged == "markdownFileResourceId":
            payload[forged] = derive_resource_id(handle.path)
        else:
            payload[forged] = 9 if forged == "revision" else "foreign-identity"
        index = RevisionTraceIndexV1.model_validate(payload)
    await workspace.awrite_bytes(
        scope.workspace_key, "reports/trace-index-v1.json", encode_trace_index(index)
    )
    manifest_identity = await register_trace_manifest(workspace, scope.workspace_key, index)
    # A valid accepted manifest registers the forged index's actual bytes and hash.
    if forged is not None:
        manifest_bytes, _ = await workspace.afile_bytes(scope.workspace_key, manifest_identity.path)
        manifest = ReportArtifactManifest.model_validate_json(manifest_bytes)
        manifest = manifest.model_copy(
            update={
                "report_id": "report-1",
                "revision": 1,
                "markdown": _identity("reports/report.md", markdown, "text/markdown"),
                "trace_index": _identity(
                    "reports/trace-index-v1.json", encode_trace_index(index), "application/json"
                ),
            }
        )
        manifest_bytes = manifest.model_dump_json(by_alias=True).encode()
        await workspace.awrite_bytes(
            scope.workspace_key, manifest_identity.path, manifest_bytes, overwrite=True
        )
        manifest_identity = _identity(manifest_identity.path, manifest_bytes, "application/json")

    durable = SimpleNamespace(state_version=3, payload={})

    class StateRepository:
        async def get(self, run_id):
            assert run_id == "workflow-run"
            return durable

        async def apply(self, run_id, command, *, expected_version):
            assert run_id == "workflow-run" and expected_version == durable.state_version
            assert command.name == "set_report_editor_context"
            context = ReportEditorContext.model_validate(command.payload["context"])
            contexts = durable.payload.setdefault("reportEditorContexts", {})
            serialized = context.model_dump(mode="json", by_alias=True)
            assert contexts.get(str(context.revision), serialized) == serialized
            contexts[str(context.revision)] = serialized
            durable.state_version += 1

    artifacts = InMemoryReportArtifactRepository()
    grants_repository = InMemoryDownloadGrantRepository()
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_registry = registry
    runtime.workspace_service = workspace
    runtime.state_repository = StateRepository()
    runtime.artifact_persistence = ReportArtifactPersistenceService(artifacts, workspace)
    runtime.download_grants = ReportDownloadGrantService(grants_repository)
    runtime.editor_grants = ReportEditorGrantService(
        InMemoryReportEditorRepository(), secret="s" * 32
    )
    runtime.report_public_base_url = "http://reports.test"
    output = {
        "reportId": "report-1",
        "revision": 2,
        "jobId": "job-1",
        "editorJob": {"jobId": "job-1", "status": "validated"},
        "markdownPath": "reports/report.md",
        "artifactManifest": manifest_identity.model_dump(mode="json", by_alias=True),
    }
    for artifact, suffix in (("pdf", "pdf"), ("word", "docx")):
        identity = _identity(
            f"reports/report.{suffix}",
            files[f"reports/report.{suffix}"],
            "application/pdf"
            if artifact == "pdf"
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        output.update(
            {
                f"{artifact}Path": identity.path,
                f"{artifact}Size": identity.size,
                f"{artifact}Sha256": identity.sha256,
            }
        )
    arguments = dict(
        thread_id=scope.workspace_key,
        caller_thread_id="caller-thread",
        user_id="user-1",
        workflow_session_id="workflow-session",
        workflow_run_id="workflow-run",
        dependencies=dependencies,
        output=output,
    )
    return runtime, arguments, scope, durable, artifacts, grants_repository, files, index


@pytest.mark.anyio
async def test_http_publication_relocates_registered_lineage_and_replays(tmp_path: Path) -> None:
    (
        runtime,
        arguments,
        scope,
        durable,
        artifacts,
        _,
        files,
        source_index,
    ) = await _publication_fixture(tmp_path)
    original_output = deepcopy(arguments["output"])
    result = await runtime.issue_http_publication(**arguments)
    assert arguments["output"] == original_output
    assert runtime.workspace_registry.get(scope.workspace_key) is None
    context_payload = deepcopy(durable.payload["reportEditorContexts"]["2"])
    context = ReportEditorContext.model_validate(context_payload)
    assert context.markdown_path == "reports/revision-2/report.md"
    assert context.artifact_manifest.path == "reports/revision-2/report.manifest.json"
    assert context.scope == scope.as_state()
    runtime.workspace_registry.resolve(scope)
    workspace = runtime.workspace_service
    manifest_bytes, _ = await workspace.afile_bytes(
        scope.workspace_key, context.artifact_manifest.path
    )
    assert (
        _identity(context.artifact_manifest.path, manifest_bytes, "application/json")
        == context.artifact_manifest
    )
    manifest = ReportArtifactManifest.model_validate_json(manifest_bytes)
    assert manifest.revision == 2 and manifest.markdown.path == context.markdown_path
    index_bytes, _ = await workspace.afile_bytes(scope.workspace_key, manifest.trace_index.path)
    assert (
        _identity(manifest.trace_index.path, index_bytes, "application/json")
        == manifest.trace_index
    )
    index = RevisionTraceIndexV1.model_validate_json(index_bytes)
    assert (index.report_id, index.revision, index.workflow_run_id) == (
        "report-1",
        2,
        "workflow-run",
    )
    assert index.markdown_file_resource_id == derive_resource_id(context.markdown_path)
    dataset = index.datasets[0]
    dataset_file = next(
        item for item in index.files if item.resource_id == dataset.file_resource_id
    )
    assert dataset_file.path == "reports/revision-2/trace-resources/datasets/input.csv"
    assert dataset.file_resource_id == derive_resource_id(dataset_file.path)
    assert dataset.file_resource_id != source_index.datasets[0].file_resource_id
    for file in index.files:
        content, _ = await workspace.afile_bytes(scope.workspace_key, file.path)
        assert (len(content), hashlib.sha256(content).hexdigest()) == (file.size, file.sha256)
    assert (await workspace.afile_bytes(scope.workspace_key, dataset_file.path))[0] == files[
        "datasets/input.csv"
    ]

    replay = await runtime.issue_http_publication(**arguments)
    assert durable.payload["reportEditorContexts"]["2"] == context_payload
    assert len(artifacts.records) == 2
    assert replay["pdf"]["downloadUrl"] != result["pdf"]["downloadUrl"]
    editor = ReportEditorService(
        state_repository=runtime.state_repository,
        workspace_registry=runtime.workspace_registry,
        workspace=workspace,
        trace_cursor_secret=b"trace-cursor-secret-32-bytes-ok!",
    )
    app = FastAPI()
    app.include_router(
        create_report_editor_router(runtime.editor_grants, editor=editor, cookie_secure=False)
    )
    app.include_router(
        create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts))
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        opened = await client.get(replay["editor"]["openUrl"], follow_redirects=False)
        assert opened.status_code == 303
        sources = await client.get("/reports/v1/editor/report-1/2/api/sources")
        assert sources.status_code == 200 and sources.json()["available"] is True
        assert sources.json()["revision"] == 2
        prefix = f"/reports/v1/editor/report-1/2/api/datasets/{dataset.dataset_id}"
        preview = await client.get(f"{prefix}/preview")
        assert preview.status_code == 200 and preview.json()["rowCountTotal"] == 1
        download = await client.get(f"{prefix}/download")
        assert download.status_code == 200 and download.content == files["datasets/input.csv"]
        for artifact, suffix in (("pdf", "pdf"), ("word", "docx")):
            response = await client.get(replay[artifact]["downloadUrl"])
            assert (
                response.status_code == 200
                and response.content == files[f"reports/report.{suffix}"]
            )
        assert (await client.get(result["pdf"]["downloadUrl"])).status_code == 404


@pytest.mark.anyio
@pytest.mark.parametrize(
    "forged",
    [
        "reportId",
        "revision",
        "workflowRunId",
        "markdownFileResourceId",
        "markdownSize",
        "markdownSha256",
    ],
)
async def test_http_publication_rejects_hash_registered_foreign_index_before_copy(
    tmp_path: Path,
    forged: str,
) -> None:
    runtime, arguments, scope, durable, artifacts, grants, _, _ = await _publication_fixture(
        tmp_path, forged=forged
    )
    with pytest.raises(ReportingError) as error:
        await runtime.issue_http_publication(**arguments)
    assert error.value.code == "report_trace_index_invalid"
    assert not await runtime.workspace_service.apath_exists(
        scope.workspace_key, "reports/revision-2"
    )
    assert durable.payload == {} and durable.state_version == 3
    assert not artifacts.records and not grants.records
