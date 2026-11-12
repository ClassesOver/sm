"""Word AI 审阅候选：显式身份授权、原生引擎与只读工具前置证据。"""
import hashlib
import json
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from agno.models.response import ModelResponse
from lxml import etree

from smart_reporting.report_editor.native_word_ai import (
    AgnoNativeWordProposalPlanner,
    NativeWordAIProposal,
    NativeWordAITools,
    selected_word_objects,
    word_candidate,
)
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_docx_comment_reply import modern_source
from smart_reporting.reporting.tests.test_docx_comment_text_host import (
    source as root_comment_source,
)
from smart_reporting.reporting.tests.test_docx_text_revision_host import source as revision_source
from smart_reporting.reporting.tests.test_native_ai import sample as sample
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel


@pytest.fixture
def comment_model():
    content = modern_source()
    return content, inspect_docx(content)


def comment_selection(model):
    target = model['commentReplies']['targets'][0]
    return {key: target[key] for key in ('sourceId', 'targetId')}


def revision_selection(model):
    target = model['blocks'][1]['reviewTargets'][0]
    return {key: target[key] for key in ('blockId', 'revisionId')}


def test_review_proposal_receipt_provides_exact_final_schema(comment_model):
    _, model = comment_model
    selection = comment_selection(model)
    tools = NativeWordAITools(selected_word_objects(model, [], [selection]))
    tools.read_review_targets([tools.selected[0]['reviewId']])
    receipt = tools.propose_operations('回复候选', [{'kind': 'replyComment', **selection, 'text': '核实收入42'}])
    final = NativeWordAIProposal.model_validate(receipt['proposal'])
    assert final.engine_operations() == tools.operations
    assert set(receipt['proposal']['operations'][0]) == {'kind', 'arguments'}
    assert receipt['needsPreview'] is True and receipt['needsAcceptance'] is True


def test_root_without_replies_keeps_existing_reply_writer_compatible():
    content = root_comment_source()
    model = inspect_docx(content)
    selection = comment_selection(model)
    selected = selected_word_objects(model, [], [selection])
    assert selected[0]['replies'] == []
    candidate = word_candidate([{'kind': 'replyComment', **selection, 'text': '首条回复'}], selected)
    reopened = inspect_docx(patch_docx(content, candidate))
    assert [reply['text'] for reply in selected_word_objects(reopened, [], [comment_selection(reopened)])[0]['replies']] == ['首条回复']


def test_explicit_root_selection_freezes_only_target_and_trusted_reply_metadata(comment_model):
    _, model = comment_model
    selected = selected_word_objects(model, [], [comment_selection(model)])
    assert len(selected) == 1
    target = selected[0]
    assert target['selectionKind'] == 'comment'
    assert target['allowedOperations'] == ['replyComment', 'resolveComment']
    assert target['text'] == 'Original note'
    assert target['done'] is True
    assert target['parentId'] is None
    assert target['replyMetadata']['author'] == 'AI Assistant'
    assert target['replyMetadata']['date'].endswith('Z')
    assert [reply['text'] for reply in target['replies']] == ['Existing reply']
    assert target['replies'][0]['parentId'] == '1'
    assert target['replies'][0]['author'] == 'Bob'
    assert target['replies'][0]['done'] is True
    assert 'Anchor text' not in json.dumps(selected)
    assert target['reviewId'].startswith('comment:')
    with pytest.raises(ReportingError):
        selected_word_objects(model, [], [{key: model['commentReplies']['targets'][1][key]
                                          for key in ('sourceId', 'targetId')}])
    for selection, base in [([comment_selection(model), {'blockId': model['blocks'][0]['blockId']}], []),
                            ([comment_selection(model)], [{'kind': 'anything'}])]:
        with pytest.raises(ReportingError):
            selected_word_objects(model, base, selection)


def test_authorized_thread_context_excludes_other_roots_and_cannot_grant_reply_authority(comment_model):
    _, model = comment_model
    other = deepcopy(model['commentThreads']['targets'][0])
    other.update(targetId='private-root', originalCommentId='private', text='其他线程机密')
    child = deepcopy(model['commentThreads']['targets'][1])
    child.update(targetId='private-child', originalCommentId='private-reply', parentId='private',
                 text='其他线程回复')
    model['commentThreads']['targets'].extend([other, child])
    selected = selected_word_objects(model, [], [comment_selection(model)])
    assert '其他线程' not in json.dumps(selected, ensure_ascii=False)
    assert [item['text'] for item in selected[0]['replies']] == ['Existing reply']
    child_id = selected[0]['replies'][0]['targetId']
    with pytest.raises(ReportingError):
        word_candidate([{'kind': 'replyComment', 'sourceId': selected[0]['sourceId'],
                         'targetId': child_id, 'text': '不授予子批注权限'}], selected)


