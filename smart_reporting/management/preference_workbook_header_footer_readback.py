"""独立核验XLSX打印区域原生包；扁平解析值不能自行证明完整字段覆盖。"""

import math
import posixpath
import re
from copy import deepcopy
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

XLSX_HEADER_FOOTER_EVIDENCE = 'xlsx_native_header_footer_fields_v1'
GUARD = 'print.headerFooter.nativeStructure'
_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
_DOC_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
_CONTENT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'
_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.'
_SIDES = {'L': 'left', 'C': 'center', 'R': 'right'}
_PREFIX = re.compile(r'&"([^"&,\x00-\x1f]+),(Bold|Regular)"&(\d{1,3}) ?&K([0-9A-Fa-f]{6})')


def _boolean(value, default=False):
    if value is None:
        return default
    if value not in ('0', '1', 'false', 'true'):
        raise ValueError('invalid native boolean')
    return value in ('1', 'true')


def _section(text):
    # 单次解码保护_x005F_x0041_字面量，不递归把它变成A。
    text = re.sub(r'_x([0-9A-Fa-f]{4})_', lambda match: chr(int(match[1], 16)), text)
    result, cursor = {}, 0
    while cursor < len(text):
        if text[cursor:cursor + 1] != '&' or text[cursor + 1:cursor + 2] not in _SIDES:
            raise ValueError('section position unavailable')
        side = _SIDES[text[cursor + 1]]
        if side in result:
            raise ValueError('duplicate section position')
        prefix = _PREFIX.match(text, cursor + 2)
        if prefix is None or not 0 < int(prefix[3]) <= 409:
            raise ValueError('unsupported section style')
        cursor, value = prefix.end(), []
        while cursor < len(text):
            char = text[cursor]
            if char != '&':
                if ord(char) < 32 and char != '\n' or 0xD800 <= ord(char) <= 0xDFFF:
                    raise ValueError('unsupported native character')
                value.append(char)
                cursor += 1
                continue
            code = text[cursor + 1:cursor + 2]
            if code in _SIDES:
                break
            if code not in ('&', 'P', 'N') or code == 'P' and re.match(r'[+-]\d', text[cursor + 2:]):
                raise ValueError('unsupported inline header format')
            value.append('&' + code)
            cursor += 2
        result[side] = {'font': prefix[1] + ',' + prefix[2], 'size': int(prefix[3]),
            'color': prefix[4], 'text': ''.join(value)}
    return result


def _xml(package, path, namespace, name):
    data = package.read(path)
    if b'<!DOCTYPE' in data.upper():
        raise ValueError('unsupported XML declaration')
    node = ElementTree.fromstring(data)
    if node.tag != '{' + namespace + '}' + name:
        raise ValueError('native namespace mismatch')
    return node


def _relationships(package, path):
    node = _xml(package, path, _REL, 'Relationships')
    relationships = {}
    for item in node:
        if item.tag != '{' + _REL + '}Relationship' or not item.get('Id') or item.get('Id') in relationships:
            raise ValueError('ambiguous native relationship')
        relationships[item.get('Id')] = item.attrib
    return relationships


def _content_types(package):
    node = _xml(package, '[Content_Types].xml', _CONTENT_NS, 'Types')
    defaults, overrides = {}, {}
    for item in node:
        content_type = item.get('ContentType')
        if not content_type or len(item):
            raise ValueError('native content type unavailable')
        if item.tag == '{' + _CONTENT_NS + '}Default':
            extension = item.get('Extension', '').casefold()
            if not re.fullmatch('[a-z0-9]+', extension) or extension in defaults:
                raise ValueError('ambiguous native default content type')
            defaults[extension] = content_type
        elif item.tag == '{' + _CONTENT_NS + '}Override':
            path = item.get('PartName', '')
            if (not path.startswith('/') or posixpath.normpath(path) != path or path in overrides
                or any(char in path for char in ('\\', ':', '#', '?', '%'))):
                raise ValueError('ambiguous native override content type')
            overrides[path] = content_type
        else:
            raise ValueError('unsupported native content type declaration')
    return defaults, overrides


