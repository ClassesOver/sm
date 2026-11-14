"""真实三格式DPI回读经过HTTP、SQL留存与批准准备，仍不得冒充完整验收。"""

import base64
import json
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update

from smart_reporting.management.api import SESSION_COOKIE, csrf_token
from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.format_preferences import FormatPreferenceService
from smart_reporting.management.models import ManagementError
from smart_reporting.management.preference_verification import PreferenceVerificationHandoffService
from smart_reporting.management.preference_verification_api import (
    create_preference_verification_router,
)
from smart_reporting.management.repository import preference_verification_results
from smart_reporting.management.settings import ManagementSettings
from smart_reporting.preferences.models import FormatPreferences
from smart_reporting.report_editor.repository import SqlAlchemyReportEditorRepository
from smart_reporting.report_editor.service import ReportEditorGrantService
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    SqlAlchemyReportArtifactRepository,
    report_artifact_chunks_v1,
    report_artifact_files_v1,
)
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_report_preflight import native_case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]
OUTPUT = Path('output/system-config-preferences/chart-dpi-persistence')
ROOT = '/management/api/v1/configuration/preferences/report-verification'


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('fault', ['valid', 'word_over_target', 'retained_drift'])
async def test_actual_dpi_evidence_survives_http_sql_and_independent_prepare(auth_context, tmp_path, monkeypatch, fault):
    from docx import Document
    from docx.shared import Inches

    from smart_reporting.management import preference_preflight, preference_report_preflight

    auth, repository, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    admin = (await auth.login('admin', OLD_PASSWORD, '127.0.0.1')).raw_token
    bound, _, states, context, _, _, _, _ = await native_case(tmp_path, 'pptx', frozen_document=True)
    # native_case原供单原生格式使用；此组合夹具也保留正文原有的冻结引用展示。
    context = context.model_copy(update={'job': {**context.job, '_citationPresentations': [
        {'citationId': 'business-source', 'label': '受控收支计算', 'coverageItems': []}]}})
    states.state.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    preferences = FormatPreferenceService(auth, FormatPreferences.model_validate({
        'common': {'signer': 'DPI链路验收编制'},
        'word': {'cover': False, 'toc': False, 'charts': {'imageDpi': 96}},
        'pdf': {'cover': False, 'toc': False, 'charts': {'imageDpi': 96}},
        'pptx': {'charts': {'imageDpi': 96}},
    }))
    editor_repository = SqlAlchemyReportEditorRepository(repository.engine)
    await editor_repository.create_schema()
    grants = ReportEditorGrantService(editor_repository, secret='dpi-persistence-fixture-' * 3)
    grant, _ = await grants.issue(context)
    editor, _ = await grants.exchange(grant)
    bound.preferences, bound.grants = preferences, grants
    async with repository.engine.begin() as connection:
        await connection.run_sync(lambda sync: report_artifact_files_v1.metadata.create_all(sync,
            tables=[report_artifact_files_v1, report_artifact_chunks_v1]))
    bound.editor.artifact_persistence = ReportArtifactPersistenceService(
        SqlAlchemyReportArtifactRepository(repository.engine), bound.editor.workspace)
    service = PreferenceVerificationHandoffService(preferences=preferences, bound=bound)
    original_generate = preference_preflight._generate
    render = preference_preflight.ReportRuntime.render_markdown
    render_errors = []

    def traced_render(runtime, *args, **kwargs):
        try:
            return render(runtime, *args, **kwargs)
        except Exception as error:
            render_errors.append({'type': type(error).__name__, 'message': str(error)})
            raise

    def generate(directory, document, frozen):
        issues = original_generate(directory, document, frozen)
        if fault == 'word_over_target':
            path = directory / 'report.docx'
            if not path.is_file():
                path = directory / 'inputs/revision/report.docx'
            actual = Document(path)
            assert actual.inline_shapes
            # 修改真实DrawingML尺寸而非伪造reader回执；实际图片DPI因此超标。
            actual.inline_shapes[-1].width = Inches(.1)
            actual.inline_shapes[-1].height = Inches(.1)
            actual.save(path)
        return issues

    async def actual_engine(function, *args, **kwargs):
        assert set(kwargs['formats']) == {'md', 'word', 'pdf', 'pptx'}
        return function(*args, **kwargs)

    monkeypatch.setattr(preference_preflight, '_generate', generate)
    monkeypatch.setattr(preference_preflight.ReportRuntime, 'render_markdown', traced_render)
    monkeypatch.setattr(preference_report_preflight, 'run_office_engine', actual_engine)
    draft = (await preferences.detail(admin))['draft']
    expected = {'expectedVersion': draft['version'], 'expectedHash': draft['contentHash']}
    token = (await service.create(admin, expected_version=draft['version'], expected_hash=draft['contentHash']))['handoffToken']
    await service.confirm(token, editor, report_id=context.report_id, revision=context.revision)
    app = FastAPI()
    app.include_router(create_preference_verification_router(service,
        ManagementSettings(public_origin='http://127.0.0.1', allow_local_http=True)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
        client.cookies.set(SESSION_COOKIE, admin, path='/management')
        response = await client.post(ROOT + '/run', json={**expected, 'handoffToken': token},
            headers={'origin': 'http://127.0.0.1', 'x-csrf-token': csrf_token(admin)})
    assert response.status_code == 200, response.text
    payload = response.json()
    receipt = payload['verificationReceipt']
    async with repository.engine.connect() as connection:
        row = (await connection.execute(select(preference_verification_results).where(
            preference_verification_results.c.id == receipt['id']))).mappings().one()
    document = row['document']
    assert row['content_hash'] == receipt['contentHash'] == configuration_hash(document)
    assert document['retained']['issues'] == []
    assert document['binding']['valid'] is document['binding']['artifactAccessAuthorized'] is True
    fields = [item for item in document['evidence'] if item.get('readerGroup') == 'chart_image_dpi_v1']
    output = OUTPUT / fault / tmp_path.parent.name
    output.mkdir(parents=True, exist_ok=True)
    (output / 'generation-diagnostic.json').write_text(json.dumps({'formats': {
        format: {'issues': entry.get('issues'), 'availability': entry.get('availability'),
            'hasArtifact': entry.get('artifact') is not None,
            'dpiChecks': [check for check in entry.get('readback', {}).get('checks', [])
                if check.get('path') == format + '.charts.imageDpi']}
        for format, entry in payload['formats'].items()}, 'dpiFields': fields,
        'renderErrors': render_errors}, ensure_ascii=False, indent=2))
    assert {item['path'] for item in fields} == {format + '.charts.imageDpi' for format in ('word', 'pdf', 'pptx')}
    failed = {item['path'] for item in fields if item['status'] == 'failed'}
    assert failed == ({'word.charts.imageDpi'} if fault == 'word_over_target' else set())
    independent = SqlAlchemyReportArtifactRepository(repository.engine)
    for item in fields:
        format = item['format']
        reference = document['retained']['formats'][format]['artifact']
        stored = await independent.get(reference['artifactKey'])
        content = b''.join([chunk async for chunk in independent.stream(reference['artifactKey'])])
        assert content == base64.b64decode(payload['formats'][format]['artifact']['base64'], validate=True)
        assert stored.size == len(content) == reference['size']
        assert stored.sha256 == sha256(content).hexdigest() == reference['sha256']
        assert item['artifact'] == {'sizeBytes': len(content), 'sha256': stored.sha256}
        suffix = 'docx' if format == 'word' else format
        (output / ('report.' + suffix)).write_bytes(content)
    from smart_reporting.management.preference_executor import executor_manifest

    (output / 'executor-before-prepare.json').write_text(json.dumps({
        'recorded': document['executorManifest'], 'recordedHash': document['executorManifestHash'],
        'beforePrepare': executor_manifest()}, ensure_ascii=False, indent=2))
    if fault == 'retained_drift':
        reference = document['retained']['formats']['word']['artifact']
        async with repository.engine.begin() as connection:
            await connection.execute(update(report_artifact_chunks_v1).where(
                report_artifact_chunks_v1.c.artifact_key == reference['artifactKey'],
                report_artifact_chunks_v1.c.chunk_index == 0).values(content=b'corrupt-retained-artifact'))
        with pytest.raises(ManagementError, match='management_preference_retained_artifact_changed'):
            await service.evidence.prepare(admin, expected_version=draft['version'],
                expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
        prepared = {'status': 'rejected', 'canApply': False, 'reason': 'management_preference_retained_artifact_changed'}
    else:
        prepared = await service.evidence.prepare(admin, expected_version=draft['version'],
            expected_hash=draft['contentHash'], evidence_ids=[receipt['id']])
        assert prepared['status'] == document['assessment']['status'] == 'incomplete'
        assert prepared['canApply'] is False
        assert any('visual' in gap['missingDimensions'] for gap in prepared['missingRequirements'])
        assert {gap['path'] for gap in prepared['missingRequirements'] if gap['reason'] == 'check_failed'} == failed
        if fault == 'valid':
            assert not any(gap.get('path') in {item['path'] for item in fields}
                and gap.get('scenario') == 'configured_field' for gap in prepared['missingRequirements'])
    assert payload['canApply'] is False
    assert all(payload['formats'][format]['artifact']['base64'] for format in ('word', 'pdf', 'pptx'))
    (output / 'evidence.json').write_text(json.dumps({'fault': fault, 'fields': fields,
        'retained': document['retained'], 'assessment': document['assessment'], 'prepared': prepared},
        ensure_ascii=False, indent=2))
