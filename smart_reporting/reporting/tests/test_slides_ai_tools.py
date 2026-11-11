"""PPTX Agno 工具循环必须读取授权内容，并经真实预览后登记候选。"""

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agno.agent import Agent
from agno.models.response import ModelResponse

from smart_reporting.report_editor.slides_ai import AgnoSlidesProposalPlanner
from smart_reporting.reporting.tests.pptx_ai_fixture import ScriptedModel


def deck():
    return {'size': {'cx': 9525000, 'cy': 5715000}, 'slides': [
        {'slideIndex': 0, 'elements': [
            {'id': 'title', 'editable': True, 'text': '人工标题', 'geometry': {'x': 10, 'y': 10, 'width': 100, 'height': 40}},
            {'id': 'private', 'editable': False, 'text': '机密', 'geometry': {'x': 10, 'y': 100, 'width': 100, 'height': 40}},
        ]},
        {'slideIndex': 1, 'elements': [{'id': 'other', 'editable': False, 'text': '另一秘密'}]},
    ]}


def proposal():
    return {'summary': '调整标题', 'edits': [{'slideIndex': 0, 'elementId': 'title', 'text': '候选标题', 'bold': True}], 'order': [0, 1]}


@pytest.mark.anyio
async def test_slides_tools_require_complete_read_and_keep_unselected_content_private():
    from smart_reporting.report_editor.slides_ai_tools import SlidesAIToolkit

    preview = AsyncMock(return_value={'draftSha256': 'a' * 64})
    tools = SlidesAIToolkit(deck=deck(), scope='selection', current_order=[0, 1], preview=preview)
    assert '机密' not in json.dumps(tools.get_presentation_context(), ensure_ascii=False)
    with pytest.raises(ValueError, match='read_required'):
        await tools.propose_operations(proposal())
    assert '机密' not in tools.read_slide(0)['content']
    with pytest.raises(ValueError, match='selection'):
        tools.read_slide(1)
    result = await tools.propose_operations(proposal())
    assert result['requiresAcceptance'] is True
    assert tools.proposal.summary == '调整标题'
    preview.assert_awaited_once()
    with pytest.raises(ValueError, match='submitted'):
        await tools.propose_operations(proposal())


@pytest.mark.anyio
async def test_slides_tools_reject_cross_scope_and_failed_preview_without_registering_candidate():
    from smart_reporting.report_editor.slides_ai_tools import SlidesAIToolkit

    preview = AsyncMock(side_effect=ValueError('engine rejected'))
    tools = SlidesAIToolkit(deck=deck(), scope='selection', current_order=[1, 0], preview=preview)
    tools.read_slide(0)
    with pytest.raises(ValueError, match='selection'):
        await tools.propose_operations(proposal())
    candidate = {**proposal(), 'order': [1, 0]}
    with pytest.raises(ValueError, match='engine rejected'):
        await tools.propose_operations(candidate)
    assert tools.proposal is None


def call(name, arguments, identity):
    return ModelResponse(tool_calls=[{'id': identity, 'type': 'function', 'function': {
        'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False),
    }}])


@pytest.mark.anyio
async def test_real_agno_slides_loop_uses_read_and_preview_tools_instead_of_assistant_prose():
    model = ScriptedModel(id='scripted-slides', responses=[
        call('get_presentation_context', {}, 'context'),
        call('read_slide', {'slide_index': 0}, 'read'),
        call('propose_operations', {'proposal': proposal()}, 'propose'),
        ModelResponse(content='候选待采纳'),
    ])
    preview = AsyncMock(return_value={'draftSha256': 'b' * 64})
    planned = await AgnoSlidesProposalPlanner(Agent(model=model)).plan_slides(
        '调整标题', deck=deck(), scope='selection', current_order=[0, 1], preview=preview,
        session_id='slides-tools', user_id='u',
    )
    assert planned.summary == '调整标题'
    preview.assert_awaited_once()
    assert '机密' not in str(model.seen)
    prose_model = ScriptedModel(id='prose-only', responses=[ModelResponse(content=json.dumps(proposal()))])
    with pytest.raises(ValueError, match='not_submitted'):
        await AgnoSlidesProposalPlanner(Agent(model=prose_model)).plan_slides(
            '调整标题', deck=deck(), scope='selection', current_order=[0, 1], preview=preview,
            session_id='prose-only', user_id='u',
        )


