import pytest

from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalRequest,
    run_standard_supplemental,
)


@pytest.mark.parametrize('operation', ['group_period_series', 'cross_group_summary'])
def test_extended_dimensions_preserve_identity_and_reconcile(operation):
    options = ({'parentPeriodTotals': (30, 20)} if operation == 'group_period_series'
               else {'secondaryDimensionField': 'channel'})
    request = StandardSupplementalRequest(
        operation=operation, datasetId='data', outputName='result',
        measureField='amount', dimensionField='department', periodField='period',
        currentPeriods=('2025-01', '2025-02'), parentTotal=50, **options,
    )
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('data',),
        authorized_fields=('period', 'department', 'channel', 'amount'),
        csv_content=b'period,department,channel,amount\n2025-01,A,X,10\n2025-01,B,X,20\n2025-02,A,Y,20\n',
        request=request,
    )
    rows = payload['findings'][0]['rows']
    assert all(item['passed'] for item in payload['reconciliations'])
    if operation == 'group_period_series':
        assert rows == [['2025-01', 'B', 20, 1, 2 / 3],
                        ['2025-01', 'A', 10, 2, 1 / 3],
                        ['2025-02', 'A', 20, 1, 1]]
    else:
        assert rows == [['A', 'Y', 20, 1, .4], ['B', 'X', 20, 2, .4],
                        ['A', 'X', 10, 3, .2]]


def test_series_requires_independent_period_totals():
    with pytest.raises(ValueError, match='parentPeriodTotals'):
        StandardSupplementalRequest(
            operation='group_period_series', datasetId='data', outputName='result',
            measureField='amount', dimensionField='department', periodField='period',
            currentPeriods=('2025-01',), parentTotal=50,
        )
