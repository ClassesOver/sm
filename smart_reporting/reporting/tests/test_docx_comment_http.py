"""已有批注改字的真实FastAPI会话链；仅仓储使用现有内存fixture。"""

import hashlib
import json
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from lxml import etree

from smart_reporting.app import require_workspace_capability
from smart_reporting.report_editor.native import NativeEditorService
from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE, create_native_editor_router
from smart_reporting.report_editor.native_import import NativeImportService
from smart_reporting.report_editor.native_import_api import create_native_import_router
from smart_reporting.reporting.delivery import docx_native
from smart_reporting.reporting.tests.test_docx_comment_text_host import ENGINE, NS, operation, source
from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication
from smart_reporting.reporting.tests.test_native_ribbon_http_roundtrip import Repository
from smart_reporting.tests.test_reporting_request_identity import SECRET, _capability


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def http_env(tmp_path, monkeypatch):
    bridge = ENGINE / 'dist/edit-docx.mjs'
    assert bridge.is_file(), '先部署生产打包Word桥；本验收不自动build或降级为tsx'
    monkeypatch.setenv('AGENT_REPORTING_DOC_ENGINE_DIR', str(ENGINE))
    publication, _, downloads = await create_publication(tmp_path)
    publication.repository = Repository()
    editor = NativeEditorService(publication.workspace, publication.repository, publication.editor_grants, docx_enabled=True, publication=publication)
    importer = NativeImportService(publication.workspace, publication.repository, publication.editor_grants)
    app = FastAPI()
    app.state.agentos_context = SimpleNamespace(settings=SimpleNamespace(workspace_hmac_secret=SECRET))
    app.middleware('http')(require_workspace_capability)
    app.include_router(create_native_import_router(importer, enabled=True))
    app.include_router(create_native_editor_router(publication.editor_grants, editor=editor,
                                                  download_service=downloads, cookie_secure=False))
    calls = []
    actual_run_bridge = docx_native.run_bridge

    def traced_bridge(engine, script, request, **kwargs):
        result = actual_run_bridge(engine, script, request, **kwargs)
        calls.append({'kind': json.loads(request.read_text())['kind'],
                      'command': result.args[:2], 'returncode': result.returncode})
        assert result.args[:2] == ['node', str(bridge)]
        return result

    # 只记录真正执行的子进程命令，不替换引擎、handler、context_for_session或鉴权。
    monkeypatch.setattr(docx_native, 'run_bridge', traced_bridge)
    return SimpleNamespace(app=app, publication=publication, editor=editor, calls=calls,
                           bridge_sha256=hashlib.sha256(bridge.read_bytes()).hexdigest(), original=source())


async def import_and_open(client, env):
    uploaded = await client.post('/reports/v1/native/import',
                                headers={'X-Workspace-Thread': 'thread-1', 'X-Workspace-Capability': _capability()},
                                data={'requestId': 'comment-http-import'},
                                files={'file': ('comments.docx', env.original)})
    assert uploaded.status_code == 200, uploaded.text
    exchange = await client.get(uploaded.json()['editor']['url'])
    assert exchange.status_code == 303, exchange.text
    cookie = exchange.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie
    page = await client.get(exchange.headers['location'])
    assert page.status_code == 200, page.text
    assert 'text/html' in page.headers['content-type']
    base = page.url.path + '/api'
    context = await client.get(base + '/context')
    assert context.status_code == 200, context.text
    context = context.json()
    assert context['editingEnabled'] and context['context']['format'] == 'docx'
    assert context['context']['origin'] == 'upload'
    assert context['context']['scope'] == {'database': 'odoo', 'companyId': '3', 'userId': '7', 'threadId': 'thread-1'}
    assert (await client.get(base + '/file')).content == env.original
    return base, context, {'Origin': 'http://test', 'X-CSRF-Token': context['csrfToken']}


def assert_comments_only(original, saved, text):
    with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(saved)) as after:
        assert after.testzip() is None
        assert before.namelist() == after.namelist()
        changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
        assert changed == ['word/comments.xml']
        for name in after.namelist():
            if name.endswith(('.xml', '.rels')):
                etree.fromstring(after.read(name))
        assert ''.join(etree.fromstring(after.read('word/comments.xml')).xpath('.//w:t/text()', namespaces=NS)) == text


