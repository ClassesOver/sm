"""真实消费者的内部链接必须由源标题和实际目标结构独立证明。"""

import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.template_body_readback import read_template_body
from smart_reporting.reporting.delivery.templates import fill_report_template

BODY = ('# original_business\n\n首节原文 1234.5600。\n\n## Next Target\n\n末节原文 -98.7600%。\n\n'
    '[前往首标题](#original_business) 与 [前往末标题](#next-target)\n\n末段原值 7.8900。')
_NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
_OUTPUT = Path('output/system-config-preferences/editor-template-parity/internal-links')


def xpath(node, expression):
    return etree.XPath(expression, namespaces=_NS)(node)


def packed(doc):
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def native_template():
    doc = Document()
    paragraph = doc.add_paragraph('宿主业务说明保持')
    start, end = OxmlElement('w:bookmarkStart'), OxmlElement('w:bookmarkEnd')
    start.set(qn('w:id'), '42')
    start.set(qn('w:name'), 'original_business')
    end.set(qn('w:id'), '42')
    paragraph._p.insert(0, start)
    paragraph._p.append(end)
    doc.add_paragraph('{{report_content}}')
    doc.add_paragraph('宿主末尾说明保持')
    return packed(doc)


@pytest.fixture(scope='module')
def actual_consumer_document():
    original = native_template()
    filled = fill_report_template(original, template_format='docx', delivery_format='docx',
        values={'report_content': BODY}, body_resources={})
    assert not filled.issues and filled.body_binding['status'] == 'projected'
    _OUTPUT.mkdir(parents=True, exist_ok=True)
    records = []
    for name, raw in [('consumer-native-sample.docx', filled.content), ('source.md', BODY.encode()), ('template.docx', original)]:
        path = _OUTPUT / name
        if not path.exists():
            path.write_bytes(raw)
        recorded = path.read_bytes()
        records.append({'path': str(path), 'size': len(recorded), 'sha256': sha256(recorded).hexdigest()})
    identity = _OUTPUT / 'initial-consumer-identities.json'
    if not identity.exists():
        identity.write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
    return filled.content


def body_and_links(doc):
    body = xpath(doc.element.body, './/w:sdt[w:sdtPr/w:tag[@w:val="report_content"]]/w:sdtContent')[0]
    return body, xpath(body, './/w:hyperlink')


def test_real_consumer_collision_rename_has_independent_complete_target_evidence(actual_consumer_document):
    doc = Document(BytesIO(actual_consumer_document))
    _, links = body_and_links(doc)
    assert links[0].get(qn('w:anchor')) != 'original_business'
    result = read_template_body(actual_consumer_document, BODY, {})
    assert result['status'] == 'passed' and result['coverage'] == 'complete'
    assert result['scope']['internalLinkCount'] == 2
    assert [target['targetBlock'] for target in result['scope']['internalLinkTargets']] == [0, 2]


def test_safe_arbitrary_actual_names_do_not_need_writer_receipt(actual_consumer_document):
    doc = Document(BytesIO(actual_consumer_document))
    body, links = body_and_links(doc)
    names = {}
    for index, start in enumerate(xpath(body, './/w:bookmarkStart')):
        names[start.get(qn('w:name'))] = 'independent_target_' + str(index)
        start.set(qn('w:name'), names[start.get(qn('w:name'))])
    for link in links:
        link.set(qn('w:anchor'), names[link.get(qn('w:anchor'))])
    assert read_template_body(packed(doc), BODY, {})['status'] == 'passed'


@pytest.mark.parametrize('change', ['wrong_target', 'last_link_word', 'duplicate_host_name', 'cross_slot',
    'nonheading_target', 'end_before_heading', 'midheading_start', 'label_boundary', 'missing_anchor', 'dual_target'])
def test_internal_link_fault_never_passes_from_same_visible_body_text(actual_consumer_document, change):
    doc = Document(BytesIO(actual_consumer_document))
    body, links = body_and_links(doc)
    starts = xpath(body, './/w:bookmarkStart')
    if change == 'wrong_target':
        links[0].set(qn('w:anchor'), links[1].get(qn('w:anchor')))
    elif change == 'last_link_word':
        xpath(links[-1], './/w:t')[-1].text += '错误末字'
    elif change == 'duplicate_host_name':
        doc.element.body.xpath('./w:p/w:bookmarkStart')[0].set(qn('w:name'), starts[0].get(qn('w:name')))
    elif change == 'cross_slot':
        links[0].set(qn('w:anchor'), 'original_business')
    elif change == 'nonheading_target':
        paragraph = xpath(body, './w:p')[1]
        paragraph.addprevious(starts[0])
    elif change == 'end_before_heading':
        ending = next(node for node in xpath(body, './/w:bookmarkEnd')
            if node.get(qn('w:id')) == starts[0].get(qn('w:id')))
        starts[0].addnext(ending)
    elif change == 'midheading_start':
        xpath(body, './w:p')[0].append(starts[0])
    elif change == 'label_boundary':
        text = xpath(links[0], './/w:t')[-1]
        character = text.text[-1]
        text.text = text.text[:-1]
        run, literal = OxmlElement('w:r'), OxmlElement('w:t')
        literal.text = character
        run.append(literal)
        links[0].addnext(run)
    elif change == 'missing_anchor':
        links[0].attrib.pop(qn('w:anchor'))
    else:
        links[0].set(qn('r:id'), 'unverified-external-rId')
    result = read_template_body(packed(doc), BODY, {})
    assert result['status'] == 'failed' and result['issues']


