import base64
import hashlib
from io import BytesIO

import pytest
from PIL import Image

from smart_reporting.report_editor.native_xlsx_pictures import validate_xlsx_pictures


def test_picture_bytes_are_decoded_and_verified_without_remote_or_path_inputs():
    stream = BytesIO()
    Image.new('RGB', (3, 2), 'red').save(stream, format='PNG')
    content = stream.getvalue()
    picture = dict(mediaType='image/png', bytesBase64=base64.b64encode(content).decode(),
                   size=len(content), sha256=hashlib.sha256(content).hexdigest(),
                   widthPx=3, heightPx=2, name='普通照片.png')
    validate_xlsx_pictures([dict(kind='insertPicture', picture=picture)])
    for key, value in [('sha256', '0' * 64), ('mediaType', 'image/jpeg'),
                       ('widthPx', 4), ('size', len(content) - 1),
                       ('bytesBase64', 'https://invalid.example/pic.png')]:
        with pytest.raises(ValueError):
            validate_xlsx_pictures([dict(kind='insertPicture', picture={**picture, key: value})])
    with pytest.raises(ValueError):
        validate_xlsx_pictures([dict(kind='insertPicture', picture={**picture, 'path': '/tmp/photo.png'})])


@pytest.mark.parametrize(('format_name', 'media_type'), [('PNG', 'image/png'), ('JPEG', 'image/jpeg')])
def test_picture_rejects_truncated_pixels_even_when_header_is_readable(format_name, media_type):
    stream = BytesIO()
    Image.new('RGB', (16, 12), 'red').save(stream, format=format_name)
    content = stream.getvalue()
    def operation(data):
        return dict(kind='insertPicture', picture=dict(
            mediaType=media_type, bytesBase64=base64.b64encode(data).decode(),
            size=len(data), sha256=hashlib.sha256(data).hexdigest(),
            widthPx=16, heightPx=12, name='picture'))
    validate_xlsx_pictures([operation(content)])
    truncated = content[:-2] if format_name == 'JPEG' else content[:-20]
    with Image.open(BytesIO(truncated)) as image:
        assert image.size == (16, 12)
    with pytest.raises(ValueError, match='native_xlsx_picture_invalid'):
        validate_xlsx_pictures([operation(truncated)])
