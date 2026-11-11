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
from smart_reporting.tests.test_report_background_delivery import (
    auth_context as auth_context,
)
from smart_reporting.tests.test_report_background_delivery import (
    basis_context as basis_context,
)
from smart_reporting.tests.test_report_background_delivery import (
    document_context as document_context,
)
from smart_reporting.tests.test_report_background_delivery import (
    exercise_background_report,
)
from smart_reporting.tests.test_report_background_delivery import (
    index_context as index_context,
)
from smart_reporting.tests.test_report_background_delivery import (
    receipt_snapshot as receipt_snapshot,
)


from .delivery_fakes import InMemoryDownloadGrantRepository, InMemoryReportArtifactRepository
from .lineage_fixtures.manifest import register_trace_manifest
from .test_native_publication_nonblocking import create_publication


@pytest.mark.anyio
async def test_http_editor_export_keeps_files_when_formal_source_explanation_fails(tmp_path, monkeypatch):
    from .test_formal_source_explanations import exercise_formal_source_export_fault

    await exercise_formal_source_export_fault(tmp_path, monkeypatch)


@pytest.mark.anyio
async def test_http_editor_export_keeps_files_when_knowledge_source_projection_fails(tmp_path, monkeypatch):
    from .test_formal_source_explanations import exercise_formal_source_export_fault

    await exercise_formal_source_export_fault(tmp_path, monkeypatch, stage='knowledge')


@pytest.mark.anyio
@pytest.mark.integration
async def test_http_initial_workbook_retains_download_on_publication_fact_read_failure(
    basis_context, document_context, receipt_snapshot, monkeypatch,
):
    from smart_reporting.tests.test_initial_workbook_delivery import (
        exercise_initial_workbook_delivery,
    )

    await exercise_initial_workbook_delivery(basis_context, document_context, receipt_snapshot,
        monkeypatch, fact_read_failure=True)


@pytest.mark.anyio
@pytest.mark.integration
async def test_http_initial_pptx_retains_download_on_slide_knowledge_registration_failure(
    basis_context, document_context, receipt_snapshot, monkeypatch,
):
    from smart_reporting.tests.test_initial_workbook_delivery import exercise_initial_workbook_delivery

    await exercise_initial_workbook_delivery(basis_context, document_context, receipt_snapshot,
        monkeypatch, delivery_format='pptx', knowledge_registration_failure=True)


@pytest.mark.anyio
@pytest.mark.integration
async def test_http_initial_pptx_retains_download_on_narrative_parsing_failure(
    basis_context, document_context, receipt_snapshot, monkeypatch,
):
    from smart_reporting.tests.test_initial_workbook_delivery import exercise_initial_workbook_delivery

    await exercise_initial_workbook_delivery(basis_context, document_context, receipt_snapshot,
        monkeypatch, delivery_format='pptx', narrative_parsing_failure=True)


@pytest.mark.anyio
@pytest.mark.integration
async def test_http_publication_keeps_pdf_word_links_when_claim_support_projection_fails(
    basis_context, document_context, receipt_snapshot, monkeypatch,
):
    """新增解释展示步骤失败时，实际双格式仍经原生生成、签发及HTTP字节核验。"""
    await exercise_background_report(basis_context, document_context, receipt_snapshot, monkeypatch,
        'causal', 'unverified', projection_failure=True)


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.parametrize('outputs', [['pptx'], ['xlsx']], ids=['pptx', 'xlsx'])
@pytest.mark.parametrize('support_failure', [False, True], ids=['current', 'support-failure'])
async def test_http_native_summary_support_is_visible_and_failure_keeps_downloads(
    basis_context, receipt_snapshot, monkeypatch, outputs, support_failure,
):
    """新增原生展示步骤：真实生成/登记/HTTP下载，支持失败不能丢掉文件。"""
    import os
    import shutil
    from io import BytesIO

    from openpyxl import load_workbook
    from pptx import Presentation

    from smart_reporting.reporting.workflow import claim_presentation
    from smart_reporting.tests import c02_native_delivery, test_report_issue_c02

    original = c02_native_delivery.exercise_c02_native_delivery
    calls = []
    if support_failure:
        async def unavailable(*args):
            calls.append('injected')
            raise OSError('injected native claim support failure')

        monkeypatch.setattr(claim_presentation, 'registered_native_claim_presentations', unavailable)

    async def inspect(report):
        format = outputs[0]
        output = Path('/tmp') / f'smart-reporting-native-claims-{os.getpid()}-{format}-{support_failure}'
        output.mkdir(exist_ok=True)
        shutil.copytree(report.evidence_dir, output / 'native', dirs_exist_ok=True)
        validation = report.content['validation']
        support = validation['claimSupport']
        assert support
        if support_failure:
            assert calls == ['injected']
            assert validation['ok'] is False
            assert any(item['code'] == 'native_claim_support_unavailable' for item in validation['issues'])
        else:
            assert not any(item['code'] == 'native_claim_support_unavailable' for item in validation['issues'])
        file = output / 'native' / ('c02-corrected.' + format)
        if format == 'pptx':
            presentation = Presentation(file)
            text = '\n'.join(shape.text for slide in presentation.slides for shape in slide.shapes if shape.has_text_frame)
            if support_failure:
                assert '（支持关系待核实）' in text
            else:
                current = await report.editor.trace.validate(report.context,
                    (await report.editor.read_document(report.context)).markdown,
                    (await report.editor.read_document(report.context)).sha256)
                actual = {item['subjectId']: item for item in current['quality']['claimSupport']}
                assert all(item['support'].get('subjectId') in actual for item in support)
                assert all(item['support']['supportStatus'] == actual[item['support']['subjectId']]['supportStatus']
                    for item in support)
        else:
            workbook = load_workbook(BytesIO(file.read_bytes()), data_only=True)
            text = '\n'.join(str(cell.value or '') for row in workbook['汇总'] for cell in row)
            workbook.close()
            if support_failure:
                assert '（支持关系待核实）' in text
            else:
                current_document = await report.editor.read_document(report.context)
                current = await report.editor.trace.validate(report.context,
                    current_document.markdown, current_document.sha256)
                actual = {item['subjectId']: item for item in current['quality']['claimSupport']}
                assert all(item['support'].get('subjectId') in actual for item in support)
                assert all(item['support']['supportStatus'] == actual[item['support']['subjectId']]['supportStatus']
                    for item in support)
                assert '（推断，待核实）' in text
            assert all(item['support']['supportStatus'] == 'unverified' for item in support)
        (output / 'text.txt').write_text(text)
        (output / 'evidence.json').write_text(json.dumps({'format': format, 'supportFailure': support_failure,
            'injectionCalls': len(calls), 'validation': validation,
            'httpDownloadsVerified': True, 'businessApproval': 'not_performed'}, ensure_ascii=False, indent=2))

    async def native(*args, **kwargs):
        return await original(*args, **kwargs, after_report=inspect)

    monkeypatch.setattr(c02_native_delivery, 'exercise_c02_native_delivery', native)
    await test_report_issue_c02.test_c02_published_ratio_replaces_real_project_mean_and_rejects_70_expectation(
        basis_context, receipt_snapshot, monkeypatch, outputs)


