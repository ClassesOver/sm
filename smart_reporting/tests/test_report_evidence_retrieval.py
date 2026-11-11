"""报告知识检索由可信运行与冻结依据授权，不借用管理员会话。"""

import pytest

from smart_reporting.reporting.tests.test_business_evidence_index import (
    index_context as index_context,
)
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_business_evidence_publication import evidence_service
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_report_basis_persistence import basis_context as basis_context
from smart_reporting.tests.test_report_basis_persistence import request_summary

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def registered_basis(context, **changes):
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.semantics.models import BuildIdentity

    service = ReportBasisService(context['scopes'])
    basis = await service.register_report_basis('run-basis', context['scope'], user_id='7', thread_id='thread-basis',
        request_summary=request_summary(context['scope_id']), build_identity=BuildIdentity(commit='a' * 40,
            sourceHash='b' * 64, dependencyHash='c' * 64, compilerVersion='semantic-v1'), **changes)
    return service, basis


async def search(service, bases, context, **changes):
    values = dict(run_id='run-basis', scope=context['scope'], user_id='7', thread_id='thread-basis',
        kind='rule_evidence', query='预算如何计算')
    values.update(changes)
    return await service.search_report(bases, **values)


async def test_c33_report_search_uses_registered_release_period_and_knowledge_time(basis_context, document_context, index_context):
    bases, basis = await registered_basis(basis_context)
    service = evidence_service(document_context, index_context)
    result = await search(service, bases, basis_context)
    assert result.basis_id == basis.id
    assert result.search.release_id == basis.evidence_release_id
    assert result.search.request.period == basis.request_summary.period
    assert result.search.request.knowledge_as_of == basis.knowledge_as_of
    assert result.search.request.metric_ids == tuple(ref.metric_id for ref in basis.metric_versions)
    assert result.search.status == 'matched'
    assert result.search.hits[0].source_hash
    assert result.search.hits[0].role == 'rule_evidence'
    assert result.search.hits[0].recorded_at <= basis.knowledge_as_of
    assert result.search.hits[0].event_time is None
    assert result.search.hits[0].applies_to == ()
    assert '不能平均' in result.search.hits[0].quote


@pytest.mark.parametrize('fault', ['user', 'thread', 'organization'])
async def test_report_search_rejects_foreign_identity_before_index(basis_context, document_context, index_context, fault, monkeypatch):
    from smart_reporting.management.models import ManagementError

    bases, _ = await registered_basis(basis_context)
    service = evidence_service(document_context, index_context)
    patch = {'user_id': 'foreign'} if fault == 'user' else {'thread_id': 'foreign'} if fault == 'thread' else {'scope': basis_context['other_scope']}
    def forbidden(*args, **kwargs):
        raise AssertionError('未授权请求不得进入索引')
    monkeypatch.setattr(service.index, 'search', forbidden)
    with pytest.raises(ManagementError) as error:
        await search(service, bases, basis_context, **patch)
    assert error.value.status == 403


async def test_report_background_missing_is_explicit_without_rule_fallback(basis_context, document_context, index_context):
    bases, _ = await registered_basis(basis_context)
    result = await search(evidence_service(document_context, index_context), bases, basis_context, kind='background')
    assert result.search is None
    assert result.issue_codes == ('background_release_unavailable',)


@pytest.mark.parametrize('fault', ['unavailable', 'revoked', 'original_missing', 'cached_tampered', 'cached_wrong_basis', 'cached_time'])
async def test_c34_report_retrieval_and_resume_recheck_current_authority(basis_context, document_context, index_context, fault, monkeypatch):
    bases, _ = await registered_basis(basis_context)
    service = evidence_service(document_context, index_context)
    saved = await search(service, bases, basis_context)
    if fault == 'unavailable':
        index_context[2].failure = 'error'
        current = await search(service, bases, basis_context)
        assert current.search.status == 'unavailable' and not current.search.hits
        return
    if fault == 'revoked':
        documents, token, scope, _, _, _ = document_context
        detail = await documents.get_document(token, scope, 'budget-rules')
        await documents.review_revision(token, scope, 'budget-rules', 1, decision='revoked', reason='撤销',
            expected_version=detail['revisions'][0]['stateVersion'])
    if fault == 'original_missing':
        async def missing(*args, **kwargs):
            raise FileNotFoundError('original missing')
        monkeypatch.setattr(service.documents.originals, 'read', missing)
    if fault == 'cached_tampered':
        hit = saved.search.hits[0].model_copy(update={'quote': '未经原文确认的经营原因'})
        saved = saved.model_copy(update={'search': saved.search.model_copy(update={'hits': (hit,)})})
    if fault == 'cached_time':
        from datetime import date
        hit = saved.search.hits[0].model_copy(update={'event_time': date(2026, 11, 1)})
        saved = saved.model_copy(update={'search': saved.search.model_copy(update={'hits': (hit,)})})
    if fault == 'cached_wrong_basis':
        saved = saved.model_copy(update={'basis_id': 'foreign-basis'})
    current = await service.revalidate_report(bases, run_id='run-basis', scope=basis_context['scope'],
        user_id='7', thread_id='thread-basis', saved=saved)
    assert current.search is None or not current.search.hits
    assert current.issue_codes or current.search.issue_codes
    assert '未经原文确认的经营原因' not in str(current.model_dump())


async def test_runtime_knowledge_context_revalidates_before_reuse(basis_context, document_context, index_context):
    from types import SimpleNamespace

    from smart_reporting.reporting.workflow.runtime.business_evidence import (
        business_knowledge_context,
    )

    bases, basis = await registered_basis(basis_context)
    service = evidence_service(document_context, index_context)
    runtime = SimpleNamespace(report_basis_service=bases, business_evidence_service=service,
        _scope=lambda _: {'database': basis_context['scope'].database, 'companyId': basis_context['scope'].company_id,
            'userId': '7', 'callerThreadId': 'thread-basis'})
    run = SimpleNamespace(run_id='run-basis')
    first = await business_knowledge_context(runtime, run, query='预算如何计算', report_revision='initial', section_code='section_001')
    assert first['reportBasisId'] == basis.id
    assert first['receipts'][0]['search']['status'] == 'matched'
    assert first['receipts'][1]['issueCodes'] == ['background_release_unavailable']
    assert first['interpretationStatus'] == 'unverified'
    assert '不能平均' in str(first)
    documents, token, scope, _, _, _ = document_context
    detail = await documents.get_document(token, scope, 'budget-rules')
    await documents.review_revision(token, scope, 'budget-rules', 1, decision='revoked', reason='撤销',
        expected_version=detail['revisions'][0]['stateVersion'])
    current = await business_knowledge_context(runtime, run, query='预算如何计算', report_revision='initial', section_code='section_001')
    assert '不能平均' not in str(current)
    assert current['receipts'][0]['search']['status'] == 'revoked'
    assert current['interpretationStatus'] == 'unverified'


