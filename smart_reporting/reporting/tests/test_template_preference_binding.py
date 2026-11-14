"""模板明确落款声明的安全边界及模板样式优先级。"""

import io
import subprocess

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.reporting.delivery.templates import fill_report_template


@pytest.mark.parametrize('prefix, inline_text', [('正文前缀', '原有行内说明{{report_title}}'), ('', '{{report_signature}}')])
def test_inline_signature_control_keeps_native_content_and_warns_instead_of_inserting_paragraphs(prefix, inline_text):
    document = Document()
    paragraph = document.add_paragraph(prefix)
    control = OxmlElement('w:sdt')
    properties = OxmlElement('w:sdtPr')
    tag = OxmlElement('w:tag')
    tag.set(qn('w:val'), 'report_signature')
    properties.append(tag)
    control.append(properties)
    content = OxmlElement('w:sdtContent')
    run = OxmlElement('w:r')
    text = OxmlElement('w:t')
    text.text = inline_text
    run.append(text)
    content.append(run)
    control.append(content)
    paragraph._p.append(control)
    original = etree.tostring(control)
    stream = io.BytesIO()
    document.save(stream)

    result = fill_report_template(stream.getvalue(), template_format='docx', delivery_format='docx',
        values={'report_title': '不可改写行内声明'}, signature={'signer': '当前署名', 'date': '2026-11-13'})

    output = Document(io.BytesIO(result.content))
    assert etree.tostring(output._element.body.xpath('.//w:sdt')[0]) == original
    assert [p.text for p in output.paragraphs][-2:] == ['当前署名', '2026-11-13']
    assert any(issue['code'] == 'report_template_signature_slot_unusable' for issue in result.issues)
    assert result.signature_binding['placement'] == 'body_end'
    assert result.signature_binding['templateSampleStatus'] == 'preserved_for_review'


def test_grouped_signature_slot_clears_only_declared_sample_and_uses_safe_ending_slide():
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    group = slide.shapes.add_group_shape()
    body = group.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    body.text = '{{report_content}}'
    nested = group.shapes.add_group_shape()
    slot = nested.shapes.add_textbox(Inches(1), Inches(3), Inches(6), Inches(2))
    slot.name = 'report_signature'
    slot.text = '旧模板署名\n2000-01-01'
    stream = io.BytesIO()
    deck.save(stream)

    result = fill_report_template(stream.getvalue(), template_format='pptx', delivery_format='pptx',
        values={'report_content': '冻结正文'}, signature={'signer': '当前署名', 'date': '2026-11-13'})

    output = Presentation(io.BytesIO(result.content))
    assert len(output.slides) == 2
    assert output.slides[0].shapes[0].shapes[0].text == '冻结正文'
    assert output.slides[0].shapes[0].shapes[1].shapes[0].text == ''
    assert output.slides[1].shapes[0].text == '当前署名\n2026-11-13'
    assert any(issue['code'] == 'report_template_signature_grouped_slot' for issue in result.issues)
    assert result.signature_binding['placement'] == 'ending_slide'
    assert result.signature_binding['slideNumber'] == 2
    assert result.signature_binding['templateSampleStatus'] == 'cleared'


def test_docx_explicit_slot_preserves_template_font_alignment_and_non_declared_date():
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    document = Document()
    document.add_paragraph('业务说明署名：既有作者；历史业务日期2000-01-01')
    slot = document.add_paragraph()
    slot.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = slot.add_run('{{report_signature}}')
    run.font.name = 'Liberation Serif'
    run.font.size = Pt(17)
    run.bold = True
    stream = io.BytesIO()
    document.save(stream)

    result = fill_report_template(stream.getvalue(), template_format='docx', delivery_format='docx',
        values={}, signature={'signer': '冻结署名', 'date': '2026-11-13'})

    output = Document(io.BytesIO(result.content))
    assert output.paragraphs[0].text == '业务说明署名：既有作者；历史业务日期2000-01-01'
    assert [p.text for p in output.paragraphs][1:] == ['冻结署名', '2026-11-13']
    assert all(p.alignment == WD_ALIGN_PARAGRAPH.LEFT for p in output.paragraphs[1:])
    assert all(p.runs[0].font.name == 'Liberation Serif' and p.runs[0].font.size.pt == 17
        and p.runs[0].bold for p in output.paragraphs[1:])


