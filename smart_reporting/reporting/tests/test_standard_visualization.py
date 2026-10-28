import json
import math
import subprocess
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_script,
)


def fixture(form='bar'):
    chart = SimpleNamespace(chart_id='chart_001', renderer='matplotlib', interactive_path=None,
                            visual_form=form, source_path='chart.png', title='收入趋势')
    content = json.dumps({'columns': ['period', 'value'],
                          'rows': [['2025-01', 10], ['2025-02', 20]]}).encode()
    source = ChartInputFile('input.json', content)
    entry = {'chartId': chart.chart_id, 'path': source.path, 'sha256': source.sha256}
    return SimpleNamespace(charts=(chart,)), ChartInputMaterialization(files=(source,), entries=(entry,))


def complex_fixture(form, *, long=False):
    plan, _ = fixture(form)
    document = ({'columns': ['period', 'department', 'value'],
                 'rows': [['2025-01', 'A', 10], ['2025-01', 'B', 20],
                          ['2025-02', 'A', 30], ['2025-02', 'B', 40]],
                 'columnMeta': {'value': {'unit': '元'}}} if long else
                {'columns': ['period', 'actual', 'budget'],
                 'rows': [['2025-01', 10, 20], ['2025-02', 30, 40]],
                 'columnMeta': {'actual': {'unit': '元'}, 'budget': {'unit': '元'}}})
    return plan, document


def materialization(document):
    source = ChartInputFile('input.json', json.dumps(document).encode())
    return ChartInputMaterialization(files=(source,), entries=({
        'chartId': 'chart_001', 'path': source.path, 'sha256': source.sha256,
    },))


@pytest.mark.parametrize('form', ['line', 'bar', 'barh', 'stacked-bar', 'stacked-area'])
@pytest.mark.parametrize('long', [False, True])
def test_complex_templates_render_all_series(tmp_path, form, long):
    plan, document = complex_fixture(form, long=long)
    inputs = materialization(document)
    script = standard_visualization_script(plan, inputs)
    assert script is not None
    (tmp_path / 'input.json').write_bytes(inputs.files[0].content)
    (tmp_path / 'draw.py').write_text(script)
    completed = subprocess.run([sys.executable, 'draw.py'], cwd=tmp_path, capture_output=True)
    assert completed.returncode == 0, completed.stderr.decode()
    assert (tmp_path / 'chart.png').read_bytes().startswith(b'\x89PNG')


@pytest.mark.parametrize('fault', ['unit', 'scale', 'window', 'duplicate', 'negative', 'nan'])
def test_ambiguous_or_unsafe_complex_shapes_fall_back(fault):
    plan, document = complex_fixture('stacked-bar')
    if fault == 'unit':
        document['columnMeta']['budget']['unit'] = '人次'
    elif fault == 'scale':
        document['columnMeta']['budget']['isPercent'] = False
    elif fault == 'window':
        document['columnMeta']['budget']['periods'] = ['2024-01']
    elif fault == 'duplicate':
        document['rows'].append(document['rows'][0])
    elif fault == 'negative':
        document['rows'][0][1] = -10
    else:
        document['rows'][0][1] = float('nan')
    assert standard_visualization_script(plan, materialization(document)) is None


def test_missing_long_table_combinations_only_allow_line_gaps():
    plan, document = complex_fixture('line', long=True)
    document['rows'].pop()
    assert standard_visualization_script(plan, materialization(document)) is not None
    plan.charts[0].visual_form = 'stacked-bar'
    assert standard_visualization_script(plan, materialization(document)) is None


def test_rendered_series_preserve_values_and_missing_gap(tmp_path, monkeypatch):
    import matplotlib.pyplot as plt

    plan, document = complex_fixture('line', long=True)
    document['rows'].pop()
    inputs = materialization(document)
    (tmp_path / 'input.json').write_bytes(inputs.files[0].content)
    monkeypatch.chdir(tmp_path)
    close = plt.close
    monkeypatch.setattr(plt, 'close', lambda *args: None)
    try:
        exec(standard_visualization_script(plan, inputs), {})
        lines = plt.gcf().axes[0].lines
        assert list(lines[0].get_ydata()) == [10, 30]
        assert lines[1].get_ydata()[0] == 20
        assert math.isnan(lines[1].get_ydata()[1])
    finally:
        close('all')


