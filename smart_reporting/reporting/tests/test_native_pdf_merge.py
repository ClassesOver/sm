from __future__ import annotations

import base64
import hashlib
from io import BytesIO

import pytest
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from .test_native_pdf_extract import extract_fixture
from .test_native_pdf_split import split_client


def merge_upload(label):
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(350, 450))
    canvas.drawString(24, 350, label)
    canvas.save()
    content = stream.getvalue()
    return {'sha256': hashlib.sha256(content).hexdigest(),
            'bytesBase64': base64.b64encode(content).decode()}


@pytest.mark.anyio
async def test_merge_pdf_appends_ordered_uploads_as_independent_document(tmp_path):
    f = await extract_fixture(tmp_path)
    client, headers = await split_client(f)
    uploads = [merge_upload('external second'), merge_upload('external first')]
    payload = {'requestId': 'merge-ordered', 'expectedSha256': f.original_identity.sha256, 'files': uploads}
    async with client:
        response = await client.post('/reports/v1/native/parent-document/4/api/merge-pdf', headers=headers, json=payload)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['validation']['ok'] is False
        assert result['source'] == {'documentId': 'parent-document', 'revision': 4,
            'sha256': f.original_identity.sha256, 'externalSha256s': [x['sha256'] for x in uploads]}
        artifact = result['artifacts']['pdf']
        downloaded = await client.get(artifact['downloadUrl'])
        assert downloaded.status_code == 200
        assert hashlib.sha256(downloaded.content).hexdigest() == artifact['sha256']
        reader = PdfReader(BytesIO(downloaded.content))
        assert [page.extract_text().strip() for page in reader.pages] == [
            'source page one', 'source page two', 'source page three', 'external second', 'external first']
        retry = await client.post('/reports/v1/native/parent-document/4/api/merge-pdf', headers=headers, json=payload)
        assert retry.status_code == 200
        assert retry.json()['documentId'] == result['documentId']
    assert len(f.repository.documents) == 1
    child = next(iter(f.repository.documents.values()))
    assert child.source.parent_sha256 == f.original_identity.sha256
    assert child.source.parent_revision == 4
    assert (await f.workspace.afile_bytes(f.thread, f.original_identity.path))[0] == f.original


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['csrf', 'origin', 'sha', 'revision', 'empty', 'external_sha', 'base64', 'path'])
async def test_merge_pdf_rejects_untrusted_uploads_and_authorization(tmp_path, fault):
    f = await extract_fixture(tmp_path)
    client, headers = await split_client(f)
    payload = {'requestId': 'merge-invalid', 'expectedSha256': f.original_identity.sha256,
               'files': [merge_upload('external')]}
    target = '/reports/v1/native/parent-document/4/api/merge-pdf'
    if fault == 'csrf': headers.pop('X-CSRF-Token')
    elif fault == 'origin': headers['Origin'] = 'https://foreign.invalid'
    elif fault == 'sha': payload['expectedSha256'] = 'f' * 64
    elif fault == 'revision': target = target.replace('/4/', '/3/')
    elif fault == 'empty': payload['files'] = []
    elif fault == 'external_sha': payload['files'][0]['sha256'] = 'f' * 64
    elif fault == 'base64': payload['files'][0]['bytesBase64'] += ' '
    else: payload['files'][0]['path'] = '/tmp/foreign.pdf'
    async with client:
        response = await client.post(target, headers=headers, json=payload)
    assert response.status_code == {'csrf': 403, 'origin': 403, 'sha': 409, 'revision': 403}.get(fault, 422), response.text
    assert f.repository.documents == {}
