"""口径编辑：同次隔离PG、真实HTTP和浏览器，不替换业务响应。"""

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from smart_reporting.reporting.tests.test_business_evidence_index import (
    index_context as index_context,
)
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_management_statistical_policies import policy_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_browser_edits_previews_and_publishes_policy_without_changing_default(document_context, index_context):
    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.business_evidence_api import create_business_evidence_router
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.metrics_api import create_metrics_router
    from smart_reporting.management.repository import audit_events
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.management.statistical_policy_api import create_statistical_policy_router
    from smart_reporting.reporting.business_knowledge.retrieval import DocumentRevisionRef
    from smart_reporting.reporting.semantics.models import PolicyVersionRef
    from smart_reporting.tests.report_issue_browser_flow import run_management_browser
    from smart_reporting.tests.test_business_document_ingestion import metadata, register

    service, definition = await policy_context(document_context, index_context)
    token, scope = document_context[1:3]
    definition = {**definition, 'filters': [{'fieldRef': 'warehouse.test.budget.project_id', 'operator': 'eq', 'values': ['A'] }],
        'readinessPolicy': {'watermarkField': 'warehouse.test.budget.updated_at', 'maximumDelaySeconds': 3600}}
    await service.save_draft(token, scope, definition, expected_version=0)
    original = await service.publish(token, scope, 'monthly-budget', expected_version=1)
    await service.set_default(token, scope, 'budget_execution', policy_version=PolicyVersionRef(policy_id='monthly-budget', revision=1), expected_version=0)
    old_default = await service.get_default(token, scope, 'budget_execution')
    original_document = await document_context[0].get_document(token, scope, 'budget-rules')
    await register(document_context, 'upload-rules-2', expected_version=1,
        body='执行额合计÷预算额合计，不能平均各组比率。\n项目B需单独核对全年期间。'.encode(),
        details=metadata(title='修订预算管理制度'))
    await document_context[0].ingest_revision(await document_context[0].claim_next())
    document = await document_context[0].get_document(token, scope, 'budget-rules')
    await document_context[0].review_revision(token, scope, 'budget-rules', 2, decision='approved',
        reason='核对第二份合成原文', expected_version=document['revisions'][0]['stateVersion'])
    target_evidence = await service.evidence.publish(token, scope, request_id='release-rules-2', kind='rule_evidence',
        revision_ids=(DocumentRevisionRef(document_id='budget-rules', revision=2),))
    app = FastAPI()
    settings = ManagementSettings(public_origin='http://127.0.0.1:5199', allow_local_http=True)
    app.include_router(create_management_router(service.scopes.auth, settings))
    app.include_router(create_statistical_policy_router(service, settings))
    app.include_router(create_metrics_router(MetricService(service.scopes), settings))
    app.include_router(create_business_evidence_router(service.evidence, settings))
    app.include_router(create_business_documents_router(document_context[0], settings))
    output = Path('/tmp') / f'smart-reporting-policy-editor-browser-{os.getpid()}'
    output.mkdir()
    browser = await run_management_browser(app, {'token': token, 'database': scope.database, 'companyId': scope.company_id,
        'targetEvidenceReleaseId': target_evidence.release_id}, output, script='smoke/management-policy-editor-postgres-smoke.mjs')
    assert browser['saves'] == browser['publications'] == browser['previews'] == 1
    current = await service.get(token, scope, 'monthly-budget')
    assert current['draft']['version'] == current['published']['revision'] == 2
    assert current['published']['document']['name'] == '修订预算口径'
    assert current['published']['document']['decisionNotes'] == '筛选项目B，明确全年期间和预期对象，采用明确修订的制度依据。'
    assert current['published']['document']['filters'][0]['values'] == ['B']
    assert original['document']['filters'][0]['values'] == ['A']
    readiness = current['published']['document']['readinessPolicy']
    assert readiness['expectedPeriods'] == [{'start': '2026-01-01', 'end': '2027-01-01'}]
    assert readiness['expectedGroups'] == [[{'dimensionId': 'project', 'value': 'B'}]]
    for field in ('watermarkField', 'maximumDelaySeconds', 'emptyObservation'):
        assert readiness[field] == original['document']['readinessPolicy'][field]
    for field in ('joins', 'metricVersions'):
        assert current['published']['document'][field] == original['document'][field]
    assert current['published']['document']['evidenceReleaseId'] == target_evidence.release_id
    assert original['document']['evidenceReleaseId'] != target_evidence.release_id
    assert (await document_context[0].get_document(token, scope, 'budget-rules'))['revisions'][1] == original_document['revisions'][0]
    assert (await service.get(token, scope, 'monthly-budget', revision=1))['published']['contentHash'] == original['contentHash']
    assert await service.get_default(token, scope, 'budget_execution') == old_default
    async with service.repository.transaction() as connection:
        audits = list((await connection.execute(select(audit_events.c.action).where(audit_events.c.action.in_([
            'statistical_policy_draft_saved', 'statistical_policy_published', 'report_policy_default_set',
        ])))).scalars())
    assert audits.count('statistical_policy_draft_saved') == audits.count('statistical_policy_published') == 2
    assert audits.count('report_policy_default_set') == 1
    (output / 'database-evidence.json').write_text(json.dumps({'original': original, 'current': current,
        'default': old_default, 'auditActions': audits, 'targetEvidence': target_evidence.model_dump(mode='json'),
        'originalDocument': original_document, 'currentDocument': await document_context[0].get_document(token, scope, 'budget-rules'),
        'fixtureScope': '合成制度原件和隔离PG；非真实模型、StarRocks或业务签认'}, ensure_ascii=False, indent=2))
