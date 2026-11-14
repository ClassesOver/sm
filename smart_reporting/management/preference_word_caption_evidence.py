"""完整受控 Word 表题的窄映射；不推断PDF、视觉或其他表格字段。"""

import re
from copy import deepcopy

from ..preferences.approval_contract import _valid_artifact, _valid_binding, approval_contract_hash
from .preference_document_table_readback import WORD_TABLE_CAPTION_EVIDENCE

_PATH = 'word.tables.captionNumbering'


def map_word_caption_evidence(result, contract, runtime_binding, retained):
    """同一草稿/合同/执行器、完整来源及独立留存身份共同限制证据范围。"""
    binding = result.get('binding', {})
    if (binding.get('valid') is not True or binding.get('artifactAccessAuthorized') is not True
        or not _valid_binding(runtime_binding)
        or runtime_binding['contractHash'] != approval_contract_hash(contract)
        or type(result.get('draftVersion')) is not int or result['draftVersion'] != runtime_binding['draftVersion']
        or result.get('contentHash') != runtime_binding['draftHash']):
        return []
    entry = result.get('formats', {}).get('word', {})
    inline = entry.get('artifact') or {}
    reference = retained.get('formats', {}).get('word', {}).get('artifact') or {}
    artifact = {'sizeBytes': inline.get('size'), 'sha256': inline.get('sha256')}
    if (not _valid_artifact(artifact) or type(reference.get('size')) is not int
        or reference['size'] != artifact['sizeBytes'] or reference.get('sha256') != artifact['sha256']
        or any(issue.get('format') == 'word' and issue.get('role') in (None, 'artifact')
            for issue in retained.get('issues', []))):
        return []
    readback = entry.get('readback', {})
    indexed = [(index, item) for index, item in enumerate(readback.get('checks', [])) if item.get('path') == _PATH]
    marked = [item for _, item in indexed if item.get('evidenceKind') == WORD_TABLE_CAPTION_EVIDENCE]
    summary = readback.get('tableCaptionReadback') or {}
    if len(marked) != 1 or summary.get('sourceStatus') != 'verified' or summary.get('issues') != []:
        return []
    check = marked[0]
    counts = check.get('evidenceObjects') or {}
    if (counts.get('sourceStatus') != 'verified' or any(type(counts.get(key)) is not int
        for key in ('expectedCaptions', 'nativeCaptions', 'checkedCaptions')) or counts['expectedCaptions'] <= 0):
        return []
    count = counts['expectedCaptions']
    failed = any(item.get('passed') is False for _, item in indexed)
    actual, expected = check.get('actual'), check.get('expected')
    complete = (len(indexed) == 1 and check.get('coverage') == 'complete' and check.get('passed') is True
        and counts['nativeCaptions'] == counts['checkedCaptions'] == count
        and summary.get('status') == 'passed' and summary.get('coverage') == 'complete'
        and type(summary.get('expectedCount')) is int and type(summary.get('actualCount')) is int
        and summary['expectedCount'] == summary['actualCount'] == count
        and isinstance(actual, list) and isinstance(expected, list) and actual == expected
        and len(actual) == 2 and type(actual[0]) is int and actual[0] == count
        and isinstance(actual[1], list) and len(actual[1]) == count)
    if complete:
        identities = []
        for caption in actual[1]:
            if (not isinstance(caption, list) or len(caption) != 7 or not isinstance(caption[0], str)
                or re.fullmatch(r'tblcap_[0-9a-f]{24}', caption[0]) is None
                or not isinstance(caption[1], str) or not caption[1].strip()
                or any(value is not True for value in caption[2:])):
                complete = False
                break
            identities.append(caption[0])
        complete = complete and len(set(identities)) == count
    if not failed and not complete:
        return []
    registration = next((field for field in contract.get('fields', []) if field.get('path') == _PATH), {})
    rows = []
    for requirement in contract['requirements']:
        for field in requirement['checks']:
            if (field.get('path') != _PATH or field.get('format') != 'word' or field.get('role') != 'tables'
                or field.get('scenario') != 'configured_field' or 'native' not in field['dimensions']
                or registration.get('support') != 'implemented' or registration.get('editable') is not True
                or registration.get('semanticRole') != field['role']
                or requirement['id'] not in registration.get('requirementIds', [])
                or 'native' not in registration.get('evidenceDimensions', [])):
                continue
            rows.append({'requirementId': requirement['id'], 'format': 'word', 'role': 'tables',
                'scenario': 'configured_field', 'path': _PATH, 'dimension': 'native',
                'status': 'failed' if failed else 'passed', 'objectScope': 'complete' if complete else 'partial',
                'authorized': True, 'binding': deepcopy(runtime_binding), 'artifact': artifact,
                'sourceArtifact': {'format': 'word', 'role': 'artifact'},
                'readerGroup': WORD_TABLE_CAPTION_EVIDENCE,
                'readbackCheckIndexes': [index for index, _ in indexed],
                'message': '全部受控原生表题逐一核验通过。' if complete else '受控原生表题回读未通过。'})
    return rows
