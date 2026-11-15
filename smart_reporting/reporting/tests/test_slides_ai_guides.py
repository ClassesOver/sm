"""Pinned PPTX guide tool contracts remain separate from native edit authority."""
import ast
import hashlib
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from agno.agent import Agent
from agno.models.response import ModelResponse

from smart_reporting.office import ai_skills
from smart_reporting.report_editor.slides_ai import AgnoSlidesProposalPlanner
from smart_reporting.report_editor.slides_ai_tools import SlidesAIToolkit
from smart_reporting.reporting.tests.pptx_ai_fixture import ScriptedModel
from smart_reporting.reporting.tests.test_slides_ai_tools import call, deck, proposal

GROUPS = ('text', 'element', 'insert', 'table', 'slide', 'deck')


def toolkit(scope='selection'):
    return SlidesAIToolkit(deck=deck(), scope=scope, current_order=[0, 1],
        preview=AsyncMock(return_value={'draftSha256': 'a' * 64}))


@pytest.mark.parametrize('group', GROUPS)
def test_every_source_guide_keeps_pinned_manifest_identity(group):
    name = f'packages/pptx-ops/src/prompts/ops/{group}.md'
    manifest = json.loads((ai_skills.SOURCE_ROOT / 'SOURCE-MANIFEST.json').read_text())
    content = ai_skills.source_slides_guide(group)
    raw = content.encode('utf-8')
    assert hashlib.sha256(raw).hexdigest() == manifest['files'][name]['sha256']
    assert len(raw) == manifest['files'][name]['size']
    assert toolkit().load_guide([group])['output'] == content


def test_guide_join_preserves_order_and_removes_duplicates_without_truncating():
    result = toolkit().load_guide(['deck', 'text', 'deck', 'element', 'insert', 'table', 'slide'])
    assert result['output'] == '\n\n---\n\n'.join(ai_skills.source_slides_guide(g)
        for g in ('deck', 'text', 'element', 'insert', 'table', 'slide'))
    assert result['mutated'] is False
    assert result['summary'].count('deck') == 1
    assert len(result['output']) > 70000
    assert 'nativeAdapter' in result and 'propose_operations' in result['nativeAdapter']


@pytest.mark.parametrize('groups', [[], 'text', None, ['text', 'unknown'], ['../text'],
    ['_format'], ['text', 1], ['TEXT'], ['text ']])
def test_invalid_guide_request_rejects_before_loading_any_file(groups, monkeypatch):
    loads = []
    def capture(name):
        loads.append(name)
        raise AssertionError('Invalid request reached filesystem')
    monkeypatch.setattr(ai_skills, 'source_slides_guide', capture)
    with pytest.raises(ValueError, match='slides_ai_guide_invalid'):
        toolkit().load_guide(groups)
    assert loads == []


def test_source_loader_does_not_allow_paths_or_fabricate_missing_sources(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match='slides_ai_guide_invalid'):
        ai_skills.source_slides_guide('../text')
    monkeypatch.setattr(ai_skills, 'SOURCE_ROOT', tmp_path)
    with pytest.raises(FileNotFoundError):
        ai_skills.source_slides_guide('text')


@pytest.mark.anyio
async def test_loading_reference_docs_does_not_read_slides_or_authorize_a_proposal():
    tools = toolkit()
    before = deepcopy(tools._deck)
    result = tools.load_guide(list(GROUPS))
    assert tools._deck == before and not tools._read and tools.proposal is None
    assert 'px' in result['nativeAdapter'] and 'EMU' in result['nativeAdapter']
    assert 'apply_ops' in result['nativeAdapter'] and 'scope=notes' in result['nativeAdapter']
    with pytest.raises(ValueError, match='read_required'):
        await tools.propose_operations(proposal())
    tools._preview.assert_not_awaited()
    assert '机密' not in json.dumps(result, ensure_ascii=False)


def test_actual_agno_schema_preserves_source_tool_name_and_groups_enum():
    function = toolkit().functions['load_guide']
    function.process_entrypoint()
    schema = function.parameters
    assert schema['required'] == ['groups']
    assert set(schema['properties']) == {'groups'}
    assert schema['properties']['groups']['items']['enum'] == list(GROUPS)


@pytest.mark.anyio
async def test_actual_agno_loads_source_guide_before_authorized_read_and_preview():
    model = ScriptedModel(id='slides-guides', responses=[
        call('load_guide', {'groups': ['text', 'element', 'text']}, 'guide'),
        call('read_slide', {'slide_index': 0}, 'read'),
        call('propose_operations', {'proposal': proposal()}, 'propose'),
        ModelResponse(content='候选已预览，等待采纳。'),
    ])
    preview = AsyncMock(return_value={'draftSha256': 'b' * 64})
    result = await AgnoSlidesProposalPlanner(Agent(model=model)).plan_slides(
        '参考源指南调整标题', deck=deck(), scope='selection', current_order=[0, 1],
        preview=preview, session_id='guides', user_id='u')
    assert result.summary == proposal()['summary']
    preview.assert_awaited_once()
    guide_messages = [m for turn in model.seen for m in turn if m.role == 'tool' and m.tool_name == 'load_guide']
    assert guide_messages
    content = ast.literal_eval(guide_messages[-1].content)
    assert content['output'] == ai_skills.source_slides_guide('text') + '\n\n---\n\n' + ai_skills.source_slides_guide('element')
    assert 'nativeAdapter' in content
    assert '机密' not in str(model.seen)

@pytest.mark.anyio
async def test_source_apply_ops_examples_do_not_bypass_native_schema_after_reading():
    tools = toolkit()
    tools.load_guide(['element', 'slide'])
    tools.read_slide(0)
    with pytest.raises(ValueError):
        await tools.propose_operations({'summary': '按指南删除', 'edits': [], 'order': [0, 1],
            'ops': [{'op': 'deleteElement', 'target': {'slide': 0, 'el': 'title'}}]})
    assert tools.proposal is None
    tools._preview.assert_not_awaited()


@pytest.mark.anyio
async def test_notes_guides_preserve_notes_only_authority_and_native_preview():
    material = deck()
    material['slides'][0].update(notesAuthorized=True, notesEditable=True, notesText='原备注')
    preview = AsyncMock(return_value={'draftSha256': 'c' * 64})
    tools = SlidesAIToolkit(deck=material, scope='notes', current_order=[0, 1], preview=preview)
    result = tools.load_guide(['text', 'element', 'deck'])
    assert 'scope=notes' in result['nativeAdapter'] and not tools._read
    tools.read_slide(0)
    with pytest.raises(ValueError):
        await tools.propose_operations(proposal())
    preview.assert_not_awaited()
    receipt = await tools.propose_operations({'summary': '润色备注', 'edits': [], 'order': [0, 1],
        'notesEdits': [{'slideIndex': 0, 'text': '候选备注'}]})
    assert receipt['requiresAcceptance'] is True
    preview.assert_awaited_once()
