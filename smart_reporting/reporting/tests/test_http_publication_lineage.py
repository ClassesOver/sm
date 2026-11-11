from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
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
    ReportArtifactSpec,
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
from smart_reporting.reporting.workflow.runtime import planning as planning_module
from smart_reporting.reporting.workflow.runtime import publication as publication_module
from smart_reporting.reporting.workflow.scope import (
    REPORT_WORKFLOW_SCOPE_DEPENDENCY,
    resolve_reporting_workflow_scope,
)

from .delivery_fakes import InMemoryDownloadGrantRepository, InMemoryReportArtifactRepository
from .lineage_fixtures.manifest import register_trace_manifest
from .test_native_publication_nonblocking import create_publication


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['registration', 'persistence', 'primary_grant', 'editor_grant', 'oversize', 'receipt', 'receipt_identity', 'postwrite', 'review', 'missing', 'identity', 'publication_review', 'publication_missing', 'publication_identity'])
async def test_pdf_extract_http_keeps_verified_download_on_post_generation_faults(tmp_path, monkeypatch, fault):
    """提取回执、写后复核及登记故障不阻断实际身份可核验的 PDF 下载。"""
    from io import BytesIO
    from pypdf import PdfReader
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE, create_native_editor_router
    from .test_native_pdf_extract import extract_fixture

    f = await extract_fixture(tmp_path)
    raw, _ = await f.editor.grants.issue(f.parent, capabilities=f.editor.capabilities(f.parent))
    token, _ = await f.editor.grants.exchange(raw)
    if fault == 'registration':
        monkeypatch.setattr(f.repository, 'create_from_source', AsyncMock(side_effect=OSError('registration failed')))
    elif fault == 'persistence':
        monkeypatch.setattr(f.publication.artifact_persistence, 'persist_available', AsyncMock(side_effect=OSError('persistence failed')))
    elif fault == 'primary_grant':
        monkeypatch.setattr(f.publication.download_grants, 'issue', AsyncMock(side_effect=OSError('primary grant failed')))
    elif fault == 'editor_grant':
        monkeypatch.setattr(f.publication.editor_grants, 'issue', AsyncMock(side_effect=OSError('editor grant failed')))
    elif fault in {'receipt', 'receipt_identity'}:
        from smart_reporting.reporting.delivery import pdf_native
        original_invoke = pdf_native._invoke
        def faulty_receipt(*args, **kwargs):
            receipt = original_invoke(*args, **kwargs)
            if args[0].get('kind') == 'extractPages':
                if fault == 'receipt':
                    raise OSError('injected after extraction output')
                return {**receipt, 'sha256': '0' * 64, 'pageCount': 999}
            return receipt
        monkeypatch.setattr(pdf_native, '_invoke', faulty_receipt)
    elif fault in {'postwrite', 'missing', 'identity'}:
        original_write = f.workspace.awrite_bytes
        async def write_then_raise(*args, **kwargs):
            if str(args[1]).endswith('/extracted.pdf'):
                if fault != 'missing':
                    await original_write(args[0], args[1], b'foreign bytes' if fault == 'identity' else args[2], **kwargs)
                raise OSError('injected after actual extraction write')
            return await original_write(*args, **kwargs)
        monkeypatch.setattr(f.workspace, 'awrite_bytes', write_then_raise)
    elif fault == 'review':
        from smart_reporting.report_editor import native_pdf_extract
        monkeypatch.setattr(native_pdf_extract, 'read_verified_file', AsyncMock(side_effect=OSError('injected extraction review failure')))
    elif fault.startswith('publication_'):
        from smart_reporting.report_editor import native_pdf_extract, native_publication
        monkeypatch.setattr(native_pdf_extract, 'read_verified_file', AsyncMock(side_effect=OSError('injected extraction review failure')))
        original_read = f.workspace.afile_bytes
        publication_review_started = False
        async def failed_publication_review(*args, **kwargs):
            nonlocal publication_review_started
            publication_review_started = True
            raise OSError('injected publication review failure')
        async def actual_output_read(key, path):
            if publication_review_started and path.endswith('/extracted.pdf'):
                if fault == 'publication_missing':
                    raise OSError('actual publication output unavailable')
                if fault == 'publication_identity':
                    _, metadata = await original_read(key, path)
                    return b'foreign bytes', metadata
            return await original_read(key, path)
        monkeypatch.setattr(native_publication, 'read_verified_file', failed_publication_review)
        monkeypatch.setattr(f.workspace, 'afile_bytes', actual_output_read)
    else:
        from smart_reporting.report_editor import native_pdf_extract
        real_extract = native_pdf_extract.extract_pdf_pages
        def larger_output(source, pages):
            receipt = real_extract(source, pages)
            content = receipt['content'] + b'\n' * (24 * 1024 * 1024)
            return {**receipt, 'content': content, 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
        monkeypatch.setattr(native_pdf_extract, 'extract_pdf_pages', larger_output)
    app = FastAPI()
    app.include_router(create_native_editor_router(f.editor.grants, editor=f.editor, download_service=f.downloads, cookie_secure=False))
    base = f'/reports/v1/native/{f.parent.document_id}/{f.parent.revision}'
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://reports.test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token, path=base)
        response = await client.post(base + '/api/extract-pages',
            headers={'Origin': 'http://reports.test', 'X-CSRF-Token': f.editor.grants.csrf_token(token)},
            json={'requestId': 'extract-fault', 'expectedSha256': f.parent.source_file.sha256, 'pages': [3, 1]})
        if fault in {'missing', 'identity'}:
            assert response.status_code == 403, response.text
            assert response.json()['detail']['code'] == 'native_extract_output_unavailable'
            assert 'artifacts' not in response.json()
            original, _ = await f.workspace.afile_bytes(f.thread, f.original_identity.path)
            assert original == f.original
            return
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['validation']['ok'] is False
        if fault in {'publication_missing', 'publication_identity'}:
            assert 'pdf' not in result['artifacts']
            assert 'native_pdf_identity_unavailable' in {issue['code'] for issue in result['validation']['issues']}
            original, _ = await f.workspace.afile_bytes(f.thread, f.original_identity.path)
            assert original == f.original
            return
        expected = {'registration': 'native_derived_registration_failed', 'persistence': 'native_artifact_persistence_failed',
                    'primary_grant': 'native_download_grant_failed', 'editor_grant': 'native_editor_grant_failed',
                    'oversize': 'native_file_too_large', 'receipt': 'native_pdf_extract_receipt_warning',
                    'receipt_identity': 'native_pdf_extract_receipt_warning',
                    'postwrite': 'native_pdf_extract_postwrite_warning', 'review': 'native_pdf_extract_review_failed',
                    'publication_review': 'native_pdf_identity_review_failed'}[fault]
        assert expected in {issue['code'] for issue in result['validation']['issues']}
        if fault == 'oversize':
            assert result['revisionRegistered'] is False and result.get('editor') is None
        artifact = result['artifacts']['pdf']
        downloaded = await client.get(artifact['downloadUrl'])
        assert downloaded.status_code == 200, downloaded.text
        assert hashlib.sha256(downloaded.content).hexdigest() == artifact['sha256']
        assert len(downloaded.content) == artifact['size']
        assert [page.extract_text().strip() for page in PdfReader(BytesIO(downloaded.content)).pages] == ['source page three', 'source page one']
        original, _ = await f.workspace.afile_bytes(f.thread, f.original_identity.path)
        assert original == f.original


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['context_read', 'context_write', 'revision_reservation', 'download_grant', 'artifact_grant', 'chart_bindings', 'chart_binding_item', 'layout_audit'])
async def test_pptx_editor_http_download_survives_delivery_faults(tmp_path, monkeypatch, fault):
    from smart_reporting.report_editor.service import ReportEditorSession
    from smart_reporting.report_editor.slides import ReportSlidesEditorService
    from smart_reporting.report_editor.slides_api import create_report_slides_editor_router

    runtime, _arguments, scope, durable, artifacts, _grants, _files, _index = await _publication_fixture(tmp_path)
    source = b'original-pptx'
    revised = b'edited-pptx'
    chart_fault = fault in {'chart_bindings', 'chart_binding_item'}
    job = {'jobId': 'job-1'}
    if chart_fault:
        job['pptxChartEdits'] = None if fault == 'chart_bindings' else [{'chartId': 'broken'}]
    await runtime.workspace_service.awrite_bytes(scope.workspace_key, 'reports/source.pptx', source)
    context = ReportEditorContext(
        reportId='report-1', revision=1, jobId='job-1', workflowRunId='workflow-run',
        markdownPath='reports/report.md', job=job, scope=scope.as_state(),
        deliveryFormat='pptx', pptxPath='reports/source.pptx', pptxSize=len(source),
        pptxSha256=hashlib.sha256(source).hexdigest(),
    )
    durable.payload['reportEditorContexts'] = {'1': context.model_dump(mode='json', by_alias=True)}
    session = ReportEditorSession(
        report_id=context.report_id, revision=1, workflow_run_id='workflow-run',
        context_sha256=context.digest(), expires_at=datetime.now(UTC),
        capabilities={'pptx_editor': True},
    )
    service = ReportSlidesEditorService(
        state_repository=runtime.state_repository, workspace_registry=runtime.workspace_registry,
        workspace=runtime.workspace_service, editor_grants=runtime.editor_grants,
        artifact_persistence=runtime.artifact_persistence, download_grants=runtime.download_grants,
        public_base_url='http://reports.test',
    )
    original_get = service.state_repository.get
    reads = 0

    async def get(run_id):
        nonlocal reads
        reads += 1
        if fault == 'context_read' and reads == 2:
            raise OSError('context read failed after file write')
        return await original_get(run_id)

    async def apply_unavailable(*args, **kwargs):
        raise OSError('context write failed')

    original_apply = service.state_repository.apply

    async def reserve_unavailable(run_id, command, **kwargs):
        if command.name == 'reserve_report_editor_revision':
            raise OSError('revision reservation unavailable')
        return await original_apply(run_id, command, **kwargs)

    original_issue = runtime.editor_grants.issue

    async def issue(saved_context, **kwargs):
        if fault == 'download_grant' and kwargs.get('capabilities', {}).get('pptx_download'):
            raise OSError('editor download grant unavailable')
        return await original_issue(saved_context, **kwargs)

    async def artifact_issue_unavailable(**kwargs):
        raise OSError('artifact grant unavailable')

    monkeypatch.setattr(service.state_repository, 'get', get)
    if fault == 'context_write':
        monkeypatch.setattr(service.state_repository, 'apply', apply_unavailable)
    elif fault == 'revision_reservation':
        monkeypatch.setattr(service.state_repository, 'apply', reserve_unavailable)
    monkeypatch.setattr(runtime.editor_grants, 'issue', issue)
    if fault == 'artifact_grant':
        monkeypatch.setattr(runtime.download_grants, 'issue', artifact_issue_unavailable)
    audit_issues = [{'page': 0, 'message': 'PPTX layout audit failed: injected'}] if fault == 'layout_audit' else []
    monkeypatch.setattr(service, '_run_engine', lambda *_args, **_kwargs: {'bytes': revised, 'issues': audit_issues})
    monkeypatch.setattr(service, '_render_pdf', lambda _bytes: b'%PDF-preview')
    if chart_fault:
        monkeypatch.setattr(
            'smart_reporting.report_editor.slides_chart_ai.replace_pptx_pictures',
            lambda content, replacements: content,
        )
    result = await service.save_revision(
        session, {'expectedSha256': context.pptx_sha256},
        chart_replacements=[{'slidePath': 'ppt/slides/slide1.xml', 'shapeId': 2, 'binding': {}}]
        if chart_fault else None,
    )
    assert result['pptx']['sha256'] == hashlib.sha256(revised).hexdigest()
    if fault == 'revision_reservation':
        assert any(issue['code'] == 'report_editor_revision_lookup_failed' for issue in result['validation']['issues'])
    if fault != 'artifact_grant':
        assert result['validation']['ok'] is False
        assert result['validation']['issues']
    if chart_fault:
        assert any(issue['code'] == 'report_slides_chart_bindings_invalid' for issue in result['validation']['issues'])
    if fault == 'layout_audit':
        assert any(issue['code'] == 'pptx_layout_audit' and 'injected' in issue['message']
                   for issue in result['validation']['issues'])
    app = FastAPI()
    app.include_router(create_report_slides_editor_router(
        runtime.editor_grants, slides=service, static_dir=tmp_path, cookie_secure=False,
    ))
    app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        response = await client.get(result['pptx']['downloadUrl'])
    assert response.status_code == 200
    assert response.content == revised
    assert response.headers['content-type'].startswith('application/vnd.openxmlformats-officedocument.presentationml.presentation')


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
            if command.name == "reserve_report_editor_revision":
                known = [int(key) for key in durable.payload.get("reportEditorContexts", {}) if str(key).isdigit()]
                durable.payload["reportEditorRevisionCounter"] = max([
                    command.payload["minimumRevision"], durable.payload.get("reportEditorRevisionCounter", 0), *known,
                ]) + 1
                durable.state_version += 1
                return SimpleNamespace(state=durable)
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
@pytest.mark.parametrize("fault", ["state", "evaluate", "chart_evaluate", "table_evaluate", "semantic_evaluate", "heading_projection", "standard_proof_sources", "overview_evaluate", "runtime_state", "quality_source_selection", "write", "read"])
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
    elif fault == "heading_projection":
        from smart_reporting.reporting.trace import claim_semantics

        def fail(*_args, **_kwargs):
            raise RuntimeError("injected semantic heading projection failure")
        monkeypatch.setattr(claim_semantics, "project_semantic_headings", fail)
    elif fault == "standard_proof_sources":
        from smart_reporting.reporting.trace import chart_quality

        def fail(*_args, **_kwargs):
            raise RuntimeError("injected standard chart proof dependency failure")
        monkeypatch.setattr(chart_quality, "standard_proof_source_ids", fail)
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
async def test_http_pptx_download_survives_generated_artifact_audit_exception(tmp_path, monkeypatch):
    from dataclasses import replace

    from smart_reporting.reporting.contract import ReportPeriod
    from smart_reporting.reporting.delivery import pptx as pptx_module
    from smart_reporting.reporting.hospital_operation.outline import ReportOutline
    from smart_reporting.reporting.tests.narrative_helpers import finding, graph
    from smart_reporting.reporting.tests.test_dynamic_checkpoint import _coverage
    from smart_reporting.reporting.workflow.checkpoint import (
        AnalysisDatasetSemantics,
        AnalysisEvidence,
        AnalysisEvidenceManifest,
        FileIdentity,
        ReportingCheckpoint,
    )
    from smart_reporting.reporting.workflow.runtime.slides import build_slide_outline

    runtime, arguments, scope, durable, artifacts, _, _, _ = await _publication_fixture(tmp_path)
    source = graph(finding())
    evidence = AnalysisEvidenceManifest(
        evidence=(AnalysisEvidence(
            analysisId="analysis_001", summary="收入同比增长5%", datasetIds=("dataset-1",),
            evidenceFiles=(FileIdentity(path="facts.json", size=1, sha256="a" * 64),),
            citationIds=("citation_001",),
        ),),
        datasetSemantics=(AnalysisDatasetSemantics(
            datasetId="dataset-1", rowGrain="month", duplicateResolution="not_applicable",
        ),),
    )
    outline = ReportOutline.model_validate({
        "reportType": "topic", "title": "医院运营分析",
        "sections": [{"code": "section_001", "sectionNumber": "1", "title": "分析",
                      "analysisIds": ["analysis_001"]}],
    })
    planned = build_slide_outline(source, evidence, title=outline.title)

    async def write_model(path, model):
        content = model.model_dump_json(by_alias=True).encode()
        await runtime.workspace_service.awrite_bytes(scope.workspace_key, path, content)
        return FileIdentity(path=path, size=len(content), sha256=hashlib.sha256(content).hexdigest())

    checkpoint = ReportingCheckpoint(
        revision=2, phase="analysis", outlineHash="a" * 64, profileCoverage=_coverage(),
        evidenceManifest=evidence, findingGraphHash=source.snapshot_hash,
        findingGraphFile=await write_model("reports/findings.json", source),
        slideOutlineFile=await write_model("reports/slides.json", planned),
    )
    durable.payload["workflowCheckpoint"] = checkpoint.model_dump(mode="json", by_alias=True)
    runtime._scope = lambda _context: scope.as_state()
    runtime._envelope = lambda _context: SimpleNamespace(
        period=ReportPeriod(start="2025-01-01", end="2025-12-31")
    )
    runtime._apply_durable_command = AsyncMock()
    original_build = pptx_module.build_editable_pptx

    def audit_exception(**kwargs):
        built = original_build(**kwargs)
        return replace(built, issues=({"page": 0, "message": "PPTX layout audit failed: injected"},))

    monkeypatch.setattr(publication_module, "build_editable_pptx", audit_exception)
    content = {key: value for key, value in arguments["output"].items()
               if key not in {"artifactManifest", "pdfPath", "pdfSize", "pdfSha256",
                              "wordPath", "wordSize", "wordSha256"}}
    context = RunContext(run_id="workflow-run", session_id="workflow-session", session_state={
        "report_request_context": {"deliveryFormat": "pptx"},
    })
    rendered = await runtime._render_pptx(context, content, outline)
    assert rendered["validation"]["ok"] is False
    assert rendered["validation"]["issues"][0]["message"] == "PPTX layout audit failed: injected"
    result = await runtime.issue_http_publication(**{**arguments, "output": rendered})
    assert result["validation"]["ok"] is False
    assert result["pptx"]["downloadUrl"]
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        response = await client.get(result["pptx"]["downloadUrl"])
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == rendered["pptxSha256"]
    assert len(response.content) == rendered["pptxSize"]


