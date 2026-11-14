"""隔离PostgreSQL验证双会话与草稿CAS；渲染替身不代表正式Office验收。"""

import base64
import hashlib

import pytest
from sqlalchemy import delete

from smart_reporting.management.format_preferences import FormatPreferenceService
from smart_reporting.preferences.models import FormatPreferences
from smart_reporting.report_editor.repository import (
    SqlAlchemyReportEditorRepository,
    report_editor_sessions_v1,
)
from smart_reporting.report_editor.service import ReportEditorGrantService, token_hash
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_report_preflight import bound_case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('change', ['none', 'draft', 'admin_logout', 'editor_revoke'])
async def test_bound_preflight_rechecks_persisted_sessions_and_current_draft(
    auth_context, tmp_path, monkeypatch, change,
):
    from smart_reporting.management import preference_report_preflight as module

    auth, repository, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    admin = (await auth.login('admin', OLD_PASSWORD, '127.0.0.1')).raw_token
    service, args, _, _, context, root, _ = await bound_case(tmp_path)
    preferences = FormatPreferenceService(auth, FormatPreferences.model_validate({
        'common': {'signer': '隔离认证测试署名'}}))
    draft = (await preferences.detail(admin))['draft']
    editor_repository = SqlAlchemyReportEditorRepository(repository.engine)
    await editor_repository.create_schema()
    grants = ReportEditorGrantService(editor_repository, secret='integration-fixture-' * 3)
    grant, _ = await grants.issue(context)
    editor, _ = await grants.exchange(grant)
    service.preferences, service.grants = preferences, grants
    args.update(admin_session=admin, editor_session=editor,
        expected_draft_version=draft['version'], expected_draft_hash=draft['contentHash'])
    content = b'fixture-generated-output-not-a-production-document'

    async def generated(function, saved, materials, **kwargs):
        assert saved == draft and materials.workspace != root
        assert not service.editor._source_lifecycle_locks
        if change == 'draft':
            document = draft['document']
            document['common']['signer'] = '并发保存的署名'
            await preferences.save_draft(admin, document, draft['version'])
        elif change == 'admin_logout':
            await auth.logout(admin)
        elif change == 'editor_revoke':
            async with repository.engine.begin() as connection:
                await connection.execute(delete(report_editor_sessions_v1).where(
                    report_editor_sessions_v1.c.session_hash == token_hash(editor)))
        return {'status': 'incomplete', 'canApply': False, 'formats': {'md': {'artifact': {
            'base64': base64.b64encode(content).decode(), 'size': len(content),
            'sha256': hashlib.sha256(content).hexdigest()}}}}

    monkeypatch.setattr(module, 'run_office_engine', generated)
    result = await service.run(**args)
    artifact = result['formats']['md']['artifact']
    assert base64.b64decode(artifact['base64'], validate=True) == content
    assert artifact['sha256'] == hashlib.sha256(content).hexdigest()
    assert result['binding']['valid'] is (change == 'none')
    assert result['canApply'] is False
    assert result['status'] == ('incomplete' if change == 'none' else 'failed')
    if change in {'admin_logout', 'editor_revoke'}:
        assert result['binding']['artifactAccessAuthorized'] is False
    if change == 'none':
        assert result['binding']['artifactAccessAuthorized'] is True
    if change != 'none':
        expected = {'draft': 'management_version_conflict',
            'admin_logout': 'management_session_invalid',
            'editor_revoke': 'report_editor_session_invalid'}[change]
        assert expected in {issue['code'] for issue in result['issues']}
    assert admin not in str(result) and editor not in str(result) and str(root) not in str(result)
    async with repository.engine.begin() as connection:
        await connection.execute(delete(report_editor_sessions_v1).where(
            report_editor_sessions_v1.c.session_hash == token_hash(editor)))
