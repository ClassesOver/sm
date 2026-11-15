from __future__ import annotations

from loguru import logger

from .repository import Identity, OfficeError


class OfficeDocuments:
    def __init__(self, office, importer, native_repository, grants, *, editor=None):
        self.office = office
        self.importer = importer
        self.native_repository = native_repository
        self.grants = grants
        self.editor = editor
        self.search = None

    def _index(self, actor, entry):
        if self.search is not None:
            try:
                self.search.schedule(actor, entry)
            except Exception as error:
                logger.warning('Office index scheduling failed: {}', type(error).__name__)

    async def import_file(self, actor, space, folder, name, content, request_id, *, copy_source=None):
        from ..report_editor.native_models import NativeScope

        await self.office.space_access(actor, space, write=True)
        scope = NativeScope(database=actor.database, companyId=actor.company,
                            userId=actor.user, threadId=f"office:{space}")
        result = await self.importer.import_file(scope, content, request_id=request_id, filename=name)
        entry = await self.office.register_file(
            actor, space, folder, name, result["format"], result["documentId"],
            result["revision"], scope.model_dump(by_alias=True),
            **({"copy_source": copy_source} if copy_source else {}),
        )
        self._index(actor, entry)
        return await self.open(actor, entry["id"])

    async def duplicate_file(self, actor, file_id, expected_version, request_id):
        entry = await self.office.file(actor, file_id, write=True)
        if entry['version'] != expected_version:
            raise OfficeError('office_version_conflict', '源文件已变化，请刷新后重试。', 409)
        current, content = await self.contents(actor, file_id)
        if current['version'] != expected_version:
            raise OfficeError('office_version_conflict', '源文件已变化，请刷新后重试。', 409)
        return await self.import_file(actor, entry['space'], entry['folder'], entry['name'], content,
                                      f'copy:{file_id}:{request_id}', copy_source=(file_id, expected_version))

    async def archive_report(self, actor, title, format, scope, result, *, space=None):
        """Register a report in the selected space or the verified publisher's personal library."""
        from ..report_editor.native_models import NativeScope

        native_scope = NativeScope.model_validate({
            key: scope[key] for key in ("database", "companyId", "userId", "threadId")
        })
        if (native_scope.database, native_scope.company_id, native_scope.user_id) != (
            actor.database, actor.company, actor.user
        ):
            raise OfficeError("office_file_scope_invalid", "报告与当前 Office 用户身份不一致。")
        if space is None:
            try:
                spaces = await self.office.spaces(actor)
            except OfficeError as error:
                if error.code == "office_user_disabled":
                    return None
                raise
            personal = next((item for item in spaces if item["personal_user"] == actor.user), None)
            if personal is None:
                raise OfficeError("office_space_missing", "当前 Office 用户的个人空间不可用。")
            space = personal["id"]
        else:
            await self.office.space_access(actor, space, write=True)
        stored = await self.native_repository.get_revision(
            result["documentId"], result["revision"], scope=native_scope,
        )
        if stored is None or stored.context is None or stored.context.format != format:
            raise OfficeError("office_document_missing", "报告的原生修订不可用。", 404)
        name = str(title or "报告").replace("/", "／").replace("\\", "＼").strip()[:180] or "报告"
        entry = await self.office.register_file(
            actor, space, None, f"{name}.{format}", format,
            result["documentId"], result["revision"], native_scope.model_dump(by_alias=True),
            follow_existing=True,
        )
        self._index(actor, entry)
        return await self.open(actor, entry["id"])

    async def open(self, actor, file_id, revision=None):
        from ..report_editor.native import NativeEditorService
        from ..report_editor.native_models import NativeScope

        entry = await self.office.file(actor, file_id)
        number = entry['revision'] if revision is None else revision
        if not isinstance(number, int) or not 1 <= number <= entry['revision']:
            raise OfficeError('office_revision_missing', '修订不存在。', 404)
        stored = await self.native_repository.get_revision(
            entry["document"], number, scope=NativeScope.model_validate(entry["scope"]))
        if stored is None or stored.context is None:
            raise OfficeError("office_document_missing", "文档修订不可用。", 404)
        account = await self.office.me(actor)
        capabilities = NativeEditorService.capabilities(stored.context)
        capabilities["office"] = {
            "database": actor.database, "company": actor.company, "user": actor.user,
            "version": account["version"], "file": file_id,
            "session": actor.session_reference,
        }
        grant, expires = await self.grants.issue(stored.context, capabilities=capabilities)
        await self.office.touch(actor, file_id)
        return {"fileId": file_id, "documentId": entry["document"], "revision": number,
                "name": entry['name'], "format": entry['format'], "space": entry['space'],
                "editor": {"url": f"/reports/v1/native/open/{grant}", "expiresAt": expires.isoformat()}}

    async def contents(self, actor, file_id):
        from ..report_editor.native_models import NativeScope
        from ..report_editor.native import bind_native_workspace
        from ..report_editor._file_identity import read_verified_file

        if self.editor is None:
            raise OfficeError('office_documents_unavailable', '文件读取服务尚未配置。', 503)
        entry = await self.office.file(actor, file_id)
        stored = await self.native_repository.get_revision(entry['document'], entry['revision'],
            scope=NativeScope.model_validate(entry['scope']))
        if stored is None or stored.context is None:
            raise OfficeError('office_document_missing', '文档修订不可用。', 404)
        context = stored.context
        source = context.source_file
        if source.size > 24 * 1024 * 1024:
            raise OfficeError('office_file_too_large', '文件超过读取上限。', 413)
        key = bind_native_workspace(self.editor.workspace, context.scope)
        content = await read_verified_file(self.editor.workspace, {'threadId': key}, source.path,
            size=source.size, sha256=source.sha256, error_code='native_source_changed', format_name=context.format)
        await self.office.file(actor, file_id)
        return entry, content

    async def authorize(self, session, *, write=False):
        value = (session.capabilities or {}).get("office")
        if value is None:
            if await self.office.owns_document(session.report_id):
                from ..reporting.models import ReportingError
                raise ReportingError("native_permission_denied", "Office 文件需要工作区授权。")
            return
        try:
            actor = Identity(value["database"], value["company"], value["user"],
                             value["version"], value["session"])
            entry = await self.office.file(actor, value["file"], write=write)
            derived = (value.get('derivedDocument') == session.report_id
                       and (session.capabilities or {}).get('scope') == entry['scope'])
            if entry["document"] != session.report_id and not derived:
                raise OfficeError("office_document_mismatch", "文件授权身份不一致。")
        except (KeyError, TypeError, OfficeError) as error:
            from ..reporting.models import ReportingError
            raise ReportingError("native_permission_denied", "Office 文件权限已失效或不足。") from error

    async def register_derived(self, session, context):
        await self.authorize(session, write=True)
        value = dict(session.capabilities['office'])
        actor = Identity(value['database'], value['company'], value['user'], value['version'], value['session'])
        parent = await self.office.file(actor, value['file'], write=True)
        if context.scope.model_dump(by_alias=True) != parent['scope']:
            raise OfficeError('office_document_mismatch', '派生文件与来源空间身份不一致。')
        name = parent['name'].rsplit('.', 1)[0][:180] + f' - 副本.{context.format}'
        entry = await self.office.register_file(actor, parent['space'], parent['folder'], name,
            context.format, context.document_id, context.revision, context.scope.model_dump(by_alias=True))
        self._index(actor, entry)
        value['file'] = entry['id']
        value.pop('derivedDocument', None)
        return value

    async def saved(self, context, result):
        from .native_access import capabilities

        value = capabilities(context.document_id).get("office")
        if value is None or not result.get("revisionRegistered"):
            return
        actor = Identity(value["database"], value["company"], value["user"],
                         value["version"], value["session"])
        try:
            entry = await self.office.record_revision(actor, value["file"], context.document_id, result["revision"])
        except Exception:
            logger.exception("Office library revision synchronization failed")
            result["officeLibraryWarning"] = "文件已保存，文件库修订同步失败，请重新打开后核对。"
        else:
            self._index(actor, entry)