def test_source_link_without_a_source_heading_target_is_unverified(actual_consumer_document):
    source = BODY.replace('](#next-target)', '](#no-source-target)')
    result = read_template_body(actual_consumer_document, source, {})
    assert result['status'] == 'unverified' and result['coverage'] == 'unverified'


def test_complex_heading_fragment_remains_unverified_instead_of_guessing():
    source = '# Target: Alpha\n\n[查看](#target-alpha)'
    filled = fill_report_template(native_template(), template_format='docx', delivery_format='docx',
        values={'report_content': source}, body_resources={})
    assert filled.body_binding['status'] == 'projected'
    result = read_template_body(filled.content, source, {})
    assert result['status'] == 'unverified'


def test_unknown_heading_cannot_shift_source_fragment_to_another_simple_heading():
    source = '# A: B\n\n# A B\n\n[打开](#a-b)'
    filled = fill_report_template(native_template(), template_format='docx', delivery_format='docx',
        values={'report_content': source}, body_resources={})
    assert filled.body_binding['status'] == 'projected'
    doc = Document(BytesIO(filled.content))
    body, links = body_and_links(doc)
    names = xpath(body, './/w:bookmarkStart/@w:name')
    links[0].set(qn('w:anchor'), names[-1])
    result = read_template_body(packed(doc), source, {})
    assert result['status'] == 'unverified'


def test_repeated_simple_heading_links_are_proved_by_block_identity():
    source = '# Target\n\n# Target\n\n[查看第二标题](#target-1)'
    filled = fill_report_template(native_template(), template_format='docx', delivery_format='docx',
        values={'report_content': source}, body_resources={})
    assert filled.body_binding['status'] == 'projected'
    result = read_template_body(filled.content, source, {})
    assert result['status'] == 'passed'
    assert result['scope']['internalLinkTargets'][0]['targetBlock'] == 1


@pytest.mark.parametrize('fragment', ['中文标题', '%E4%B8%AD%E6%96%87%E6%A0%87%E9%A2%98'])
def test_unicode_source_fragments_resolve_to_the_same_native_heading(fragment):
    source = '# 中文标题\n\n[查看完整标题](#' + fragment + ')'
    filled = fill_report_template(native_template(), template_format='docx', delivery_format='docx',
        values={'report_content': source}, body_resources={})
    assert filled.body_binding['status'] == 'projected'
    result = read_template_body(filled.content, source, {})
    assert result['status'] == 'passed'
    assert result['scope']['internalLinkTargets'][0]['targetText'] == '中文标题'


@pytest.mark.parametrize('target', ['#unknown-target', 'https://example.invalid/#known'])
def test_consumer_keeps_literal_and_warns_for_unbound_or_external_link(target):
    source = '# Known\n\n[必须保留原文](' + target + ')'
    filled = fill_report_template(native_template(), template_format='docx', delivery_format='docx',
        values={'report_content': source}, body_resources={})
    assert filled.body_binding['status'] == 'unverified'
    assert source in ''.join(Document(BytesIO(filled.content)).element.body.xpath('.//w:t/text()'))
    assert any(issue['code'] == 'report_template_body_projection_unavailable' for issue in filled.issues)


def test_new_body_bookmark_does_not_activate_dangling_host_anchor():
    doc = Document(BytesIO(native_template()))
    link = OxmlElement('w:hyperlink')
    link.set(qn('w:anchor'), 'report_content_heading_1')
    doc.paragraphs[0]._p.append(link)
    filled = fill_report_template(packed(doc), template_format='docx', delivery_format='docx',
        values={'report_content': BODY}, body_resources={})
    assert filled.body_binding['status'] == 'projected'
    actual = Document(BytesIO(filled.content))
    body, links = body_and_links(actual)
    names = actual.element.body.xpath('.//w:bookmarkStart/@w:name')
    assert 'report_content_heading_1' not in names
    assert actual.paragraphs[0]._p.xpath('./w:hyperlink/@w:anchor') == ['report_content_heading_1']
    assert links[0].get(qn('w:anchor')) in xpath(body, './/w:bookmarkStart/@w:name')
    assert read_template_body(filled.content, BODY, {})['status'] == 'passed'


def test_management_outside_comparison_independently_rejects_activated_host_anchor():
    from smart_reporting.management.preference_template_readback import read_template_document
    from smart_reporting.tests.test_template_rich_body_readback import RESOURCES, management_case

    original, actual, resolved, frozen = management_case()

    def add_reference(raw, add_target):
        doc = Document(BytesIO(raw))
        link = OxmlElement('w:hyperlink')
        link.set(qn('w:anchor'), 'newly_imported_target')
        doc.paragraphs[0]._p.append(link)
        if add_target:
            body, _ = body_and_links(doc)
            start, end = OxmlElement('w:bookmarkStart'), OxmlElement('w:bookmarkEnd')
            start.set(qn('w:id'), '987')
            start.set(qn('w:name'), 'newly_imported_target')
            end.set(qn('w:id'), '987')
            body.insert(0, start)
            body.append(end)
        return packed(doc)

    result = read_template_document(add_reference(actual, True), 'word', resolved, frozen,
        add_reference(original, False), body_resources=RESOURCES)
    assert result['templateReadback']['body']['status'] == 'passed'
    assert result['templateReadback']['outsideDeclaredTargets']['status'] == 'failed'
