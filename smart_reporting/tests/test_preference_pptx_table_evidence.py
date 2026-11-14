"""表格字段证据必须覆盖同文件全部冻结表及全部原生续页。"""

from copy import deepcopy
from hashlib import sha256

import pytest

from smart_reporting.preferences.approval_contract import (
    approval_contract,
    approval_contract_hash,
    evaluate_required_coverage,
)

MARKER = 'pptx_native_table_fields_v1'
FIELDS = ('tables.repeatHeader', 'tables.borders', 'tables.striped', 'tables.captionNumbering',
    'typography.table.font', 'typography.table.size', 'typography.table.color', 'typography.table.bold',
    'typography.table.lineHeight', 'typography.table.spaceBefore', 'typography.table.spaceAfter')
GUARDS = ('tables.content', 'tables.visibility', 'tables.structure', 'tables.bounds', 'tables.nativeRuns')


def check(path, **changes):
    return {'path': 'pptx.' + path, 'passed': True, 'coverage': 'complete', 'evidenceKind': MARKER, **changes}


def material():
    contract = approval_contract()
    binding = {'draftVersion': 7, 'draftHash': 'a' * 64,
        'contractHash': approval_contract_hash(contract), 'executorManifestHash': 'b' * 64}
    checks = [check(path) for index in range(2) for path in (*GUARDS, *FIELDS)]
    checks.append(check('tables.objectCoverage', actual=[True, True, True], expected=[True, True, True],
        evidenceObjects={'sourceTables': 2, 'nativeTables': 3, 'checkedNativeTables': 3, 'bodyRuns': 8}))
    artifact = {'size': 4, 'sha256': sha256(b'test').hexdigest(), 'base64': 'dGVzdA=='}
    result = {'draftVersion': 7, 'contentHash': 'a' * 64,
        'binding': {'valid': True, 'artifactAccessAuthorized': True}, 'formats': {'pptx': {
            'artifact': artifact, 'pdf': None, 'status': 'failed', 'capabilities': [],
            'readback': {'status': 'failed', 'checks': checks}}}}
    retained = {'formats': {'pptx': {'artifact': {'size': 4, 'sha256': artifact['sha256']}}}, 'issues': []}
    return result, contract, binding, retained


def mapped(inputs):
    from smart_reporting.management.preference_pptx_table_evidence import map_pptx_table_evidence

    return map_pptx_table_evidence(*inputs)


def checks(inputs):
    return inputs[0]['formats']['pptx']['readback']['checks']


def test_maps_eleven_complete_fields_with_contract_roles_and_actual_native_identity():
    inputs = material()
    original = deepcopy(inputs)
    rows = mapped(inputs)
    assert len(rows) == 11
    assert {row['path'] for row in rows} == {'pptx.' + path for path in FIELDS}
    for row in rows:
        assert row['requirementId'] == 'slides-native-content-and-style'
        assert row['role'] == ('table' if row['path'].startswith('pptx.typography.') else 'tables')
        assert row['status'] == 'passed' and row['objectScope'] == 'complete' and row['authorized'] is True
        assert row['format'] == 'pptx' and row['dimension'] == 'native' and row['scenario'] == 'configured_field'
        assert row['binding'] == inputs[2]
        assert row['sourceArtifact'] == {'format': 'pptx', 'role': 'artifact'}
        assert row['artifact'] == {'sizeBytes': 4, 'sha256': sha256(b'test').hexdigest()}
        assert row['readerGroup'] == MARKER
        assert row['readbackCheckIndexes'] and all(type(index) is int for index in row['readbackCheckIndexes'])
    assert inputs == original
    gaps = evaluate_required_coverage({**inputs[1], 'expectedBinding': inputs[2]}, rows)
    assert gaps and any('visual' in gap['missingDimensions'] for gap in gaps)
    assert not any(gap.get('path') in {row['path'] for row in rows}
        and gap.get('scenario') == 'configured_field' for gap in gaps)


@pytest.mark.parametrize('guard', GUARDS)
def test_late_group_guard_failure_cannot_be_covered_by_first_table_success(guard):
    inputs = material()
    row = next(row for row in reversed(checks(inputs)) if row['path'] == 'pptx.' + guard)
    row['passed'] = False
    rows = mapped(inputs)
    assert len(rows) == 11 and all(row['status'] == 'failed' for row in rows)
    gaps = evaluate_required_coverage({**inputs[1], 'expectedBinding': inputs[2]}, rows)
    assert len([gap for gap in gaps if gap['reason'] == 'check_failed']) == 11


