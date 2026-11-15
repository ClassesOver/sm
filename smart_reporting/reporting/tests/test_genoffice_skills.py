"""Complete fixed-source skills and real Agno progressive loading."""
from __future__ import annotations

import hashlib
import json
from importlib import import_module
from pathlib import Path

import pytest
from agno.agent import Agent
from agno.models.response import ModelResponse
from agno.skills import LocalSkills, Skills

SOURCE_ROOT = Path(__file__).resolve().parents[2] / 'office' / 'vendor' / 'genoffice'
EXPECTED_SKILLS = set('''brand-copy budget-planner business-plan business-report campaign-planner
contract-drafter course-slides data-analyst data-cleaning deep-research email-drafter
executive-deck expense-report financial-statement-analysis genoffice interview-coach
invoice-tax-checklist job-description kpi-dashboard labor-contract lesson-plan
meeting-minutes nda-drafter okr-planner onboarding-plan performance-review personal-finance
policy-compliance product-launch proposal-writer quiz-maker resume-polisher sales-forecast
seo-content slide-planner social-media sop-writer study-plan survey-analyst swot-strategy
terms-of-service thesis-advisor weekly-report'''.split())


def test_complete_snapshot_keeps_fixed_source_bytes_and_all_skills():
    manifest = json.loads((SOURCE_ROOT / 'SOURCE-MANIFEST.json').read_text())
    assert manifest['commit'] == 'f8c17004fb730df11f0f743164ffd8b4281bb38c'
    assert len(manifest['files']) == 213
    for name, identity in manifest['files'].items():
        raw = (SOURCE_ROOT / name).read_bytes()
        assert len(raw) == identity['size'], name
        assert hashlib.sha256(raw).hexdigest() == identity['sha256'], name
        assert hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest() == identity['gitBlobSha1'], name
    packages = {Path(name).parent.name for name in manifest['files'] if name.endswith('/SKILL.md')}
    assert packages == EXPECTED_SKILLS
    assert len([p for p in manifest['files'] if p.startswith('skills/recommended/locales/')]) == 21
    assert 'LICENSE' in manifest['files']
    assert all(f'apps/{app}/src/renderer/ai/{name}' in manifest['files'] for app, name in [
        ('docs', 'docs-skill.ts'), ('sheets', 'workbook-skill.ts'), ('slides', 'slides-skill.ts'),
        ('pdf', 'pdf-skill.ts'), ('html', 'html-skill.ts'), ('markdown', 'markdown-skill.ts'),
    ])


def test_native_agno_loads_every_original_skill_without_scripts_or_rewriting():
    module = import_module('smart_reporting.office.ai_skills')
    skills = module.office_skills()
    assert isinstance(skills, Skills)
    assert set(skills.get_skill_names()) == EXPECTED_SKILLS
    for skill in skills.get_all_skills():
        raw = (Path(skill.source_path) / 'SKILL.md').read_text()
        assert skill.instructions and skill.instructions in raw
        assert skill.description and skill.description in raw
        assert not skill.scripts
    assert 'Follow their steps' not in skills.get_skill('data-analyst').instructions
    prompt = skills.get_system_prompt_snippet()
    assert '<name>data-analyst</name>' in prompt
    assert 'Sheet 1 holds the cleaned detail' not in prompt


def test_skill_attachment_preserves_document_tools_and_callable_instructions(tmp_path):
    module = import_module('smart_reporting.office.ai_skills')
    custom = tmp_path / 'custom'
    custom.mkdir()
    (custom / 'SKILL.md').write_text('---\nname: custom\ndescription: Tenant workflow\n---\nKeep tenant rules.\n')

    def document_tool():
        return {'frozen': True}

    def instructions():
        return ['Original authorization rules']

    agent = Agent(tools=[document_tool], instructions=instructions,
        additional_context='Existing context', skills=Skills(loaders=[LocalSkills(str(custom))]))
    original_skills = agent.skills
    module.attach_office_skills(agent)
    module.attach_office_skills(agent)
    assert agent.tools == [document_tool]
    assert agent.instructions is instructions
    assert agent.additional_context.startswith('Existing context')
    assert agent.additional_context.count('GenOffice native host') == 1
    assert set(agent.skills.get_skill_names()) == EXPECTED_SKILLS | {'custom'}
    assert original_skills.get_skill_names() == ['custom']
    assert agent.skills.get_skill('custom').instructions == 'Keep tenant rules.'


