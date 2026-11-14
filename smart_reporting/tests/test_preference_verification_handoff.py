"""隔离数据库验证两类Cookie交接；报告生成替身不代表Office版式验收。"""

from copy import deepcopy
from datetime import timedelta
from hashlib import sha256

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.management.api import SESSION_COOKIE, csrf_token
from smart_reporting.management.format_preferences import FormatPreferenceService
from smart_reporting.management.settings import ManagementSettings
from smart_reporting.preferences.models import FormatPreferences
from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE
from smart_reporting.report_editor.repository import (
    SqlAlchemyReportEditorRepository,
    report_editor_sessions_v1,
)
from smart_reporting.report_editor.service import ReportEditorGrantService, token_hash
from smart_reporting.tests.test_management_persistence import OLD_PASSWORD
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_report_preflight import bound_case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]
ORIGIN = 'http://127.0.0.1'
ROOT = '/management/api/v1/configuration/preferences/report-verification'


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def case(auth_context, tmp_path, monkeypatch):
    from smart_reporting.management import preference_report_preflight as preflight
    from smart_reporting.management.preference_verification import (
        PreferenceVerificationHandoffService,
    )
    from smart_reporting.management.preference_verification_api import (
        create_preference_verification_router,
    )

    auth, repository, clock = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    admin = (await auth.login('admin', OLD_PASSWORD, '127.0.0.1')).raw_token
    bound, _, _, _, context, _, _ = await bound_case(tmp_path)
    preferences = FormatPreferenceService(auth, FormatPreferences.model_validate({'common': {'signer': '验收署名'}}))
    editor_repository = SqlAlchemyReportEditorRepository(repository.engine)
    await editor_repository.create_schema()
    grants = ReportEditorGrantService(editor_repository, secret='handoff-test-secret-' * 3)
    grant, _ = await grants.issue(context)
    raw_editor, _ = await grants.exchange(grant)
    bound.preferences, bound.grants = preferences, grants
    service = PreferenceVerificationHandoffService(preferences=preferences, bound=bound)
    generated = []

    async def generate(*args, **kwargs):
        generated.append(True)
        return {'status': 'incomplete', 'canApply': False, 'formats': {'md': {
            'status': 'incomplete', 'artifact': {'base64': 'dGVzdA==', 'size': 4,
                'filename': 'fixture.md', 'mediaType': 'text/markdown', 'sha256': sha256(b'test').hexdigest()}, 'pdf': None}}}

    monkeypatch.setattr(preflight, 'run_office_engine', generate)
    app = FastAPI()
    app.include_router(create_preference_verification_router(service,
        ManagementSettings(public_origin=ORIGIN, allow_local_http=True)))
    path = f'/reports/v1/editor/{context.report_id}/{context.revision}'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        client.cookies.set(SESSION_COOKIE, admin, path='/management')
        client.cookies.set(EDITOR_SESSION_COOKIE, raw_editor, path=path)
        yield service, client, {'expectedVersion': 1,
            'expectedHash': (await preferences.detail(admin))['draft']['contentHash']}, \
            {'origin': ORIGIN, 'x-csrf-token': csrf_token(admin)}, \
            path, admin, raw_editor, repository, grants, clock, generated


async def begin(case):
    _, client, draft, admin_headers, path, _, raw_editor, _, grants, _, _ = case
    created = await client.post(ROOT, json=draft, headers=admin_headers)
    assert created.status_code == 200, created.text
    assert case[6] not in created.request.headers.get('cookie', '')
    token = created.json()['handoffToken']
    attached = await client.post(path + '/api/preference-verification', json={'handoffToken': token},
        headers={'origin': ORIGIN, 'x-csrf-token': grants.csrf_token(raw_editor)})
    assert attached.status_code == 200, attached.text
    assert case[5] not in attached.request.headers.get('cookie', '')
    return token


