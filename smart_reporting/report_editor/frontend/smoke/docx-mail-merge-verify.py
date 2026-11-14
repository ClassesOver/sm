"""独立回读真实下载的字段修订和多记录合并文件，不调用编辑桥。"""
import argparse
import hashlib
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from lxml import etree

parser = argparse.ArgumentParser()
parser.add_argument('--directory', type=Path, required=True)
args = parser.parse_args()
field = (args.directory / 'field-saved.docx').read_bytes()
merged = (args.directory / 'merged.docx').read_bytes()
with ZipFile(BytesIO(field)) as source, ZipFile(BytesIO(merged)) as output:
    before = source.read('word/document.xml')
    after = output.read('word/document.xml')
    assert b'MERGEFIELD' in before
    assert b'MERGEFIELD' not in after and b'fldChar' not in after
    for name in output.namelist():
        if name.endswith(('.xml', '.rels')):
            etree.fromstring(output.read(name))
    assert source.read('word/header1.xml') == output.read('word/header1.xml')
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    xml = etree.fromstring(after)
    assert len(xml.xpath('.//w:body/w:sectPr', namespaces=ns)) == 1
    assert len(xml.xpath('.//w:body/w:p/w:r/w:br[@w:type="page"]', namespaces=ns)) == 1
paragraphs = [p.text for p in Document(BytesIO(merged)).paragraphs]
assert paragraphs == ['Dear Ada,', 'Retained body', '', 'Dear Grace,', 'Retained body']
result = {'fieldSha256': hashlib.sha256(field).hexdigest(), 'mergedSha256': hashlib.sha256(merged).hexdigest(),
          'paragraphs': paragraphs, 'mergeFieldFlattened': True, 'headerPreserved': True,
          'allXmlValid': True, 'oneBodyPageBreak': True}
for name, digest in [('field-save.json', result['fieldSha256']), ('merge-save.json', result['mergedSha256'])]:
    assert json.loads((args.directory / name).read_text())['result']['artifacts']['word']['sha256'] == digest
(args.directory / 'independent-read.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False))