@pytest.mark.anyio
async def test_comment_http_authentication_preview_save_download_and_revision_reopen(http_env):
    env = http_env

    async def failed_validation(context, artifacts):
        raise RuntimeError('comment_http_validation_probe')

    env.publication.validator = failed_validation
    async with AsyncClient(transport=ASGITransport(app=env.app), base_url='http://test') as client:
        base, context, headers = await import_and_open(client, env)
        expected = context['context']['sourceFile']['sha256']
        assert expected == hashlib.sha256(env.original).hexdigest()
        inspect = await client.post(base + '/preview', headers=headers, json={'expectedSha256': expected, 'operations': []})
        assert inspect.status_code == 200, inspect.text
        original_model = inspect.json()['model']
        target = original_model['comments']['commentTargets'][0]
        assert original_model['comments']['commentReadOnlyReason'] is None and target['editableText']
        assert target['text'] == 'Original note'
        edit = operation(target, 'HTTP会话核实的批注 😀')
        preview = await client.post(base + '/preview', headers=headers, json={'expectedSha256': expected, 'operations': [edit]})
        assert preview.status_code == 200, preview.text
        assert preview.json()['sourceSha256'] == expected
        assert preview.json()['model']['comments']['commentTargets'][0]['text'] == edit['text']
        assert (await client.get(base + '/file')).content == env.original
        payload = {'requestId': 'comment-http-save', 'expectedSha256': expected, 'operations': [edit]}
        response = await client.post(base + '/save', headers=headers, json=payload)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['revisionRegistered'] and result['revision'] == 2 and result['parentRevision'] == 1
        assert result['validation']['ok'] is False
        assert {'code': 'native_validation_failed', 'message': '文件已保存，但内容或版式验收执行失败。'} in result['validation']['issues']
        artifact = result['artifacts']['word']
        # 下载签名是能力URL，实际下载router独立核验作用域与文件身份，不借用编辑cookie。
        async with AsyncClient(transport=ASGITransport(app=env.app), base_url='http://test') as downloader:
            downloaded = await downloader.get(artifact['downloadUrl'])
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.headers['x-content-type-options'] == 'nosniff'
        assert hashlib.sha256(downloaded.content).hexdigest() == artifact['sha256']
        assert_comments_only(env.original, downloaded.content, edit['text'])
        retry = await client.post(base + '/save', headers=headers, json=payload)
        assert retry.status_code == 200, retry.text
        assert retry.json()['revision'] == 2 and retry.json()['artifacts']['word']['sha256'] == artifact['sha256']
        assert env.publication.repository.completions == 1
        assert (await client.get(base + '/file')).content == env.original
        reopened = await client.get(result['editor']['openUrl'], follow_redirects=True)
        assert reopened.status_code == 200, reopened.text
        next_base = reopened.url.path + '/api'
        next_context = (await client.get(next_base + '/context')).json()
        assert next_context['context']['revision'] == 2 and next_context['context']['parentRevision'] == 1
        assert (await client.get(next_base + '/file')).content == downloaded.content
        next_headers = {'Origin': 'http://test', 'X-CSRF-Token': next_context['csrfToken']}
        next_expected = next_context['context']['sourceFile']['sha256']
        inspected_next = await client.post(next_base + '/preview', headers=next_headers, json={'expectedSha256': next_expected, 'operations': []})
        assert inspected_next.status_code == 200, inspected_next.text
        assert inspected_next.json()['model']['comments']['commentTargets'][0]['text'] == edit['text']
        assert inspected_next.json()['model']['comments']['sourceId'] != original_model['comments']['sourceId']
        stale = await client.post(next_base + '/preview', headers=next_headers, json={'expectedSha256': next_expected, 'operations': [edit]})
        assert stale.status_code == 422 and stale.json()['detail']['code'] == 'native_operations_invalid'
        stale_save = await client.post(next_base + '/save', headers=next_headers,
                                       json={'requestId': 'old-target-new-revision', 'expectedSha256': next_expected, 'operations': [edit]})
        assert stale_save.status_code == 422 and stale_save.json()['detail']['code'] == 'native_operations_invalid'
        assert env.publication.repository.completions == 1
        assert (await client.get(next_base + '/file')).content == downloaded.content
    assert {call['kind'] for call in env.calls} == {'inspect', 'patch'}
    assert any(call['returncode'] != 0 for call in env.calls)
    print('comment_http_evidence=' + json.dumps({'bridgeSha256': env.bridge_sha256,
          'sourceSha256': expected, 'outputSha256': artifact['sha256'], 'changedParts': ['word/comments.xml'],
          'validationIssue': 'native_validation_failed', 'revision': 2, 'completions': 1,
          'realBridgeCalls': len(env.calls), 'staleTargetsRejected': True}, ensure_ascii=False))