def test_percentage_display_uses_frozen_scale(tmp_path, monkeypatch):
    import matplotlib.pyplot as plt

    plan, _ = fixture('bar')
    document = {'columns': ['label', 'value'], 'rows': [['A', .25], ['B', .75]],
                'columnMeta': {'value': {'unit': '%', 'isPercent': False}}}
    inputs = materialization(document)
    (tmp_path / 'input.json').write_bytes(inputs.files[0].content)
    monkeypatch.chdir(tmp_path)
    close = plt.close
    monkeypatch.setattr(plt, 'close', lambda *args: None)
    try:
        exec(standard_visualization_script(plan, inputs), {})
        axes = plt.gcf().axes[0]
        assert [bar.get_height() for bar in axes.patches] == [25, 75]
        assert axes.get_ylabel() == '%'
    finally:
        close('all')


@pytest.mark.parametrize('selected', [('医疗收入金额',), ('占比',), ('foreign',)])
def test_explicit_selection_supports_chinese_labels_without_implicit_auxiliary_projection(selected):
    plan, _ = fixture('barh')
    plan.charts[0].standard_value_fields = selected
    document = {'columns': ['收入类型', '医疗收入金额', '同范围总额', '占比'],
                'rows': [['甲', 30, 100, 30], ['乙', 70, 100, 70]],
                'columnMeta': {'医疗收入金额': {'unit': '元'}, '同范围总额': {'unit': '元'},
                               '占比': {'unit': '%', 'isPercent': True}}}
    script = standard_visualization_script(plan, materialization(document))
    assert (script is not None) == (selected != ('foreign',))
    plan.charts[0].standard_value_fields = ()
    assert standard_visualization_script(plan, materialization(document)) is None


@pytest.mark.parametrize('form', ['line', 'bar', 'barh', 'stacked-bar', 'stacked-area'])
def test_annotations_use_frozen_values_and_correct_series_coordinates(tmp_path, monkeypatch, form):
    import matplotlib.pyplot as plt

    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartAnnotation

    plan, document = complex_fixture(form)
    plan.charts[0].standard_annotations = tuple(StandardChartAnnotation.model_validate(item) for item in [
        {'kind': 'peak', 'series': 'budget'},
        {'kind': 'trough', 'series': 'actual'},
        {'kind': 'point', 'series': 'actual', 'label': '2025-02'},
        {'kind': 'reference', 'series': 'actual', 'label': '2025-01'},
        {'kind': 'range', 'label': '2025-01', 'endLabel': '2025-02'},
    ])
    inputs = materialization(document)
    (tmp_path / 'input.json').write_bytes(inputs.files[0].content)
    monkeypatch.chdir(tmp_path)
    close = plt.close
    monkeypatch.setattr(plt, 'close', lambda *args: None)
    try:
        script = standard_visualization_script(plan, inputs)
        assert script is not None
        exec(script, {})
        axes = plt.gcf().axes[0]
        peak = next(text for text in axes.texts if text.get_text().startswith('峰值'))
        assert peak.get_text() == '峰值 40.00元'
        expected_height = 70 if form.startswith('stacked') else 40
        assert peak.xy[0 if form == 'barh' else 1] == expected_height
        assert any('参考 2025-01' in text.get_text() and '10.00元' in text.get_text() for text in axes.texts)
        assert (tmp_path / 'chart.png').read_bytes().startswith(b'\x89PNG')
    finally:
        close('all')


