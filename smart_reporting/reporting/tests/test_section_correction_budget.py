"""纠错新增材料必须重新计入证据投影预算，不能复用首轮已占满的视图。"""

import copy
import hashlib
import json

import pytest

from smart_reporting.reporting.model_policy import ThinkingRequest
from smart_reporting.reporting.tests.test_content_review import _metric
from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _context,
    _plan_claim,
    _revenue_work_item,
)
from smart_reporting.reporting.workflow.runtime import sections
from smart_reporting.reporting.workflow.runtime.phase_models import (
    RenderSectionPlan,
    SectionContent,
    SectionEvidenceBundle,
    SectionEvidenceFile,
    SectionSemanticReview,
)
from smart_reporting.task_execution import TaskExecutionScope


@pytest.mark.anyio
async def test_whole_section_correction_reprojects_evidence_after_adding_feedback(monkeypatch):
    budget = 8_000
    requests = []
    first_text = '另见 analysis_001 的明细。' * 300
    monkeypatch.setattr(sections, '_STYLE_CORRECTION_THRESHOLD', 1)
    monkeypatch.setattr(sections, '_section_block_input_token_budget', lambda *_: budget)
    def count(payload):
        return sections._estimated_section_tokens(sections._json_text(payload))
    monkeypatch.setattr(sections, '_section_request_tokens', lambda _agent, payload, *_: count(payload))
    monkeypatch.setattr(sections, '_section_block_evidence_token_budget',
                        lambda _agent, payload, **_: budget - count(payload) - 400)

    async def stage(_agent, _schema, phase, payload, **_kwargs):
        if phase == 'semantics':
            return SectionSemanticReview(interpretations=())
        requests.append(copy.deepcopy(payload))
        assert count(payload) <= budget
        return SectionContent.model_validate({'blocks': [{
            'blockId': 'block_1',
            'markdown': first_text if len(requests) == 1 else '收入结构保持稳定。',
        }]})

    monkeypatch.setattr(sections, '_run_section_stage', stage)
    work = _revenue_work_item()
    source = chr(10).join(f'收入明细第{i}项：保留来源材料供运营分析使用。' for i in range(3000))
    evidence = SectionEvidenceBundle(sectionCode='section_001', factSummaries=(), files=(
        SectionEvidenceFile(identity=work.evidence[0].evidence_files[0].model_copy(update={
            'size': len(source.encode()), 'sha256': hashlib.sha256(source.encode()).hexdigest(),
        }), content=source),
    ))
    plan = RenderSectionPlan.model_validate({'sectionCode': 'section_001',
        'blocks': [{'blockId': 'block_1', 'objective': '收入', 'claimIds': ['claim_1']}],
        'claims': [_plan_claim('claim_1')]})
    result = await sections._generate_whole_section_content(
        object(), {}, evidence, work, plan,
        number_contents=(json.dumps({'analysisId': 'analysis_001', 'metrics': [_metric()]}),),
        scope=TaskExecutionScope('task', 'user', 'thread', 'sandbox', 'section'),
        run_context=_context(), thinking_request=ThinkingRequest(
            operation='section_generation', complexity='standard'),
    )
    assert len(requests) == 2
    assert result.blocks[0].markdown == '收入结构保持稳定。'
    first, corrected = requests
    assert corrected['correction']['previousOutput']['blocks'][0]['markdown'] == first_text
    assert corrected['evidence']['files'][0]['identity'] == first['evidence']['files'][0]['identity']
    assert len(corrected['evidence']['files'][0]['content']) < len(first['evidence']['files'][0]['content'])
    assert corrected['frozenNumbers'] == first['frozenNumbers']
