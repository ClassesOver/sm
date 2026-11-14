"""普通Home列表的默认定义/未使用源定义，经真实原生writer独立回读。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def source():
    doc = Document()
    doc.add_paragraph('保留原文字').runs[0].bold = True
    doc.add_paragraph('第二段')
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def op(block, binding, kind='ordered', level=0):
    return {'kind': 'setParagraphNumberingValue', 'blockId': block['blockId'],
            'expectedObjectSha256': block['expectedObjectSha256'], 'binding': binding,
            'listKind': kind, 'ilvl': level}


@pytest.mark.parametrize('kind', ['ordered', 'bullet'])
def test_home_default_and_restart_share_same_new_native_abstract(kind):
    original = source()
    blocks = inspect_docx(original)['blocks']
    base = {'id': 'home-list', 'defaultNumbering': {'id': 'home-base', 'kind': kind}}
    result = patch_docx(original, [op(blocks[0], base, kind),
        op(blocks[1], {**base, 'id': 'restart', 'startOverrides': {'0': 9}}, kind)])
    with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(result)) as after:
        body = etree.fromstring(after.read('word/document.xml'))
        nums = etree.fromstring(after.read('word/numbering.xml'))
        ids = body.xpath('/w:document/w:body/w:p/w:pPr/w:numPr/w:numId/@w:val', namespaces=NS)
        assert len(ids) == 2 and ids[0] != ids[1]
        abstracts = [nums.xpath(f'string(w:num[@w:numId="{num}"]/w:abstractNumId/@w:val)', namespaces=NS) for num in ids]
        assert abstracts[0] == abstracts[1] and not abstracts[0].startswith('pending-')
        levels = nums.xpath(f'w:abstractNum[@w:abstractNumId="{abstracts[0]}"]/w:lvl', namespaces=NS)
        assert len(levels) == 5
        assert {n.xpath('string(w:numFmt/@w:val)', namespaces=NS) for n in levels} == {'bullet' if kind == 'bullet' else 'decimal'}
        assert nums.xpath(f'w:num[@w:numId="{ids[1]}"]/w:lvlOverride/w:startOverride/@w:val', namespaces=NS) == ['9']
        for name in before.namelist():
            if name not in {'word/document.xml', 'word/numbering.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name
    doc = Document(BytesIO(result))
    assert [p.text for p in doc.paragraphs] == ['保留原文字', '第二段']
    assert doc.paragraphs[0].runs[0].bold is True


def test_home_can_restart_a_definition_not_used_by_body_without_copying_abstract():
    original = source()
    blocks = inspect_docx(original)['blocks']
    with ZipFile(BytesIO(original)) as z:
        nums = etree.fromstring(z.read('word/numbering.xml'))
        num_id = nums.xpath('w:num[w:abstractNumId/@w:val="7"]/@w:numId', namespaces=NS)[0]
    result = patch_docx(original, [op(blocks[0], {'id': 'unused', 'sourceNumId': num_id, 'startOverrides': {'0': 1}}, 'ordered')])
    with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(result)) as after:
        old = etree.fromstring(before.read('word/numbering.xml'))
        new = etree.fromstring(after.read('word/numbering.xml'))
        assert len(new.xpath('w:abstractNum', namespaces=NS)) == len(old.xpath('w:abstractNum', namespaces=NS))
        identity = etree.fromstring(after.read('word/document.xml')).xpath('string(/w:document/w:body/w:p[1]/w:pPr/w:numPr/w:numId/@w:val)', namespaces=NS)
        assert identity != num_id
        assert new.xpath(f'string(w:num[@w:numId="{identity}"]/w:abstractNumId/@w:val)', namespaces=NS) == '7'


@pytest.mark.parametrize('patch', [
    {'listKind': 'bullet'}, {'ilvl': 5},
    {'binding': {'id': 'bad', 'defaultNumbering': {'id': 'a', 'kind': 'invalid'}}},
    {'binding': {'id': 'bad', 'sourceNumId': '1', 'defaultNumbering': {'id': 'a', 'kind': 'ordered'}}},
])
def test_home_default_rejects_forged_kind_out_of_range_and_mixed_definition(patch):
    original = source()
    block = inspect_docx(original)['blocks'][0]
    operation = op(block, {'id': 'home', 'defaultNumbering': {'id': 'home', 'kind': 'ordered'}})
    with pytest.raises(ValueError):
        patch_docx(original, [{**operation, **patch}])


def test_home_default_identity_cannot_change_kind_in_same_batch():
    original = source()
    blocks = inspect_docx(original)['blocks']
    with pytest.raises(ValueError, match='list_definition_conflict'):
        patch_docx(original, [op(blocks[0], {'id': 'first', 'defaultNumbering': {'id': 'same', 'kind': 'ordered'}}),
            op(blocks[1], {'id': 'second', 'defaultNumbering': {'id': 'same', 'kind': 'bullet'}}, 'bullet')])