@pytest.mark.anyio
async def test_http_pptx_publication_keeps_link_when_layout_audit_fails(monkeypatch):
    pptx = b"pptx bytes"
    digest = hashlib.sha256(pptx).hexdigest()
    expires = datetime.now(UTC)
    captured = {}

    class Workspace:
        async def ahash_file(self, thread_id, path):
            return {"path": path, "size": len(pptx), "sha256": digest}

    class Persistence:
        async def persist_available(self, **values):
            captured["artifacts"] = values["artifacts"]
            return values["artifacts"]

    class Grants:
        async def issue(self, **values):
            captured["grant"] = values
            return "pptx-token", SimpleNamespace(
                pptx_path=values["pptx_path"],
                pptx_size=values["pptx_size"],
                pptx_sha256=values["pptx_sha256"],
                xlsx_path="",
                pdf_path="",
                word_path="",
                expires_at=expires,
            )

    class EditorGrants:
        async def issue(self, context, *, capabilities):
            captured["editor_context"] = context
            captured["editor_capabilities"] = capabilities
            return "slides-token", expires

    class StateRepository:
        async def get(self, _run_id):
            return SimpleNamespace(payload={}, state_version=3)

        async def apply(self, _run_id, command, *, expected_version):
            captured["editor_command"] = command
            captured["editor_expected_version"] = expected_version

    monkeypatch.setattr(
        planning_module,
        "resolve_reporting_workflow_scope",
        lambda **_kwargs: SimpleNamespace(
            database="db",
            company_id="company",
            caller_thread_id="caller",
            as_state=lambda: {"database": "db", "companyId": "company"},
        ),
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = Workspace()
    runtime.artifact_persistence = Persistence()
    runtime.download_grants = Grants()
    runtime.editor_grants = EditorGrants()
    runtime.state_repository = StateRepository()
    runtime._release_workspace = lambda _thread_id: None
    output = await runtime._issue_http_pptx_publication(
        thread_id="workspace",
        caller_thread_id="caller",
        user_id="user",
        workflow_session_id="session",
        workflow_run_id="run",
        dependencies=None,
        base_url="https://reports.test",
        content={
            "reportId": "report-pptx",
            "revision": 1,
            "jobId": "job-pptx",
            "editorJob": {"jobId": "job-pptx"},
            "markdownPath": "reports/report.md",
            "pptxPath": "reports/board.pptx",
            "pptxSize": len(pptx),
            "pptxSha256": digest,
            "validation": {"ok": False, "issues": [{"code": "pptx_layout_audit"}]},
            "validationIssues": [{"code": "pptx_layout_audit", "message": "版式溢出"}],
            "publicationGate": {"formalReleaseAllowed": False, "issues": [{"code": "quality_audit_failed"}]},
        },
    )

    assert captured["artifacts"] == (
        ReportArtifactSpec(artifact="pptx", path="reports/board.pptx", size=len(pptx), sha256=digest),
    )
    assert output["pptx"]["downloadUrl"] == "https://reports.test/reports/v1/download/pptx-token/pptx"
    assert output["editor"]["openUrl"] == "https://reports.test/reports/v1/slides/open/slides-token"
    assert captured["editor_capabilities"] == {"pptx_editor": True}
    assert captured["editor_context"].pptx_path == "reports/board.pptx"
    assert output["validation"]["ok"] is False
    assert output["validationIssues"][0]["code"] == "pptx_layout_audit"
    assert output["publicationGate"]["formalReleaseAllowed"] is False


@pytest.mark.anyio
async def test_http_pptx_publication_falls_back_to_verified_editor_download_on_persistence_failure(monkeypatch):
    pptx = b"pptx bytes"
    digest = hashlib.sha256(pptx).hexdigest()
    expires = datetime.now(UTC)
    issued_capabilities: list[dict[str, bool]] = []

    class Workspace:
        async def ahash_file(self, _thread_id, _path):
            return {"missing": False, "size": len(pptx), "sha256": digest}

    class Persistence:
        async def persist_available(self, **_values):
            raise OSError("storage unavailable")

    class Grants:
        async def issue(self, **_values):
            raise AssertionError("普通产物授权不应在持久化失败时签发")

    class EditorGrants:
        async def issue(self, _context, *, capabilities: dict[str, bool]):
            issued_capabilities.append(capabilities)
            return (
                "slides-download-token" if capabilities.get("pptx_download") else "slides-editor-token",
                expires,
            )

    class StateRepository:
        async def get(self, _run_id):
            return SimpleNamespace(payload={}, state_version=3)

        async def apply(self, _run_id, _command, *, expected_version):
            assert expected_version == 3

    monkeypatch.setattr(
        planning_module,
        "resolve_reporting_workflow_scope",
        lambda **_kwargs: SimpleNamespace(
            database="db",
            company_id="company",
            caller_thread_id="caller",
            as_state=lambda: {
                "database": "db",
                "companyId": "company",
                "userId": "user",
                "sessionId": "session",
                "callerThreadId": "caller",
                "threadId": "workspace",
            },
        ),
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = Workspace()
    runtime.artifact_persistence = Persistence()
    runtime.download_grants = Grants()
    runtime.editor_grants = EditorGrants()
    runtime.state_repository = StateRepository()
    runtime._release_workspace = lambda _thread_id: None
    output = await runtime._issue_http_pptx_publication(
        thread_id="workspace",
        caller_thread_id="caller",
        user_id="user",
        workflow_session_id="session",
        workflow_run_id="run",
        dependencies=None,
        base_url="https://reports.test",
        content={
            "reportId": "report-pptx",
            "revision": 1,
            "jobId": "job-pptx",
            "editorJob": {"jobId": "job-pptx"},
            "markdownPath": "reports/report.md",
            "pptxPath": "reports/board.pptx",
            "pptxSize": len(pptx),
            "pptxSha256": digest,
            "validation": {"ok": True, "issues": []},
            "publicationGate": {"formalReleaseAllowed": True, "issues": []},
        },
    )

    assert output["pptx"]["downloadUrl"] == (
        "https://reports.test/reports/v1/slides/download/slides-download-token"
    )
    assert output['editor']['openUrl'] == (
        'https://reports.test/reports/v1/slides/open/slides-editor-token'
    )
    assert output["publicationGate"]["formalReleaseAllowed"] is False
    assert output["publicationIssues"][0]["code"] == "report_pptx_persistence_failed"
    assert {item.get("pptx_download", False) for item in issued_capabilities} == {False, True}


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
        tmp_path, "l2_plot_changed", "paginated_reedit", []
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_publication_keeps_links_when_legacy_template_binding_recovery_fails(tmp_path):
    """旧报告模板回溯故障：丢弃对应追溯，已生成成品仍照常签发。"""
    from smart_reporting.reporting.tests.test_report_editor_lineage_export import (
        test_export_revision_registers_l2_chart_edit_plot_data,
    )

    await test_export_revision_registers_l2_chart_edit_plot_data(
        tmp_path, "template_binding_failed", "legacy_template", []
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_publication_keeps_lineage_and_links_when_chart_continuation_fails(tmp_path):
    """继续编辑侧车写入失败不能丢弃正式追溯或阻断 PDF/Word 下载。"""
    from smart_reporting.reporting.tests.test_report_editor_lineage_export import (
        test_export_revision_registers_l2_chart_edit_plot_data,
    )

    await test_export_revision_registers_l2_chart_edit_plot_data(
        tmp_path, "continuation_failed", "paginated_reedit", []
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
async def test_chart_fact_binding_failure_preserves_index_and_http_downloads(tmp_path, monkeypatch):
    from smart_reporting.reporting.tests.test_report_editor_chart_ai import _png_bytes
    from smart_reporting.reporting.trace import chart_facts
    from smart_reporting.reporting.trace.contracts_v1 import ChartTraceV1, TraceFileRefV1

    runtime, arguments, scope, _, artifacts, _, files, index = await _publication_fixture(tmp_path)
    sources = {"reports/chart.png": _png_bytes(),
        "reports/chart-input.json": b'{"schema":"chart-input/v1","chartId":"chart_001"}'}
    refs = []
    for path, raw in sources.items():
        await runtime.workspace_service.awrite_bytes(scope.workspace_key, path, raw)
        refs.append(TraceFileRefV1(resourceId=derive_resource_id(path), path=path, size=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            mediaType="image/png" if path.endswith(".png") else "application/json"))
    chart = ChartTraceV1(chartId="chart_001", imageFileResourceId=refs[0].resource_id,
        plotDataFileResourceIds=(refs[1].resource_id,), datasetIds=(index.datasets[0].dataset_id,))
    index = index.model_copy(update={"files": (*index.files, *refs), "chart_traces": (chart,)})
    state = {}
    runtime._scope = lambda _: scope.as_state()
    runtime._state = lambda _: state
    runtime._profile = lambda _: SimpleNamespace(effective_profile_hash="a" * 64)
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    monkeypatch.setattr(publication_module, "build_csv_trace_index", lambda **_: index)
    fail = AsyncMock(side_effect=RuntimeError("injected chart fact binding failure"))
    monkeypatch.setattr(chart_facts, "recover_chart_fact_refs", fail)
    identity = await runtime._write_trace_index("reports/report.manifest.json", handles=(), lineage=(),
        markdown_artifact=_identity("reports/report.md", files["reports/report.md"], "text/markdown"),
        revision=1, run_context=SimpleNamespace(run_id="report-1"))
    fail.assert_awaited_once()
    saved = RevisionTraceIndexV1.model_validate_json(await runtime.workspace_service.read_limited_regular_file(
        scope.workspace_key, identity.path, max_bytes=identity.size))
    assert saved.chart_traces[0].fact_refs == ()
    assert state["report_quality_issues"][0]["code"] == "chart_fact_binding_unavailable"
    manifest = await register_trace_manifest(runtime.workspace_service, scope.workspace_key, saved, overwrite=True)
    arguments["output"]["artifactManifest"] = manifest.model_dump(mode="json", by_alias=True)
    result = await runtime.issue_http_publication(**arguments)
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        for kind, suffix in (("pdf", "pdf"), ("word", "docx")):
            response = await client.get(result[kind]["downloadUrl"])
            assert response.status_code == 200
            assert response.content == files[f"reports/report.{suffix}"]


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


@pytest.mark.anyio
@pytest.mark.parametrize("delivery_format", ["pptx", "xlsx"])
@pytest.mark.parametrize("fault", ["persistence", "empty_persistence", "context_build", "context_read", "context_write", "editor_grant"])
async def test_office_publication_faults_retain_verified_downloads(
    tmp_path, monkeypatch, delivery_format, fault,
):
    runtime, arguments, scope, _, artifacts, _, _, _ = await _publication_fixture(tmp_path)
    content = b"PK office-report"
    path = f"reports/report.{delivery_format}"
    await runtime.workspace_service.awrite_bytes(scope.workspace_key, path, content)
    output = arguments["output"]
    output["deliveryFormat"] = delivery_format
    output.update({
        f"{delivery_format}Path": path,
        f"{delivery_format}Size": len(content),
        f"{delivery_format}Sha256": hashlib.sha256(content).hexdigest(),
        "validation": {"ok": False, "issues": [{"code": "source_needs_review"}]},
        "validationIssues": [{"code": "source_needs_review"}],
    })
    if fault == "persistence":
        monkeypatch.setattr(runtime.artifact_persistence, "persist_available", AsyncMock(side_effect=OSError("storage unavailable")))
    elif fault == "empty_persistence":
        monkeypatch.setattr(runtime.artifact_persistence, "persist_available", AsyncMock(return_value=()))
    elif fault == "context_build":
        monkeypatch.setattr(planning_module, "ReportEditorContext", lambda **_: (_ for _ in ()).throw(ValueError("context unavailable")))
    elif fault == "context_read":
        monkeypatch.setattr(runtime.state_repository, "get", AsyncMock(side_effect=OSError("state unavailable")))
    elif fault == "context_write":
        monkeypatch.setattr(runtime.state_repository, "apply", AsyncMock(side_effect=OSError("state unavailable")))
    else:
        monkeypatch.setattr(runtime.editor_grants, "issue", AsyncMock(side_effect=OSError("grant unavailable")))

    result = await runtime.issue_http_publication(**arguments)

    assert result[delivery_format]["downloadUrl"]
    assert result["validation"]["ok"] is False
    assert result["publicationGate"]["formalReleaseAllowed"] is False
    assert result["publicationIssues"]
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(
        runtime.download_grants, artifacts, workspace_service=runtime.workspace_service,
    )))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        response = await client.get(result[delivery_format]["downloadUrl"])
    assert response.status_code == 200
    assert response.content == content


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["source_mapping", "source_marking", "inspection", "revision_lookup", "revision_reservation", "persistence", "context_write", "editor_grant"])
async def test_workbook_editor_save_faults_keep_verified_downloads(tmp_path, monkeypatch, fault):
    from smart_reporting.report_editor import workbook as workbook_module
    from smart_reporting.reporting.tests.test_workbook_editor import _bytes

    runtime, _, scope, durable, artifacts, _, _, _ = await _publication_fixture(tmp_path)
    source = _bytes(12)
    source_path = "reports/editable.xlsx"
    await runtime.workspace_service.awrite_bytes(scope.workspace_key, source_path, source)
    context = ReportEditorContext(
        reportId="report-1", revision=2, jobId="job-1", workflowRunId="workflow-run",
        markdownPath="reports/report.md", job={"jobId": "job-1", "validation": {"ok": False}},
        scope=scope.as_state(), deliveryFormat="xlsx", xlsxPath=source_path,
        xlsxSize=len(source), xlsxSha256=hashlib.sha256(source).hexdigest(),
    )
    editor = workbook_module.ReportWorkbookEditorService(
        state_repository=runtime.state_repository, workspace_registry=runtime.workspace_registry,
        workspace=runtime.workspace_service, editor_grants=runtime.editor_grants,
        artifact_persistence=runtime.artifact_persistence, download_grants=runtime.download_grants,
        public_base_url="http://reports.test",
    )
    editor.context_for_session = AsyncMock(return_value=context)
    def failed():
        return AsyncMock(side_effect=OSError("injected workbook delivery failure"))
    if fault == "source_mapping":
        monkeypatch.setattr(editor, "_source_mapping", lambda *_: (_ for _ in ()).throw(ValueError("mapping unavailable")))
    elif fault == "source_marking":
        monkeypatch.setattr(editor, "_source_mapping", lambda *_: {"sources": {"cells": []}})
        monkeypatch.setattr(editor, "_mark_sources_unverified", lambda *_: (_ for _ in ()).throw(ValueError("mapping write unavailable")))
    elif fault == "inspection":
        monkeypatch.setattr(workbook_module, "inspect_workbook", lambda *_: (_ for _ in ()).throw(ValueError("inspection unavailable")))
    elif fault == "revision_lookup":
        monkeypatch.setattr(runtime.state_repository, "get", failed())
    elif fault == "revision_reservation":
        original_apply = runtime.state_repository.apply

        async def reserve_unavailable(run_id, command, **kwargs):
            if command.name == "reserve_report_editor_revision":
                raise OSError("revision reservation unavailable")
            return await original_apply(run_id, command, **kwargs)

        monkeypatch.setattr(runtime.state_repository, "apply", reserve_unavailable)
    elif fault == "persistence":
        monkeypatch.setattr(runtime.artifact_persistence, "persist_available", failed())
    elif fault == "context_write":
        monkeypatch.setattr(runtime.state_repository, "apply", failed())
    else:
        monkeypatch.setattr(runtime.editor_grants, "issue", failed())

    result = await editor.save_revision(None, {"expectedSha256": context.xlsx_sha256,
        "operations": [{"kind": "applyCellEdits", "edits": [{"sheetName": "汇总", "row": 0,
            "column": 0, "writeValue": True, "cell": {"value": 99}}]}]})

    assert result["xlsx"]["downloadUrl"]
    if fault == "revision_reservation":
        assert any(issue["code"] == "report_editor_revision_lookup_failed" for issue in result["validation"]["issues"])
    assert result["validation"]["ok"] is False
    assert result["validation"]["issues"]
    assert (await runtime.workspace_service.afile_bytes(scope.workspace_key, source_path))[0] == source
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(
        runtime.download_grants, artifacts, workspace_service=runtime.workspace_service,
    )))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        response = await client.get(result["xlsx"]["downloadUrl"])
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == result["xlsx"]["sha256"]


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('fault', [None, 'record', 'manifest', 'validation', 'persistence', 'office_postwrite'])
async def test_data_export_service_keeps_downloads_and_registers_common_revision(tmp_path, monkeypatch, fault, anyio_backend):
    from smart_reporting.report_editor import data_revision_exports as module
    from smart_reporting.reporting.delivery import office_engine
    from smart_reporting.reporting.delivery.publishing import ReportDownloadScope
    from smart_reporting.reporting.tests.test_report_data_revision_service import service_case

    async def run_local(func, **kwargs):
        return func(**kwargs)

    monkeypatch.setattr(office_engine, 'run_office_engine', run_local)

    service, context, repository, files, editor = service_case()
    context.scope.update(database='test', companyId='company-1', sessionId='session-1')
    # 编辑上下文的摘要受作用域影响；内存恢复器及状态均共享该已授权上下文。
    repository.state.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    snapshot = await service.freeze(context)
    editor.workspace_registry.get = lambda thread: SimpleNamespace(root=tmp_path)
    grants = InMemoryDownloadGrantRepository()
    artifacts = InMemoryReportArtifactRepository()

    async def chunks(thread, path, **kwargs):
        yield files[path]

    async def read_regular(thread, path, **kwargs):
        return files[path]

    editor.workspace.aiter_regular_file_chunks = chunks
    editor.workspace.read_limited_regular_file = read_regular
    editor.workspace.normalize_path = ReportingWorkspaceRouter.normalize_path
    editor.artifact_persistence = ReportArtifactPersistenceService(artifacts, editor.workspace)
    if fault == 'persistence':
        async def fail_persist(**kwargs):
            raise RuntimeError('persistence unavailable')
        editor.artifact_persistence.persist_available = fail_persist
    editor.download_grants = ReportDownloadGrantService(grants)
    editor.public_base_url = 'http://test'
    old_token, _ = await editor.download_grants.issue(
        scope=ReportDownloadScope('test', 'user-1', 'company-1', 'session-1', 'thread-1', context.workflow_run_id),
        report_id=context.report_id, revision=1, pdf_path='reports/original.pdf',
        pdf_size=1, pdf_sha256='a' * 64,
    )
    original_apply = repository.apply

    async def apply(run_id, command, **kwargs):
        if fault == 'record' and command.name == 'record_report_data_export':
            raise RuntimeError('record unavailable')
        return await original_apply(run_id, command, **kwargs)

    repository.apply = apply
    original_write = editor.workspace.awrite_bytes

    async def write(thread, path, raw, **kwargs):
        if fault == 'manifest' and path.endswith('/export-manifest.json'):
            raise RuntimeError('manifest unavailable')
        return await original_write(thread, path, raw, **kwargs)

    editor.workspace.awrite_bytes = write

    def render(**kwargs):
        refs = {}
        for label, suffix in [('pdf', 'pdf'), ('word', 'docx'), ('pptx', 'pptx'), ('xlsx', 'xlsx')]:
            raw = f'{label} snapshot={snapshot["snapshotId"]}'.encode()
            path = kwargs['output_root'] + '/report.' + suffix
            files[path] = raw
            refs[label] = {'path': path, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        return {'snapshotId': snapshot['snapshotId'],
            'chartRevisions': {key: chart['chartRevision'] for key, chart in snapshot['charts'].items()},
            'artifacts': refs, 'validation': {'ok': fault != 'validation', 'issues': [
                {'code': 'test_validation_failed', 'message': '验收失败'}
            ] if fault == 'validation' else []}}

    monkeypatch.setattr(module, 'render_data_revision_formats', render)
    if fault == 'office_postwrite':
        render_formats = module.render_data_revision_formats
        def office_postwrite(**kwargs):
            result = render_formats(**kwargs)
            result['validation'] = {'ok': False, 'issues': [
                {'code': 'report_data_pptx_render_failed', 'message': 'PPTX写入后回执失败，保留实际文件。'},
                {'code': 'report_data_xlsx_render_failed', 'message': 'XLSX写入后回执失败，保留实际文件。'},
            ]}
            return result
        monkeypatch.setattr(module, 'render_data_revision_formats', office_postwrite)
    first = await service.export(context, snapshot['snapshotId'])
    second = await service.export(context, snapshot['snapshotId'])
    assert first['snapshotId'] == second['snapshotId'] == snapshot['snapshotId']
    assert first['exportId'] != second['exportId']
    assert second['revision'] > first['revision']
    assert all(first[label]['downloadUrl'].startswith('http://test/reports/v1/download/') for label in ['pdf', 'word', 'pptx', 'xlsx'])
    assert all('path' not in first[label] for label in ['pdf', 'word', 'pptx', 'xlsx'])
    assert len(artifacts.records) == (0 if fault == 'persistence' else 8)
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(
        editor.download_grants, artifacts, workspace_service=editor.workspace,
    )))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for label in ['pdf', 'word', 'pptx', 'xlsx']:
            response = await client.get(first[label]['downloadUrl'])
            assert response.status_code == 200
            assert response.content == f'{label} snapshot={snapshot["snapshotId"]}'.encode()
    assert (await editor.download_grants.lookup(old_token)).revision == 1
    first_token = first['pdf']['downloadUrl'].rsplit('/', 1)[-1]
    assert (await editor.download_grants.lookup(first_token)).revision == first['revision']
    assert await service.read(context, snapshot['snapshotId']) == snapshot
    if fault:
        assert first['validation']['ok'] is False and first['validation']['issues']
    if fault not in {'record', 'manifest'}:
        history = (await service._history(context))['exports']
        assert set(history) == {first['exportId'], second['exportId']}
        manifest = json.loads(files[history[first['exportId']]['manifest']['path']])
        assert manifest['snapshotId'] == snapshot['snapshotId']
        assert manifest['chartRevisions'] == first['chartRevisions']
        assert set(manifest['artifacts']) == {'pdf', 'word', 'pptx', 'xlsx'}


