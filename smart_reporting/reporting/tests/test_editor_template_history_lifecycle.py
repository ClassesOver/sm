"""历史正文真实恢复后走编辑器入口，模板/偏好/图片不得串入当前修订。"""

import hashlib
import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from zipfile import ZipFile

import pytest
from docx import Document
from PIL import Image
from pypdf import PdfReader

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.report_editor import ReportEditorContext
from smart_reporting.reporting.contract import ReportFileInput
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_editor_partial_delivery import delivery_editor
from smart_reporting.tests.test_preference_template_preflight import template_bytes

_OUTPUT = Path('output/system-config-preferences/editor-template-lifecycle/history')
_OLD = '# 历史正文\n\n历史原值 1234.5600。\n\n![历史登记图](chart.png)\n\n末段保留 -7.8900%。'
_CURRENT = '# 当前正文\n\n当前原值 9999.0000。\n\n![当前登记图](chart.png)'


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def image(color):
    stream = BytesIO()
    Image.new('RGB', (120, 60), color).save(stream, format='PNG')
    return stream.getvalue()


def preferences(historical):
    values = FormatPreferences.model_validate({'common': {'signer': '历史默认' if historical else '当前默认',
        'dateFormat': 'iso'}})
    result = {format: resolve_format_preferences(values, format) for format in ('word', 'pdf')}
    for format in result:
        result[format]['common']['signer'] = ('历史' if historical else '当前') + ('文字编制' if format == 'word' else '版式编制')
        result[format]['signature']['description'] = '历史冻结说明' if historical else '当前冻结说明'
    return result


async def lifecycle_case(tmp_path, delivery_format):
    f = await delivery_editor(tmp_path, ('pdf', 'word'), set())
    editor = f.editor
    contexts = f.repository.durable.payload['reportEditorContexts']
    historical = ReportEditorContext.model_validate(contexts['1'])
    old_image, current_image = image('#bc3456'), image('#23ab67')
    await editor.workspace.awrite_text(f.thread, historical.markdown_path, _OLD, overwrite=True)
    await editor.workspace.awrite_text(f.thread, f.current.markdown_path, _CURRENT, overwrite=True)
    for revision, content in ((1, old_image), (2, current_image)):
        await editor.workspace.awrite_bytes(f.thread, f'reports/revision-{revision}/chart.png', content)

    def frozen(context, old):
        source = _OLD if old else _CURRENT
        data = source.encode()
        chart = old_image if old else current_image
        return context.model_copy(update={'artifact_manifest': None, 'delivery_format': delivery_format,
            'job': {**context.job, '_formatPreferences': preferences(old),
                '_documentContext': {'title': '历史冻结标题' if old else '当前冻结标题',
                    'generatedDate': '2026-08-17' if old else '2026-10-19'},
                'render': {'markdown': {'path': context.markdown_path, 'size': len(data), 'sha256': digest(data)},
                    'images': [{'path': f'reports/revision-{context.revision}/chart.png', 'size': len(chart), 'sha256': digest(chart)}],
                    'pdf': {'path': f'reports/revision-{context.revision}/report.pdf'},
                    'word': {'path': f'reports/revision-{context.revision}/report.docx'}}}})

    historical, current = frozen(historical, True), frozen(f.current, False)
    contexts['1'], contexts['2'] = [context.model_dump(mode='json', by_alias=True) for context in (historical, current)]
    original = template_bytes()
    identity = ReportFileInput(path='inputs/history-template.docx', filename='冻结模板.docx', size=len(original), sha256=digest(original))
    await editor.workspace.awrite_bytes(f.thread, identity.path, original)
    f.repository.durable.payload['requestMaterials'] = {'fileInputs': [], 'templateInput': identity.model_dump(mode='json', by_alias=True)}
    editor.state_repository.get_run = AsyncMock(return_value={'database': current.scope['database'], 'company_id': current.scope['companyId']})

    async def forbidden(*args, **kwargs):
        pytest.fail('历史模板恢复不得经过通用renderer')

    editor.report_tools._render_report_pair = forbidden
    before = await editor.read_document(current)
    restored = await editor.restore_history(current, 1, expected_sha256=before.sha256)
    assert restored.markdown == _OLD and restored.source_revision == 1
    assert (await editor.read_document(current)).source_revision == 1
    assert await editor.workspace.aread_text(f.thread, historical.markdown_path) == _OLD
    assert await editor.workspace.aread_text(f.thread, current.markdown_path) == _CURRENT
    return SimpleNamespace(f=f, editor=editor, historical=historical, current=current, restored=restored,
        template=original, template_identity=identity, old_image=old_image, current_image=current_image)