@pytest.mark.parametrize('specification', [
    {'kind': 'point', 'series': 'foreign', 'label': '2025-01'},
    {'kind': 'point', 'series': 'actual', 'label': 'unknown'},
    {'kind': 'range', 'label': '2025-02', 'endLabel': '2025-01'},
    {'kind': 'peak'},
])
def test_unbound_annotations_fall_back(specification):
    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartAnnotation

    plan, document = complex_fixture('line')
    plan.charts[0].standard_annotations = (StandardChartAnnotation.model_validate(specification),)
    assert standard_visualization_script(plan, materialization(document)) is None


@pytest.mark.parametrize('mode', ['dual', 'panels', 'zoom', 'log'])
def test_advanced_axes_preserve_values_units_and_scale(tmp_path, monkeypatch, mode):
    import matplotlib.pyplot as plt

    from smart_reporting.reporting.workflow.runtime.phase_models import (
        StandardChartAnnotation,
        StandardChartAxes,
    )

    plan, document = complex_fixture('line')
    options = {'mode': mode} if mode != 'log' else {'scale': 'log'}
    if mode in {'panels', 'log', 'zoom'}:
        document['rows'][0][1] = 1
        document['rows'][1][1] = 1_000_000_000_000
    if mode == 'dual':
        document['columnMeta']['budget'] = {'unit': '%', 'isPercent': False}
        document['rows'][0][2], document['rows'][1][2] = .2, .4
        options['rightFields'] = ('budget',)
        plan.charts[0].standard_annotations = (
            StandardChartAnnotation(kind='reference', series='budget', label='2025-01'),
        )
    elif mode == 'zoom':
        options.update(zoomStart='2025-01', zoomEnd='2025-02')
    plan.charts[0].standard_axes = StandardChartAxes.model_validate(options)
    inputs = materialization(document)
    (tmp_path / 'input.json').write_bytes(inputs.files[0].content)
    monkeypatch.chdir(tmp_path)
    close = plt.close
    monkeypatch.setattr(plt, 'close', lambda *args: None)
    try:
        script = standard_visualization_script(plan, inputs)
        assert script is not None
        exec(script, {})
        axes = plt.gcf().axes
        assert list(axes[0].lines[0].get_ydata()) == (
            [10, 30] if mode == 'dual' else [1, 1_000_000_000_000]
        )
        if mode == 'dual':
            assert list(axes[1].lines[0].get_ydata()) == [20, 40]
            assert axes[0].get_ylabel() == '左轴 · 元'
            assert axes[1].get_ylabel() == '右轴 · %'
            assert list(axes[1].lines[1].get_ydata()) == [20, 20]
            assert not axes[0].texts
        elif mode == 'panels':
            assert len(axes) == 2
            assert list(axes[1].lines[0].get_ydata()) == [20, 40]
        elif mode == 'log':
            assert axes[0].get_yscale() == 'log'
            assert '对数刻度' in axes[0].get_ylabel()
        else:
            assert len(axes[0].child_axes) == 1
            assert '局部放大' in axes[0].child_axes[0].get_title()
        assert (tmp_path / 'chart.png').exists()
    finally:
        close('all')


@pytest.mark.parametrize('fault', ['zero_log', 'negative_log', 'unknown_axis', 'all_right', 'zoom', 'mixed_single'])
def test_advanced_axes_reject_unverifiable_or_misleading_settings(fault):
    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartAxes

    plan, document = complex_fixture('line')
    options = {}
    if fault.endswith('log'):
        options = {'scale': 'log'}
        document['rows'][0][1] = 0 if fault == 'zero_log' else -1
    elif fault in {'unknown_axis', 'all_right'}:
        options = {'mode': 'dual', 'rightFields': ('foreign',) if fault == 'unknown_axis' else ('actual', 'budget')}
    elif fault == 'zoom':
        options = {'mode': 'zoom', 'zoomStart': 'unknown', 'zoomEnd': '2025-02'}
    else:
        document['columnMeta']['budget']['unit'] = '%'
    plan.charts[0].standard_axes = StandardChartAxes.model_validate(options)
    assert standard_visualization_script(plan, materialization(document)) is None


