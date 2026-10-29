"""Replay editor parameter transport with independent production geometry oracles.

No model is called. These are explicit planner fixtures, not online hit-rate data.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from scripts.replay_standard_visualization_variants import run_case, write_replay_report
from scripts.standard_visualization_box_summary_cases import summary_cases
from scripts.standard_visualization_break_cases import break_cases
from scripts.standard_visualization_domain_cases import domain_cases
from scripts.standard_visualization_dual_stack_cases import dual_stack_cases
from scripts.standard_visualization_geometry_cases import geometry_cases
from scripts.standard_visualization_horizontal_break_cases import horizontal_break_cases
from scripts.standard_visualization_statistics_cases import statistics_cases
from smart_reporting.report_editor.standard_charts import (
    StandardChartEditParameters,
    standard_edit_plan,
)
from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_preflight,
)


def editor_plan(parameters):
    standard = StandardChartEditParameters.model_validate({
        key: value for key, value in parameters.items() if key.startswith('standard_')
    })
    plan, _inputs = standard_edit_plan(chart_id=parameters['chart_id'], output_path=parameters['source_path'],
        title=parameters['title'], alt_text='标准改图离线参数回放', visual_form=parameters['visual_form'],
        standard=standard, bindings=(), plot_files=())
    return plan


def cases():
    for factory, forms in ((geometry_cases, {'scatter', 'bubble', 'heatmap', 'line'}),
                           (statistics_cases, {'waterfall', 'boxplot'}),
                           (summary_cases, {'boxplot'}), (dual_stack_cases, {'stacked-total'}),
                           (horizontal_break_cases, {'barh'}), (break_cases, {'line'})):
        found = set()
        for item in factory():
            form = item['parameters']['visual_form']
            if item.get('expected', 'render') == 'render' and form in forms and form not in found:
                found.add(form)
                item['id'] = 'editor-' + item['id']
                yield item
    for item in domain_cases():
        if item.get('expected', 'render') == 'render' and item['parameters'].get('standard_axes', {}).get('mode') == 'dual':
            item['id'] = 'editor-' + item['id']
            yield item
            break


def verify(output):
    report = json.loads((output/'variants.json').read_text())
    checked = []
    for record in report['results']:
        folder = output/record['id']
        plan = editor_plan(json.loads((folder/'parameters.json').read_text()))
        files = tuple(ChartInputFile(p.name, p.read_bytes()) for p in sorted(folder.glob('input-*.json')))
        inputs = ChartInputMaterialization(files=files, entries=tuple(
            {'chartId': plan.charts[0].chart_id, 'path': f.path, 'sha256': f.sha256} for f in files))
        source = standard_visualization_preflight(plan, inputs).source
        assert source is not None, record['id']
        assert source == (folder/'render.py').read_text(), record['id']
        checked.append({'id': record['id'], 'sha256': hashlib.sha256(source.encode()).hexdigest()})
    proof = {'codeCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'workingTreeDirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()),
        'editorParameterScriptsVerified': len(checked), 'results': checked}
    (output/'final-source-proof.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in proof.items() if key != 'results'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.verify_only:
        verify(args.output)
        return
    records = []
    for case in cases():
        result = run_case(case, args.output, plan_factory=editor_plan)
        assert result['status'] == 'rendered_geometry_checked', result
        result['expectationMet'] = True
        records.append(result)
        print(result['id'], result['status'], flush=True)
    report = {'mode': 'offline_editor_parameter_transport_no_model', 'cases': len(records),
        'counts': {'rendered_geometry_checked': len(records)}, 'results': records}
    (args.output/'variants.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    write_replay_report(report, args.output)
    verify(args.output)


if __name__ == '__main__':
    main()
