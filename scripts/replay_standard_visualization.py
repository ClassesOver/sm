"""Offline template coverage over trace-registered chart inputs, without model calls."""
import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace

from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputFile,
    ChartInputMaterialization,
)
from smart_reporting.reporting.workflow.runtime.standard_visualization import (
    standard_visualization_script,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    # Python <3.14 does not natively support ZIP zstd method 93.
    if sys.version_info < (3, 14):
        import zstandard
        original = zipfile._get_decompressor
        zipfile._get_decompressor = lambda method: (
            zstandard.ZstdDecompressor().decompressobj() if method == 93 else original(method)
        )
    results = []
    with zipfile.ZipFile(args.archive) as archive:
        names = archive.namelist()
        index = json.loads(archive.read(next(name for name in names if name.endswith('/trace-index-v1.json'))))
        files = {item['resourceId']: item for item in index['files']}
        for position, trace in enumerate(index['chartTraces']):
            record = {'chartId': trace['chartId'], 'covered': False,
                      'originalPlanAvailable': False, 'candidates': []}
            results.append(record)
            resource_ids = trace['plotDataFileResourceIds']
            if len(resource_ids) != 1:
                record['reason'] = 'multiple_sources_require_explicit_alignment'
                continue
            identity = files[resource_ids[0]]
            raw = archive.read(identity['path'])
            if len(raw) != identity['size'] or hashlib.sha256(raw).hexdigest() != identity['sha256']:
                raise ValueError('registered input identity mismatch')
            document = json.loads(raw)
            metadata = document.get('columnMeta', {})
            fields = [column for column in document['columns'] if metadata.get(column, {}).get('unit')]
            selections = [('bar', ())] + [('bar', (column,)) for column in fields]
            if len(document['rows']) == 1:
                selections.extend(('summary-bars', pair) for pair in combinations(fields, 2))
            source = ChartInputFile('input.json', raw)
            inputs = ChartInputMaterialization(files=(source,), entries=({
                'chartId': trace['chartId'], 'path': source.path, 'sha256': source.sha256,
            },))
            for form, selected in selections:
                chart = SimpleNamespace(
                    chart_id=trace['chartId'], renderer='matplotlib', interactive_path=None,
                    visual_form=form, source_path='chart.png', title='冻结输入模板覆盖回放',
                    standard_value_fields=selected,
                )
                script = standard_visualization_script(SimpleNamespace(charts=(chart,)), inputs)
                if script is None:
                    continue
                folder = output / f'chart-{position:02d}-{len(record["candidates"]):02d}'
                folder.mkdir(exist_ok=True)
                (folder / 'input.json').write_bytes(raw)
                (folder / 'render.py').write_text(script)
                completed = subprocess.run([sys.executable, 'render.py'], cwd=folder, capture_output=True)
                if completed.returncode:
                    raise RuntimeError(completed.stderr.decode()[-2000:])
                record['candidates'].append({'visualForm': form, 'valueFields': selected, 'inputSha256': source.sha256,
                                             'image': str(folder / 'chart.png')})
                record['covered'] = True
            if not record['covered']:
                record['reason'] = 'shape_requires_explicit_label_or_unsupported_template'
    report = {'mode': 'offline_candidate_coverage_not_original_route_hit',
              'charts': len(results), 'covered': sum(item['covered'] for item in results),
              'results': results}
    (output / 'replay.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != 'results'}))


if __name__ == '__main__':
    main()
