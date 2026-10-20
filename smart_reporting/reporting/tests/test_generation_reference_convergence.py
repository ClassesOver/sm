"""纠错评分、最终正文与编辑器引用必须使用同一份规范化候选。"""

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
from smart_reporting.reporting.trace import semantic_bindings
from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id
from smart_reporting.reporting.trace.semantic_bindings import (
    anchor_bound_numbers,
    resolve_number_reference,
)
from smart_reporting.reporting.trace.subject_builder import claim_status
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
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


def _source_file(content, *, path='evidence/table.json', **overrides):
    raw = content.encode('utf-8')
    identity = FileIdentity(
        path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
    ).model_copy(update=overrides)
    return SectionEvidenceFile(identity=identity, content=content)


async def _generate(monkeypatch, mode, outputs, *, project=False):
    work_item = _revenue_work_item()
    metric = {**_metric(values=(10, 20)), 'displayName': '收入'}
    source = json.dumps({'analysisId': 'analysis_001', 'metrics': [metric]}, ensure_ascii=False)
    evidence_file = _source_file(source, path=work_item.evidence[0].evidence_files[0].path)
    evidence = SectionEvidenceBundle(
        sectionCode='section_001', factSummaries=(), files=(evidence_file,),
    )
    if project:
        work_item = work_item.model_copy(update={'finding_ids': ('finding-test',)})

        def project_evidence(files, _work_item):
            # Projection deliberately changes bytes without changing the frozen identity.
            return (files[0].model_copy(update={'content': source + ' '}),), {
                'fact-aaaaaaaaaaaaaaaa',
            }, ()

        monkeypatch.setattr(sections, 'finding_evidence_view', project_evidence)
    plan_payload = {
        'sectionCode': 'section_001',
        'blocks': [{'blockId': 'block_001', 'objective': '收入', 'claimIds': ['claim_001']}],
        'claims': [_plan_claim('claim_001', factIds=['fact-aaaaaaaaaaaaaaaa'])],
    }
    calls = []
    bound_source_maps = []
    render_bound_numbers = semantic_bindings.render_bound_numbers

    def capture_bound_numbers(*args, **kwargs):
        bound_source_maps.append(kwargs.get('table_sources'))
        return render_bound_numbers(*args, **kwargs)

    monkeypatch.setattr(semantic_bindings, 'render_bound_numbers', capture_bound_numbers)

    async def fake_stage(_agent, _schema, stage, payload, **_kwargs):
        if stage == 'plan':
            return SectionPlanOutput.model_validate({'kind': 'render', **plan_payload})
        text = outputs[min(len(calls), len(outputs) - 1)]
        calls.append(payload)
        if mode in {'whole', 'whole_entry'}:
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
        result = await sections._generate_section_in_blocks(
            object(), {}, evidence, work_item, whole_section=mode == 'whole_entry', **options,
        )
    return result.blocks[0], notices.get('block_001', []), calls, source, bound_source_maps


def _assert_original_source_maps(source_maps, source):
    path = _revenue_work_item().evidence[0].evidence_files[0].path
    assert source_maps
    assert all(mapping == {derive_resource_id(path): source.encode('utf-8')} for mapping in source_maps)


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
    block, notices, calls, source, source_maps = await _generate(monkeypatch, mode, [RAW_RETARGETABLE])
    _assert_original_source_maps(source_maps, source)
    _assert_editor_binding_is_current(block, source)
    assert len(calls) == 1
    assert notices == []


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole', 'blocks'])
async def test_correction_is_scored_after_alignment_and_does_not_restore_unknown_number(monkeypatch, mode):
    block, notices, calls, source, source_maps = await _generate(monkeypatch, mode, ['收入999人次。', RAW_RETARGETABLE])
    _assert_original_source_maps(source_maps, source)
    _assert_editor_binding_is_current(block, source)
    assert len(calls) == 2
    assert notices == []


@pytest.mark.anyio
@pytest.mark.parametrize('mode', ['whole_entry', 'blocks'])
async def test_projection_keeps_original_verified_bytes_for_number_rendering(monkeypatch, mode):
    block, notices, calls, source, source_maps = await _generate(
        monkeypatch, mode, [RAW_RETARGETABLE], project=True,
    )
    _assert_original_source_maps(source_maps, source)
    _assert_editor_binding_is_current(block, source)
    assert len(calls) == 1
    assert notices == []


@pytest.mark.parametrize('fault', ['size', 'hash', 'unicode', 'conflict'])
@pytest.mark.parametrize('reverse', [False, True])
def test_verified_table_sources_rejects_entire_conflicting_group(fault, reverse):
    good = _source_file('{"收入": 20}')
    other = _source_file('{"收入": 40}', path='evidence/other.json')
    if fault == 'size':
        bad = good.model_copy(update={'identity': good.identity.model_copy(update={'size': 1})})
    elif fault == 'hash':
        bad = good.model_copy(update={'identity': good.identity.model_copy(update={'sha256': 'b' * 64})})
    elif fault == 'unicode':
        bad = good.model_copy(update={'content': '\ud800'})
    else:
        bad = _source_file('{"收入": 30}')
    files = (good, bad, good, other)
    if reverse:
        files = tuple(reversed(files))
    assert sections._verified_table_sources(files) == {
        derive_resource_id(other.identity.path): other.content.encode('utf-8'),
    }
