"""生产工厂连接Word原生工具，预览/采纳保留来源与选区边界。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO

import pytest
from agno.models.response import ModelResponse
from docx import Document

from smart_reporting.report_editor.native_ai import NativeAIService, create_native_ai_service
from smart_reporting.report_editor.native_word_ai import NativeWordAIProposal
from smart_reporting.reporting.delivery.docx_native import patch_docx
from smart_reporting.reporting.tests.test_native_ai import pdf_sample as pdf_sample
from smart_reporting.reporting.tests.test_native_ai import sample as sample
from smart_reporting.reporting.tests.test_native_word_read_ai import (
    ScriptedModel as BaseScriptedModel,
)


@dataclass
class ScriptedModel(BaseScriptedModel):
    def invoke(self, *args, **kwargs):
        messages = kwargs.get("messages", args[0] if args else [])
        if len(self.responses) == 1:
            assert any(message.role == "tool" and "第一段原文" in str(message.content)
                       for message in messages)
            assert "未经选择的机密段落" not in str(messages)
        return self.responses.pop(0)


def call(name, arguments, identity):
    return ModelResponse(tool_calls=[{'id': identity, 'type': 'function', 'function': {
        'name': name, 'arguments': json.dumps(arguments, ensure_ascii=False)}}])


@pytest.mark.anyio
async def test_production_factory_word_tools_preview_accept_and_preserve_source(sample):
    editor, context, session, model, source = sample
    target = model['blocks'][0]
    operation = {'kind': 'setParagraphSpacing', 'blockId': target['blockId'],
        'spaceBefore': 240, 'spaceAfter': 120, 'lineSpacing': 1.5}
    final_operation = {**operation, 'expectedObjectSha256': target['expectedObjectSha256']}
    scripted = ScriptedModel(id='scripted-word-wiring', responses=[
        call('get_document_context', {}, 'context'),
        call('read_blocks', {'block_ids': [target['blockId']]}, 'read'),
        call('propose_operations', {'summary': '调整选段间距', 'operations': [operation]}, 'propose'),
        ModelResponse(content=json.dumps({'summary': '调整选段间距', 'operations': [{
            'kind': final_operation['kind'], 'arguments': {
                key: value for key, value in final_operation.items() if key != 'kind'}}]})),
    ])
    ai = create_native_ai_service(scripted, editor, enabled=True)
    try:
        started = await ai.start_edit(session, instruction='调整所选段落间距',
            expected_sha256=context.source_file.sha256, operations=[],
            selection=[{'blockId': target['blockId']}])
        result = await ai.wait_edit_status(session, started['editId'])
        assert result['status'] == 'succeeded', result
        assert result['proposal']['operations'] == [final_operation]
        accepted = await ai.accept_edit(session, started['editId'],
            expected_sha256=context.source_file.sha256, operations=[],
            snapshot_sha256=result['snapshotSha256'])
        changed = Document(BytesIO(patch_docx(source, accepted['operations'])))
        assert changed.paragraphs[0].paragraph_format.space_before.twips == 240
        assert changed.paragraphs[1].text == '未经选择的机密段落'
        assert await editor.read_file(context) == source
        assert len(scripted.responses) == 4
    finally:
        await ai.aclose()


class TablePlanner:
    def __init__(self, operation):
        self.operation = operation
        self.selected = None

    async def plan_word(self, prompt, *, selected, **kwargs):
        self.selected = selected
        return NativeWordAIProposal(summary='调整授权表格', operations=[{
            'kind': self.operation['kind'], 'arguments': {
                key: value for key, value in self.operation.items() if key != 'kind'}}])


@pytest.mark.anyio
@pytest.mark.parametrize('selection', [None, {'blockId': 'invalid'}])
async def test_word_wiring_rejects_invalid_selection_with_domain_error(sample, selection):
    from smart_reporting.reporting.models import ReportingError

    editor, context, session, _, _ = sample
    ai = NativeAIService(editor, planner=TablePlanner({}), enabled=True)
    try:
        with pytest.raises(ReportingError, match='请选择'):
            await ai.start_edit(session, instruction='调整段落',
                expected_sha256=context.source_file.sha256, operations=[], selection=selection)
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_service_word_whole_table_uses_complex_capability_and_server_hash(sample):
    editor, context, session, model, source = sample
    table = next(item for item in model['blocks'] if item['type'] == 'table')
    operation = {'kind': 'setTableAlignment', 'blockId': table['blockId'],
        'alignment': 'center'}
    planner = TablePlanner(operation)
    ai = NativeAIService(editor, planner=planner, enabled=True)
    try:
        started = await ai.start_edit(session, instruction='增加表格行',
            expected_sha256=context.source_file.sha256, operations=[],
            selection=[{'blockId': table['blockId']}])
        result = await ai.wait_edit_status(session, started['editId'])
        assert result['status'] == 'succeeded', result
        assert 'setTableAlignment' in planner.selected[0]['allowedOperations']
        assert result['proposal']['operations'][0]['expectedObjectSha256'] == table['expectedObjectSha256']
        accepted = await ai.accept_edit(session, started['editId'],
            expected_sha256=context.source_file.sha256, operations=[], snapshot_sha256=result['snapshotSha256'])
        assert Document(BytesIO(patch_docx(source, accepted['operations']))).tables[0].alignment == 1
        assert await editor.read_file(context) == source
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_service_word_single_cell_does_not_authorize_table_or_neighbours(sample):
    editor, context, session, model, source = sample
    table = next(item for item in model['blocks'] if item['type'] == 'table')
    cell = table['cells'][0][0]
    planner = TablePlanner({'kind': 'restructureTable', 'blockId': table['blockId'],
        'steps': [{'kind': 'insertTableRow', 'index': 1}]})
    ai = NativeAIService(editor, planner=planner, enabled=True)
    try:
        started = await ai.start_edit(session, instruction='只处理当前格',
            expected_sha256=context.source_file.sha256, operations=[],
            selection=[{'blockId': table['blockId'], 'cellId': cell['cellId']}])
        result = await ai.wait_edit_status(session, started['editId'])
        assert result['status'] == 'failed', result
        assert result['error']['code'] == 'native_ai_selection_mismatch'
        assert planner.selected[0]['cellId'] == cell['cellId']
        assert 'cells' not in planner.selected[0]
        assert await editor.read_file(context) == source
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_word_complex_structure_draft_is_not_silently_projected(sample):
    from smart_reporting.reporting.models import ReportingError

    editor, context, session, model, _ = sample
    table = next(item for item in model['blocks'] if item['type'] == 'table')
    planner = TablePlanner({'kind': 'setTableAlignment', 'blockId': table['blockId'],
        'alignment': 'center'})
    ai = NativeAIService(editor, planner=planner, enabled=True)
    try:
        with pytest.raises(ReportingError, match='保存'):
            await ai.start_edit(session, instruction='调整表格',
                expected_sha256=context.source_file.sha256,
                operations=[{'kind': 'restructureTable', 'blockId': table['blockId'],
                    'expectedObjectSha256': table['expectedObjectSha256'],
                    'steps': [{'kind': 'insertTableRow', 'index': 0}]}],
                selection=[{'blockId': table['blockId']}])
        assert planner.selected is None
    finally:
        await ai.aclose()


@pytest.mark.anyio
async def test_production_factory_pdf_keeps_legacy_planner_path(pdf_sample, monkeypatch):
    from smart_reporting.reporting.tests.test_native_ai import pdf_ai_selection

    editor, context, session, model, original = pdf_sample
    selection = pdf_ai_selection(model)
    scripted = BaseScriptedModel(id='scripted-pdf-wiring', responses=[ModelResponse(
        content=json.dumps({'summary': 'PDF候选', 'operations': [{'kind': 'replaceText',
            'arguments': {**selection, 'newText': 'Amount due 600'}}]}))])
    ai = create_native_ai_service(scripted, editor, enabled=True)
    async def forbidden_word(*args, **kwargs):
        pytest.fail('PDF不应委托Word工具')
    monkeypatch.setattr(ai.planner.word_planner, 'plan_word', forbidden_word)
    try:
        started = await ai.start_edit(session, instruction='修改所选数字',
            expected_sha256=context.source_file.sha256, operations=[], selection=[selection])
        result = await ai.wait_edit_status(session, started['editId'])
        assert result['status'] == 'succeeded', result
        assert result['proposal']['operations'][0]['kind'] == 'replaceText'
        assert await editor.read_file(context) == original
    finally:
        await ai.aclose()
