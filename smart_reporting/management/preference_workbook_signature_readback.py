"""完整核验生成工作簿末尾说明页的原生文本，不据此证明打印或视觉。"""

import math
import re
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

from ..preferences.workbook_adapter import displayed_date
from .preference_workbook_header_footer_readback import _NS, _boolean, _xml

XLSX_SIGNATURE_EVIDENCE = 'xlsx_native_signature_content_v1'
GUARD = 'signature.nativeStructure'
FIELDS = ('common.signer', 'common.dateFormat', 'signature.description')


def _native_text(raw):
    def decode(match):
        value = int(match[1], 16)
        if 0xD800 <= value <= 0xDFFF:
            raise ValueError('unsupported native surrogate escape')
        return chr(value)

    # 单次解码：_x005F_x0041_是字面_x0041_，不能递归解码成A。
    return re.sub(r'_x([0-9A-Fa-f]{4})_', decode, raw)


def _positive_dimension(value):
    return math.isfinite(float(value)) and float(value) > 0


def read_workbook_signature(content, book, prefs, frozen, source, check):
    """原生包身份复用已核组；说明页逐行逐格与独立库解析结果交叉核验。"""
    expected = ['报告落款', prefs['common']['signer'], displayed_date(
        frozen['state']['_documentContext']['generatedDate'], prefs['common']['dateFormat']),
        *prefs['signature']['description'].splitlines()]
    summary = {'sourceStatus': 'unverified', 'status': 'unverified', 'sheet': None, 'part': None,
        'expectedRows': len(expected), 'nativeRows': 0, 'checkedRows': 0, 'cells': [], 'issues': []}
    lines = []
    try:
        # 已核组保证ZIP成员、类型、根关系、工作表身份/顺序/可见性及无别名。
        if (source.get('sourceStatus') != 'verified' or source.get('status') != 'passed'
            or source.get('expectedSheets') != len(frozen['sheets']) + 1
            or source.get('sheetNames') != book.sheetnames
            or len(source.get('worksheetParts', [])) != len(book.sheetnames)):
            raise ValueError('native signature sheet identity unavailable')
        summary.update(sheet=source['sheetNames'][-1], part=source['worksheetParts'][-1])
        sheet = book[summary['sheet']]
        ns = '{' + _NS + '}'
        with ZipFile(BytesIO(content)) as package:
            node = _xml(package, summary['part'], _NS, 'worksheet')
        allowed = {'sheetPr', 'dimension', 'sheetViews', 'sheetFormatPr', 'cols', 'sheetData',
            'pageMargins', 'pageSetup', 'headerFooter', 'printOptions'}
        if any(child.tag not in {ns + name for name in allowed} for child in node):
            raise ValueError('unsupported signature worksheet objects')
        if len({child.tag for child in node}) != len(node):
            raise ValueError('duplicate signature worksheet objects')
        text_tags = {ns + 't', *{ns + variant + kind for variant in ('odd', 'first', 'even')
            for kind in ('Header', 'Footer')}}
        for child in node.iter():
            if ((child.tag not in text_tags and re.fullmatch(r'[ \t\r\n]*', child.text or '') is None)
                or re.fullmatch(r'[ \t\r\n]*', child.tail or '') is None):
                raise ValueError('unconsumed mixed signature XML text')
        defaults = node.find(ns + 'sheetFormatPr')
        if defaults is not None and _boolean(defaults.get('zeroHeight')):
            raise ValueError('hidden signature default rows')
        default_height = defaults.get('defaultRowHeight', '1') if defaults is not None else '1'
        default_width = defaults.get('defaultColWidth', '1') if defaults is not None else '1'
        columns = node.findall(ns + 'cols/' + ns + 'col')
        used_columns = [column for column in columns if int(column.get('min')) <= 1 <= int(column.get('max'))]
        if len(used_columns) > 1 or not _positive_dimension(
            used_columns[0].get('width', default_width) if used_columns else default_width):
            raise ValueError('ambiguous or hidden signature column width')
        for column in columns:
            if (_boolean(column.get('hidden')) or _boolean(column.get('collapsed'))
                or column.get('outlineLevel', '0') != '0'
                or not _positive_dimension(column.get('width', default_width))):
                raise ValueError('hidden signature column')
        data = node.find(ns + 'sheetData')
        if data is None:
            raise ValueError('missing signature rows')
        summary['nativeRows'] = len(data)
        if len(data) != len(expected):
            raise ValueError('signature row coverage mismatch')
        for index, row in enumerate(data, 1):
            coordinate = 'A' + str(index)
            if (row.tag != ns + 'row' or row.get('r') != str(index) or len(row) != 1
                or _boolean(row.get('hidden')) or _boolean(row.get('collapsed'))
                or row.get('outlineLevel', '0') != '0'
                or not _positive_dimension(row.get('ht', default_height))):
                raise ValueError('ambiguous or hidden signature row')
            cell = row[0]
            if (cell.tag != ns + 'c' or cell.get('r') != coordinate or cell.get('t') != 'inlineStr'
                or set(cell.attrib) - {'r', 's', 't'} or len(cell) != 1 or cell[0].tag != ns + 'is'
                or cell[0].attrib or len(cell[0]) != 1 or cell[0][0].tag != ns + 't'):
                raise ValueError('unsupported signature cell text')
            text = cell[0][0]
            if (len(text) or set(text.attrib) - {'{http://www.w3.org/XML/1998/namespace}space'}
                or text.get('{http://www.w3.org/XML/1998/namespace}space', 'preserve') not in ('preserve', 'default')):
                raise ValueError('ambiguous signature text')
            raw = text.text or ''
            # openpyxl的inlineStr读取保留转义码；先交叉核原文，再独立解码原生语义。
            if raw != (sheet[coordinate].value or ''):
                raise ValueError('signature text parser mismatch')
            lines.append(_native_text(raw))
            summary['cells'].append(coordinate)
            summary['checkedRows'] += 1
        if lines[0] != expected[0]:
            raise ValueError('signature title mismatch')
        summary.update(sourceStatus='verified', status='passed')
    except Exception:
        summary['issues'].append({'code': 'management_preference_workbook_signature_unverified',
            'message': '说明页身份、可见文本或完整单元格结构未获核验，不能授予落款完整原生证据。'})
    complete = summary['sourceStatus'] == 'verified'
    options = {'coverage': 'complete' if complete else 'sample', 'evidence_kind': XLSX_SIGNATURE_EVIDENCE}
    check(GUARD, complete, True, evidence_objects=deepcopy(summary), **options)
    for field, actual, value, cells in (
        (FIELDS[0], lines[1] if complete else None, expected[1], ['A2']),
        (FIELDS[1], lines[2] if complete else None, expected[2], ['A3']),
        (FIELDS[2], '\n'.join(lines[3:]) if complete else None, '\n'.join(expected[3:]), summary['cells'][3:]),
    ):
        check(field, actual, value, '唯一末尾说明页的落款文本已逐行逐格核验。',
            evidence_objects={'sheet': summary['sheet'], 'part': summary['part'], 'cells': cells}, **options)
    return summary
