"""固定版本上游 PDF 引擎的字节桥接，不覆盖来源文件。"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

from loguru import logger
from PIL import Image

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


def _verify_pdf_read_png(result: dict[str, Any]) -> None:
    encoded = result.get('image')
    if not isinstance(encoded, str) or not 0 < len(encoded) <= 6_000_000:
        raise ValueError('invalid_image')
    png = base64.b64decode(encoded, validate=True)
    if result.get('sha256') != hashlib.sha256(png).hexdigest():
        raise ValueError('invalid_sha256')
    with Image.open(BytesIO(png)) as image:
        if (
            image.format != 'PNG'
            or any(type(result.get(key)) is not int or result[key] <= 0 for key in ('width', 'height'))
            or image.size != (result['width'], result['height'])
        ):
            raise ValueError('invalid_dimensions')
        image.verify()


def read_pdf_image_pixels(content: bytes, target: dict[str, str]) -> dict[str, Any]:
    """只读原图自身像素；target 不包含路径，来源字节由现有授权工作区提供。"""
    with tempfile.TemporaryDirectory(prefix='read-pdf-image-') as temporary:
        root = Path(temporary)
        source = root / 'input.pdf'
        source.write_bytes(content)
        result = _invoke({'kind': 'imagePixels', 'input': str(source), 'target': target}, root)
        if result.get('sourceSha256') != hashlib.sha256(content).hexdigest():
            raise ValueError('pdf_image_source_identity_invalid')
        if any(result.get(key) != target.get(key) for key in ('pageId', 'imageId', 'expectedImageSha256')):
            raise ValueError('pdf_image_target_identity_invalid')
        try:
            _verify_pdf_read_png(result)
        except (ValueError, TypeError, OSError, binascii.Error) as error:
            raise ValueError('pdf_image_pixels_identity_invalid') from error
        return result


def read_pdf_image_background(content: bytes, target: dict[str, Any]) -> dict[str, Any]:
    """临时移除已核验目标后读取区域背景，不修改工作区来源或生成修订。"""
    clip, width = target.get('clip'), target.get('pxWidth')
    keys = ('x', 'y', 'width', 'height')
    if (
        not isinstance(clip, dict) or set(clip) != set(keys)
        or any(type(clip[key]) not in (int, float) or not math.isfinite(clip[key]) for key in keys)
        or clip['x'] < 0 or clip['y'] < 0 or clip['width'] <= 0 or clip['height'] <= 0
        or type(width) is not int or not 1 <= width <= 2400
    ):
        raise ValueError('pdf_image_background_identity_invalid')
    raster_height = clip['height'] * width / clip['width']
    if not math.isfinite(raster_height):
        raise ValueError('pdf_image_background_identity_invalid')
    height = max(1, math.floor(raster_height + 0.5))
    if height > 2400:
        raise ValueError('pdf_image_background_identity_invalid')
    with tempfile.TemporaryDirectory(prefix='read-pdf-image-background-') as temporary:
        root = Path(temporary)
        (root / 'input.pdf').write_bytes(content)
        result = _invoke({'kind': 'imageBackground', 'input': str(root / 'input.pdf'), 'target': target}, root)
        if result.get('sourceSha256') != hashlib.sha256(content).hexdigest():
            raise ValueError('pdf_image_source_identity_invalid')
        if any(result.get(key) != target.get(key) for key in ('pageId', 'imageId', 'expectedImageSha256')):
            raise ValueError('pdf_image_target_identity_invalid')
        try:
            actual_clip = result.get('clip')
            if (
                not isinstance(actual_clip, dict) or set(actual_clip) != set(keys)
                or any(type(actual_clip[key]) not in (int, float) or not math.isfinite(actual_clip[key])
                       or abs(actual_clip[key] - clip[key]) > 1e-6 for key in keys)
                or type(result.get('width')) is not int or result['width'] != width
                or type(result.get('height')) is not int or result['height'] != height
            ):
                raise ValueError('invalid_background_geometry')
            _verify_pdf_read_png(result)
        except (ValueError, TypeError, OSError, binascii.Error) as error:
            raise ValueError('pdf_image_background_identity_invalid') from error
        return result


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


def merge_pdf_files(content: bytes, others: list[bytes]) -> dict[str, Any]:
    """复用固定源mergePdfBytes；回执/后置复核失败仍保留实际合并文件。"""
    with tempfile.TemporaryDirectory(prefix='merge-pdf-') as temporary:
        root = Path(temporary)
        source, output = root / 'input.pdf', root / 'output.pdf'
        source.write_bytes(content)
        paths = []
        for index, external in enumerate(others):
            path = root / f'external-{index}.pdf'
            path.write_bytes(external)
            paths.append(str(path))
        review_issues = []
        try:
            receipt = _invoke({'kind': 'mergePdf', 'input': str(source), 'output': str(output), 'others': paths}, root)
        except Exception:
            if not output.is_file():
                raise
            receipt = {}
            review_issues.append('合并引擎回执异常，实际生成文件保留，请下载核对。')
            logger.warning('pdf_merge_receipt_failed_actual_output_retained')
        result = output.read_bytes()
        if not result:
            raise ValueError('pdf_merge_output_unavailable')
        if not isinstance(receipt, dict):
            receipt = {}
        actual_sha = hashlib.sha256(result).hexdigest()
        source_sha = hashlib.sha256(content).hexdigest()
        external_shas = [hashlib.sha256(value).hexdigest() for value in others]
        if (receipt.get('sourceSha256') != source_sha or receipt.get('externalSha256s') != external_shas
            or receipt.get('sha256') != actual_sha or type(receipt.get('size')) is not int
            or receipt['size'] != len(result)):
            receipt = {}
            review_issues.append('合并引擎回执身份不一致，已丢弃不可信元数据；实际文件下载保留。')
        details = receipt.get('reviewIssues', [])
        if not isinstance(details, list) or any(not isinstance(value, str) or len(value) > 2000 for value in details):
            details = []
            review_issues.append('合并复核回执格式无效，实际文件已保留；请下载后人工核对。')
        return {**receipt, 'content': result, 'sourceSha256': source_sha,
            'externalSha256s': external_shas, 'sha256': actual_sha, 'size': len(result),
            'reviewIssues': [*details, *review_issues]}


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


def shrink_pdf(content: bytes) -> dict[str, Any]:
    """Return an independently identified compressed copy; never modify source bytes."""
    if not isinstance(content, bytes) or not content or len(content) > 24 * 1024 * 1024:
        raise ValueError('pdf_shrink_request_invalid')
    source_sha = hashlib.sha256(content).hexdigest()
    with tempfile.TemporaryDirectory(prefix='shrink-pdf-') as temporary:
        root=Path(temporary);source,output=root/'input.pdf',root/'output.pdf';source.write_bytes(content);issues=[]
        try:receipt=_invoke({'kind':'shrinkPdf','input':str(source),'output':str(output)},root)
        except Exception:
            if not output.is_file():raise
            receipt={};issues.append('PDF 已压缩，但引擎回执读取失败；实际副本身份由服务端重新核验。');logger.warning('pdf_shrink_receipt_failed_actual_output_retained')
        result=output.read_bytes()
        if not result:raise ValueError('pdf_shrink_output_unavailable')
        actual_sha=hashlib.sha256(result).hexdigest()
        if receipt.get('sourceSha256')!=source_sha or receipt.get('sha256')!=actual_sha or type(receipt.get('size')) is not int or receipt['size']!=len(result):
            receipt={};issues.append('压缩引擎回执身份不一致，已丢弃回执元数据；下载绑定实际副本。')
        return {**receipt,'content':result,'sourceSha256':source_sha,'sha256':actual_sha,'size':len(result),'reviewIssues':issues}


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
