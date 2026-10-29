"""Charts sharing one immutable cohort keep independent display semantics."""

import json
from pathlib import Path

import pytest

from smart_reporting.report_editor.standard_charts import (
    StandardChartEditParameters,
    standard_edit_plan,
)
from smart_reporting.reporting.tests.test_report_editor_standard_charts import plot_file
from smart_reporting.reporting.tests.test_standard_chart_presentation import render  # noqa: F401
from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    ChartDraft,
    VisualizationPlanDraft,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def chart(number=1, **options):
    return ChartDraft(chartId=f'chart{number}', sourcePath='chart.png' if number == 1 else f'chart{number}.png',
        title=f'冻结数据图{number}', altText='逐图呈现原始数据', citationIds=['citation'], metricCodes=['metric'],
        currentPeriod='2026-10', sourceDatasetId='dataset', aggregationGrain='category',
        dataBindings=[{'analysisId': 'analysis', 'factPath': 'facts.json', 'dataPath': 'rows',
                       'fields': ['actual'], 'role': 'frozen'}],
        visualForm=options.pop('visualForm', 'barh'), standardLabelField=options.pop('standardLabelField', 'label'),
        standardValueFields=options.pop('standardValueFields', ['actual']), **options)


def shared(document, *charts):
    source = ChartInputFile('input.json', json.dumps(document, ensure_ascii=False).encode())
    inputs = ChartInputMaterialization(files=(source,), entries=tuple(
        {'chartId': item.chart_id, 'path': source.path, 'sha256': source.sha256} for item in charts
    ))
    return VisualizationPlanDraft(charts=charts), inputs


def table(values=(10, 20, 30), *, labels=('甲', '乙', '丙')):
    return {'columns': ['label', 'actual'], 'rows': [[label, value] for label, value in zip(labels, values, strict=True)],
            'columnMeta': {'actual': {'unit': '元'}}}


@pytest.fixture
def render_all(render, monkeypatch):  # noqa: F811
    from matplotlib.figure import Figure

    original_save = Figure.savefig
    saved = {}

    def capture(figure, path, *args, **kwargs):
        assert str(path) not in saved
        saved[str(path)] = figure
        return original_save(figure, path, *args, **kwargs)

    monkeypatch.setattr(Figure, 'savefig', capture)

    def execute(plan, inputs):
        result = standard_visualization_preflight(plan, inputs)
        assert result.source is not None, result.diagnostic
        render(plan, inputs)
        assert set(saved) == {item.source_path for item in plan.charts}
        for item in plan.charts:
            assert Path(item.source_path).read_bytes().startswith(b'\x89PNG')
        return saved

    return execute


def assert_bars(figure, labels, values, unit):
    axes = figure.axes[0]
    assert [tick.get_text() for tick in axes.get_yticklabels()] == labels
    assert [bar.get_width() for bar in axes.containers[0]] == pytest.approx(values)
    assert axes.get_xlabel() == unit


@pytest.mark.parametrize('page_size,expected', [
    (1, [(['甲'], [10]), (['乙'], [20]), (['丙'], [30])]),
    (2, [(['甲', '乙'], [10, 20]), (['丙'], [30])]),
])
def test_editor_pages_using_one_full_cohort_render_each_own_window(render_all, page_size, expected):
    document = table()
    plan, inputs = standard_edit_plan(chart_id='chart', output_path='chart.png', title='完整来源逐页',
        alt_text='全部冻结类别', visual_form='barh', bindings=(), plot_files=[plot_file(document)],
        standard=StandardChartEditParameters.model_validate({'standardLabelField': 'label',
            'standardValueFields': ['actual'], 'standardPagination': {'pageSize': page_size}}))
    assert len(inputs.files) == 1
    assert len({entry['path'] for entry in inputs.entries}) == 1
    saved = render_all(plan, inputs)
    assert len(saved) == len(expected)
    domains = []
    for item, (labels, values) in zip(plan.charts, expected, strict=True):
        figure = saved[item.source_path]
        assert_bars(figure, labels, values, '元')
        domains.append(figure.axes[0].get_xlim())
    assert domains[0] == domains[-1]
    assert json.loads(inputs.files[0].content)['rows'] == document['rows']


def test_shared_source_keeps_distinct_windows_and_independent_domain_checks(render_all):
    document = table((-10, 20, 30, -40), labels=('甲', '乙', '丙', '丁'))
    first = chart(1, standardLabels=['甲', '丙'], standardDomains={'left': {'min': -15, 'max': 35}})
    second = chart(2, standardLabels=['乙', '丁'], standardDomains={'left': {'min': -45, 'max': 25}})
    plan, inputs = shared(document, first, second)
    figures = render_all(plan, inputs)
    assert_bars(figures['chart.png'], ['甲', '丙'], [-10, 30], '元')
    assert_bars(figures['chart2.png'], ['乙', '丁'], [20, -40], '元')
    assert figures['chart.png'].axes[0].get_xlim() == (-15, 35)
    assert figures['chart2.png'].axes[0].get_xlim() == (-45, 25)


