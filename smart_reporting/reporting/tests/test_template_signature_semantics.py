"""模板语义选区仅绑定身份和安全原生段落，不猜固定署名词。"""

from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

import pytest
from lxml import etree

from smart_reporting.reporting.delivery.template_signature_semantics import (
    bind_semantic_signature_slot,
    inspect_signature_candidates,
)

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}


def paragraph(text):
    node = etree.Element(f'{{{W}}}p')
    run = etree.SubElement(node, f'{{{W}}}r')
    etree.SubElement(run, f'{{{W}}}t').text = text
    return etree.tostring(node).decode()


def package(body, extra=None):
    document = f'<w:document xmlns:w="{W}"><w:body>{body}<w:sectPr/></w:body></w:document>'.encode()
    output = BytesIO()
    entries = {'word/document.xml': document, 'word/styles.xml': f'<w:styles xmlns:w="{W}"/>'.encode(),
        'custom/opaque.bin': b'\x00keep\xff', **(extra or {})}
    with ZipFile(output, 'w') as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


def selection(raw, indexes):
    view = inspect_signature_candidates(raw)
    selected = [view['blocks'][index] for index in indexes]
    return {'version': 1, 'templateSha256': view['templateSha256'], 'status': 'resolved',
        'blockIds': [block['blockId'] for block in selected],
        'evidence': [{'blockId': block['blockId'], 'text': block['text']} for block in selected]}


