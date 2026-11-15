"""Fail-closed opt-in Word task dispatch seam."""
from importlib import import_module, util
from types import SimpleNamespace
from unittest.mock import AsyncMock

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
@pytest.mark.parametrize(('checks', 'read_count'), [([False], 0), ([True, False], 1)])
async def test_word_dispatch_checks_grant_around_completed_receipt(checks, read_count):
    module = adapter()
    scope = SimpleNamespace(external_run_id='word-receipt')
    task = SimpleNamespace(scope=scope, state=module.TaskState.COMPLETED)
    repository = SimpleNamespace(get_task_snapshot=AsyncMock(return_value=task))
    dispatcher = module.WordTaskDispatcher(repository, None, None, scope_factory=object(),
                                           secret='s' * 32, transport=object(), enabled=True)
    dispatcher._completed_proposal = AsyncMock(return_value=object())
    with pytest.raises(module.ReportingError) as error:
        await dispatcher.execute(SimpleNamespace(scope=scope), authorization_check=AsyncMock(side_effect=checks))
    assert error.value.code == 'native_permission_denied'
    assert dispatcher._completed_proposal.await_count == read_count


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
        async def execute(self, ref, *, shutdown_requested=None):
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


@pytest.mark.anyio
async def test_durable_same_request_changed_input_maps_to_snapshot_conflict():
    from smart_reporting.reporting.tests.test_native_word_task_builder import inputs
    from smart_reporting.task_execution.models import TaskExecutionScope
    from smart_reporting.task_execution.repository import TaskExecutionRepositoryError

    module = adapter()
    data = inputs()
    class Repository:
        async def create_native_word_task(self, *args):
            raise TaskExecutionRepositoryError('native_word_input_conflict', 'private stored input conflict')
    dispatcher = module.WordTaskDispatcher(Repository(), data.grants, data.editor,
        scope_factory=lambda context, task_id: TaskExecutionScope(task_id, 'user', 'thread', 'workspace', 'word'),
        secret='s' * 32, enabled=True, transport=object())
    with pytest.raises(Exception) as error:
        await dispatcher.prepare(context=data.context, session_reference='c' * 64, instruction='Edit',
            expected_sha256='a' * 64, operations=[], selection=[{'blockId': 'p1'}], request_id='same')
    assert getattr(error.value, 'code', None) == 'native_ai_snapshot_changed'


@pytest.mark.anyio
async def test_capacity_is_rechecked_after_prepare_and_only_new_task_is_cancelled():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from smart_reporting.report_editor.native_ai import NativeAIService, _NativeAIJob
    from smart_reporting.reporting.tests.test_native_word_task_builder import inputs

    data = inputs()
    cancelled = []
    class Dispatcher:
        enabled = True
        def require_available(self):
            pass
        async def prepare(self, **kwargs):
            for index in range(32):
                ai._jobs[str(index)] = _NativeAIJob(str(index), data.context.digest(), 'd' * 64,
                    'user', datetime.now(UTC))
            return SimpleNamespace(scope=SimpleNamespace(external_run_id='only-this-new-task'))
        async def execute(self, ref, *, shutdown_requested=None):
            import asyncio
            await asyncio.Event().wait()
        async def cancel(self, ref):
            cancelled.append(ref.scope.external_run_id)
    ai = NativeAIService(data.editor, planner=object(), enabled=True, word_task_dispatcher=Dispatcher())
    try:
        with pytest.raises(Exception) as error:
            await ai.start_edit(data.session, instruction='Edit', expected_sha256='a' * 64,
                operations=[], selection=[{'blockId': 'p1'}], client_request_id='capacity',
                server_session_reference='c' * 64)
        assert getattr(error.value, 'code', None) == 'native_ai_busy'
        assert cancelled == ['only-this-new-task']
        assert 'only-this-new-task' not in ai._jobs
    finally:
        await ai.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("swallow_cancel", [False, True])
