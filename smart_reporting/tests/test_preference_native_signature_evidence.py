"""严格尾部内容仅补对应字段的原生证据，不推断视觉或完整落款场景。"""

from copy import deepcopy
from hashlib import sha256

import pytest

from smart_reporting.management.configuration_store import configuration_hash
from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.preferences.approval_contract import (
    approval_contract,
    approval_contract_hash,
    evaluate_required_coverage,
)
from smart_reporting.preferences.markdown_adapter import START, append_signature
from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences

MARKER = 'terminal_signature_content_v1'
PATHS = ('common.signer', 'common.dateFormat', 'signature.description')


def material(format='md'):
    contract = approval_contract()
    binding = {'draftVersion': 7, 'draftHash': 'a' * 64,
        'contractHash': approval_contract_hash(contract), 'executorManifestHash': 'b' * 64}
    artifact = {'size': 4, 'sha256': sha256(b'test').hexdigest(), 'base64': 'dGVzdA=='}
    checks = [{'path': format + '.' + path, 'passed': True, 'coverage': 'complete',
        'evidenceKind': MARKER, 'message': '真实尾部检查'} for path in PATHS]
    result = {'draftVersion': 7, 'contentHash': 'a' * 64,
        'binding': {'valid': True, 'artifactAccessAuthorized': True},
        'formats': {format: {'artifact': artifact, 'readback': {'status': 'failed', 'checks': checks},
            'capabilities': [], 'status': 'failed'}}}
    retained = {'formats': {format: {'artifact': {'size': 4, 'sha256': artifact['sha256']}}}, 'issues': []}
    return result, contract, binding, retained


def mapped(inputs):
    from smart_reporting.management.preference_native_evidence import map_native_signature_evidence

    return map_native_signature_evidence(*inputs)


@pytest.mark.parametrize('format', ['md', 'word', 'pptx'])
def test_maps_only_three_registered_native_content_fields_and_preserves_input(format):
    inputs = material(format)
    original = deepcopy(inputs)
    rows = mapped(inputs)
    assert len(rows) == 3
    assert {row['path'] for row in rows} == {format + '.' + path for path in PATHS}
    for row in rows:
        assert row['requirementId'] == 'signature-content-and-layout'
        assert row['format'] == format and row['role'] == 'terminal_signature'
        assert row['scenario'] == 'configured_field' and row['dimension'] == 'native'
        assert row['status'] == 'passed' and row['objectScope'] == 'complete' and row['authorized'] is True
        assert row['binding'] == inputs[2]
        assert row['sourceArtifact'] == {'format': format, 'role': 'artifact'}
        assert row['artifact'] == {'sizeBytes': 4, 'sha256': sha256(b'test').hexdigest()}
    assert inputs == original
    runtime = {**inputs[1], 'expectedBinding': inputs[2]}
    gaps = evaluate_required_coverage(runtime, rows)
    assert gaps and not any(gap.get('path') in {row['path'] for row in rows}
        and gap.get('scenario') == 'configured_field' for gap in gaps)
    assert any('visual' in gap['missingDimensions'] for gap in gaps)


@pytest.mark.parametrize('fault', ['missing_marker', 'message_only', 'capability_only', 'sample',
    'partial', 'missing_coverage', 'missing_passed', 'wrong_marker'])
def test_never_promotes_unmarked_sample_or_capability_checks(fault):
    inputs = material()
    entry = inputs[0]['formats']['md']
    for check in entry['readback']['checks']:
        if fault in ('missing_marker', 'message_only', 'capability_only'):
            check.pop('evidenceKind')
        elif fault == 'wrong_marker':
            check['evidenceKind'] = 'different_reader'
        elif fault == 'missing_passed':
            check.pop('passed')
        elif fault == 'missing_coverage':
            check.pop('coverage')
        else:
            check['coverage'] = fault
    entry['readback']['status'] = 'passed'
    entry['capabilities'] = [{'path': 'md.' + path, 'status': 'verified'} for path in PATHS]
    assert mapped(inputs) == []


@pytest.mark.parametrize('format', ['xlsx', 'pdf'])
def test_excludes_workbook_extra_sheet_and_pdf_sampling_even_with_marker(format):
    assert mapped(material(format)) == []


@pytest.mark.parametrize('fault', ['unauthorized', 'invalid_binding', 'wrong_version', 'wrong_draft',
    'wrong_contract', 'missing_runtime', 'inline_size', 'inline_hash', 'boolean_size',
    'missing_native', 'preview_only', 'retained_size', 'retained_hash'])