@pytest.mark.anyio
@pytest.mark.parametrize('edit_kind',['insert','styledReplace','selectionRuns','styledMarkup','styledMarkupWriterFault','styledDrawing','styledDrawingWriterFault','styledVector','styledVectorWriterFault','styledPng','styledPngWriterFault','styledLink','styledInternalLink','styledLinkWriterFault','styledMeasure','styledCaret','styledMeasureWriterFault','styledMeasureBounds'])
async def test_static_text_postwrite_review_warning_keeps_verified_http_download(tmp_path, monkeypatch, edit_kind):
    """静态文字输出复核故障登记：已生成字节保留 HTTP 下载。"""
    from io import BytesIO
    from pypdf import PdfReader
    from pypdf.generic import NullObject
    from smart_reporting.report_editor import native_publication
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE, create_native_editor_router
    from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture
    editor, context, _, downloads = await fixture(tmp_path)
    operations = [{'kind': 'insertText', 'sourceSha256': context.source_file.sha256,
        'pageId': f'sha256:{context.source_file.sha256}:page:0', 'origin': [50, 180],
        'text': 'RETAINED INSERT', 'fontSize': 12, 'color': [0, 0, 0], 'align': 'left'}]
    if edit_kind in {'styledReplace','selectionRuns','styledMarkup','styledMarkupWriterFault','styledDrawing','styledDrawingWriterFault','styledVector','styledVectorWriterFault','styledPng','styledPngWriterFault','styledLink','styledInternalLink','styledLinkWriterFault','styledMeasure','styledCaret','styledMeasureWriterFault','styledMeasureBounds'}:
        from smart_reporting.reporting.tests.test_pdf_native_text_edits import text_operation
        operations=[{**text_operation(await editor.read_file(context),'RETAINED INSERT'),
            'sourceSha256':context.source_file.sha256,**({'styleRuns':[{'start':0,'end':15,'bold':True}]} if edit_kind=='selectionRuns' else {'font':'times','bold':True,'italic':True,'fontSize':14})}]
    if edit_kind in {'styledMarkup','styledMarkupWriterFault'}:
        operations.insert(0,{'kind':'addMarkup','pageId':operations[0]['pageId'],
            'markupType':'underline','quads':[[30,174,160,174,30,158,160,158]],
            'color':[0.2,0.4,0.6]})
    if edit_kind in {'styledDrawing','styledDrawingWriterFault'}:
        operations.insert(0,{'kind':'addDrawing','pageId':operations[0]['pageId'],
            'shape':'rect','rect':[25,150,170,185],'color':[0.2,0.4,0.6],
            'width':2})
    if edit_kind in {'styledVector','styledVectorWriterFault'}:
        operations.insert(0,{'kind':'addDrawing','pageId':operations[0]['pageId'],
            'shape':'arrow','from':[25,150],'to':[170,185],'color':[0.2,0.4,0.6],
            'width':2})
    if edit_kind in {'styledPng','styledPngWriterFault'}:
        operations.insert(0,{'kind':'addDrawing','pageId':operations[0]['pageId'],
            'shape':'image','rect':[25,100,125,140],'image':'iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAYAAAD0In+KAAAAEUlEQVR4nGP4z8Dwn+E/QwMAEHkDfiHA/Y0AAAAASUVORK5CYII=',
            'color':[0,0,0],'width':1})
    if edit_kind in {'styledLink','styledInternalLink','styledLinkWriterFault'}:
        operations.insert(0,{'kind':'addDrawing','pageId':operations[0]['pageId'],
            'shape':'link','rect':[25,100,125,140],'color':[0,0,0],'width':1,
            **({'destPage':1} if edit_kind=='styledInternalLink' else {'url':'https://example.com/report?pdf=1#section'})})
    if edit_kind in {'styledMeasure','styledMeasureWriterFault','styledCaret','styledMeasureBounds'}:
        operations.insert(0,{'kind':'addDrawing','pageId':operations[0]['pageId'],
            'shape':'caret' if edit_kind=='styledCaret' else 'measure',
            **({'point':[180,120]} if edit_kind=='styledCaret' else {'from':[25,100],'to':[27,100],'label':'W'*24} if edit_kind=='styledMeasureBounds' else {'from':[25,100],'to':[170,160],'label':'145 pt'}),
            'color':[0.2,0.4,0.6],'width':2})
    def check_measure_caret(content):
        expected='/Caret' if edit_kind=='styledCaret' else '/Line'
        annotation=next(ref.get_object() for ref in PdfReader(BytesIO(content)).pages[0]['/Annots']
            if ref.get_object()['/Subtype']==expected)
        assert annotation['/AP']['/N'].get_data()
        if edit_kind=='styledMeasureBounds':
            assert list(annotation['/L'])==[25,100,27,100] and annotation['/Contents']=='W'*24
            rect=list(annotation['/Rect'])
            assert rect[2]>230 and rect[3]>114
            assert list(annotation['/AP']['/N']['/BBox'])==rect
        elif edit_kind=='styledMeasure':
            assert list(annotation['/L'])==[25,100,170,160]
            assert annotation['/Contents']=='145 pt'
        else:
            assert list(annotation['/Rect'])==[170,110,190,130]
    def check_link(content):
        reader=PdfReader(BytesIO(content))
        link=next(ref.get_object() for ref in reader.pages[0]['/Annots']
            if ref.get_object()['/Subtype']=='/Link')
        assert list(link['/Rect'])==[25,100,125,140]
        assert not {'/AP','/AA','/Next'} & set(link)
        if edit_kind=='styledInternalLink':
            destination=link['/Dest']
            assert destination[0]==reader.pages[0].indirect_reference
            assert str(destination[1])=='/XYZ' and all(isinstance(value,NullObject) for value in destination[2:])
            assert '/A' not in link
        else:
            assert link['/A']['/S']=='/URI'
            assert link['/A']['/URI']=='https://example.com/report?pdf=1#section'
            assert set(link['/A'])=={'/Type','/S','/URI'}
    original = native_publication.patch_pdf_with_receipt
    def review_warning(content, ops):
        # 模拟第二阶段批注/绘图写入失败，保留第一阶段真实改字字节。
        writer_fault = edit_kind in {'styledMarkupWriterFault','styledDrawingWriterFault','styledVectorWriterFault','styledPngWriterFault','styledLinkWriterFault','styledMeasureWriterFault'}
        result = original(content, ops[1:] if writer_fault else ops)
        assert 'RETAINED INSERT' in PdfReader(BytesIO(result['content'])).pages[0].extract_text()
        if edit_kind=='styledMarkup':
            annotations=PdfReader(BytesIO(result['content'])).pages[0]['/Annots']
            assert any(ref.get_object()['/Subtype']=='/Underline' for ref in annotations)
        if edit_kind=='styledDrawing':
            annotations=PdfReader(BytesIO(result['content'])).pages[0]['/Annots']
            assert any(ref.get_object()['/Subtype']=='/Square' for ref in annotations)
        if edit_kind=='styledVector':
            annotation=next(ref.get_object() for ref in PdfReader(BytesIO(result['content'])).pages[0]['/Annots']
                if ref.get_object()['/Subtype']=='/Line')
            assert list(annotation['/L'])==[25,150,170,185]
            assert annotation['/AP']['/N'].get_data()
        if edit_kind=='styledPng':
            stamp=next(ref.get_object() for ref in PdfReader(BytesIO(result['content'])).pages[0]['/Annots']
                if ref.get_object()['/Subtype']=='/Stamp')
            image=stamp['/AP']['/N']['/Resources']['/XObject']['/Im0']
            assert list(stamp['/Rect'])==[25,100,125,140]
            assert image['/Width']==2 and image['/Height']==1
            assert image.get_data()==bytes([255,0,0,0,255,0])
            assert image['/SMask'].get_data()==bytes([255,128])
        if edit_kind in {'styledMeasure','styledCaret','styledMeasureBounds'}:
            check_measure_caret(result['content'])
        if edit_kind in {'styledLink','styledInternalLink'}:
            check_link(result['content'])
        return {**result, 'appliedOperationIndices': [1] if writer_fault else [],
            'skippedOperations': [{'operationIndex': 0, 'kind': operations[0]['kind'],
            'reason': (('pdf_text_drawing_writer_failed_generated_bytes_retained: injected readback fault'
                if edit_kind in {'styledDrawingWriterFault','styledVectorWriterFault','styledPngWriterFault','styledLinkWriterFault','styledMeasureWriterFault'} else 'pdf_text_markup_writer_failed_generated_bytes_retained: injected readback fault')
                if writer_fault else 'pdf_text_output_review_failed: injected readback fault')}]}
    monkeypatch.setattr(native_publication, 'patch_pdf_with_receipt', review_warning)
    preview = review_warning(await editor.read_file(context), operations)
    editor.context_for_session = AsyncMock(return_value=context)
    grants = editor.grants
    raw, _ = await grants.issue(context, capabilities=editor.capabilities(context))
    token, _ = await grants.exchange(raw)
    app = FastAPI()
    app.include_router(create_native_editor_router(grants, editor=editor, download_service=downloads,
        cookie_secure=False, allowed_origin='http://test'))
    base = f'/reports/v1/native/{context.document_id}/{context.revision}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token, path=base)
        response = await client.post(base + '/api/save',
            headers={'Origin': 'http://test', 'X-CSRF-Token': grants.csrf_token(token)},
            json={'requestId': 'static-review-fault', 'expectedSha256': context.source_file.sha256,
                'operations': operations, 'confirmedPreviewDigest': preview['previewDigest']})
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved['validation']['ok'] is False
        warning = next(issue['message'] for issue in saved['validation']['issues'] if 'injected readback fault' in issue['message'])
        assert '实际生成文件' in warning
        assert '未应用' not in warning and '保留原文' not in warning
        artifact = saved['artifacts']['pdf']
        actual = await client.get(artifact['downloadUrl'])
        assert actual.status_code == 200
        assert hashlib.sha256(actual.content).hexdigest() == artifact['sha256']
        assert actual.content == preview['content']
        assert 'RETAINED INSERT' in PdfReader(BytesIO(actual.content)).pages[0].extract_text()
        if edit_kind=='styledMarkup':
            assert any(ref.get_object()['/Subtype']=='/Underline'
                for ref in PdfReader(BytesIO(actual.content)).pages[0]['/Annots'])
        if edit_kind=='styledDrawing':
            assert any(ref.get_object()['/Subtype']=='/Square'
                for ref in PdfReader(BytesIO(actual.content)).pages[0]['/Annots'])
        if edit_kind=='styledVector':
            annotation=next(ref.get_object() for ref in PdfReader(BytesIO(actual.content)).pages[0]['/Annots']
                if ref.get_object()['/Subtype']=='/Line')
            assert list(annotation['/L'])==[25,150,170,185]
            assert annotation['/AP']['/N'].get_data()
        if edit_kind=='styledPng':
            stamp=next(ref.get_object() for ref in PdfReader(BytesIO(actual.content)).pages[0]['/Annots']
                if ref.get_object()['/Subtype']=='/Stamp')
            image=stamp['/AP']['/N']['/Resources']['/XObject']['/Im0']
            assert list(stamp['/Rect'])==[25,100,125,140]
            assert image.get_data()==bytes([255,0,0,0,255,0])
            assert image['/SMask'].get_data()==bytes([255,128])
        if edit_kind in {'styledMeasure','styledCaret','styledMeasureBounds'}:
            check_measure_caret(actual.content)
        if edit_kind in {'styledLink','styledInternalLink'}:
            check_link(actual.content)
        if edit_kind=='styledLinkWriterFault':
            assert not PdfReader(BytesIO(actual.content)).pages[0].get('/Annots')


