"""真实 DOCX 桥接：对象绑定、允许操作和未修改部件保留。"""
from __future__ import annotations

import hashlib
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.shared import Inches, Pt, RGBColor
from PIL import Image


@pytest.fixture
def content(tmp_path):
    picture = tmp_path / 'image.png'
    Image.new('RGB', (32, 24), (20, 100, 160)).save(picture)
    doc = Document()
    doc.sections[0].header.paragraphs[0].text = '中文页眉，保留'
    doc.sections[0].footer.paragraphs[0].text = '中文页脚，保留'
    doc.add_heading('中文经营报告', level=1)
    para = doc.add_paragraph()
    para.add_run('原正文：').bold = True
    run = para.add_run('收入100万元')
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor.from_string('194361')
    doc.add_paragraph('未改段落')
    table = doc.add_table(rows=2, cols=2)
    table.style = 'Table Grid'
    for row, values in zip(table.rows, [('项目', '金额'), ('收入', '100')]):
        for cell, text in zip(row.cells, values):
            cell.text = text
    table.cell(1, 1).paragraphs[0].runs[0].bold = True
    doc.add_picture(str(picture), width=Inches(0.5))
    field = doc.add_paragraph()
    token = OxmlElement('w:fldSimple')
    from docx.oxml.ns import qn
    token.set(qn('w:instr'), 'PAGE')
    field._p.append(token)
    nested = doc.add_table(rows=1, cols=1)
    nested.cell(0, 0).text = '含嵌套表格外层'
    nested.cell(0, 0).add_table(rows=1, cols=1).cell(0, 0).text = '内层'
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def api():
    from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
    return inspect_docx, patch_docx


def paragraph(model):
    return next(block for block in model['blocks'] if block.get('text') == '原正文：收入100万元')


def operation(block, kind, **kwargs):
    return {'kind': kind, 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], **kwargs}


def test_docx_inspect_and_noop_preserve_original_bytes(content):
    inspect, patch = api()
    model = inspect(content)
    assert model['sourceSha256'] == hashlib.sha256(content).hexdigest()
    assert model['modelSource'] == 'genoffice-docx-engine:f8c17004fb730df11f0f743164ffd8b4281bb38c'
    assert paragraph(model)['editable'] is True
    assert next(b for b in model['blocks'] if b['type'] == 'image')['editable'] is False
    assert any(b.get('readOnlyReason') for b in model['blocks'])
    assert model == inspect(content)
    assert patch(content, []) == content


def test_docx_changes_text_and_cell_without_damaging_other_parts(content):
    inspect, patch = api()
    model = inspect(content)
    block = paragraph(model)
    table = next(b for b in model['blocks'] if b['type'] == 'table')
    cell = table['cells'][1][1]
    edited = patch(content, [
        operation(block, 'replaceParagraph', text='新正文：收入125万元'),
        operation(table, 'replaceCellText', cellId=cell['cellId'], expectedObjectSha256=cell['expectedObjectSha256'], text='125（已核对）'),
    ])
    doc = Document(BytesIO(edited))
    assert doc.paragraphs[1].text == '新正文：收入125万元'
    assert doc.tables[0].cell(1, 1).text == '125（已核对）'
    assert doc.tables[0].cell(1, 1).paragraphs[0].runs[0].bold is True
    assert len(doc.inline_shapes) == 1
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(edited)) as after:
        names = {name for name in before.namelist() if not name.endswith('/')}
        assert names == {name for name in after.namelist() if not name.endswith('/')}
        for name in names - {'word/document.xml', 'docProps/core.xml'}:
            assert before.read(name) == after.read(name), name
    original = Document(BytesIO(content))
    assert doc.paragraphs[2]._p.xml == original.paragraphs[2]._p.xml
    assert doc.sections[0]._sectPr.xml == original.sections[0]._sectPr.xml
    assert doc.tables[1]._tbl.xml == original.tables[1]._tbl.xml
    assert any(b.get('text') == '新正文：收入125万元' for b in inspect(edited)['blocks'])
    assert patch(edited, []) == edited


def test_docx_paragraph_style_insert_delete_and_reopen(content):
    inspect, patch = api()
    model = inspect(content)
    target = paragraph(model)
    removed = next(b for b in model['blocks'] if b.get('text') == '未改段落')
    edited = patch(content, [
        operation(target, 'formatParagraph', style={
            'bold': True, 'italic': True, 'underline': True, 'strike': True,
            'fontFamily': 'Microsoft YaHei', 'fontSize': 16, 'color': 'AABBCC',
        }),
        operation(target, 'insertParagraph', position='after', text='新增中文段落'),
        operation(removed, 'deleteParagraph'),
    ])
    doc = Document(BytesIO(edited))
    assert '未改段落' not in [p.text for p in doc.paragraphs]
    assert doc.paragraphs[2].text == '新增中文段落'
    assert doc.paragraphs[1].text == '原正文：收入100万元'
    assert doc.paragraphs[1].runs[0].bold is True
    for run in doc.paragraphs[1].runs:
        assert run.bold is True
        assert run.italic is True
        assert run.underline is True
        assert run.font.strike is True
        assert run.font.name == 'Microsoft YaHei'
        assert run.font.size == Pt(16)
        assert str(run.font.color.rgb) == 'AABBCC'


