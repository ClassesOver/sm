"""多份有界上传按选定顺序追加，复用原派生登记与非阻断下载。"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re

from ..reporting.delivery.office_engine import run_office_engine
from ..reporting.delivery.pdf_native import merge_pdf_files
from ..reporting.models import ReportingError
from .native_models import NativeIssue, native_digest
from .native_pdf_external_pages import MAX_EXTERNAL_PDF_BYTES
from .native_pdf_extract import _publish_derived_pdf


async def merge_pdf(editor, context, *, request_id, files):
    editor.require_enabled('pdf')
    if context.format != 'pdf':
        raise ReportingError('native_format_invalid', '只有 PDF 可以合并文件。')
    if (not isinstance(files, list) or not files or not isinstance(request_id, str)
        or not request_id.strip() or len(request_id) > 256):
        raise ReportingError('native_operations_invalid', '请选择外部 PDF 并提供请求身份。')
    others, total = [], 0
    for upload in files:
        try:
            if not isinstance(upload, dict) or set(upload) != {'sha256', 'bytesBase64'}:
                raise ValueError('external fields')
            if (not isinstance(upload['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', upload['sha256'])
                or not isinstance(upload['bytesBase64'], str)
                or len(upload['bytesBase64']) > 4 * ((MAX_EXTERNAL_PDF_BYTES + 2) // 3)):
                raise ValueError('external identity')
            content = base64.b64decode(upload['bytesBase64'], validate=True)
            total += len(content)
            if (not content.startswith(b'%PDF-') or total > MAX_EXTERNAL_PDF_BYTES
                or base64.b64encode(content).decode() != upload['bytesBase64']
                or hashlib.sha256(content).hexdigest() != upload['sha256']):
                raise ValueError('external content')
        except (ValueError, binascii.Error):
            raise ReportingError('native_operations_invalid', '外部 PDF 内容或 SHA256 无效；上传文件总大小不得超过现有 6 MiB 上限。') from None
        others.append(content)
    if editor.publication is None:
        raise ReportingError('native_engine_unavailable', '原生文件发布服务尚未部署。')
    source = await editor.read_file(context)
    try:
        receipt = await run_office_engine(merge_pdf_files, source, others)
    except ValueError:
        raise ReportingError('native_operations_invalid', '无法读取或合并所选 PDF；请检查文件内容或加密状态。') from None
    external_shas = [hashlib.sha256(value).hexdigest() for value in others]
    result = await _publish_derived_pdf(editor, context, receipt=receipt, request_id=request_id,
        identity_key=native_digest({'action': 'mergePdf', 'context': context.digest(),
            'requestId': request_id, 'externalSha256s': external_shas}), filename='merged.pdf',
        label='合并', issue_prefix='native_pdf_merge', output_error='native_merge_output_unavailable',
        extra_issues=tuple(NativeIssue(code='native_pdf_merge_review', message=message)
            for message in receipt.get('reviewIssues', [])))
    return {**result, 'source': {'documentId': context.document_id, 'revision': context.revision,
        'sha256': context.source_file.sha256, 'externalSha256s': external_shas}}
