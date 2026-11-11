"""工作簿自由摘要必须登记原文，计算表不能替解释背书。"""

from types import SimpleNamespace

import pytest

from smart_reporting.reporting.tests.test_claim_knowledge_support import candidate
from smart_reporting.reporting.tests.test_narrative_knowledge_support import knowledge_context
from smart_reporting.reporting.trace.native_claims import (
    native_claim_presentations,
    present_native_summary,
)
from smart_reporting.reporting.trace.registered_claims import registered_narrative_support
from smart_reporting.reporting.trace.semantic_bindings import anchor_bound_numbers
from smart_reporting.reporting.trace.subject_builder import build_claim_subject_bindings
from smart_reporting.reporting.workflow.analysis_summaries import build_analysis_summary_section
from smart_reporting.reporting.workflow.runtime import business_evidence, sections
from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview


@pytest.mark.anyio
@pytest.mark.parametrize('relation,current,expected', [
    ('supports', True, 'supported'), ('contradicts', True, 'conflicted'),
    ('irrelevant', True, 'unverified'), ('supports', False, 'unverified'),
    ('missing', True, 'unverified'),
])
async def test_workbook_summary_uses_actual_review_and_current_original(monkeypatch, relation, current, expected):
    evidence = candidate()
    text = '建议按原始金额累计预算，避免把期间平均当作合计。'
    view = SimpleNamespace(basis_id=evidence.reference.basis_id, report_revision='initial',
        request=SimpleNamespace(period=evidence.period))
    section = SimpleNamespace(code='section_001', title='预算管理', analysis_ids=('analysis_001',))
    calls = []

    async def knowledge(runtime, context, **kwargs):
        assert kwargs['report_revision'] == 'initial' and kwargs['section_code'] == 'section_001'
        return knowledge_context(evidence)

    async def review(agent, schema, stage, payload, **kwargs):
        reference, = payload['references']
        calls.append(reference['claimId'])
        assert payload['knowledgeEvidence'][0]['quote'] == evidence.hit.quote
        assert text in next(iter(payload['contexts'].values()))
        return SectionSemanticReview.model_validate({'interpretations': [] if relation == 'missing' else [{
            'claimId': reference['claimId'], 'claimKind': 'recommendation', 'kindEvidence': ['建议'],
            'knowledgeRelations': [{'evidenceId': evidence.reference.evidence_id,
                'relationship': relation, 'explanationType': 'recommendation',
                'claimEvidence': ['按原始金额累计预算'], 'sourceEvidence': ['预算按原始金额累计']}]}]})

    monkeypatch.setattr(business_evidence, 'business_knowledge_context', knowledge)
    monkeypatch.setattr(sections, '_run_section_stage', review)
    runtime = SimpleNamespace(section_generator=object(), _scope=lambda _: {
        'userId': 'tester', 'threadId': 'workspace'})
    artifact = await build_analysis_summary_section(runtime, SimpleNamespace(), section=section,
        evidence=(SimpleNamespace(analysis_id='analysis_001', summary=text),), view=view)
    assert len(calls) == 1
    assert artifact.knowledge_receipt_ids == (evidence.reference.receipt_id,)
    block, = artifact.blocks
    assert block.markdown == text and not block.number_references
    ref, = block.narrative_references
    assert ref.analysis_id == 'analysis_001'
    subject, = build_claim_subject_bindings((artifact,), {}, {})
    markdown = anchor_bound_numbers(block.markdown, block.narrative_references)
    support, issues = registered_narrative_support(subject, markdown, basis_id=view.basis_id,
        knowledge_evidence={evidence.reference.evidence_id: evidence} if current else {})
    assert support.support_status == expected
    index = SimpleNamespace(subject_bindings=(subject,))
    presentations = native_claim_presentations(index, markdown, (support,))
    shown = present_native_summary(text, presentations, section_ids=('section_001',), analysis_ids=('analysis_001',))
    assert shown['support']['subjectId'] == subject.subject_id
    assert shown['support']['supportStatus'] == expected
    foreign = present_native_summary(text, presentations, section_ids=('section_001',), analysis_ids=('analysis_002',))
    assert 'subjectId' not in foreign['support']


