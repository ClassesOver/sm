"""固定版本上游 PDF 引擎的字节桥接，不覆盖来源文件。"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from .office_engine import last_json_line, run_bridge


def _invoke(payload: dict[str, Any], root: Path, *, timeout: float = 120) -> dict[str, Any]:
    request = root / 'request.json'
    request.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    completed = run_bridge('pdf', 'cli', request, timeout=timeout)
    if completed.returncode:
        raise ValueError(f'pdf_engine_failed: {completed.stderr[-2000:]}')
    try:
        receipt = last_json_line(completed.stdout)
    except ValueError as error:
        raise ValueError('pdf_engine_receipt_invalid') from error
    if not isinstance(receipt, dict):
        raise ValueError('pdf_engine_receipt_invalid')
    return receipt


def inspect_pdf(content: bytes, *, include_text: bool = False) -> dict[str, Any]:
    """读取源摘要和 PDF user-space 页面信息，页面身份绑定本次源文件。"""
    with tempfile.TemporaryDirectory(prefix='inspect-pdf-') as temporary:
        root = Path(temporary)
        source = root / 'input.pdf'
        source.write_bytes(content)
        receipt = _invoke({'kind': 'inspect', 'input': str(source), 'includeText': include_text}, root)
        if receipt.get('sourceSha256') != hashlib.sha256(content).hexdigest():
            raise ValueError('pdf_engine_source_identity_invalid')
        return receipt


def patch_pdf_with_receipt(content: bytes, operations: list[dict[str, Any]]) -> dict[str, Any]:
    """返回新字节及文字修改执行/跳过回执；调用方须显式呈现跳过原因。"""
    if not isinstance(operations, list) or any(not isinstance(op, dict) for op in operations):
        raise ValueError('pdf_operation_invalid')
    with tempfile.TemporaryDirectory(prefix='patch-pdf-') as temporary:
        root = Path(temporary)
        source, output = root / 'input.pdf', root / 'output.pdf'
        source.write_bytes(content)
        receipt = _invoke({
            'kind': 'patch', 'input': str(source), 'output': str(output),
            'sourceSha256': hashlib.sha256(content).hexdigest(), 'operations': operations,
        }, root)
        result = output.read_bytes()
        if (
            not result or receipt.get('size') != len(result)
            or receipt.get('sourceSha256') != hashlib.sha256(content).hexdigest()
            or receipt.get('sha256') != hashlib.sha256(result).hexdigest()
        ):
            raise ValueError('pdf_engine_output_identity_invalid')
        return {**receipt, 'content': result}


def patch_pdf(content: bytes, operations: list[dict[str, Any]]) -> bytes:
    """兼容字节调用；文字修改跳过时必须显式失败，避免吞掉未执行修改。"""
    if not isinstance(operations, list) or any(not isinstance(op, dict) for op in operations):
        raise ValueError('pdf_operation_invalid')
    if not operations:
        return content
    receipt = patch_pdf_with_receipt(content, operations)
    if receipt.get('skippedOperations'):
        raise ValueError('pdf_text_operations_skipped')
    return receipt['content']


def check_text_resources() -> dict[str, Any]:
    """用真实中文数字替换验证当前部署的 PDFium、字体选择和嵌入链。"""
    with tempfile.TemporaryDirectory(prefix='pdf-text-resources-') as temporary:
        return _invoke({'kind': 'textResources'}, Path(temporary), timeout=15)
