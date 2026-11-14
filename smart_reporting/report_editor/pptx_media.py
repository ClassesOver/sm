"""固定源音视频插入协议；只接收有界字节，不接收本机路径。"""
import base64
import binascii
import math
import hashlib
from io import BytesIO
from PIL import Image


def native_media_insertions(operation: dict) -> list[dict]:
    items = operation.get('mediaInsertions', [])
    invalid = 'native_office_operations_invalid'
    if not isinstance(items, list) or len(items) > 50:
        raise ValueError(invalid)
    total = 0
    for item in items:
        if (not isinstance(item, dict) or not {'slideIndex', 'kind', 'extension', 'bytesBase64'}.issubset(item)
            or set(item) - {'slideIndex', 'kind', 'extension', 'bytesBase64', 'name', 'center', 'poster'}
            or not isinstance(item['slideIndex'], int) or isinstance(item['slideIndex'], bool) or not 0 <= item['slideIndex'] < 500
            or not isinstance(item['kind'], str) or item['kind'] not in {'video', 'audio'}
            or not isinstance(item['extension'], str)
            or item['extension'] not in ({'mp4', 'm4v', 'mov', 'webm', 'avi'} if item['kind'] == 'video' else {'mp3', 'wav', 'm4a', 'aac', 'ogg'})
            or not isinstance(item['bytesBase64'], str) or not 0 < len(item['bytesBase64']) <= 8 * 1024 * 1024):
            raise ValueError(invalid)
        if 'name' in item and (not isinstance(item['name'], str) or len(item['name']) > 500 or any(ord(c) < 32 or ord(c) == 127 for c in item['name'])):
            raise ValueError(invalid)
        if 'center' in item:
            center = item['center']
            if (not isinstance(center, dict) or set(center) != {'x', 'y'}
                or any(not isinstance(n, (int, float)) or isinstance(n, bool) or not math.isfinite(n) or not 0 <= n <= 51206400 for n in center.values())):
                raise ValueError(invalid)
        try:
            data = base64.b64decode(item['bytesBase64'], validate=True)
        except (ValueError, binascii.Error):
            raise ValueError(invalid) from None
        if not data or len(data) > 6 * 1024 * 1024 or base64.b64encode(data).decode() != item['bytesBase64']:
            raise ValueError(invalid)
        if 'poster' in item:
            poster = item['poster']
            if item['kind'] != 'video' or not isinstance(poster, dict) or set(poster) != {'bytesBase64', 'sha256'} or not isinstance(poster['bytesBase64'], str) or len(poster['bytesBase64']) > 5592408:
                raise ValueError(invalid)
            try:
                png = base64.b64decode(poster['bytesBase64'], validate=True)
                if not png or len(png) > 4 * 1024 * 1024 or base64.b64encode(png).decode() != poster['bytesBase64'] or hashlib.sha256(png).hexdigest() != poster['sha256']:
                    raise ValueError(invalid)
                with Image.open(BytesIO(png)) as image:
                    if image.format != 'PNG' or any(not 0 < n <= 1600 for n in image.size):
                        raise ValueError(invalid)
                    image.verify()
                with Image.open(BytesIO(png)) as image:
                    image.load()
            except Exception:
                raise ValueError(invalid) from None
            total += len(png)
        total += len(data)
    # 图片本身仍由既有图片校验器核验；此处只把全部上传字节纳入同一预算。
    for key in ('images', 'pictureReplacements', 'backgroundImages'):
        for item in operation.get(key, []):
            try:
                total += len(base64.b64decode(item['bytesBase64'], validate=True))
            except (KeyError, TypeError, ValueError, binascii.Error):
                raise ValueError(invalid) from None
    if total > 8 * 1024 * 1024:
        raise ValueError(invalid)
    return items