def test_requires_exact_authorized_draft_and_native_retained_identity(fault):
    inputs = material()
    result, contract, binding, retained = inputs
    inline = result['formats']['md']['artifact']
    if fault == 'unauthorized':
        result['binding']['artifactAccessAuthorized'] = False
    elif fault == 'invalid_binding':
        result['binding']['valid'] = False
    elif fault == 'wrong_version':
        result['draftVersion'] = 8
    elif fault == 'wrong_draft':
        result['contentHash'] = 'c' * 64
    elif fault == 'wrong_contract':
        binding['contractHash'] = 'c' * 64
    elif fault == 'missing_runtime':
        binding.pop('executorManifestHash')
    elif fault == 'inline_size':
        inline['size'] = 8
    elif fault == 'inline_hash':
        inline['sha256'] = 'c' * 64
    elif fault == 'boolean_size':
        inline['size'] = True
        retained['formats']['md']['artifact']['size'] = True
    elif fault == 'missing_native':
        result['formats']['md']['artifact'] = None
    elif fault == 'preview_only':
        retained['formats']['md']['pdf'] = retained['formats']['md'].pop('artifact')
    elif fault == 'retained_size':
        retained['formats']['md']['artifact']['size'] = 8
    else:
        retained['formats']['md']['artifact']['sha256'] = 'c' * 64
    assert mapped(inputs) == []


@pytest.mark.parametrize('extra', [
    {'passed': False, 'coverage': 'complete', 'evidenceKind': MARKER},
    {'passed': False, 'coverage': 'sample'},
    {'passed': True, 'coverage': 'sample'},
    {'passed': True, 'coverage': 'partial'},
])
def test_all_same_path_checks_participate_and_failure_cannot_be_overwritten(extra):
    inputs = material()
    inputs[0]['formats']['md']['readback']['checks'].append({'path': 'md.common.signer', **extra})
    rows = mapped(inputs)
    signer = [row for row in rows if row['path'] == 'md.common.signer']
    if extra['passed'] is False:
        assert len(signer) == 1 and signer[0]['status'] == 'failed'
        gaps = evaluate_required_coverage({**inputs[1], 'expectedBinding': inputs[2]}, rows)
        assert any(gap.get('path') == 'md.common.signer' and gap['reason'] == 'check_failed' for gap in gaps)
    else:
        assert signer == []
    assert len([row for row in rows if row['status'] == 'passed']) == 2


def test_requires_exact_registered_contract_native_configured_field():
    inputs = material()
    for requirement in inputs[1]['requirements']:
        requirement['checks'] = [check for check in requirement['checks']
            if check.get('path') != 'md.common.signer']
    inputs[2]['contractHash'] = approval_contract_hash(inputs[1])
    assert {row['path'] for row in mapped(inputs)} == {'md.common.dateFormat', 'md.signature.description'}


@pytest.mark.parametrize('fault', ['missing', 'compatibility_only', 'not_editable', 'wrong_role', 'wrong_requirement'])
def test_contract_field_registration_must_authorize_each_configured_path(fault):
    inputs = material()
    field = next(field for field in inputs[1]['fields'] if field['path'] == 'md.common.signer')
    if fault == 'missing':
        inputs[1]['fields'].remove(field)
    elif fault == 'compatibility_only':
        field['support'] = 'compatibility_only'
    elif fault == 'not_editable':
        field['editable'] = False
    elif fault == 'wrong_role':
        field['semanticRole'] = 'body'
    else:
        field['requirementIds'] = ['different-requirement']
    inputs[2]['contractHash'] = approval_contract_hash(inputs[1])
    assert {row['path'] for row in mapped(inputs)} == {'md.common.dateFormat', 'md.signature.description'}


@pytest.mark.parametrize(('format', 'role', 'allowed'), [('md', 'artifact', False), ('md', 'pdf', True), ('word', 'artifact', True)])
def test_only_same_native_file_retention_issue_prevents_qualification(format, role, allowed):
    inputs = material()
    inputs[3]['issues'] = [{'format': format, 'role': role, 'stage': 'readback', 'code': 'test_readback_failed'}]
    assert len(mapped(inputs)) == (3 if allowed else 0)


