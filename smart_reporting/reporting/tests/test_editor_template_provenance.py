"""来源摘要不泄露内部材料，不把生成分支冒充独立验收。"""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def template_delivery_case(tmp_path):
    """实际模板与成品走正式渲染/持久化/签发；状态仓储为隔离内存夹具。"""
    from smart_reporting.preferences.document_adapter import document_design
    from smart_reporting.reporting.delivery.publishing import (
        ReportArtifactPersistenceService,
        ReportDownloadGrantService,
    )

    from .delivery_fakes import InMemoryDownloadGrantRepository, InMemoryReportArtifactRepository
    from .test_editor_partial_delivery import delivery_editor
    from .test_editor_template_render import render_case

    source = await render_case(tmp_path / 'source')
    harness = await delivery_editor(tmp_path / 'editor', ('pdf', 'word'), set())
    editor = harness.editor
    current = harness.current.model_copy(update={'job': {**harness.current.job,
        '_documentContext': source.context.job['_documentContext'],
        '_formatDesigns': {format: document_design(value).compact()
            for format, value in source.context.job['_formatPreferences'].items()},
        '_formatPreferences': source.context.job['_formatPreferences']}})
    durable = harness.repository.durable
    durable.payload['reportEditorContexts'][str(current.revision)] = current.model_dump(mode='json', by_alias=True)
    durable.payload['requestMaterials'] = {'fileInputs': [],
        'templateInput': source.source.identity.model_dump(mode='json', by_alias=True)}
    editor.state_repository.get_run = AsyncMock(return_value={'database': current.scope['database'],
        'company_id': current.scope['companyId']})
    await editor.workspace.awrite_bytes(harness.thread, source.source.identity.path, source.original)
    artifacts = InMemoryReportArtifactRepository()
    editor.artifact_persistence = ReportArtifactPersistenceService(artifacts, editor.workspace)
    editor.download_grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
    editor.public_base_url = 'http://reports.test'
    document = await editor.read_document(current)
    return SimpleNamespace(editor=editor, current=current, document=document,
        artifacts=artifacts, harness=harness, source=source)


def receipt():
    return {'ok': False, 'issues': [{'code': 'layout_unverified', 'message': '布局待复核'}],
        'sourceContentSha256': 'c' * 64,
        'layoutProvenance': {'version': 1,
            'template': {'filename': '模板.docx', 'size': 12, 'sha256': 'a' * 64, 'path': '/private/template'},
            'contentSha256': 'c' * 64, 'layoutValidation': 'unverified', 'undeclaredSamples': 'not_assessed',
            'formats': {format: {'artifact': {'size': 20, 'sha256': sha * 64, 'path': '/private/output'},
                'layoutSource': 'uploaded_template', 'signatureSource': 'frozen_revision_preferences',
                'generatedDate': '2026-09-16', 'dateFormatSource': 'frozen_revision_preferences',
                'descriptionSource': 'editor_design', 'placement': 'declared_template_slot',
                'signatureLayoutSource': 'template', 'templateSampleStatus': 'replaced',
                'signatureReadback': 'passed' if format == 'word' else 'unverified',
                'bodyReadback': 'structure_verified' if format == 'word' else 'sample_only'}
                for format, sha in [('word', 'b'), ('pdf', 'd')]}}}


def test_public_provenance_only_describes_verified_delivered_identity_and_strips_internal_fields():
    from smart_reporting.report_editor.template_provenance import public_validation

    original = receipt()
    before = deepcopy(original)
    result = public_validation(original, {'word': {'size': 20, 'sha256': 'b' * 64}})
    source = result['layoutProvenance']
    assert set(source['formats']) == {'word'}
    assert source['formats']['word']['signatureReadback'] == 'passed'
    assert 'path' not in source['template'] and 'path' not in source['formats']['word']['artifact']
    assert set(result) == {'ok', 'issues', 'layoutProvenance'}
    assert original == before


