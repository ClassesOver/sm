"""结构化数值的期间仅归属当前锚点，省略年份仍从正文继承。"""

import hashlib
import json

import pytest

from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
from smart_reporting.reporting.tests.test_semantic_bindings import contents
from smart_reporting.reporting.tests.test_trace_subject_validate import _make_editor_with_subject
from smart_reporting.reporting.trace.index_builder import encode_trace_index
from smart_reporting.reporting.trace.semantic_bindings import (
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import claim_status


def _check(statement, claim_id, index, *, unit='元'):
    bundle = json.loads(contents()[0])
    bundle['metrics'][0]['unit'] = unit or None
    selected = resolve_number_reference(
        '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.' + str(index) + ':' + unit + '}}',
        [json.dumps(bundle)],
    )
    assert selected is not None
    return claim_status(
        statement, claim_id, selected['value'], expected_unit=selected['unit'],
        expected_periods=selected['periods'], expected_period_roles=selected['period_roles'],
        expected_scope=selected['scope'], expected_reference=selected,
    )


@pytest.mark.parametrize('statement', [
    '2025年1月收入10元[[claim:jan]]及2月收入20元[[claim:feb]]。',
    '2025年1月收入10元[[claim:jan]]和2月收入20元[[claim:feb]]。',
    pytest.param('2025年1月收入10元[[claim:jan]]与2月收入20元[[claim:feb]]。', id='with_conjunction'),
    '2025年2月收入20元[[claim:feb]]、1月收入10元[[claim:jan]]。',
    '收入10元[[claim:jan]]（2025年1月）及收入20元[[claim:feb]]（2月）。',
    '收入10元[[claim:jan]][[citation:sub-0000000000000000]]（2025年1月）'
    '及收入20元[[claim:feb]][[citation:sub-1111111111111111]]（2月）。',
    pytest.param('收入10元[[claim:jan]]（口径（2025年1月））及2月收入20元[[claim:feb]]。', id='nested_notes'),
    '2025年1月收入10元。[[claim:jan]]2025年2月收入20元。[[claim:feb]]',
])
def test_each_claim_uses_its_own_month_and_inherits_the_written_year(statement):
    assert _check(statement, 'jan', 0) == {'status': 'valid', 'warnings': []}
    assert _check(statement, 'feb', 1) == {'status': 'valid', 'warnings': []}


def test_shared_date_is_not_lost_after_the_previous_reference():
    statement = '2025年2月门诊收入20元[[claim:first]]及住院收入20元[[claim:second]]。'
    assert _check(statement, 'second', 1) == {'status': 'valid', 'warnings': []}


@pytest.mark.parametrize('statement', [
    '2025年2月收入10元[[claim:jan]]及1月收入20元[[claim:feb]]。',
    '收入10元[[claim:jan]]（2025年2月）及收入20元[[claim:feb]]（1月）。',
])
def test_real_wrong_month_is_still_reported_for_each_reference(statement):
    for claim_id, index in [('jan', 0), ('feb', 1)]:
        result = _check(statement, claim_id, index)
        assert result['status'] == 'valid'
        assert any('期间' in warning for warning in result['warnings'])


def test_unanchored_equal_value_cannot_supply_the_current_claim_month():
    result = _check('2025年1月调整10元，2月收入10元[[claim:jan]]。', 'jan', 0)
    assert result['status'] == 'valid'
    assert any('期间' in warning for warning in result['warnings'])


def test_current_wrong_number_cannot_borrow_another_anchored_value():
    result = _check('2025年1月调整20元[[claim:other]]，2月收入30元[[claim:feb]]。', 'feb', 1)
    assert result['status'] == 'stale'


@pytest.mark.parametrize('unit', ['台', '套', '件', '平方米', ''])
def test_registered_custom_or_missing_unit_remains_bindable(unit):
    statement = f'2025年1月数量10{unit}[[claim:jan]]及2月数量20{unit}[[claim:feb]]。'
    assert _check(statement, 'jan', 0, unit=unit) == {'status': 'valid', 'warnings': []}
    assert _check(statement, 'feb', 1, unit=unit) == {'status': 'valid', 'warnings': []}


async def _editor_with_both_references(tmp_path, *, equal_values=False):
    statement = ('2025年9月收入{{value:fact-aaaaaaaaaaaaaaaa:periodValues.0:万元}}'
                 '及10月收入{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:万元}}。')
    editor, grants, context = await _make_editor_with_subject(
        tmp_path, period_table=True, number_reference=True, include_table=False,
        number_statement=statement, metric_values=(10, 10) if equal_values else None,
    )
    index = await editor.trace.load_index(context)
    source = next(tmp_path.rglob('analysis_001.json')).read_text()
    _markdown, references, _notices = render_bound_numbers(statement, [source], key='section_002:block')
    assert index is not None and len(references) == 2
    original = index.subject_bindings[0]
    index = index.model_copy(update={'subject_bindings': tuple(
        original.model_copy(update={
            'subject_id': 'sub-' + str(position) * 16,
            'claim_id': reference.claim_id, 'number_reference': reference,
        }) for position, reference in enumerate(references)
    )})
    await editor.workspace.awrite_bytes(
        context.scope['threadId'], 'reports/revision-1/trace-index-v1.json',
        encode_trace_index(index), overwrite=True,
    )
    manifest = await register_trace_manifest(editor.workspace, context.scope['threadId'], index, overwrite=True)
    context = context.model_copy(update={'artifact_manifest': manifest})
    state = await editor.state_repository.get(context.workflow_run_id)
    state.payload['reportEditorContexts']['1'] = context.model_dump(mode='json', by_alias=True)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    markdown = next(tmp_path.rglob('report.md')).read_text()
    return editor, context, session, markdown


@pytest.mark.anyio
@pytest.mark.parametrize('equal_values', [False, True])
async def test_editor_api_validates_both_parallel_monthly_references(tmp_path, equal_values):
    editor, context, session, markdown = await _editor_with_both_references(tmp_path, equal_values=equal_values)
    result = await editor.trace_validate(context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert len(result['subjects']) == 2
    assert result['summary'] == {'valid': 2, 'stale': 0, 'unbound': 0}
    assert all(subject['warnings'] == [] for subject in result['subjects'])


@pytest.mark.anyio
async def test_editor_api_retains_true_period_warnings_after_dates_are_swapped(tmp_path):
    editor, context, session, markdown = await _editor_with_both_references(tmp_path)
    markdown = markdown.replace('2025年9月', '2025年11月').replace('10月', '8月')
    result = await editor.trace_validate(context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    assert len(result['subjects']) == 2
    assert all(any('期间' in warning for warning in subject['warnings']) for subject in result['subjects'])
