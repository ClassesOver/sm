"""DOCX 原生编辑的薄桥接；授权与产物发布由上层服务负责。"""
from __future__ import annotations

import hashlib
import json
import tempfile
import base64
import binascii
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from .office_engine import last_json_line, run_bridge
from ..models import ReportingError

_MAX_BYTES = 24 * 1024 * 1024
_OPERATION_KINDS = frozenset({
    'formatTableProperties', 'replaceImage', 'setParagraphDropCap',
    'setParagraphProperties',
    'setParagraphCustomList', 'setParagraphNumberingValue',
    'insertCrossReference', 'insertCaption', 'pasteRichContent', 'mailMergeSingle', 'insertMailMergeField', 'editEquations', 'setPageColor', 'setWatermark',
    'createBookmark', 'deleteBookmark', 'insertToc', 'updateToc', 'deleteComment', 'resolveComment', 'replyComment', 'createComment', 'editCommentText', 'resolveTextRevision', 'recordTextRevision', 'setTrackRevisions', 'insertNote', 'updateNote', 'deleteNote', 'patchParagraphRuns',
    'clearParagraphFormatting', 'setParagraphRulerIndent', 'setParagraphTabStops', 'setTableCellBorders', 'setTableRepeatHeaders', 'reshapeTableCells', 'resizeTableColumns', 'setTableRowHeights', 'setTableAutoFit', 'setTableCellTextDirection', 'setTableCellAlignment', 'setTableCellMargins', 'setTableCellMarginOverrides', 'setTableRowBreaks', 'setTableAlignment', 'setTableCellWrap', 'setTableAltText',
    'replaceParagraph', 'insertParagraph', 'insertParagraphImage', 'insertTable', 'insertCoverPage', 'deleteParagraph',
    'insertTableRow', 'deleteTableRow', 'insertTableColumn', 'deleteTableColumn', 'restructureTable', 'insertSectionBreak',
    'formatParagraph', 'formatRange', 'setParagraphVerticalAlign', 'setParagraphLink', 'replaceNestedCellText', 'replaceCellText', 'setCellShading', 'setTableCellParagraphProperties', 'setParagraphAlignment', 'setParagraphList', 'setParagraphListLevel', 'setParagraphIndent', 'setParagraphRightIndent', 'setParagraphSpecialIndent', 'setParagraphSpacing', 'setParagraphStyle', 'upsertStyle', 'applyDocumentStyle', 'setParagraphShading', 'setParagraphBorders', 'setParagraphPageBreakBefore', 'setSectionLayout', 'setHeaderFooter', 'setHeaderFooterLink',
})


def _validate_paste_images(operations: list[dict[str, Any]]) -> None:
    """Fully decode rich-paste PNG/JPEG bytes before handing them to the bridge."""
    for operation in operations:
        if operation.get('kind') != 'pasteRichContent':
            continue
        stack = list(operation.get('blocks', [])) if isinstance(operation.get('blocks'), list) else []
        while stack:
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            attrs = node.get('attrs')
            if node.get('type') == 'docInlineImage' and isinstance(attrs, dict):
                data_url = attrs.get('dataUrl')
                if not isinstance(data_url, str) or not data_url.startswith('data:image/'):
                    raise ValueError('docx_image_invalid')
                try:
                    header, encoded = data_url.split(',', 1)
                    mime = header[5:].split(';', 1)[0]
                    if mime not in {'image/png', 'image/jpeg'} or not header.endswith(';base64'):
                        raise ValueError
                    content = base64.b64decode(encoded, validate=True)
                    if not content or len(content) > 8 * 1024 * 1024:
                        raise ValueError
                    with Image.open(BytesIO(content)) as image:
                        if image.format != {'image/png': 'PNG', 'image/jpeg': 'JPEG'}[mime] or image.width * image.height > 40_000_000:
                            raise ValueError
                        image.verify()
                    with Image.open(BytesIO(content)) as image:
                        image.load()
                except (ValueError, binascii.Error, OSError, Image.DecompressionBombError):
                    raise ValueError('docx_image_invalid') from None
            children = node.get('content')
            if isinstance(children, list):
                stack.extend(children)


def _invoke(content: bytes, operations: list[dict[str, Any]] | None, revision_author: str | None = None) -> tuple[dict[str, Any], bytes | None]:
    if not isinstance(content, bytes) or not content or len(content) > _MAX_BYTES:
        raise ValueError('docx_content_invalid_or_too_large')
    with tempfile.TemporaryDirectory(prefix='native-docx-') as temporary:
        root = Path(temporary)
        source, output, request = root / 'input.docx', root / 'output.docx', root / 'request.json'
        source.write_bytes(content)
        payload: dict[str, Any] = {'kind': 'inspect' if operations is None else 'patch', 'input': str(source)}
        if operations is not None:
            payload.update(output=str(output), operations=operations)
            if any(operation.get('kind') == 'recordTextRevision' for operation in operations):
                if not isinstance(revision_author, str) or not revision_author or len(revision_author) > 255:
                    raise ValueError('docx_revision_author_unavailable')
                payload.update(revisionAuthor=revision_author, revisionDate=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'))
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError('docx_operation_invalid') from error
        if len(encoded.encode()) > 12 * 1024 * 1024:
            raise ValueError('docx_operations_too_large')
        request.write_text(encoded, encoding='utf-8')
        completed = run_bridge('doc', 'edit-docx', request)
        if completed.returncode:
            raise ValueError(f'docx_engine_failed: {completed.stderr[-2000:]}')
        try:
            receipt = last_json_line(completed.stdout)
        except ValueError as error:
            raise ValueError('docx_engine_receipt_invalid') from error
        if not isinstance(receipt, dict):
            raise ValueError('docx_engine_receipt_invalid')
        if receipt.get('sourceSha256') != hashlib.sha256(content).hexdigest():
            raise ValueError('docx_source_identity_mismatch')
        if operations is None:
            return receipt, None
        if not output.is_file() or not output.stat().st_size:
            raise ValueError('docx_output_unavailable')
        result = output.read_bytes()
        if type(receipt.get('size')) is not int or receipt['size'] != len(result) or receipt.get('sha256') != hashlib.sha256(result).hexdigest():
            raise ValueError('docx_output_identity_mismatch')
        return receipt, result


def inspect_docx(content: bytes) -> dict[str, Any]:
    return _invoke(content, None)[0]


def patch_docx(content: bytes, operations: list[dict[str, Any]], *, revision_author: str | None = None) -> bytes:
    if not isinstance(operations, list) or len(operations) > 500 or any(
        not isinstance(operation, dict) or operation.get('kind') not in _OPERATION_KINDS
        for operation in operations
    ):
        raise ValueError('docx_operation_unsupported')
    if any(operation.get('kind') == 'mailMergeSingle' for operation in operations):
        if len(operations) != 1:
            raise ValueError('docx_mail_merge_batch_conflict')
        from ...report_editor.native_mail_merge import normalize_mail_merge_operations

        try:
            operations = normalize_mail_merge_operations(operations)
        except ReportingError as error:
            raise ValueError(error.code) from error
    _validate_paste_images(operations)
    _, output = _invoke(content, operations, revision_author)
    assert output is not None
    return output
