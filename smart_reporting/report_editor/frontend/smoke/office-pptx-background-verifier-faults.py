"""只读原保存产物，证明背景文件校验器能拒绝具体损坏。"""
import importlib.util
import json
import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree


directory = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location('background_fixture', Path(__file__).with_name('office-pptx-background-fixture.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
assert fixture.run({'mode': 'verify', 'directory': str(directory)})['ok']
actual = directory / 'downloaded.pptx'
before = sha256(actual.read_bytes()).hexdigest()
with ZipFile(actual) as archive:
    original = {name: archive.read(name) for name in archive.namelist()}
ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'rel': 'http://schemas.openxmlformats.org/package/2006/relationships'}
faults = []


def reject(name, part, mutation=None, replacement=None):
    parts = dict(original)
    if replacement is None:
        root = etree.fromstring(parts[part])
        mutation(root)
        parts[part] = etree.tostring(root)
    else:
        parts[part] = replacement
    path = directory / f'{name}-fault.pptx'
    assert not path.exists()
    try:
        with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
            for filename, data in parts.items():
                archive.writestr(filename, data)
        try:
            fixture.run({'mode': 'verify', 'directory': str(directory), 'file': str(path)})
        except AssertionError as error:
            faults.append({'fault': name, 'rejected': True, 'reason': str(error)[:300]})
        else:
            raise AssertionError('校验器漏检 ' + name)
    finally:
        path.unlink()


reject('image-mode', 'ppt/slides/slide1.xml', lambda r: setattr(r.find('.//p:bg//a:tile', ns), 'tag', '{'+ns['a']+'}stretch'))
reject('gradient-color', 'ppt/slides/slide2.xml', lambda r: r.find('.//p:bg//a:srgbClr', ns).set('val', '000000'))
reject('gradient-angle', 'ppt/slides/slide2.xml', lambda r: r.find('.//p:bg//a:lin', ns).set('ang', '0'))
with ZipFile(directory / 'revision-1.pptx') as archive:
    source_bg = etree.fromstring(archive.read('ppt/slides/slide3.xml')).find('p:cSld/p:bg', ns)
reject('reset-background', 'ppt/slides/slide3.xml', lambda r: r.find('p:cSld', ns).insert(0, deepcopy(source_bg)))
reject('graphics', 'ppt/slides/slide1.xml', lambda r: r.set('showMasterSp', '1'))
reject('foreground-text', 'ppt/slides/slide1.xml', lambda r: setattr(r.find('.//a:t', ns), 'text', 'changed'))
reject('foreground-geometry', 'ppt/slides/slide1.xml', lambda r: r.find('.//a:xfrm/a:off', ns).set('x', '999'))
reject('notes', 'ppt/notesSlides/notesSlide1.xml', lambda r: setattr(r.find('.//a:t', ns), 'text', 'changed'))
reject('hyperlink', 'ppt/slides/_rels/slide1.xml.rels', lambda r: next(n for n in r if n.get('Type', '').endswith('/hyperlink')).set('Target', 'https://example.invalid/changed'))
reject('background-bytes', 'ppt/media/image2.png', replacement=original['ppt/media/image1.png'])
assert len(faults) == 10
assert sha256(actual.read_bytes()).hexdigest() == before
result = {'positiveControl': True, 'faults': faults, 'savedArtifactUnchanged': True,
          'outputSha256': before, 'verifierSha256': sha256(Path(spec.origin).read_bytes()).hexdigest()}
(directory / 'verifier-faults.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'positiveControl': True, 'faultsRejected': len(faults), 'savedArtifactUnchanged': True}))
