"""DOCX 原生编辑的薄桥接；授权与产物发布由上层服务负责。"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from .office_engine import last_json_line, run_bridge

_MAX_BYTES = 24 * 1024 * 1024
_OPERATION_KINDS = frozenset({
    'replaceParagraph', 'insertParagraph', 'insertParagraphImage', 'insertTable', 'deleteParagraph',
    'insertTableRow', 'deleteTableRow', 'insertTableColumn', 'deleteTableColumn',
    'formatParagraph', 'setParagraphVerticalAlign', 'setParagraphLink', 'replaceCellText', 'setParagraphAlignment', 'setParagraphList', 'setParagraphListLevel', 'setParagraphIndent', 'setParagraphRightIndent', 'setParagraphSpacing', 'setParagraphStyle', 'setParagraphShading', 'setParagraphBorders', 'setParagraphPageBreakBefore', 'setSectionLayout', 'setHeaderFooter',
})


def _invoke(content: bytes, operations: list[dict[str, Any]] | None) -> tuple[dict[str, Any], bytes | None]:
    if not isinstance(content, bytes) or not content or len(content) > _MAX_BYTES:
        raise ValueError('docx_content_invalid_or_too_large')
    with tempfile.TemporaryDirectory(prefix='native-docx-') as temporary:
        root = Path(temporary)
        source, output, request = root / 'input.docx', root / 'output.docx', root / 'request.json'
        source.write_bytes(content)
        payload: dict[str, Any] = {'kind': 'inspect' if operations is None else 'patch', 'input': str(source)}
        if operations is not None:
            payload.update(output=str(output), operations=operations)
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError('docx_operation_invalid') from error
        if len(encoded.encode()) > 12 * 1024 * 1024:
            raise ValueError('docx_operations_too_large')
        request.write_text(encoded, encoding='utf-8')
        completed = run_bridge('slides', 'edit-docx', request)
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


def patch_docx(content: bytes, operations: list[dict[str, Any]]) -> bytes:
    if not isinstance(operations, list) or len(operations) > 500 or any(
        not isinstance(operation, dict) or operation.get('kind') not in _OPERATION_KINDS
        for operation in operations
    ):
        raise ValueError('docx_operation_unsupported')
    _, output = _invoke(content, operations)
    assert output is not None
    return output
