"""Word 阅读使用真实草稿，只读授权内容且不生成编辑候选。"""

import asyncio
from copy import deepcopy

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_ai import replacement
from smart_reporting.reporting.tests.test_native_ai import sample as sample


async def reading_planner(*, reader, action, **kwargs):
    identities = [item['blockId'] for item in reader.get_document_context()['blocks']]
    read = reader.read_blocks(identities)
    assert read['nextOffset'] is None
    return reader.result(read['content'], identities, action=action)


@pytest.mark.anyio
async def test_word_summary_reads_real_unsaved_draft_and_never_writes_source(sample):
    from smart_reporting.report_editor.native_word_read_tasks import NativeWordReadService

    editor, context, session, model, source = sample
    base = [replacement(model['blocks'][0], '人工草稿：收入42，成本17。')]
    frozen = deepcopy(base)
    service = NativeWordReadService(editor, planner=reading_planner, enabled=True)
    try:
        started = await service.start(session, client_request_id='summary', action='summarize',
            instruction='', expected_sha256=context.source_file.sha256, operations=base, selection=[])
        result = await service.status(session, started['taskId'])
        assert result['status'] == 'completed', result
        assert '人工草稿：收入42，成本17。' in result['result']['answer']
        assert result['result']['readingVersion'] == 'draft'
        assert result['result']['coverage']['scopeReadComplete'] is True
        assert 'operations' not in result['result'] and 'proposal' not in result['result']
        assert base == frozen and await editor.read_file(context) == source
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_word_selection_reads_actual_replacement_without_private_blocks(sample):
    from smart_reporting.report_editor.native_word_read_tasks import NativeWordReadService

    editor, context, session, model, _ = sample
    service = NativeWordReadService(editor, planner=reading_planner, enabled=True)
    try:
        started = await service.start(session, client_request_id='selection', action='ask',
            instruction='收入多少', expected_sha256=context.source_file.sha256,
            operations=[replacement(model['blocks'][0], '收入42')],
            selection=[{'blockId': model['blocks'][0]['blockId']}])
        result = await service.status(session, started['taskId'])
        assert result['status'] == 'completed', result
        assert '收入42' in result['result']['answer']
        assert '机密' not in str(result['result']) and '表格原文' not in str(result['result'])
        assert result['result']['coverage']['scope'] == 'selection'
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_word_read_is_available_without_editing_enabled(sample):
    from smart_reporting.report_editor.native_word_read_tasks import NativeWordReadService

    editor, context, session, _, source = sample
    editor.docx_enabled = False
    service = NativeWordReadService(editor, planner=reading_planner, enabled=True)
    try:
        started = await service.start(session, client_request_id='readonly', action='summarize',
            instruction='', expected_sha256=context.source_file.sha256, operations=[], selection=[])
        result = await service.status(session, started['taskId'])
        assert result['status'] == 'completed', result
        assert result['result']['readingVersion'] == 'source'
        assert await editor.read_file(context) == source
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_word_cancel_request_cannot_be_revived_and_request_identity_binds_snapshot(sample):
    from smart_reporting.report_editor.native_word_read_tasks import NativeWordReadService

    editor, context, session, _, _ = sample
    calls = []

    async def planner(**kwargs):
        calls.append(True)
        return await reading_planner(**kwargs)

    service = NativeWordReadService(editor, planner=planner, enabled=True)
    try:
        cancelled = await service.cancel_request(session, 'cancel-first')
        started = await service.start(session, client_request_id='cancel-first', action='summarize',
            instruction='', expected_sha256=context.source_file.sha256, operations=[], selection=[])
        assert started['taskId'] == cancelled['taskId'] and started['status'] == 'cancelled'
        assert calls == []
        started = await service.start(session, client_request_id='snapshot', action='summarize',
            instruction='', expected_sha256=context.source_file.sha256, operations=[], selection=[])
        await service.status(session, started['taskId'])
        with pytest.raises(ReportingError, match='已变化'):
            await service.start(session, client_request_id='snapshot', action='keyPoints',
                instruction='', expected_sha256=context.source_file.sha256, operations=[], selection=[])
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_cancelled_word_planner_cannot_publish_late_answer(sample):
    from smart_reporting.report_editor.native_word_read_tasks import NativeWordReadService

    editor, context, session, _, _ = sample
    entered = asyncio.Event()

    async def planner(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return {'answer': '迟到答案'}

    service = NativeWordReadService(editor, planner=planner, enabled=True)
    try:
        started = await service.start(session, client_request_id='late', action='summarize',
            instruction='', expected_sha256=context.source_file.sha256, operations=[], selection=[])
        await asyncio.wait_for(entered.wait(), 10)
        cancelled = await service.cancel_request(session, 'late')
        assert cancelled['status'] == 'cancelled' and 'result' not in cancelled
        result = await service.status(session, started['taskId'])
        assert result['status'] == 'cancelled' and 'result' not in result
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_word_read_real_agno_loop_streams_tool_events_and_no_edit_proposal(sample):
    import json

    from agno.models.response import ModelResponse

    from smart_reporting.report_editor.native_word_read_ai import AgnoNativeWordReadPlanner
    from smart_reporting.report_editor.native_word_read_tasks import NativeWordReadService
    from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel

    editor, context, session, model, source = sample
    block_id = model['blocks'][0]['blockId']

    def call(name, arguments, identity):
        return ModelResponse(tool_calls=[{'id': identity, 'type': 'function', 'function': {
            'name': name, 'arguments': json.dumps(arguments),
        }}])

    scripted = ScriptedModel(id='word-read-service', responses=[
        call('get_document_context', {}, 'context'),
        call('read_blocks', {'block_ids': [block_id]}, 'read'),
        ModelResponse(content=json.dumps({'answer': '第一段原文', 'citations': [block_id]})),
    ])
    service = NativeWordReadService(editor, planner=AgnoNativeWordReadPlanner(scripted), enabled=True)
    try:
        started = await service.start(session, client_request_id='real-agno', action='ask',
            instruction='所选段落说了什么', expected_sha256=context.source_file.sha256, operations=[],
            selection=[{'blockId': block_id}])
        result = await service.status(session, started['taskId'])
        assert result['status'] == 'completed', result
        assert result['result']['citations'] == [{'blockId': block_id, 'blockNumber': 1}]
        assert '机密' not in str(scripted.seen) and 'operations' not in result['result']
        events = next(iter(service._jobs.values())).event_log.history
        assert [(event['toolName'], event['toolCallId']) for event in events if event['kind'] == 'toolCompleted'] == [
            ('get_document_context', 'context'), ('read_blocks', 'read'),
        ]
        assert events[-1]['kind'] == 'terminal' and events[-1]['status'] == 'completed'
        assert await editor.read_file(context) == source
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_word_full_draft_summary_reads_insertions_but_stale_selection_is_not_expanded(sample):
    from smart_reporting.report_editor.native_word_read_tasks import NativeWordReadService

    editor, context, session, model, source = sample
    block = model['blocks'][0]
    base = [{'kind': 'insertParagraph', 'blockId': block['blockId'],
             'expectedObjectSha256': block['expectedObjectSha256'], 'position': 'before', 'text': '草稿新增段落'}]
    service = NativeWordReadService(editor, planner=reading_planner, enabled=True)
    try:
        full = await service.start(session, client_request_id='structure-full', action='summarize',
            instruction='', expected_sha256=context.source_file.sha256, operations=base, selection=[])
        result = await service.status(session, full['taskId'])
        assert result['status'] == 'completed', result
        assert '草稿新增段落' in result['result']['answer']
        selected = await service.start(session, client_request_id='structure-selection', action='ask',
            instruction='读取旧选区', expected_sha256=context.source_file.sha256, operations=base,
            selection=[{'blockId': block['blockId']}])
        failed = await service.status(session, selected['taskId'])
        assert failed['status'] == 'failed' and 'result' not in failed
        assert failed['error']['code'] == 'native_ai_selection_invalid'
        assert await editor.read_file(context) == source
    finally:
        await service.aclose()
