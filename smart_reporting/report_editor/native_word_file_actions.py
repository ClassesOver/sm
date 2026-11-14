"""Source-bound New and Save As create independent files; they never overwrite a revision."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

from ..reporting.delivery.office_engine import last_json_line, run_bridge, run_office_engine
from ..reporting.models import ReportingError
from .native_import import NativeImportService
from .native_models import native_digest


def render_blank_word() -> bytes:
    """Use the fixed source builder including its ordinary empty paragraph and styles."""
    try:
        with tempfile.TemporaryDirectory(prefix='native-new-word-') as temporary:
            root=Path(temporary);output=root/'new.docx';request=root/'request.json'
            request.write_text(json.dumps({'output':str(output)}),encoding='utf-8')
            completed=run_bridge('doc','new-docx',request)
            if completed.returncode:
                raise ValueError('new_word_bridge_failed')
            receipt=last_json_line(completed.stdout)
            if not output.is_file() or not 1<=output.stat().st_size<=24*1024*1024:
                raise ValueError('new_word_output_invalid')
            content=output.read_bytes()
            if (not isinstance(receipt,dict) or receipt.get('ok') is not True
                or receipt.get('size')!=len(content) or receipt.get('sha256')!=hashlib.sha256(content).hexdigest()):
                raise ValueError('new_word_receipt_invalid')
            return content
    except (OSError,ValueError,TypeError,subprocess.SubprocessError):
        raise ReportingError('native_engine_unavailable','新建 Word 文档暂不可用，请稍后重试。') from None


def word_filename(filename: str) -> str:
    """Validate the persisted display basename; paths are never accepted."""
    value=filename.strip()
    if (not value or len(value)>160 or re.search(r'[\\/:*?"<>|\x00-\x1f\x7f]',value)
        or value.startswith('.') or value.endswith('.') or not value.lower().endswith('.docx')
        or not value[:-5].strip()):
        raise ReportingError('native_word_filename_invalid','请输入有效的 Word 文件名（.docx），不能包含路径。')
    return value


async def create_word_file(editor, context, *, action: str, expected_sha256: str, request_id: str,
                           filename: str='document.docx'):
    editor.require_enabled('docx')
    if context.format!='docx':
        raise ReportingError('native_permission_denied','此命令只适用于 Word 文档。')
    if expected_sha256!=context.source_file.sha256:
        raise ReportingError('native_source_changed','Word 来源已变化，请重新打开后操作。')
    filename=word_filename(filename)
    # Read even for New: the authorized source must still have its verified identity.
    source=await editor.read_file(context)
    if action=='new':content=await run_office_engine(render_blank_word)
    elif action=='save-as':content=source
    else:raise ReportingError('native_word_file_action_invalid','Word 文件操作无效。')
    creation_id=native_digest({'action':action,'scope':context.scope.model_dump(),'documentId':context.document_id,
        'revision':context.revision,'sourceSha256':expected_sha256,'requestId':request_id,'filename':filename})
    result=await NativeImportService(editor.workspace,editor.repository,editor.grants).import_file(
        scope=context.scope,content=content,request_id=creation_id,filename=filename,display_name=filename)
    result['filename']=filename
    result['editor']['openUrl']=result['editor']['url']
    return result
