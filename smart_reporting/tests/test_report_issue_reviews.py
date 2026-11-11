"""报告反馈保持原修订身份；采纳不冒充修复，管理裁定使用CAS。"""

import asyncio

import pytest
from sqlalchemy import func, select

from smart_reporting.tests.test_report_basis_persistence import (
    auth_context as auth_context,
)
from smart_reporting.tests.test_report_basis_persistence import (
    basis_context as basis_context,
)
from smart_reporting.tests.test_report_basis_persistence import (
    document_context as document_context,
)
from smart_reporting.tests.test_report_basis_persistence import (
    index_context as index_context,
)
from smart_reporting.tests.test_report_basis_persistence import (
    request_summary,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def issue_context(basis_context):
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.report_issue_reviews import ReportIssueReviewService
    from smart_reporting.reporting.semantics.models import BuildIdentity

    bases = ReportBasisService(basis_context['scopes'])
    basis = await bases.register_report_basis('run-basis', basis_context['scope'], user_id='7',
        thread_id='thread-basis', request_summary=request_summary(basis_context['scope_id']),
        build_identity=BuildIdentity(commit='a' * 40, sourceHash='b' * 64,
            dependencyHash='c' * 64, compilerVersion='semantic-v1'))
    service = ReportIssueReviewService(bases)
    binding = dict(run_id='run-basis', scope=basis_context['scope'], user_id='7', thread_id='thread-basis',
        basis_id=basis.id, report_id='report-budget', revision=2)
    return basis_context, service, binding


def submission(issue_id='issue-C02', **changes):
    return dict(issueId=issue_id, objectRefs=['fact-rate'], category='calculation',
        description='总执行率不能取各项目执行率的算术平均，应由实际合计除以预算合计。', **changes)


async def test_report_issue_submission_is_durable_idempotent_and_keeps_original_binding(issue_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_issue_reviews import ReportIssueReviewService
    from smart_reporting.management.repository import audit_events

    ctx, service, binding = issue_context
    first, duplicate = await asyncio.gather(*(service.submit(**binding,
        allowed_object_refs=('fact-rate',), payload=submission()) for _ in range(2)))
    assert first == duplicate
    assert first['version'] == 1 and first['review']['status'] == 'open'
    assert first['review']['objectRefs'] == ['fact-rate']
    assert first['reportId'] == 'report-budget' and first['revision'] == 2
    rebuilt = ReportIssueReviewService(service.bases)
    assert (await rebuilt.report_list(**binding))['items'] == [first]
    with pytest.raises(ManagementError) as conflict:
        await service.submit(**binding, allowed_object_refs=('fact-rate',),
            payload={**submission(), 'description': '同一身份的另一条内容'})
    assert conflict.value.status == 409
    assert (await service.report_list(**{**binding, 'revision': 3}))['items'] == []
    async with ctx['repository'].transaction() as connection:
        assert await connection.scalar(select(func.count()).select_from(audit_events)
            .where(audit_events.c.action == 'report_issue_submitted')) == 1


async def test_report_issue_rejects_foreign_identity_basis_and_unregistered_objects(issue_context):
    from smart_reporting.management.models import ManagementError

    ctx, service, binding = issue_context
    for changes in ({'user_id': 'foreign'}, {'thread_id': 'foreign'}, {'scope': ctx['other_scope']},
                    {'basis_id': 'foreign-basis'}):
        with pytest.raises(ManagementError) as rejected:
            await service.submit(**{**binding, **changes}, allowed_object_refs=('fact-rate',), payload=submission())
        assert rejected.value.status in (403, 404, 409)
    with pytest.raises(ManagementError) as foreign_object:
        await service.submit(**binding, allowed_object_refs=('other-fact',), payload=submission())
    assert foreign_object.value.status == 403
    assert (await service.report_list(**binding))['items'] == []


async def test_admin_acceptance_records_proposed_fix_counterexample_and_cas_without_publishing(issue_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.repository import metric_versions, report_bases

    ctx, service, binding = issue_context
    await service.submit(**binding, allowed_object_refs=('fact-rate',), payload=submission())
    proposal = {'changeSummary': '将项目执行率均值替换为合计实际/合计预算',
        'counterexample': '预算100、200，实际90、100；均值70%错误，190/300应展示63.33%。'}
    decision = {'expectedVersion': 1, 'status': 'accepted', 'decisionReason': '独立行级汇总证实平均比率有偏',
        'proposal': proposal}
    with pytest.raises(ManagementError) as no_proposal:
        await service.decide(ctx['token'], ctx['scope'], 'issue-C02', {**decision, 'proposal': None})
    assert no_proposal.value.status == 422
    results = await asyncio.gather(*(service.decide(ctx['token'], ctx['scope'], 'issue-C02', decision)
        for _ in range(2)), return_exceptions=True)
    accepted = next(item for item in results if isinstance(item, dict))
    assert accepted['version'] == 2 and accepted['review']['status'] == 'accepted'
    assert accepted['proposal'] == proposal
    assert sum(isinstance(item, ManagementError) and item.status == 409 for item in results) == 1
    assert (await service.report_list(**binding))['items'][0] == accepted
    assert (await service.admin_list(ctx['token'], ctx['other_scope']))['items'] == []
    async with ctx['repository'].transaction() as connection:
        assert await connection.scalar(select(func.count()).select_from(metric_versions)) == 1
        assert await connection.scalar(select(func.count()).select_from(report_bases)) == 1


async def test_report_issue_resolution_never_accepts_claimed_regression_ids_as_verified_evidence(issue_context):
    from smart_reporting.management.models import ManagementError

    ctx, service, binding = issue_context
    await service.submit(**binding, allowed_object_refs=('fact-rate',), payload=submission())
    with pytest.raises(ManagementError) as unproven:
        await service.decide(ctx['token'], ctx['scope'], 'issue-C02', {'expectedVersion': 1,
            'status': 'resolved', 'decisionReason': '声称修复',
            'correctedVersions': [{'assetType': 'metric', 'assetId': 'budget', 'revision': 1}],
            'regressionCaseIds': ['C02'], 'notRecalculatedReason': '声称无需重算'})
    assert unproven.value.status == 409
    assert unproven.value.code == 'management_issue_resolution_unverified'
    assert (await service.report_list(**binding))['items'][0]['review']['status'] == 'open'


async def test_management_issue_http_uses_real_storage_auth_csrf_and_scope(issue_context):
    import httpx
    from fastapi import FastAPI

    from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
    from smart_reporting.management.settings import ManagementSettings

    ctx, service, binding = issue_context
    await service.submit(**binding, allowed_object_refs=('fact-rate',), payload=submission())
    app = FastAPI()
    app.include_router(create_management_router(ctx['scopes'].auth, ManagementSettings(public_origin='https://reports.example')))
    params = {'scopeDatabase': ctx['scope'].database, 'companyId': ctx['scope'].company_id}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        path = '/management/api/v1/report-issue-reviews'
        assert (await client.get(path, params=params)).status_code == 401
        client.cookies.set(SESSION_COOKIE, ctx['token'], path='/management')
        listed = await client.get(path, params=params)
        assert listed.status_code == 200
        assert listed.headers['cache-control'] == 'no-store'
        assert listed.json()['items'][0]['review']['issueId'] == 'issue-C02'
        assert (await client.get(path, params={**params, 'companyId': ctx['other_scope'].company_id})).json()['items'] == []
        decision = {**params, 'expectedVersion': 1, 'status': 'accepted', 'decisionReason': '合计比例应为63.33%',
            'proposal': {'changeSummary': '使用分子分母合计', 'counterexample': '100/200预算与90/100实际，平均比率70%错误'}}
        assert (await client.post(path + '/issue-C02/decision', json=decision)).status_code == 403
        headers = {'origin': 'https://reports.example', 'x-csrf-token': csrf_token(ctx['token'])}
        assert (await client.post(path + '/issue-C02/decision', json={**decision, 'scopeId': ctx['scope_id']}, headers=headers)).status_code == 422
        response = await client.post(path + '/issue-C02/decision', json=decision, headers=headers)
        assert response.status_code == 200 and response.json()['review']['status'] == 'accepted'
        assert response.headers['cache-control'] == 'no-store'
        assert (await client.post(path + '/issue-C02/decision', json=decision, headers=headers)).status_code == 409


async def test_submission_commit_response_loss_reads_exact_issue_without_recreating(issue_context, monkeypatch):
    from contextlib import asynccontextmanager

    ctx, service, binding = issue_context
    original = ctx['repository'].transaction

    @asynccontextmanager
    async def lost_response():
        async with original() as connection:
            yield connection
        raise ConnectionError('response lost after actual commit')

    with monkeypatch.context() as fault:
        fault.setattr(ctx['repository'], 'transaction', lost_response)
        with pytest.raises(ConnectionError):
            await service.submit(**binding, allowed_object_refs=('fact-rate',), payload=submission())
    result = await service.report_list(**binding, issue_id='issue-C02')
    assert len(result['items']) == 1 and result['items'][0]['version'] == 1
    assert (await service.report_list(**binding, issue_id='unknown-issue'))['items'] == []
    await service.submit(**binding, allowed_object_refs=('fact-rate',), payload=submission('issue-other'))
    first = await service.report_list(**binding, limit=1)
    second = await service.report_list(**binding, limit=1, after=first['nextCursor'])
    assert [first['items'][0]['review']['issueId'], second['items'][0]['review']['issueId']] == ['issue-C02', 'issue-other']
    assert second['nextCursor'] is None


async def publish_fix(ctx):
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.reporting.tests.test_semantic_models import metric_payload

    metrics = MetricService(ctx['scopes'])
    body = metric_payload(name='核对原始字段后的预算额')
    body.pop('scopeId')
    body.pop('revision')
    await metrics.save_draft(ctx['token'], ctx['scope'], body, 1)
    await metrics.publish(ctx['token'], ctx['scope'], 'budget', expected_version=2)
    policies = ctx['policy_service']
    original = await policies.get(ctx['token'], ctx['scope'], 'monthly-budget')
    body = {key: value for key, value in original['draft']['document'].items() if key not in ('scopeId', 'revision')}
    await policies.save_draft(ctx['token'], ctx['scope'], {**body, 'metricVersions': [{'metricId': 'budget', 'revision': 2}]}, expected_version=1)
    await policies.publish(ctx['token'], ctx['scope'], 'monthly-budget', expected_version=2)


def accepted_fix(**changes):
    return {'expectedVersion': 1, 'status': 'accepted', 'decisionReason': '管理员核对候选并关联正式发布；仍须回归验证',
        'proposal': {'changeSummary': '核对并修订取数字段', 'counterexample': '预算合计300，实际合计190，应为63.33%，不能用70%'},
        'correctedVersions': [{'assetType': 'metric', 'assetId': 'budget', 'revision': 2},
            {'assetType': 'statistical_policy', 'assetId': 'monthly-budget', 'revision': 2}], **changes}


async def test_accepted_issue_links_exact_published_fix_versions_without_claiming_resolved(issue_context):
    from smart_reporting.management.repository import audit_events

    ctx, service, binding = issue_context
    await service.submit(**binding, allowed_object_refs=('fact-rate',), payload=submission())
    await publish_fix(ctx)
    decision = accepted_fix()
    result = await service.decide(ctx['token'], ctx['scope'], 'issue-C02', decision)
    assert result['review']['status'] == 'accepted'
    assert result['review']['correctedVersions'] == decision['correctedVersions']
    assert result['review']['regressionCaseIds'] == []
    assert result['review']['newReportRevision'] is None
    assert (await service.report_list(**binding))['items'][0] == result
    basis = await service.bases.load_report_basis('run-basis', ctx['scope'], user_id='7', thread_id='thread-basis')
    assert basis.policy_version.revision == 1 and basis.metric_versions[0].revision == 1
    async with ctx['repository'].transaction() as connection:
        event = (await connection.execute(select(audit_events).where(audit_events.c.action == 'report_issue_decided'))).mappings().one()
        assert event['details']['correctedVersions'] == decision['correctedVersions']
    # 后续理由裁定不静默清除已关联修复；明确空数组才能解除关联。
    without_links = {key: value for key, value in decision.items() if key != 'correctedVersions'}
    preserved = await service.decide(ctx['token'], ctx['scope'], 'issue-C02', {**without_links, 'expectedVersion': 2})
    assert preserved['review']['correctedVersions'] == decision['correctedVersions']
    cleared = await service.decide(ctx['token'], ctx['scope'], 'issue-C02', {**decision, 'expectedVersion': 3, 'correctedVersions': []})
    assert cleared['review']['correctedVersions'] == []


async def test_issue_fix_options_use_published_history_scope_and_explicit_eligibility(issue_context):
    import httpx
    from fastapi import FastAPI

    from smart_reporting.management.api import SESSION_COOKIE, create_management_router
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.settings import ManagementSettings

    ctx, service, binding = issue_context
    await service.submit(**binding, allowed_object_refs=('fact-rate',), payload=submission())
    await publish_fix(ctx)
    app = FastAPI()
    app.include_router(create_management_router(ctx['scopes'].auth, ManagementSettings(public_origin='https://reports.example')))
    path = '/management/api/v1/report-issue-reviews/issue-C02/fix-options'
    params = {'scopeDatabase': ctx['scope'].database, 'companyId': ctx['scope'].company_id, 'assetType': 'metric', 'limit': 1}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        assert (await client.get(path, params=params)).status_code == 401
        client.cookies.set(SESSION_COOKIE, ctx['token'], path='/management')
        first = await client.get(path, params=params)
        assert first.status_code == 200
        assert first.headers['cache-control'] == 'no-store'
        old = first.json()['items'][0]
        assert old['reference'] == {'assetType': 'metric', 'assetId': 'budget', 'revision': 1}
        assert old['available'] is False and old['reason']
        second = await client.get(path, params={**params, 'after': first.json()['nextCursor']})
        new = second.json()['items'][0]
        assert new['reference']['revision'] == 2 and new['available'] is True and new['name']
        assert second.json()['nextCursor'] is None
        policies = await client.get(path, params={**params, 'assetType': 'statistical_policy', 'limit': 100})
        assert [(item['reference']['revision'], item['available']) for item in policies.json()['items']] == [(1, False), (2, True)]
        releases = await client.get(path, params={**params, 'assetType': 'evidence_release'})
        assert releases.json()['items'][0]['reference']['revision'] is None
        assert releases.json()['items'][0]['available'] is False
        await MetricService(ctx['scopes']).retire(ctx['token'], ctx['scope'], 'budget', 2, reason='合成退役测试')
        retired = await client.get(path, params={**params, 'q': 'budget', 'limit': 100})
        assert all(not item['available'] for item in retired.json()['items'])
        assert (await client.get(path, params={**params, 'q': 'no-match'})).json()['items'] == []
        assert (await client.get(path, params={**params, 'after': 'invalid'})).status_code == 422
        assert (await client.get(path, params={**params, 'companyId': ctx['other_scope'].company_id})).status_code == 404
        assert (await client.get(path, params={**params, 'assetType': 'unknown'})).status_code == 422


async def test_issue_fix_rejects_original_draft_foreign_retired_and_mismatched_versions(issue_context):
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.models import ManagementError
    from smart_reporting.reporting.tests.test_semantic_models import metric_payload

    ctx, service, binding = issue_context
    await service.submit(**binding, allowed_object_refs=('fact-rate',), payload=submission())
    await publish_fix(ctx)
    metrics = MetricService(ctx['scopes'])
    body = metric_payload(name='尚未发布的第三版草稿')
    body.pop('scopeId')
    body.pop('revision')
    await metrics.save_draft(ctx['token'], ctx['scope'], body, 2)
    foreign = {**body, 'id': 'foreign-only'}
    await metrics.save_draft(ctx['token'], ctx['other_scope'], foreign, 0)
    await metrics.publish(ctx['token'], ctx['other_scope'], 'foreign-only', expected_version=1)
    candidates = [
        ([{'assetType': 'metric', 'assetId': 'budget', 'revision': 1}], 'management_issue_fix_unchanged'),
        ([{'assetType': 'metric', 'assetId': 'budget', 'revision': 3}], 'management_policy_metric_missing'),
        ([{'assetType': 'metric', 'assetId': 'foreign-only', 'revision': 1}], 'management_policy_metric_missing'),
        ([{'assetType': 'metric', 'assetId': 'budget', 'revision': 2}] * 2, 'management_issue_invalid'),
    ]
    for refs, code in candidates:
        with pytest.raises(ManagementError) as rejected:
            await service.decide(ctx['token'], ctx['scope'], 'issue-C02', accepted_fix(correctedVersions=refs))
        assert rejected.value.code == code
    policies = ctx['policy_service']
    latest = await policies.get(ctx['token'], ctx['scope'], 'monthly-budget')
    old_dependencies = {key: value for key, value in latest['draft']['document'].items() if key not in ('scopeId', 'revision')}
    await policies.save_draft(ctx['token'], ctx['scope'], {**old_dependencies, 'metricVersions': [{'metricId': 'budget', 'revision': 1}]}, expected_version=2)
    await policies.publish(ctx['token'], ctx['scope'], 'monthly-budget', expected_version=3)
    with pytest.raises(ManagementError) as mismatch:
        await service.decide(ctx['token'], ctx['scope'], 'issue-C02', accepted_fix(correctedVersions=[
            {'assetType': 'metric', 'assetId': 'budget', 'revision': 2},
            {'assetType': 'statistical_policy', 'assetId': 'monthly-budget', 'revision': 3}]))
    assert mismatch.value.code == 'management_issue_fix_dependency_mismatch'
    await metrics.retire(ctx['token'], ctx['scope'], 'budget', 2, reason='回归发现仍有边界问题')
    for refs in ([{'assetType': 'metric', 'assetId': 'budget', 'revision': 2}],
                 [{'assetType': 'statistical_policy', 'assetId': 'monthly-budget', 'revision': 2}]):
        with pytest.raises(ManagementError) as retired:
            await service.decide(ctx['token'], ctx['scope'], 'issue-C02', accepted_fix(correctedVersions=refs))
        assert retired.value.code == 'management_semantic_asset_retired'
    original = (await service.report_list(**binding))['items'][0]
    assert original['version'] == 1 and original['review']['status'] == 'open'
    assert original['review']['correctedVersions'] == []


async def test_issue_fix_links_published_document_and_evidence_but_rejects_original_or_revoked(issue_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_issue_fix_options import list_fix_options
    from smart_reporting.reporting.business_knowledge.retrieval import DocumentRevisionRef
    from smart_reporting.tests.test_business_document_ingestion import metadata

    ctx, service, binding = issue_context
    evidence = ctx['policy_service'].evidence
    documents = evidence.documents
    await service.submit(**binding, allowed_object_refs=('fact-rate',), payload=submission())
    uploaded = await documents.register_document(ctx['token'], ctx['scope'],
        '合成更正说明：分别合计预算与执行额后求比率。'.encode(), filename='correction.txt', metadata=metadata(),
        request_id='correction-upload', expected_version=1)
    await documents.ingest_revision(await documents.claim_next())
    detail = await documents.get_document(ctx['token'], ctx['scope'], 'budget-rules')
    state = next(item['stateVersion'] for item in detail['revisions'] if item['revision'] == uploaded.revision)
    await documents.review_revision(ctx['token'], ctx['scope'], 'budget-rules', 2, decision='approved', reason='核对合成更正原文', expected_version=state)
    with pytest.raises(ManagementError) as unpublished:
        await service.decide(ctx['token'], ctx['scope'], 'issue-C02', accepted_fix(correctedVersions=[
            {'assetType': 'document', 'assetId': 'budget-rules', 'revision': 2}]))
    assert unpublished.value.code == 'management_issue_fix_unavailable'
    options = await list_fix_options(service, ctx['token'], ctx['scope'], 'issue-C02', asset_type='document')
    assert all(item['reference']['revision'] != 2 for item in options['items'])
    release = await evidence.publish(ctx['token'], ctx['scope'], request_id='correction-release', kind='rule_evidence',
        revision_ids=(DocumentRevisionRef(document_id='budget-rules', revision=2),))
    options = await list_fix_options(service, ctx['token'], ctx['scope'], 'issue-C02', asset_type='document')
    assert [(item['reference']['revision'], item['available']) for item in options['items']] == [(1, False), (2, True)]
    for refs in ([{'assetType': 'document', 'assetId': 'budget-rules', 'revision': 1}],
                 [{'assetType': 'evidence_release', 'assetId': ctx['release_id']}],
                 [{'assetType': 'evidence_release', 'assetId': 'foreign-release'}]):
        with pytest.raises(ManagementError):
            await service.decide(ctx['token'], ctx['scope'], 'issue-C02', accepted_fix(correctedVersions=refs))
    refs = [{'assetType': 'document', 'assetId': 'budget-rules', 'revision': 2},
        {'assetType': 'evidence_release', 'assetId': release.release_id}]
    accepted = await service.decide(ctx['token'], ctx['scope'], 'issue-C02', accepted_fix(correctedVersions=refs))
    assert [ref['assetType'] for ref in accepted['review']['correctedVersions']] == ['document', 'evidence_release']
    detail = await documents.get_document(ctx['token'], ctx['scope'], 'budget-rules')
    state = next(item['stateVersion'] for item in detail['revisions'] if item['revision'] == 2)
    await documents.review_revision(ctx['token'], ctx['scope'], 'budget-rules', 2, decision='revoked', reason='撤销该更正说明', expected_version=state)
    options = await list_fix_options(service, ctx['token'], ctx['scope'], 'issue-C02', asset_type='document')
    assert all(not item['available'] for item in options['items'])
    for ref in refs:
        with pytest.raises(ManagementError) as revoked:
            await service.decide(ctx['token'], ctx['scope'], 'issue-C02', accepted_fix(expectedVersion=2, correctedVersions=[ref]))
        assert revoked.value.code == 'management_issue_fix_unavailable'
    assert (await service.report_list(**binding))['items'][0] == accepted


async def test_http_decision_preserves_linked_fix_when_field_omitted(issue_context):
    import httpx
    from fastapi import FastAPI

    from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
    from smart_reporting.management.settings import ManagementSettings

    ctx, service, binding = issue_context
    await service.submit(**binding, allowed_object_refs=('fact-rate',), payload=submission())
    await publish_fix(ctx)
    app = FastAPI()
    app.include_router(create_management_router(ctx['scopes'].auth, ManagementSettings(public_origin='https://reports.example')))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        client.cookies.set(SESSION_COOKIE, ctx['token'], path='/management')
        headers = {'origin': 'https://reports.example', 'x-csrf-token': csrf_token(ctx['token'])}
        params = {'scopeDatabase': ctx['scope'].database, 'companyId': ctx['scope'].company_id}
        path = '/management/api/v1/report-issue-reviews/issue-C02/decision'
        first = await client.post(path, json={**params, **accepted_fix()}, headers=headers)
        assert first.status_code == 200
        omitted = {key: value for key, value in accepted_fix(expectedVersion=2).items() if key != 'correctedVersions'}
        second = await client.post(path, json={**params, **omitted}, headers=headers)
        assert second.status_code == 200
        assert second.json()['review']['correctedVersions'] == first.json()['review']['correctedVersions']


async def test_fix_link_audit_failure_rolls_back_and_lost_commit_response_is_readable(issue_context, monkeypatch):
    from contextlib import asynccontextmanager

    from smart_reporting.management.repository import audit_events

    ctx, service, binding = issue_context
    await service.submit(**binding, allowed_object_refs=('fact-rate',), payload=submission())
    await publish_fix(ctx)

    async def failed_audit(*args, **kwargs):
        raise RuntimeError('audit write failed')

    with monkeypatch.context() as fault:
        fault.setattr(ctx['scopes'], 'audit', failed_audit)
        with pytest.raises(RuntimeError, match='audit write failed'):
            await service.decide(ctx['token'], ctx['scope'], 'issue-C02', accepted_fix())
    original = (await service.report_list(**binding))['items'][0]
    assert original['version'] == 1 and original['review']['correctedVersions'] == []
    transaction = ctx['scopes'].write_transaction

    @asynccontextmanager
    async def lost_response(actor):
        async with transaction(actor) as connection:
            yield connection
        raise ConnectionError('fix link committed but response lost')

    with monkeypatch.context() as fault:
        fault.setattr(ctx['scopes'], 'write_transaction', lost_response)
        with pytest.raises(ConnectionError):
            await service.decide(ctx['token'], ctx['scope'], 'issue-C02', accepted_fix())
    restored = (await service.admin_list(ctx['token'], ctx['scope'], issue_id='issue-C02'))['items'][0]
    assert restored['version'] == 2 and restored['review']['status'] == 'accepted'
    assert restored['review']['correctedVersions'] == accepted_fix()['correctedVersions']
    async with ctx['repository'].transaction() as connection:
        assert await connection.scalar(select(func.count()).select_from(audit_events)
            .where(audit_events.c.action == 'report_issue_decided')) == 1
