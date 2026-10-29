from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext
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
    FactRefV1,
    RevisionTraceIndexV1,
    SubjectBindingV1,
    TableTraceV1,
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


async def _publication_fixture(
    tmp_path: Path, *, forged: str | None = None, table_source: bool = False, source_cell: bool = False, denominator: bool = False, population: bool = False,
    quality_record: bool = False,
):
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
    table_bytes = b'{"tables":[["month","revenue"],["2025-09",1200]]}'
    files = {
        "reports/report.md": markdown,
        "datasets/input.csv": csv,
        "reports/report.pdf": b"%PDF-1.4 report",
        "reports/report.docx": b"PK report",
    }
    table_source_path = "evidence/table.json"
    if table_source:
        files[table_source_path] = table_bytes
    denominator_path = "facts/denominator.json"
    if denominator:
        files[denominator_path] = b'{"analysisId":"analysis_001","metrics":[{"factId":"fact-aaaaaaaaaaaaaaaa","total":200}]}'
    if population:
        from .test_semantic_quantity import _proven_catalog

        proven_sources = _proven_catalog().sources
        table_bytes = proven_sources['trf-' + 'b' * 20]
        files[table_source_path] = table_bytes
        files[denominator_path] = proven_sources['trf-' + 'a' * 20]
    if quality_record:
        files["reports/quality-bundle-v1.json"] = b'{"version":"1","mode":"shadow"}'
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
    if table_source:
        table_resource_id = derive_resource_id(table_source_path)
        subject = SubjectBindingV1.model_validate({
            "subjectId": "sub-" + "4" * 16,
            "subjectKind": "text_claim",
            "locator": {"sectionId": "section_001"},
            "subjectSha256": hashlib.sha256(b"revenue is 1200").hexdigest(),
            "claimId": "claim-table",
            "factRefs": [],
            "numberReference": {
                "claimId": "claim-table",
                "token": "{{value:table-0000000000000001:amount:万元}}",
                "statementSha256": hashlib.sha256(b"revenue is 1200").hexdigest(),
                "tableDerivation": {
                    "unit": "万元",
                    "operands": [{
                        "fileResourceId": table_resource_id,
                        "tablePointer": "/tables/0",
                        "rowIndex": 0,
                        "columnIndex": 1,
                        "coefficient": "1",
                    }],
                },
            },
        })
        if denominator:
            proof = subject.number_reference.table_derivation.model_copy(update={
                "denominator_fact": FactRefV1(
                    analysisId="analysis_001", fileResourceId=derive_resource_id(denominator_path),
                    jsonPointer="/metrics/0", factKind="metric", factKey="fact-aaaaaaaaaaaaaaaa",
                ),
            })
            subject = subject.model_copy(update={"number_reference": subject.number_reference.model_copy(
                update={"table_derivation": proof},
            )})
        if population:
            from smart_reporting.reporting.trace.contracts_v1 import (
                TableDerivationV1,
                canonical_sha256,
            )
            from smart_reporting.reporting.trace.table_sources import (
                resolve_table_derivation,
                table_derivation_token,
            )

            parent = json.loads(files[denominator_path])
            proof = TableDerivationV1.model_validate({
                'unit': '元', 'operands': [{
                    'fileResourceId': table_resource_id, 'tablePointer': '/findings/0',
                    'rowIndex': row, 'columnIndex': 1, 'coefficient': '1',
                } for row in (0, 1)],
                'populationFact': {'analysisId': parent['analysisId'],
                    'fileResourceId': derive_resource_id(denominator_path), 'jsonPointer': '/metrics/0',
                    'factKind': 'metric', 'factKey': parent['metrics'][0]['factId']},
                'populationProofSha256': canonical_sha256(json.loads(table_bytes)['findings'][0]['populationProof']),
                'topSelection': 'items', 'topLimit': 2,
            })
            proof_sources = {table_resource_id: table_bytes,
                             derive_resource_id(denominator_path): files[denominator_path]}
            token = table_derivation_token(proof, proof_sources)
            assert token and resolve_table_derivation(token, proof, proof_sources)['value'] == 90
            subject = subject.model_copy(update={
                'fact_refs': (proof.population_fact,),
                'number_reference': subject.number_reference.model_copy(update={
                    'token': token, 'table_derivation': proof, 'display_text': '90元',
                }),
            })
        table_source_identity = _identity(
            table_source_path, table_bytes, "application/json"
        )
    else:
        subject = None
        table_source_identity = None
    index = build_csv_trace_index(
        handles=(handle,),
        lineage=(lineage,),
        report_id="report-1",
        revision=1,
        workflow_run_id="workflow-run",
        markdown_file=_identity("reports/report.md", markdown, "text/markdown"),
        table_source_files=(() if table_source_identity is None else (table_source_identity,))
        + ((_identity(denominator_path, files[denominator_path], "application/json"),) if denominator or population else ()),
        fact_files=({"analysis_001": _identity(denominator_path, files[denominator_path], "application/json")}
                    if denominator or population else None),
        subject_bindings=() if subject is None else (subject,),
        server_table_traces=(() if not source_cell else (TableTraceV1.model_validate({
            "tableId": "table-source-cell", "rowKeys": ["source-row:0"], "columnKeys": ["收入"],
            "cells": [{"rowKey": "source-row:0", "columnKey": "收入", "sourceCell": {
                "fileResourceId": table_resource_id, "tablePointer": "/tables/0",
                "rowIndex": 0, "columnIndex": 1, "coefficient": "1",
            }}],
        }),)),
        computation_files=(_identity("reports/quality-bundle-v1.json",
                                      files["reports/quality-bundle-v1.json"], "application/json"),)
        if quality_record else (),
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
@pytest.mark.parametrize("fault", ["state", "evaluate", "chart_evaluate", "table_evaluate", "semantic_evaluate", "overview_evaluate", "runtime_state", "quality_source_selection", "write", "read"])
async def test_quality_record_failure_preserves_index_and_http_downloads(tmp_path, monkeypatch, fault):
    from smart_reporting.reporting.trace import quality_bundle

    runtime, arguments, scope, durable, _, _, files, index = await _publication_fixture(tmp_path)
    original_get = runtime.state_repository.get
    async def get(run_id):
        if run_id == "report-1":
            if fault == "state":
                raise OSError("injected frozen requirements read failure")
            return durable
        return await original_get(run_id)
    runtime.state_repository.get = get
    state = {}
    runtime._scope = lambda _context: scope.as_state()
    runtime._state = lambda _context: state
    if fault == "runtime_state":
        def unavailable_state(_context):
            raise OSError("injected quality state failure")
        runtime._state = unavailable_state
    runtime._profile = lambda _context: SimpleNamespace(effective_profile_hash="a" * 64)
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    monkeypatch.setattr(publication_module, "build_csv_trace_index", lambda **_kwargs: index)
    if fault in {"evaluate", "chart_evaluate", "table_evaluate", "semantic_evaluate", "overview_evaluate"}:
        def fail(*_args, **_kwargs):
            raise RuntimeError("injected quality evaluation failure")
        monkeypatch.setattr(quality_bundle, {"evaluate": "evaluate_quality_bundle", "chart_evaluate": "evaluate_chart_quality", "table_evaluate": "evaluate_table_quality", "semantic_evaluate": "evaluate_semantic_alignment", "overview_evaluate": "build_management_overview"}[fault], fail)
    elif fault == "quality_source_selection":
        def fail(*_args, **_kwargs):
            raise RuntimeError("injected quality source dependency failure")
        monkeypatch.setattr(publication_module, "_quality_source_ids", fail)
    elif fault in {"write", "read"}:
        workspace = runtime.workspace_service
        original = workspace.awrite_bytes if fault == "write" else workspace.read_limited_regular_file
        async def fail(thread_id, path, *args, **kwargs):
            if path.endswith(quality_bundle.QUALITY_FILENAME):
                raise OSError("injected quality storage failure")
            return await original(thread_id, path, *args, **kwargs)
        monkeypatch.setattr(workspace, "awrite_bytes" if fault == "write" else "read_limited_regular_file", fail)
    identity = await runtime._write_trace_index(
        "reports/artifact-manifest.json", handles=(), lineage=(),
        markdown_artifact=_identity("reports/report.md", files["reports/report.md"], "text/markdown"),
        revision=1, run_context=SimpleNamespace(run_id="report-1"),
        markdown=files["reports/report.md"].decode(),
    )
    if fault == "overview_evaluate":
        index_raw = await runtime.workspace_service.read_limited_regular_file(
            scope.workspace_key, identity.path, max_bytes=16 * 1024 * 1024,
        )
        registered = RevisionTraceIndexV1.model_validate_json(index_raw)
        original = registered.model_copy(update={"files": tuple(
            file for file in registered.files if not file.path.endswith("/quality-bundle-v1.json")
        )})
        assert encode_trace_index(original) == encode_trace_index(index)
        quality_raw = await runtime.workspace_service.read_limited_regular_file(
            scope.workspace_key, "reports/quality-bundle-v1.json", max_bytes=16 * 1024 * 1024,
        )
        quality = quality_bundle.QualityBundle.model_validate_json(quality_raw)
        assert quality.management_overview.status == "unavailable"
        assert any(issue.code == "management_overview_unavailable" for issue in quality.issues)
    else:
        assert identity.sha256 == hashlib.sha256(encode_trace_index(index)).hexdigest()
    if fault not in {"runtime_state", "overview_evaluate"}:
        assert state["report_quality_issues"][0]["status"] == "unknown"
    elif fault == "runtime_state":
        runtime._state = lambda _context: state
    result = await runtime.issue_http_publication(**arguments)
    assert result["pdf"]["downloadUrl"] and result["word"]["downloadUrl"]


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["provider", "freeze", "receipt", "invalid_frozen"])
async def test_answer_registration_failure_preserves_quality_index_and_http_downloads(tmp_path, monkeypatch, fault):
    from smart_reporting.reporting.trace.quality_bundle import QualityBundle
    from smart_reporting.reporting.workflow.answer_review import AnswerReviewPlan, questions_sha256
    from smart_reporting.reporting.workflow.questions import request_questions

    runtime, arguments, scope, durable, artifacts, _, files, index = await _publication_fixture(tmp_path)
    questions = request_questions("核验收入")
    durable.payload["questionSpecs"] = questions.model_dump(mode="json", by_alias=True)
    if fault == "invalid_frozen":
        durable.payload["answerReviewPlan"] = {"version": "invalid"}
    original_get = runtime.state_repository.get

    async def get(run_id):
        return durable if run_id == "report-1" else await original_get(run_id)

    runtime.state_repository.get = get
    observed = []

    async def provider(_context):
        observed.append("provider")
        if fault == "provider":
            raise OSError("injected domain approval failure")
        return AnswerReviewPlan(questionSetSha256=questions_sha256(questions))

    async def command(_context, command):
        if command.name == "freeze_answer_review_plan":
            observed.append("freeze")
            if fault == "freeze":
                raise OSError("injected durable mapping failure")
            return SimpleNamespace(state=SimpleNamespace(report_run_id="foreign", payload={}))

    runtime.answer_review_plan_provider = provider
    runtime._apply_durable_command = command
    state = {}
    runtime._scope = lambda _: scope.as_state()
    runtime._state = lambda _: state
    runtime._profile = lambda _: SimpleNamespace(effective_profile_hash="a" * 64)
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    monkeypatch.setattr(publication_module, "build_csv_trace_index", lambda **_: index)
    identity = await runtime._write_trace_index("reports/report.manifest.json", handles=(), lineage=(),
        markdown_artifact=_identity("reports/report.md", files["reports/report.md"], "text/markdown"),
        revision=1, run_context=SimpleNamespace(run_id="report-1"), markdown=files["reports/report.md"].decode())
    expected = [] if fault == "invalid_frozen" else ["provider"] if fault == "provider" else ["provider", "freeze"]
    assert observed == expected
    assert state["report_quality_issues"][0]["code"] == "answer_review_registration_unavailable"
    workspace = runtime.workspace_service
    registered = RevisionTraceIndexV1.model_validate_json(await workspace.read_limited_regular_file(
        scope.workspace_key, identity.path, max_bytes=16 * 1024 * 1024))
    quality_file = next(file for file in registered.files if file.path.endswith("/quality-bundle-v1.json"))
    quality = QualityBundle.model_validate_json(await workspace.read_limited_regular_file(
        scope.workspace_key, quality_file.path, max_bytes=16 * 1024 * 1024))
    assert quality.question_coverage["answered"] == 0
    assert quality.answer_review_plan is None
    assert any(issue.code == "answer_review_registration_unavailable" for issue in quality.issues)
    expected_reason = "registered_plan_invalid" if fault == "invalid_frozen" else f"registration_{fault}_unavailable"
    assert any(expected_reason in issue.reasons for issue in quality.issues)
    assert registered.subject_bindings == index.subject_bindings and registered.datasets == index.datasets
    manifest_identity = await register_trace_manifest(workspace, scope.workspace_key, registered, overwrite=True)
    arguments["output"]["artifactManifest"] = manifest_identity.model_dump(mode="json", by_alias=True)
    result = await runtime.issue_http_publication(**arguments)
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        for kind, suffix in (("pdf", "pdf"), ("word", "docx")):
            response = await client.get(result[kind]["downloadUrl"])
            assert response.status_code == 200 and response.content == files[f"reports/report.{suffix}"]


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
async def test_http_publication_drops_hash_registered_foreign_index_but_still_issues_links(
    tmp_path: Path,
    forged: str,
) -> None:
    runtime, arguments, scope, durable, artifacts, grants, files, _ = await _publication_fixture(
        tmp_path, forged=forged
    )
    # AGENTS：清单/索引核验失败属于门禁问题，不阻止已生成 PDF/Word 的签发；
    # 伪造索引仍绝不被使用——新修订不复制、不登记该索引，编辑上下文不带溯源清单。
    result = await runtime.issue_http_publication(**arguments)
    assert result["publicationIssues"][0]["code"] == "report_trace_index_invalid"
    assert result["pdf"]["downloadUrl"] and result["word"]["downloadUrl"]
    assert artifacts.records and grants.records
    runtime.workspace_registry.resolve(scope)
    assert not await runtime.workspace_service.apath_exists(
        scope.workspace_key, "reports/revision-2/trace-index-v1.json"
    )
    context = ReportEditorContext.model_validate(durable.payload["reportEditorContexts"]["2"])
    assert context.artifact_manifest is None
    assert await runtime.workspace_service.aread_text(
        scope.workspace_key, context.markdown_path
    ) == files["reports/report.md"].decode()


