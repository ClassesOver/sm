"""可信四维作用域的文件导入；校验实际内容后才创建独立文档。"""
from __future__ import annotations

import hashlib
import subprocess
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from zipfile import ZipFile

from defusedxml import ElementTree
from pypdf import PdfReader

from ..reporting.delivery.artifacts_v1 import ArtifactFile
from ..reporting.delivery.docx_native import inspect_docx
from ..reporting.delivery.office_engine import run_office_engine
from ..reporting.delivery.pdf_native import inspect_pdf
from ..reporting.delivery.xlsx import inspect_workbook
from ..reporting.models import ReportingError
from ..workspace import WorkspacePathConflict
from ._file_identity import read_verified_file
from .native import NativeEditorService, bind_native_workspace
from .native_models import NATIVE_MEDIA, NativeFormat, NativeScope, NativeSource, native_digest
from .slides import ReportSlidesEditorService

MAX_IMPORT_BYTES = 24 * 1024 * 1024
_MAX_PART_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_BYTES = 128 * 1024 * 1024
_MAIN_PARTS: dict[str, tuple[NativeFormat, str]] = {
    'word/document.xml': ('docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'),
    'xl/workbook.xml': ('xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'),
    'ppt/presentation.xml': ('pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml'),
}
_REJECTED_EXTENSIONS = {'.doc', '.xls', '.ppt', '.docm', '.xlsm', '.pptm', '.dotm', '.xltm', '.potm', '.ppsm', '.xlsb'}


def _invalid() -> ReportingError:
    return ReportingError('native_import_invalid', '文件内容无效或不受支持；仅支持未加密、无宏的 PDF、DOCX、XLSX、PPTX。')


def inspect_native_upload(content: bytes, *, filename: str = '') -> NativeFormat:
    """名称不参与格式选择；标准库仅检查容器，Office 内容交给既有引擎解析。"""
    if not isinstance(content, bytes) or not content or len(content) > MAX_IMPORT_BYTES:
        raise ReportingError('native_import_size_invalid', '文件必须为 1 字节至 24 MiB。')
    if PurePosixPath(filename.replace('\\', '/')).suffix.lower() in _REJECTED_EXTENSIONS:
        raise _invalid()
    try:
        if content.startswith(b'%PDF-'):
            reader = PdfReader(BytesIO(content), strict=True)
            if reader.is_encrypted or not len(reader.pages):
                raise _invalid()
            inspect_pdf(content)
            return 'pdf'
        if not content.startswith(b'PK\x03\x04'):
            raise _invalid()
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) > 10000 or len(set(names)) != len(names):
                raise _invalid()
            total = 0
            for entry in entries:
                name = entry.filename
                if (entry.flag_bits & 1 or '\\' in name or '\x00' in name or name.startswith('/')
                    or '..' in PurePosixPath(name).parts or ':' in name or 'vbaproject' in name.lower()
                    or entry.file_size > _MAX_PART_BYTES):
                    raise _invalid()
                # 逐块计量实际膨胀字节，不能只相信 ZIP 中央目录声明。
                actual = 0
                with archive.open(entry) as stream:
                    while chunk := stream.read(65536):
                        actual += len(chunk)
                        total += len(chunk)
                        if actual > _MAX_PART_BYTES or total > _MAX_TOTAL_BYTES:
                            raise _invalid()
                if actual != entry.file_size:
                    raise _invalid()
            info = archive.getinfo('[Content_Types].xml')
            if info.file_size > 1024 * 1024:
                raise _invalid()
            types = ElementTree.fromstring(archive.read(info))
            if types.tag != '{http://schemas.openxmlformats.org/package/2006/content-types}Types':
                raise _invalid()
            overrides: dict[str, str] = {}
            for item in types:
                kind = item.attrib.get('ContentType', '')
                if 'macroenabled' in kind.lower() or 'vbaproject' in kind.lower():
                    raise _invalid()
                if item.tag == '{http://schemas.openxmlformats.org/package/2006/content-types}Override':
                    name = item.attrib.get('PartName', '').removeprefix('/')
                    if name in overrides:
                        raise _invalid()
                    overrides[name] = kind
            candidates = [(format, part) for part, (format, kind) in _MAIN_PARTS.items() if part in names and overrides.get(part) == kind]
            if len(candidates) != 1 or sum(part in names for part in _MAIN_PARTS) != 1:
                raise _invalid()
            format, _ = candidates[0]
        if format == 'docx':
            inspect_docx(content)
        elif format == 'xlsx':
            inspect_workbook(content)
        else:
            ReportSlidesEditorService._run_engine(content, 'inspect')
        return format
    except (OSError, subprocess.SubprocessError):
        raise ReportingError('native_engine_unavailable', '文件解析引擎暂不可用，请稍后重试。') from None
    except ReportingError as error:
        if error.code in {'native_engine_unavailable', 'native_feature_disabled'}:
            raise
        # 不暴露引擎临时路径、上传内容或堆栈到调用方。
        raise _invalid() from None
    except Exception:
        raise _invalid() from None


class NativeImportService:
    def __init__(self, workspace: Any, repository: Any, grants: Any):
        self.workspace, self.repository, self.grants = workspace, repository, grants

    async def import_file(self, scope: NativeScope, content: bytes, *, request_id: str, filename: str = '', display_name: str | None = None) -> dict[str, Any]:
        """scope 必须由宿主可信会话构造，不接收上传表单中的身份字段。"""
        if not isinstance(scope, NativeScope) or not isinstance(request_id, str) or not request_id or len(request_id) > 256:
            raise ReportingError('native_import_request_invalid', '文件导入请求身份无效。')
        format = await run_office_engine(inspect_native_upload, content, filename=filename)
        digest = hashlib.sha256(content).hexdigest()
        key = bind_native_workspace(self.workspace, scope)
        copy_id = native_digest({'scope': scope.model_dump(), 'sha256': digest, 'requestId': request_id})
        path = f'native/uploads/{copy_id}/original.{format}'
        identity = ArtifactFile(path=path, size=len(content), sha256=digest, mediaType=NATIVE_MEDIA[format])
        try:
            await self.workspace.awrite_bytes(key, path, content)
        except WorkspacePathConflict:
            pass
        await read_verified_file(self.workspace, {'threadId': key}, path, size=identity.size,
            sha256=identity.sha256, error_code='native_import_source_changed', format_name=format.upper())
        source = NativeSource(format=format, origin='upload', sourceFile=identity, displayName=display_name)
        document = await self.repository.create_from_source(source, scope=scope, request_id=request_id)
        revision = await self.repository.get_revision(document.document_id, 1, scope=scope)
        if revision is None or revision.context is None:
            raise ReportingError('native_document_not_found', '上传文档修订尚未登记。')
        grant, expires = await self.grants.issue(revision.context, capabilities=NativeEditorService.capabilities(revision.context))
        return {'documentId': document.document_id, 'revision': 1, 'parentRevision': None,
            'format': format, 'editor': {'url': f'/reports/v1/native/open/{grant}', 'expiresAt': expires.isoformat()}}
