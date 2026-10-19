"""登记显示原文恢复后再次校验必须收敛，不能被数值格式差异锁在 stale。"""

import hashlib

import pytest

from smart_reporting.reporting.tests.test_trace_subject_validate import _make_editor_with_subject


@pytest.mark.anyio
@pytest.mark.parametrize(
    ('unit', 'values', 'prefix', 'display_unit', 'published', 'edited'),
    [
        ('万元', (1200, 2400), '收入', '万元', '2,400.00万元', '2,500.00万元'),
        ('万元', (1200, 2400), '收入', '万元', '2,400.00万元', '2,500万元'),
        ('元', (0.5, 0.505), '收入', '元', '0.51元', '0.52元'),
        ('元', (1200000, 2400000), '收入', '万元', '240.00万元', '250.000万元'),
        ('元/人次', (10, 30), '次均费用', '元/人次', '30元/人次', '31元/人次'),
        ('个百分点', (-1, -2), '占比变化为', '个百分点', '-2.00个百分点', '-3个百分点'),
        ('个百分点', (-1, -2), '占比下降', '个百分点', '2.00个百分点', '3个百分点'),
        ('元', (-1, -2), '收入下降', '元', '2元', '3元'),
    ],
)
async def test_editor_restores_exact_published_display_and_clears_review(
    tmp_path, unit, values, prefix, display_unit, published, edited,
):
    statement = ('2025年10月' + prefix + '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:'
                 + display_unit + '}}。')
    editor, grants, context = await _make_editor_with_subject(
        tmp_path, period_table=True, number_reference=True, include_table=False,
        number_statement=statement, metric_unit=unit, metric_values=values,
    )
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    original = next(tmp_path.rglob('report.md')).read_text()

    async def validate(markdown):
        return await editor.trace_validate(
            context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest(),
        )

    initial = await validate(original)
    assert initial['subjects'][0]['restoreText'] == published
    assert initial['subjects'][0]['status'] == 'valid'
    assert initial['subjects'][0]['warnings'] == []
    changed = original.replace(published, edited)
    assert changed != original
    modified = await validate(changed)
    subject = modified['subjects'][0]
    assert subject['status'] == 'stale'
    assert subject['comparable'] is True
    assert subject['restoreText'] == published
    restored = changed.replace(edited, subject['restoreText'])
    assert restored == original
    checked = await validate(restored)
    assert checked['subjects'][0]['status'] == 'valid'
    assert checked['subjects'][0]['warnings'] == []
    assert checked['warnings'] == []


@pytest.mark.anyio
async def test_restore_display_preserves_a_converted_unit(tmp_path):
    editor, grants, context = await _make_editor_with_subject(
        tmp_path, period_table=True, number_reference=True, include_table=False,
        number_statement='2025年10月收入{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:万元}}。',
        metric_unit='元', metric_values=(1200000, 2400000),
    )
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    markdown = next(tmp_path.rglob('report.md')).read_text()
    checked = await editor.trace_validate(
        context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest(),
    )
    assert checked['subjects'][0]['restoreText'] == '240.00万元'
    assert checked['subjects'][0]['status'] == 'valid'
    assert checked['subjects'][0]['warnings'] == []


@pytest.mark.anyio
async def test_restore_display_does_not_clear_a_semantic_edit(tmp_path):
    editor, grants, context = await _make_editor_with_subject(
        tmp_path, period_table=True, number_reference=True, include_table=False,
        number_statement='2025年10月收入{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:万元}}。',
    )
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    markdown = next(tmp_path.rglob('report.md')).read_text().replace('收入', '成本')
    checked = await editor.trace_validate(
        context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest(),
    )
    subject = checked['subjects'][0]
    assert subject['restoreText'] == '2,400.00万元'
    assert subject['status'] == 'stale'
    assert subject['comparable'] is False


@pytest.mark.anyio
async def test_legacy_claim_does_not_invent_restore_display(tmp_path):
    editor, grants, context = await _make_editor_with_subject(tmp_path, include_table=False)
    raw, _ = await grants.issue(context)
    _token, session = await grants.exchange(raw)
    markdown = next(tmp_path.rglob('report.md')).read_text()
    checked = await editor.trace_validate(
        context, session, markdown, hashlib.sha256(markdown.encode()).hexdigest(),
    )
    assert checked['subjects'][0]['restoreText'] is None