@pytest.mark.parametrize('width, expected_sheets', [(8, ['业务', '报告落款']), (65, ['业务'])])
def test_workbook_signature_preserves_sufficient_slot_but_moves_clipped_identity_to_printable_sheet(width, expected_sheets):
    from openpyxl import Workbook, load_workbook
    from openpyxl.workbook.defined_name import DefinedName

    book = Workbook()
    book.active.title = '业务'
    book.active['A1'] = '=SUM(1,2)'
    book.active['B5'] = 'Old sample author'
    book.active['B6'] = '2000-01-01'
    book.active.column_dimensions['B'].width = width
    book.defined_names.add(DefinedName('report_signature', attr_text="'业务'!$B$5:$B$6"))
    stream = io.BytesIO()
    book.save(stream)

    result = fill_report_template(stream.getvalue(), template_format='xlsx', delivery_format='xlsx',
        values={}, signature={'signer': 'Frozen Template Author', 'date': '2026-11-13'})

    output = load_workbook(io.BytesIO(result.content))
    assert output.sheetnames == expected_sheets
    assert output['业务']['A1'].value == '=SUM(1,2)'
    assert output['业务'].column_dimensions['B'].width == width
    if width == 8:
        assert output['业务']['B5'].value is None and output['业务']['B6'].value is None
        assert output['报告落款']['A2'].value == 'Frozen Template Author'
        assert output['报告落款']['A3'].value == '2026-11-13'
        assert any(issue['code'] == 'report_template_signature_range_small' for issue in result.issues)
        assert result.signature_binding['placement'] == 'signature_sheet'
        assert result.signature_binding['templateSampleStatus'] == 'cleared'
    else:
        assert output['业务']['B5'].value == 'Frozen Template Author'
        assert output['业务']['B6'].value == '2026-11-13'
        assert not any(issue['code'] == 'report_template_signature_range_small' for issue in result.issues)


@pytest.mark.parametrize('fault', ['missing_font_command', 'font_command_failed', 'font_unreadable'])
def test_workbook_signature_measurement_failure_keeps_original_slot_and_actual_printable_fallback(monkeypatch, fault):
    from openpyxl import Workbook, load_workbook
    from openpyxl.workbook.defined_name import DefinedName
    from PIL import ImageFont

    from smart_reporting.reporting.delivery import templates

    book = Workbook()
    book.active.title = '业务'
    book.active['A1'] = '{{report_content}}'
    book.active['A2'] = '=SUM(1,2)'
    book.active['B5'] = 'Original author retained for review'
    book.active['B6'] = '2000-01-01'
    book.defined_names.add(DefinedName('report_signature', attr_text="'业务'!$B$5:$B$6"))
    stream = io.BytesIO()
    book.save(stream)
    original_run = templates.subprocess.run

    def fail_font_command(command, *args, **kwargs):
        if command[0] == 'fc-match':
            if fault == 'missing_font_command':
                raise FileNotFoundError('font matcher unavailable')
            raise subprocess.CalledProcessError(1, command)
        return original_run(command, *args, **kwargs)

    def fail_font_read(*args, **kwargs):
        raise OSError('font file unreadable')

    if fault == 'font_unreadable':
        monkeypatch.setattr(ImageFont, 'truetype', fail_font_read)
    else:
        monkeypatch.setattr(templates.subprocess, 'run', fail_font_command)
    result = fill_report_template(stream.getvalue(), template_format='xlsx', delivery_format='xlsx',
        values={'report_content': 'Frozen business body'},
        signature={'signer': 'Current frozen author', 'date': '2026-11-13'})

    output = load_workbook(io.BytesIO(result.content))
    assert output.sheetnames == ['业务', '报告落款']
    assert output['业务']['A1'].value == 'Frozen business body'
    assert output['业务']['A2'].value == '=SUM(1,2)'
    assert output['业务']['B5'].value == 'Original author retained for review'
    assert output['业务']['B6'].value == '2000-01-01'
    assert output['报告落款']['A2'].value == 'Current frozen author'
    assert output['报告落款']['A3'].value == '2026-11-13'
    assert str(output['报告落款'].print_area) == "'报告落款'!$A$1:$A$3"
    assert any(issue['code'] == 'report_template_signature_measurement_unavailable' for issue in result.issues)
