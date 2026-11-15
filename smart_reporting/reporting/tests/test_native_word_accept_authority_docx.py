"""Accept observes authority changes across real DOCX/receipt waits; no provider."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from docx import Document

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
from smart_reporting.report_editor.native_models import NativeScope
from smart_reporting.report_editor.service import token_hash
from smart_reporting.reporting.tests.test_native_word_task_chain_docx import (
    chain as chain,
)
from smart_reporting.reporting.tests.test_native_word_task_chain_docx import (
    settled,
    started,
)
from smart_reporting.task_execution.tests.test_native_word_repository import (
    word_repository as word_repository,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.mark.parametrize('wait_point', ['preview', 'receipt'])
@pytest.mark.parametrize('change', ['natural_expiry', 'revoked', 'source_changed'])
async def test_accept_reobserves_authority_after_wait(chain, monkeypatch, wait_point, change):
    first = await started(chain)
    done = await settled(chain, first['editId'])
    assert done['status'] == 'succeeded', done
    job = chain.ai._jobs[first['editId']]
    assert job.accepted is False
    scope = NativeScope.model_validate(chain.context['context']['scope'])
    document_id = chain.context['context']['documentId']
    revision = await chain.editor.repository.get_revision(document_id, 1, scope=scope)
    assert revision is not None
    key = bind_native_workspace(chain.editor.workspace, scope)
    source_path = revision.context.source_file.path
    assert await chain.editor.read_file(revision.context) == chain.original
    entered, release = asyncio.Event(), asyncio.Event()
    target = chain.editor if wait_point == 'preview' else chain.repository
    method = 'preview' if wait_point == 'preview' else 'get_completed_native_word_candidate'
    original_method = getattr(target, method)

    async def waiting(*args, **kwargs):
        value = await original_method(*args, **kwargs)
        entered.set()
        await release.wait()
        return value

    monkeypatch.setattr(target, method, waiting)
    accept = asyncio.create_task(chain.client.post(
        chain.base + '/ai/' + first['editId'] + '/accept', headers=chain.headers,
        json={'expectedSha256': chain.payload['expectedSha256'],
              'snapshotSha256': done['snapshotSha256'], 'operations': []}))
    expected_bytes = chain.original
    try:
        await asyncio.wait_for(entered.wait(), timeout=30)
        assert not accept.done(), 'accept must actually be waiting after real work'
        session_hash = token_hash(chain.client.cookies.get(NATIVE_SESSION_COOKIE))
        sessions = chain.editor.grants.repository.sessions
        if change == 'natural_expiry':
            expiry = datetime.now(UTC) + timedelta(milliseconds=150)
            sessions[session_hash] = replace(sessions[session_hash], expires_at=expiry)
            # Real wall time, no mocked clock or already-expired fixture session.
            while datetime.now(UTC) <= expiry:
                await asyncio.sleep(.02)
        elif change == 'revoked':
            del sessions[session_hash]
        else:
            altered = Document(BytesIO(chain.original))
            altered.paragraphs[0].text = 'Synthetic external source change'
            stream = BytesIO()
            altered.save(stream)
            expected_bytes = stream.getvalue()
            await chain.editor.workspace.awrite_bytes(key, source_path, expected_bytes, overwrite=True)
        release.set()
        response = await asyncio.wait_for(accept, timeout=30)
        assert response.status_code in {400, 401, 403, 409, 410}, response.text
        expected_code = {'natural_expiry': 'report_editor_session_expired',
                         'revoked': 'report_editor_session_invalid',
                         'source_changed': 'native_source_changed'}[change]
        assert expected_code in response.text, response.text
        assert job.accepted is False
        assert await chain.editor.repository.get_revision(document_id, 2, scope=scope) is None
        actual_bytes, _ = await chain.editor.workspace.afile_bytes(key, source_path)
        assert actual_bytes == expected_bytes, 'accept must not write the source'
    finally:
        release.set()
        if not accept.done():
            accept.cancel()
        await asyncio.gather(accept, return_exceptions=True)
        if change == 'source_changed':
            await chain.editor.workspace.awrite_bytes(key, source_path, chain.original, overwrite=True)
