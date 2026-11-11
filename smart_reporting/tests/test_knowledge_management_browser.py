"""业务知识原件审核：真实HTTP、浏览器和同次隔离管理数据库。"""

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_business_document_ingestion import metadata, register
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_browser_reviews_exact_original_with_unknown_response_readback(document_context):
    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.repository import audit_events
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.tests.report_issue_browser_flow import run_management_browser

    service, token, scope, other, *_ = document_context
    await register(document_context, body='执行额合计÷预算额合计，不能平均各组比率。'.encode())
    await service.ingest_revision(await service.claim_next())
    original = await service.get_document(token, scope, 'budget-rules')
    await register(document_context, 'rules-revision-2', expected_version=1,
        body='执行额合计÷预算额合计，不能平均各组比率。\n项目B需单独核对全年期间。'.encode(),
        details=metadata(title='修订预算管理制度'))
    await service.ingest_revision(await service.claim_next())
    foreign_context = (service, token, other, scope, document_context[5], document_context[4])
    await register(foreign_context, details=metadata(title='组织B同名原件'))
    foreign = await service.get_document(token, other, 'budget-rules')
    before = await service.get_document(token, scope, 'budget-rules')
    app = FastAPI()
    settings = ManagementSettings(public_origin='http://127.0.0.1:5201', allow_local_http=True)
    app.include_router(create_management_router(service.scopes.auth, settings))
    app.include_router(create_business_documents_router(service, settings))
    output = Path('/tmp') / f'smart-reporting-knowledge-browser-{os.getpid()}'
    output.mkdir()
    browser = await run_management_browser(app, {'token': token, 'database': scope.database, 'companyId': scope.company_id},
        output, script='smoke/management-knowledge-postgres-smoke.mjs')
    assert browser['reviews'] == 1 and browser['originalDownloaded']
    current = await service.get_document(token, scope, 'budget-rules')
    target = current['revisions'][0]
    assert target['revision'] == 2 and target['reviewStatus'] == 'approved' and target['ingestionStatus'] == 'parsed'
    assert target['stateVersion'] == before['revisions'][0]['stateVersion'] + 1
    assert target['reviewReceipt']['reason'] == '已核对原件合计比值及项目B全年期间。'
    assert target['originalHash'] == before['revisions'][0]['originalHash']
    assert target['parseReceipt'] == before['revisions'][0]['parseReceipt']
    assert current['revisions'][1] == original['revisions'][0]
    assert await service.get_document(token, other, 'budget-rules') == foreign
    async with service.repository.transaction() as connection:
        audits = list((await connection.execute(select(audit_events.c.action).where(
            audit_events.c.action == 'business_document_reviewed'))).scalars())
    assert len(audits) == 1
    (output / 'database-evidence.json').write_text(json.dumps({'before': before, 'current': current, 'original': original,
        'foreignBefore': foreign, 'foreignAfter': await service.get_document(token, other, 'budget-rules'), 'auditActions': audits,
        'fixtureScope': '真实隔离PG与合成原件；没有发布集合、索引调用、真实模型、StarRocks和业务签认'}, ensure_ascii=False, indent=2))


