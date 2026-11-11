"""未保存标注只按引擎回执撤销所属草稿操作，不按几何猜归属。"""

import json
from copy import deepcopy

import pytest
from agno.models.response import ModelResponse

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel
from smart_reporting.reporting.tests.test_native_pdf_review_delete_markup import tools_with_markups


def pending_tools():
    tools = tools_with_markups()
    reader = tools.reader
    reader._original_pages = deepcopy(reader.pages)
    reader._original_pages[1]['markups'] = []
    reader._operations = [{'kind': 'addMarkup', 'pageId': reader.pages[1]['pageId'],
        'markupType': 'highlight', 'quads': reader.pages[1]['markups'][0]['quads'], 'color': [1, 1, 0]}]
    reader.projection = {'appliedOperationIndices': [0], 'pendingMarkupMapping': [{
        'operationIndex': 0, 'pageId': reader.pages[1]['pageId'],
        'effectivePageId': reader.pages[1]['pageId'], 'annotationId': 'd' * 64,
        'sourceRef': '10R', 'expectedAnnotationSha256': 'd' * 64,
    }], 'pageMapping': [{'originalPageId': page['pageId'], 'effectivePageId': page['pageId']}
                       for page in reader.pages]}
    return tools


def test_delete_pending_markup_returns_explicit_base_removal_not_saved_identity():
    tools = pending_tools()
    tools.read_annotations()
    result = tools.delete_markup('a' * 64, 2, '撤销新增标注', ['d' * 64])
    assert result['removedBaseOperationIndices'] == [0]
    assert tools.operations == []
    tools.propose_reply('a' * 64, '已提出撤销新增标注候选。')
    final = tools.result('待采纳')
    assert final['removedBaseOperationIndices'] == [0]
    assert final['notes'][0]['removedBaseOperationIndices'] == [0]
    assert final['notes'][0]['operationIndices'] == []
    with pytest.raises(ReportingError):
        tools.delete_markup('a' * 64, 2, '重复撤销', ['d' * 64])
    assert reader_operations_unchanged(tools)


def reader_operations_unchanged(tools):
    return len(tools.reader._operations) == 1 and tools.reader._operations[0]['kind'] == 'addMarkup'


def test_mixed_pending_and_unbound_markup_does_not_partially_remove_base():
    tools = pending_tools()
    tools.read_annotations()
    with pytest.raises(ReportingError):
        tools.delete_markup('a' * 64, 2, '删除全部标注')
    assert tools.result('不能完整处理')['removedBaseOperationIndices'] == []
    assert tools.operations == []


def test_skip_is_not_allowed_after_proposing_base_removal():
    tools = pending_tools()
    tools.read_annotations()
    tools.delete_markup('a' * 64, 2, '撤销', ['d' * 64])
    with pytest.raises(ReportingError):
        tools.skip_note('a' * 64, '不能同时跳过')


@pytest.mark.anyio
async def test_agno_delete_markup_tool_can_propose_pending_base_removal():
    from smart_reporting.report_editor.native_pdf_review_ai import AgnoNativePDFReviewPlanner

    def call(name, arguments, identity):
        return ModelResponse(tool_calls=[{'id': identity, 'type': 'function', 'function': {
            'name': name, 'arguments': json.dumps(arguments),
        }}])

    tools = pending_tools()
    model = ScriptedModel(id='pending-markup-tools', responses=[
        call('read_annotations', {}, 'read'),
        call('delete_markup', {'annotation_id': 'a' * 64, 'page_number': 2,
            'reason': '撤销草稿高亮', 'markup_ids': ['d' * 64]}, 'delete'),
        call('propose_reply', {'annotation_id': 'a' * 64, 'contents': '已提出撤销候选。'}, 'reply'),
        ModelResponse(content=json.dumps({'answer': '撤销候选待采纳'})),
    ])
    result = await AgnoNativePDFReviewPlanner(model)(reader=tools.reader, instruction='撤销新增高亮',
        session_id='pending-markup-tools', user_id='u')
    assert result['operations'] == []
    assert result['removedBaseOperationIndices'] == [0]
    assert result['notes'][0]['removedBaseOperationIndices'] == [0]
    assert len(result['replies']) == 1
    assert reader_operations_unchanged(tools)