def test_exact_multisource_alignment_preserves_order_and_rejects_missing_labels(tmp_path):
    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartSource
    from smart_reporting.reporting.workflow.runtime.standard_chart_alignment import (
        align_chart_sources,
    )

    documents = [
        {'columns': ['period', 'value'], 'rows': [['Jan', 1], ['Feb', 2]],
         'columnMeta': {'value': {'unit': '元'}}},
        {'columns': ['period', 'value'], 'rows': [['Feb', 20], ['Jan', 10]],
         'columnMeta': {'value': {'unit': '元'}}},
    ]
    files = tuple(ChartInputFile(f'input-{i}.json', json.dumps(doc).encode())
                  for i, doc in enumerate(documents))
    entries = tuple({'chartId': 'chart_001', 'path': file.path, 'sha256': file.sha256} for file in files)
    selections = tuple(StandardChartSource(sourceIndex=i, labelField='period', valueField='value',
                                          seriesName=f'series{i}') for i in range(2))
    document, identities = align_chart_sources(entries, files, selections)
    assert document['rows'] == [['Jan', 1, 10], ['Feb', 2, 20]]
    assert identities == [(file.path, file.sha256) for file in files]
    plan, _ = fixture('line')
    plan.charts[0].standard_sources = selections
    script = standard_visualization_script(plan, ChartInputMaterialization(files=files, entries=entries))
    assert script is not None
    for file in files:
        (tmp_path / file.path).write_bytes(file.content)
    (tmp_path / 'draw.py').write_text(script)
    completed = subprocess.run([sys.executable, 'draw.py'], cwd=tmp_path, capture_output=True)
    assert completed.returncode == 0, completed.stderr.decode()
    (tmp_path / files[1].path).write_text('{}')
    completed = subprocess.run([sys.executable, 'draw.py'], cwd=tmp_path, capture_output=True)
    assert completed.returncode != 0
    assert b'aligned chart input identity changed' in completed.stderr
    documents[1]['rows'].pop()
    changed = ChartInputFile(files[1].path, json.dumps(documents[1]).encode())
    entries[1]['sha256'] = changed.sha256
    assert align_chart_sources(entries, (files[0], changed), selections) is None


def test_stacked_total_and_auxiliary_labels_preserve_distinct_semantics(tmp_path, monkeypatch):
    import matplotlib.pyplot as plt

    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartAnnotation

    plan, document = complex_fixture('stacked-total')
    document['columns'].append('share')
    document['rows'][0].append(.3)
    document['rows'][1].append(.7)
    document['columnMeta']['share'] = {'unit': '%', 'isPercent': False}
    plan.charts[0].standard_value_fields = ('actual', 'budget')
    plan.charts[0].standard_label_fields = ('share',)
    plan.charts[0].standard_annotations = (StandardChartAnnotation(kind='values', series='actual'),)
    inputs = materialization(document)
    (tmp_path / 'input.json').write_bytes(inputs.files[0].content)
    monkeypatch.chdir(tmp_path)
    close = plt.close
    monkeypatch.setattr(plt, 'close', lambda *args: None)
    try:
        script = standard_visualization_script(plan, inputs)
        assert script is not None
        exec(script, {})
        axes = plt.gcf().axes[0]
        assert list(axes.lines[0].get_ydata()) == [30, 70]
        assert '服务端求和' in axes.lines[0].get_label()
        assert 'share: 30.00%' in axes.texts[0].get_text()
        assert axes.texts[0].get_text().startswith('10.00元')
    finally:
        close('all')


