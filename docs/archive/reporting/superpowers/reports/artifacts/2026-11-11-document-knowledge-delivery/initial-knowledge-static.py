import ast
import collections
import json
import subprocess

files = subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines()
ruff = '/home/junge/pros/smart_reporting/.venv/bin/ruff'
new, existing, parsed = [], 0, 0
for file in files:
    if not file.endswith('.py'):
        continue
    data = open(file).read()
    ast.parse(data, filename=file)
    parsed += 1
    old = subprocess.check_output(['git', 'show', 'ccc1f83fa6dbed1a7ded8821f6a69c562170e9fc:' + file], text=True)
    def check(source):
        result = subprocess.run([ruff, 'check', '--output-format', 'json', '--stdin-filename', file, '-'], input=source, text=True, capture_output=True)
        assert result.returncode in (0, 1), result.stderr
        return collections.Counter((item['code'], item['message']) for item in json.loads(result.stdout))
    before, after = check(old), check(data)
    existing += sum((before & after).values())
    new.extend((file, code, message, count) for (code, message), count in (after - before).items())
subprocess.run(['node', '--check', 'smart_reporting/report_editor/frontend/smoke/report-historical-retirement-postgres-smoke.mjs'], check=True)
subprocess.run(['git', 'diff', '--check'], check=True)
print(json.dumps({'pythonFilesParsed': parsed, 'newRuffDiagnostics': new, 'unchangedRuffDiagnostics': existing, 'javascriptSyntax': 'passed', 'gitDiffCheck': 'passed'}, ensure_ascii=False))
assert not new
