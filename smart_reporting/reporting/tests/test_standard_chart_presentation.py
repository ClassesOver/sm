import json
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
    _table_for_binding,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    ChartDataBinding,
    StandardChartAnnotation,
    StandardChartAxes,
    StandardChartOrder,
    StandardChartPresentation,
    StandardChartStyle,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_script,
)


def build(document, *, form='barh', presentation=None, style=None, selected=('actual',)):
    chart = SimpleNamespace(chart_id='chart', renderer='matplotlib', interactive_path=None,
        visual_form=form, source_path='chart.png', title='预算执行情况',
        standard_value_fields=selected,
        standard_annotations=(StandardChartAnnotation(kind='values', series='value' if form == 'summary-bars' else selected[0]),),
        standard_presentation=StandardChartPresentation.model_validate(presentation or {}),
        standard_style=StandardChartStyle.model_validate(style or {}))
    source = ChartInputFile('input.json', json.dumps(document, ensure_ascii=False).encode())
    inputs = ChartInputMaterialization(files=(source,), entries=({'chartId': 'chart', 'path': source.path, 'sha256': source.sha256},))
    return SimpleNamespace(charts=(chart,)), inputs


@pytest.fixture
def render(tmp_path, monkeypatch):
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure

    saved = []
    original_save = Figure.savefig
    close = plt.close

    def capture(figure, *args, **kwargs):
        saved.append(figure)
        return original_save(figure, *args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Figure, 'savefig', capture)
    monkeypatch.setattr(plt, 'close', lambda *args: None)

    def execute(plan, inputs):
        for source in inputs.files:
            (tmp_path / source.path).write_bytes(source.content)
        script = standard_visualization_script(plan, inputs)
        assert script is not None
        exec(script, {})
        for source in inputs.files:
            assert (tmp_path / source.path).read_bytes() == source.content
        assert (tmp_path / 'chart.png').read_bytes().startswith(b'\x89PNG')
        return saved[-1]

    yield execute
    close('all')


def test_sorted_bottom_subset_keeps_color_and_auxiliary_values_bound_to_same_row(render):
    import matplotlib.colors as colors

    document = {'columns': ['label', 'actual', 'budget'],
        'rows': [['普通', 90, 100], ['体检', 50, 100], ['缺失', None, 100], ['特需', 70, 100]],
        'columnMeta': {'actual': {'unit': '元'}, 'budget': {'unit': '元'}}}
    plan, inputs = build(document, presentation={
        'order': {'mode': 'value', 'field': 'actual', 'excludeMissing': True, 'limit': 2},
        'labelFormats': [{'field': 'budget', 'displayUnit': '元', 'caption': '预算'},
                         {'numerator': 'actual', 'denominator': 'budget', 'caption': '完成率'}]},
        style={'points': [{'series': 'actual', 'label': '体检', 'color': '#bd4f4f'}],
               'annotationOffsetY': 0, 'annotationOffsetX': 7, 'valueMargin': .5})
    figure = render(plan, inputs)
    axes = figure.axes[0]
    assert [tick.get_text() for tick in axes.get_yticklabels()] == ['体检', '特需']
    assert [bar.get_width() for bar in axes.containers[0]] == [50, 70]
    assert colors.to_hex(axes.containers[0][0].get_facecolor()) == '#bd4f4f'
    assert '预算 100.00元' in axes.texts[0].get_text()
    assert '完成率 50.00%' in axes.texts[0].get_text()
    assert colors.to_hex(axes.texts[0].get_color()) == '#bd4f4f'


