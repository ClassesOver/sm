"""为人工修订加入可见说明；仅改目录和新增说明部件，保留原业务部件。"""

from io import BytesIO
from posixpath import dirname, normpath
from zipfile import ZipFile

from lxml import etree as ET
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Pt

_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
_OFFICE_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_CONTENT = 'http://schemas.openxmlformats.org/package/2006/content-types'
_SHEET = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_SLIDE = 'http://schemas.openxmlformats.org/presentationml/2006/main'
_NAME = 'smart-reporting-manual-revision-notice'
_SHEET_CODE = 'SRManualRevisionNotice'
_TITLE = '本修订待核验'
_LINES = ('本文件为人工保存的新修订。', '数值、解释与建议尚未重新核验。',
    '原有标签与来源记录仅供追溯，', '不代表本修订已获确认。')


def _xml(root):
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def _write_parts(package, parts):
    output = BytesIO()
    with ZipFile(output, 'w') as target:
        for entry in package.infolist():
            target.writestr(entry, parts.pop(entry.filename, package.read(entry.filename)))
        for path, raw in parts.items():
            target.writestr(path, raw)
    return output.getvalue()


def _register_part(package, parts, document_path, part_path, kind):
    rel_path = dirname(document_path) + '/_rels/' + document_path.rsplit('/', 1)[-1] + '.rels'
    rels = ET.fromstring(package.read(rel_path))
    for rel in rels:
        target = rel.get('Target', '')
        resolved = normpath(dirname(document_path) + '/' + target) if not target.startswith('/') else target[1:]
        if resolved == part_path and rel.get('Type') == _OFFICE_REL + '/' + kind:
            return rel.get('Id')
    used = {rel.get('Id') for rel in rels}
    number = 1
    while f'rIdSRNotice{number}' in used:
        number += 1
    rid = f'rIdSRNotice{number}'
    ET.SubElement(rels, f'{{{_REL}}}Relationship', Id=rid, Type=_OFFICE_REL + '/' + kind,
        Target=part_path.removeprefix(dirname(document_path) + '/'))
    parts[rel_path] = _xml(rels)
    types = ET.fromstring(package.read('[Content_Types].xml'))
    ET.SubElement(types, f'{{{_CONTENT}}}Override', PartName='/' + part_path,
        ContentType='application/vnd.openxmlformats-officedocument.' +
        ('spreadsheetml.worksheet+xml' if kind == 'worksheet' else 'presentationml.slide+xml'))
    parts['[Content_Types].xml'] = _xml(types)
    return rid


def add_workbook_revision_notice(content: bytes, *, revision: int, parent_revision: int) -> bytes:
    path = 'xl/worksheets/srRevisionNotice.xml'
    def tag(name):
        return f'{{{_SHEET}}}{name}'
    with ZipFile(BytesIO(content)) as package:
        parts = {}
        if path in package.namelist():
            previous = ET.fromstring(package.read(path))
            if previous.find(tag('sheetPr')).get('codeName') != _SHEET_CODE:
                raise ValueError('workbook_revision_notice_identity_invalid')
        rid = _register_part(package, parts, 'xl/workbook.xml', path, 'worksheet')
        book = ET.fromstring(package.read('xl/workbook.xml'))
        sheets = book.find(tag('sheets'))
        before = list(sheets)
        existing = next((sheet for sheet in before if sheet.get(f'{{{_OFFICE_REL}}}id') == rid), None)
        if existing is None:
            names = {sheet.get('name') for sheet in before}
            name, suffix = '修订核验说明', 2
            while name in names:
                name, suffix = f'修订核验说明 {suffix}', suffix + 1
            existing = ET.Element(tag('sheet'), name=name,
                sheetId=str(max(int(sheet.get('sheetId')) for sheet in before) + 1),
                attrib={f'{{{_OFFICE_REL}}}id': rid})
        else:
            sheets.remove(existing)
        existing.set('state', 'visible')
        sheets.insert(0, existing)
        positions = {id(sheet): i for i, sheet in enumerate(sheets)}
        for name in book.findall(f"{tag('definedNames')}/{tag('definedName')}"):
            if 'localSheetId' in name.attrib:
                name.set('localSheetId', str(positions[id(before[int(name.get('localSheetId'))])]))
        for view in book.findall(f"{tag('bookViews')}/{tag('workbookView')}"):
            view.set('activeTab', '0')
            view.set('firstSheet', '0')
        parts['xl/workbook.xml'] = _xml(book)
        sheet = ET.Element(tag('worksheet'))
        ET.SubElement(sheet, tag('sheetPr'), codeName=_SHEET_CODE)
        columns = ET.SubElement(sheet, tag('cols'))
        ET.SubElement(columns, tag('col'), min='1', max='1', width='80', customWidth='1')
        data = ET.SubElement(sheet, tag('sheetData'))
        rows = [(1, _TITLE), (3, f'第 {revision} 版 · 基于第 {parent_revision} 版人工保存'),
            *zip((5, 6, 8, 9), _LINES), (11, '请在采用结论前核对本报告计算依据及当前知识状态。')]
        for number, text in rows:
            row = ET.SubElement(data, tag('row'), r=str(number), ht='34', customHeight='1')
            cell = ET.SubElement(row, tag('c'), r=f'A{number}', t='inlineStr')
            run = ET.SubElement(ET.SubElement(cell, tag('is')), tag('r'))
            font = ET.SubElement(run, tag('rPr'))
            ET.SubElement(font, tag('rFont'), val='Microsoft YaHei')
            ET.SubElement(font, tag('sz'), val='20' if number == 1 else '12')
            ET.SubElement(font, tag('color'), rgb='FF17365D' if number == 1 else 'FF334155')
            if number == 1:
                ET.SubElement(font, tag('b'))
            ET.SubElement(run, tag('t')).text = text
        ET.SubElement(sheet, tag('pageMargins'), left='0.5', right='0.5', top='0.5', bottom='0.5', header='0.2', footer='0.2')
        ET.SubElement(sheet, tag('pageSetup'), paperSize='9', orientation='portrait', fitToWidth='1', fitToHeight='1')
        parts[path] = _xml(sheet)
        return _write_parts(package, parts)