async def preview(case):
    record = await case.editor.design.read(case.current)
    started = await case.editor.design_preview.start(case.current, case.restored.sha256, record['designSha256'])
    job = case.editor.design_preview.jobs[started['previewId']]
    try:
        await job.task
    except ReportingError:
        # 状态端点负责报告后台失败，测试仍经过真实status入口读取原因。
        pass
    result = await case.editor.design_preview.status(case.current, started['previewId'])
    if job.expiry:
        job.expiry.cancel()
    return result


async def persist_evidence(case, name, artifacts, result):
    folder = _OUTPUT / name
    if folder.exists():
        folder = _OUTPUT / (name + '-' + uuid4().hex[:12])
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    for label, raw in artifacts.items():
        path = folder / label
        assert not path.exists(), '生命周期原件证据不得覆盖'
        path.write_bytes(raw)
        records.append({'path': str(path), 'size': len(raw), 'sha256': digest(raw)})
    (folder / 'receipt.json').write_text(json.dumps({'scope': 'real service restore_history and preview/export, synthetic frozen template and image, no business DB/models/visual/V; old report without trace manifest',
        'historicalSourceContextSha256': case.historical.digest(), 'currentContextSha256': case.current.digest(),
        'selectedSourceRevision': case.restored.source_revision, 'selectedDraftSha256': case.restored.sha256,
        'templateIdentity': case.template_identity.model_dump(mode='json', by_alias=True),
        'frozenHistoricalPreferences': case.historical.job['_formatPreferences'],
        'historicalImageSha256': digest(case.old_image), 'currentImageSha256': digest(case.current_image),
        'files': records, 'result': result}, ensure_ascii=False, indent=2, default=str) + '\n')


