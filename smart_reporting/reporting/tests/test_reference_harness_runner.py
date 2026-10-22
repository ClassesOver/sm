"""故障注入：退出码、实际执行数和跳过状态必须共同决定 harness 是否通过。"""

import os
import subprocess
import sys

import pytest

from scripts.check_reference_review import collect_case_ids, run_stage


@pytest.mark.parametrize(('body', 'exit_code', 'passed'), [
    ('<testcase name="ok"/>', 0, True),
    ('', 0, False),
    ('<testcase name="skipped"><skipped/></testcase>', 0, False),
    ('<testcase name="failed"><failure/></testcase>', 0, False),
    ('<testcase name="ok"/>', 1, False),
    ('<broken', 0, False),
])
def test_harness_rejects_empty_skipped_failed_and_malformed_results(tmp_path, body, exit_code, passed):
    junit = tmp_path / 'guard.xml'
    xml = '<testsuites><testsuite>' + body + '</testsuite></testsuites>'
    command = [sys.executable, '-c',
               'from pathlib import Path; import sys; '
               f'Path({str(junit)!r}).write_text({xml!r}); sys.exit({exit_code})']
    result = run_stage('guard', command, tmp_path, tmp_path, dict(os.environ), 10, 1)
    assert result['passed'] is passed
    assert result['exitCode'] == exit_code


@pytest.mark.parametrize(('output', 'exit_code', 'valid'), [
    ('tests/test_example.py::first\ntests/test_example.py::second[x]\n2 tests collected', 0, True),
    ('no tests collected', 0, False),
    ('tests/test_example.py::first\ntests/test_example.py::first', 0, False),
    ('tests/test_example.py::first', 1, False),
])
def test_collection_freezes_nonempty_unique_current_case_ids(tmp_path, monkeypatch, output, exit_code, valid):
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], exit_code, stdout=output,
    ))
    if valid:
        assert collect_case_ids('tests/test_example.py', tmp_path, tmp_path, {}, 10) == [
            'tests/test_example.py::first', 'tests/test_example.py::second[x]',
        ]
    else:
        with pytest.raises(ValueError):
            collect_case_ids('tests/test_example.py', tmp_path, tmp_path, {}, 10)


@pytest.mark.parametrize('actual_name', ['expected', 'substitute'])
def test_harness_checks_collected_identity_even_when_count_matches(tmp_path, actual_name):
    junit = tmp_path / 'identity.xml'
    xml = '<testsuites><testsuite><testcase classname="tests.test_example" name="' + actual_name + '"/></testsuite></testsuites>'
    command = [sys.executable, '-c', 'from pathlib import Path; '
               f'Path({str(junit)!r}).write_text({xml!r})']
    result = run_stage('identity', command, tmp_path, tmp_path, dict(os.environ), 10, 1,
                       ['tests/test_example.py::expected'])
    assert result['passed'] is (actual_name == 'expected')