@pytest.mark.parametrize('fault', ['identity', 'backend'])
async def test_runtime_knowledge_failure_stays_explicit_and_nonblocking(basis_context, document_context, index_context, fault, monkeypatch):
    from types import SimpleNamespace

    from smart_reporting.reporting.workflow.runtime.business_evidence import (
        business_knowledge_context,
    )

    bases, _ = await registered_basis(basis_context)
    service = evidence_service(document_context, index_context)
    runtime = SimpleNamespace(report_basis_service=bases, business_evidence_service=service,
        _scope=lambda _: {'database': basis_context['scope'].database, 'companyId': basis_context['scope'].company_id,
            'userId': 'foreign', 'callerThreadId': 'thread-basis'})
    if fault == 'backend':
        runtime._scope = lambda _: {'database': basis_context['scope'].database, 'companyId': basis_context['scope'].company_id,
            'userId': '7', 'callerThreadId': 'thread-basis'}
        async def failed(*args, **kwargs):
            raise RuntimeError('backend unavailable')
        monkeypatch.setattr(service, 'search_report', failed)
    current = await business_knowledge_context(runtime, SimpleNamespace(run_id='run-basis'), query='预算如何计算', report_revision='initial', section_code='section_001')
    assert current['status'] == 'unavailable' and not current['receipts']
    assert current['issueCodes'] == [
        'management_run_identity_conflict' if fault == 'identity' else 'knowledge_revalidation_unavailable']


async def test_report_revocation_during_search_removes_fragment(basis_context, document_context, index_context, monkeypatch):
    bases, _ = await registered_basis(basis_context)
    service = evidence_service(document_context, index_context)
    original = service.index.search

    async def revoke(*args, **kwargs):
        hits = await original(*args, **kwargs)
        documents, token, scope, _, _, _ = document_context
        detail = await documents.get_document(token, scope, 'budget-rules')
        await documents.review_revision(token, scope, 'budget-rules', 1, decision='revoked', reason='撤销',
            expected_version=detail['revisions'][0]['stateVersion'])
        return hits

    monkeypatch.setattr(service.index, 'search', revoke)
    current = await search(service, bases, basis_context)
    assert current.search.status == 'revoked'
    assert not current.search.hits
    assert '不能平均' not in str(current.model_dump())


async def test_report_search_applies_knowledge_cutoff_before_ranking(basis_context, document_context, index_context, monkeypatch):
    from datetime import timedelta

    bases, _ = await registered_basis(basis_context,
        knowledge_as_of=document_context[0].clock() - timedelta(days=1))
    service = evidence_service(document_context, index_context)
    async def forbidden(*args, **kwargs):
        raise AssertionError('当时尚不可知的材料不能进入向量排序')
    monkeypatch.setattr(service.index, 'search', forbidden)
    result = await search(service, bases, basis_context)
    assert result.search.status == 'inapplicable'
    assert not result.search.hits


@pytest.mark.parametrize('case', ['applicable', 'event_after_period', 'future_event', 'wrong_metric', 'wrong_organization', 'unspecified_project'])
async def test_report_pins_background_independently_from_formula(basis_context, document_context, index_context, case, monkeypatch):
    from smart_reporting.reporting.business_knowledge.retrieval import DocumentRevisionRef
    from smart_reporting.tests.test_business_document_ingestion import metadata, register

    documents, token, scope, _, _, _ = document_context
    event_time = '2026-12-01' if case == 'event_after_period' else '2026-11-30' if case == 'future_event' else '2026-11-01'
    applies = [{'kind': 'metric', 'id': 'budget'}] if case == 'applicable' else [{'kind': 'metric', 'id': 'foreign'}] if case == 'wrong_metric' else [{'kind': 'organization', 'id': 'foreign'}] if case == 'wrong_organization' else [{'kind': 'project', 'id': 'project-a'}] if case == 'unspecified_project' else []
    upload = await register(document_context, request_id='background-upload', details=metadata(
        id='budget-event', title='预算调整记录', kind='background', eventTime=event_time,
        appliesTo=applies), body='本月预算调整已经批准。'.encode())
    await documents.ingest_revision(await documents.claim_next())
    detail = await documents.get_document(token, scope, upload.document_id)
    await documents.review_revision(token, scope, upload.document_id, 1, decision='approved', reason='核对原文',
        expected_version=detail['revisions'][0]['stateVersion'])
    service = evidence_service(document_context, index_context)
    release = await service.publish(token, scope, request_id='background-release', kind='background',
        revision_ids=[DocumentRevisionRef(document_id=upload.document_id, revision=1)])
    default = await basis_context['policy_service'].get_default(token, scope, 'budget_execution')
    await basis_context['policy_service'].set_default(token, scope, 'budget_execution',
        policy_version={'policyId': 'monthly-budget', 'revision': 1}, background_release_id=release.release_id,
        expected_version=default['version'])
    bases, basis = await registered_basis(basis_context)
    if case != 'applicable':
        async def forbidden(*args, **kwargs):
            raise AssertionError('不适用材料不得进入向量排序')
        monkeypatch.setattr(service.index, 'search', forbidden)
    result = await search(service, bases, basis_context, kind='background')
    if case != 'applicable':
        assert result.search.status == 'inapplicable' and not result.search.hits
        return
    assert basis.policy_version.revision == 1
    assert result.search.release_id == release.release_id
    hit, = result.search.hits
    assert hit.role == 'background' and hit.event_time.isoformat() == '2026-11-01'
    assert hit.applies_to[0].id == 'budget'
    assert hit.recorded_at <= basis.knowledge_as_of


