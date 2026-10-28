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
    binding = SimpleNamespace(execution_receipt=receipt, visual_inspection_receipts={})

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
        with pytest.raises(module.ReportingError, match='标准可视化'):
            await runner.run_standard_visualization(context, object(), 'source', {})
        toolkit.require_current_receipt.assert_not_called()
    else:
        result = await runner.run_standard_visualization(context, object(), 'source', {})
        assert result.execution_receipt is receipt
        toolkit.require_current_receipt.assert_awaited_once_with(receipt)
    runner.code_mode_runtime.shutdown.assert_awaited_once_with('session')
