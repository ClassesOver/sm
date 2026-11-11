"""真实 Word 审阅模型的只读授权与独立阅读覆盖。"""
import json

import pytest
from agno.models.response import ModelResponse

from smart_reporting.report_editor.native_word_read_ai import (
    AgnoNativeWordReadPlanner,
    NativeWordReadTools,
)
from smart_reporting.reporting.delivery.docx_native import inspect_docx
from smart_reporting.reporting.tests.test_docx_comment_reply import modern_source
from smart_reporting.reporting.tests.test_docx_text_revision_host import rewrite, source
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel


def test_actual_comment_threads_have_evidence_identity_and_do_not_count_as_body_read():
    model = inspect_docx(modern_source())
    reader = NativeWordReadTools(model)
    page = reader.read_comments()
    comments = json.loads(page['content'])
    assert [item['text'] for item in comments] == ['Original note', 'Existing reply']
    assert comments[0]['author'] == 'Alice'
    assert comments[0]['done'] is True
    assert comments[1]['parentId'] == '1'
    ids = [item['reviewId'] for item in comments]
    result = reader.result('两条审阅意见', [], review_citations=ids + ['comment:forged'])
    assert [item['id'] for item in result['reviewCitations']] == ids
    assert result['reviewCitations'][0]['id'].endswith(model['comments']['commentTargets'][0]['targetId'])
    assert result['reviewCoverage']['comments']['readComplete']
    assert not result['coverage']['scopeReadComplete']
    assert 'native_word_ai_unread_review_citation' in {i['code'] for i in result['issues']}


def test_selection_does_not_leak_unanchored_comments_or_cell_block_revisions():
    model = inspect_docx(modern_source())
    reader = NativeWordReadTools(model, [{'blockId': model['blocks'][0]['blockId']}])
    assert json.loads(reader.read_comments()['content']) == []
    assert 'Original note' not in repr(reader._review.__dict__)
    assert any('锚点' in text for text in reader.result('无可读批注', [])['limitations'])
    model = {'blocks': [{'blockId': 'table', 'type': 'table', 'cells': [[
        {'cellId': 'selected', 'text': '授权'}, {'cellId': 'private', 'text': '秘密'}]],
        'reviewTargets': [{'revisionId': 'r', 'blockId': 'table', 'type': 'insertion',
                           'sourceRange': {'text': '秘密修订'}}]}]}
    selected = NativeWordReadTools(model, [{'blockId': 'table', 'cellId': 'selected'}])
    assert json.loads(selected.read_revisions()['content']) == []
    assert '秘密修订' not in repr(selected._review.__dict__)


def test_actual_revision_source_text_and_complex_revision_limitations():
    model = inspect_docx(source())
    block = model['blocks'][1]
    reader = NativeWordReadTools(model, [{'blockId': block['blockId']}])
    revisions = json.loads(reader.read_revisions([block['blockId']])['content'])
    assert [r['text'] for r in revisions] == [' 新😀 ', '旧文']
    assert [r['type'] for r in revisions] == ['insertion', 'deletion']
    assert revisions[0]['revisionId'] == block['reviewTargets'][0]['revisionId']
    assert reader.result('插入和删除', [], review_citations=[r['reviewId'] for r in revisions])[
        'reviewCoverage']['revisions']['readComplete']
    other = NativeWordReadTools(model, [{'blockId': model['blocks'][0]['blockId']}])
    with pytest.raises(ValueError):
        other.read_revisions([block['blockId']])
    opaque = rewrite(source(), lambda n, b: b.replace('<w:t>保留</w:t>'.encode(),
        '<w:drawing/><w:t>保留</w:t>'.encode()) if n == 'word/document.xml' else b)
    limited = NativeWordReadTools(inspect_docx(opaque))
    assert json.loads(limited.read_revisions()['content']) == []
    assert any('docx_revision_projection_unsupported' in text for text in limited.result('无法完整读取修订', [])['limitations'])


