"""离线回放真实生成、冻结绑定和编辑器 API，并向前端交付同一次校验的结果。"""

import hashlib
import json
import os
import re
from pathlib import Path

import pytest

from smart_reporting.reporting.tests.test_trace_subject_validate import _make_editor_with_subject

CASES = json.loads((Path(__file__).parent / 'fixtures/reference_review_cases.json').read_text())['cases']


@pytest.mark.anyio
@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
async def test_reference_review_roundtrip(tmp_path, case):
    unit = case.get('unit', '万元')
    display_unit = case.get('displayUnit', unit)
    statement = case['prefix'] + '{{value:fact-aaaaaaaaaaaaaaaa:' + case['selector'] + ':' + display_unit + '}}'
    statement += case.get('suffix', '') + '。'
    editor, grants, context = await _make_editor_with_subject(
        tmp_path, period_table=True, number_reference=True, include_table=False,
        number_statement=statement, metric_scope=case.get('scope'), metric_unit=unit,
        metric_values=tuple(case['values']) if 'values' in case else None,
    )
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    markdown = next(tmp_path.rglob('report.md')).read_text()
    claim_id = re.search(r'\[\[claim:([^\]]+)\]\]', markdown)[1]
    # 正式装配把同一 claim 的来源入口放在其旁边；指纹忽略这些协议标记。
    markdown = markdown.replace(f'[[claim:{claim_id}]]', f'[[citation:sub-{"0" * 16}]][[claim:{claim_id}]]')
    published_markdown = markdown
    mutation = case.get('mutation', {})
    if 'replace' in mutation:
        before, after = mutation['replace']
        assert before in markdown
        markdown = markdown.replace(before, after)
    markdown = mutation.get('prepend', '') + markdown
    if mutation.get('duplicate'):
        markdown += markdown
    if mutation.get('removeClaim'):
        markdown = markdown.replace(f'[[claim:{claim_id}]]', '')
    result = await editor.trace_validate(context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest())
    subject = result['subjects'][0]
    assert subject['status'] == case.get('binding', 'valid')
    if case.get('warning'):
        assert any(case['warning'] in warning for warning in subject['warnings']), subject
    elif not mutation:
        assert subject['warnings'] == [] and result['warnings'] == [], result
    if 'original' in case:
        notices = [notice for notice in result['reviewNotices'] if notice['kind'] == 'numeric_unverified']
        assert len(notices) == 1 and notices[0]['originalText'] == case['original']
        assert notices[0]['bound'] is True and notices[0]['occurrences'] == 1
    restored = None
    if case.get('canRestore'):
        assert subject['status'] == 'stale' and subject['comparable'] is True
        assert subject['restoreText']
        restored_validation = await editor.trace_validate(
            context, session, published_markdown, hashlib.sha256(published_markdown.encode()).hexdigest(),
        )
        assert restored_validation['subjects'][0]['status'] == 'valid'
        assert restored_validation['subjects'][0]['warnings'] == []
        restored = {'markdown': published_markdown, 'validation': restored_validation}
    if output := os.environ.get('REFERENCE_REVIEW_HARNESS_OUTPUT'):
        destination = Path(output)
        destination.mkdir(parents=True, exist_ok=True)
        (destination / (case['id'] + '.json')).write_text(json.dumps({
            'case': case, 'markdown': markdown, 'validation': result, 'restored': restored,
        }, ensure_ascii=False), encoding='utf-8')
