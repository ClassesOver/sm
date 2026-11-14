"""完整XLSX打印区域到最多13个native字段V的窄映射。"""

import math
import re
from copy import deepcopy

from ..preferences.approval_contract import _valid_artifact, _valid_binding, approval_contract_hash
from .preference_workbook_header_footer_readback import GUARD, XLSX_HEADER_FOOTER_EVIDENCE

_PREFIX = 'xlsx.print.headerFooter.'
_FIELDS = ('enabled', 'header.left', 'header.center', 'header.right', 'footer.left', 'footer.center',
    'footer.right', 'style.font', 'style.size', 'style.color', 'style.bold', 'headerDistance', 'footerDistance')


def _positions(value):
    if not isinstance(value, list) or any(not isinstance(item, list) or len(item) != 2
        or item[0] not in ('header', 'footer') or item[1] not in ('left', 'center', 'right') for item in value):
        return None
    positions = [tuple(item) for item in value]
    return positions if len(set(positions)) == len(positions) else None


def _complete_group(summary, guards):
    if (not isinstance(summary, dict) or len(guards) != 1 or summary.get('status') != 'passed'
        or summary.get('sourceStatus') != 'verified' or summary.get('issues') != []):
        return False
    guard = guards[0][1]
    if (guard.get('passed') is not True or guard.get('actual') is not True or guard.get('expected') is not True
        or guard.get('coverage') != 'complete' or guard.get('evidenceKind') != XLSX_HEADER_FOOTER_EVIDENCE
        or guard.get('evidenceObjects') != summary):
        return False
    if any(type(summary.get(key)) is not int or summary[key] <= 0
        for key in ('sourceSheets', 'expectedSheets', 'nativeSheets', 'checkedSheets')):
        return False
    count = summary['expectedSheets']
    names, parts = summary.get('sheetNames'), summary.get('worksheetParts')
    if (count != summary['sourceSheets'] + 1 or count != summary['nativeSheets'] or count != summary['checkedSheets']
        or not isinstance(names, list) or not isinstance(parts, list) or len(names) != count or len(parts) != count
        or any(not isinstance(name, str) or not name.strip() for name in names)
        or any(not isinstance(part, str) or not part or part.startswith('/') or '..' in part.split('/') for part in parts)
        or len(set(name.casefold() for name in names)) != count or len(set(parts)) != count):
        return False
    sheets = summary.get('sheetVariants')
    if not isinstance(sheets, list) or len(sheets) != count:
        return False
    identities = set()
    for name, part, sheet in zip(names, parts, sheets, strict=True):
        if (not isinstance(sheet, dict) or sheet.get('sheet') != name or sheet.get('part') != part
            or type(sheet.get('first')) is not bool or type(sheet.get('even')) is not bool):
            return False
        for variant in ('odd', *(['first'] if sheet['first'] else []), *(['even'] if sheet['even'] else [])):
            identities.add((name, part, variant))
    variants = summary.get('variants')
    if not isinstance(variants, list) or len(variants) != len(identities):
        return False
    actual = []
    for item in variants:
        if (not isinstance(item, dict) or _positions(item.get('styledPositions')) is None
            or any(not isinstance(item.get(key), str) for key in ('sheet', 'part', 'variant'))):
            return False
        actual.append((item.get('sheet'), item.get('part'), item.get('variant')))
    return (len(set(actual)) == len(actual) and set(actual) == identities
        and _positions(summary.get('configuredStylePositions')) is not None)


def _locations(summary, field):
    if field in ('headerDistance', 'footerDistance'):
        return [{'sheet': name, 'part': part} for name, part in zip(
            summary['sheetNames'], summary['worksheetParts'], strict=True)]
    result = []
    for variant in summary['variants']:
        location = {key: variant[key] for key in ('sheet', 'part', 'variant')}
        if field == 'enabled':
            result.append(location)
        elif field.startswith('style.'):
            if not summary['configuredStylePositions'] or variant['styledPositions'] != summary['configuredStylePositions']:
                return None
            result.extend({**location, 'kind': kind, 'side': side} for kind, side in variant['styledPositions'])
        else:
            kind, side = field.split('.')
            result.append({**location, 'kind': kind, 'side': side})
    return result


