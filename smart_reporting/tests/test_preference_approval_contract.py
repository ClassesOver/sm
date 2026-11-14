"""批准合同只接受同一服务端绑定下的完整证据，不把采样提升为全量。"""
import importlib
import importlib.util
from copy import deepcopy

import pytest

from smart_reporting.preferences.models import (
    FORMATS,
    CommonPreferences,
    FormatPreferences,
    resolve_format_preferences,
)


def api():
    assert importlib.util.find_spec('smart_reporting.preferences.approval_contract'), '缺少服务端批准合同'
    return importlib.import_module('smart_reporting.preferences.approval_contract')


def leaves(value, prefix=''):
    result = set()
    for key, nested in value.items():
        path = f'{prefix}.{key}' if prefix else key
        result.update(leaves(nested, path) if isinstance(nested, dict) else {path})
    return result


def fixture_contract():
    contract = {'contractVersion': 1, 'requirementsVersion': 1, 'specDigest': 'a' * 64,
        'fields': [], 'editablePaths': [], 'requirements': [{'id': 'test-only-signature',
            'implementation': 'implemented', 'checks': [
                {'format': 'word', 'role': 'terminal_signature', 'scenario': 'long_name',
                    'dimensions': ['native', 'visual']},
                {'format': 'xlsx', 'role': 'terminal_signature', 'scenario': 'print',
                    'dimensions': ['native']}]}]}
    contract['expectedBinding'] = {'draftVersion': 4, 'draftHash': 'b' * 64,
        'contractHash': api().approval_contract_hash(contract), 'executorManifestHash': 'c' * 64}
    return contract


def evidence(contract, *, format='word', scenario='long_name', dimension='native', **changes):
    result = {'binding': deepcopy(contract['expectedBinding']), 'requirementId': 'test-only-signature',
        'format': format, 'role': 'terminal_signature', 'scenario': scenario,
        'dimension': dimension, 'status': 'passed', 'objectScope': 'complete',
        'authorized': True, 'artifact': {'sha256': 'd' * 64, 'sizeBytes': 42}}
    result.update(changes)
    return result


def complete_evidence(contract):
    return [evidence(contract), evidence(contract, dimension='visual'),
        evidence(contract, format='xlsx', scenario='print')]


def test_registry_exactly_covers_real_405_leaves_and_preserves_legacy_rejections():
    module = api()
    contract = module.approval_contract()
    model = FormatPreferences(common=CommonPreferences(signer='合同测试'))
    expected = set().union(*(leaves(resolve_format_preferences(model, format), format) for format in FORMATS))
    paths = [item['path'] for item in contract['fields']]
    assert len(paths) == len(set(paths)) == 405
    assert set(paths) == expected
    from smart_reporting.tests.test_preference_supported_changes import unsupported_paths
    assert {item['path'] for item in contract['fields'] if item['legacyUnsupportedReason']} == set(unsupported_paths())
    fields = {item['path']: item for item in contract['fields']}
    assert fields['md.common.font']['support'] == 'not_applicable'
    assert not fields['md.common.font']['editable']
    assert fields['pdf.embedFonts']['support'] == 'compatibility_only'
    assert fields['pptx.typography.h2.font']['support'] == 'not_applicable'
    assert fields['xlsx.body.spaceAfter']['support'] == 'not_applicable'
    assert fields['pptx.tables.borders']['requirementIds'] == ['slides-native-content-and-style']
    assert all(item['consumer'] and item['nativeProperty'] for item in contract['fields'] if item['support'] == 'implemented')
    assert all(set(item['resolvedPaths']) <= {field['path'] for field in contract['fields'] if field['support'] == 'implemented'}
        for item in contract['editablePaths'])


def test_unknown_model_leaf_is_not_silently_added(monkeypatch):
    module = api()
    original = module.resolve_format_preferences
    def changed(document, format):
        result = original(document, format)
        if format == 'word':
            result['futureOption'] = True
        return result
    monkeypatch.setattr(module, 'resolve_format_preferences', changed)
    with pytest.raises(ValueError, match='word.futureOption'):
        module.approval_contract()


def test_contract_hash_is_stable_excludes_binding_and_returns_independent_data():
    module = api()
    first = module.approval_contract()
    digest = module.approval_contract_hash(first)
    first['expectedBinding'] = {'draftVersion': 999}
    assert module.approval_contract_hash(first) == digest
    first['requirements'][0]['checks'].clear()
    assert module.approval_contract_hash(first) != digest
    assert module.approval_contract_hash(module.approval_contract()) == digest


def test_production_requirements_keep_original_unimplemented_behaviors():
    contract = api().approval_contract()
    requirements = {item['id']: item for item in contract['requirements']}
    assert {'signature-content-and-layout', 'template-binding-and-precedence', 'markdown-semantic-transform',
        'native-editable-role-style', 'paged-header-footer-and-numbering', 'workbook-display-invariants',
        'workbook-print-layout', 'slides-native-content-and-style', 'pdf-accessible-quality',
        'freeze-history-and-download', 'authorization-and-integrity', 'nonblocking-artifact-delivery',
        'maintenance-and-version-workflow'} <= requirements.keys()
    assert all(item['sourceSections'] and item['sourceText'] and item['checks'] for item in requirements.values())
    assert requirements['template-binding-and-precedence']['implementation'] != 'implemented'
    assert any(check['scenario'] == 'native_table_style' for check in requirements['slides-native-content-and-style']['checks'])
    gaps = api().evaluate_required_coverage(contract, [])
    assert any(item['reason'] == 'implementation_missing' and item['requirementId'] == 'template-binding-and-precedence' for item in gaps)
    assert any(item['reason'] == 'missing_binding' for item in gaps)


