"""独立库读取验收产物；逐字段返回证据，不用生成回执自证正确。"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import partial
from hashlib import sha256
from io import BytesIO
from string import Formatter

from markdown_it import MarkdownIt
from PIL import Image

from ..preferences.workbook_adapter import FONTS, displayed_date
from .preference_workbook_header_footer_readback import (
    XLSX_HEADER_FOOTER_EVIDENCE,
    read_header_footer_group,
)
from .preference_workbook_number_readback import read_workbook_numbers
from .preference_workbook_signature_readback import read_workbook_signature

TERMINAL_SIGNATURE_CONTENT_EVIDENCE = 'terminal_signature_content_v1'
PPTX_TABLE_FIELD_EVIDENCE = 'pptx_native_table_fields_v1'
CHART_IMAGE_DPI_EVIDENCE = 'chart_image_dpi_v1'


def readback(content, format, resolved, frozen):
    checks = []
    table_captions = None
    word_tables = None
    workbook_headers = None
    workbook_signature = None
    workbook_numbers = None

    def check(path, actual, expected, message='实际原生属性与冻结偏好一致。', *, coverage='complete', evidence_kind=None,
        evidence_objects=None, exact=False):
        equal = (actual == expected and isinstance(actual, bool) == isinstance(expected, bool)) if exact else (
            abs(actual - expected) < .05 if isinstance(actual, (float, int)) and isinstance(expected, (float, int)) else actual == expected)
        checks.append({'path': format + '.' + path if path else None, 'passed': bool(equal),
            'message': message if equal else '实际原生属性与冻结偏好不一致。',
            'actual': actual, 'expected': expected, 'coverage': coverage})
        if evidence_kind is not None:
            checks[-1]['evidenceKind'] = evidence_kind
        if evidence_objects is not None:
            checks[-1]['evidenceObjects'] = deepcopy(evidence_objects)

    context = frozen['state']['_documentContext']
    signer = resolved['common']['signer']
    date = displayed_date(context['generatedDate'], resolved['common']['dateFormat'])
    if format == 'md':
        _markdown(content, resolved, frozen, check)
    elif format == 'xlsx':
        workbook_headers, workbook_signature, workbook_numbers = _workbook(content, resolved, frozen, check)
    elif format == 'pptx':
        _slides(content, resolved, frozen, check)
    elif format == 'word':
        table_captions, word_tables = _word(content, resolved, frozen, check)
    else:
        table_captions = _pdf(content, resolved, frozen, check)
    if format == 'pdf':
        text = _text(content, format)
        compact = ''.join(text.split())
        message = 'PDF 可见文字片段采样；未证明末尾独立落款区域、顺序或唯一性。'
        check('common.signer', ''.join(signer.split()) in compact, True, message, coverage='sample')
        check('common.dateFormat', ''.join(date.split()) in compact, True, message, coverage='sample')
        check('signature.description', all(''.join(line.split()) in compact
            for line in resolved['signature']['description'].splitlines()), True, message, coverage='sample')
    result = {'status': 'passed' if checks and all(item['passed'] for item in checks) else 'failed',
        'checks': checks}
    if table_captions is not None:
        result['tableCaptionReadback'] = table_captions
    if word_tables is not None:
        result['tableReadback'] = word_tables
    if workbook_headers is not None:
        result['headerFooterReadback'] = workbook_headers
    if workbook_signature is not None:
        result['signatureReadback'] = workbook_signature
    if workbook_numbers is not None:
        result['numbersReadback'] = workbook_numbers
    return result


def _signature_values(prefs, frozen):
    return [prefs['common']['signer'], displayed_date(
        frozen['state']['_documentContext']['generatedDate'], prefs['common']['dateFormat']),
        *prefs['signature']['description'].splitlines()]


def _signature_checks(lines, valid, prefs, frozen, check):
    check = partial(check, evidence_kind=TERMINAL_SIGNATURE_CONTENT_EVIDENCE)
    expected = _signature_values(prefs, frozen)
    # 文本内容按原生段核验；空白排版不冒充字体、间距或视觉版式证据。
    def normalize(value):
        return ' '.join(value.split())
    actual = [normalize(line) for line in lines]
    message = '唯一末尾原生落款区域中的独立段、身份顺序及完整说明已逐段核验。'
    check('common.signer', actual[0] if valid and actual else None, normalize(expected[0]), message)
    check('common.dateFormat', actual[1] if valid and len(actual) > 1 else None, normalize(expected[1]), message)
    check('signature.description', '\n'.join(actual[2:]) if valid else None,
        '\n'.join(normalize(line) for line in expected[2:]), message)


def _markdown_signature(text, parser, tokens, prefs, frozen, check):
    starts = [index for index, token in enumerate(tokens)
        if token.type == 'html_block' and token.content.strip() == '<!-- report-signature:v1 -->']
    ends = [index for index, token in enumerate(tokens)
        if token.type == 'html_block' and token.content.strip() == '<!-- /report-signature:v1 -->']
    valid = len(starts) == len(ends) == 1 and starts[0] < ends[0] == len(tokens) - 1
    lines = []
    if valid:
        source = text.splitlines(keepends=True)
        block = ''.join(source[tokens[starts[0]].map[1]:tokens[ends[0]].map[0]]).strip('\n')
        for paragraph in block.split('\n\n'):
            if not paragraph:
                lines.append('')
                continue
            native = parser.parse(paragraph)
            if ('\n' in paragraph or [token.type for token in native] !=
                ['paragraph_open', 'inline', 'paragraph_close'] or
                any(child.type != 'text' for child in native[1].children)):
                valid = False
                break
            lines.append(''.join(child.content for child in native[1].children))
    _signature_checks(lines, valid, prefs, frozen, check)


def _word_signature(doc, prefs, frozen, check):
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph

    # 目录/章节的原生书签边界不承载正文，可能跨到落款之后闭合。
    elements = [element for element in doc.element.body
        if element.tag not in {qn('w:bookmarkStart'), qn('w:bookmarkEnd')}]
    paragraphs = {index: Paragraph(element, doc._body) for index, element in enumerate(elements)
        if element.tag == qn('w:p')}
    indices = [index for index, paragraph in paragraphs.items() if paragraph.style.name == 'Report Signature']
    valid = bool(indices) and indices == list(range(indices[0], indices[-1] + 1))
    if valid:
        tail = elements[indices[-1] + 1:]
        for index in range(indices[-1] + 1, len(elements)):
            paragraph = paragraphs.get(index)
            if (prefs['sources'] and paragraph is not None and paragraph.style.name == 'Report Source Appendix'
                and paragraph.text in {'实际引用附录', '数据来源附录', '业务知识来源'}):
                tail = elements[indices[-1] + 1:index]
                break
        valid = all(element.tag == qn('w:sectPr') or element.tag == qn('w:p')
            and not Paragraph(element, doc._body).text.strip()
            and not element.xpath('.//w:drawing|.//w:pict|.//w:object|.//w:instrText|.//w:fldSimple') for element in tail)
        valid = valid and not any(paragraphs[index].style.font.hidden
            or any(run.font.hidden for run in paragraphs[index].runs) for index in indices)
    lines = [paragraphs[index].text for index in indices]
    _signature_checks(lines, valid, prefs, frozen, check)
    return paragraphs[indices[0]] if valid else None


def _slide_signature(deck, prefs, frozen, check):
    headings = ('报告落款', '报告落款（附加说明续页）')
    pages = []
    for slide in deck.slides:
        matches = [shape for shape in slide.shapes if shape.has_text_frame and shape.text in headings
            and shape.top < deck.slide_height / 3
            and not shape._element.xpath('.//p:cNvPr[@hidden="1" or @hidden="true"]')]
        pages.append(matches[0] if len(matches) == 1 else None)
    start = len(pages)
    while start and pages[start - 1] is not None:
        start -= 1
    valid = start < len(pages) and pages[start].text == headings[0] and all(
        heading.text == headings[1] for heading in pages[start + 1:])
    expected = _signature_values(prefs, frozen)
    # 只计具有落款页标题和同框身份两段的原生块；普通业务引用不算重复落款。
    identity_pages = [index for index, heading in enumerate(pages) if heading is not None and any(
        shape.has_text_frame and [paragraph.text for paragraph in shape.text_frame.paragraphs] == expected[:2]
        for shape in deck.slides[index].shapes)]
    valid = valid and identity_pages == [start]
    chunks, identity = [], None
    context = frozen['state']['_documentContext']
    for page in range(start, len(pages)):
        heading = pages[page]
        values = {'title': context['title'], 'period': context['periodLabel'], 'signer': expected[0],
            'date': expected[1], 'filename': 'report.pptx', 'slide': str(page + 1), 'slides': str(len(pages))}
        footers = {template.format(**values) for template in prefs['footer'].values() if template}
        body = []
        for shape in deck.slides[page].shapes:
            if shape == heading or not shape.has_text_frame:
                continue
            if shape.text in footers and shape.width < heading.width and shape.top > heading.top:
                continue
            inside = (shape.left >= 0 and shape.top >= heading.top + heading.height
                and shape.width > 0 and shape.height > 0 and shape.left + shape.width <= deck.slide_width + 100
                and shape.top + shape.height <= deck.slide_height + 100
                and abs(shape.left - heading.left) <= 100 and abs(shape.width - heading.width) <= 100
                and not shape._element.xpath('.//p:cNvPr[@hidden="1" or @hidden="true"]'))
            valid = valid and inside
            body.append(shape)
        body.sort(key=lambda shape: (shape.top, shape.left))
        actual_gap = round((body[0].top - heading.top - heading.height) / 12700, 3) if body else None
        check('signature.spaceBefore', actual_gap, prefs['signature']['spaceBefore'],
            '逐页独立回读标题底部到首个落款文本框顶部的实际磅值。')
        if page == start:
            identity = body.pop(0) if body else None
            valid = valid and identity is not None and len(identity.text_frame.paragraphs) == 2
        for shape in body:
            valid = valid and len(shape.text_frame.paragraphs) == 1
            chunks.append(shape.text)
    lines = [paragraph.text for paragraph in identity.text_frame.paragraphs] if identity is not None else []
    # 说明可跨原生文本框和续页拆分，但不能漏段、换序或把相邻两段合为一段。
    cursor = 0
    for expected_line in expected[2:]:
        combined = ''
        first = True
        while cursor < len(chunks) and (first or combined != expected_line):
            combined += chunks[cursor]
            cursor += 1
            first = False
            if not expected_line.startswith(combined):
                break
        valid = valid and not first and combined == expected_line
        lines.append(combined)
    valid = valid and cursor == len(chunks)
    _signature_checks(lines, valid, prefs, frozen, check)
    return identity if valid and lines[:2] == expected[:2] else None


def _text(content, format):
    if format == 'md':
        return content.decode('utf-8')
    if format == 'word':
        from docx import Document

        doc = Document(BytesIO(content))
        return '\n'.join([p.text for p in doc.paragraphs] + [cell.text for table in doc.tables for row in table.rows for cell in row.cells])
    if format == 'pptx':
        from pptx import Presentation

        return '\n'.join(shape.text for slide in Presentation(BytesIO(content)).slides for shape in slide.shapes if shape.has_text_frame)
    from pypdf import PdfReader

    return '\n'.join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)


def _markdown(content, prefs, frozen, check):
    sample = partial(check, coverage='sample')
    text = content.decode('utf-8')
    parser = MarkdownIt('commonmark', {'html': True}).enable('table')
    tokens = parser.parse(text)
    source_tokens = parser.parse(frozen['markdown'])
    tables = any(token.type == 'table_open' for token in source_tokens)
    if tables:
        check('tableStyle', any(token.type == 'table_open' for token in tokens), prefs['tableStyle'] == 'pipe')
        if prefs['tableStyle'] == 'html':
            check('tableStyle', '<table' in text, True)
    if any(token.type == 'bullet_list_open' for token in source_tokens):
        lists = [token for token in tokens if token.type == 'bullet_list_open']
        check('listMarker', all(token.markup == prefs['listMarker'] for token in lists) and bool(lists), True)
    fences = [token for token in tokens if token.type == 'fence']
    if any(token.type == 'fence' for token in source_tokens):
        check('codeFence', all(token.markup[0] == ('~' if prefs['codeFence'] == 'tildes' else '`') for token in fences) and bool(fences), True)
    check('toc', 'report-md-toc:v1' in text, prefs['toc'])
    section = frozen['state']['_documentContext']['sections'][0]['title']
    heading = next((tokens[index - 1].tag for index, token in enumerate(tokens)
        if token.type == 'inline' and section in token.content and index and tokens[index - 1].type == 'heading_open'), None)
    sample('sectionHeadingLevel', heading, 'h' + str(prefs['sectionHeadingLevel']))
    if '[[citation:' in frozen['markdown']:
        check('references', '[来源 ' in text, prefs['references'])
    if '*图表：' in frozen['markdown']:
        check('imageCaptions', '图表：' in text, prefs['imageCaptions'])
    _markdown_signature(text, parser, tokens, prefs, frozen, check)
    for token in source_tokens:
        if token.type == 'inline' and token.content.replace('.', '', 1).replace('-', '', 1).isdigit():
            check(None, token.content in text, True, '来源数值在 Markdown 中保留。')


def _font(font, style, prefix, check, *, xlsx=False):
    check(prefix + '.font', font.name, FONTS[style['font']])
    check(prefix + '.size', font.sz if xlsx else font.size.pt, style['size'])
    check(prefix + '.bold', bool(font.bold), style['bold'])
    color = font.color.rgb if xlsx else str(font.color.rgb)
    check(prefix + '.color', str(color)[-6:].upper(), style['color'][1:].upper())


def _workbook(content, prefs, frozen, check):
    sample = partial(check, coverage='sample')
    from xml.etree import ElementTree
    from zipfile import ZipFile

    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter
    from openpyxl.utils.datetime import to_excel

    book = load_workbook(BytesIO(content))
    cached = load_workbook(BytesIO(content), data_only=True)
    header_summary = read_header_footer_group(content, book, prefs, frozen, check)
    parts = dict(zip(header_summary['sheetNames'], header_summary['worksheetParts'], strict=True))
    with ZipFile(BytesIO(content)) as package:
        native_cells = {}
        ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        for name, part in parts.items():
            cells = {}
            for node in ElementTree.fromstring(package.read(part)).findall(
                './' + ns + 'sheetData/' + ns + 'row/' + ns + 'c'):
                cells.setdefault(node.get('r'), []).append(node)
            native_cells[name] = cells
    for source in frozen['sheets']:
        sheet = book[source['name']]
        for row_index, row in enumerate(source['rows'], 1):
            for column_index, raw in enumerate(row, 1):
                value = raw if isinstance(raw, dict) else {'value': raw}
                cell = sheet.cell(row_index, column_index)
                expected = '=' + value['formula'].lstrip('=') if value.get('formula') else value.get('value')
                actual = cell.value
                # 日期按冻结来源核对Excel序列值，显示覆盖不改变日期身份。
                native_date = False
                if value.get('valueType') == 'date' and not value.get('formula'):
                    try:
                        parsed = date.fromisoformat(expected)
                        native_date = parsed.year >= 1900
                        if native_date:
                            expected = to_excel(parsed, book.epoch)
                    except (ValueError, TypeError):
                        pass
                if native_date:
                    # 日期解码非单射（1900序列59/60），且会舍入时间；必须核原始数值。
                    cells = native_cells.get(source['name'], {}).get(cell.coordinate, [])
                    values = cells[0].findall(ns + 'v') if len(cells) == 1 else []
                    raw = values[0].text if len(values) == 1 else None
                    try:
                        equal = (len(cells) == 1 and cells[0].get('t', 'n') == 'n'
                            and cells[0].find(ns + 'f') is None and Decimal(raw) == Decimal(str(expected)))
                    except (InvalidOperation, TypeError):
                        equal = False
                    check(None, equal, True, '来源日期原始序列保持不变。', exact=True,
                        evidence_objects={'sheet': source['name'], 'cell': cell.coordinate,
                            'rawValue': raw, 'expectedSerial': expected})
                else:
                    check(None, actual, expected, '来源业务值/公式保持不变。', exact=True)
                if value.get('formula'):
                    check(None, cached[source['name']].cell(row_index, column_index).value,
                        value['value'], '冻结公式缓存保持不变。', exact=True)
                explicit_format = value.get('style', {}).get('numberFormat')
                if explicit_format is not None:
                    actual_format = cell.number_format
                    # 既有引擎以区域短日期内建14/22存储这些别名；不能按库的美式展示字符串误报。
                    regional = {14: {'m/d/yyyy'}, 22: {'m/d/yyyy h:mm', 'm/d/yyyy hh:mm'}}
                    if explicit_format in regional.get(cell._style.numFmtId, set()):
                        actual_format = explicit_format
                    check(None, actual_format, explicit_format, '来源显式数字格式保持不变。')
                else:
                    numbers = prefs['numbers']
                    kind = value.get('valueType') or source.get('cellTypes', {}).get(cell.coordinate)
                    if native_date:
                        check('numbers.dateFormat', cell.number_format,
                            {'iso': 'yyyy-mm-dd', 'slash': 'yyyy/mm/dd',
                                'chinese': 'yyyy"年"m"月"d"日"'}[numbers['dateFormat']])
                    elif type(value.get('value')) in (int, float):
                        percent = kind == 'percentPoints'
                        places = numbers['percentPlaces'] if percent else numbers['decimalPlaces']
                        positive = ('0' if percent or not numbers['thousandsSeparator'] else '#,##0')
                        positive += ('.' + '0' * places if places else '') + ('"%"' if percent else '')
                        negative = '(' + positive + ')' if numbers['negativeStyle'] == 'parentheses' else (
                            '[Red]-' if numbers['negativeStyle'] == 'red' else '-') + positive
                        for key in (['percentPlaces', 'negativeStyle'] if percent else [
                            'decimalPlaces', 'thousandsSeparator', 'negativeStyle']):
                            check('numbers.' + key, cell.number_format, positive + ';' + negative)
        unstyled_body = [(r, c) for r, row in enumerate(source['rows'], 1)
            for c, raw in enumerate(row, 1) if r != source.get('headerRow', 0) + 1
            and not (isinstance(raw, dict) and raw.get('style'))]
        if unstyled_body:
            cell = sheet.cell(*unstyled_body[0])
            _font(cell.font, prefs['body'], 'body', sample, xlsx=True)
            sample('alignment', cell.alignment.horizontal, prefs['alignment'])
            sample('wrapText', bool(cell.alignment.wrap_text), prefs['wrapText'])
        header_index = source.get('headerRow', 0)
        headers = [sheet.cell(header_index + 1, index + 1) for index, raw in enumerate(source['rows'][header_index])
            if not (isinstance(raw, dict) and raw.get('style'))]
        if headers:
            header = headers[0]
            sample('header.font', header.font.name, FONTS[prefs['header']['font']])
            sample('header.size', header.font.sz, prefs['header']['size'])
            sample('header.bold', bool(header.font.bold), prefs['header']['bold'])
            sample('common.accentColor', header.fill.fgColor.rgb[-6:].upper(), prefs['common']['accentColor'][1:].upper())
            sample('borders', bool(header.border.bottom.style), prefs['borders'] in {'light', 'all'})
        if unstyled_body:
            cell = sheet.cell(*unstyled_body[0])
            sample('borders', bool(cell.border.left.style), prefs['borders'] == 'all')
        stripe = next((sheet.cell(r, c) for r, c in unstyled_body if (r - 1) % 2 == 0), None)
        if stripe:
            sample('striped', stripe.fill.fgColor.rgb == 'FFF4F7FA', prefs['striped'])
        check('freezeHeader', sheet.freeze_panes, 'A' + str(source.get('headerRow', 0) + 2) if prefs['freezeHeader'] else None)
        check('autoFilter', bool(sheet.auto_filter.ref), prefs['autoFilter'] and len(source['rows']) > 1)
        if prefs['rowHeight'] is not None:
            sample('rowHeight', sheet.row_dimensions[2].height, prefs['rowHeight'])
        if prefs['columnWidth'] is not None:
            sample('columnWidth', sheet.column_dimensions[get_column_letter(1)].width, prefs['columnWidth'])
        page = prefs['print']['page']
        check('print.page.paper', int(sheet.page_setup.paperSize), {'A4': 9, 'A3': 8, 'Letter': 1}[page['paper']])
        check('print.page.orientation', sheet.page_setup.orientation, page['orientation'])
        for side, value in page['margins'].items():
            check('print.page.margins.' + side, getattr(sheet.page_margins, side), value / 25.4)
        for name, attr in [('fitToWidth', 'fitToWidth'), ('fitToHeight', 'fitToHeight')]:
            if prefs['print']['scalePercent'] is None:
                actual = getattr(sheet.page_setup, attr)
                # 正式引擎对原生默认值1省略属性；显式0仍表示不限页数。
                check('print.' + name, 1 if actual is None else actual, prefs['print'][name] or 0)
        if prefs['print']['scalePercent'] is not None:
            check('print.scalePercent', sheet.page_setup.scale, prefs['print']['scalePercent'])
        check('print.repeatTitleRows', sheet.print_title_rows,
            '$1:$' + str(prefs['print']['repeatTitleRows']) if prefs['print']['repeatTitleRows'] else None)
    # 内容、距离及样式覆盖说明页和所有激活的页变体，不能用odd内容掩盖首页/偶数页缺失。
    hf = prefs['print']['headerFooter']
    values = {'title': frozen['state']['_documentContext']['title'], 'signer': prefs['common']['signer'],
        'period': frozen['state']['_documentContext']['periodLabel'], 'date': displayed_date(
            frozen['state']['_documentContext']['generatedDate'], prefs['common']['dateFormat']),
        'filename': 'report.xlsx', 'page': '&P', 'pages': '&N'}
    for sheet in book:
        location = {'sheet': sheet.title, 'part': parts.get(sheet.title)}
        distance_check = partial(check, evidence_kind=XLSX_HEADER_FOOTER_EVIDENCE, evidence_objects=location)
        for side in ('header', 'footer'):
            distance = getattr(sheet.page_margins, side)
            distance_check('print.headerFooter.' + side + 'Distance', None if distance is None else distance * 25.4,
                hf[side + 'Distance'])
        variants = ['odd']
        if sheet.HeaderFooter.differentFirst:
            variants.append('first')
        if sheet.HeaderFooter.differentOddEven:
            variants.append('even')
        for variant in variants:
            variant_location = {**location, 'variant': variant}
            for kind in ('header', 'footer'):
                native = getattr(sheet, variant + kind.title())
                for side in ('left', 'center', 'right'):
                    part = getattr(native, side)
                    region_check = partial(check, evidence_kind=XLSX_HEADER_FOOTER_EVIDENCE,
                        evidence_objects={**variant_location, 'kind': kind, 'side': side})
                    expected = ''
                    if hf['enabled']:
                        for literal, name, _, _ in Formatter().parse(hf[kind][side]):
                            expected += literal.replace('&', '&&')
                            if name:
                                expected += values[name] if name in {'page', 'pages'} else values[name].replace('&', '&&')
                    region_check('print.headerFooter.' + kind + '.' + side, part.text or '', expected)
                    if not hf['enabled'] or not part.text and not hf[kind][side]:
                        continue
                    style = hf['style']
                    face, _, weight = (part.font or '').rpartition(',')
                    region_check('print.headerFooter.style.font', face, FONTS[style['font']])
                    region_check('print.headerFooter.style.bold', weight == 'Bold' if part.text else None, style['bold'])
                    region_check('print.headerFooter.style.size', part.size, style['size'])
                    region_check('print.headerFooter.style.color', part.color, style['color'][1:].upper())
            partial(check, evidence_kind=XLSX_HEADER_FOOTER_EVIDENCE, evidence_objects=variant_location)(
                'print.headerFooter.enabled', any(getattr(getattr(sheet, variant + kind.title()), side).text
                for kind in ('header', 'footer') for side in ('left', 'center', 'right')),
                hf['enabled'] and any(hf[kind][side]
                    for kind in ('header', 'footer') for side in ('left', 'center', 'right')))
    signature_summary = read_workbook_signature(content, book, prefs, frozen, header_summary, check)
    if signature_summary['sourceStatus'] == 'verified':
        signature = book[signature_summary['sheet']]
        _font(signature['A2'].font, prefs['signature'], 'signature', sample, xlsx=True)
        sample('signature.align', signature['A2'].alignment.horizontal, prefs['signature']['align'])
    number_summary = read_workbook_numbers(content, book, prefs, frozen, header_summary, check)
    return header_summary, signature_summary, number_summary


def _slide_tables(deck, prefs, frozen, check):
    """按冻结表次序重建所有横向分组及纵向续页，逐格核对原生属性。"""
    sources = [(slide, table) for slide in frozen['slides'] for table in slide.get('tables', [])]
    native = [(slide, shape) for slide in deck.slides for shape in slide.shapes if shape.has_table]
    if not sources and not native:
        return
    check = partial(check, evidence_kind=PPTX_TABLE_FIELD_EVIDENCE)
    rgb = [int(prefs['common']['accentColor'][index:index + 2], 16) / 255 for index in (1, 3, 5)]
    luminance = sum((value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4) * weight
        for value, weight in zip(rgb, (.2126, .7152, .0722), strict=True))
    header_color = '#000000' if luminance > .179 else '#FFFFFF'
    cursor = 0
    body_runs = 0
    for number, (source_slide, source) in enumerate(sources, 1):
        caption = source['caption'] or source_slide['title']
        title = (f'表 {number} ' if prefs['tables']['captionNumbering'] else '') + caption
        table_page = 0
        for column in range(1, max(2, len(source['headers'])), 5):
            indices = [0, *range(column, min(column + 5, len(source['headers'])))]
            headers = [source['headers'][index] for index in indices]
            rows = [[row[index] for index in indices] for row in source['rows']]
            offset = 0
            while offset < len(rows):
                if cursor >= len(native):
                    check('tables.content', None, rows[offset:], '缺少冻结表格的原生续页。')
                    break
                slide, shape = native[cursor]
                cursor += 1
                table = shape.table
                actual = [[cell.text for cell in row.cells] for row in table.rows]
                header = offset == 0 or prefs['tables']['repeatHeader']
                count = len(actual) - int(header)
                expected = ([headers] if header else []) + rows[offset:offset + max(0, count)]
                check('tables.content', actual, expected, '全部冻结单元格按原生表格顺序核验，含续页及宽表列分组。')
                check('tables.repeatHeader', table.first_row, header)
                expected_title = title + (f'（续 {table_page + 1}）' if table_page else '')
                check('tables.captionNumbering', sum(shape.has_text_frame and shape.text == expected_title
                    for shape in slide.shapes), 1)
                check('tables.visibility', slide._element.get('show', '1') not in {'0', 'false'}
                    and not shape._element.xpath('.//p:cNvPr[@hidden="1" or @hidden="true"]'), True)
                check('tables.structure', not any(cell.is_merge_origin or cell.is_spanned
                    for row in table.rows for cell in row.cells), True)
                check('tables.bounds', shape.top >= 0 and shape.left >= 0
                    and shape.left + shape.width <= deck.slide_width
                    and shape.top + shape.height <= deck.slide_height * 640 / 720, True)
                for row_index, row in enumerate(table.rows):
                    is_header = header and row_index == 0
                    index = offset + row_index - int(header)
                    stripe = prefs['tables']['striped'] and index % 2 == 1
                    fill = (prefs['common']['accentColor'][1:].upper() if is_header
                        else 'EAF0F3' if stripe else 'FFFFFF')
                    for cell in row.cells:
                        shading = cell._tc.xpath('./a:tcPr/a:solidFill/a:srgbClr/@val')
                        check('tables.striped', shading, [fill])
                        for side in ('L', 'R', 'T', 'B'):
                            lines = cell._tc.xpath('./a:tcPr/a:ln' + side)
                            preset = prefs['tables']['borders']
                            actual_border = [(line.get('w'), any(child.tag.endswith('}noFill') for child in line),
                                [child.get('val') for child in line.iter() if child.tag.endswith('}srgbClr')]) for line in lines]
                            expected_border = [('0', True, [])] if preset == 'none' else [(
                                '9525' if preset == 'all' else '3175', False, ['D5DEDF'])]
                            check('tables.borders', actual_border, expected_border)
                        for paragraph_index, paragraph in enumerate(cell.text_frame.paragraphs):
                            style = {**prefs['typography']['table'],
                                **({'bold': True, 'color': header_color} if is_header else {})}
                            check('typography.table.lineHeight', paragraph.line_spacing, style['lineHeight'])
                            check('typography.table.spaceBefore', paragraph.space_before.pt
                                if paragraph.space_before is not None else 0,
                                style['spaceBefore'] if paragraph_index == 0 else 0)
                            check('typography.table.spaceAfter', paragraph.space_after.pt
                                if paragraph.space_after is not None else 0,
                                style['spaceAfter'] if paragraph_index == len(cell.text_frame.paragraphs) - 1 else 0)
                            check('tables.nativeRuns', bool(paragraph.runs) or not paragraph.text, True)
                            for run in paragraph.runs:
                                if not is_header:
                                    body_runs += 1
                                font = run.font
                                check('typography.table.font', font.name, FONTS[style['font']])
                                check('typography.table.size', font.size.pt if font.size is not None else None, style['size'])
                                check('typography.table.bold', bool(font.bold), style['bold'])
                                check('typography.table.color', str(font.color.rgb) if font.color.type == 1 else None,
                                    style['color'][1:].upper())
                table_page += 1
                if count <= 0:
                    check('tables.content', count, 'positive body rows')
                    break
                offset += count
    check('tables.content', len(native), cursor, '不得存在未绑定的额外原生表格。')
    check('tables.objectCoverage', [bool(sources), bool(native), cursor == len(native)], [True, True, True],
        '冻结表对象和实际表格页均非空，所有原生表格均已进入本次逐格回读。',
        evidence_objects={'sourceTables': len(sources), 'nativeTables': len(native), 'checkedNativeTables': cursor,
            'bodyRuns': body_runs})


def _slides(content, prefs, frozen, check):
    from .preference_pptx_indent_readback import read_pptx_indents

    native_checks = []
    original_check = check

    def check(path, actual, expected, *args, **kwargs):
        original_check(path, actual, expected, *args, **kwargs)
        native_checks.append({'path': 'pptx.' + path if path else None,
            'passed': actual == expected, 'coverage': kwargs.get('coverage', 'complete')})

    sample = partial(check, coverage='sample')
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    deck = Presentation(BytesIO(content))
    chart_slides = [index for index, source in enumerate(frozen['slides'], 1) if source.get('chartPath')]
    if chart_slides:
        dpi_rows = []
        for slide in deck.slides:
            for shape in slide.shapes:
                if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
                    continue
                media = shape.image.blob
                with Image.open(BytesIO(media)) as image:
                    dpi_rows.append({'mediaSha256': sha256(media).hexdigest(),
                        'effectiveDpi': {'x': image.width * 914400 / shape.width,
                            'y': image.height * 914400 / shape.height}})
        check('charts.imageDpi', len(dpi_rows) == len(chart_slides) and all(
            item['effectiveDpi']['x'] <= prefs['charts']['imageDpi'] + .05
            and item['effectiveDpi']['y'] <= prefs['charts']['imageDpi'] + .05 for item in dpi_rows), True,
            '从最终PPTX图片媒体和原生对象尺寸独立计算图表有效DPI。',
            evidence_kind=CHART_IMAGE_DPI_EVIDENCE,
            evidence_objects={'targetDpi': prefs['charts']['imageDpi'],
                'expectedImages': len(chart_slides), 'readImages': len(dpi_rows),
                'images': [{'mediaSha256': item['mediaSha256'], 'effectiveDpi': {
                    'x': round(item['effectiveDpi']['x'], 3), 'y': round(item['effectiveDpi']['y'], 3)}}
                    for item in dpi_rows]})
    check('aspectRatio', deck.slide_width / deck.slide_height, 4 / 3 if prefs['aspectRatio'] == '4:3' else 16 / 9)
    shapes = [shape for slide in deck.slides for shape in slide.shapes if shape.has_text_frame]
    for role, value in [('h1', frozen['state']['_documentContext']['title']),
        ('body', next((bullet for slide in frozen['slides'] for bullet in slide.get('bullets', [])), None))]:
        if value is None:
            continue
        shape = next((shape for shape in shapes if shape.text == value), None)
        if shape is None:
            # 分页首段不再是一整个文本框；由下方全对象来源片段回读核验。
            continue
        paragraph = shape.text_frame.paragraphs[0]
        _font(paragraph.runs[0].font, prefs['typography'][role], 'typography.' + role, sample)
        sample('typography.' + role + '.lineHeight', paragraph.line_spacing, prefs['typography'][role]['lineHeight'])
        for key, actual in [('spaceBefore', paragraph.space_before), ('spaceAfter', paragraph.space_after)]:
            sample('typography.' + role + '.' + key, actual.pt if actual is not None else 0, prefs['typography'][role][key])
    chart_number = 0
    for source in frozen['slides']:
        if not source.get('chartPath'):
            continue
        chart_number += 1
        value = ('图 ' + str(chart_number) + ' ' if prefs['charts']['captionNumbering'] else '') + source['title']
        caption = next((shape for shape in shapes if shape.text == value and shape.top >= 174 * 9525), None)
        check('charts.captionNumbering', caption is not None, True)
        if caption:
            paragraph = caption.text_frame.paragraphs[0]
            _font(paragraph.runs[0].font, prefs['typography']['caption'], 'typography.caption', sample)
            sample('typography.caption.lineHeight', paragraph.line_spacing, prefs['typography']['caption']['lineHeight'])
            for key, actual in [('spaceBefore', paragraph.space_before), ('spaceAfter', paragraph.space_after)]:
                sample('typography.caption.' + key, actual.pt if actual is not None else 0, prefs['typography']['caption'][key])
        check(None, any(shape.shape_type == MSO_SHAPE_TYPE.PICTURE for slide in deck.slides for shape in slide.shapes), True, '保留真实静态图像。')
    _slide_tables(deck, prefs, frozen, check)
    identity = _slide_signature(deck, prefs, frozen, check)
    if identity is not None:
        paragraph = identity.text_frame.paragraphs[0]
        if paragraph.runs:
            _font(paragraph.runs[0].font, prefs['signature'], 'signature', sample)
            sample('signature.lineHeight', paragraph.line_spacing, prefs['signature']['lineHeight'])
    read_pptx_indents(deck, prefs, frozen, original_check, native_checks)


def _document_captions(markdown, numbered):
    """从来源段落独立提取相邻图注；不使用生成器的展示 HTML 或回执。"""
    from bs4 import BeautifulSoup

    source = BeautifulSoup(MarkdownIt('commonmark').render(markdown), 'html.parser')
    captions = []
    for paragraph in source.find_all('p'):
        emphasis = paragraph.find('em', recursive=False)
        previous = paragraph.find_previous_sibling()
        if not emphasis or paragraph.get_text().strip() != emphasis.get_text().strip():
            continue
        if not previous or previous.name != 'p' or not previous.find('img', recursive=False):
            continue
        if previous.get_text().strip():
            continue
        text = emphasis.get_text().strip()
        if not text.startswith('图表：'):
            continue
        # 来源别名在展示阶段消歧；尚无独立映射时保守保留未核验状态。
        if '[[citation:' in text:
            return []
        captions.append(f'图 {len(captions) + 1}：{text.removeprefix("图表：")}' if numbered else text)
    return captions


def _document_chart_count(frozen):
    """Count Markdown images whose paths have a registered frozen source identity."""
    import posixpath
    from urllib.parse import unquote, urlsplit

    sources = {item['path'] for item in frozen['state'].get('sources', []) if isinstance(item.get('path'), str)}
    base = posixpath.dirname(frozen['markdownPath'])
    count = 0
    for token in MarkdownIt('commonmark').parse(frozen['markdown']):
        if token.type != 'inline':
            continue
        for child in token.children or ():
            if child.type != 'image':
                continue
            source = unquote(urlsplit(child.attrGet('src') or '').path)
            path = posixpath.normpath(posixpath.join(base, source))
            if path in sources:
                count += 1
    return count


def _check_pdf_captions(text, markdown, numbered, check):
    compact = ''.join(text.split())
    expected = Counter(''.join(item.split()) for item in _document_captions(markdown, numbered))
    for caption, count in expected.items():
        check('charts.captionNumbering', compact.count(caption), count,
            message='PDF 可见图注文字片段及出现数量匹配；不代表完整图注边界与全部语义块已核验。', coverage='sample')


def _word(content, prefs, frozen, check):
    sample = partial(check, coverage='sample')
    from docx import Document

    doc = Document(BytesIO(content))
    expected_images = _document_chart_count(frozen)
    if expected_images:
        from hashlib import sha256

        rows = []
        for shape in doc.inline_shapes:
            rel_id = shape._inline.graphic.graphicData.pic.blipFill.blip.embed
            image = doc.part.related_parts[rel_id].blob
            with Image.open(BytesIO(image)) as pixels:
                rows.append({'mediaSha256': sha256(image).hexdigest(), 'effectiveDpi': {
                    'x': round(pixels.width * 914400 / shape.width, 3),
                    'y': round(pixels.height * 914400 / shape.height, 3)}})
        coverage = 'complete' if len(rows) == expected_images else 'sample'
        check('charts.imageDpi', len(rows) == expected_images and all(
            item['effectiveDpi']['x'] <= prefs['charts']['imageDpi'] + .05
            and item['effectiveDpi']['y'] <= prefs['charts']['imageDpi'] + .05 for item in rows), True,
            '从最终DOCX媒体身份和DrawingML实际尺寸独立计算图表有效DPI。', coverage=coverage,
            evidence_kind=CHART_IMAGE_DPI_EVIDENCE,
            evidence_objects={'targetDpi': prefs['charts']['imageDpi'],
                'expectedImages': expected_images, 'readImages': len(rows), 'images': rows})
    for role, name in [('body', 'Normal'), ('h1', 'Heading 1'), ('h2', 'Heading 2'), ('h3', 'Heading 3'), ('caption', 'Caption')]:
        style = doc.styles[name]
        _font(style.font, prefs['typography'][role], 'typography.' + role, sample)
        paragraph = style.paragraph_format
        for key, actual in [('lineHeight', paragraph.line_spacing),
            ('spaceBefore', paragraph.space_before.pt if paragraph.space_before else 0),
            ('spaceAfter', paragraph.space_after.pt if paragraph.space_after else 0),
            ('indent', paragraph.first_line_indent.pt if paragraph.first_line_indent else 0)]:
            sample('typography.' + role + '.' + key, actual, prefs['typography'][role][key])
    section = doc.sections[0]
    width, height = {'A4': (210, 297), 'A3': (297, 420), 'Letter': (215.9, 279.4)}[prefs['page']['paper']]
    if prefs['page']['orientation'] == 'landscape':
        width, height = height, width
    sample('page.paper', section.page_width.mm, width)
    sample('page.orientation', section.page_height.mm, height)
    for side, value in prefs['page']['margins'].items():
        sample('page.margins.' + side, getattr(section, side + '_margin').mm, value)
    check('toc', any('TOC ' in (field.text or '') for field in doc.element.xpath('//w:instrText')), prefs['toc'])
    from .preference_word_table_readback import read_word_tables

    word_tables = read_word_tables(doc, prefs, frozen, check)
    pictures = [paragraph for paragraph in doc.paragraphs if paragraph._p.xpath('.//w:drawing')]
    pairs = [(picture, doc.paragraphs[index + 1]) for index, picture in enumerate(doc.paragraphs[:-1])
        if picture._p.xpath('.//w:drawing') and doc.paragraphs[index + 1].style.name == 'Caption'
        and picture._p.getnext() is doc.paragraphs[index + 1]._p
        and not doc.paragraphs[index + 1]._p.xpath('./w:bookmarkStart[starts-with(@w:name, "tblcap_")]')]
    if pairs:
        for picture, caption in pairs:
            check('charts.keepWithCaption', picture.paragraph_format.keep_with_next, prefs['charts']['keepWithCaption'])
            check('charts.keepWithCaption', caption.paragraph_format.keep_together, prefs['charts']['keepWithCaption'])
    expected_captions = _document_captions(frozen['markdown'], prefs['charts']['captionNumbering'])
    if expected_captions:
        check('charts.captionNumbering', [caption.text.strip() for _, caption in pairs], expected_captions,
            message='全部原生图文相邻图注与冻结编号及原文一致。')
    if pictures:
        check(None, len(doc.inline_shapes) > 0, True, '真实静态图像保留为原生文档图片。')
    signature = _word_signature(doc, prefs, frozen, check)
    if signature and signature.runs:
        _font(signature.style.font, prefs['signature'], 'signature', sample)
        sample('signature.align', signature.alignment, {'left': 0, 'center': 1, 'right': 2}[prefs['signature']['align']])
        sample('signature.lineHeight', signature.style.paragraph_format.line_spacing, prefs['signature']['lineHeight'])
        sample('signature.spaceBefore', signature.paragraph_format.space_before.pt, prefs['signature']['spaceBefore'])
    labels = [item['label'] for item in frozen['state'].get('_citationPresentations', [])]
    if labels:
        text = '\n'.join(paragraph.text for paragraph in doc.paragraphs)
        check('sources', all(label in text for label in labels), prefs['sources'])
    from .preference_document_table_readback import read_table_captions

    return read_table_captions(doc, 'word', prefs['tables']['captionNumbering'], frozen, check), word_tables


def _pdf(content, prefs, frozen, check):
    sample = partial(check, coverage='sample')
    import pymupdf
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content))
    check(None, len(reader.pages) > 0, True, '真实 PDF 至少有一页且可独立读取。')
    width, height = {'A4': (210, 297), 'A3': (297, 420), 'Letter': (215.9, 279.4)}[prefs['page']['paper']]
    if prefs['page']['orientation'] == 'landscape':
        width, height = height, width
    sample('page.paper', float(reader.pages[0].mediabox.width) * 25.4 / 72, width)
    sample('page.orientation', float(reader.pages[0].mediabox.height) * 25.4 / 72, height)
    check('bookmarks', bool(reader.outline), prefs['bookmarks'])
    pdf = pymupdf.open(stream=content, filetype='pdf')
    expected_images = _document_chart_count(frozen)
    if expected_images:
        dpi_rows = []
        for page in pdf:
            for item in page.get_image_info(xrefs=True):
                x0, y0, x1, y1 = item['bbox']
                if x1 <= x0 or y1 <= y0:
                    continue
                xref = item.get('xref')
                media = pdf.extract_image(xref)['image'] if type(xref) is int and xref > 0 else b''
                dpi_rows.append({'mediaSha256': sha256(media).hexdigest() if media else None,
                    'effectiveDpi': {'x': item['width'] * 72 / (x1 - x0),
                        'y': item['height'] * 72 / (y1 - y0)}, 'xref': xref})
        coverage = 'complete' if len(dpi_rows) == expected_images else 'sample'
        check('charts.imageDpi', len(dpi_rows) == expected_images and all(
            item['mediaSha256'] is not None
            and item['effectiveDpi']['x'] <= prefs['charts']['imageDpi'] + .05
            and item['effectiveDpi']['y'] <= prefs['charts']['imageDpi'] + .05 for item in dpi_rows), True,
            '从最终PDF图像资源与实际绘制矩阵独立计算图表有效DPI。', coverage=coverage,
            evidence_kind=CHART_IMAGE_DPI_EVIDENCE,
            evidence_objects={'targetDpi': prefs['charts']['imageDpi'],
                'expectedImages': expected_images, 'readImages': len(dpi_rows), 'images': dpi_rows})
    anchors = {item['anchor'] for item in frozen['state']['_documentContext']['headingNumbers'] if item.get('anchor')}
    spans, heading_spans = [], []
    for page in pdf:
        page_spans = [span for block in page.get_text('dict')['blocks']
            for line in block.get('lines', []) for span in line['spans']]
        # 目录链接只是标题引用；按冻结章节锚点排除其链接来源，不能按期望样式挑选标题。
        references = [link['from'] for link in page.get_links() if link.get('nameddest') in anchors]
        spans.extend(page_spans)
        heading_spans.extend(span for span in page_spans if not any(rect.contains(pymupdf.Point(
            (span['bbox'][0] + span['bbox'][2]) / 2, (span['bbox'][1] + span['bbox'][3]) / 2)) for rect in references))
    _check_pdf_captions('\n'.join(page.get_text() for page in pdf), frozen['markdown'],
        prefs['charts']['captionNumbering'], check)
    tokens = MarkdownIt('commonmark').enable('table').parse(frozen['markdown'])
    body = next((token.content for index, token in enumerate(tokens) if token.type == 'inline'
        and index and tokens[index - 1].type == 'paragraph_open' and not token.content.startswith(('[', '!'))), None)
    if body:
        span = next((span for span in spans if body[:8] in span['text']), None)
        check(None, span is not None, True, '冻结业务正文出现在真实 PDF 可见文字中。')
        if span:
            sample('typography.body.size', span['size'], prefs['typography']['body']['size'])
            sample('typography.body.color', span['color'], int(prefs['typography']['body']['color'][1:], 16))
            sample('typography.body.font', 'Serif' in span['font'], prefs['typography']['body']['font'] == 'serif')
            sample('typography.body.bold', bool(span['flags'] & 16), prefs['typography']['body']['bold'])
    role_texts = [(f'h{item["level"] - 1}', item['title'])
        for item in frozen['state']['_documentContext']['headingNumbers']]
    table_text = next((token.content for index, token in enumerate(tokens) if token.type == 'inline'
        and index and tokens[index - 1].type == 'td_open'), None)
    if table_text:
        role_texts.append(('table', table_text))
    caption_text = next(iter(_document_captions(frozen['markdown'], prefs['charts']['captionNumbering'])), None)
    if caption_text:
        role_texts.append(('caption', caption_text))
    for role, text in role_texts:
        style = prefs['typography'][role]
        candidates = heading_spans if role in {'h1', 'h2', 'h3'} else spans
        span = next((span for span in candidates if text[:8] in span['text']), None)
        check(None, span is not None, True, '冻结角色内容出现在真实 PDF 可见文字中。')
        if span:
            sample('typography.' + role + '.size', span['size'], style['size'])
            sample('typography.' + role + '.color', span['color'], int(style['color'][1:], 16))
            sample('typography.' + role + '.font', 'Serif' in span['font'], style['font'] == 'serif')
            sample('typography.' + role + '.bold', bool(span['flags'] & 16), style['bold'])
    signature_date = displayed_date(frozen['state']['_documentContext']['generatedDate'], prefs['common']['dateFormat'])
    signature = next((span for index, span in enumerate(spans[:-1]) if span['text'] == prefs['common']['signer']
        and spans[index + 1]['text'] == signature_date), None)
    if signature:
        for key, actual, expected in [('font', 'Serif' in signature['font'], prefs['signature']['font'] == 'serif'),
            ('size', signature['size'], prefs['signature']['size']),
            ('color', signature['color'], int(prefs['signature']['color'][1:], 16)),
            ('bold', bool(signature['flags'] & 16), prefs['signature']['bold'])]:
            sample('signature.' + key, actual, expected)
    labels = [item['label'] for item in frozen['state'].get('_citationPresentations', [])]
    if labels:
        check('sources', all(label in '\n'.join(page.get_text() for page in pdf) for label in labels), prefs['sources'])
    from .preference_document_table_readback import read_table_captions

    table_captions = read_table_captions('\n'.join(page.get_text() for page in pdf), 'pdf',
        prefs['tables']['captionNumbering'], frozen, check)
    pdf.close()
    return table_captions