@pytest.mark.parametrize('fault', ['missing', 'sample', 'unmarked'])
def test_missing_or_incomplete_group_guard_never_qualifies_field_pass(fault):
    inputs = material()
    group = checks(inputs)
    if fault == 'missing':
        group[:] = [row for row in group if row['path'] != 'pptx.tables.nativeRuns']
    elif fault == 'unmarked':
        for row in group:
            if row['path'] == 'pptx.tables.nativeRuns':
                row.pop('evidenceKind')
    else:
        next(row for row in group if row['path'] == 'pptx.tables.nativeRuns')['coverage'] = 'sample'
    assert mapped(inputs) == []


@pytest.mark.parametrize('fault', ['absent', 'old_marker', 'missing_counts', 'boolean_count',
    'no_frozen', 'no_native', 'sample'])
def test_requires_trusted_nonzero_group_object_witness(fault):
    inputs = material()
    group = checks(inputs)
    witness = group[-1]
    if fault == 'absent':
        group.pop()
    elif fault == 'old_marker':
        witness['evidenceKind'] = 'some_other_reader'
    elif fault == 'missing_counts':
        witness.pop('evidenceObjects')
    elif fault == 'boolean_count':
        witness['evidenceObjects']['sourceTables'] = True
    elif fault == 'no_frozen':
        witness['evidenceObjects']['sourceTables'] = 0
    elif fault == 'no_native':
        witness['evidenceObjects']['nativeTables'] = 0
    else:
        witness['coverage'] = 'sample'
    assert mapped(inputs) == []


def test_unconsumed_extra_native_table_fails_whole_group_even_if_witness_boolean_is_wrongly_true():
    inputs = material()
    checks(inputs)[-1]['evidenceObjects']['nativeTables'] = 4
    rows = mapped(inputs)
    assert len(rows) == 11 and all(row['status'] == 'failed' for row in rows)


@pytest.mark.parametrize('count', [None, 0, True, -1])
def test_header_override_does_not_prove_user_body_color_or_bold_without_checked_body_runs(count):
    inputs = material()
    objects = checks(inputs)[-1]['evidenceObjects']
    if count is None:
        objects.pop('bodyRuns')
    else:
        objects['bodyRuns'] = count
    rows = mapped(inputs)
    assert len(rows) == 9
    assert not any(row['path'] in {'pptx.typography.table.color', 'pptx.typography.table.bold'} for row in rows)
    assert all(row['status'] == 'passed' for row in rows)


@pytest.mark.parametrize('extra', [{'passed': False}, {'passed': False, 'evidenceKind': None},
    {'coverage': 'sample'}, {'coverage': 'partial'}])
def test_late_field_failure_or_sampling_cannot_be_overwritten(extra):
    inputs = material()
    checks(inputs).append(check('typography.table.color', **extra))
    rows = mapped(inputs)
    target = [row for row in rows if row['path'] == 'pptx.typography.table.color']
    if extra.get('passed') is False:
        assert len(target) == 1 and target[0]['status'] == 'failed'
    else:
        assert target == []
    assert len([row for row in rows if row['status'] == 'passed']) == 10


@pytest.mark.parametrize('fault', ['old_unmarked', 'capability_only', 'unexercised'])
def test_does_not_infer_field_evidence_from_overall_status_or_capabilities(fault):
    inputs = material()
    entry = inputs[0]['formats']['pptx']
    entry['status'] = entry['readback']['status'] = 'passed'
    entry['capabilities'] = [{'path': 'pptx.' + path, 'status': 'verified'} for path in FIELDS]
    if fault in ('old_unmarked', 'capability_only'):
        for row in checks(inputs):
            row.pop('evidenceKind')
    else:
        checks(inputs)[:] = [row for row in checks(inputs) if row['path'] not in {'pptx.' + path for path in FIELDS}]
    assert mapped(inputs) == []


@pytest.mark.parametrize('fault', ['unauthorized', 'invalid_binding', 'wrong_draft', 'wrong_version',
    'wrong_contract', 'missing_executor', 'preview_only', 'different_hash', 'different_size',
    'boolean_size', 'same_file_issue'])
def test_reuses_exact_authority_runtime_and_same_native_file_identity_boundaries(fault):
    inputs = material()
    result, _, binding, retained = inputs
    if fault == 'unauthorized':
        result['binding']['artifactAccessAuthorized'] = False
    elif fault == 'invalid_binding':
        result['binding']['valid'] = False
    elif fault == 'wrong_draft':
        result['contentHash'] = 'c' * 64
    elif fault == 'wrong_version':
        result['draftVersion'] = 8
    elif fault == 'wrong_contract':
        binding['contractHash'] = 'c' * 64
    elif fault == 'missing_executor':
        binding.pop('executorManifestHash')
    elif fault == 'preview_only':
        retained['formats']['pptx']['pdf'] = retained['formats']['pptx'].pop('artifact')
    elif fault == 'different_hash':
        retained['formats']['pptx']['artifact']['sha256'] = 'c' * 64
    elif fault == 'different_size':
        retained['formats']['pptx']['artifact']['size'] = 5
    elif fault == 'boolean_size':
        result['formats']['pptx']['artifact']['size'] = retained['formats']['pptx']['artifact']['size'] = True
    else:
        retained['issues'].append({'format': 'pptx', 'role': 'artifact', 'stage': 'readback'})
    assert mapped(inputs) == []


