"""真实原生包中的修订说明不改写业务对象或推断段落含义。"""

from io import BytesIO
from zipfile import ZipFile

import openpyxl
from pptx import Presentation
from pptx.util import Inches


def test_workbook_notice_preserves_cells_and_updates_one_identified_sheet():
    from smart_reporting.report_editor.revision_notice import add_workbook_revision_notice
    from smart_reporting.reporting.delivery.xlsx import patch_workbook

    book = openpyxl.Workbook()
    book.active.title = '修订核验说明'
    book.active['A1'] = '同名业务表，不得覆盖'
    book.active['B2'] = '=SUM(1,2)'
    book.active.print_area = 'A1:B2'
    stream = BytesIO()
    book.save(stream)
    original = stream.getvalue()
    revised = add_workbook_revision_notice(original, revision=2, parent_revision=1)
    with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(revised)) as after:
        for name in before.namelist():
            if name not in {'xl/workbook.xml', 'xl/_rels/workbook.xml.rels', '[Content_Types].xml'}:
                assert before.read(name) == after.read(name), name
    current = openpyxl.load_workbook(BytesIO(revised))
    assert len(current.worksheets) == 2
    assert current.worksheets[0]['A1'].value == '本修订待核验'
    assert '第 2 版' in current.worksheets[0]['A3'].value
    assert current['修订核验说明']['A1'].value == '同名业务表，不得覆盖'
    assert current['修订核验说明']['B2'].value == '=SUM(1,2)'
    assert str(current['修订核验说明'].print_area) == "'修订核验说明'!$A$1:$B$2"
    revised = patch_workbook(revised, [{'kind': 'applySheetEdits', 'plan': {'renames': [
        {'sheetName': '修订核验说明 2', 'newName': '上次说明'}], 'additions': [], 'removals': [],
        'order': ['修订核验说明', '上次说明']}}])
    again = add_workbook_revision_notice(revised, revision=3, parent_revision=2)
    current = openpyxl.load_workbook(BytesIO(again))
    assert len(current.worksheets) == 2
    assert '第 3 版' in current.worksheets[0]['A3'].value
    assert '尚未重新核验' in current.worksheets[0]['A6'].value
    assert current.active == current.worksheets[0]


def test_slides_notice_preserves_original_slide_and_updates_one_identified_slide():
    from smart_reporting.report_editor.revision_notice import add_slides_revision_notice
    from smart_reporting.report_editor.slides import ReportSlidesEditorService

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1))
    box.text = '本修订待核验：这是业务正文中的同名文字，不能覆盖。'
    stream = BytesIO()
    deck.save(stream)
    original = stream.getvalue()
    revised = add_slides_revision_notice(original, revision=2, parent_revision=1)
    with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(revised)) as after:
        for name in before.namelist():
            if name not in {'ppt/presentation.xml', 'ppt/_rels/presentation.xml.rels', '[Content_Types].xml'}:
                assert before.read(name) == after.read(name), name
    current = Presentation(BytesIO(revised))
    assert len(current.slides) == 2
    assert '本修订待核验' in '\n'.join(shape.text for shape in current.slides[0].shapes if shape.has_text_frame)
    assert current.slides[1].shapes[0].text == box.text
    revised = ReportSlidesEditorService._run_engine(revised, 'edit', order=[1, 0])['bytes']
    again = add_slides_revision_notice(revised, revision=3, parent_revision=2)
    current = Presentation(BytesIO(again))
    assert len(current.slides) == 2
    text = '\n'.join(shape.text for shape in current.slides[0].shapes if shape.has_text_frame)
    assert '第 3 版' in text and '尚未重新核验' in text
    assert current.slide_width == deck.slide_width and current.slide_height == deck.slide_height
