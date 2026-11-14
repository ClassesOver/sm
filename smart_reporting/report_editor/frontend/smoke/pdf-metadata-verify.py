"""独立进程以 pypdf 回读已下载 PDF，不复用写入器或运行时 inspector。"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

root = Path(sys.argv[1])
evidence = json.loads((root / 'evidence.json').read_text())
data = (root / 'downloaded.pdf').read_bytes()
reader = PdfReader(root / 'downloaded.pdf')
source = PdfReader(root / 'source.pdf')
assert hashlib.sha256(data).hexdigest() == evidence['saved']['artifacts']['pdf']['sha256']
assert len(data) == evidence['saved']['artifacts']['pdf']['size']
operation = next(op for op in evidence['staged'] if op['kind'] == 'setMetadata')
expected = operation['metadata']
assert reader.metadata.title == expected['title']
assert reader.metadata.author == expected['author']
assert reader.metadata.subject == expected['subject'] == ''
assert reader.metadata.keywords == 'alpha beta 中文 gamma'
assert reader.metadata.modification_date.astimezone(timezone.utc) == datetime.fromtimestamp(operation['modifiedMs'] // 1000, timezone.utc)
for key in ['/Creator', '/Producer', '/CreationDate', '/CustomAudit']:
    assert reader.metadata[key] == source.metadata[key]
assert len(reader.pages) == 2
assert [p.extract_text().strip() for p in reader.pages] == ['Original metadata page 2', 'Original metadata page 1']
assert reader.pages[0].rotation == 90
assert reader.outline[0].title == 'Preserved source bookmark'
assert reader.get_destination_page_number(reader.outline[0]) == 1
assert reader.attachments['evidence.txt'] == [b'Preserved source attachment']
assert hashlib.sha256((root / 'source.pdf').read_bytes()).hexdigest() == evidence['sourceSha256']
result = {'ok': True, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data),
          'metadata': {k: str(v) for k, v in reader.metadata.items()},
          'pageText': [p.extract_text().strip() for p in reader.pages],
          'rotations': [p.rotation for p in reader.pages], 'bookmarkPreserved': True,
          'attachmentPreserved': True, 'sourceUnchanged': True}
(root / 'independent-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False))
