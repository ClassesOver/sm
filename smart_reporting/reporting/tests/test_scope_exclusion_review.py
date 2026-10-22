"""Explicit scope exclusions cannot be accepted merely because a name occurs."""

import json

import pytest

from smart_reporting.reporting.tests.test_semantic_bindings import contents
from smart_reporting.reporting.trace.content_review import review_content_result
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    render_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import claim_status

FIRST = '{{value:fact-aaaaaaaaaaaaaaaa:total:元}}'
SECOND = '{{value:fact-bbbbbbbbbbbbbbbb:total:元}}'


def _sources():
    bundle = json.loads(contents()[0])
    for metric in bundle['metrics']:
        metric['scope'] = {'院区': '北院'}
    return [json.dumps(bundle)]


def _warnings(statement, stage):
    sources = _sources()
    if stage == 'generation':
        result = review_content_result(statement, sources)
        return {issue['token']: issue['warnings'] for issue in result.reference_issues}
    markdown, references, _ = render_bound_numbers(statement, sources, key='scope-exclusion')
    markdown = anchor_bound_numbers(markdown, references)
    warnings = {}
    for reference in references:
        selected = resolve_number_reference(reference.token, sources)
        result = claim_status(
            markdown, reference.claim_id, selected['value'],
            expected_unit=selected['unit'], expected_scope=selected['scope'], expected_reference=selected,
        )
        assert result['status'] == 'valid'
        warnings[reference.token] = result['warnings']
    return warnings


@pytest.mark.parametrize('stage', ['generation', 'editor'])
@pytest.mark.parametrize('statement', [
    '非北院收入{value}。', '不含北院的收入{value}。', '剔除北院后的收入{value}。',
    '北院以外收入{value}。', '北院之外收入{value}。',
    '收入{value}（不含北院）。', '收入{value}（北院除外）。',
    '不包括**北院**的收入{value}。',
])
def test_explicit_scope_exclusion_is_not_affirmative_scope(statement, stage):
    warnings = _warnings(statement.format(value=FIRST), stage)
    assert any('登记范围' in warning for warning in warnings.get(FIRST, []))


@pytest.mark.parametrize('stage', ['generation', 'editor'])
@pytest.mark.parametrize('statement', [
    '北院收入{value}。', '北院收入未增长，为{value}。',
    '北院收入{value}（不含其他院区）。', '北院收入{value}（非预算口径）。',
    '未排除北院收入{value}。', '无法排除北院收入{value}。',
    '并非不含北院的收入{value}。', '不含北院以外的收入{value}。',
])
def test_unrelated_negation_does_not_exclude_the_registered_scope(statement, stage):
    warnings = _warnings(statement.format(value=FIRST), stage)
    assert not any('登记范围' in warning for warning in warnings.get(FIRST, []))


@pytest.mark.parametrize('stage', ['generation', 'editor'])
def test_parallel_reference_does_not_borrow_a_previous_exclusion(stage):
    warnings = _warnings(f'不含北院收入{FIRST}及北院收入{SECOND}。', stage)
    assert any('登记范围' in warning for warning in warnings.get(FIRST, []))
    assert not any('登记范围' in warning for warning in warnings.get(SECOND, []))


def test_legacy_numeric_binding_preserves_scope_exclusion_warning():
    result = claim_status('非北院收入30元[[claim:scope]]。', 'scope', 30,
                          expected_unit='元', expected_scope={'院区': '北院'})
    assert result['status'] == 'valid'
    assert any('登记范围' in warning for warning in result['warnings'])
