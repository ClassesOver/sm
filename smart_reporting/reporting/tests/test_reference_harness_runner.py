"""故障注入：退出码、实际执行数和跳过状态必须共同决定 harness 是否通过。"""

import os
import sys

import pytest

from scripts.check_reference_review import run_stage


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