@pytest.mark.anyio
async def test_workbook_review_outage_keeps_exact_registered_summary(monkeypatch):
    evidence = candidate()
    async def unavailable(*args, **kwargs):
        raise OSError('review unavailable')
    async def knowledge(*args, **kwargs):
        return knowledge_context(evidence)
    monkeypatch.setattr(business_evidence, 'business_knowledge_context', knowledge)
    monkeypatch.setattr(sections, '_run_section_stage', unavailable)
    runtime = SimpleNamespace(section_generator=object(), _scope=lambda _: {'userId': 'tester', 'threadId': 'workspace'})
    result = await build_analysis_summary_section(runtime, SimpleNamespace(),
        section=SimpleNamespace(code='section_001', title='预算', analysis_ids=('analysis_001',)),
        evidence=(SimpleNamespace(analysis_id='analysis_001', summary='已计算不代表经营原因已证实。'),),
        view=SimpleNamespace(basis_id=evidence.reference.basis_id, report_revision='initial',
            request=SimpleNamespace(period=evidence.period)))
    block, = result.blocks
    assert block.markdown == '已计算不代表经营原因已证实。'
    assert block.narrative_references and block.narrative_references[0].semantic_receipt is None
    assert result.warnings


@pytest.mark.anyio
async def test_nonstatement_summary_is_preserved_without_blocking_delivery(monkeypatch):
    evidence = candidate()
    async def knowledge(*args, **kwargs):
        return knowledge_context(evidence)
    monkeypatch.setattr(business_evidence, 'business_knowledge_context', knowledge)
    artifact = await build_analysis_summary_section(
        SimpleNamespace(_scope=lambda _: {'userId': 'tester', 'threadId': 'workspace'}), SimpleNamespace(),
        section=SimpleNamespace(code='section_001', title='预算', analysis_ids=('analysis_001',)),
        evidence=(SimpleNamespace(analysis_id='analysis_001', summary='### 预算结果'),),
        view=SimpleNamespace(basis_id=evidence.reference.basis_id, report_revision='initial',
            request=SimpleNamespace(period=evidence.period)))
    assert artifact.blocks[0].markdown == '### 预算结果'
    assert not artifact.blocks[0].narrative_references
    assert artifact.warnings


