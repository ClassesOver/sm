"""PDF原图像素只读接口：回执身份、会话边界与来源字节保持。"""
import base64
import hashlib
from io import BytesIO

import pytest
from PIL import Image

from smart_reporting.reporting.delivery import pdf_native


def _target(content=b'pdf-source'):
    return {'sourceSha256': hashlib.sha256(content).hexdigest(), 'pageId': 'page-1',
            'imageId': 'a' * 64, 'expectedImageSha256': 'b' * 64}


def _receipt(content=b'pdf-source'):
    stream = BytesIO(); Image.new('RGBA', (3, 2), 'red').save(stream, 'PNG')
    png = stream.getvalue()
    return {**_target(content), 'image': base64.b64encode(png).decode(), 'width': 3, 'height': 2,
            'sha256': hashlib.sha256(png).hexdigest()}


@pytest.mark.parametrize('change', [
    {'sourceSha256': '0' * 64}, {'pageId': 'foreign'}, {'imageId': 'c' * 64}, {'expectedImageSha256': 'd' * 64},
    {'sha256': '0' * 64}, {'width': 4}, {'height': 3}, {'width': True}, {'height': 0},
    {'image': 'not base64!'}, {'image': base64.b64encode(b'not PNG').decode()},
])
def test_pixel_read_rejects_unverified_receipt(monkeypatch, change):
    monkeypatch.setattr(pdf_native, '_invoke', lambda *args: {**_receipt(), **change})
    with pytest.raises(ValueError, match='pdf_image_.*identity_invalid'):
        pdf_native.read_pdf_image_pixels(b'pdf-source', _target())


def test_pixel_read_accepts_actual_png_identity_without_mutating_source(monkeypatch):
    content = b'pdf-source'; receipt = _receipt(content)
    def invoke(payload, root):
        assert payload['kind'] == 'imagePixels' and payload['target'] == _target(content)
        assert (root / 'input.pdf').read_bytes() == content
        return receipt
    monkeypatch.setattr(pdf_native, '_invoke', invoke)
    assert pdf_native.read_pdf_image_pixels(content, _target(content)) == receipt
    assert content == b'pdf-source'

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE, create_native_editor_router
from smart_reporting.report_editor.native_models import NativeArtifacts, NativeRevision
from smart_reporting.reporting.tests.test_native_editor_api import Repository
from smart_reporting.reporting.tests.test_native_pdf_existing_image_bake import _source
from smart_reporting.reporting.tests.test_native_pdf_existing_image_replace import _fixture


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def pixels_http(tmp_path):
    content = _source(); editor, context, _ = await _fixture(tmp_path, content)
    model = pdf_native.inspect_pdf(content)
    target = next(image for image in model['existingImages'] if image['rect'] == [60, 90, 160, 170])
    repository = Repository(); editor.repository = repository
    repository.revisions[(context.document_id, context.revision)] = NativeRevision(
        documentId=context.document_id, revision=1, scope=context.scope, requestId='pixels-source',
        requestSha256=context.source_file.sha256, status='saved', context=context,
        artifacts=NativeArtifacts(pdf=context.source_file), createdAt=datetime.now(UTC))
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context)); token, _ = await editor.grants.exchange(raw)
    app = FastAPI(); app.include_router(create_native_editor_router(editor.grants, editor=editor, cookie_secure=False))
    headers = {'Origin': 'http://test', 'X-CSRF-Token': editor.grants.csrf_token(token)}
    body = {'sourceSha256': context.source_file.sha256, **{key: target[key] for key in ('pageId', 'imageId', 'expectedImageSha256')}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token)
        yield SimpleNamespace(client=client, editor=editor, context=context, repository=repository, headers=headers, body=body, content=content, token=token)


BASE = '/reports/v1/native/document/1/api/image-pixels'


@pytest.mark.anyio
async def test_pixel_http_reads_only_selected_image_and_never_writes_revision(pixels_http):
    f = pixels_http; f.editor.save = AsyncMock(side_effect=AssertionError('read must not save'))
    response = await f.client.post(BASE, json=f.body, headers=f.headers)
    assert response.status_code == 200, response.text
    result = response.json(); png = base64.b64decode(result['image'], validate=True)
    assert result['sha256'] == hashlib.sha256(png).hexdigest()
    assert {key: result[key] for key in f.body} == f.body
    with Image.open(BytesIO(png)) as image:
        assert image.format == 'PNG' and image.size == (result['width'], result['height']) == (300, 240)
        red = image.convert('RGBA').getpixel((75, 60))
        assert red[0] > 240 and red[1] < 20 and red[2] < 20
    actual, _ = await f.editor.workspace.afile_bytes(bind_native_workspace(f.editor.workspace, f.context.scope), f.context.source_file.path)
    assert actual == f.content and len(f.repository.revisions) == 1 and not f.repository.documents
    f.editor.save.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('mode, status', [('cookie', 403), ('csrf', 403), ('origin', 403), ('revision', 403), ('scope', 404), ('stale', 409), ('image', 422), ('fingerprint', 422), ('page', 422), ('extra', 422), ('changed', 409), ('disabled', 503)])
async def test_pixel_http_enforces_session_csrf_scope_and_source_identity(pixels_http, mode, status):
    f = pixels_http; body = dict(f.body); headers = dict(f.headers); url = BASE
    if mode == 'cookie': f.client.cookies.clear()
    elif mode == 'csrf': headers['X-CSRF-Token'] = 'wrong'
    elif mode == 'origin': headers['Origin'] = 'http://foreign'
    elif mode == 'revision': url = BASE.replace('/1/', '/2/')
    elif mode == 'scope':
        foreign = f.context.model_copy(update={'scope': f.context.scope.model_copy(update={'user_id': 'foreign'})})
        raw, _ = await f.editor.grants.issue(foreign, capabilities=f.editor.capabilities(foreign)); token, _ = await f.editor.grants.exchange(raw)
        f.client.cookies.set(NATIVE_SESSION_COOKIE, token); headers['X-CSRF-Token'] = f.editor.grants.csrf_token(token)
    elif mode == 'stale': body['sourceSha256'] = '0' * 64
    elif mode == 'image': body['imageId'] = '0' * 64
    elif mode == 'fingerprint': body['expectedImageSha256'] = '0' * 64
    elif mode == 'page': body['pageId'] += ':foreign'
    elif mode == 'extra': body['path'] = '/etc/passwd'
    elif mode == 'changed':
        await f.editor.workspace.awrite_bytes(bind_native_workspace(f.editor.workspace, f.context.scope), f.context.source_file.path, b'changed', overwrite=True, expected_sha256=f.context.source_file.sha256)
    elif mode == 'disabled': f.editor.pdf_enabled = False
    response = await f.client.post(url, json=body, headers=headers)
    assert response.status_code == status, response.text
    assert len(f.repository.revisions) == 1 and not f.repository.documents


def test_pixel_read_rejects_non_png_even_when_byte_hash_matches(monkeypatch):
    stream = BytesIO(); Image.new('RGB', (3, 2), 'red').save(stream, 'JPEG')
    jpeg = stream.getvalue()
    receipt = {**_receipt(), 'image': base64.b64encode(jpeg).decode(), 'sha256': hashlib.sha256(jpeg).hexdigest()}
    monkeypatch.setattr(pdf_native, '_invoke', lambda *args: receipt)
    with pytest.raises(ValueError, match='pdf_image_pixels_identity_invalid'):
        pdf_native.read_pdf_image_pixels(b'pdf-source', _target())
