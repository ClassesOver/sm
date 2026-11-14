"""Synthetic transport, actual authenticated MCP/PG/DOCX and existing HTTP routes.

No real Codex/provider; no production task/executor registration.
"""
from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
from types import SimpleNamespace

import pytest
from docx import Document
from fastapi import FastAPI
from fastmcp.utilities.tests import asgi_server
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_ai import NativeAIService
from smart_reporting.report_editor.native_ai_api import create_native_ai_router
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_import import NativeImportService
from smart_reporting.report_editor.native_import_api import create_native_import_router
from smart_reporting.report_editor.native_word_task_dispatcher import WordTaskDispatcher
from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication
from smart_reporting.task_execution.models import TaskExecutionScope, TaskState
from smart_reporting.task_execution.tests.test_native_word_repository import (
    word_repository as word_repository,
)
from smart_reporting.tests.test_reporting_request_identity import SECRET, _capability

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


class SyntheticMcpTransport:
    def __init__(self):
        self.calls = 0
        self.proposed = asyncio.Event()
        self.release = None
        self.mode = 'valid'

    async def run(self, *, server, ticket, task_id, instruction):
        self.calls += 1
        assert instruction == '  Rewrite selected paragraph  '
        async with asgi_server(server) as endpoint:
            async with endpoint.client(auth=ticket) as client:
                context = (await client.call_tool('get_document_context', {'task_id': task_id})).data
                # Public tool context exposes authorized IDs, not source bytes/paths.
                block_id = context['blocks'][0]['blockId']
                await client.call_tool('read_blocks', {'task_id': task_id, 'block_ids': [block_id]})
                result = await client.call_tool('propose_operations', {'task_id': task_id,
                    'summary': 'Synthetic checked candidate', 'operations': [
                        {'kind': 'replaceParagraph', 'blockId': block_id, 'text': 'Synthetic candidate'}]})
                final = result.data['proposal']
                self.proposed.set()
                if self.release is not None:
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        # Deliberately malicious late provider behavior; server must refuse.
                        if self.mode != 'swallow_cancel':
                            raise
                if self.mode == 'mismatch':
                    final['summary'] = 'Not the registered candidate'
                return final


@pytest.fixture
async def chain(tmp_path, word_repository):
    from smart_reporting.app import require_workspace_capability

    repository, _ = word_repository
    publication, _, _ = await create_publication(tmp_path)
    editor = NativeEditorService(publication.workspace, publication.repository, publication.editor_grants,
        report_editor=None, docx_enabled=True, publication=publication)
    transport = SyntheticMcpTransport()
    def scope_factory(context, task_id):
        return TaskExecutionScope(task_id, context.scope.user_id, context.scope.thread_id,
            bind_native_workspace(editor.workspace, context.scope), 'word-chain-test-only')
    dispatcher = WordTaskDispatcher(repository, editor.grants, editor, scope_factory=scope_factory,
        secret='word-test-only-isolated-ticket-key-0123456789', transport=transport, enabled=True)
    ai = NativeAIService(editor, planner=object(), enabled=True, word_task_dispatcher=dispatcher)
    app = FastAPI()
    app.state.agentos_context = SimpleNamespace(settings=SimpleNamespace(workspace_hmac_secret=SECRET))
    app.middleware('http')(require_workspace_capability)
    app.include_router(create_native_import_router(NativeImportService(editor.workspace,
        editor.repository, editor.grants), enabled=True))
    app.include_router(create_native_editor_router(editor.grants, editor=editor, cookie_secure=False))
    app.include_router(create_native_ai_router(editor.grants, editor=editor, ai=ai))
    document = Document()
    document.add_paragraph('Selected original')
    document.add_paragraph('UNCHANGED CONTROL')
    stream = BytesIO()
    document.save(stream)
    original = stream.getvalue()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            uploaded = await client.post('/reports/v1/native/import', headers={
                'X-Workspace-Thread': 'thread-1', 'X-Workspace-Capability': _capability()},
                data={'requestId': 'word-chain-import'}, files={'file': ('synthetic.docx', original)})
            assert uploaded.status_code == 200, uploaded.text
            opened = await client.get(uploaded.json()['editor']['url'], follow_redirects=True)
            assert opened.status_code == 200
            base = opened.url.path + '/api'
            context = (await client.get(base + '/context')).json()
            headers = {'Origin': 'http://test', 'X-CSRF-Token': context['csrfToken']}
            preview = await client.post(base + '/preview', headers=headers,
                json={'expectedSha256': hashlib.sha256(original).hexdigest(), 'operations': []})
            assert preview.status_code == 200, preview.text
            payload = {'clientRequestId': 'word-chain-request', 'instruction': '  Rewrite selected paragraph  ',
                'expectedSha256': hashlib.sha256(original).hexdigest(), 'operations': [],
                'selection': [{'blockId': preview.json()['model']['blocks'][0]['blockId']}]}
            yield SimpleNamespace(client=client, base=base, headers=headers, payload=payload,
                original=original, ai=ai, transport=transport, repository=repository, editor=editor,
                context=context)
    finally:
        await ai.aclose()


async def started(chain):
    response = await chain.client.post(chain.base + '/ai/start', headers=chain.headers, json=chain.payload)
    assert response.status_code == 200, response.text
    return response.json()


async def settled(chain, edit_id):
    response = await chain.client.get(chain.base + '/ai/' + edit_id + '?waitMs=20000')
    assert response.status_code == 200, response.text
    return response.json()


