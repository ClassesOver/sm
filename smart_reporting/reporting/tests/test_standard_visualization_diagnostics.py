import pytest

from smart_reporting.reporting.tests.test_standard_visualization import (
    complex_fixture,
    materialization,
)
from smart_reporting.reporting.workflow.runtime import standard_visualization
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def _code(plan, document):
    result = standard_visualization_preflight(plan, materialization(document))
    assert result.source is None
    return result.diagnostic['code']


def test_incomplete_long_table_reports_specific_reason():
    plan, document = complex_fixture('bar', long=True)
    document['rows'].pop()
    assert _code(plan, document) == 'standard_long_table_incomplete'


@pytest.mark.parametrize('selected,code', [
    (('actual',), 'standard_summary_bars_selection_invalid'),
    (('actual', 'ratio'), 'standard_summary_bars_units_incompatible'),
])
def test_summary_bars_rejections_name_the_failed_rule(selected, code):
    plan, _ = complex_fixture('summary-bars')
    chart = plan.charts[0]
    chart.standard_value_fields = selected
    document = {'columns': ['actual', 'budget', 'ratio'], 'rows': [[10, 20, 0.5]],
                'columnMeta': {'actual': {'unit': '元'}, 'budget': {'unit': '元'}, 'ratio': {'unit': '%'}}}
    assert _code(plan, document) == code


def test_unreconciled_independent_total_reports_specific_reason():
    plan, _ = complex_fixture('stacked-total')
    plan.charts[0].standard_total_field = 'total'
    document = {'columns': ['period', 'a', 'b', 'total'],
                'rows': [['2025-01', 1, 2, 3], ['2025-02', 1, 2, 4]],
                'columnMeta': {name: {'unit': '元'} for name in ('a', 'b', 'total')}}
    assert _code(plan, document) == 'standard_total_reconciliation_failed'


def test_template_anchor_drift_falls_back_with_diagnostic(monkeypatch):
    plan, document = complex_fixture('bar')
    assert standard_visualization_preflight(plan, materialization(document)).source
    monkeypatch.setattr(standard_visualization, '_BODY', standard_visualization._BODY.replace(
        '__STATISTICAL_DISPATCH__', ''))
    assert _code(plan, document) == 'standard_template_anchor_drift'


def test_compiled_configs_remain_plain_tuples_in_script():
    plan, document = complex_fixture('bar')
    source = standard_visualization_preflight(plan, materialization(document)).source
    assert source.startswith('CONFIGS = [(') and 'StandardChartConfig' not in source
