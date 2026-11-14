"""模板只修改声明占位符，保留非目标 ZIP 部件和原始模板。"""

import io
import zipfile

import pytest


def test_docx_template_replaces_split_run_placeholder_and_preserves_other_objects():
    from docx import Document

    from smart_reporting.reporting.delivery.templates import fill_report_template

    document = Document()
    title = document.add_paragraph()
    title.add_run("{{report_").bold = True
    title.add_run("title}}")
    document.add_paragraph("保留说明")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "{{report_content}}"
    stream = io.BytesIO()
    document.save(stream)
    raw = stream.getvalue()

    result = fill_report_template(raw, template_format="docx", delivery_format="docx",
        values={"report_title": "收入报告", "report_content": "数据库核验内容"})

    rendered = Document(io.BytesIO(result.content))
    assert rendered.paragraphs[0].text == "收入报告"
    assert rendered.paragraphs[0].runs[0].bold is True
    assert rendered.paragraphs[1].text == "保留说明"
    assert rendered.tables[0].cell(0, 0).text == "数据库核验内容"
    assert Document(io.BytesIO(raw)).paragraphs[0].text == "{{report_title}}"
    with zipfile.ZipFile(io.BytesIO(raw)) as before, zipfile.ZipFile(io.BytesIO(result.content)) as after:
        assert before.namelist() == after.namelist()
        for name in before.namelist():
            if name != "word/document.xml":
                assert before.read(name) == after.read(name)


def test_xlsx_template_preserves_formula_styles_and_non_target_sheet():
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import PatternFill

    from smart_reporting.reporting.delivery.templates import fill_report_template

    workbook = Workbook()
    workbook.active["A1"] = "{{report_title}}"
    workbook.active["A1"].fill = PatternFill("solid", fgColor="CCDDFF")
    workbook.active["B2"] = "=SUM(C2:C3)"
    workbook.create_sheet("保留")["A1"] = "说明"
    stream = io.BytesIO()
    workbook.save(stream)

    result = fill_report_template(stream.getvalue(), template_format="xlsx", delivery_format="xlsx",
        values={"report_title": "收入核验"})

    rendered = load_workbook(io.BytesIO(result.content), data_only=False)
    assert rendered.active["A1"].value == "收入核验"
    assert rendered.active["A1"].fill.fgColor.rgb == "00CCDDFF"
    assert rendered.active["B2"].value == "=SUM(C2:C3)"
    assert rendered["保留"]["A1"].value == "说明"


def test_pptx_template_preserves_slide_geometry_and_non_target_shape():
    from pptx import Presentation

    from smart_reporting.reporting.delivery.templates import fill_report_template

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    target = slide.shapes.add_textbox(1, 2, 300000, 400000)
    target.text = "{{report_title}}"
    kept = slide.shapes.add_textbox(5, 6, 700000, 800000)
    kept.text = "固定说明"
    stream = io.BytesIO()
    presentation.save(stream)

    result = fill_report_template(stream.getvalue(), template_format="pptx", delivery_format="pptx",
        values={"report_title": "正式报告"})

    rendered = Presentation(io.BytesIO(result.content))
    assert rendered.slides[0].shapes[0].text == "正式报告"
    assert rendered.slides[0].shapes[1].text == "固定说明"
    assert (rendered.slides[0].shapes[0].left, rendered.slides[0].shapes[0].top,
        rendered.slides[0].shapes[0].width, rendered.slides[0].shapes[0].height) == (1, 2, 300000, 400000)


def test_unknown_template_placeholder_returns_specific_warning():
    from docx import Document

    from smart_reporting.reporting.delivery.templates import fill_report_template

    document = Document()
    document.add_paragraph("{{missing_metric}}")
    stream = io.BytesIO()
    document.save(stream)

    result = fill_report_template(stream.getvalue(), template_format="docx", delivery_format="docx", values={})

    assert result.issues[0]["code"] == "report_template_unresolved_placeholder"
    assert result.issues[0]["placeholders"] == ["missing_metric"]


def test_office_template_rejects_other_office_target_instead_of_changing_extension():
    from smart_reporting.reporting.delivery.templates import fill_report_template

    with pytest.raises(ValueError, match="同格式"):
        fill_report_template(b"unused", template_format="docx", delivery_format="pptx", values={})


