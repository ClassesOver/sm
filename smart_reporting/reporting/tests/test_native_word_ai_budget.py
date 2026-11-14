"""内部 Word agent 必须能完整读取合法长选区后登记候选。"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from agno.models.response import ModelResponse

from smart_reporting.report_editor.native_word_ai import (
    AgnoNativeWordProposalPlanner,
    NativeWordAITools,
)
from smart_reporting.reporting.tests.test_native_word_read_ai import ScriptedModel


@dataclass
class BudgetModel(ScriptedModel):
    def invoke(self, *args, **kwargs):
        return self.responses.pop(0)


def tool_call(name, arguments, identity):
    return ModelResponse(tool_calls=[{
        'id': identity, 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)},
    }])


@pytest.mark.anyio
@pytest.mark.parametrize('block_count,text_length,review', [
    (24, 30, False), (100, 30, False), (24, 30, True),
])
async def test_internal_word_agent_reads_beyond_twenty_calls_before_proposing(
    block_count, text_length, review,
):
    selected = [
        {'blockId': f'p{index}', 'type': 'paragraph', 'text': '文' * text_length,
         'expectedObjectSha256': 'a' * 64, 'allowedOperations': ['replaceParagraph']}
        for index in range(block_count)
    ]
    if review:
        selected = [
            {'selectionKind': 'revision', 'reviewId': f'revision:p{index}:r{index}',
             'blockId': f'p{index}', 'revisionId': f'r{index}', 'text': '修订' * text_length,
             'expectedObjectSha256': 'a' * 64, 'allowedOperations': ['resolveTextRevision']}
            for index in range(block_count)
        ]
    # 保持在生产start_edit的100对象/48000字符准入上限内。
    assert len(selected) <= 100
    assert len(json.dumps(selected, ensure_ascii=False)) <= 48000
    reader = NativeWordAITools(selected)
    responses = [tool_call('get_document_context', {}, 'context')]
    for target in selected:
        offset = 0
        while True:
            if review:
                page = reader.read_review_targets([target['reviewId']], offset=offset)
                name, arguments = 'read_review_targets', {'review_ids': [target['reviewId']]}
            else:
                page = reader.read_blocks([target['blockId']], offset=offset)
                name, arguments = 'read_blocks', {'block_ids': [target['blockId']]}
            responses.append(tool_call(name, {**arguments, 'offset': offset},
                                       f'read-{target["blockId"]}-{offset}'))
            if page['nextOffset'] is None:
                break
            offset = page['nextOffset']
    operation = {'kind': 'replaceParagraph', 'blockId': 'p0', 'text': '候选'}
    if review:
        operation = {'kind': 'resolveTextRevision', 'blockId': 'p0', 'revisionId': 'r0',
                     'action': 'reject'}
    receipt = reader.propose_operations('完整读取后修改', [operation])
    responses.extend([
        tool_call('propose_operations', {'summary': '完整读取后修改', 'operations': [operation]},
                  'propose'),
        ModelResponse(content=json.dumps(receipt['proposal'], ensure_ascii=False)),
    ])
    assert len(responses) > 20
    planner = AgnoNativeWordProposalPlanner(BudgetModel(id='internal-budget-test', responses=responses))
    proposal = await planner.plan_word('完整读取授权正文后修改第一段', selected=selected,
                                       session_id='budget-task', user_id='user')
    assert proposal.engine_operations() == receipt['operations']
    assert proposal.engine_operations()[0]['expectedObjectSha256'] == 'a' * 64
