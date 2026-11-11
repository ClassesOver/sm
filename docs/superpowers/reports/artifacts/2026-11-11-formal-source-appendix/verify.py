"""离线检查归档字节身份与正式来源附录，不调用数据库或模型。"""

import hashlib
import json
import re
from pathlib import Path

from docx import Document
from pypdf import PdfReader

root = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def identity(path, expected):
    raw = path.read_bytes()
    assert len(raw) == expected['size'], path
    assert hashlib.sha256(raw).hexdigest() == expected['sha256'], path


manifest = read(root / 'manifest.json')
actual = {str(path.relative_to(root)) for path in root.rglob('*') if path.is_file()
    and path != root / 'manifest.json' and '__pycache__' not in path.parts}
assert actual == {item['path'] for item in manifest}
for item in manifest:
    identity(root / item['path'], item)

rendered = root / 'rendered'
index = read(rendered / 'index.json')
for item in index['files']:
    identity(rendered / 'registered' / item['path'], item)
render = read(rendered / 'render.json')['render']
for label, name in [('markdown', 'source.md'), ('pdf', 'formal.pdf'), ('word', 'formal.docx')]:
    identity(rendered / name, render[label])

pdf = PdfReader(rendered / 'formal.pdf')
word = Document(rendered / 'formal.docx')
texts = ['\n'.join(page.extract_text() or '' for page in pdf.pages),
    '\n'.join(paragraph.text for paragraph in word.paragraphs)]
for content in texts:
    content = re.sub(r'\s+', '', content)
    for expected in ['数据来源附录', '预算额（第1版）', '合成预算执行（第1版）',
        '300.123456789123456789CNY', '2026-11-01', '2026-12-01', '含起日、不含止日',
        '数据完整性与更新状态尚未核实', '登记结果不等于业务核验通过']:
        assert expected in content, expected
assert len(pdf.pages) == 2
assert len(PdfReader(rendered / 'word-pages/formal.pdf').pages) == 2
for name, expected in [('formal-source-http-fault-4.log', '1 passed'),
    ('formal-source-related.log', '80 passed'),
    ('formal-source-nonblocking.log', '76 passed, 1 skipped'),
    ('formal-source-long-green.log', '5 passed')]:
    assert expected in (root / 'logs' / name).read_text(encoding='utf-8')
assert read(root / 'environment.json')['businessAcceptance'] == 'not_performed'
print(f'归档 {len(manifest)} 文件、登记源与渲染身份、两格式附录及故障日志核对通过；业务验收未执行。')
