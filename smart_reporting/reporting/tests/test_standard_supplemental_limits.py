"""长期间与批量补证不应因正确对账项数量而被误判为不支持。"""

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _standard_analysis_state,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    empty_supplemental_evidence_error,
    validate_supplemental_evidence,
)
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalRequest,
    compact_standard_reconciliations,
    run_standard_supplemental,
    standard_computation_candidates,
)


def test_previous_period_candidate_does_not_request_unrelated_history():
    state = _standard_analysis_state()
    periods = tuple((date(2025, 1, 1) + timedelta(days=index)).isoformat() for index in range(60))
    parent = state.facts.metrics[0]
    parent.period_granularity = 'day'
    parent.period_values = tuple(SimpleNamespace(period=period, value=1) for period in periods)
    candidates = standard_computation_candidates(state.facts, state.instruction['datasets'], periods[31:59])
    comparison = next(item['standardComputation'] for item in candidates
                      if item['standardComputation']['operation'] == 'group_period_comparison')
    assert comparison['baselinePeriods'] == list(periods[30:58])


@pytest.mark.parametrize('mismatched_baseline', [False, True])
def test_long_daily_comparison_preserves_all_checks_within_evidence_limit(mismatched_baseline):
    periods = tuple((date(2025, 1, 1) + timedelta(days=index)).isoformat() for index in range(60))
    csv = 'period,group,amount\n' + ''.join(f'{period},A,1\n' for period in periods)
    request = StandardSupplementalRequest(
        operation='group_period_comparison', datasetId='data', outputName='daily',
        measureField='amount', dimensionField='group', periodField='period', periodGranularity='day',
        currentPeriods=periods, parentTotal=60, parentPeriodTotals=(1,) * 60,
        baselineMethod='mean', baselinePeriods=periods,
        baselinePeriodTotals=((9 if mismatched_baseline else 1), *((1,) * 59)),
    )
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('data',), authorized_fields=('period', 'group', 'amount'),
        csv_content=csv.encode(), request=request,
    )
    evidence = validate_supplemental_evidence(
        json.dumps(payload).encode(), {'analysisId': 'analysis_001', 'datasetIds': ['data']},
    )

    def leaves(checks):
        return [leaf for check in checks for leaf in (leaves(check['checks']) if 'checks' in check else [check])]

    original = leaves(evidence.reconciliations)
    assert len(evidence.reconciliations) <= 100
    assert len(original) == 181
    assert len({check['name'] for check in original}) == 181
    assert all(check['passed'] for check in evidence.reconciliations) is (not mismatched_baseline)
    check = next(item for item in original if item['name'] == 'daily_baseline_2025-01-01_total')
    assert check == {'name': 'daily_baseline_2025-01-01_total', 'left': 1, 'right': 9 if mismatched_baseline else 1,
                     'passed': not mismatched_baseline}
    if mismatched_baseline:
        assert evidence.warnings


@pytest.mark.parametrize('zero_side', [False, True])
def test_compacted_checks_preserve_empty_table_repair_and_soft_warning_boundary(zero_side):
    checks = [{'name': 'empty_part', 'passed': False, 'left': 0 if zero_side else 2, 'right': 3}]
    checks += [{'name': f'populated_{index}', 'passed': True, 'left': 1, 'right': 1} for index in range(100)]
    payload = {
        'findings': [{'name': 'populated', 'columns': ['group', 'value'], 'rows': [['A', 1]]},
                     {'name': 'empty', 'columns': ['group', 'value'], 'rows': []}],
        'reconciliations': compact_standard_reconciliations(checks, 'batch'),
        'warnings': ['对账差异'],
    }
    evidence = validate_supplemental_evidence(
        json.dumps(payload).encode(), {'analysisId': 'analysis_001', 'datasetIds': ['data']},
    )
    error = empty_supplemental_evidence_error(evidence)
    if zero_side:
        assert error is not None
        assert error.code == 'report_analysis_evidence_empty'
        assert error.details['zeroSidedReconciliations'] == ['empty_part']
    else:
        assert error is None
