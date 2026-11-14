"""Zoom协议：服务端负责PNG解码与schema，桥再核验实际页面身份。"""
import base64
from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image

from smart_reporting.report_editor.native_office import _pptx_arguments


def insertion():
    stream = BytesIO()
    Image.new('RGB', (2, 2), 'white').save(stream, format='PNG')
    return {'slideIdentity': 'a' * 64, 'targetSlideIdentity': 'b' * 64,
            'bytesBase64': base64.b64encode(stream.getvalue()).decode(),
            'geometry': {'x': 0, 'y': 0, 'width': 240, 'height': 135}, 'mode': 'slide'}


def test_zoom_protocol_accepts_multiple_targets_and_preserves_identity_fields():
    first = insertion()
    second = {**first, 'targetSlideIdentity': 'c' * 64, 'mode': 'section'}
    items = [first, second]
    assert _pptx_arguments({'kind': 'editSlides', 'zoomInsertions': items})['zoom_insertions'] == items


@pytest.mark.parametrize('fault', ['identity', 'mode', 'png', 'geometry', 'duplicate', 'path'])
def test_zoom_protocol_rejects_untrusted_or_malformed_records(fault):
    item = insertion()
    items = [item]
    if fault == 'identity': item['slideIdentity'] = 'client-path.xml'
    if fault == 'mode': item['mode'] = 'summary'
    if fault == 'png': item['bytesBase64'] = base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()
    if fault == 'geometry': item['geometry']['width'] = True
    if fault == 'duplicate': items.append(deepcopy(item))
    if fault == 'path': item['targetPath'] = 'ppt/slides/slide99.xml'
    with pytest.raises(ValueError):
        _pptx_arguments({'kind': 'editSlides', 'zoomInsertions': items})
