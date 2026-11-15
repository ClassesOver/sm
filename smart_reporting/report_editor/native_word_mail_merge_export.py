"""会话内 Word 邮件合并下载。CSV 独立回读，输出不创建修订或持久化下载授权。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from ..reporting.delivery.office_engine import last_json_line, run_bridge, run_office_engine
from ..reporting.models import ReportingError
from .native import bind_native_workspace
from .native_mail_merge import decode_mail_merge_csv, verify_mail_merge_sources

MAX_SOURCE_BYTES = 24 * 1024 * 1024
MAX_EXPORT_BYTES = 64 * 1024 * 1024


def _invalid(message='邮件合并导出失败，请检查模板域、标签内容和输出设置。'):
    return ReportingError('native_mail_merge_export_invalid', message)


def render_word_mail_merge(content: bytes, operation: dict):
    """Run only with host-derived records; all paths stay inside the temporary directory."""
    if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_SOURCE_BYTES:
        raise _invalid('Word 来源无效或超过 24 MiB。')
    with tempfile.TemporaryDirectory(prefix='native-mail-merge-') as temporary:
        root = Path(temporary)
        source, output, request = root/'source.docx', root/'output.bin', root/'request.json'
        source.write_bytes(content)
        try:
            encoded = json.dumps({'input':str(source), 'output':str(output), 'operation':operation}, ensure_ascii=False, allow_nan=False)
            if len(encoded.encode()) > 12*1024*1024:
                raise _invalid('邮件合并参数超过大小限制。')
            request.write_text(encoded, encoding='utf-8')
            completed = run_bridge('doc', 'export-docx-mail-merge', request)
            if completed.returncode:
                if 'control_output_mode_unsupported' in completed.stderr:
                    raise _invalid('NEXT、SKIPIF 仅支持单一文档合并；分文件、标签及信封导出请使用 MERGEFIELD、IF 模板。')
                if 'label_content_unsupported' in completed.stderr:
                    raise _invalid('标签模板仅支持正文段落、标题和列表；表格、文本框或受控内容无法放入标签。')
                raise _invalid()
            receipt = last_json_line(completed.stdout)
            if not isinstance(receipt, dict) or receipt.get('ok') is not True or receipt.get('sourceSha256') != hashlib.sha256(content).hexdigest():
                raise _invalid('邮件合并来源回执身份不一致。')
            if not output.is_file() or not 1 <= output.stat().st_size <= MAX_EXPORT_BYTES:
                raise _invalid('邮件合并输出为空或超过 64 MiB。')
            raw = output.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            expected_format = 'docx' if operation.get('mode') == 'labels' else 'zip'
            files = receipt.get('files')
            if (receipt.get('format') != expected_format or type(receipt.get('size')) is not int or receipt['size'] != len(raw)
                or receipt.get('sha256') != digest or not isinstance(files, list) or not 1 <= len(files) <= 2000):
                raise _invalid('邮件合并输出回执身份不一致。')
            names = []
            for file in files:
                name = file.get('name') if isinstance(file, dict) else None
                if (not isinstance(name, str) or not name.endswith('.docx') or len(name) > 160 or name in {'.','..'}
                    or any(char in name for char in '/\\\x00\r\n') or type(file.get('size')) is not int or file['size'] <= 0):
                    raise _invalid('邮件合并文件名或大小无效。')
                names.append(name)
            if len(set(name.casefold() for name in names)) != len(names):
                raise _invalid('邮件合并文件名重复。')
            with ZipFile(BytesIO(raw)) as archive:
                if expected_format == 'zip':
                    if archive.namelist() != names or sum(item.file_size for item in archive.infolist()) > MAX_EXPORT_BYTES:
                        raise _invalid('邮件合并 ZIP 清单不一致。')
                    if any(archive.getinfo(file['name']).file_size != file['size'] for file in files):
                        raise _invalid('邮件合并 ZIP 文件大小不一致。')
                elif len(files) != 1 or '[Content_Types].xml' not in archive.namelist() or 'word/document.xml' not in archive.namelist():
                    raise _invalid('邮件合并 DOCX 不完整。')
        except ReportingError:
            raise
        except (ValueError, TypeError, KeyError, OSError, BadZipFile, subprocess.SubprocessError):
            raise _invalid() from None
        return {'content':raw, 'sha256':digest, 'size':len(raw), 'sourceSha256':receipt['sourceSha256'],
                'filename':'mail-merge-labels.docx' if expected_format=='docx' else 'mail-merge.zip',
                'mediaType':'application/vnd.openxmlformats-officedocument.wordprocessingml.document' if expected_format=='docx' else 'application/zip'}


async def export_word_mail_merge(editor, context, *, document_sha256: str, source_sha256: str,
                                 source_base64: str, mode: str, name_pattern: str, layout=None):
    editor.require_enabled('docx')
    if context.format != 'docx':
        raise ReportingError('native_format_invalid', '邮件合并仅支持 DOCX。')
    if document_sha256 != context.source_file.sha256:
        raise ReportingError('native_source_changed', 'Word 来源身份已变化，请重新打开修订。')
    content = await editor.read_file(context)
    if hashlib.sha256(content).hexdigest() != document_sha256:
        raise ReportingError('native_source_changed', 'Word 实际文件身份已变化。')
    key = bind_native_workspace(editor.workspace, context.scope)
    await verify_mail_merge_sources(editor.workspace, key, [{'kind':'mailMergeSingle','sourceSha256':source_sha256,'sourceBase64':source_base64}])
    _, parsed = decode_mail_merge_csv(source_base64)
    operation = {'kind':'mailMergeOutput','documentSha256':document_sha256,'sourceSha256':source_sha256,
                 'fields':parsed['fields'],'records':parsed['records'],'mode':mode,'namePattern':name_pattern}
    if layout is not None:
        operation['layout'] = layout
    return await run_office_engine(render_word_mail_merge, content, operation)
