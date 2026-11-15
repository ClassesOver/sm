"""Register a named independent native file in the source workspace."""
from ..office.repository import OfficeError
from ..reporting.models import ReportingError
from .native_import import NativeImportService


async def register_native_file(editor, context, *, content, creation_id, filename, session, generated=False, expected_format=None):
    authorize_created = None
    if session is not None and (session.capabilities or {}).get('office'):
        documents = getattr(getattr(editor, 'office_authorize', None), '__self__', None)
        if documents is None:
            raise ReportingError('native_permission_denied', 'Office 文件权限服务不可用。')

        async def authorize_created(created):
            try:
                return {'office': await documents.register_derived(session, created, name=filename)}
            except OfficeError as error:
                raise ReportingError('native_permission_denied', '无法将新文件登记到当前工作区。') from error

    result = await NativeImportService(editor.workspace, editor.repository, editor.grants).import_file(
        scope=context.scope, content=content, request_id=creation_id, filename=filename, display_name=filename,
        authorize_created=authorize_created,
        generation_key=creation_id if generated else None,
        expected_format=expected_format,
    )
    result['filename'] = filename
    result['editor']['openUrl'] = result['editor']['url']
    return result
