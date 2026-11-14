"""数字原生组的授权、对象完整性和留存身份边界。"""

from copy import deepcopy
from hashlib import sha256

import pytest

from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.preferences.approval_contract import approval_contract, approval_contract_hash
from smart_reporting.tests.test_preference_workbook_number_native import (
    MARKER,
)
from smart_reporting.tests.test_preference_workbook_number_native import (
    native_numbers as native_numbers,
)
from smart_reporting.tests.test_preference_workbook_number_readback import _mutate


@pytest.fixture
def material(native_numbers):
    content, prefs, frozen = native_numbers
    contract = approval_contract()
    binding = {'draftVersion': 7, 'draftHash': 'a' * 64,
        'contractHash': approval_contract_hash(contract), 'executorManifestHash': 'b' * 64}
    identity = {'size': len(content), 'sha256': sha256(content).hexdigest()}
    result = {'draftVersion': 7, 'contentHash': 'a' * 64,
        'binding': {'valid': True, 'artifactAccessAuthorized': True},
        'formats': {'xlsx': {'artifact': deepcopy(identity), 'readback': readback(content, 'xlsx', prefs, frozen)}}}
    return result, contract, binding, {'formats': {'xlsx': {'artifact': deepcopy(identity)}}, 'issues': []}


def mapped(material):
    from smart_reporting.management.preference_workbook_number_evidence import (
        map_workbook_number_evidence,
    )

    return map_workbook_number_evidence(*material)


def test_maps_exactly_five_native_number_fields_without_mutating_inputs(material):
    before = deepcopy(material)
    rows = mapped(material)
    assert len(rows) == 5
    assert {r['path'] for r in rows} == {'xlsx.numbers.' + f for f in (
        'decimalPlaces', 'thousandsSeparator', 'negativeStyle', 'percentPlaces', 'dateFormat')}
    assert all(r['role'] == 'numbers' and r['scenario'] == 'configured_field' and r['dimension'] == 'native'
        and r['status'] == 'passed' and r['objectScope'] == 'complete' and r['readerGroup'] == MARKER
        and r['requirementId'] == 'workbook-display-invariants' for r in rows)
    assert material == before
    rows[0]['binding']['draftVersion'] = 99
    assert rows[1]['binding']['draftVersion'] == 7


@pytest.mark.parametrize('fault', ['unauthorized', 'binding', 'draft', 'version', 'contract', 'retained_hash',
    'retained_size', 'retained_issue', 'missing_artifact', 'missing_group', 'bad_group', 'count',
    'missing_guard', 'duplicate_guard', 'missing_marker', 'sample', 'location', 'missing_check',
    'duplicate_check', 'wrong_value', 'wrong_field_set', 'duplicate_cell', 'wrong_kind', 'unregistered'])
def test_incomplete_or_unbound_number_checks_never_become_passed_evidence(material, fault):
    result, contract, binding, retained = material
    entry = result['formats']['xlsx']
    read = entry['readback']
    checks = read['checks']
    marked = [c for c in checks if c.get('evidenceKind') == MARKER]
    summary = read['numbersReadback']
    if fault == 'unauthorized':
        result['binding']['artifactAccessAuthorized'] = False
    elif fault == 'binding':
        result['binding']['valid'] = False
    elif fault == 'draft':
        result['contentHash'] = 'c' * 64
    elif fault == 'version':
        result['draftVersion'] = True
    elif fault == 'contract':
        binding['contractHash'] = 'c' * 64
    elif fault == 'retained_hash':
        retained['formats']['xlsx']['artifact']['sha256'] = 'c' * 64
    elif fault == 'retained_size':
        retained['formats']['xlsx']['artifact']['size'] += 1
    elif fault == 'retained_issue':
        retained['issues'].append({'format': 'xlsx', 'role': 'artifact', 'code': 'failed'})
    elif fault == 'missing_artifact':
        entry['artifact'] = None
    elif fault == 'missing_group':
        read.pop('numbersReadback')
    elif fault == 'bad_group':
        summary['sourceStatus'] = 'unverified'
    elif fault == 'count':
        summary['checkedCells'] -= 1
    elif fault == 'missing_guard':
        checks.remove(marked[0])
    elif fault == 'duplicate_guard':
        checks.append(deepcopy(marked[0]))
    elif fault in ('missing_marker', 'sample', 'location', 'wrong_value'):
        for item in marked[1:]:
            if fault == 'missing_marker':
                item.pop('evidenceKind')
            elif fault == 'sample':
                item['coverage'] = 'sample'
            elif fault == 'location':
                item['evidenceObjects']['cell'] = 'Z99'
            else:
                item['actual'] = '错误格式仍声称passed'
    elif fault == 'missing_check':
        for item in marked[1:]:
            checks.remove(item)
    elif fault == 'duplicate_check':
        for item in marked[1:]:
            checks.append(deepcopy(item))
    elif fault == 'wrong_field_set':
        summary['fields']['decimalPlaces'] = []
    elif fault == 'duplicate_cell':
        summary['cells'].append(deepcopy(summary['cells'][0]))
    elif fault == 'wrong_kind':
        summary['cells'][0]['kind'] = 'text'
    else:
        for field in contract['fields']:
            if field['path'].startswith('xlsx.numbers.'):
                field['editable'] = False
        binding['contractHash'] = approval_contract_hash(contract)
    assert mapped(material) == []


def test_actual_format_failure_maps_only_affected_fields_as_failed(material, native_numbers):
    content, prefs, frozen = native_numbers
    changed = _mutate(content, 'B2', number_format=True)
    identity = {'size': len(changed), 'sha256': sha256(changed).hexdigest()}
    material[0]['formats']['xlsx'].update(artifact=identity, readback=readback(changed, 'xlsx', prefs, frozen))
    material[3]['formats']['xlsx']['artifact'] = deepcopy(identity)
    rows = mapped(material)
    assert len(rows) == 5
    assert {r['path'] for r in rows if r['status'] == 'failed'} == {
        'xlsx.numbers.decimalPlaces', 'xlsx.numbers.thousandsSeparator', 'xlsx.numbers.negativeStyle'}


@pytest.mark.parametrize('fault', ['sample', 'unmarked'])
def test_legacy_failure_cannot_be_hidden_by_native_group_success(material, fault):
    checks = material[0]['formats']['xlsx']['readback']['checks']
    failed = deepcopy(next(c for c in checks if c['path'] == 'xlsx.numbers.dateFormat'))
    failed.update(passed=False, actual='错误日期格式')
    if fault == 'sample':
        failed['coverage'] = 'sample'
    else:
        failed.pop('evidenceKind', None)
    checks.append(failed)
    row = next(r for r in mapped(material) if r['path'] == 'xlsx.numbers.dateFormat')
    assert row['status'] == 'failed' and row['objectScope'] == 'partial'
