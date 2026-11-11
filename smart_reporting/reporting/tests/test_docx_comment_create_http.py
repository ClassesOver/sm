"""新建批注的真实 FastAPI、生产打包 Node 桥及独立 ZIP/lxml 回读。"""
import hashlib
import json
from io import BytesIO
from zipfile import ZipFile

import pytest
from httpx import ASGITransport, AsyncClient
from lxml import etree

from smart_reporting.reporting.tests.test_docx_comment_http import http_env, import_and_open, anyio_backend  # noqa: F401

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


@pytest.mark.anyio
async def test_create_comment_http_exact_selection_save_download_and_reopen_nonblocking(http_env, tmp_path):
    env = http_env

    async def failed_validation(context, artifacts):
        raise RuntimeError('new_comment_validation_probe')

    env.publication.validator = failed_validation
    async with AsyncClient(transport=ASGITransport(app=env.app), base_url='http://test') as client:
        base, context, headers = await import_and_open(client, env)
        expected = context['context']['sourceFile']['sha256']
        inspected = await client.post(base + '/preview', headers=headers, json={'expectedSha256': expected, 'operations': []})
        assert inspected.status_code == 200, inspected.text
        model = inspected.json()['model']['commentCreation']
        assert model['readOnlyReason'] is None
        target = model['targets'][0]
        assert target['text'] == 'Anchor text'
        operation = {'kind': 'createComment', 'sourceId': model['sourceId'], 'clientId': 'http-new-thread',
                     'author': 'HTTP测试用户', 'date': '2026-11-11T01:02:03Z', 'text': 'HTTP精确新批注 😀 &',
                     'ranges': [{'targetId': target['targetId'], 'expectedParagraphSha256': target['expectedParagraphSha256'],
                                 'from': 2, 'to': 8, 'text': 'chor t'}]}
        payload = {'expectedSha256': expected, 'operations': [operation]}
        no_csrf = await client.post(base + '/preview', json=payload)
        assert no_csrf.status_code == 403
        for bad in ({**operation, 'sourceId': 'f' * 64}, {**operation, 'ranges': [{**operation['ranges'][0], 'text': 'forged'}]}):
            denied = await client.post(base + '/preview', headers=headers, json={**payload, 'operations': [bad]})
            assert denied.status_code == 422, denied.text
        preview = await client.post(base + '/preview', headers=headers, json=payload)
        assert preview.status_code == 200, preview.text
        assert preview.json()['model']['comments']['commentTargets'][-1]['text'] == operation['text']
        request = {**payload, 'requestId': 'create-comment-http-save'}
        response = await client.post(base + '/save', headers=headers, json=request)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['revisionRegistered'] and result['revision'] == 2 and result['parentRevision'] == 1
        assert result['validation']['ok'] is False and result['validation']['issues']
        artifact = result['artifacts']['word']
        async with AsyncClient(transport=ASGITransport(app=env.app), base_url='http://test') as downloader:
            download = await downloader.get(artifact['downloadUrl'])
        assert download.status_code == 200, download.text
        assert hashlib.sha256(download.content).hexdigest() == artifact['sha256']
        with ZipFile(BytesIO(env.original)) as original, ZipFile(BytesIO(download.content)) as saved:
            assert saved.testzip() is None
            changed = [p for p in original.namelist() if original.read(p) != saved.read(p)]
            assert changed == ['word/document.xml', 'word/comments.xml']
            for name in saved.namelist():
                if name.endswith(('.xml', '.rels')):
                    etree.fromstring(saved.read(name))
            comments = etree.fromstring(saved.read('word/comments.xml'))
            old = comments.find('w:comment', NS)
            assert ''.join(old.itertext()) == 'Original note'
            new = comments.findall('w:comment', NS)[-1]
            new_id = new.get('{' + NS['w'] + '}id')
            assert new_id != old.get('{' + NS['w'] + '}id')
            assert new.get('{' + NS['w'] + '}author') == operation['author']
            assert new.get('{' + NS['w'] + '}date') == operation['date']
            assert ''.join(new.itertext()) == operation['text']
            document = etree.fromstring(saved.read('word/document.xml'))
            paragraph = document.find('.//w:body/w:p', NS)
            selected, active = '', False
            for child in paragraph:
                if child.tag == '{' + NS['w'] + '}commentRangeStart' and child.get('{' + NS['w'] + '}id') == new_id:
                    active = True
                elif child.tag == '{' + NS['w'] + '}commentRangeEnd' and child.get('{' + NS['w'] + '}id') == new_id:
                    active = False
                elif active:
                    selected += ''.join(child.xpath('.//w:t/text()', namespaces=NS))
            assert selected == 'chor t'
        repeated = await client.post(base + '/save', headers=headers, json=request)
        assert repeated.status_code == 200 and repeated.json()['revision'] == 2
        assert env.publication.repository.completions == 1
        assert (await client.get(base + '/file')).content == env.original
        reopened = await client.get(result['editor']['openUrl'], follow_redirects=True)
        assert reopened.status_code == 200, reopened.text
        next_base = reopened.url.path + '/api'
        next_context = (await client.get(next_base + '/context')).json()
        assert next_context['context']['revision'] == 2 and next_context['context']['parentRevision'] == 1
        assert (await client.get(next_base + '/file')).content == download.content
        next_headers = {'Origin': 'http://test', 'X-CSRF-Token': next_context['csrfToken']}
        next_expected = next_context['context']['sourceFile']['sha256']
        next_model = await client.post(next_base + '/preview', headers=next_headers, json={'expectedSha256': next_expected, 'operations': []})
        assert next_model.status_code == 200, next_model.text
        assert next_model.json()['model']['comments']['commentTargets'][-1]['text'] == operation['text']
        stale = await client.post(next_base + '/save', headers=next_headers, json={**request, 'requestId': 'stale-new-thread', 'expectedSha256': next_expected})
        assert stale.status_code == 422 and env.publication.repository.completions == 1
        (tmp_path / 'source.docx').write_bytes(env.original)
        (tmp_path / 'downloaded.docx').write_bytes(download.content)
        evidence = {'bridgeSha256': env.bridge_sha256, 'sourceSha256': expected, 'outputSha256': artifact['sha256'],
                    'exactText': selected, 'newId': new_id, 'revision': 2, 'validationFailedButLinkIssued': True,
                    'changedParts': changed, 'realBridgeCalls': len(env.calls), 'staleRejected': True}
        (tmp_path / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        print('create_comment_http_evidence=' + json.dumps(evidence, ensure_ascii=False))
