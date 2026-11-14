"""Trusted private Word input derivation; no production task submission."""
from __future__ import annotations

import hashlib
from importlib import import_module, util
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.native_models import NativeEditorContext, NativeScope
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.task_execution.models import TaskExecutionScope


def builder_class():
    name = 'smart_reporting.report_editor.native_word_task_builder'
    assert util.find_spec(name) is not None, 'trusted Word input builder missing'
    return import_module(name).NativeWordTaskInputBuilder


def inputs():
    from datetime import UTC, datetime, timedelta

    context = NativeEditorContext(documentId='doc', revision=1, format='docx', origin='upload',
        scope=NativeScope(database='db', companyId='company', userId='user', threadId='thread'),
        sourceFile=ArtifactFile(path='native/source.docx', size=1, sha256='a' * 64,
            mediaType='application/vnd.openxmlformats-officedocument.wordprocessingml.document'))
    session = SimpleNamespace(report_id='doc', revision=1, workflow_run_id='native:doc',
        context_sha256=context.digest(), expires_at=datetime.now(UTC) + timedelta(minutes=5),
        capabilities={'native_editor': True})
    block = {'blockId': 'p1', 'type': 'paragraph', 'text': 'Selected source',
             'editable': True, 'capabilities': ['replaceParagraph'], 'expectedObjectSha256': 'b' * 64}
    class Grants:
        async def lookup_registered_session(self, ref):
            return session
    class Editor:
        def require_enabled(self, format):
            assert format == 'docx'
        async def context_for_session(self, recovered):
            assert recovered is session
            return context
        async def preview(self, recovered, **kwargs):
            return {'model': {'blocks': [block]}}
    args = dict(scope=TaskExecutionScope('task', 'user', 'thread', 'workspace', 'word-test'),
        server_session_reference='c' * 64, instruction='  Keep exact whitespace  ',
        expected_sha256='a' * 64, operations=[], selection=[{'blockId': 'p1'}])
    return SimpleNamespace(grants=Grants(), editor=Editor(), context=context, session=session,
                           block=block, args=args)


@pytest.mark.anyio
async def test_builder_derives_authority_and_hashes_without_trimming():
    factory = builder_class()
    data = inputs()
    result = await factory(data.grants, data.editor).build(**data.args)
    assert result.binding.scope.user_id == 'user'
    assert result.binding.document_id == 'doc'
    assert result.binding.context_sha256 == data.context.digest()
    assert result.instruction_sha256 == hashlib.sha256(data.args['instruction'].encode()).hexdigest()
    assert result.selected_paragraphs[0].text == 'Selected source'
    assert result.selected_paragraphs[0].expected_object_sha256 == 'b' * 64
    assert 'Selected source' not in repr(result)


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['owner', 'thread', 'expected', 'blank', 'long', 'selection', 'many', 'forged'])
async def test_builder_rejects_untrusted_or_invalid_request(fault):
    factory = builder_class()
    data = inputs()
    if fault in {'owner', 'thread'}:
        data.args['scope'] = TaskExecutionScope('task', 'foreign' if fault == 'owner' else 'user',
            'foreign' if fault == 'thread' else 'thread', 'workspace', 'word-test')
    elif fault == 'expected':
        data.args['expected_sha256'] = 'f' * 64
    elif fault == 'blank':
        data.args['instruction'] = ' \n '
    elif fault == 'long':
        data.args['instruction'] = 'a' * 2001
    elif fault == 'selection':
        data.args['selection'] = [{'blockId': 'p1', 'cellId': 'c1'}]
    elif fault == 'many':
        data.args['operations'] = [{}] * 501
    else:
        data.args['selection'][0]['allowedOperations'] = ['deleteParagraph']
    with pytest.raises(ValueError, match='native_word_builder_'):
        await factory(data.grants, data.editor).build(**data.args)


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['capabilities', 'context', 'expired', 'deleted'])
async def test_builder_revalidates_private_identity_after_previews(fault):
    factory = builder_class()
    data = inputs()
    old = data.editor.preview
    calls = 0
    async def preview(*args, **kwargs):
        nonlocal calls
        result = await old(*args, **kwargs)
        calls += 1
        if calls == 2:
            if fault == 'capabilities':
                data.session.capabilities['native_editor'] = False
            elif fault == 'context':
                data.context.source_file.sha256 = 'd' * 64
            else:
                async def invalid(ref):
                    raise ValueError('registered session unavailable')
                data.grants.lookup_registered_session = invalid
        return result
    data.editor.preview = preview
    with pytest.raises(ValueError, match='native_word_builder_'):
        await factory(data.grants, data.editor).build(**data.args)


@pytest.mark.anyio
async def test_builder_snapshots_request_before_first_await():
    factory = builder_class()
    data = inputs()
    old = data.grants.lookup_registered_session
    async def lookup(ref):
        data.args['operations'].append({'kind': 'replaceParagraph', 'blockId': 'p1', 'text': 'MUTATED'})
        data.args['selection'][0]['blockId'] = 'foreign'
        return await old(ref)
    data.grants.lookup_registered_session = lookup
    result = await factory(data.grants, data.editor).build(**data.args)
    assert result.selected_paragraphs[0].block_id == 'p1'
    assert result.selected_paragraphs[0].text == 'Selected source'
    assert result.selected_paragraphs[0].draft_operations == []


@pytest.mark.anyio
async def test_builder_rejects_source_table_despite_plain_block_selection():
    factory = builder_class()
    data = inputs()
    data.block.update(type='table', cells=[])
    with pytest.raises(ValueError, match='native_word_builder_'):
        await factory(data.grants, data.editor).build(**data.args)


@pytest.mark.anyio
async def test_builder_rejects_natural_expiry_during_final_context_await(monkeypatch):
    from datetime import UTC, datetime, timedelta

    factory = builder_class()
    module = import_module(factory.__module__)
    data = inputs()
    current = datetime.now(UTC)
    data.session.expires_at = current + timedelta(seconds=1)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current
    monkeypatch.setattr(module, 'datetime', Clock, raising=False)
    context_for_session = data.editor.context_for_session
    calls = 0
    async def advancing_context(session):
        nonlocal calls, current
        result = await context_for_session(session)
        calls += 1
        if calls == 2:
            current += timedelta(seconds=2)
        return result
    data.editor.context_for_session = advancing_context
    with pytest.raises(ValueError, match='^native_word_builder_invalid$'):
        await factory(data.grants, data.editor).build(**data.args)
    assert calls == 2


@pytest.mark.anyio
async def test_builder_rechecks_registry_after_final_context_await():
    factory = builder_class()
    data = inputs()
    context_for_session = data.editor.context_for_session
    calls = 0
    async def deleting_context(session):
        nonlocal calls
        result = await context_for_session(session)
        calls += 1
        if calls == 2:
            async def missing(ref):
                raise ValueError('missing')
            data.grants.lookup_registered_session = missing
        return result
    data.editor.context_for_session = deleting_context
    with pytest.raises(ValueError, match='^native_word_builder_invalid$'):
        await factory(data.grants, data.editor).build(**data.args)
    assert calls == 2
