from copy import deepcopy

import pytest

from scripts.planner_matrix_support import validate_plan
from scripts.test_planner_plan_matrix import coverage_issues, load_candidate_instructions


def fixture():
    return ({'analyses': [{'requirementIds': ['r'], 'periodRoles': ['current', 'yoy'],
                           'seriesGranularity': 'month'}],
             'requirements': [{'requirementId': 'r', 'sourceId': 's',
                 'tables': [{'table': 'db.t', 'measureColumns': ['amount']}],
                 'dimensionColumns': ['area', 'data_date'], 'comparisonRoles': ['yoy']}]},
            {'required': [{'ref': 's.db.t.amount', 'dimensions': ['area', 'data_date'],
                           'roles': ['current', 'yoy'], 'monthly': True}]})


def test_coverage_accepts_linked_metric_with_dimensions_and_roles():
    plan, case = fixture()
    assert coverage_issues(plan, case) == []


def test_orphan_requirement_does_not_count_as_task_coverage():
    plan, case = fixture()
    plan['analyses'][0]['requirementIds'] = ['other']
    assert coverage_issues(plan, case)


def test_metric_presence_does_not_hide_missing_dimensions_or_yoy():
    plan, case = fixture()
    for key, value in [('periodRoles', ['current']), ('seriesGranularity', None)]:
        changed = deepcopy(plan)
        changed['analyses'][0][key] = value
        assert coverage_issues(changed, case)
    plan['requirements'][0]['dimensionColumns'] = ['area']
    assert coverage_issues(plan, case)


def test_current_only_requirement_allows_null_comparison_roles():
    plan, case = fixture()
    plan['requirements'][0]['comparisonRoles'] = None
    case['required'][0]['roles'] = ['current']
    assert coverage_issues(plan, case) == []


def test_contract_accepts_null_comparison_roles():
    plan, _ = fixture()
    plan['requirements'][0].update(grainColumns=['area', 'data_date'], relations=[], comparisonRoles=None)
    plan['requirements'][0]['tables'][0].update(periodColumn='data_date', periodGranularity='date')
    plan['analyses'][0].update(code='a', analysisName='收入', description='按院区汇总收入',
        managementQuestion='各院区收入如何？', primaryMetricFamily='收入', domain='income',
        metricPurposes=['收入分析'])
    source = {'domains': ['income'], 'periodWindows': {'windows': [{'role': 'current'}, {'role': 'yoy'}]},
        'analysisContext': {'profile': {'metrics': [{'fieldRef': 's.db.t.amount', 'purpose': '收入分析'}]}},
        'schemas': [{'tables': [{'sourceId': 's', 'table': 'db.t', 'periodColumn': 'data_date',
            'periodGranularity': 'date', 'columns': [{'name': n} for n in ['area', 'data_date', 'amount']]}],
            'measureSemantics': [{'fieldRef': 's.db.t.amount'}]}]}
    assert validate_plan(plan, source)['valid']


def test_cumulative_yoy_and_current_monthly_can_cover_separate_tasks():
    plan, case = fixture()
    plan['analyses'][0]['seriesGranularity'] = None
    plan['analyses'].append({'requirementIds': ['r'], 'periodRoles': ['current'],
                             'seriesGranularity': 'month'})
    case['required'][0]['monthly'] = False
    case['required'].append({**case['required'][0], 'roles': ['current'], 'monthly': True})
    assert coverage_issues(plan, case) == []


@pytest.mark.parametrize('content', ['{}', '[]', '[1]', '[""]'])
def test_candidate_instructions_reject_invalid_lists(tmp_path, content):
    path = tmp_path / 'candidate.json'
    path.write_text(content)
    with pytest.raises(ValueError):
        load_candidate_instructions(path)


def test_candidate_instructions_load_without_production_changes(tmp_path):
    path = tmp_path / 'candidate.json'
    path.write_text('["候选规则"]')
    assert load_candidate_instructions(path) == ['候选规则']