# ---------------------------------------------------------------------------
# AGENTS 非阻断契约：PDF/Word 已生成且身份可读取时，签发阶段任何溯源/门禁类故障
# 都不得阻止下载链接签发；须返回失败原因，且不得标记为正式发布通过。
# 新增签发链路中可能失败的步骤时，在此登记一条故障注入用例。
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [OSError("editor storage unavailable"),
                                     ReportingError("editor_unavailable", "编辑授权不可用。")])
async def test_editor_grant_failure_preserves_verified_downloads(tmp_path, monkeypatch, failure):
    from smart_reporting.reporting.workflow.runtime.base import merge_publication_issues
    from smart_reporting.reporting_mcp.contracts import ReportingPublishedReport

    runtime, arguments, _, _, artifacts, grants, files, _ = await _publication_fixture(tmp_path)
    monkeypatch.setattr(runtime.editor_grants, "issue", AsyncMock(side_effect=failure))

    result = await runtime.issue_http_publication(**arguments)

    assert "editor" not in result
    assert artifacts.records and grants.records
    assert result["publicationIssues"][0]["code"] == "report_editor_grant_unavailable"
    gate = merge_publication_issues({"formalReleaseAllowed": True, "issues": []}, result["publicationIssues"])
    assert gate["formalReleaseAllowed"] is False
    # MCP's closed output schema must also accept a report with downloads only.
    report = ReportingPublishedReport.model_validate({
        "reportId": result["reportId"], "revision": result["revision"],
        **{kind: {key: value for key, value in result[kind].items() if key != "path"}
           for kind in ("pdf", "word")},
    })
    assert report.editor is None
    app = FastAPI()
    app.include_router(create_report_download_router(
        ReportDownloadHttpService(runtime.download_grants, artifacts)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        for artifact, suffix in (("pdf", "pdf"), ("word", "docx")):
            response = await client.get(result[artifact]["downloadUrl"])
            assert response.status_code == 200
            assert response.content == files[f"reports/report.{suffix}"]


@pytest.mark.anyio
@pytest.mark.parametrize("fault", [
    "manifest_unreadable", "manifest_changed", "index_unreadable", "lineage_snapshot",
    "lineage_runtime", "editor_snapshot", "editor_context", "editor_state_read", "editor_scope",
    "table_source_missing", "table_source_changed", "source_cell_missing", "source_cell_changed", "denominator_missing", "denominator_changed", "population_missing", "population_changed",
    "quality_record_missing", "quality_record_changed",
])
async def test_http_publication_never_blocks_links_on_lineage_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    from smart_reporting.report_editor import trace_revisions
    from smart_reporting.reporting.workflow.runtime.base import merge_publication_issues

    table_source_fault = fault.startswith(("table_source_", "source_cell_", "denominator_", "population_"))
    runtime, arguments, scope, durable, artifacts, grants, files, index = await _publication_fixture(
        tmp_path, table_source=table_source_fault, source_cell=fault.startswith("source_cell_"), denominator=fault.startswith("denominator_"), population=fault.startswith("population_"), quality_record=fault.startswith("quality_record_"),
    )
    manifest_path = arguments["output"]["artifactManifest"]["path"]
    workspace = runtime.workspace_service
    original_read = workspace.read_limited_regular_file
    if fault.startswith("quality_record_"):
        if fault == "quality_record_missing":
            await workspace.adelete_file(scope.workspace_key, "reports/quality-bundle-v1.json")
        else:
            await workspace.awrite_bytes(scope.workspace_key, "reports/quality-bundle-v1.json", b"{}", overwrite=True)
    elif table_source_fault:
        source_path = "facts/denominator.json" if fault.startswith(("denominator_", "population_")) else "evidence/table.json"
        source_id = derive_resource_id(source_path)
        assert any(file.resource_id == source_id for file in index.files)
        derivation = index.subject_bindings[0].number_reference.table_derivation
        assert (derivation.denominator_fact.file_resource_id if fault.startswith("denominator_")
                else derivation.population_fact.file_resource_id if fault.startswith("population_")
                else derivation.operands[0].file_resource_id) == source_id
        if fault in {"table_source_missing", "source_cell_missing", "denominator_missing", "population_missing"}:
            await workspace.adelete_file(scope.workspace_key, source_path)
        else:
            await workspace.awrite_bytes(scope.workspace_key, source_path, b"{}", overwrite=True)
    elif fault == "manifest_changed":
        await workspace.awrite_bytes(scope.workspace_key, manifest_path, b"{}", overwrite=True)
    elif fault in {"manifest_unreadable", "index_unreadable"}:
        target = manifest_path if fault == "manifest_unreadable" else "reports/trace-index-v1.json"

        async def failing_read(thread_id, path, **kwargs):
            if path == target:
                raise OSError("injected read failure")
            return await original_read(thread_id, path, **kwargs)

        monkeypatch.setattr(workspace, "read_limited_regular_file", failing_read)
    elif fault == "editor_snapshot":
        original_write = workspace.awrite_text

        async def failing_editor_write(thread_id, path, content, **kwargs):
            if path == "reports/revision-2/report.md":
                raise RuntimeError("injected editor snapshot failure")
            return await original_write(thread_id, path, content, **kwargs)

        monkeypatch.setattr(workspace, "awrite_text", failing_editor_write)
    elif fault == "editor_scope":
        # 作用域不一致（调用方 thread 与发布作用域不符）只拒绝编辑上下文。
        arguments = {**arguments, "caller_thread_id": "another-caller-thread"}
    elif fault == "editor_state_read":
        monkeypatch.setattr(
            runtime.state_repository,
            "get",
            AsyncMock(side_effect=RuntimeError("injected editor state read failure")),
        )
    elif fault == "editor_context":
        monkeypatch.setattr(
            runtime.state_repository,
            "apply",
            AsyncMock(side_effect=RuntimeError("injected editor context failure")),
        )
    else:
        error = (
            RuntimeError("injected lineage runtime failure")
            if fault == "lineage_runtime"
            else ReportingError("snapshot_integrity_failed", "注入的溯源快照失败。")
        )
        monkeypatch.setattr(
            trace_revisions, "snapshot_revision_lineage",
            AsyncMock(side_effect=error),
        )

    result = await runtime.issue_http_publication(**arguments)

    assert result["pdf"]["downloadUrl"] and result["word"]["downloadUrl"]
    assert artifacts.records and grants.records
    assert result["publicationIssues"] and all(item["message"] for item in result["publicationIssues"])
    if fault in {"editor_snapshot", "editor_context", "editor_state_read", "editor_scope"}:
        assert "editor" not in result
        assert result["publicationIssues"][-1]["code"] == {
            "editor_snapshot": "report_editor_snapshot_unavailable",
            "editor_context": "report_editor_context_unavailable",
            "editor_state_read": "report_editor_context_unavailable",
            "editor_scope": "report_editor_scope_mismatch",
        }[fault]
        assert "reportEditorContexts" not in durable.payload
    else:
        assert result["editor"]["openUrl"]
        context = ReportEditorContext.model_validate(durable.payload["reportEditorContexts"]["2"])
        assert context.artifact_manifest is None
    gate = merge_publication_issues({"formalReleaseAllowed": True, "issues": []}, result["publicationIssues"])
    assert gate["formalReleaseAllowed"] is False and gate["issues"] == result["publicationIssues"]
    app = FastAPI()
    app.include_router(create_report_download_router(
        ReportDownloadHttpService(runtime.download_grants, artifacts)
    ))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        for artifact, suffix in (("pdf", "pdf"), ("word", "docx")):
            response = await client.get(result[artifact]["downloadUrl"])
            assert response.status_code == 200
            assert response.content == files[f"reports/report.{suffix}"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_publication_keeps_links_when_second_chart_page_identity_changes(tmp_path):
    """Register the new editor page-identity fault in the publication fault contract.

    The shared integration scenario exercises real editor export, corrupts page2,
    and asserts failed lineage validation while both generated download links stay
    available; document rendering itself uses the existing deterministic fixture.
    """
    from smart_reporting.reporting.tests.test_report_editor_lineage_export import (
        test_export_revision_registers_ai_chart_edit_and_still_issues_links,
    )

    await test_export_revision_registers_ai_chart_edit_and_still_issues_links(tmp_path, "page_changed")


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_publication_keeps_links_when_reedited_paginated_data_changes(tmp_path):
    """多轮补证改图的新快照身份变化：PDF/Word 仍签发，追溯明确降级。"""
    from smart_reporting.reporting.tests.test_report_editor_lineage_export import (
        test_export_revision_registers_l2_chart_edit_plot_data,
    )

    await test_export_revision_registers_l2_chart_edit_plot_data(
        tmp_path, "l2_plot_changed", "paginated_reedit"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_publication_keeps_lineage_and_links_when_chart_continuation_fails(tmp_path):
    """继续编辑侧车写入失败不能丢弃正式追溯或阻断 PDF/Word 下载。"""
    from smart_reporting.reporting.tests.test_report_editor_lineage_export import (
        test_export_revision_registers_l2_chart_edit_plot_data,
    )

    await test_export_revision_registers_l2_chart_edit_plot_data(
        tmp_path, "continuation_failed", "paginated_reedit"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["none", "overview_write", "state_store"])
async def test_overview_delivery_faults_preserve_files_and_http_downloads(tmp_path, monkeypatch, fault):
    from smart_reporting.reporting.delivery.report_runtime.overview import load_overview
    from smart_reporting.reporting.workflow.management_overview import (
        management_overview_projection,
    )
    from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY, WorkspaceReportService

    runtime, arguments, scope, _, artifacts, _, files, _ = await _publication_fixture(tmp_path)
    workspace = runtime.workspace_service
    service = WorkspaceReportService(workspace)
    context = RunContext(run_id="workflow-run", session_id=scope.workspace_key, session_state={})
    job = {"jobId": "job-1", "sources": []}
    monkeypatch.setattr(service, "_load_job", lambda *_: job)
    monkeypatch.setattr(service, "_job_status", AsyncMock(return_value={}))
    original_write = workspace.awrite_bytes
    faults_seen = []

    async def write(thread, path, content, **kwargs):
        if fault == "overview_write" and path.startswith(".reporting-projections/"):
            faults_seen.append(fault)
            raise OSError("injected overview storage failure")
        return await original_write(thread, path, content, **kwargs)

    monkeypatch.setattr(workspace, "awrite_bytes", write)
    if fault == "state_store":
        def store(*_):
            faults_seen.append(fault)
            raise OSError("injected job storage failure")
        monkeypatch.setattr(service, "_store_job", store)

    async def run(action, payload, _context):
        if action == "validate_pdf":
            return {"ok": fault != "overview_write", "issues": (
                [{"code": "management_overview_projection_unknown"}] if fault == "overview_write" else [])}
        assert action == "render_markdown"
        render = {"markdown": _identity("reports/report.md", files["reports/report.md"], "text/markdown").model_dump(by_alias=True)}
        if fault == "overview_write":
            assert payload["job"]["_managementOverviewProjection"]["invalid"]
        else:
            identity = payload["job"]["_managementOverviewProjectionFile"]
            assert identity["size"] > 48 * 1024
            assert "_managementOverviewProjection" not in payload["job"]
            root = runtime.workspace_registry.resolve(scope).root
            assert load_overview(payload["job"], root)["status"] == "unavailable"
        for kind, path_key, suffix in (("pdf", "output_path", "pdf"), ("word", "word_output_path", "docx")):
            path = payload[path_key]
            raw = files[f"reports/report.{suffix}"]
            await workspace.aensure_directory(scope.workspace_key, str(Path(path).parent))
            await original_write(scope.workspace_key, path, raw)
            render[kind] = {"path": path, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        return {"status": "rendered", "render": render}

    monkeypatch.setattr(service, "_run_report_runtime", run)
    payload = management_overview_projection(None, hashlib.sha256(files["reports/report.md"]).hexdigest())
    payload["markdown"] = "待确认事项" * 6000  # Exceeds the durable job budget, within the sidecar budget.
    output = await service._render_report_pair("job-1", "reports/report.md", "rendered/revision-2/report.pdf",
        artifact_manifest=None, management_overview=payload, run_context=context)
    assert faults_seen == ([] if fault == "none" else [fault])
    assert output["validation"]["ok"] == (fault == "none")
    if fault == "state_store":
        assert output["validation"]["issues"][0]["code"] == "report_render_state_unavailable"
    if fault == "none":
        assert len(json.dumps(context.session_state[REPORT_JOBS_STATE_KEY]).encode()) < 48 * 1024
    for kind, suffix in (("pdf", "pdf"), ("word", "docx")):
        arguments["output"][f"{kind}Path"] = output[f"{kind}Path"]
        raw, _ = await workspace.afile_bytes(scope.workspace_key, output[f"{kind}Path"])
        assert raw == files[f"reports/report.{suffix}"]
    result = await runtime.issue_http_publication(**arguments)
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        for kind, suffix in (("pdf", "pdf"), ("word", "docx")):
            response = await client.get(result[kind]["downloadUrl"])
            assert response.status_code == 200
            assert response.content == files[f"reports/report.{suffix}"]


@pytest.mark.anyio
async def test_published_quality_uses_cas_frozen_requirements_over_session_mirror(tmp_path, monkeypatch):
    from smart_reporting.reporting.trace.quality_bundle import QUALITY_FILENAME, QualityBundle
    from smart_reporting.reporting.workflow.questions import request_questions

    runtime, _, scope, durable, _, _, files, index = await _publication_fixture(tmp_path)
    frozen = request_questions("原始收入与成本问题，保留数据缺口")
    durable.payload["questionSpecs"] = frozen.model_dump(mode="json", by_alias=True)
    runtime.state_repository.get = AsyncMock(return_value=durable)
    state = {"report_request_context": {"questionSpecs": request_questions("只问收入").model_dump(mode="json", by_alias=True)}}
    runtime._scope = lambda _context: scope.as_state()
    runtime._state = lambda _context: state
    runtime._profile = lambda _context: SimpleNamespace(effective_profile_hash="a" * 64)
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    monkeypatch.setattr(publication_module, "build_csv_trace_index", lambda **_kwargs: index)
    identity = await runtime._write_trace_index(
        "reports/artifact-manifest.json", handles=(), lineage=(),
        markdown_artifact=_identity("reports/report.md", files["reports/report.md"], "text/markdown"),
        revision=1, run_context=SimpleNamespace(run_id="report-1"),
        markdown=files["reports/report.md"].decode(),
    )
    stored = RevisionTraceIndexV1.model_validate_json(await runtime.workspace_service.read_limited_regular_file(
        scope.workspace_key, identity.path, max_bytes=identity.size))
    quality_file = next(file for file in stored.files if file.path.endswith("/" + QUALITY_FILENAME))
    raw = await runtime.workspace_service.read_limited_regular_file(scope.workspace_key, quality_file.path,
                                                                  max_bytes=quality_file.size)
    assert hashlib.sha256(raw).hexdigest() == quality_file.sha256
    bundle = QualityBundle.model_validate_json(raw)
    assert bundle.question_specs == frozen
    assert bundle.question_coverage["effectiveAnswerRate"] is None
    assert state["report_quality_issues"] == []


@pytest.mark.anyio
@pytest.mark.parametrize("failed_format", ["pdf", "word"])
async def test_format_persistence_failure_keeps_other_download(tmp_path, failed_format):
    runtime, arguments, _, _, artifacts, _, files, _ = await _publication_fixture(tmp_path)
    original_put = artifacts.put

    async def put(artifact, chunks):
        if artifact.artifact == failed_format:
            raise OSError("injected storage failure")
        await original_put(artifact, chunks)

    artifacts.put = put
    result = await runtime.issue_http_publication(**arguments)
    surviving = "word" if failed_format == "pdf" else "pdf"
    assert surviving in result and failed_format not in result
    assert result["publicationIssues"][-1]["code"] == "report_format_persistence_failed"
    app = FastAPI()
    app.include_router(
        create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts))
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        response = await client.get(result[surviving]["downloadUrl"])
        assert response.status_code == 200
        assert (
            response.content == files[f"reports/report.{'pdf' if surviving == 'pdf' else 'docx'}"]
        )


@pytest.mark.anyio
async def test_answer_review_checker_failure_preserves_index_and_downloads(tmp_path, monkeypatch):
    import hashlib

    from smart_reporting.reporting.trace import quality_bundle
    from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
    from smart_reporting.reporting.workflow.answer_review import AnswerReviewPlan, questions_sha256
    from smart_reporting.reporting.workflow.questions import request_questions
    from smart_reporting.reporting.workflow.runtime import publication as publication_module

    runtime, arguments, scope, durable, _, _, files, index = await _publication_fixture(tmp_path)
    questions = request_questions("收入证据是否充分")
    durable.payload.update(
        {
            "questionSpecs": questions.model_dump(mode="json", by_alias=True),
            "answerReviewPlan": AnswerReviewPlan(
                questionSetSha256=questions_sha256(questions)
            ).model_dump(mode="json", by_alias=True),
        }
    )
    original_get = runtime.state_repository.get

    async def get(run_id):
        return durable if run_id == "report-1" else await original_get(run_id)

    runtime.state_repository.get = get
    runtime._scope = lambda _: scope.as_state()
    state = {}
    runtime._state = lambda _: state
    runtime._profile = lambda _: SimpleNamespace(effective_profile_hash="a" * 64)
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    monkeypatch.setattr(publication_module, "build_csv_trace_index", lambda **_: index)

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected answer reviewer failure")

    monkeypatch.setattr(quality_bundle, "evaluate_answer_review", fail)
    identity = await runtime._write_trace_index(
        "reports/artifact-manifest.json",
        handles=(),
        lineage=(),
        markdown_artifact=_identity(
            "reports/report.md", files["reports/report.md"], "text/markdown"
        ),
        revision=1,
        run_context=SimpleNamespace(run_id="report-1"),
        markdown=files["reports/report.md"].decode(),
    )
    raw = await runtime.workspace_service.read_limited_regular_file(
        scope.workspace_key, identity.path, max_bytes=identity.size
    )
    assert hashlib.sha256(raw).hexdigest() == identity.sha256
    saved_index = RevisionTraceIndexV1.model_validate_json(raw)
    quality_file = next(
        file for file in saved_index.files if file.path.endswith(quality_bundle.QUALITY_FILENAME)
    )
    stored = await runtime.workspace_service.read_limited_regular_file(
        scope.workspace_key, quality_file.path, max_bytes=quality_file.size
    )
    quality = quality_bundle.QualityBundle.model_validate_json(stored)
    assert any(issue.code == "answer_review_unavailable" for issue in quality.issues)
    assert quality.question_coverage["effectiveAnswerRate"] is None
    result = await runtime.issue_http_publication(**arguments)
    assert result["pdf"]["downloadUrl"] and result["word"]["downloadUrl"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", ["word_persistence", "editor_grant", "delivery_record"])
async def test_editor_delivery_retry_never_blocks_links_on_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    """编辑器交付重试（补存、补签、登记重试结果）任一步失败都不阻断已核验格式的下载签发。"""
    from .test_editor_partial_delivery import delivery_editor

    failing = {"word"}
    harness = await delivery_editor(tmp_path, ("pdf", "word"), failing)
    editor, current, document = harness.editor, harness.current, harness.document
    first = await editor.export_revision(current, expected_sha256=document.sha256)
    assert first["revision"] == 3 and "word" not in first

    failing.clear()
    if fault == "word_persistence":
        failing.add("word")
    elif fault == "editor_grant":
        monkeypatch.setattr(editor.editor_grants, "issue", AsyncMock(side_effect=OSError("editor grants down")))
    else:
        original_apply = harness.repository.apply

        async def failing_apply(run_id, command, *, expected_version):
            if command.name == "record_report_editor_delivery":
                raise RuntimeError("injected delivery record failure")
            return await original_apply(run_id, command, expected_version=expected_version)

        monkeypatch.setattr(harness.repository, "apply", failing_apply)

    retried = await editor.export_revision(current, expected_sha256=document.sha256)

    assert retried["revision"] == 3 and "pdf" in retried
    codes = [issue["code"] for issue in retried["validation"]["issues"]]
    if fault == "word_persistence":
        assert "word" not in retried and codes == ["report_word_persistence_failed"]
        assert retried["validation"]["ok"] is False
    elif fault == "editor_grant":
        assert "word" in retried and "editor" not in retried
        assert codes == ["report_editor_grant_unavailable"] and retried["validation"]["ok"] is False
    else:
        # 登记失败只影响后续读取到的验收状态；本次补存补签照常完成。
        assert "word" in retried and retried["validation"] == {"ok": True, "issues": []}
        assert "reportEditorDeliveries" not in harness.repository.durable.payload
    assert "4" not in harness.repository.durable.payload["reportEditorContexts"]
