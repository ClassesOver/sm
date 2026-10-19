"""并列数值引用各自归属当前主语，同时保留省略的范围与期间。"""

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

DEPARTMENT = '{{value:fact-aaaaaaaaaaaaaaaa:total:元}}'
HOSPITAL = '{{value:fact-bbbbbbbbbbbbbbbb:total:元}}'


def _income_sources():
    bundle = json.loads(contents()[0])
    bundle['metrics'][0]['scope'] = {'科室': '普通外科'}
    return [json.dumps(bundle)]


def _reference_warnings(statement, stage):
    sources = _income_sources()
    if stage == 'generation':
        result = review_content_result(statement, sources)
        issues = {issue['token']: issue['warnings'] for issue in result.reference_issues}
        # 这里的场景只涉及引用归属，不能让结构化反馈遗漏同一范围告警。
        assert set(result.warnings) == {warning for warnings in issues.values() for warning in warnings}
        return {token: issues.get(token, []) for token in (DEPARTMENT, HOSPITAL)}

    markdown, references, notices = render_bound_numbers(statement, sources, key='context-boundary')
    assert len(references) == 2 and not notices
    markdown = anchor_bound_numbers(markdown, references)
    warnings = {}
    for reference in references:
        selected = resolve_number_reference(reference.token, sources)
        assert selected is not None
        result = claim_status(
            markdown, reference.claim_id, selected['value'],
            expected_unit=selected['unit'], expected_periods=selected['periods'],
            expected_period_roles=selected['period_roles'], expected_scope=selected['scope'],
            expected_reference=selected,
        )
        assert result['status'] == 'valid'
        warnings[reference.token] = result['warnings']
    return warnings


@pytest.mark.parametrize('stage', ['generation', 'editor'])
@pytest.mark.parametrize('separator', ['及', '和', '、', '，'])
def test_parallel_hospital_reference_does_not_borrow_previous_department(stage, separator):
    warnings = _reference_warnings(f'普通外科收入{DEPARTMENT}{separator}全院收入{HOSPITAL}。', stage)
    assert warnings == {DEPARTMENT: [], HOSPITAL: []}


@pytest.mark.parametrize('stage', ['generation', 'editor'])
def test_new_subject_retains_the_shared_cumulative_period(stage):
    warnings = _reference_warnings(f'2025年1—2月普通外科收入{DEPARTMENT}及全院收入{HOSPITAL}。', stage)
    assert warnings == {DEPARTMENT: [], HOSPITAL: []}


@pytest.mark.parametrize('stage', ['generation', 'editor'])
def test_reference_without_a_new_subject_retains_the_existing_department(stage):
    warnings = _reference_warnings(f'普通外科收入{DEPARTMENT}及收入{HOSPITAL}。', stage)
    assert warnings[DEPARTMENT] == []
    assert any('业务范围' in warning for warning in warnings[HOSPITAL])