def test_display_unit_conversion_uses_registered_scale(tmp_path, monkeypatch):
    import matplotlib.pyplot as plt

    plan, _ = fixture('bar')
    plan.charts[0].standard_display_unit = '亿元'
    document = {'columns': ['label', 'value'], 'rows': [['A', 100_000_000], ['B', 200_000_000]],
                'columnMeta': {'value': {'unit': '元'}}}
    inputs = materialization(document)
    (tmp_path / 'input.json').write_bytes(inputs.files[0].content)
    monkeypatch.chdir(tmp_path)
    close = plt.close
    monkeypatch.setattr(plt, 'close', lambda *args: None)
    try:
        exec(standard_visualization_script(plan, inputs), {})
        axes = plt.gcf().axes[0]
        assert [bar.get_height() for bar in axes.patches] == [1, 2]
        assert axes.get_ylabel() == '亿元'
    finally:
        close('all')
    plan.charts[0].standard_display_unit = '人次'
    assert standard_visualization_script(plan, inputs) is None


@pytest.mark.parametrize('kind', ['summary', 'window', 'independent_total'])
def test_report_gap_templates_render_exact_frozen_views(tmp_path, monkeypatch, kind):
    import matplotlib.pyplot as plt

    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartSource

    plan, document = complex_fixture('bar')
    chart = plan.charts[0]
    if kind == 'summary':
        chart.visual_form = 'summary-bars'
        chart.standard_value_fields = ('budget', 'actual')
        document = {'columns': ['budget', 'actual', 'difference'], 'rows': [[100, 80, -20]],
                    'columnMeta': {field: {'unit': '元'} for field in ('budget', 'actual', 'difference')}}
        inputs = materialization(document)
    elif kind == 'window':
        chart.standard_labels = ('2025-02',)
        inputs = materialization(document)
    else:
        chart.visual_form = 'stacked-total'
        chart.standard_total_field = 'total'
        chart.standard_sources = tuple(StandardChartSource.model_validate(item) for item in [
            {'sourceIndex': 0, 'labelField': 'period', 'valueField': 'value', 'seriesName': 'A',
             'categoryField': 'department', 'categoryValue': 'A'},
            {'sourceIndex': 0, 'labelField': 'period', 'valueField': 'value', 'seriesName': 'B',
             'categoryField': 'department', 'categoryValue': 'B'},
            {'sourceIndex': 1, 'labelField': 'period', 'valueField': 'value', 'seriesName': 'total'},
        ])
        _, first = complex_fixture('line', long=True)
        second = {'columns': ['period', 'value'], 'rows': [['2025-02', 70], ['2025-01', 30]],
                  'columnMeta': {'value': {'unit': '元'}}}
        files = tuple(ChartInputFile(f'input-{i}.json', json.dumps(doc).encode())
                      for i, doc in enumerate((first, second)))
        entries = tuple({'chartId': chart.chart_id, 'path': file.path, 'sha256': file.sha256} for file in files)
        inputs = ChartInputMaterialization(files=files, entries=entries)
    for source in inputs.files:
        (tmp_path / source.path).write_bytes(source.content)
    monkeypatch.chdir(tmp_path)
    close = plt.close
    monkeypatch.setattr(plt, 'close', lambda *args: None)
    try:
        script = standard_visualization_script(plan, inputs)
        assert script is not None
        exec(script, {})
        axes = plt.gcf().axes[0]
        if kind == 'summary':
            assert [bar.get_height() for bar in axes.patches] == [100, 80]
            assert [tick.get_text() for tick in axes.get_xticklabels()] == ['budget', 'actual']
        elif kind == 'window':
            assert [bar.get_height() for bar in axes.patches] == [30, 40]
            assert [tick.get_text() for tick in axes.get_xticklabels()] == ['2025-02']
        else:
            assert list(axes.lines[0].get_ydata()) == [30, 70]
            assert len(axes.patches) == 4
            assert '独立冻结总额' in axes.lines[0].get_label()
            second['rows'][0][1] = 71
            changed = ChartInputFile(files[1].path, json.dumps(second).encode())
            entries[1]['sha256'] = changed.sha256
            assert standard_visualization_script(plan, ChartInputMaterialization(
                files=(files[0], changed), entries=entries,
            )) is None
        assert (tmp_path / 'chart.png').exists()
    finally:
        close('all')