async def test_report_knowledge_receipt_is_immutable_idempotent_and_revalidated(basis_context, document_context, index_context, monkeypatch):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.reporting.semantics.basis import BasisKnowledgeReceipt

    bases, basis = await registered_basis(basis_context)
    service = evidence_service(document_context, index_context)
    params = dict(run_id='run-basis', scope=basis_context['scope'], user_id='7', thread_id='thread-basis',
        receipt_id='knowledge-section-1-rules', report_revision='initial', section_code='section_001',
        kind='rule_evidence', query='预算如何计算', evidence_service=service)
    first = await bases.append_knowledge_receipt(**params)
    assert isinstance(first, BasisKnowledgeReceipt)
    assert first.basis_id == basis.id and first.evidence.search.status == 'matched'
    receipts = await bases.load_basis_receipts(params['run_id'], params['scope'], user_id='7',
        thread_id='thread-basis', report_revision='initial')
    assert first in receipts
    async def forbidden(*args, **kwargs):
        raise AssertionError('同一检索回执读回不能重新向量检索')
    monkeypatch.setattr(service, 'search_report', forbidden)
    assert await bases.append_knowledge_receipt(**params) == first
    with pytest.raises(ManagementError) as error:
        await bases.append_knowledge_receipt(**{**params, 'query': '另一问题'})
    assert error.value.status == 409
    documents, token, scope, _, _, _ = document_context
    detail = await documents.get_document(token, scope, 'budget-rules')
    await documents.review_revision(token, scope, 'budget-rules', 1, decision='revoked', reason='撤销',
        expected_version=detail['revisions'][0]['stateVersion'])
    stored, = await bases.load_basis_receipts(params['run_id'], params['scope'], user_id='7',
        thread_id='thread-basis', report_revision='initial')
    assert stored == first  # 历史回执不重写，但不是当前授权证明。
    current = await service.revalidate_report(bases, run_id=params['run_id'], scope=params['scope'],
        user_id='7', thread_id='thread-basis', saved=stored.evidence)
    assert current.search.status == 'revoked' and not current.search.hits


async def test_knowledge_receipt_audit_failure_rolls_back_registration(basis_context, document_context, index_context, monkeypatch):
    bases, _ = await registered_basis(basis_context)
    async def fail(*args, **kwargs):
        raise OSError('audit unavailable')
    monkeypatch.setattr(bases, '_audit', fail)
    with pytest.raises(OSError):
        await bases.append_knowledge_receipt('run-basis', basis_context['scope'], user_id='7', thread_id='thread-basis',
            receipt_id='knowledge-section-1', report_revision='initial', section_code='section_001',
            kind='rule_evidence', query='预算如何计算', evidence_service=evidence_service(document_context, index_context))
    assert not await bases.load_basis_receipts('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', report_revision='initial')


async def test_durable_knowledge_context_restores_without_reranking_and_drops_revoked_quote(basis_context, document_context, index_context, monkeypatch):
    from types import SimpleNamespace

    from smart_reporting.reporting.semantics.basis import BasisKnowledgeReceipt
    from smart_reporting.reporting.workflow.runtime.business_evidence import (
        business_knowledge_context,
    )

    bases, basis = await registered_basis(basis_context)
    service = evidence_service(document_context, index_context)
    runtime = SimpleNamespace(report_basis_service=bases, business_evidence_service=service,
        _scope=lambda _: {'database': basis_context['scope'].database, 'companyId': basis_context['scope'].company_id,
            'userId': '7', 'callerThreadId': 'thread-basis'})
    params = dict(query='预算如何计算', report_revision='initial', section_code='section_001')
    first = await business_knowledge_context(runtime, SimpleNamespace(run_id='run-basis'), **params)
    assert first['reportBasisId'] == basis.id and '不能平均' in str(first)
    receipts = await bases.load_basis_receipts('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', report_revision='initial')
    assert len(receipts) == 2 and all(isinstance(item, BasisKnowledgeReceipt) for item in receipts)
    assert first['receiptIds'] == [item.receipt_id for item in sorted(receipts, key=lambda item: ('rule_evidence', 'background').index(item.evidence.kind))]
    async def forbidden(*args, **kwargs):
        raise AssertionError('恢复不能用当前索引重新排序改变冻结知识选择')
    monkeypatch.setattr(service, 'search_report', forbidden)
    restored = await business_knowledge_context(runtime, SimpleNamespace(run_id='run-basis'), **params)
    assert restored == first
    documents, token, scope, _, _, _ = document_context
    detail = await documents.get_document(token, scope, 'budget-rules')
    await documents.review_revision(token, scope, 'budget-rules', 1, decision='revoked', reason='撤销',
        expected_version=detail['revisions'][0]['stateVersion'])
    current = await business_knowledge_context(runtime, SimpleNamespace(run_id='run-basis'), **params)
    assert current['receipts'][0]['search']['status'] == 'revoked'
    assert current['receiptIds'] == first['receiptIds']
    assert '不能平均' not in str(current)
    assert current['interpretationStatus'] == 'unverified'