def test_checkpoint_summary_identity_survives_stale_writes_and_rejects_replacement():
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.tests.test_dynamic_checkpoint import _coverage
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity, ReportingCheckpoint
    from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin

    empty = ReportingCheckpoint(revision=1, phase='analysis', outlineHash='a' * 64, profileCoverage=_coverage())
    file = FileIdentity(path='workbook/summary.json', size=10, sha256='b' * 64)
    frozen = empty.model_copy(update={'workbook_summary_files': (file,), 'files': (file,)})
    assert RuntimeAnalysisMixin._merge_reporting_checkpoints(frozen, empty).workbook_summary_files == (file,)
    changed = file.model_copy(update={'sha256': 'c' * 64})
    with pytest.raises(ReportingError, match='摘要身份不一致'):
        RuntimeAnalysisMixin._merge_reporting_checkpoints(frozen,
            empty.model_copy(update={'workbook_summary_files': (changed,), 'files': (changed,)}))
    with pytest.raises(ReportingError, match='覆盖'):
        RuntimeAnalysisMixin._merge_reporting_checkpoints(frozen, empty.model_copy(update={'files': (changed,)}))


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['statement', 'analysis', 'period', 'omitted', 'section', 'basis'])
async def test_summary_artifact_cannot_rebind_registered_statement(monkeypatch, fault):
    from pydantic import ValidationError

    from smart_reporting.reporting.workflow.analysis_summaries import AnalysisSummarySection

    evidence = candidate()
    async def knowledge(*args, **kwargs):
        return knowledge_context(evidence)
    monkeypatch.setattr(business_evidence, 'business_knowledge_context', knowledge)
    artifact = await build_analysis_summary_section(
        SimpleNamespace(_scope=lambda _: {'userId': 'tester', 'threadId': 'workspace'}), SimpleNamespace(),
        section=SimpleNamespace(code='section_001', title='预算', analysis_ids=('analysis_001',)),
        evidence=(SimpleNamespace(analysis_id='analysis_001', summary='建议核对累计规则。'),),
        view=SimpleNamespace(basis_id=evidence.reference.basis_id, report_revision='initial',
            request=SimpleNamespace(period=evidence.period)))
    payload = artifact.model_dump(mode='json', by_alias=True)
    reference = payload['blocks'][0]['narrativeReferences'][0]
    if fault == 'statement':
        payload['blocks'][0]['markdown'] = '建议忽略累计规则。'
    elif fault == 'analysis':
        reference['analysisId'] = 'analysis_002'
    elif fault == 'period':
        reference['period'] = {'start': '2025-11-01', 'end': '2025-12-01'}
    elif fault == 'omitted':
        payload['blocks'][0]['narrativeReferences'] = []
    elif fault == 'section':
        payload['sectionCode'] = 'section_002'
    else:
        payload['basisId'] = 'another-basis'
    with pytest.raises(ValidationError):
        AnalysisSummarySection.model_validate(payload)


@pytest.mark.anyio
async def test_summary_freeze_restores_registered_bytes_and_stops_unknown_writes(monkeypatch):
    import hashlib

    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.tests.test_dynamic_checkpoint import _coverage
    from smart_reporting.reporting.workflow import workbook_claims
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity, ReportingCheckpoint

    evidence = candidate()
    view = SimpleNamespace(basis_id=evidence.reference.basis_id, report_revision='initial',
        request=SimpleNamespace(period=evidence.period))
    section = SimpleNamespace(code='section_001', title='预算', analysis_ids=('analysis_001',))
    outline = SimpleNamespace(sections=(section,))
    checkpoint = ReportingCheckpoint(revision=1, phase='analysis', outlineHash='a' * 64, profileCoverage=_coverage())
    checkpoint = checkpoint.model_copy(update={'evidence_manifest': SimpleNamespace(evidence=(
        SimpleNamespace(analysis_id='analysis_001', summary='\n建议核对累计规则。\n'),))})
    stored, registered, calls = {}, {}, []

    async def knowledge(*args, **kwargs):
        return knowledge_context(evidence)

    async def hashes(thread, paths):
        return [{'missing': path not in stored} for path in paths]

    async def write(thread, path, content):
        assert path not in stored
        stored[path] = content
        calls.append(path)
        return FileIdentity(path=path, size=len(content), sha256=hashlib.sha256(content).hexdigest())

    async def command(context, value, **kwargs):
        file = value.payload['artifact']
        registered[file['path']] = file

    async def read(thread, file, model):
        raw = stored[file.path]
        assert len(raw) == file.size and hashlib.sha256(raw).hexdigest() == file.sha256
        return model.model_validate_json(raw)

    async def persist(context, value, **kwargs):
        return value

    async def durable(run_id):
        return SimpleNamespace(payload={'artifacts': list(registered.values())})

    monkeypatch.setattr(business_evidence, 'business_knowledge_context', knowledge)
    runtime = SimpleNamespace(_scope=lambda _: {'userId': 'tester', 'threadId': 'workspace'},
        workspace_service=SimpleNamespace(abatch_hash_files=hashes), state_repository=SimpleNamespace(get=durable),
        _write_immutable_artifact=write, _apply_durable_command=command, _read_identity_model=read,
        _persist_reporting_checkpoint=persist,
        _update_reporting_checkpoint=lambda value, **updates: value.model_copy(update=updates),
        _merge_checkpoint_files=lambda current, *files: (*current, *files))
    context = SimpleNamespace(run_id='first-report')
    checkpoint, summaries = await workbook_claims.freeze_workbook_summary_sections(runtime, context,
        checkpoint=checkpoint, outline=outline, root='workbook/revision-1', view=view)
    assert len(summaries) == len(checkpoint.workbook_summary_files) == len(registered) == 1
    restored, same = await workbook_claims.freeze_workbook_summary_sections(runtime, context,
        checkpoint=checkpoint, outline=outline, root='workbook/revision-1', view=view)
    assert same == summaries and restored == checkpoint and len(calls) == 1
    empty = checkpoint.model_copy(update={'workbook_summary_files': ()})
    with pytest.raises(ReportingError, match='禁止自动重写'):
        await workbook_claims.freeze_workbook_summary_sections(runtime, context,
            checkpoint=empty, outline=outline, root='workbook/revision-1', view=view)
    registered.clear()
    with pytest.raises(ReportingError, match='未登记'):
        await workbook_claims.freeze_workbook_summary_sections(runtime, context,
            checkpoint=checkpoint, outline=outline, root='workbook/revision-1', view=view)
    assert len(calls) == 1


