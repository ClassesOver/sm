"""标准图回退应保留可修复的结构诊断及精确来源身份。"""

import pytest

from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _chart,
    _visualization_payload,
)
from smart_reporting.reporting.tests.test_standard_chart_contract import monthly, plan_and_inputs
from smart_reporting.reporting.tests.test_standard_chart_presentation import render  # noqa: F401
from smart_reporting.reporting.workflow.runtime.chart_inputs import ChartInputFile
from smart_reporting.reporting.workflow.runtime.phase_models import VisualizationPlanDraft
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_plan_diagnostics,
    standard_visualization_preflight,
)
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
    _validate_visualization_plan_bindings,
)


@pytest.mark.parametrize('foreign_analysis', [False, True])
@pytest.mark.parametrize('subset', [False, True])
def test_binding_file_correction_preserves_exact_table_among_identical_column_sets(foreign_analysis, subset):
    payload = _visualization_payload()
    chart = _chart()
    binding = chart.data_bindings[0].model_copy(update={'data_path': 'findings[2].rows'})
    if subset:
        binding = binding.model_copy(update={'fields': ('value',)})
    analysis = payload['visualizationFacts'][0]
    source = {
        'sourceFile': {'path': 'evidence/supplement.json'},
        'dataDescriptors': [
            {'dataPath': f'findings[{index}].rows', 'fields': list(chart.data_bindings[0].fields)}
            for index in (2, 3)
        ],
    }
    if foreign_analysis:
        payload['visualizationFacts'].append({
            'analysisId': 'analysis_other', 'supplementalEvidenceSources': [source],
        })
    else:
        analysis['supplementalEvidenceSources'] = [source]
    plan = VisualizationPlanDraft(charts=(chart.model_copy(update={'data_bindings': (binding,)}),))

    corrected = _validate_visualization_plan_bindings(plan, payload).charts[0].data_bindings[0]

    assert corrected.fact_path == (binding.fact_path if foreign_analysis else 'evidence/supplement.json')
    assert corrected.data_path == 'findings[2].rows'
    assert corrected.analysis_id == binding.analysis_id


def test_mixed_unit_series_reports_specific_fix_instead_of_generic_template_failure():
    document = {
        'columns': ['period', 'value', 'rank', 'share'],
        'rows': [['一月', 10, 1, 0.4], ['二月', 15, 2, 0.6]],
        'columnMeta': {'value': {'unit': '元'}, 'rank': {'unit': '名'},
                       'share': {'unit': '%', 'isPercent': False}},
    }
    plan, inputs = plan_and_inputs([document], standardValueFields=['value', 'rank', 'share'])
    result = standard_visualization_preflight(plan, inputs)
    assert result.source is None
    assert result.diagnostic['code'] == 'standard_axis_units_incompatible'
    issues = standard_plan_diagnostics(plan, inputs)
    assert issues[0]['sources'][0]['columnMeta'] == document['columnMeta']
    # 仅显式选择金额列即可继续标准路线，不删除来源中的排名和占比。
    repaired, _ = plan_and_inputs([document], standardValueFields=['value'])
    assert standard_visualization_preflight(repaired, inputs).source is not None


@pytest.mark.parametrize('fault,reason', [
    ('duplicate', 'source_labels_duplicate'),
    ('unit', 'source_unit_missing'),
    ('window', 'source_label_sets_differ'),
])
def test_alignment_failure_exposes_specific_reason_and_source_metadata(fault, reason):
    first, second = monthly(), monthly()
    if fault == 'duplicate':
        second['rows'].append(second['rows'][0])
    elif fault == 'unit':
        second.pop('columnMeta')
    else:
        second['rows'][1][0] = '2025-03-01'
    plan, inputs = plan_and_inputs([first, second], standardValueFields=['本期', '同期'],
        standardSources=[{'sourceIndex': index, 'labelField': 'period', 'valueField': 'value',
                          'seriesName': name} for index, name in enumerate(['本期', '同期'])])

    result = standard_visualization_preflight(plan, inputs)

    assert result.source is None
    assert result.diagnostic['code'] == 'standard_source_alignment_failed'
    assert result.diagnostic['details']['reason'] == reason
    assert result.diagnostic['details']['sourceIndex'] == 1


@pytest.mark.parametrize('fault', ['malformed', 'identity'])
def test_diagnostic_metadata_does_not_trust_invalid_or_changed_inputs(fault):
    plan, inputs = plan_and_inputs([monthly()])
    file = ChartInputFile(inputs.files[0].path, b'{' if fault == 'malformed' else inputs.files[0].content)
    entry = {**inputs.entries[0], 'sha256': file.sha256 if fault == 'malformed' else '0' * 64}
    inputs = type(inputs)(files=(file,), entries=(entry,))
    issues = standard_plan_diagnostics(plan, inputs)
    assert issues[0]['sources'] == []


@pytest.mark.parametrize('explicit_bounds', [False, True])
def test_format_only_domain_needs_no_invented_unit_but_bounds_still_require_one(
    render, explicit_bounds,  # noqa: F811
):
    document = monthly()
    document.pop('columnMeta')
    domain = {'min': 0, 'max': 30} if explicit_bounds else {'tickFormat': 'number', 'decimals': 1}
    plan, inputs = plan_and_inputs([document], standardDomains={'left': domain})
    result = standard_visualization_preflight(plan, inputs)
    if explicit_bounds:
        assert result.source is None
        assert result.diagnostic['code'] == 'standard_domain_units_missing'
    else:
        assert result.source is not None
        figure = render(plan, inputs)
        assert figure.axes[0].get_ylabel() == ''
        assert [bar.get_height() for bar in figure.axes[0].containers[0]] == [10, 20]
