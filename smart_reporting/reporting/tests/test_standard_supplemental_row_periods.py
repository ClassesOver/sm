"""逐期补证单元格追溯必须绑定实际行期间，不能冒充整列窗口。"""

import json

import pytest

from smart_reporting.reporting.trace.contracts_v1 import TableDerivationV1, TableOperandV1
from smart_reporting.reporting.trace.table_sources import (
    resolve_source_cell,
    resolve_table_derivation,
    table_derivation_token,
    table_semantics,
)

RID = 'trf-' + '1' * 20


def frozen_table():
    return {
        'name': '逐期比较', 'periodGranularity': 'month',
        'periods': ['2025-02', '2025-03', '2025-01'],
        'scope': {'site': '甲院'}, 'rowPeriodColumn': 'period',
        'columns': ['period', 'group', 'current', 'baseline'],
        'rows': [['2025-02', 'A', 20, 10], ['2025-03', 'A', 40, 20]],
        'columnMeta': {
            'current': {
                'unit': '元', 'periodRoles': ['current'], 'periods': ['2025-02', '2025-03'],
                'periodsByRowPeriod': {'2025-02': ['2025-02'], '2025-03': ['2025-03']},
            },
            'baseline': {
                'unit': '元', 'periodRoles': ['prior'], 'periods': ['2025-01', '2025-02'],
                'periodsByRowPeriod': {'2025-02': ['2025-01'], '2025-03': ['2025-02']},
            },
        },
    }


def operand(row, column, coefficient='1'):
    return TableOperandV1(fileResourceId=RID, tablePointer='/findings/0',
                          rowIndex=row, columnIndex=column, coefficient=coefficient)


def sources(table):
    return {RID: json.dumps({'findings': [table]}, ensure_ascii=False).encode()}


@pytest.mark.parametrize('row,expected,value', [(0, ('2025-01',), 10), (1, ('2025-02',), 20)])
def test_source_cell_baseline_uses_only_its_row_reference_period(row, expected, value):
    view = resolve_source_cell(operand(row, 3), sources(frozen_table()))
    assert view['value'] == value
    assert view['periods'] == expected
    assert view['period_roles'] == {'prior': expected}
    assert view['scope'] == {'site': '甲院'}


@pytest.mark.parametrize('row,current,prior,value', [
    (0, '2025-02', '2025-01', 10), (1, '2025-03', '2025-02', 20),
])
def test_linear_difference_combines_actual_row_current_and_reference_periods(row, current, prior, value):
    registered = sources(frozen_table())
    derivation = TableDerivationV1(unit='元', operands=(operand(row, 2), operand(row, 3, '-1')))
    token = table_derivation_token(derivation, registered)
    view = resolve_table_derivation(token, derivation, registered)
    assert view['value'] == value
    assert view['periods'] == (current, prior)
    assert view['period_roles'] == {'current': (current,), 'prior': (prior,)}


def test_column_catalog_without_row_keeps_full_window_semantics():
    table = frozen_table()
    assert table_semantics({}, table, 'baseline')['periods'] == ('2025-01', '2025-02')


def test_legacy_metadata_without_row_binding_preserves_existing_semantics():
    table = frozen_table()
    table.pop('rowPeriodColumn')
    for meta in table['columnMeta'].values():
        meta.pop('periodsByRowPeriod')
    view = resolve_source_cell(operand(0, 3), sources(table))
    assert view['periods'] == ('2025-01', '2025-02')
    assert view['period_roles'] == {'prior': ('2025-01', '2025-02')}


def test_row_period_alias_is_an_explicit_mapping_key_not_a_guessed_date():
    table = frozen_table()
    table['rows'][0][0] = '2025/02'
    table['columnMeta']['baseline']['periodsByRowPeriod']['2025/02'] = ['2025-01']
    view = resolve_source_cell(operand(0, 3), sources(table))
    assert view['periods'] == ('2025-01',)


