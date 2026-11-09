"""P0 回归：复用冻结审计输入，检查真实文字和显示坐标中的数据路径。"""
import json
from pathlib import Path

import pytest

from scripts.replay_standard_visualization_variants import plan_from_saved
from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_script,
)

EVIDENCE = Path(__file__).parent / 'fixtures' / 'standard_line_layout'


def render_saved_case(case, tmp_path, monkeypatch, *, mode=None):
    import matplotlib.pyplot as plt

    folder = EVIDENCE / case
    parameters = json.loads((folder / 'parameters.json').read_text())
    if mode is not None:
        parameters['standard_axes']['mode'] = mode
    plan = plan_from_saved(parameters)
    source = ChartInputFile('input-0.json', (folder / 'input-0.json').read_bytes())
    inputs = ChartInputMaterialization(files=(source,), entries=({
        'chartId': parameters['chart_id'], 'path': source.path, 'sha256': source.sha256,
    },))
    (tmp_path / source.path).write_bytes(source.content)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(plt, 'close', lambda *args: None)
    script = standard_visualization_script(plan, inputs)
    assert script is not None
    namespace = {}
    exec(script, namespace)
    return plt.gcf(), namespace


@pytest.mark.parametrize('mode', ['single', 'panels'])
def test_missing_note_uses_registered_chinese_series_label(tmp_path, monkeypatch, mode):
    import matplotlib.pyplot as plt

    close = plt.close
    try:
        fig, _ = render_saved_case('unit-negative-long-chinese', tmp_path, monkeypatch, mode=mode)
        notes = [text.get_text() for ax in fig.axes for text in ax.texts if '缺失' in text.get_text()]
        assert len(notes) == 1
        assert '实际收入' in notes[0] and '未上报科室' in notes[0]
        assert 'actual' not in notes[0]
        values = [patch.get_width() for ax in fig.axes for container in ax.containers for patch in container]
        assert any(value == pytest.approx(-123.4567) for value in values)
        assert any(value == pytest.approx(987.6543) for value in values)
        assert (tmp_path / 'standard.png').read_bytes().startswith(b'\x89PNG')
    finally:
        close('all')


@pytest.mark.parametrize('obstacle', ['reference', 'secondary_axis', 'axes_transform', 'clipped', 'nan_gap'])
def test_line_layout_respects_transforms_clipping_strokes_and_gaps(tmp_path, monkeypatch, obstacle):
    import matplotlib.pyplot as plt
    from matplotlib.text import Text
    from matplotlib.transforms import Bbox

    close = plt.close
    try:
        _, namespace = render_saved_case('percent-fraction-scale', tmp_path, monkeypatch)
        policy = namespace['CONFIGS'][0][-1]
        policy['layout'] = 'manual'
        policy['left'], policy['right'], policy['bottom'], policy['top'] = .2, .8, .2, .8
        fig, ax = plt.subplots(figsize=(8, 6), dpi=100)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        if obstacle == 'secondary_axis':
            secondary = ax.twinx()
            secondary.set_ylim(0, 1000)
            line = secondary.axhline(500, linewidth=20)
        elif obstacle == 'nan_gap':
            line, = ax.plot([0, .25, float('nan'), .75, 1], [.5] * 5, linewidth=20,
                            transform=ax.transAxes)
        elif obstacle in {'axes_transform', 'clipped'}:
            y = -.08 if obstacle == 'clipped' else .5
            line, = ax.plot([0, 1], [y, y], linewidth=20, transform=ax.transAxes)
        else:
            line = ax.axhline(.5, linewidth=20)
        y = -.08 if obstacle == 'clipped' else .5
        annotation = ax.annotate('冻结值', (.5, y), xycoords='axes fraction',
                                 xytext=(0, 0), textcoords='offset points', ha='center', va='center')
        annotation._standard_custom_position = True
        namespace['finish_standard_layout'](fig, policy)
        fig.canvas.draw()
        if obstacle in {'clipped', 'nan_gap'}:
            assert annotation.get_position() == (0, 0)
        else:
            assert annotation.get_position() != (0, 0)
            bounds = Text.get_window_extent(annotation, fig.canvas.get_renderer())
            visible = Bbox.intersection(bounds.padded(line.get_linewidth() * fig.dpi / 144), line.get_clip_box())
            assert visible is None or not line.get_path().transformed(line.get_transform()).intersects_bbox(visible, filled=False)
    finally:
        close('all')


def test_negative_percent_annotation_avoids_real_transformed_data_line(tmp_path, monkeypatch):
    import matplotlib.pyplot as plt
    from matplotlib.text import Annotation, Text

    close = plt.close
    try:
        fig, _ = render_saved_case('percent-fraction-scale', tmp_path, monkeypatch)
        fig.canvas.draw()
        ax = fig.axes[0]
        assert list(ax.lines[0].get_ydata()) == [12.5, -5, 100]
        annotations = [text for text in ax.texts if isinstance(text, Annotation)]
        assert len(annotations) == 3
        for annotation in annotations:
            bounds = Text.get_window_extent(annotation, fig.canvas.get_renderer())
            for line in ax.lines:
                path = line.get_path().transformed(line.get_transform())
                padding = line.get_linewidth() * fig.dpi / 144
                assert not path.intersects_bbox(bounds.padded(padding), filled=False), annotation.get_text()
        assert (tmp_path / 'standard.png').read_bytes().startswith(b'\x89PNG')
    finally:
        close('all')
