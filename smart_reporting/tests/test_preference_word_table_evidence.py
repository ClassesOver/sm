"""只有来源、全部对象及独立 Word 身份完整时授予表格字段原生证据。"""

from copy import deepcopy
from hashlib import sha256
from io import BytesIO

import pytest

from smart_reporting.preferences.approval_contract import (
    approval_contract,
    approval_contract_hash,
    evaluate_required_coverage,
)
from smart_reporting.tests.test_preference_word_table_readback import (
    FIELDS,
    native_case,
    read,
)


def material(tmp_path):
    document, prefs, frozen = native_case(tmp_path)
    checks, summary = read(document, prefs, frozen)
    for check in checks:
        check['path'] = 'word.' + check['path']
        check['evidenceKind'] = check.pop('evidence_kind')
        check['evidenceObjects'] = check.pop('evidence_objects')
    stream = BytesIO()
    document.save(stream)
    content = stream.getvalue()
    artifact = {'size': len(content), 'sha256': sha256(content).hexdigest()}
    contract = approval_contract()
    binding = {'draftVersion': 7, 'draftHash': 'a' * 64, 'contractHash': approval_contract_hash(contract),
        'executorManifestHash': 'b' * 64}
    result = {'draftVersion': 7, 'contentHash': 'a' * 64,
        'binding': {'valid': True, 'artifactAccessAuthorized': True},
        'formats': {'word': {'artifact': artifact,
            'readback': {'status': 'failed', 'checks': checks, 'tableReadback': summary}}}}
    return result, contract, binding, {'formats': {'word': {'artifact': deepcopy(artifact)}}, 'issues': []}


def mapped(inputs):
    from smart_reporting.management.preference_word_table_evidence import map_word_table_evidence

    return map_word_table_evidence(*inputs)


def test_maps_all_twelve_complete_fields_without_visual_or_lifecycle_approval(tmp_path):
    inputs = material(tmp_path)
    before = deepcopy(inputs)
    rows = mapped(inputs)
    assert inputs == before
    assert len(rows) == 12 and {item['path'] for item in rows} == {'word.' + path for path in FIELDS}
    assert all(item['format'] == 'word' and item['role'] == (
        'table' if '.typography.table.' in item['path'] else 'tables') and item['scenario'] == 'configured_field'
        and item['dimension'] == 'native' and item['status'] == 'passed' and item['objectScope'] == 'complete'
        and item['authorized'] is True and item['binding'] == inputs[2] for item in rows)
    gaps = evaluate_required_coverage({**inputs[1], 'expectedBinding': inputs[2]}, rows)
    assert gaps and any('visual' in gap['missingDimensions'] for gap in gaps)
    assert not any(gap.get('path') in {item['path'] for item in rows}
        and gap.get('scenario') == 'configured_field' for gap in gaps)


@pytest.mark.parametrize('fault', ['missing_kind', 'sample', 'missing_guard', 'duplicate_guard',
    'unverified_source', 'zero_count', 'boolean_count', 'partial_count', 'false_summary',
    'field_count', 'count_disagreement', 'empty_grid', 'missing_expected'])
def test_incomplete_group_cannot_be_promoted(tmp_path, fault):
    inputs = material(tmp_path)
    readback = inputs[0]['formats']['word']['readback']
    checks = readback['checks']
    if fault in ('missing_kind', 'sample'):
        for item in checks:
            if fault == 'missing_kind':
                item.pop('evidenceKind')
            else:
                item['coverage'] = 'sample'
    elif fault == 'missing_guard':
        checks.pop(0)
    elif fault == 'duplicate_guard':
        checks.append(deepcopy(checks[0]))
    elif fault in ('unverified_source', 'zero_count', 'boolean_count', 'partial_count'):
        key, value = {'unverified_source': ('sourceStatus', 'unverified'), 'zero_count': ('sourceTables', 0),
            'boolean_count': ('runs', True), 'partial_count': ('checkedNativeCells', 1)}[fault]
        for item in checks:
            item['evidenceObjects'][key] = value
        readback['tableReadback'][key] = value
    elif fault == 'false_summary':
        readback['tableReadback']['status'] = 'unverified'
    elif fault == 'field_count':
        check = next(item for item in checks if item['path'] == 'word.typography.table.size')
        check['actual'].pop()
        check['expected'].pop()
    elif fault == 'count_disagreement':
        checks[-1]['evidenceObjects']['runs'] += 1
    elif fault == 'empty_grid':
        checks[0]['actual'] = checks[0]['expected'] = [True, []]
    else:
        checks[0].pop('expected')
    rows = mapped(inputs)
    if fault in ('field_count', 'count_disagreement'):
        path = 'word.typography.table.' + ('size' if fault == 'field_count' else 'indent')
        assert not any(item['status'] == 'passed' and item['path'] == path for item in rows)
        assert len([item for item in rows if item['status'] == 'passed']) == 11
    else:
        assert not any(item['status'] == 'passed' for item in rows)


@pytest.mark.parametrize('fault', ['unauthorized', 'invalid_binding', 'draft', 'contract',
    'retained_hash', 'retained_size', 'retention_issue', 'preview_only', 'pdf'])
def test_mapping_requires_current_authority_and_same_retained_word(tmp_path, fault):
    inputs = material(tmp_path)
    result, _, binding, retained = inputs
    if fault == 'unauthorized':
        result['binding']['artifactAccessAuthorized'] = False
    elif fault == 'invalid_binding':
        result['binding']['valid'] = False
    elif fault == 'draft':
        result['contentHash'] = 'd' * 64
    elif fault == 'contract':
        binding['contractHash'] = 'd' * 64
    elif fault == 'retained_hash':
        retained['formats']['word']['artifact']['sha256'] = 'd' * 64
    elif fault == 'retained_size':
        retained['formats']['word']['artifact']['size'] += 1
    elif fault == 'retention_issue':
        retained['issues'] = [{'format': 'word', 'role': 'artifact'}]
    elif fault == 'preview_only':
        retained['formats']['word']['pdf'] = retained['formats']['word'].pop('artifact')
    else:
        result['formats']['pdf'] = result['formats'].pop('word')
    assert mapped(inputs) == []


@pytest.mark.parametrize('guard_failure', [False, True])
def test_late_or_duplicate_failure_cannot_be_overwritten_by_passing_checks(tmp_path, guard_failure):
    inputs = material(tmp_path)
    checks = inputs[0]['formats']['word']['readback']['checks']
    item = deepcopy(checks[0] if guard_failure else next(
        item for item in checks if item['path'] == 'word.typography.table.size'))
    item['passed'] = False
    item['actual'] = None
    checks.append(item)
    rows = mapped(inputs)
    assert len(rows) == 12
    failed = [row for row in rows if row['status'] == 'failed']
    assert len(failed) == (12 if guard_failure else 1)
    assert all(row['objectScope'] == 'partial' for row in failed)