def test_layout_wraps_labels_and_separates_colliding_annotation_text(tmp_path, monkeypatch):
    import matplotlib.pyplot as plt
    from matplotlib.text import Annotation, Text

    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartAnnotation

    plan, _ = fixture('barh')
    label = '这是一个需要换行显示的非常长的业务条线名称'
    document = {'columns': ['label', 'value'], 'rows': [[label, 100], ['其他业务', 50]],
                'columnMeta': {'value': {'unit': '元'}}}
    plan.charts[0].standard_annotations = (
        StandardChartAnnotation(kind='values'),
        StandardChartAnnotation(kind='peak'),
    )
    inputs = materialization(document)
    (tmp_path / 'input.json').write_bytes(inputs.files[0].content)
    monkeypatch.chdir(tmp_path)
    close = plt.close
    monkeypatch.setattr(plt, 'close', lambda *args: None)
    try:
        exec(standard_visualization_script(plan, inputs), {})
        fig = plt.gcf()
        fig.canvas.draw()
        axes = fig.axes[0]
        assert '\n' in axes.get_yticklabels()[0].get_text()
        assert [bar.get_width() for bar in axes.patches] == [100, 50]
        annotations = [text for text in axes.texts if isinstance(text, Annotation)]
        boxes = [Text.get_window_extent(text, fig.canvas.get_renderer()) for text in annotations]
        assert not any(left.overlaps(right) for index, left in enumerate(boxes) for right in boxes[index + 1:])
    finally:
        close('all')


@pytest.mark.parametrize('mode,layout', [('single', 'tight'), ('dual', 'constrained'), ('panels', 'manual')])
def test_standard_canvas_fixed_export_has_exact_pixels(tmp_path, monkeypatch, mode, layout):
    import matplotlib.pyplot as plt
    from PIL import Image

    from smart_reporting.reporting.workflow.runtime.phase_models import (
        StandardChartAxes,
        StandardChartCanvas,
    )

    plan, document = complex_fixture('line')
    plan.charts[0].standard_axes = StandardChartAxes(
        mode=mode, rightFields=('budget',) if mode == 'dual' else (),
    )
    plan.charts[0].standard_canvas = StandardChartCanvas(
        sizeMode='fixed', width=8, height=5, dpi=100, layout=layout, crop='canvas',
        left=.2, right=.9, bottom=.2, top=.85, tickFontSize=11, labelWrap=10,
    )
    inputs = materialization(document)
    (tmp_path / 'input.json').write_bytes(inputs.files[0].content)
    monkeypatch.chdir(tmp_path)
    close = plt.close
    monkeypatch.setattr(plt, 'close', lambda *args: None)
    try:
        exec(standard_visualization_script(plan, inputs), {})
        with Image.open(tmp_path / 'chart.png') as image:
            assert image.size == (800, 500)
        fig = plt.gcf()
        assert fig.dpi == 100
        assert fig.axes[-1].get_xticklabels()[0].get_fontsize() == 11
        if layout == 'manual':
            assert fig.subplotpars.left == .2
            assert fig.subplotpars.bottom == .2
    finally:
        close('all')


@pytest.mark.parametrize('options', [
    {'dpi': 500}, {'width': 100}, {'height': float('nan')},
    {'width': 20, 'height': 24, 'dpi': 240}, {'labelWrap': 0},
])
def test_standard_canvas_rejects_invalid_or_oversized_configuration(options):
    from pydantic import ValidationError

    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartCanvas

    with pytest.raises(ValidationError):
        StandardChartCanvas.model_validate(options)