def test_reply_context_requires_complete_pagination_and_preserves_frozen_snapshot(comment_model):
    _, model = comment_model
    model['commentThreads']['targets'][1]['text'] = '历史回复' * 9000
    selected = selected_word_objects(model, [], [comment_selection(model)])
    model['commentThreads']['targets'][1]['text'] = '稍后变化'
    reader = NativeWordAITools(selected)
    identity = selected[0]['reviewId']
    operation = {'kind': 'replyComment', **comment_selection(model), 'text': '根据完整线程答复'}
    page = reader.read_review_targets([identity])
    assert page['nextOffset'] is not None
    with pytest.raises(ReportingError):
        reader.propose_operations('尚未完整读取回复', [operation])
    content = page['content']
    while page['nextOffset'] is not None:
        page = reader.read_review_targets([identity], page['nextOffset'])
        content += page['content']
    assert json.loads(content)[0]['replies'][0]['text'] == '历史回复' * 9000
    assert reader.propose_operations('完整线程答复', [operation])['needsAcceptance'] is True


def test_changed_thread_invalidates_frozen_reply_candidate_in_real_writer(comment_model):
    content, model = comment_model
    selection = comment_selection(model)
    candidate = word_candidate([{'kind': 'replyComment', **selection, 'text': '过期候选'}],
                               selected_word_objects(model, [], [selection]))
    concurrent = word_candidate([{'kind': 'replyComment', **selection, 'text': '最新问题'}],
                                selected_word_objects(model, [], [selection]))
    changed = patch_docx(content, concurrent)
    with pytest.raises(ValueError, match='docx_engine_failed'):
        patch_docx(changed, candidate)
    selected = selected_word_objects(inspect_docx(changed), [], [comment_selection(inspect_docx(changed))])
    assert [reply['text'] for reply in selected[0]['replies']] == ['Existing reply', '最新问题']
    fresh = word_candidate([{'kind': 'replyComment', **comment_selection(inspect_docx(changed)),
                            'text': '针对最新问题的答复'}], selected)
    output = patch_docx(changed, fresh)
    with ZipFile(BytesIO(output)) as package:
        root = etree.fromstring(package.read('word/comments.xml'))
        texts = root.xpath('.//w:comment//w:t/text()',
                           namespaces={'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'})
        assert texts == ['Original note', 'Existing reply', '最新问题', '针对最新问题的答复']


@pytest.mark.parametrize('fault', ['projection', 'text', 'parent'])
def test_unreadable_thread_never_silently_becomes_complete_context(comment_model, fault):
    _, model = comment_model
    if fault == 'projection':
        model['commentThreads']['readOnlyReason'] = 'unsupported'
    elif fault == 'text':
        model['commentThreads']['targets'][1]['text'] = None
    else:
        model['commentThreads']['targets'][1]['parentId'] = 'missing'
    with pytest.raises(ReportingError):
        selected_word_objects(model, [], [comment_selection(model)])


@pytest.mark.parametrize('kind,values', [('replyComment', {'text': 'AI回复'}),
                                        ('resolveComment', {'done': False})])
def test_comment_candidate_uses_real_engine_without_modifying_source(comment_model, kind, values):
    content, model = comment_model
    selection = comment_selection(model)
    selected = selected_word_objects(model, [], [selection])
    candidate = word_candidate([{'kind': kind, **selection, **values}], selected)
    assert candidate[0]['expectedObjectSha256'] == selected[0]['expectedObjectSha256']
    assert candidate[0]['expectedCommentsSha256'] == selected[0]['expectedCommentsSha256']
    if kind == 'replyComment':
        assert all(candidate[0][key] == selected[0]['replyMetadata'][key] for key in ('author', 'date', 'clientId'))
    proposal = NativeWordAIProposal(summary='审阅候选', operations=[{
        'kind': kind, 'arguments': {key: value for key, value in candidate[0].items() if key != 'kind'}}])
    assert proposal.engine_operations() == candidate
    changed = patch_docx(content, candidate)
    reopened = inspect_docx(changed)
    if kind == 'replyComment':
        assert reopened['commentReplies']['targets'][-1]['text'] == 'AI回复'
        assert reopened['commentReplies']['targets'][-1]['author'] == 'AI Assistant'
    else:
        assert reopened['commentThreads']['targets'][0]['done'] is False
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(changed)) as after:
        # 原文正文语义不受审阅操作改变。
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        assert etree.fromstring(before.read('word/document.xml')).xpath('.//w:body//w:t/text()', namespaces=ns) == etree.fromstring(after.read('word/document.xml')).xpath('.//w:body//w:t/text()', namespaces=ns)


