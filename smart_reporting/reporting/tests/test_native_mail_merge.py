import base64
import hashlib
from io import BytesIO
from docx import Document
from zipfile import ZipFile
from pathlib import Path

import pytest

from smart_reporting.report_editor.native_mail_merge import decode_mail_merge_csv, parse_mail_merge_csv
from smart_reporting.report_editor.native_mail_merge import verify_mail_merge_sources
from smart_reporting.reporting.models import ReportingError


def test_mail_merge_csv_parses_utf8_records_and_identity():
    content = '\ufeffName,City\nAda,London\nGrace,New York\n'.encode()
    result = parse_mail_merge_csv(content)
    assert result['fields'] == ['Name', 'City']
    assert result['records'] == [{'Name': 'Ada', 'City': 'London'}, {'Name': 'Grace', 'City': 'New York'}]
    assert result['sourceSha256']
    assert decode_mail_merge_csv(base64.b64encode(content).decode())[1] == result


@pytest.mark.parametrize('content', [b'', b'Name,Name\nAda,London\n', b'Name\n', b'Name\nAda\nGrace,extra\n'])
def test_mail_merge_csv_rejects_empty_duplicate_or_ragged_sources(content):
    with pytest.raises(ReportingError):
        parse_mail_merge_csv(content)


def test_mail_merge_csv_rejects_non_utf8_and_noncanonical_base64():
    with pytest.raises(ReportingError, match='UTF-8'):
        parse_mail_merge_csv(b'Name\n\xff')
    with pytest.raises(ReportingError):
        decode_mail_merge_csv('bmFtZQ=')


@pytest.mark.anyio
async def test_mail_merge_source_is_read_from_bound_workspace_before_render():
    content = b'Name\nAda\n'
    digest = hashlib.sha256(content).hexdigest()
    calls = []
    class Workspace:
        current = content
        async def afile_bytes(self, key, path):
            calls.append((key, path))
            return self.current, None
    workspace = Workspace()
    operations = [{'kind': 'mailMergeSingle', 'sourceSha256': digest, 'sourceBase64': base64.b64encode(content).decode()}]
    await verify_mail_merge_sources(workspace, 'authorized-scope', operations)
    assert calls == [('authorized-scope', f'native/mailmerge/{digest}.csv')]
    workspace.current = b'Name\nForged\n'
    with pytest.raises(ReportingError, match='身份不一致'):
        await verify_mail_merge_sources(workspace, 'authorized-scope', operations)


def test_mail_merge_csv_refuses_unrepresentable_quoted_field_names():
    with pytest.raises(ReportingError):
        parse_mail_merge_csv(b'"Na""me"\nAda\n')


def test_mail_merge_csv_refuses_xml_control_characters_but_keeps_tab_newline():
    with pytest.raises(ReportingError, match='控制字符'):
        parse_mail_merge_csv(b'Name\nA\x00da\n')
    assert parse_mail_merge_csv(b'Name\n"Ada\tA\nB"\n')['records'] == [{'Name': 'Ada\tA\nB'}]


@pytest.mark.anyio
async def test_direct_save_and_changed_source_are_rejected_before_generation(tmp_path, monkeypatch):
    from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication
    from smart_reporting.report_editor.native import bind_native_workspace
    service, context, _ = await create_publication(tmp_path)
    content = b'Name\nAda\n'
    digest = hashlib.sha256(content).hexdigest()
    operation = {'kind': 'mailMergeSingle', 'documentSha256': context.source_file.sha256,
                 'sourceSha256': digest, 'sourceBase64': base64.b64encode(content).decode()}
    # 无上传登记，直接保存也不能只凭自报 SHA 生成。
    with pytest.raises(ReportingError):
        await service.save_revision(context, request_id='missing', expected_sha256=context.source_file.sha256, operations=[operation])
    key = bind_native_workspace(service.workspace, context.scope)
    await service.workspace.awrite_bytes(key, f'native/mailmerge/{digest}.csv', content)
    await verify_mail_merge_sources(service.workspace, key, [operation])
    # 模拟已预览后被篡改，保存必须再次独立回读。
    await service.workspace.awrite_bytes(key, f'native/mailmerge/{digest}.csv', b'Name\nForged\n', overwrite=True)
    with pytest.raises(ReportingError):
        await service.save_revision(context, request_id='changed', expected_sha256=context.source_file.sha256, operations=[operation])


def test_mail_merge_native_bridge_cannot_bypass_alias_namespace_protection(tmp_path, monkeypatch):
    from smart_reporting.reporting.delivery.docx_native import patch_docx
    engine = Path(__file__).resolve().parents[1] / 'doc_engine'
    runtime = tmp_path / 'source-engine'
    runtime.mkdir()
    for name in ('bridge', 'packages', 'node_modules'):
        (runtime / name).symlink_to(engine / name, target_is_directory=True)
    monkeypatch.setenv('AGENT_REPORTING_DOC_ENGINE_DIR', str(runtime))
    document = Document()
    document.add_paragraph('Dear ,')
    stream = BytesIO()
    document.save(stream)
    output = BytesIO()
    with ZipFile(BytesIO(stream.getvalue())) as original, ZipFile(output, 'w') as result:
        for name in original.namelist():
            data = original.read(name)
            if name == 'word/settings.xml':
                data = b'<x:settings xmlns:x="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><x:documentProtection x:enforcement="&#49;"/></x:settings>'
            result.writestr(name, data)
    source = output.getvalue()
    operation = {'kind': 'insertMailMergeField', 'documentSha256': hashlib.sha256(source).hexdigest(),
                 'docxIndex': 0, 'expectedObjectSha256': '0' * 64, 'offset': 5, 'name': 'Name'}
    with pytest.raises(ValueError, match='mail_merge_protected_or_namespace_unsupported'):
        patch_docx(source, [operation])


@pytest.mark.anyio
async def test_docx_preview_checks_doc_runtime_independently_of_slides(tmp_path, monkeypatch):
    from unittest.mock import Mock
    from smart_reporting.report_editor import native
    from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication

    doc_runtime, slides_runtime = tmp_path / 'doc-runtime', tmp_path / 'slides-runtime'
    for runtime, script in ((doc_runtime, 'edit-docx'), (slides_runtime, 'edit-pptx')):
        (runtime / 'dist').mkdir(parents=True)
        (runtime / 'dist' / f'{script}.mjs').write_text('// readiness fixture')
    monkeypatch.setenv('AGENT_REPORTING_DOC_ENGINE_DIR', str(doc_runtime))
    monkeypatch.setenv('AGENT_REPORTING_SLIDES_ENGINE_DIR', str(slides_runtime))
    inspect = Mock(return_value={'paragraphs': []})
    monkeypatch.setattr(native, 'inspect_docx', inspect)
    service, context, _ = await create_publication(tmp_path / 'workspace')
    editor = native.NativeEditorService(service.workspace, service.repository, service.editor_grants, docx_enabled=True)
    try:
        result = await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[])
        assert result['model'] == {'paragraphs': []}
        inspect.assert_called_once_with(await editor.read_file(context))
    finally:
        await service.workspace.registry.aclose()