async def test_existing_http_start_status_explicit_accept_save_and_independent_docx_readback(chain):
    first = await started(chain)
    retry = await started(chain)
    assert retry['editId'] == first['editId']
    done = await settled(chain, first['editId'])
    assert done['status'] == 'succeeded', done
    assert done['accepted'] is False and chain.transport.calls == 1
    task = await chain.repository.get_task_snapshot(first['editId'])
    assert task.state is TaskState.COMPLETED
    # Same request content mismatch must not start another provider.
    conflict = await chain.client.post(chain.base + '/ai/start', headers=chain.headers,
        json={**chain.payload, 'instruction': 'Different instruction'})
    assert conflict.status_code == 409
    stale = await chain.client.post(chain.base + '/ai/' + first['editId'] + '/accept', headers=chain.headers,
        json={'expectedSha256': chain.payload['expectedSha256'], 'snapshotSha256': done['snapshotSha256'],
              'operations': [{'kind': 'deleteParagraph', 'blockId': chain.payload['selection'][0]['blockId']}]})
    assert stale.status_code == 409
    accepted = await chain.client.post(chain.base + '/ai/' + first['editId'] + '/accept', headers=chain.headers,
        json={'expectedSha256': chain.payload['expectedSha256'], 'snapshotSha256': done['snapshotSha256'], 'operations': []})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['accepted'] is True
    saved = await chain.client.post(chain.base + '/save', headers=chain.headers,
        json={'requestId': 'word-chain-save', 'expectedSha256': chain.payload['expectedSha256'],
              'operations': accepted.json()['operations']})
    assert saved.status_code == 200, saved.text
    # Use persisted revision lookup and independent DOCX parser, not candidate text.
    document_id = chain.context['context']['documentId']
    old = await chain.editor.repository.get_revision(document_id, 1,
        scope=__import__('smart_reporting.report_editor.native_models', fromlist=['NativeScope']).NativeScope.model_validate(
            chain.context['context']['scope']))
    new = await chain.editor.repository.get_revision(document_id, 2, scope=old.context.scope)
    assert await chain.editor.read_file(old.context) == chain.original
    content = await chain.editor.read_file(new.context)
    assert [p.text for p in Document(BytesIO(content)).paragraphs] == ['Synthetic candidate', 'UNCHANGED CONTROL']
    events = await chain.client.get(chain.base + '/ai/' + first['editId'] + '/events')
    assert events.status_code == 200
    assert all(secret not in events.text for secret in ['word-test-only-isolated-ticket-key',
        'Selected original', 'UNCHANGED CONTROL', 'Bearer ', 'native-word-task-mcp-v1'])


async def test_cancel_before_start_tombstone_prevents_provider(chain):
    cancelled = await chain.client.post(chain.base + '/ai/cancel-request', headers=chain.headers,
        json={'clientRequestId': chain.payload['clientRequestId']})
    assert cancelled.status_code == 200
    result = await started(chain)
    assert result['status'] == 'cancelled'
    assert chain.transport.calls == 0


async def test_cancel_after_tool_registration_rejects_late_swallowed_candidate(chain):
    chain.transport.release = asyncio.Event()
    chain.transport.mode = 'swallow_cancel'
    result = await started(chain)
    await asyncio.wait_for(chain.transport.proposed.wait(), timeout=20)
    cancelled = await chain.client.post(chain.base + '/ai/' + result['editId'] + '/cancel', headers=chain.headers)
    assert cancelled.status_code == 200, cancelled.text
    done = await settled(chain, result['editId'])
    assert done['status'] == 'cancelled' and 'proposal' not in done
    assert (await chain.repository.get_task_snapshot(result['editId'])).state is TaskState.CANCELLED


async def test_model_final_must_equal_actual_mcp_registration(chain):
    chain.transport.mode = 'mismatch'
    result = await started(chain)
    done = await settled(chain, result['editId'])
    assert done['status'] == 'failed' and 'proposal' not in done
    assert (await chain.repository.get_task_snapshot(result['editId'])).state is not TaskState.COMPLETED


async def test_old_executor_cancel_after_pg_takeover_must_not_cancel_new_claim(chain):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    chain.transport.release = asyncio.Event()
    result = await started(chain)
    await asyncio.wait_for(chain.transport.proposed.wait(), timeout=20)
    task_id = result['editId']
    async with chain.repository.db.db_engine.begin() as connection:
        await connection.execute(update(chain.repository.tasks).where(
            chain.repository.tasks.c.external_run_id == task_id).values(
                lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    new_lease = await chain.repository.claim_lease(task_id, 'new-owner-after-expiry')
    assert new_lease is not None
    task = await chain.repository.get_task_snapshot(task_id)
    current, _ = await chain.repository.resume_current(task_id, new_lease, task.state_version)
    assert current.lease_owner == 'new-owner-after-expiry'
    old_job = chain.ai._jobs[task_id]
    old_job.task.cancel()  # local executor cancellation, NOT authenticated user cancel
    await asyncio.gather(old_job.task, return_exceptions=True)
    after = await chain.repository.get_task_snapshot(task_id)
    assert after.state is TaskState.ACTIVE, 'old executor cancellation terminated new claim'
    assert after.lease_owner == current.lease_owner
    assert after.lease_epoch == current.lease_epoch
    assert after.state_version == current.state_version