@pytest.mark.parametrize('count', [1, 200])
def test_server_summary_blocks_do_not_collide_with_or_consume_model_block_budget(count):
    from pydantic import ValidationError

    from smart_reporting.reporting.delivery.draft_v1 import (
        ReportDraft,
        ReportDraftBlock,
        ReportDraftSection,
        ReportSectionDefinition,
        assemble_report_markdown,
    )
    from smart_reporting.reporting.trace.narrative_claims import discover_narrative_references

    evidence = candidate()
    body = ReportDraftSection(sectionCode='section_001', blocks=(
        ReportDraftBlock(blockId='analysis_001', markdown='已冻结的原正文。'),))
    summaries = []
    for index in range(count):
        block = ReportDraftBlock(blockId=f'analysis_{index + 1:03d}', markdown=f'独立的摘要说明{index}。')
        summaries.append(block.model_copy(update={'narrative_references': discover_narrative_references(block,
            section_code='section_001', basis_id=evidence.reference.basis_id, period=evidence.period)}))
    summary = ReportDraftSection(sectionCode=body.section_code, blocks=tuple(summaries))
    with pytest.raises(ValidationError):
        ReportDraftSection(sectionCode=body.section_code, blocks=(*body.blocks, *summary.blocks))
    draft = ReportDraft(sections=(body,))
    before = draft.model_dump(mode='json')
    rendered = assemble_report_markdown(draft, expected_title='工作簿来源', markdown_path='report.md',
        sections=(ReportSectionDefinition(code='section_001', sectionNumber='1', title='预算',
            analysisIds=tuple(block.block_id for block in summaries)),), citation_ids=(),
        server_narrative_sections=(summary,))
    assert draft.model_dump(mode='json') == before
    assert rendered.markdown.count('已冻结的原正文。') == 1
    for block in summary.blocks:
        assert rendered.markdown.count(block.markdown) == 1
        for reference in block.narrative_references:
            assert rendered.markdown.count(f'[[claim:{reference.claim_id}]]') == 1