@pytest.mark.parametrize('invalid_binding', [
    'missing_column_binding', 'unknown_column', 'duplicate_column', 'nontext_row_period',
    'missing_period_key', 'invalid_periods', 'invalid_mapping', 'empty_periods',
])
def test_invalid_row_binding_never_falls_back_to_full_window(invalid_binding):
    table = frozen_table()
    if invalid_binding == 'missing_column_binding':
        table.pop('rowPeriodColumn')
    elif invalid_binding == 'unknown_column':
        table['rowPeriodColumn'] = 'unknown'
    elif invalid_binding == 'duplicate_column':
        table['columns'][1] = 'period'
    elif invalid_binding == 'nontext_row_period':
        table['rows'][0][0] = 202502
    elif invalid_binding == 'missing_period_key':
        table['columnMeta']['baseline']['periodsByRowPeriod'].pop('2025-02')
    elif invalid_binding == 'invalid_periods':
        table['columnMeta']['baseline']['periodsByRowPeriod']['2025-02'] = ['not-a-period']
    elif invalid_binding == 'invalid_mapping':
        table['columnMeta']['baseline']['periodsByRowPeriod'] = ['2025-01']
    else:
        table['columnMeta']['baseline']['periodsByRowPeriod']['2025-02'] = []
    view = table_semantics({}, table, 'baseline', row_index=0)
    assert view == {'periods': (), 'period_roles': {}, 'scope': {'site': '甲院'}}


@pytest.mark.parametrize('row_index', [-1, True, 2])
def test_invalid_row_index_cannot_read_another_row_or_full_window(row_index):
    assert table_semantics({}, frozen_table(), 'baseline', row_index=row_index)['periods'] == ()


@pytest.mark.parametrize('method,reference', [
    ('previous_period', ('2025-01',)), ('mean', ('2025-01', '2025-02')),
    ('median', ('2025-01', '2025-02')),
])
def test_production_comparison_cells_replay_only_their_actual_periods(method, reference):
    from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
        StandardSupplementalRequest,
        run_standard_supplemental,
    )

    request = StandardSupplementalRequest(
        operation='group_period_comparison', datasetId='data', outputName='result',
        measureField='amount', measureUnit='元', dimensionField='group', periodField='period',
        periodGranularity='month', currentPeriods=('2025-02', '2025-03'), parentTotal=60,
        parentPeriodTotals=(20, 40), baselineMethod=method,
        baselinePeriods=('2025-01', '2025-02'), baselinePeriodTotals=(10, 20),
    )
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('data',),
        authorized_fields=('period', 'group', 'amount'),
        csv_content=b'period,group,amount\n2025-01,A,10\n2025-02,A,20\n2025-03,A,40\n',
        request=request,
    )
    table = payload['findings'][0]
    for name, expected in (('current', ('2025-02',)), ('baseline', reference),
                           ('baselineTotal', reference),
                           ('change', tuple(dict.fromkeys(('2025-02', *reference))))):
        view = resolve_source_cell(operand(0, table['columns'].index(name)), sources(table))
        assert view['periods'] == expected


@pytest.mark.parametrize('operation,column,expected', [
    ('group_period_series', 'value', ('2025-02',)),
    ('group_period_series', 'previous', ('2025-01',)),
    ('group_period_series', 'change', ('2025-02', '2025-01')),
    ('cross_group_summary', 'value', ('2025-02',)),
    ('cross_group_summary', 'primaryTotal', ('2025-02',)),
])
def test_production_series_and_period_cross_cells_do_not_claim_all_periods(operation, column, expected):
    from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
        StandardSupplementalRequest,
        run_standard_supplemental,
    )

    options = ({'includePeriodChange': True} if operation == 'group_period_series' else
               {'secondaryDimensionField': 'kind', 'includeMarginalShares': True, 'groupByPeriod': True})
    request = StandardSupplementalRequest(
        operation=operation, datasetId='data', outputName='result', measureField='amount',
        measureUnit='元', dimensionField='group', periodField='period', periodGranularity='month',
        currentPeriods=('2025-01', '2025-02'), parentTotal=30, parentPeriodTotals=(10, 20), **options,
    )
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('data',),
        authorized_fields=('period', 'group', 'kind', 'amount'),
        csv_content=b'period,group,kind,amount\n2025-01,A,X,10\n2025-02,A,X,20\n', request=request,
    )
    table = payload['findings'][0]
    view = resolve_source_cell(operand(1, table['columns'].index(column)), sources(table))
    assert view['periods'] == expected
