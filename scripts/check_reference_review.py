"""离线回放生成纠错闭环，再把后端真实 API 结果交给 ProseMirror。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'smart_reporting/report_editor/frontend'
CASES = ROOT / 'smart_reporting/reporting/tests/fixtures/reference_review_cases.json'
GENERATION_TEST_COUNT = 4


def run_stage(name: str, command: list[str], cwd: Path, directory: Path,
              environment: dict[str, str], timeout: int, expected_tests: int) -> dict:
    junit = directory / f'{name}.xml'
    log = directory / f'{name}.log'
    started = time.monotonic()
    result = {'name': name, 'passed': False, 'junit': str(junit), 'log': str(log)}
    print(f'{name}: running', flush=True)
    try:
        with log.open('w', encoding='utf-8') as stream:
            process = subprocess.run(command, cwd=cwd, env=environment, stdout=stream,
                                     stderr=subprocess.STDOUT, timeout=timeout, check=False)
        result['exitCode'] = process.returncode
        suites = ET.parse(junit).getroot()
        tests = list(suites.iter('testcase'))
        failed = sum(test.find('failure') is not None or test.find('error') is not None for test in tests)
        skipped = sum(test.find('skipped') is not None for test in tests)
        result.update(tests=len(tests), failed=failed, skipped=skipped)
        result['passed'] = process.returncode == 0 and len(tests) == expected_tests and failed == skipped == 0
        if len(tests) != expected_tests:
            result['error'] = f'Expected {expected_tests} cases, executed {len(tests)}.'
    except subprocess.TimeoutExpired:
        result.update(exitCode=124, error=f'Timed out after {timeout} seconds.')
    except (OSError, ET.ParseError) as error:
        result['error'] = f'{type(error).__name__}: {error}'
    result['durationSeconds'] = round(time.monotonic() - started, 3)
    print(f"{name}: {'passed' if result['passed'] else 'failed'} ({log})", flush=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(tempfile.gettempdir()) / 'report-reference-harness')
    parser.add_argument('--timeout', type=int, default=180, help='Timeout per stage in seconds.')
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error('--timeout must be positive')
    examples = json.loads(CASES.read_text())['cases']
    ids = [case['id'] for case in examples]
    if not ids or len(ids) != len(set(ids)):
        parser.error('Case IDs must be nonempty and unique.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='run-', dir=output))
    artifacts = directory / 'cases'
    environment = {**os.environ, 'REFERENCE_REVIEW_HARNESS_OUTPUT': str(artifacts),
                   'MPLCONFIGDIR': str(directory / 'matplotlib')}
    report = {'version': 1, 'passed': False, 'caseCount': len(ids), 'generationCaseCount': GENERATION_TEST_COUNT,
              'stages': [], 'artifacts': str(artifacts)}
    generation = run_stage('generation', [
        sys.executable, '-m', 'pytest', '-q', 'smart_reporting/reporting/tests/test_generation_reference_convergence.py',
        '--tb=short', f'--junitxml={directory / "generation.xml"}',
    ], ROOT, directory, environment, args.timeout, GENERATION_TEST_COUNT)
    report['stages'].append(generation)
    backend = None
    if generation['passed']:
        backend = run_stage('backend', [
            sys.executable, '-m', 'pytest', '-q', 'smart_reporting/reporting/tests/test_reference_review_harness.py',
            '--tb=short', f'--junitxml={directory / "backend.xml"}',
        ], ROOT, directory, environment, args.timeout, len(ids))
        report['stages'].append(backend)
    if backend is not None and backend['passed']:
        node = shutil.which('node')
        if node is None:
            report['stages'].append({'name': 'frontend', 'passed': False, 'error': 'node is not installed.'})
        else:
            frontend = run_stage('frontend', [
                node, str(FRONTEND / 'node_modules/vitest/vitest.mjs'), 'run',
                'src/reference-review-harness.test.ts', '--reporter=junit',
                f'--outputFile={directory / "frontend.xml"}',
            ], FRONTEND, directory, environment, args.timeout, len(ids))
            report['stages'].append(frontend)
            report['passed'] = frontend['passed']
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    (directory / 'report.json').write_text(serialized, encoding='utf-8')
    (output / 'report.json').write_text(serialized, encoding='utf-8')
    print(f"{'PASS' if report['passed'] else 'FAIL'}: {output / 'report.json'}", flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
