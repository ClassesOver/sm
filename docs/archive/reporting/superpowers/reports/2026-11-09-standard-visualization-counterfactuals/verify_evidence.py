"""仅用标准库核对已保存身份与配对；不执行生产变换、模型或绘图。"""

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

REPORT = Path(__file__).resolve().parent
REPO = REPORT.parents[3]
EVIDENCE = REPORT / 'evidence'


def check_identity(folder, ref):
    raw = (folder / ref['path']).read_bytes()
    assert len(raw) == ref['size'], ref['path']
    assert hashlib.sha256(raw).hexdigest() == ref['sha256'], ref['path']
    return raw


def deltas(a, b, path=''):
    if type(a) is not type(b):
        return [path]
    if isinstance(a, dict):
        return [change for key in sorted(a.keys() | b.keys()) for change in (
            deltas(a[key], b[key], f'{path}/{key}') if key in a and key in b else [f'{path}/{key}'])]
    if isinstance(a, list):
        if len(a) != len(b):
            return [path]
        return [change for i, (left, right) in enumerate(zip(a, b, strict=True))
                for change in deltas(left, right, f'{path}/{i}')]
    return [] if a == b else [path]


def main():
    rows = [json.loads(line) for line in (EVIDENCE / 'final/results.jsonl').read_text().splitlines()]
    assert len(rows) == 22
    pairs, frozen = {}, {}
    for row in rows:
        folder = EVIDENCE / 'final' / row['case'] / row['variant']
        state = json.loads(check_identity(folder, row['frozen']))
        assert json.loads(check_identity(folder, row['plan'])) == state['plan']
        assert [json.loads(check_identity(folder, ref)) for ref in row['inputs']] == state['documents']
        for key in ('compiled_script', 'image'):
            if key in row['actual']:
                check_identity(folder, row['actual'][key])
        assert row['pair_assertions'] == 'passed'
        pairs.setdefault(row['case'], []).append(row)
        frozen[row['case'], row['variant']] = state
    assert set(pairs) == {'U1', 'U2', 'U3', 'U4', 'P1', 'P2', 'P3', 'B1', 'B2', 'L1', 'D1'}
    identities = []
    for case, pair in pairs.items():
        a, b = pair
        assert [a['variant'], b['variant']] == ['control', 'counterfactual']
        assert deltas(frozen[case, 'control'], frozen[case, 'counterfactual']) == [a['changed_path']]
        identities.append({'case': case, 'changed_path': a['changed_path'],
                           'same_input_bytes': a['inputs'] == b['inputs'], 'same_plan': a['plan'] == b['plan']})
    assert pairs['U2'][1]['actual']['preflight_diagnostic']['code'] == 'standard_unit_conversion_invalid'
    assert 'execution' not in pairs['U2'][1]['actual']
    for case, reason in [('P1', 'source_period_year_mismatch'), ('P2', 'source_label_sets_differ')]:
        actual = pairs[case][1]['actual']
        assert actual['document'] is None
        assert actual['diagnostics'] == [{'reason': reason, 'sourceIndex': 1}]
    env = json.loads((EVIDENCE / 'final/environment.json').read_text())
    check_identity(REPORT, env['runner_script'])
    for ref in env['source_and_lock_identities']:
        check_identity(REPO, ref)
    services = EVIDENCE / 'services-2'
    result = json.loads((services / 'result.json').read_text())
    assert result['exit_code'] == 0
    check_identity(REPORT, result['runner'])
    for ref in result['sources']:
        check_identity(REPO, ref)
    tests = ET.parse(services / 'junit.xml').getroot().findall('.//testcase')
    assert len(tests) == 8 and not any(test.find(status) is not None
        for test in tests for status in ('failure', 'error', 'skipped'))
    assert {Path(ref['path']).suffix for ref in result['generated_files']} >= {'.pdf', '.docx', '.pptx', '.xlsx'}
    trials = json.loads((EVIDENCE / 'trial-history.json').read_text())
    check_identity(EVIDENCE, trials['archive'])
    print(json.dumps({'paired_observations': len(rows), 'pairs': identities,
                      'service_tests_passed': len(tests), 'identities_verified': True,
                      'limits': '身份检查不能证明业务与视觉正确；独立oracle在replay.py，外部复现仍待完成'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
