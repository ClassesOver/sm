"""书签操作复用原保存回执；结构复核故障不得丢弃真实下载。"""
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_outline_review_warning_retains_saved_download_and_failed_validation(tmp_path, monkeypatch):
    # 源码桥运行在隔离目录，避免使用共享 dist 的旧协议，也不改写或重建共享产物。
    engine = Path(__file__).resolve().parents[1] / 'pdf_engine'
    runtime = tmp_path / 'engine-source'
    runtime.mkdir()
    for name in ('bridge', 'src', 'vendor', 'node_modules', 'package.json'):
        (runtime / name).symlink_to(engine / name)
    monkeypatch.setenv('AGENT_REPORTING_PDF_ENGINE_DIR', str(runtime))
    editor, context, source, downloads = await fixture(tmp_path / 'service', text_enabled=False)
    model = inspect_pdf(source)
    operation = {'kind': 'setOutline', 'sourceSha256': model['sourceSha256'],
                 'tree': [{'title': 'Saved bookmark', 'pageId': model['pages'][0]['pageId'],
                           'top': None, 'children': []}]}
    preview = await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[operation])
    assert preview['appliedOperationIndices'] == [0]
    assert preview['skippedOperations'] == []

    import smart_reporting.report_editor.native_publication as publication
    original = publication.patch_pdf_with_receipt

    def inject_outline_review_fault(*args, **kwargs):
        receipt = original(*args, **kwargs)
        return {**receipt, 'reviewIssues': [*receipt.get('reviewIssues', []), {
            'operationIndex': 0, 'kind': 'setOutline', 'fieldName': '',
            'code': 'pdf_outline_output_review_failed',
            'message': '书签结构复核故障；实际 PDF 已生成并保留。',
        }]}

    monkeypatch.setattr(publication, 'patch_pdf_with_receipt', inject_outline_review_fault)
    result = await editor.save(context, expected_sha256=context.source_file.sha256,
                               operations=[operation], request_id='outline-warning-download')
    assert result['revisionRegistered'] is True
    assert result['validation']['ok'] is False
    assert any(issue['code'] == 'pdf_outline_output_review_failed' for issue in result['validation']['issues'])
    _, chunks = await downloads.stream(result['artifacts']['pdf']['downloadUrl'].split('/')[-2], artifact='pdf')
    content = b''.join([chunk async for chunk in chunks])
    reader = PdfReader(BytesIO(content))
    assert reader.outline[0].title == 'Saved bookmark'
    assert reader.get_destination_page_number(reader.outline[0]) == 0
    assert reader.pages[0].extract_text() == PdfReader(BytesIO(source)).pages[0].extract_text()
    actual_source = (await editor.workspace.afile_bytes(bind_native_workspace(editor.workspace, context.scope), context.source_file.path))[0]
    assert actual_source == source