@pytest.mark.anyio
async def test_native_slides_service_runs_agno_tools_and_streams_actual_calls():
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    from smart_reporting.reporting.tests.test_slides_native_ai import Editor

    model = ScriptedModel(id='native-slides-tools', responses=[
        call('get_presentation_context', {}, 'context'),
        call('read_slide', {'slide_index': 0}, 'read'),
        call('propose_operations', {'proposal': proposal()}, 'propose'),
        ModelResponse(content='候选待采纳'),
    ])
    editor = Editor()
    ai = NativeSlidesAIService(editor, planner=AgnoSlidesProposalPlanner(Agent(model=model)), enabled=True)
    base = [{'kind': 'editSlides', 'textFormatting': [
        {'slideIndex': 0, 'elementId': 'title', 'italic': True},
    ]}]
    started = await ai.start_edit(None, client_request_id=uuid4().hex, instruction='调整标题',
        expected_sha256='a' * 64, operations=base, selection=[{'slideIndex': 0, 'elementId': 'title'}])
    result = await ai.wait_edit_status(None, started['editId'])
    assert result['status'] == 'succeeded', result
    assert result['accepted'] is False
    assert '未选择的机密文字' not in str(model.seen)
    accepted = await ai.accept_edit(None, started['editId'], expected_sha256='a' * 64,
        operations=base, snapshot_sha256=result['snapshotSha256'])
    assert accepted['operations'][0]['textFormatting'] == [
        {'slideIndex': 0, 'elementId': 'title', 'italic': True, 'bold': True},
    ]
    events = ai._jobs[started['editId']].event_log.history
    assert [(event['toolName'], event['toolCallId']) for event in events if event['kind'] == 'toolCompleted'] == [
        ('get_presentation_context', 'context'), ('read_slide', 'read'), ('propose_operations', 'propose'),
    ]
    assert events[-1]['kind'] == 'terminal' and events[-1]['status'] == 'succeeded'
    await ai.aclose()


@pytest.mark.anyio
async def test_agno_slides_tools_preview_real_pptx_and_preserve_manual_draft():
    import asyncio
    import hashlib
    from copy import deepcopy
    from io import BytesIO

    from pptx import Presentation
    from pptx.util import Inches

    from smart_reporting.report_editor.native_models import NativeEditorContext
    from smart_reporting.report_editor.native_office import inspect_office, patch_office
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    from smart_reporting.reporting.tests.test_slides_native_ai import Editor

    presentation = Presentation()
    for text in ['第一张', '不授权的秘密']:
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = text
    stream = BytesIO()
    presentation.save(stream)
    content = stream.getvalue()
    inspected = await asyncio.to_thread(inspect_office, 'pptx', content)
    target = inspected['slides'][0]['elements'][0]['id']
    candidate = {'summary': '润色并调整版式', 'order': [1, 0], 'edits': [{
        'slideIndex': 0, 'elementId': target, 'text': '候选标题', 'bold': True,
        'fontSizePt': 24, 'color': '#123456',
        'geometry': {'x': 120, 'y': 100, 'width': 300, 'height': 100},
    }]}
    model = ScriptedModel(id='real-engine-slides-tools', responses=[
        call('get_presentation_context', {}, 'context'),
        call('read_slide', {'slide_index': 0}, 'read'),
        call('propose_operations', {'proposal': candidate}, 'propose'),
        ModelResponse(content='候选待采纳'),
    ])

    class RealEditor(Editor):
        def __init__(self):
            super().__init__()
            raw = self.context.model_dump(by_alias=True)
            raw['sourceFile'].update(sha256=hashlib.sha256(content).hexdigest(), size=len(content))
            self.context = NativeEditorContext.model_validate(raw)

        async def preview(self, _context, *, expected_sha256, operations):
            assert expected_sha256 == self.context.source_file.sha256
            edited = await asyncio.to_thread(patch_office, 'pptx', content, operations)
            self.previews.append(deepcopy(operations))
            return {'draftSha256': hashlib.sha256(edited).hexdigest(),
                    'model': await asyncio.to_thread(inspect_office, 'pptx', edited)}

    editor = RealEditor()
    ai = NativeSlidesAIService(editor, planner=AgnoSlidesProposalPlanner(Agent(model=model)), enabled=True)
    base = [{'kind': 'editSlides', 'order': [1, 0], 'edits': [
        {'slideIndex': 0, 'elementId': target, 'text': '人工标题'},
    ], 'textFormatting': [{'slideIndex': 0, 'elementId': target, 'italic': True}],
        'backgrounds': [{'slideIndex': 0, 'color': '#abcdef'}]}]
    original_base = deepcopy(base)
    sha = editor.context.source_file.sha256
    started = await ai.start_edit(None, client_request_id=uuid4().hex,
        instruction='润色标题并调整样式和位置，保留人工页序', expected_sha256=sha,
        operations=base, selection=[{'slideIndex': 0, 'elementId': target}])
    result = await ai.wait_edit_status(None, started['editId'])
    assert result['status'] == 'succeeded', result
    assert '人工标题' in str(model.seen) and '不授权的秘密' not in str(model.seen)
    accepted = await ai.accept_edit(None, started['editId'], expected_sha256=sha,
        operations=base, snapshot_sha256=result['snapshotSha256'])
    edited = await asyncio.to_thread(patch_office, 'pptx', content, accepted['operations'])
    reopened = Presentation(BytesIO(edited))
    assert reopened.slides[0].shapes[0].text == '不授权的秘密'
    shape = reopened.slides[1].shapes[0]
    assert shape.text == '候选标题' and shape.left == 120 * 9525
    run = shape.text_frame.paragraphs[0].runs[0]
    assert run.font.size.pt == 24 and run.font.bold is True and run.font.italic is True
    assert str(run.font.color.rgb) == '123456'
    assert str(reopened.slides[1].background.fill.fore_color.rgb) == 'ABCDEF'
    assert Presentation(BytesIO(content)).slides[0].shapes[0].text == '第一张'
    assert base == original_base
    assert editor.previews[-1] == accepted['operations']
    await ai.aclose()