@pytest.mark.anyio
@pytest.mark.integration
async def test_http_workbook_summary_registration_fault_keeps_actual_download(
    basis_context, receipt_snapshot, monkeypatch,
):
    """摘要知识登记读取失败只撤回支持关系，不阻断实际 XLSX 签发。"""
    import os
    import shutil

    from smart_reporting.reporting.workflow.analysis_summaries import AnalysisSummarySection
    from smart_reporting.tests import c02_native_delivery, test_report_issue_c02

    read_model = ReportWorkflowRuntime._read_identity_model
    native = c02_native_delivery.exercise_c02_native_delivery
    calls = []

    async def unavailable(self, thread_id, file, model):
        if model is AnalysisSummarySection:
            calls.append(file.path)
            raise OSError('injected workbook knowledge registration failure')
        return await read_model(self, thread_id, file, model)

    monkeypatch.setattr(ReportWorkflowRuntime, '_read_identity_model', unavailable)

    async def inspect(report):
        index = await report.editor.trace.require_index(report.context)
        assert index.knowledge_registration_status == 'unavailable'
        assert len(calls) == 1
        support = report.content['validation']['claimSupport']
        assert support and all(item['support']['supportStatus'] == 'unverified' for item in support)
        output = Path('/tmp') / f'smart-reporting-workbook-registration-fault-{os.getpid()}'
        shutil.copytree(report.evidence_dir, output / 'native', dirs_exist_ok=True)
        (output / 'evidence.json').write_text(json.dumps({'injectionCalls': len(calls),
            'knowledgeRegistrationStatus': index.knowledge_registration_status,
            'validation': report.content['validation'], 'httpDownloadsVerified': True,
            'businessApproval': 'not_performed'}, ensure_ascii=False, indent=2))

    async def exercise(*args, **kwargs):
        return await native(*args, **kwargs, after_report=inspect)

    monkeypatch.setattr(c02_native_delivery, 'exercise_c02_native_delivery', exercise)
    await test_report_issue_c02.test_c02_published_ratio_replaces_real_project_mean_and_rejects_70_expectation(
        basis_context, receipt_snapshot, monkeypatch, ['xlsx'])


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
    runtime._basis_execution_context = AsyncMock(return_value=SimpleNamespace(basis=SimpleNamespace(id="basis-test")))
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
    assert captured["report_basis_id"] == "basis-test"
    assert "effective_profile_hash" not in captured
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
    quality_record: bool = False, registered_result: bool = False, native_document: bool = False,
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
    registered_tables = ()
    registered_fact_files = {}
    report_basis_id = "basis-test"
    if registered_result:
        from smart_reporting.reporting.semantics.analysis_facts import (
            build_registered_analysis_bundle,
        )
        from smart_reporting.reporting.trace.table_builder import build_analysis_tables

        from .test_registered_analysis_facts import analysis_inputs

        analysis, context, result = analysis_inputs()
        report_basis_id = context.basis_id
        result = result.model_copy(update={'dataset_ids': ('dataset-url-abc0001',)})
        context = context.model_copy(update={'calculations': (context.calculations[0].model_copy(update={'results': (result,)}),)})
        bundle = build_registered_analysis_bundle(analysis, context, ())
        path = 'facts/registered.json'
        files[path] = bundle.model_dump_json(by_alias=True).encode()
        registered_fact_files = {analysis.analysis_id: _identity(path, files[path], 'application/json')}
        trace, table_markdown = build_analysis_tables(bundle, fact_file_resource_id=derive_resource_id(path))[0]
        registered_tables = (trace,)
        heading = '# Report\n\n'
        if native_document:
            heading += '[[section:overview]]\n\n## 1. 经营概览\n\n'
        markdown = (heading + table_markdown).encode()
        files['reports/report.md'] = markdown
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
    index = build_csv_trace_index(report_basis_id=report_basis_id,
        handles=(handle,),
        lineage=(lineage,),
        report_id="report-1",
        revision=1,
        workflow_run_id="workflow-run",
        markdown_file=_identity("reports/report.md", markdown, "text/markdown"),
        table_source_files=(() if table_source_identity is None else (table_source_identity,))
        + ((_identity(denominator_path, files[denominator_path], "application/json"),) if denominator or population else ()),
        fact_files=({"analysis_001": _identity(denominator_path, files[denominator_path], "application/json")}
                    if denominator or population else registered_fact_files or None),
        subject_bindings=() if subject is None else (subject,),
        server_table_traces=registered_tables + (() if not source_cell else (TableTraceV1.model_validate({
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
                "report_basis_id": "basis-test",
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
@pytest.mark.parametrize("fault", ["state", "evaluate", "chart_evaluate", "table_evaluate", "semantic_evaluate", "heading_projection", "standard_proof_sources", "overview_evaluate", "runtime_state", "quality_source_selection", "registered_claim_support", "registered_narrative_support", "registered_question_coverage", "registered_answer_provider", "registered_overview", "knowledge_authorization", "revision_quality_notice", "write", "read"])
async def test_quality_record_failure_preserves_index_and_http_downloads(tmp_path, monkeypatch, fault):
    from smart_reporting.reporting.trace import quality_bundle

    if fault in {'registered_narrative_support', 'registered_claim_support', 'registered_question_coverage', 'registered_answer_provider', 'registered_overview'}:
        from .test_registered_claim_support import native_quality_inputs

        runtime, arguments, scope, durable, _, _, files, index = await native_quality_inputs(
            tmp_path, publication_fixture=True)
        if fault == 'registered_narrative_support':
            from smart_reporting.reporting.trace.contracts_v1 import NarrativeReferenceV1, SubjectBindingV1

            narrative = NarrativeReferenceV1(offset=0, claimId='narr-http', basisId=index.report_basis_id,
                period={'start': '2026-11-01', 'end': '2026-12-01'}, statementSha256='a' * 64)
            subject = SubjectBindingV1(subjectId='sub-' + 'a' * 16, subjectKind='text_claim',
                locator={'sectionId': 'section_001'}, subjectSha256='a' * 64, claimId=narrative.claim_id,
                narrativeReference=narrative)
            index = index.model_copy(update={'subject_bindings': (*index.subject_bindings, subject)})
        if fault == 'registered_answer_provider':
            from smart_reporting.reporting.semantics.request_types import ReportQuestion
            from smart_reporting.reporting.workflow.questions import request_questions

            required = request_questions('核对预算', questions=(ReportQuestion(id='q-budget', text='预算是多少？'),))
            durable.payload['questionSpecs'] = required.model_dump(mode='json', by_alias=True)

            async def unavailable_native_provider(_context):
                raise OSError('injected registered answer provider failure')

            runtime.registered_answer_plan_provider = unavailable_native_provider
    else:
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
    runtime._basis_execution_context = AsyncMock(return_value=SimpleNamespace(basis=SimpleNamespace(id=index.report_basis_id)))
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    monkeypatch.setattr(publication_module, "build_csv_trace_index", lambda **_kwargs: index)
    if fault == "knowledge_authorization":
        from smart_reporting.reporting.workflow.runtime import business_evidence

        async def failed_knowledge_authorization(*args, **kwargs):
            raise OSError("knowledge authorization unavailable")
        monkeypatch.setattr(business_evidence, "resolve_runtime_knowledge", failed_knowledge_authorization)
    elif fault in {"evaluate", "chart_evaluate", "table_evaluate", "semantic_evaluate", "overview_evaluate"}:
        def fail(*_args, **_kwargs):
            raise RuntimeError("injected quality evaluation failure")
        monkeypatch.setattr(quality_bundle, {"evaluate": "evaluate_quality_bundle", "chart_evaluate": "evaluate_chart_quality", "table_evaluate": "evaluate_table_quality", "semantic_evaluate": "evaluate_semantic_alignment", "overview_evaluate": "build_management_overview"}[fault], fail)
    elif fault == 'registered_overview':
        def fail(*_args, **_kwargs):
            raise RuntimeError('injected native overview failure')
        monkeypatch.setattr(quality_bundle, 'build_registered_management_overview', fail)
    elif fault == "heading_projection":
        from smart_reporting.reporting.trace import claim_semantics

        def fail(*_args, **_kwargs):
            raise RuntimeError("injected semantic heading projection failure")
        monkeypatch.setattr(claim_semantics, "project_semantic_headings", fail)
    elif fault in {'registered_claim_support', 'registered_narrative_support'}:
        from smart_reporting.reporting.trace import registered_claims

        def fail(*_args, **_kwargs):
            raise RuntimeError('injected registered claim support failure')
        monkeypatch.setattr(registered_claims, fault, fail)
    elif fault == 'registered_question_coverage':
        from smart_reporting.reporting.semantics import question_coverage

        def fail(*_args, **_kwargs):
            raise RuntimeError('injected registered question coverage failure')
        monkeypatch.setattr(question_coverage, 'evaluate_registered_question_coverage', fail)
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
    execution_options = {}
    if fault == 'revision_quality_notice':
        from smart_reporting.reporting.workflow import revision_execution

        execution = SimpleNamespace(execution_run_id='revision-execution', basis_id=index.report_basis_id)
        monkeypatch.setattr(revision_execution, 'require_revision_execution', AsyncMock(return_value=durable))
        runtime._apply_durable_command = AsyncMock(side_effect=OSError('injected revision quality notice failure'))
        def failed_quality(*args, **kwargs):
            raise OSError('injected revision quality evaluation failure')
        monkeypatch.setattr(quality_bundle, 'evaluate_quality_bundle', failed_quality)
        execution_options = {'execution': execution}
    identity = await runtime._write_trace_index(
        "reports/artifact-manifest.json", report_basis_id=index.report_basis_id, handles=(), lineage=(),
        markdown_artifact=_identity("reports/report.md", files["reports/report.md"], "text/markdown"),
        revision=1, run_context=SimpleNamespace(run_id="report-1"),
        markdown=files["reports/report.md"].decode(), **execution_options,
    )
    if fault in {"overview_evaluate", 'registered_answer_provider', 'registered_overview'}:
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
        if fault in {'registered_answer_provider', 'registered_overview'}:
            assert quality.registered_management_overview is not None
            if fault == 'registered_overview':
                assert quality.registered_management_overview.status == 'unavailable'
                assert quality.claim_support[0].support_status == 'supported'
        else:
            assert quality.management_overview.status == "unavailable"
        assert any(issue.code == ('registered_answer_plan_unavailable'
            if fault == 'registered_answer_provider' else 'management_overview_unavailable') for issue in quality.issues)
    else:
        assert identity.sha256 == hashlib.sha256(encode_trace_index(index)).hexdigest()
    if fault == 'revision_quality_notice':
        runtime._apply_durable_command.assert_awaited_once()
        assert runtime._apply_durable_command.call_args.args[1].name == 'record_warnings'
        assert state == {}
    elif fault not in {"runtime_state", "overview_evaluate", "registered_overview"}:
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
    runtime._basis_execution_context = AsyncMock(return_value=SimpleNamespace(basis=SimpleNamespace(id="basis-test")))
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    monkeypatch.setattr(publication_module, "build_csv_trace_index", lambda **_: index)
    identity = await runtime._write_trace_index("reports/report.manifest.json", report_basis_id="basis-test", handles=(), lineage=(),
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
        "reportBasisId",
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
@pytest.mark.parametrize('fault', ['layout_audit', 'slide_projection'])
async def test_http_pptx_download_survives_generated_artifact_audit_exception(tmp_path, monkeypatch, fault):
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
    if fault == 'slide_projection':
        # 已生成文件仍存在；重新核对正式摘要时失败，不得丢弃其实际身份或下载资格。
        from smart_reporting.reporting.workflow.runtime import slides as slides_module

        def unavailable_projection(*args, **kwargs):
            raise ValueError('injected registered result projection failure')

        monkeypatch.setattr(slides_module, 'build_slide_outline', unavailable_projection)
        original_identity = rendered['pptxSha256'], rendered['pptxSize']
        rendered = await runtime._render_pptx(context, content, outline)
        assert rendered['validation']['ok'] is False
        assert (rendered['pptxSha256'], rendered['pptxSize']) == original_identity
        assert 'pptx_generation_failed' in {item['code'] for item in rendered['validation']['issues']}
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
@pytest.mark.parametrize('issue_code', ['pptx_layout_audit', 'pptx_generation_failed', 'pptx_validation_receipt_unavailable'])
async def test_http_pptx_publication_keeps_link_when_layout_audit_fails(monkeypatch, issue_code):
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
            "validation": {"ok": False, "issues": [{"code": issue_code}]},
            "validationIssues": [{"code": issue_code, "message": "版式溢出"}],
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
    assert output["validationIssues"][0]["code"] == issue_code
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
    "lineage_runtime", "editor_snapshot", "revision_editor_input", "editor_context", "editor_state_read", "editor_scope",
    "table_source_missing", "table_source_changed", "source_cell_missing", "source_cell_changed", "denominator_missing", "denominator_changed", "population_missing", "population_changed",
    "quality_record_missing", "quality_record_changed",
    "registered_result_missing", "registered_result_changed",
])
async def test_http_publication_never_blocks_links_on_lineage_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    from smart_reporting.report_editor import trace_revisions
    from smart_reporting.reporting.workflow.runtime.base import merge_publication_issues

    table_source_fault = fault.startswith(("table_source_", "source_cell_", "denominator_", "population_"))
    runtime, arguments, scope, durable, artifacts, grants, files, index = await _publication_fixture(
        tmp_path, table_source=table_source_fault, source_cell=fault.startswith("source_cell_"), denominator=fault.startswith("denominator_"), population=fault.startswith("population_"), quality_record=fault.startswith("quality_record_"),
        registered_result=fault.startswith("registered_result_"),
    )
    manifest_path = arguments["output"]["artifactManifest"]["path"]
    workspace = runtime.workspace_service
    original_read = workspace.read_limited_regular_file
    if fault.startswith("registered_result_"):
        source_path = 'facts/registered.json'
        assert index.tables[0].cells[0].fact_refs[0].json_pointer == '/metricContext/calculations/0/results/0'
        if fault == 'registered_result_missing':
            await workspace.adelete_file(scope.workspace_key, source_path)
        else:
            await workspace.awrite_bytes(scope.workspace_key, source_path, b'{}', overwrite=True)
    elif fault.startswith("quality_record_"):
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
    elif fault == "revision_editor_input":
        arguments['output']['editorAvailable'] = False
        arguments['output']['publicationGate'] = {'formalReleaseAllowed': False, 'issues': [
            {'code': 'revision_publication_editor_job_unavailable', 'message': '编辑任务身份未核实。'}]}
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
    if fault in {"editor_snapshot", "revision_editor_input", "editor_context", "editor_state_read", "editor_scope"}:
        assert "editor" not in result
        assert result["publicationIssues"][-1]["code"] == {
            "editor_snapshot": "report_editor_snapshot_unavailable",
            "revision_editor_input": "report_editor_snapshot_unavailable",
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
    runtime._basis_execution_context = AsyncMock(return_value=SimpleNamespace(basis=SimpleNamespace(id="basis-test")))
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    monkeypatch.setattr(publication_module, "build_csv_trace_index", lambda **_kwargs: index)
    identity = await runtime._write_trace_index(
        "reports/artifact-manifest.json", report_basis_id="basis-test", handles=(), lineage=(),
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
@pytest.mark.parametrize('notice_unavailable', [False, True])
async def test_chart_fact_binding_failure_preserves_index_and_http_downloads(tmp_path, monkeypatch, notice_unavailable):
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
    def read_notice_state(_):
        if notice_unavailable:
            raise OSError('injected chart notice storage failure')
        return state
    runtime._state = read_notice_state
    runtime._basis_execution_context = AsyncMock(return_value=SimpleNamespace(basis=SimpleNamespace(id="basis-test")))
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    monkeypatch.setattr(publication_module, "build_csv_trace_index", lambda **_: index)
    fail = AsyncMock(side_effect=RuntimeError("injected chart fact binding failure"))
    monkeypatch.setattr(chart_facts, "recover_chart_fact_refs", fail)
    identity = await runtime._write_trace_index("reports/report.manifest.json", report_basis_id="basis-test", handles=(), lineage=(),
        markdown_artifact=_identity("reports/report.md", files["reports/report.md"], "text/markdown"),
        revision=1, run_context=SimpleNamespace(run_id="report-1"))
    fail.assert_awaited_once()
    saved = RevisionTraceIndexV1.model_validate_json(await runtime.workspace_service.read_limited_regular_file(
        scope.workspace_key, identity.path, max_bytes=identity.size))
    assert saved.chart_traces[0].fact_refs == ()
    if not notice_unavailable:
        assert state["report_quality_issues"][0]["code"] == "chart_fact_binding_unavailable"
    runtime._state = lambda _: state
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
    runtime._basis_execution_context = AsyncMock(return_value=SimpleNamespace(basis=SimpleNamespace(id="basis-test")))
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    monkeypatch.setattr(publication_module, "build_csv_trace_index", lambda **_: index)

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected answer reviewer failure")

    monkeypatch.setattr(quality_bundle, "evaluate_answer_review", fail)
    identity = await runtime._write_trace_index(
        "reports/artifact-manifest.json",
        report_basis_id="basis-test", handles=(),
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
@pytest.mark.parametrize('issue_code', ['xlsx_generation_failed', 'xlsx_validation_receipt_unavailable',
    'pptx_generation_failed', 'pptx_validation_receipt_unavailable', 'refresh_completion_record_unavailable',
    'policy_adoption_completion_record_unavailable'])
@pytest.mark.parametrize('delivery_format', ['xlsx', 'pptx'])
async def test_xlsx_revision_validation_fault_preserves_http_download(tmp_path, issue_code, delivery_format):
    """登记刷新交付只读恢复的完成记录缺失；身份和恢复执行另由PG节点核验。"""
    runtime, arguments, scope, _, artifacts, _, _, _ = await _publication_fixture(tmp_path)
    content = b'PK isolated-workbook-identity-fixture'
    path = f'reports/revision-office.{delivery_format}'
    await runtime.workspace_service.awrite_bytes(scope.workspace_key, path, content)
    issue = {'code': issue_code, 'message': '工作簿已生成，验收或来源登记未完成。'}
    arguments['output'].update({'deliveryFormat': delivery_format, f'{delivery_format}Path': path,
        f'{delivery_format}Size': len(content), f'{delivery_format}Sha256': hashlib.sha256(content).hexdigest(),
        'validation': {'ok': False, 'issues': [issue]}, 'validationIssues': [issue]})
    result = await runtime.issue_http_publication(**arguments)
    assert result['validation']['ok'] is False
    assert any(item['code'] == issue_code for item in result['validationIssues'])
    assert result[delivery_format]['downloadUrl']
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(
        runtime.download_grants, artifacts, workspace_service=runtime.workspace_service)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        downloaded = await client.get(result[delivery_format]['downloadUrl'])
    assert downloaded.status_code == 200 and downloaded.content == content


@pytest.mark.anyio
@pytest.mark.parametrize('issue_code', [
    'document_validation_receipt_unavailable', 'document_result_checkpoint_unavailable',
    'refresh_completion_record_unavailable',
    'policy_adoption_completion_record_unavailable', 'policy_adoption_pdf_artifact_unavailable',
    'policy_adoption_word_artifact_unavailable',
    'refresh_pdf_artifact_unavailable',
    'report_pdf_checkpoint_unavailable', 'report_word_checkpoint_unavailable',
    'report_pdf_receipt_mismatch', 'report_word_receipt_mismatch',
])
async def test_document_revision_validation_fault_preserves_http_downloads(tmp_path, issue_code):
    """登记独立文档渲染的新增签发失败点；真实渲染/PG故障由刷新节点验证。"""
    runtime, arguments, _, _, artifacts, _, files, _ = await _publication_fixture(tmp_path)
    issue = {'code': issue_code, 'message': '文档已生成，验收或完成状态尚需复核。'}
    arguments['output'].update({'deliveryFormat': 'document',
        'validation': {'ok': False, 'issues': [issue]}, 'validationIssues': [issue]})
    result = await runtime.issue_http_publication(**arguments)
    assert result['validation']['ok'] is False
    assert any(item['code'] == issue_code for item in result['validationIssues'])
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(
        runtime.download_grants, artifacts, workspace_service=runtime.workspace_service)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        for label, suffix in (('pdf', 'pdf'), ('word', 'docx')):
            downloaded = await client.get(result[label]['downloadUrl'])
            assert downloaded.status_code == 200
            assert downloaded.content == files[f'reports/report.{suffix}']


@pytest.mark.anyio
@pytest.mark.parametrize('damaged', ['pdf', 'word'])
async def test_document_recovery_drops_changed_format_but_issues_other_download(tmp_path, damaged):
    """新口径复用的文档恢复边界：只撤回损坏格式，另一实际文件照常HTTP下载。"""
    runtime, arguments, scope, _, artifacts, _, files, _ = await _publication_fixture(tmp_path)
    output = arguments['output']
    await runtime.workspace_service.awrite_bytes(scope.workspace_key, output[f'{damaged}Path'], b'changed', overwrite=True)
    for suffix in ('Path', 'Size', 'Sha256'):
        output.pop(f'{damaged}{suffix}')
    issue = {'code': f'report_{damaged}_artifact_unavailable', 'message': '已登记格式身份变化，仅保留其他实际可读文件。'}
    output.update({'deliveryFormat': 'document', 'validation': {'ok': False, 'issues': [issue]}, 'validationIssues': [issue]})
    result = await runtime.issue_http_publication(**arguments)
    retained, extension = ('word', 'docx') if damaged == 'pdf' else ('pdf', 'pdf')
    assert not result.get(damaged) and result['validation']['ok'] is False
    assert any(item['code'] == issue['code'] for item in result['validationIssues'])
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(
        runtime.download_grants, artifacts, workspace_service=runtime.workspace_service)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        downloaded = await client.get(result[retained]['downloadUrl'])
    assert downloaded.status_code == 200 and downloaded.content == files[f'reports/report.{extension}']


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["source_mapping", "source_marking", "source_marking_unchanged", "source_mapping_drop", "inspection", "revision_lookup", "revision_reservation", "persistence", "context_write", "editor_grant"])
async def test_workbook_editor_save_faults_keep_verified_downloads(tmp_path, monkeypatch, fault):
    from io import BytesIO
    from zipfile import ZipFile

    from smart_reporting.report_editor import workbook as workbook_module
    from smart_reporting.reporting.tests.test_workbook_editor import _bytes

    runtime, _, scope, durable, artifacts, _, _, _ = await _publication_fixture(tmp_path)
    original = _bytes(12)
    stream = BytesIO()
    mapping = {"sources": {"cells": [{"cell": "A1", "exactValue": "12"}], "claims": [{
        "support": {"kind": "recommendation", "supportStatus": "supported", "evidenceRefs": ["old-background"]}}]}}
    with ZipFile(BytesIO(original)) as package, ZipFile(stream, "w") as target:
        for info in package.infolist():
            target.writestr(info, package.read(info.filename))
        target.writestr("smart-reporting/source-mapping.json", json.dumps(mapping))
    source = stream.getvalue()
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
    elif fault in {"source_marking", "source_marking_unchanged", "source_mapping_drop"}:
        monkeypatch.setattr(editor, "_mark_sources_unverified", lambda *_: (_ for _ in ()).throw(ValueError("mapping write unavailable")))
        if fault == "source_mapping_drop":
            monkeypatch.setattr(editor, "_drop_source_mapping", lambda *_: (_ for _ in ()).throw(ValueError("mapping removal unavailable")))
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
            "column": 0, "writeValue": True, "cell": {"value": 99}}]}] if fault != "source_marking_unchanged" else []})

    assert result["xlsx"]["downloadUrl"]
    if fault == "revision_reservation":
        assert any(issue["code"] == "report_editor_revision_lookup_failed" for issue in result["validation"]["issues"])
    assert result["validation"]["ok"] is False
    assert result["validation"]["issues"]
    if fault == "source_mapping_drop":
        assert "workbook_source_mapping_unavailable" in {issue["code"] for issue in result["validation"]["issues"]}
    assert (await runtime.workspace_service.afile_bytes(scope.workspace_key, source_path))[0] == source
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(
        runtime.download_grants, artifacts, workspace_service=runtime.workspace_service,
    )))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        response = await client.get(result["xlsx"]["downloadUrl"])
    with ZipFile(BytesIO(response.content)) as package:
        if "smart-reporting/source-mapping.json" in package.namelist() and fault != "source_mapping_drop":
            current = json.loads(package.read("smart-reporting/source-mapping.json"))
            assert all(item["support"]["supportStatus"] == "unverified" and not item["support"]["evidenceRefs"]
                for item in current["sources"].get("claims", []))
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == result["xlsx"]["sha256"]