def test_simple_revision_accept_and_reject_use_original_identity():
    content = revision_source()
    model = inspect_docx(content)
    selection = revision_selection(model)
    selected = selected_word_objects(model, [], [selection])
    assert selected[0]['selectionKind'] == 'revision'
    assert selected[0]['text'] == ' 新😀 '
    for action in ['accept', 'reject']:
        candidate = word_candidate([{'kind': 'resolveTextRevision', **selection, 'action': action}], selected)
        changed = inspect_docx(patch_docx(content, candidate))
        assert len(changed['blocks'][1]['reviewTargets']) == 1
    with pytest.raises(ReportingError):
        word_candidate([{'kind': 'resolveTextRevision', **selection, 'action': 'all'}], selected)
    invalid = deepcopy(model)
    invalid['blocks'][1]['revisionReadOnlyReason'] = 'docx_revision_projection_unsupported'
    with pytest.raises(ReportingError):
        selected_word_objects(invalid, [], [selection])


def test_review_candidates_reject_forgery_families_duplicates_and_implicit_authority(comment_model):
    _, model = comment_model
    selection = comment_selection(model)
    selected = selected_word_objects(model, [], [selection])
    reply = {'kind': 'replyComment', **selection, 'text': '回复'}
    resolve = {'kind': 'resolveComment', **selection, 'done': False}
    for operation in [{**reply, 'author': '伪造'}, {**reply, 'date': '2020-01-01T00:00:00Z'},
                      {**reply, 'clientId': '伪造'}, {**reply, 'expectedCommentsSha256': '0'*64},
                      {**reply, 'targetId': 'foreign'}, {**resolve, 'done': 'false'}]:
        with pytest.raises(ReportingError):
            word_candidate([operation], selected)
    for operations in [[reply, resolve], [reply, reply]]:
        with pytest.raises(ReportingError):
            word_candidate(operations, selected)
    # 普通段落选区不得隐式取得其评论权限。
    ordinary = [{'blockId': 'p', 'expectedObjectSha256': 'x', 'text': '正文',
                 'allowedOperations': ['replaceParagraph']}]
    with pytest.raises(ReportingError):
        word_candidate([reply], ordinary)


def test_review_tools_require_full_pages_and_reject_cross_call_family_or_duplicates(comment_model):
    _, model = comment_model
    model['commentReplies']['targets'][0]['text'] = '长' * 60000
    selected = selected_word_objects(model, [], [comment_selection(model)])
    reader = NativeWordAITools(selected)
    identity = selected[0]['reviewId']
    assert reader.get_document_context()['reviewTargets'][0]['reviewId'] == identity
    reply = {'kind': 'replyComment', **comment_selection(model), 'text': '回复'}
    with pytest.raises(ReportingError):
        reader.read_blocks([model['blocks'][0]['blockId']])
    assert reader.search_text('长')['matches'] == []
    tail = reader.read_review_targets([identity], offset=48000)
    assert tail['nextOffset'] is None
    with pytest.raises(ReportingError):
        reader.propose_operations('未读完', [reply])
    first = reader.read_review_targets([identity])
    reader.read_review_targets([identity], offset=first['nextOffset'])
    candidate = reader.propose_operations('回复', [reply])['operations']
    assert candidate[0]['author'] == 'AI Assistant'
    for operations in [[reply], [{'kind': 'resolveComment', **comment_selection(model), 'done': False}]]:
        with pytest.raises(ReportingError):
            reader.propose_operations('重复或混批', operations)