def test_docx_template_signature_rebinds_declared_slot_and_removes_md_duplicate():
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    from smart_reporting.preferences.markdown_adapter import append_signature
    from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
    from smart_reporting.reporting.delivery.templates import fill_report_template

    document = Document()
    document.add_paragraph('{{report_content}}')
    slot = OxmlElement('w:sdt')
    properties = OxmlElement('w:sdtPr')
    tag = OxmlElement('w:tag')
    tag.set(qn('w:val'), 'report_signature')
    properties.append(tag)
    slot.append(properties)
    content = OxmlElement('w:sdtContent')
    for value in ['模板示例署名', '2000-01-01']:
        p = OxmlElement('w:p')
        r = OxmlElement('w:r')
        t = OxmlElement('w:t')
        t.text = value
        r.append(t)
        p.append(r)
        content.append(p)
    slot.append(content)
    document._element.body.insert(-1, slot)
    stream = io.BytesIO()
    document.save(stream)
    prefs = resolve_format_preferences(FormatPreferences(common={'signer': 'MD旧署名'}), 'md')
    markdown = append_signature('冻结正文', prefs, '2026-11-11')
    result = fill_report_template(stream.getvalue(), template_format='docx', delivery_format='docx',
        values={'report_content': markdown}, signature={'signer': '本次署名', 'date': '2026-11-12', 'description': '复核说明\n内部使用'})
    output = Document(io.BytesIO(result.content))
    text = '\n'.join(output._element.body.xpath('.//w:t/text()'))
    assert '模板示例署名' not in text and '2000-01-01' not in text and 'MD旧署名' not in text
    assert 'report-signature:v1' not in text
    assert text.count('本次署名') == 1 and text.count('2026-11-12') == 1
    assert all(value in text for value in ['冻结正文', '复核说明', '内部使用'])
    assert len(output._element.body.xpath('.//w:sdt')) == 1


def test_docx_template_without_signature_slot_appends_native_paragraphs_once():
    from docx import Document

    from smart_reporting.reporting.delivery.templates import fill_report_template

    document = Document()
    document.add_paragraph('{{report_content}}')
    stream = io.BytesIO()
    document.save(stream)
    result = fill_report_template(stream.getvalue(), template_format='docx', delivery_format='docx',
        values={'report_content': '冻结正文'}, signature={'signer': '本次署名', 'date': '2026-11-12', 'description': ''})
    output = Document(io.BytesIO(result.content))
    assert [p.text for p in output.paragraphs] == ['冻结正文', '本次署名', '2026-11-12']
    assert output.paragraphs[-2].paragraph_format.keep_with_next is True
    assert output.paragraphs[-1].alignment == 2


def test_template_signature_literal_placeholders_are_not_interpreted_and_duplicates_warn():
    from docx import Document

    from smart_reporting.reporting.delivery.templates import fill_report_template

    document = Document()
    document.add_paragraph('{{report_content}}')
    document.add_paragraph('{{report_signature}}')
    document.add_paragraph('{{report_signature}}')
    stream = io.BytesIO()
    document.save(stream)
    result = fill_report_template(stream.getvalue(), template_format='docx', delivery_format='docx',
        values={'report_content': '正文', 'report_title': '不可替代署名'},
        signature={'signer': '{{report_title}}', 'date': '2026-11-12'})
    output = Document(io.BytesIO(result.content))
    assert [p.text for p in output.paragraphs] == ['正文', '{{report_title}}', '2026-11-12']
    assert any(issue['code'] == 'report_template_signature_multiple_slots' for issue in result.issues)


def test_actual_pdf_from_docx_template_contains_bound_signature_once():
    from docx import Document
    from pypdf import PdfReader

    from smart_reporting.reporting.delivery.templates import fill_report_template

    document = Document()
    document.add_paragraph('{{report_content}}')
    document.add_paragraph('{{report_signature}}')
    stream = io.BytesIO()
    document.save(stream)
    result = fill_report_template(stream.getvalue(), template_format='docx', delivery_format='pdf',
        values={'report_content': 'Frozen report body'},
        signature={'signer': 'Current Author', 'date': '2026-11-12', 'description': 'Reviewed'})
    text = ''.join(page.extract_text() for page in PdfReader(io.BytesIO(result.content)).pages)
    assert text.count('Current Author') == 1 and text.count('2026-11-12') == 1
    assert 'Frozen report body' in text and 'Reviewed' in text


