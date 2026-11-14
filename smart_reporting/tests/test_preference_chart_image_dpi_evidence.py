"""图表DPI原生证据只能引用当前草稿的完整最终文件回读。"""

from copy import deepcopy
from hashlib import sha256

import pytest

from smart_reporting.preferences.approval_contract import (
    approval_contract,
    approval_contract_hash,
    evaluate_required_coverage,
)

MARKER = 'chart_image_dpi_v1'
FORMATS = ('pptx', 'pdf', 'word')


def evidence_input():
    contract = approval_contract()
    binding = {'draftVersion': 4, 'draftHash': 'a' * 64,
        'contractHash': approval_contract_hash(contract), 'executorManifestHash': 'b' * 64}
    formats = {}
    retained_formats = {}
    for format in FORMATS:
        artifact = {'size': 8, 'sha256': sha256((format + '-artifact').encode()).hexdigest(),
            'base64': 'eHl6'}
        check = {'path': format + '.charts.imageDpi', 'passed': True, 'actual': True, 'expected': True,
            'coverage': 'complete', 'evidenceKind': MARKER,
            'evidenceObjects': {'targetDpi': 150, 'expectedImages': 1, 'readImages': 1,
                'images': [{'mediaSha256': sha256((format + '-image').encode()).hexdigest(),
                    'effectiveDpi': {'x': 150.0, 'y': 150.0}}]}}
        formats[format] = {'artifact': artifact, 'readback': {'checks': [check]},
            'capabilities': [{'path': format + '.charts.imageDpi', 'value': 150, 'status': 'verified'}]}
        retained_formats[format] = {'artifact': {'size': artifact['size'], 'sha256': artifact['sha256']}}
    result = {'draftVersion': 4, 'contentHash': binding['draftHash'],
        'binding': {'valid': True, 'artifactAccessAuthorized': True}, 'formats': formats}
    retained = {'formats': retained_formats, 'issues': []}
    return result, contract, binding, retained


def mapped(inputs):
    from smart_reporting.management.preference_native_evidence import (
        map_native_chart_image_dpi_evidence,
    )

    return map_native_chart_image_dpi_evidence(*inputs)


def test_maps_all_three_format_dpi_checks_only_to_complete_native_evidence():
    inputs = evidence_input()
    original = deepcopy(inputs)
    rows = mapped(inputs)
    assert {row['path'] for row in rows} == {format + '.charts.imageDpi' for format in FORMATS}
    assert all(row['status'] == 'passed' and row['objectScope'] == 'complete'
        and row['dimension'] == 'native' and row['authorized'] is True for row in rows)
    runtime = {**inputs[1], 'expectedBinding': inputs[2]}
    gaps = evaluate_required_coverage(runtime, rows)
    for format in FORMATS:
        assert not any(gap.get('path') == format + '.charts.imageDpi'
            and gap.get('scenario') == 'configured_field' and 'native' in gap.get('missingDimensions', [])
            for gap in gaps)
    assert gaps
    assert inputs == original


@pytest.mark.parametrize('fault', ['missing_marker', 'sample', 'empty', 'count_mismatch', 'boolean_count', 'over_target',
    'invalid_image_hash', 'capability_not_verified'])
def test_never_promotes_incomplete_or_unverified_dpi_readback(fault):
    inputs = evidence_input()
    check = inputs[0]['formats']['pdf']['readback']['checks'][0]
    if fault == 'missing_marker':
        check.pop('evidenceKind')
    elif fault == 'sample':
        check['coverage'] = 'sample'
    elif fault == 'empty':
        check['evidenceObjects']['expectedImages'] = 0
        check['evidenceObjects']['readImages'] = 0
        check['evidenceObjects']['images'] = []
    elif fault == 'count_mismatch':
        check['evidenceObjects']['readImages'] = 2
    elif fault == 'boolean_count':
        check['evidenceObjects']['readImages'] = True
    elif fault == 'over_target':
        check['evidenceObjects']['images'][0]['effectiveDpi']['x'] = 150.1
    elif fault == 'invalid_image_hash':
        check['evidenceObjects']['images'][0]['mediaSha256'] = 'invalid'
    else:
        inputs[0]['formats']['pdf']['capabilities'][0]['status'] = 'not_verified'
    assert not any(row['format'] == 'pdf' for row in mapped(inputs))


def test_records_a_failed_native_check_without_turning_it_into_passed_evidence():
    inputs = evidence_input()
    inputs[0]['formats']['word']['readback']['checks'][0]['passed'] = False
    rows = [row for row in mapped(inputs) if row['format'] == 'word']
    assert len(rows) == 1 and rows[0]['status'] == 'failed'
    gaps = evaluate_required_coverage({**inputs[1], 'expectedBinding': inputs[2]}, rows)
    assert any(gap.get('path') == 'word.charts.imageDpi' and gap['reason'] == 'check_failed'
        for gap in gaps)


@pytest.mark.parametrize('fault', ['wrong_binding', 'wrong_version', 'wrong_draft', 'inline_hash', 'retained_size'])
def test_requires_current_draft_and_exact_retained_final_artifact(fault):
    inputs = evidence_input()
    result, _contract, binding, retained = inputs
    if fault == 'wrong_binding':
        binding['contractHash'] = 'c' * 64
    elif fault == 'wrong_version':
        result['draftVersion'] += 1
    elif fault == 'wrong_draft':
        result['contentHash'] = 'c' * 64
    elif fault == 'inline_hash':
        result['formats']['pptx']['artifact']['sha256'] = 'c' * 64
    else:
        retained['formats']['word']['artifact']['size'] += 1
    affected = 'pptx' if fault == 'inline_hash' else 'word' if fault == 'retained_size' else None
    rows = mapped(inputs)
    assert not rows if affected is None else not any(row['format'] == affected for row in rows)
