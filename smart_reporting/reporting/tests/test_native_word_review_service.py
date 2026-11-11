"""审阅候选走真实 DOCX preview/accept；来源身份、选区与未保存草稿不能扩大。"""
from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.report_editor.native_ai import NativeAIService
from smart_reporting.report_editor.native_word_ai import NativeWordAIProposal, NativeWordAITools
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_docx_comment_reply import modern_source
from smart_reporting.reporting.tests.test_docx_comment_text_host import source as comment_source
from smart_reporting.reporting.tests.test_docx_text_revision_host import source as revision_source
from smart_reporting.reporting.tests.test_native_ai import sample as sample


async def review_document(sample, family):
    editor, original_context, _, _, _ = sample
    source = revision_source() if family == 'revision' else modern_source() if family == 'resolve' else comment_source()
    path = 'native/review-write.docx'
    await editor.workspace.awrite_bytes(bind_native_workspace(editor.workspace, original_context.scope), path, source)
    context = original_context.model_copy(update={'source_file': ArtifactFile(
        path=path, size=len(source), sha256=hashlib.sha256(source).hexdigest(),
        mediaType=original_context.source_file.media_type)})
    editor.repository.get_revision.return_value = SimpleNamespace(status='saved', context=context)
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    _, session = await editor.grants.exchange(raw)
    model = inspect_docx(source)
    if family == 'revision':
        block = next(block for block in model['blocks'] if block['reviewTargets'])
        target = block['reviewTargets'][0]
        selection = {'blockId': target['blockId'], 'revisionId': target['revisionId']}
        operation = {'kind': 'resolveTextRevision', **selection, 'action': 'accept'}
    else:
        key = 'commentReplies' if family == 'reply' else 'commentThreads'
        target = next(target for target in model[key]['targets'] if target['parentId'] is None)
        selection = {key: target[key] for key in ('sourceId', 'targetId')}
        operation = ({'kind': 'replyComment', **selection, 'text': 'AI建议：请核实收入42'}
            if family == 'reply' else {'kind': 'resolveComment', **selection, 'done': False})
    return editor, context, session, model, source, selection, operation


class ReviewPlanner:
    def __init__(self, operation):
        self.operation = operation
        self.selected = None

    async def plan_word(self, prompt, *, selected, **kwargs):
        self.selected = selected
        tools = NativeWordAITools(selected)
        review_ids = [item['reviewId'] for item in selected]
        offset = 0
        while True:
            page = tools.read_review_targets(review_ids, offset=offset)
            offset = page['nextOffset']
            if offset is None:
                break
        tools.propose_operations('审阅候选', [self.operation])
        return NativeWordAIProposal(summary='审阅候选', operations=[
            {'kind': op['kind'], 'arguments': {key: value for key, value in op.items() if key != 'kind'}}
            for op in tools.operations])


@pytest.mark.anyio
@pytest.mark.parametrize('family', ['reply', 'resolve', 'revision'])
async def test_review_candidate_actual_preview_accept_and_source_preservation(sample, family):
    editor, context, session, model, source, selection, operation = await review_document(sample, family)
    planner = ReviewPlanner(operation)
    service = NativeAIService(editor, planner=planner, enabled=True)
    try:
        started = await service.start_edit(session, instruction='按当前授权审阅项提出修改',
            expected_sha256=context.source_file.sha256, operations=[], selection=[selection])
        result = await service.wait_edit_status(session, started['editId'])
        assert result['status'] == 'succeeded', result
        candidate = result['proposal']['operations']
        assert candidate[0]['expectedObjectSha256']
        assert planner.selected[0]['selectionKind'] in {'comment', 'revision'}
        accepted = await service.accept_edit(session, started['editId'],
            expected_sha256=context.source_file.sha256, operations=[], snapshot_sha256=result['snapshotSha256'])
        output = patch_docx(source, accepted['operations'])
        reopened = inspect_docx(output)
        if family == 'reply':
            targets = reopened['commentReplies']['targets']
            assert len(targets) == len(model['commentReplies']['targets']) + 1
            assert targets[-1]['text'] == 'AI建议：请核实收入42'
            assert targets[-1]['parentId'] == model['commentReplies']['targets'][0]['originalCommentId']
            assert candidate[0]['clientId'] and candidate[0]['author'] and candidate[0]['date']
        elif family == 'resolve':
            assert reopened['commentThreads']['targets'][0]['done'] is False
            assert model['commentThreads']['targets'][0]['done'] is True
            assert [target['text'] for target in reopened['commentThreads']['targets']] == [
                target['text'] for target in model['commentThreads']['targets']]
        else:
            before = next(block for block in model['blocks'] if block['reviewTargets'])
            after = next(block for block in reopened['blocks'] if block['reviewTargets'])
            assert len(after['reviewTargets']) == len(before['reviewTargets']) - 1
            assert after['text'] == before['text']
            assert after['reviewTargets'][0]['type'] == 'deletion'
        assert await editor.read_file(context) == source
    finally:
        await service.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize('family', ['reply', 'resolve', 'revision'])
