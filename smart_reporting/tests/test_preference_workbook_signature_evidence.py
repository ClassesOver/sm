"""只有完整说明页见证与独立留存原件才授予三项落款内容native证据。"""

from copy import deepcopy
from hashlib import sha256

import pytest

from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.preferences.approval_contract import approval_contract, approval_contract_hash
from smart_reporting.tests.test_preference_workbook_signature_native import (
    native_signature as native_signature,
)


@pytest.fixture
def material(native_signature):
    content, prefs, frozen = native_signature
    contract = approval_contract()
    binding = {'draftVersion': 7, 'draftHash': 'a' * 64,
        'contractHash': approval_contract_hash(contract), 'executorManifestHash': 'b' * 64}
    identity = {'size': len(content), 'sha256': sha256(content).hexdigest()}
    result = {'draftVersion': 7, 'contentHash': 'a' * 64,
        'binding': {'valid': True, 'artifactAccessAuthorized': True},
        'formats': {'xlsx': {'artifact': deepcopy(identity), 'readback': readback(content, 'xlsx', prefs, frozen)}}}
    retained = {'formats': {'xlsx': {'artifact': deepcopy(identity)}}, 'issues': []}
    return result, contract, binding, retained


def mapped(material):
    from smart_reporting.management.preference_workbook_signature_evidence import (
        map_workbook_signature_evidence,
    )

    return map_workbook_signature_evidence(*material)


def test_maps_only_three_content_fields_with_exact_native_locations(material):
    original = deepcopy(material)
    rows = mapped(material)
    assert {row['path'] for row in rows} == {
        'xlsx.common.signer', 'xlsx.common.dateFormat', 'xlsx.signature.description'}
    assert len(rows) == 3
    assert all(row['status'] == 'passed' and row['objectScope'] == 'complete'
        and row['scenario'] == 'configured_field' and row['dimension'] == 'native'
        and row['readerGroup'] == 'xlsx_native_signature_content_v1'
        and row['role'] == 'terminal_signature' and row['requirementId'] == 'signature-content-and-layout'
        and row['artifact']['sha256'] == material[0]['formats']['xlsx']['artifact']['sha256'] for row in rows)
    assert material == original
    rows[0]['binding']['draftVersion'] = 99
    assert rows[1]['binding']['draftVersion'] == 7


@pytest.mark.parametrize('fault', ['unauthorized', 'invalid_binding', 'wrong_draft', 'wrong_version', 'wrong_contract',
    'retained_hash', 'retained_size', 'retained_issue', 'missing_native', 'missing_group', 'bad_group',
    'wrong_counts', 'missing_guard', 'duplicate_guard', 'missing_marker', 'sample', 'wrong_location',
    'missing_check', 'wrong_value', 'unregistered_field'])
def test_incomplete_or_unbound_checks_do_not_become_passed_evidence(material, fault):
    result, contract, binding, retained = material
    entry = result['formats']['xlsx']
    checks = entry['readback']['checks']
    marked = [item for item in checks if item.get('evidenceKind') == 'xlsx_native_signature_content_v1']
    if fault == 'unauthorized':
        result['binding']['artifactAccessAuthorized'] = False
    elif fault == 'invalid_binding':
        result['binding']['valid'] = False
    elif fault == 'wrong_draft':
        result['contentHash'] = 'c' * 64
    elif fault == 'wrong_version':
        result['draftVersion'] = True
    elif fault == 'wrong_contract':
        binding['contractHash'] = 'c' * 64
    elif fault == 'retained_hash':
        retained['formats']['xlsx']['artifact']['sha256'] = 'c' * 64
    elif fault == 'retained_size':
        retained['formats']['xlsx']['artifact']['size'] += 1
    elif fault == 'retained_issue':
        retained['issues'].append({'format': 'xlsx', 'role': 'artifact', 'code': 'failed'})
    elif fault == 'missing_native':
        entry['artifact'] = None
    elif fault == 'missing_group':
        entry['readback'].pop('signatureReadback')
    elif fault == 'bad_group':
        entry['readback']['signatureReadback']['sourceStatus'] = 'unverified'
    elif fault == 'wrong_counts':
        entry['readback']['signatureReadback']['checkedRows'] -= 1
    elif fault == 'missing_guard':
        checks.remove(marked[0])
    elif fault == 'duplicate_guard':
        checks.append(deepcopy(marked[0]))
    elif fault == 'missing_marker':
        for item in marked:
            item.pop('evidenceKind')
    elif fault == 'sample':
        for item in marked:
            item['coverage'] = 'sample'
    elif fault == 'wrong_location':
        for item in marked[1:]:
            item['evidenceObjects']['cells'] = ['B2']
    elif fault == 'missing_check':
        for item in marked[1:]:
            checks.remove(item)
    elif fault == 'wrong_value':
        for item in marked[1:]:
            item['actual'] = '值不一致但被错误标为通过'
    else:
        for field in contract['fields']:
            if field['path'].startswith('xlsx.'):
                field['editable'] = False
        binding['contractHash'] = approval_contract_hash(contract)
    assert mapped(material) == []


def test_same_path_failure_cannot_be_hidden_by_later_success(material):
    checks = material[0]['formats']['xlsx']['readback']['checks']
    failed = deepcopy(next(item for item in checks if item['path'] == 'xlsx.common.signer'))
    failed.update(passed=False, actual='错误署名')
    checks.insert(0, failed)
    rows = mapped(material)
    assert len(rows) == 3
    assert {row['path'] for row in rows if row['status'] == 'failed'} == {'xlsx.common.signer'}


@pytest.mark.parametrize('fault', ['sample', 'missing_marker'])
def test_same_path_partial_failure_is_retained_without_granting_complete_scope(material, fault):
    checks = material[0]['formats']['xlsx']['readback']['checks']
    failed = deepcopy(next(item for item in checks if item['path'] == 'xlsx.common.signer'))
    failed.update(passed=False, actual='错误署名')
    if fault == 'sample':
        failed['coverage'] = 'sample'
    else:
        failed.pop('evidenceKind')
    checks.insert(0, failed)
    rows = mapped(material)
    assert len(rows) == 3
    row = next(item for item in rows if item['path'] == 'xlsx.common.signer')
    assert row['status'] == 'failed' and row['objectScope'] == 'partial'
