"""复用已合并L1冻结输入，只比较既有Matplotlib布局参数。"""

import argparse
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

REPORT = Path(__file__).resolve().parent
PREVIOUS = REPORT.parent / '2026-11-09-standard-visualization-counterfactuals'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('counterfactual_replay', PREVIOUS / 'replay.py')
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    from matplotlib.figure import Figure

    original_save = Figure.savefig
    original = json.loads((PREVIOUS / 'evidence/final/L1/counterfactual/frozen.json').read_text())
    records = []
    for wrap in (8, 40):
        for layout in ('manual', 'tight', 'constrained'):
            state = deepcopy(original)
            state['plan']['charts'][0]['standardCanvas'].update(layout=layout, labelWrap=wrap)
            folder = output / f'wrap-{wrap}-{layout}'
            folder.mkdir()
            (folder / 'frozen.json').write_bytes(replay.encoded(state))
            for file in replay.materialize(state).files:
                (folder / file.path).write_bytes(file.content)
            plot_geometry = []

            def save_and_measure(figure, *args, **kwargs):
                result = original_save(figure, *args, **kwargs)
                plot_geometry[:] = [{'bbox_px': list(axis.bbox.bounds),
                    'xlim': list(axis.get_xlim()), 'ylim': list(axis.get_ylim()),
                    'tick_font_sizes': [tick.get_fontsize() for tick in axis.get_yticklabels()]}
                    for axis in figure.axes]
                return result

            with patch.object(Figure, 'savefig', save_and_measure):
                actual = replay.render(state, folder)
            actual['plot_geometry'] = plot_geometry
            assert actual['bar_values'] == [-12.0]
            assert ''.join(actual['category_labels']).replace('\n', '') == original['documents'][0]['rows'][0][0]
            assert actual['geometry']['canvas_px'] == [600, 450]
            assert not actual['geometry']['missing_glyphs']
            records.append({'variant': folder.name,
                'differences_from_frozen_L1_wrap8': replay.differences(original, state),
                'inputs': [replay.identity(file.path, file.content) for file in replay.materialize(state).files],
                'frozen': replay.identity('frozen.json', (folder / 'frozen.json').read_bytes()),
                'actual': actual, 'visual_review': 'not_run'})
            (output / 'results.json').write_bytes(replay.encoded(replay.normalize(records)))
    env = replay.environment()
    env['frozen_input_baseline_commit'] = env.pop('baseline_commit')
    env['baseline_commit'] = env['runner_commit']
    # environment()的runner身份指向被复用脚本，保留其真实相对来源。
    env['replay_source'] = env.pop('runner_script')
    env['replay_source']['path'] = str((PREVIOUS / 'replay.py').relative_to(REPORT.parent))
    env['probe_script'] = replay.identity('probe.py', Path(__file__).read_bytes())
    (output / 'environment.json').write_bytes(replay.encoded(env))
    print(json.dumps([{'variant': r['variant'], 'execution': r['actual'].get('execution'),
                       'outside': [text['text'] for text in r['actual']['geometry']['texts'] if text['outside_canvas']]}
                      for r in records], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
