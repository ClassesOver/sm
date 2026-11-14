"""模板落款内容沿用冻结身份，并接受编辑器明确重置或修改。"""

import hashlib
from copy import deepcopy
from io import BytesIO

import pytest
from docx import Document
from pypdf import PdfReader

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.report_editor.template_render import _format_content, render_editor_template
from smart_reporting.reporting.tests.test_editor_template_render import render_case
from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('format', ['word', 'pdf'])
@pytest.mark.parametrize('reset', [True, False])
def test_template_format_content_preserves_explicit_signature_reset_and_content_changes(format, reset):
    resolved = resolve_format_preferences(FormatPreferences(common={
        'signer': '冻结编制人', 'dateFormat': 'chinese'}), format)
    resolved['signature']['description'] = '冻结默认说明'
    override = None if reset else {'dateFormat': 'slash', 'description': '编辑器确认说明'}
    job = {'_formatPreferences': {format: resolved},
        '_documentContext': {'title': '冻结标题', 'generatedDate': '2026-09-16'},
        '_reportDesign': {'signature': override}}
    original = deepcopy(job)

    title, signature, effective, generated = _format_content(job, None, format)

    assert title == '冻结标题' and generated == '2026-09-16'
    assert signature == {'signer': '冻结编制人',
        'date': '2026-09-16' if reset else '2026/09/16',
        'description': '' if reset else '编辑器确认说明'}
    assert effective['common']['dateFormat'] == ('iso' if reset else 'slash')
    assert effective['signature']['description'] == signature['description']
    assert job == original


@pytest.mark.anyio
@pytest.mark.parametrize('reset', [True, False])
async def test_editor_design_difference_reaches_real_template_files_without_replacing_frozen_identity(tmp_path, reset):
    from smart_reporting.preferences.document_adapter import document_design
    from smart_reporting.report_editor.design import editor_base_design, editor_design_overrides

    case = await render_case(tmp_path)
    job = case.run.session_state[REPORT_JOBS_STATE_KEY][case.context.job_id]
    for resolved in job['_formatPreferences'].values():
        resolved['common']['dateFormat'] = 'chinese'
        resolved['signature']['description'] = '冻结默认说明'
    job['_formatDesigns'] = {format: document_design(value).compact()
        for format, value in job['_formatPreferences'].items()}
    case.context = case.context.model_copy(update={'job': deepcopy(job)})
    design = editor_base_design(case.context)
    if reset:
        design.signature = None
    else:
        design.signature.date_format = 'slash'
        design.signature.description = '编辑器确认说明'
    job['_reportDesign'] = editor_design_overrides(case.context, design)
    if reset:
        assert job['_reportDesign'] == {'signature': None}
    frozen = deepcopy(job['_formatPreferences'])

    result = await render_editor_template(case.editor, template_source=case.source, context=case.context,
        source_context=case.context, document=case.document, snapshot_path=case.snapshot,
        output_path='reports/revision-2/report.pdf', formats=('word', 'pdf'), render_manifest=None, run_context=case.run)

    expected_date = '2026-09-16' if reset else '2026/09/16'
    provenance = result['validation']['layoutProvenance']
    assert provenance['contentSha256'] == case.document.sha256
    for entry in provenance['formats'].values():
        assert entry['dateFormatSource'] == ('editor_reset' if reset else 'editor_design')
        assert entry['descriptionSource'] == ('editor_reset' if reset else 'editor_design')
        assert entry['generatedDate'] == '2026-09-16'
    for format, signer, foreign_signer in [('word', '文字编制', '版式编制'), ('pdf', '版式编制', '文字编制')]:
        raw = (await case.editor.workspace.afile_bytes(case.context.scope['threadId'], result[format + 'Path']))[0]
        assert len(raw) == result[format + 'Size']
        assert hashlib.sha256(raw).hexdigest() == result[format + 'Sha256']
        if format == 'word':
            document = Document(BytesIO(raw))
            text = '\n'.join(document._element.body.xpath('.//w:t/text()'))
            assert document.styles['Normal'].font.size.pt == 17
            assert len(document._element.body.xpath('.//w:tbl')) == 1
            assert len(document.inline_shapes) == 1
        else:
            text = '\n'.join(page.extract_text() or '' for page in PdfReader(BytesIO(raw)).pages)
        assert signer in text and foreign_signer not in text
        assert expected_date in text and '冻结默认说明' not in text
        assert '2026年9月16日' not in text
        assert ('编辑器确认说明' in text) is not reset
        assert '1234.5600' in text
        receipt = result['validation']['readback'][format]
        assert receipt['templateReadback']['signature']['status'] == ('passed' if format == 'word' else 'unverified')
        assert receipt['checks'] and all(check['passed'] for check in receipt['checks'])
    assert job['_formatPreferences'] == frozen
    assert (await case.editor.workspace.afile_bytes(case.context.scope['threadId'], case.source.identity.path))[0] == case.original
    assert result['validation']['ok'] is False
    assert not any(issue['code'] == 'report_editor_template_generation_failed' for issue in result['validation']['issues'])

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.reporting.delivery.publishing import (
        ReportDownloadHttpService,
        create_report_download_router,
    )
    from smart_reporting.reporting.tests.test_http_publication_lineage import _publication_fixture

    runtime, arguments, scope, _, artifacts, *_ = await _publication_fixture(tmp_path / 'publisher')
    for format in ('word', 'pdf'):
        raw = (await case.editor.workspace.afile_bytes(case.context.scope['threadId'], result[format + 'Path']))[0]
        await runtime.workspace_service.awrite_bytes(scope.workspace_key, result[format + 'Path'], raw)
        arguments['output'].update({format + field: result[format + field] for field in ('Path', 'Size', 'Sha256')})
    arguments['output'].update(validation=result['validation'], deliveryFormat='document')
    published = await runtime.issue_http_publication(**arguments)
    assert published['validation']['ok'] is False
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants,
        artifacts, workspace_service=runtime.workspace_service)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        for format in ('word', 'pdf'):
            response = await client.get(published[format]['downloadUrl'])
            assert response.status_code == 200
            assert len(response.content) == result[format + 'Size']
            assert hashlib.sha256(response.content).hexdigest() == result[format + 'Sha256']
