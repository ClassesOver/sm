"""章节预检必须与实际请求的输出预留一致，压缩不得丢失语义。"""

import json

from agno.agent import Agent
from agno.run import RunContext

from smart_reporting.reporting.agent import ReportingPhaseOpenAIChat
from smart_reporting.reporting.workflow.runtime import sections
from smart_reporting.reporting.workflow.runtime.phase_models import SectionContent


def test_section_budget_matches_stage_request_without_mutating_template():
    model = ReportingPhaseOpenAIChat(id='deepseek-v4.1-flash', api_key='test', max_tokens=65536)
    model._task_execution_input_token_budget = 458752
    agent = Agent(model=model)
    stage = sections._section_stage_agent(agent, SectionContent, 'content')
    assert stage.model.max_tokens == 32768
    assert sections._section_block_input_token_budget(agent, RunContext(run_id='r', session_id='s')) == 229376
    assert model.max_tokens == 65536
    model._task_execution_input_token_budget = 100000
    assert sections._section_block_input_token_budget(agent, RunContext(run_id='r', session_id='s')) == 100000


def test_semantic_payload_compression_preserves_complete_context_and_sources():
    periods = [f'2025-{month:02d}' for month in range(1, 10)]
    payload = {
        'contexts': {'chapter': '本章共同口径。不得借用另一院区；以下除外。' * 50},
        'references': [{'claimId': f'c{i}', 'periods': periods,
                        'selector': {'factId': 'fact-aaaaaaaaaaaaaaaa', 'path': 'periodValues.0'}}
                       for i in range(10)],
        'quantitySources': [{'sourceId': f's{i}', 'periods': periods} for i in range(10)],
    }
    compact = sections._semantic_review_payload(payload)

    def expand(value):
        if isinstance(value, dict):
            if set(value) == {'$ref'}:
                return expand(compact['$defs'][value['$ref'].split('/')[-1]])
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    assert {key: expand(compact[key]) for key in payload} == payload
    assert len(json.dumps(compact, ensure_ascii=False)) < len(json.dumps(payload, ensure_ascii=False))
