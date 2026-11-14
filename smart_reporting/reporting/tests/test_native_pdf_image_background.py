"""已有图像缩略图的真实背景区域：回执、授权和只读边界。"""

import base64
import hashlib
from io import BytesIO

import pytest
from PIL import Image

from smart_reporting.reporting.delivery import pdf_native
from smart_reporting.reporting.tests.test_native_pdf_image_pixels import anyio_backend, pixels_http, _target


def _request(content=b'pdf-source'):
    return {**_target(content), 'clip': {'x': 0.0, 'y': 0.0, 'width': 3.0, 'height': 2.0}, 'pxWidth': 3}


def _receipt(content=b'pdf-source'):
    stream = BytesIO()
    Image.new('RGB', (3, 2), 'white').save(stream, 'PNG')
    png = stream.getvalue()
    request = _request(content)
    return {key: value for key, value in request.items() if key != 'pxWidth'} | {
        'image': base64.b64encode(png).decode(), 'width': 3, 'height': 2,
        'sha256': hashlib.sha256(png).hexdigest(),
    }


def test_background_read_verifies_png_and_keeps_source_bytes(monkeypatch):
    content = b'pdf-source'
    receipt = _receipt(content)

    def invoke(payload, root):
        assert payload['kind'] == 'imageBackground' and payload['target'] == _request(content)
        assert (root / 'input.pdf').read_bytes() == content
        return receipt

    monkeypatch.setattr(pdf_native, '_invoke', invoke)
    result = pdf_native.read_pdf_image_background(content, _request(content))
    with Image.open(BytesIO(base64.b64decode(result['image']))) as image:
        assert image.convert('RGB').getpixel((1, 1)) == (255, 255, 255)
    assert result == receipt and content == b'pdf-source'


@pytest.mark.parametrize('change', [
    {'sourceSha256': '0' * 64}, {'pageId': 'foreign'}, {'imageId': 'c' * 64},
    {'expectedImageSha256': 'd' * 64}, {'sha256': '0' * 64}, {'width': 4},
    {'height': True}, {'image': 'not PNG'},
    {'clip': {'x': 1.0, 'y': 0.0, 'width': 3.0, 'height': 2.0}},
    {'clip': {'x': False, 'y': 0.0, 'width': 3.0, 'height': 2.0}},
])
def test_background_read_rejects_unbound_or_malformed_patch(monkeypatch, change):
    monkeypatch.setattr(pdf_native, '_invoke', lambda *args: {**_receipt(), **change})
    with pytest.raises(ValueError, match='pdf_image_.*identity_invalid'):
        pdf_native.read_pdf_image_background(b'pdf-source', _request())


def test_background_read_rejects_valid_png_with_wrong_requested_raster_size(monkeypatch):
    monkeypatch.setattr(pdf_native, '_invoke', lambda *args: _receipt())
    request = {**_request(), 'pxWidth': 6}
    with pytest.raises(ValueError, match='pdf_image_background_identity_invalid'):
        pdf_native.read_pdf_image_background(b'pdf-source', request)


def test_background_raster_limit_uses_rounded_pixel_height(monkeypatch):
    stream = BytesIO()
    Image.new('RGB', (1, 2400), 'white').save(stream, 'PNG')
    png = stream.getvalue()
    request = {**_request(), 'clip': {'x': 0.0, 'y': 0.0, 'width': 1.0, 'height': 2400.499}, 'pxWidth': 1}
    receipt = {**_receipt(), 'clip': request['clip'], 'width': 1, 'height': 2400,
               'image': base64.b64encode(png).decode(), 'sha256': hashlib.sha256(png).hexdigest()}
    monkeypatch.setattr(pdf_native, '_invoke', lambda *args: receipt)
    assert pdf_native.read_pdf_image_background(b'pdf-source', request)['height'] == 2400


BASE = '/reports/v1/native/document/1/api/image-background'


@pytest.mark.anyio
async def test_background_http_uses_authorized_source_without_creating_revision(pixels_http, monkeypatch):
    fixture = pixels_http
    body = {**fixture.body, 'clip': _request()['clip'], 'pxWidth': 3}
    receipt = {**_receipt(fixture.content), **{key: body[key] for key in fixture.body}}

    def invoke(payload, root):
        assert payload['kind'] == 'imageBackground'
        assert (root / 'input.pdf').read_bytes() == fixture.content
        return receipt

    monkeypatch.setattr(pdf_native, '_invoke', invoke)
    response = await fixture.client.post(BASE, json=body, headers=fixture.headers)
    assert response.status_code == 200, response.text
    assert response.json()['sha256'] == receipt['sha256']
    assert len(fixture.repository.revisions) == 1 and not fixture.repository.documents