def test_summary_badges_and_two_category_colors_use_frozen_single_row(render):
    import matplotlib.colors as colors

    document = {'columns': ['预算', '实际', '差额', '完成率'], 'rows': [[1e9, 8e8, -2e8, 80]],
        'columnMeta': {'预算': {'unit': '元'}, '实际': {'unit': '元'}, '差额': {'unit': '元'}, '完成率': {'unit': '%', 'isPercent': True}}}
    plan, inputs = build(document, form='summary-bars', selected=('预算', '实际'), presentation={
        'subtitle': '年度预算执行｜单位：亿元', 'sourceNote': '数据来源：收入预算执行汇总。',
        'summaries': [{'field': '差额', 'displayUnit': '亿元', 'showSign': True}, {'field': '完成率'}]},
        style={'points': [{'series': 'value', 'label': '预算', 'color': '#4c72b0'},
                          {'series': 'value', 'label': '实际', 'color': '#dd8452'}]})
    plan.charts[0].standard_display_unit = '亿元'
    figure = render(plan, inputs)
    assert [bar.get_height() for bar in figure.axes[0].containers[0]] == [10, 8]
    assert [colors.to_hex(bar.get_facecolor()) for bar in figure.axes[0].containers[0]] == ['#4c72b0', '#dd8452']
    texts = [text.get_text() for text in figure.texts]
    assert '差额 -2.00亿元' in texts
    assert '完成率 80.00%' in texts
    assert any('数据来源' in text for text in texts)
    assert figure._suptitle.get_fontweight() == 'bold'
    assert all(text.arrow_patch is None for text in figure.axes[0].texts)


def test_peak_trough_colors_month_labels_and_deduplication(render):
    import matplotlib.colors as colors

    document = {'columns': ['period', 'actual'], 'rows': [['2025-01', 10], ['2025-02', 5], ['2025-03', 20]],
                'columnMeta': {'actual': {'unit': '人次'}}}
    plan, inputs = build(document, form='line', presentation={'labelMode': 'month'})
    plan.charts[0].standard_annotations += (
        StandardChartAnnotation(kind='peak', series='actual', color='#258558', highlight=True),
        StandardChartAnnotation(kind='trough', series='actual', color='#bd4f4f', highlight=True, position='below'))
    figure = render(plan, inputs)
    axes = figure.axes[0]
    assert [text.get_text() for text in axes.get_xticklabels()] == ['1月', '2月', '3月']
    assert list(axes.lines[0].get_ydata()) == [10, 5, 20]
    assert len(axes.texts) == 3
    peak = next(text for text in axes.texts if text.get_text().startswith('峰值'))
    trough = next(text for text in axes.texts if text.get_text().startswith('谷值'))
    assert colors.to_hex(peak.get_color()) == '#258558'
    assert colors.to_hex(trough.get_color()) == '#bd4f4f'
    assert trough.get_position()[1] < 0
    assert len(axes.collections) == 2


@pytest.mark.parametrize('mode,expected', [('reverse', ['B', 'A']), ('label', ['A', 'B']), ('explicit', ['B', 'A'])])
def test_order_modes_do_not_change_amounts(render, mode, expected):
    document = {'columns': ['label', 'actual'], 'rows': [['A', 10], ['B', 20]], 'columnMeta': {'actual': {'unit': '元'}}}
    order = {'mode': mode, **({'labels': ['B', 'A']} if mode == 'explicit' else {})}
    plan, inputs = build(document, presentation={'order': order})
    axes = render(plan, inputs).axes[0]
    assert [tick.get_text() for tick in axes.get_yticklabels()] == expected
    assert [bar.get_width() for bar in axes.containers[0]] == [10 if label == 'A' else 20 for label in expected]


def test_cost_change_horizontal_chart_keeps_numeric_ticks_horizontal(render):
    # 本次真实报告的七项冻结成本变动；数值轴不能套用类别轴的旋转角度。
    document = {'columns': ['indicator_name', 'change'], 'rows': [
        ['人员支出', 175901433], ['其他费用', -14837553],
        ['卫生材料成本', 9883877], ['药品成本', 1030645],
        ['固定资产折旧', 286787], ['无形资产摊销费', 155517],
        ['提取医疗风险基金', -85606]], 'columnMeta': {'change': {'unit': '元'}}}
    plan, inputs = build(document, selected=('change',), presentation={
        'order': {'mode': 'value', 'field': 'change', 'descending': True}})
    plan.charts[0].standard_label_field = 'indicator_name'
    plan.charts[0].standard_display_unit = '万元'
    figure = render(plan, inputs)
    axes = figure.axes[0]
    ticks = [tick for tick in axes.get_xticklabels() if tick.get_visible()]
    assert ticks and all(tick.get_rotation() == 0 for tick in ticks)
    boxes = [tick.get_window_extent(figure.canvas.get_renderer()) for tick in ticks]
    assert all(not left.overlaps(right) for left, right in zip(boxes, boxes[1:]))
    assert [bar.get_width() for bar in axes.containers[0]] == pytest.approx(
        [17590.1433, 988.3877, 103.0645, 28.6787, 15.5517, -8.5606, -1483.7553])


