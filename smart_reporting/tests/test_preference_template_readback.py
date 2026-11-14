"""模板声明区读取需同时核原生内容与声明外的实际XML，回执不能自证。"""

from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement

from smart_reporting.management.preference_template_readback import read_template_document
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.templates import fill_report_template
from smart_reporting.tests.test_preference_template_preflight import template_bytes


def reader_case():
    original = template_bytes()
    preferences = FormatPreferences.model_validate({'common': {'signer': '实际署名', 'dateFormat': 'iso'},
        'word': {'signature': {'description': '完整说明一\n完整说明二'}}})
    resolved = resolve_format_preferences(preferences, 'word')
    frozen = {'markdown': '受控正文123.45', 'state': {'_documentContext': {
        'title': '冻结标题', 'generatedDate': '2026-11-13'}}}
    filled = fill_report_template(original, template_format='docx', delivery_format='docx',
        values={'report_title': '冻结标题', 'report_content': '受控正文123.45'},
        signature={'signer': '实际署名', 'date': '2026-11-13', 'description': '完整说明一\n完整说明二'})
    return original, resolved, frozen, filled.content


@pytest.mark.parametrize('change', ['body_text', 'body_font', 'extra_paragraph'])
def test_template_reader_detects_changes_outside_slot_inside_same_modified_xml(change):
    original, resolved, frozen, content = reader_case()
    document = Document(BytesIO(content))
    if change == 'body_text':
        document.paragraphs[0].runs[0].text = '错误改写业务日期2001-01-01'
    elif change == 'body_font':
        document.paragraphs[0].runs[0].bold = True
    else:
        document.add_paragraph('未声明新增内容')
    output = BytesIO()
    document.save(output)
    result = read_template_document(output.getvalue(), 'word', resolved, frozen, original)
    assert result['templateReadback']['outsideDeclaredTargets']['status'] == 'failed'
    assert result['status'] == 'failed'
    assert all('evidenceKind' not in row for row in result['checks'])


@pytest.mark.parametrize('change', ['wrong_signer', 'wrong_date', 'missing_description', 'hidden_run', 'field_in_slot', 'complex_field'])
def test_template_reader_checks_entire_sdt_not_any_matching_body_quote(change):
    original, resolved, frozen, content = reader_case()
    document = Document(BytesIO(content))
    content_node = document._element.body.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_signature"]]/w:sdtContent')[0]
    if change in {'wrong_signer', 'wrong_date'}:
        content_node[0 if change == 'wrong_signer' else 1].xpath('.//w:t')[0].text = '错误值'
    elif change == 'missing_description':
        content_node.remove(content_node[-1])
    elif change == 'hidden_run':
        run = content_node[0].xpath('.//w:r')[0]
        properties = run.get_or_add_rPr()
        properties.append(OxmlElement('w:vanish'))
    elif change == 'field_in_slot':
        field = OxmlElement('w:fldSimple')
        content_node[0].append(field)
    else:
        from docx.oxml.ns import qn
        paragraph = content_node[0]
        for offset, kind in enumerate(('begin', 'instruction', 'separate'), 1):
            run = OxmlElement('w:r')
            if kind == 'instruction':
                field = OxmlElement('w:instrText')
                field.text = ' DOCPROPERTY Author '
            else:
                field = OxmlElement('w:fldChar')
                field.set(qn('w:fldCharType'), kind)
            run.append(field)
            paragraph.insert(offset, run)
        run, field = OxmlElement('w:r'), OxmlElement('w:fldChar')
        field.set(qn('w:fldCharType'), 'end')
        run.append(field)
        paragraph.append(run)
    output = BytesIO()
    document.save(output)
    result = read_template_document(output.getvalue(), 'word', resolved, frozen, original)
    assert result['templateReadback']['signature']['status'] == 'failed'
    assert result['status'] == 'failed'
    if change == 'complex_field':
        assert any(issue['code'] == 'management_preference_template_signature_dynamic_field' for issue in result['issues'])


def test_external_zip_part_changes_are_not_hidden_by_declaration_receipt():
    original, resolved, frozen, content = reader_case()
    output = BytesIO()
    with ZipFile(BytesIO(content)) as source, ZipFile(output, 'w') as target:
        for entry in source.infolist():
            raw = source.read(entry)
            if entry.filename == 'word/styles.xml':
                raw = raw.replace(b'Liberation Serif', b'Arial')
            target.writestr(entry, raw)
    result = read_template_document(output.getvalue(), 'word', resolved, frozen, original)
    assert result['templateReadback']['outsideDeclaredTargets']['status'] == 'failed'


def test_slot_only_reader_cannot_use_body_citations_when_slot_removed():
    original, resolved, frozen, content = reader_case()
    document = Document(BytesIO(content))
    slot = document._element.body.xpath('.//w:sdt[w:sdtPr/w:tag[@w:val="report_signature"]]')[0]
    slot.getparent().remove(slot)
    for text in ['实际署名', '2026-11-13', '完整说明一', '完整说明二']:
        document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    result = read_template_document(output.getvalue(), 'word', resolved, frozen, original)
    assert result['templateReadback']['signature']['status'] == 'unverified'
    assert all(row['coverage'] == 'sample' for row in result['checks'] if row['path'])
