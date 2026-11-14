"""普通 XLSX 图片的受控媒体校验；不接收文件路径或远程 URL。"""
from __future__ import annotations

import base64
import binascii
import hashlib
from io import BytesIO
from typing import Any

from PIL import Image


def validate_xlsx_pictures(operations: list[dict[str, Any]]) -> None:
    for operation in operations:
        if operation.get('kind') != 'insertPicture':
            continue
        picture = operation.get('picture')
        fields = {'mediaType', 'bytesBase64', 'size', 'sha256', 'widthPx', 'heightPx', 'name'}
        if not isinstance(picture, dict) or set(picture) != fields:
            raise ValueError('native_xlsx_picture_invalid')
        encoded = picture['bytesBase64']
        if not isinstance(encoded, str) or len(encoded) > 9 * 1024 * 1024:
            raise ValueError('native_xlsx_picture_invalid')
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError('native_xlsx_picture_invalid') from None
        if (not content or len(content) > 6 * 1024 * 1024
            or base64.b64encode(content).decode('ascii') != encoded
            or type(picture['size']) is not int or picture['size'] != len(content)
            or picture['sha256'] != hashlib.sha256(content).hexdigest()):
            raise ValueError('native_xlsx_picture_identity_invalid')
        try:
            with Image.open(BytesIO(content)) as image:
                media_type = {'PNG': 'image/png', 'JPEG': 'image/jpeg'}.get(image.format)
                width, height = image.size
                if not media_type or width * height > 40_000_000 or width > 30000 or height > 30000:
                    raise ValueError('native_xlsx_picture_identity_invalid')
                image.verify()
            with Image.open(BytesIO(content)) as image:
                image.load()
        except Exception:
            raise ValueError('native_xlsx_picture_invalid') from None
        if (not media_type or media_type != picture['mediaType'] or width * height > 40_000_000
            or width > 30000 or height > 30000
            or type(picture['widthPx']) is not int or type(picture['heightPx']) is not int
            or picture['widthPx'] != width or picture['heightPx'] != height):
            raise ValueError('native_xlsx_picture_identity_invalid')
