"""有限合成反事实；只在新输出目录运行，不覆盖已保存证据。"""

# ruff: noqa: E402 -- 独立运行时先定位仓库并固定Agg后端。

import argparse
import hashlib
import json
import locale
import math
import os
import platform
import subprocess
import sys
import tempfile
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from loguru import logger
from matplotlib import font_manager
from matplotlib.ft2font import FT2Font
from matplotlib.text import Text

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    ChartDraft,
    StandardChartDerivation,
    VisualizationPlanDraft,
)
from smart_reporting.reporting.workflow.runtime.standard_chart_alignment import align_chart_sources
from smart_reporting.reporting.workflow.runtime.standard_chart_encoding import scaled_column
from smart_reporting.reporting.workflow.runtime.standard_chart_pagination import (
    expand_standard_pagination,
)
from smart_reporting.reporting.workflow.runtime.standard_chart_transform import (
    transform_chart_document,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
    _validate_visualization_plan_bindings,
)

BASELINE = '7550d1da392dcf928e81c3b8478b953c49c433b5'


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def normalize(value):
    """缺失柱的Matplotlib NaN按JSON null保存；原始语义由oracle断言。"""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    return value


def identity(path, raw):
    return {'path': str(path), 'size': len(raw), 'sha256': sha(raw)}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def differences(before, after, path=''):
    if type(before) is not type(after):
        return [path]
    if isinstance(before, dict):
        return [item for key in sorted(before.keys() | after.keys())
                for item in (differences(before[key], after[key], f'{path}/{key}')
                             if key in before and key in after else [f'{path}/{key}'])]
    if isinstance(before, list):
        if len(before) != len(after):
            return [path]
        return [item for i, (a, b) in enumerate(zip(before, after, strict=True))
                for item in differences(a, b, f'{path}/{i}')]
    return [] if before == after else [path]


def plan(**options):
    values = dict(chartId='synthetic', sourcePath='chart.png', title='合成数据：金额对照',
        altText='合成类别金额，负数与缺失保持原义', citationIds=['synthetic'], metricCodes=['synthetic'],
        currentPeriod='2025-01', sourceDatasetId='synthetic', aggregationGrain='category',
        visualForm='barh', standardForm='barh', standardLabelField='label', standardValueFields=['value'],
        dataBindings=[{'analysisId': 'synthetic', 'factPath': 'facts.json', 'dataPath': 'rows',
                       'fields': ['label', 'value'], 'role': '合成冻结数据'}])
    values.update(options)
    return VisualizationPlanDraft(charts=(ChartDraft.model_validate(values),))


def setup(documents, chart_plan, **extra):
    return {'documents': deepcopy(documents), 'plan': chart_plan.model_dump(mode='json', by_alias=True), **extra}


def materialize(state):
    files = tuple(ChartInputFile(f'input-{i}.json', encoded(doc)) for i, doc in enumerate(state['documents']))
    return ChartInputMaterialization(files=files, entries=tuple(
        {'chartId': 'synthetic', 'path': file.path, 'sha256': file.sha256} for file in files))


def document(values, unit='元', **meta):
    return {'columns': ['label', 'value'], 'rows': [[f'合成类别{i+1}', value] for i, value in enumerate(values)],
            'columnMeta': {'value': {'unit': unit, **meta}}}


def close_enough(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected, strict=True):
        if expected_value is None:
            assert actual_value is None
        else:
            assert actual_value is not None and math.isclose(actual_value, float(expected_value), rel_tol=1e-12, abs_tol=1e-12)


def measure(figure):
    figure.canvas.draw()
    renderer, canvas = figure.canvas.get_renderer(), figure.bbox
    texts, fonts, missing = [], {}, []
    for artist in figure.findobj(Text):
        if not artist.get_visible() or not artist.get_text().strip():
            continue
        box = artist.get_window_extent(renderer)
        path = Path(font_manager.findfont(artist.get_fontproperties(), fallback_to_default=False))
        fonts[path.name] = identity(path.name, path.read_bytes())
        cmap = FT2Font(str(path)).get_charmap()
        missing.extend(sorted({char for char in artist.get_text() if not char.isspace() and ord(char) not in cmap}))
        texts.append({'text': artist.get_text(), 'bbox': list(box.bounds),
                      'outside_canvas': not (box.x0 >= canvas.x0 and box.y0 >= canvas.y0
                          and box.x1 <= canvas.x1 and box.y1 <= canvas.y1)})
    overlaps = []
    for i, first in enumerate(texts):
        ax, ay, aw, ah = first['bbox']
        for second in texts[i+1:]:
            bx, by, bw, bh = second['bbox']
            if min(ax+aw, bx+bw) > max(ax, bx) and min(ay+ah, by+bh) > max(ay, by):
                overlaps.append([first['text'], second['text']])
    return {'canvas_px': [canvas.width, canvas.height], 'texts': texts, 'fonts': fonts,
            'missing_glyphs': sorted(set(missing)), 'text_bbox_intersections': overlaps,
            'limitation': 'bbox相交不等于感知遮挡；未测全部图元；未进行独立视觉审查'}


