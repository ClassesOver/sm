"""Whole frozen breakdowns keep partition identity, units and complete pages."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from smart_reporting.reporting.tests.test_standard_chart_presentation import render  # noqa: F401
from smart_reporting.reporting.workflow.runtime.chart_data_descriptors import breakdown_descriptors
from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputError,
    _table_for_binding,
    materialize_chart_inputs,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    ChartDataBinding,
    ChartDraft,
    VisualizationPlanDraft,
)
from smart_reporting.reporting.workflow.runtime.standard_chart_pagination import (
    expand_standard_pagination,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)

PARENT = 'fact-' + 'a' * 16
FULL_FIELDS = ['parentFactId', 'breakdownField', 'breakdownLabel', 'breakdownValue', 'displayName', 'total', 'unit']


def frozen_document(values=(-125.5, 270.25, 0), *, unit='万元', percent=None):
    rows = []
    for number, value in enumerate(values):
        row = {
            'factId': f'fact-{number + 1:016x}', 'parentFactId': PARENT,
            'breakdownField': 'department', 'breakdownLabel': '科室',
            'breakdownValue': f'科室{number + 1}', 'displayName': f'冻结收入（科室{number + 1}）',
            'total': value, 'unit': unit,
        }
        if percent is not None:
            row['isPercent'] = percent
        rows.append(row)
    return {'metrics': [{'factId': PARENT}], 'breakdowns': rows}


def project(document, fields=('breakdownValue', 'total')):
    binding = ChartDataBinding(analysisId='analysis_001', factPath='facts.json', dataPath='breakdowns',
                               fields=fields, role='完整科室分组')
    original = deepcopy(document)
    try:
        return _table_for_binding(document, binding)
    finally:
        assert document == original


@pytest.mark.parametrize('fields', [('breakdownValue', 'total'), tuple(FULL_FIELDS)])
@pytest.mark.parametrize('unit', ['元', '万元', '%', '件', '元/人', ' 万元 '])
def test_whole_partition_inherits_exact_common_unit_without_changing_rows(fields, unit):
    document = frozen_document(unit=unit)
    columns, rows, metadata = project(document, fields)
    assert columns == list(fields)
    assert rows == [[row[field] for field in fields] for row in document['breakdowns']]
    assert metadata == {'total': {'unit': unit}}


@pytest.mark.parametrize('percent', [True, False])
def test_whole_partition_carries_only_the_explicit_common_percent_scale(percent):
    _, rows, metadata = project(frozen_document(unit='%', percent=percent))
    assert rows == [['科室1', -125.5], ['科室2', 270.25], ['科室3', 0]]
    assert metadata == {'total': {'unit': '%', 'isPercent': percent}}


@pytest.mark.parametrize('unit', [None, '', '  ', 123])
def test_unknown_units_do_not_invent_total_metadata(unit):
    columns, rows, metadata = project(frozen_document(unit=unit))
    assert columns == ['breakdownValue', 'total']
    assert rows == [['科室1', -125.5], ['科室2', 270.25], ['科室3', 0]]
    assert metadata is None


def test_all_unknown_unit_forms_still_do_not_make_up_a_unit():
    document = frozen_document()
    for row, unit in zip(document['breakdowns'], [None, '', '  '], strict=True):
        row['unit'] = unit
    assert project(document)[2] is None


@pytest.mark.parametrize('fault', ['different_unit', 'missing_unit', 'unknown_unit', 'percent_scale',
                                 'parent', 'dimension', 'missing_parent', 'missing_dimension'])
def test_ambiguous_whole_partition_is_rejected_without_changing_data(fault):
    document = frozen_document(unit='元', percent=True)
    second = document['breakdowns'][1]
    if fault == 'different_unit':
        second['unit'] = '万元'
    elif fault == 'missing_unit':
        second.pop('unit')
    elif fault == 'unknown_unit':
        second['unit'] = None
    elif fault == 'percent_scale':
        second['isPercent'] = False
    elif fault == 'parent':
        second['parentFactId'] = 'fact-' + 'b' * 16
    elif fault == 'dimension':
        second['breakdownField'] = 'campus'
    elif fault == 'missing_parent':
        for row in document['breakdowns']:
            row.pop('parentFactId')
    else:
        for row in document['breakdowns']:
            row.pop('breakdownField')
    with pytest.raises(ChartInputError):
        project(document)


def test_unselected_total_does_not_gain_metadata_or_require_a_measure_partition():
    document = frozen_document()
    document['breakdowns'][1]['unit'] = '元'
    document['breakdowns'][1]['parentFactId'] = 'fact-' + 'b' * 16
    assert project(document, fields=['breakdownValue']) == (
        ['breakdownValue'], [['科室1'], ['科室2'], ['科室3']], None,
    )


def prepared(document, *, form='barh', display_unit=None, page_size=None):
    descriptor = next(item for item in breakdown_descriptors(document) if item['dataPath'] == 'breakdowns')
    chart = ChartDraft(chartId='chart', sourcePath='chart.png', title='冻结科室分组', altText='同口径全部科室',
        citationIds=['citation'], metricCodes=['revenue'], currentPeriod='2026-10', sourceDatasetId='dataset',
        aggregationGrain='department', visualForm=form, standardLabelField='breakdownValue',
        standardValueFields=['total'], standardDisplayUnit=display_unit,
        standardPagination={'pageSize': page_size} if page_size is not None else None,
        dataBindings=[{'analysisId': 'analysis_001', 'factPath': 'facts.json', 'dataPath': 'breakdowns',
                       'fields': descriptor['fields'], 'role': '完整科室分组'}])
    plan = VisualizationPlanDraft(charts=(chart,))
    content = json.dumps(document, ensure_ascii=False).encode()
    facts = [{'analysisId': 'analysis_001', 'factFile': {'path': 'facts.json', 'size': len(content),
             'sha256': hashlib.sha256(content).hexdigest()}, 'dataDescriptors': [descriptor]}]
    documents = {'facts.json': document}
    inputs = materialize_chart_inputs(plan, facts, documents, output_root='.')
    assert not inputs.fallback_chart_ids
    if page_size is not None:
        plan = expand_standard_pagination(plan, inputs)
        inputs = materialize_chart_inputs(plan, facts, documents, output_root='.')
    return plan, inputs


@pytest.mark.parametrize('form,unit,display_unit,percent,values,expected', [
    ('barh', '万元', None, None, [-125.5, 270.25, 0], [-125.5, 270.25, 0]),
    ('bar', '元', '亿元', None, [-125000000, 500000000, 0], [-1.25, 5, 0]),
    ('barh', '%', None, True, [-12.5, 27.025, 0], [-12.5, 27.025, 0]),
    ('bar', '%', None, False, [-.125, .27025, 0], [-12.5, 27.025, 0]),
])
def test_real_standard_axes_use_breakdown_labels_units_and_frozen_geometry(
    render, form, unit, display_unit, percent, values, expected,  # noqa: F811
):
    document = frozen_document(values, unit=unit, percent=percent)
    original = deepcopy(document)
    plan, inputs = prepared(document, form=form, display_unit=display_unit)
    assert standard_visualization_preflight(plan, inputs).source
    figure = render(plan, inputs)
    axes = figure.axes[0]
    labels = axes.get_yticklabels() if form == 'barh' else axes.get_xticklabels()
    assert [label.get_text() for label in labels] == [row['breakdownValue'] for row in document['breakdowns']]
    assert (axes.get_xlabel() if form == 'barh' else axes.get_ylabel()) == (display_unit or unit)
    actual = [bar.get_width() if form == 'barh' else bar.get_height() for bar in axes.containers[0]]
    assert actual == pytest.approx(expected)
    assert document == original


@pytest.mark.parametrize('form,count,page_size,unit,display_unit,percent,factor', [
    ('barh', 5, 3, '元', '万元', None, .0001),
    ('bar', 7, 3, '万元', '亿元', None, .0001),
    ('barh', 7, 3, '%', None, False, 100),
])
def test_whole_partition_paginates_complete_labels_and_values_with_shared_unit_and_domain(
    render, monkeypatch, form, count, page_size, unit, display_unit, percent, factor,  # noqa: F811
):
    from matplotlib.figure import Figure

    values = [-125.5 if index == 0 else (index + 1) * 250.25 for index in range(count)]
    document = frozen_document(values, unit=unit, percent=percent)
    original = deepcopy(document)
    plan, inputs = prepared(document, form=form, display_unit=display_unit, page_size=page_size)
    expected_count = (count + page_size - 1) // page_size
    assert len(plan.charts) == expected_count
    assert standard_visualization_preflight(plan, inputs).source
    saved = []
    savefig = Figure.savefig

    def capture(figure, *args, **kwargs):
        saved.append(figure)
        return savefig(figure, *args, **kwargs)

    monkeypatch.setattr(Figure, 'savefig', capture)
    render(plan, inputs)
    assert len(saved) == expected_count
    all_labels, all_values, domains = [], [], []
    for number, (page, figure) in enumerate(zip(plan.charts, saved, strict=True)):
        axes = figure.axes[0]
        labels = axes.get_yticklabels() if form == 'barh' else axes.get_xticklabels()
        actual_labels = [label.get_text() for label in labels]
        selected = document['breakdowns'][number * page_size:(number + 1) * page_size]
        assert actual_labels == [row['breakdownValue'] for row in selected]
        assert (axes.get_xlabel() if form == 'barh' else axes.get_ylabel()) == (display_unit or unit)
        widths = [bar.get_width() if form == 'barh' else bar.get_height() for bar in axes.containers[0]]
        assert widths == pytest.approx([row['total'] * factor for row in selected])
        all_labels.extend(actual_labels)
        all_values.extend(widths)
        domains.append(axes.get_xlim() if form == 'barh' else axes.get_ylim())
        assert Path(page.source_path).read_bytes().startswith(b'\x89PNG')
    assert all_labels == [row['breakdownValue'] for row in document['breakdowns']]
    assert all_values == pytest.approx([value * factor for value in values])
    assert all(domain == domains[0] for domain in domains)
    for source in inputs.files:
        payload = json.loads(source.content)
        assert payload['rows'] == [[row[field] for field in FULL_FIELDS] for row in document['breakdowns']]
    assert document == original