async def test_channel_revocation_cancels_running_word_execution(swallow_cancel):
    import asyncio
    from types import SimpleNamespace

    from smart_reporting.report_editor.native_ai import NativeAIService
    from smart_reporting.reporting.tests.test_native_word_task_builder import inputs

    data = inputs()
    active = True
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def authorized():
        return active

    class Dispatcher:
        enabled = True

        def require_available(self):
            pass

        async def prepare(self, **kwargs):
            return SimpleNamespace(scope=SimpleNamespace(external_run_id="channel-word-task"))

        async def execute(self, ref, **kwargs):
            assert await kwargs["authorization_check"]()
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                if swallow_cancel:
                    return object()  # A late dependency result must never become a candidate.
                raise

    ai = NativeAIService(data.editor, planner=object(), enabled=True, word_task_dispatcher=Dispatcher())
    try:
        await ai.start_edit(data.session, instruction="Edit", expected_sha256="a" * 64,
                            operations=[], selection=[{"blockId": "p1"}],
                            authorization_check=authorized, server_session_reference="c" * 64)
        await asyncio.wait_for(started.wait(), 2)
        active = False
        await asyncio.wait_for(cancelled.wait(), 2)
        job = ai._jobs["channel-word-task"]
        await asyncio.wait_for(asyncio.shield(job.task), 2)
        assert job.status == "failed"
        assert job.error["code"] == "native_permission_denied"
        assert job.proposal is None
    finally:
        await ai.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize('during_source_io', [False, True])
async def test_word_mcp_rechecks_channel_grant_on_each_tool_call(monkeypatch, during_source_io):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.report_editor.native_word_task_builder import NativeWordTaskInputBuilder
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.tests.test_native_word_task_builder import inputs
    from smart_reporting.task_execution.models import TaskState
    from smart_reporting.task_execution.native_word_contracts import canonical_digest

    module = adapter()
    data = inputs()
    value = await NativeWordTaskInputBuilder(data.grants, data.editor).build(**data.args)
    ref = module.WordTaskReference(data.args['scope'], canonical_digest(value.model_dump(mode='json', by_alias=True)), value)
    task = SimpleNamespace(state=TaskState.ACTIVE, state_version=1, current_internal_run_id='run',
                           current_attempt_no=1, deadline_at=datetime.now(UTC) + timedelta(minutes=1))
    repository = SimpleNamespace(
        get_task_snapshot=AsyncMock(return_value=task), resume_current=AsyncMock(return_value=(task, None)),
        recover_native_word_candidate=AsyncMock(return_value=None), read_native_word_input=AsyncMock(),
        attempt_instruction=AsyncMock(return_value=data.args['instruction']),
        commit_native_word_candidate=AsyncMock(),
    )
    bridges = []
    original_bridge = module.WordTaskMcpBridge

    def bridge(**kwargs):
        result = original_bridge(**kwargs)
        bridges.append(result)
        return result

    monkeypatch.setattr(module, 'WordTaskMcpBridge', bridge)
    active = True
    flip_during_io = False

    async def authorized():
        return active

    async def current_editor(*args):
        nonlocal active
        if flip_during_io:
            active = False

    class TransportFinished(Exception):
        pass

    class Transport:
        async def run(self, *, server, ticket, task_id, instruction):
            nonlocal active, flip_during_io
            # Exercise the actual bridge verifier and dispatcher's authorizer.
            await bridges[0]._authorize(task_id, ticket=ticket)
            if during_source_io:
                flip_during_io = True
            else:
                active = False
            with pytest.raises(ReportingError) as denied:
                await bridges[0]._authorize(task_id, ticket=ticket)
            assert denied.value.code == 'native_permission_denied'
            raise TransportFinished()

    dispatcher = module.WordTaskDispatcher(repository, data.grants, data.editor,
        scope_factory=None, secret='s' * 32, transport=Transport(), enabled=True)
    dispatcher._current_editor = current_editor
    dispatcher._close_failed_claim = AsyncMock()
    task_session = SimpleNamespace(lease=SimpleNamespace(owner='worker', epoch=1), assert_alive=lambda: None)
    with pytest.raises(TransportFinished):
        await dispatcher._execute_claim(ref, task_session, authorization_check=authorized)
    repository.commit_native_word_candidate.assert_not_awaited()
    assert bridges[0]._closed