async def test_review_identity_forgery_never_produces_candidate(sample, family):
    editor, context, session, _, source, selection, operation = await review_document(sample, family)
    operation['expectedObjectSha256'] = '0' * 64
    service = NativeAIService(editor, planner=ReviewPlanner(operation), enabled=True)
    try:
        started = await service.start_edit(session, instruction='生成候选',
            expected_sha256=context.source_file.sha256, operations=[], selection=[selection])
        result = await service.wait_edit_status(session, started['editId'])
        assert result['status'] == 'failed', result
        assert 'proposal' not in result
        assert await editor.read_file(context) == source
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_review_rejects_unsaved_base_and_mixed_selection_before_planner(sample):
    editor, context, session, model, source, selection, operation = await review_document(sample, 'revision')
    planner = ReviewPlanner(operation)
    service = NativeAIService(editor, planner=planner, enabled=True)
    plain = next(block for block in model['blocks'] if block.get('editable'))
    try:
        with pytest.raises(ReportingError, match='保存'):
            await service.start_edit(session, instruction='审阅', expected_sha256=context.source_file.sha256,
                operations=[{'kind': 'replaceParagraph', 'blockId': plain['blockId'],
                    'expectedObjectSha256': plain['expectedObjectSha256'], 'text': '未保存草稿'}],
                selection=[selection])
        with pytest.raises(ReportingError):
            await service.start_edit(session, instruction='混合审阅', expected_sha256=context.source_file.sha256,
                operations=[], selection=[selection, {'blockId': plain['blockId']}])
        assert planner.selected is None
        assert await editor.read_file(context) == source
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_review_cancel_discards_late_planner_proposal(sample):
    editor, context, session, _, source, selection, operation = await review_document(sample, 'reply')
    entered = asyncio.Event()
    class LatePlanner(ReviewPlanner):
        async def plan_word(self, *args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return await super().plan_word(*args, **kwargs)
    service = NativeAIService(editor, planner=LatePlanner(operation), enabled=True)
    try:
        started = await service.start_edit(session, instruction='建议回复',
            expected_sha256=context.source_file.sha256, operations=[], selection=[selection])
        await asyncio.wait_for(entered.wait(), 30)
        result = await service.cancel_edit(session, started['editId'])
        assert result['status'] == 'cancelled' and 'proposal' not in result
        assert (await service.wait_edit_status(session, started['editId']))['status'] == 'cancelled'
        assert await editor.read_file(context) == source
    finally:
        await service.aclose()


@pytest.mark.anyio
async def test_production_agno_review_tool_registration_and_real_preview(sample):
    import json

    from agno.models.response import ModelResponse

    from smart_reporting.report_editor.native_ai import create_native_ai_service
    from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel

    editor, context, session, _, source, selection, operation = await review_document(sample, 'revision')
    review_id = 'revision:' + selection['blockId'] + ':' + selection['revisionId']
    def call(name, arguments, identity):
        return ModelResponse(tool_calls=[{'id': identity, 'type': 'function', 'function': {
            'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}])
    scripted = ScriptedModel(id='word-review-factory', responses=[
        call('read_review_targets', {'review_ids': [review_id]}, 'review-read'),
        call('propose_operations', {'summary': '接受选中插入修订', 'operations': [operation]}, 'review-propose'),
        ModelResponse(content=json.dumps({'summary': '接受选中插入修订', 'operations': [{
            'kind': operation['kind'], 'arguments': {key: value for key, value in operation.items() if key != 'kind'}}]})),
    ])
    service = create_native_ai_service(scripted, editor, enabled=True)
    try:
        started = await service.start_edit(session, instruction='接受选中的插入修订',
            expected_sha256=context.source_file.sha256, operations=[], selection=[selection])
        result = await service.wait_edit_status(session, started['editId'])
        assert result['status'] == 'succeeded', result
        assert result['proposal']['operations'][0]['expectedObjectSha256']
        history = service._jobs[started['editId']].event_log.history
        assert [(event['toolName'], event['toolCallId']) for event in history
                if event['kind'] == 'toolCompleted'] == [
            ('read_review_targets', 'review-read'), ('propose_operations', 'review-propose')]
        assert await editor.read_file(context) == source
        assert len(scripted.responses) == 3
    finally:
        await service.aclose()