@pytest.mark.parametrize('alignment,logical', [('left', 'left'), ('center', 'center'), ('right', 'right'), ('justify', 'both')])
@pytest.mark.parametrize('rtl', [False, True])
def test_docx_paragraph_alignment_roundtrip_preserves_other_properties(alignment, logical, rtl):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    inspect, patch = api()
    document = Document()
    document.styles['Normal'].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph = document.add_paragraph('保留正文与格式')
    paragraph.paragraph_format.left_indent = Inches(0.25)
    paragraph.paragraph_format.space_after = Pt(9)
    paragraph.paragraph_format.keep_with_next = True
    paragraph.add_run('加粗').bold = True
    if rtl:
        paragraph._p.get_or_add_pPr().append(OxmlElement('w:bidi'))
    document.add_paragraph('未修改段落')
    stream = BytesIO()
    document.save(stream)
    source = stream.getvalue()
    target = inspect(source)['blocks'][0]
    result = patch(source, [operation(target, 'setParagraphAlignment', alignment=alignment)])
    reopened = Document(BytesIO(result))
    changed = reopened.paragraphs[0]
    expected = {'left': WD_ALIGN_PARAGRAPH.LEFT, 'center': WD_ALIGN_PARAGRAPH.CENTER,
                'right': WD_ALIGN_PARAGRAPH.RIGHT, 'both': WD_ALIGN_PARAGRAPH.JUSTIFY}
    physical = ('right' if logical == 'left' else 'left') if rtl and logical in {'left', 'right'} else logical
    assert changed.alignment == expected[physical]
    assert changed.text == paragraph.text
    assert changed.runs[-1].bold is True
    assert changed.paragraph_format.left_indent == paragraph.paragraph_format.left_indent
    assert changed.paragraph_format.space_after == Pt(9)
    assert changed.paragraph_format.keep_with_next is True
    assert bool(changed._p.xpath('./w:pPr/w:bidi')) is rtl
    assert changed._p.xpath('./w:pPr/w:jc')[0].get(qn('w:val')) == physical
    assert reopened.paragraphs[1]._p.xml == document.paragraphs[1]._p.xml
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name


@pytest.mark.parametrize('alignment', ['distribute', None, 1, '<w:evil/>'])
def test_docx_paragraph_alignment_rejects_invalid_values(content, alignment):
    inspect, patch = api()
    target = paragraph(inspect(content))
    with pytest.raises(ValueError, match='alignment_invalid'):
        patch(content, [operation(target, 'setParagraphAlignment', alignment=alignment)])


@pytest.mark.parametrize('alignment_first', [False, True])
def test_docx_paragraph_alignment_composes_with_text_and_character_format(content, alignment_first):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    inspect, patch = api()
    target = paragraph(inspect(content))
    alignment = operation(target, 'setParagraphAlignment', alignment='right')
    changes = [operation(target, 'replaceParagraph', text='修改后的经营报告'),
               operation(target, 'formatParagraph', style={'bold': True, 'fontSize': 18})]
    edited = patch(content, [alignment, *changes] if alignment_first else [*changes, alignment])
    result = Document(BytesIO(edited)).paragraphs[1]
    assert result.alignment == WD_ALIGN_PARAGRAPH.RIGHT
    assert result.text == '修改后的经营报告'
    assert all(run.bold is True and run.font.size == Pt(18) for run in result.runs)


@pytest.mark.parametrize('kind', ['bullet', 'ordered'])
def test_docx_native_lists_create_definition_continue_and_remove(content, kind):
    from docx.oxml.ns import qn
    inspect, patch = api()
    original = inspect(content)
    targets = [paragraph(original), next(block for block in original['blocks'] if block.get('text') == '未改段落')]
    edited = patch(content, [operation(target, 'setParagraphList', list=kind) for target in targets])
    reopened = inspect(edited)
    listed = [block for block in reopened['blocks'] if block.get('text') in [target['text'] for target in targets]]
    assert all(block['type'] == 'listItem' for block in listed)
    doc = Document(BytesIO(edited))
    refs = [p._p.xpath('./w:pPr/w:numPr/w:numId')[0].get(qn('w:val')) for p in doc.paragraphs[1:3]]
    assert refs[0] == refs[1]
    with ZipFile(BytesIO(edited)) as archive:
        from lxml import etree
        numbering = etree.fromstring(archive.read('word/numbering.xml'))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        abstract = numbering.xpath(f'./w:num[@w:numId="{refs[0]}"]/w:abstractNumId/@w:val', namespaces=ns)[0]
        fmt = numbering.xpath(f'./w:abstractNum[@w:abstractNumId="{abstract}"]/w:lvl[@w:ilvl="0"]/w:numFmt/@w:val', namespaces=ns)[0]
        assert fmt == ('bullet' if kind == 'bullet' else 'decimal')
    removed = patch(edited, [operation(listed[0], 'setParagraphList', list='none')])
    assert next(block for block in inspect(removed)['blocks'] if block.get('text') == targets[0]['text'])['type'] == 'paragraph'
    assert next(block for block in inspect(removed)['blocks'] if block.get('text') == targets[1]['text'])['type'] == 'listItem'
    assert Document(BytesIO(removed)).paragraphs[1].runs[0].bold is True
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(edited)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'word/numbering.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name


