"""旧精确引用只从已核验原发布正文恢复显示，损坏时软降级。"""

import hashlib
import re

import pytest

from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
from smart_reporting.reporting.tests.test_trace_subject_validate import _make_editor_with_subject
from smart_reporting.reporting.trace.index_builder import encode_trace_index
from smart_reporting.reporting.trace.semantic_bindings import statement_fingerprint


async def _legacy_editor(tmp_path, *, unit='万元', values=(1200, 2400), display_unit='万元',
                         prefix='收入', citation=False, bad_fingerprint=False, bad_value=False,
                         duplicate_binding=False):
    token = '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:' + display_unit + '}}'
    statement = '2025年10月' + prefix + token + ('及收入' + token if duplicate_binding else '') + '。'
    editor, _grants, context = await _make_editor_with_subject(
        tmp_path, period_table=True, number_reference=True, include_table=False,
        number_statement=statement, metric_unit=unit, metric_values=values,
    )
    index = await editor.trace.require_index(context)
    original = next(tmp_path.rglob('report.md')).read_text()
    if citation:
        original = re.sub(r'(?=\[\[claim:)', '[[citation:sub-0000000000000000]]', original)
    if bad_value:
        original = original.replace('2,400.00万元', '999万元')
    bindings = []
    for binding in index.subject_bindings:
        number = binding.number_reference.model_copy(update={'display_text': None})
        if bad_fingerprint:
            number = number.model_copy(update={'statement_sha256': 'f' * 64})
        elif bad_value:
            number = number.model_copy(update={'statement_sha256': statement_fingerprint(original, binding.claim_id)})
        bindings.append(binding.model_copy(update={'number_reference': number}))
    if duplicate_binding:
        claim_id = re.findall(r'\[\[claim:([^\]]+)\]\]', original)[1]
        number = bindings[0].number_reference.model_copy(update={
            'claim_id': claim_id, 'statement_sha256': statement_fingerprint(original, claim_id),
        })
        bindings.append(bindings[0].model_copy(update={
            'subject_id': 'sub-' + '1' * 16, 'claim_id': claim_id, 'number_reference': number,
        }))
    markdown_bytes = original.encode()
    files = tuple(file.model_copy(update={'size': len(markdown_bytes),
                                         'sha256': hashlib.sha256(markdown_bytes).hexdigest()})
                  if file.resource_id == index.markdown_file_resource_id else file for file in index.files)
    index = index.model_copy(update={'files': files, 'subject_bindings': tuple(bindings)})
    await editor.workspace.awrite_text(context.scope['threadId'], context.markdown_path, original, overwrite=True)
    await editor.workspace.awrite_bytes(context.scope['threadId'], 'reports/revision-1/trace-index-v1.json',
                                       encode_trace_index(index), overwrite=True)
    identity = await register_trace_manifest(editor.workspace, context.scope['threadId'], index, overwrite=True)
    return editor, context.model_copy(update={'artifact_manifest': identity}), original


async def _validate(editor, context, markdown):
    return await editor.trace.validate(context, markdown, hashlib.sha256(markdown.encode()).hexdigest())


@pytest.mark.anyio
@pytest.mark.parametrize(('unit', 'values', 'display_unit', 'prefix', 'published', 'edited'), [
    ('万元', (1200, 2400), '万元', '收入', '2,400.00万元', '2,500万元'),
    ('元', (1200000, 2400000), '万元', '收入', '240.00万元', '250万元'),
    ('元', (-1, -2), '元', '收入下降', '2元', '3元'),
    ('元/人次', (10, 30), '元/人次', '次均费用', '30元/人次', '31元/人次'),
])
async def test_legacy_exact_display_restores_the_original_format_and_unit(
    tmp_path, unit, values, display_unit, prefix, published, edited,
):
    editor, context, original = await _legacy_editor(
        tmp_path, unit=unit, values=values, display_unit=display_unit, prefix=prefix, citation=True,
    )
    changed = original.replace(published, edited)
    assert changed != original
    result = await _validate(editor, context, changed)
    subject = result['subjects'][0]
    assert subject['status'] == 'stale'
    assert subject['restoreText'] == published
    restored = changed.replace(edited, subject['restoreText'])
    assert restored == original
    checked = await _validate(editor, context, restored)
    assert checked['subjects'][0]['status'] == 'valid'
    assert checked['subjects'][0]['warnings'] == [] and checked['warnings'] == []


@pytest.mark.anyio
@pytest.mark.parametrize('failure', ['fingerprint', 'value', 'unreadable', 'integrity', 'decode', 'extraction'])
async def test_legacy_restore_failures_do_not_abort_validation(tmp_path, monkeypatch, failure):
    editor, context, original = await _legacy_editor(
        tmp_path, bad_fingerprint=failure == 'fingerprint', bad_value=failure == 'value',
    )
    read = editor.trace._read_registered_file

    async def fail_source(context, identity, **kwargs):
        if identity.path == context.markdown_path:
            if failure == 'unreadable':
                raise OSError('frozen source missing')
            if failure == 'decode':
                return b'\xff'
        return await read(context, identity, **kwargs)

    monkeypatch.setattr(editor.trace, '_read_registered_file', fail_source)
    if failure == 'extraction':
        from smart_reporting.reporting.trace import semantic_bindings

        def fail_display(*_args):
            raise ValueError('display extraction failed')

        monkeypatch.setattr(semantic_bindings, 'bound_number_display', fail_display)
    if failure == 'integrity':
        await editor.workspace.awrite_text(context.scope['threadId'], context.markdown_path,
                                          original + 'changed', overwrite=True)
    result = await _validate(editor, context, original.replace('2,400.00万元', '2,500万元'))
    assert len(result['subjects']) == 1
    assert result['subjects'][0]['restoreText'] is None
    assert result['summary']['stale'] == 1


@pytest.mark.anyio
async def test_legacy_original_markdown_is_loaded_once_for_multiple_claims(tmp_path, monkeypatch):
    editor, context, original = await _legacy_editor(tmp_path, duplicate_binding=True)
    read = editor.trace._read_registered_file
    calls = 0

    async def count_source(context, identity, **kwargs):
        nonlocal calls
        if identity.path == context.markdown_path:
            calls += 1
        return await read(context, identity, **kwargs)

    monkeypatch.setattr(editor.trace, '_read_registered_file', count_source)
    result = await _validate(editor, context, original.replace('2,400.00万元', '2,500万元'))
    assert len(result['subjects']) == 2 and calls == 1
    assert all(subject['restoreText'] == '2,400.00万元' for subject in result['subjects'])
