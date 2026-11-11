"""原生 PPTX AI 备注仅在显式页授权下读写。"""
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from smart_reporting.report_editor.slides_ai_native_operations import validate_native_proposal
from smart_reporting.report_editor.slides_ai_tools import SlidesAIToolkit


def deck():
    return {'size': {'cx': 9144000, 'cy': 5143500}, 'slides': [
        {'slideIndex': 0, 'notesText': '人工备注', 'notesEditable': True, 'notesAuthorized': True,
         'elements': [{'id': 'title', 'type': 'text', 'text': '季度收入42', 'editable': False,
                       'geometry': {'x': 1, 'y': 1, 'width': 100, 'height': 30}}]},
        {'slideIndex': 1, 'notesText': '未授权机密备注', 'notesEditable': True, 'notesAuthorized': False, 'elements': []},
    ]}


def proposal(**kw):
    return {'summary': '补充演讲备注', 'edits': [], 'order': [0, 1],
            'notesEdits': [{'slideIndex': 0, 'text': '本季度收入42。'}], **kw}


def test_notes_require_explicit_authorization_and_strict_text():
    assert validate_native_proposal(proposal(), {}, deck())['notesEdits'][0]['text'] == '本季度收入42。'
    for edits in ([{'slideIndex': 1, 'text': '越权'}], [{'slideIndex': 0, 'text': '\x01'}],
                  [{'slideIndex': 0, 'text': 'x' * 20001}], [{'slideIndex': 0, 'text': '\ud800'}],
                  [{'slideIndex': 0, 'text': 'a'}, {'slideIndex': 0, 'text': 'b'}]):
        with pytest.raises(ValueError):
            validate_native_proposal(proposal(notesEdits=edits), {}, deck())


@pytest.mark.anyio
async def test_notes_tool_reads_only_authorized_notes_and_requires_complete_read():
    preview = AsyncMock(return_value={'draftSha256': 'b' * 64})
    toolkit = SlidesAIToolkit(deck=deck(), scope='notes', current_order=[0, 1], preview=preview)
    assert toolkit.get_presentation_context()['slides'][0]['slideIndex'] == 0
    with pytest.raises(ValueError, match='read_required'):
        await toolkit.propose_operations(proposal())
    page = toolkit.read_slide(0)
    assert '人工备注' in page['content'] and '季度收入42' in page['content']
    assert '未授权机密备注' not in str(toolkit.get_presentation_context())
    with pytest.raises(ValueError):
        toolkit.read_slide(1)
    result = await toolkit.propose_operations(proposal())
    assert result['requiresAcceptance'] is True
    assert result['editCount'] == 1
    preview.assert_awaited_once()


def test_canvas_authorization_does_not_grant_notes():
    model = deepcopy(deck())
    model['slides'][0]['notesAuthorized'] = False
    with pytest.raises(ValueError):
        validate_native_proposal(proposal(), {}, model)


@pytest.mark.anyio
async def test_notes_service_keeps_manual_draft_and_order_mapping():
    from uuid import uuid4

    from smart_reporting.report_editor.slides_ai_native_operations import NativeSlidesAIProposal
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    from smart_reporting.reporting.tests.test_slides_native_ai import Editor

    class NotesEditor(Editor):
        async def preview(self, context, *, expected_sha256, operations):
            self.previews.append(deepcopy(operations))
            model = deck()
            if operations:
                model['slides'][0]['notesText'] = '机密页手写备注'
                model['slides'][1]['notesText'] = '当前页人工未保存'
                model['slides'] = [model['slides'][1], model['slides'][0]]
            return {'draftSha256': 'b' * 64, 'model': model}

    seen = []
    class Planner:
        async def plan_slides(self, prompt, **kwargs):
            assert 'notesEdits' in prompt and '仅提出已授权文字、表格单元格或图表候选' not in prompt
            seen.append(kwargs['deck'])
            toolkit = SlidesAIToolkit(deck=kwargs['deck'], scope=kwargs['scope'],
                                     current_order=kwargs['current_order'], preview=kwargs['preview'])
            assert '当前页人工未保存' in toolkit.read_slide(1)['content']
            raw = proposal(order=[1, 0], notesEdits=[{'slideIndex': 1, 'text': 'AI演讲备注'}])
            await toolkit.propose_operations(raw)
            return NativeSlidesAIProposal.model_validate(raw)

    editor = NotesEditor()
    service = NativeSlidesAIService(editor, planner=Planner(), enabled=True)
    base = [{'kind': 'editSlides', 'order': [1, 0], 'notesEdits': [
        {'slideIndex': 0, 'text': '机密页手写备注'}, {'slideIndex': 1, 'text': '当前页人工未保存'}]}]
    started = await service.start_edit(None, client_request_id=uuid4().hex, instruction='生成演讲备注',
                                      expected_sha256='a' * 64, operations=base,
                                      selection=[{'slideIndex': 1}], scope='notes')
    result = await service.wait_edit_status(None, started['editId'])
    assert result['status'] == 'succeeded', result
    accepted = await service.accept_edit(None, started['editId'], expected_sha256='a' * 64,
                                        operations=base, snapshot_sha256=result['snapshotSha256'])
    assert accepted['operations'][0]['notesEdits'] == [
        {'slideIndex': 0, 'text': '机密页手写备注'}, {'slideIndex': 1, 'text': 'AI演讲备注'}]
    assert seen[0]['slides'][1]['notesText'] == '当前页人工未保存'
    assert not any(element['editable'] for slide in seen[0]['slides'] for element in slide['elements'])