@pytest.mark.anyio
async def test_real_agno_review_reads_before_registering_final_exact_candidate(comment_model):
    _, inspected = comment_model
    selection = comment_selection(inspected)
    selected = selected_word_objects(inspected, [], [selection])
    operation = {'kind': 'resolveComment', **selection, 'done': False}
    expected = word_candidate([operation], selected)[0]
    def call(name, arguments, identity):
        return ModelResponse(tool_calls=[{'id': identity, 'type': 'function', 'function': {
            'name': name, 'arguments': json.dumps(arguments)}}])
    model = ScriptedModel(id='scripted', expected_tool_text='Existing reply', responses=[
        call('get_document_context', {}, 'context'),
        call('read_review_targets', {'review_ids': [selected[0]['reviewId']]}, 'read'),
        call('propose_operations', {'summary': '重新打开线程', 'operations': [operation]}, 'propose'),
        ModelResponse(content=json.dumps({'summary': '重新打开线程', 'operations': [{
            'kind': expected['kind'], 'arguments': {key: value for key, value in expected.items() if key != 'kind'}}]})),
    ])
    proposal = await AgnoNativeWordProposalPlanner(model).plan_word('重新打开授权线程', selected=selected,
        session_id='review-edit', user_id='user')
    assert proposal.engine_operations() == [expected]
    assert len(model.responses) == 4


@pytest.mark.anyio
async def test_thread_reply_service_preview_accept_and_changed_source_rejection(sample):
    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.report_editor.native_ai import NativeAIService

    editor, previous, _, _, _ = sample
    content = modern_source()
    identity = previous.source_file.model_copy(update={
        'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()})
    context = previous.model_copy(update={'source_file': identity})
    key = bind_native_workspace(editor.workspace, context.scope)
    await editor.workspace.awrite_bytes(key, identity.path, content, overwrite=True)
    editor.repository.get_revision.return_value = SimpleNamespace(status='saved', context=context)
    grant, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    _, session = await editor.grants.exchange(grant)
    selection = comment_selection(inspect_docx(content))

    class ThreadPlanner:
        async def plan_word(self, prompt, *, selected, **kwargs):
            tools = NativeWordAITools(selected)
            page = tools.read_review_targets([selected[0]['reviewId']])
            thread = json.loads(page['content'])[0]
            assert thread['replies'][-1]['text'] == 'Existing reply'
            result = tools.propose_operations('根据完整线程回复', [{
                'kind': 'replyComment', **selection,
                'text': '已阅读Bob的Existing reply，补充确认。'}])
            return NativeWordAIProposal.model_validate(result['proposal'])

    ai = NativeAIService(editor, planner=ThreadPlanner(), enabled=True)
    try:
        started = await ai.start_edit(session, instruction='根据最后回复答复',
            expected_sha256=identity.sha256, operations=[], selection=[selection])
        result = await ai.wait_edit_status(session, started['editId'])
        assert result['status'] == 'succeeded', result
        accepted = await ai.accept_edit(session, started['editId'], expected_sha256=identity.sha256,
            operations=[], snapshot_sha256=result['snapshotSha256'])
        saved = patch_docx(content, accepted['operations'])
        assert inspect_docx(saved)['commentReplies']['targets'][-1]['text'].endswith('补充确认。')
        assert await editor.read_file(context) == content
        # An out-of-band thread change cannot pass the immutable source check on acceptance.
        await editor.workspace.awrite_bytes(key, identity.path, saved, overwrite=True)
        with pytest.raises(ReportingError) as error:
            await ai.accept_edit(session, started['editId'], expected_sha256=identity.sha256,
                operations=[], snapshot_sha256=result['snapshotSha256'])
        assert error.value.code == 'native_source_changed'
    finally:
        await ai.aclose()


@pytest.mark.parametrize('missing', ['expectedCommentsSha256', 'expectedObjectSha256'])
def test_missing_trusted_comment_hash_never_becomes_an_ai_selection(comment_model, missing):
    _, model = comment_model
    broken = deepcopy(model)
    del broken['commentReplies']['targets'][0][missing]
    with pytest.raises(ReportingError):
        selected_word_objects(broken, [], [comment_selection(broken)])


def test_reply_schema_uses_native_utf16_text_limit(comment_model):
    _, model = comment_model
    selection = comment_selection(model)
    selected = selected_word_objects(model, [], [selection])
    assert word_candidate([{'kind': 'replyComment', **selection, 'text': 'x'*65536}], selected)
    with pytest.raises(ReportingError):
        word_candidate([{'kind': 'replyComment', **selection, 'text': 'x'*65537}], selected)
    with pytest.raises(ReportingError):
        word_candidate([{'kind': 'replyComment', **selection, 'text': '😀'*32769}], selected)
