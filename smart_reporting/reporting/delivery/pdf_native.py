"""固定版本上游 PDF 引擎的字节桥接，不覆盖来源文件。"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

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


def extract_pdf_pages(content: bytes, pages: list[int]) -> dict[str, Any]:
    """Create a separately identified PDF containing the requested source pages."""
    if not isinstance(content, bytes) or not content or not isinstance(pages, list):
        raise ValueError('pdf_extract_pages_invalid')
    with tempfile.TemporaryDirectory(prefix='extract-pdf-pages-') as temporary:
        root = Path(temporary)
        source, output = root / 'input.pdf', root / 'output.pdf'
        source.write_bytes(content)
        review_issues = []
        try:
            receipt = _invoke({'kind': 'extractPages', 'input': str(source), 'output': str(output), 'pages': pages}, root)
        except Exception:
            if not output.is_file():
                raise
            receipt = {}
            review_issues.append('pdf_extract_receipt_failed_actual_output_retained')
            logger.warning('pdf_extract_receipt_failed_actual_output_retained')
        result = output.read_bytes()
        if not result:
            raise ValueError('pdf_extract_output_unavailable')
        actual_sha = hashlib.sha256(result).hexdigest()
        if (
            receipt.get('sourceSha256') != hashlib.sha256(content).hexdigest()
            or receipt.get('sha256') != actual_sha
            or type(receipt.get('size')) is not int or receipt['size'] != len(result)
            or type(receipt.get('pageCount')) is not int or receipt['pageCount'] != len(pages)
        ):
            # 不使用身份不一致的回执元数据，下载仍绑定实际文件字节。
            receipt = {}
            review_issues.append('pdf_extract_receipt_identity_failed_actual_output_retained')
        return {**receipt, 'content': result, 'sourceSha256': hashlib.sha256(content).hexdigest(),
            'sha256': actual_sha, 'size': len(result), 'reviewIssues': review_issues}


def check_text_resources() -> dict[str, Any]:
    """用真实中文数字替换验证当前部署的 PDFium、字体选择和嵌入链。"""
    with tempfile.TemporaryDirectory(prefix='pdf-text-resources-') as temporary:
        return _invoke({'kind': 'textResources'}, Path(temporary), timeout=15)


def protect_pdf(content: bytes, *, user_password: str, owner_password: str,
                permissions: dict[str, bool]) -> dict[str, Any]:
    """密码仅保存在权限隔离的临时请求目录，返回值不包含密码。"""
    with tempfile.TemporaryDirectory(prefix='protect-pdf-') as temporary:
        root = Path(temporary)
        source, output = root / 'input.pdf', root / 'output.pdf'
        source.write_bytes(content)
        source_sha = hashlib.sha256(content).hexdigest()
        review_issues = []
        try:
            receipt = _invoke({'kind': 'protect', 'input': str(source), 'output': str(output),
                'protection': {'sourceSha256': source_sha,
                    'userPassword': user_password, 'ownerPassword': owner_password,
                    'permissions': permissions}}, root)
        except Exception:
            if not output.is_file():
                raise
            receipt = {}
            review_issues.append('pdf_protection_receipt_failed_actual_output_retained')
            logger.warning('pdf_protection_receipt_failed_actual_output_retained')
        result = output.read_bytes()
        if not result:
            raise ValueError('pdf_protection_output_unavailable')
        actual_sha = hashlib.sha256(result).hexdigest()
        if (receipt.get('sourceSha256') != source_sha or receipt.get('sha256') != actual_sha
            or type(receipt.get('size')) is not int or receipt['size'] != len(result)
            or receipt.get('algorithm') != 'AES-256' or receipt.get('revision') != 6):
            # Reject the inconsistent receipt, not the readable actual output.
            receipt = {}
            review_issues.append('pdf_protection_receipt_identity_failed_actual_output_retained')
        previous_issues = receipt.get('reviewIssues')
        if isinstance(previous_issues, list):
            review_issues.extend(issue for issue in previous_issues if isinstance(issue, str))
        return {**receipt, 'content': result, 'sourceSha256': source_sha,
            'sha256': actual_sha, 'size': len(result), 'reviewIssues': list(dict.fromkeys(review_issues))}


def convert_pdf_office(content: bytes, *, output_format: str = 'pptx') -> dict[str, Any]:
    """固定源非 OCR PDF→Office；后置回执故障不丢实际已生成文件。"""
    if not isinstance(content, bytes) or not content or len(content) > 24 * 1024 * 1024 or output_format not in {'pptx', 'docx', 'xlsx'}:
        raise ValueError('pdf_conversion_request_invalid')
    source_sha = hashlib.sha256(content).hexdigest()
    with tempfile.TemporaryDirectory(prefix='convert-pdf-office-') as temporary:
        root = Path(temporary)
        source, output = root / 'input.pdf', root / f'output.{output_format}'
        source.write_bytes(content)
        issues = []
        try:
            receipt = _invoke({'kind': 'convertOffice', 'input': str(source), 'output': str(output),
                'format': output_format, 'sourceSha256': source_sha}, root)
        except Exception:
            if not output.is_file():
                raise
            receipt = {}
            issues.append('Office 文件已生成，但转换引擎回执读取失败；实际产物已保留，请人工核对。')
            logger.warning('pdf_conversion_receipt_failed_actual_output_retained')
        result = output.read_bytes()
        if not result:
            raise ValueError('pdf_conversion_output_unavailable')
        actual_sha = hashlib.sha256(result).hexdigest()
        trusted = (receipt.get('sourceSha256') == source_sha and receipt.get('sha256') == actual_sha
            and type(receipt.get('size')) is int and receipt['size'] == len(result) and receipt.get('format') == output_format)
        if not trusted:
            issues.append('转换回执文件身份未通过，已丢弃其转换元数据；下载绑定实际生成文件的 SHA 和大小。')
            receipt = {}
        validation = receipt.get('validation')
        if isinstance(validation, dict) and isinstance(validation.get('issues'), list):
            issues.extend(message for message in validation['issues'] if isinstance(message, str))
        issues.append('PDF 转换已生成；尚未通过完整内容与版式保真验收，请人工核对。')
        return {**receipt, 'content': result, 'sha256': actual_sha, 'size': len(result),
            'sourceSha256': source_sha, 'format': output_format, 'validation': {'ok': False, 'issues': list(dict.fromkeys(issues))}}