def add_slides_revision_notice(content: bytes, *, revision: int, parent_revision: int) -> bytes:
    path = 'ppt/slides/srRevisionNotice.xml'
    source = Presentation(BytesIO(content))
    note = Presentation()
    note.slide_width, note.slide_height = source.slide_width, source.slide_height
    slide = note.slides.add_slide(note.slide_layouts[6])
    slide.name = _NAME
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor.from_string('F5F7FA')
    for y, text, size in [(0.12, _TITLE, 30), (0.28, f'第 {revision} 版 · 基于第 {parent_revision} 版人工保存', 16),
            (0.44, '\n'.join(_LINES[:2]), 21), (0.69, '\n'.join(_LINES[2:]), 18)]:
        frame = slide.shapes.add_textbox(int(source.slide_width * 0.08), int(source.slide_height * y),
            int(source.slide_width * 0.84), int(source.slide_height * 0.22)).text_frame
        frame.word_wrap = True
        frame.text = text
        for paragraph in frame.paragraphs:
            paragraph.font.name = 'Microsoft YaHei'
            paragraph.font.size = Pt(size)
            paragraph.font.bold = y == 0.12
            paragraph.font.color.rgb = RGBColor.from_string('17365D' if y == 0.12 else '334155')
    stream = BytesIO()
    note.save(stream)
    with ZipFile(BytesIO(content)) as package, ZipFile(stream) as donor:
        if path in package.namelist() and ET.fromstring(package.read(path)).find(f'{{{_SLIDE}}}cSld').get('name') != _NAME:
            raise ValueError('slides_revision_notice_identity_invalid')
        parts = {path: donor.read('ppt/slides/slide1.xml')}
        rid = _register_part(package, parts, 'ppt/presentation.xml', path, 'slide')
        presentation = ET.fromstring(package.read('ppt/presentation.xml'))
        slides = presentation.find(f'{{{_SLIDE}}}sldIdLst')
        existing = next((item for item in slides if item.get(f'{{{_OFFICE_REL}}}id') == rid), None)
        if existing is None:
            existing = ET.Element(f'{{{_SLIDE}}}sldId', id=str(max((int(item.get('id')) for item in slides), default=255) + 1),
                attrib={f'{{{_OFFICE_REL}}}id': rid})
        else:
            slides.remove(existing)
        slides.insert(0, existing)
        parts['ppt/presentation.xml'] = _xml(presentation)
        layout = min(source.slide_layouts, key=lambda item: len(item.placeholders))
        rels = ET.Element(f'{{{_REL}}}Relationships')
        ET.SubElement(rels, f'{{{_REL}}}Relationship', Id='rId1', Type=_OFFICE_REL + '/slideLayout',
            Target='..' + str(layout.part.partname).removeprefix('/ppt'))
        parts['ppt/slides/_rels/srRevisionNotice.xml.rels'] = _xml(rels)
        return _write_parts(package, parts)