async def test_cookie_scoped_handoff_generates_once_and_stores_no_raw_sessions(case):
    from smart_reporting.management.repository import preference_verification_handoffs

    service, client, draft, headers, _, admin, editor, repository, _, _, generated = case
    token = await begin(case)
    async with repository.engine.connect() as connection:
        row = dict((await connection.execute(select(preference_verification_handoffs))).mappings().one())
    assert admin not in str(row) and editor not in str(row) and token not in str(row)
    assert row['editor_session_hash'] == token_hash(editor)
    response = await client.post(ROOT + '/run', json={**draft, 'handoffToken': token}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['formats']['md']['artifact']['base64'] == 'dGVzdA=='
    assert response.json()['canApply'] is False
    assert admin not in response.text and editor not in response.text
    assert response.headers['cache-control'] == 'no-store'
    repeated = await client.post(ROOT + '/run', json={**draft, 'handoffToken': token}, headers=headers)
    assert repeated.status_code == 409 and len(generated) == 1


@pytest.mark.parametrize('fault', ['expired', 'draft', 'other_admin', 'editor_revoke'])
async def test_handoff_rechecks_current_authority_before_generating(case, fault):
    service, client, draft, headers, _, _, editor, repository, _, clock, generated = case
    token = await begin(case)
    if fault == 'expired':
        clock[0] += timedelta(minutes=6)
    elif fault == 'draft':
        document = deepcopy((await service.preferences.detail(case[5]))['draft']['document'])
        document['common']['signer'] = '并发修改'
        await service.preferences.save_draft(case[5], document, 1)
    elif fault == 'other_admin':
        other = (await service.preferences.auth.login('admin', OLD_PASSWORD, '127.0.0.2')).raw_token
        client.cookies.set(SESSION_COOKIE, other, path='/management')
        headers = {'origin': ORIGIN, 'x-csrf-token': csrf_token(other)}
    else:
        async with repository.engine.begin() as connection:
            await connection.execute(delete(report_editor_sessions_v1).where(
                report_editor_sessions_v1.c.session_hash == token_hash(editor)))
    response = await client.post(ROOT + '/run', json={**draft, 'handoffToken': token}, headers=headers)
    assert response.status_code in {401, 403, 409}, response.text
    assert 'dGVzdA==' not in response.text and not generated


async def test_editor_attach_rejects_restricted_session_and_replay(case):
    _, client, draft, headers, path, _, editor, _, grants, _, generated = case
    created = await client.post(ROOT, json=draft, headers=headers)
    token = created.json()['handoffToken']
    context = await case[0].bound.editor.context_for_session(await grants.lookup_session(editor))
    grant, _ = await grants.issue(context, capabilities={'download_original': True})
    limited, _ = await grants.exchange(grant)
    client.cookies.set(EDITOR_SESSION_COOKIE, limited, path=path)
    response = await client.post(path + '/api/preference-verification', json={'handoffToken': token},
        headers={'origin': ORIGIN, 'x-csrf-token': grants.csrf_token(limited)})
    assert response.status_code == 403 and not generated
    client.cookies.set(EDITOR_SESSION_COOKIE, editor, path=path)
    for expected in (200, 409):
        response = await client.post(path + '/api/preference-verification', json={'handoffToken': token},
            headers={'origin': ORIGIN, 'x-csrf-token': grants.csrf_token(editor)})
        assert response.status_code == expected, response.text


@pytest.mark.parametrize('fault', ['ttl', 'draft', 'material', 'admin_logout', 'editor_revoke'])
async def test_after_generation_preserves_authorized_artifact_but_never_leaks_after_revocation(case, monkeypatch, fault):
    from smart_reporting.management import preference_report_preflight as preflight

    service, client, draft, headers, _, admin, editor, repository, _, clock, generated = case
    token = await begin(case)
    generate = preflight.run_office_engine

    async def changed(*args, **kwargs):
        result = await generate(*args, **kwargs)
        if fault == 'ttl':
            clock[0] += timedelta(minutes=6)
        elif fault == 'draft':
            document = deepcopy((await service.preferences.detail(admin))['draft']['document'])
            document['common']['signer'] = '渲染后并发署名'
            await service.preferences.save_draft(admin, document, 1)
        elif fault == 'admin_logout':
            await service.auth.logout(admin)
        elif fault == 'material':
            context = await service.bound.editor.context_for_session(await service.bound.grants.lookup_session(editor))
            workspace = service.bound.editor.workspace_registry.get(context.scope['threadId'])
            source = workspace.root / context.markdown_path
            source.write_bytes(source.read_bytes() + b'\nchanged after render\n')
        else:
            async with repository.engine.begin() as connection:
                await connection.execute(delete(report_editor_sessions_v1).where(
                    report_editor_sessions_v1.c.session_hash == token_hash(editor)))
        return result

    monkeypatch.setattr(preflight, 'run_office_engine', changed)
    response = await client.post(ROOT + '/run', json={**draft, 'handoffToken': token}, headers=headers)
    assert generated
    if fault in {'ttl', 'draft', 'material'}:
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload['formats']['md']['artifact']['base64'] == 'dGVzdA=='
        assert payload['formats']['md']['artifact']['size'] == 4
        assert payload['formats']['md']['artifact']['sha256'] == sha256(b'test').hexdigest()
        assert payload['canApply'] is False
        if fault == 'draft':
            assert payload['status'] == 'failed' and payload['bindingValid'] is False
            assert 'management_version_conflict' in {issue['code'] for issue in payload['issues']}
        if fault == 'material':
            assert payload['status'] == 'failed' and payload['bindingValid'] is False
            assert payload['issues']
    else:
        assert response.status_code in {401, 403} and 'dGVzdA==' not in response.text
        if fault == 'editor_revoke':
            assert response.status_code == 403  # 报告撤权不得触发管理页面的401自动登出。


async def test_handoff_does_not_checkout_second_connection_while_holding_admin_lock(case):
    service, client, draft, headers, _, _, _, repository, grants, _, generated = case
    engine = create_async_engine(repository.engine.url, pool_size=1, max_overflow=0, pool_timeout=0.2)
    old_engine = repository.engine
    repository.engine = grants.repository.engine = engine
    try:
        token = await begin(case)
        response = await client.post(ROOT + '/run', json={**draft, 'handoffToken': token}, headers=headers)
        assert response.status_code == 200, response.text
        assert generated
    finally:
        repository.engine = grants.repository.engine = old_engine
        await engine.dispose()


async def test_handoff_rejects_csrf_session_injection_and_wrong_report_scope(case):
    _, client, draft, headers, path, _, editor, _, grants, _, generated = case
    assert (await client.post(ROOT, json=draft)).status_code == 403
    created = await client.post(ROOT, json=draft, headers=headers)
    token = created.json()['handoffToken']
    response = await client.post(path + '/api/preference-verification', json={'handoffToken': token},
        headers={'origin': 'https://foreign.invalid', 'x-csrf-token': grants.csrf_token(editor)})
    assert response.status_code == 403
    response = await client.post(ROOT + '/run', json={**draft, 'handoffToken': token,
        'editorSessionHash': token_hash(editor)}, headers=headers)
    assert response.status_code == 422 and not generated
    wrong = path.replace('/editor/', '/editor/foreign-')
    assert (await client.get(wrong + '/api/preference-verification')).status_code in {401, 403, 404}
