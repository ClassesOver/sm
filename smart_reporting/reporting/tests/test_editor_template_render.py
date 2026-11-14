"""模板报告的编辑器路径、材料与真实渲染，不用通用布局冒充。"""

import hashlib
from io import BytesIO
from pathlib import PurePosixPath
from types import SimpleNamespace

import pytest
from agno.run import RunContext
from docx import Document

from smart_reporting.report_editor.service import _next_pdf_path
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_report_editor import _context, _scope


@pytest.mark.parametrize('format', ['docx', 'pdf'])
def test_template_hash_output_exports_into_frozen_markdown_revision_directory(format):
    markdown = '报表/智能分析/run/document/revision-2/report.md'
    output = f'报表/智能分析/run/template/revision-2/{"a" * 20}/report.{format}'
    context = _context(markdown).model_copy(update={'revision': 2, 'delivery_format': format,
        'job': {'jobId': 'job-1', 'render': {
            'word' if format == 'docx' else 'pdf': {'path': output}}}})
    assert _next_pdf_path(context, revision=3) == str(PurePosixPath(markdown).parent.with_name('revision-3') / 'report.pdf')


@pytest.mark.parametrize('path', [
    '报表/智能分析/run/template/revision-2/not-a-request-hash/report.docx',
    '报表/智能分析/foreign/template/revision-2/aaaaaaaaaaaaaaaaaaaa/report.docx',
    '报表/智能分析/run/other/revision-2/aaaaaaaaaaaaaaaaaaaa/report.docx',
])
def test_template_output_path_rejects_unrelated_nested_directory(path):
    context = _context('报表/智能分析/run/document/revision-2/report.md').model_copy(update={
        'revision': 2, 'delivery_format': 'docx',
        'job': {'jobId': 'job-1', 'render': {'word': {'path': path}}}})
    with pytest.raises(ReportingError, match='revision'):
        _next_pdf_path(context, revision=3)


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def render_case(tmp_path):
    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
    from smart_reporting.reporting.contract import ReportFileInput
    from smart_reporting.reporting.host_workspace import (
        ReportingWorkspaceRegistry,
        ReportingWorkspaceRouter,
    )
    from smart_reporting.reporting.tests.test_template_rich_body import BODY, resources
    from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY
    from smart_reporting.tests.test_preference_template_preflight import template_bytes

    context = _context()
    registry = ReportingWorkspaceRegistry(tmp_path, secret='s' * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(_scope())
    thread = context.scope['threadId']
    images = resources()
    await workspace.awrite_bytes(thread, 'reports/revision-1/chart.png', images['chart.png'])
    raw = template_bytes()
    identity = ReportFileInput(path='inputs/template.docx', filename='模板.docx', size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    await workspace.awrite_bytes(thread, identity.path, raw)
    preferences = FormatPreferences.model_validate({'common': {'signer': '冻结编制'}})
    values = {format: resolve_format_preferences(preferences, format) for format in ('word', 'pdf')}
    for format, signer in [('word', '文字编制'), ('pdf', '版式编制')]:
        values[format]['common']['signer'] = signer
    job = {**context.job, '_formatPreferences': values,
        '_documentContext': {'title': '冻结标题', 'generatedDate': '2026-09-16'},
        'render': {'images': [{'path': 'reports/revision-1/chart.png', 'size': len(images['chart.png']),
            'sha256': hashlib.sha256(images['chart.png']).hexdigest()}]}}
    context = context.model_copy(update={'job': job})
    snapshot = 'reports/revision-1/.preview-template.md'
    await workspace.awrite_text(thread, snapshot, BODY)
    document = SimpleNamespace(markdown=BODY, sha256=hashlib.sha256(BODY.encode()).hexdigest())
    source = SimpleNamespace(identity=identity, content=raw, material_run_id=context.workflow_run_id,
        binding={'schemaVersion': 1, 'originRevision': 1, 'originContextSha256': context.digest(),
            'materialRunId': context.workflow_run_id, 'identity': identity.model_dump(mode='json', by_alias=True)}, configuration=None)
    run = RunContext(run_id=context.workflow_run_id, session_id=thread, user_id=context.scope['userId'],
        session_state={REPORT_JOBS_STATE_KEY: {context.job_id: job}})
    return SimpleNamespace(editor=SimpleNamespace(workspace=workspace), context=context, source=source,
        document=document, snapshot=snapshot, run=run, original=raw)


@pytest.mark.anyio
async def test_editor_template_bridge_writes_native_body_and_separate_frozen_signatures(tmp_path):
    from pypdf import PdfReader

    from smart_reporting.report_editor.template_render import render_editor_template
    from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY

    case = await render_case(tmp_path)
    result = await render_editor_template(case.editor, template_source=case.source, context=case.context,
        source_context=case.context, document=case.document, snapshot_path=case.snapshot,
        output_path='reports/revision-2/report.pdf', formats=('word', 'pdf'), render_manifest=None, run_context=case.run)
    workspace, thread = case.editor.workspace, case.context.scope['threadId']
    word, _ = await workspace.afile_bytes(thread, result['wordPath'])
    pdf, _ = await workspace.afile_bytes(thread, result['pdfPath'])
    doc = Document(BytesIO(word))
    assert len(doc._element.body.xpath('.//w:tbl')) == 1
    assert len(doc.inline_shapes) == 1 and doc.styles['Normal'].font.size.pt == 17
    text = ''.join(doc._element.body.xpath('.//w:t/text()'))
    assert '文字编制' in text and '版式编制' not in text
    visible = ''.join(page.extract_text() or '' for page in PdfReader(BytesIO(pdf)).pages)
    assert '版式编制' in visible and '文字编制' not in visible
    assert result['validation']['ok'] is False
    assert result['validation']['readback']['word']['templateReadback']['body']['status'] == 'passed'
    assert result['validation']['readback']['word']['templateReadback']['outsideDeclaredTargets']['status'] == 'passed'
    record = case.run.session_state[REPORT_JOBS_STATE_KEY][case.context.job_id]
    assert record['render']['markdown']['sha256'] == case.document.sha256
    assert record['_templateSource'] == case.source.binding
    assert (await workspace.afile_bytes(thread, case.source.identity.path))[0] == case.original


@pytest.mark.anyio
async def test_template_render_uses_selected_snapshot_during_concurrent_draft_edits(tmp_path, monkeypatch):
    from smart_reporting.report_editor import template_render

    case = await render_case(tmp_path)
    original = template_render.fill_report_template
    def edit(*a, **kwargs):
        # 真实自动保存路径与本次冻结快照不同；转换仍只能使用传入的冻结正文。
        root = case.editor.workspace.registry.get(case.context.scope['threadId']).root
        draft = root / 'reports/revision-1/draft/report.md'
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text('后台新编辑不得串入 9999.0000')
        return original(*a, **kwargs)
    monkeypatch.setattr(template_render, 'fill_report_template', edit)
    result = await template_render.render_editor_template(case.editor, template_source=case.source,
        context=case.context, source_context=case.context, document=case.document, snapshot_path=case.snapshot,
        output_path='reports/revision-2/report.pdf', formats=('word',), render_manifest=None, run_context=case.run)
    raw = (await case.editor.workspace.afile_bytes(case.context.scope['threadId'], result['wordPath']))[0]
    text = ''.join(Document(BytesIO(raw))._element.body.xpath('.//w:t/text()'))
    assert '1234.5600' in text and '9999.0000' not in text


@pytest.mark.anyio
async def test_template_body_still_renders_known_title_without_inventing_legacy_date(tmp_path):
    from smart_reporting.report_editor.template_render import render_editor_template
    from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY

    case = await render_case(tmp_path)
    job = case.run.session_state[REPORT_JOBS_STATE_KEY][case.context.job_id]
    job.pop('_documentContext')
    job.pop('_formatPreferences')
    case.source.document_context = {'title': '历史冻结标题'}
    result = await render_editor_template(case.editor, template_source=case.source, context=case.context,
        source_context=case.context, document=case.document, snapshot_path=case.snapshot,
        output_path='reports/revision-2/report.pdf', formats=('word',), render_manifest=None, run_context=case.run)
    raw = (await case.editor.workspace.afile_bytes(case.context.scope['threadId'], result['wordPath']))[0]
    text = ''.join(Document(BytesIO(raw))._element.body.xpath('.//w:t/text()'))
    assert '历史冻结标题' in text and '1234.5600' in text
    assert any(issue['code'] == 'report_editor_template_signature_unavailable' for issue in result['validation']['issues'])
    assert 'generatedDate' not in job['_documentContext']


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['reader', 'pdf_generation', 'pdf_conflict', 'postwrite'])
async def test_template_bridge_failure_keeps_other_verified_file(tmp_path, monkeypatch, fault):
    from smart_reporting.report_editor import template_render
    from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY

    case = await render_case(tmp_path)
    original_fill = template_render.fill_report_template
    original_write = case.editor.workspace.awrite_bytes
    if fault == 'reader':
        monkeypatch.setattr(template_render, 'read_template_document', lambda *a, **k: (_ for _ in ()).throw(OSError('reader down')))
    elif fault == 'pdf_generation':
        def fill(*a, **kwargs):
            if kwargs['delivery_format'] == 'pdf':
                raise OSError('PDF converter down')
            return original_fill(*a, **kwargs)
        monkeypatch.setattr(template_render, 'fill_report_template', fill)
    elif fault == 'pdf_conflict':
        await original_write(case.context.scope['threadId'], 'reports/revision-2/report.pdf', b'foreign PDF')
    else:
        async def write(*a, **kwargs):
            await original_write(*a, **kwargs)
            raise OSError('save receipt failed after actual write')
        monkeypatch.setattr(case.editor.workspace, 'awrite_bytes', write)
    result = await template_render.render_editor_template(case.editor, template_source=case.source,
        context=case.context, source_context=case.context, document=case.document, snapshot_path=case.snapshot,
        output_path='reports/revision-2/report.pdf', formats=('word', 'pdf'), render_manifest=None, run_context=case.run)
    raw = (await case.editor.workspace.afile_bytes(case.context.scope['threadId'], result['wordPath']))[0]
    assert hashlib.sha256(raw).hexdigest() == result['wordSha256']
    assert result['validation']['ok'] is False
    assert case.run.session_state[REPORT_JOBS_STATE_KEY][case.context.job_id]['render']['word']['sha256'] == result['wordSha256']
    if fault in ('pdf_generation', 'pdf_conflict'):
        assert 'pdfPath' not in result
    else:
        assert result['pdfPath']


@pytest.mark.anyio
@pytest.mark.parametrize('target', ['preview', 'export', 'docx_preview', 'repeat_export'])
async def test_real_editor_entry_uses_durable_template_instead_of_generic_renderer(tmp_path, target):
    from unittest.mock import AsyncMock

    from smart_reporting.report_editor import ReportEditorContext
    from smart_reporting.reporting.tests.test_editor_partial_delivery import delivery_editor

    case = await render_case(tmp_path / 'source')
    f = await delivery_editor(tmp_path / 'editor', ('pdf', 'word'), set())
    editor = f.editor
    current = f.current.model_copy(update={'job': {**f.current.job,
        '_documentContext': case.context.job['_documentContext'],
        '_formatPreferences': case.context.job['_formatPreferences']}})
    if target == 'docx_preview':
        current = current.model_copy(update={'delivery_format': 'docx'})
    durable = f.repository.durable
    durable.payload['reportEditorContexts'][str(current.revision)] = current.model_dump(mode='json', by_alias=True)
    durable.payload['requestMaterials'] = {'fileInputs': [],
        'templateInput': case.source.identity.model_dump(mode='json', by_alias=True)}
    editor.state_repository.get_run = AsyncMock(return_value={'database': current.scope['database'],
        'company_id': current.scope['companyId']})
    await editor.workspace.awrite_bytes(f.thread, case.source.identity.path, case.original)
    async def forbidden(*a, **kw):
        pytest.fail('模板入口不能退回通用布局')
    editor.report_tools._render_report_pair = forbidden
    document = await editor.read_document(current)
    if target in ('export', 'repeat_export'):
        result = await editor.export_revision(current, expected_sha256=document.sha256)
        assert result['revision'] == 3
        provenance = result['validation']['layoutProvenance']
        assert set(provenance['formats']) == {'word', 'pdf'}
        assert provenance['formats']['word']['signatureReadback'] == 'passed'
        assert provenance['formats']['pdf']['signatureReadback'] == 'unverified'
        assert provenance['formats']['word']['dateFormatSource'] == 'frozen_revision_preferences'
        current_state = await editor.state_repository.get(current.workflow_run_id)
        next_context = await editor._restore(ReportEditorContext.model_validate(
            current_state.payload['reportEditorContexts']['3']))
        assert next_context.job['_templateSource']['identity'] == case.source.identity.model_dump(mode='json', by_alias=True)
        actual_path = next_context.job['render']['word']['path']
        raw = (await editor.workspace.afile_bytes(f.thread, actual_path))[0]
        assert Document(BytesIO(raw)).styles['Normal'].font.size.pt == 17
        if target == 'repeat_export':
            binding = next_context.job['_templateSource']
            second_document = await editor.read_document(next_context)
            second = await editor.export_revision(next_context, expected_sha256=second_document.sha256)
            assert second['revision'] == 4
            state = await editor.state_repository.get(current.workflow_run_id)
            latest = ReportEditorContext.model_validate(state.payload['reportEditorContexts']['4'])
            assert latest.job['_templateSource'] == binding
            assert (await editor.workspace.afile_bytes(f.thread, actual_path))[0] == raw
    else:
        record = await editor.design.read(current)
        started = await editor.design_preview.start(current, document.sha256, record['designSha256'])
        job = editor.design_preview.jobs[started['previewId']]
        await job.task
        result = await editor.design_preview.status(current, started['previewId'])
        assert result['status'] == 'succeeded'
        provenance = result['validation']['layoutProvenance']
        assert provenance['template'] == {'filename': '模板.docx', 'size': case.source.identity.size,
            'sha256': case.source.identity.sha256}
        assert 'pdfPath' not in result and 'identity' not in result
        assert 'template' not in result['validation'] and 'readback' not in result['validation']
        if target == 'docx_preview':
            from pypdf import PdfReader

            raw = await editor.design_preview.pdf(current, started['previewId'])
            text = ''.join(page.extract_text() or '' for page in PdfReader(BytesIO(raw)).pages)
            assert '文字编制' in text and '版式编制' not in text
            assert provenance['previewSourceFormat'] == 'word'
            assert set(provenance['formats']) == {'word'}
        else:
            assert set(provenance['formats']) == {'pdf'}
        assert '3' not in durable.payload['reportEditorContexts']
        if job.expiry:
            job.expiry.cancel()
