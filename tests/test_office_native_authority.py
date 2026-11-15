from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.office import native_access
from smart_reporting.office.documents import OfficeDocuments
from smart_reporting.office.repository import Identity, OfficeRepository
from smart_reporting.reporting.models import ReportingError


@pytest.mark.asyncio
@pytest.mark.parametrize('revoke', ['logout', 'membership', 'disable'])
async def test_saved_office_links_keep_authority_and_revoke(tmp_path, revoke):
    pytest.importorskip('fcntl', reason='Native editor runtime currently requires Linux file locks')
    from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
    from smart_reporting.report_editor.native_models import NativeArtifacts, NativeValidation
    from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication
    publication, context, _ = await create_publication(tmp_path)
    engine = create_async_engine('sqlite+aiosqlite://')
    office = OfficeRepository(engine)
    await office.create_schema()
    admin = Identity('db', 'company', 'admin')
    await office.bootstrap(admin, 'Admin')
    await office.provision(admin, 'user', 'User')
    space = await office.create_space(admin, 'Team', 'admin')
    await office.set_member(admin, space['id'], 'user', 'editor')
    raw = await office.create_session(Identity('db', 'company', 'user'))
    actor = await office.authenticate(raw)
    entry = await office.register_file(actor, space['id'], None, 'File.docx', 'docx',
                                      context.document_id, 1, context.scope.model_dump(by_alias=True))
    authority = dict(database=actor.database, company=actor.company, user=actor.user,
                     version=actor.session_version, session=actor.session_reference, file=entry['id'])
    documents = OfficeDocuments(office, None, None, None)
    original = SimpleNamespace(report_id=context.document_id, capabilities={'office': authority})
    native_access.bind(original, documents.authorize)
    try:
        result = await publication._publish_artifacts(
            context, NativeArtifacts(word=context.source_file),
            NativeValidation(ok=False), True,
            bind_native_workspace(publication.workspace, context.scope),
        )
        assert result['validation']['ok'] is False
        url = result['artifacts']['word']['downloadUrl']
        assert '/native/download/' in url
        _, download = await publication.editor_grants.exchange(unquote(url.split('/')[-2]))
        _, opened = await publication.editor_grants.exchange(unquote(result['editor']['openUrl'].split('/')[-1]))
        assert download.capabilities['office'] == authority
        assert opened.capabilities['office'] == authority
        editor = NativeEditorService(publication.workspace, None, publication.editor_grants)
        editor.office_authorize = documents.authorize
        assert (await editor.download(download, 'word'))[0]
        if revoke == 'logout':
            await office.logout(raw)
        elif revoke == 'membership':
            await office.set_member(admin, space['id'], 'user', None)
        else:
            await office.update_user(admin, 'user', enabled=False)
        with pytest.raises(ReportingError, match='Office'):
            await editor.download(download, 'word')
        with pytest.raises(ReportingError):
            await documents.authorize(opened)
    finally:
        native_access.bind(SimpleNamespace(capabilities={}), None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_office_task_authority_rechecks_read_write_and_revocation():
    engine = create_async_engine('sqlite+aiosqlite://')
    office = OfficeRepository(engine)
    await office.create_schema()
    admin = Identity('db', 'company', 'admin')
    await office.bootstrap(admin, 'Admin')
    await office.provision(admin, 'reader', 'Reader')
    space = await office.create_space(admin, 'Team', 'admin')
    entry = await office.register_file(admin, space['id'], None, 'File.docx', 'docx', 'doc', 1,
                                      {'database': 'db', 'companyId': 'company'})
    await office.set_member(admin, space['id'], 'reader', 'viewer')
    raw = await office.create_session(Identity('db', 'company', 'reader'))
    actor = await office.authenticate(raw)
    session = SimpleNamespace(report_id='doc', capabilities={'office': dict(
        database=actor.database, company=actor.company, user=actor.user,
        version=actor.session_version, session=actor.session_reference, file=entry['id'])})
    documents = OfficeDocuments(office, None, None, None)
    native_access.bind(session, documents.authorize)
    try:
        with pytest.raises(ReportingError):
            await documents.authorize(SimpleNamespace(report_id='doc', capabilities={}))
        await documents.authorize(SimpleNamespace(report_id='non-office-doc', capabilities={}))
        await native_access.check('doc')
        with pytest.raises(ReportingError):
            await native_access.check('doc', write=True)
        with pytest.raises(ReportingError):
            await native_access.check('another-doc')
        derived = native_access.capabilities('derived-doc')['office']
        assert derived['file'] == entry['id'] and derived['derivedDocument'] == 'derived-doc'
        await office.set_member(admin, space['id'], 'reader', 'editor')
        await native_access.check('doc', write=True)
        await office.update_space(admin, space['id'], archived=True)
        await native_access.check('doc')
        with pytest.raises(ReportingError, match='Office'):
            await native_access.check('doc', write=True)
        await office.update_space(admin, space['id'], archived=False)
        await native_access.check('doc', write=True)
        await office.logout(raw)
        with pytest.raises(ReportingError):
            await native_access.check('doc')
    finally:
        native_access.bind(SimpleNamespace(capabilities={}), None)
        await engine.dispose()


def test_shared_xlsx_comments_use_the_current_member_as_author():
    pytest.importorskip('fcntl', reason='Native editor runtime currently requires Linux file locks')
    from smart_reporting.report_editor.native_models import NativeScope
    from smart_reporting.report_editor.native_xlsx_threads import xlsx_thread_actor

    scope = NativeScope(database="db", companyId="company", userId="alice", threadId="office:team")
    original_actor = xlsx_thread_actor(scope)
    session = SimpleNamespace(capabilities={"office": {"user": "bob"}})
    native_access.bind(session, None)
    try:
        shared_actor = xlsx_thread_actor(scope)
    finally:
        native_access.bind(SimpleNamespace(capabilities={}), None)

    assert original_actor["author"] == "alice"
    assert shared_actor["author"] == "bob"
    assert shared_actor["personId"] != original_actor["personId"]


@pytest.mark.asyncio
async def test_native_file_read_rechecks_revocation_after_io(monkeypatch):
    pytest.importorskip("fcntl")
    from smart_reporting.report_editor import native

    document = SimpleNamespace(
        document_id="doc", scope=None, format="docx",
        source_file=SimpleNamespace(size=4, sha256="hash", path="original.docx"),
    )
    editor = native.NativeEditorService(None, None, None)
    revoked = False

    async def authorize(_session, *, write=False):
        if revoked:
            raise ReportingError("native_permission_denied", "Office 权限已撤销。")

    async def read(*_args, **_kwargs):
        nonlocal revoked
        revoked = True
        return b"file"

    monkeypatch.setattr(native, "bind_native_workspace", lambda *_: "workspace")
    monkeypatch.setattr(native, "read_verified_file", read)
    native_access.bind(SimpleNamespace(report_id="doc", capabilities={"office": {"file": "file"}}), authorize)
    try:
        with pytest.raises(ReportingError, match="Office 权限已撤销"):
            await editor.read_file(document)
    finally:
        native_access.bind(SimpleNamespace(capabilities={}), None)


@pytest.mark.asyncio
async def test_shared_document_read_jobs_are_isolated_by_office_session():
    from unittest.mock import AsyncMock

    from smart_reporting.report_editor.native_pdf_ai_tasks import NativePDFReadService

    context = SimpleNamespace(digest=lambda: "same-document")
    service = NativePDFReadService(None, planner=None)
    service._context = AsyncMock(return_value=context)

    def session(user, reference):
        return SimpleNamespace(capabilities={"office": {
            "database": "db", "company": "1", "user": user, "version": 1, "session": reference,
        }})

    owner = session("10", "owner-session")
    another_login = session("10", "another-session")
    member = session("20", "member-session")
    receipt = await service.cancel_request(owner, "request-id")
    for actor in (another_login, member):
        for read in (service.status, service.event_stream):
            with pytest.raises(ReportingError) as missing:
                await read(actor, receipt["taskId"])
            assert missing.value.code == "native_ai_job_missing"
        other = await service.cancel_request(actor, "request-id")
        assert other["taskId"] != receipt["taskId"]
    assert await service.status(owner, receipt["taskId"]) == receipt
