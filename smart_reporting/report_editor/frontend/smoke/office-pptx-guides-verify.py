"""参考线专项：使用python-pptx/ZIP/lxml独立核对唯一正文哨兵与非目标部件。"""
import hashlib
import json
import sys
from uuid import UUID
from pathlib import Path
from tempfile import TemporaryDirectory
from shutil import copyfile
from zipfile import ZipFile

from lxml import etree
from pptx import Presentation


def verify(directory):
    source, output = [directory / name for name in ['revision-1.pptx', 'downloaded.pptx']]
    before, after = Presentation(source), Presentation(output)
    assert len(before.slides) == len(after.slides) == 3
    assert (before.slide_width, before.slide_height) == (after.slide_width, after.slide_height)
    expected = '参考线专项保存哨兵 PC'
    assert after.slides[0].shapes[0].text == expected
    assert before.slides[0].shapes[0].text != expected
    for i, (old, new) in enumerate(zip(before.slides, after.slides)):
        assert old.notes_slide.notes_text_frame.text == new.notes_slide.notes_text_frame.text
        assert len(old.shapes) == len(new.shapes)
        for j, (a, b) in enumerate(zip(old.shapes, new.shapes)):
            assert (a.left, a.top, a.width, a.height) == (b.left, b.top, b.width, b.height)
            if i == 0 and j == 0:
                assert b.text_frame.paragraphs[0].runs[0].font.bold
                assert b.text_frame.paragraphs[0].runs[0].font.size == a.text_frame.paragraphs[0].runs[0].font.size
            elif a.has_text_frame:
                assert a.text == b.text
    ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}
    with ZipFile(source) as a, ZipFile(output) as b:
        assert a.testzip() is None and b.testzip() is None
        names_a = {n for n in a.namelist() if not n.endswith('/')}
        names_b = {n for n in b.namelist() if not n.endswith('/')}
        assert names_a == names_b
        changed = sorted(name for name in names_a if a.read(name) != b.read(name))
        assert changed == ['ppt/slides/slide1.xml'], changed
        original, actual = [etree.fromstring(z.read(changed[0])) for z in [a, b]]
        # 真实引擎为被编辑形状补齐creationId；只允许这一精确身份节点，不吞掉其它扩展。
        registration = actual.find('p:cSld/p:spTree/p:sp/p:nvSpPr/p:cNvPr', ns)
        old_registration = original.find('p:cSld/p:spTree/p:sp/p:nvSpPr/p:cNvPr', ns)
        a_ns = 'http://schemas.openxmlformats.org/drawingml/2006/main'
        a16_ns = 'http://schemas.microsoft.com/office/drawing/2014/main'
        ext_list = registration.find('{'+a_ns+'}extLst')
        assert old_registration.find('{'+a_ns+'}extLst') is None
        assert ext_list is not None and len(ext_list) == 1
        extension = ext_list[0]
        assert extension.tag == '{'+a_ns+'}ext' and extension.attrib == {'uri': '{FF2B5EF4-FFF2-40B4-BE49-F238E27FC236}'}
        assert len(extension) == 1 and extension[0].tag == '{'+a16_ns+'}creationId'
        assert set(extension[0].attrib) == {'id'}
        UUID(extension[0].get('id').strip('{}'))
        registration.remove(ext_list)
        for root in [original, actual]:
            target = root.find('p:cSld/p:spTree/p:sp/p:txBody', ns)
            assert target is not None
            target.getparent().remove(target)
        assert etree.tostring(original, method='c14n') == etree.tostring(actual, method='c14n'), '目标正文之外的幻灯片结构变化'
    return {'ok': True, 'changedParts': changed, 'onlyTargetTextAndCreationRegistrationChanged': True,
            'notesLinksGeometryImagesAndOtherPartsPreserved': True,
            'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'outputSha256': hashlib.sha256(output.read_bytes()).hexdigest()}


def fault_check(directory):
    rejected = []
    for fault in ['foreign_hyperlink', 'unexpected_registration', 'foreign_image']:
        with TemporaryDirectory(prefix='pptx-guides-verifier-') as temporary:
            case = Path(temporary)
            copyfile(directory / 'revision-1.pptx', case / 'revision-1.pptx')
            with ZipFile(directory / 'downloaded.pptx') as original, ZipFile(case / 'downloaded.pptx', 'w') as output:
                media = next(name for name in original.namelist() if name.startswith('ppt/media/') and not name.endswith('/'))
                for entry in original.infolist():
                    data = original.read(entry.filename)
                    if entry.filename == media and fault == 'foreign_image':
                        data += b'unrelated mutation'
                    if entry.filename == 'ppt/slides/slide1.xml' and fault != 'foreign_image':
                        root = etree.fromstring(data)
                        if fault == 'foreign_hyperlink':
                            link = root.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}hlinkClick')
                            link.set('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id', 'forged')
                        else:
                            registration = root.find('.//{http://schemas.openxmlformats.org/drawingml/2006/main}extLst')
                            etree.SubElement(registration, '{http://schemas.openxmlformats.org/drawingml/2006/main}ext', uri='unrelated-extension')
                        data = etree.tostring(root)
                    output.writestr(entry, data)
            try:
                verify(case)
            except AssertionError:
                rejected.append(fault)
            else:
                raise AssertionError('独立核验没有拒绝非目标变更：' + fault)
    return rejected


if __name__ == '__main__':
    directory = Path(sys.argv[1])
    result = verify(directory)
    result['rejectedFaults'] = fault_check(directory)
    (directory / 'independent-fidelity.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))
