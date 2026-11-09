"""上传先验证实际文件，成功后才登记独立原生文档。"""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from smart_reporting.report_editor.native_models import NativeScope
from smart_reporting.reporting.models import ReportingError


def file_bytes(format):
    stream = BytesIO()
    if format == 'pdf':
        from pypdf import PdfWriter
        writer = PdfWriter(); writer.add_blank_page(width=300, height=400); writer.write(stream)
    elif format == 'docx':
        from docx import Document
        document = Document(); document.add_paragraph('导入正文'); document.save(stream)
    elif format == 'xlsx':
        from openpyxl import Workbook
        workbook = Workbook(); workbook.active['A1'] = '上传数据'; workbook.save(stream)
    else:
        from pptx import Presentation
        presentation = Presentation(); presentation.slides.add_slide(presentation.slide_layouts[6]); presentation.save(stream)
    return stream.getvalue()


def change_zip(content, *, add=None, replace=None):
    stream = BytesIO()
    with ZipFile(BytesIO(content)) as source, ZipFile(stream, 'w', ZIP_DEFLATED) as target:
        for item in source.infolist():
            target.writestr(item.filename, (replace or {}).get(item.filename, source.read(item)))
        for name, value in (add or {}).items(): target.writestr(name, value)
    return stream.getvalue()


@pytest.mark.parametrize('format', ['pdf', 'docx', 'xlsx', 'pptx'])
def test_detects_real_formats_without_trusting_filename(format):
    from smart_reporting.report_editor.native_import import inspect_native_upload
    result = inspect_native_upload(file_bytes(format), filename='伪装.pdf')
    assert result == format


