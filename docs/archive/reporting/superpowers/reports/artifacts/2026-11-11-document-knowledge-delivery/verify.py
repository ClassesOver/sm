"""离线核对隔离技术交付证据，不把受控模型与合成数据当作业务验收。"""

import gzip
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile

from docx import Document
from lxml import etree
from pypdf import PdfReader

root = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def identity(path, expected, *, compressed=False):
    raw = path.read_bytes()
    if compressed:
        raw = gzip.decompress(raw)
    assert len(raw) == expected['size'], path
    assert hashlib.sha256(raw).hexdigest() == expected['sha256'], path


manifest = read(root / 'manifest.json')
actual = {str(path.relative_to(root)) for path in root.rglob('*') if path.is_file()
    and path != root / 'manifest.json' and '__pycache__' not in path.parts}
assert actual == {item['path'] for item in manifest}
for item in manifest:
    identity(root / item['path'], item)

for case in sorted((root / 'cases').iterdir()):
    evidence = read(case / 'evidence.json')
    index = read(case / 'native/trace-index.json')
    artifact = read(case / 'native/artifact-manifest.json')
    native = read(case / 'native/evidence.json')
    identity(case / 'native/trace-index.json', artifact['traceIndex'])
    identity(case / 'native/report.md', artifact['markdown'])
    assert index['revision'] == artifact['revision']
    assert index['reportBasisId'] == artifact['reportBasisId'] == evidence['basis']['id']
    ref, = evidence['knowledgeRefs']
    assert ref['documentId'] == 'known-context' and ref['documentRevision'] == 1
    for document_id, original in evidence['registeredOriginals'].items():
        path = case / (document_id + '.txt')
        identity(path, original)
        registration, = original['registration']['revisions']
        assert registration['originalHash'] == original['sha256']
        assert registration['sizeBytes'] == original['size']
        assert registration['reviewStatus'] == 'approved' and registration['ingestionStatus'] == 'ready'
    early = (case / 'known-context.txt').read_text()
    late = (case / 'later-context.txt').read_text()
    assert hashlib.sha256(early.encode()).hexdigest() == ref['sourceHash'] == ref['quoteSha256']
    assert evidence['knowledgeDetail']['quote'] == early and evidence['knowledgeDetail']['available'] is True
    assert late not in json.dumps(evidence['modelInputs'], ensure_ascii=False)
    for file in index['files']:
        candidates = [case / 'registered-inputs' / (file['resourceId'] + '.bin.gz'),
            case / 'native' / (file['resourceId'] + '.json')]
        if file['resourceId'] == index['markdownFileResourceId']:
            candidates.append(case / 'native/report.md')
        available = next((path for path in candidates if path.is_file()), None)
        if available:
            identity(available, file, compressed=available.suffix == '.gz')
        if evidence['initialPipeline']:
            assert available is not None, file
    for file in native['files']:
        identity(case / 'native' / file['file'], file)
        identity(case / 'browser' / ('historical.' + file['file'].rsplit('.', 1)[1]), file)
        if evidence['initialPipeline']:
            assert f'/revision-{index["revision"]}/' in file['path']
    pdf = PdfReader(case / 'native/c02-corrected.pdf')
    word = Document(case / 'native/c02-corrected.docx')
    texts = ['\n'.join(page.extract_text() or '' for page in pdf.pages),
        '\n'.join(paragraph.text for paragraph in word.paragraphs)]
    assert all(late not in text for text in texts)
    validation = evidence['deliveryValidation']
    if evidence['knowledgeProjectionFailure']:
        assert validation['ok'] is False
        assert any(item['code'] == 'knowledge_source_projection_unavailable' for item in validation['issues'])
        assert all('业务知识来源' not in text for text in texts)
    elif evidence['projectionFailure']:
        assert validation['ok'] is False
        assert any(item['code'] == 'claim_support_projection_unavailable' for item in validation['issues'])
        assert all('解释与建议的支持状态未能核验' in re.sub(r'\s+', '', text) for text in texts)
    else:
        for text in texts:
            compact = re.sub(r'\s+', '', text)
            for expected in ['业务知识来源', '登记引用：known-context（第1版）', '原件第1–1行',
                early, '原文可访问不等于解释已获支持']:
                assert expected in compact, (case.name, expected)
        title = next(item for item in word.paragraphs if item.text == '业务知识来源')
        assert title.style.name == 'Report Source Appendix' and title.paragraph_format.page_break_before is True
        expected_url = (f'https://reports.test/reports/v1/editor/{quote(index["reportId"], safe="")}/'
            f'{index["revision"]}?subject={evidence["subjectId"]}')
        pdf_urls = [annot.get_object().get('/A', {}).get('/URI')
            for page in pdf.pages for annot in page.get('/Annots', [])]
        assert expected_url in pdf_urls
        with ZipFile(case / 'native/c02-corrected.docx') as package:
            relationships = etree.fromstring(package.read('word/_rels/document.xml.rels'))
            assert expected_url in [item.attrib.get('Target') for item in relationships]
    browser = read(case / 'browser/browser-evidence.json')
    assert browser['writes'] == 0 and browser['errors'] == []
    assert {item['width'] for item in browser['viewports']} == {1440, 1280, 768, 390}
    assert all(item['seriousOrCritical'] == [] for item in browser['viewports'])
    assert browser['knowledge']['keyboardToggleVerified'] and browser['knowledge']['quote'] == early
    assert {item['format'] for item in browser['downloads']} == {'pdf', 'docx'}
    assert all(item['status'] == 200 for item in browser['downloads'])
    assert native['businessApproval'] == 'not_performed'

for variant in ['initial', 'recalculation']:
    assert len(list((root / 'visual' / variant / 'pdf').glob('page-*.png'))) == 6
    assert len(list((root / 'visual' / variant / 'word').glob('page-*.png'))) == 5

for name, expected in [('initial-knowledge-final-http', '5 passed'),
    ('initial-knowledge-revision-final-http', '2 passed'), ('initial-knowledge-revision-path-green', '20 passed'),
    ('initial-knowledge-nonblocking', '130 passed'), ('initial-knowledge-shared-regression', '31 passed'),
    ('initial-knowledge-unit-red', '5 failed'), ('initial-knowledge-revision-path-red', 'assert 2 == 1')]:
    content = gzip.decompress((root / 'logs' / (name + '.log.gz')).read_bytes()).decode()
    assert expected in content, name
assert read(root / 'environment.json')['businessApproval'] == 'not_performed'
print(f'{len(manifest)}文件身份、五组原件登记与下载、精确修订链接、两格式知识附录及日志通过；非真实业务验收。')
