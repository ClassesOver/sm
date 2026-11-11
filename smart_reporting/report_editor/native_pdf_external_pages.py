"""有界外部 PDF 上传只形成独立保存操作，复用既有不变修订和非阻断签发。"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
from typing import Literal

from ..reporting.models import ReportingError

MAX_EXTERNAL_PDF_BYTES = 6 * 1024 * 1024


async def external_pages(
    editor, context, *, action: Literal['insert', 'replace'], request_id: str,
    expected_sha256: str, external_sha256: str, bytes_base64: str,
    after_page: int | None = None, pages: list[int] | None = None,
):
    editor.require_enabled('pdf')
    if context.format != 'pdf':
        raise ReportingError('native_format_invalid', '只有 PDF 可以插入或替换外部页面。')
    if expected_sha256 != context.source_file.sha256:
        raise ReportingError('native_source_changed', '父 PDF 来源身份已变化，请重新打开修订。')
    valid = (isinstance(request_id, str) and bool(request_id.strip()) and len(request_id) <= 256
        and isinstance(external_sha256, str) and re.fullmatch(r'[a-f0-9]{64}', external_sha256)
        and isinstance(bytes_base64, str) and 8 <= len(bytes_base64) <= 4 * ((MAX_EXTERNAL_PDF_BYTES + 2) // 3))
    if action == 'insert':
        valid = valid and type(after_page) is int and 0 <= after_page <= 10000 and pages is None
    elif action == 'replace':
        valid = valid and after_page is None and isinstance(pages, list) and 1 <= len(pages) <= 10000
        valid = valid and all(type(page) is int and 1 <= page <= 10000 for page in pages) and len(set(pages)) == len(pages)
    else:
        valid = False
    if not valid:
        raise ReportingError('native_operations_invalid', '外部 PDF 请求、页码或文件身份无效。')
    try:
        external = base64.b64decode(bytes_base64, validate=True)
        if (not 1 <= len(external) <= MAX_EXTERNAL_PDF_BYTES or not external.startswith(b'%PDF-')
            or base64.b64encode(external).decode() != bytes_base64
            or hashlib.sha256(external).hexdigest() != external_sha256):
            raise ValueError('external identity')
    except (ValueError, binascii.Error):
        raise ReportingError('native_operations_invalid', '外部 PDF 内容或 SHA256 不匹配。') from None
    source = await editor.read_file(context)
    if hashlib.sha256(source).hexdigest() != expected_sha256:
        raise ReportingError('native_source_changed', '父 PDF 实际文件身份已变化。')
    operation = {'kind': 'externalPages', 'action': action, 'sourceSha256': expected_sha256,
        'externalSha256': external_sha256, 'bytesBase64': bytes_base64}
    if action == 'insert':
        operation['afterPageIndex'] = after_page - 1
    else:
        operation['pages'] = [page - 1 for page in pages]
    # 引擎严格验证双方 PDF 及输出，editor.save 保留既有预约、恢复、验收和下载逻辑。
    return await editor.save(context, request_id=request_id, expected_sha256=expected_sha256, operations=[operation])