def test_vertical_chart_retains_declared_category_rotation(render):
    document = {'columns': ['label', 'actual'], 'rows': [['甲', 10], ['乙', 20]],
                'columnMeta': {'actual': {'unit': '元'}}}
    plan, inputs = build(document, form='bar', style={'labelRotation': 30})
    axes = render(plan, inputs).axes[0]
    assert all(tick.get_rotation() == 30 for tick in axes.get_xticklabels())


def test_negative_horizontal_auto_labels_stay_outside_their_bars(render):
    from matplotlib.text import Text

    document = {'columns': ['label', 'actual'],
        'rows': [['门诊部', -20626], ['儿内科', -12051], ['消化内科', -9626]],
        'columnMeta': {'actual': {'unit': '人次'}}}
    plan, inputs = build(document)
    figure = render(plan, inputs)
    axes = figure.axes[0]
    renderer = figure.canvas.get_renderer()
    for annotation, bar in zip(axes.texts, axes.containers[0], strict=True):
        assert annotation.get_ha() == 'right'
        assert annotation.get_position()[0] < 0
        assert not Text.get_window_extent(annotation, renderer).overlaps(bar.get_window_extent(renderer))


def test_negative_horizontal_explicit_right_label_retains_requested_position(render):
    document = {'columns': ['label', 'actual'], 'rows': [['门诊部', -20626]],
                'columnMeta': {'actual': {'unit': '人次'}}}
    plan, inputs = build(document)
    plan.charts[0].standard_annotations = (
        StandardChartAnnotation(kind='values', series='actual', position='right'),)
    annotation = render(plan, inputs).axes[0].texts[0]
    assert annotation.get_ha() == 'left'
    assert annotation.get_position()[0] > 0


def test_max_abs_explicit_missing_exclusion_keeps_frozen_top_changes(render):
    document = {'columns': ['label', 'change'], 'rows': [
        ['门诊部', -20626], ['儿内科', -12051], ['临床营养科', 109], ['脑病中心', None]],
        'columnMeta': {'change': {'unit': '人次'}}}
    plan, inputs = build(document, selected=('change',), presentation={
        'order': {'mode': 'max_abs', 'fields': ['change'], 'descending': True,
                  'excludeMissing': True, 'limit': 2}})
    axes = render(plan, inputs).axes[0]
    assert [tick.get_text() for tick in axes.get_yticklabels()] == ['门诊部', '儿内科']
    assert [bar.get_width() for bar in axes.containers[0]] == [-20626, -12051]
    assert json.loads(inputs.files[0].content) == document


@pytest.mark.parametrize('bad', [True, float('inf'), float('nan')])
@pytest.mark.parametrize('missing_peer', [False, True])
def test_max_abs_explicit_missing_exclusion_still_rejects_invalid_values(bad, missing_peer):
    from smart_reporting.reporting.workflow.runtime.standard_chart_presentation import (
        order_standard_rows,
    )

    document = {'columns': ['label', 'a', 'b'],
        'rows': [['valid', -10, 20], ['missing', None, 30],
                 ['invalid', bad, None if missing_peer else 40]],
        'columnMeta': {'a': {'unit': '人次'}, 'b': {'unit': '人次'}}}
    order = StandardChartOrder(mode='max_abs', fields=('a', 'b'), excludeMissing=True)
    assert order_standard_rows(document, 'label', order) is None


def test_max_abs_explicit_missing_exclusion_requires_all_sort_operands_and_same_unit():
    from smart_reporting.reporting.workflow.runtime.standard_chart_presentation import (
        order_standard_rows,
    )

    document = {'columns': ['label', 'a', 'b'],
        'rows': [['first', -10, 20], ['missing_a', None, 30], ['missing_b', 40, None],
                 ['last', 5, -50]],
        'columnMeta': {'a': {'unit': '人次'}, 'b': {'unit': '人次'}}}
    order = StandardChartOrder(mode='max_abs', fields=('a', 'b'), descending=True, excludeMissing=True)
    assert order_standard_rows(document, 'label', order)['rows'] == [
        ['last', 5, -50], ['first', -10, 20]]
    assert order_standard_rows(document, 'label', order.model_copy(update={'exclude_missing': False})) is None
    document['columnMeta']['b']['unit'] = '床日'
    assert order_standard_rows(document, 'label', order) is None
    document['columnMeta']['b']['unit'] = '人次'
    document['rows'] = [['missing', None, None]]
    assert order_standard_rows(document, 'label', order) is None