def render(state, folder):
    inputs = materialize(state)
    chart_plan = VisualizationPlanDraft.model_validate(state['plan'])
    result = standard_visualization_preflight(chart_plan, inputs)
    answer = {'preflight_diagnostic': result.diagnostic, 'warnings': result.warnings}
    if result.source is None:
        return answer
    (folder / 'compiled.py').write_text(result.source)
    answer['compiled_script'] = identity('compiled.py', result.source.encode())
    with tempfile.TemporaryDirectory(prefix='sr-counterfactual-') as directory:
        previous = Path.cwd()
        original_close = plt.close
        try:
            os.chdir(directory)
            for file in inputs.files:
                Path(file.path).write_bytes(file.content)
            with patch.object(plt, 'close', lambda *args: None):
                try:
                    exec(compile(result.source, 'compiled.py', 'exec'), {})
                    answer['execution'] = 'rendered'
                except ValueError as error:
                    answer['execution'] = 'rejected'
                    answer['error'] = str(error)
            assert plt.get_fignums(), 'No figure available for measurement'
            figure = plt.figure(plt.get_fignums()[-1])
            answer['geometry'] = measure(figure)
            axis = figure.axes[0]
            answer['bar_values'] = [float(bar.get_width()) for container in axis.containers for bar in container]
            answer['category_labels'] = [tick.get_text() for tick in axis.get_yticklabels()]
            answer['value_axis_label'] = axis.get_xlabel()
            for file in inputs.files:
                assert Path(file.path).read_bytes() == file.content
            if Path('chart.png').exists():
                raw = Path('chart.png').read_bytes()
                filename = 'chart.png'
            else:
                filename = 'rejected-debug.png'
                figure.savefig(folder / filename, dpi=figure.dpi)
                raw = (folder / filename).read_bytes()
            (folder / filename).write_bytes(raw)
            answer['image'] = identity(filename, raw)
        finally:
            os.chdir(previous)
            original_close('all')
    return answer


def align(state, _folder):
    inputs = materialize(state)
    chart = VisualizationPlanDraft.model_validate(state['plan']).charts[0]
    diagnostics = []
    result = align_chart_sources(inputs.entries, inputs.files, chart.standard_sources, diagnostics=diagnostics)
    return {'document': result[0] if result else None, 'identities': result[1] if result else [],
            'diagnostics': diagnostics}


def bind(state, _folder):
    events = []
    sink = logger.add(lambda message: events.append({'message': message.record['message'],
                                                    'extra': message.record['extra']}))
    try:
        result = _validate_visualization_plan_bindings(VisualizationPlanDraft.model_validate(state['plan']), state['facts'])
    finally:
        logger.remove(sink)
    return {'binding': result.charts[0].data_bindings[0].model_dump(mode='json', by_alias=True), 'events': events}


def pages(state, _folder):
    inputs = materialize(state)
    expanded = expand_standard_pagination(VisualizationPlanDraft.model_validate(state['plan']), inputs)
    return {'pages': expanded.model_dump(mode='json', by_alias=True),
            'input_sha256': inputs.files[0].sha256}


