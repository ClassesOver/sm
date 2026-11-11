"""审阅读取走真实 DOCX 草稿与 Agno 事件，保留原件和选区边界。"""

import hashlib
import json
from types import SimpleNamespace

import pytest
from agno.models.response import ModelResponse

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.report_editor.native_word_read_ai import AgnoNativeWordReadPlanner
from smart_reporting.report_editor.native_word_read_tasks import NativeWordReadService
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.delivery.docx_native import inspect_docx
from smart_reporting.reporting.tests.test_docx_comment_reply import modern_source
from smart_reporting.reporting.tests.test_docx_comment_text_host import operation
from smart_reporting.reporting.tests.test_native_ai import sample as sample
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel


async def review_source(sample):
    editor, original_context, _, _, _ = sample
    source = modern_source()
    key = bind_native_workspace(editor.workspace, original_context.scope)
    await editor.workspace.awrite_bytes(key, 'native/review.docx', source)
    context = original_context.model_copy(update={'source_file': ArtifactFile(
        path='native/review.docx', size=len(source), sha256=hashlib.sha256(source).hexdigest(),
        mediaType=original_context.source_file.media_type)})
    editor.repository.get_revision.return_value = SimpleNamespace(status='saved', context=context)
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    _, session = await editor.grants.exchange(raw)
    return editor, context, session, inspect_docx(source), source


@pytest.mark.anyio
async def test_agno_comment_read_uses_actual_draft_and_streams_real_tool_ids(sample):
    editor, context, session, model, source = await review_source(sample)
    target = model['comments']['commentTargets'][0]
    base = [operation(target, '草稿批注：请核实收入42')]
    scripted = ScriptedModel(id='word-review-service', expected_tool_text='草稿批注：请核实收入42', responses=[
        ModelResponse(tool_calls=[{'id': 'comments-actual', 'type': 'function', 'function': {
            'name': 'read_comments', 'arguments': '{}'}}]),
        ModelResponse(content=json.dumps({'answer': '请核实收入42', 'citations': [],
                                          'reviewCitations': []})),
    ])
    service = NativeWordReadService(editor, planner=AgnoNativeWordReadPlanner(scripted), enabled=True)
    try:
        started = await service.start(session, client_request_id='review-draft', action='ask',
            instruction='总结批注意见', expected_sha256=context.source_file.sha256,
            operations=base, selection=[])
        task = await service.status(session, started['taskId'])
        assert task['status'] == 'completed', task
        result = task['result']
        assert result['readingVersion'] == 'draft'
        assert result['reviewCoverage']['comments']['readComplete'] is True
        assert result['reviewCoverage']['comments']['totalItems'] == 2
        history = next(iter(service._jobs.values())).event_log.history
        assert [(event['toolName'], event['toolCallId']) for event in history
                if event['kind'] == 'toolCompleted'] == [('read_comments', 'comments-actual')]
        assert 'operations' not in result and 'proposal' not in result
        assert await editor.read_file(context) == source
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_selected_review_cannot_expose_unanchored_comment_threads(sample):
    editor, context, session, model, source = await review_source(sample)

    async def planner(*, reader, **kwargs):
        comments = reader.read_comments()
        assert 'Original note' not in str(comments) and 'Existing reply' not in str(comments)
        return reader.result('当前选区无法确定批注归属。', [])

    service = NativeWordReadService(editor, planner=planner, enabled=True)
    try:
        started = await service.start(session, client_request_id='selected-review', action='ask',
            instruction='读取选区批注', expected_sha256=context.source_file.sha256, operations=[],
            selection=[{'blockId': model['blocks'][0]['blockId']}])
        task = await service.status(session, started['taskId'])
        assert task['status'] == 'completed', task
        assert task['result']['limitations']
        assert task['result']['reviewCoverage']['comments']['totalItems'] == 0
        assert await editor.read_file(context) == source
    finally:
        await service.aclose()