@pytest.mark.parametrize('kind', ['bullet', 'ordered'])
def test_docx_native_lists_create_missing_numbering_part_without_id_collisions(kind):
    from lxml import etree
    document = Document()
    document.add_paragraph('没有编号部件的正文')
    raw = BytesIO()
    document.save(raw)
    clean = BytesIO()
    ns = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships', 'ct': 'http://schemas.openxmlformats.org/package/2006/content-types'}
    with ZipFile(raw) as source, ZipFile(clean, 'w') as target:
        for name in source.namelist():
            if name == 'word/numbering.xml':
                continue
            data = source.read(name)
            if name in {'word/_rels/document.xml.rels', '[Content_Types].xml'}:
                root = etree.fromstring(data)
                for element in root.xpath('./r:Relationship[contains(@Type,"/numbering")]|./ct:Override[@PartName="/word/numbering.xml"]', namespaces=ns):
                    root.remove(element)
                data = etree.tostring(root)
            target.writestr(name, data)
    inspect, patch = api()
    source = clean.getvalue()
    block = inspect(source)['blocks'][0]
    result = patch(source, [operation(block, 'setParagraphList', list=kind)])
    assert inspect(result)['blocks'][0]['list']['kind'] == kind
    with ZipFile(BytesIO(result)) as archive:
        root = etree.fromstring(archive.read('word/numbering.xml'))
        ids = root.xpath('./w:num/@w:numId', namespaces={'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
        assert len(ids) == len(set(ids))


@pytest.mark.parametrize('list_value', ['invalid', None, '<w:numPr/>', 1])
def test_docx_native_lists_reject_untrusted_values(content, list_value):
    inspect, patch = api()
    target = paragraph(inspect(content))
    with pytest.raises(ValueError, match='list_invalid'):
        patch(content, [operation(target, 'setParagraphList', list=list_value)])


def test_docx_native_lists_remove_inherited_numbering_and_keep_property_order():
    from docx.oxml.ns import qn
    inspect, patch = api()
    document = Document()
    paragraph = document.add_paragraph('继承项目符号', style='List Bullet')
    paragraph.paragraph_format.keep_with_next = True
    paragraph.paragraph_format.space_after = Pt(8)
    raw = BytesIO()
    document.save(raw)
    source = raw.getvalue()
    target = inspect(source)['blocks'][0]
    assert target['type'] == 'listItem'
    removed = patch(source, [operation(target, 'setParagraphList', list='none')])
    assert inspect(removed)['blocks'][0]['type'] == 'paragraph'
    p = Document(BytesIO(removed)).paragraphs[0]
    assert p._p.xpath('./w:pPr/w:numPr/w:numId')[0].get(qn('w:val')) == '0'
    assert p.paragraph_format.keep_with_next is True
    assert p.paragraph_format.space_after == Pt(8)
    tags = [element.tag.rsplit('}', 1)[-1] for element in p._p.pPr]
    assert tags.index('keepNext') < tags.index('numPr') < tags.index('spacing')


def _multilevel_list_docx():
    from docx.oxml.ns import qn
    doc = Document()
    numbering = doc.part.numbering_part.element
    abstract_id = max((int(item.get(qn('w:abstractNumId'))) for item in numbering.findall(qn('w:abstractNum'))), default=-1) + 1
    num_id = max((int(item.get(qn('w:numId'))) for item in numbering.findall(qn('w:num'))), default=0) + 1
    abstract = OxmlElement('w:abstractNum')
    abstract.set(qn('w:abstractNumId'), str(abstract_id))
    for level_index, fmt in enumerate(('bullet', 'bullet', 'decimal')):
        level = OxmlElement('w:lvl')
        level.set(qn('w:ilvl'), str(level_index))
        start = OxmlElement('w:start'); start.set(qn('w:val'), '1'); level.append(start)
        num_fmt = OxmlElement('w:numFmt'); num_fmt.set(qn('w:val'), fmt); level.append(num_fmt)
        text = OxmlElement('w:lvlText'); text.set(qn('w:val'), '•' if fmt == 'bullet' else '%1.'); level.append(text)
        abstract.append(level)
    numbering.append(abstract)
    num = OxmlElement('w:num'); num.set(qn('w:numId'), str(num_id))
    abstract_ref = OxmlElement('w:abstractNumId'); abstract_ref.set(qn('w:val'), str(abstract_id)); num.append(abstract_ref)
    numbering.append(num)
    for value, ilvl in [('目标列表项', 0), ('保留的同列表项', 0)]:
        paragraph = doc.add_paragraph(value)
        ppr = paragraph._p.get_or_add_pPr()
        num_pr = OxmlElement('w:numPr')
        level_ref = OxmlElement('w:ilvl'); level_ref.set(qn('w:val'), str(ilvl)); num_pr.append(level_ref)
        num_ref = OxmlElement('w:numId'); num_ref.set(qn('w:val'), str(num_id)); num_pr.append(num_ref)
        ppr.append(num_pr)
    stream = BytesIO(); doc.save(stream)
    return stream.getvalue()


def test_docx_native_list_level_changes_ilvl_only_and_roundtrips():
    from docx.oxml.ns import qn
    inspect, patch = api()
    source = _multilevel_list_docx()
    model = inspect(source)
    target = next(block for block in model['blocks'] if block.get('text') == '目标列表项')
    other = next(block for block in model['blocks'] if block.get('text') == '保留的同列表项')
    source_num_id = target['list']['numId']
    result = patch(source, [operation(target, 'setParagraphListLevel', ilvl=1)])
    reopened = inspect(result)
    changed = next(block for block in reopened['blocks'] if block.get('text') == '目标列表项')
    unchanged = next(block for block in reopened['blocks'] if block.get('text') == '保留的同列表项')
    assert changed['list'] == {'kind': 'bullet', 'numId': source_num_id, 'ilvl': 1}
    assert unchanged['list'] == other['list']
    doc = Document(BytesIO(result))
    num_ref = doc.paragraphs[0]._p.xpath('./w:pPr/w:numPr/w:numId')[0].get(qn('w:val'))
    level_ref = doc.paragraphs[0]._p.xpath('./w:pPr/w:numPr/w:ilvl')[0].get(qn('w:val'))
    assert num_ref == source_num_id and level_ref == '1'
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name


@pytest.mark.parametrize(('ilvl', 'reason'), [(4, 'list_level_unsupported'), (2, 'list_level_unsupported')])
def test_docx_native_list_level_rejects_missing_or_incompatible_target(content, ilvl, reason):
    inspect, patch = api()
    source = _multilevel_list_docx()
    target = next(block for block in inspect(source)['blocks'] if block.get('text') == '目标列表项')
    with pytest.raises(ValueError, match=reason):
        patch(source, [operation(target, 'setParagraphListLevel', ilvl=ilvl)])


def test_docx_native_trailing_section_layout_roundtrips_page_setup_and_header_footer_distances():
    from docx.oxml.ns import qn
    doc = Document()
    section = doc.sections[0]
    section.page_width = Inches(8.5); section.page_height = Inches(11)
    section.top_margin = Inches(1); section.right_margin = Inches(1)
    section.bottom_margin = Inches(1); section.left_margin = Inches(1)
    section.header_distance = Inches(0.5); section.footer_distance = Inches(0.5)
    doc.add_paragraph('页面设置正文')
    source_file = BytesIO(); doc.save(source_file)
    source = source_file.getvalue()
    inspect, patch = api()
    model = inspect(source)
    section_anchor = model['sections'][-1]
    assert section_anchor['settings']['columns'] == 1
    result = patch(source, [{
        'kind': 'setSectionLayout', 'sectionId': section_anchor['sectionId'],
        'expectedSectionSha256': section_anchor['expectedSectionSha256'],
        'values': {
            'orientation': 'landscape', 'pageWidth': 15840, 'pageHeight': 12240,
            'marginTop': 900, 'marginRight': 1000, 'marginBottom': 1100, 'marginLeft': 1200,
            'columns': 2, 'headerDist': 600, 'footerDist': 650,
        },
    }])
    updated = inspect(result)['sections'][-1]['settings']
    assert {key: updated[key] for key in ['orientation', 'pageWidth', 'pageHeight', 'marginTop', 'marginRight', 'marginBottom', 'marginLeft', 'columns', 'headerDist', 'footerDist']} == {
        'orientation': 'landscape', 'pageWidth': 15840, 'pageHeight': 12240,
        'marginTop': 900, 'marginRight': 1000, 'marginBottom': 1100, 'marginLeft': 1200,
        'columns': 2, 'headerDist': 600, 'footerDist': 650,
    }
    reopened = Document(BytesIO(result)).sections[0]
    assert reopened.orientation == 1
    assert reopened.page_width.twips == 15840 and reopened.page_height.twips == 12240
    assert reopened.top_margin.twips == 900 and reopened.right_margin.twips == 1000
    assert reopened.bottom_margin.twips == 1100 and reopened.left_margin.twips == 1200
    assert reopened.header_distance.twips == 600 and reopened.footer_distance.twips == 650
    assert reopened._sectPr.xpath('./w:cols')[0].get(qn('w:num')) == '2'
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name


def test_docx_native_section_layout_rejects_invalid_values():
    doc = Document(); doc.add_paragraph('正文')
    raw = BytesIO(); doc.save(raw); source = raw.getvalue()
    inspect, patch = api()
    section_anchor = inspect(source)['sections'][-1]
    with pytest.raises(ValueError, match='section_anchor_invalid'):
        patch(source, [{
            'kind': 'setSectionLayout', 'sectionId': 'forged',
            'expectedSectionSha256': section_anchor['expectedSectionSha256'], 'values': {'columns': 2},
        }])
    for values in [{'columns': 4}, {'marginLeft': -1}, {'pageWidth': 0}, {'unexpected': 1}]:
        with pytest.raises(ValueError):
            patch(source, [{
                'kind': 'setSectionLayout', 'sectionId': section_anchor['sectionId'],
                'expectedSectionSha256': section_anchor['expectedSectionSha256'], 'values': values,
            }])


def test_docx_native_paragraph_spacing_roundtrips_source_values_and_preserves_other_formatting(content):
    from docx.oxml.ns import qn
    inspect, patch = api()
    source = Document(BytesIO(content))
    target_para = source.add_paragraph('段落间距目标')
    target_para.paragraph_format.space_before = Pt(0)
    target_para.paragraph_format.space_after = Pt(6)
    target_para.paragraph_format.line_spacing = 1.5
    target_para.paragraph_format.left_indent = Inches(0.25)
    target_para.paragraph_format.keep_with_next = True
    target_para.runs[0].bold = True
    raw = BytesIO(); source.save(raw); original = raw.getvalue()
    target = next(block for block in inspect(original)['blocks'] if block.get('text') == '段落间距目标')
    result = patch(original, [operation(target, 'setParagraphSpacing', spaceBefore=240, spaceAfter=0, lineSpacing=2)])
    reopened = Document(BytesIO(result))
    changed = next(paragraph for paragraph in reopened.paragraphs if paragraph.text == '段落间距目标')
    assert changed.paragraph_format.space_before.twips == 240
    assert changed.paragraph_format.space_after.twips == 0
    assert changed.paragraph_format.line_spacing == 2
    assert changed.paragraph_format.left_indent.twips == 360
    assert changed.paragraph_format.keep_with_next is True
    assert changed.runs[0].bold is True
    spacing = changed._p.pPr.find(qn('w:spacing'))
    assert spacing.get(qn('w:before')) == '240'
    assert spacing.get(qn('w:after')) == '0'
    assert spacing.get(qn('w:line')) == '480'
    assert spacing.get(qn('w:lineRule')) == 'auto'
    with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(result)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name


@pytest.mark.parametrize('values', [
    {'spaceBefore': 120}, {'spaceAfter': -1}, {'lineSpacing': 1.2},
    {'lineSpacing': 4}, {'spaceBeforeAuto': True}, {'lineRule': 'exact'},
])
def test_docx_native_paragraph_spacing_rejects_unmodeled_or_out_of_source_values(content, values):
    inspect, patch = api()
    target = paragraph(inspect(content))
    with pytest.raises(ValueError, match='paragraph_spacing_invalid'):
        patch(content, [operation(target, 'setParagraphSpacing', **values)])


@pytest.mark.parametrize('rule,raw_line', [('exact', 360), ('atLeast', 360), ('atLeast', 0)])
@pytest.mark.parametrize('values', [{'spaceBefore': 240}, {'lineSpacing': 2}])
def test_docx_native_spacing_preserves_untouched_raw_spacing_groups(rule, raw_line, values):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    inspect, patch = api()
    source = Document()
    para = source.add_paragraph('原始段落间距')
    spacing = OxmlElement('w:spacing')
    raw_attrs = {'before': '0', 'beforeLines': '120', 'beforeAutospacing': '1',
                 'after': '0', 'afterLines': '150', 'afterAutospacing': '1',
                 'line': str(raw_line), 'lineRule': rule, 'contextualSpacing': '1'}
    for key, value in raw_attrs.items():
        spacing.set(qn(f'w:{key}'), value)
    para._p.get_or_add_pPr().append(spacing)
    para.paragraph_format.keep_with_next = True
    raw = BytesIO(); source.save(raw); original = raw.getvalue()
    target = next(block for block in inspect(original)['blocks'] if block.get('text') == '原始段落间距')
    result = patch(original, [operation(target, 'setParagraphSpacing', **values)])
    changed = Document(BytesIO(result)).paragraphs[0]
    updated = changed._p.pPr.find(qn('w:spacing'))
    assert updated is not None
    expected = dict(raw_attrs)
    if 'spaceBefore' in values:
        expected['before'] = '240'
        expected.pop('beforeLines')
        expected.pop('beforeAutospacing')
    else:
        expected.update(line='480', lineRule='auto')
    assert dict(updated.attrib) == {qn(f'w:{key}'): value for key, value in expected.items()}
    assert changed.paragraph_format.keep_with_next is True


def test_docx_native_spacing_removes_before_even_when_style_has_before_spacing():
    inspect, patch = api()
    source = Document()
    source.styles['Normal'].paragraph_format.space_before = Pt(18)
    para = source.add_paragraph('删除段前间距')
    para.paragraph_format.space_before = Pt(12)
    raw = BytesIO(); source.save(raw)
    original = raw.getvalue()
    target = next(block for block in inspect(original)['blocks'] if block.get('text') == '删除段前间距')
    result = patch(original, [operation(target, 'setParagraphSpacing', spaceBefore=0)])
    assert Document(BytesIO(result)).paragraphs[0].paragraph_format.space_before == Pt(0)


@pytest.mark.parametrize('side', ['before', 'after'])
def test_docx_native_spacing_clears_auto_even_when_literal_spacing_is_unchanged(side):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    inspect, patch = api()
    source = Document()
    para = source.add_paragraph('取消自动间距')
    spacing = OxmlElement('w:spacing')
    spacing.set(qn(f'w:{side}'), '240')
    spacing.set(qn(f'w:{side}Autospacing'), '1')
    para._p.get_or_add_pPr().append(spacing)
    raw = BytesIO(); source.save(raw); original = raw.getvalue()
    target = next(block for block in inspect(original)['blocks'] if block.get('text') == '取消自动间距')
    result = patch(original, [operation(target, 'setParagraphSpacing', **{f'space{side.title()}': 240})])
    changed = Document(BytesIO(result)).paragraphs[0]._p.pPr.find(qn('w:spacing'))
    assert changed.get(qn(f'w:{side}')) == '240'
    assert changed.get(qn(f'w:{side}Autospacing')) is None


@pytest.mark.parametrize('twips', [0, 720, 1440])
def test_docx_paragraph_indent_roundtrip_preserves_other_indents_and_style(twips):
    from docx.oxml.ns import qn
    inspect, patch = api()
    document = Document()
    document.styles['Normal'].paragraph_format.left_indent = Inches(0.5)
    paragraph = document.add_paragraph('正文缩进')
    paragraph.paragraph_format.left_indent = Inches(0.25)
    paragraph.paragraph_format.right_indent = Inches(0.75)
    paragraph.paragraph_format.first_line_indent = Inches(-0.1)
    paragraph.paragraph_format.space_after = Pt(9)
    paragraph.paragraph_format.keep_with_next = True
    paragraph.runs[0].bold = True
    paragraph._p.pPr.ind.set(qn('w:leftChars'), '200')
    paragraph._p.pPr.ind.set(qn('w:firstLineChars'), '100')
    document.add_paragraph('不改的段落')
    raw = BytesIO()
    document.save(raw)
    source = raw.getvalue()
    result = patch(source, [operation(inspect(source)['blocks'][0], 'setParagraphIndent', twips=twips)])
    reopened = Document(BytesIO(result))
    changed = reopened.paragraphs[0]
    assert changed.paragraph_format.left_indent.twips == twips
    assert changed.paragraph_format.right_indent == paragraph.paragraph_format.right_indent
    assert changed.paragraph_format.first_line_indent == paragraph.paragraph_format.first_line_indent
    assert changed._p.pPr.ind.get(qn('w:leftChars')) == '0'
    assert changed._p.pPr.ind.get(qn('w:firstLineChars')) == '100'
    assert changed.paragraph_format.space_after == Pt(9)
    assert changed.paragraph_format.keep_with_next is True
    assert changed.runs[0].bold is True
    assert reopened.paragraphs[1]._p.xml == document.paragraphs[1]._p.xml
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name


@pytest.mark.parametrize('twips', [-1, 300, 15000, 720.5, True, '720'])
def test_docx_paragraph_indent_rejects_non_stop_values(content, twips):
    inspect, patch = api()
    with pytest.raises(ValueError, match='indent_invalid'):
        patch(content, [operation(paragraph(inspect(content)), 'setParagraphIndent', twips=twips)])


@pytest.mark.parametrize('twips', [0, 360, 720, -120])
def test_docx_paragraph_right_indent_roundtrip_preserves_other_indents_and_style(twips):
    from docx.oxml.ns import qn
    inspect, patch = api()
    document = Document()
    paragraph = document.add_paragraph('正文右缩进')
    paragraph.paragraph_format.left_indent = Inches(0.25)
    paragraph.paragraph_format.right_indent = Inches(0.75)
    paragraph.paragraph_format.first_line_indent = Inches(-0.1)
    paragraph.paragraph_format.space_after = Pt(9)
    paragraph.paragraph_format.keep_with_next = True
    paragraph.runs[0].bold = True
    paragraph._p.pPr.ind.set(qn('w:rightChars'), '200')
    paragraph._p.pPr.ind.set(qn('w:leftChars'), '100')
    document.add_paragraph('不改的段落')
    raw = BytesIO()
    document.save(raw)
    source = raw.getvalue()
    result = patch(source, [operation(inspect(source)['blocks'][0], 'setParagraphRightIndent', twips=twips)])
    reopened = Document(BytesIO(result))
    changed = reopened.paragraphs[0]
    assert changed.paragraph_format.right_indent.twips == twips
    assert changed.paragraph_format.left_indent == paragraph.paragraph_format.left_indent
    assert changed.paragraph_format.first_line_indent == paragraph.paragraph_format.first_line_indent
    assert changed._p.pPr.ind.get(qn('w:rightChars')) == '0'
    assert changed._p.pPr.ind.get(qn('w:leftChars')) == '100'
    assert changed.paragraph_format.space_after == Pt(9)
    assert changed.paragraph_format.keep_with_next is True
    assert changed.runs[0].bold is True
    assert reopened.paragraphs[1]._p.xml == document.paragraphs[1]._p.xml
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(result)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name


@pytest.mark.parametrize('twips', [-14401, 14401, 720.5, True, '360'])
def test_docx_paragraph_right_indent_rejects_values_outside_twip_range(content, twips):
    inspect, patch = api()
    with pytest.raises(ValueError, match='right_indent_invalid'):
        patch(content, [operation(paragraph(inspect(content)), 'setParagraphRightIndent', twips=twips)])


@pytest.mark.parametrize('mutation', ['wrong-hash', 'wrong-id', 'cross-source', 'xml', 'unknown-style'])
def test_docx_rejects_stale_or_untrusted_operations(content, mutation):
    inspect, patch = api()
    block = paragraph(inspect(content))
    op = operation(block, 'replaceParagraph', text='不得写入')
    source = content
    if mutation == 'wrong-hash':
        op['expectedObjectSha256'] = '0' * 64
    elif mutation == 'wrong-id':
        op['blockId'] = 'not-a-block'
    elif mutation == 'cross-source':
        source = patch(content, [operation(block, 'insertParagraph', position='after', text='另一个文件')])
    elif mutation == 'xml':
        op['xml'] = '<w:p/>'
    else:
        op = operation(block, 'formatParagraph', style={'rawRPr': '<w:rPr/>'})
    with pytest.raises(ValueError, match='docx_'):
        patch(source, [op])


def test_docx_rejects_complex_cell_and_unauthorized_picture(content):
    inspect, patch = api()
    model = inspect(content)
    nested = [b for b in model['blocks'] if b['type'] == 'table'][1]
    cell = nested['cells'][0][0]
    assert cell['editable'] is False
    with pytest.raises(ValueError, match='docx_.*unsupported'):
        patch(content, [operation(nested, 'replaceCellText', cellId=cell['cellId'], expectedObjectSha256=cell['expectedObjectSha256'], text='不能静默成功')])
    image = next(b for b in model['blocks'] if b['type'] == 'image')
    with pytest.raises(ValueError, match='docx_.*unsupported'):
        patch(content, [operation(image, 'replaceImage', path='/tmp/foreign.png')])


@pytest.mark.parametrize('source', [b'', b'not a docx', b'PK\x03\x04broken'])
def test_docx_corrupt_input_is_rejected(source):
    inspect, patch = api()
    with pytest.raises(ValueError, match='docx_'):
        inspect(source)
    with pytest.raises(ValueError, match='docx_'):
        patch(source, [])


def test_docx_empty_paragraph_remains_editable_and_same_anchor_ops_are_ordered():
    inspect, patch = api()
    document = Document()
    document.add_paragraph('')
    stream = BytesIO()
    document.save(stream)
    source = stream.getvalue()
    target = inspect(source)['blocks'][0]
    assert target['editable'] is True
    edited = patch(source, [
        operation(target, 'replaceParagraph', text='第一稿'),
        operation(target, 'replaceParagraph', text='第二稿'),
        operation(target, 'formatParagraph', style={'bold': True}),
        operation(target, 'insertParagraph', position='after', text='新增一'),
        operation(target, 'insertParagraph', position='after', text='新增二'),
    ])
    reopened = Document(BytesIO(edited))
    assert [p.text for p in reopened.paragraphs] == ['第二稿', '新增一', '新增二']
    assert reopened.paragraphs[0].runs[0].bold is True


def test_docx_cell_level_content_control_cannot_be_flattened():
    inspect, patch = api()
    document = Document()
    cell = document.add_table(rows=1, cols=1).cell(0, 0)
    cell.text = '受保护单元格'
    sdt = OxmlElement('w:sdt')
    sdt.append(OxmlElement('w:sdtPr'))
    sdt_content = OxmlElement('w:sdtContent')
    sdt_content.append(cell.paragraphs[0]._p)
    sdt.append(sdt_content)
    cell._tc.append(sdt)
    stream = BytesIO()
    document.save(stream)
    source = stream.getvalue()
    table = inspect(source)['blocks'][0]
    target = table['cells'][0][0]
    assert target['editable'] is False
    with pytest.raises(ValueError, match='docx_cell_unsupported'):
        patch(source, [operation(table, 'replaceCellText', cellId=target['cellId'], expectedObjectSha256=target['expectedObjectSha256'], text='不得展平')])


@pytest.mark.parametrize('alias', ['same', 'symlink', 'hardlink'])
def test_docx_cli_refuses_overwriting_source(content, tmp_path, alias):
    import json
    import subprocess
    from pathlib import Path
    source = tmp_path / 'source.docx'
    source.write_bytes(content)
    output = source
    if alias != 'same':
        output = tmp_path / 'alias.docx'
        if alias == 'symlink':
            output.symlink_to(source)
        else:
            output.hardlink_to(source)
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({'kind': 'patch', 'input': str(source), 'output': str(output), 'operations': []}))
    engine = Path(__file__).parents[1] / 'slides_engine'
    result = subprocess.run(['node', str(engine / 'dist/edit-docx.mjs'), str(request)], cwd=engine, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'docx_output_overwrites_source' in result.stderr
    assert source.read_bytes() == content


@pytest.mark.parametrize('kind', ['inspect-source', 'patch-source', 'patch-size', 'patch-sha'])
def test_docx_wrapper_rejects_inconsistent_receipt(content, monkeypatch, kind):
    import json
    from pathlib import Path
    from subprocess import CompletedProcess
    from smart_reporting.reporting.delivery import docx_native
    def bridge(_engine, _script, request):
        payload = json.loads(Path(request).read_text())
        receipt = {'sourceSha256': hashlib.sha256(content).hexdigest(), 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
        if 'source' in kind:
            receipt['sourceSha256'] = '0' * 64
        elif kind == 'patch-size':
            receipt['size'] += 1
        else:
            receipt['sha256'] = '0' * 64
        if 'output' in payload:
            Path(payload['output']).write_bytes(content)
        return CompletedProcess([], 0, json.dumps(receipt), '')
    monkeypatch.setattr(docx_native, 'run_bridge', bridge)
    with pytest.raises(ValueError, match='docx_.*identity'):
        if kind.startswith('inspect'):
            docx_native.inspect_docx(content)
        else:
            docx_native.patch_docx(content, [])


def test_docx_silent_cell_patch_failure_is_not_reported_as_success(content, tmp_path):
    import json
    import subprocess
    from pathlib import Path
    inspect, _ = api()
    table = next(b for b in inspect(content)['blocks'] if b['type'] == 'table')
    cell = table['cells'][1][1]
    engine = Path(__file__).parents[1] / 'slides_engine'
    isolated = tmp_path / 'isolated'
    (isolated / 'bridge').mkdir(parents=True)
    for name in ('node_modules', 'packages', 'package.json'):
        (isolated / name).symlink_to(engine / name, target_is_directory=(engine / name).is_dir())
    script = (engine / 'bridge/edit-docx.ts').read_text().replace(
        'parseDocx, saveDocx, patchTableCellTexts,', 'parseDocx, saveDocx,',
    ).replace('type ObjectValue =', 'const patchTableCellTexts = (xml: string, _grid: unknown) => xml\ntype ObjectValue =')
    (isolated / 'bridge/edit-docx.ts').write_text(script)
    source, output, request = tmp_path / 'source.docx', tmp_path / 'edited.docx', tmp_path / 'request.json'
    source.write_bytes(content)
    request.write_text(json.dumps({'kind': 'patch', 'input': str(source), 'output': str(output), 'operations': [
        operation(table, 'replaceCellText', cellId=cell['cellId'], expectedObjectSha256=cell['expectedObjectSha256'], text='必须真正写入'),
    ]}))
    result = subprocess.run([str(engine / 'node_modules/.bin/tsx'), str(isolated / 'bridge/edit-docx.ts'), str(request)], cwd=isolated, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'docx_cell_write_not_applied' in result.stderr
    assert not output.exists()
    assert source.read_bytes() == content


def test_docx_tracked_table_row_is_read_only():
    inspect, patch = api()
    document = Document()
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = '修订行内容'
    change = OxmlElement('w:ins')
    from docx.oxml.ns import qn
    change.set(qn('w:id'), '4')
    change.set(qn('w:author'), 'reviewer')
    change.set(qn('w:date'), '2026-11-05T00:00:00Z')
    table.rows[0]._tr.get_or_add_trPr().append(change)
    stream = BytesIO()
    document.save(stream)
    source = stream.getvalue()
    target = inspect(source)['blocks'][0]
    cell = target['cells'][0][0]
    assert cell['editable'] is False
    with pytest.raises(ValueError, match='docx_cell_unsupported'):
        patch(source, [operation(target, 'replaceCellText', cellId=cell['cellId'], expectedObjectSha256=cell['expectedObjectSha256'], text='不修改修订行')])


def test_docx_report_larger_than_ten_mib_can_open_within_product_limit(content):
    # 未引用的合法 ZIP 部件模拟体积较大的报告，避免引擎上限小于产品入口上限。
    stream = BytesIO(content)
    with ZipFile(stream, 'a') as archive:
        archive.writestr('customXml/large-retained-part.bin', b'0' * (10 * 1024 * 1024))
    source = stream.getvalue()
    inspect, patch = api()
    assert inspect(source)['sourceSha256'] == hashlib.sha256(source).hexdigest()
    assert patch(source, []) == source