def test_shared_source_keeps_distinct_display_units_and_values(render_all):
    plan, inputs = shared(table((10000, 20000, 30000)),
        chart(1, standardDisplayUnit='万元'), chart(2, standardDisplayUnit='亿元'))
    figures = render_all(plan, inputs)
    assert_bars(figures['chart.png'], ['甲', '乙', '丙'], [1, 2, 3], '万元')
    assert_bars(figures['chart2.png'], ['甲', '乙', '丙'], [.0001, .0002, .0003], '亿元')


def test_shared_source_scales_frozen_range_bands_with_each_chart_unit(render_all):
    document = {'columns': ['label', 'actual', 'lower', 'upper'],
        'rows': [['甲', 10000, 9000, 11000], ['乙', 20000, 19000, 21000]],
        'columnMeta': {name: {'unit': '元'} for name in ('actual', 'lower', 'upper')}}
    bands = [{'series': 'actual', 'lowerField': 'lower', 'upperField': 'upper'}]
    plan, inputs = shared(document,
        chart(1, visualForm='line', standardDisplayUnit='万元', standardBands=bands),
        chart(2, visualForm='line', standardDisplayUnit='亿元', standardBands=bands))
    figures = render_all(plan, inputs)
    for path, unit, values, lower, upper in [
        ('chart.png', '万元', [1, 2], [.9, 1.9], [1.1, 2.1]),
        ('chart2.png', '亿元', [.0001, .0002], [.00009, .00019], [.00011, .00021]),
    ]:
        axes = figures[path].axes[0]
        assert [tick.get_text() for tick in axes.get_xticklabels()] == ['甲', '乙']
        assert axes.get_ylabel() == unit
        assert list(axes.lines[0].get_ydata()) == pytest.approx(values)
        vertices = axes.collections[0].get_paths()[0].vertices
        for position in range(2):
            points = [y for x, y in vertices if x == position]
            assert min(points) == pytest.approx(lower[position])
            assert max(points) == pytest.approx(upper[position])


@pytest.mark.parametrize('form', ['barh', 'bar'])
def test_shared_source_breaks_keep_each_chart_display_units_and_auxiliary_values(render_all, form):
    document = {'columns': ['label', 'actual', 'budget', 'difference'],
        'rows': [['甲', 10000, 7, 2], ['乙', 1000000, 11, 5]],
        'columnMeta': {name: {'unit': '元'} for name in ('actual', 'budget', 'difference')}}
    annotations = [{'kind': 'values', 'series': 'actual'}]
    first = chart(1, visualForm=form, standardDisplayUnit='万元', standardLabelFields=['budget'],
        standardAnnotations=annotations, standardBreak={'lower': {'min': 0, 'max': 5},
                                                       'upper': {'min': 90, 'max': 110}})
    second = chart(2, visualForm=form, standardDisplayUnit='亿元', standardLabelFields=['difference'],
        standardAnnotations=annotations, standardBreak={'lower': {'min': 0, 'max': .0005},
                                                       'upper': {'min': .009, 'max': .011}})
    plan, inputs = shared(document, first, second)
    figures = render_all(plan, inputs)
    for path, values, unit, field, extras, absent in [
        ('chart.png', [1, 100], '万元', 'budget', [7, 11], 'difference'),
        ('chart2.png', [.0001, .01], '亿元', 'difference', [2, 5], 'budget'),
    ]:
        figure = figures[path]
        assert len(figure.axes) == 2
        for axes in figure.axes:
            actual = [bar.get_width() if form == 'barh' else bar.get_height() for bar in axes.containers[0]]
            assert actual == pytest.approx(values)
        assert any(unit in (axes.get_xlabel() if form == 'barh' else axes.get_ylabel()) for axes in figure.axes)
        labels = figure.axes[0].get_yticklabels() if form == 'barh' else figure.axes[1].get_xticklabels()
        assert [label.get_text() for label in labels] == ['甲', '乙']
        texts = [text.get_text() for axes in figure.axes for text in axes.texts]
        assert all(any(f'{field}: {value:.2f}元' in text for text in texts) for value in extras)
        assert all(absent + ':' not in text for text in texts)


