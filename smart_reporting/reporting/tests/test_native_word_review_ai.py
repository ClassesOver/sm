"""Word AI 审阅候选：显式身份授权、原生引擎与只读工具前置证据。"""
import json
from copy import deepcopy
from io import BytesIO
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
from smart_reporting.reporting.tests.test_docx_text_revision_host import source as revision_source
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
    assert 'Existing reply' not in json.dumps(selected)
    assert 'Anchor text' not in json.dumps(selected)
    assert target['reviewId'].startswith('comment:')
    with pytest.raises(ReportingError):
        selected_word_objects(model, [], [{key: model['commentReplies']['targets'][1][key]
                                          for key in ('sourceId', 'targetId')}])
    for selection, base in [([comment_selection(model), {'blockId': model['blocks'][0]['blockId']}], []),
                            ([comment_selection(model)], [{'kind': 'anything'}])]:
        with pytest.raises(ReportingError):
            selected_word_objects(model, base, selection)


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
    model = ScriptedModel(id='scripted', expected_tool_text='Original note', responses=[
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