@pytest.mark.anyio
@pytest.mark.parametrize('format_', ['xlsx', 'pptx'])
async def test_native_revision_notice_failure_keeps_actual_http_download(tmp_path, monkeypatch, format_):
    from io import BytesIO

    from pptx import Presentation

    from smart_reporting.report_editor import revision_notice, workbook
    from smart_reporting.report_editor.slides import ReportSlidesEditorService
    from smart_reporting.reporting.tests.test_workbook_editor import _bytes

    runtime, _, scope, _, artifacts, _, _, _ = await _publication_fixture(tmp_path)
    if format_ == 'xlsx':
        content = _bytes(12)
        service_type = workbook.ReportWorkbookEditorService
    else:
        deck = Presentation()
        deck.slides.add_slide(deck.slide_layouts[6])
        stream = BytesIO()
        deck.save(stream)
        content = stream.getvalue()
        service_type = ReportSlidesEditorService
    path = f'reports/notice-source.{format_}'
    await runtime.workspace_service.awrite_bytes(scope.workspace_key, path, content)
    context = ReportEditorContext(reportId='report-1', revision=2, jobId='job-1', workflowRunId='workflow-run',
        markdownPath='reports/report.md', job={'jobId': 'job-1'}, scope=scope.as_state(), deliveryFormat=format_,
        **{f'{format_}Path': path, f'{format_}Size': len(content), f'{format_}Sha256': hashlib.sha256(content).hexdigest()})
    editor = service_type(state_repository=runtime.state_repository, workspace_registry=runtime.workspace_registry,
        workspace=runtime.workspace_service, editor_grants=runtime.editor_grants,
        artifact_persistence=runtime.artifact_persistence, download_grants=runtime.download_grants,
        public_base_url='http://reports.test')
    editor.context_for_session = AsyncMock(return_value=context)
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(kwargs)
        raise OSError('injected visible revision notice failure')

    if format_ == 'xlsx':
        monkeypatch.setattr(workbook, 'add_workbook_revision_notice', unavailable)
    else:
        monkeypatch.setattr(revision_notice, 'add_slides_revision_notice', unavailable)
        monkeypatch.setattr(editor, '_run_engine', lambda *args, **kwargs: {'bytes': content, 'issues': []})
        monkeypatch.setattr(editor, '_render_pdf', lambda *args: b'%PDF-preview')
    result = await editor.save_revision(None, {'expectedSha256': getattr(context, f'{format_}_sha256')})
    assert len(calls) == 1 and calls[0]['parent_revision'] == 2
    code = f'{"workbook" if format_ == "xlsx" else "pptx"}_revision_notice_unavailable'
    assert code in {issue['code'] for issue in result['validation']['issues']}
    assert result['validation']['ok'] is False
    app = FastAPI()
    if format_ == 'pptx':
        from smart_reporting.report_editor.slides_api import create_report_slides_editor_router

        app.include_router(create_report_slides_editor_router(runtime.editor_grants, slides=editor,
            static_dir=tmp_path, cookie_secure=False))
    app.include_router(create_report_download_router(ReportDownloadHttpService(
        runtime.download_grants, artifacts, workspace_service=runtime.workspace_service)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        response = await client.get(result[format_]['downloadUrl'])
    assert response.status_code == 200
    assert len(response.content) == result[format_]['size']
    assert hashlib.sha256(response.content).hexdigest() == result[format_]['sha256']
    assert (await runtime.workspace_service.afile_bytes(scope.workspace_key, path))[0] == content


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


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['revoked', 'partial', 'backend_unavailable'])
async def test_http_publication_keeps_downloads_after_section_knowledge_recheck(tmp_path, monkeypatch, fault):
    """发布前知识核验新增失败点：旧解释不通过验收，已核验文件仍可下载。"""
    from smart_reporting.reporting.tests.test_dynamic_checkpoint import _coverage
    from smart_reporting.reporting.workflow.checkpoint import ReportingCheckpoint, SectionArtifact
    from smart_reporting.reporting.workflow.runtime import business_evidence

    runtime, arguments, scope, durable, artifacts, _, files, _ = await _publication_fixture(tmp_path)
    artifact = SectionArtifact(sectionCode='section_001', blocks=[{
        'blockId': 'b', 'markdown': '旧解释', 'claimIds': ['c']}], claims=[{
        'claimId': 'c', 'metricCode': 'budget', 'value': 1, 'periodBasis': '本期',
        'managementQuestion': '预算变化', 'currentPeriod': '本期', 'citationIds': ['citation_001']}],
        knowledgeReceiptIds=('knowledge-rules',))
    checkpoint = ReportingCheckpoint.model_validate({
        'revision': 1, 'phase': 'analysis', 'outlineHash': 'a' * 64,
        'profileCoverage': _coverage().model_dump(mode='json', by_alias=True),
        'evidenceManifest': {
            'evidence': [{'analysisId': 'analysis_001', 'summary': '预算',
                'datasetIds': ['dataset-1'], 'citationIds': ['citation_001'],
                'evidenceFiles': [{'path': 'facts.json', 'size': 1, 'sha256': 'a' * 64}]}],
            'datasetSemantics': [{'datasetId': 'dataset-1', 'rowGrain': 'month',
                'duplicateResolution': 'not_applicable'}]},
        'completedSections': [{'sectionCode': 'section_001', 'workItemHash': 'a' * 64,
            'artifactFile': {'path': 'section.json', 'size': 1, 'sha256': 'b' * 64}}],
    })
    durable.payload['workflowCheckpoint'] = checkpoint.model_dump(mode='json', by_alias=True)
    runtime._scope = lambda _: scope.as_state()
    runtime._state = lambda _: {}
    runtime._workflow_result = lambda _: {}
    runtime._read_identity_model = AsyncMock(return_value=artifact)
    runtime._verify_claim_fact_bindings = AsyncMock(return_value=([], []))
    runtime.quality_warning_service = None
    async def revalidate(*args, **kwargs):
        if fault == 'backend_unavailable':
            raise OSError('knowledge backend unavailable')
        if fault == 'partial':
            from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock

            return SectionArtifact.model_validate({**dict(artifact), 'knowledge_status': 'partial',
                'blocks': (artifact.blocks[0], ReportDraftBlock(blockId='withdrawn', knowledgeWithdrawn=True,
                    markdown='知识依据不可用，受影响解释暂不列示。')),
                'warnings': ({'code': 'report_section_knowledge_unavailable', 'message': '知识部分撤销'},)})
        return artifact.model_copy(update={'knowledge_status': 'unavailable', 'claims': (),
            'blocks': (artifact.blocks[0].model_copy(update={'claim_ids': (), 'markdown': '知识不可用'}),),
            'warnings': ({'code': 'report_section_knowledge_unavailable', 'message': '知识已撤销'},)})
    checked = AsyncMock(side_effect=revalidate)
    monkeypatch.setattr(business_evidence, 'revalidate_section_knowledge', checked)
    output = arguments['output']
    gate = await runtime._dataset_publication_gate(RunContext(run_id='workflow-run', session_id='workflow-session'), output)
    checked.assert_awaited_once()
    assert not gate['formalReleaseAllowed']
    assert any(item['code'] == 'report_section_knowledge_unavailable' for item in gate['issues'])
    assert any(item['code'] == 'report_section_knowledge_unavailable' for item in gate['warnings'])
    result = await runtime.issue_http_publication(**{**arguments, 'output': {**output, 'publicationGate': gate}})
    # issue_http_publication只返回签发结果；工作流持有原始门禁并合并签发问题。
    from smart_reporting.reporting.workflow.runtime.base import merge_publication_issues

    assert merge_publication_issues(gate, result.get('publicationIssues'))['formalReleaseAllowed'] is False
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        for kind, suffix in (('pdf', 'pdf'), ('word', 'docx')):
            response = await client.get(result[kind]['downloadUrl'])
            assert response.status_code == 200
            assert response.content == files[f'reports/report.{suffix}']


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_editor_knowledge_unavailable_preserves_export_links_and_dependency(tmp_path, monkeypatch):
    """登记编辑器导出知识核验失败点：保留文件交付和原始依赖身份。"""
    from smart_reporting.reporting.tests.test_report_editor_lineage_export import (
        test_export_revision_drops_lineage_but_still_issues_links_when_source_file_missing,
    )

    await test_export_revision_drops_lineage_but_still_issues_links_when_source_file_missing(
        tmp_path, "knowledge", monkeypatch)


@pytest.mark.anyio
async def test_knowledge_registration_failure_keeps_trace_index_and_http_downloads(tmp_path, monkeypatch):
    """新增签发步骤登记：知识注册后端异常仅登记不可用，不丢弃独立来源与下载。"""
    runtime, arguments, scope, _, artifacts, _, files, index = await _publication_fixture(tmp_path)
    runtime._scope = lambda _: scope.as_state()
    runtime.report_basis_service = SimpleNamespace(load_report_basis=AsyncMock(side_effect=OSError('registry unavailable')))
    runtime._build_drilldown_metrics = AsyncMock(return_value=())
    observed = []
    def build(**kwargs):
        observed.append(kwargs['knowledge_registration_status'])
        assert kwargs['knowledge_dependencies'] == ()
        return index.model_copy(update={'knowledge_registration_status': kwargs['knowledge_registration_status']})
    monkeypatch.setattr(publication_module, 'build_csv_trace_index', build)
    await runtime._write_trace_index('reports/report.manifest.json', report_basis_id=index.report_basis_id,
        handles=(), lineage=(), revision=index.revision, run_context=SimpleNamespace(run_id='workflow-run'),
        markdown_artifact=_identity('reports/report.md', files['reports/report.md'], 'text/markdown'))
    assert observed == ['unavailable']
    saved = RevisionTraceIndexV1.model_validate_json(await runtime.workspace_service.read_limited_regular_file(
        scope.workspace_key, 'reports/trace-index-v1.json', max_bytes=1024 * 1024))
    assert saved.knowledge_registration_status == 'unavailable'
    assert saved.datasets == index.datasets
    manifest = await register_trace_manifest(runtime.workspace_service, scope.workspace_key, saved, overwrite=True)
    output = {**arguments['output'], 'artifactManifest': manifest.model_dump(mode='json', by_alias=True)}
    result = await runtime.issue_http_publication(**{**arguments, 'output': output})
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        for kind, suffix in (('pdf', 'pdf'), ('word', 'docx')):
            response = await client.get(result[kind]['downloadUrl'])
            assert response.status_code == 200
            assert response.content == files[f'reports/report.{suffix}']


@pytest.mark.anyio
async def test_editor_revision_impact_failure_preserves_export_links(tmp_path, monkeypatch):
    from smart_reporting.reporting.tests.test_report_editor_lineage_export import (
        test_export_revision_drops_lineage_but_still_issues_links_when_source_file_missing,
    )

    await test_export_revision_drops_lineage_but_still_issues_links_when_source_file_missing(
        tmp_path, 'revision_impact', monkeypatch,
    )


@pytest.mark.anyio
@pytest.mark.parametrize('delivery_format', ['pptx', 'xlsx'])
@pytest.mark.parametrize('fault', ['editor_input_unavailable', 'analysis_context_invalid',
    'source_receipt_unavailable', 'policy_adoption_preparation_unavailable'])
async def test_revision_editor_input_failure_keeps_office_download(tmp_path, delivery_format, fault):
    runtime, arguments, scope, durable, artifacts, _, _, _ = await _publication_fixture(tmp_path)
    raw = b'office-http-identity-fixture'
    path = f'reports/revision-2/report.{delivery_format}'
    await runtime.workspace_service.awrite_bytes(scope.workspace_key, path, raw)
    content = {key: value for key, value in arguments['output'].items()
        if not key.startswith(('pdf', 'word'))}
    content.update({'deliveryFormat': delivery_format, f'{delivery_format}Path': path,
        f'{delivery_format}Size': len(raw), f'{delivery_format}Sha256': hashlib.sha256(raw).hexdigest(),
        'validation': {'ok': False, 'issues': [{'code': 'revision_publication_editor_job_unavailable',
            'message': '新修订编辑输入未核实。'}]}})
    if fault in {'editor_input_unavailable', 'source_receipt_unavailable', 'policy_adoption_preparation_unavailable'}:
        content['editorAvailable'] = False
        if fault == 'source_receipt_unavailable':
            content['validation']['issues'].append({'code': f'{delivery_format}_validation_receipt_unavailable',
                'message': '当前修订来源回执无法核验。'})
    else:
        content['analysisContextFile'] = {'path': 'foreign', 'size': 1, 'sha256': 'invalid'}
    result = await runtime.issue_http_publication(**{**arguments, 'output': content})
    assert 'editor' not in result
    assert result['validation']['ok'] is False
    if fault == 'source_receipt_unavailable':
        assert f'{delivery_format}_validation_receipt_unavailable' in {
            item['code'] for item in result['validation']['issues']}
    assert 'reportEditorContexts' not in durable.payload
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        response = await client.get(result[delivery_format]['downloadUrl'])
    assert response.status_code == 200 and response.content == raw