@pytest.mark.parametrize('fault', ['identity', 'content', 'enum', 'date', 'filename', 'version'])
def test_invalid_source_is_soft_warning_and_never_asserts_verified_layout(fault):
    from smart_reporting.report_editor.template_provenance import public_validation

    value = receipt()
    summary = value['layoutProvenance']
    if fault == 'identity':
        summary['formats']['word']['artifact']['sha256'] = 'f' * 64
    elif fault == 'content':
        summary['contentSha256'] = 'f' * 64
    elif fault == 'enum':
        summary['layoutValidation'] = 'passed'
    elif fault == 'date':
        summary['formats']['word']['generatedDate'] = '2026-02-30'
    elif fault == 'filename':
        summary['template']['filename'] = '/private/template.docx'
    else:
        summary['version'] = True
    result = public_validation(value, {'word': {'size': 20, 'sha256': 'b' * 64}})
    assert 'layoutProvenance' not in result
    assert result['ok'] is False
    assert result['issues'][-1]['code'] == 'report_editor_layout_provenance_unavailable'


def test_old_receipt_without_provenance_stays_readable_and_does_not_invent_sources():
    from smart_reporting.report_editor.template_provenance import public_validation

    assert public_validation({'ok': True, 'issues': [], 'template': {'path': '/private'}}, {}) == {
        'ok': True, 'issues': []}


def test_retry_falls_back_to_original_receipt_and_filters_out_failed_persistence():
    from smart_reporting.report_editor.template_provenance import public_validation

    original = receipt()
    result = public_validation({'ok': False, 'issues': []}, {'pdf': {'size': 20, 'sha256': 'd' * 64}},
        fallback=original)
    assert set(result['layoutProvenance']['formats']) == {'pdf'}
    assert result['layoutProvenance']['formats']['pdf']['bodyReadback'] == 'sample_only'
    assert result['issues'] == []


def test_retry_reprojects_safe_delivery_record_against_original_frozen_content():
    from smart_reporting.report_editor.template_provenance import public_validation

    original = receipt()
    identities = {'word': {'size': 20, 'sha256': 'b' * 64}}
    first = public_validation(original, identities)
    again = public_validation(first, identities, fallback=original)
    assert again['layoutProvenance'] == first['layoutProvenance']
    assert again['issues'] == first['issues']


def test_recovered_format_uses_original_receipt_instead_of_previous_partial_delivery():
    from smart_reporting.report_editor.template_provenance import public_validation

    original = receipt()
    first = public_validation(original, {'pdf': {'size': 20, 'sha256': 'd' * 64}})
    recovered = public_validation(first, {'pdf': {'size': 20, 'sha256': 'd' * 64},
        'word': {'size': 20, 'sha256': 'b' * 64}}, fallback=original)
    assert set(recovered['layoutProvenance']['formats']) == {'pdf', 'word'}
    assert recovered['layoutProvenance']['formats']['word']['signatureReadback'] == 'passed'


@pytest.mark.parametrize('value,fallback', [({'ok': False, 'issues': 1}, None),
    ({'ok': False, 'issues': []}, 1)])
def test_corrupt_legacy_validation_cannot_raise_after_download_signing(value, fallback):
    from smart_reporting.report_editor.template_provenance import public_validation

    result = public_validation(value, {}, fallback=fallback)
    assert result['ok'] is False
    assert 'layoutProvenance' not in result
    assert result['issues'][-1]['code'] == 'report_editor_layout_provenance_unavailable'


@pytest.mark.parametrize('override,source', [({}, 'frozen_revision_preferences'),
    ({'signature': None}, 'editor_reset'),
    ({'signature': {'dateFormat': 'slash', 'description': '本次修改'}}, 'editor_design')])