@pytest.mark.anyio
async def test_pdf_measure_appearance_warning_keeps_applied_indices_and_actual_http_download(tmp_path):
    """固定测量线外观差异是软告警：已应用的线和改字均可预览、保存、下载。"""
    from io import BytesIO
    from pypdf import PdfReader
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE, create_native_editor_router
    from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture
    from smart_reporting.reporting.tests.test_pdf_native_text_edits import text_operation
    editor, context, source, downloads = await fixture(tmp_path)
    operation = {**text_operation(source, 'MEASURE RETAINED'),
        'sourceSha256': context.source_file.sha256, 'font': 'times', 'bold': True}
    operations = [{'kind': 'addDrawing', 'pageId': operation['pageId'], 'shape': 'measure',
        'from': [25, 100], 'to': [170, 160], 'label': '145 pt', 'color': [0.2, 0.4, 0.6], 'width': 2}, operation]
    editor.context_for_session = AsyncMock(return_value=context)
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    token, _ = await editor.grants.exchange(raw)
    app = FastAPI()
    app.include_router(create_native_editor_router(editor.grants, editor=editor,
        download_service=downloads, cookie_secure=False, allowed_origin='http://test'))
    base = f'/reports/v1/native/{context.document_id}/{context.revision}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token, path=base)
        headers = {'Origin': 'http://test', 'X-CSRF-Token': editor.grants.csrf_token(token)}
        payload = {'expectedSha256': context.source_file.sha256, 'operations': operations}
        response = await client.post(base + '/api/preview', headers=headers, json=payload)
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview['appliedOperationIndices'] == [0, 1] and preview['skippedOperations'] == []
        assert len(preview['reviewIssues']) == 1
        issue = preview['reviewIssues'][0]
        assert issue['operationIndex'] == 0 and issue['kind'] == 'addDrawing'
        assert issue['code'] == 'pdf_measure_label_appearance_review_required'
        assert '字体' in issue['message'] and '页边' in issue['message']
        assert '草稿居中位置不同' not in issue['message']
        response = await client.post(base + '/api/save', headers=headers,
            json={**payload, 'requestId': 'measure-appearance-warning', 'confirmedPreviewDigest': preview['previewDigest']})
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved['validation']['ok'] is False
        assert any(item['code'] == issue['code'] and issue['message'] in item['message']
            for item in saved['validation']['issues'])
        assert not any(item['code'] == 'native_pdf_text_skipped' for item in saved['validation']['issues'])
        artifact = saved['artifacts']['pdf']
        downloaded = await client.get(artifact['downloadUrl'])
        assert downloaded.status_code == 200
        assert hashlib.sha256(downloaded.content).hexdigest() == artifact['sha256']
        assert len(downloaded.content) == artifact['size']
        reader = PdfReader(BytesIO(downloaded.content))
        assert 'MEASURE RETAINED' in reader.pages[0].extract_text()
        line = next(ref.get_object() for ref in reader.pages[0]['/Annots'] if ref.get_object()['/Subtype'] == '/Line')
        assert list(line['/L']) == [25, 100, 170, 160] and line['/Contents'] == '145 pt'
        assert line['/AP']['/N'].get_data()
        assert await editor.read_file(context) == source


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['overflow', 'review_failed', 'metadata_null', 'metadata_object', 'metadata_incomplete'])
async def test_pdf_form_review_issues_keep_applied_value_and_actual_http_download(tmp_path, monkeypatch, fault):
    """填值后溢出或测量故障是独立软告警，不得伪装未执行或阻断下载。"""
    from io import BytesIO
    from pypdf import PdfReader
    from reportlab.pdfgen import canvas
    from smart_reporting.report_editor import native, native_publication
    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE, create_native_editor_router
    from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf_with_receipt
    from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture

    editor, context, _, downloads = await fixture(tmp_path)
    stream = BytesIO()
    page = canvas.Canvas(stream, pagesize=(300, 400))
    page.drawString(20, 360, 'FORM WARNING CONTROL')
    page.acroForm.textfield(name='customer', x=30, y=230, width=120, height=24,
        fontName='Courier-BoldOblique', fontSize=18, value='Alice')
    page.showPage(); page.save()
    source = stream.getvalue()
    identity = ArtifactFile(path='native/form-review.pdf', size=len(source),
        sha256=hashlib.sha256(source).hexdigest(), mediaType='application/pdf')
    await editor.workspace.awrite_bytes(bind_native_workspace(editor.workspace, context.scope), identity.path, source)
    context = context.model_copy(update={'source_file': identity})
    field = inspect_pdf(source)['formFields'][0]
    operation = {'kind': 'setFormValue', **{key: field[key] for key in
        ('fieldId', 'expectedFieldSha256', 'name')}, 'fieldKind': 'text', 'value': 'Alice Updated'}
    issue = {'operationIndex': 0, 'kind': 'setFormValue', 'fieldName': 'customer',
        'code': 'pdf_form_text_overflow' if fault == 'overflow' else 'pdf_form_text_overflow_review_failed',
        'message': '字段 customer 的文本超出控件可见范围，实际内容与下载已保留。' if fault == 'overflow'
            else '字段 customer 的溢出测量失败，实际内容与下载已保留，请人工核对。'}
    malformed = {'metadata_null': None, 'metadata_object': {}, 'metadata_incomplete': [{}]}
    if fault in malformed:
        issue = {'operationIndex': 0, 'kind': 'pdfOutput', 'fieldName': '',
            'code': 'native_pdf_review_issues_invalid',
            'message': 'PDF 内容或版式复核回执无效；已保留实际生成文件，请人工核对。'}
    def review_warning(content, operations):
        result = patch_pdf_with_receipt(content, operations)
        assert PdfReader(BytesIO(result['content'])).get_fields()['customer']['/V'] == 'Alice Updated'
        assert result['appliedOperationIndices'] == [0] and result['skippedOperations'] == []
        return {**result, 'reviewIssues': malformed[fault] if fault in malformed else [issue]}
    monkeypatch.setattr(native, 'patch_pdf_with_receipt', review_warning)
    monkeypatch.setattr(native_publication, 'patch_pdf_with_receipt', review_warning)
    editor.context_for_session = AsyncMock(return_value=context)
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    token, _ = await editor.grants.exchange(raw)
    app = FastAPI()
    app.include_router(create_native_editor_router(editor.grants, editor=editor,
        download_service=downloads, cookie_secure=False, allowed_origin='http://test'))
    base = f'/reports/v1/native/{context.document_id}/{context.revision}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token, path=base)
        headers = {'Origin': 'http://test', 'X-CSRF-Token': editor.grants.csrf_token(token)}
        payload = {'expectedSha256': identity.sha256, 'operations': [operation]}
        preview = await client.post(base + '/api/preview', headers=headers, json=payload)
        assert preview.status_code == 200, preview.text
        assert preview.json()['reviewIssues'] == [issue]
        assert preview.json()['appliedOperationIndices'] == [0]
        assert preview.json()['skippedOperations'] == []
        saved_response = await client.post(base + '/api/save', headers=headers,
            json={**payload, 'requestId': 'form-review-' + fault})
        assert saved_response.status_code == 200, saved_response.text
        saved = saved_response.json()
        assert saved['validation']['ok'] is False
        assert any(item['code'] == issue['code'] and issue['message'] in item['message']
            for item in saved['validation']['issues'])
        assert not any(item['code'] == 'native_pdf_text_skipped' for item in saved['validation']['issues'])
        artifact = saved['artifacts']['pdf']
        actual = await client.get(artifact['downloadUrl'])
        assert actual.status_code == 200
        assert hashlib.sha256(actual.content).hexdigest() == artifact['sha256']
        assert len(actual.content) == artifact['size']
        reader = PdfReader(BytesIO(actual.content))
        assert reader.get_fields()['customer']['/V'] == 'Alice Updated'
        assert 'FORM WARNING CONTROL' in reader.pages[0].extract_text()
        assert await editor.read_file(context) == source


