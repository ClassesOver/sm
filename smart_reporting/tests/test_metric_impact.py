"""精确指标版本影响沿不可变依赖及实际冻结依据读取。"""

import pytest
from sqlalchemy import insert

from smart_reporting.reporting.tests.test_business_evidence_index import (
    index_context as index_context,
)
from smart_reporting.reporting.tests.test_semantic_models import metric_payload, ratio_payload
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_management_metrics import draft
from smart_reporting.tests.test_management_metrics_api import metric_client as metric_client
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_management_statistical_policies import policy_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_metric_impact_exact_transitive_pagination_and_frozen_reports(document_context, index_context):
    import json
    import os
    from pathlib import Path

    from fastapi import FastAPI

    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.business_documents import _digest
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.metrics_api import create_metrics_router
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.repository import report_bases
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.reporting.semantics.models import PolicyVersionRef

    policies, definition = await policy_context(document_context, index_context)
    token, scope, other, scope_id, _ = document_context[1:]
    metrics = MetricService(policies.scopes)
    await metrics.save_draft(token, scope, draft(metric_payload('actual')), 0)
    await metrics.publish(token, scope, 'actual', expected_version=1)
    for payload in (ratio_payload(), ratio_payload('outer', numerator='rate', denominator='rate')):
        await metrics.save_draft(token, scope, draft(payload), 0)
        await metrics.publish(token, scope, payload['id'], expected_version=1)
    definition = {**definition, 'metricVersions': [{'metricId': 'outer', 'revision': 1}]}
    await policies.save_draft(token, scope, definition, expected_version=0)
    published = await policies.publish(token, scope, 'monthly-budget', expected_version=1)
    await policies.set_default(token, scope, 'budget_execution', policy_version=PolicyVersionRef(policy_id='monthly-budget', revision=1), expected_version=0)
    await metrics.save_draft(token, scope, draft(metric_payload()), 1)
    await metrics.publish(token, scope, 'budget', expected_version=2)
    # 同组织同名指标2版、另组织同名指标1版均不得混入1版影响。
    for payload in (metric_payload('budget'), metric_payload('actual'), ratio_payload('foreign-rate')):
        await metrics.save_draft(token, other, draft(payload), 0)
        await metrics.publish(token, other, payload['id'], expected_version=1)
    async with policies.repository.transaction() as connection:
        for run, metric_revision in [('old-run', 1), ('new-run', 2)]:
            body = {'id': 'basis-' + run, 'metricVersions': [{'metricId': 'budget', 'revision': metric_revision}]}
            await connection.execute(insert(report_bases).values(scope_id=scope_id, run_id=run, basis_id=body['id'],
                policy_id='monthly-budget', policy_revision=1, evidence_release_id=published['document']['evidenceReleaseId'],
                document=body, content_hash=_digest(body), registered_at=policies.scopes.auth.clock()))
    pages, after = [], None
    while True:
        result = await metrics.impact(token, scope, 'budget', revision=1, limit=1, after=after)
        pages.extend(result['items'])
        after = result['nextCursor']
        if after is None:
            break
    assert [(item['kind'], item['referenceId']) for item in pages] == [
        ('default', 'budget_execution'), ('metric', 'outer'), ('metric', 'rate'), ('policy', 'monthly-budget'), ('report', 'old-run')]
    assert pages[1]['revision'] == pages[2]['revision'] == 1
    assert pages[-1]['basisId'] == 'basis-old-run'
    assert pages[0]['policyVersion'] == {'policyId': 'monthly-budget', 'revision': 1}
    assert [item['referenceId'] for item in (await metrics.impact(token, scope, 'budget', revision=2))['items']] == ['new-run']
    assert (await metrics.impact(token, scope, 'budget', revision=1))['items'] == pages
    for kwargs in ({'revision': True}, {'revision': 1, 'limit': 0}, {'revision': 1, 'after': 'x' * 301}):
        with pytest.raises(ManagementError) as invalid:
            await metrics.impact(token, scope, 'budget', **kwargs)
        assert invalid.value.status == 422
    with pytest.raises(ManagementError) as absent:
        await metrics.impact(token, other, 'budget', revision=2)
    assert absent.value.status == 404
    app = FastAPI()
    settings = ManagementSettings(public_origin='http://127.0.0.1:5196', allow_local_http=True)
    app.include_router(create_management_router(policies.scopes.auth, settings))
    app.include_router(create_metrics_router(metrics, settings))
    from smart_reporting.tests.report_issue_browser_flow import run_management_browser

    out = Path('/tmp') / f'smart-reporting-metric-impact-browser-{os.getpid()}'
    out.mkdir()
    evidence = await run_management_browser(app, {'token': token, 'database': scope.database, 'companyId': scope.company_id},
        out, script='smoke/management-metric-postgres-smoke.mjs')
    assert evidence['writeRequests'] == 1 and evidence['historicalVersionPreserved']
    assert (await metrics.get(token, scope, 'budget', revision=1))['retirement']['reason'] == '合成退役'
    assert (await metrics.get(token, scope, 'budget', revision=1))['retirement']['replacement'] == {'metricId': 'budget', 'revision': 2}
    assert (await metrics.impact(token, scope, 'budget', revision=1))['items'] == pages
    default = await policies.get_default(token, scope, 'budget_execution')
    assert default['policyVersion'] == {'policyId': 'monthly-budget', 'revision': 1}
    assert any(issue['code'] == 'semantic_asset_retired' for issue in default['issues'])
    from sqlalchemy import select

    from smart_reporting.management.repository import audit_events

    async with policies.repository.transaction() as connection:
        audits = (await connection.execute(select(audit_events.c.action).where(audit_events.c.action == 'semantic_asset_retired'))).scalars().all()
    assert audits == ['semantic_asset_retired']
    (out / 'database-evidence.json').write_text(json.dumps({'metricVersion': {'metricId': 'budget', 'revision': 1},
        'items': pages, 'version2': await metrics.impact(token, scope, 'budget', revision=2), 'auditActions': list(audits), 'default': default,
        'fixtureScope': '隔离管理元数据与冻结引用；不是实际报告生成或StarRocks'}, ensure_ascii=False, indent=2))


async def test_metric_impact_http_requires_explicit_revision_scope_and_session(metric_client):
    client, _, service, token, scope, other = metric_client
    await service.save_draft(token, scope, draft(metric_payload()), 0)
    await service.publish(token, scope, 'budget', expected_version=1)
    params = {'scopeDatabase': scope.database, 'companyId': scope.company_id, 'revision': 1}
    path = '/management/api/v1/metrics/budget/impact'
    response = await client.get(path, params=params)
    assert response.status_code == 200
    assert response.json() == {'metricVersion': {'metricId': 'budget', 'revision': 1}, 'items': [], 'nextCursor': None}
    assert response.headers['cache-control'] == 'no-store'
    assert (await client.get(path, params={**params, 'companyId': other.company_id})).status_code == 404
    assert (await client.get(path, params={key: value for key, value in params.items() if key != 'revision'})).status_code == 422
    assert (await client.get(path, params={**params, 'after': 'x' * 301})).status_code == 422
    client.cookies.clear()
    assert (await client.get(path, params=params)).status_code == 401
