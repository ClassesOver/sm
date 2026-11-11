"""经典批注真实授权/CSRF/Node/下载闭环，仓储使用既有内存夹具。"""
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.app import require_workspace_capability
from smart_reporting.report_editor.native import NativeEditorService
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_import import NativeImportService
from smart_reporting.report_editor.native_import_api import create_native_import_router
from smart_reporting.report_editor import slides
from smart_reporting.reporting.delivery.office_engine import engine_dir
from smart_reporting.reporting.tests.pptx_comments_fixture import create, verify
from smart_reporting.reporting.tests.test_native_ribbon_http_roundtrip import Repository, anyio_backend  # noqa: F401
from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication
from smart_reporting.tests.test_reporting_request_identity import SECRET, _capability


@pytest.mark.anyio
async def test_classic_comments_http_exact_delete_add_and_nonblocking_download(tmp_path, monkeypatch):
    bridge = engine_dir('slides') / 'dist/edit-pptx.mjs'
    assert bridge.is_file(), '验收使用生产打包桥，不自动构建或降级为tsx'
    calls, actual = [], slides.run_bridge

    def traced(engine, name, request, **kwargs):
        result = actual(engine, name, request, **kwargs)
        calls.append({'action': json.loads(request.read_text())['action'], 'command': result.args[:2], 'returncode': result.returncode})
        assert result.args[:2] == ['node', str(bridge)]
        return result

    monkeypatch.setattr(slides, 'run_bridge', traced)
    publication, _, downloads = await create_publication(tmp_path)
    publication.repository = Repository()
    publication.validator = AsyncMock(side_effect=RuntimeError('pptx_comments_validation_probe'))
    editor = NativeEditorService(publication.workspace, publication.repository, publication.editor_grants,
                                 report_editor=None, office_enabled=True, publication=publication)
    importer = NativeImportService(publication.workspace, publication.repository, publication.editor_grants)
    app = FastAPI()
    app.state.agentos_context = SimpleNamespace(settings=SimpleNamespace(workspace_hmac_secret=SECRET))
    app.middleware('http')(require_workspace_capability)
    app.include_router(create_native_import_router(importer, enabled=True))
    app.include_router(create_native_editor_router(publication.editor_grants, editor=editor, download_service=downloads, cookie_secure=False))
    source = create(); source_sha = hashlib.sha256(source).hexdigest(); text = 'HTTP真实根批注😀 <&>'
    operations = [{'kind': 'editSlides', 'commentEdits': [
        {'slideIndex': 0, 'kind': 'delete', 'authorId': 0, 'idx': 1},
        {'slideIndex': 1, 'kind': 'delete', 'authorId': 0, 'idx': 2},
        {'slideIndex': 0, 'kind': 'add', 'clientId': 'http-comment-1', 'text': text},
    ]}]
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        uploaded = await client.post('/reports/v1/native/import', headers={'X-Workspace-Thread': 'thread-1', 'X-Workspace-Capability': _capability()},
                                     data={'requestId': 'pptx-comments-import'}, files={'file': ('comments.pptx', source)})
        assert uploaded.status_code == 200, uploaded.text
        exchange = await client.get(uploaded.json()['editor']['url'])
        assert exchange.status_code == 303 and 'HttpOnly' in exchange.headers['set-cookie']
        opened = await client.get(exchange.headers['location']); assert opened.status_code == 200
        base = opened.url.path + '/api'; context = (await client.get(base+'/context')).json()
        assert context['editingEnabled'] and context['context']['format'] == 'pptx'
        assert context['context']['sourceFile']['sha256'] == source_sha
        headers = {'Origin': 'http://test', 'X-CSRF-Token': context['csrfToken']}
        payload = {'expectedSha256': source_sha, 'operations': operations}
        assert (await client.post(base+'/preview', json=payload)).status_code == 403
        preview = await client.post(base+'/preview', headers=headers, json=payload)
        assert preview.status_code == 200, preview.text
        assert preview.json()['model']['slides'][1]['comments']['items'] == []
        assert preview.json()['model']['slides'][0]['comments']['items'][-1]['text'] == text
        bad = {'kind': 'editSlides', 'commentEdits': operations[0]['commentEdits'], 'commentAuthor': '冒认作者'}
        assert (await client.post(base+'/preview', headers=headers, json={**payload, 'operations': [bad]})).status_code == 422
        request = {**payload, 'requestId': 'pptx-comments-save'}
        saved = await client.post(base+'/save', headers=headers, json=request); assert saved.status_code == 200, saved.text
        result = saved.json(); artifact = result['artifacts']['pptx']
        assert result['revisionRegistered'] and result['revision'] == 2 and result['parentRevision'] == 1
        assert result['validation']['ok'] is False and result['validation']['issues']
        download = await client.get(artifact['downloadUrl']); assert download.status_code == 200
        assert hashlib.sha256(download.content).hexdigest() == artifact['sha256']
        proof = verify(source, download.content, [text])
        repeated = await client.post(base+'/save', headers=headers, json=request)
        assert repeated.status_code == 200 and repeated.json()['revision'] == 2 and publication.repository.completions == 1
        assert (await client.get(base+'/file')).content == source
        reopened = await client.get(result['editor']['openUrl'], follow_redirects=True); assert reopened.status_code == 200
        next_base = reopened.url.path+'/api'; next_context = (await client.get(next_base+'/context')).json()
        next_model = await client.post(next_base+'/preview', headers={'Origin': 'http://test', 'X-CSRF-Token': next_context['csrfToken']},
                                       json={'expectedSha256': artifact['sha256'], 'operations': []})
        assert next_model.status_code == 200, next_model.text
        assert next_model.json()['model']['slides'][0]['comments']['items'][-1]['text'] == text
        (tmp_path/'source.pptx').write_bytes(source); (tmp_path/'downloaded.pptx').write_bytes(download.content)
        evidence = {'sourceSha256': source_sha, 'outputSha256': artifact['sha256'], 'bridgeSha256': hashlib.sha256(bridge.read_bytes()).hexdigest(),
                    'calls': calls, 'revision': 2, 'validationFailedButLinkIssued': True, 'changedParts': proof['changedParts'],
                    'sameIndexOtherAuthorPreserved': True, 'lastCommentRemoved': True, 'realHTTP': True, 'inMemoryRepository': True}
        (tmp_path/'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