@pytest.mark.parametrize('form', ['bar', 'line', 'barh'])
def test_standard_template_executes_and_rejects_changed_input(tmp_path, form):
    plan, inputs = fixture(form)
    script = standard_visualization_script(plan, inputs)
    assert script is not None
    (tmp_path / 'input.json').write_bytes(inputs.files[0].content)
    (tmp_path / 'draw.py').write_text(script)
    completed = subprocess.run([sys.executable, 'draw.py'], cwd=tmp_path, capture_output=True)
    assert completed.returncode == 0, completed.stderr.decode()
    assert (tmp_path / 'chart.png').read_bytes().startswith(b'\x89PNG')
    (tmp_path / 'input.json').write_text('{}')
    completed = subprocess.run([sys.executable, 'draw.py'], cwd=tmp_path, capture_output=True)
    assert completed.returncode != 0
    assert b'identity changed' in completed.stderr


@pytest.mark.parametrize('form,mode', [
    ('line', 'single'), ('bar', 'single'), ('barh', 'single'),
    ('stacked-bar', 'single'), ('stacked-area', 'single'),
    ('line', 'dual'), ('bar', 'panels'), ('line', 'zoom'),
])
def test_model_can_combine_style_with_complex_layout_without_changing_values(tmp_path, monkeypatch, form, mode):
    import matplotlib.colors as colors
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure

    from smart_reporting.reporting.workflow.runtime.phase_models import (
        StandardChartAnnotation,
        StandardChartAxes,
        StandardChartStyle,
    )

    plan, document = complex_fixture(form)
    chart = plan.charts[0]
    chart.standard_axes = StandardChartAxes(mode=mode, rightFields=['budget'] if mode == 'dual' else [],
                                           zoomBounds=[.08, .5, .4, .35],
                                           zoomStart='2025-01' if mode == 'zoom' else None,
                                           zoomEnd='2025-02' if mode == 'zoom' else None)
    chart.standard_annotations = (StandardChartAnnotation(kind='peak', series='actual'),)
    chart.standard_style = StandardChartStyle.model_validate({
        'palette': 'cividis', 'background': '#fafafa', 'grid': 'both',
        'labelRotation': 0, 'legendColumns': 2, 'decimals': 0,
        'annotationOffsetX': 15, 'annotationOffsetY': 20, 'annotationFontSize': 12,
        'titleFontSize': 18, 'series': [
            {'series': 'actual', 'color': '#cc3311', 'lineStyle': '--',
             'lineWidth': 3, 'marker': 's', 'alpha': .7, 'hatch': '//'},
        ],
    })
    inputs = materialization(document)
    original = inputs.files[0].content
    (tmp_path / 'input.json').write_bytes(original)
    monkeypatch.chdir(tmp_path)
    close = plt.close
    monkeypatch.setattr(plt, 'close', lambda *args: None)
    saved = []
    savefig = Figure.savefig

    def capture_savefig(figure, *args, **kwargs):
        saved.append(figure)
        return savefig(figure, *args, **kwargs)

    monkeypatch.setattr(Figure, 'savefig', capture_savefig)
    try:
        script = standard_visualization_script(plan, inputs)
        assert script is not None
        exec(script, {})
        fig = saved[-1]
        ax = fig.axes[0]
        assert colors.to_hex(fig.get_facecolor()) == '#fafafa'
        assert fig.axes[-1].get_xticklabels()[0].get_rotation() == 0
        assert ax.texts[0].get_fontsize() == 12
        assert ax.texts[0].get_position() == (15, 20)
        assert '30元' in ax.texts[0].get_text()
        if form == 'line':
            line = ax.lines[0]
            assert list(line.get_ydata()) == [10, 30]
            assert colors.to_hex(line.get_color()) == '#cc3311'
            assert line.get_linestyle() == '--'
            assert line.get_marker() == 's'
            assert line.get_linewidth() == 3
            if mode == 'zoom':
                inset_line = ax.child_axes[0].lines[0]
                assert colors.to_hex(inset_line.get_color()) == '#cc3311'
                assert list(inset_line.get_ydata()) == [10, 30]
                inset = ax.child_axes[0].get_position()
                parent = ax.get_position()
                assert (inset.x0 - parent.x0) / parent.width == pytest.approx(.08)
        elif form != 'stacked-area':
            bars = ax.containers[0].patches
            assert [bar.get_width() if form == 'barh' else bar.get_height() for bar in bars] == [10, 30]
            assert bars[0].get_hatch() == '//'
            assert colors.to_hex(bars[0].get_facecolor()) == '#cc3311'
        assert (tmp_path / 'input.json').read_bytes() == original
        assert (tmp_path / 'chart.png').stat().st_size > 1000
    finally:
        close('all')


