"""缩进原生证据只认完整逐段回读及相同留存身份，不提升成视觉验收。"""

from copy import deepcopy
from hashlib import sha256

import pytest

from smart_reporting.preferences.approval_contract import approval_contract, approval_contract_hash
from smart_reporting.tests.test_preference_pptx_indent_capabilities import INDENTS

MARKER = 'pptx_native_indent_fields_v1'


def material():
    contract = approval_contract()
    # mapper自身的字段合同夹具；实际能力登记另以真实消费者专项验证。
    for field in contract['fields']:
        if field['path'] in {'pptx.' + local for local in INDENTS}:
            field.update(support='implemented', editable=True)
    binding = {'draftVersion': 7, 'draftHash': 'a' * 64,
        'contractHash': approval_contract_hash(contract), 'executorManifestHash': 'b' * 64}
    checks = [{'path': 'pptx.' + local, 'passed': True, 'coverage': 'complete',
        'evidenceKind': MARKER, 'actual': [228600, 228600], 'expected': [228600, 228600],
        'evidenceObjects': {'nativeObjects': 2, 'checkedNativeObjects': 2, 'paragraphs': 2}}
        for local in INDENTS]
    artifact = {'size': 4, 'sha256': sha256(b'test').hexdigest()}
    result = {'draftVersion': 7, 'contentHash': 'a' * 64,
        'binding': {'valid': True, 'artifactAccessAuthorized': True},
        'formats': {'pptx': {'artifact': artifact, 'readback': {'checks': checks}}}}
    retained = {'formats': {'pptx': {'artifact': deepcopy(artifact)}}, 'issues': []}
    return result, contract, binding, retained


def mapped(values):
    from smart_reporting.management.preference_native_evidence import (
        map_native_pptx_indent_evidence,
    )

    return map_native_pptx_indent_evidence(*values)


def test_six_complete_fields_use_contract_roles_and_exact_native_artifact():
    values = material()
    rows = mapped(values)
    assert len(rows) == 6 and all(row['status'] == 'passed' for row in rows)
    assert {row['path'] for row in rows} == {'pptx.' + path for path in INDENTS}
    for row in rows:
        assert row['dimension'] == 'native' and row['objectScope'] == 'complete'
        assert row['binding'] == values[2] and row['readerGroup'] == MARKER
        assert row['readbackCheckIndexes']
        assert row['sourceArtifact'] == {'format': 'pptx', 'role': 'artifact'}
        assert row['role'] == ('terminal_signature' if row['path'] == 'pptx.signature.indent'
            else row['path'].split('.')[2] if '.typography.' in row['path'] else 'footerStyle')


@pytest.mark.parametrize('fault', ['sample', 'unmarked', 'empty', 'missing_counts', 'unchecked', 'wrong_length',
    'bool_emu', 'float_emu', 'lying_pass', 'late_failure', 'late_sample'])
def test_partial_forged_or_late_object_cannot_qualify_pass(fault):
    values = material()
    checks = values[0]['formats']['pptx']['readback']['checks']
    field = checks[0]
    path = field['path']
    if fault == 'sample':
        field['coverage'] = 'sample'
    elif fault == 'unmarked':
        field.pop('evidenceKind')
    elif fault == 'empty':
        field.update(actual=[], expected=[])
        field['evidenceObjects'].update(nativeObjects=0, checkedNativeObjects=0, paragraphs=0)
    elif fault == 'missing_counts':
        field.pop('evidenceObjects')
    elif fault == 'unchecked':
        field['evidenceObjects']['checkedNativeObjects'] = 1
    elif fault == 'wrong_length':
        field['actual'] = [228600]
    elif fault in {'bool_emu', 'float_emu', 'lying_pass'}:
        field['actual'][-1] = {'bool_emu': True, 'float_emu': 228600.0, 'lying_pass': 0}[fault]
    else:
        late = deepcopy(field)
        late.update(passed=False, actual=[228600, 0])
        if fault == 'late_sample':
            late['coverage'] = 'sample'
        checks.append(late)
    assert not any(row['path'] == path and row['status'] == 'passed' for row in mapped(values))
    assert len([row for row in mapped(values) if row['status'] == 'passed']) == 5


@pytest.mark.parametrize('fault', ['binding', 'draft', 'contract', 'retained_hash', 'retained_issue'])
def test_identity_or_binding_drift_produces_no_evidence(fault):
    values = material()
    if fault == 'binding':
        values[0]['binding']['artifactAccessAuthorized'] = False
    elif fault == 'draft':
        values[0]['contentHash'] = 'f' * 64
    elif fault == 'contract':
        values[2]['contractHash'] = 'f' * 64
    elif fault == 'retained_hash':
        values[3]['formats']['pptx']['artifact']['sha256'] = 'f' * 64
    else:
        values[3]['issues'].append({'format': 'pptx', 'role': 'artifact'})
    assert mapped(values) == []