@pytest.mark.parametrize('fault', ['unknown_field', 'ratio_zero', 'ratio_unit', 'bad_display_unit', 'ambiguous_summary', 'unknown_point', 'month_cross_year'])
def test_unbound_or_invalid_presentation_falls_back(fault):
    document = {'columns': ['label', 'actual', 'budget'], 'rows': [['2025-01', 10, 20], ['2026-01', 15, 20]],
                'columnMeta': {'actual': {'unit': '元'}, 'budget': {'unit': '元'}}}
    options, style = {}, {}
    if fault == 'unknown_field':
        options = {'labelFormats': [{'field': 'invented'}]}
    elif fault in {'ratio_zero', 'ratio_unit'}:
        options = {'labelFormats': [{'numerator': 'actual', 'denominator': 'budget'}]}
        if fault == 'ratio_zero':
            document['rows'][0][2] = 0
        else:
            document['columnMeta']['budget']['unit'] = '人次'
    elif fault == 'bad_display_unit':
        options = {'labelFormats': [{'field': 'actual', 'displayUnit': '人次'}]}
    elif fault == 'ambiguous_summary':
        options = {'summaries': [{'field': 'actual'}]}
    elif fault == 'unknown_point':
        style = {'points': [{'series': 'actual', 'label': 'foreign', 'color': '#ff0000'}]}
    else:
        options = {'labelMode': 'month'}
    plan, inputs = build(document, presentation=options, style=style)
    assert standard_visualization_script(plan, inputs) is None


def test_zero_baseline_is_explicit_and_cannot_override_log_scale(render):
    document = {'columns': ['period', 'actual'], 'rows': [['2025-01', 10], ['2025-02', 20]], 'columnMeta': {'actual': {'unit': '元'}}}
    plan, inputs = build(document, form='line')
    plan.charts[0].standard_axes = StandardChartAxes(zeroBaseline=True)
    assert render(plan, inputs).axes[0].get_ylim()[0] == 0
    plan.charts[0].standard_axes = StandardChartAxes(zeroBaseline=True, scale='log')
    assert standard_visualization_script(plan, inputs) is None


@pytest.mark.parametrize('unit', ['元', '人次', None])
def test_period_values_inherit_only_exact_frozen_metric_unit(unit):
    binding = ChartDataBinding(analysisId='analysis', factPath='facts.json', dataPath='metrics[0].periodValues',
                               fields=['period', 'value'], role='月度指标')
    document = {'metrics': [{'unit': unit, 'periodValues': [{'period': '2025-01', 'value': 42}]}]}
    columns, rows, metadata = _table_for_binding(document, binding)
    assert columns == ['period', 'value'] and rows == [['2025-01', 42]]
    assert metadata == ({'value': {'unit': unit}} if unit else None)


def test_metric_projection_does_not_borrow_neighbor_or_unrelated_units():
    binding = ChartDataBinding(analysisId='analysis', factPath='facts.json', dataPath='metrics[1].periodValues',
                               fields=['period', 'value'], role='月度指标')
    document = {'unit': '元', 'metrics': [{'unit': '元'}, {'periodValues': [{'period': '2025-01', 'value': 42}]}]}
    assert _table_for_binding(document, binding)[2] is None


@pytest.mark.parametrize('form', ['barh', 'line'])
def test_business_series_names_with_delimiters_keep_exact_colors(render, form):
    import matplotlib.colors as colors

    name = '急诊（非病区） · 本期'
    document = {'columns': ['label', name], 'rows': [['A', 10], ['B', 20]], 'columnMeta': {name: {'unit': '元'}}}
    plan, inputs = build(document, form=form, selected=(name,), style={'series': [{'series': name, 'color': '#4c72b0'}]})
    axes = render(plan, inputs).axes[0]
    artist = axes.lines[0] if form == 'line' else axes.containers[0][0]
    assert colors.to_hex(artist.get_color() if form == 'line' else artist.get_facecolor()) == '#4c72b0'