@pytest.mark.parametrize('fault', ['missing_field', 'compatibility_only', 'not_editable', 'wrong_role', 'missing_check'])
def test_only_same_contract_registered_implemented_editable_fields_can_map(fault):
    inputs = material()
    path = 'pptx.typography.table.color'
    field = next(field for field in inputs[1]['fields'] if field['path'] == path)
    if fault == 'missing_field':
        inputs[1]['fields'].remove(field)
    elif fault == 'compatibility_only':
        field['support'] = 'compatibility_only'
    elif fault == 'not_editable':
        field['editable'] = False
    elif fault == 'wrong_role':
        field['semanticRole'] = 'caption'
    else:
        for requirement in inputs[1]['requirements']:
            requirement['checks'] = [check for check in requirement['checks'] if check.get('path') != path]
    inputs[2]['contractHash'] = approval_contract_hash(inputs[1])
    rows = mapped(inputs)
    assert len(rows) == 10 and all(row['path'] != path for row in rows)


@pytest.mark.parametrize(('qualified_runtime', 'failed_group'), [(True, False), (True, True), (False, False), (False, True)])
def test_record_result_combines_table_fields_before_existing_runtime_gate_and_gap_assessment(qualified_runtime, failed_group):
    import asyncio
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from smart_reporting.management.configuration_store import configuration_hash
    from smart_reporting.management.preference_evidence import PreferenceEvidenceService

    async def scenario():
        inputs = material()
        result, _, _, retained = inputs
        if failed_group:
            next(row for row in checks(inputs) if row['path'] == 'pptx.tables.content')['passed'] = False
        now = datetime(2026, 11, 13, tzinfo=UTC)
        manifest = {'runtimeIdentityComplete': qualified_runtime, 'runtimeIdentityIssues': []}
        captured = {}

        async def scalar(statement):
            return now + timedelta(hours=1)

        @asynccontextmanager
        async def connect():
            yield SimpleNamespace(scalar=scalar)

        async def retain(*args, **kwargs):
            return deepcopy(retained)

        async def session(*args):
            return SimpleNamespace(expires_at=now + timedelta(hours=1))

        async def insert(table, id, document):
            captured.update(id=id, document=deepcopy(document), content_hash=configuration_hash(document))
            return captured['content_hash']

        async def load(table, id):
            return captured

        service = object.__new__(PreferenceEvidenceService)
        service.retention = SimpleNamespace(retain=retain)
        service.repository = SimpleNamespace(engine=SimpleNamespace(connect=connect))
        service.handoff = SimpleNamespace(bound=SimpleNamespace(grants=SimpleNamespace(lookup_registered_session=session)))
        service.auth = SimpleNamespace(clock=lambda: now)
        service._insert, service._load = insert, load
        receipt, issues = await service.record_result(result, {'draft_version': 7, 'draft_hash': 'a' * 64,
            'editor_session_hash': 'editor', 'admin_session_hash': 'admin', 'admin_auth_version': 1}, manifest)
        document = captured['document']
        assert receipt['contentHash'] == captured['content_hash'] and issues == []
        rows = document['evidence']
        assert len(rows) == (11 if qualified_runtime or failed_group else 0)
        assert all(row['status'] == ('failed' if failed_group else 'passed') for row in rows)
        assert all(row['binding']['executorManifestHash'] == configuration_hash(manifest) for row in rows)
        assert document['assessment']['status'] == 'incomplete' and document['assessment']['canApply'] is False
        gaps = document['assessment']['missingRequirements']
        assert gaps and any('visual' in gap['missingDimensions'] for gap in gaps)
        if qualified_runtime and not failed_group:
            assert not any(gap.get('path') in {row['path'] for row in rows}
                and gap.get('scenario') == 'configured_field' for gap in gaps)
        if failed_group:
            assert len([gap for gap in gaps if gap['reason'] == 'check_failed']) == 11
        if not qualified_runtime:
            assert any(gap['reason'] == 'executor_identity_unavailable' for gap in gaps)

    asyncio.run(scenario())