@pytest.mark.anyio
async def test_notes_ai_real_engine_preview_accept_and_independent_pptx_readback(tmp_path):
    import asyncio
    import hashlib
    from io import BytesIO
    from uuid import uuid4

    from pptx import Presentation
    from pptx.util import Inches

    from smart_reporting.report_editor.native_models import NativeEditorContext
    from smart_reporting.report_editor.native_office import inspect_office, patch_office
    from smart_reporting.report_editor.slides_ai_native_operations import NativeSlidesAIProposal
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    from smart_reporting.reporting.tests.test_slides_native_ai import Editor

    presentation = Presentation()
    for text, note in [('季度收入42', '来源备注'), ('未选择正文', '未选择的机密备注')]:
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = text
        slide.notes_slide.notes_text_frame.text = note
    # python-pptx 不自动登记 presentation 的 notesMasterIdLst，显式构造合法来源。
    from lxml import etree
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from pptx.oxml.ns import qn
    master_rel = next(rel for rel in presentation.part.rels.values() if rel.reltype == RT.NOTES_MASTER)
    master_ids = etree.Element(qn('p:notesMasterIdLst'))
    etree.SubElement(master_ids, qn('p:notesMasterId')).set(qn('r:id'), master_rel.rId)
    presentation._element.insert(presentation._element.index(presentation._element.find(qn('p:sldMasterIdLst'))) + 1, master_ids)
    output = BytesIO()
    presentation.save(output)
    content = output.getvalue()
    (tmp_path / 'source.pptx').write_bytes(content)

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

    class Planner:
        async def plan_slides(self, prompt, **kwargs):
            toolkit = SlidesAIToolkit(deck=kwargs['deck'], scope=kwargs['scope'],
                                     current_order=kwargs['current_order'], preview=kwargs['preview'])
            context = toolkit.get_presentation_context()
            assert len(context['slides']) == 1
            text = toolkit.read_slide(0)['content']
            assert '人工草稿备注' in text and '季度收入42' in text and '机密' not in text
            raw = proposal(notesEdits=[{'slideIndex': 0, 'text': '季度收入42，保持稳健增长。\n\n谢谢。'}])
            await toolkit.propose_operations(raw)
            return NativeSlidesAIProposal.model_validate(raw)

    editor = RealEditor()
    ai = NativeSlidesAIService(editor, planner=Planner(), enabled=True)
    base = [{'kind': 'editSlides', 'notesEdits': [{'slideIndex': 0, 'text': '人工草稿备注'}]}]
    started = await ai.start_edit(None, client_request_id=uuid4().hex, instruction='撰写本页演讲备注',
                                 expected_sha256=editor.context.source_file.sha256, operations=base,
                                 selection=[{'slideIndex': 0}], scope='notes')
    result = await ai.wait_edit_status(None, started['editId'])
    assert result['status'] == 'succeeded', result
    accepted = await ai.accept_edit(None, started['editId'], expected_sha256=editor.context.source_file.sha256,
                                   operations=base, snapshot_sha256=result['snapshotSha256'])
    edited = await asyncio.to_thread(patch_office, 'pptx', content, accepted['operations'])
    (tmp_path / 'candidate.pptx').write_bytes(edited)
    reopened = Presentation(BytesIO(edited))
    assert reopened.slides[0].notes_slide.notes_text_frame.text == '季度收入42，保持稳健增长。\n\n谢谢。'
    assert reopened.slides[1].notes_slide.notes_text_frame.text == '未选择的机密备注'
    assert reopened.slides[0].shapes[0].text == '季度收入42'
    assert reopened.slides[1].shapes[0].text == '未选择正文'
    assert Presentation(BytesIO(content)).slides[0].notes_slide.notes_text_frame.text == '来源备注'