@pytest.mark.anyio
@pytest.mark.parametrize('kind',['editFormWidget','arrangeFormWidgets','appendRadioWidget','editFormTextProperties','renameFormWidget','editChoiceOptions','renameRadioGroup','removeRadioWidget','requiredRadioGroup','arrangePerPage'])
async def test_form_design_postwrite_review_warning_keeps_actual_http_download(tmp_path,monkeypatch,kind):
    """新控件属性/排列/单选追加签发：复读故障仅告警，保留真实修改后的 PDF。"""
    from io import BytesIO
    from pypdf import PdfReader
    from pypdf.generic import StreamObject
    from smart_reporting.report_editor import native_publication
    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE, create_native_editor_router
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
    from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf_with_receipt
    from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture

    editor,context,source,downloads=await fixture(tmp_path)
    if kind=='arrangePerPage':
        from pypdf import PdfWriter
        writer=PdfWriter();writer.clone_document_from_reader(PdfReader(BytesIO(source)))
        writer.add_blank_page(width=300,height=400);writer.add_blank_page(width=300,height=400)
        stream=BytesIO();writer.write(stream);source=stream.getvalue()
    for index,rect in enumerate([[30,100,100,124],[150,150,220,174]]):
        digest=hashlib.sha256(source).hexdigest()
        source=patch_pdf_with_receipt(source,[{'kind':'createFormField','sourceSha256':digest,
            'pageId':f'sha256:{digest}:page:0','fieldKind':'choice' if kind=='editChoiceOptions' and index==0 else 'text','fieldName':f'field{index}',
            'rect':rect,'required':False,**({'options':['One','Two','Three'],'value':'Two'} if kind=='editChoiceOptions' and index==0 else {})}])['content']
    if kind=='arrangePerPage':
        for name,page_index,rect in [('page10',1,[100,200,150,224]),('page11',1,[200,140,250,164]),('page20',2,[170,240,220,264])]:
            digest=hashlib.sha256(source).hexdigest()
            source=patch_pdf_with_receipt(source,[{'kind':'createFormField','sourceSha256':digest,
                'pageId':f'sha256:{digest}:page:{page_index}','fieldKind':'text','fieldName':name,
                'rect':rect,'required':False,'value':name}])['content']
    if kind in {'appendRadioWidget','renameRadioGroup','removeRadioWidget','requiredRadioGroup'}:
        digest=hashlib.sha256(source).hexdigest()
        page_id=f'sha256:{digest}:page:0'
        source=patch_pdf_with_receipt(source,[{'kind':'createFormField','sourceSha256':digest,
            'pageId':page_id,'fieldKind':'radio','fieldName':'answer','rect':[30,200,50,220],
            'required':True,'radioWidgets':[{'pageId':page_id,'rect':[30,200,50,220],'exportValue':'Yes','checked':True},{'pageId':page_id,'rect':[130,200,150,220],'exportValue':'Maybe'}]}])['content']
    digest=hashlib.sha256(source).hexdigest()
    identity=ArtifactFile(path='native/design-base.pdf',size=len(source),sha256=digest,mediaType='application/pdf')
    key=bind_native_workspace(editor.workspace,context.scope)
    await editor.workspace.awrite_bytes(key,identity.path,source)
    context=context.model_copy(update={'source_file':identity})
    widgets=inspect_pdf(source)['formDesignWidgets']
    keys=['fieldName','widgetId','widgetIdentity','expectedWidgetSha256']
    targets=[{name:widget[name] for name in keys} for widget in widgets]
    operation=({'kind':kind,'sourceSha256':digest,**targets[0],'rect':[30,80,140,104],'required':True}
        if kind=='editFormWidget' else {'kind':kind,'sourceSha256':digest,'targets':targets,'alignment':'left'})
    if kind=='arrangePerPage':operation={**operation,'kind':'arrangeFormWidgets'}
    if kind=='renameFormWidget':
        operation={'kind':'editFormWidget','sourceSha256':digest,**targets[0],'newFieldName':'renamed0'}
    if kind=='renameRadioGroup':
        anchor=next(widget for widget in widgets if widget['fieldName']=='answer')
        operation={'kind':'editFormWidget','sourceSha256':digest,
            **{key:anchor[key] for key in keys},'newFieldName':'renamedAnswer'}
    if kind=='requiredRadioGroup':
        anchor=next(widget for widget in widgets if widget['fieldName']=='answer')
        operation={'kind':'editFormWidget','sourceSha256':digest,**{key:anchor[key] for key in keys},'required':False}
    if kind=='removeRadioWidget':
        anchor=next(widget for widget in widgets if widget['fieldName']=='answer' and widget.get('radioRemovalEditable'))
        operation={'kind':'removeFormWidget','sourceSha256':digest,**{key:anchor[key] for key in keys}}
    if kind=='editChoiceOptions':
        operation={'kind':'editFormWidget','sourceSha256':digest,**targets[0],'choiceOptions':['Four','Two','One']}
    if kind=='appendRadioWidget':
        anchor=next(widget for widget in widgets if widget['fieldName']=='answer')
        operation={'kind':kind,'sourceSha256':digest,**{key:anchor[key] for key in keys},
            'pageId':f'sha256:{digest}:page:0','rect':[80,200,100,220],'exportValue':'No'}
    if kind=='editFormTextProperties':
        operation={'kind':kind,'sourceSha256':digest,**targets[0],
            'multiLine':True,'maxLen':50,'textAlignment':'right','fontSize':18,
            'fontName':'Courier-BoldOblique'}
    original=native_publication.patch_pdf_with_receipt
    def review_warning(content,operations):
        receipt=original(content,operations)
        return {**receipt,'appliedOperationIndices':[],'skippedOperations':[{'operationIndex':0,
            'kind':operation['kind'],'reason':'injected form output review failure'}]}
    monkeypatch.setattr(native_publication,'patch_pdf_with_receipt',review_warning)
    preview=review_warning(source,[operation])
    editor.context_for_session=AsyncMock(return_value=context)
    raw,_=await editor.grants.issue(context,capabilities=editor.capabilities(context))
    token,_=await editor.grants.exchange(raw)
    app=FastAPI();app.include_router(create_native_editor_router(editor.grants,editor=editor,
        download_service=downloads,cookie_secure=False,allowed_origin='http://test'))
    base=f'/reports/v1/native/{context.document_id}/{context.revision}'
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE,token,path=base)
        response=await client.post(base+'/api/save',headers={'Origin':'http://test',
            'X-CSRF-Token':editor.grants.csrf_token(token)},json={'requestId':kind+'-review',
            'expectedSha256':digest,'operations':[operation],'confirmedPreviewDigest':preview['previewDigest']})
        assert response.status_code==200,response.text
        saved=response.json();assert saved['validation']['ok'] is False
        warning=next(issue['message'] for issue in saved['validation']['issues'] if 'injected form' in issue['message'])
        assert '实际生成文件' in warning and '保留原文' not in warning
        artifact=saved['artifacts']['pdf'];download=await client.get(artifact['downloadUrl'])
        assert download.status_code==200 and download.content==preview['content']
        assert hashlib.sha256(download.content).hexdigest()==artifact['sha256']
        fields=PdfReader(BytesIO(download.content)).get_fields()
        expected_names={'field0','field1','answer'} if kind in {'appendRadioWidget','renameRadioGroup','removeRadioWidget','requiredRadioGroup'} else {'field0','field1'}
        if kind=='renameFormWidget':expected_names=expected_names-{targets[0]['fieldName']}|{'renamed0'}
        if kind=='renameRadioGroup':expected_names=expected_names-{'answer'}|{'renamedAnswer'}
        if kind=='arrangePerPage':expected_names|={'page10','page11','page20'}
        assert set(fields)==expected_names
        actual=inspect_pdf(download.content)['formDesignWidgets']
        if kind=='editFormWidget':
            assert next(w for w in actual if w['fieldName']==targets[0]['fieldName'])['rect']==[30,80,140,104]
            assert int(fields[targets[0]['fieldName']]['/Ff'])&2
        elif kind in {'renameFormWidget','renameRadioGroup'}:
            before=PdfReader(BytesIO(source));after=PdfReader(BytesIO(download.content))
            old_name='answer' if kind=='renameRadioGroup' else targets[0]['fieldName']
            new_name='renamedAnswer' if kind=='renameRadioGroup' else 'renamed0'
            old_ref=next(ref for ref in before.trailer['/Root']['/AcroForm']['/Fields']
                if str(ref.get_object()['/T'])==old_name)
            new_ref=next(ref for ref in after.trailer['/Root']['/AcroForm']['/Fields']
                if str(ref.get_object()['/T'])==new_name)
            assert (old_ref.idnum,old_ref.generation)==(new_ref.idnum,new_ref.generation)
            assert [(ref.idnum,ref.generation) for ref in before.pages[0]['/Annots']]==[(ref.idnum,ref.generation) for ref in after.pages[0]['/Annots']]
            for old,new in zip(before.pages[0]['/Annots'],after.pages[0]['/Annots'],strict=True):
                old_normal=old.get_object()['/AP']['/N'];new_normal=new.get_object()['/AP']['/N']
                if kind=='renameRadioGroup' and not isinstance(old_normal,StreamObject):
                    assert set(old_normal)==set(new_normal)
                    for state in old_normal:
                        old_state=old_normal.raw_get(state);new_state=new_normal.raw_get(state)
                        assert (old_state.idnum,old_state.generation)==(new_state.idnum,new_state.generation)
                        assert old_state.get_object().get_data()==new_state.get_object().get_data()
                else:
                    assert old_normal.get_data()==new_normal.get_data()
            assert before.pages[0].get_contents().get_data()==after.pages[0].get_contents().get_data()
            old_ids={widget['widgetId'] for widget in widgets if widget['fieldName']==old_name}
            assert {widget['widgetId'] for widget in actual if widget['fieldName']==new_name}==old_ids
            if kind=='renameRadioGroup':
                assert str(fields[new_name]['/V'])=='/0' and len(fields[new_name]['/Kids'])==2
                assert [(ref.idnum,ref.generation) for ref in old_ref.get_object()['/Kids']]==[(ref.idnum,ref.generation) for ref in new_ref.get_object()['/Kids']]
                assert [str(ref.get_object()['/AS']) for ref in new_ref.get_object()['/Kids']]==['/0','/Off']
        elif kind=='requiredRadioGroup':
            from pypdf.generic import IndirectObject
            before=PdfReader(BytesIO(source));after=PdfReader(BytesIO(download.content))
            original=before.get_fields()['answer']
            assert int(original['/Ff']) ^ int(fields['answer']['/Ff']) == 2
            assert str(fields['answer']['/V'])=='/0' and len(fields['answer']['/Kids'])==2
            assert all(widget.get('radioRequiredEditable') for widget in actual if widget['fieldName']=='answer')
            def canonical(value):
                if isinstance(value,IndirectObject):return ['ref',value.idnum,value.generation]
                if isinstance(value,StreamObject):return [canonical(dict(value)),hashlib.sha256(value._data).hexdigest(),hashlib.sha256(value.get_data()).hexdigest()]
                if isinstance(value,dict):return [[str(k),canonical(v)] for k,v in sorted(value.items())]
                if isinstance(value,list):return [canonical(v) for v in value]
                return repr(value)
            target=next(ref for ref in before.trailer['/Root']['/AcroForm']['/Fields'] if str(ref.get_object()['/T'])=='answer')
            assert before.xref.keys()==after.xref.keys()
            for generation,objects in before.xref.items():
                assert set(objects)==set(after.xref[generation])
                for number in objects:
                    if number==0:continue
                    old=before.get_object(IndirectObject(number,generation,before));new=after.get_object(IndirectObject(number,generation,after))
                    if (number,generation)==(target.idnum,target.generation):
                        old={k:v for k,v in old.items() if k!='/Ff'};new={k:v for k,v in new.items() if k!='/Ff'}
                    assert canonical(old)==canonical(new),(number,generation)
        elif kind=='removeRadioWidget':
            assert len(fields['answer']['/Kids'])==1 and str(fields['answer']['/V'])=='/0'
            assert [str(option) for option in fields['answer']['/Opt']]==['Yes']
            remaining=[widget for widget in actual if widget['fieldName']=='answer']
            assert len(remaining)==1 and remaining[0]['widgetId']!=operation['widgetId']
            assert remaining[0]['designEditable'] is True
            assert PdfReader(BytesIO(source)).pages[0].get_contents().get_data()==PdfReader(BytesIO(download.content)).pages[0].get_contents().get_data()
        elif kind=='editChoiceOptions':
            options=[(str(option[0]),str(option[1])) if isinstance(option,list)
                else (str(option),str(option)) for option in fields['field0']['/Opt']]
            assert options==[(value,value) for value in ['Four','Two','One']]
            assert fields['field0']['/V']=='Two'
            before=PdfReader(BytesIO(source));after=PdfReader(BytesIO(download.content))
            assert [(ref.idnum,ref.generation) for ref in before.pages[0]['/Annots']]==[(ref.idnum,ref.generation) for ref in after.pages[0]['/Annots']]
            for old,new in zip(before.pages[0]['/Annots'],after.pages[0]['/Annots'],strict=True):
                assert old.get_object()['/AP']['/N'].get_data()==new.get_object()['/AP']['/N'].get_data()
            assert before.pages[0].get_contents().get_data()==after.pages[0].get_contents().get_data()
        elif kind=='arrangePerPage':
            before=PdfReader(BytesIO(source));after=PdfReader(BytesIO(download.content))
            by_name={widget['fieldName']:widget for widget in actual}
            assert [by_name[name]['rect'][0] for name in ['field0','field1','page10','page11','page20']]==[30,30,100,100,170]
            assert [by_name[name]['pageIndex'] for name in ['field0','field1','page10','page11','page20']]==[0,0,1,1,2]
            assert fields['page20']['/V']=='page20'
            for old_page,new_page in zip(before.pages,after.pages,strict=True):
                assert [(ref.idnum,ref.generation) for ref in old_page['/Annots']]==[(ref.idnum,ref.generation) for ref in new_page['/Annots']]
                old_contents=old_page.get_contents();new_contents=new_page.get_contents()
                assert (old_contents.get_data() if old_contents else None)==(new_contents.get_data() if new_contents else None)
            old_widget=before.pages[2]['/Annots'][0].get_object();new_widget=after.pages[2]['/Annots'][0].get_object()
            assert list(old_widget['/Rect'])==list(new_widget['/Rect'])
            assert old_widget['/AP']['/N'].get_data()==new_widget['/AP']['/N'].get_data()
        elif kind=='arrangeFormWidgets':assert len({w['rect'][0] for w in actual})==1
        elif kind=='editFormTextProperties':
            raw_reader=PdfReader(BytesIO(download.content))
            field=next(ref.get_object() for ref in raw_reader.trailer['/Root']['/AcroForm']['/Fields']
                if str(ref.get_object()['/T'])==targets[0]['fieldName'])
            assert int(field['/Ff'])&4096
            assert int(field['/MaxLen'])==50 and int(field['/Q'])==2
            target=next(w for w in actual if w['fieldName']==targets[0]['fieldName'])
            assert target['textProperties']['fontName']=='Courier-BoldOblique'
            assert len(actual)==2
        else:
            assert len(fields['answer']['/Kids'])==3
            assert str(fields['answer']['/V'])=='/0'
            assert next(field for field in inspect_pdf(download.content)['formFields'] if field['name']=='answer')['options']==['Yes','Maybe','No']
        assert await editor.read_file(context)==source


