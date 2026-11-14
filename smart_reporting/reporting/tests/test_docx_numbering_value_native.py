"""设置编号值复用原生编号writer：同abstractNum、覆盖值与原包部件保全。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def fixture():
    doc = Document()
    for index, num_id in enumerate(['5', '5', '6', '6']):
        paragraph = doc.add_paragraph(f'编号段{index}')
        if index == 3:
            paragraph.runs[0].bold = True
        num = OxmlElement('w:numPr')
        level = OxmlElement('w:ilvl'); level.set(qn('w:val'), '0')
        identity = OxmlElement('w:numId'); identity.set(qn('w:val'), num_id)
        num.extend([level, identity]); paragraph._p.get_or_add_pPr().append(num)
    stream = BytesIO(); doc.save(stream)
    return stream.getvalue()


@pytest.mark.parametrize('restart', [False, True])
def test_original_num_binding_reuses_source_or_adds_start_override_on_same_abstract(restart):
    source = fixture(); blocks = inspect_docx(source)['blocks']; target = blocks[3]
    binding = {'id': 'value-one', 'sourceNumId': '5'}
    if restart:
        binding['startOverrides'] = {'0': 7}
    result = patch_docx(source, [{'kind': 'setParagraphNumberingValue', 'blockId': target['blockId'],
        'expectedObjectSha256': target['expectedObjectSha256'], 'binding': binding, 'ilvl': 0}])
    with ZipFile(BytesIO(source)) as a, ZipFile(BytesIO(result)) as b:
        before = etree.fromstring(a.read('word/numbering.xml'))
        after = etree.fromstring(b.read('word/numbering.xml'))
        body = etree.fromstring(b.read('word/document.xml'))
        ids = body.xpath('/w:document/w:body/w:p/w:pPr/w:numPr/w:numId/@w:val', namespaces=NS)
        assert ids[:3] == ['5', '5', '6']
        original_abstract = before.xpath('string(w:num[@w:numId="5"]/w:abstractNumId/@w:val)', namespaces=NS)
        assert after.xpath(f'string(w:num[@w:numId="{ids[3]}"]/w:abstractNumId/@w:val)', namespaces=NS) == original_abstract
        if restart:
            assert ids[3] != '5'
            assert after.xpath(f'w:num[@w:numId="{ids[3]}"]/w:lvlOverride[@w:ilvl="0"]/w:startOverride/@w:val', namespaces=NS) == ['7']
        else:
            assert ids[3] == '5'
            assert a.read('word/numbering.xml') == b.read('word/numbering.xml')
        for node in before:
            attr = 'abstractNumId' if etree.QName(node).localname == 'abstractNum' else 'numId'
            match = after.xpath(f'w:{etree.QName(node).localname}[@w:{attr}="{node.get(qn("w:" + attr))}"]', namespaces=NS)
            assert len(match) == 1 and etree.tostring(node, method='c14n') == etree.tostring(match[0], method='c14n')
        for name in a.namelist():
            if name not in {'word/document.xml', 'word/numbering.xml', 'docProps/core.xml'}:
                assert a.read(name) == b.read(name), name
    assert Document(BytesIO(result)).paragraphs[3].runs[0].bold is True


def test_pending_custom_restart_resolves_native_pending_abstract_identity():
    source = fixture(); blocks = inspect_docx(source)['blocks']
    custom = {'id': 'custom-base', 'levels': [{'numFmt': 'upperRoman', 'lvlText': '%1)', 'indentLeft': 720, 'hanging': 360}]}
    operations = [
        {'kind': 'setParagraphCustomList', 'definitionId': custom['id'], 'levels': custom['levels'], 'ilvl': 0},
        {'kind': 'setParagraphNumberingValue', 'binding': {'id': 'custom-restart', 'custom': custom, 'startOverrides': {'0': 4}}, 'ilvl': 0},
    ]
    for op, block in zip(operations, blocks[2:]):
        op.update(blockId=block['blockId'], expectedObjectSha256=block['expectedObjectSha256'])
    result = patch_docx(source, operations)
    with ZipFile(BytesIO(result)) as z:
        doc = etree.fromstring(z.read('word/document.xml')); nums = etree.fromstring(z.read('word/numbering.xml'))
        ids = doc.xpath('/w:document/w:body/w:p/w:pPr/w:numPr/w:numId/@w:val', namespaces=NS)[2:]
        assert ids[0] != ids[1]
        abstract = [nums.xpath(f'string(w:num[@w:numId="{identity}"]/w:abstractNumId/@w:val)', namespaces=NS) for identity in ids]
        assert abstract[0] == abstract[1] and not abstract[0].startswith('pending-')
        assert nums.xpath(f'w:num[@w:numId="{ids[1]}"]/w:lvlOverride/w:startOverride/@w:val', namespaces=NS) == ['4']


@pytest.mark.parametrize('patch', [
    {'sourceNumId': '999999'}, {'sourceNumId': '../5'}, {'startOverrides': {'9': 2}},
    {'startOverrides': {'0': 32768}}, {'startOverrides': {'0': -1}}, {'xml': '<w:num/>'},
])
def test_numbering_binding_rejects_unknown_source_and_invalid_fields(patch):
    source = fixture(); target = inspect_docx(source)['blocks'][3]
    with pytest.raises(ValueError):
        patch_docx(source, [{'kind': 'setParagraphNumberingValue', 'blockId': target['blockId'],
            'expectedObjectSha256': target['expectedObjectSha256'], 'binding': {'id': 'bad', 'sourceNumId': '5', **patch}, 'ilvl': 0}])


def test_numbering_value_rejects_character_style_as_paragraph_link():
    source = fixture(); target = inspect_docx(source)['blocks'][3]
    custom = {'id': 'bad-style', 'levels': [{'numFmt': 'decimal', 'lvlText': '%1.',
        'indentLeft': 720, 'hanging': 360, 'pStyle': 'DefaultParagraphFont'}]}
    with pytest.raises(ValueError, match='list_style_invalid'):
        patch_docx(source, [{'kind': 'setParagraphNumberingValue', 'blockId': target['blockId'],
            'expectedObjectSha256': target['expectedObjectSha256'],
            'binding': {'id': 'bad-binding', 'custom': custom, 'startOverrides': {'0': 7}}, 'ilvl': 0}])
