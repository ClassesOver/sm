"""按冻结来源逐格核验数字原始身份和直接生效格式，不推断视觉验收。"""

import re
from copy import deepcopy
from datetime import date
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

from openpyxl.styles.numbers import BUILTIN_FORMATS
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import to_excel

from .preference_workbook_header_footer_readback import (
    _NS,
    _boolean,
    _content_types,
    _relationships,
    _require_content_type,
    _target,
    _xml,
)
from .preference_workbook_signature_readback import _positive_dimension

XLSX_NUMBER_EVIDENCE = 'xlsx_native_number_fields_v1'
GUARD = 'numbers.nativeStructure'
FIELDS = ('decimalPlaces', 'thousandsSeparator', 'negativeStyle', 'percentPlaces', 'dateFormat')
_NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
_N = '{' + _NS + '}'


def _kind(value, source, address, epoch):
    raw = value.get('value')
    if value.get('valueType') == 'date' and not value.get('formula'):
        try:
            parsed = date.fromisoformat(raw)
            if parsed.year >= 1900:
                return 'date', to_excel(parsed, epoch)
        except (ValueError, TypeError):
            pass
    if type(raw) in (int, float):
        return ('percent' if (value.get('valueType') or source.get('cellTypes', {}).get(address))
            == 'percentPoints' else 'number'), raw
    return None, None


def _fields(kind):
    return ('dateFormat',) if kind == 'date' else ('percentPlaces', 'negativeStyle') if kind == 'percent' else (
        'decimalPlaces', 'thousandsSeparator', 'negativeStyle')


def _expected_format(numbers, kind):
    if kind == 'date':
        return {'iso': 'yyyy-mm-dd', 'slash': 'yyyy/mm/dd', 'chinese': 'yyyy"年"m"月"d"日"'}[numbers['dateFormat']]
    percent = kind == 'percent'
    places = numbers['percentPlaces'] if percent else numbers['decimalPlaces']
    positive = ('0' if percent or not numbers['thousandsSeparator'] else '#,##0')
    positive += ('.' + '0' * places if places else '') + ('"%"' if percent else '')
    negative = '(' + positive + ')' if numbers['negativeStyle'] == 'parentheses' else (
        '[Red]-' if numbers['negativeStyle'] == 'red' else '-') + positive
    return positive + ';' + negative


def _styles(package):
    relationships = _relationships(package, 'xl/_rels/workbook.xml.rels')
    styles = [item for item in relationships.values() if item.get('Type', '').endswith('/styles')]
    if len(styles) != 1:
        raise ValueError('ambiguous native number styles')
    part = _target(styles[0], 'xl', 'styles')
    _require_content_type(_content_types(package), part, 'styles+xml')
    root = _xml(package, part, _NS, 'styleSheet')
    groups = {}
    for name in ('numFmts', 'cellXfs', 'cellStyleXfs'):
        nodes = root.findall(_N + name)
        if len(nodes) != (0 if name == 'numFmts' and not nodes else 1):
            raise ValueError('ambiguous native format collection')
        group = nodes[0] if nodes else []
        if nodes and int(group.get('count')) != len(group):
            raise ValueError('native format count mismatch')
        groups[name] = group
    if (not len(groups['cellXfs']) or not len(groups['cellStyleXfs'])
        or groups['cellStyleXfs'][0].get('numFmtId', '0') != '0'):
        raise ValueError('unresolved inherited number format')
    custom = {}
    for item in groups['numFmts']:
        identity = int(item.get('numFmtId'))
        code = item.get('formatCode')
        if item.tag != _N + 'numFmt' or identity < 164 or identity in custom or not code:
            raise ValueError('ambiguous custom number format')
        custom[identity] = code
    formats = []
    for item in groups['cellXfs']:
        identity = int(item.get('numFmtId', '0'))
        if (item.tag != _N + 'xf' or item.get('xfId', '0') != '0'
            or identity and not _boolean(item.get('applyNumberFormat'), True)):
            raise ValueError('number format is not directly active')
        code = custom.get(identity, BUILTIN_FORMATS.get(identity))
        if code is None:
            raise ValueError('unknown native number format')
        formats.append((identity, code))
    return formats


def _numeric_identity(cell, expected, formula):
    values, formulas = cell.findall(_N + 'v'), cell.findall(_N + 'f')
    if (cell.get('t', 'n') != 'n' or len(values) != 1 or len(values[0]) or values[0].attrib
        or any(child.tag not in (_N + 'v', _N + 'f') for child in cell)
        or len(formulas) != bool(formula) or formula and (formulas[0].attrib or len(formulas[0])
            or formulas[0].text != formula.lstrip('='))):
        raise ValueError('native numeric value/formula type mismatch')
    raw = (values[0].text or '').strip()
    if (_NUMBER.fullmatch(raw) is None or not Decimal(raw).is_finite()
        or Decimal(raw) != Decimal(str(expected))):
        raise ValueError('frozen numeric value/cache changed')