@pytest.mark.anyio
async def test_protected_pdf_review_warning_keeps_verified_http_download(tmp_path,monkeypatch):
    """新增保护签发：生成后权限复核故障只能告警，不能丢弃加密下载。"""
    from io import BytesIO
    from pypdf import PdfReader
    from smart_reporting.report_editor import native_pdf_protection
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
    from smart_reporting.reporting.tests.test_native_pdf_protection import protection_client

    editor,context,_,app,base,token=await protection_client(tmp_path)
    original=native_pdf_protection.protect_pdf_bytes
    def fault(*args,**kwargs):
        receipt=original(*args,**kwargs)
        return {**receipt,'reviewIssues':['injected review failure']}
    monkeypatch.setattr(native_pdf_protection,'protect_pdf_bytes',fault)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE,token,path=base)
        response=await client.post(base+'/api/protect-pdf',headers={'Origin':'http://test','X-CSRF-Token':editor.grants.csrf_token(token)},json={'requestId':'protect-review-fault','expectedSha256':context.source_file.sha256,'userPassword':'reader-secret','ownerPassword':'owner-secret','permissions':{'printing':False,'modifying':False,'annotating':False,'copying':False}})
        assert response.status_code==200,response.text
        saved=response.json();assert not saved['validation']['ok']
        assert any(i['code']=='native_pdf_protection_review_failed' for i in saved['validation']['issues'])
        artifact=saved['artifacts']['pdf'];actual=await client.get(artifact['downloadUrl'])
        assert actual.status_code==200 and hashlib.sha256(actual.content).hexdigest()==artifact['sha256']
        pdf=PdfReader(BytesIO(actual.content));assert pdf.is_encrypted and pdf.decrypt('reader-secret')==1
        assert 'Amount due 500' in pdf.pages[0].extract_text()


