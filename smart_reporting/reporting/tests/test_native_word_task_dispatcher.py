"""Fail-closed opt-in Word task dispatch seam."""
from importlib import import_module, util

import pytest


def adapter():
    name = 'smart_reporting.report_editor.native_word_task_dispatcher'
    assert util.find_spec(name) is not None, 'trusted Word dispatcher missing'
    return import_module(name)


def test_explicit_word_dispatch_without_transport_never_falls_back():
    module = adapter()
    dispatcher = module.WordTaskDispatcher(None, None, None, scope_factory=None, secret='s' * 32,
                                           transport=None, enabled=True)
    with pytest.raises(Exception) as error:
        dispatcher.require_available()
    assert error.value.code == 'native_word_task_unavailable'


@pytest.mark.anyio
async def test_existing_native_start_selected_word_dispatch_unavailable_fails_closed():
    import inspect

    from smart_reporting.report_editor.native_ai import NativeAIService
    from smart_reporting.reporting.tests.test_native_word_task_builder import inputs

    assert 'word_task_dispatcher' in inspect.signature(NativeAIService).parameters
    module = adapter()
    data = inputs()
    dispatcher = module.WordTaskDispatcher(None, None, None, scope_factory=None, secret='s' * 32,
                                           transport=None, enabled=True)
    ai = NativeAIService(data.editor, planner=object(), enabled=True, word_task_dispatcher=dispatcher)
    with pytest.raises(Exception) as error:
        await ai.start_edit(data.session, instruction='Edit', expected_sha256='a' * 64,
                            operations=[], selection=[{'blockId': 'p1'}])
    assert error.value.code == 'native_word_task_unavailable'


@pytest.mark.anyio
async def test_current_editor_cannot_hide_inplace_session_change_during_source_read():
    from smart_reporting.report_editor.native_word_task_builder import NativeWordTaskInputBuilder
    from smart_reporting.reporting.tests.test_native_word_task_builder import inputs
    from smart_reporting.task_execution.native_word_contracts import canonical_digest

    module = adapter()
    data = inputs()
    value = await NativeWordTaskInputBuilder(data.grants, data.editor).build(**data.args)
    ref = module.WordTaskReference(data.args['scope'], canonical_digest(value.model_dump(mode='json', by_alias=True)), value)
    async def changing_read(context):
        data.session.capabilities['native_editor'] = False
        return b'fake unit source'
    data.editor.read_file = changing_read
    dispatcher = module.WordTaskDispatcher(None, data.grants, data.editor,
        scope_factory=None, secret='s' * 32)
    with pytest.raises(Exception) as error:
        await dispatcher._current_editor(ref, data.args['server_session_reference'])
    assert error.value.code == 'native_word_task_invalid'


@pytest.mark.anyio
async def test_current_editor_rechecks_context_after_source_io():
    from smart_reporting.report_editor.native_word_task_builder import NativeWordTaskInputBuilder
    from smart_reporting.reporting.tests.test_native_word_task_builder import inputs
    from smart_reporting.task_execution.native_word_contracts import canonical_digest

    module = adapter()
    data = inputs()
    value = await NativeWordTaskInputBuilder(data.grants, data.editor).build(**data.args)
    ref = module.WordTaskReference(data.args['scope'], canonical_digest(value.model_dump(mode='json', by_alias=True)), value)
    async def context_for_session(session):
        return data.context
    data.editor.context_for_session = context_for_session
    async def changing_read(context):
        data.context = data.context.model_copy(update={'source_file': data.context.source_file.model_copy(
            update={'sha256': 'd' * 64})})
        return b'fake unit source'
    data.editor.read_file = changing_read
    dispatcher = module.WordTaskDispatcher(None, data.grants, data.editor,
        scope_factory=None, secret='s' * 32)
    with pytest.raises(Exception) as error:
        await dispatcher._current_editor(ref, data.args['server_session_reference'])
    assert error.value.code == 'native_word_task_invalid'


@pytest.mark.anyio
async def test_parallel_exact_start_retry_never_cancels_shared_durable_task():
    import asyncio
    from types import SimpleNamespace

    from smart_reporting.report_editor.native_ai import NativeAIService
    from smart_reporting.reporting.tests.test_native_word_task_builder import inputs

    data = inputs()
    prepared = asyncio.Event()
    release = asyncio.Event()
    cancelled = []
    calls = 0
    class Dispatcher:
        enabled = True
        def require_available(self):
            pass
        async def prepare(self, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                prepared.set()
            await release.wait()
            return SimpleNamespace(scope=SimpleNamespace(external_run_id='shared-word-task'))
        async def execute(self, ref):
            await asyncio.Event().wait()
        async def cancel(self, ref):
            cancelled.append(ref.scope.external_run_id)
    ai = NativeAIService(data.editor, planner=object(), enabled=True, word_task_dispatcher=Dispatcher())
    kwargs = dict(instruction='Edit', expected_sha256='a' * 64, operations=[], selection=[{'blockId': 'p1'}],
                  client_request_id='same', server_session_reference='c' * 64)
    first = asyncio.create_task(ai.start_edit(data.session, **kwargs))
    second = asyncio.create_task(ai.start_edit(data.session, **kwargs))
    try:
        await asyncio.wait_for(prepared.wait(), 2)
        release.set()
        a, b = await asyncio.gather(first, second)
        assert a['editId'] == b['editId'] == 'shared-word-task'
        assert cancelled == []
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
        await ai.aclose()


@pytest.mark.anyio
async def test_accept_cancel_during_completed_lookup_is_domain_rejection_not_typeerror():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from smart_reporting.report_editor.native_ai import NativeAIService, _NativeAIJob
    from smart_reporting.report_editor.native_word_ai import NativeWordAIProposal
    from smart_reporting.reporting.tests.test_native_word_task_builder import inputs

    data = inputs()
    data.editor.preview = None
    async def preview(*args, **kwargs):
        return {'draftSha256': 'd' * 64}
    data.editor.preview = preview
    class Dispatcher:
        enabled = True
        async def completed(self, *args, **kwargs):
            job.status, job.proposal = 'cancelled', None
            return NativeWordAIProposal(summary='Candidate', operations=[{'kind': 'replaceParagraph',
                'arguments': {'blockId': 'p1', 'text': 'Candidate', 'expectedObjectSha256': 'b' * 64}}])
    ai = NativeAIService(data.editor, planner=object(), enabled=True, word_task_dispatcher=Dispatcher())
    job = _NativeAIJob('job', data.context.digest(), ai._snapshot(data.context, []), 'user', datetime.now(UTC),
        status='succeeded', proposal={'summary': 'Candidate', 'operations': [{'kind': 'replaceParagraph',
            'blockId': 'p1', 'text': 'Candidate', 'expectedObjectSha256': 'b' * 64}]},
        word_task_reference=SimpleNamespace())
    ai._jobs[job.edit_id] = job
    with pytest.raises(Exception) as error:
        await ai.accept_edit(data.session, job.edit_id, expected_sha256='a' * 64, operations=[],
            snapshot_sha256=job.snapshot_sha256, server_session_reference='c' * 64)
    assert getattr(error.value, 'code', None) == 'native_ai_not_ready'
