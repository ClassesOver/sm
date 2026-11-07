"""Range hyperlinks verified independently with python-docx relationships and ZIP parts."""
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import RGBColor

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def saved(document):
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def add_link(paragraph, text='旧链接', href='https://old.example/a', **attributes):
    link = OxmlElement('w:hyperlink')
    link.set(qn('r:id'), paragraph.part.relate_to(href, RT.HYPERLINK, is_external=True))
    for key, value in attributes.items():
        link.set(qn('w:' + key), value)
    run = OxmlElement('w:r')
    props = OxmlElement('w:rPr')
    bold = OxmlElement('w:b')
    props.append(bold)
    run.append(props)
    token = OxmlElement('w:t')
    token.text = text
    run.append(token)
    link.append(run)
    paragraph._p.append(link)


@pytest.fixture
def source():
    document = Document()
    document.sections[0].header.paragraphs[0].text = '保留页眉'
    document.sections[0].footer.paragraphs[0].text = '保留页脚'
    paragraph = document.add_paragraph()
    paragraph.add_run('前😀').bold = True
    run = paragraph.add_run('中段')
    run.italic = True
    run.font.color.rgb = RGBColor.from_string('123456')
    paragraph.add_run('尾').underline = True
    other = document.add_paragraph('未改')
    add_link(other, tooltip='保留提示')
    return saved(document)


def op(block, **values):
    return dict(kind='setParagraphLink', blockId=block['blockId'],
                expectedObjectSha256=block['expectedObjectSha256'], **values)


def runs(document, index=0):
    """Read nested runs without asking our bridge to interpret its own output."""
    result = []
    paragraph = document.paragraphs[index]
    for run in paragraph._p.xpath('.//w:r'):
        parent = run.getparent()
        linked = parent.tag == qn('w:hyperlink')
        relationship = document.part.rels[parent.get(qn('r:id'))] if linked else None
        result.append((
            ''.join(run.xpath('./w:t/text()')),
            relationship.target_ref if linked else None,
            bool(run.xpath('./w:rPr/w:b')), bool(run.xpath('./w:rPr/w:i')),
            bool(run.xpath('./w:rPr/w:u')),
            run.xpath('./w:rPr/w:color/@w:val'),
        ))
        if linked:
            assert relationship.reltype == RT.HYPERLINK
            assert relationship.is_external
    return result


def test_utf16_range_links_preserve_styles_source_and_unrelated_parts(source):
    original_hash = sha256(source).hexdigest()
    model = inspect_docx(source)
    target = model['blocks'][0]
    assert target['links'] == []
    assert model['blocks'][1]['links'] == [{'from': 2, 'to': 5, 'href': 'https://old.example/a'}]
    assert model['blocks'][1]['editable'] is True
    result = patch_docx(source, [op(target, **{'from': 1, 'to': 5, 'href': 'https://new.example/q?a=1&b=2'})])
    document = Document(BytesIO(result))
    assert runs(document) == [
        ('前', None, True, False, False, []),
        ('😀', 'https://new.example/q?a=1&b=2', True, False, False, []),
        ('中段', 'https://new.example/q?a=1&b=2', False, True, False, ['123456']),
        ('尾', None, False, False, True, []),
    ]
    original = Document(BytesIO(source))
    assert document.paragraphs[1]._p.xml == original.paragraphs[1]._p.xml
    assert sha256(source).hexdigest() == original_hash == model['sourceSha256']
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'word/_rels/document.xml.rels', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name
    assert inspect_docx(result)['blocks'][0]['links'] == [{'from': 1, 'to': 5, 'href': 'https://new.example/q?a=1&b=2'}]
    assert patch_docx(source, []) == source


def test_existing_link_partial_edit_and_remove_preserve_untouched_metadata(source):
    target = inspect_docx(source)['blocks'][1]
    result = patch_docx(source, [op(target, **{'from': 3, 'to': 4, 'href': 'mailto:a@example.com'})])
    document = Document(BytesIO(result))
    assert [(text, href) for text, href, *_ in runs(document, 1)] == [
        ('未改', None), ('旧', 'https://old.example/a'), ('链', 'mailto:a@example.com'), ('接', 'https://old.example/a')]
    links = document.paragraphs[1]._p.xpath('./w:hyperlink')
    old_id = Document(BytesIO(source)).paragraphs[1]._p.xpath('./w:hyperlink')[0].get(qn('r:id'))
    assert [link.get(qn('w:tooltip')) for link in links] == ['保留提示'] * 3
    assert links[0].get(qn('r:id')) == links[2].get(qn('r:id')) == old_id
    assert links[1].get(qn('r:id')) != old_id
    assert not links[1].xpath('.//w:rStyle')  # preserve originally unstyled source link
    target = inspect_docx(result)['blocks'][1]
    removed = Document(BytesIO(patch_docx(result, [op(target, **{'from': 3, 'to': 4, 'href': None})])))
    assert [(text, href) for text, href, *_ in runs(removed, 1)] == [
        ('未改', None), ('旧', 'https://old.example/a'), ('链', None), ('接', 'https://old.example/a')]
    assert all(bold for _, _, bold, *_ in runs(removed, 1)[1:])