def test_unknown_series_style_falls_back_instead_of_silently_ignoring_model_choice():
    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartStyle

    plan, inputs = fixture()
    plan.charts[0].standard_style = StandardChartStyle.model_validate({'series': [{'series': 'invented'}]})
    assert standard_visualization_script(plan, inputs) is None


@pytest.mark.parametrize('options', [
    {'series': [{'series': 'value', 'color': 'red; code'}]},
    {'series': [{'series': 'value'}, {'series': 'value'}]},
    {'annotationOffsetY': 10000}, {'decimals': -1}, {'valueMargin': float('nan')},
])
def test_style_schema_rejects_invalid_parameters(options):
    from pydantic import ValidationError

    from smart_reporting.reporting.workflow.runtime.phase_models import StandardChartStyle

    with pytest.raises(ValidationError):
        StandardChartStyle.model_validate(options)


@pytest.mark.parametrize('fault', ['complex', 'identity', 'fallback', 'renderer'])
def test_unsupported_or_unverified_inputs_do_not_select_standard_route(fault):
    plan, inputs = fixture()
    if fault == 'complex':
        plan.charts[0].visual_form = '双轴组合图'
    elif fault == 'renderer':
        plan.charts[0].renderer = 'plotly'
    elif fault == 'identity':
        inputs.entries[0]['sha256'] = '0' * 64
    else:
        inputs = ChartInputMaterialization(fallback_chart_ids=frozenset({'chart_001'}))
    assert standard_visualization_script(plan, inputs) is None


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('failed_stage', [None, 'write_script', 'run_script', 'view_image', 'submit_script'])
async def test_standard_execution_keeps_all_existing_gates(monkeypatch, failed_stage):
    from smart_reporting.reporting.workflow.runtime import code_generation as module

    receipt = SimpleNamespace(source_file='signed-script')
    review = {'code': 'visual_review_failed', 'details': {'issues': ['label_overlap']}}
    binding = SimpleNamespace(execution_receipt=receipt, visual_inspection_receipts={},
                              visual_repair_diagnostic=review)

    @asynccontextmanager
    async def bind(*args):
        yield binding

    toolkit = SimpleNamespace(**{
        stage: AsyncMock(return_value={'ok': stage != failed_stage})
        for stage in ('write_script', 'run_script', 'view_image', 'submit_script')
    }, require_current_receipt=AsyncMock(), refresh_delivery_state=AsyncMock())
    monkeypatch.setattr(module, 'ReportingCodeModeToolkit', lambda *args, **kwargs: toolkit)
    runner = object.__new__(module.ReportingCodeGenerationRunner)
    runner.registry = SimpleNamespace(bind=bind)
    runner.code_mode_runtime = SimpleNamespace(shutdown=AsyncMock())
    runner.vision_reviewer = object()
    runner.lsp_manager = None
    context = SimpleNamespace(declared_output_paths=('chart.png',), code_mode_session_id='session')
    if failed_stage:
        with pytest.raises(module.ReportingError, match='标准可视化') as captured:
            await runner.run_standard_visualization(context, object(), 'source', {})
        assert captured.value.details['standardDiagnostic'] == review
        toolkit.require_current_receipt.assert_not_called()
    else:
        result = await runner.run_standard_visualization(context, object(), 'source', {})
        assert result.execution_receipt is receipt
        toolkit.require_current_receipt.assert_awaited_once_with(receipt)
    runner.code_mode_runtime.shutdown.assert_awaited_once_with('session')
