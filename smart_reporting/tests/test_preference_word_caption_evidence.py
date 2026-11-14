"""仅完整受控 Word 表题产生原生字段证据，拒绝来源或产物身份缺口。"""

from copy import deepcopy
from hashlib import sha256

import pytest

from smart_reporting.preferences.approval_contract import (
    approval_contract,
    approval_contract_hash,
    evaluate_required_coverage,
)

PATH = 'word.tables.captionNumbering'
KIND = 'word_native_table_captions_v1'


def material():
    contract = approval_contract()
    binding = {'draftVersion': 7, 'draftHash': 'a' * 64,
        'contractHash': approval_contract_hash(contract), 'executorManifestHash': 'b' * 64}
    captions = [['tblcap_' + sha256(key.encode()).hexdigest()[:24], title, True, True, True, True, True]
        for key, title in [('first', '表 1：同名表题'), ('last', '表 2：同名表题')]]
    check = {'path': PATH, 'passed': True, 'coverage': 'complete', 'evidenceKind': KIND,
        'actual': [2, captions], 'expected': [2, deepcopy(captions)],
        'evidenceObjects': {'sourceStatus': 'verified', 'expectedCaptions': 2, 'nativeCaptions': 2, 'checkedCaptions': 2}}
    artifact = {'size': 4, 'sha256': sha256(b'test').hexdigest()}
    result = {'draftVersion': 7, 'contentHash': 'a' * 64,
        'binding': {'valid': True, 'artifactAccessAuthorized': True},
        'formats': {'word': {'artifact': artifact,
            'readback': {'status': 'failed', 'checks': [check], 'tableCaptionReadback': {
                'status': 'passed', 'sourceStatus': 'verified', 'coverage': 'complete',
                'expectedCount': 2, 'actualCount': 2, 'issues': []}}}}}
    retained = {'formats': {'word': {'artifact': deepcopy(artifact)}}, 'issues': []}
    return result, contract, binding, retained


def mapped(inputs):
    from smart_reporting.management.preference_word_caption_evidence import (
        map_word_caption_evidence,
    )

    return map_word_caption_evidence(*inputs)


def test_maps_only_complete_word_caption_native_field_without_global_approval():
    inputs = material()
    before = deepcopy(inputs)
    rows = mapped(inputs)
    assert inputs == before
    assert len(rows) == 1
    row = rows[0]
    assert row['path'] == PATH and row['format'] == 'word' and row['role'] == 'tables'
    assert row['requirementId'] == 'native-editable-role-style'
    assert row['scenario'] == 'configured_field' and row['dimension'] == 'native'
    assert row['status'] == 'passed' and row['objectScope'] == 'complete' and row['authorized'] is True
    assert row['binding'] == inputs[2]
    assert row['sourceArtifact'] == {'format': 'word', 'role': 'artifact'}
    assert row['artifact'] == {'sizeBytes': 4, 'sha256': sha256(b'test').hexdigest()}
    gaps = evaluate_required_coverage({**inputs[1], 'expectedBinding': inputs[2]}, rows)
    assert gaps and any('visual' in gap['missingDimensions'] for gap in gaps)
    assert not any(gap.get('path') == PATH and gap.get('scenario') == 'configured_field' for gap in gaps)


