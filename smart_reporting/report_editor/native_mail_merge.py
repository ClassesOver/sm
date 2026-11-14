"""受控 Word 邮件合并 CSV 来源：只接受请求体字节，不接收任意路径。"""
from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import hmac
import io
import re
from typing import Any

from ..reporting.models import ReportingError

MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 2000
MAX_FIELDS = 100
MAX_CELL_CHARS = 10_000
_FIELD_RE = re.compile(r'^[^"\x00-\x1f\x7f]{1,128}$')


def parse_mail_merge_csv(content: bytes) -> dict[str, Any]:
    if not isinstance(content, bytes) or not content or len(content) > MAX_SOURCE_BYTES:
        raise ReportingError("native_mail_merge_source_invalid", "收件人 CSV 必须为 1 字节至 4 MiB。")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ReportingError("native_mail_merge_source_encoding", "收件人 CSV 必须使用 UTF-8 编码。") from error
    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as error:
        raise ReportingError("native_mail_merge_source_csv", "收件人 CSV 格式无效。") from error
    if not rows or not rows[0]:
        raise ReportingError("native_mail_merge_source_empty", "收件人 CSV 缺少表头。")
    headers = [str(value).strip() for value in rows[0]]
    if len(headers) > MAX_FIELDS or any(not _FIELD_RE.fullmatch(value) for value in headers):
        raise ReportingError("native_mail_merge_source_fields", "收件人 CSV 表头无效或超过 100 列。")
    if len(set(headers)) != len(headers):
        raise ReportingError("native_mail_merge_source_fields", "收件人 CSV 表头不能重复。")
    records: list[dict[str, str]] = []
    for row in rows[1:]:
        if not any(value.strip() for value in row):
            continue
        if len(records) >= MAX_RECORDS or len(row) != len(headers):
            raise ReportingError("native_mail_merge_source_rows", "收件人 CSV 行数或列数不符合要求。")
        values = [str(value) for value in row]
        if any(len(value) > MAX_CELL_CHARS for value in values):
            raise ReportingError("native_mail_merge_source_cell", "收件人 CSV 单元格超过 10000 字符。")
        if any(re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]', value) for value in values):
            raise ReportingError("native_mail_merge_source_cell_xml", "收件人 CSV 单元格包含 XML 无法表示的控制字符。")
        records.append(dict(zip(headers, values)))
    if not records:
        raise ReportingError("native_mail_merge_source_empty", "收件人 CSV 没有有效收件人记录。")
    return {"sourceSha256": hashlib.sha256(content).hexdigest(), "fields": headers, "records": records, "recordCount": len(records)}


def decode_mail_merge_csv(value: str) -> tuple[bytes, dict[str, Any]]:
    if not isinstance(value, str) or len(value) > (MAX_SOURCE_BYTES * 4 // 3) + 8:
        raise ReportingError("native_mail_merge_source_invalid", "收件人 CSV 编码无效或超过大小上限。")
    try:
        content = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ReportingError("native_mail_merge_source_invalid", "收件人 CSV 编码无效。") from error
    if base64.b64encode(content).decode("ascii") != value:
        raise ReportingError("native_mail_merge_source_invalid", "收件人 CSV 编码不是规范 Base64。")
    return content, parse_mail_merge_csv(content)


def normalize_mail_merge_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for operation in operations:
        if operation.get('kind') != 'mailMergeSingle':
            normalized.append(operation)
            continue
        source = operation.get('sourceBase64')
        expected = operation.get('sourceSha256')
        if not isinstance(source, str):
            raise ReportingError('native_mail_merge_source_invalid', '邮件合并来源身份无效，请重新选择收件人文件。')
        content, parsed = decode_mail_merge_csv(source)
        if not isinstance(expected, str) or not hmac.compare_digest(parsed['sourceSha256'], expected):
            raise ReportingError('native_mail_merge_source_changed', '收件人文件身份已变化，请重新选择来源。')
        normalized.append({'kind': 'mailMergeSingle', 'documentSha256': operation.get('documentSha256'), 'sourceSha256': expected,
                           'fields': parsed['fields'], 'records': parsed['records']})
    return normalized


async def verify_mail_merge_sources(workspace: Any, key: str, operations: list[dict[str, Any]]) -> None:
    """渲染前从授权工作区独立回读；客户端不能提供路径或替代已登记字节。"""
    for operation in operations:
        if operation.get('kind') != 'mailMergeSingle':
            continue
        expected = operation.get('sourceSha256')
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ReportingError('native_mail_merge_source_invalid', '邮件合并来源身份无效。')
        try:
            stored, _ = await workspace.afile_bytes(key, f'native/mailmerge/{expected}.csv')
        except Exception as error:
            raise ReportingError('native_mail_merge_source_unavailable', '已登记的收件人文件无法读取，请重新上传。') from error
        supplied, _ = decode_mail_merge_csv(operation.get('sourceBase64'))
        if not hmac.compare_digest(hashlib.sha256(stored).hexdigest(), expected) or stored != supplied:
            raise ReportingError('native_mail_merge_source_changed', '收件人文件与授权工作区登记身份不一致。')
