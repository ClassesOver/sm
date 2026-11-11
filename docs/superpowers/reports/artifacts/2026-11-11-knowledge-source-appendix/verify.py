"""离线检查分层技术证据；不将合成知识摘录当作业务原件。"""

import gzip
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
render = read(rendered / 'render.json')['render']
for label, name in [('markdown', 'source.md'), ('pdf', 'knowledge.pdf'), ('word', 'knowledge.docx')]:
    identity(rendered / name, render[label])
assert render['knowledgeSourceAppendixPresent'] is True
assert render['traceSourceAppendixPresent'] is False
pdf = PdfReader(rendered / 'knowledge.pdf')
word = Document(rendered / 'knowledge.docx')
texts = ['\n'.join(page.extract_text() or '' for page in pdf.pages),
    '\n'.join(paragraph.text for paragraph in word.paragraphs)]
for content in texts:
    compact = re.sub(r'\s+', '', content)
    for expected in ['业务知识来源', '预算制度（第1版）', '原件第1–1行',
        '预算按原始金额累计，不取期间平均。', '原文可访问不等于解释已获支持', '待核实']:
        assert expected in compact, expected
title = next(item for item in word.paragraphs if item.text == '业务知识来源')
assert title.style.name == 'Report Source Appendix'
assert title.paragraph_format.page_break_before is True
assert len(pdf.pages) == len(PdfReader(rendered / 'word-pages/knowledge.pdf').pages) == 2

for name, expected in [('knowledge-source-final-related', '86 passed'),
    ('knowledge-source-final-http', '6 passed'), ('knowledge-source-nonblocking', '76 passed, 1 skipped'),
    ('knowledge-source-actual-visibility', '1 passed'), ('knowledge-source-appendix-red', '4 failed'),
    ('knowledge-source-visibility-red', '3 failed')]:
    content = gzip.decompress((root / 'logs' / (name + '.log.gz')).read_bytes()).decode('utf-8')
    assert expected in content, name
assert read(root / 'environment.json')['businessApproval'] == 'not_performed'
print(f'{len(manifest)}文件与原生成品身份、知识摘录/Word样式/日志核对通过；真实业务验收未执行。')