@pytest.mark.parametrize('content,filename', [(b'%PDF-1.4\nnot a pdf', 'ok.pdf'), (b'hello', 'ok.docx'), (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1', 'ok.xlsx'), (b'', 'ok.pdf')])
def test_rejects_spoofed_corrupt_or_legacy_files(content, filename):
    from smart_reporting.report_editor.native_import import inspect_native_upload
    with pytest.raises(ReportingError): inspect_native_upload(content, filename=filename)


def test_rejects_macros_duplicate_parts_and_zip_paths():
    from smart_reporting.report_editor.native_import import inspect_native_upload
    content = file_bytes('docx')
    for name in ['word/vbaProject.bin', '../outside.xml', 'word/document.xml']:
        with pytest.raises(ReportingError): inspect_native_upload(change_zip(content, add={name: b'payload'}), filename='ok.docx')
    with pytest.raises(ReportingError): inspect_native_upload(content, filename='macro.docm')


def test_rejects_encrypted_pdf_and_expanded_zip_limit():
    from pypdf import PdfWriter
    from smart_reporting.report_editor.native_import import inspect_native_upload
    writer = PdfWriter(); writer.add_blank_page(width=300, height=400); writer.encrypt('secret'); stream = BytesIO();writer.write(stream)
    with pytest.raises(ReportingError): inspect_native_upload(stream.getvalue())
    with pytest.raises(ReportingError): inspect_native_upload(change_zip(file_bytes('docx'), add={'word/bomb.xml': b'0' * (65*1024*1024)}))


@pytest.fixture
def anyio_backend(): return 'asyncio'


@pytest.mark.anyio
async def test_invalid_upload_never_writes_or_registers():
    from smart_reporting.report_editor.native_import import NativeImportService
    workspace = SimpleNamespace(awrite_bytes=AsyncMock()); repository = SimpleNamespace(create_from_source=AsyncMock())
    service = NativeImportService(workspace, repository, SimpleNamespace())
    scope = NativeScope(database='db', companyId='c', userId='u', threadId='t')
    with pytest.raises(ReportingError): await service.import_file(scope, b'fake', request_id='r')
    workspace.awrite_bytes.assert_not_called(); repository.create_from_source.assert_not_called()

@pytest.mark.anyio
@pytest.mark.parametrize('format', ['pdf', 'docx', 'xlsx', 'pptx'])
async def test_import_registers_verified_copy_and_scope_bound_grant(tmp_path, format):
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4
    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.report_editor.native_import import NativeImportService
    from smart_reporting.report_editor.native_models import NativeDocument, NativeEditorContext, NativeRevision, NativeArtifacts, NATIVE_ARTIFACT_KEYS, native_digest
    from smart_reporting.reporting.host_workspace import ReportingWorkspaceRegistry, ReportingWorkspaceRouter

    class Repository:
        def __init__(self): self.documents = {}; self.revisions = {}
        async def create_from_source(self, source, *, scope, request_id):
            key = native_digest([source.model_dump(mode='json'), scope.model_dump(), request_id])
            if key in self.documents: return self.documents[key]
            document = NativeDocument(documentId=uuid4().hex, scope=scope, ownerId=scope.user_id,
                source=source, createdAt=datetime.now(UTC), nextRevision=2)
            context = NativeEditorContext(documentId=document.document_id, format=source.format, revision=1,
                scope=scope, sourceFile=source.source_file, origin=source.origin)
            self.documents[key] = document
            self.revisions[document.document_id] = NativeRevision(documentId=document.document_id, revision=1,
                scope=scope, requestId=request_id, requestSha256=key, status='saved', context=context,
                artifacts=NativeArtifacts(**{NATIVE_ARTIFACT_KEYS[format]:source.source_file}),createdAt=datetime.now(UTC))
            return document
        async def get_revision(self, document_id, revision, *, scope):
            result = self.revisions.get(document_id)
            return result if result and result.scope == scope and revision == 1 else None

    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(tmp_path / 'native', secret='s'*32))
    repository = Repository()
    grants = SimpleNamespace(issue=AsyncMock(return_value=('test-grant', datetime.now(UTC)+timedelta(minutes=5))))
    service = NativeImportService(workspace, repository, grants)
    scope = NativeScope(database='db', companyId='c', userId='u', threadId='t')
    content = file_bytes(format)
    first = await service.import_file(scope, content, request_id='upload-1', filename='wrong.pdf')
    second = await service.import_file(scope, content, request_id='upload-1')
    assert first['documentId'] == second['documentId'] and first['format'] == format
    document = next(iter(repository.documents.values()))
    assert document.source.origin == 'upload' and document.source.report_id is None
    assert document.source.source_file.path.startswith('native/uploads/')
    actual, _ = await workspace.afile_bytes(bind_native_workspace(workspace, scope), document.source.source_file.path)
    assert actual == content
    assert grants.issue.await_args.args[0].scope == scope
    other = scope.model_copy(update={'user_id':'other'})
    third = await service.import_file(other, content, request_id='upload-1')
    assert third['documentId'] != first['documentId']


def test_rejects_wrong_content_type_and_missing_or_ambiguous_primary_parts():
    from smart_reporting.report_editor.native_import import inspect_native_upload
    content = file_bytes('docx')
    with ZipFile(BytesIO(content)) as source: original = source.read('[Content_Types].xml')
    changed = original.replace(b'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml', b'application/vnd.ms-word.document.macroEnabled.main+xml')
    with pytest.raises(ReportingError): inspect_native_upload(change_zip(content, replace={'[Content_Types].xml':changed}))
    with pytest.raises(ReportingError): inspect_native_upload(change_zip(content, replace={'word/document.xml':b'<invalid/>'}))


def test_rejects_two_primary_parts_even_when_second_has_no_content_type():
    from smart_reporting.report_editor.native_import import inspect_native_upload
    with pytest.raises(ReportingError):
        inspect_native_upload(change_zip(file_bytes('docx'), add={'xl/workbook.xml':b'<workbook/>'}))


@pytest.mark.anyio
async def test_copy_identity_failure_never_registers_document(tmp_path):
    from smart_reporting.report_editor.native_import import NativeImportService
    from smart_reporting.reporting.host_workspace import ReportingWorkspaceRegistry, ReportingWorkspaceRouter
    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(tmp_path / 'native', secret='s'*32))
    write = workspace.awrite_bytes
    async def tamper(key, path, content): await write(key, path, b'tampered')
    workspace.awrite_bytes = tamper
    repository = SimpleNamespace(create_from_source=AsyncMock())
    service = NativeImportService(workspace, repository, SimpleNamespace())
    scope = NativeScope(database='db', companyId='c', userId='u', threadId='t')
    with pytest.raises(ReportingError) as error: await service.import_file(scope, file_bytes('pdf'), request_id='upload-1')
    assert error.value.code == 'native_import_source_changed'
    repository.create_from_source.assert_not_called()


def test_valid_upload_reports_engine_deployment_failure_separately(monkeypatch):
    from smart_reporting.report_editor import native_import
    from reportlab.pdfgen.canvas import Canvas
    from io import BytesIO
    stream=BytesIO();canvas=Canvas(stream);canvas.drawString(10,10,'valid');canvas.save()
    def unavailable(_content):
        raise FileNotFoundError('node missing')
    monkeypatch.setattr(native_import,'inspect_pdf',unavailable)
    with pytest.raises(ReportingError) as caught:
        native_import.inspect_native_upload(stream.getvalue())
    assert caught.value.code=='native_engine_unavailable'
