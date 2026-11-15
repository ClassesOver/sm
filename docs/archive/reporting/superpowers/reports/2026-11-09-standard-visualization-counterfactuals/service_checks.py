"""复用既有定向节点；保存真实执行日志、源码和生成文件身份。"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TESTS = 'smart_reporting/reporting/tests/'
NODES = [
    TESTS + 'test_report_data_revision_exports.py::test_native_paginated_data_revision_redraws_and_exports_current_images[.png-asyncio]',
    TESTS + 'test_report_data_revision_service.py::test_revise_expands_verified_standard_pages_and_requires_current_receipts_for_each_page',
    TESTS + 'test_report_data_revision_service.py::test_redraw_failure_or_old_review_preserves_latest_and_original_files',
    TESTS + 'test_report_data_revision_service.py::test_concurrent_revisions_have_one_cas_winner_without_overwriting_history',
    TESTS + 'test_report_data_revision_state.py::test_data_export_records_reexports_without_changing_snapshot_history',
    TESTS + 'test_report_data_revision_state.py::test_editor_revisions_have_independent_snapshot_cas_and_export_history',
]


def identity(path, raw):
    return {'path': str(path), 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='sr-counterfactual-services-') as directory:
        command = [sys.executable, '-m', 'pytest', '-o', 'addopts=', '-vv',
                   '--basetemp', directory, '--junitxml', str(output / 'junit.xml'), *NODES]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        (output / 'pytest.stdout.txt').write_text(result.stdout)
        (output / 'pytest.stderr.txt').write_text(result.stderr)
        generated = []
        for path in sorted(Path(directory).rglob('*')):
            if path.is_file() and not path.is_symlink() and path.suffix in {'.png', '.pdf', '.docx', '.pptx', '.xlsx', '.json'}:
                if 'reports' in path.parts:
                    generated.append(identity(path.relative_to(directory), path.read_bytes()))
        source_paths = sorted({node.split('::')[0] for node in NODES} | {
            TESTS + 'test_report_data_snapshot_edits.py', TESTS + 'test_report_data_revision_state.py',
            TESTS + 'fixtures/data_revision/document-context.json', TESTS + 'fixtures/data_revision/report.md',
            'smart_reporting/report_editor/data_revisions.py',
            'smart_reporting/report_editor/data_revision_exports.py',
        })
        record = {
            'command': command, 'exit_code': result.returncode,
            'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'runner': identity('service_checks.py', Path(__file__).read_bytes()),
            'sources': [identity(path, (ROOT / path).read_bytes()) for path in source_paths],
            'generated_files': generated,
            'limitations': ['Synthetic fixtures only', 'Local Agno CodeMode and native renderers; no AgentOS report run',
                'Vision reviewer and repositories are test doubles',
                'D2 PNG only; JPEG cases were verified in the preceding merge work',
                'Generated files hashed before temporary-directory cleanup; rerun to reconstruct'],
        }
        (output / 'result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
        print(result.stdout)
        print(json.dumps({'exit_code': result.returncode, 'generated_files': len(generated)}, ensure_ascii=False))
        sys.exit(result.returncode)


if __name__ == '__main__':
    main()
