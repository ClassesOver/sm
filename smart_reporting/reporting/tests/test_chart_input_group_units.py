"""Registered grouped/period facts retain parent units through standard plotting."""

from copy import deepcopy

import pytest

from smart_reporting.reporting.tests.test_standard_chart_presentation import (  # noqa: F401
    build,
    render,
)
from smart_reporting.reporting.workflow.runtime.chart_inputs import _table_for_binding
from smart_reporting.reporting.workflow.runtime.phase_models import ChartDataBinding
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)

ARRAYS = ('periodValues', 'topGroups', 'bottomGroups', 'groupPopulation')


def bound_table(collection, array, *, unit='万元', is_percent=False, include_value=True):
    label = 'period' if array == 'periodValues' else 'group'
    metric = {'unit': unit, 'isPercent': is_percent, array: [
        {label: '甲', 'value': -125.5}, {label: '乙', 'value': 270.25},
    ]}
    document = {collection: [metric]}
    binding = ChartDataBinding(
        analysisId='analysis_001', factPath='facts.json',
        dataPath=f'{collection}[0].{array}',
        fields=[label, 'value'] if include_value else [label], role='main',
    )
    original = deepcopy(document)
    table = _table_for_binding(document, binding)
    assert document == original
    return table


@pytest.mark.parametrize('collection', ['metrics', 'breakdowns'])
@pytest.mark.parametrize('array', ARRAYS)
@pytest.mark.parametrize('unit,is_percent', [('万元', False), ('%', True), ('%', False)])
def test_group_and_period_projection_preserves_exact_units_scale_and_signed_values(
    collection, array, unit, is_percent,
):
    columns, rows, metadata = bound_table(collection, array, unit=unit, is_percent=is_percent)
    assert columns == ['period' if array == 'periodValues' else 'group', 'value']
    assert rows == [['甲', -125.5], ['乙', 270.25]]
    assert metadata == {'value': {'unit': unit, 'isPercent': is_percent}}


@pytest.mark.parametrize('collection', ['metrics', 'breakdowns'])
@pytest.mark.parametrize('unit', [None, '', '  ', 123])
def test_unavailable_parent_unit_does_not_invent_unit_or_percent_metadata(collection, unit):
    _, rows, metadata = bound_table(collection, 'groupPopulation', unit=unit, is_percent=True)
    assert rows == [['甲', -125.5], ['乙', 270.25]]
    assert metadata is None


@pytest.mark.parametrize('collection', ['metrics', 'breakdowns', 'unregisteredRows'])
def test_only_selected_measure_on_known_frozen_parent_inherits_unit(collection):
    _, _, metadata = bound_table(collection, 'topGroups', include_value=False)
    assert metadata is None
    if collection == 'unregisteredRows':
        assert bound_table(collection, 'topGroups')[2] is None


@pytest.mark.parametrize('collection,array,form,unit', [
    ('breakdowns', 'periodValues', 'line', '万元'),
    ('metrics', 'topGroups', 'barh', '元'),
    ('breakdowns', 'bottomGroups', 'bar', '万元'),
    ('metrics', 'groupPopulation', 'barh', '万元'),
    ('breakdowns', 'groupPopulation', 'barh', '%'),
])
def test_registered_group_unit_reaches_real_standard_axis_without_value_changes(
    render, collection, array, form, unit,  # noqa: F811
):
    columns, rows, metadata = bound_table(collection, array, unit=unit, is_percent=unit == '%')
    plan, inputs = build({'columns': columns, 'rows': rows, 'columnMeta': metadata},
                         form=form, selected=('value',))
    assert standard_visualization_preflight(plan, inputs).source is not None
    figure = render(plan, inputs)
    axes = figure.axes[0]
    assert (axes.get_xlabel() if form == 'barh' else axes.get_ylabel()) == unit
    if form == 'line':
        values = list(axes.lines[0].get_ydata())
    else:
        values = [bar.get_width() if form == 'barh' else bar.get_height()
                  for bar in axes.containers[0]]
    assert values == [-125.5, 270.25]
