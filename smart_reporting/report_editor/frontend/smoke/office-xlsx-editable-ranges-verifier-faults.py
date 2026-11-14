"""只读验证独立校验器拒绝范围/权限/文件保真损坏，不创建修订。"""
import importlib.util
import json
import sys
import tempfile
from copy import copy
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from lxml import etree

directory = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('editable_fixture', Path(__file__).with_name('office-xlsx-editable-ranges-fixture.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
source, output = directory / 'source.xlsx', directory / 'downloaded.xlsx'
identity = sha256(output.read_bytes()).hexdigest()
positive = fixture.inspect(source, output)
ns = fixture.NS


def attribute(xpath, key, value):
    def mutate(root):
        nodes = root.xpath(xpath, namespaces=ns)
        assert len(nodes) == 1
        nodes[0].set(key, value)
    return mutate


def text(xpath, value):
    def mutate(root):
        nodes = root.xpath(xpath, namespaces=ns)
        assert len(nodes) == 1
        nodes[0].text = value
    return mutate


def first_text(root):
    node = next(n for n in root.iter() if n.text and n.text.strip())
    node.text = 'fault-' + node.text


sheet = 'xl/worksheets/sheet1.xml'
faults = [
    ('widened-range', sheet, attribute('m:protectedRanges/m:protectedRange[1]', 'sqref', 'A2:F9')),
    ('wrong-name', sheet, attribute('m:protectedRanges/m:protectedRange[1]', 'name', 'Wrong')),
    ('removed-range-reintroduced', sheet, attribute('m:protectedRanges/m:protectedRange[2]', 'name', 'Remove')),
    ('protection-disabled', sheet, attribute('m:sheetProtection', 'sheet', '0')),
    ('protection-permission-changed', sheet, attribute('m:sheetProtection', 'formatCells', '0')),
    ('allowed-value-corrupted', sheet, text('.//m:c[@r="B2"]/m:v', '999')),
    ('allowed-formula-corrupted', sheet, text('.//m:c[@r="E2"]/m:f', 'SUM(A2:C2)')),
    ('non-target-style', sheet, attribute('.//m:c[@r="B3"]', 's', '0')),
    ('hyperlink-target', 'xl/worksheets/_rels/sheet1.xml.rels', lambda root: next(n for n in root if n.get('Type','').endswith('/hyperlink')).set('Target','https://example.invalid/corrupted')),
    ('comment-body', 'xl/comments/comment1.xml', first_text),
    ('chart-body', 'xl/charts/chart1.xml', first_text),
    ('other-sheet-protection', 'xl/worksheets/sheet2.xml', attribute('m:sheetProtection', 'sheet', '0')),
]
rejected = []
with tempfile.TemporaryDirectory(prefix='editable-ranges-faults-', dir='/dev/shm') as temp:
    with ZipFile(output) as saved:
        for name, part, mutate in faults:
            root = etree.fromstring(saved.read(part)); before = etree.tostring(root); mutate(root)
            assert etree.tostring(root) != before, name
            path = Path(temp) / f'{name}.xlsx'
            with ZipFile(path, 'w', ZIP_DEFLATED) as damaged:
                for info in saved.infolist():
                    damaged.writestr(copy(info), etree.tostring(root) if info.filename == part else saved.read(info.filename))
            try:
                fixture.inspect(source, path)
            except Exception as error:
                rejected.append({'name':name,'part':part,'reason':f'{type(error).__name__}: {error}'})
            else:
                raise AssertionError(f'校验器漏检: {name}')
assert sha256(output.read_bytes()).hexdigest() == identity
result = {'ok':True,'positiveControl':positive['ok'],'outputSha256':identity,'rejected':rejected,'originalUnchanged':True}
(directory / 'verifier-faults.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'ok':True,'rejected':len(rejected),'originalUnchanged':True}))