def _value(check, field):
    actual, expected = check.get('actual'), check.get('expected')
    if field == 'enabled' or field == 'style.bold':
        return type(actual) is bool and type(expected) is bool and actual == expected
    if field in ('style.size', 'headerDistance', 'footerDistance'):
        return (type(actual) in (int, float) and type(expected) in (int, float)
            and math.isfinite(actual) and math.isfinite(expected) and actual >= 0 and expected >= 0
            and abs(actual - expected) < .05)
    if field == 'style.color':
        return isinstance(actual, str) and re.fullmatch('[0-9A-F]{6}', actual) is not None and actual == expected
    return isinstance(actual, str) and actual == expected and (bool(actual.strip()) if field == 'style.font' else True)


def map_workbook_header_footer_evidence(result, contract, runtime_binding, retained):
    """组见证、精确对象集合和独立留存身份缺一不可；不升视觉或生命周期。"""
    binding = result.get('binding', {})
    if (binding.get('valid') is not True or binding.get('artifactAccessAuthorized') is not True
        or not _valid_binding(runtime_binding) or runtime_binding['contractHash'] != approval_contract_hash(contract)
        or type(result.get('draftVersion')) is not int or result['draftVersion'] != runtime_binding['draftVersion']
        or result.get('contentHash') != runtime_binding['draftHash']):
        return []
    entry = result.get('formats', {}).get('xlsx', {})
    inline = entry.get('artifact') or {}
    reference = retained.get('formats', {}).get('xlsx', {}).get('artifact') or {}
    artifact = {'sizeBytes': inline.get('size'), 'sha256': inline.get('sha256')}
    if (not _valid_artifact(artifact) or type(reference.get('size')) is not int
        or reference['size'] != artifact['sizeBytes'] or reference.get('sha256') != artifact['sha256']
        or any(issue.get('format') == 'xlsx' and issue.get('role') in (None, 'artifact') for issue in retained.get('issues', []))):
        return []
    read = entry.get('readback', {})
    checks = list(enumerate(read.get('checks', [])))
    guards = [(index, item) for index, item in checks if item.get('path') == 'xlsx.' + GUARD]
    summary = read.get('headerFooterReadback')
    if not _complete_group(summary, guards):
        return []
    registered = {field['path']: field for field in contract.get('fields', [])}
    rows = []
    for requirement in contract['requirements']:
        for field in requirement['checks']:
            path = field.get('path', '')
            local = path.removeprefix(_PREFIX)
            registration = registered.get(path, {})
            if (not path.startswith(_PREFIX) or local not in _FIELDS or field.get('format') != 'xlsx'
                or field.get('role') != 'print' or field.get('scenario') != 'configured_field'
                or 'native' not in field['dimensions'] or registration.get('support') != 'implemented'
                or registration.get('editable') is not True or registration.get('semanticRole') != 'print'
                or requirement['id'] not in registration.get('requirementIds', [])
                or 'native' not in registration.get('evidenceDimensions', [])):
                continue
            current = [(index, item) for index, item in checks if item.get('path') == path]
            locations = _locations(summary, local)
            failed = any(item.get('passed') is False for _, item in current)
            complete = (locations is not None and len(current) == len(locations) > 0
                and all(sum(item.get('evidenceObjects') == location for _, item in current) == 1 for location in locations)
                and all(item.get('passed') is True and item.get('coverage') == 'complete'
                    and item.get('evidenceKind') == XLSX_HEADER_FOOTER_EVIDENCE and _value(item, local)
                    for _, item in current))
            if not failed and not complete:
                continue
            rows.append({'requirementId': requirement['id'], 'format': 'xlsx', 'role': 'print', 'scenario': 'configured_field',
                'path': path, 'dimension': 'native', 'status': 'failed' if failed else 'passed',
                'objectScope': 'complete' if complete else 'partial', 'authorized': True,
                'binding': deepcopy(runtime_binding), 'artifact': deepcopy(artifact),
                'sourceArtifact': {'format': 'xlsx', 'role': 'artifact'}, 'readerGroup': XLSX_HEADER_FOOTER_EVIDENCE,
                'readbackCheckIndexes': sorted({index for index, _ in [*guards, *current]}),
                'message': '全部原生打印区域字段独立回读通过。' if complete else '打印区域字段回读未通过。'})
    return rows