@pytest.mark.anyio
async def test_actual_agno_reader_loads_source_skill_as_tool_before_reading_file():
    from smart_reporting.report_editor.native_workbook_read_ai import (
        AgnoNativeWorkbookReadPlanner,
        NativeWorkbookReadTools,
    )
    from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel

    def call(name, arguments, identity):
        return ModelResponse(tool_calls=[{'id': identity, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(arguments)}}])

    class SkillsModel(ScriptedModel):
        def invoke(self, *args, **kwargs):
            messages = kwargs.get('messages', args[0] if args else [])
            assert any('GenOffice native host' in str(message.content)
                       for message in messages if message.role == 'system')
            return super().invoke(*args, **kwargs)

    model = SkillsModel(id='copied-skills', expected_tool_text='Sheet 1 holds the cleaned detail', responses=[
        call('get_skill_instructions', {'skill_name': 'data-analyst'}, 'skill'),
        call('read_cells', {'addresses': ['A1'], 'sheetId': 'Sheet'}, 'read'),
        ModelResponse(content=json.dumps({'answer': '收入42', 'citations': ['Sheet!A1']})),
    ])
    reader = NativeWorkbookReadTools({'sheets': [{'name': 'Sheet', 'cells': {'A1': {'value': 42}}}]})
    result = await AgnoNativeWorkbookReadPlanner(model)(reader=reader, action='ask',
        instruction='使用data-analyst技能分析收入', session_id='skills-read', user_id='u')
    assert result['answer'] == '收入42'
    assert result['citations'] == [{'sheetName': 'Sheet', 'address': 'A1', 'label': 'Sheet!A1'}]
    assert result['coverage']['fullyReadBlockIds'] == ['Sheet!A1']
    assert 'operations' not in result


GUIDES = ['writing', 'formatting', 'layout', 'structure', 'charts', 'data',
          'financial-formatting', 'data-attribution', 'table', 'pivot', 'shape-image']


@pytest.mark.parametrize('name', GUIDES)
def test_every_source_guide_is_returned_verbatim_with_separate_native_adapter_notes(name):
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet', 'cells': {}}]},
        scope='workbook', selection={}, preview=None)
    source = (SOURCE_ROOT / 'apps/sheets/src/renderer/ai/prompts/guides' / f'{name}.md').read_text()
    result = tools.load_guide([name])
    assert result[name].startswith(source)
    assert '\n## Native Agno adapter\n' in result[name]
    assert '预览' in result[name] and '显式采纳' in result[name]
    if name == 'structure':
        assert 'applyRowColumnOps' in result[name]
    if name == 'charts':
        assert 'applyChartSource' in result[name]


@pytest.mark.parametrize('names', [[], ['writing', '../secrets'], ['formatting', 'unknown']])
def test_unknown_or_empty_guide_request_fails_atomically(names):
    from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit

    tools = WorkbookAIToolkit(model={'sheets': [{'name': 'Sheet', 'cells': {}}]},
        scope='workbook', selection={}, preview=None)
    with pytest.raises(ValueError, match='workbook_ai_guide_invalid'):
        tools.load_guide(names)


@pytest.mark.parametrize('relative', ['skills/genoffice', 'skills/recommended'])
def test_partial_existing_builtin_loader_still_receives_every_skill(relative):
    module = import_module('smart_reporting.office.ai_skills')
    existing = Skills(loaders=[LocalSkills(str(SOURCE_ROOT / relative), validate=False)])
    before = set(existing.get_skill_names())
    agent = Agent(skills=existing)
    module.attach_office_skills(agent)
    assert set(agent.skills.get_skill_names()) == EXPECTED_SKILLS
    assert set(existing.get_skill_names()) == before
