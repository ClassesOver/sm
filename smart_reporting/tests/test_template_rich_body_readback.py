"""从手造原生对象检验独立reader，不让消费者的生成回执自证。"""

from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree
from PIL import Image

MARKDOWN = '# 正文标题\n\n精确值 **1234.5600**。\n\n- 甲\n- 乙\n\n1. 第一\n2. 第二\n\n| 项目 | 原值 |\n| --- | --- |\n| 首表 | -12.3400 |\n\n![首图](first.png)\n\n| 月份 | 原值 |\n| --- | --- |\n| 末表 | 98.7600% |\n\n![末图](last.png)\n\n末段保留 7.8900 亿元。'


def image_bytes(color):
    stream = BytesIO()
    Image.new('RGB', (14, 11), color).save(stream, format='PNG')
    return stream.getvalue()


RESOURCES = {'first.png': image_bytes('red'), 'last.png': image_bytes('blue')}


def xpath(node, expression):
    return etree.XPath(expression, namespaces={'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})(node)


def native_case():
    doc = Document()
    doc.add_paragraph('模板前部业务说明')
    control, props, tag, body = [OxmlElement(name) for name in ('w:sdt', 'w:sdtPr', 'w:tag', 'w:sdtContent')]
    tag.set(qn('w:val'), 'report_content')
    props.append(tag)
    control.append(props)
    control.append(body)
    doc.element.body.insert(1, control)

    def move(paragraph):
        body.append(paragraph._p)
        return paragraph

    move(doc.add_heading('正文标题', 1))
    paragraph = move(doc.add_paragraph('精确值 '))
    paragraph.add_run('1234.5600').bold = True
    paragraph.add_run('。')
    numbering = doc.part.numbering_part.element
    for index, fmt in [(90, 'bullet'), (91, 'decimal')]:
        abstract = OxmlElement('w:abstractNum')
        abstract.set(qn('w:abstractNumId'), str(index))
        level = OxmlElement('w:lvl')
        level.set(qn('w:ilvl'), '0')
        for name, value in [('w:start', '1'), ('w:numFmt', fmt), ('w:lvlText', '•' if fmt == 'bullet' else '%1.')]:
            child = OxmlElement(name)
            child.set(qn('w:val'), value)
            level.append(child)
        abstract.append(level)
        numbering.append(abstract)
        num = OxmlElement('w:num')
        num.set(qn('w:numId'), str(index))
        ref = OxmlElement('w:abstractNumId')
        ref.set(qn('w:val'), str(index))
        num.append(ref)
        numbering.append(num)
        for text in (('甲', '乙') if fmt == 'bullet' else ('第一', '第二')):
            p = move(doc.add_paragraph(text))
            num_props = p._p.get_or_add_pPr().get_or_add_numPr()
            num_props.get_or_add_numId().val = index
            num_props.get_or_add_ilvl().val = 0
    for labels, name, alt in [(('项目', '原值', '首表', '-12.3400'), 'first.png', '首图'),
        (('月份', '原值', '末表', '98.7600%'), 'last.png', '末图')]:
        table = doc.add_table(rows=2, cols=2)
        for cell, value in zip((c for row in table.rows for c in row.cells), labels, strict=True):
            cell.text = value
        body.append(table._tbl)
        picture = move(doc.add_paragraph()).add_run().add_picture(BytesIO(RESOURCES[name]))
        picture._inline.docPr.set('descr', alt)
    move(doc.add_paragraph('末段保留 7.8900 亿元。'))
    doc.add_paragraph('模板末部说明')
    return doc, body


def packed(doc):
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def read(doc, markdown=MARKDOWN, resources=RESOURCES):
    from smart_reporting.reporting.delivery.template_body_readback import read_template_body

    return read_template_body(packed(doc), markdown, resources)


def test_complete_native_body_reads_all_objects_and_relationships():
    doc, _ = native_case()
    result = read(doc)
    assert result['status'] == 'passed'
    assert result['coverage'] == 'complete'
    assert len(result['scope']['mediaParts']) == 2
    assert len(result['scope']['relationshipIds']) == 2
    assert result['scope']['bodyTag'] == 'report_content'


@pytest.mark.parametrize('change', ['last_cell', 'last_row', 'last_picture', 'last_text', 'heading', 'numbering',
    'literal', 'hidden', 'inherited_hidden', 'field', 'duplicate_slot', 'missing_slot', 'relationship', 'swapped_image'])
def test_late_or_native_structure_fault_cannot_pass_by_text_presence(change):
    doc, body = native_case()
    if change == 'last_cell':
        xpath(body, './w:tbl')[-1].xpath('.//w:t')[-1].text = '98.7601%'
    elif change == 'last_row':
        table = xpath(body, './w:tbl')[-1]
        table.remove(table[-1])
    elif change == 'last_picture':
        paragraph = xpath(body, './w:p[w:r/w:drawing]')[-1]
        body.remove(paragraph)
    elif change == 'last_text':
        body[-1].xpath('.//w:t')[0].text = '末段保留 7.8901 亿元。'
    elif change == 'heading':
        body[0].find(qn('w:pPr')).remove(body[0].find(qn('w:pPr')).find(qn('w:pStyle')))
    elif change == 'numbering':
        xpath(body, './w:p[w:pPr/w:numPr]')[-1].xpath('./w:pPr/w:numPr/w:numId')[0].set(qn('w:val'), '9999')
    elif change == 'literal':
        for child in list(body):
            body.remove(child)
        paragraph = doc.add_paragraph(MARKDOWN)
        body.append(paragraph._p)
    elif change in ('hidden', 'field'):
        run = body[-1].xpath('./w:r')[0]
        if change == 'hidden':
            properties = OxmlElement('w:rPr')
            properties.append(OxmlElement('w:vanish'))
            run.insert(0, properties)
        else:
            field = OxmlElement('w:fldSimple')
            field.set(qn('w:instr'), 'DOCPROPERTY BusinessValue')
            body[-1].append(field)
    elif change == 'inherited_hidden':
        doc.styles['Normal'].font.hidden = True
    elif change == 'duplicate_slot':
        from copy import deepcopy

        doc.element.body.insert(0, deepcopy(body.getparent()))
    elif change == 'missing_slot':
        body.getparent().find(qn('w:sdtPr')).find(qn('w:tag')).set(qn('w:val'), 'other')
    elif change == 'relationship':
        body.xpath('.//*[local-name()="blip"]')[-1].set(qn('r:embed'), 'missing-rId')
    else:
        images = body.xpath('.//*[local-name()="blip"]')
        images[-1].set(qn('r:embed'), images[0].get(qn('r:embed')))
    result = read(doc)
    assert result['status'] in ('failed', 'unverified')
    assert result['coverage'] != 'complete' or result['status'] == 'failed'
    assert result['issues']


def test_missing_actual_resource_does_not_make_empty_expected_pass():
    doc, _ = native_case()
    assert read(doc, resources={'first.png': RESOURCES['first.png']})['status'] == 'unverified'


def test_expected_pdf_text_uses_visible_markdown_semantics():
    from smart_reporting.reporting.delivery.template_body_readback import expected_body_text

    text = expected_body_text(MARKDOWN)
    assert '正文标题' in text and '98.7600%' in text and '末段保留 7.8900 亿元。' in text
    assert '| --- |' not in text and '**1234.5600**' not in text and '](last.png)' not in text


def test_protocol_markers_are_not_body_objects_but_inline_code_keeps_its_literal():
    doc, body = native_case()
    source = '[[section:overview]]\n\n' + MARKDOWN.replace('末段保留 7.8900 亿元。',
        '末段保留 7.8900 亿元。[[citation:registered-1]]')
    assert read(doc, markdown=source)['status'] == 'passed'
    for child in list(body):
        body.remove(child)
    body.append(doc.add_paragraph('协议示例 [[citation:sample]]')._p)
    assert read(doc, markdown='协议示例 `[[citation:sample]]`', resources={})['status'] == 'passed'


@pytest.mark.parametrize('change', ['valid', 'missing_end', 'duplicate_id', 'duplicate_name', 'end_outside'])
def test_transparent_bookmarks_require_unique_paired_body_identity(change):
    doc, body = native_case()
    start, end = OxmlElement('w:bookmarkStart'), OxmlElement('w:bookmarkEnd')
    start.set(qn('w:id'), '501')
    start.set(qn('w:name'), 'body_heading')
    end.set(qn('w:id'), '501')
    body.insert(0, start)
    body.append(end)
    if change == 'missing_end':
        body.remove(end)
    elif change in ('duplicate_id', 'duplicate_name'):
        other, other_end = OxmlElement('w:bookmarkStart'), OxmlElement('w:bookmarkEnd')
        other.set(qn('w:id'), '501' if change == 'duplicate_id' else '502')
        other.set(qn('w:name'), 'other_name' if change == 'duplicate_id' else 'body_heading')
        other_end.set(qn('w:id'), other.get(qn('w:id')))
        doc.element.body.insert(0, other)
        doc.element.body.insert(1, other_end)
    elif change == 'end_outside':
        doc.element.body.insert(0, end)
    result = read(doc)
    assert result['status'] == ('passed' if change == 'valid' else 'failed')


def test_table_ending_body_allows_only_one_required_empty_native_tail():
    doc, body = native_case()
    tables = xpath(body, './w:tbl')
    for child in list(body):
        body.remove(child)
    body.append(tables[-1])
    body.append(OxmlElement('w:p'))
    source = '| 月份 | 原值 |\n| --- | --- |\n| 末表 | 98.7600% |'
    assert read(doc, markdown=source, resources={})['status'] == 'passed'
    body.append(OxmlElement('w:p'))
    assert read(doc, markdown=source, resources={})['status'] == 'failed'


@pytest.mark.parametrize('change', ['unknown_run', 'extra_drawing', 'table_node', 'inline_picture_position'])
def test_complete_coverage_does_not_silently_ignore_extra_native_objects(change):
    doc, body = native_case()
    if change == 'unknown_run':
        body[-1].xpath('./w:r')[0].append(OxmlElement('w:footnoteReference'))
    elif change == 'extra_drawing':
        xpath(body, './w:p[w:r/w:drawing]')[-1].xpath('./w:r')[0].append(OxmlElement('w:drawing'))
    elif change == 'table_node':
        xpath(body, './w:tbl')[-1].append(OxmlElement('w:customXml'))
    else:
        for child in list(body):
            body.remove(child)
        paragraph = doc.add_paragraph('前')
        paragraph.add_run().add_picture(BytesIO(RESOURCES['first.png']))
        paragraph.add_run('后')
        body.append(paragraph._p)
        source = '前![图](first.png)后'
        assert read(doc, markdown=source)['status'] == 'passed'
        paragraph._p.append(paragraph._p.xpath('./w:r')[1])
        assert read(doc, markdown=source)['status'] == 'failed'
        return
    assert read(doc)['status'] == 'failed'


def test_ordered_list_start_is_not_proved_by_text_and_numfmt_alone():
    doc, _ = native_case()
    level = doc.part.numbering_part.element.xpath('./w:abstractNum[@w:abstractNumId="91"]/w:lvl')[0]
    level.find(qn('w:start')).set(qn('w:val'), '3')
    source = MARKDOWN.replace('1. 第一\n2. 第二', '3. 第一\n4. 第二')
    assert read(doc, markdown=source)['status'] == 'passed'
    level.find(qn('w:start')).set(qn('w:val'), '1')
    assert read(doc, markdown=source)['status'] == 'failed'


def test_invalid_media_bytes_cannot_pass_by_matching_declared_resource():
    from smart_reporting.reporting.delivery.template_body_readback import read_template_body

    doc, body = native_case()
    image_id = body.xpath('.//*[local-name()="blip"]')[0].get(qn('r:embed'))
    part = str(doc.part.related_parts[image_id].partname).lstrip('/')
    output = BytesIO()
    with ZipFile(BytesIO(packed(doc))) as source, ZipFile(output, 'w') as target:
        for name in source.namelist():
            target.writestr(name, b'not-a-static-image' if name == part else source.read(name))
    result = read_template_body(output.getvalue(), MARKDOWN, {**RESOURCES, 'first.png': b'not-a-static-image'})
    assert result['status'] != 'passed'


def test_unreadable_package_returns_failed_detail_instead_of_raising():
    from smart_reporting.reporting.delivery.template_body_readback import read_template_body

    result = read_template_body(b'not-a-zip', MARKDOWN, RESOURCES)
    assert result['status'] == 'failed' and result['issues']


def test_media_bytes_change_is_detected_even_when_relationship_and_text_still_match():
    from smart_reporting.reporting.delivery.template_body_readback import read_template_body

    doc, body = native_case()
    image_id = body.xpath('.//*[local-name()="blip"]')[-1].get(qn('r:embed'))
    part = str(doc.part.related_parts[image_id].partname).lstrip('/')
    output = BytesIO()
    with ZipFile(BytesIO(packed(doc))) as source, ZipFile(output, 'w') as target:
        for name in source.namelist():
            target.writestr(name, RESOURCES['first.png'] if name == part else source.read(name))
    assert read_template_body(output.getvalue(), MARKDOWN, RESOURCES)['status'] == 'failed'


def management_case():
    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences

    doc, body = native_case()
    slot, props, tag, content = [OxmlElement(name) for name in ('w:sdt', 'w:sdtPr', 'w:tag', 'w:sdtContent')]
    tag.set(qn('w:val'), 'report_signature')
    props.append(tag)
    slot.extend((props, content))
    doc.element.body.insert(-1, slot)
    for value in ('实际署名', '2026-11-13', '完整说明'):
        content.append(doc.add_paragraph(value)._p)
    actual = packed(doc)
    for child in list(body):
        body.remove(child)
    body.append(doc.add_paragraph('{{report_content}}')._p)
    content[0].xpath('.//w:t')[0].text = '旧署名'
    original = packed(doc)
    # 原模板没有导入正文的依赖；reader必须逐条允许必要追加，不能全ZIP等长。
    output = BytesIO()
    with ZipFile(BytesIO(original)) as source, ZipFile(output, 'w') as target:
        for name in source.namelist():
            if name.startswith('word/media/'):
                continue
            raw = source.read(name)
            if name == 'word/_rels/document.xml.rels':
                root = etree.fromstring(raw)
                for node in list(root):
                    if node.get('Type', '').endswith('/image'):
                        root.remove(node)
                raw = etree.tostring(root)
            elif name == 'word/numbering.xml':
                root = etree.fromstring(raw)
                for node in list(root):
                    if node.get(qn('w:numId')) in ('90', '91') or node.get(qn('w:abstractNumId')) in ('90', '91'):
                        root.remove(node)
                raw = etree.tostring(root)
            target.writestr(name, raw)
    original = output.getvalue()
    preferences = FormatPreferences.model_validate({'common': {'signer': '实际署名', 'dateFormat': 'iso'},
        'word': {'signature': {'description': '完整说明'}}})
    resolved = resolve_format_preferences(preferences, 'word')
    frozen = {'markdown': MARKDOWN, 'state': {'_documentContext': {'title': '模板前部业务说明', 'generatedDate': '2026-11-13'}}}
    return original, actual, resolved, frozen


def test_management_reader_accepts_only_declared_rich_body_changes():
    from smart_reporting.management.preference_template_readback import read_template_document

    original, actual, resolved, frozen = management_case()
    result = read_template_document(actual, 'word', resolved, frozen, original, body_resources=RESOURCES)
    assert result['templateReadback']['body']['status'] == 'passed'
    assert result['templateReadback']['outsideDeclaredTargets']['status'] == 'passed'
    assert result['templateReadback']['signature']['status'] == 'passed'
    assert not any(check['passed'] is False for check in result['checks'])
    assert all('evidenceKind' not in check for check in result['checks'])
    assert result['templateReadback']['layoutValidation'] == 'unverified'


@pytest.mark.parametrize('change', ['existing_style', 'existing_relationship', 'extra_media', 'outside_text'])
def test_management_reader_does_not_exempt_whole_parts_for_rich_body(change):
    from smart_reporting.management.preference_template_readback import read_template_document

    original, actual, resolved, frozen = management_case()
    output = BytesIO()
    with ZipFile(BytesIO(actual)) as source, ZipFile(output, 'w') as target:
        for name in source.namelist():
            raw = source.read(name)
            if name == 'word/styles.xml' and change == 'existing_style':
                changed = raw.replace(b'w:val="Normal"', b'w:val="ChangedOriginal"', 1)
                assert changed != raw
                raw = changed
            elif name == 'word/_rels/document.xml.rels' and change == 'existing_relationship':
                raw = raw.replace(b'Target="fontTable.xml"', b'Target="elsewhere.xml"')
            elif name == 'word/document.xml' and change == 'outside_text':
                raw = raw.replace('模板末部说明'.encode(), '改写末部说明'.encode())
            target.writestr(name, raw)
        if change == 'extra_media':
            target.writestr('word/media/unrelated.png', RESOURCES['first.png'])
    result = read_template_document(output.getvalue(), 'word', resolved, frozen, original, body_resources=RESOURCES)
    assert result['templateReadback']['body']['status'] == 'passed'
    assert result['templateReadback']['outsideDeclaredTargets']['status'] == 'failed'


@pytest.mark.parametrize('reference', ['pStyle', 'rStyle', 'tblStyle', 'header', 'basedOn', 'link', 'next'])
def test_new_body_style_must_not_activate_original_dangling_style_reference(reference):
    from smart_reporting.management.preference_template_readback import read_template_document

    original, actual, resolved, frozen = management_case()

    def changed_package(raw, new_definition):
        with ZipFile(BytesIO(raw)) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        root = etree.fromstring(parts['word/document.xml'])
        styles = etree.fromstring(parts['word/styles.xml'])
        outside = xpath(root, './w:body/w:p')[0]
        if reference in ('pStyle', 'rStyle'):
            parent = outside.find(qn('w:pPr')) if reference == 'pStyle' else outside[0].find(qn('w:rPr'))
            if parent is None:
                parent = OxmlElement('w:pPr' if reference == 'pStyle' else 'w:rPr')
                (outside if reference == 'pStyle' else outside[0]).insert(0, parent)
            child = OxmlElement('w:' + reference)
            child.set(qn('w:val'), 'NewBodyStyle')
            parent.append(child)
        elif reference == 'tblStyle':
            table, props, style = [OxmlElement(name) for name in ('w:tbl', 'w:tblPr', 'w:tblStyle')]
            style.set(qn('w:val'), 'NewBodyStyle')
            props.append(style)
            table.append(props)
            outside.addprevious(table)
        elif reference == 'header':
            header = etree.Element(qn('w:hdr'), nsmap={'w': qn('w:hdr')[1:].split('}')[0]})
            paragraph, props, style = [OxmlElement(name) for name in ('w:p', 'w:pPr', 'w:pStyle')]
            style.set(qn('w:val'), 'NewBodyStyle')
            props.append(style)
            paragraph.append(props)
            header.append(paragraph)
            parts['word/header1.xml'] = etree.tostring(header)
        else:
            alias, name, dependency = [OxmlElement(tag) for tag in ('w:style', 'w:name', 'w:' + reference)]
            alias.set(qn('w:styleId'), 'OriginalUnusedAlias')
            alias.set(qn('w:type'), 'paragraph')
            name.set(qn('w:val'), 'Original unused alias')
            dependency.set(qn('w:val'), 'NewBodyStyle')
            alias.extend((name, dependency))
            styles.append(alias)
        if new_definition:
            style, name, base = [OxmlElement(tag) for tag in ('w:style', 'w:name', 'w:basedOn')]
            style.set(qn('w:styleId'), 'NewBodyStyle')
            style.set(qn('w:type'), 'paragraph')
            name.set(qn('w:val'), 'New body style')
            base.set(qn('w:val'), 'Normal')
            style.extend((name, base))
            styles.append(style)
            body = xpath(root, './/w:sdt[w:sdtPr/w:tag[@w:val="report_content"]]/w:sdtContent')[0]
            paragraph = xpath(body, './w:p')[1]
            properties = paragraph.find(qn('w:pPr'))
            if properties is None:
                properties = OxmlElement('w:pPr')
                paragraph.insert(0, properties)
            selected = OxmlElement('w:pStyle')
            selected.set(qn('w:val'), 'NewBodyStyle')
            properties.append(selected)
        parts['word/document.xml'] = etree.tostring(root)
        parts['word/styles.xml'] = etree.tostring(styles)
        output = BytesIO()
        with ZipFile(output, 'w') as archive:
            for name, value in parts.items():
                archive.writestr(name, value)
        return output.getvalue()

    result = read_template_document(changed_package(actual, True), 'word', resolved, frozen,
        changed_package(original, False), body_resources=RESOURCES)
    assert result['templateReadback']['body']['status'] == 'passed'
    assert result['templateReadback']['outsideDeclaredTargets']['status'] == 'failed'


@pytest.mark.parametrize('reference', ['numId', 'abstractNumId', 'relationship'])
def test_new_body_dependencies_cannot_activate_original_dangling_identity(reference):
    from smart_reporting.management.preference_template_readback import read_template_document

    original, actual, resolved, frozen = management_case()

    def insert_reference(raw):
        with ZipFile(BytesIO(raw)) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        root = etree.fromstring(parts['word/document.xml'])
        outside = xpath(root, './w:body/w:p')[0]
        if reference == 'numId':
            props, numbering, identity = [OxmlElement(name) for name in ('w:pPr', 'w:numPr', 'w:numId')]
            identity.set(qn('w:val'), '90')
            numbering.append(identity)
            props.append(numbering)
            outside.insert(0, props)
        elif reference == 'abstractNumId':
            numbers = etree.fromstring(parts['word/numbering.xml'])
            number, abstract = OxmlElement('w:num'), OxmlElement('w:abstractNumId')
            number.set(qn('w:numId'), '800')
            abstract.set(qn('w:val'), '90')
            number.append(abstract)
            numbers.append(number)
            parts['word/numbering.xml'] = etree.tostring(numbers)
        else:
            # 原模板悬空r:id在导入图片的新relationship出现后才被激活。
            with ZipFile(BytesIO(actual)) as archive:
                relationships = etree.fromstring(archive.read('word/_rels/document.xml.rels'))
            image_id = next(node.get('Id') for node in relationships if node.get('Type', '').endswith('/image'))
            link = OxmlElement('w:hyperlink')
            link.set(qn('r:id'), image_id)
            outside.append(link)
        parts['word/document.xml'] = etree.tostring(root)
        stream = BytesIO()
        with ZipFile(stream, 'w') as archive:
            for name, value in parts.items():
                archive.writestr(name, value)
        return stream.getvalue()

    result = read_template_document(insert_reference(actual), 'word', resolved, frozen,
        insert_reference(original), body_resources=RESOURCES)
    assert result['templateReadback']['body']['status'] == 'passed'
    assert result['templateReadback']['outsideDeclaredTargets']['status'] == 'failed'


def test_pdf_rich_body_uses_sample_and_never_claims_native_complete():
    import pymupdf

    from smart_reporting.management.preference_template_readback import read_template_document

    original, _, resolved, frozen = management_case()
    frozen['markdown'] = '# Visible title\n\n| Col | Value |\n| --- | --- |\n| last | 1.2300 |'
    frozen['state']['_documentContext']['title'] = 'Visible title'
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((40, 50), 'Visible title\nCol Value\nlast 1.2300\nActual signer 2026-11-13 Description')
    result = read_template_document(pdf.tobytes(), 'pdf', resolved, frozen, original, body_resources={})
    assert result['templateReadback']['body']['coverage'] == 'sample'
    assert result['templateReadback']['body']['status'] == 'sampled'
    assert all(check['coverage'] == 'sample' for check in result['checks'])
