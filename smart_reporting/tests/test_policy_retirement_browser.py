"""统计口径退役：真实浏览器、管理HTTP与隔离PG同次核对。"""

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


async def test_browser_retires_exact_policy_and_recovers_committed_response(document_context, index_context):
    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.repository import audit_events
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.management.statistical_policy_api import create_statistical_policy_router
    from smart_reporting.reporting.business_knowledge.retrieval import DocumentRevisionRef
    from smart_reporting.reporting.semantics.models import PolicyVersionRef
    from smart_reporting.tests.report_issue_browser_flow import run_management_browser
    from smart_reporting.tests.test_business_document_ingestion import metadata, register

    service, definition = await policy_context(document_context, index_context)
    token, scope = document_context[1:3]
    await service.save_draft(token, scope, definition, expected_version=0)
    published = await service.publish(token, scope, 'monthly-budget', expected_version=1)
    ref = PolicyVersionRef(policy_id='monthly-budget', revision=1)
    documents = document_context[0]
    await register(document_context, request_id='migration-background-upload', details=metadata(id='migration-background', kind='background'))
    await documents.ingest_revision(await documents.claim_next())
    document = await documents.get_document(token, scope, 'migration-background')
    await documents.review_revision(token, scope, 'migration-background', 1, decision='approved', reason='合成背景核对',
        expected_version=document['revisions'][0]['stateVersion'])
    background = await service.evidence.publish(token, scope, request_id='migration-background-release', kind='background',
        revision_ids=(DocumentRevisionRef(document_id='migration-background', revision=1),))
    await service.set_default(token, scope, 'budget_execution', policy_version=ref, expected_version=0, background_release_id=background.release_id)
    await service.save_draft(token, scope, {**definition, 'name': '合成预算执行修正版'}, expected_version=1)
    await service.publish(token, scope, 'monthly-budget', expected_version=2)
    app = FastAPI()
    settings = ManagementSettings(public_origin='http://127.0.0.1:5194', allow_local_http=True)
    app.include_router(create_management_router(service.scopes.auth, settings))
    app.include_router(create_statistical_policy_router(service, settings))
    out = Path('/tmp') / f'smart-reporting-policy-pg-browser-{os.getpid()}'
    out.mkdir()
    browser = await run_management_browser(app, {'token': token, 'database': scope.database, 'companyId': scope.company_id},
        out, script='smoke/management-policy-postgres-smoke.mjs')
    assert browser['posts'] == browser['defaultWrites'] == 1 and browser['recoveryReads'] >= 1
    assert browser['axe'] == [] and not browser['overflow'] and not browser['errors']
    current = await service.get(token, scope, 'monthly-budget', revision=1)
    assert current['published'] == {key: published[key] for key in ('revision', 'document', 'contentHash')}
    assert current['retirement'] == browser['retirement']
    assert current['retirement']['replacement'] == {'policyId': 'monthly-budget', 'revision': 2}
    default = await service.get_default(token, scope, 'budget_execution')
    assert default['policyVersion'] == {'policyId': 'monthly-budget', 'revision': 2}
    assert default['version'] == 2 and default['issues'] == []
    assert default['backgroundReleaseId'] == background.release_id
    with pytest.raises(ManagementError) as retired:
        await service.set_default(token, scope, 'budget_execution', policy_version=ref, expected_version=2)
    assert retired.value.code == 'management_semantic_asset_retired'
    async with service.repository.transaction() as connection:
        events = (await connection.execute(select(audit_events.c.action).where(audit_events.c.action == 'semantic_asset_retired'))).scalars().all()
        default_events = (await connection.execute(select(audit_events.c.action).where(audit_events.c.action == 'report_policy_default_set'))).scalars().all()
    assert events == ['semantic_asset_retired']
    assert len(default_events) == 2
    (out / 'database-evidence.json').write_text(json.dumps({'publishedUnchanged': True,
        'retirement': current['retirement'], 'default': default, 'auditActions': list(events),
        'defaultAuditCount': len(default_events)}, ensure_ascii=False, indent=2))
