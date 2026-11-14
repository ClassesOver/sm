"""唯一末尾说明页到三项落款内容native证据的窄映射。"""

from copy import deepcopy

from ..preferences.approval_contract import _valid_artifact, _valid_binding, approval_contract_hash
from .preference_workbook_signature_readback import FIELDS, GUARD, XLSX_SIGNATURE_EVIDENCE


def _complete_group(summary, checks):
    guards = [(index, item) for index, item in checks if item.get('path') == 'xlsx.' + GUARD]
    if (not isinstance(summary, dict) or len(guards) != 1 or summary.get('sourceStatus') != 'verified'
        or summary.get('status') != 'passed' or summary.get('issues') != []):
        return None
    count = summary.get('expectedRows')
    if (type(count) is not int or count < 3 or any(type(summary.get(key)) is not int
        or summary[key] != count for key in ('nativeRows', 'checkedRows'))
        or summary.get('cells') != ['A' + str(index) for index in range(1, count + 1)]
        or not isinstance(summary.get('sheet'), str) or not summary['sheet'].strip()
        or not isinstance(summary.get('part'), str) or not summary['part'].startswith('xl/')
        or any(part in ('', '.', '..') for part in summary['part'].split('/'))):
        return None
    index, guard = guards[0]
    if (guard.get('passed') is not True or guard.get('actual') is not True or guard.get('expected') is not True
        or guard.get('coverage') != 'complete' or guard.get('evidenceKind') != XLSX_SIGNATURE_EVIDENCE
        or guard.get('evidenceObjects') != summary):
        return None
    return index


def map_workbook_signature_evidence(result, contract, runtime_binding, retained):
    """精确绑定草稿与独立留存原件；旧采样、总体passed或预览均不能替代原生组。"""
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
    readback = entry.get('readback', {})
    summary = readback.get('signatureReadback')
    checks = list(enumerate(readback.get('checks', [])))
    guard = _complete_group(summary, checks)
    if guard is None:
        return []
    registered = {field['path']: field for field in contract.get('fields', [])}
    rows = []
    for requirement in contract['requirements']:
        if requirement['id'] != 'signature-content-and-layout':
            continue
        for field in requirement['checks']:
            path = field.get('path')
            registration = registered.get(path, {})
            if (path not in {'xlsx.' + local for local in FIELDS} or field.get('format') != 'xlsx'
                or field.get('scenario') != 'configured_field' or field.get('role') != 'terminal_signature'
                or 'native' not in field['dimensions'] or registration.get('support') != 'implemented'
                or registration.get('editable') is not True or registration.get('semanticRole') != field['role']
                or requirement['id'] not in registration.get('requirementIds', [])
                or 'native' not in registration.get('evidenceDimensions', [])):
                continue
            selected = [(index, item) for index, item in checks if item.get('path') == path]
            if not selected:
                continue
            if not any(item.get('evidenceKind') == XLSX_SIGNATURE_EVIDENCE for _, item in selected):
                continue
            cells = (['A2'] if path == 'xlsx.common.signer' else ['A3'] if path == 'xlsx.common.dateFormat'
                else summary['cells'][3:])
            location = {'sheet': summary['sheet'], 'part': summary['part'], 'cells': cells}
            complete = all(item.get('evidenceKind') == XLSX_SIGNATURE_EVIDENCE
                and item.get('coverage') == 'complete' and item.get('evidenceObjects') == location
                and isinstance(item.get('actual'), str) and isinstance(item.get('expected'), str)
                for _, item in selected)
            failed = any(item.get('passed') is False for _, item in selected)
            if not failed and (not complete or not all(item.get('passed') is True
                and item['actual'] == item['expected'] for _, item in selected)):
                continue
            rows.append({'requirementId': requirement['id'], 'format': 'xlsx', 'role': field['role'],
                'scenario': 'configured_field', 'path': path, 'dimension': 'native',
                'status': 'failed' if failed else 'passed', 'objectScope': 'complete' if complete else 'partial', 'authorized': True,
                'binding': deepcopy(runtime_binding), 'artifact': deepcopy(artifact),
                'sourceArtifact': {'format': 'xlsx', 'role': 'artifact'}, 'readerGroup': XLSX_SIGNATURE_EVIDENCE,
                'readbackCheckIndexes': [guard, *[index for index, _ in selected]],
                'message': '说明页落款完整原生文本回读未通过。' if failed else '说明页落款完整原生文本回读通过。'})
    return rows