@pytest.mark.anyio
@pytest.mark.parametrize('mode, status', [
    ('cookie', 403), ('csrf', 403), ('stale', 409), ('extra', 422),
    ('clip-extra', 422), ('clip-boolean', 422), ('disabled', 503),
])
async def test_background_http_enforces_existing_read_boundaries(pixels_http, monkeypatch, mode, status):
    fixture = pixels_http
    body = {**fixture.body, 'clip': _request()['clip'], 'pxWidth': 3}
    headers = dict(fixture.headers)
    if mode == 'cookie':
        fixture.client.cookies.clear()
    elif mode == 'csrf':
        headers['X-CSRF-Token'] = 'wrong'
    elif mode == 'stale':
        body['sourceSha256'] = '0' * 64
    elif mode == 'extra':
        body['path'] = '/etc/passwd'
    elif mode == 'clip-extra':
        body['clip'] = {**body['clip'], 'path': '/etc/passwd'}
    elif mode == 'clip-boolean':
        body['clip'] = {**body['clip'], 'width': True}
    elif mode == 'disabled':
        fixture.editor.pdf_enabled = False

    def unexpected_engine(*args):
        raise AssertionError('被拒请求不应进入引擎')

    monkeypatch.setattr(pdf_native, '_invoke', unexpected_engine)
    response = await fixture.client.post(BASE, json=body, headers=headers)
    assert response.status_code == status, response.text
    assert len(fixture.repository.revisions) == 1 and not fixture.repository.documents


@pytest.mark.anyio
async def test_background_http_renders_actual_underlying_color_and_text_without_writing(tmp_path):
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE, create_native_editor_router
    from smart_reporting.report_editor.native_models import NativeArtifacts, NativeRevision
    from smart_reporting.reporting.tests.test_native_editor_api import Repository
    from smart_reporting.reporting.tests.test_native_pdf_existing_image_replace import _fixture

    source, overlay = BytesIO(), BytesIO()
    Image.new('RGB', (8, 6), 'red').save(overlay, 'PNG')
    pdf = canvas.Canvas(source, pagesize=(400, 500), invariant=True)
    pdf.setFillColorRGB(40 / 255, 120 / 255, 210 / 255)
    pdf.rect(60, 90, 100, 80, fill=1, stroke=0)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.drawString(65, 120, 'under image')
    pdf.drawImage(ImageReader(BytesIO(overlay.getvalue())), 60, 90, 100, 80)
    pdf.save()
    content = source.getvalue()
    editor, context, _ = await _fixture(tmp_path, content)
    editor.save = AsyncMock(side_effect=AssertionError('background read must not save'))
    model = pdf_native.inspect_pdf(content)
    target = model['existingImages'][0]
    repository = Repository()
    editor.repository = repository
    repository.revisions[(context.document_id, context.revision)] = NativeRevision(
        documentId=context.document_id, revision=1, scope=context.scope, requestId='background-source',
        requestSha256=context.source_file.sha256, status='saved', context=context,
        artifacts=NativeArtifacts(pdf=context.source_file), createdAt=datetime.now(UTC))
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    token, _ = await editor.grants.exchange(raw)
    app = FastAPI()
    app.include_router(create_native_editor_router(editor.grants, editor=editor, cookie_secure=False))
    body = {
        'sourceSha256': context.source_file.sha256,
        **{key: target[key] for key in ('pageId', 'imageId', 'expectedImageSha256')},
        'clip': {'x': 60, 'y': 330, 'width': 100, 'height': 80}, 'pxWidth': 200,
    }
    headers = {'Origin': 'http://test', 'X-CSRF-Token': editor.grants.csrf_token(token)}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token)
        response = await client.post(BASE, json=body, headers=headers)
        assert response.status_code == 200, response.text
        receipt = response.json()
        png = base64.b64decode(receipt['image'], validate=True)
        assert receipt['sha256'] == hashlib.sha256(png).hexdigest()
        assert {key: receipt[key] for key in body if key != 'pxWidth'} == {
            key: value for key, value in body.items() if key != 'pxWidth'
        }
        with Image.open(BytesIO(png)) as image:
            assert image.size == (200, 160)
            pixels = list(image.convert('RGB').getdata())
            assert sum(all(abs(channel - expected) <= 2 for channel, expected in zip(pixel, (40, 120, 210)))
                       for pixel in pixels) > 20_000
            assert sum(max(pixel) < 80 for pixel in pixels) > 50, '原图下面的正文必须保留'
            assert sum(pixel[0] > 200 and pixel[1] < 40 and pixel[2] < 40 for pixel in pixels) == 0
        rejected = await client.post(BASE, json={**body, 'expectedImageSha256': '0' * 64}, headers=headers)
        assert rejected.status_code == 422, rejected.text
    actual, _ = await editor.workspace.afile_bytes(
        bind_native_workspace(editor.workspace, context.scope), context.source_file.path)
    assert actual == content and len(repository.revisions) == 1 and not repository.documents
    editor.save.assert_not_awaited()