def test_builder_distinguishes_frozen_explicit_and_reset_sources(override, source):
    from smart_reporting.report_editor.template_provenance import build_template_provenance

    job = {'_formatPreferences': {'word': {'common': {'signer': '冻结署名'}}},
        '_documentContext': {'generatedDate': '2026-09-16'}, '_reportDesign': override}
    summary = build_template_provenance(job=job, configuration=None,
        template={'filename': '模板.docx', 'size': 12, 'sha256': 'a' * 64}, content_sha256='c' * 64,
        identities={'word': {'size': 20, 'sha256': 'b' * 64}}, bindings={'word': {
            'placement': 'body_end', 'layoutSource': 'generated_fallback', 'templateSampleStatus': 'no_declared_slot'}},
        readbacks={})
    entry = summary['formats']['word']
    assert entry['dateFormatSource'] == source and entry['descriptionSource'] == source
    assert entry['signatureSource'] == 'frozen_revision_preferences'
    assert entry['signatureReadback'] == entry['bodyReadback'] == 'unverified'
    assert summary['layoutValidation'] == 'unverified'


@pytest.mark.anyio
async def test_retry_retains_original_sources_but_only_for_persisted_formats(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor import ReportEditorContext
    from smart_reporting.reporting.delivery.publishing import (
        ReportDownloadHttpService,
        create_report_download_router,
    )
    from smart_reporting.reporting.workflow.scope import resolve_reporting_workflow_scope

    case = await template_delivery_case(tmp_path)
    editor = case.editor
    try:
        first = await editor.export_revision(case.current, expected_sha256=case.document.sha256)
        durable = await editor.state_repository.get(case.current.workflow_run_id)
        context = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['3'])
        original = editor.artifact_persistence.persist_available

        async def only_pdf(**kwargs):
            return await original(**{**kwargs, 'artifacts': tuple(spec for spec in kwargs['artifacts'] if spec.artifact == 'pdf')})

        monkeypatch.setattr(editor.artifact_persistence, 'persist_available', only_pdf)
        scope = resolve_reporting_workflow_scope(run_id=context.workflow_run_id, session_id=context.scope['sessionId'],
            user_id=context.scope['userId'], stored_scope=context.scope)
        validation = context.job['validation']
        for _ in range(2):
            retried = await editor._retry_export_delivery(context, scope=scope, validation=validation,
                session_capabilities=None, artifact_persistence=editor.artifact_persistence,
                download_grants=editor.download_grants, editor_grants=editor.editor_grants,
                public_base_url=editor.public_base_url)
            assert retried['revision'] == 3 and 'pdf' in retried and 'word' not in retried
            source = retried['validation']['layoutProvenance']
            assert set(source['formats']) == {'pdf'}
            assert source['formats']['pdf'] == first['validation']['layoutProvenance']['formats']['pdf']
            assert source['contentSha256'] == case.document.sha256
            assert not any(issue['code'] == 'report_editor_layout_provenance_unavailable'
                for issue in retried['validation']['issues'])
            validation = retried['validation']
        monkeypatch.setattr(editor.artifact_persistence, 'persist_available', original)
        recovered = await editor._retry_export_delivery(context, scope=scope, validation=validation,
            session_capabilities=None, artifact_persistence=editor.artifact_persistence,
            download_grants=editor.download_grants, editor_grants=editor.editor_grants,
            public_base_url=editor.public_base_url)
        assert set(recovered['validation']['layoutProvenance']['formats']) == {'word', 'pdf'}
        assert recovered['validation']['layoutProvenance']['formats']['word'] == first['validation']['layoutProvenance']['formats']['word']
        app = FastAPI()
        app.include_router(create_report_download_router(ReportDownloadHttpService(editor.download_grants, case.artifacts)))
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
            actual = await client.get(recovered['pdf']['downloadUrl'])
        import hashlib
        assert actual.status_code == 200
        assert hashlib.sha256(actual.content).hexdigest() == source['formats']['pdf']['artifact']['sha256']
    finally:
        await editor.aclose()
