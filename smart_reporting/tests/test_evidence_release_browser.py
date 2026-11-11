"""真实管理HTTP/隔离PG/原件及索引，浏览器明确发布两种用途集合。"""

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
from smart_reporting.tests.test_business_document_ingestion import metadata, register
from smart_reporting.tests.test_business_evidence_publication import evidence_service
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_browser_publishes_rule_and_background_exact_revisions_and_recovers_unknown_responses(document_context, index_context):
    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.business_evidence_api import create_business_evidence_router
    from smart_reporting.management.repository import (
        audit_events,
        business_evidence_releases,
        reporting_policy_defaults,
    )
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.tests.report_issue_browser_flow import run_management_browser

    documents, token, scope, other, *_ = document_context
    await register(document_context, body='执行额合计÷预算额合计，不能平均各组比率。'.encode())
    await documents.ingest_revision(await documents.claim_next())
    initial = await documents.get_document(token, scope, 'budget-rules')
    await documents.review_revision(token, scope, 'budget-rules', 1, decision='approved', reason='合成原文核对', expected_version=initial['revisions'][0]['stateVersion'])
    old = await documents.get_document(token, scope, 'budget-rules')
    await register(document_context, 'rule-revision-2', expected_version=1, body='新版尚未审核，不应自动选用'.encode())
    await documents.ingest_revision(await documents.claim_next())
    await register(document_context, 'background-one', details=metadata(id='budget-background', title='预算项目背景', kind='background', eventTime='2026-06-01'), body='项目B的期间安排说明，仅为背景材料，不构成计算公式。'.encode())
    await documents.ingest_revision(await documents.claim_next())
    background = await documents.get_document(token, scope, 'budget-background')
    await documents.review_revision(token, scope, 'budget-background', 1, decision='approved', reason='背景合成原文核对', expected_version=background['revisions'][0]['stateVersion'])
    foreign_context = (documents, token, other, scope, document_context[5], document_context[4])
    await register(foreign_context, details=metadata(title='组织B同名制度'))
    foreign = await documents.get_document(token, other, 'budget-rules')
    before = await documents.get_document(token, scope, 'budget-rules')
    service = evidence_service(document_context, index_context)
    app = FastAPI()
    settings = ManagementSettings(public_origin='http://127.0.0.1:5204', allow_local_http=True)
    app.include_router(create_management_router(documents.scopes.auth, settings))
    app.include_router(create_business_documents_router(documents, settings))
    app.include_router(create_business_evidence_router(service, settings))
    output = Path('/tmp') / f'smart-reporting-evidence-release-browser-{os.getpid()}'
    output.mkdir()
    browser = await run_management_browser(app, {'token': token, 'database': scope.database, 'companyId': scope.company_id}, output,
        script='smoke/management-evidence-release-postgres-smoke.mjs')
    assert browser['publications'] == 2
    releases = [await service.get_by_request(token, scope, request_id) for request_id in browser['requestIds']]
    assert [r.kind for r in releases] == ['rule_evidence', 'background']
    assert [[(d.reference.document_id, d.reference.revision) for d in r.documents] for r in releases] == [[('budget-rules', 1)], [('budget-background', 1)]]
    for release in releases:
        assert release.index_receipt.chunk_count > 0
    current = await documents.get_document(token, scope, 'budget-rules')
    selected = current['revisions'][1]
    assert current['version'] == 2 and current['revisions'][0] == before['revisions'][0]
    assert selected['reviewStatus'] == 'approved' and selected['ingestionStatus'] == 'ready'
    for key in ('metadata', 'originalHash', 'parseReceipt', 'reviewReceipt'):
        assert selected[key] == old['revisions'][0][key]
    assert await documents.get_document(token, other, 'budget-rules') == foreign
    async with documents.repository.transaction() as connection:
        rows = list((await connection.execute(select(business_evidence_releases))).mappings())
        actions = list((await connection.execute(select(audit_events.c.action).where(audit_events.c.action == 'business_evidence_published'))).scalars())
        defaults = list((await connection.execute(select(reporting_policy_defaults))).mappings())
    assert len(rows) == len(actions) == 2 and defaults == []
    (output/'database-evidence.json').write_text(json.dumps({'releases':[r.model_dump(mode='json') for r in releases],
        'before':before,'current':current,'selectedBefore':old['revisions'][0], 'foreignBefore':foreign,
        'foreignAfter':await documents.get_document(token,other,'budget-rules'),'auditActions':actions,'defaults':[],
        'fixtureScope':'真实隔离PG和Agno PgVector，合成固定向量及原文；不验证中文召回/真实模型/StarRocks/专家签认'},ensure_ascii=False,indent=2))