@pytest.mark.parametrize('fault', ['revoked', 'original_missing', 'foreign_section', 'receipt_missing', 'read_failure'])
async def test_section_restoration_withdraws_prose_when_registered_knowledge_is_revoked(basis_context, document_context, index_context, fault, monkeypatch):
    from types import SimpleNamespace

    from smart_reporting.reporting.workflow.checkpoint import SectionArtifact
    from smart_reporting.reporting.workflow.runtime.business_evidence import (
        business_knowledge_context,
        revalidate_section_knowledge,
    )

    bases, _ = await registered_basis(basis_context)
    runtime = SimpleNamespace(report_basis_service=bases, business_evidence_service=evidence_service(document_context, index_context),
        _scope=lambda _: {'database': basis_context['scope'].database, 'companyId': basis_context['scope'].company_id,
            'userId': '7', 'callerThreadId': 'thread-basis'})
    run = SimpleNamespace(run_id='run-basis')
    context = await business_knowledge_context(runtime, run, query='预算如何计算', report_revision='1', section_code='section_001')
    artifact = SectionArtifact(sectionCode='section_001', blocks=[{'blockId': 'block_001',
        'markdown': '依据制度解释预算变化。', 'claimIds': ['claim_001']}], claims=[{
        'claimId': 'claim_001', 'metricCode': 'budget', 'value': 1, 'periodBasis': '本期',
        'managementQuestion': '预算变化', 'currentPeriod': '本期', 'citationIds': ['citation_001']}],
        knowledgeReceiptIds=context['receiptIds'])
    assert await revalidate_section_knowledge(runtime, run, artifact, report_revision='1') == artifact
    if fault == 'revoked':
        artifact = artifact.model_copy(update={'warnings': tuple({'code': 'note', 'message': '旧知识引用内容'} for _ in range(500))})
        documents, token, scope, _, _, _ = document_context
        detail = await documents.get_document(token, scope, 'budget-rules')
        await documents.review_revision(token, scope, 'budget-rules', 1, decision='revoked', reason='撤销',
            expected_version=detail['revisions'][0]['stateVersion'])
    elif fault == 'original_missing':
        async def missing(*args, **kwargs):
            raise FileNotFoundError('missing original')
        monkeypatch.setattr(runtime.business_evidence_service.documents.originals, 'read', missing)
    elif fault == 'foreign_section':
        artifact = artifact.model_copy(update={'section_code': 'section_002'})
    elif fault == 'receipt_missing':
        artifact = artifact.model_copy(update={'knowledge_receipt_ids': ('foreign-receipt',)})
    else:
        async def failed(*args, **kwargs):
            raise OSError('registry read unavailable')
        monkeypatch.setattr(bases, 'load_basis_receipts', failed)
    withdrawn = await revalidate_section_knowledge(runtime, run, artifact, report_revision='1')
    assert not withdrawn.claims
    assert '依据制度解释预算变化' not in str(withdrawn.model_dump())
    assert '知识依据' in withdrawn.blocks[0].markdown
    assert '旧知识引用内容' not in str(withdrawn.model_dump())
    assert withdrawn.warnings[-1]['code'] == 'report_section_knowledge_unavailable'
    assert SectionArtifact.model_validate(withdrawn.model_dump()) == withdrawn
    if fault == 'foreign_section':
        return
    # 实际durable章节恢复也必须经过知识重验，不能直接回放原章节正文。
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin
    runtime.state_repository = SimpleNamespace(get_by_external_run_id=AsyncMock(return_value=SimpleNamespace(payload={
        'sectionArtifacts': {'section_001': {'revision': 1, 'workItemHash': 'a' * 64,
            'analysisIds': ['analysis_001'], 'artifactFile': {'path': 'section.json', 'size': 2, 'sha256': 'b' * 64}}}})))
    runtime._read_identity_model = AsyncMock(return_value=artifact)
    original_scope = runtime._scope
    runtime._scope = lambda context: {**original_scope(context), 'threadId': 'workspace-key', 'externalRunId': 'external'}
    _, restored = await RuntimeSectionsMixin._durable_completed_section(runtime, run, revision=1,
        section_code='section_001', section_title='预算变化', analysis_ids=('analysis_001',), work_item_hash='a' * 64)
    assert restored.knowledge_status == 'unavailable'
    assert not restored.claims
    assert '依据制度解释预算变化' not in str(restored.model_dump())


async def test_actual_section_phase_registers_knowledge_dependency_and_rechecks_on_restore(basis_context, document_context, index_context, tmp_path):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agno.run import RunContext

    from smart_reporting.reporting.tests.test_report_capacity import (
        _CheckpointRuntime,
        _coverage,
        _identity,
    )
    from smart_reporting.reporting.workflow.checkpoint import (
        ReportingCheckpoint,
        SectionArtifact,
        SectionWorkItem,
    )

    bases, _ = await registered_basis(basis_context)
    checkpoint = ReportingCheckpoint(revision=1, phase='analysis', outlineHash='a' * 64,
        profileCoverage=_coverage(), pendingSections=('section_001',))
    runtime = _CheckpointRuntime(tmp_path, checkpoint)
    runtime.report_basis_service = bases
    runtime.business_evidence_service = evidence_service(document_context, index_context)
    runtime.section_generator = object()
    runtime._scope = lambda _: {'database': basis_context['scope'].database, 'companyId': basis_context['scope'].company_id,
        'userId': '7', 'callerThreadId': 'thread-basis', 'threadId': 'thread-1', 'externalRunId': 'run-1'}
    runtime._envelope = lambda _: SimpleNamespace(report_goal='解释预算', delivery_format='document')
    tasks = {}
    async def start(scope, instruction, **kwargs):
        tasks[scope.external_run_id] = json.loads(instruction)
    async def run(scope, **kwargs):
        payload = tasks[scope.external_run_id]
        assert payload['businessKnowledge']['receipts'][0]['search']['status'] == 'matched'
        artifact = SectionArtifact(sectionCode='section_001', blocks=[{'blockId': 'b',
            'markdown': '依据制度解释预算变化。', 'claimIds': ['c']}], claims=[{
            'claimId': 'c', 'metricCode': 'budget', 'value': 1, 'periodBasis': '本期',
            'managementQuestion': '预算变化', 'currentPeriod': '本期', 'citationIds': ['citation_001']}])
        identity = await runtime._write_immutable_artifact('thread-1', payload['sectionOutputPath'],
            artifact.model_dump_json(by_alias=True).encode())
        return {'artifacts': [identity.model_dump(mode='json', by_alias=True)]}
    async def hash_file(thread, path):
        return _identity(path, (tmp_path / path).read_bytes()).model_dump(mode='json', by_alias=True)
    runtime.task_runner = SimpleNamespace(repository=SimpleNamespace(get_task_snapshot=AsyncMock(return_value=None)), start=start, run=run)
    runtime.workspace_service = SimpleNamespace(ahash_file=hash_file)
    context = RunContext(run_id='run-basis', session_id='session-1')
    item = SectionWorkItem(sectionCode='section_001', sectionNumber='1', title='预算变化', objective='解释预算',
        analysisIds=('analysis_001',), completionConditions=('保留证据',), markdownRequirements=('使用事实',))
    params = dict(revision=1, sandbox_id='sandbox', validation_context_file=_identity('validation.json'),
        work_item=item, analysis_rework_constraints={}, analysis_rework_allowed=False, degraded_rework=None)
    completed, artifact, rework = await runtime._run_section_phase(context, checkpoint=checkpoint, **params)
    assert not rework and len(artifact.knowledge_receipt_ids) == 2
    persisted = await runtime._read_identity_model('thread-1', completed.completed_sections[0].artifact_file, SectionArtifact)
    assert persisted.knowledge_receipt_ids == artifact.knowledge_receipt_ids
    from smart_reporting.reporting.workflow.runtime.business_evidence import (
        register_section_knowledge,
    )

    dependencies, registration_status = await register_section_knowledge(runtime, context,
        basis_id=(await bases.load_report_basis('run-basis', basis_context['scope'],
            user_id='7', thread_id='thread-basis')).id)
    assert registration_status == 'registered'
    assert dependencies[0].receipt_ids == persisted.knowledge_receipt_ids
    assert dependencies[0].section_code == 'section_001'
    assert dependencies[0].report_revision == '1'
    documents, token, scope, _, _, _ = document_context
    detail = await documents.get_document(token, scope, 'budget-rules')
    await documents.review_revision(token, scope, 'budget-rules', 1, decision='revoked', reason='撤销',
        expected_version=detail['revisions'][0]['stateVersion'])
    # 实际PG撤销也要在最终发布门禁重验，不能只验证恢复路径。
    from smart_reporting.reporting.tests.test_report_capacity import _appendix_inputs
    from smart_reporting.reporting.workflow.runtime.publication import RuntimePublicationMixin

    publication_checkpoint = completed.model_copy(update={
        'evidence_manifest': _appendix_inputs(count=1, analysis_count=1)[3].evidence_manifest})
    gate_runtime = SimpleNamespace(
        report_basis_service=bases, business_evidence_service=runtime.business_evidence_service,
        _scope=runtime._scope, _state=lambda _: {}, _workflow_result=lambda _: {},
        state_repository=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(payload={
            'workflowCheckpoint': publication_checkpoint.model_dump(mode='json', by_alias=True)}))),
        _read_identity_model=runtime._read_identity_model,
        _verify_claim_fact_bindings=AsyncMock(return_value=([], [])),
        quality_warning_service=None)
    gate = await RuntimePublicationMixin._dataset_publication_gate(gate_runtime, context, {'revision': 1})
    assert any(item['code'] == 'report_section_knowledge_unavailable' for item in gate['issues'])
    assert any(item['code'] == 'report_section_knowledge_unavailable' for item in gate['warnings'])
    assert not gate['formalReleaseAllowed']
    _, restored, _ = await runtime._run_section_phase(context, checkpoint=completed, **params)
    assert restored.knowledge_status == 'unavailable' and not restored.claims
    assert len(tasks) == 1


