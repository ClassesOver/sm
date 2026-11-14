"""PPTX母版文字对象的有限结构协议；实际部件/SPID仍交源引擎核验。"""
import math
import re
from typing import Any


def native_master_element_edits(records: Any) -> list[dict[str, Any]]:
    if not isinstance(records, list) or len(records) > 200:
        raise ValueError('native_office_operations_invalid')
    seen, result, total = set(), [], 0
    for item in records:
        if (not isinstance(item, dict) or not isinstance(item.get('partPath'), str)
            or not re.fullmatch(r'ppt/(?:slideMasters/slideMaster|slideLayouts/slideLayout)[1-9]\d*\.xml', item['partPath'])):
            raise ValueError('native_office_operations_invalid')
        if item.get('kind') in ('delete', 'setFill', 'setStroke', 'setTransform'):
            spid = item.get('spid')
            expected = {'kind', 'partPath', 'spid', 'fill'} if item['kind'] == 'setFill' else {'kind', 'partPath', 'spid', 'box'} if item['kind'] == 'setTransform' else {'kind', 'partPath', 'spid', 'stroke'} if item['kind'] == 'setStroke' else {'kind', 'partPath', 'spid'}
            if (set(item) != expected or isinstance(spid, bool) or not isinstance(spid, int) or not 0 < spid <= 4294967295
                or item['kind'] == 'setFill' and (not isinstance(item.get('fill'), str) or not re.fullmatch(r'none|#[0-9A-Fa-f]{6}', item['fill']))
                or item['kind'] == 'setStroke' and not (item['stroke'] is None or isinstance(item['stroke'], dict) and set(item['stroke']) == {'color', 'widthPt'}
                    and item['stroke']['widthPt'] == 1 and not isinstance(item['stroke']['widthPt'], bool) and isinstance(item['stroke']['color'], str) and re.fullmatch(r'#[0-9A-Fa-f]{6}', item['stroke']['color']))
                or item['kind'] == 'setTransform' and (not isinstance(item.get('box'), dict) or set(item['box']) != {'x', 'y', 'width', 'height', 'rotationDeg'}
                    or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > (360 if key == 'rotationDeg' else 100000) for key, value in item['box'].items())
                    or item['box']['width'] <= 0 or item['box']['height'] <= 0)):
                raise ValueError('native_office_operations_invalid')
            key = (item['partPath'], spid)
            normalized = dict(item)
        else:
            text, box, client_id = item.get('text'), item.get('box'), item.get('clientId')
            if (item.get('kind') != 'addTextBox' or set(item) != {'kind', 'partPath', 'clientId', 'text', 'box'}
                or not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', client_id)
                or not isinstance(text, str) or not isinstance(box, dict) or set(box) != {'x', 'y', 'width', 'height'}
                or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100000 or not math.isfinite(value) for value in box.values())
                or box['width'] == 0 or box['height'] == 0):
                raise ValueError('native_office_operations_invalid')
            size = sum(2 if ord(char) > 0xffff else 1 for char in text)
            total += size
            if (size > 20000 or total > 200000 or any(not (ord(char) in {9, 10, 13} or 0x20 <= ord(char) <= 0xd7ff or 0xe000 <= ord(char) <= 0xfffd or 0x10000 <= ord(char) <= 0x10ffff) for char in text)):
                raise ValueError('native_office_operations_invalid')
            key = ('new', client_id)
            normalized = {**item, 'text': text.replace('\r\n', '\n').replace('\r', '\n'), 'box': dict(box)}
        if key in seen:
            raise ValueError('native_office_operations_invalid')
        seen.add(key)
        result.append(normalized)
    return result