async def test_browser_uploads_new_revision_recovers_registration_and_reviews_parsed_original(document_context):
    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.business_ingestion_worker import BusinessIngestionWorker
    from smart_reporting.management.repository import audit_events, business_ingestion_jobs
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.tests.report_issue_browser_flow import run_management_browser

    service, token, scope, other, *_ = document_context
    await register(document_context, body='执行额合计÷预算额合计，不能平均各组比率。'.encode())
    await service.ingest_revision(await service.claim_next())
    original = await service.get_document(token, scope, 'budget-rules')
    foreign_context = (service, token, other, scope, document_context[5], document_context[4])
    await register(foreign_context, details=metadata(title='组织B同名原件'))
    await service.ingest_revision(await service.claim_next())
    foreign = await service.get_document(token, other, 'budget-rules')
    worker = BusinessIngestionWorker(service)
    app = FastAPI()
    settings = ManagementSettings(public_origin='http://127.0.0.1:5202', allow_local_http=True)
    app.include_router(create_management_router(service.scopes.auth, settings))
    app.include_router(create_business_documents_router(service, settings, notify=worker.notify))
    output = Path('/tmp') / f'smart-reporting-knowledge-upload-browser-{os.getpid()}'
    output.mkdir()
    await worker.start()
    try:
        browser = await run_management_browser(app, {'token': token, 'database': scope.database, 'companyId': scope.company_id},
            output, script='smoke/management-knowledge-upload-postgres-smoke.mjs')
    finally:
        await worker.aclose()
    assert browser['uploads'] == browser['reviews'] == 1
    current = await service.get_document(token, scope, 'budget-rules')
    target = current['revisions'][0]
    assert target['revision'] == current['version'] == 2
    assert target['metadata']['title'] == '修订预算管理制度'
    assert target['reviewStatus'] == 'approved' and target['ingestionStatus'] == 'parsed'
    assert target['stateVersion'] == 4
    assert target['reviewReceipt']['reason'] == '已核对原件合计比值及项目B全年期间。'
    expected = '执行额合计÷预算额合计，不能平均各组比率。\n项目B需单独核对全年期间。'.encode()
    assert await service.read_original(token, scope, 'budget-rules', 2) == expected
    assert current['revisions'][1] == original['revisions'][0]
    assert await service.get_document(token, other, 'budget-rules') == foreign
    registration = await service.get_registration(token, scope, browser['uploadRequestId'])
    assert registration['receipt']['revision'] == 2 and registration['expectedVersion'] == 1
    assert registration['originalHash'] == target['originalHash']
    async with service.repository.transaction() as connection:
        audits = list((await connection.execute(select(audit_events.c.action).where(audit_events.c.action.in_(
            ['business_document_registered', 'business_document_reviewed'])))).scalars())
        jobs = list((await connection.execute(select(business_ingestion_jobs.c.document_id, business_ingestion_jobs.c.revision,
            business_ingestion_jobs.c.attempts, business_ingestion_jobs.c.status).where(
                business_ingestion_jobs.c.job_id == registration['receipt']['jobId']))).mappings())
    assert audits.count('business_document_registered') == 3 and audits.count('business_document_reviewed') == 1
    assert len(jobs) == 1 and jobs[0]['attempts'] == 1 and jobs[0]['status'] == 'parsed'
    (output / 'database-evidence.json').write_text(json.dumps({'original': original, 'current': current,
        'foreignBefore': foreign, 'foreignAfter': await service.get_document(token, other, 'budget-rules'),
        'registration': registration, 'auditActions': audits, 'jobs': [dict(job) for job in jobs],
        'fixtureScope': '真实隔离PG和持久解析worker；合成上传原件，不含真实模型/StarRocks/集合发布/业务签认'}, ensure_ascii=False, indent=2))


async def test_browser_explicitly_retries_failed_parse_and_reads_unknown_result(document_context, monkeypatch):
    import smart_reporting.management.business_documents as module
    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.business_evidence import BusinessEvidenceService
    from smart_reporting.management.business_evidence_api import create_business_evidence_router
    from smart_reporting.management.business_ingestion_worker import BusinessIngestionWorker
    from smart_reporting.management.repository import audit_events
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.tests.report_issue_browser_flow import run_management_browser

    service, token, scope, *_ = document_context
    uploaded = await register(document_context, body='执行额合计÷预算额合计，不能平均各组比率。'.encode())
    real_parse = module.parse_document

    def failed_parse(*args, **kwargs):
        raise RuntimeError('controlled parse failure')

    monkeypatch.setattr(module, 'parse_document', failed_parse)
    failed = await service.ingest_revision(await service.claim_next())
    assert failed.status == 'failed' and failed.attempt == 1
    original = await service.read_original(token, scope, 'budget-rules', 1)
    monkeypatch.setattr(module, 'parse_document', real_parse)
    worker = BusinessIngestionWorker(service)
    app = FastAPI()
    settings = ManagementSettings(public_origin='http://127.0.0.1:5203', allow_local_http=True)
    app.include_router(create_management_router(service.scopes.auth, settings))
    app.include_router(create_business_documents_router(service, settings, notify=worker.notify))
    app.include_router(create_business_evidence_router(BusinessEvidenceService(service, None), settings))
    output = Path('/tmp') / f'smart-reporting-ingestion-retry-browser-{os.getpid()}'
    output.mkdir()
    await worker.start()
    try:
        browser = await run_management_browser(app, {'token': token, 'database': scope.database,
            'companyId': scope.company_id, 'jobId': uploaded.job_id}, output,
            script='smoke/management-ingestion-retry-postgres-smoke.mjs')
    finally:
        await worker.aclose()
    assert browser['retries'] == 1
    current = await service.get_job(token, scope, uploaded.job_id)
    assert current.status == 'parsed' and current.attempt == 2
    document = await service.get_document(token, scope, 'budget-rules')
    assert document['version'] == 1 and len(document['revisions']) == 1
    assert document['revisions'][0]['reviewStatus'] == 'pending'
    assert await service.read_original(token, scope, 'budget-rules', 1) == original
    async with service.repository.transaction() as connection:
        actions = list((await connection.execute(select(audit_events.c.action).where(audit_events.c.action.in_(
            ['business_document_registered', 'business_document_retry_requested', 'business_document_reviewed'])))).scalars())
    assert actions.count('business_document_registered') == actions.count('business_document_retry_requested') == 1
    assert actions.count('business_document_reviewed') == 0
    (output / 'database-evidence.json').write_text(json.dumps({'before': failed.model_dump(mode='json'),
        'after': current.model_dump(mode='json'), 'document': document, 'auditActions': actions,
        'fixtureScope': '合成原件首轮控制解析失败后恢复真实解析器；隔离PG/worker，非模型或StarRocks验收'}, ensure_ascii=False, indent=2))