@pytest.mark.anyio
async def test_external_pdf_postwrite_warning_keeps_actual_http_download(tmp_path,monkeypatch):
    """外部页生成后复核异常，仍签发实际包含外部页面的新文件。"""
    import base64
    from io import BytesIO
    from pypdf import PdfReader
    from smart_reporting.report_editor import native_publication
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
    from smart_reporting.reporting.tests.test_native_pdf_protection import protection_client
    from smart_reporting.reporting.tests.test_pdf_external_pages import pdf
    editor,context,_,app,base,token=await protection_client(tmp_path)
    original=native_publication.patch_pdf_with_receipt
    def fault(content,operations):
        receipt=original(content,operations)
        return {**receipt,'appliedOperationIndices':[],'skippedOperations':[{'operationIndex':0,'kind':'externalPages','reason':'injected external output review fault'}]}
    monkeypatch.setattr(native_publication,'patch_pdf_with_receipt',fault)
    foreign=pdf('retained external',1)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE,token,path=base)
        response=await client.post(base+'/api/external-pages',headers={'Origin':'http://test','X-CSRF-Token':editor.grants.csrf_token(token)},json={'requestId':'external-review-fault','expectedSha256':context.source_file.sha256,'action':'insert','afterPage':1,'externalSha256':hashlib.sha256(foreign).hexdigest(),'bytesBase64':base64.b64encode(foreign).decode()})
        assert response.status_code==200,response.text
        saved=response.json();assert not saved['validation']['ok']
        warning=next(i['message'] for i in saved['validation']['issues'] if 'injected external output review fault' in i['message'])
        assert '实际生成文件' in warning and '保留原文' not in warning
        artifact=saved['artifacts']['pdf'];actual=await client.get(artifact['downloadUrl'])
        assert actual.status_code==200 and hashlib.sha256(actual.content).hexdigest()==artifact['sha256']
        assert 'retained external 1' in PdfReader(BytesIO(actual.content)).pages[1].extract_text()


@pytest.mark.anyio
async def test_pdf_xlsx_rich_supplement_failure_keeps_plain_actual_http_download(tmp_path,monkeypatch):
    """富文本补写步骤登记：原生专项验证真实补写故障，此处验证其回退回执不阻断签发。"""
    from io import BytesIO
    from openpyxl import load_workbook
    from smart_reporting.report_editor import native_pdf_convert
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
    from smart_reporting.reporting.tests.test_native_pdf_protection import protection_client

    editor,context,source,app,base,token=await protection_client(tmp_path)
    original=native_pdf_convert.convert_pdf_office
    retained={}
    message='XLSX 富文本补写失败，已保留补写前实际工作簿：injected rich supplement failure'
    def fallback_receipt(content,*,output_format):
        # 来源仅有统一样式正文，实际转换结果就是补写前可读的 plain workbook。
        result=original(content,output_format=output_format)
        retained['content']=result['content']
        return {**result,'warnings':[*result.get('warnings',[]),message],
            'validation':{'ok':False,'issues':[*result['validation']['issues'],message]}}
    monkeypatch.setattr(native_pdf_convert,'convert_pdf_office',fallback_receipt)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE,token,path=base)
        response=await client.post(base+'/api/convert-office',headers={'Origin':'http://test',
            'X-CSRF-Token':editor.grants.csrf_token(token)},json={'requestId':'xlsx-rich-fallback',
            'expectedSha256':context.source_file.sha256,'format':'xlsx'})
        assert response.status_code==200,response.text
        saved=response.json();assert saved['validation']['ok'] is False
        assert any(message in issue['message'] for issue in saved['validation']['issues'])
        artifact=saved['artifacts']['xlsx'];actual=await client.get(artifact['downloadUrl'])
        assert actual.status_code==200 and actual.content==retained['content']
        assert hashlib.sha256(actual.content).hexdigest()==artifact['sha256']
        workbook=load_workbook(BytesIO(actual.content))
        assert 'Amount due 500' in ' '.join(str(cell.value) for sheet in workbook for row in sheet for cell in row if cell.value is not None)
        assert await editor.read_file(context)==source


@pytest.mark.anyio
@pytest.mark.parametrize('output_format',['pptx','docx','xlsx'])
@pytest.mark.parametrize('fault',['review','registration','postwrite','persistence','receipt'])
async def test_pdf_conversion_late_fault_keeps_actual_pptx_http_download(tmp_path,monkeypatch,fault,output_format):
    """转换新增签发步骤故障：真实Office身份可读便保留下载，始终声明待人工验收。"""
    from io import BytesIO
    from pptx import Presentation
    from smart_reporting.report_editor import native_pdf_convert
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
    from smart_reporting.reporting.tests.test_native_pdf_protection import protection_client
    editor,context,source,app,base,token=await protection_client(tmp_path)
    linked_source=output_format=='pptx' and fault=='review'
    shaded_source=output_format=='docx' and fault=='review'
    if shaded_source:
        from reportlab.lib.colors import HexColor
        from reportlab.pdfgen.canvas import Canvas
        from smart_reporting.report_editor.native import bind_native_workspace
        from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
        buffer=BytesIO();canvas=Canvas(buffer,pagesize=(400,300),invariant=1)
        canvas.setFillColor(HexColor('#FFF2CC'));canvas.rect(39,217,115,16,fill=1,stroke=0)
        canvas.setFillColor(HexColor('#123456'));canvas.setFont('Helvetica',12);canvas.drawString(40,220,'Amount due 500')
        canvas.showPage();canvas.save();source=buffer.getvalue()
        identity=ArtifactFile(path='native/conversion-shaded.pdf',size=len(source),sha256=hashlib.sha256(source).hexdigest(),mediaType='application/pdf')
        await editor.workspace.awrite_bytes(bind_native_workspace(editor.workspace,context.scope),identity.path,source)
        context=context.model_copy(update={'source_file':identity});editor.context_for_session=AsyncMock(return_value=context)
        raw,_=await editor.grants.issue(context,capabilities=editor.capabilities(context));token,_=await editor.grants.exchange(raw)
    if linked_source:
        from pypdf import PdfReader, PdfWriter
        from pypdf.annotations import Link
        from smart_reporting.report_editor.native import bind_native_workspace
        from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
        writer=PdfWriter();writer.clone_document_from_reader(PdfReader(BytesIO(source)))
        writer.add_annotation(0,Link(rect=(30,225,170,245),url='https://example.com/report'))
        buffer=BytesIO();writer.write(buffer);source=buffer.getvalue()
        identity=ArtifactFile(path='native/conversion-linked.pdf',size=len(source),sha256=hashlib.sha256(source).hexdigest(),mediaType='application/pdf')
        await editor.workspace.awrite_bytes(bind_native_workspace(editor.workspace,context.scope),identity.path,source)
        context=context.model_copy(update={'source_file':identity});editor.context_for_session=AsyncMock(return_value=context)
        raw,_=await editor.grants.issue(context,capabilities=editor.capabilities(context));token,_=await editor.grants.exchange(raw)
    if fault=='receipt':
        from smart_reporting.reporting.delivery import pdf_native
        original_invoke=pdf_native._invoke
        def receipt_then_raise(*args,**kwargs):
            result=original_invoke(*args,**kwargs)
            if args[0].get('kind')=='convertOffice':raise RuntimeError('injected after conversion output')
            return result
        monkeypatch.setattr(pdf_native,'_invoke',receipt_then_raise)
    if fault=='review':monkeypatch.setattr(native_pdf_convert,'read_verified_file',AsyncMock(side_effect=RuntimeError('injected output review failure')))
    if fault=='registration':monkeypatch.setattr(editor.repository,'create_from_source',AsyncMock(side_effect=RuntimeError('injected registration failure')),raising=False)
    if fault=='persistence':monkeypatch.setattr(editor.publication.artifact_persistence,'persist_available',AsyncMock(side_effect=RuntimeError('injected persistence failure')))
    if fault=='postwrite':
        original=editor.workspace.awrite_bytes
        async def write_then_raise(*args,**kwargs):
            result=await original(*args,**kwargs)
            if str(args[1]).endswith('.'+output_format):raise RuntimeError('injected after actual write')
            return result
        monkeypatch.setattr(editor.workspace,'awrite_bytes',write_then_raise)
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE,token,path=base)
        response=await client.post(base+'/api/convert-office',headers={'Origin':'http://test','X-CSRF-Token':editor.grants.csrf_token(token)},json={'requestId':'conversion-'+fault,'expectedSha256':context.source_file.sha256,'format':output_format})
        assert response.status_code==200,response.text
        saved=response.json();assert saved['validation']['ok'] is False
        if fault=='receipt':assert any('回执' in issue.get('message','') for issue in saved['validation']['issues'])
        else:assert any(fault in issue['code'] for issue in saved['validation']['issues'])
        artifact=saved['artifacts'][{'docx':'word','xlsx':'xlsx','pptx':'pptx'}[output_format]];actual=await client.get(artifact['downloadUrl'])
        assert actual.status_code==200 and len(actual.content)==artifact['size']
        assert hashlib.sha256(actual.content).hexdigest()==artifact['sha256']
        if output_format=='pptx':
            deck=Presentation(BytesIO(actual.content));assert len(deck.slides)==1
            text=' '.join(shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame)
        elif output_format=='docx':
            from docx import Document
            document=Document(BytesIO(actual.content));text=' '.join(p.text for p in document.paragraphs)
            text+=' '.join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
        else:
            from openpyxl import load_workbook
            workbook=load_workbook(BytesIO(actual.content));text=' '.join(str(cell.value) for sheet in workbook for row in sheet for cell in row if cell.value is not None)
        assert 'Amount due 500' in text
        if shaded_source:
            from zipfile import ZipFile
            import xml.etree.ElementTree as ET
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            with ZipFile(BytesIO(actual.content)) as archive:
                document_xml=ET.fromstring(archive.read('word/document.xml'))
            runs=[run for run in document_xml.findall('.//w:r',ns) if 'Amount due 500' in ''.join(run.itertext())]
            assert runs and any(run.find('w:rPr/w:shd',ns) is not None and run.find('w:rPr/w:shd',ns).get('{'+ns['w']+'}fill')=='FFF2CC' for run in runs)
        if linked_source:
            from zipfile import ZipFile
            import xml.etree.ElementTree as ET
            ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
            with ZipFile(BytesIO(actual.content)) as archive:
                slide=ET.fromstring(archive.read('ppt/slides/slide1.xml'))
                rels=ET.fromstring(archive.read('ppt/slides/_rels/slide1.xml.rels'))
                targets={rel.attrib['Id']:rel.attrib for rel in rels}
                linked_runs=[run for run in slide.findall('.//a:r',ns) if run.find('a:rPr/a:hlinkClick',ns) is not None]
                assert any('Amount due 500' in (run.findtext('a:t',default='',namespaces=ns)) for run in linked_runs)
                assert all(targets[run.find('a:rPr/a:hlinkClick',ns).attrib['{'+ns['r']+'}id']]['Target']=='https://example.com/report' for run in linked_runs)
                assert all(targets[run.find('a:rPr/a:hlinkClick',ns).attrib['{'+ns['r']+'}id']]['TargetMode']=='External' for run in linked_runs)
        assert await editor.read_file(context)==source