@pytest.mark.anyio
async def test_cancel_during_agno_tool_preview_cannot_publish_candidate():
    import asyncio

    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    from smart_reporting.reporting.tests.test_slides_native_ai import Editor

    entered = asyncio.Event()
    editor = Editor()
    original_preview = editor.preview
    calls = []

    async def blocking_preview(context, **kwargs):
        calls.append(kwargs['operations'])
        if len(calls) == 2:
            entered.set()
            await asyncio.Event().wait()
        return await original_preview(context, **kwargs)

    editor.preview = blocking_preview
    model = ScriptedModel(id='cancel-slides-tools', responses=[
        call('read_slide', {'slide_index': 0}, 'read'),
        call('propose_operations', {'proposal': proposal()}, 'propose'),
        ModelResponse(content='不应发布候选'),
    ])
    original_agent = Agent(model=model, instructions=['原代理说明'])
    original_tools = list(original_agent.tools)
    ai = NativeSlidesAIService(editor, planner=AgnoSlidesProposalPlanner(original_agent), enabled=True)
    try:
        started = await ai.start_edit(None, client_request_id=uuid4().hex, instruction='调整标题',
            expected_sha256='a' * 64, operations=[], selection=[{'slideIndex': 0, 'elementId': 'title'}])
        await asyncio.wait_for(entered.wait(), timeout=5)
        cancelled = await ai.cancel_edit(None, started['editId'])
        assert cancelled['status'] == 'cancelled' and 'proposal' not in cancelled
        result = await ai.wait_edit_status(None, started['editId'])
        assert result['status'] == 'cancelled' and 'proposal' not in result
        assert len(calls) == 2
        assert original_agent.tools == original_tools and original_agent.instructions == ['原代理说明']
        events = ai._jobs[started['editId']].event_log.history
        assert events[-1]['kind'] == 'terminal' and events[-1]['status'] == 'cancelled'
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_agno_full_deck_proposal_has_budget_to_read_more_than_thirty_slides():
    from copy import deepcopy

    large_deck = {'size': deck()['size'], 'slides': []}
    for index in range(31):
        slide = deepcopy(deck()['slides'][0])
        slide['slideIndex'] = index
        large_deck['slides'].append(slide)
    candidate = {'summary': '调整整稿页序', 'edits': [], 'order': list(reversed(range(31)))}
    model = ScriptedModel(id='large-deck-tools', responses=[
        call('get_presentation_context', {}, 'context'),
        *[call('read_slide', {'slide_index': index}, f'read-{index}') for index in range(31)],
        call('propose_operations', {'proposal': candidate}, 'propose'),
        ModelResponse(content='候选待采纳'),
    ])
    preview = AsyncMock(return_value={'draftSha256': 'a' * 64})
    planned = await AgnoSlidesProposalPlanner(Agent(model=model)).plan_slides(
        '倒序排列整稿', deck=large_deck, scope='deck', current_order=list(range(31)), preview=preview,
        session_id='large-slides', user_id='u',
    )
    assert planned.order == tuple(reversed(range(31)))
    preview.assert_awaited_once()
