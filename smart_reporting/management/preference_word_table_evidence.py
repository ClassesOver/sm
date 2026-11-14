"""完整 Word 表格组的窄证据映射；不授予视觉、生命周期或总体批准。"""

import math
import re
from copy import deepcopy

from ..preferences.approval_contract import _valid_artifact, _valid_binding, approval_contract_hash
from .preference_word_table_readback import TABLE_FIELDS, TEXT_FIELDS, WORD_TABLE_FIELD_EVIDENCE

_FIELDS = {'word.tables.' + key for key in TABLE_FIELDS} | {'word.typography.table.' + key for key in TEXT_FIELDS}
_GUARD = 'word.tables.nativeStructure'
_COUNTS = ('sourceTables', 'sourceCells', 'expectedTables', 'nativeTables', 'checkedTables',
    'expectedCells', 'nativeCells', 'checkedNativeCells', 'rows', 'paragraphs', 'runs')


def _complete_group(guard, summary):
    counts = guard.get('evidenceObjects') or {}
    if (counts.get('sourceStatus') != 'verified' or summary.get('sourceStatus') != 'verified'
        or summary.get('status') not in ('passed', 'failed') or summary.get('issues') != []
        or any(type(counts.get(key)) is not int or counts[key] <= 0 or summary.get(key) != counts[key]
            or type(summary.get(key)) is not int for key in _COUNTS)
        or counts['expectedTables'] != counts['nativeTables'] or counts['checkedTables'] != counts['nativeTables']
        or counts['expectedCells'] != counts['nativeCells'] or counts['checkedNativeCells'] != counts['nativeCells']
        or counts['paragraphs'] < counts['nativeCells'] or counts['runs'] < counts['paragraphs']):
        return False
    actual = guard.get('actual')
    if (guard.get('passed') is not True or guard.get('coverage') != 'complete'
        or not isinstance(actual, list) or actual != guard.get('expected') or len(actual) != 2
        or actual[0] is not True or not isinstance(actual[1], list) or len(actual[1]) != counts['nativeTables']):
        return False
    cells, rows = 0, 0
    for grid in actual[1]:
        if not isinstance(grid, list) or not grid or not isinstance(grid[0], list) or not grid[0]:
            return False
        for row in grid:
            if not isinstance(row, list) or len(row) != len(grid[0]) or any(not isinstance(cell, str) for cell in row):
                return False
            cells += len(row)
            rows += 1
    return cells == counts['nativeCells'] and rows == counts['rows']


def _complete_field(check, counts, path):
    actual = check.get('actual')
    key = path.rsplit('.', 1)[-1]
    count = counts['nativeTables'] if key == 'borders' else counts['nativeCells'] if key == 'striped' else (
        counts['rows'] if key in ('repeatHeader', 'splitRows') else counts['runs'] if key in ('font', 'size', 'color', 'bold')
        else counts['paragraphs'])
    if (check.get('passed') is not True or check.get('coverage') != 'complete'
        or check.get('evidenceObjects') != counts or check.get('evidenceKind') != WORD_TABLE_FIELD_EVIDENCE
        or not isinstance(actual, list) or len(actual) != count or actual != check.get('expected')):
        return False
    if key in ('repeatHeader', 'splitRows', 'bold'):
        return all(type(value) is bool for value in actual)
    if key == 'font':
        return all(isinstance(value, list) and len(value) == 4 and all(
            isinstance(font, str) and font.strip() for font in value) for value in actual)
    if key == 'color':
        return all(isinstance(value, str) and re.fullmatch(r'#[0-9A-F]{6}', value) for value in actual)
    if key == 'borders':
        return all(isinstance(value, list) and len(value) == 6 and all(isinstance(edge, list) and len(edge) == 3
            and edge[0] in ('nil', 'single') and edge[1] == '4' and edge[2] == 'C7D7E5' for edge in value) for value in actual)
    if key == 'striped':
        return all(isinstance(value, list) and len(value) == 2 and value[0] in (None, 'EDF5FC', 'F9FAFB')
            and value[1] == 'clear' for value in actual)
    return all(type(value) in (float, int) and math.isfinite(value) for value in actual)


