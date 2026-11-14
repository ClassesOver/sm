from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pypdf import PdfReader

from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE, create_native_editor_router
from .test_native_pdf_extract import extract_fixture


async def split_client(f):
    raw, _ = await f.editor.grants.issue(f.parent, capabilities=f.editor.capabilities(f.parent))
    token, _ = await f.editor.grants.exchange(raw)
    app = FastAPI()
    app.include_router(create_native_editor_router(f.editor.grants, editor=f.editor,
        download_service=f.downloads, cookie_secure=False))
    client = AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url='http://test')
    client.cookies.set(NATIVE_SESSION_COOKIE, token, path='/reports/v1/native')
    return client, {'Origin': 'http://test', 'X-CSRF-Token': f.editor.grants.csrf_token(token)}


@pytest.mark.anyio
async def test_split_pdf_registers_each_consecutive_chunk_and_retains_remainder(tmp_path):
    f = await extract_fixture(tmp_path)
    client, headers = await split_client(f)
    async with client:
        response = await client.post('/reports/v1/native/parent-document/4/api/split-pdf', headers=headers,
            json={'requestId': 'split-two', 'expectedSha256': f.original_identity.sha256, 'chunkSize': 2})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['source'] == {'documentId': 'parent-document', 'revision': 4, 'sha256': f.original_identity.sha256}
        assert [part['pages'] for part in result['parts']] == [[1, 2], [3]]
        assert [part['filename'] for part in result['parts']] == ['source-1.pdf', 'source-2.pdf']
        assert result['validation']['ok'] is False
        texts = []
        for part in result['parts']:
            artifact = part['result']['artifacts']['pdf']
            downloaded = await client.get(artifact['downloadUrl'])
            assert downloaded.status_code == 200
            assert len(downloaded.content) == artifact['size']
            assert hashlib.sha256(downloaded.content).hexdigest() == artifact['sha256']
            texts.append([page.extract_text().strip() for page in PdfReader(BytesIO(downloaded.content)).pages])
            child = next(doc for doc in f.repository.documents.values() if doc.document_id == part['result']['documentId'])
            assert child.source.parent_sha256 == f.original_identity.sha256
            assert child.source.parent_revision == 4
        assert texts == [['source page one', 'source page two'], ['source page three']]
        retry = await client.post('/reports/v1/native/parent-document/4/api/split-pdf', headers=headers,
            json={'requestId': 'split-two', 'expectedSha256': f.original_identity.sha256, 'chunkSize': 2})
        assert retry.status_code == 200
        assert [p['result']['documentId'] for p in retry.json()['parts']] == [p['result']['documentId'] for p in result['parts']]
    assert len(f.repository.documents) == 2
    original, _ = await f.workspace.afile_bytes(f.thread, f.original_identity.path)
    assert original == f.original


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['csrf', 'origin', 'sha', 'revision', 'boolean', 'zero', 'all_pages'])
async def test_split_pdf_rejects_untrusted_or_non_splitting_requests(tmp_path, fault):
    f = await extract_fixture(tmp_path)
    client, headers = await split_client(f)
    payload = {'requestId': 'invalid-split', 'expectedSha256': f.original_identity.sha256, 'chunkSize': 1}
    target = '/reports/v1/native/parent-document/4/api/split-pdf'
    if fault == 'csrf': headers.pop('X-CSRF-Token')
    elif fault == 'origin': headers['Origin'] = 'https://foreign.invalid'
    elif fault == 'sha': payload['expectedSha256'] = 'f' * 64
    elif fault == 'revision': target = target.replace('/4/', '/3/')
    elif fault == 'boolean': payload['chunkSize'] = True
    elif fault == 'zero': payload['chunkSize'] = 0
    else: payload['chunkSize'] = 3
    async with client:
        response = await client.post(target, headers=headers, json=payload)
    assert response.status_code == {'csrf': 403, 'origin': 403, 'sha': 409, 'revision': 403,
        'boolean': 422, 'zero': 422, 'all_pages': 422}[fault], response.text
    assert f.repository.documents == {}
