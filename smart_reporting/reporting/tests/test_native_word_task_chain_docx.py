"""Synthetic transport, actual authenticated MCP/PG/DOCX and existing HTTP routes.

No real Codex/provider; no production task/executor registration.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from docx import Document
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.utilities.tests import asgi_server
from httpx import ASGITransport, AsyncClient

from smart_reporting.external_word_transport import ExternalWordTransport
from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_ai import NativeAIService
from smart_reporting.report_editor.native_ai_api import create_native_ai_router
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_import import NativeImportService
from smart_reporting.report_editor.native_import_api import create_native_import_router
from smart_reporting.report_editor.native_repository import NativeDocumentRepository
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
async def chain(tmp_path, word_repository, request):
    from sqlalchemy import text

    from smart_reporting.app import require_workspace_capability

    repository, database = word_repository
    publication, _, _ = await create_publication(tmp_path)
    # The publication helper's minimal fake supports save-only tests, NOT import.
    # Use the real repository contract required by NativeImportService here.
    native_repository = NativeDocumentRepository(database.async_engine)
    await native_repository.create_schema()
    assert callable(native_repository.create_from_source)
    assert callable(native_repository.get_revision)
    assert callable(native_repository.complete_revision)
    async with database.async_engine.begin() as connection:
        await connection.execute(text('TRUNCATE report_native_documents_v1 CASCADE'))
    publication.repository = native_repository
    editor = NativeEditorService(publication.workspace, publication.repository, publication.editor_grants,
        report_editor=None, docx_enabled=True, publication=publication)
    transport = getattr(request, 'param', SyntheticMcpTransport)()
    def scope_factory(context, task_id):
        return TaskExecutionScope(task_id, context.scope.user_id, context.scope.thread_id,
            bind_native_workspace(editor.workspace, context.scope), 'word-chain-test-only')
    dispatcher = WordTaskDispatcher(repository, editor.grants, editor, scope_factory=scope_factory,
        secret='word-test-only-isolated-ticket-key-0123456789', transport=transport, enabled=True)
    ai = NativeAIService(editor, planner=object(), enabled=True, word_task_dispatcher=dispatcher)
    app = FastAPI()
    static = Path(__file__).resolve().parents[2] / 'report_editor' / 'static'
    if static.is_dir():
        app.mount('/reports/v1/editor/assets', StaticFiles(directory=static))
    app.state.agentos_context = SimpleNamespace(settings=SimpleNamespace(workspace_hmac_secret=SECRET))
    app.middleware('http')(require_workspace_capability)
    app.include_router(create_native_import_router(NativeImportService(editor.workspace,
        editor.repository, editor.grants), enabled=True))
    app.include_router(create_native_editor_router(editor.grants, editor=editor, cookie_secure=False, ai_enabled=True,
        report_channel_enabled=bool(os.getenv('WORD_CHANNEL_VIDEO_DIR'))))
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
            yield SimpleNamespace(app=app, publication=publication, open_url=uploaded.json()['editor']['url'],
                client=client, base=base, headers=headers, payload=payload,
                original=original, ai=ai, transport=transport, repository=repository, editor=editor,
                context=context)
    finally:
        await ai.aclose()
        async with database.async_engine.begin() as connection:
            await connection.execute(text('TRUNCATE report_native_documents_v1 CASCADE'))


async def test_chain_fixture_real_import_context_preview_preserves_source(chain):
    from smart_reporting.report_editor.native_models import NativeScope

    native_context = chain.context['context']
    revision = await chain.editor.repository.get_revision(native_context['documentId'], 1,
        scope=NativeScope.model_validate(native_context['scope']))
    assert revision is not None and revision.status == 'saved'
    assert await chain.editor.read_file(revision.context) == chain.original
    assert chain.transport.calls == 0


async def started(chain):
    response = await chain.client.post(chain.base + '/ai/start', headers=chain.headers, json=chain.payload)
    assert response.status_code == 200, response.text
    return response.json()


async def settled(chain, edit_id):
    response = await chain.client.get(chain.base + '/ai/' + edit_id + '?waitMs=20000')
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('chain', [ExternalWordTransport], indirect=True)
async def test_external_mcp_candidate_accept_save_and_readback(chain, tmp_path):
    from smart_reporting.report_editor.native_models import NativeScope
    from smart_reporting.task_execution.native_word_contracts import canonical_digest

    transport = chain.transport
    native_context = chain.context['context']
    document_id = native_context['documentId']
    scope = NativeScope.model_validate(native_context['scope'])
    original = await chain.editor.repository.get_revision(document_id, 1, scope=scope)
    task_id = 'word-' + canonical_digest({
        'context': original.context.digest(), 'request': chain.payload['clientRequestId'],
    })
    reference = transport.invite(task_id=task_id, subject='synthetic-client')
    start = await started(chain)
    assert start['editId'] == task_id
    handoff = tmp_path / 'desktop-handoff.json'
    async with asyncio.TaskGroup() as tasks:
        tasks.create_task(submit_desktop_candidate(transport, reference, task_id, handoff))
        async with asyncio.timeout(5):
            while not handoff.exists():
                await asyncio.sleep(.01)
        assert handoff.stat().st_mode & 0o777 == 0o600
        connection = json.loads(handoff.read_text(encoding='utf-8'))
        assert connection['taskId'] == task_id
        await call_candidate_tools(connection['endpoint'], connection['ticket'], task_id)
    assert not handoff.exists()
    candidate = await settled(chain, task_id)
    assert candidate['status'] == 'succeeded' and not candidate['accepted']
    assert await chain.editor.read_file(original.context) == chain.original
    accepted = await chain.client.post(chain.base + '/ai/' + task_id + '/accept',
        headers=chain.headers, json={'expectedSha256': chain.payload['expectedSha256'],
            'snapshotSha256': candidate['snapshotSha256'], 'operations': []})
    assert accepted.status_code == 200, accepted.text
    saved = await chain.client.post(chain.base + '/save', headers=chain.headers,
        json={'requestId': 'external-word-save', 'expectedSha256': chain.payload['expectedSha256'],
            'operations': accepted.json()['operations']})
    assert saved.status_code == 200, saved.text
    await verify_saved_revision(chain, saved.json()['editor']['openUrl'], document_id, scope)


@asynccontextmanager
async def serve_word_mcp(app, *, port=0):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', port))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, access_log=False))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    if serving.done():
                        await serving
                        raise RuntimeError('Word MCP listener failed to start')
                    await asyncio.sleep(.01)
            yield f'http://127.0.0.1:{port}/mcp'
        finally:
            server.should_exit = True
            await serving


async def submit_external_candidate(transport, reference, task_id):
    access = await redeem_candidate_access(transport, reference)
    app = transport.app_for_task(task_id, subject='synthetic-client')
    async with serve_word_mcp(app) as endpoint:
        await call_candidate_tools(endpoint, access.ticket, task_id)
    transport.complete(task_id, subject='synthetic-client')


async def redeem_candidate_access(transport, reference):
    async with asyncio.timeout(5):
        while True:
            try:
                return transport.redeem(reference, subject='synthetic-client')
            except ValueError:
                await asyncio.sleep(.01)


async def call_candidate_tools(endpoint, ticket, task_id):
        async with AsyncClient(trust_env=False) as anonymous:
            denied = await anonymous.post(endpoint, headers={
                'Accept': 'application/json, text/event-stream',
            }, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
            assert denied.status_code == 401
        async with Client(endpoint, auth=ticket) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert set(tools) == {
                'get_document_context', 'read_blocks', 'search_text', 'propose_operations',
            }
            description = tools['propose_operations'].description or ''
            assert '{"kind":"replaceParagraph","blockId":' in description
            with pytest.raises(ToolError):
                await client.call_tool('get_document_context', {'task_id': 'synthetic-other-task'})
            context = (await client.call_tool('get_document_context', {'task_id': task_id})).data
            block_id = context['blocks'][0]['blockId']
            await client.call_tool('read_blocks', {'task_id': task_id, 'block_ids': [block_id]})
            await client.call_tool('propose_operations', {
                'task_id': task_id, 'summary': 'External candidate', 'operations': [
                    {'kind': 'replaceParagraph', 'blockId': block_id,
                     'text': 'External synthetic candidate'},
                ],
            })


async def submit_desktop_candidate(transport, reference, task_id, handoff):
    access = await redeem_candidate_access(transport, reference)
    app = transport.app_for_task(task_id, subject='synthetic-client')
    if os.getenv('WORD_ACCEPTANCE_DESKTOP_HANDOFF'):
        from starlette.middleware.base import BaseHTTPMiddleware

        async def record_mcp_exchange(request, call_next):
            method = None
            if request.method == 'POST':
                try:
                    payload = await request.json()
                    if isinstance(payload, dict):
                        method = payload.get('method')
                except ValueError:
                    pass
            response = await call_next(request)
            if method in ('initialize', 'tools/list', 'tools/call'):
                print(f'Desktop MCP {method}: HTTP {response.status_code}', flush=True)
            return response

        app.add_middleware(BaseHTTPMiddleware, dispatch=record_mcp_exchange)
    port = int(os.getenv('WORD_ACCEPTANCE_DESKTOP_MCP_PORT', '0'))
    async with serve_word_mcp(app, port=port) as endpoint:
        staging = handoff.with_suffix(handoff.suffix + '.pending')
        fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        published = False
        completed = False
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump({'endpoint': endpoint, 'taskId': task_id, 'ticket': access.ticket}, stream)
            os.link(staging, handoff)
            published = True
            staging.unlink()
            try:
                async with asyncio.timeout(50):
                    while transport.is_pending_candidate(task_id, ticket=access.ticket):
                        await asyncio.sleep(.1)
            except TimeoutError:
                raise AssertionError(
                    'Desktop acceptance received no Word MCP candidate before the handoff deadline'
                ) from None
            transport.complete(task_id, subject='synthetic-client')
            completed = True
        finally:
            if not completed:
                transport.revoke(task_id, ticket=access.ticket)
            if published:
                handoff.unlink(missing_ok=True)
            staging.unlink(missing_ok=True)


async def verify_saved_revision(chain, open_url, document_id, scope, *, candidate='External synthetic candidate'):
    reopened_page = await chain.client.get(open_url, follow_redirects=True)
    assert reopened_page.status_code == 200
    reopened_api = reopened_page.url.path + '/api'
    served = await chain.client.get(reopened_api + '/file')
    assert served.status_code == 200
    reopened = await chain.editor.repository.get_revision(document_id, 2, scope=scope)
    content = await chain.editor.read_file(reopened.context)
    assert served.content == content
    assert [p.text for p in Document(BytesIO(content)).paragraphs] == [
        candidate, 'UNCHANGED CONTROL',
    ]


@pytest.mark.parametrize('chain', [ExternalWordTransport], indirect=True)
async def test_external_word_browser_recording(chain):
    from playwright.async_api import async_playwright

    from smart_reporting.report_editor.native_models import NativeScope
    from smart_reporting.task_execution.native_word_contracts import canonical_digest

    directory = os.getenv('WORD_ACCEPTANCE_VIDEO_DIR')
    if not directory:
        pytest.skip('Set WORD_ACCEPTANCE_VIDEO_DIR to record the local synthetic browser run')
    native_context = chain.context['context']
    document_id = native_context['documentId']
    scope = NativeScope.model_validate(native_context['scope'])
    original = await chain.editor.repository.get_revision(document_id, 1, scope=scope)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=os.getenv('WORD_ACCEPTANCE_CHROMIUM'),
            args=['--single-process', '--disable-dev-shm-usage'],
        )
        context = await browser.new_context(base_url="http://127.0.0.1:4296", record_video_dir=directory, viewport={'width': 1440, 'height': 960})
        page = await context.new_page()
        invitation = asyncio.get_running_loop().create_future()

        browser_app = FastAPI()
        browser_app.mount('/', chain.app)

        @browser_app.middleware('http')
        async def prepare_invitation(request, call_next):
            if request.url.path.endswith('/api/ai/start'):
                payload = await request.json()
                task_id = 'word-' + canonical_digest({
                    'context': original.context.digest(), 'request': payload['clientRequestId'],
                })
                reference = chain.transport.invite(task_id=task_id, subject='synthetic-client')
                invitation.set_result((reference, task_id))
            return await call_next(request)

        chain.publication.public_base_url = "http://127.0.0.1:4296"
        server = uvicorn.Server(uvicorn.Config(browser_app, host='127.0.0.1', port=4296, access_log=False))
        serving = asyncio.create_task(server.serve())
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(.05)

        try:
            await page.goto(chain.open_url)
            await page.wait_for_function(
                "document.querySelector('#report-editor')?.getAttribute('aria-busy') === 'false'",
                timeout=90_000,
            )
            await page.get_by_text('Selected original', exact=True).first.click(click_count=3)
            await page.locator('[data-action=word-edit-ai]').click()
            panel = page.get_by_role('region', name='AI 编辑选区')
            await panel.get_by_label('AI 修改要求').fill('Rewrite selected paragraph')
            async with page.expect_response(lambda response: response.url.endswith('/api/ai/start')) as started_response:
                await panel.locator('[data-ai=start]').click()
            response = await started_response.value
            body = await response.json()
            assert response.ok, body
            reference, task_id = await asyncio.wait_for(invitation, 10)
            assert body['editId'] == task_id and body['status'] in {'queued', 'running', 'pending'}, body
            await page.wait_for_timeout(1200)
            if handoff := os.getenv('WORD_ACCEPTANCE_DESKTOP_HANDOFF'):
                await submit_desktop_candidate(chain.transport, reference, task_id, Path(handoff))
            else:
                await submit_external_candidate(chain.transport, reference, task_id)
            accept = panel.locator('[data-ai=accept]')
            await accept.wait_for()
            await panel.get_by_text('查看建议修改').click()
            await page.wait_for_timeout(1500)
            await accept.click()
            await page.get_by_text('External synthetic candidate', exact=True).first.wait_for()
            await page.locator('[data-action=save]').click()
            link = page.get_by_role('link', name='打开新修订继续编辑')
            open_url = await link.get_attribute('href')
            await link.click()
            await page.get_by_text('External synthetic candidate', exact=True).first.wait_for()
            await verify_saved_revision(chain, open_url.replace("http://127.0.0.1:4296", "http://test"), document_id, scope)
            await page.wait_for_timeout(1500)
        finally:
            await context.close()
            await browser.close()
            server.should_exit = True
            await serving


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


@pytest.mark.parametrize('revoke', [False, True])
async def test_channel_invitation_delegates_to_word_mcp_and_editor_saves(chain, word_repository, revoke):
    from uuid import uuid4

    from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router
    from smart_reporting.report_channel_editor import report_channel_editor_authorizer
    from smart_reporting.report_channel_mcp import create_report_channel_mcp
    from smart_reporting.report_channel_repository import ReportChannelRepository
    from smart_reporting.report_channel_word import ChannelWordDraft, ReportChannelWordAssistant
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
    from smart_reporting.report_editor.native_models import NativeScope
    from smart_reporting.report_editor.service import token_hash

    _, database = word_repository
    channels = ReportChannelRepository(database.async_engine)
    await channels.create_schema()
    channel = uuid4().hex
    raw_session = chain.client.cookies.get(NATIVE_SESSION_COOKIE)
    session = await chain.editor.grants.lookup_session(raw_session)
    draft = ChannelWordDraft(session, chain.payload['expectedSha256'], [],
        chain.payload['selection'], token_hash(raw_session))
    origin = 'https://127.0.0.1:4296' if os.getenv('WORD_CHANNEL_TLS_CERT') else 'https://reports.test'

    async def resolve_draft(channel_id):
        return draft if channel_id == channel else None

    async def authenticate(request):
        if request.headers.get('Authorization') == 'Bearer synthetic-connector':
            return ConnectorIdentity('dsh', 'synthetic-subject', channel)
        return None

    async def resolve_channel(context):
        if context.document_id == session.report_id and context.revision == session.revision:
            return channel
        return None

    assistant = ReportChannelWordAssistant(chain.ai, resolve_draft, channels)
    app = FastAPI()
    router = create_report_channel_router(channels, authenticate,
        authorize_editor=report_channel_editor_authorizer(chain.editor, resolve_channel, allowed_origin=origin),
        public_origin=origin,
        editor_path=lambda _: chain.base.removesuffix('/api'),
        delegate_word=assistant.start, word_status=assistant.status)
    if not revoke and (directory := os.getenv('WORD_CHANNEL_VIDEO_DIR')):
        await record_channel_review(chain, router, origin, directory)
        return
    app.include_router(router)
    server = create_report_channel_mcp(app, origin=origin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=origin,
                           cookies={NATIVE_SESSION_COOKIE: raw_session}) as issuer:
        invitation = await issuer.post('/reports/v1/channels/invitations',
            headers={**chain.headers, 'Origin': origin},
            json={'connector': 'dsh', 'subject': 'synthetic-subject'})
        assert invitation.status_code == 201, invitation.text
    if revoke:
        chain.transport.release = asyncio.Event()
    async with asgi_server(server) as endpoint, endpoint.client(auth='synthetic-connector') as connector:
        joined = (await connector.call_tool('join_report_channel', {'share_link': invitation.json()['url']})).data
        assert joined['channel'] == channel
        editor_path = joined['editorUrl'].removeprefix(origin)
        async with AsyncClient(transport=ASGITransport(app=chain.app), base_url='http://test',
                               headers={'Authorization': 'Bearer synthetic-connector'}) as ungranted:
            assert (await ungranted.get(editor_path)).status_code in {401, 403}
            assert (await ungranted.get(editor_path + '/api/context')).status_code in {401, 403}
        assert (await chain.client.get(editor_path)).status_code == 200
        delegated = (await connector.call_tool('delegate_report_word_task', {'channel': channel,
            'request_id': 'channel-word', 'instruction': chain.payload['instruction']})).data
        task_id = delegated['taskId']
        assert delegated['reviewUrl'] == f"{joined['editorUrl']}#word-task={task_id}"
        assert delegated['status'] == 'running'
        status_query = {'channel': channel, 'task_id': task_id}
        if revoke:
            await asyncio.wait_for(chain.transport.proposed.wait(), 30)
            await channels.revoke(channel, connector='dsh', subject='synthetic-subject')
            chain.transport.release.set()
            job = chain.ai._jobs[task_id]
            await asyncio.wait_for(job.task, 30)
            assert job.status == 'failed' and job.proposal is None
            assert (await chain.client.get(chain.base + f'/ai/{task_id}')).status_code == 403
            return
        done = await settled(chain, task_id)
        assert done['status'] == 'succeeded' and not done['accepted'], done
        assert (await connector.call_tool('report_word_task_status', status_query)).data == {
            'taskId': task_id, 'status': 'succeeded', 'accepted': False}
        accepted = await chain.client.post(chain.base + f'/ai/{task_id}/accept', headers=chain.headers,
            json={'expectedSha256': draft.source_sha256, 'snapshotSha256': done['snapshotSha256'],
                  'operations': []})
        assert accepted.status_code == 200, accepted.text
        assert (await connector.call_tool('report_word_task_status', status_query)).data['accepted'] is True
        saved = await chain.client.post(chain.base + '/save', headers=chain.headers,
            json={'requestId': 'channel-word-save', 'expectedSha256': draft.source_sha256,
                  'operations': accepted.json()['operations']})
        assert saved.status_code == 200, saved.text
        native = chain.context['context']
        await verify_saved_revision(chain, saved.json()['editor']['openUrl'], native['documentId'],
            NativeScope.model_validate(native['scope']), candidate='Synthetic candidate')


async def record_channel_review(chain, router, share_origin, directory):
    from playwright.async_api import async_playwright

    from smart_reporting.report_editor.native_models import NativeScope
    from smart_reporting.report_channel_host import mount_report_channel

    tls_cert = os.getenv('WORD_CHANNEL_TLS_CERT')
    origin = share_origin if tls_cert else 'http://127.0.0.1:4296'
    chain.publication.public_base_url = origin
    browser_app = FastAPI()
    mount_report_channel(browser_app, router, origin=share_origin)
    browser_app.mount('/', chain.app)
    server = uvicorn.Server(uvicorn.Config(browser_app, host='127.0.0.1', port=4296, access_log=False,
        ssl_certfile=tls_cert, ssl_keyfile=os.getenv('WORD_CHANNEL_TLS_KEY')))
    serving = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(.05)
        async with Client(origin + '/reports/channel-mcp', auth='synthetic-connector') as connector, async_playwright() as playwright:
            args = ['--single-process', '--disable-dev-shm-usage']
            if tls_cert:
                args.append('--ignore-certificate-errors-spki-list=' + os.environ['WORD_CHANNEL_TLS_SPKI'])
            browser = await playwright.chromium.launch(executable_path=os.getenv('WORD_ACCEPTANCE_CHROMIUM'),
                args=args)
            context = await browser.new_context(base_url=origin, record_video_dir=directory,
                viewport={'width': 1440, 'height': 960})
            try:
                page = await context.new_page()
                await page.goto(chain.open_url)
                await page.locator('[data-action=word-edit-ai]').click(timeout=90_000)
                await page.get_by_text('分享报告频道', exact=True).click()
                await page.get_by_label('DSH 连接器身份').fill('synthetic-subject')
                await page.get_by_role('button', name='生成邀请链接').click()
                share = page.get_by_label('报告频道邀请链接')
                await share.wait_for()
                joined = (await connector.call_tool('join_report_channel', {'share_link': await share.input_value()})).data
                channel = joined['channel']
                if tls_cert:
                    assert joined['editorUrl'] == page.url
                await page.get_by_label('频道消息', exact=True).fill('Please edit the synthetic selection')
                await page.get_by_role('button', name='发送到频道').click()
                await page.get_by_text('编辑者 · Please edit the synthetic selection', exact=True).wait_for()
                messages = (await connector.call_tool('read_report_channel', {'channel': channel})).data
                assert messages[0]['text'] == 'Please edit the synthetic selection'
                await connector.call_tool('post_report_channel_message', {'channel': channel,
                    'message_id': 'synthetic-reply', 'text': 'Preparing a candidate'})
                await page.get_by_text('连接器 · Preparing a candidate', exact=True).wait_for()
                delegated = (await connector.call_tool('delegate_report_word_task', {'channel': channel,
                    'request_id': 'channel-word', 'instruction': chain.payload['instruction']})).data
                review_url = delegated['reviewUrl']
                assert review_url == f"{joined['editorUrl']}#word-task={delegated['taskId']}"
                await page.get_by_role('button', name='查看 Word 任务进度和候选').click(timeout=30_000)
                panel = page.get_by_role('region', name='AI 编辑选区')
                await panel.get_by_text('Synthetic candidate', exact=False).first.wait_for(timeout=60_000)
                accept = panel.locator('[data-ai=accept]')
                await accept.scroll_into_view_if_needed()
                await page.wait_for_timeout(1200)
                await accept.click()
                await page.get_by_text('Synthetic candidate', exact=True).first.wait_for()
                await page.locator('[data-action=save]').click()
                link = page.get_by_role('link', name='打开新修订继续编辑')
                open_url = await link.get_attribute('href')
                await link.click()
                await page.get_by_text('Synthetic candidate', exact=True).first.wait_for()
                native = chain.context['context']
                await verify_saved_revision(chain, open_url.replace(origin, 'http://test'), native['documentId'],
                    NativeScope.model_validate(native['scope']), candidate='Synthetic candidate')
                await page.wait_for_timeout(1200)
            finally:
                await context.close()
                await browser.close()
    finally:
        server.should_exit = True
        await serving


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


async def restart_projection(chain):
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
    from smart_reporting.report_editor.service import token_hash

    # New service/projection maps; persisted task and receipt remain sole authority.
    ai = NativeAIService(chain.editor, planner=object(), enabled=True,
        word_task_dispatcher=chain.ai.word_task_dispatcher)
    raw_session = chain.client.cookies.get(NATIVE_SESSION_COOKIE)
    session = await chain.editor.grants.lookup_session(raw_session)
    payload = chain.payload
    try:
        result = await ai.start_edit(session, instruction=payload['instruction'],
            expected_sha256=payload['expectedSha256'], operations=payload['operations'],
            selection=payload['selection'], client_request_id=payload['clientRequestId'],
            server_session_reference=token_hash(raw_session))
        return await ai.wait_edit_status(session, result['editId'], wait_ms=20000)
    finally:
        await ai.aclose()


async def test_completed_receipt_restores_new_service_without_provider_rerun(chain):
    first = await started(chain)
    done = await settled(chain, first['editId'])
    assert done['status'] == 'succeeded', done
    restored = await restart_projection(chain)
    assert restored['editId'] == first['editId']
    assert restored['status'] == 'succeeded' and restored['accepted'] is False
    assert chain.transport.calls == 1


async def test_failed_model_attempt_closes_and_cannot_rerun_same_request_after_restart(chain):
    from smart_reporting.task_execution.models import AttemptOutcome, AttemptState

    chain.transport.mode = 'mismatch'
    first = await started(chain)
    done = await settled(chain, first['editId'])
    assert done['status'] == 'failed', done
    task = await chain.repository.get_task_snapshot(first['editId'])
    assert task.state is TaskState.SUSPENDED
    attempt = await chain.repository.get_attempt(task.current_internal_run_id)
    assert attempt.state is AttemptState.CLOSED and attempt.outcome is AttemptOutcome.ERROR
    chain.transport.mode = 'valid'
    restored = await restart_projection(chain)
    assert restored['status'] == 'failed'
    assert chain.transport.calls == 1


@pytest.mark.parametrize('fault', ['commit_ack', 'request_finish'])
async def test_persisted_receipt_after_uncertain_ack_or_finish_failure_recovers_without_provider(chain, monkeypatch, fault):
    repository = chain.repository
    method = 'commit_native_word_candidate' if fault == 'commit_ack' else 'request_finish'
    original = getattr(repository, method)
    injected = False
    async def fail_once(*args, **kwargs):
        nonlocal injected
        if not injected:
            injected = True
            if fault == 'commit_ack':
                await original(*args, **kwargs)
            raise RuntimeError('synthetic post-receipt failure')
        return await original(*args, **kwargs)
    monkeypatch.setattr(repository, method, fail_once)
    first = await started(chain)
    done = await settled(chain, first['editId'])
    assert done['status'] == 'failed' and injected
    restored = await restart_projection(chain)
    assert restored['status'] == 'succeeded', restored
    assert chain.transport.calls == 1
    task = await repository.get_task_snapshot(first['editId'])
    attempt = await repository.get_attempt(task.current_internal_run_id)
    assert task.state is TaskState.COMPLETED
    assert attempt.agno_status == 'receipt-recovered'


async def test_cancel_request_during_prepare_cancels_only_its_late_task(chain, monkeypatch):
    dispatcher = chain.ai.word_task_dispatcher
    original = dispatcher.prepare
    waiting, release = asyncio.Event(), asyncio.Event()
    async def held_prepare(**kwargs):
        result = await original(**kwargs)
        waiting.set()
        await release.wait()
        return result
    monkeypatch.setattr(dispatcher, 'prepare', held_prepare)
    start = asyncio.create_task(started(chain))
    try:
        await asyncio.wait_for(waiting.wait(), 20)
        response = await chain.client.post(chain.base + '/ai/cancel-request', headers=chain.headers,
            json={'clientRequestId': chain.payload['clientRequestId']})
        assert response.status_code == 200
        release.set()
        result = await start
        assert result['status'] == 'cancelled' and chain.transport.calls == 0
    finally:
        release.set()
        await asyncio.gather(start, return_exceptions=True)


async def test_parallel_http_exact_retries_share_task_and_never_cancel_it(chain, monkeypatch):
    dispatcher = chain.ai.word_task_dispatcher
    original = dispatcher.prepare
    ready, release = asyncio.Event(), asyncio.Event()
    calls = 0
    cancelled = []
    original_cancel = dispatcher.cancel
    async def held_prepare(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            ready.set()
        await release.wait()
        return await original(**kwargs)
    async def record_cancel(ref):
        cancelled.append(ref.scope.external_run_id)
        return await original_cancel(ref)
    monkeypatch.setattr(dispatcher, 'prepare', held_prepare)
    monkeypatch.setattr(dispatcher, 'cancel', record_cancel)
    first, second = asyncio.create_task(started(chain)), asyncio.create_task(started(chain))
    try:
        await asyncio.wait_for(ready.wait(), 20)
        release.set()
        a, b = await asyncio.gather(first, second)
        assert a['editId'] == b['editId']
        done = await settled(chain, a['editId'])
        assert done['status'] == 'succeeded', done
        assert cancelled == [] and chain.transport.calls == 1
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)


async def test_parallel_changed_request_returns409_without_cancelling_original_task(chain, monkeypatch):
    dispatcher = chain.ai.word_task_dispatcher
    original = dispatcher.prepare
    prepared, release = asyncio.Event(), asyncio.Event()
    calls = 0
    cancelled = []
    original_cancel = dispatcher.cancel
    async def held_prepare(**kwargs):
        nonlocal calls
        calls += 1
        result = await original(**kwargs)
        if calls == 1:
            prepared.set()
            await release.wait()
        return result
    async def record_cancel(ref):
        cancelled.append(ref.scope.external_run_id)
        return await original_cancel(ref)
    monkeypatch.setattr(dispatcher, 'prepare', held_prepare)
    monkeypatch.setattr(dispatcher, 'cancel', record_cancel)
    first = asyncio.create_task(started(chain))
    try:
        await asyncio.wait_for(prepared.wait(), 20)
        changed = await chain.client.post(chain.base + '/ai/start', headers=chain.headers,
            json={**chain.payload, 'instruction': 'Changed content during prepare'})
        assert changed.status_code == 409, changed.text
        release.set()
        result = await first
        done = await settled(chain, result['editId'])
        assert done['status'] == 'succeeded', done
        assert cancelled == [] and chain.transport.calls == 1
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)

@pytest.mark.parametrize("mode", ["valid", "swallow_cancel"])
async def test_word_service_shutdown_allows_same_attempt_recovery(chain, mode):
    from smart_reporting.task_execution.models import TaskState

    chain.transport.mode = mode
    chain.transport.release = asyncio.Event()
    first = await started(chain)
    await asyncio.wait_for(chain.transport.proposed.wait(), 10)

    await chain.ai.aclose()
    interrupted = await chain.repository.get_task_snapshot(first["editId"])
    assert interrupted.state is TaskState.ACTIVE
    assert interrupted.lease_owner is None

    chain.transport.release = None
    restored = await restart_projection(chain)
    assert restored["editId"] == first["editId"]
    assert restored["status"] == "succeeded", restored
    completed = await chain.repository.get_task_snapshot(first["editId"])
    assert completed.state is TaskState.COMPLETED
    assert completed.current_internal_run_id == interrupted.current_internal_run_id
    attempt = await chain.repository.get_attempt(completed.current_internal_run_id)
    assert attempt.resume_count == 1
    assert chain.transport.calls == 2

async def test_reconnecting_word_service_waits_for_current_lease_holder(chain, monkeypatch):
    chain.transport.release = asyncio.Event()
    first = await started(chain)
    await asyncio.wait_for(chain.transport.proposed.wait(), 10)
    lease_observed = asyncio.Event()
    get_snapshot = chain.repository.get_task_snapshot

    async def observe_snapshot(task_id):
        task = await get_snapshot(task_id)
        if task is not None and task.lease_owner is not None:
            lease_observed.set()
        return task

    monkeypatch.setattr(chain.repository, "get_task_snapshot", observe_snapshot)
    observer = asyncio.create_task(restart_projection(chain))
    try:
        await asyncio.wait_for(lease_observed.wait(), 20)
        chain.transport.release.set()
        original = await settled(chain, first["editId"])
        restored = await asyncio.wait_for(observer, 20)
        assert original["status"] == "succeeded", original
        assert restored["editId"] == first["editId"]
        assert restored["status"] == "succeeded", restored
        assert restored["proposal"] == original["proposal"]
        assert chain.transport.calls == 1
    finally:
        chain.transport.release.set()
        if not observer.done():
            observer.cancel()
        await asyncio.gather(observer, return_exceptions=True)