def test_docx_template_keeps_signature_placeholder_inside_body_text_literal():
    from docx import Document

    from smart_reporting.reporting.delivery.templates import fill_report_template

    document = Document()
    document.add_paragraph('{{report_content}}')
    stream = io.BytesIO()
    document.save(stream)
    result = fill_report_template(stream.getvalue(), template_format='docx', delivery_format='docx',
        values={'report_content': '{{report_signature}}'}, signature={'signer': '本次署名', 'date': '2026-11-12'})
    output = Document(io.BytesIO(result.content))
    assert [p.text for p in output.paragraphs] == ['{{report_signature}}', '本次署名', '2026-11-12']


def test_xlsx_template_signature_uses_separate_printable_sheet_and_preserves_formula_cache():
    from openpyxl import Workbook, load_workbook

    from smart_reporting.reporting.delivery.templates import fill_report_template

    book = Workbook()
    book.active.title = '业务数据'
    book.active['A1'] = '{{report_title}}'
    book.active['B2'] = '=SUM(1,2)'
    book.active['C2'] = 123.456
    book.create_sheet('说明')['A1'] = '保留原有说明'
    stream = io.BytesIO()
    book.save(stream)
    # 真实冻结计算缓存不得因追加落款而被清空。
    changed = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(stream.getvalue())) as package, zipfile.ZipFile(changed, 'w') as target:
        for member in package.infolist():
            raw = package.read(member)
            if member.filename == 'xl/worksheets/sheet1.xml':
                raw = raw.replace(b'<f>SUM(1,2)</f><v></v>', b'<f>SUM(1,2)</f><v>3</v>')
            target.writestr(member, raw)
    result = fill_report_template(changed.getvalue(), template_format='xlsx', delivery_format='xlsx',
        values={'report_title': '冻结标题'}, signature={'signer': '=不作为公式', 'date': '2026-11-12', 'description': '复核完成'})
    output = load_workbook(io.BytesIO(result.content), data_only=False)
    assert output.sheetnames == ['业务数据', '说明', '报告落款']
    assert output['业务数据']['B2'].value == '=SUM(1,2)'
    assert output['业务数据']['C2'].value == 123.456
    assert output['说明']['A1'].value == '保留原有说明'
    assert load_workbook(io.BytesIO(result.content), data_only=True)['业务数据']['B2'].value == 3
    signature = output['报告落款']
    assert [signature.cell(row, 1).value for row in range(1, 5)] == ['报告落款', '=不作为公式', '2026-11-12', '复核完成']
    assert signature['A2'].data_type == 's'
    assert str(signature.print_area) == "'报告落款'!$A$1:$A$4"
    assert signature.sheet_state == 'visible'


def test_xlsx_template_reuses_named_signature_range_and_keeps_slot_style():
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font
    from openpyxl.workbook.defined_name import DefinedName

    from smart_reporting.reporting.delivery.templates import fill_report_template

    book = Workbook()
    book.active.title = '说明'
    book.active['A1'] = '模板固定说明'
    book.active['D3'] = '保留右侧业务说明'
    book.active.print_area = 'A1:D3'
    book.active['B5'] = '旧示例署名'
    book.active['B6'] = '2000-01-01'
    book.active['B7'] = '旧说明'
    book.active['B5'].font = Font(name='Noto Serif CJK SC', size=14, bold=True)
    book.active.column_dimensions['B'].width = 24
    book.defined_names.add(DefinedName('report_signature', attr_text="'说明'!$B$5:$B$8"))
    stream = io.BytesIO()
    book.save(stream)
    result = fill_report_template(stream.getvalue(), template_format='xlsx', delivery_format='xlsx',
        values={}, signature={'signer': '当前署名', 'date': '2026-11-12', 'description': '当前说明'})
    output = load_workbook(io.BytesIO(result.content))
    assert output.sheetnames == ['说明']
    assert output.active['A1'].value == '模板固定说明'
    assert [output.active.cell(row, 2).value for row in range(5, 9)] == ['当前署名', '2026-11-12', '当前说明', None]
    assert output.active['B5'].font.bold and output.active['B5'].font.sz == 14
    assert str(output.active.print_area) == "'说明'!$A$1:$D$8"


