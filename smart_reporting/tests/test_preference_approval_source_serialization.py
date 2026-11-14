"""真实管理SQL批准与既有来源锁；测试合同不代替完整生产批准。"""

import asyncio
import sys

import pytest

from smart_reporting.management.models import ManagementError
from smart_reporting.report_editor.trace_retention import source_lifecycle_lock
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_approval_apply import (
    approved as approved,
)
from smart_reporting.tests.test_preference_approval_apply import (
    count_publications,
)
from smart_reporting.tests.test_preference_verification_handoff import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_source_writer_waits_for_apply_commit_and_changed_source_cannot_replay(case, approved, monkeypatch):
    service, request, _, _ = approved
    editor = service.handoff.bound.editor
    context = await editor.context_for_session(await case[8].lookup_session(case[6]))
    source = editor.workspace_registry.get(context.scope['threadId']).root / context.markdown_path
    checked, release, writer_started, wrote = (asyncio.Event() for _ in range(4))
    original = service.evidence._current_artifacts

    async def pause_after_source_check(*args):
        result = await original(*args)
        checked.set()
        await release.wait()
        return result

    async def writer():
        writer_started.set()
        async with source_lifecycle_lock(editor, context):
            source.write_bytes(b'changed after source verification')
            wrote.set()

    monkeypatch.setattr(service.evidence, '_current_artifacts', pause_after_source_check)
    applying = asyncio.create_task(service.preferences.apply_approved(case[5], **request))
    writing = None
    try:
        await asyncio.wait_for(checked.wait(), 20)
        writing = asyncio.create_task(writer())
        await asyncio.wait_for(writer_started.wait(), 5)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(wrote.wait(), .2)
        assert await count_publications(case) == (0, 0)
        release.set()
        result = await asyncio.wait_for(applying, 20)
        assert result['revision'] == 1
        await asyncio.wait_for(writing, 5)
    finally:
        release.set()
        await asyncio.gather(applying, *([writing] if writing else []), return_exceptions=True)
    assert await count_publications(case) == (1, 1)
    with pytest.raises(ManagementError):
        await service.preferences.apply_approved(case[5], **request)
    assert await count_publications(case) == (1, 1)


@pytest.mark.parametrize('outcome', ['cancel', 'rollback'])
async def test_source_lock_released_after_interrupted_apply_without_partial_publication(case, approved, monkeypatch, outcome):
    service, request, _, _ = approved
    editor = service.handoff.bound.editor
    context = await editor.context_for_session(await case[8].lookup_session(case[6]))
    checked, release, acquired = (asyncio.Event() for _ in range(3))
    original = service.preferences._audit

    async def interrupted(connection, action, **details):
        result = await original(connection, action, **details)
        if action == 'format_preferences_published':
            checked.set()
            await release.wait()
            if outcome == 'rollback':
                raise RuntimeError('fixture-interrupted-before-commit')
        return result

    async def reader():
        async with source_lifecycle_lock(editor, context):
            acquired.set()

    monkeypatch.setattr(service.preferences, '_audit', interrupted)
    applying = asyncio.create_task(service.preferences.apply_approved(case[5], **request))
    reading = None
    try:
        await asyncio.wait_for(checked.wait(), 20)
        reading = asyncio.create_task(reader())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(acquired.wait(), .2)
        if outcome == 'cancel':
            applying.cancel()
            with pytest.raises(asyncio.CancelledError):
                await applying
        else:
            release.set()
            with pytest.raises(RuntimeError, match='fixture-interrupted-before-commit'):
                await applying
        await asyncio.wait_for(reading, 5)
    finally:
        release.set()
        await asyncio.gather(applying, *([reading] if reading else []), return_exceptions=True)
    assert await count_publications(case) == (0, 0)
    assert not editor._source_lifecycle_locks
    monkeypatch.setattr(service.preferences, '_audit', original)
    assert (await service.preferences.apply_approved(case[5], **request))['revision'] == 1
    assert await count_publications(case) == (1, 1)


async def test_source_lock_blocks_independent_worker_until_commit(case, approved, monkeypatch):
    service, request, _, _ = approved
    editor = service.handoff.bound.editor
    context = await editor.context_for_session(await case[8].lookup_session(case[6]))
    root = editor.workspace_registry.get(context.scope['threadId']).root
    checked, release = asyncio.Event(), asyncio.Event()
    original = service.evidence._current_artifacts

    async def paused(*args):
        result = await original(*args)
        checked.set()
        await release.wait()
        return result

    monkeypatch.setattr(service.evidence, '_current_artifacts', paused)
    applying = asyncio.create_task(service.preferences.apply_approved(case[5], **request))
    worker = waiting = None
    try:
        await asyncio.wait_for(checked.wait(), 20)
        worker = await asyncio.create_subprocess_exec(sys.executable, '-c',
            'import fcntl,sys; from pathlib import Path; '
            'f=open(sys.argv[1], "r+"); print("started", flush=True); '
            'fcntl.flock(f, fcntl.LOCK_SH); '
            'Path(sys.argv[2]).write_bytes(b"worker changed source"); print("written", flush=True)',
            str(root / '.editor-sources.lock'), str(root / context.markdown_path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        assert await asyncio.wait_for(worker.stdout.readline(), 5) == b'started\n'
        waiting = asyncio.create_task(worker.stdout.readline())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(waiting), .2)
        release.set()
        assert (await asyncio.wait_for(applying, 20))['revision'] == 1
        assert await asyncio.wait_for(waiting, 5) == b'written\n'
        assert await asyncio.wait_for(worker.wait(), 5) == 0
    finally:
        release.set()
        if worker is not None and worker.returncode is None:
            worker.kill()
            await worker.wait()
        await asyncio.gather(applying, *([waiting] if waiting else []), return_exceptions=True)
    assert await count_publications(case) == (1, 1)
    with pytest.raises(ManagementError):
        await service.preferences.apply_approved(case[5], **request)
    assert await count_publications(case) == (1, 1)