@pytest.mark.anyio
async def test_notes_agno_tool_loop_does_not_leak_other_page_notes():
    import json

    from agno.agent import Agent
    from agno.models.response import ModelResponse

    from smart_reporting.report_editor.slides_ai import AgnoSlidesProposalPlanner
    from smart_reporting.reporting.tests.pptx_ai_fixture import ScriptedModel
    def call(name, args, identity):
        return ModelResponse(tool_calls=[{'id': identity, 'type': 'function', 'function': {
            'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}])
    model = ScriptedModel(id='scripted-notes', expected_tool_text='notesText', responses=[
        call('get_presentation_context', {}, 'ctx'), call('read_slide', {'slide_index': 0}, 'read'),
        call('propose_operations', {'proposal': proposal()}, 'propose'), ModelResponse(content='备注候选待采纳')])
    preview = AsyncMock(return_value={'draftSha256': 'b' * 64})
    planned = await AgnoSlidesProposalPlanner(Agent(model=model)).plan_slides('补充备注',
        deck=deck(), scope='notes', current_order=[0, 1], preview=preview, session_id='notes', user_id='u')
    assert planned.notes_edits[0].text == '本季度收入42。'
    assert '未授权机密备注' not in str(model.seen)
    preview.assert_awaited_once()


@pytest.mark.anyio
async def test_notes_partial_read_and_canvas_edits_cannot_bypass_authorization():
    model = deck()
    model['slides'][0]['notesText'] = '资料' * 15000
    model['slides'][0]['elements'][0]['editable'] = True
    toolkit = SlidesAIToolkit(deck=model, scope='notes', current_order=[0, 1],
                             preview=AsyncMock(return_value={'draftSha256': 'b' * 64}))
    page = toolkit.read_slide(0)
    assert page['nextOffset'] is not None and page['readComplete'] is False
    with pytest.raises(ValueError, match='read_required'):
        await toolkit.propose_operations(proposal())
    toolkit.read_slide(0, page['nextOffset'])
    with pytest.raises(ValueError):
        await toolkit.propose_operations(proposal(edits=[{'slideIndex': 0, 'elementId': 'title', 'text': '越权画布'}]))
    await toolkit.propose_operations(proposal())


@pytest.mark.anyio
async def test_notes_service_accepts_blank_page_and_rejects_implicit_element_authorization():
    from uuid import uuid4

    from smart_reporting.report_editor.slides_ai_native_operations import NativeSlidesAIProposal
    from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
    from smart_reporting.reporting.tests.test_slides_native_ai import Editor

    class BlankEditor(Editor):
        async def preview(self, _context, **_kwargs):
            model = deck()
            model['slides'][0]['elements'] = []
            return {'draftSha256': 'b' * 64, 'model': model}
    async def planner(_prompt, **_kwargs):
        return NativeSlidesAIProposal.model_validate(proposal(notesEdits=[{'slideIndex': 0, 'text': ''}]))
    service = NativeSlidesAIService(BlankEditor(), planner=planner, enabled=True)
    started = await service.start_edit(None, client_request_id=uuid4().hex, instruction='清空备注',
                                      expected_sha256='a' * 64, operations=[], selection=[{'slideIndex': 0}], scope='notes')
    assert (await service.wait_edit_status(None, started['editId']))['status'] == 'succeeded'
    started = await service.start_edit(None, client_request_id=uuid4().hex, instruction='越权备注',
                                      expected_sha256='a' * 64, operations=[],
                                      selection=[{'slideIndex': 0, 'elementId': 'title'}], scope='notes')
    assert (await service.wait_edit_status(None, started['editId']))['status'] == 'failed'
