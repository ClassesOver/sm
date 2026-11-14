"""公开进度必须随任务终态结束，取消不能留下永久等待的 SSE。"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from smart_reporting.report_editor.agent_event_streams import AgentEventLog, stream_agent_events
from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_ai_tasks import payload, service
from smart_reporting.reporting.tests.test_native_pdf_ai_tasks import pdf_sample as pdf_sample
from smart_reporting.reporting.tests.test_slides_native_ai import Editor as SlidesEditor
from smart_reporting.reporting.tests.test_workbook_native_ai import Editor as WorkbookEditor


@pytest.mark.anyio
async def test_terminal_is_final_even_with_concurrent_finish_and_late_callbacks():
    log = AgentEventLog()
    await log.emit('phase', label='读取')
    await asyncio.gather(log.finish('cancelled'), log.finish('cancelled'))
    await log.emit('content', delta='迟到内容')
    await log.emit('toolStarted', toolName='late_tool')
    assert [event['kind'] for event in log.history] == ['phase', 'terminal']
    assert log.sequence == 2


@pytest.mark.anyio
async def test_reconnect_after_consumed_terminal_ends_without_heartbeat():
    log = AgentEventLog()
    await log.finish('completed')
    result = await asyncio.wait_for(
        anext(stream_agent_events(log, log.sequence), None), timeout=0.1,
    )
    assert result is None


@pytest.mark.anyio
async def test_future_cursor_resets_and_replays_terminal():
    log = AgentEventLog()
    await log.emit('phase', label='读取')
    await log.finish('completed')

    async def collect():
        return [frame async for frame in stream_agent_events(log, 100)]

    frames = await asyncio.wait_for(collect(), timeout=0.1)
    assert len(frames) == 3
    assert '"kind":"reset"' in frames[0]
    assert '"sequence":0' in frames[0]
    assert '"kind":"terminal"' in frames[-1]


@pytest.mark.anyio
async def test_terminal_arriving_during_replay_is_not_lost():
    log = AgentEventLog()
    await log.emit('phase', label='读取')
    stream = stream_agent_events(log)
    assert '"kind":"phase"' in await anext(stream)
    await log.finish('completed')
    assert '"kind":"terminal"' in await anext(stream)
    assert await anext(stream, None) is None


@pytest.mark.anyio
async def test_pdf_cancel_before_start_publishes_terminal(pdf_sample):
    editor, _, session, _, _ = pdf_sample
    ai = service(editor, AsyncMock())
    try:
        cancelled = await ai.cancel_request(session, 'cancel-before-start')
        response = await ai.event_stream(session, cancelled['taskId'])
        frame = await asyncio.wait_for(anext(response.body_iterator), timeout=0.1)
        assert '"kind":"terminal"' in frame and '"status":"cancelled"' in frame
        assert await anext(response.body_iterator, None) is None
    finally:
        await ai.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize('format', ['xlsx', 'pptx'])
async def test_candidate_cancel_before_start_publishes_terminal(format):
    editor = WorkbookEditor() if format == 'xlsx' else SlidesEditor()
    cls = NativeWorkbookAIService if format == 'xlsx' else NativeSlidesAIService
    ai = cls(editor, planner=AsyncMock(), enabled=True)
    try:
        cancelled = await ai.cancel_request(None, 'cancel-before-start')
        response = await ai.event_stream(None, cancelled['editId'])
        frame = await asyncio.wait_for(anext(response.body_iterator), timeout=0.1)
        assert '"kind":"terminal"' in frame and '"status":"cancelled"' in frame
        assert await anext(response.body_iterator, None) is None
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_pdf_shutdown_prevents_new_work_and_finishes_unstarted_job(pdf_sample):
    editor, context, session, _, _ = pdf_sample
    planner = AsyncMock()
    ai = service(editor, planner)
    started = await ai.start(session, **payload(context))
    await ai.aclose()
    response = await ai.event_stream(session, started['taskId'])
    frame = await asyncio.wait_for(anext(response.body_iterator), timeout=0.1)
    assert '"status":"cancelled"' in frame
    with pytest.raises(ReportingError) as error:
        await ai.start(session, **payload(context, client_request_id='after-close'))
    assert error.value.code == 'native_ai_closed'
    planner.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize('format', ['xlsx', 'pptx'])
async def test_candidate_shutdown_prevents_new_work_and_finishes_unstarted_job(format):
    editor = WorkbookEditor() if format == 'xlsx' else SlidesEditor()
    cls = NativeWorkbookAIService if format == 'xlsx' else NativeSlidesAIService
    planner = AsyncMock()
    ai = cls(editor, planner=planner, enabled=True)
    selection = ([{'slideIndex': 0, 'elementId': 'title'}] if format == 'pptx' else {
        'sheetName': 'Sheet', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0,
    })
    kwargs = dict(instruction='修改', expected_sha256='a' * 64, operations=[], selection=selection)
    started = await ai.start_edit(None, client_request_id='before-close', **kwargs)
    await ai.aclose()
    response = await ai.event_stream(None, started['editId'])
    frame = await asyncio.wait_for(anext(response.body_iterator), timeout=0.1)
    assert '"status":"cancelled"' in frame
    with pytest.raises(ReportingError) as error:
        await ai.start_edit(None, client_request_id='after-close', **kwargs)
    assert error.value.code == 'native_ai_closed'
    planner.assert_not_awaited()