@pytest.mark.anyio
@pytest.mark.parametrize('fault',['receipt','postwrite','review'])
async def test_protected_pdf_late_fault_keeps_actual_encrypted_http_download(tmp_path,monkeypatch,fault):
    """保护新增后置签发步骤故障：拒绝坏回执，保留实际加密PDF的身份下载。"""
    from io import BytesIO
    from pypdf import PdfReader
    from smart_reporting.report_editor import native_pdf_protection
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
    from smart_reporting.reporting.delivery import pdf_native
    from smart_reporting.reporting.tests.test_native_pdf_protection import protection_client
    editor,context,source,app,base,token=await protection_client(tmp_path)
    if fault=='receipt':
        original=pdf_native._invoke
        def receipt_then_raise(*args,**kwargs):
            result=original(*args,**kwargs)
            if args[0].get('kind')=='protect':raise RuntimeError('injected after engine output')
            return result
        monkeypatch.setattr(pdf_native,'_invoke',receipt_then_raise)
    if fault=='postwrite':
        original_write=editor.workspace.awrite_bytes
        async def write_then_raise(*args,**kwargs):
            result=await original_write(*args,**kwargs)
            if '/protected/' in str(args[1]):raise RuntimeError('injected after actual write')
            return result
        monkeypatch.setattr(editor.workspace,'awrite_bytes',write_then_raise)
    if fault=='review':monkeypatch.setattr(native_pdf_protection,'read_verified_file',AsyncMock(side_effect=RuntimeError('injected review helper failure')))
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE,token,path=base)
        response=await client.post(base+'/api/protect-pdf',headers={'Origin':'http://test','X-CSRF-Token':editor.grants.csrf_token(token)},json={'requestId':'protect-late-'+fault,'expectedSha256':context.source_file.sha256,'userPassword':'reader-secret','ownerPassword':'owner-secret','permissions':{'printing':True,'modifying':False,'annotating':False,'copying':False}})
        assert response.status_code==200,response.text
        saved=response.json();assert saved['validation']['ok'] is False
        code='native_pdf_protection_postwrite_warning' if fault=='postwrite' else 'native_pdf_protection_review_failed'
        assert any(issue['code']==code for issue in saved['validation']['issues'])
        artifact=saved['artifacts']['pdf'];actual=await client.get(artifact['downloadUrl'])
        assert actual.status_code==200 and len(actual.content)==artifact['size'] and hashlib.sha256(actual.content).hexdigest()==artifact['sha256']
        pdf=PdfReader(BytesIO(actual.content));assert pdf.is_encrypted and pdf.decrypt('reader-secret')==1
        assert 'Amount due 500' in pdf.pages[0].extract_text()
        assert await editor.read_file(context)==source


# 新签发链路故障点在这里逐项登记；使用真实文件桥接、签名授权及 HTTP 下载。
@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['validation', 'receipt', 'receipt_probe', 'primary_identity', 'registration', 'persistence', 'primary_grant', 'editor_grant', 'pdf_export'])
async def test_native_http_publication_keeps_download_on_optional_faults(tmp_path, monkeypatch, fault):
    from smart_reporting.report_editor.native import NativeEditorService
    from smart_reporting.report_editor.native_api import (
        NATIVE_SESSION_COOKIE,
        create_native_editor_router,
    )

    publication, context, downloads = await create_publication(tmp_path)
    grants = publication.editor_grants
    editor = NativeEditorService(publication.workspace, publication.repository, grants,
        report_editor=None, docx_enabled=True, publication=publication)
    # 本测试覆盖保存与签发，来源分支/仓储鉴权另由 native_editor_api 与真实PG测试验证。
    editor.context_for_session = AsyncMock(return_value=context)
    raw, _ = await grants.issue(context, capabilities=editor.capabilities(context))
    token, _ = await grants.exchange(raw)
    if fault == 'validation':
        publication.validator = AsyncMock(side_effect=RuntimeError('layout unavailable'))
    elif fault == 'receipt':
        original_write = publication.workspace.awrite_bytes
        async def write(thread, path, content, **kwargs):
            if path.endswith('/saved.json'):
                raise OSError('recovery record unavailable')
            return await original_write(thread, path, content, **kwargs)
        monkeypatch.setattr(publication.workspace, 'awrite_bytes', write)
    elif fault == 'receipt_probe':
        monkeypatch.setattr(publication.workspace, 'apath_exists', AsyncMock(side_effect=OSError('recovery lookup unavailable')))
    elif fault == 'primary_identity':
        from io import BytesIO

        from reportlab.pdfgen.canvas import Canvas

        output = BytesIO()
        canvas = Canvas(output)
        canvas.drawString(30, 700, 'retained PDF')
        canvas.save()
        monkeypatch.setattr('smart_reporting.report_editor.native_publication.libreoffice_to_pdf', lambda *a, **k: output.getvalue())
        original_write = publication._write_file
        async def write_primary(key, path, content, media_type):
            identity = await original_write(key, path, content, media_type)
            if path.endswith('.docx'):
                raise OSError('primary identity unavailable')
            return identity
        monkeypatch.setattr(publication, '_write_file', write_primary)
    elif fault == 'registration':
        monkeypatch.setattr(publication.repository, 'complete_revision', AsyncMock(side_effect=RuntimeError('registration unavailable')))
    elif fault == 'persistence':
        monkeypatch.setattr(publication.artifact_persistence, 'persist_available', AsyncMock(side_effect=RuntimeError('copy unavailable')))
    elif fault == 'primary_grant':
        monkeypatch.setattr(publication.download_grants, 'issue', AsyncMock(side_effect=RuntimeError('primary unavailable')))
    elif fault == 'editor_grant':
        monkeypatch.setattr(grants, 'issue', AsyncMock(side_effect=RuntimeError('editor unavailable')))
    elif fault == 'pdf_export':
        def failed_conversion(*args, **kwargs):
            raise RuntimeError('conversion unavailable')
        monkeypatch.setattr('smart_reporting.report_editor.native_publication.libreoffice_to_pdf', failed_conversion)
    app = FastAPI()
    app.include_router(create_native_editor_router(grants, editor=editor, download_service=downloads,
        cookie_secure=False, allowed_origin='http://test'))
    path = f'/reports/v1/native/{context.document_id}/{context.revision}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token, path=path)
        result = await client.post(path + ('/api/export' if fault in {'pdf_export', 'primary_identity'} else '/api/save'),
            headers={'Origin': 'http://test', 'X-CSRF-Token': grants.csrf_token(token)},
            json={'requestId': 'save-http', 'expectedSha256': context.source_file.sha256, 'operations': [], 'note': 'HTTP故障回归'})
        assert result.status_code == 200, result.text
        payload = result.json()
        assert payload['validation']['ok'] is False
        expected = {'validation': 'native_validation_failed', 'receipt': 'native_recovery_record_failed',
            'receipt_probe': 'native_recovery_record_invalid', 'primary_identity': 'native_word_identity_unavailable',
            'registration': 'native_revision_registration_failed', 'persistence': 'native_artifact_persistence_failed',
            'primary_grant': 'native_download_grant_failed', 'editor_grant': 'native_editor_grant_failed',
            'pdf_export': 'native_pdf_export_failed'}[fault]
        assert expected in {issue['code'] for issue in payload['validation']['issues']}
        artifact = payload['artifacts']['pdf' if fault == 'primary_identity' else 'word']
        downloaded = await client.get(artifact['downloadUrl'])
        assert downloaded.status_code == 200, downloaded.text
        assert hashlib.sha256(downloaded.content).hexdigest() == artifact['sha256']


@pytest.mark.anyio
@pytest.mark.parametrize('format',['xlsx','pptx'])
async def test_native_office_postwrite_validation_failure_keeps_http_download(tmp_path,monkeypatch,format):
    """新增签发步骤登记：Office写回后的结构回读失败只生成告警。"""
    from io import BytesIO
    from openpyxl import Workbook, load_workbook
    from pptx import Presentation
    from smart_reporting.report_editor import native_office
    from smart_reporting.report_editor.native import NativeEditorService,bind_native_workspace
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE,create_native_editor_router
    from smart_reporting.report_editor.native_models import NativeEditorContext,NATIVE_MEDIA
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
    publication,old,downloads=await create_publication(tmp_path)
    stream=BytesIO()
    if format == 'xlsx':
        book = Workbook()
        book.active['A1'] = '原值'
        operations = [{'kind': 'applyCellEdits', 'edits': [{
            'sheetName': 'Sheet', 'row': 0, 'column': 0, 'writeValue': True,
            'cell': {'value': '修改值'},
        }]}]
    else:
        book = Presentation()
        slide = book.slides.add_slide(book.slide_layouts[6])
        slide.shapes.add_textbox(0, 0, 100, 100)
        operations = [{'kind': 'editSlides', 'animations': [{
            'slideIndex': 0, 'elementId': 'sp_0', 'effect': 'flyIn',
            'trigger': 'onClick', 'direction': 'right',
        }]}]
    book.save(stream)
    content=stream.getvalue();key=bind_native_workspace(publication.workspace,old.scope)
    path=f'native/source.{format}';await publication.workspace.awrite_bytes(key,path,content)
    context=NativeEditorContext(documentId='document',revision=1,origin='upload',format=format,scope=old.scope,sourceFile=ArtifactFile(path=path,mediaType=NATIVE_MEDIA[format],size=len(content),sha256=hashlib.sha256(content).hexdigest()))
    editor=NativeEditorService(publication.workspace,publication.repository,publication.editor_grants,report_editor=None,office_enabled=True,publication=publication)
    editor.context_for_session=AsyncMock(return_value=context)
    raw,_=await publication.editor_grants.issue(context,capabilities=editor.capabilities(context));token,_=await publication.editor_grants.exchange(raw)
    monkeypatch.setattr(native_office,'inspect_office',lambda *_: (_ for _ in ()).throw(ValueError('structure unavailable')))
    app=FastAPI();app.include_router(create_native_editor_router(publication.editor_grants,editor=editor,download_service=downloads,cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        base='/reports/v1/native/document/1'
        client.cookies.set(NATIVE_SESSION_COOKIE,token,path=base)
        response=await client.post(base+'/api/save',headers={'Origin':'http://test','X-CSRF-Token':publication.editor_grants.csrf_token(token)},json={'requestId':'save','expectedSha256':context.source_file.sha256,'operations':operations})
        assert response.status_code==200,response.text
        saved=response.json()
        assert saved['revisionRegistered'] and not saved['validation']['ok']
        assert any(issue['code']=='native_office_read_validation_failed' for issue in saved['validation']['issues'])
        artifact=saved['artifacts'][format]
        actual=await client.get(artifact['downloadUrl'])
        assert actual.status_code == 200 and actual.content != content
        assert hashlib.sha256(actual.content).hexdigest() == artifact['sha256']
        if format == 'xlsx':
            assert load_workbook(BytesIO(actual.content)).active['A1'].value == '修改值'
        else:
            assert len(Presentation(BytesIO(actual.content)).slides[0].shapes) == 1