def markdown_case():
    preferences = FormatPreferences.model_validate({'common': {'signer': '尾部署名', 'dateFormat': 'iso'},
        'md': {'toc': False, 'signature': {'description': '第一行说明\n第二行说明'}}})
    resolved = resolve_format_preferences(preferences, 'md')
    source = '# 报告\n\n## 业务\n\n尾部署名\n\n2026-11-13\n\n第一行说明\n\n第二行说明\n'
    frozen = {'markdown': source, 'state': {'_documentContext': {
        'generatedDate': '2026-11-13', 'sections': [{'title': '业务'}]}}}
    content = append_signature(source, resolved, '2026-11-13').encode()
    return resolved, frozen, content


@pytest.mark.parametrize('fault', [None, 'missing', 'duplicate', 'missing_description'])
def test_actual_markdown_tail_reader_marks_only_strict_content_and_maps_positive_negative(fault):
    import json
    from pathlib import Path

    resolved, frozen, content = markdown_case()
    if fault == 'missing':
        content = content.decode().split(START)[0].encode()
    elif fault == 'duplicate':
        content += (START + content.decode().split(START)[1]).encode()
    elif fault == 'missing_description':
        body, signature = content.decode().split(START)
        content = (body + START + signature.replace('第二行说明', '')).encode()
    actual = readback(content, 'md', resolved, frozen)
    checks = [check for check in actual['checks'] if check['path'] in {'md.' + path for path in PATHS}]
    assert len(checks) == 3 and all(check.get('evidenceKind') == MARKER for check in checks)
    assert all('evidenceKind' not in check for check in actual['checks'] if check not in checks)
    inputs = material()
    inputs[0]['formats']['md']['readback'] = actual
    identity = {'size': len(content), 'sha256': sha256(content).hexdigest()}
    inputs[0]['formats']['md']['artifact'].update(identity)
    inputs[3]['formats']['md']['artifact'].update(identity)
    rows = mapped(inputs)
    assert len(rows) == 3
    failed = {row['path'] for row in rows if row['status'] == 'failed'}
    assert failed == ({'md.signature.description'} if fault == 'missing_description' else
        {'md.' + path for path in PATHS} if fault else set())
    root = Path('output/system-config-preferences/native-signature-evidence')
    root.mkdir(parents=True, exist_ok=True)
    label = fault or 'valid'
    (root / ('md-' + label + '.md')).write_bytes(content)
    (root / ('md-' + label + '-proof.json')).write_text(json.dumps({'realGenerator': True,
        'realReader': True, 'binding': 'fixture', 'retention': 'fixture_same_identity_not_sql',
        **identity, 'signatureChecks': checks, 'evidence': rows}, ensure_ascii=False, indent=2))


@pytest.mark.parametrize(('runtime_qualified', 'actual_failed'), [(True, False), (True, True), (False, False), (False, True)])
def test_record_result_persists_only_qualified_native_fields_and_computes_remaining_gaps(runtime_qualified, actual_failed):
    import asyncio
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from smart_reporting.management.preference_evidence import PreferenceEvidenceService

    async def scenario():
        result, contract, binding, retained = material()
        if actual_failed:
            for check in result['formats']['md']['readback']['checks']:
                check['passed'] = False
        now = datetime(2026, 11, 13, tzinfo=UTC)
        manifest = {'runtimeIdentityComplete': runtime_qualified, 'runtimeIdentityIssues': []}
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
        handoff = {'draft_version': 7, 'draft_hash': 'a' * 64,
            'editor_session_hash': 'editor-hash', 'admin_session_hash': 'admin-hash', 'admin_auth_version': 1}
        receipt, issues = await service.record_result(result, handoff, manifest)
        document = captured['document']
        assert receipt['contentHash'] == captured['content_hash'] and issues == []
        rows = document['evidence']
        assert len(rows) == (3 if runtime_qualified or actual_failed else 0)
        assert all(row['status'] == ('failed' if actual_failed else 'passed') for row in rows)
        assert all(row['binding']['executorManifestHash'] == configuration_hash(manifest) for row in rows)
        assert document['assessment']['status'] == 'incomplete' and document['assessment']['canApply'] is False
        gaps = document['assessment']['missingRequirements']
        assert gaps
        if runtime_qualified and not actual_failed:
            assert not any(gap.get('path') in {'md.' + path for path in PATHS}
                and gap.get('scenario') == 'configured_field' for gap in gaps)
        if actual_failed:
            assert {gap['path'] for gap in gaps if gap['reason'] == 'check_failed'} == {'md.' + path for path in PATHS}
        if not runtime_qualified:
            assert any(gap['reason'] == 'executor_identity_unavailable' for gap in gaps)

    asyncio.run(scenario())