def parts(raw):
    with ZipFile(BytesIO(raw)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


@pytest.mark.parametrize('prefix,conflict', [(None, False), ('office', False), (None, True)])
def test_namespace_selection_preserves_default_namespace_and_existing_aliases(prefix, conflict):
    from smart_reporting.reporting.delivery.template_signature_readback import (
        read_semantic_preparation,
    )

    tag = f'{prefix}:' if prefix else ''
    namespace = f'xmlns:{prefix}' if prefix else 'xmlns'
    reserved = ' xmlns:srSignature="urn:existing-template-extension"' if conflict else ''
    document = (f'<{tag}document {namespace}="{W}"{reserved}><{tag}body>'
        f'<{tag}p><{tag}r><{tag}t>业务引用保留</{tag}t></{tag}r></{tag}p>'
        f'<{tag}p><{tag}r><{tag}t>样例编制人</{tag}t></{tag}r></{tag}p>'
        f'<{tag}p><{tag}r><{tag}t>2001-02-03</{tag}t></{tag}r></{tag}p>'
        f'<{tag}sectPr/></{tag}body></{tag}document>').encode()
    raw = package('', {'word/document.xml': document})
    record = selection(raw, [1, 2])
    prepared, receipt = bind_semantic_signature_slot(raw, record)
    before, after = parts(raw), parts(prepared)
    control = etree.fromstring(after['word/document.xml']).find('w:body/w:sdt', NS)
    expected_prefix = prefix or ('srSignature_' if conflict else 'srSignature')
    assert control.prefix == expected_prefix
    declaration = '' if prefix else f' xmlns:{expected_prefix}="{W}"'
    opening = (f'<{expected_prefix}:sdt{declaration}><{expected_prefix}:sdtPr>'
        f'<{expected_prefix}:tag {expected_prefix}:val="report_signature"/></{expected_prefix}:sdtPr>'
        f'<{expected_prefix}:sdtContent>').encode()
    closing = f'</{expected_prefix}:sdtContent></{expected_prefix}:sdt>'.encode()
    assert after['word/document.xml'].replace(opening, b'', 1).replace(closing, b'', 1) == document
    assert all(before[name] == after[name] for name in before if name != 'word/document.xml')
    independent = read_semantic_preparation(raw, prepared, record, receipt)
    assert independent['status'] == 'passed' and independent['coverage'] == 'complete'


def test_inspection_is_complete_stable_and_identity_bound():
    raw = package(paragraph('业务引用：甲团队 2025-01-02') + '<w:tbl><w:tr><w:tc>' + paragraph('表内上下文')
        + '</w:tc></w:tr></w:tbl>' + paragraph('甲团队') + paragraph('2025-01-02'))
    view = inspect_signature_candidates(raw)
    assert view == inspect_signature_candidates(raw)
    assert view['version'] == 1 and view['templateSha256'] == sha256(raw).hexdigest()
    assert len(view['blocks']) == 5
    assert [item['eligible'] for item in view['blocks']] == [True, False, True, True, False]
    assert view['blocks'][1]['text'] == '表内上下文'
    changed = inspect_signature_candidates(package(paragraph('更改业务引用') + paragraph('甲团队')))
    assert view['blocks'][0]['blockId'] != changed['blocks'][0]['blockId']
    duplicate = inspect_signature_candidates(package(paragraph('甲团队') + paragraph('甲团队')))
    assert duplicate['blocks'][0]['blockId'] != duplicate['blocks'][1]['blockId']


@pytest.mark.parametrize('name,date', [('甲团队', '2025-01-02'), ('Reviewed by Ω', '十一月十三日')])
def test_binding_preserves_native_properties_business_references_and_every_other_part(name, date):
    preserved = paragraph(f'业务引用：{name}，历史日期：{date}')
    selected = f'<w:p><w:pPr><w:jc w:val="right"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="28"/></w:rPr><w:t>{name}</w:t></w:r></w:p>'
    raw = package(preserved + selected + paragraph(date) + paragraph('附录引用仍保留'))
    record = selection(raw, [1, 2])
    prepared, receipt = bind_semantic_signature_slot(raw, record)
    before, after = parts(raw), parts(prepared)
    assert before.keys() == after.keys()
    assert all(before[key] == after[key] for key in before if key != 'word/document.xml')
    original = etree.fromstring(before['word/document.xml'])
    result = etree.fromstring(after['word/document.xml'])
    control = result.find('.//w:body/w:sdt', NS)
    assert control.find('w:sdtPr/w:tag', NS).get(f'{{{W}}}val') == 'report_signature'
    content = control.find('w:sdtContent', NS)
    assert [node.find('w:r/w:t', NS).text for node in content] == [name, date]
    assert content[0].find('w:pPr/w:jc', NS).get(f'{{{W}}}val') == 'right'
    assert content[0].find('w:r/w:rPr/w:sz', NS).get(f'{{{W}}}val') == '28'
    prefix = control.prefix
    opening = f'<{prefix}:sdt><{prefix}:sdtPr><{prefix}:tag {prefix}:val="report_signature"/></{prefix}:sdtPr><{prefix}:sdtContent>'.encode()
    ending = f'</{prefix}:sdtContent></{prefix}:sdt>'.encode()
    assert after['word/document.xml'].replace(opening, b'', 1).replace(ending, b'', 1) == before['word/document.xml']
    assert result.find('w:body/w:p/w:r/w:t', NS).text == original.find('w:body/w:p/w:r/w:t', NS).text
    assert receipt == {'templateSha256': sha256(raw).hexdigest(), 'preparedTemplateSha256': sha256(prepared).hexdigest(),
        'selectedBlockIds': record['blockIds'], 'status': 'resolved'}
    assert inspect_signature_candidates(prepared)['declared'] is True


@pytest.mark.parametrize('mutate', [
    lambda record: record.update(templateSha256='0' * 64),
    lambda record: record.update(version=True),
    lambda record: record.update(status='unresolved'),
    lambda record: record['blockIds'].append(record['blockIds'][0]),
    lambda record: record['evidence'][0].update(text='甲团队 '),
    lambda record: record['evidence'].reverse(),
    lambda record: record['blockIds'].reverse(),
    lambda record: record['blockIds'].__setitem__(0, 'unknown'),
    lambda record: record.update(evidence=[]),
])
def test_binding_rejects_invalid_identity_duplicates_drift_and_unmatched_evidence(mutate):
    raw = package(paragraph('甲团队') + paragraph('2025-01-02'))
    record = selection(raw, [0, 1])
    mutate(record)
    with pytest.raises(ValueError):
        bind_semantic_signature_slot(raw, record)


@pytest.mark.parametrize('indexes', [[], [0, 2], list(range(13))])
def test_binding_requires_nonempty_contiguous_bounded_group(indexes):
    raw = package(''.join(paragraph(str(i)) for i in range(13)))
    with pytest.raises(ValueError):
        bind_semantic_signature_slot(raw, selection(raw, indexes))


@pytest.mark.parametrize('fragment', [
    '<w:fldSimple w:instr="DATE"/>', '<w:r><w:fldChar w:fldCharType="begin"/></w:r>',
    '<w:r><w:drawing/></w:r>', '<w:hyperlink><w:r><w:t>链接</w:t></w:r></w:hyperlink>',
    '<w:bookmarkStart w:id="1" w:name="ref"/>', '<w:commentRangeStart w:id="1"/>',
    '<w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr>',
    '<w:r><w:rPr><w:vanish/></w:rPr></w:r>', '<w:r><w:br w:type="page"/></w:r>',
    '<w:pPr><w:sectPr/></w:pPr>', '<w:pPr><w:pageBreakBefore/></w:pPr>',
    '<w:pPr><w:pStyle w:val="HiddenStyle"/></w:pPr>', '<w:ins><w:r><w:t>修订</w:t></w:r></w:ins>',
])
def test_protected_paragraphs_are_context_only_and_cannot_be_selected(fragment):
    raw = package(f'<w:p>{fragment}<w:r><w:t>旧署名</w:t></w:r></w:p>')
    assert inspect_signature_candidates(raw)['blocks'][0]['eligible'] is False
    with pytest.raises(ValueError):
        bind_semantic_signature_slot(raw, selection(raw, [0]))


@pytest.mark.parametrize('body,extra', [
    ('<w:sdt><w:sdtPr><w:tag w:val="report_signature"/></w:sdtPr><w:sdtContent/></w:sdt>', None),
    (paragraph('{{report_signature}}'), None),
    ('', {'word/header1.xml': f'<w:hdr xmlns:w="{W}">{paragraph("{{report_signature}}")}</w:hdr>'.encode()}),
])
def test_existing_declaration_always_prevents_semantic_override(body, extra):
    raw = package(paragraph('候选署名') + body, extra)
    assert inspect_signature_candidates(raw)['declared'] is True
    with pytest.raises(ValueError):
        bind_semantic_signature_slot(raw, selection(raw, [0]))


@pytest.mark.parametrize('body', [''.join(paragraph('x') for _ in range(400)), paragraph('x' * 60001),
    '<w:tbl><w:tr><w:tc>' + paragraph('x' * 60001) + '</w:tc></w:tr></w:tbl>'])
def test_inspection_refuses_over_limit_context_instead_of_truncating(body):
    with pytest.raises(ValueError):
        inspect_signature_candidates(package(body))


def test_duplicate_parts_and_unsafe_xml_are_rejected():
    raw = package(paragraph('甲团队'))
    output = BytesIO(raw)
    with pytest.warns(UserWarning), ZipFile(output, 'a') as archive:
        archive.writestr('word/document.xml', parts(raw)['word/document.xml'])
    with pytest.raises(ValueError):
        inspect_signature_candidates(output.getvalue())
    unsafe = b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///private/secret">]><w:document xmlns:w="' + W.encode() + b'"><w:body><w:p><w:r><w:t>&e;</w:t></w:r></w:p></w:body></w:document>'
    with pytest.raises(ValueError):
        inspect_signature_candidates(package('', {'word/document.xml': unsafe}))


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16-le', 'utf-16-be'])
def test_binding_preserves_xml_bytes_with_alias_namespaces_comments_and_encoding(encoding):
    document = (f'<?xml version="1.0" encoding="{encoding}"?><d:document xmlns:d="{W}" xmlns:srSignature="urn:existing">'
        '<d:body><!--context--><?context keep?><d:p><d:r><d:t>部门甲</d:t></d:r></d:p>\n'
        '<d:p><d:r><d:t>日期乙</d:t></d:r></d:p><d:sectPr/></d:body></d:document>').encode(encoding)
    raw = package('', {'word/document.xml': document})
    view = inspect_signature_candidates(raw)
    assert len(view['blocks']) == 5
    assert [item['text'] for item in view['blocks']][2:4] == ['部门甲', '日期乙']
    prepared, _ = bind_semantic_signature_slot(raw, selection(raw, [2, 3]))
    actual = parts(prepared)['word/document.xml'].decode(encoding)
    opening = '<d:sdt><d:sdtPr><d:tag d:val="report_signature"/></d:sdtPr><d:sdtContent>'
    assert actual.replace(opening, '', 1).replace('</d:sdtContent></d:sdt>', '', 1) == document.decode(encoding)


@pytest.mark.parametrize('styles', [
    '<w:docDefaults><w:rPrDefault><w:rPr><w:vanish/></w:rPr></w:rPrDefault></w:docDefaults>',
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:pPr><w:numPr/></w:pPr></w:style>',
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:basedOn w:val="Parent"/></w:style><w:style w:styleId="Parent"><w:rPr><w:vanish/></w:rPr></w:style>',
])
def test_inherited_hidden_or_list_defaults_make_unstyled_paragraphs_ineligible(styles):
    raw = package(paragraph('旧署名'), {'word/styles.xml': f'<w:styles xmlns:w="{W}">{styles}</w:styles>'.encode()})
    assert inspect_signature_candidates(raw)['blocks'][0]['eligible'] is False
    with pytest.raises(ValueError):
        bind_semantic_signature_slot(raw, selection(raw, [0]))


def test_exact_context_limits_and_empty_paragraph_protection():
    assert len(inspect_signature_candidates(package(''.join(paragraph('x') for _ in range(399))))['blocks']) == 400
    assert len(inspect_signature_candidates(package(paragraph('x' * 60000)))['blocks'][0]['text']) == 60000
    raw = package(paragraph('  '))
    assert inspect_signature_candidates(raw)['blocks'][0]['eligible'] is False
    with pytest.raises(ValueError):
        bind_semantic_signature_slot(raw, selection(raw, [0]))


def test_real_docx_package_reopens_after_binding_without_changing_other_parts(tmp_path):
    from docx import Document
    from docx.shared import Pt

    document = Document()
    document.add_paragraph('业务引用：复核组，期间2026-11-13')
    document.add_table(rows=1, cols=1).cell(0, 0).text = '表内日期2026-11-13'
    signer = document.add_paragraph()
    signer.add_run('复核组').font.size = Pt(14)
    document.add_paragraph('2026-11-13')
    original = tmp_path / 'original.docx'
    document.save(original)
    raw = original.read_bytes()
    prepared, _ = bind_semantic_signature_slot(raw, selection(raw, [2, 3]))
    result = Document(BytesIO(prepared))
    assert result.tables[0].cell(0, 0).text == '表内日期2026-11-13'
    assert result.paragraphs[0].text == '业务引用：复核组，期间2026-11-13'
    control = result.element.body.find('w:sdt', NS)
    assert control is not None and control.find('w:sdtContent/w:p/w:r/w:rPr/w:sz', NS).get(f'{{{W}}}val') == '28'
    before, after = parts(raw), parts(prepared)
    assert all(before[key] == after[key] for key in before if key != 'word/document.xml')


@pytest.mark.parametrize('properties', ['<w:pageBreakBefore/>', '<w:sectPr/>'])
def test_inherited_pagination_defaults_cannot_be_selected(properties):
    styles = f'<w:styles xmlns:w="{W}"><w:docDefaults><w:pPrDefault><w:pPr>{properties}</w:pPr></w:pPrDefault></w:docDefaults></w:styles>'
    raw = package(paragraph('旧署名'), {'word/styles.xml': styles.encode()})
    assert inspect_signature_candidates(raw)['blocks'][0]['eligible'] is False
    with pytest.raises(ValueError):
        bind_semantic_signature_slot(raw, selection(raw, [0]))


@pytest.mark.parametrize('text', ['{{report_content}}', '{{report_title}}',
    '正文前缀{{report_content}}正文后缀', '标题{{report_title}}与{{custom_field}}混排'])
def test_template_placeholders_are_context_only_even_with_two_matching_selections(text):
    raw = package(paragraph(text) + paragraph('旧署名') + paragraph('旧日期'))
    first = selection(raw, [0, 1, 2])
    second = selection(raw, [0, 1, 2])
    assert first == second
    for record in (first, second):
        with pytest.raises(ValueError):
            bind_semantic_signature_slot(raw, record)
    assert inspect_signature_candidates(raw)['blocks'][0]['eligible'] is False


@pytest.mark.parametrize('start,end', [('bookmarkStart', 'bookmarkEnd'), ('commentRangeStart', 'commentRangeEnd'),
    ('moveFromRangeStart', 'moveFromRangeEnd'), ('moveToRangeStart', 'moveToRangeEnd'), ('permStart', 'permEnd'),
    ('customXmlInsRangeStart', 'customXmlInsRangeEnd'), ('customXmlDelRangeStart', 'customXmlDelRangeEnd')])
@pytest.mark.parametrize('nested', [False, True])
def test_existing_native_ranges_protect_enclosed_paragraphs_even_without_inline_markers(start, end, nested):
    before, after = f'<w:{start} w:id="1"/>', f'<w:{end} w:id="1"/>'
    if nested:
        before, after = f'<w:p>{before}<w:r><w:t>业务前文</w:t></w:r></w:p>', f'<w:p>{after}<w:r><w:t>业务后文</w:t></w:r></w:p>'
    raw = package(before + paragraph('候选旧署名') + after)
    record = selection(raw, [1])
    with pytest.raises(ValueError):
        bind_semantic_signature_slot(raw, record)
    assert inspect_signature_candidates(raw)['blocks'][1]['eligible'] is False
