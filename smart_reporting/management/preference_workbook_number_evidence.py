"""完整数字来源组到最多五个configured_field/native证据的窄映射。"""

import re
from copy import deepcopy

from ..preferences.approval_contract import _valid_artifact, _valid_binding, approval_contract_hash
from .preference_workbook_number_readback import FIELDS, GUARD, XLSX_NUMBER_EVIDENCE

_PREFIX = 'xlsx.numbers.'
_BY_KIND = {'number': ('decimalPlaces', 'thousandsSeparator', 'negativeStyle'),
    'percent': ('percentPlaces', 'negativeStyle'), 'date': ('dateFormat',)}


def _complete_group(summary, guards):
    if (not isinstance(summary, dict) or len(guards) != 1 or summary.get('sourceStatus') != 'verified'
        or summary.get('status') != 'passed' or summary.get('issues') != []):
        return False
    guard = guards[0][1]
    if (guard.get('passed') is not True or guard.get('actual') is not True or guard.get('expected') is not True
        or guard.get('coverage') != 'complete' or guard.get('evidenceKind') != XLSX_NUMBER_EVIDENCE
        or guard.get('evidenceObjects') != summary):
        return False
    count = summary.get('sourceSheets')
    names, parts = summary.get('sheetNames'), summary.get('worksheetParts')
    if (type(count) is not int or count <= 0 or type(summary.get('checkedSheets')) is not int
        or summary['checkedSheets'] != count or not isinstance(names, list) or not isinstance(parts, list)
        or len(names) != count or len(parts) != count
        or any(not isinstance(n, str) or not n.strip() for n in names)
        or any(not isinstance(p, str) or not p.startswith('xl/')
            or any(s in ('', '.', '..') for s in p.split('/')) for p in parts)
        or len(set(n.casefold() for n in names)) != count or len(set(parts)) != count):
        return False
    expected, cells, fields = summary.get('expectedCells'), summary.get('cells'), summary.get('fields')
    if (type(expected) is not int or expected < 0 or type(summary.get('checkedCells')) is not int
        or summary['checkedCells'] != expected or not isinstance(cells, list) or len(cells) != expected
        or not isinstance(fields, dict) or set(fields) != set(FIELDS)):
        return False
    pairs = dict(zip(names, parts, strict=True))
    positions, derived = set(), {field: [] for field in FIELDS}
    for cell in cells:
        if (not isinstance(cell, dict) or cell.get('kind') not in _BY_KIND or type(cell.get('override')) is not bool
            or not isinstance(cell.get('sheet'), str) or cell['sheet'] not in pairs
            or cell.get('part') != pairs[cell['sheet']] or not isinstance(cell.get('cell'), str)
            or re.fullmatch('[A-Z]{1,3}[1-9][0-9]{0,6}', cell['cell']) is None):
            return False
        position = (cell['sheet'], cell['cell'])
        if position in positions:
            return False
        positions.add(position)
        if not cell['override']:
            location = {key: cell[key] for key in ('sheet', 'part', 'cell')}
            for field in _BY_KIND[cell['kind']]:
                derived[field].append(location)
    return fields == derived


def map_workbook_number_evidence(result, contract, runtime_binding, retained):
    """原件独立留存、完整组和精确适用对象缺一不可；无数据保持未验证。"""
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
    summary = read.get('numbersReadback')
    checks = list(enumerate(read.get('checks', [])))
    guards = [(i, c) for i, c in checks if c.get('path') == 'xlsx.' + GUARD]
    if not _complete_group(summary, guards):
        return []
    registered = {field['path']: field for field in contract.get('fields', [])}
    rows = []
    for requirement in contract['requirements']:
        for field in requirement['checks']:
            path = field.get('path', '')
            local = path.removeprefix(_PREFIX)
            registration = registered.get(path, {})
            if (not path.startswith(_PREFIX) or local not in FIELDS or field.get('format') != 'xlsx'
                or field.get('role') != 'numbers' or field.get('scenario') != 'configured_field'
                or 'native' not in field['dimensions'] or registration.get('support') != 'implemented'
                or registration.get('editable') is not True or registration.get('semanticRole') != 'numbers'
                or requirement['id'] not in registration.get('requirementIds', [])
                or 'native' not in registration.get('evidenceDimensions', [])):
                continue
            locations = summary['fields'][local]
            selected = [(i, c) for i, c in checks if c.get('path') == path]
            marked = [(i, c) for i, c in selected if c.get('evidenceKind') == XLSX_NUMBER_EVIDENCE]
            if not locations or not marked:
                continue
            complete = (len(marked) == len(locations)
                and all(sum(c.get('evidenceObjects') == location for _, c in marked) == 1 for location in locations)
                and all(c.get('coverage') == 'complete' and isinstance(c.get('actual'), str)
                    and isinstance(c.get('expected'), str) for _, c in marked))
            failed = any(c.get('passed') is False for _, c in selected)
            if not failed and (not complete or not all(c.get('passed') is True
                and c['actual'] == c['expected'] for _, c in marked)):
                continue
            if any(c.get('passed') is False and (c.get('evidenceKind') != XLSX_NUMBER_EVIDENCE
                or c.get('coverage') != 'complete') for _, c in selected):
                complete = False
            rows.append({'requirementId': requirement['id'], 'format': 'xlsx', 'role': 'numbers',
                'scenario': 'configured_field', 'path': path, 'dimension': 'native',
                'status': 'failed' if failed else 'passed', 'objectScope': 'complete' if complete else 'partial',
                'authorized': True, 'binding': deepcopy(runtime_binding), 'artifact': deepcopy(artifact),
                'sourceArtifact': {'format': 'xlsx', 'role': 'artifact'}, 'readerGroup': XLSX_NUMBER_EVIDENCE,
                'readbackCheckIndexes': sorted({i for i, _ in [*guards, *selected]}),
                'message': '全部适用原生单元格数字格式回读未通过。' if failed else '全部适用原生单元格数字格式回读通过。'})
    return rows
