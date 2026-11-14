"""PDF 文档属性确认与写后复核告警不阻断真实修订和下载。"""
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_metadata_review_warning_retains_actual_saved_download(tmp_path, monkeypatch):
    engine = Path(__file__).resolve().parents[1] / 'pdf_engine'
    runtime = tmp_path / 'engine-source'
    runtime.mkdir()
    for name in ('bridge', 'src', 'vendor', 'node_modules', 'package.json'):
        (runtime / name).symlink_to(engine / name)
    monkeypatch.setenv('AGENT_REPORTING_PDF_ENGINE_DIR', str(runtime))
    editor, context, source, downloads = await fixture(tmp_path / 'service', text_enabled=False)
    operation = {'kind': 'setMetadata', 'sourceSha256': context.source_file.sha256,
                 'modifiedMs': 1794550028000,
                 'metadata': {'title': '更新中文标题', 'author': 'Alice & 张三', 'subject': '',
                              'keywords': 'alpha， beta; 中文；gamma'}}
    preview = await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[operation])
    assert preview['appliedOperationIndices'] == [0]
    assert preview['reviewIssues'] == []
    with pytest.raises(ReportingError) as missing:
        await editor.save(context, expected_sha256=context.source_file.sha256,
                          operations=[operation], request_id='metadata-unconfirmed')
    assert missing.value.code == 'native_pdf_text_confirmation_required'

    import smart_reporting.report_editor.native_publication as publication
    original = publication.patch_pdf_with_receipt

    def review_fault(*args, **kwargs):
        receipt = original(*args, **kwargs)
        return {**receipt, 'reviewIssues': [*receipt.get('reviewIssues', []), {
            'operationIndex': 0, 'kind': 'setMetadata', 'fieldName': '',
            'code': 'pdf_metadata_output_review_failed', 'message': '属性写后复核故障，实际 PDF 已保留。',
        }]}

    monkeypatch.setattr(publication, 'patch_pdf_with_receipt', review_fault)
    result = await editor.save(context, expected_sha256=context.source_file.sha256,
                               operations=[operation], request_id='metadata-warning-download',
                               confirmed_preview_digest=preview['previewDigest'])
    assert result['revisionRegistered'] is True
    assert result['validation']['ok'] is False
    assert any(issue['code'] == 'pdf_metadata_output_review_failed' for issue in result['validation']['issues'])
    _, chunks = await downloads.stream(result['artifacts']['pdf']['downloadUrl'].split('/')[-2], artifact='pdf')
    content = b''.join([chunk async for chunk in chunks])
    reader = PdfReader(BytesIO(content))
    assert reader.metadata.title == '更新中文标题'
    assert reader.metadata.author == 'Alice & 张三'
    assert reader.metadata.subject == ''
    assert reader.metadata.keywords == 'alpha beta 中文 gamma'
    assert 'Amount due 500' in reader.pages[0].extract_text()
    actual_source = (await editor.workspace.afile_bytes(bind_native_workspace(editor.workspace, context.scope), context.source_file.path))[0]
    assert actual_source == source