def test_independently_authorized_same_binding_scenarios_can_aggregate():
    contract = fixture_contract()
    rows = complete_evidence(contract)
    assert api().evaluate_required_coverage(contract, rows[:2])
    assert api().evaluate_required_coverage(contract, rows) == []


@pytest.mark.parametrize('changes', [
    {'objectScope': 'sample'}, {'objectScope': 'partial'}, {'status': 'not_exercised'},
    {'role': 'footer'}, {'authorized': False}, {'authorized': 1}, {'artifact': {}},
    {'artifact': {'sha256': 'd' * 64, 'sizeBytes': 0}}, {'status': 'sample'},
])
def test_incomplete_or_wrong_scope_evidence_never_covers_a_requirement(changes):
    contract = fixture_contract()
    rows = complete_evidence(contract)
    rows[0].update(changes)
    gaps = api().evaluate_required_coverage(contract, rows)
    assert any(item['requirementId'] == 'test-only-signature' and item.get('format') == 'word'
        and 'native' in item.get('missingDimensions', []) for item in gaps)


@pytest.mark.parametrize('key,value', [('draftVersion', 3), ('draftHash', 'e' * 64),
    ('contractHash', 'f' * 64), ('executorManifestHash', 'a' * 64)])
def test_wrong_binding_is_a_gap_even_alongside_good_evidence(key, value):
    contract = fixture_contract()
    rows = complete_evidence(contract)
    wrong = evidence(contract)
    wrong['binding'][key] = value
    gaps = api().evaluate_required_coverage(contract, [*rows, wrong])
    assert any(item['reason'] == 'binding_mismatch' for item in gaps)


def test_failure_cannot_be_hidden_by_complete_or_sample_success():
    contract = fixture_contract()
    failed = evidence(contract, status='failed', objectScope='sample', message='落款被裁切')
    rows = [*complete_evidence(contract), failed, evidence(contract, objectScope='sample')]
    gaps = api().evaluate_required_coverage(contract, rows)
    assert any(item['reason'] == 'check_failed' and item['message'] == '落款被裁切' for item in gaps)


def test_missing_expected_binding_and_forged_contract_hash_fail_closed():
    contract = fixture_contract()
    rows = complete_evidence(contract)
    contract.pop('expectedBinding')
    assert any(item['reason'] == 'missing_binding' for item in api().evaluate_required_coverage(contract, rows))
    contract['expectedBinding'] = {**rows[0]['binding'], 'contractHash': '0' * 64}
    assert any(item['reason'] == 'contract_hash_mismatch' for item in api().evaluate_required_coverage(contract, rows))


def test_unknown_requirement_is_not_usable_evidence_and_unchanged_legacy_value_is_allowed():
    module = api()
    contract = fixture_contract()
    assert any(item['reason'] == 'unknown_requirement' for item in module.evaluate_required_coverage(
        contract, [evidence(contract, requirementId='client-invented')]))
    before = {'word': {'charts': {'imageDpi': 200}}}
    assert module.editable_change_reason('word.charts.imageDpi', before, deepcopy(before)) is None
    assert module.editable_change_reason('word.charts.imageDpi', before, {'word': {'charts': {'imageDpi': 300}}}) is None
    assert module.editable_change_reason('word.futureOption', {}, {'word': {'futureOption': True}})
    assert module.editable_change_reason('common.font', {'common': {'font': 'sans'}}, {'common': {'font': 'serif'}}) is None


def test_required_missing_field_consumer_cannot_be_hidden_by_complete_role_checks():
    contract = fixture_contract()
    contract['fields'] = [{'path': 'word.charts.imageDpi', 'support': 'missing',
        'semanticRole': 'charts', 'requirementIds': ['test-only-signature'],
        'notApplicableReason': '正式图像输出质量字段未消费。'}]
    contract['expectedBinding']['contractHash'] = api().approval_contract_hash(contract)
    gaps = api().evaluate_required_coverage(contract, complete_evidence(contract))
    assert any(item.get('path') == 'word.charts.imageDpi' and item['reason'] == 'implementation_missing' for item in gaps)


def test_workbook_print_requirement_does_not_invent_manual_controls():
    requirement = next(item for item in api().approval_contract()['requirements']
        if item['id'] == 'workbook-print-layout')
    scenarios = {check['scenario'] for check in requirement['checks']}
    assert 'manual_print_range_pagination' not in scenarios
    assert 'print_range_pagination_semantics' in scenarios
    assert requirement['implementation'] != 'implemented'


def test_duplicate_registered_leaf_fails_contract_construction(monkeypatch):
    module = api()
    paths = deepcopy(module._REGISTERED_PATHS)
    paths['word'].append(paths['word'][0])
    monkeypatch.setattr(module, '_REGISTERED_PATHS', paths)
    with pytest.raises(ValueError, match='重复'):
        module.approval_contract()


def test_workbook_print_paragraph_only_fields_are_not_native_requirements():
    contract = api().approval_contract()
    fields = {item['path']: item for item in contract['fields']}
    for property in ('lineHeight', 'spaceBefore', 'spaceAfter', 'indent'):
        item = fields[f'xlsx.print.headerFooter.style.{property}']
        assert item['support'] == 'not_applicable'
        assert not item['editable']
        assert item['legacyUnsupportedReason']
    requirement = next(item for item in contract['requirements'] if item['id'] == 'workbook-print-layout')
    assert {'actual_print_range', 'arbitrary_long_table_header_signature'} <= {
        check['scenario'] for check in requirement['checks']}
    assert any(check['path'] == 'xlsx.print.headerFooter.style.size'
        for check in requirement['checks'] if 'path' in check)
