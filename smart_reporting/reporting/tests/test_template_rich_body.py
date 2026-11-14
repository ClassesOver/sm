"""富文档必须成为模板里的原生对象，且不改声明外业务内容。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from PIL import Image

from smart_reporting.reporting.delivery.templates import fill_report_template


def template(*, duplicate=False):
    doc = Document()
    doc.styles['Normal'].font.name = 'Liberation Serif'
    doc.styles['Normal'].font.size = Pt(17)
    doc.sections[0].header.paragraphs[0].text = '原模板页眉'
    before = doc.add_paragraph('保留业务引用 1234.5600')
    start, end = OxmlElement('w:bookmarkStart'), OxmlElement('w:bookmarkEnd')
    start.set(qn('w:id'), '42')
    start.set(qn('w:name'), 'original_business')
    end.set(qn('w:id'), '42')
    before._p.insert(0, start)
    before._p.append(end)
    doc.add_paragraph('{{report_content}}')
    if duplicate:
        doc.add_paragraph('{{report_content}}')
    doc.add_paragraph('末尾业务文字保持')
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def resources():
    stream = BytesIO()
    Image.new('RGB', (100, 50), '#345678').save(stream, format='PNG')
    return {'chart.png': stream.getvalue()}


BODY = ('# 原标题\n\n## 收支分析\n\n**重要原值** 1234.5600\n\n'
    '- 第一项\n- 第二项\n\n| 指标 | 金额 |\n| --- | ---: |\n| 收入 | 1234.5600 |\n\n'
    '![冻结图](chart.png)\n\n`{{report_title}}` 应当保留字面。')


def test_template_body_is_native_editable_and_preserves_outside_template():
    original = template()
    filled = fill_report_template(original, template_format='docx', delivery_format='docx',
        values={'report_content': BODY, 'report_title': '不能递归替换'}, body_resources=resources())
    doc = Document(BytesIO(filled.content))
    content = doc._element.body.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_content"]]/w:sdtContent')
    assert len(content) == 1
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    assert len(content[0].xpath('./w:tbl', namespaces=ns)) == 1
    assert content[0].xpath('.//w:tc/w:p/w:r/w:t/text()', namespaces=ns) == ['指标', '金额', '收入', '1234.5600']
    assert len(content[0].xpath('.//w:drawing', namespaces=ns)) == 1
    assert content[0].xpath('.//w:pPr/w:numPr', namespaces=ns)
    assert content[0].xpath('.//w:rPr/w:b', namespaces=ns)
    assert '{{report_title}}' in ''.join(content[0].xpath('.//w:t/text()', namespaces=ns))
    assert doc.paragraphs[0].text == '保留业务引用 1234.5600'
    assert doc.paragraphs[-1].text == '末尾业务文字保持'
    assert doc._element.body.xpath('.//w:bookmarkStart[@w:name="original_business"]/@w:id') == ['42']
    assert doc.styles['Normal'].font.size.pt == 17
    with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(filled.content)) as after:
        assert before.read('word/header1.xml') == after.read('word/header1.xml')
    assert filled.body_binding['status'] == 'projected'
    assert not filled.issues


@pytest.mark.parametrize('failure', ['ambiguous', 'missing_image', 'converter'])
def test_template_body_failure_retains_literal_content_and_specific_warning(monkeypatch, failure):
    if failure == 'converter':
        from smart_reporting.reporting.delivery import template_body
        def fail(*args, **kwargs):
            raise OSError('injected converter failure')
        monkeypatch.setattr(template_body.subprocess, 'run', fail)
    filled = fill_report_template(template(duplicate=failure == 'ambiguous'),
        template_format='docx', delivery_format='docx', values={'report_content': BODY},
        body_resources={} if failure == 'missing_image' else resources())
    text = ''.join(Document(BytesIO(filled.content))._element.body.xpath('.//w:t/text()'))
    assert BODY in text
    assert filled.body_binding['status'] != 'projected'
    assert any(issue['code'].startswith('report_template_body_') for issue in filled.issues)


def test_imported_bookmark_names_do_not_shadow_template_links():
    original = template()
    filled = fill_report_template(original, template_format='docx', delivery_format='docx',
        values={'report_content': '# original_business\n\n[回到正文标题](#original_business)'}, body_resources={})
    doc = Document(BytesIO(filled.content))
    names = doc._element.body.xpath('.//w:bookmarkStart/@w:name')
    assert len(names) == len(set(names))
    assert doc._element.body.xpath('.//w:bookmarkStart[@w:name="original_business"]/@w:id') == ['42']
    content = doc._element.body.xpath('.//w:sdtContent')[0]
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    anchors = content.xpath('.//w:hyperlink/@w:anchor', namespaces=ns)
    imported = content.xpath('.//w:bookmarkStart/@w:name', namespaces=ns)
    assert len(anchors) == 1 and anchors[0] in imported
    assert anchors[0] != 'original_business'
    assert filled.body_binding['status'] == 'projected'


def test_pandoc_first_body_paragraph_has_a_defined_template_style():
    filled = fill_report_template(template(), template_format='docx', delivery_format='docx',
        values={'report_content': '# 标题\n\n![图片](chart.png)'}, body_resources=resources())
    doc = Document(BytesIO(filled.content))
    defined = set(doc.styles.element.xpath('./w:style/@w:styleId'))
    used = set(doc._element.body.xpath('.//w:pStyle/@w:val|.//w:rStyle/@w:val|.//w:tblStyle/@w:val'))
    assert used <= defined
    assert filled.body_binding['status'] == 'projected'


def test_added_body_styles_cannot_activate_undefined_outside_template_style():
    doc = Document(BytesIO(template()))
    style = OxmlElement('w:pStyle')
    style.set(qn('w:val'), 'FirstParagraph')
    doc.paragraphs[0]._p.get_or_add_pPr().append(style)
    assert 'FirstParagraph' not in doc.styles.element.xpath('./w:style/@w:styleId')
    stream = BytesIO()
    doc.save(stream)
    filled = fill_report_template(stream.getvalue(), template_format='docx', delivery_format='docx',
        values={'report_content': '# 标题\n\n正文。'}, body_resources={})
    assert filled.body_binding['status'] == 'unverified'
    assert any(issue['code'] == 'report_template_body_projection_unavailable' for issue in filled.issues)
    actual = Document(BytesIO(filled.content))
    assert 'FirstParagraph' not in actual.styles.element.xpath('./w:style/@w:styleId')
    assert actual.paragraphs[0]._p.xpath('./w:pPr/w:pStyle/@w:val') == ['FirstParagraph']


@pytest.mark.parametrize('dependency', ['numbering', 'abstract_numbering', 'image_relationship'])
def test_imported_dependencies_cannot_activate_unresolved_outside_objects(dependency):
    doc = Document(BytesIO(template()))
    numbers = doc.part.numbering_part.element
    if dependency == 'numbering':
        next_id = max(map(int, numbers.xpath('./w:num/@w:numId'))) + 1
        props, identity = OxmlElement('w:numPr'), OxmlElement('w:numId')
        identity.set(qn('w:val'), str(next_id))
        props.append(identity)
        doc.paragraphs[0]._p.get_or_add_pPr().append(props)
    elif dependency == 'abstract_numbering':
        next_id = max(map(int, numbers.xpath('./w:abstractNum/@w:abstractNumId'))) + 1
        numbers.xpath('./w:num/w:abstractNumId')[0].set(qn('w:val'), str(next_id))
    else:
        picture = doc.paragraphs[0].add_run().add_picture(BytesIO(resources()['chart.png']))
        identity = picture._inline.xpath('.//a:blip/@r:embed')[0]
        del doc.part.rels[identity]
    stream = BytesIO()
    doc.save(stream)
    filled = fill_report_template(stream.getvalue(), template_format='docx', delivery_format='docx',
        values={'report_content': '# 标题\n\n- 项目\n\n![图片](chart.png)'}, body_resources=resources())
    assert filled.body_binding['status'] == 'unverified'
    assert any(issue['code'] == 'report_template_body_projection_unavailable' for issue in filled.issues)