def read_workbook_numbers(content, book, prefs, frozen, source, check):
    """完整来源/对象见证；格式不匹配保留字段失败，身份不明则整组拒证。"""
    summary = {'sourceStatus': 'unverified', 'status': 'unverified', 'sourceSheets': len(frozen['sheets']),
        'checkedSheets': 0, 'sheetNames': [], 'worksheetParts': [], 'expectedCells': 0, 'checkedCells': 0,
        'cells': [], 'fields': {field: [] for field in FIELDS}, 'issues': []}
    comparisons = []
    try:
        names = [sheet['name'] for sheet in frozen['sheets']]
        if (source.get('sourceStatus') != 'verified' or source.get('status') != 'passed'
            or source.get('sheetNames') != book.sheetnames or source.get('sourceSheets') != len(names)
            or source.get('sheetNames', [])[:-1] != names):
            raise ValueError('native numeric sheet identity unavailable')
        parts = dict(zip(source['sheetNames'], source['worksheetParts'], strict=True))
        with ZipFile(BytesIO(content)) as package:
            formats = _styles(package)
            for sheet in frozen['sheets']:
                name, part = sheet['name'], parts[sheet['name']]
                root = _xml(package, part, _NS, 'worksheet')
                if any(root.find(_N + tag) is not None for tag in ('conditionalFormatting', 'mergeCells', 'extLst', 'tableParts')):
                    raise ValueError('unsupported effective number format objects')
                if any(len(root.findall(_N + tag)) > 1 for tag in ('sheetData', 'cols', 'sheetFormatPr')):
                    raise ValueError('ambiguous numeric worksheet objects')
                data = root.find(_N + 'sheetData')
                rows, cells = {}, {}
                for row in data:
                    index = int(row.get('r'))
                    if row.tag != _N + 'row' or index in rows:
                        raise ValueError('ambiguous native numeric row')
                    rows[index] = row
                    for cell in row:
                        address = cell.get('r')
                        if cell.tag != _N + 'c' or address in cells:
                            raise ValueError('ambiguous native numeric cell')
                        cells[address] = cell
                expected_addresses = {get_column_letter(c) + str(r) for r, row in enumerate(sheet['rows'], 1)
                    for c in range(1, len(row) + 1)}
                if set(cells) != expected_addresses or set(rows) != set(range(1, len(sheet['rows']) + 1)):
                    raise ValueError('native numeric grid differs from source')
                defaults = root.find(_N + 'sheetFormatPr')
                default_height = defaults.get('defaultRowHeight', '1') if defaults is not None else '1'
                default_width = defaults.get('defaultColWidth', '1') if defaults is not None else '1'
                for r, row in enumerate(sheet['rows'], 1):
                    for c, raw in enumerate(row, 1):
                        address = get_column_letter(c) + str(r)
                        value = raw if isinstance(raw, dict) else {'value': raw}
                        kind, expected = _kind(value, sheet, address, book.epoch)
                        if kind is None:
                            continue
                        summary['expectedCells'] += 1
                        cell = cells[address]
                        if cell not in list(rows[r]):
                            raise ValueError('native numeric row coordinate mismatch')
                        columns = [col for col in root.findall(_N + 'cols/' + _N + 'col')
                            if int(col.get('min')) <= c <= int(col.get('max'))]
                        if (defaults is not None and _boolean(defaults.get('zeroHeight'))
                            or _boolean(rows[r].get('hidden')) or not _positive_dimension(rows[r].get('ht', default_height))
                            or len(columns) > 1 or columns and (_boolean(columns[0].get('hidden'))
                                or not _positive_dimension(columns[0].get('width', default_width)))
                            or not columns and not _positive_dimension(default_width)):
                            raise ValueError('numeric source is hidden or collapsed')
                        _numeric_identity(cell, expected, value.get('formula'))
                        style_index = cell.get('s', '0')
                        if re.fullmatch('[0-9]+', style_index) is None or int(style_index) >= len(formats):
                            raise ValueError('invalid native number style index')
                        identity, actual = formats[int(style_index)]
                        if actual != book[name][address].number_format:
                            raise ValueError('native numeric format parse mismatch')
                        explicit = value.get('style', {}).get('numberFormat')
                        override = explicit is not None
                        regional = {14: {'m/d/yyyy'}, 22: {'m/d/yyyy h:mm', 'm/d/yyyy hh:mm'}}
                        if override and actual != explicit and explicit not in regional.get(identity, set()):
                            raise ValueError('explicit source number format changed')
                        location = {'sheet': name, 'part': part, 'cell': address}
                        summary['cells'].append({**location, 'kind': kind, 'override': override})
                        summary['checkedCells'] += 1
                        if not override:
                            for field in _fields(kind):
                                summary['fields'][field].append(deepcopy(location))
                                comparisons.append((field, actual, _expected_format(prefs['numbers'], kind), location))
                summary['sheetNames'].append(name)
                summary['worksheetParts'].append(part)
                summary['checkedSheets'] += 1
        summary['sourceStatus'], summary['status'] = 'verified', 'passed'
    except Exception:
        summary['issues'].append({'code': 'management_preference_workbook_numbers_native_unverified',
            'message': '无法完整核验数字来源、原生值/公式缓存、显示对象或生效样式，不授予完整数字字段证据。'})
    check(GUARD, summary['status'] == 'passed', True, evidence_kind=XLSX_NUMBER_EVIDENCE,
        coverage='complete' if summary['status'] == 'passed' else 'sample', evidence_objects=deepcopy(summary))
    if summary['status'] == 'passed':
        for field, actual, expected, location in comparisons:
            check('numbers.' + field, actual, expected, evidence_kind=XLSX_NUMBER_EVIDENCE,
                evidence_objects=location)
    return summary