@pytest.mark.anyio
@pytest.mark.parametrize('entry', ['pdf_preview', 'word_preview', 'export'])
async def test_restored_history_uses_exact_template_preferences_and_revision_local_image(tmp_path, entry):
    case = await lifecycle_case(tmp_path, 'docx' if entry == 'word_preview' else 'document')
    before_job = deepcopy(case.current.job)
    if entry == 'export':
        result = await case.editor.export_revision(case.current, expected_sha256=case.restored.sha256)
        durable = await case.f.repository.get(case.current.workflow_run_id)
        target = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['3'])
        word = (await case.editor.workspace.afile_bytes(case.f.thread, target.job['render']['word']['path']))[0]
        pdf = (await case.editor.workspace.afile_bytes(case.f.thread, target.job['render']['pdf']['path']))[0]
        doc = Document(BytesIO(word))
        visible = ''.join(doc.element.body.xpath('.//w:t/text()'))
        assert '历史文字编制' in visible and '2026-08-17' in visible
        assert '当前' not in visible and '9999.0000' not in visible
        assert doc.styles['Normal'].font.size.pt == 17
        assert len(doc.inline_shapes) == 1
        with ZipFile(BytesIO(word)) as archive:
            media = [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
        assert media == [case.old_image]
        assert target.job['_formatPreferences'] == case.historical.job['_formatPreferences']
        assert target.job['_documentContext'] == case.historical.job['_documentContext']
        assert target.job['_templateSource']['originRevision'] == 1
        assert target.job['_templateSource']['originContextSha256'] == case.historical.digest()
        assert target.job['_templateSource']['identity'] == case.template_identity.model_dump(mode='json', by_alias=True)
        assert result['word']['downloadUrl'] and result['pdf']['downloadUrl']
        artifacts = {'actual.docx': word, 'actual.pdf': pdf}
    else:
        result = await preview(case)
        assert result['status'] == 'succeeded'
        pdf = await case.editor.design_preview.pdf(case.current, result['previewId'])
        assert result['validation']['layoutProvenance']['template'] == {
            'filename': case.template_identity.filename, 'size': case.template_identity.size,
            'sha256': case.template_identity.sha256}
        assert '3' not in (await case.f.repository.get(case.current.workflow_run_id)).payload['reportEditorContexts']
        artifacts = {'actual.pdf': pdf}
    text = ''.join(page.extract_text() or '' for page in PdfReader(BytesIO(pdf)).pages)
    assert ('历史文字编制' if entry == 'word_preview' else '历史版式编制') in text
    assert '历史冻结标题' in text and '2026-08-17' in text and '1234.5600' in text
    assert '当前' not in text and '9999.0000' not in text and '2026-10-19' not in text
    assert case.current.job == before_job
    assert (await case.editor.workspace.afile_bytes(case.f.thread, case.template_identity.path))[0] == case.template
    assert (await case.editor.workspace.afile_bytes(case.f.thread, 'reports/revision-1/chart.png'))[0] == case.old_image
    assert (await case.editor.workspace.afile_bytes(case.f.thread, 'reports/revision-2/chart.png'))[0] == case.current_image
    await persist_evidence(case, entry, {**artifacts, 'template.docx': case.template, 'source.md': _OLD.encode(), 'historical-chart.png': case.old_image}, result)
    await case.editor.design_preview.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize('entry', ['preview', 'export'])
async def test_history_template_identity_drift_never_uses_generic_fallback(tmp_path, entry):
    case = await lifecycle_case(tmp_path, 'document')
    await case.editor.workspace.awrite_bytes(case.f.thread, case.template_identity.path, b'drifted template', overwrite=True)
    if entry == 'export':
        with pytest.raises(ReportingError) as error:
            await case.editor.export_revision(case.current, expected_sha256=case.restored.sha256)
        assert error.value.code == 'report_editor_template_source_unavailable'
    else:
        result = await preview(case)
        assert result['status'] == 'failed'
    assert await case.editor.workspace.aread_text(case.f.thread, case.historical.markdown_path) == _OLD
    assert '3' not in (await case.f.repository.get(case.current.workflow_run_id)).payload['reportEditorContexts']
    await case.editor.design_preview.aclose()


@pytest.mark.anyio
async def test_history_image_drift_preserves_generated_downloads_with_specific_warning(tmp_path):
    case = await lifecycle_case(tmp_path, 'document')
    await case.editor.workspace.awrite_bytes(case.f.thread, 'reports/revision-1/chart.png', case.current_image, overwrite=True)
    result = await case.editor.export_revision(case.current, expected_sha256=case.restored.sha256)
    assert result['word']['downloadUrl'] and result['pdf']['downloadUrl']
    assert result['validation']['ok'] is False
    assert any(issue['code'] == 'report_template_body_resource_unavailable' for issue in result['validation']['issues'])
    target = ReportEditorContext.model_validate((await case.f.repository.get(case.current.workflow_run_id)).payload['reportEditorContexts']['3'])
    word = (await case.editor.workspace.afile_bytes(case.f.thread, target.job['render']['word']['path']))[0]
    assert len(Document(BytesIO(word)).inline_shapes) == 0
    assert (await case.editor.workspace.afile_bytes(case.f.thread, case.template_identity.path))[0] == case.template


@pytest.mark.anyio
async def test_restart_after_history_restore_keeps_origin_and_actual_preview_image_pixels(tmp_path):
    from smart_reporting.report_editor.service import ReportEditorService

    case = await lifecycle_case(tmp_path, 'document')
    original_editor = case.editor
    case.editor = ReportEditorService(state_repository=original_editor.state_repository,
        workspace_registry=original_editor.workspace_registry, workspace=original_editor.workspace,
        report_tools=original_editor.report_tools, public_base_url=original_editor.public_base_url)
    document = await case.editor.read_document(case.current)
    assert document.source_revision == 1 and document.sha256 == case.restored.sha256
    result = await preview(case)
    assert result['status'] == 'succeeded'
    pdf = await case.editor.design_preview.pdf(case.current, result['previewId'])
    images = [Image.open(BytesIO(item.data)).convert('RGB') for page in PdfReader(BytesIO(pdf)).pages for item in page.images]
    expected = Image.open(BytesIO(case.old_image)).convert('RGB')
    assert len(images) == 1 and images[0].size == expected.size and images[0].tobytes() == expected.tobytes()
    assert images[0].tobytes() != Image.open(BytesIO(case.current_image)).convert('RGB').tobytes()
    text = ''.join(page.extract_text() or '' for page in PdfReader(BytesIO(pdf)).pages)
    assert '历史版式编制' in text and '2026-08-17' in text and '当前' not in text
    await persist_evidence(case, 'restart-preview', {'actual.pdf': pdf, 'source.md': _OLD.encode(),
        'historical-chart.png': case.old_image, 'template.docx': case.template}, result)
    await case.editor.design_preview.aclose()
