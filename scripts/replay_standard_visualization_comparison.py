"""Offline manually configured comparison; run in repo with PYTHONPATH=. python SCRIPT ZIP OUTPUT."""
import hashlib
import json
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path
from types import SimpleNamespace

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
    _table_for_binding,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    ChartDataBinding,
    StandardChartAnnotation,
    StandardChartAxes,
    StandardChartCanvas,
    StandardChartPresentation,
    StandardChartSource,
    StandardChartStyle,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_script,
)


def main():
    archive_path, output_path = sys.argv[1:3]
    baseline = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else None
    output = Path(output_path).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if sys.version_info < (3, 14):
        import zstandard
        original = zipfile._get_decompressor
        zipfile._get_decompressor = lambda m: zstandard.ZstdDecompressor().decompressobj() if m == 93 else original(m)
    plt.rcParams['font.sans-serif'] = ['Noto Sans CJK SC', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    numbers = ['004', '005', '007', '009', '010', '012', '013', '014', '015']
    titles = ['医疗收入月度走势', '收入类型构成', '月度成本堆叠与独立总额', '院区成本分布',
              '门诊双系列趋势', '出院人次月度趋势', '全院预算与实际收入', '院区预算与实际收入', '业务条线完成率最低10条']
    notes = [
        '补齐月份简写、零基线、蓝色折线、副标题与来源说明；数据及亿元换算一致。使用统一报告字体、网格和无箭头标注。',
        '补齐绿色横向柱、金额/占比联合标注、副标题及来源说明。标准报告主题统一文字层级与留白。',
        '从登记事实继承总额单位后，七项堆叠与独立总额完成对账并成图；总额保持深色，分项分别绑定颜色。图例及来源脚注标准化。',
        '补齐绿色柱、亿元金额与占比、来源说明。统一报告主题保留真实量级；较小院区柱高差异不做夸大。',
        '从登记事实继承人次单位后，双来源对齐成图；仅取1—9月，换算万人次，门诊蓝色圆点、另一系列橙色方点，标注分别位于线上下。',
        '从登记事实继承单位，按万人次显示；峰值绿色、谷值红色，数值标注不重复，使用月份简写和来源说明。',
        '两柱分别为预算蓝、实际橙；增加冻结差额与完成率摘要徽章、副标题和来源说明，显示亿元金额。',
        '按原图倒序、预算蓝与实际橙；实际柱附冻结差额，并以同单位冻结实际/预算确定性计算执行率。统一图例与来源说明。',
        '按完成率升序选最低10项，预算/实际辅助标注换算亿元；整体参考线红色，条线绿色，补齐子集说明与来源说明。',
    ]
    records = []
    pages = []
    with zipfile.ZipFile(archive_path) as archive, PdfPages(output / 'comparison.pdf') as pdf:
        index = json.loads(archive.read(next(n for n in archive.namelist() if n.endswith('/trace-index-v1.json'))))
        resources = {f['resourceId']: f for f in index['files']}

        def registered(rid):
            identity = resources[rid]
            raw = archive.read(identity['path'])
            assert len(raw) == identity['size']
            assert hashlib.sha256(raw).hexdigest() == identity['sha256']
            return raw, identity

        for i, trace in enumerate(index['chartTraces']):
            number = numbers[i]
            folder = output / f'chart-{number}'
            folder.mkdir(exist_ok=True)
            raw_image, image_identity = registered(trace['imageFileResourceId'])
            (folder / 'original.png').write_bytes(raw_image)
            files, entries, documents, dependencies = [], [], [], []
            for j, rid in enumerate(trace['plotDataFileResourceIds']):
                raw, identity = registered(rid)
                name = f'input-{j}.json'
                frozen_raw = raw
                document = json.loads(raw)
                source_identity = document.get('source', {})
                # Reproject only from a source fact registered in this same trace index.
                # Old bytes remain as frozen-input; no unit is guessed from the picture.
                fact_rid = next((rid for rid, f in resources.items() if f['sha256'] == source_identity.get('sha256')), None)
                if fact_rid:
                    fact_raw, fact_identity = registered(fact_rid)
                    binding = ChartDataBinding(analysisId=source_identity['analysisId'], factPath=source_identity['path'],
                        dataPath=source_identity['dataPath'], fields=document['columns'], role=document['role'])
                    cols, rows, meta = _table_for_binding(json.loads(fact_raw), binding)
                    assert cols == document['columns'] and rows == document['rows']
                    if meta and meta != document.get('columnMeta'):
                        document = {**document, 'columnMeta': meta}
                        raw = (json.dumps(document, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
                        (folder / f'fact-{j}.json').write_bytes(fact_raw)
                        dependencies.append({'path': f'fact-{j}.json', 'sha256': fact_identity['sha256'], 'size': len(fact_raw), 'role': 'verified_metadata_source'})
                (folder / f'frozen-{name}').write_bytes(frozen_raw)
                (folder / name).write_bytes(raw)
                source = ChartInputFile(name, raw)
                files.append(source)
                entries.append({'chartId': trace['chartId'], 'path': name, 'sha256': source.sha256})
                documents.append(json.loads(raw))
                dependencies.append({'path': f'frozen-{name}', 'sha256': identity['sha256'], 'size': len(frozen_raw), 'role': 'original_registered_input'})
                dependencies.append({'path': name, 'sha256': source.sha256, 'size': len(raw)})
            chart = SimpleNamespace(chart_id=trace['chartId'], renderer='matplotlib', interactive_path=None,
                visual_form='bar', source_path='standard.png', title=titles[i],
                standard_canvas=StandardChartCanvas(sizeMode='fixed', width=12, height=7, dpi=150, labelWrap=18),
                standard_style=StandardChartStyle(labelRotation=0, annotationFontSize=9, titleFontSize=15,
                                                 annotationOffsetX=4, annotationOffsetY=10, valueMargin=.25))
            values, annotations = [], []
            if i == 0:
                chart.visual_form = 'line'
                values = ['医疗收入金额']
                chart.standard_display_unit = '亿元'
            elif i == 1:
                chart.visual_form = 'barh'
                values = ['医疗收入金额']
                chart.standard_display_unit = '亿元'
                chart.standard_label_fields = ('占比',)
            elif i == 2:
                chart.visual_form = 'stacked-total'
                categories = list(dict.fromkeys(row[1] for row in documents[0]['rows']))
                chart.standard_sources = tuple(StandardChartSource(sourceIndex=0, labelField='period', valueField='amount',
                    seriesName=name, categoryField='indicator_name', categoryValue=name) for name in categories) + (
                    StandardChartSource(sourceIndex=1, labelField='period', valueField='value', seriesName='月度独立总额'),)
                values = categories + ['月度独立总额']
                chart.standard_total_field = '月度独立总额'
            elif i == 3:
                values = ['成本金额']
                chart.standard_display_unit = '亿元'
                chart.standard_label_fields = ('占比',)
            elif i == 4:
                chart.visual_form = 'line'
                chart.standard_sources = (
                    StandardChartSource(sourceIndex=0, labelField='period', valueField='value', seriesName='门诊人次'),
                    StandardChartSource(sourceIndex=1, labelField='period', valueField='value', seriesName='不含体检及急诊门诊人次'))
                values = ['门诊人次', '不含体检及急诊门诊人次']
                chart.standard_labels = tuple(row[0] for row in documents[0]['rows'][:9])
            elif i == 5:
                chart.visual_form = 'line'
                values = ['value']
                chart.standard_labels = tuple(row[0] for row in documents[0]['rows'][:9])
            elif i == 6:
                chart.visual_form = 'summary-bars'
                values = ['预算医疗收入合计', '实际医疗收入合计']
                chart.standard_display_unit = '亿元'
            elif i == 7:
                chart.visual_form = 'barh'
                values = ['预算总医疗收入', '实际总医疗收入']
                chart.standard_display_unit = '亿元'
                chart.standard_style = StandardChartStyle(labelRotation=0, grid='x', annotationOffsetX=5,
                    annotationOffsetY=0, valueMargin=.25, legendColumns=2, legendLocation='lower right',
                    series=[{'series': values[0], 'color': '#4c72b0'}, {'series': values[1], 'color': '#dd8452'}])
            else:
                chart.visual_form = 'barh'
                values = ['完成率(%)']
                field_index = documents[0]['columns'].index(values[0])
                valid = [row for row in documents[0]['rows'] if isinstance(row[field_index], (float, int))]
                selected = sorted(valid, key=lambda row: row[field_index])[:10]
                chart.standard_labels = tuple(row[0] for row in selected)
            if i not in (2, 4):
                annotations = [{'kind': 'values', 'series': 'value' if i == 6 else name} for name in (values[:1] if i == 6 else values)]
            if i == 5:
                annotations += [{'kind': 'peak', 'series': 'value'}, {'kind': 'trough', 'series': 'value'}]
            if i == 8:
                annotations += [{'kind': 'reference', 'series': values[0], 'label': '合计'}]
            if i in (1, 8):
                chart.standard_canvas = StandardChartCanvas(sizeMode='fixed', width=14, height=9, dpi=150)
                chart.standard_style = StandardChartStyle(labelRotation=0, grid='x', annotationFontSize=9,
                    annotationOffsetX=5, annotationOffsetY=0, valueMargin=.45 if i == 1 else .2)
            chart.standard_value_fields = tuple(values)
            chart.standard_annotations = tuple(StandardChartAnnotation.model_validate(a) for a in annotations)
            chart.standard_axes = StandardChartAxes()
            # Presentation choices are explicit and saved, separate from immutable values.
            captions = ['开单口径医疗收入｜2025年1—9月｜单位：亿元', '2025年1—9月收入类型构成｜金额与同范围占比',
                '2025年1—9月｜七类成本堆叠与独立月度合计｜单位：亿元', '2025年1—9月｜5个院区完整分布｜单位：亿元、%',
                '2025年1—9月｜全院月度汇总｜单位：万人次', '2025年1—9月｜月度出院人次｜单位：万人次',
                '2025年1—9月累计｜登记原值单位：元｜显示：亿元', '2025年1—9月累计｜执行率=实际/预算｜单位：亿元、%',
                '2025年1—9月｜仅展示最低10项排序子集，不代表完整业务构成']
            sources = ['医疗收入月度汇总（开单口径）', '医疗收入类型构成（2025年1—9月同范围汇总）',
                '成本明细月度净额汇总（含冲销与调整）', '成本明细按院区汇总（完整院区范围）',
                '门诊工作量月度汇总；无同期及预算基准，不作同比与目标判断', '住院工作量月度汇总；无同期及预算基准',
                '收入预算执行总览（全院汇总）', '各院区预算执行偏差（覆盖全部院区分组）', '各业务条线预算执行明细（排序子集）']
            settings = {'subtitle': captions[i], 'sourceNote': '数据来源：' + sources[i] + '。'}
            style_options = {'labelRotation': 0, 'titleFontSize': 17, 'axisFontSize': 10,
                'annotationFontSize': 9, 'annotationOffsetX': 0, 'annotationOffsetY': 9, 'valueMargin': .22,
                'grid': 'x' if chart.visual_form == 'barh' else 'y'}
            if i in (0, 2, 4, 5):
                settings['labelMode'] = 'month'
            if i == 0:
                chart.standard_axes = StandardChartAxes(zeroBaseline=True)
            if i in (1, 3):
                chart.standard_label_fields = ()
                settings['labelFormats'] = [{'field': '占比', 'caption': '占比'}]
                style_options['series'] = [{'series': values[0], 'color': '#4d9a69'}]
            if chart.visual_form == 'barh':
                style_options.update(annotationOffsetX=7, annotationOffsetY=0, valueMargin=.48)
            if i == 2:
                chart.standard_display_unit = '亿元'
                hues = ['#3676a9', '#df9449', '#bb5864', '#8e7764', '#ad81ae', '#b5aa62', '#6fa5ac', '#253348']
                style_options['series'] = [{'series': name, 'color': color} for name, color in zip(values, hues, strict=True)]
                annotations = [{'kind': 'values', 'series': values[-1]}]
            if i == 4:
                chart.standard_display_unit = '万人次'
                style_options['series'] = [{'series': values[0], 'color': '#3066a3'}, {'series': values[1], 'color': '#dc884d', 'marker': 's'}]
                annotations = [{'kind': 'values', 'series': values[0], 'position': 'above'},
                               {'kind': 'values', 'series': values[1], 'position': 'below'}]
            if i == 5:
                chart.standard_display_unit = '万人次'
                annotations = [{'kind': 'values', 'series': 'value'},
                    {'kind': 'peak', 'series': 'value', 'color': '#258558', 'highlight': True, 'position': 'above'},
                    {'kind': 'trough', 'series': 'value', 'color': '#bd4f4f', 'highlight': True, 'position': 'below'}]
            if i == 6:
                style_options['points'] = [{'series': 'value', 'label': values[0], 'color': '#4c72b0'},
                                          {'series': 'value', 'label': values[1], 'color': '#dd8452'}]
                settings['summaries'] = [{'field': '差额', 'displayUnit': '亿元', 'color': '#b55d68', 'showSign': True},
                                         {'field': '完成率', 'color': '#3066a3'}]
            if i == 7:
                settings['order'] = {'mode': 'reverse'}
                settings['labelFormats'] = [
                    {'numerator': values[1], 'denominator': values[0], 'caption': '执行率', 'series': [values[1]]},
                    {'field': '差额', 'displayUnit': '亿元', 'showSign': True, 'series': [values[1]]}]
                style_options['series'] = [{'series': values[0], 'color': '#4c72b0'}, {'series': values[1], 'color': '#dd8452'}]
                style_options.update(legendColumns=2, legendLocation='lower right', annotationFontSize=8, valueMargin=.5)
                chart.standard_canvas = StandardChartCanvas(sizeMode='fixed', width=16, height=8, dpi=150)
            if i == 8:
                chart.standard_labels = ()
                settings['order'] = {'mode': 'value', 'field': values[0], 'limit': 10, 'excludeMissing': True}
                settings['labelFormats'] = [{'field': '预算合计', 'caption': '预算', 'displayUnit': '亿元'},
                                           {'field': '实际合计', 'caption': '实际', 'displayUnit': '亿元'}]
                style_options['series'] = [{'series': values[0], 'color': '#4d9a69'}]
                style_options.update(annotationFontSize=8, valueMargin=.5)
                annotations[-1]['color'] = '#b84b56'
                annotations[-1]['caption'] = '全院整体完成率'
            chart.standard_presentation = StandardChartPresentation.model_validate(settings)
            chart.standard_style = StandardChartStyle.model_validate(style_options)
            chart.standard_annotations = tuple(StandardChartAnnotation.model_validate(a) for a in annotations)
            inputs = ChartInputMaterialization(files=tuple(files), entries=tuple(entries))
            script = standard_visualization_script(SimpleNamespace(charts=(chart,)), inputs)
            success = False
            if script:
                (folder / 'render.py').write_text(script)
                run = subprocess.run([sys.executable, 'render.py'], cwd=folder, capture_output=True, text=True)
                if run.returncode:
                    raise RuntimeError(f'{number}: {run.stderr[-3000:]}')
                success = True
            parameters = {k: v.model_dump(by_alias=True) if hasattr(v, 'model_dump') else
                          [x.model_dump(by_alias=True) for x in v] if v and isinstance(v, tuple) and hasattr(v[0], 'model_dump') else v
                          for k, v in vars(chart).items()}
            (folder / 'parameters.json').write_text(json.dumps(parameters, ensure_ascii=False, indent=2))
            for source in files:
                assert (folder / source.path).read_bytes() == source.content
            record = {'chart': number, 'title': titles[i], 'chartId': trace['chartId'], 'standardRendered': success,
                      'comparison': f'comparison-{number}.png', 'sourceInputs': dependencies,
                      'originalImageSha256': image_identity['sha256'], 'notes': notes[i]}
            records.append(record)
            fig = plt.figure(figsize=(20, 10.8), dpi=150, facecolor='#f4f6f8')
            fig.text(.035, .965, f'{number}  {titles[i]}', fontsize=19, weight='bold', va='top')
            fig.text(.035, .918, '左：上传报告原图', fontsize=13, color='#334155')
            fig.text(.52, .918, '右：当前标准参数回放' if success else '右：标准路线未成图', fontsize=13,
                     color='#146c43' if success else '#b45309')
            for k, name in enumerate(['original.png', 'standard.png']):
                ax = fig.add_axes([.025 + k * .495, .20, .475, .69], facecolor='white')
                ax.axis('off')
                if k == 0 or success:
                    ax.imshow(plt.imread(folder / name))
                else:
                    ax.text(.5, .55, '未命中标准路线\n\n' + '\n'.join(textwrap.wrap(notes[i], width=28)),
                        transform=ax.transAxes, va='center', ha='center', fontsize=15, color='#9a3412', linespacing=1.8)
            fig.text(.035, .135, '差异：' + '\n'.join(textwrap.wrap(notes[i], width=100)), fontsize=12,
                     color='#334155', va='top', linespacing=1.6)
            fig.text(.035, .025, '离线回放｜按登记事实恢复单位，行值不变｜原图及来源均核验SHA256｜人工选参，未执行线上视觉验收',
                     fontsize=10, color='#64748b')
            page = output / record['comparison']
            fig.savefig(page, dpi=150)
            pdf.savefig(fig)
            plt.close(fig)
            pages.append(page)
            print(number, 'rendered' if success else 'rejected', flush=True)
    report = {'mode': 'offline_manually_selected_standard_parameters_not_online_hit_rate',
              'originalPlanAvailable': False,
              'standardCodeCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'workingTreeDirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()),
              'total': len(records),
              'rendered': sum(r['standardRendered'] for r in records), 'originalBytesPreserved': True,
              'inputValuesUnchanged': True, 'metadataReprojectedFromRegisteredFacts': True,
              'onlineVisualGatesExecuted': False, 'results': records}
    (output / 'replay.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    fig, axes = plt.subplots(3, 3, figsize=(24, 13), dpi=150)
    for ax, page in zip(axes.flat, pages, strict=True):
        ax.imshow(plt.imread(page))
        ax.axis('off')
    fig.subplots_adjust(left=.005, right=.995, top=.995, bottom=.005, hspace=.015, wspace=.015)
    fig.savefig(output / 'overview.png', dpi=150)
    plt.close(fig)
    markdown = ['# 原报告与标准可视化逐图对比', '',
        '原图、原输入及用于单位恢复的事实均核验登记size/SHA256；原文件保留，来源行值不变。缺失单位按修复后的投影重新物化到新输入，不能声称旧输入原样9/9覆盖。', '',
        f'人工选择标准参数，{report["rendered"]}/9张生成PNG。原计划未保存；本结果不是线上命中率或全视觉验收结论。', '',
        '| 原图 | 标准成图 | 差异 |', '|---|---|---|']
    markdown += [f'| {r["chart"]} {r["title"]} | {"是" if r["standardRendered"] else "否"} | {r["notes"]} |' for r in records]
    markdown += ['', 'comparison.pdf为9页左右对照；comparison-*.png为单页高清图；overview.png为总览。',
        'chart-*内含原图、冻结输入、标准参数及实际执行脚本/标准图片。',
        '复现：在仓库中PYTHONPATH=. python scripts/replay_standard_visualization_comparison.py ARCHIVE OUTPUT，需要zstandard读取历史ZIP。']
    (output / 'README.md').write_text('\n'.join(markdown))
    if baseline:
        with PdfPages(output / 'before-after.pdf') as pdf:
            for record in records:
                number = record['chart']
                fig = plt.figure(figsize=(20, 10.8), dpi=150, facecolor='#f4f6f8')
                fig.text(.035, .965, f'{number}  {record["title"]}：标准图优化前后', fontsize=18, weight='bold')
                for side, root in enumerate([baseline, output]):
                    fig.text(.035 + side * .495, .92, '上一版标准图' if side == 0 else '新版报告主题与补齐后的参数', fontsize=13)
                    ax = fig.add_axes([.025 + side * .495, .19, .475, .69])
                    ax.axis('off')
                    picture = root / f'chart-{number}' / 'standard.png'
                    if picture.exists():
                        ax.imshow(plt.imread(picture))
                    else:
                        ax.text(.5, .5, '上一版未命中标准路线', transform=ax.transAxes, ha='center', color='#b45309', fontsize=16)
                fig.text(.035, .12, '\n'.join(textwrap.wrap(record['notes'], width=100)), fontsize=12, color='#334155')
                fig.text(.035, .025, '来源数值不变；新版按登记事实重新物化缺失单位。此为人工选参离线回放，不代表线上视觉验收。', fontsize=10, color='#64748b')
                fig.savefig(output / f'before-after-{number}.png', dpi=150)
                pdf.savefig(fig)
                plt.close(fig)


if __name__ == '__main__':
    main()
