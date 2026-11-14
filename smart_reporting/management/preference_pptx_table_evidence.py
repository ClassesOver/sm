"""仅映射完整原生表格组的十一项可维护字段。"""

from copy import deepcopy

from ..preferences.approval_contract import _valid_artifact, _valid_binding, approval_contract_hash

TABLE_FIELD_EVIDENCE_KIND = 'pptx_native_table_fields_v1'
_FIELDS = {'pptx.' + path for path in ('tables.repeatHeader', 'tables.borders', 'tables.striped',
    'tables.captionNumbering', 'typography.table.font', 'typography.table.size', 'typography.table.color',
    'typography.table.bold', 'typography.table.lineHeight', 'typography.table.spaceBefore', 'typography.table.spaceAfter')}
_GUARDS = {'pptx.tables.' + key for key in ('content', 'visibility', 'structure', 'bounds', 'nativeRuns')}
_OBJECT_COVERAGE = 'pptx.tables.objectCoverage'


def map_pptx_table_evidence(result, contract, runtime_binding, retained):
    """可信组见证、全部保护检查和逐字段检查共同证明；不产视觉/生命周期证据。"""
    binding = result.get('binding', {})
    if (binding.get('valid') is not True or binding.get('artifactAccessAuthorized') is not True
        or not _valid_binding(runtime_binding)
        or runtime_binding['contractHash'] != approval_contract_hash(contract)
        or type(result.get('draftVersion')) is not int or result['draftVersion'] != runtime_binding['draftVersion']
        or result.get('contentHash') != runtime_binding['draftHash']):
        return []
    entry = result.get('formats', {}).get('pptx', {})
    inline = entry.get('artifact') or {}
    reference = retained.get('formats', {}).get('pptx', {}).get('artifact') or {}
    artifact = {'sizeBytes': inline.get('size'), 'sha256': inline.get('sha256')}
    if (not _valid_artifact(artifact) or type(reference.get('size')) is not int
        or reference['size'] != artifact['sizeBytes'] or reference.get('sha256') != artifact['sha256']
        or any(issue.get('format') == 'pptx' and issue.get('role') in (None, 'artifact')
            for issue in retained.get('issues', []))):
        return []
    indexed = list(enumerate(entry.get('readback', {}).get('checks', [])))
    witnesses = [item for _, item in indexed if item.get('path') == _OBJECT_COVERAGE
        and item.get('evidenceKind') == TABLE_FIELD_EVIDENCE_KIND]
    if not witnesses:
        return []
    objects = [witness.get('evidenceObjects', {}) for witness in witnesses]
    if any(any(type(counts.get(key)) is not int for key in ('sourceTables', 'nativeTables', 'checkedNativeTables'))
        or counts['sourceTables'] <= 0 or counts['nativeTables'] <= 0 or counts['checkedNativeTables'] < 0
        for counts in objects):
        return []
    group = [(index, item) for index, item in indexed if item.get('path') in _GUARDS | {_OBJECT_COVERAGE}]
    failed_group = any(item.get('passed') is False for _, item in group) or any(
        counts['checkedNativeTables'] != counts['nativeTables'] for counts in objects)
    complete_group = all(item.get('coverage') == 'complete' and item.get('passed') is True for _, item in group) and all(
        any(item.get('path') == guard and item.get('evidenceKind') == TABLE_FIELD_EVIDENCE_KIND
            for _, item in group) for guard in _GUARDS) and not failed_group
    registered = {field['path']: field for field in contract.get('fields', [])}
    evidence = []
    for requirement in contract['requirements']:
        for field in requirement['checks']:
            path = field.get('path')
            if (path not in _FIELDS or field.get('format') != 'pptx' or field.get('scenario') != 'configured_field'
                or 'native' not in field['dimensions']):
                continue
            registration = registered.get(path, {})
            if (registration.get('support') != 'implemented' or registration.get('editable') is not True
                or registration.get('semanticRole') != field.get('role')
                or requirement['id'] not in registration.get('requirementIds', [])
                or 'native' not in registration.get('evidenceDimensions', [])):
                continue
            checks = [(index, item) for index, item in indexed if item.get('path') == path]
            marked = any(item.get('evidenceKind') == TABLE_FIELD_EVIDENCE_KIND for _, item in checks)
            failed = failed_group or marked and any(item.get('passed') is False for _, item in checks)
            complete = complete_group and marked and all(
                item.get('coverage') == 'complete' and item.get('passed') is True for _, item in checks)
            if not failed and not complete:
                continue
            # 表头会强制黑白/粗体；只有实际表体run才消费用户的颜色与加粗配置。
            if (not failed and path in {'pptx.typography.table.bold', 'pptx.typography.table.color'}
                and not all(type(counts.get('bodyRuns')) is int and counts['bodyRuns'] > 0 for counts in objects)):
                continue
            evidence.append({'requirementId': requirement['id'], 'format': 'pptx', 'role': field['role'],
                'scenario': 'configured_field', 'path': path, 'dimension': 'native',
                'status': 'failed' if failed else 'passed', 'objectScope': 'complete' if complete else 'partial',
                'authorized': True, 'binding': deepcopy(runtime_binding),
                'sourceArtifact': {'format': 'pptx', 'role': 'artifact'}, 'artifact': deepcopy(artifact),
                'readerGroup': TABLE_FIELD_EVIDENCE_KIND,
                'readbackCheckIndexes': sorted({index for index, _ in [*group, *checks]}),
                'message': '原生表格组或字段检查未通过。' if failed else '全部原生表格字段完整回读通过。'})
    return evidence