def map_word_table_evidence(result, contract, runtime_binding, retained):
    """来源、原生组、逐字段和留存身份均一致才映射；任何同路径失败均保留。"""
    binding = result.get('binding', {})
    if (binding.get('valid') is not True or binding.get('artifactAccessAuthorized') is not True
        or not _valid_binding(runtime_binding) or runtime_binding['contractHash'] != approval_contract_hash(contract)
        or type(result.get('draftVersion')) is not int or result['draftVersion'] != runtime_binding['draftVersion']
        or result.get('contentHash') != runtime_binding['draftHash']):
        return []
    entry = result.get('formats', {}).get('word', {})
    inline = entry.get('artifact') or {}
    reference = retained.get('formats', {}).get('word', {}).get('artifact') or {}
    artifact = {'sizeBytes': inline.get('size'), 'sha256': inline.get('sha256')}
    if (not _valid_artifact(artifact) or type(reference.get('size')) is not int
        or reference['size'] != artifact['sizeBytes'] or reference.get('sha256') != artifact['sha256']
        or any(issue.get('format') == 'word' and issue.get('role') in (None, 'artifact') for issue in retained.get('issues', []))):
        return []
    readback = entry.get('readback', {})
    indexed = list(enumerate(readback.get('checks', [])))
    guards = [(index, item) for index, item in indexed if item.get('path') == _GUARD]
    marked = [item for _, item in guards if item.get('evidenceKind') == WORD_TABLE_FIELD_EVIDENCE]
    if not marked:
        return []
    counts = marked[0].get('evidenceObjects') or {}
    if (counts.get('sourceStatus') != 'verified' or any(type(counts.get(key)) is not int or counts[key] <= 0
        for key in ('sourceTables', 'sourceCells'))):
        return []
    failed_group = any(item.get('passed') is False for _, item in guards)
    complete_group = len(guards) == len(marked) == 1 and _complete_group(marked[0], readback.get('tableReadback') or {})
    registered = {field['path']: field for field in contract.get('fields', [])}
    rows = []
    for requirement in contract['requirements']:
        for field in requirement['checks']:
            path = field.get('path')
            registration = registered.get(path, {})
            role = 'table' if path in _FIELDS and '.typography.' in path else 'tables'
            if (path not in _FIELDS or field.get('format') != 'word' or field.get('role') != role
                or field.get('scenario') != 'configured_field' or 'native' not in field['dimensions']
                or registration.get('support') != 'implemented' or registration.get('editable') is not True
                or registration.get('semanticRole') != role or requirement['id'] not in registration.get('requirementIds', [])
                or 'native' not in registration.get('evidenceDimensions', [])):
                continue
            checks = [(index, item) for index, item in indexed if item.get('path') == path]
            marked_checks = [item for _, item in checks if item.get('evidenceKind') == WORD_TABLE_FIELD_EVIDENCE]
            failed = failed_group or bool(marked_checks) and any(item.get('passed') is False for _, item in checks)
            complete = (complete_group and len(checks) == len(marked_checks) == 1
                and _complete_field(marked_checks[0], counts, path))
            if not failed and not complete:
                continue
            rows.append({'requirementId': requirement['id'], 'format': 'word', 'role': role, 'scenario': 'configured_field',
                'path': path, 'dimension': 'native', 'status': 'failed' if failed else 'passed',
                'objectScope': 'complete' if complete and not failed else 'partial', 'authorized': True,
                'binding': deepcopy(runtime_binding), 'artifact': deepcopy(artifact),
                'sourceArtifact': {'format': 'word', 'role': 'artifact'}, 'readerGroup': WORD_TABLE_FIELD_EVIDENCE,
                'readbackCheckIndexes': sorted({index for index, _ in [*guards, *checks]}),
                'message': '全部原生表格字段逐对象回读通过。' if complete and not failed else '原生表格组或字段回读未通过。'})
    return rows