def test_operations_use_current_text_and_reject_linked_text_remapping(source):
    target = inspect_docx(source)['blocks'][0]
    replace = op(target, text='新😀段尾')
    replace['kind'] = 'replaceParagraph'
    result = patch_docx(source, [replace, op(target, **{'from': 1, 'to': 3, 'href': 'http://example.com'}),
                               dict(op(target, alignment='center'), kind='setParagraphAlignment')])
    document = Document(BytesIO(result))
    assert ''.join(t for t, *_ in runs(document)) == '新😀段尾'
    assert [(t, h) for t, h, *_ in runs(document) if h] == [('😀', 'http://example.com')]
    assert document.paragraphs[0]._p.xpath('./w:pPr/w:jc/@w:val') == ['center']
    with pytest.raises(ValueError, match='link_text_replace_unsupported'):
        patch_docx(source, [op(target, **{'from': 1, 'to': 3, 'href': 'https://example.com'}), replace])
    linked = inspect_docx(source)['blocks'][1]
    with pytest.raises(ValueError, match='link_text_replace_unsupported'):
        patch_docx(source, [dict(op(linked, text='改变'), kind='replaceParagraph')])


@pytest.mark.parametrize('href', ['javascript:alert(1)', 'data:text/plain,x', 'file:///tmp/a', '/relative',
                                    'https:example.com', 'https://user:secret@example.com', '', 'mailto:',
                                    'mailto://a@example.com', 'https://example.com/a b', 'https://example.com/\n', 'x' * 4097])
def test_rejects_unsafe_urls(source, href):
    with pytest.raises(ValueError, match='link_href_invalid'):
        patch_docx(source, [op(inspect_docx(source)['blocks'][0], **{'from': 1, 'to': 3, 'href': href})])


@pytest.mark.parametrize('start,end', [(-1, 2), (0, 7), (2, 3), (1, 2), (1, 1), (1.5, 3), (True, 3)])
def test_rejects_invalid_utf16_ranges(source, start, end):
    with pytest.raises(ValueError, match='link_range_invalid'):
        patch_docx(source, [op(inspect_docx(source)['blocks'][0], **{'from': start, 'to': end, 'href': None})])


@pytest.mark.parametrize('field,value', [('blockId', 'forged'), ('expectedObjectSha256', '0' * 64), ('rId', 'rId7')])
def test_rejects_forged_anchors_and_relationship_ids(source, field, value):
    operation = op(inspect_docx(source)['blocks'][0], **{'from': 1, 'to': 3, 'href': 'https://example.com'})
    operation[field] = value
    with pytest.raises(ValueError):
        patch_docx(source, [operation])


def test_complex_unsafe_and_table_links_stay_readonly():
    document = Document()
    add_link(document.add_paragraph(), history='1')
    add_link(document.add_paragraph(), href='javascript:alert(1)')
    table = document.add_table(rows=1, cols=1)
    add_link(table.cell(0, 0).paragraphs[0])
    source = saved(document)
    model = inspect_docx(source)
    assert model['blocks'][0]['editable'] is False
    assert model['blocks'][1]['editable'] is False
    assert model['blocks'][2]['cells'][0][0]['editable'] is False
    with pytest.raises(ValueError, match='paragraph_unsupported'):
        patch_docx(source, [op(model['blocks'][0], **{'from': 0, 'to': 1, 'href': None})])


def test_upstream_tooltip_grouping_limit_is_explicit():
    document = Document()
    paragraph = document.add_paragraph()
    add_link(paragraph, '甲', tooltip='提示甲')
    add_link(paragraph, '乙', tooltip='提示乙')
    assert inspect_docx(saved(document))['blocks'][0]['editable'] is False

    document = Document()
    paragraph = document.add_paragraph()
    add_link(paragraph, '甲', href='https://a.example', tooltip='提示甲')
    add_link(paragraph, '乙', href='https://b.example', tooltip='提示乙')
    source = saved(document)
    block = inspect_docx(source)['blocks'][0]
    assert block['editable'] is True
    with pytest.raises(ValueError, match='link_metadata_merge_unsupported'):
        patch_docx(source, [op(block, **{'from': 1, 'to': 2, 'href': 'https://a.example'})])


@pytest.mark.parametrize('modify_link', [False, True])
def test_source_links_without_rpr_stay_unstyled_across_paragraph_regeneration(modify_link):
    document = Document()
    paragraph = document.add_paragraph()
    add_link(paragraph, 'ABC', href='https://a.example', tooltip='保留原提示')
    paragraph.add_run('隔')
    add_link(paragraph, '另链', href='https://other.example', tooltip='另一提示')
    for props in paragraph._p.xpath('.//w:rPr'):
        props.getparent().remove(props)
    source = saved(document)
    block = inspect_docx(source)['blocks'][0]
    operation = (op(block, **{'from': 1, 'to': 2, 'href': 'https://new.example'}) if modify_link
                 else dict(op(block, alignment='center'), kind='setParagraphAlignment'))
    result = patch_docx(source, [operation])
    reopened = Document(BytesIO(result))
    assert not reopened.paragraphs[0]._p.xpath('.//w:rPr/w:rStyle')
    assert not reopened.paragraphs[0]._p.xpath('.//w:rPr')
    expected = ([('A', 'https://a.example'), ('B', 'https://new.example'), ('C', 'https://a.example')]
                if modify_link else [('ABC', 'https://a.example')])
    assert [(text, href) for text, href, *_ in runs(reopened)] == expected + [('隔', None), ('另链', 'https://other.example')]
    original_links = Document(BytesIO(source)).paragraphs[0]._p.xpath('./w:hyperlink')
    links = reopened.paragraphs[0]._p.xpath('./w:hyperlink')
    assert links[0].get(qn('r:id')) == original_links[0].get(qn('r:id'))
    assert links[-1].get(qn('r:id')) == original_links[-1].get(qn('r:id'))
    assert links[-1].get(qn('w:tooltip')) == '另一提示'
    if modify_link:
        assert links[2].get(qn('r:id')) == original_links[0].get(qn('r:id'))
        assert [link.get(qn('w:tooltip')) for link in links[:3]] == ['保留原提示'] * 3