@pytest.mark.parametrize('fault', [None, 'revoked', 'original_missing', 'wrong_section', 'wrong_revision', 'wrong_basis', 'wrong_user', 'missing_receipt'])
async def test_registered_knowledge_dependencies_require_current_basis_and_originals(basis_context, document_context, index_context, fault, monkeypatch):
    from types import SimpleNamespace

    from smart_reporting.reporting.business_knowledge.dependencies import (
        read_knowledge_dependencies,
    )
    from smart_reporting.reporting.trace.contracts_v1 import SectionKnowledgeDependencyV1
    from smart_reporting.reporting.workflow.runtime.business_evidence import (
        business_knowledge_context,
    )

    bases, basis = await registered_basis(basis_context)
    service = evidence_service(document_context, index_context)
    runtime = SimpleNamespace(report_basis_service=bases, business_evidence_service=service,
        _scope=lambda _: {'database': basis_context['scope'].database, 'companyId': basis_context['scope'].company_id,
            'userId': '7', 'callerThreadId': 'thread-basis'})
    context = await business_knowledge_context(runtime, SimpleNamespace(run_id='run-basis'),
        query='预算如何计算', report_revision='1', section_code='section_001')
    dependency = SectionKnowledgeDependencyV1(sectionCode='section_001', reportRevision='1', receiptIds=context['receiptIds'])
    identity = dict(run_id='run-basis', scope=basis_context['scope'], user_id='7', thread_id='thread-basis')
    if fault == 'revoked':
        documents, token, scope, _, _, _ = document_context
        detail = await documents.get_document(token, scope, 'budget-rules')
        await documents.review_revision(token, scope, 'budget-rules', 1, decision='revoked', reason='撤销',
            expected_version=detail['revisions'][0]['stateVersion'])
    elif fault == 'original_missing':
        async def unavailable(*args, **kwargs):
            raise FileNotFoundError('original unavailable')
        monkeypatch.setattr(service.documents.originals, 'read', unavailable)
    elif fault == 'wrong_section':
        dependency = dependency.model_copy(update={'section_code': 'section_002'})
    elif fault == 'wrong_revision':
        dependency = dependency.model_copy(update={'report_revision': '2'})
    elif fault == 'wrong_basis':
        basis = basis.model_copy(update={'id': 'foreign-basis'})
    elif fault == 'wrong_user':
        identity['user_id'] = 'foreign'
    elif fault == 'missing_receipt':
        dependency = dependency.model_copy(update={'receipt_ids': ('missing',)})
    result = await read_knowledge_dependencies(bases, service, identity=identity, basis_id=basis.id,
        dependencies=(dependency,), registration_status='registered')
    assert result['interpretationStatus'] == 'unverified'
    assert result['status'] == ('unavailable' if fault else 'available')
    assert result['sections'][0]['status'] == result['status']
    assert '不能平均' not in str(result)  # 索引和当前状态都不复制历史片段
    if fault:
        assert result['sections'][0]['issueCodes']
    else:
        assert result['sections'][0]['receiptIds'] == list(dependency.receipt_ids)