@pytest.mark.parametrize('valid', [True, False])
def test_summary_claim_collision_uses_current_projection_without_rewriting_frozen_receipt(valid):
    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.trace.claim_semantics import (
        freeze_interpretation,
        semantic_receipt_status,
    )
    from smart_reporting.reporting.trace.narrative_claims import discover_narrative_references
    from smart_reporting.reporting.trace.semantic_bindings import statement_fingerprint
    from smart_reporting.reporting.workflow import workbook_claims

    evidence = candidate()
    block = ReportDraftBlock(blockId='analysis_001', markdown='建议核对累计规则。')
    reference, = discover_narrative_references(block, section_code='section_001',
        basis_id=evidence.reference.basis_id, period=evidence.period)
    marked = anchor_bound_numbers(block.markdown, (reference,))
    receipt = freeze_interpretation(marked, reference.claim_id, {'claimId': reference.claim_id,
        'claimKind': 'recommendation', 'kindEvidence': ['建议']}, reference={'entry': {'basisId': evidence.reference.basis_id}})
    if not valid:
        receipt = receipt.model_copy(update={'context_sha256': 'f' * 64})
    reference = reference.model_copy(update={'analysis_id': 'analysis_001', 'semantic_receipt': receipt,
        'statement_sha256': statement_fingerprint(marked, reference.claim_id)})
    block = block.model_copy(update={'narrative_references': (reference,)})
    summary = workbook_claims.AnalysisSummarySection(basisId=evidence.reference.basis_id,
        reportRevision='initial', period=evidence.period, sectionCode='section_001', blocks=(block,))
    body = SimpleNamespace(section_code='section_001', blocks=(block,), claims=())
    frozen = summary.model_dump(mode='json')
    projected, = workbook_claims.project_workbook_summary_sections((body,), (summary,))
    new_ref, = projected.blocks[0].narrative_references
    assert new_ref.claim_id != reference.claim_id
    assert new_ref.analysis_id == reference.analysis_id and new_ref.statement_sha256 == reference.statement_sha256
    assert projected.blocks[0].markdown == block.markdown
    assert summary.model_dump(mode='json') == frozen
    bindings = build_claim_subject_bindings((body, projected), {}, {})
    assert len(bindings) == 2
    markdown = marked + '\n\n' + anchor_bound_numbers(projected.blocks[0].markdown, (new_ref,))
    assert markdown.count(f'[[claim:{new_ref.claim_id}]]') == 1
    if valid:
        assert new_ref.semantic_receipt.context_sha256 == receipt.context_sha256
        assert new_ref.semantic_receipt.knowledge_references == receipt.knowledge_references
        assert semantic_receipt_status(markdown, new_ref.claim_id, new_ref.semantic_receipt) == 'interpreted'
    else:
        assert semantic_receipt_status(markdown, new_ref.claim_id, new_ref.semantic_receipt) != 'interpreted'
    assert workbook_claims.project_workbook_summary_sections((body,), (summary,)) == (projected,)


@pytest.mark.parametrize('fault', ['foreign_section', 'duplicate_section', 'chart', 'claim'])
def test_server_summary_input_cannot_extend_registered_charts_claims_or_sections(fault):
    from smart_reporting.reporting.delivery.draft_v1 import (
        ReportDraft,
        ReportDraftBlock,
        ReportDraftSection,
        ReportSectionDefinition,
        assemble_report_markdown,
    )
    from smart_reporting.reporting.models import ReportingError

    body = ReportDraftSection(sectionCode='section_001', blocks=(ReportDraftBlock(blockId='body', markdown='正文。'),))
    block = ReportDraftBlock(blockId='summary', markdown='摘要。',
        **({'chartIds': ['unregistered-chart']} if fault == 'chart' else
           {'claimIds': ['unregistered-claim']} if fault == 'claim' else {}))
    summary = ReportDraftSection(sectionCode='section_002' if fault == 'foreign_section' else 'section_001', blocks=(block,))
    with pytest.raises(ReportingError, match='服务端摘要'):
        assemble_report_markdown(ReportDraft(sections=(body,)), expected_title='报告', markdown_path='report.md',
            sections=(ReportSectionDefinition(code='section_001', sectionNumber='1', title='预算'),), citation_ids=(),
            server_narrative_sections=(summary, summary) if fault == 'duplicate_section' else (summary,))
