"""从已保存 PDF 派生独立 Office 文档；后置故障不得丢弃实际可核验产物。"""
from __future__ import annotations

import hashlib
import subprocess

from loguru import logger

from ..office.artifacts import ArtifactFile
from ..reporting.delivery.office_engine import run_office_engine
from ..reporting.delivery.pdf_native import convert_pdf_office
from ..reporting.models import ReportingError
from ._file_identity import read_verified_file
from .native_models import (
    NativeArtifacts,
    NativeEditorContext,
    NativeIssue,
    NativeSource,
    NativeValidation,
    native_digest,
)


async def convert_office(editor, context, *, expected_sha256: str, request_id: str, output_format: str = 'pptx'):
    from .native import bind_native_workspace

    editor.require_enabled('pdf')
    if context.format != 'pdf' or output_format not in {'pptx', 'docx', 'xlsx'}:
        raise ReportingError('native_format_invalid', '目前支持从 PDF 转换为 DOCX、XLSX 或 PPTX。')
    if expected_sha256 != context.source_file.sha256:
        raise ReportingError('native_source_changed', 'PDF 来源身份已变化，请重新打开修订。')
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 256:
        raise ReportingError('native_operations_invalid', '请提供有效的转换请求身份。')
    if editor.publication is None:
        raise ReportingError('native_engine_unavailable', '原生文件发布服务尚未部署。')
    source = await editor.read_file(context)
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        raise ReportingError('native_source_changed', 'PDF 实际文件身份已变化。')
    try:
        receipt = await run_office_engine(convert_pdf_office, source, output_format=output_format)
    except ValueError:
        raise ReportingError('native_operations_invalid', 'PDF 转换失败；请检查来源保护信息、50 页与文件/像素预算。') from None
    except (OSError, subprocess.SubprocessError):
        raise ReportingError('native_engine_unavailable', 'PDF 本地转换引擎暂不可用。') from None
    label = output_format.upper()
    artifact_key = {'docx': 'word', 'xlsx': 'xlsx', 'pptx': 'pptx'}[output_format]
    media_type = {'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'}[output_format]
    content = receipt['content']
    if not isinstance(content, bytes) or not content:
        raise ReportingError('native_conversion_output_unavailable', f'没有生成可读取的 {label} 文件。')
    issues = [NativeIssue(code='native_conversion_review_pending', message=f'{label} 已生成并核验文件身份，尚未通过完整内容与版式保真验收，请人工核对。')]
    raw_validation = receipt.get('validation', {})
    if isinstance(raw_validation, dict):
        raw_issues = raw_validation.get('issues')
        if isinstance(raw_issues, list):
            issues.extend(NativeIssue(code='native_conversion_warning', message=message[:2000]) for message in raw_issues[:200] if isinstance(message, str) and message)
    key = bind_native_workspace(editor.workspace, context.scope)
    identity_key = native_digest({'context': context.digest(), 'requestId': request_id, 'format': output_format})
    actual_sha = hashlib.sha256(content).hexdigest()
    # Content-addressed file names preserve concurrent/retry outputs without overwrite.
    path = f'native/derived/{identity_key}/converted-{actual_sha}.{output_format}'
    identity = ArtifactFile(path=path, size=len(content), sha256=actual_sha, mediaType=media_type)
    try:
        await editor.workspace.awrite_bytes(key, path, content)
    except Exception:
        issues.append(NativeIssue(code='native_conversion_postwrite_warning', message=f'{label} 工作区写入回执异常；继续核验实际文件并保留可用下载。'))
        logger.warning('native_pdf_conversion_write_receipt_failed')
    try:
        await read_verified_file(editor.workspace, {'threadId': key}, path, size=identity.size, sha256=identity.sha256, error_code='native_conversion_output_unavailable', format_name=label)
    except Exception:
        # A failed review helper is not proof the actual file disappeared.
        try:
            actual, _ = await editor.workspace.afile_bytes(key, path)
            if len(actual) != identity.size or hashlib.sha256(actual).hexdigest() != identity.sha256:
                raise ValueError('actual identity mismatch')
        except Exception:
            raise ReportingError('native_conversion_output_unavailable', f'{label} 实际文件无法读取或身份不匹配，暂无法签发下载。') from None
        issues.append(NativeIssue(code='native_conversion_review_failed', message=f'{label} 后置复核异常，但实际文件身份已重新核验，下载仍可用。'))
    derived = NativeSource(format=output_format, origin='derived', sourceFile=identity, parentDocumentId=context.document_id, parentRevision=context.revision, parentSha256=context.source_file.sha256)
    child_context = NativeEditorContext(documentId=identity_key, revision=1, format=output_format, scope=context.scope, sourceFile=identity, origin='derived')
    registered = False
    if len(content) > 24 * 1024 * 1024:
        issues.append(NativeIssue(code='native_file_too_large', message=f'{label} 超过 24 MiB 在线编辑上限，保留下载但不开放在线编辑。'))
    else:
        try:
            child = await editor.repository.create_from_source(derived, scope=context.scope, request_id=request_id)
            revision = await editor.repository.get_revision(child.document_id, 1, scope=context.scope)
            if (revision is None or revision.context is None or revision.status != 'saved'
                or revision.context.source_file != identity or revision.context.scope != context.scope
                or revision.context.document_id != child.document_id or revision.context.revision != 1
                or revision.context.format != output_format or revision.context.origin != 'derived'):
                raise ValueError('derived identity mismatch')
            child_context = revision.context
            registered = True
        except Exception:
            issues.append(NativeIssue(code='native_derived_registration_failed', message=f'派生 {label} 文档登记失败，已核验实际文件的下载仍可用。'))
            logger.bind(documentId=context.document_id, revision=context.revision).warning('native_pdf_conversion_registration_failed')
    result = await editor.publication._publish_artifacts(child_context, NativeArtifacts(**{artifact_key: identity}), NativeValidation(ok=False, issues=tuple(issues)), registered, key, allow_editor=editor.is_enabled(output_format))
    return {**result, 'source': {'documentId': context.document_id, 'revision': context.revision, 'sha256': context.source_file.sha256},
        'conversion': {'format': output_format, 'pages': receipt.get('pages'), 'warnings': receipt.get('warnings', []), 'pageResults': receipt.get('pageResults', []), 'scannedDocument': receipt.get('scannedDocument', False)}}