def environment():
    paths = ['uv.lock', 'pyproject.toml', 'smart_reporting/reporting/units.py']
    paths += git('ls-files', 'smart_reporting/reporting/workflow/runtime/*.py').splitlines()
    paths += ['smart_reporting/reporting/slides_engine/package-lock.json',
              'smart_reporting/reporting/workbook_engine/package-lock.json']
    return {'baseline_commit': BASELINE, 'runner_commit': git('rev-parse', 'HEAD'),
            'runner_script': identity('replay.py', Path(__file__).read_bytes()),
            'python': sys.version, 'platform': platform.platform(), 'machine': platform.machine(),
            'os_release': platform.freedesktop_os_release(), 'locale': locale.setlocale(locale.LC_ALL, None),
            'available_locales': subprocess.check_output(['locale', '-a'], text=True).splitlines(),
            'node': subprocess.check_output(['node', '--version'], text=True).strip(),
            'backend': matplotlib.get_backend(),
            'installed_distributions': sorted((d.metadata['Name'], d.version) for d in metadata.distributions()),
            'source_and_lock_identities': [identity(path, (ROOT / path).read_bytes()) for path in paths],
            'flint': {'commit': 'a794557384adcc3293a77043f6b9aff1c33d152c',
                      'upstream_tests': 'not_run: no installed local dependencies; no installation attempted'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='必须是尚不存在的输出目录')
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / 'environment.json').write_bytes(encoded(environment()))
    records = []

    def pair(case, intent, before, after, changed, operation, verify):
        actual_changes = differences(before, after)
        assert actual_changes == [changed], (case, actual_changes)
        values = []
        for variant, state in [('control', before), ('counterfactual', after)]:
            folder = output / case / variant
            folder.mkdir(parents=True)
            frozen = encoded(state)
            (folder / 'frozen.json').write_bytes(frozen)
            inputs = materialize(state)
            input_ids = []
            for file in inputs.files:
                (folder / file.path).write_bytes(file.content)
                input_ids.append(identity(file.path, file.content))
            plan_raw = encoded(state['plan'])
            (folder / 'plan.json').write_bytes(plan_raw)
            actual = operation(state, folder)
            record = {'case': case, 'variant': variant, 'business_intent': intent,
                      'changed_path': changed, 'frozen': identity('frozen.json', frozen),
                      'inputs': input_ids, 'plan': identity('plan.json', plan_raw),
                      'actual': actual, 'visual_review': 'not_run', 'production_run': False,
                      'model_calls': 0, 'performance_inference': 'not_applicable'}
            records.append(record)
            values.append(actual)
            # 先保存观测，再做断言；失败时仍可审查原始反例。
            (output / 'results.jsonl').write_text(''.join(json.dumps(normalize(r), ensure_ascii=False, allow_nan=False) + '\n' for r in records))
        verify(*values)
        for record in records[-2:]:
            record['pair_assertions'] = 'passed'

    def check_render(actual, expected):
        assert actual['execution'] == 'rendered'
        close_enough(actual['bar_values'], expected)
        assert not actual['geometry']['missing_glyphs']

    money = setup([document([250000, -12500, 0, None])], plan(standardDisplayUnit='元', standardAxes={'allowNulls': True}))
    wan = deepcopy(money)
    wan['plan']['charts'][0]['standardDisplayUnit'] = '万元'

    def check_money(a, b):
        # Decimal oracle 不读取生产倍率表。
        close_enough(scaled_column(money['documents'][0], 'value', '元', True)[0], [250000, -12500, 0, None])
        close_enough(scaled_column(money['documents'][0], 'value', '万元', True)[0],
                     [Decimal('250000')/Decimal('10000'), Decimal('-12500')/Decimal('10000'), Decimal(0), None])
        # 模板将缺失柱保留为NaN，不将其当成0；其余几何独立检查。
        for actual, expected in [(a, [250000, -12500, 0]), (b, [25, -1.25, 0])]:
            assert actual['execution'] == 'rendered'
            close_enough(actual['bar_values'][:3], expected)
            assert len(actual['bar_values']) == 4 and math.isnan(actual['bar_values'][3])
        assert '万元' in b['value_axis_label']

    pair('U1', '同一金额只改显示单位，保留符号与缺失', money, wan,
         '/plan/charts/0/standardDisplayUnit', render, check_money)

    compound = setup([document([250, -12.5], '元/人次')], plan(standardDisplayUnit='元/人次'))
    compound_wan = deepcopy(compound)
    compound_wan['plan']['charts'][0]['standardDisplayUnit'] = '万元/人次'

    def check_compound(a, b):
        check_render(a, [Decimal('250'), Decimal('-12.5')])
        assert '元/人次' in a['value_axis_label']
        assert b['preflight_diagnostic'] is not None and 'execution' not in b

    pair('U2', '复合单位保留分母；未登记换算不猜倍率', compound, compound_wan,
         '/plan/charts/0/standardDisplayUnit', render, check_compound)

    ratio_doc = {'columns': ['label', 'value', 'base'], 'rows': [['一月', 1, 8], ['二月', 2, 0], ['三月', None, 4]],
                 'columnMeta': {'value': {'unit': '元'}, 'base': {'unit': '元'}}}
    ratio = setup([ratio_doc], plan(standardDerivations=[{'kind': 'ratio_percent', 'name': '占比', 'numerator': 'value', 'denominator': 'base'}]))
    wrong_unit = deepcopy(ratio)
    wrong_unit['documents'][0]['columnMeta']['base']['unit'] = '人次'

    def transform(state, _folder):
        try:
            transformed = transform_chart_document(state['documents'][0], None,
                [StandardChartDerivation.model_validate(state['plan']['charts'][0]['standardDerivations'][0])])
            return {'document': transformed}
        except ValueError as error:
            return {'error': str(error), 'error_type': type(error).__name__}

    def check_ratio(a, b):
        close_enough([row[-1] for row in a['document']['rows']], [Fraction(1, 8)*100, None, None])
        assert b['error_type'] == 'ValueError' and b['error'] == 'Incompatible derivation units'

    pair('U3', '仅同量纲可派生占比；零分母和缺失为null', ratio, wrong_unit,
         '/documents/0/columnMeta/base/unit', transform, check_ratio)

    percent = setup([document([0.125], '%', isPercent=True)], plan(standardDisplayUnit='%'))
    fraction = deepcopy(percent)
    fraction['documents'][0]['columnMeta']['value']['isPercent'] = False

    def check_percent(a, b):
        check_render(a, [Decimal('0.125')])
        check_render(b, [Fraction(1, 8)*100])

    pair('U4', '显式百分数/小数尺度，不从列名猜测', percent, fraction,
         '/documents/0/columnMeta/value/isPercent', render, check_percent)

    sources = [dict(sourceIndex=i, labelField='label', valueField='value', seriesName=name,
                    labelMode='month_of_year', periodYear=year)
               for i, name, year in [(0, '本期', 2025), (1, '同期', 2024)]]
    current, previous = document([10, 20]), document([18, 9])
    current['rows'] = [['2025-01', 10], ['2025-02', 20]]
    previous['rows'] = [['2024-02', 18], ['2024-01', 9]]
    aligned = setup([current, previous], plan(standardValueFields=['本期', '同期'], standardSources=sources,
                    comparisonType='yoy', comparisonPeriod='2024-01至2024-02'))

    def check_alignment(a):
        assert a['document']['rows'] == [['01', 10, 9], ['02', 20, 18]]
        assert set(a['document']['columnMeta']['同期']['periods']) == {'2024-01', '2024-02'}

    year = deepcopy(aligned)
    year['plan']['charts'][0]['standardSources'][1]['periodYear'] = 2023

    def check_year(a, b):
        check_alignment(a)
        assert b['diagnostics'] == [{'reason': 'source_period_year_mismatch', 'sourceIndex': 1}]

    pair('P1', '逆序来源按月对齐且保留真实年份', aligned, year,
         '/plan/charts/0/standardSources/1/periodYear', align, check_year)
    month = deepcopy(aligned)
    month['documents'][1]['rows'][0][0] = '2024-03'

    def check_month(a, b):
        check_alignment(a)
        assert b['diagnostics'] == [{'reason': 'source_label_sets_differ', 'sourceIndex': 1}]

    pair('P2', '同期月份必须对应，不能仅凭同列/同值接受', aligned, month,
         '/documents/1/rows/0/0', align, check_month)
    note = deepcopy(aligned)
    note['documents'][1]['researchNote'] = '无业务含义的合成备注'

    def check_note(a, b):
        check_alignment(a)
        assert a['document'] == b['document'] and a['identities'] != b['identities']

    pair('P3', '无关元数据改变身份，但不改变对齐结果', aligned, note,
         '/documents/1/researchNote', align, check_note)

    facts = {'visualizationFacts': [{'analysisId': 'synthetic', 'factFile': {'path': 'facts.json'},
              'dataDescriptors': [{'dataPath': 'metrics[0].rows', 'fields': ['label', 'value']}],
              'supplementalEvidenceSources': [{'sourceFile': {'path': 'supplement.json'},
                  'dataDescriptors': [{'dataPath': 'findings[2].rows', 'fields': ['label', 'value']}]}]}]}
    binding = setup([], plan(dataBindings=[{'analysisId': 'synthetic', 'factPath': 'missing.json',
                    'dataPath': 'findings[2].rows', 'fields': ['label', 'value'], 'role': '同业务表'}]), facts=facts)
    registered = deepcopy(binding)
    registered['plan']['charts'][0]['dataBindings'][0]['factPath'] = 'facts.json'

    def check_registered(a, b):
        assert a['binding']['factPath'] == 'supplement.json'
        assert b['binding']['factPath'] == 'facts.json'
        assert any('binding_mismatch' in event['message'] for event in b['events'])

    pair('B1', '只有未登记文件可按唯一精确路径改指', binding, registered,
         '/plan/charts/0/dataBindings/0/factPath', bind, check_registered)
    ambiguous = deepcopy(binding)
    alternative = deepcopy(facts['visualizationFacts'][0]['supplementalEvidenceSources'][0])
    alternative['sourceFile']['path'] = 'another.json'
    ambiguous['facts']['visualizationFacts'][0]['supplementalEvidenceSources'].append(alternative)

    def check_ambiguous(a, b):
        assert a['binding']['factPath'] == 'supplement.json'
        assert b['binding']['factPath'] == 'missing.json'
        assert any('binding_mismatch' in event['message'] for event in b['events'])

    pair('B2', '增加同路径候选后不能凭同列自动选业务表', binding, ambiguous,
         '/facts/visualizationFacts/0/supplementalEvidenceSources', bind, check_ambiguous)

    long_label = '合成机构超长中文分类标签用于验证画布边缘完整显示'
    layout_doc = document([-12], '人次')
    layout_doc['rows'][0][0] = long_label
    wide_wrap = setup([layout_doc], plan(standardCanvas={'sizeMode': 'fixed', 'width': 4,
                      'height': 3, 'crop': 'canvas', 'layout': 'manual', 'labelWrap': 40}))
    short_wrap = deepcopy(wide_wrap)
    short_wrap['plan']['charts'][0]['standardCanvas']['labelWrap'] = 8

    def check_layout(a, b):
        assert a['execution'] == 'rejected' and '分类标签超出画布' in a['error']
        # 候选失败也保留结果，不能调整第二因素来凑通过。
        for actual in (a, b):
            close_enough(actual['bar_values'], [Decimal('-12')])
            assert ''.join(actual['category_labels']).replace('\n', '') == long_label
            assert not actual['geometry']['missing_glyphs']

    pair('L1', '只调整中文折行宽度，固定画布/数据域/负值', wide_wrap, short_wrap,
         '/plan/charts/0/standardCanvas/labelWrap', render, check_layout)

    paged = setup([document([-10000, 20000, 30000])], plan(standardDisplayUnit='万元', standardPagination={'pageSize': 2}))
    changed = deepcopy(paged)
    changed['documents'][0]['rows'][2][1] = 100000

    def check_pages(a, b):
        for result, upper in [(a, Decimal('3.4')), (b, Decimal('11.1'))]:
            charts = result['pages']['charts']
            assert len(charts) == 2
            assert charts[0]['standardDomains'] == charts[1]['standardDomains']
            assert math.isclose(charts[0]['standardDomains']['left']['max'], float(upper))
            assert [label for chart in charts for label in chart['standardLabels']] == [row[0] for row in paged['documents'][0]['rows']]
        assert a['input_sha256'] != b['input_sha256']
        inputs = materialize(changed)
        diagnostics = []
        chart = VisualizationPlanDraft.model_validate(aligned['plan']).charts[0]
        assert align_chart_sources([{'path': inputs.files[0].path, 'sha256': a['input_sha256']}],
            inputs.files, chart.standard_sources[:1], diagnostics=diagnostics) is None
        assert diagnostics == [{'reason': 'source_identity_mismatch', 'sourceIndex': 0}]
        b['stale_sha_injection'] = diagnostics

    pair('D1', '单格变化重算分页共享值域且拒用旧输入SHA', paged, changed,
         '/documents/0/rows/2/1', pages, check_pages)
    (output / 'results.jsonl').write_text(''.join(json.dumps(normalize(r), ensure_ascii=False, allow_nan=False) + '\n' for r in records))
    print(json.dumps({'pairs': len(records)//2, 'observations': len(records), 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