def test_shared_source_dual_stacks_keep_each_auxiliary_measure(render_all):
    document = {'columns': ['label', 'actual', 'part', 'ratio', 'limit', 'sample'],
        'rows': [['甲', 10000, 2, .2, 7, 2], ['乙', 30000, 4, .4, 11, 5]],
        'columnMeta': {'actual': {'unit': '元'}, 'part': {'unit': '万元'},
                       'ratio': {'unit': '%', 'isPercent': False}, 'limit': {'unit': '件'}, 'sample': {'unit': '件'}}}
    options = {'visualForm': 'stacked-bar', 'standardValueFields': ['actual', 'part', 'ratio'],
               'standardAxes': {'mode': 'dual', 'rightFields': ['ratio'], 'leftDisplayUnit': '万元'},
               'standardAnnotations': [{'kind': 'values', 'series': 'actual'}]}
    plan, inputs = shared(document, chart(1, standardLabelFields=['limit'], **options),
                          chart(2, standardLabelFields=['sample'], **options))
    figures = render_all(plan, inputs)
    for path, field, extras, absent in [('chart.png', 'limit', [7, 11], 'sample'),
                                      ('chart2.png', 'sample', [2, 5], 'limit')]:
        left, right = figures[path].axes
        assert [tick.get_text() for tick in left.get_xticklabels()] == ['甲', '乙']
        assert [bar.get_height() for bar in left.containers[0]] == [1, 3]
        assert [bar.get_height() for bar in left.containers[1]] == [2, 4]
        assert [bar.get_y() for bar in left.containers[1]] == [1, 3]
        assert list(right.lines[0].get_ydata()) == [20, 40]
        texts = [text.get_text() for text in left.texts]
        assert all(any(f'{field}: {value:.2f}件' in text for text in texts) for value in extras)
        assert all(absent + ':' not in text for text in texts)


def test_shared_source_keeps_untransformed_and_grouped_views_separate(render_all):
    document = {'columns': ['label', 'region', 'actual'],
        'rows': [['甲', '东', 10], ['乙', '东', 20], ['丙', '西', 40]],
        'columnMeta': {'actual': {'unit': '元'}}}
    plan, inputs = shared(document, chart(1), chart(2, standardLabelField='region',
        standardView={'kind': 'group', 'labelField': 'region', 'valueFields': ['actual']}))
    figures = render_all(plan, inputs)
    assert_bars(figures['chart.png'], ['甲', '乙', '丙'], [10, 20, 40], '元')
    assert_bars(figures['chart2.png'], ['东', '西'], [30, 40], '元')


def test_shared_source_keeps_per_chart_auxiliary_annotations(render_all):
    document = {'columns': ['label', 'actual', 'budget', 'difference'],
        'rows': [['甲', 10, 12, 2], ['乙', 20, 25, 5]],
        'columnMeta': {name: {'unit': '元'} for name in ('actual', 'budget', 'difference')}}
    annotations = [{'kind': 'values', 'series': 'actual'}]
    plan, inputs = shared(document, chart(1, standardLabelFields=['budget'], standardAnnotations=annotations),
                          chart(2, standardLabelFields=['difference'], standardAnnotations=annotations))
    figures = render_all(plan, inputs)
    for path in ('chart.png', 'chart2.png'):
        assert_bars(figures[path], ['甲', '乙'], [10, 20], '元')
    first = [text.get_text() for text in figures['chart.png'].axes[0].texts]
    second = [text.get_text() for text in figures['chart2.png'].axes[0].texts]
    assert any('budget: 12.00元' in text for text in first)
    assert any('budget: 25.00元' in text for text in first)
    assert all('difference:' not in text for text in first)
    assert any('difference: 2.00元' in text for text in second)
    assert any('difference: 5.00元' in text for text in second)
    assert all('budget:' not in text for text in second)


def test_shared_single_row_keeps_each_summary_projection_separate(render_all):
    document = {'columns': ['budget', 'actual', 'difference'], 'rows': [[100, 80, 20]],
        'columnMeta': {name: {'unit': '元'} for name in ('budget', 'actual', 'difference')}}
    plan, inputs = shared(document,
        chart(1, visualForm='summary-bars', standardValueFields=['budget', 'actual']),
        chart(2, visualForm='summary-bars', standardValueFields=['actual', 'difference']))
    figures = render_all(plan, inputs)
    for path, labels, values in [('chart.png', ['budget', 'actual'], [100, 80]),
                               ('chart2.png', ['actual', 'difference'], [80, 20])]:
        axes = figures[path].axes[0]
        assert [tick.get_text() for tick in axes.get_xticklabels()] == labels
        assert [bar.get_height() for bar in axes.containers[0]] == values
        assert axes.get_ylabel() == '元'


def test_shared_transformed_source_still_rejects_changed_original_bytes(tmp_path, monkeypatch):
    document = {'columns': ['label', 'region', 'actual'],
        'rows': [['甲', '东', 10], ['乙', '东', 20]], 'columnMeta': {'actual': {'unit': '元'}}}
    plan, inputs = shared(document, chart(1), chart(2, standardLabelField='region',
        standardView={'kind': 'group', 'labelField': 'region', 'valueFields': ['actual']}))
    result = standard_visualization_preflight(plan, inputs)
    assert result.source is not None
    monkeypatch.chdir(tmp_path)
    Path('input.json').write_bytes(b'{}')
    with pytest.raises(ValueError, match='chart input identity changed'):
        exec(result.source, {})
    assert not Path('chart.png').exists() and not Path('chart2.png').exists()
