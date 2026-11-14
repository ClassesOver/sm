"""Actual DOCX/NativeEditorService evidence; controlled session/revision repositories."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

import pytest

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.report_editor.native_ai import NativeAIService
from smart_reporting.report_editor.native_word_task_builder import NativeWordTaskInputBuilder
from smart_reporting.reporting.tests.test_native_ai import sample as sample
from smart_reporting.task_execution.models import TaskExecutionScope
from smart_reporting.task_execution.native_word_contracts import canonical_digest


def request(sample):
    editor, context, _, model, _ = sample
    target = model['blocks'][0]
    ref = next(iter(editor.grants.repository.sessions))
    base = [{'kind': 'replaceParagraph', 'blockId': target['blockId'],
             'expectedObjectSha256': target['expectedObjectSha256'], 'text': 'Selected draft'}]
    return dict(scope=TaskExecutionScope('builder-test', 'user', 'thread', 'test-only', 'word-test'),
        server_session_reference=ref, instruction='  Exact instruction  ',
        expected_sha256=context.source_file.sha256, operations=base,
        selection=[{'blockId': target['blockId']}])


@pytest.mark.anyio
async def test_actual_docx_builder_preserves_source_and_selects_only_authorized_paragraph(sample):
    editor, context, _, model, original = sample
    args = request(sample)
    # Whole-base hash includes unselected edits, but the private payload must not.
    unselected = model['blocks'][1]
    args['operations'].append({'kind': 'replaceParagraph', 'blockId': unselected['blockId'],
        'expectedObjectSha256': unselected['expectedObjectSha256'], 'text': 'SECRET OTHER DRAFT'})
    result = await NativeWordTaskInputBuilder(editor.grants, editor).build(**args)
    assert len(result.selected_paragraphs) == 1
    assert result.selected_paragraphs[0].text == 'Selected draft'
    assert result.selected_paragraphs[0].expected_object_sha256 == model['blocks'][0]['expectedObjectSha256']
    assert result.binding.snapshot_sha256 == NativeAIService._snapshot(context, args['operations'])
    assert result.binding.draft_operations_sha256 == canonical_digest(args['operations'])
    assert result.instruction_sha256 == hashlib.sha256(args['instruction'].encode()).hexdigest()
    assert await editor.read_file(context) == original
    serialized = result.model_dump_json()
    assert 'SECRET OTHER DRAFT' not in serialized
    assert '未经选择的机密段落' not in serialized
    assert args['server_session_reference'] not in repr(result)


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['source', 'delete_session', 'expire_session', 'capabilities', 'context'])
async def test_actual_docx_builder_rejects_observed_identity_change_after_preview(sample, fault):
    editor, context, session, _, original = sample
    args = request(sample)
    preview = editor.preview
    calls = 0
    injected = False
    async def changing_preview(*positional, **kwargs):
        nonlocal calls, injected
        result = await preview(*positional, **kwargs)
        calls += 1
        if calls == 1 and fault == 'source':
            injected = True
            key = bind_native_workspace(editor.workspace, context.scope)
            await editor.workspace.awrite_bytes(key, context.source_file.path, original + b'changed')
        elif calls == 2:
            injected = True
            if fault == 'delete_session':
                editor.grants.repository.sessions.clear()
            elif fault == 'expire_session':
                editor.grants.repository.sessions[args['server_session_reference']] = replace(
                    session, expires_at=datetime.now(UTC) - timedelta(seconds=1))
            elif fault == 'capabilities':
                session.capabilities['native_editor'] = False
            elif fault == 'context':
                editor.repository.get_revision.return_value.context = context.model_copy(update={'revision': 2})
        return result
    editor.preview = changing_preview
    with pytest.raises(ValueError, match='^native_word_builder_invalid$') as error:
        await NativeWordTaskInputBuilder(editor.grants, editor).build(**args)
    assert injected, 'fault must execute; missing engine/dependency is not negative evidence'
    assert args['server_session_reference'] not in str(error.value)


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['table', 'forged_object_hash', 'forged_allowed_operations', 'notes'])
async def test_actual_docx_builder_rejects_nonbody_and_forged_authority(sample, fault):
    editor, _, _, model, _ = sample
    args = request(sample)
    await editor.preview(sample[1], expected_sha256=args['expected_sha256'], operations=[])
    if fault == 'table':
        args['selection'] = [{'blockId': model['blocks'][2]['blockId']}]
    elif fault == 'forged_object_hash':
        args['operations'][0]['expectedObjectSha256'] = 'f' * 64
    elif fault == 'forged_allowed_operations':
        args['selection'][0]['allowedOperations'] = ['deleteParagraph']
    else:
        args['selection'][0]['selectionKind'] = 'footnote'
    with pytest.raises(ValueError, match='^native_word_builder_invalid$'):
        await NativeWordTaskInputBuilder(editor.grants, editor).build(**args)


@pytest.mark.anyio
async def test_actual_docx_builder_snapshots_nested_request_before_grant_lookup(sample):
    editor, _, _, _, _ = sample
    args = request(sample)
    lookup = editor.grants.lookup_registered_session
    async def mutate(ref):
        args['operations'][0]['text'] = 'MUTATED CALLER'
        args['selection'][0]['blockId'] = 'foreign'
        return await lookup(ref)
    editor.grants.lookup_registered_session = mutate
    result = await NativeWordTaskInputBuilder(editor.grants, editor).build(**args)
    assert result.selected_paragraphs[0].text == 'Selected draft'
    assert result.selected_paragraphs[0].draft_operations[0]['text'] == 'Selected draft'


@pytest.mark.anyio
@pytest.mark.integration
async def test_actual_docx_builder_existing_atomic_task_creation_disposable_pg(sample):
    import os

    from sqlalchemy import select, text

    from smart_reporting.runtime.database import create_agent_database
    from smart_reporting.task_execution.native_word_contracts import canonical_digest
    from smart_reporting.task_execution.repository import TaskExecutionRepository

    url = os.getenv('REPORTING_TEST_DB_URL', '').strip()
    if not url:
        pytest.skip('requires disposable PostgreSQL')
    editor, _, _, _, _ = sample
    args = request(sample)
    value = await NativeWordTaskInputBuilder(editor.grants, editor).build(**args)
    database = create_agent_database(url)
    repository = TaskExecutionRepository(database.async_db)
    await repository.initialize()
    try:
        async with database.async_engine.begin() as connection:
            await connection.execute(text('TRUNCATE agentos_coding.agentos_coding_tasks CASCADE'))
        task = await repository.create_native_word_task(args['scope'], args['instruction'], value)
        assert task.scope == args['scope']
        async with database.async_engine.connect() as connection:
            stored = (await connection.execute(select(repository.tasks).where(
                repository.tasks.c.external_run_id == args['scope'].external_run_id))).mappings().one()
        async with database.async_engine.connect() as connection:
            initial = (await connection.execute(select(repository.instructions.c.content).where(
                repository.instructions.c.external_run_id == args['scope'].external_run_id))).scalar_one()
        assert initial == args['instruction']
        assert stored['native_word_input_sha256'] == canonical_digest(value.model_dump(mode='json', by_alias=True))
        assert stored['native_word_input']['selectedParagraphs'][0]['text'] == 'Selected draft'
        assert 'Selected draft' not in repr(asdict(task))
        assert args['server_session_reference'] not in repr(asdict(task))
    finally:
        async with database.async_engine.begin() as connection:
            await connection.execute(text('TRUNCATE agentos_coding.agentos_coding_tasks CASCADE'))
        await database.async_engine.dispose()
        database.sync_engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['natural_expiry', 'deleted'])
async def test_actual_docx_final_context_wait_cannot_hide_session_expiry_or_deletion(sample, monkeypatch, fault):
    import smart_reporting.report_editor.native_word_task_builder as builder_module

    editor, _, session, _, _ = sample
    args = request(sample)
    current = datetime.now(UTC)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current
    monkeypatch.setattr(builder_module, 'datetime', Clock)
    context_for_session = editor.context_for_session
    calls = 0
    injected = False
    async def changed_context(recovered):
        nonlocal calls, current, injected
        result = await context_for_session(recovered)
        calls += 1
        if calls == 2:
            injected = True
            if fault == 'natural_expiry':
                current = session.expires_at + timedelta(microseconds=1)
            else:
                editor.grants.repository.sessions.clear()
        return result
    editor.context_for_session = changed_context
    with pytest.raises(ValueError, match='^native_word_builder_invalid$'):
        await NativeWordTaskInputBuilder(editor.grants, editor).build(**args)
    assert injected and calls == 2
