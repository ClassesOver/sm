"""Copy the verified presentation and apply a frozen draft to the copy."""
import re

from ..reporting.delivery.office_engine import run_office_engine
from ..reporting.models import ReportingError
from .native_file_actions import register_native_file
from .native_models import native_digest
from .native_office import patch_office


async def save_slides_as(editor, context, *, expected_sha256, request_id, filename, operations, session):
    editor.require_enabled('pptx')
    if context.format != 'pptx':
        raise ReportingError('native_permission_denied', '此命令只适用于演示文稿。')
    if expected_sha256 != context.source_file.sha256:
        raise ReportingError('native_source_changed', '演示文稿来源已变化，请重新打开后操作。')
    filename = filename.strip()
    if (len(filename) > 160 or not filename[:-5].strip() or filename.startswith('.')
            or not filename.lower().endswith('.pptx') or re.search(r'[\\/:*?"<>|\x00-\x1f\x7f]', filename)):
        raise ReportingError('native_slides_filename_invalid', '请输入有效的演示文稿文件名（.pptx），不能包含路径。')
    source = await editor.read_file(context)
    try:
        content = await run_office_engine(patch_office, 'pptx', source, operations) if operations else source
        creation_id = native_digest({
            'action': 'slides-save-as', 'scope': context.scope.model_dump(), 'documentId': context.document_id,
            'revision': context.revision, 'sourceSha256': expected_sha256, 'requestId': request_id,
            'filename': filename, 'operations': operations,
        })
    except (TypeError, ValueError, OverflowError):
        raise ReportingError('native_operations_invalid', '无法将当前演示文稿草稿写入副本。') from None
    return await register_native_file(
        editor, context, content=content, creation_id=creation_id, filename=filename, session=session, generated=True,
    )