@pytest.mark.parametrize('options', [
    {'mode': 'value'}, {'mode': 'source', 'excludeMissing': True},
    {'mode': 'reverse', 'descending': True}, {'mode': 'explicit'},
])
def test_incomplete_order_parameters_are_rejected(options):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StandardChartPresentation.model_validate({'order': options})


def test_multiline_heading_and_footer_reserve_real_plot_space(render):
    document = {'columns': ['label', 'actual'], 'rows': [['业务', 100]], 'columnMeta': {'actual': {'unit': '元'}}}
    plan, inputs = build(document, presentation={'subtitle': '预算执行统计口径说明' * 12, 'sourceNote': '数据来源与口径说明' * 18})
    plan.charts[0].title = '预算执行与经济运行分析报告' * 5
    figure = render(plan, inputs)
    assert '\n' in figure._suptitle.get_text()
    bounds = figure.axes[0].get_position()
    assert bounds.y1 < .8
    assert bounds.y0 > .1


@pytest.mark.parametrize('value', [1e-14, -1e-12, 1e15, -1e16])
@pytest.mark.parametrize('form', ['line', 'barh'])
def test_changed_value_magnitude_never_formats_nonzero_as_zero(render, value, form):
    from smart_reporting.reporting.workflow.runtime.standard_chart_presentation import (
        format_standard_number,
    )

    document = {'columns': ['label', 'actual'], 'rows': [['业务', value]], 'columnMeta': {'actual': {'unit': '元'}}}
    plan, inputs = build(document, form=form)
    axes = render(plan, inputs).axes[0]
    text = axes.texts[0].get_text().removesuffix('元')
    assert 'e' in text
    assert float(text) == pytest.approx(value)
    assert text == format_standard_number(value)
    data = list(axes.lines[0].get_ydata()) if form == 'line' else [bar.get_width() for bar in axes.containers[0]]
    assert data == [value]


def test_tiny_frozen_summary_and_auxiliary_values_remain_visible(render):
    document = {'columns': ['label', 'actual', 'budget'], 'rows': [['业务', 1e-12, 2e-12]],
                'columnMeta': {'actual': {'unit': '元'}, 'budget': {'unit': '元'}}}
    plan, inputs = build(document, presentation={'labelFormats': [{'field': 'budget'}], 'summaries': [{'field': 'actual'}]})
    figure = render(plan, inputs)
    assert '1.00e-12元' in figure.axes[0].texts[0].get_text()
    assert 'budget 2.00e-12元' in figure.axes[0].texts[0].get_text()
    assert any(text.get_text() == 'actual 1.00e-12元' for text in figure.texts)


@pytest.mark.parametrize('form', ['stacked-bar', 'stacked-area', 'stacked-total'])
def test_finite_inputs_with_overflowing_stack_require_fallback(form):
    document = {'columns': ['label', 'actual', 'budget'], 'rows': [['业务', 1e308, 1e308]],
                'columnMeta': {'actual': {'unit': '元'}, 'budget': {'unit': '元'}}}
    plan, inputs = build(document, form=form, selected=('actual', 'budget'))
    assert standard_visualization_script(plan, inputs) is None


def test_dense_category_axis_thins_only_ticks_and_preserves_all_points(render):
    document = {'columns': ['label', 'actual'], 'rows': [[f'业务名称-{i:02}', i + 1] for i in range(60)],
                'columnMeta': {'actual': {'unit': '元'}}}
    plan, inputs = build(document, form='line')
    plan.charts[0].standard_annotations = ()
    figure = render(plan, inputs)
    axes = figure.axes[0]
    assert list(axes.lines[0].get_ydata()) == list(range(1, 61))
    assert len(axes.get_xticklabels()) <= 18
    assert axes.get_xticklabels()[-1].get_text() == '业务名称-59'


@pytest.mark.parametrize('document', [None, [], {'rows': []}, {'columns': ['label'], 'rows': None}])
def test_malformed_replacement_data_never_raises_outside_standard_preflight(document):
    plan, inputs = build(document)
    assert standard_visualization_script(plan, inputs) is None


