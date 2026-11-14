"""3D草稿规范化：沿现有资产预算，不接受路径或远端资源。"""
import base64
import binascii
import json
import math
import re
import struct


def native_model_edits(operation: dict) -> dict:
    invalid = 'native_office_operations_invalid'
    def fail():
        raise ValueError(invalid)
    def decode(value, limit):
        try:
            if not isinstance(value, str) or len(value) > (limit + 2) // 3 * 4:
                fail()
            data = base64.b64decode(value, validate=True)
            if not data or len(data) > limit or base64.b64encode(data).decode() != value:
                fail()
            return data
        except (ValueError, binascii.Error):
            fail()
    def png(value):
        data = decode(value, 4 * 1024 * 1024)
        if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or any(not 0 < n <= 1600 for n in struct.unpack('>II', data[16:24])):
            fail()
        return data
    result, total = {}, 0
    for key, fields in [('modelInsertions', {'slideIndex', 'key', 'bytesBase64', 'posterBase64', 'name', 'aspect', 'rot'}), ('modelViews', {'slideIndex', 'elementId', 'expectedSha256', 'rot', 'posterBase64'})]:
        items = operation.get(key, [])
        if not isinstance(items, list) or len(items) > (30 if key == 'modelInsertions' else 100):
            fail()
        seen = set()
        for item in items:
            if not isinstance(item, dict) or set(item) != fields or not isinstance(item['slideIndex'], int) or isinstance(item['slideIndex'], bool) or not 0 <= item['slideIndex'] < 500:
                fail()
            rot = item['rot']
            if not isinstance(rot, dict) or set(rot) != {'ax', 'ay', 'az'} or any(not isinstance(n, (int, float)) or isinstance(n, bool) or not math.isfinite(n) or abs(n) > 2160000000 for n in rot.values()):
                fail()
            total += len(png(item['posterBase64']))
            if key == 'modelInsertions':
                if not isinstance(item['key'], str) or not re.fullmatch('[a-zA-Z0-9-]{1,80}', item['key']) or not isinstance(item['name'], str) or len(item['name']) > 500 or any(ord(c) < 32 or ord(c) == 127 for c in item['name']) or not isinstance(item['aspect'], (int, float)) or isinstance(item['aspect'], bool) or not 1/3 <= item['aspect'] <= 3:
                    fail()
                identity = item['key']
                data = decode(item['bytesBase64'], 6 * 1024 * 1024); total += len(data)
                try:
                    if len(data) < 20 or struct.unpack('<III', data[:12]) != (0x46546c67, 2, len(data)) or struct.unpack('<I', data[16:20])[0] != 0x4e4f534a:
                        fail()
                    length = struct.unpack('<I', data[12:16])[0]
                    if length % 4 or 20 + length > len(data):
                        fail()
                    gltf = json.loads(data[20:20+length])
                    if gltf.get('asset', {}).get('version') != '2.0' or any('uri' in resource for name in ('images', 'buffers') for resource in gltf.get(name, [])):
                        fail()
                except (ValueError, TypeError, AttributeError, struct.error):
                    fail()
            else:
                if not isinstance(item['elementId'], str) or not item['elementId'] or not isinstance(item['expectedSha256'], str) or not re.fullmatch('[a-f0-9]{64}', item['expectedSha256']):
                    fail()
                identity = (item['slideIndex'], item['elementId'])
            if identity in seen:
                fail()
            seen.add(identity)
        result['model_insertions' if key == 'modelInsertions' else 'model_views'] = items
    for key in ('images', 'pictureReplacements', 'backgroundImages', 'mediaInsertions'):
        for item in operation.get(key, []):
            total += len(decode(item.get('bytesBase64'), 8 * 1024 * 1024))
            if key == 'mediaInsertions' and item.get('poster'):
                total += len(decode(item['poster'].get('bytesBase64'), 4 * 1024 * 1024))
    if total > 8 * 1024 * 1024:
        fail()
    return result
