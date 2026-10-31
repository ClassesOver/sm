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


@pytest.mark.parametrize('name,section', [
    ('render_family_chart', 'FAMILY_SCRIPT'),
    ('render_statistical_chart', 'STATISTICS_SCRIPT'),
    ('read_summary_box_stats', 'SUMMARY_SCRIPT'),
    ('render_dual_stack', 'DUAL_STACK_SCRIPT'),
    ('render_broken_chart', 'BREAK_SCRIPT'),
    ('layout_standard_break', 'BREAK_SCRIPT'),
    ('render_horizontal_broken_chart', 'HORIZONTAL_BREAK_SCRIPT'),
    ('layout_horizontal_standard_break', 'HORIZONTAL_BREAK_SCRIPT'),
    ('apply_standard_domains', 'DOMAIN_SCRIPT'),
])
def test_static_branches_call_only_helpers_from_their_conditional_section(name, section):
    """模板分支固定存在、按运行时条件选择；被调用函数只能定义在同条件附加的辅助段中。"""
    sections = {key: getattr(standard_visualization, key) for key in (
        'FAMILY_SCRIPT', 'STATISTICS_SCRIPT', 'SUMMARY_SCRIPT', 'DUAL_STACK_SCRIPT', 'BREAK_SCRIPT',
        'HORIZONTAL_BREAK_SCRIPT', 'DOMAIN_SCRIPT', '_LAYOUT', 'ENCODING_SCRIPT', '_ADVANCED',
        'PRESENTATION_SCRIPT', '_BODY')}
    assert [key for key, text in sections.items() if f'def {name}(' in text] == [section]
    assert any(name in text for key, text in sections.items() if key != section)


def test_compiled_configs_remain_plain_tuples_in_script():
    plan, document = complex_fixture('bar')
    source = standard_visualization_preflight(plan, materialization(document)).source
    assert source.startswith('CONFIGS = [(') and 'StandardChartConfig' not in source