@pytest.mark.parametrize('seed', [7, 41, 99])
@pytest.mark.parametrize('form', ['line', 'barh', 'stacked-total'])
def test_unfamiliar_random_datasets_preserve_every_series_value(render, seed, form):
    import math
    import random

    rng = random.Random(seed)
    names = [f'新指标-{i}' for i in range(rng.randint(2, 5))]
    rows = []
    for index in range(rng.randint(3, 12)):
        values = [rng.uniform(-1000, 1000) for name in names]
        if form == 'stacked-total':
            values = [abs(value) for value in values]
        rows.append([f'未知业务-{seed}-{index}', *values])
    document = {'columns': ['label', *names], 'rows': rows, 'columnMeta': {name: {'unit': '元'} for name in names}}
    plan, inputs = build(document, form=form, selected=tuple(names))
    plan.charts[0].standard_annotations = ()
    axes = render(plan, inputs).axes[0]
    for index, name in enumerate(names):
        expected = [row[index + 1] for row in rows]
        if form == 'line':
            assert list(axes.lines[index].get_ydata()) == expected
        elif form == 'barh':
            assert [bar.get_width() for bar in axes.containers[index]] == expected
        else:
            assert [bar.get_height() for bar in axes.containers[index]] == pytest.approx(expected)
    if form == 'stacked-total':
        assert list(axes.lines[0].get_ydata()) == [math.fsum(row[1:]) for row in rows]


def test_invalid_json_bytes_require_fallback_without_escaping_preflight():
    plan, _ = build({'columns': ['label', 'actual'], 'rows': [['A', 1]]})
    source = ChartInputFile('input.json', b'{invalid')
    inputs = ChartInputMaterialization(files=(source,), entries=({'chartId': 'chart', 'path': source.path, 'sha256': source.sha256},))
    assert standard_visualization_script(plan, inputs) is None


@pytest.mark.parametrize('metadata', [None, {'budget': {'unit': '元'}, 'actual': None}])
def test_summary_projection_with_malformed_metadata_requires_fallback(metadata):
    document = {'columns': ['budget', 'actual'], 'rows': [[100, 80]], 'columnMeta': metadata}
    plan, inputs = build(document, form='summary-bars', selected=('budget', 'actual'))
    assert standard_visualization_script(plan, inputs) is None


def test_manual_canvas_cannot_silently_clip_external_legend(render):
    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartCanvas

    names = [f'系列{i}' for i in range(8)]
    document = {'columns': ['label', *names], 'rows': [['甲', *range(1, 9)], ['乙', *range(2, 10)]],
                'columnMeta': {name: {'unit': '元'} for name in names}}
    plan, inputs = build(document, form='line', selected=tuple(names))
    plan.charts[0].standard_annotations = ()
    plan.charts[0].standard_canvas = StandardChartCanvas(layout='manual', legendPosition='outside')
    with pytest.raises(ValueError, match='图例超出画布'):
        render(plan, inputs)


@pytest.mark.parametrize('text,width,expected', [
    ('神经外科一病区', 14, ['神经外科一病区']),
    ('心血管内科（含CCU）住院收入', 14, ['心血管内科（含', 'CCU）住院收入']),
    ('2025年1月门诊收入合计（万元）', 14, ['2025年1月门诊', '收入合计（万元）']),
    ('骨科关节与运动医学中心', 6, ['骨科关节与运', '动医学中心']),
    ('2025年1月门诊收入合计（万元）', 8, ['2025年', '1月门诊收入', '合计（万元）']),
    ('甲：缺失\n乙：范围缺失未补零', 6, ['甲：缺失', '乙：范围缺', '失未补零']),
])
def test_standard_wrap_balances_lines_and_respects_cjk_punctuation(text, width, expected):
    from smart_reporting.reporting.workflow.runtime.standard_chart_presentation import (
        PRESENTATION_SCRIPT,
    )

    namespace = {}
    exec(PRESENTATION_SCRIPT, namespace)
    lines = namespace['standard_wrap'](text, width).split('\n')
    assert lines == expected
    # 只换行不改字：去掉换行后与原文逐字一致。
    assert ''.join(lines) == text.replace('\n', '')
    assert not any(line[-1] in '（([【《' for line in lines[:-1])
