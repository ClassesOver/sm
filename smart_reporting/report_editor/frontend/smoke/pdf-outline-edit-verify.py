"""使用独立 pypdf 回读实际下载文件，不依赖写入器的目录解析。"""
import hashlib
import json
import sys
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import NullObject

root = Path(sys.argv[1])
evidence = json.loads((root / 'evidence.json').read_text())
path = root / 'downloaded.pdf'
content = path.read_bytes()
reader = PdfReader(path)


def walk(items):
    result = []
    for node in items:
        if isinstance(node, list):
            result[-1]['children'] = walk(node)
        else:
            result.append({'title': node.title, 'pageIndex': reader.get_destination_page_number(node),
                           'top': float(node.top) if node.top is not None and not isinstance(node.top, NullObject) else None, 'children': []})
    return result


actual = walk(reader.outline)
assert actual == [
    {'title': '修订书签', 'pageIndex': 2, 'top': 320.0, 'children': []},
    {'title': 'Second renewed', 'pageIndex': 0, 'top': None, 'children': []},
    {'title': 'Blank', 'pageIndex': 1, 'top': None, 'children': []},
], actual
assert len(reader.pages) == 3
assert reader.metadata.title == 'Preserved outline source'
assert hashlib.sha256(content).hexdigest() == evidence['saved']['artifacts']['pdf']['sha256']
assert len(content) == evidence['saved']['artifacts']['pdf']['size']
result = {'ok': True, 'path': str(path), 'sha256': hashlib.sha256(content).hexdigest(),
          'pageCount': len(reader.pages), 'outline': actual, 'title': reader.metadata.title}
(root / 'independent-verification.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
print(json.dumps(result, ensure_ascii=False))
