"""独立 pypdf 回读下载的 Bates 正文、页目标及原内容；不调用写入器。"""
import hashlib
import json
import sys
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import ContentStream

root = Path(sys.argv[1])
evidence = json.loads((root / 'evidence.json').read_text())
content = (root / 'downloaded.pdf').read_bytes()
reader = PdfReader(root / 'downloaded.pdf')
texts = [page.extract_text() for page in reader.pages]
assert len(reader.pages) == 4
assert 'CASE-000043' in texts[0] and 'Original' not in texts[0]
assert 'CASE-000041' in texts[1] and 'Original page 2' in texts[1]
assert 'Original page 3' in texts[2] and 'CASE-' not in texts[2]
assert 'CASE-' not in texts[3] and 'Original' not in texts[3]
assert all('CASE-000042' not in text and 'Original page 1' not in text for text in texts)
assert [page.rotation for page in reader.pages] == [0, 180, 0, 0]
assert reader.metadata.title == 'Preserved Bates source'
assert hashlib.sha256(content).hexdigest() == evidence['saved']['artifacts']['pdf']['sha256']
assert len(content) == evidence['saved']['artifacts']['pdf']['size']
matrices = []
for index, page in enumerate(reader.pages):
    found = []

    def visitor(text, cm, tm, font, size):
        if 'CASE-' in text:
            found.append({'text': text.strip(), 'cm': list(cm), 'tm': list(tm), 'fontSize': float(size)})

    page.extract_text(visitor_text=visitor)
    matrices.append(found)
    resources = page.get('/Resources', {})
    for obj in resources.get('/XObject', {}).values():
        assert obj.get_object().get('/Subtype') != '/Image', 'Bates must be real searchable text, not a page-number bitmap'
    if index in (0, 1):
        assert len(found) == 1 and abs(found[0]['fontSize'] - 12) < .01
        entry_index = 2 if index == 0 else 0
        entry = next(op for op in evidence['staged'] if op['kind'] == 'addBates')['entries'][entry_index]
        assert entry['origin'] == ([150, 360] if index == 0 else [50, 200])
        assert entry['rotate'] == (0 if index == 0 else 90)
        expected_origin = [150 + entry['lineXOffsets'][0], 360] if index == 0 else [50, 200 + entry['lineXOffsets'][0]]
        assert all(abs(actual - expected) < .001 for actual, expected in zip(found[0]['cm'][4:6], expected_origin))
        assert found[0]['tm'][:4] == ([1, 0, 0, 1] if index == 0 else [0, 1, -1, 0])
        colors = [list(map(float, args)) for args, op in ContentStream(page.get_contents(), reader).operations if op == b'rg']
        assert any(all(abs(a-b) < .001 for a, b in zip(color, [43/255, .4, 1])) for color in colors), colors
result = {'ok': True, 'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content),
          'pageCount': len(reader.pages), 'texts': texts, 'rotations': [page.rotation for page in reader.pages],
          'nativeTextMatrices': matrices, 'title': reader.metadata.title, 'batesIsSearchableTextNotBitmap': True}
(root / 'independent-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False))