@pytest.mark.parametrize('narrative', [False, True])
@pytest.mark.parametrize('relation,expected', [('supports', 'supported'), ('irrelevant', 'unverified'), ('contradicts', 'conflicted')])
async def test_actual_editor_rechecks_registered_knowledge_after_revocation(basis_context, document_context, index_context, tmp_path, relation, expected, narrative):
    import hashlib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.report_editor import ReportEditorContext, ReportEditorService
    from smart_reporting.reporting.business_knowledge.claims import candidates_from_context
    from smart_reporting.reporting.data_sources import DatasetHandle
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile, DatasetLineage
    from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
    from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs
    from smart_reporting.reporting.tests.test_report_capacity import _coverage, _identity
    from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
    from smart_reporting.reporting.workflow.checkpoint import ReportingCheckpoint, SectionArtifact
    from smart_reporting.reporting.workflow.runtime.business_evidence import (
        business_knowledge_context,
    )

    bases, basis = await registered_basis(basis_context)
    service = evidence_service(document_context, index_context)
    runtime = SimpleNamespace(report_basis_service=bases, business_evidence_service=service,
        _scope=lambda _: {'database': basis_context['scope'].database, 'companyId': basis_context['scope'].company_id,
            'userId': '7', 'callerThreadId': 'thread-basis'})
    knowledge = await business_knowledge_context(runtime, SimpleNamespace(run_id='run-basis'),
        query='预算如何计算', report_revision='1', section_code='section_001')
    candidates = candidates_from_context(knowledge, section_code='section_001')
    evidence = next(iter(candidates.values()))
    def interpretation(item):
        item.update(claimKind='inference', knowledgeRelations=[{
            'evidenceId': evidence.reference.evidence_id, 'relationship': relation,
            'explanationType': 'interpretation', 'sourceEvidence': [evidence.hit.quote], 'claimEvidence': ['预算合计']}])
    host, _, workspace_scope, _, _, _, _, index = await native_quality_inputs(tmp_path,
        publication_fixture=True, change=interpretation, knowledge_candidates=candidates, basis_id=basis.id)

    if narrative:
        from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
        from smart_reporting.reporting.trace.claim_semantics import freeze_interpretation
        from smart_reporting.reporting.trace.narrative_claims import discover_narrative_references
        from smart_reporting.reporting.trace.semantic_bindings import (
            anchor_bound_numbers,
            statement_fingerprints,
        )
        from smart_reporting.reporting.trace.subject_builder import build_claim_subject_bindings

        block = ReportDraftBlock(blockId='knowledge-narrative', markdown='建议按原始金额累计预算。')
        ref, = discover_narrative_references(block, section_code='section_001', basis_id=basis.id, period=evidence.period)
        markdown = anchor_bound_numbers(block.markdown, (ref,))
        item = {'claimId': ref.claim_id, 'claimKind': 'recommendation', 'kindEvidence': ['建议'],
            'knowledgeRelations': [{'evidenceId': evidence.reference.evidence_id, 'relationship': relation,
                'explanationType': 'recommendation', 'claimEvidence': ['累计预算'], 'sourceEvidence': [evidence.hit.quote]}]}
        receipt = freeze_interpretation(markdown, ref.claim_id, item,
            reference={'entry': {'basisId': basis.id}}, knowledge_candidates=candidates)
        ref = ref.model_copy(update={'semantic_receipt': receipt,
            'statement_sha256': statement_fingerprints(markdown, (ref.claim_id,))[ref.claim_id]})
        block = block.model_copy(update={'narrative_references': (ref,)})
        subjects = build_claim_subject_bindings((SimpleNamespace(section_code='section_001', blocks=(block,), claims=()),), {}, {})
        raw = markdown.encode()
        index = index.model_copy(update={'subject_bindings': subjects, 'files': tuple(file.model_copy(update={
            'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
            if file.resource_id == index.markdown_file_resource_id else file for file in index.files)})
        await host.workspace_service.awrite_bytes(workspace_scope.workspace_key, 'reports/report.md', raw, overwrite=True)

    scope = {**workspace_scope.as_state(), 'database': basis_context['scope'].database,
        'companyId': basis_context['scope'].company_id, 'userId': '7', 'callerThreadId': 'thread-basis'}
    artifact = SectionArtifact(sectionCode='section_001', blocks=[{'blockId': 'b',
        'markdown': '依据制度解释预算变化。', 'claimIds': ['c']}], claims=[{
        'claimId': 'c', 'metricCode': 'budget', 'value': 1, 'periodBasis': '本期',
        'managementQuestion': '预算变化', 'currentPeriod': '本期', 'citationIds': ['citation_001']}],
        knowledgeReceiptIds=knowledge['receiptIds'])
    artifact_bytes = artifact.model_dump_json(by_alias=True).encode()
    await host.workspace_service.awrite_bytes(workspace_scope.workspace_key, 'section.json', artifact_bytes)
    checkpoint = ReportingCheckpoint(revision=1, phase='analysis', outlineHash='a' * 64, profileCoverage=_coverage(),
        completedSections=[{'sectionCode': 'section_001', 'workItemHash': 'a' * 64,
            'artifactFile': _identity('section.json', artifact_bytes)}])
    host.report_basis_service = bases
    host.business_evidence_service = service
    host._scope = lambda _: scope
    host._state = lambda _: {'report_request_context': {'assertionPolicy': {'mode': 'shadow'}}}
    host._build_drilldown_metrics = AsyncMock(return_value=())
    host.state_repository.get = AsyncMock(return_value=SimpleNamespace(payload={
        'workflowCheckpoint': checkpoint.model_dump(mode='json', by_alias=True)}))
    dataset = index.datasets[0]
    data_file = next(item for item in index.files if item.resource_id == dataset.file_resource_id)
    markdown_file = next(item for item in index.files if item.resource_id == index.markdown_file_resource_id)
    handle = DatasetHandle(dataset_id=dataset.dataset_id, source_id='mcp-url', source_type=dataset.source_type,
        path=data_file.path, row_count=dataset.row_count, size=data_file.size, sha256=data_file.sha256,
        requirement_id=dataset.requirement_id, sql_hash=dataset.sql_hash, filename=dataset.filename)
    lineage = DatasetLineage(datasetId=handle.dataset_id, sourceId=handle.source_id, sourceType=handle.source_type,
        requirementId=handle.requirement_id, sqlHash=handle.sql_hash, rowCount=handle.row_count,
        size=handle.size, sha256=handle.sha256)
    trace_identity = await host._write_trace_index('reports/report.manifest.json', report_basis_id=basis.id,
        handles=(handle,), lineage=(lineage,), revision=1,
        subject_bindings=index.subject_bindings,
        fact_files={entry.analysis_id: ArtifactFile(path=file.path, size=file.size,
            sha256=file.sha256, mediaType=file.media_type) for entry in index.fact_files
            for file in index.files if file.resource_id == entry.file_resource_id},
        markdown_artifact=ArtifactFile(path=markdown_file.path, size=markdown_file.size,
            sha256=markdown_file.sha256, mediaType='text/markdown'), run_context=SimpleNamespace(run_id='run-basis'),
        markdown=(await host.workspace_service.read_limited_regular_file(workspace_scope.workspace_key,
            markdown_file.path, max_bytes=64000)).decode())
    raw_index = await host.workspace_service.read_limited_regular_file(workspace_scope.workspace_key,
        trace_identity.path, max_bytes=1024 * 1024)
    index = RevisionTraceIndexV1.model_validate_json(raw_index)
    assert index.knowledge_registration_status == 'registered'
    from smart_reporting.reporting.trace.quality_bundle import QualityBundle

    publication_quality = QualityBundle.model_validate_json(await host.workspace_service.read_limited_regular_file(
        workspace_scope.workspace_key, 'reports/quality-bundle-v1.json', max_bytes=1024 * 1024))
    assert publication_quality.claim_support[0].support_status == expected
    assert publication_quality.claim_support[0].evidence_refs == (evidence.reference.evidence_id,)
    assert index.knowledge_dependencies[0].receipt_ids == tuple(knowledge['receiptIds'])
    manifest = await register_trace_manifest(host.workspace_service, workspace_scope.workspace_key, index, overwrite=True)
    context = ReportEditorContext(reportId=index.report_id, revision=index.revision, workflowRunId='run-basis',
        jobId='job-1', markdownPath='reports/report.md', job={'jobId': 'job-1'}, scope=scope,
        artifactManifest=manifest)
    editor = ReportEditorService(state_repository=host.state_repository,
        workspace_registry=host.workspace_registry, workspace=host.workspace_service,
        report_basis_service=bases, business_evidence_service=service)
    raw = await host.workspace_service.read_limited_regular_file(workspace_scope.workspace_key, context.markdown_path, max_bytes=1024)
    for revoked in (False, True):
        if revoked:
            documents, token, tenant, _, _, _ = document_context
            detail = await documents.get_document(token, tenant, 'budget-rules')
            await documents.review_revision(token, tenant, 'budget-rules', 1, decision='revoked', reason='撤销',
                expected_version=detail['revisions'][0]['stateVersion'])
        detail = await editor.trace.knowledge_detail(context, index.subject_bindings[0].subject_id,
            evidence.reference.evidence_id)
        assert detail['available'] is not revoked
        if revoked:
            assert 'quote' not in detail and 'title' not in detail
        else:
            assert detail['quote'] == evidence.hit.quote
            assert detail['reference']['documentRevision'] == evidence.hit.revision
            assert 'path' not in detail
        for subject_id, evidence_id in ((index.subject_bindings[0].subject_id, 'evidence-foreign'),
                ('sub-' + 'f' * 16, evidence.reference.evidence_id)):
            from smart_reporting.reporting.models import ReportingError

            with pytest.raises(ReportingError, match='来源'):
                await editor.trace.knowledge_detail(context, subject_id, evidence_id)
        result = await editor.trace.validate(context, raw.decode(), hashlib.sha256(raw).hexdigest())
        assert result['businessKnowledge']['status'] == ('unavailable' if revoked else 'available')
        support = result['quality']['claimSupport'][0]
        assert support['supportStatus'] == ('unverified' if revoked else expected)
        assert bool(support['evidenceRefs']) is not revoked
        if narrative:
            assert result['subjects'][0]['claimId'] == ref.claim_id
            assert result['subjects'][0]['factValue'] is None
            assert result['subjects'][0]['supportStatus'] == ('unknown' if revoked or expected == 'unverified' else 'conflicting' if expected == 'conflicted' else 'supported')
        assert result['businessKnowledge']['interpretationStatus'] == 'unverified'
        assert '不能平均' not in str(result['businessKnowledge'])
        sources = await editor.trace.sources(context)
        assert sources['businessKnowledge'] == result['businessKnowledge']
        citation, = sources['subjects'][0]['knowledgeReferences']
        assert citation['evidenceId'] == evidence.reference.evidence_id
        assert citation['available'] is not revoked
        assert 'quote' not in citation and (citation['title'] is not None) is not revoked


async def test_missing_knowledge_service_preserves_trusted_report_basis_and_period(basis_context):
    from types import SimpleNamespace

    from smart_reporting.reporting.workflow.runtime.business_evidence import (
        business_knowledge_context,
    )

    bases, basis = await registered_basis(basis_context)
    runtime = SimpleNamespace(report_basis_service=bases, business_evidence_service=None,
        _scope=lambda _: {'database': basis_context['scope'].database, 'companyId': basis_context['scope'].company_id,
            'userId': '7', 'callerThreadId': 'thread-basis'})
    context = await business_knowledge_context(runtime, SimpleNamespace(run_id='run-basis'),
        query='预算建议', report_revision='1', section_code='section_001')
    assert context['status'] == 'unavailable'
    assert context['reportBasisId'] == basis.id
    assert context['requestedPeriod'] == basis.request_summary.period.model_dump(mode='json')
    assert not context['receipts']


async def test_real_revocation_withdraws_dependent_block_but_keeps_independent_fact(basis_context, document_context, index_context, tmp_path):
    from types import SimpleNamespace

    from smart_reporting.reporting.business_knowledge.claims import candidates_from_context
    from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
    from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs
    from smart_reporting.reporting.tests.test_section_knowledge_withdrawal import (
        artifact_for,
        reviewed_block,
    )
    from smart_reporting.reporting.trace.semantic_bindings import strip_bound_anchors
    from smart_reporting.reporting.workflow.checkpoint import SectionArtifact
    from smart_reporting.reporting.workflow.runtime.business_evidence import (
        business_knowledge_context,
        revalidate_section_knowledge,
    )

    bases, basis = await registered_basis(basis_context)
    runtime = SimpleNamespace(report_basis_service=bases, business_evidence_service=evidence_service(document_context, index_context),
        _scope=lambda _: {'database': basis_context['scope'].database, 'companyId': basis_context['scope'].company_id,
            'userId': '7', 'callerThreadId': 'thread-basis'})
    run = SimpleNamespace(run_id='run-basis')
    knowledge = await business_knowledge_context(runtime, run, query='预算建议', report_revision='1', section_code='section_001')
    evidence = next(iter(candidates_from_context(knowledge, section_code='section_001').values()))
    dependent = reviewed_block(evidence, block_id='explanation', text='建议遵照制度核对预算。', claim_id='explain')
    index, markdown, _ = await native_quality_inputs(tmp_path, basis_id=basis.id)
    number = index.subject_bindings[0].number_reference
    plain, numbers, notices = strip_bound_anchors(markdown, (number,), ())
    independent = ReportDraftBlock(blockId='fact', markdown=plain, numberReferences=numbers,
        reviewNotices=notices, claimIds=('independent',))
    artifact = artifact_for((independent, dependent)).model_copy(update={'knowledge_receipt_ids': tuple(knowledge['receiptIds'])})
    assert await revalidate_section_knowledge(runtime, run, artifact, report_revision='1') == artifact
    documents, token, tenant, _, _, _ = document_context
    detail = await documents.get_document(token, tenant, 'budget-rules')
    await documents.review_revision(token, tenant, 'budget-rules', 1, decision='revoked', reason='撤销',
        expected_version=detail['revisions'][0]['stateVersion'])
    result = await revalidate_section_knowledge(runtime, run, artifact, report_revision='1')
    assert result.knowledge_status == 'partial'
    assert result.blocks[0] == independent
    assert result.blocks[1].knowledge_withdrawn and '遵照制度' not in result.model_dump_json()
    assert [claim.claim_id for claim in result.claims] == ['independent']
    assert SectionArtifact.model_validate(result.model_dump()) == result

    from unittest.mock import AsyncMock

    from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin

    runtime.state_repository = SimpleNamespace(get_by_external_run_id=AsyncMock(return_value=SimpleNamespace(payload={
        'sectionArtifacts': {'section_001': {'revision': 1, 'workItemHash': 'a' * 64,
            'analysisIds': ['analysis_001'], 'artifactFile': {'path': 'section.json', 'size': 2, 'sha256': 'b' * 64}}}})))
    runtime._read_identity_model = AsyncMock(return_value=artifact)
    original_scope = runtime._scope
    runtime._scope = lambda ctx: {**original_scope(ctx), 'threadId': 'workspace-key', 'externalRunId': 'external'}
    _, restored = await RuntimeSectionsMixin._durable_completed_section(runtime, run, revision=1,
        section_code='section_001', section_title='预算变化', analysis_ids=('analysis_001',), work_item_hash='a' * 64)
    assert restored == result


async def test_public_historical_request_excludes_later_registered_background_before_index(
    basis_context, document_context, index_context, monkeypatch
):
    from datetime import timedelta

    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.reporting.business_knowledge.retrieval import DocumentRevisionRef
    from smart_reporting.tests.test_business_document_ingestion import metadata, register
    from smart_reporting.tests.test_report_basis_persistence import build_identity

    documents, token, scope = document_context[:3]
    cutoff = documents.clock() - timedelta(days=1)
    await register(
        document_context,
        "historical-background-upload",
        details=metadata(
            id="later-background",
            title="后补登记的项目说明",
            kind="background",
            eventTime="2026-11-01",
            appliesTo=[{"kind": "metric", "id": "budget"}],
        ),
        body="采购进度调整；此说明在历史截止时间之后登记。".encode(),
    )
    await documents.ingest_revision(await documents.claim_next())
    detail = await documents.get_document(token, scope, "later-background")
    await documents.review_revision(
        token,
        scope,
        "later-background",
        1,
        decision="approved",
        reason="合成原文核对",
        expected_version=detail["revisions"][0]["stateVersion"],
    )
    evidence = evidence_service(document_context, index_context)
    release = await evidence.publish(
        token,
        scope,
        request_id="historical-background-release",
        kind="background",
        revision_ids=(DocumentRevisionRef(document_id="later-background", revision=1),),
    )
    await basis_context["policy_service"].set_default(
        token,
        scope,
        "budget_execution",
        policy_version={"policyId": "monthly-budget", "revision": 1},
        expected_version=1,
        background_release_id=release.release_id,
    )
    bases = ReportBasisService(basis_context["scopes"])
    request = {
        "reportGoal": "按当时可知材料解释预算",
        "scenario": "budget_execution",
        "period": {"start": "2026-11-01", "end": "2026-11-30"},
        "comparisonRoles": [],
        "knowledgeAsOf": cutoff.isoformat(),
    }
    basis = await bases.register_request_basis(
        "run-basis",
        scope,
        user_id="7",
        thread_id="thread-basis",
        request=request,
        build_identity=build_identity(),
    )
    calls = []
    original = evidence.index.search

    async def watched(*args, **kwargs):
        calls.append(kwargs.get("document_keys"))
        return await original(*args, **kwargs)

    monkeypatch.setattr(evidence.index, "search", watched)
    historical = await search(evidence, bases, basis_context, kind="background")
    assert historical.search.status == "inapplicable" and not historical.search.hits and not calls
    assert historical.search.request.knowledge_as_of == cutoff
    # 当前视角另建运行，不改历史运行的截止时间或引用。
    await basis_context["provider"].register_run(
        "run-current-background",
        scope,
        user_id="7",
        thread_id="thread-current-background",
        entrypoint="cli",
    )
    current_basis = await bases.register_request_basis(
        "run-current-background",
        scope,
        user_id="7",
        thread_id="thread-current-background",
        request={k: v for k, v in request.items() if k != "knowledgeAsOf"},
        build_identity=build_identity(),
    )
    current = await evidence.search_report(
        bases,
        run_id="run-current-background",
        scope=scope,
        user_id="7",
        thread_id="thread-current-background",
        kind="background",
        query="采购进度变化",
    )
    assert current.search.status == "matched" and len(calls) == 1
    assert (
        current.search.hits[0].recorded_at > basis.knowledge_as_of
        and current.search.hits[0].event_time.isoformat() == "2026-11-01"
    )
    assert (
        current_basis.policy_version == basis.policy_version
        and current_basis.background_release_id == basis.background_release_id
    )
    assert (
        await bases.load_report_basis("run-basis", scope, user_id="7", thread_id="thread-basis")
        == basis
    )

    import json
    import os
    from pathlib import Path

    output = Path('/tmp') / f'smart-reporting-knowledge-cutoff-{os.getpid()}'
    output.mkdir()
    (output/'temporal-evidence.json').write_text(json.dumps({
        'publicRequest':request, 'historicalBasis':basis.model_dump(mode='json'),
        'currentBasis':current_basis.model_dump(mode='json'),
        'historicalSearch':historical.model_dump(mode='json'), 'currentSearch':current.model_dump(mode='json'),
        'indexSearchCalls':len(calls), 'historicalBasisUnchanged':True,
        'fixtureScope':'真实隔离PG/Agno PgVector/原件，合成固定向量；非完整报告/中文召回/真实模型/StarRocks/业务确认'},ensure_ascii=False,indent=2))
