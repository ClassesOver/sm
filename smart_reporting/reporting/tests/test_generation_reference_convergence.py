"""纠错评分、最终正文与编辑器引用必须使用同一份规范化候选。"""

import json

import pytest

from smart_reporting.reporting.model_policy import ThinkingRequest
from smart_reporting.reporting.tests.test_content_review import _metric
from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _context,
    _plan_claim,
    _revenue_work_item,
)
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import claim_status
from smart_reporting.reporting.workflow.runtime import sections
from smart_reporting.reporting.workflow.runtime.phase_models import (
    RenderSectionPlan,
    SectionBlockContent,
    SectionContent,
    SectionEvidenceBundle,
    SectionEvidenceFile,
    SectionPlanOutput,
)
from smart_reporting.task_execution import TaskExecutionScope

RAW_RETARGETABLE = '2025年2月收入{{value:fact-aaaaaaaaaaaaaaaa:total:人次}}。'
EXPECTED_REFERENCE = '{{value:fact-aaaaaaaaaaaaaaaa:periodValues.1:人次}}'


async def _generate(monkeypatch, mode, outputs):
    work_item = _revenue_work_item()
    metric = {**_metric(values=(10, 20)), 'displayName': '收入'}
    source = json.dumps({'analysisId': 'analysis_001', 'metrics': [metric]})
    evidence = SectionEvidenceBundle(sectionCode='section_001', factSummaries=(), files=(SectionEvidenceFile(
        identity=work_item.evidence[0].evidence_files[0], content=source,
    ),))
    plan_payload = {
        'sectionCode': 'section_001',
        'blocks': [{'blockId': 'block_001', 'objective': '收入', 'claimIds': ['claim_001']}],
        'claims': [_plan_claim('claim_001', factIds=['fact-aaaaaaaaaaaaaaaa'])],
    }
    calls = []

    async def fake_stage(_agent, _schema, stage, payload, **_kwargs):
        if stage == 'plan':
            return SectionPlanOutput.model_validate({'kind': 'render', **plan_payload})
        text = outputs[min(len(calls), len(outputs) - 1)]
        calls.append(payload)
        if mode == 'whole':
            return SectionContent.model_validate({'blocks': [{'blockId': 'block_001', 'markdown': text}]})
        return SectionBlockContent(markdown=text)

    monkeypatch.setattr(sections, '_run_section_stage', fake_stage)
    notices = {}
    options = {
        'scope': TaskExecutionScope('task-1', 'user-1', 'thread-1', 'sandbox-1', 'section'),
        'run_context': _context(),
        'thinking_request': ThinkingRequest(operation='section_generation', complexity='standard'),
        'review_notices': notices,
    }
    if mode == 'whole':
        result = await sections._generate_whole_section_content(
            object(), {}, evidence, work_item, RenderSectionPlan.model_validate(plan_payload), **options,
        )
    else:
        result = await sections._generate_section_in_blocks(object(), {}, evidence, work_item, **options)
    return result.blocks[0], notices.get('block_001', []), calls, source


def _assert_editor_binding_is_current(block, source):
    assert block.markdown == '2025年2月收入20人次。'
    assert not block.review_notices
    assert len(block.number_references) == 1
    reference = block.number_references[0]
    assert reference.token == EXPECTED_REFERENCE
    selected = resolve_number_reference(reference.token, [source])
    assert selected is not None
    markdown = anchor_bound_numbers(block.markdown, block.number_references)
    assert claim_status(
        markdown, reference.claim_id, selected['value'],
        expected_unit=selected['unit'], expected_periods=selected['periods'],
        expected_period_roles=selected['period_roles'], expected_scope=selected['scope'],
        expected_reference=selected,
    ) == {'status': 'valid', 'warnings': []}


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks'])
async def test_unique_reference_alignment_converges_without_an_extra_model_call(monkeypatch, mode):
    block, notices, calls, source = await _generate(monkeypatch, mode, [RAW_RETARGETABLE])
    _assert_editor_binding_is_current(block, source)
    assert len(calls) == 1
    assert notices == []


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks'])
async def test_correction_is_scored_after_alignment_and_does_not_restore_unknown_number(monkeypatch, mode):
    block, notices, calls, source = await _generate(monkeypatch, mode, ['收入999人次。', RAW_RETARGETABLE])
    _assert_editor_binding_is_current(block, source)
    assert len(calls) == 2
    assert notices == []
