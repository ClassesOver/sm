"""Bates 原生文字写入的预览确认与非阻断下载契约。"""
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_bates_confirmation_and_review_warning_retain_actual_saved_download(tmp_path, monkeypatch):
    engine = Path(__file__).resolve().parents[1] / 'pdf_engine'
    runtime = tmp_path / 'engine-source'
    runtime.mkdir()
    for name in ('bridge', 'src', 'vendor', 'node_modules', 'package.json'):
        (runtime / name).symlink_to(engine / name)
    monkeypatch.setenv('AGENT_REPORTING_PDF_ENGINE_DIR', str(runtime))
    editor, context, source, downloads = await fixture(tmp_path / 'service', text_enabled=False)
    model = inspect_pdf(source)
    operation = {'kind': 'addBates', 'sourceSha256': model['sourceSha256'],
                 'config': {'prefix': 'CASE-', 'start': 9, 'digits': 4, 'fontSize': 10,
                            'color': [.1, .1, .12], 'position': 'bottom-right', 'firstPage': 1, 'lastPage': 1},
                 'entries': [{'pageId': model['pages'][0]['pageId'], 'ordinal': 0,
                              'origin': [270, 28], 'rotate': 0, 'lineXOffsets': [-58]}]}
    preview = await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[operation])
    assert preview['appliedOperationIndices'] == [0]
    assert preview['skippedOperations'] == []
    with pytest.raises(ReportingError) as missing:
        await editor.save(context, expected_sha256=context.source_file.sha256,
                          operations=[operation], request_id='unconfirmed')
    assert missing.value.code == 'native_pdf_text_confirmation_required'

    import smart_reporting.report_editor.native_publication as publication
    original = publication.patch_pdf_with_receipt

    def inject_review_fault(*args, **kwargs):
        receipt = original(*args, **kwargs)
        return {**receipt, 'reviewIssues': [*receipt.get('reviewIssues', []), {
            'operationIndex': 0, 'kind': 'addBates', 'fieldName': '',
            'code': 'pdf_bates_output_review_failed', 'message': 'Bates 独立复核故障，实际 PDF 已保留。',
        }]}

    monkeypatch.setattr(publication, 'patch_pdf_with_receipt', inject_review_fault)
    result = await editor.save(context, expected_sha256=context.source_file.sha256,
                               operations=[operation], request_id='bates-warning-download',
                               confirmed_preview_digest=preview['previewDigest'])
    assert result['revisionRegistered'] is True
    assert result['validation']['ok'] is False
    assert any(issue['code'] == 'pdf_bates_output_review_failed' for issue in result['validation']['issues'])
    _, chunks = await downloads.stream(result['artifacts']['pdf']['downloadUrl'].split('/')[-2], artifact='pdf')
    content = b''.join([chunk async for chunk in chunks])
    reader = PdfReader(BytesIO(content))
    assert 'CASE-0009' in reader.pages[0].extract_text()
    assert 'Amount due 500' in reader.pages[0].extract_text()
    actual_source = (await editor.workspace.afile_bytes(bind_native_workspace(editor.workspace, context.scope), context.source_file.path))[0]
    assert actual_source == source