def test_review_tail_pages_and_body_reads_cannot_forge_review_coverage():
    model = inspect_docx(modern_source())
    model['commentThreads']['targets'][0]['text'] = '长' * 60000
    reader = NativeWordReadTools(model)
    reader.read_blocks([model['blocks'][0]['blockId']])
    assert not reader.result('只读正文', [])['reviewCoverage']['comments']['readComplete']
    assert reader.tool_call_budget() >= 16
    tail = reader.read_comments(offset=48000)
    assert tail['nextOffset'] is None
    assert reader.result('未完整读取', [])['reviewCoverage']['comments']['fullyReadIds'] == []
    first = reader.read_comments()
    reader.read_comments(offset=first['nextOffset'])
    assert reader.result('已完整读取', [])['reviewCoverage']['comments']['readComplete']


@pytest.mark.anyio
async def test_agno_calls_review_tools_and_server_rebuilds_citations():
    inspected = inspect_docx(modern_source())
    target = inspected['commentThreads']['targets'][0]
    identity = 'comment:' + target['sourceId'] + ':' + target['targetId']
    model = ScriptedModel(id='scripted', expected_tool_text='Original note', responses=[
        ModelResponse(tool_calls=[{'id': 'comments', 'type': 'function', 'function': {
            'name': 'read_comments', 'arguments': '{}'}}]),
        ModelResponse(tool_calls=[{'id': 'revisions', 'type': 'function', 'function': {
            'name': 'read_revisions', 'arguments': '{}'}}]),
        ModelResponse(content=json.dumps({'answer': 'Alice提出Original note，线程已解决。',
                                         'citations': [], 'reviewCitations': [identity]})),
    ])
    result = await AgnoNativeWordReadPlanner(model)(reader=NativeWordReadTools(inspected),
        action='ask', instruction='总结审阅意见与修订', session_id='review-read', user_id='user')
    assert result['reviewCitations'][0]['id'].endswith(target['targetId'])
    assert [event['tool'] for event in result['toolEvents']] == ['read_comments', 'read_revisions']
    assert result['coverage']['fullyReadBlockIds'] == []
    assert result['reviewCoverage']['comments']['readComplete']
    assert 'operations' not in result


def test_review_tools_expose_limits_and_keep_empty_comment_identity():
    model = {'blocks': [{'blockId': 'p', 'type': 'paragraph', 'text': '正文',
                        'revisionReadOnlyReason': 'docx_revision_projection_unsupported'}],
        'comments': {'commentTargets': [{'sourceId': 'source', 'targetId': 'target',
            'originalCommentId': '1', 'text': '', 'author': '作者'}]}}
    reader = NativeWordReadTools(model)
    model['comments']['commentTargets'][0]['text'] = '外部变更'
    page = reader.read_comments()
    assert json.loads(page['content'])[0]['text'] == ''
    revisions = reader.read_revisions()
    assert any('docx_revision_projection_unsupported' in text for text in revisions['limitations'])
    assert revisions['reviewCoverage']['comments']['fullyReadIds'] == ['comment:source:target']


def test_review_only_evidence_suppresses_no_evidence_but_not_body_coverage_warning():
    model = inspect_docx(source())
    reader = NativeWordReadTools(model)
    initial = reader.result('没有阅读依据', [])
    assert 'native_word_ai_no_evidence' in {item['code'] for item in initial['issues']}
    page = reader.read_revisions()
    revision_ids = [item['reviewId'] for item in json.loads(page['content'])]
    result = reader.result('修订摘要', [], action='summary', review_citations=revision_ids)
    codes = {item['code'] for item in result['issues']}
    assert 'native_word_ai_no_evidence' not in codes
    assert 'native_word_ai_incomplete_coverage' in codes
    assert result['coverage']['fullyReadBlockIds'] == []
    assert [item['label'] for item in result['reviewCitations']] == ['第2块：插入修订1', '第2块：删除修订2']
