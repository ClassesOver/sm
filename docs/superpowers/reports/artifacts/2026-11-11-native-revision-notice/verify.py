"""离线核对实际原生修订说明、登记身份与受影响验证记录。"""

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook
from pptx import Presentation

root = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def identity(path, expected):
    raw = path.read_bytes()
    assert len(raw) == expected['size'], path
    assert hashlib.sha256(raw).hexdigest() == expected['sha256'], path


manifest = read(root / 'manifest.json')
actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()
    and p != root / 'manifest.json' and '__pycache__' not in p.parts}
assert actual == {item['path'] for item in manifest}
for item in manifest:
    identity(root / item['path'], item)

for case in ['xlsx-edit', 'xlsx-unchanged', 'pptx']:
    folder = root / case
    parent = folder / 'parent'
    context = read(parent / 'context.json')
    artifact = read(parent / 'artifact-manifest.json')
    identity(parent / 'artifact-manifest.json', context['artifactManifest'])
    identity(parent / 'trace-index.json', artifact['traceIndex'])
    index = read(parent / 'trace-index.json')
    assert context['revision'] == artifact['revision'] == index['revision']
    for file in index['files']:
        identity(parent / 'registered-files' / file['resourceId'], file)
    evidence = read(parent / 'evidence.json')
    assert evidence['businessApproval'] == 'not_performed'
    for file in evidence['files']:
        identity(parent / file['file'], file)
    result = read(folder / 'result.json')
    assert result['revision'] == context['revision'] + 1
    assert result['reportId'] == context['reportId']
    assert result['validation']['ok'] is False
    codes = {item['code'] for item in result['validation']['issues']}
    assert not {'workbook_revision_notice_unavailable', 'pptx_revision_notice_unavailable'} & codes
    current = read(folder / 'current-after-withdrawal.json')
    supports = [item for item in current['quality']['claimSupport'] if item['kind'] == 'recommendation']
    assert supports and all(item['supportStatus'] == 'unverified' and not item['evidenceRefs'] for item in supports)
    if case.startswith('xlsx'):
        identity(folder / 'edited.xlsx', result['xlsx'])
        assert 'workbook_semantic_verification_pending' in codes
        book = load_workbook(folder / 'edited.xlsx')
        original = load_workbook(parent / 'c02-corrected.xlsx')
        try:
            assert len(book.worksheets) == len(original.worksheets) + 1
            assert book.worksheets[0]['A1'].value == '本修订待核验'
            assert '尚未重新核验' in book.worksheets[0]['A6'].value
            assert f'第 {result["revision"]} 版' in book.worksheets[0]['A3'].value
            assert book.active == book.worksheets[0]
            assert book['汇总']['A1'].value == ('预算执行报告 人工复核' if case == 'xlsx-edit' else original['汇总']['A1'].value)
        finally:
            book.close()
            original.close()
        with ZipFile(folder / 'edited.xlsx') as package:
            mapping = json.loads(package.read('smart-reporting/source-mapping.json'))
            assert len([p for p in package.namelist() if p == 'xl/worksheets/srRevisionNotice.xml']) == 1
        assert mapping == read(folder / 'edited-source-mapping.json')
        assert mapping['sources']['claims'] and all(item['support']['supportStatus'] == 'unverified'
            and not item['support']['evidenceRefs'] for item in mapping['sources']['claims'])
    else:
        identity(folder / 'edited.pptx', result['pptx'])
        assert 'pptx_semantic_verification_pending' in codes
        deck = Presentation(folder / 'edited.pptx')
        original = Presentation(parent / 'c02-corrected.pptx')
        assert len(deck.slides) == len(original.slides) + 1
        assert deck.slide_width == original.slide_width and deck.slide_height == original.slide_height
        text = '\n'.join(shape.text for shape in deck.slides[0].shapes if shape.has_text_frame)
        assert '本修订待核验' in text and '尚未重新核验' in text
        assert f'第 {result["revision"]} 版' in text
        body = '\n'.join(shape.text for slide in list(deck.slides)[1:] for shape in slide.shapes if shape.has_text_frame)
        assert '预算执行报告 人工复核' in body and '70.00%' in body
        with ZipFile(folder / 'edited.pptx') as package:
            assert len([p for p in package.namelist() if p == 'ppt/slides/srRevisionNotice.xml']) == 1
        new = read(folder / 'new-context.json')
        assert new['revision'] == result['revision'] and new['pptxSha256'] == result['pptx']['sha256']

for name, expected in [('affected', '40 passed'), ('integration', '3 passed, 1 deselected'),
    ('nonblocking', '93 passed, 2 deselected'), ('preservation', '2 passed')]:
    content = (root / 'logs' / f'native-revision-notice-{name}.log').read_text()
    assert expected in content
    if name == 'integration':
        assert 'isolated_vector_database_cleanup=True' in content
assert '1 failed, 3 deselected' in (root / 'logs/native-revision-notice-integration-red.log').read_text()
visual = read(root / 'visual-review.json')
assert visual['completeSemanticReverification'] is False
assert sum(visual['pageCounts'].values()) == 15
for case, count in visual['pageCounts'].items():
    assert len(list((root / 'visual' / case).glob('page-*.png'))) == count
repository = root.parents[4]
for snapshot in (root / 'source').rglob('*.py'):
    assert snapshot.read_bytes() == (repository / snapshot.relative_to(root / 'source')).read_bytes()
print(f'verified {len(manifest)} files: 3 native editor deliveries with visible pending revision notices; not semantic reapproval')
