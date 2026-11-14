"""独立ZIP/OOXML核对新增、修改、移除链接；不调用产品检查器计算预期。"""
import json
import sys
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'
CP = 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties'
DC = 'http://purl.org/dc/terms/'
XML = 'http://www.w3.org/XML/1998/namespace'
NS = {'w': W, 'r': R, 'cp': CP, 'dcterms': DC}
canonical = lambda element: etree.tostring(element, method='c14n')


def verify(directory):
    directory = Path(directory)
    receipts = []
    with ZipFile(directory / 'revision-1.docx') as source:
        source_files = {name for name in source.namelist() if not name.endswith('/')}
        source_document = etree.fromstring(source.read('word/document.xml'))
        source_core = etree.fromstring(source.read('docProps/core.xml'))
        source_rels = etree.fromstring(source.read('word/_rels/document.xml.rels'))
        for revision, href, rid in [(2, 'https://example.test/report?a=1&b=2', 'rId11'), (3, 'mailto:reports@example.test', 'rId12'), (4, None, None)]:
            saved = (directory / f'revision-{revision}.docx').read_bytes()
            assert saved == (directory / f'download-{revision}.docx').read_bytes()
            with ZipFile(directory / f'download-{revision}.docx') as actual:
                assert actual.testzip() is None
                assert {name for name in actual.namelist() if not name.endswith('/')} == source_files
                changed = [name for name in source_files if source.read(name) != actual.read(name)]
                expected_parts = {'word/document.xml', 'docProps/core.xml'} | ({'word/_rels/document.xml.rels'} if href else set())
                assert set(changed) == expected_parts, (revision, changed)
                for name in source_files:
                    if name.endswith(('.xml', '.rels')):
                        etree.fromstring(actual.read(name))
                expected = deepcopy(source_document)
                paragraph = expected.find('w:body/w:p', NS)
                run = paragraph[1]
                assert ''.join(run.itertext()) == '经营收入100万元'
                style = etree.Element(f'{{{W}}}rStyle')
                style.set(f'{{{W}}}val', 'Hyperlink')
                run.find('w:rPr', NS).insert(0, style)
                run.find('w:t', NS).set(f'{{{XML}}}space', 'preserve')
                # 已知引擎只在被重建的第一段给无空白文本显式写入xml:space。
                paragraph.find('w:hyperlink/w:r/w:t', NS).set(f'{{{XML}}}space', 'preserve')
                if href:
                    link = etree.Element(f'{{{W}}}hyperlink')
                    link.set(f'{{{R}}}id', rid)
                    paragraph.replace(run, link)
                    link.append(run)
                assert canonical(expected) == canonical(etree.fromstring(actual.read('word/document.xml'))), ('document', revision)
                relationships = deepcopy(source_rels)
                if href:
                    relation = etree.SubElement(relationships, f'{{{P}}}Relationship')
                    relation.attrib.update({'Id': rid, 'Type': R + '/hyperlink', 'Target': href, 'TargetMode': 'External'})
                assert canonical(relationships) == canonical(etree.fromstring(actual.read('word/_rels/document.xml.rels'))), ('relationships', revision)
                core = etree.fromstring(actual.read('docProps/core.xml'))
                assert core.find('cp:revision', NS).text == str(revision)
                modified = core.find('dcterms:modified', NS)
                assert datetime.fromisoformat(modified.text.replace('Z', '+00:00')).tzinfo is not None
                core.find('cp:revision', NS).text = source_core.find('cp:revision', NS).text
                modified.text = source_core.find('dcterms:modified', NS).text
                assert canonical(core) == canonical(source_core), ('core', revision)
                receipts.append({'revision': revision, 'sha256': sha256(saved).hexdigest(), 'size': len(saved), 'href': href, 'changedParts': sorted(changed), 'addedEmptyDirectories': sorted(set(actual.namelist()) - set(source.namelist()))})
    result = {'ok': True, 'revisionChecks': receipts, 'untargetedPartsAndXmlPreserved': True, 'allowedNormalization': ['target-run Hyperlink character style remains after removal', 'first-paragraph non-whitespace text xml:space=preserve', 'core revision and modified timestamp']}
    (directory / 'independent-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    print(json.dumps(verify(sys.argv[1]), ensure_ascii=False))