def test_xlsx_template_actual_pdf_prints_signature_sheet():
    from openpyxl import Workbook
    from pypdf import PdfReader

    from smart_reporting.reporting.delivery.templates import fill_report_template

    book = Workbook()
    book.active['A1'] = 'Frozen business data'
    stream = io.BytesIO()
    book.save(stream)
    result = fill_report_template(stream.getvalue(), template_format='xlsx', delivery_format='pdf',
        values={}, signature={'signer': 'Workbook Author', 'date': '2026-11-12', 'description': 'Reviewed'})
    pdf = PdfReader(io.BytesIO(result.content))
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    assert 'Frozen business data' in text
    assert text.count('Workbook Author') == 1 and text.count('2026-11-12') == 1
    assert 'Reviewed' in pdf.pages[-1].extract_text()


@pytest.mark.parametrize('reference', ["'说明'!$B$5:$B$5", "'说明'!$B$5:$B$8", 'INVALID'])
def test_xlsx_template_invalid_signature_range_warns_and_keeps_business_formula(reference):
    from openpyxl import Workbook, load_workbook
    from openpyxl.workbook.defined_name import DefinedName

    from smart_reporting.reporting.delivery.templates import fill_report_template

    book = Workbook()
    book.active.title = '说明'
    book.active['B5'] = '=SUM(1,2)'
    book.defined_names.add(DefinedName('report_signature', attr_text=reference))
    stream = io.BytesIO()
    book.save(stream)
    result = fill_report_template(stream.getvalue(), template_format='xlsx', delivery_format='xlsx',
        values={}, signature={'signer': '本次署名', 'date': '2026-11-12'})
    output = load_workbook(io.BytesIO(result.content))
    assert output['说明']['B5'].value == '=SUM(1,2)'
    assert output['报告落款']['A2'].value == '本次署名'
    assert any(issue['code'] == 'report_template_signature_range_unusable' for issue in result.issues)


@pytest.mark.parametrize('declared', [True, False])
def test_pptx_template_signature_reuses_native_slot_or_adds_ending_slide(declared):
    from pptx import Presentation
    from pptx.util import Inches, Pt

    from smart_reporting.reporting.delivery.templates import fill_report_template

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    body = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(2))
    body.text = '{{report_content}}'
    if declared:
        slot = slide.shapes.add_textbox(Inches(1), Inches(4), Inches(8), Inches(2))
        slot.name = 'report_signature'
        slot.text = 'Old Author\n2000-01-01'
        slot.text_frame.paragraphs[0].runs[0].font.size = Pt(18)
    stream = io.BytesIO()
    deck.save(stream)
    result = fill_report_template(stream.getvalue(), template_format='pptx', delivery_format='pptx',
        values={'report_content': 'Frozen body'}, signature={'signer': 'Current Author', 'date': '2026-11-12', 'description': 'Reviewed'})
    output = Presentation(io.BytesIO(result.content))
    assert len(output.slides) == (1 if declared else 2)
    text = '\n'.join(shape.text for slide in output.slides for shape in slide.shapes if shape.has_text_frame)
    assert text.count('Current Author') == 1 and text.count('2026-11-12') == 1
    assert 'Old Author' not in text and '2000-01-01' not in text
    assert 'Frozen body' in text and 'Reviewed' in text
    if declared:
        actual = output.slides[0].shapes[1]
        assert (actual.left, actual.top, actual.width, actual.height) == (slot.left, slot.top, slot.width, slot.height)
        assert actual.text_frame.paragraphs[0].runs[0].font.size == Pt(18)
    with zipfile.ZipFile(io.BytesIO(stream.getvalue())) as before, zipfile.ZipFile(io.BytesIO(result.content)) as after:
        assert before.read('ppt/theme/theme1.xml') == after.read('ppt/theme/theme1.xml')


