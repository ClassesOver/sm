"""Legal generic Word selections unsupported by this stage fail as domain input."""
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.native_ai import NativeAIService
from smart_reporting.report_editor.native_ai_api import create_native_ai_router
from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
from smart_reporting.report_editor.native_word_ai import selected_word_objects
from smart_reporting.report_editor.native_word_task_dispatcher import WordTaskDispatcher
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
    token_hash,
)
from smart_reporting.reporting.tests.test_native_word_task_builder import inputs
from smart_reporting.task_execution.models import TaskExecutionScope


@pytest.mark.anyio
async def test_http_legal_table_selection_rejected_before_task_or_provider():
    data = inputs()
    data.block.update(type='table', cells=[], columnWidthEditable=True)
    selection = [{'blockId': 'p1'}]
    # The real generic validator permits this table; the trusted stage does not.
    assert selected_word_objects({'blocks': [data.block]}, [], selection)[0]['type'] == 'table'
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw_session = 'synthetic-table-session'
    await grants.repository.put_session(token_hash(raw_session), data.session)
    repository = AsyncMock(spec=['create_native_word_task'])
    transport = AsyncMock(spec=['run'])
    dispatcher = WordTaskDispatcher(repository, grants, data.editor,
        scope_factory=lambda context, task_id: TaskExecutionScope(task_id, 'user', 'thread', 'workspace', 'word'),
        secret='s' * 32, transport=transport, enabled=True)
    ai = NativeAIService(data.editor, planner=object(), enabled=True, word_task_dispatcher=dispatcher)
    app = FastAPI()
    app.include_router(create_native_ai_router(grants, editor=data.editor, ai=ai))
    try:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                               base_url='http://test') as client:
            client.cookies.set(NATIVE_SESSION_COOKIE, raw_session)
            response = await client.post('/reports/v1/native/doc/1/api/ai/start',
                headers={'Origin': 'http://test', 'X-CSRF-Token': grants.csrf_token(raw_session)},
                json={'clientRequestId': 'unsupported-table', 'instruction': 'Edit selected table',
                      'expectedSha256': 'a' * 64, 'operations': [], 'selection': selection})
        assert response.status_code == 422, response.text
        assert response.json()['detail']['code'] == 'native_ai_selection_invalid'
        assert 'native_word_builder_invalid' not in response.text
        repository.create_native_word_task.assert_not_called()
        transport.run.assert_not_called()
        assert ai._jobs == {}
    finally:
        await ai.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize('kind', ['unknown_value_error', 'authorization_error'])
async def test_prepare_does_not_convert_unknown_or_authorization_errors(kind):
    from smart_reporting.reporting.models import ReportingError

    data = inputs()
    error = (ValueError('unexpected implementation defect') if kind == 'unknown_value_error'
             else ReportingError('native_permission_denied', 'Synthetic authorization refusal'))
    repository = AsyncMock(spec=['create_native_word_task'])
    transport = AsyncMock(spec=['run'])
    dispatcher = WordTaskDispatcher(repository, data.grants, data.editor,
        scope_factory=lambda context, task_id: TaskExecutionScope(task_id, 'user', 'thread', 'workspace', 'word'),
        secret='s' * 32, transport=transport, enabled=True)
    dispatcher.builder.build = AsyncMock(side_effect=error)
    with pytest.raises(type(error)) as caught:
        await dispatcher.prepare(context=data.context, session_reference='c' * 64,
            instruction='Edit', expected_sha256='a' * 64, operations=[],
            selection=[{'blockId': 'p1'}], request_id='known-boundary-only')
    assert caught.value is error
    repository.create_native_word_task.assert_not_called()
    transport.run.assert_not_called()