def _require_content_type(content_types, path, expected):
    defaults, overrides = content_types
    actual = overrides.get('/' + path, defaults.get(path.rsplit('.', 1)[-1].casefold()))
    if actual != _CONTENT_TYPE + expected:
        raise ValueError('native part content type mismatch')


def _target(relationship, root, kind):
    value = relationship.get('Target', '')
    if (relationship.get('TargetMode') not in (None, 'Internal')
        or relationship.get('Type') != _DOC_REL + '/' + kind or not value
        or any(char in value for char in ('\\', ':', '#', '?', '%'))):
        raise ValueError('unsupported native relationship target')
    path = posixpath.normpath(value.lstrip('/') if value.startswith('/') else posixpath.join(root, value))
    if path.startswith('../') or path in ('.', '..'):
        raise ValueError('native relationship escapes package')
    return path


def read_header_footer_group(content, book, prefs, frozen, check):
    """完整原生对象见证；任何不完整解析只记告警，不中断已生成文件。"""
    summary = {'sourceStatus': 'unverified', 'status': 'unverified', 'sourceSheets': 0,
        'expectedSheets': 0, 'nativeSheets': 0, 'checkedSheets': 0,
        'sheetNames': [], 'worksheetParts': [], 'sheetVariants': [], 'variants': [],
        'configuredStylePositions': [[kind, side] for kind in ('header', 'footer') for side in _SIDES.values()
            if prefs['print']['headerFooter']['enabled'] and prefs['print']['headerFooter'][kind][side]], 'issues': []}
    try:
        names = [sheet['name'] for sheet in frozen['sheets']]
        if not names or any(not isinstance(name, str) or not name for name in names) or len({
            name.casefold() for name in names}) != len(names):
            raise ValueError('source sheet identity unavailable')
        summary['sourceSheets'] = len(names)
        signature, index = '说明', 2
        while signature.casefold() in {name.casefold() for name in names}:
            signature, index = '说明' + str(index), index + 1
        names = [*names, signature]
        summary['expectedSheets'] = len(names)
        with ZipFile(BytesIO(content)) as package:
            if len(package.namelist()) != len(set(package.namelist())):
                raise ValueError('duplicate package member')
            content_types = _content_types(package)
            _require_content_type(content_types, 'xl/workbook.xml', 'sheet.main+xml')
            roots = _relationships(package, '_rels/.rels')
            documents = [item for item in roots.values() if item.get('Type') == _DOC_REL + '/officeDocument']
            if len(documents) != 1 or _target(documents[0], '', 'officeDocument') != 'xl/workbook.xml':
                raise ValueError('ambiguous workbook identity')
            workbook = _xml(package, 'xl/workbook.xml', _NS, 'workbook')
            sheet_groups = workbook.findall('{' + _NS + '}sheets')
            if len(sheet_groups) != 1:
                raise ValueError('ambiguous native sheet collection')
            sheets = list(sheet_groups[0])
            summary['nativeSheets'] = len(sheets)
            if ([sheet.get('name') for sheet in sheets] != names or book.sheetnames != names
                or any(not re.fullmatch('[0-9]+', sheet.get('sheetId', ''))
                    or not 1 <= int(sheet.get('sheetId')) <= 4294967295 for sheet in sheets)
                or len({int(sheet.get('sheetId')) for sheet in sheets}) != len(sheets)):
                raise ValueError('native sheets differ from complete source')
            relationships = _relationships(package, 'xl/_rels/workbook.xml.rels')
            used, used_ids = set(), set()
            for sheet, native in zip(sheets, book, strict=True):
                identity = sheet.get('{' + _DOC_REL + '}id')
                if (sheet.tag != '{' + _NS + '}sheet' or identity in used_ids
                    or identity not in relationships or sheet.get('state', 'visible') != 'visible'):
                    raise ValueError('ambiguous native sheet identity')
                used_ids.add(identity)
                path = _target(relationships[identity], 'xl', 'worksheet')
                if path in used:
                    raise ValueError('aliased native worksheet')
                used.add(path)
                _require_content_type(content_types, path, 'worksheet+xml')
                worksheet = _xml(package, path, _NS, 'worksheet')
                groups = worksheet.findall('{' + _NS + '}headerFooter')
                margins = worksheet.findall('{' + _NS + '}pageMargins')
                if len(groups) > 1 or len(margins) != 1 or worksheet.find('{' + _NS + '}legacyDrawingHF') is not None:
                    raise ValueError('ambiguous native print objects')
                for side in ('header', 'footer'):
                    distance = float(margins[0].get(side))
                    if not math.isfinite(distance) or distance < 0 or distance != getattr(native.page_margins, side):
                        raise ValueError('native margin parse mismatch')
                group = groups[0] if groups else None
                attributes = group.attrib if group is not None else {}
                if set(attributes) - {'differentFirst', 'differentOddEven', 'scaleWithDoc', 'alignWithMargins'}:
                    raise ValueError('unsupported header/footer attributes')
                flags = {key: _boolean(value, key in ('scaleWithDoc', 'alignWithMargins'))
                    for key, value in attributes.items()}
                if (flags.get('differentFirst', False) != bool(native.HeaderFooter.differentFirst)
                    or flags.get('differentOddEven', False) != bool(native.HeaderFooter.differentOddEven)):
                    raise ValueError('native page variant parse mismatch')
                nodes = {}
                for node in group if group is not None else ():
                    if (node.tag not in {'{' + _NS + '}' + variant + kind for variant in ('odd', 'first', 'even')
                        for kind in ('Header', 'Footer')} or node.tag in nodes or node.attrib or len(node)):
                        raise ValueError('ambiguous native header/footer node')
                    nodes[node.tag] = node.text or ''
                variants = ['odd', *(['first'] if flags.get('differentFirst') else []),
                    *(['even'] if flags.get('differentOddEven') else [])]
                for variant in variants:
                    styled = []
                    for kind in ('header', 'footer'):
                        parts = _section(nodes.get('{' + _NS + '}' + variant + kind.title(), ''))
                        for side in _SIDES.values():
                            part = getattr(getattr(native, variant + kind.title()), side)
                            parsed = parts.get(side, {'font': None, 'size': None, 'color': None, 'text': ''})
                            if parsed != {'font': part.font, 'size': part.size, 'color': part.color, 'text': part.text or ''}:
                                raise ValueError('flattened native section parse mismatch')
                            if prefs['print']['headerFooter']['enabled'] and (
                                part.text or prefs['print']['headerFooter'][kind][side]):
                                styled.append([kind, side])
                    summary['variants'].append({'sheet': native.title, 'part': path,
                        'variant': variant, 'styledPositions': styled})
                summary['sheetNames'].append(native.title)
                summary['worksheetParts'].append(path)
                summary['sheetVariants'].append({'sheet': native.title, 'part': path,
                    'first': flags.get('differentFirst', False), 'even': flags.get('differentOddEven', False)})
                summary['checkedSheets'] += 1
        summary['sourceStatus'], summary['status'] = 'verified', 'passed'
    except Exception:
        summary['issues'].append({'code': 'management_preference_header_footer_native_unverified',
            'message': '无法完整核验打印区域的原生包、唯一节点或全部内联格式；不授予完整字段证据。'})
    check(GUARD, summary['status'] == 'passed', True,
        coverage='complete' if summary['status'] == 'passed' else 'sample',
        evidence_kind=XLSX_HEADER_FOOTER_EVIDENCE, evidence_objects=deepcopy(summary))
    return summary