@pytest.mark.parametrize('fault', [
    'missing_kind', 'wrong_kind', 'sample', 'missing_coverage', 'missing_passed', 'capability_only',
    'unverified_source', 'summary_source', 'source_issues', 'zero', 'boolean_count', 'partial_count',
    'wrong_summary_count', 'actual_mismatch', 'duplicate_identity', 'missing_expected', 'empty_text',
])
def test_incomplete_or_inconsistent_caption_proof_cannot_be_promoted(fault):
    inputs = material()
    readback = inputs[0]['formats']['word']['readback']
    check = readback['checks'][0]
    counts = check['evidenceObjects']
    if fault == 'missing_kind':
        check.pop('evidenceKind')
    elif fault == 'wrong_kind':
        check['evidenceKind'] = 'different_reader'
    elif fault == 'sample':
        check['coverage'] = 'sample'
    elif fault == 'missing_coverage':
        check.pop('coverage')
    elif fault == 'missing_passed':
        check.pop('passed')
    elif fault == 'capability_only':
        readback['checks'] = []
        inputs[0]['formats']['word']['capabilities'] = [{'path': PATH, 'status': 'verified'}]
    elif fault == 'unverified_source':
        counts['sourceStatus'] = 'unverified'
    elif fault == 'summary_source':
        readback['tableCaptionReadback']['sourceStatus'] = 'unverified'
    elif fault == 'source_issues':
        readback['tableCaptionReadback']['issues'] = [{'code': 'source_unverified'}]
    elif fault in ('zero', 'boolean_count', 'partial_count'):
        counts['checkedCaptions'] = {'zero': 0, 'boolean_count': True, 'partial_count': 1}[fault]
    elif fault == 'wrong_summary_count':
        readback['tableCaptionReadback']['actualCount'] = 1
    elif fault == 'actual_mismatch':
        check['actual'][1][-1][-2] = False
    elif fault == 'duplicate_identity':
        check['actual'][1][-1][0] = check['actual'][1][0][0]
        check['expected'] = deepcopy(check['actual'])
    elif fault == 'missing_expected':
        check.pop('expected')
    else:
        check['actual'][1][-1][1] = ''
        check['expected'] = deepcopy(check['actual'])
    assert mapped(inputs) == []


@pytest.mark.parametrize('fault', ['unauthorized', 'invalid_binding', 'draft_version', 'draft_hash',
    'contract_hash', 'missing_runtime', 'inline_size', 'retained_hash', 'preview_only', 'retention_issue',
    'registration_support', 'registration_role', 'registration_dimension', 'pdf'])
def test_caption_mapping_requires_current_authority_contract_and_retained_word(fault):
    inputs = material()
    result, contract, binding, retained = inputs
    if fault == 'unauthorized':
        result['binding']['artifactAccessAuthorized'] = False
    elif fault == 'invalid_binding':
        result['binding']['valid'] = False
    elif fault == 'draft_version':
        result['draftVersion'] += 1
    elif fault == 'draft_hash':
        result['contentHash'] = 'c' * 64
    elif fault == 'contract_hash':
        binding['contractHash'] = 'c' * 64
    elif fault == 'missing_runtime':
        binding.pop('executorManifestHash')
    elif fault == 'inline_size':
        result['formats']['word']['artifact']['size'] = True
    elif fault == 'retained_hash':
        retained['formats']['word']['artifact']['sha256'] = 'c' * 64
    elif fault == 'preview_only':
        retained['formats']['word']['pdf'] = retained['formats']['word'].pop('artifact')
    elif fault == 'retention_issue':
        retained['issues'].append({'format': 'word', 'role': 'artifact'})
    elif fault.startswith('registration_'):
        field = next(f for f in contract['fields'] if f['path'] == PATH)
        if fault == 'registration_support':
            field['support'] = 'compatibility_only'
        elif fault == 'registration_role':
            field['semanticRole'] = 'body'
        else:
            field['evidenceDimensions'] = ['visual']
        binding['contractHash'] = approval_contract_hash(contract)
    else:
        result['formats']['pdf'] = result['formats'].pop('word')
        retained['formats']['pdf'] = retained['formats'].pop('word')
    assert mapped(inputs) == []


@pytest.mark.parametrize('passed', [False, True])
def test_extra_same_path_failure_or_sample_cannot_be_overwritten(passed):
    inputs = material()
    inputs[0]['formats']['word']['readback']['checks'].append({
        'path': PATH, 'passed': passed, 'coverage': 'sample'})
    rows = mapped(inputs)
    if passed:
        assert rows == []
    else:
        assert len(rows) == 1 and rows[0]['status'] == 'failed'
        gaps = evaluate_required_coverage({**inputs[1], 'expectedBinding': inputs[2]}, rows)
        assert any(gap.get('path') == PATH and gap['reason'] == 'check_failed' for gap in gaps)