def test_pptx_template_small_slot_moves_signature_without_losing_body():
    from pptx import Presentation
    from pptx.util import Inches

    from smart_reporting.reporting.delivery.templates import fill_report_template

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slot = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(1), Inches(.2))
    slot.name = 'report_signature'
    slot.text = 'Old Author'
    body = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(2))
    body.text = '{{report_content}}'
    stream = io.BytesIO()
    deck.save(stream)
    result = fill_report_template(stream.getvalue(), template_format='pptx', delivery_format='pptx',
        values={'report_content': '{{report_signature}}', 'report_title': '不得替代'},
        signature={'signer': '{{report_title}}', 'date': '2026-11-12'})
    output = Presentation(io.BytesIO(result.content))
    assert len(output.slides) == 2
    assert output.slides[0].shapes[1].text == '{{report_signature}}'
    assert '{{report_title}}' in output.slides[1].shapes[0].text
    assert any(issue['code'] == 'report_template_signature_slot_small' for issue in result.issues)


def test_pptx_template_actual_pdf_keeps_body_and_single_signature():
    from pptx import Presentation
    from pptx.util import Inches
    from pypdf import PdfReader

    from smart_reporting.reporting.delivery.templates import fill_report_template

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(3)).text = '{{report_content}}'
    stream = io.BytesIO()
    deck.save(stream)
    result = fill_report_template(stream.getvalue(), template_format='pptx', delivery_format='pdf',
        values={'report_content': 'Frozen slide body'}, signature={'signer': 'Slide Author', 'date': '2026-11-12'})
    pdf = PdfReader(io.BytesIO(result.content))
    text = '\n'.join(page.extract_text() for page in pdf.pages)
    assert len(pdf.pages) == 2
    assert 'Frozen slide body' in text
    assert text.count('Slide Author') == 1 and text.count('2026-11-12') == 1


def test_pptx_template_signature_overlapping_body_moves_to_ending_slide():
    from pptx import Presentation
    from pptx.util import Inches

    from smart_reporting.reporting.delivery.templates import fill_report_template

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(3)).text = '保留正文'
    slot = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(2))
    slot.name = 'report_signature'
    slot.text = '旧署名'
    stream = io.BytesIO()
    deck.save(stream)
    result = fill_report_template(stream.getvalue(), template_format='pptx', delivery_format='pptx',
        values={}, signature={'signer': '当前署名', 'date': '2026-11-12'})
    output = Presentation(io.BytesIO(result.content))
    assert len(output.slides) == 2
    assert output.slides[0].shapes[0].text == '保留正文'
    assert not output.slides[0].shapes[1].text
    assert '当前署名' in output.slides[1].shapes[0].text


def test_pptx_template_ending_preserves_existing_image_and_unmodified_slide_parts():
    from PIL import Image
    from pptx import Presentation
    from pptx.util import Inches

    from smart_reporting.reporting.delivery.templates import fill_report_template

    picture = io.BytesIO()
    Image.new('RGB', (64, 32), 'blue').save(picture, format='PNG')
    picture.seek(0)
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_picture(picture, Inches(1), Inches(1), Inches(6), Inches(3))
    stream = io.BytesIO()
    deck.save(stream)
    result = fill_report_template(stream.getvalue(), template_format='pptx', delivery_format='pptx',
        values={}, signature={'signer': '编制人' * 50, 'date': '2026-11-12', 'description': '复核说明' * 100})
    with zipfile.ZipFile(io.BytesIO(stream.getvalue())) as before, zipfile.ZipFile(io.BytesIO(result.content)) as after:
        assert before.read('ppt/slides/slide1.xml') == after.read('ppt/slides/slide1.xml')
        for name in before.namelist():
            if name.startswith('ppt/media/'):
                assert before.read(name) == after.read(name)
    output = Presentation(io.BytesIO(result.content))
    text = output.slides[-1].shapes[0].text
    assert text.count('编制人') == 50 and text.count('复核说明') == 100
    assert output.slides[-1].shapes[0].text_frame.paragraphs[0].runs[0].font.size.pt >= 14