@pytest.mark.anyio
async def test_comment_http_rejects_unauthorized_csrf_origin_source_and_target_without_mutating_source(http_env):
    env = http_env
    async with AsyncClient(transport=ASGITransport(app=env.app), base_url='http://test') as client:
        base, context, headers = await import_and_open(client, env)
        expected = context['context']['sourceFile']['sha256']
        payload = {'expectedSha256': expected, 'operations': []}
        for invalid_headers in ({}, {**headers, 'Origin': 'https://foreign.invalid'}, {**headers, 'X-CSRF-Token': 'forged'}):
            for endpoint in ('preview', 'save'):
                response = await client.post(base + '/' + endpoint, headers=invalid_headers,
                                             json={**payload, **({'requestId': 'csrf-rejected'} if endpoint == 'save' else {})})
                assert response.status_code == 403, response.text
                assert response.json()['detail']['code'] == 'native_csrf_invalid'
        assert env.publication.repository.rows == {}
        token = client.cookies.get(NATIVE_SESSION_COOKIE)
        async with AsyncClient(transport=ASGITransport(app=env.app), base_url='http://test') as stranger:
            denied = await stranger.get(base + '/context')
            assert denied.status_code == 403 and denied.json()['detail']['code'] == 'report_editor_session_invalid'
            wrong_version = base.replace('/1/api', '/2/api')
            denied = await stranger.get(wrong_version + '/context', headers={'Cookie': NATIVE_SESSION_COOKIE + '=' + token})
            assert denied.status_code == 403 and denied.json()['detail']['code'] == 'native_permission_denied'
            denied = await stranger.get('/reports/v1/native/another-document/1/api/file', headers={'Cookie': NATIVE_SESSION_COOKIE + '=' + token})
            assert denied.status_code == 403 and denied.json()['detail']['code'] == 'native_permission_denied'
        for endpoint in ('preview', 'save'):
            stale = await client.post(base + '/' + endpoint, headers=headers,
                                      json={**payload, 'expectedSha256': '0' * 64, **({'requestId': 'stale-source'} if endpoint == 'save' else {})})
            assert stale.status_code == 409 and stale.json()['detail']['code'] == 'native_source_changed'
        assert env.publication.repository.rows == {}
        inspect = await client.post(base + '/preview', headers=headers, json=payload)
        assert inspect.status_code == 200, inspect.text
        target = inspect.json()['model']['comments']['commentTargets'][0]
        forged = {**operation(target, '不得写入'), 'sourceId': 'f' * 64}
        for endpoint in ('preview', 'save'):
            denied = await client.post(base + '/' + endpoint, headers=headers,
                                       json={**payload, 'operations': [forged], **({'requestId': 'forged-target'} if endpoint == 'save' else {})})
            assert denied.status_code == 422 and denied.json()['detail']['code'] == 'native_operations_invalid'
        assert env.publication.repository.completions == 0
        assert all(row.status == 'failed' for row in env.publication.repository.rows.values())
        assert (await client.get(base + '/file')).content == env.original


@pytest.mark.anyio
async def test_comment_http_rejects_unverified_import_and_signed_scope_or_context_mismatch(http_env):
    env = http_env
    async with AsyncClient(transport=ASGITransport(app=env.app), base_url='http://test') as client:
        rejected = await client.post('/reports/v1/native/import',
                                     headers={'X-Workspace-Thread': 'thread-1', 'X-Workspace-Capability': 'forged'},
                                     data={'requestId': 'unauthorized-import'}, files={'file': ('comments.docx', env.original)})
        assert rejected.status_code == 401, rejected.text
        assert not env.publication.repository.documents and env.calls == []
        _, context, _ = await import_and_open(client, env)
        actual = env.publication.repository.revisions[(context['context']['documentId'], 1)].context
        calls_before = len(env.calls)
        grants = env.publication.editor_grants
        capabilities = env.editor.capabilities(actual)
        foreign_scope = {**capabilities, 'scope': {**capabilities['scope'], 'userId': 'another-user'}}
        source_changed = actual.model_copy(update={'source_file': actual.source_file.model_copy(update={'sha256': '0' * 64})})
        for signed_context, caps, status, code in (
            (actual, foreign_scope, 404, 'native_document_not_found'),
            (actual, {**capabilities, 'native_editor': False}, 403, 'native_permission_denied'),
            (source_changed, capabilities, 403, 'native_permission_denied'),
        ):
            raw, _ = await grants.issue(signed_context, capabilities=caps)
            rejected = await client.get('/reports/v1/native/open/' + raw)
            assert rejected.status_code == status, rejected.text
            assert rejected.json()['detail']['code'] == code
        invalid_grant = await client.get('/reports/v1/native/open/forged')
        assert invalid_grant.status_code == 403 and invalid_grant.json()['detail']['code'] == 'report_editor_grant_invalid'
        assert len(env.calls) == calls_before and env.publication.repository.rows == {}
