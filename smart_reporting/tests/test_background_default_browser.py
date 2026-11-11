"""背景默认选择：真实HTTP/隔离PG/浏览器及新旧计算依据，不取业务数据。"""
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
from smart_reporting.tests.test_report_basis_persistence import basis_context as basis_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_browser_changes_background_without_formula_publication_and_old_basis_drift(basis_context, document_context):
    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.business_evidence_api import create_business_evidence_router
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import audit_events
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.management.statistical_policy_api import create_statistical_policy_router
    from smart_reporting.reporting.business_knowledge.retrieval import DocumentRevisionRef
    from smart_reporting.reporting.semantics.models import BuildIdentity
    from smart_reporting.tests.report_issue_browser_flow import run_management_browser
    from smart_reporting.tests.test_business_document_ingestion import metadata, register
    from smart_reporting.tests.test_report_basis_persistence import request_summary

    ctx = basis_context
    documents, token, scope = document_context[:3]
    policies = ctx['policy_service']
    evidence = policies.evidence
    basis_service = ReportBasisService(ctx['scopes'])
    build = BuildIdentity(commit='a'*40, sourceHash='b'*64, dependencyHash='c'*64, compilerVersion='semantic-v1')
    summary = request_summary(ctx['scope_id'])
    old = await basis_service.register_report_basis('run-basis', scope, user_id='7', thread_id='thread-basis', request_summary=summary, build_identity=build)
    original_policy = await policies.get(token, scope, 'monthly-budget')
    original_default = await policies.get_default(token, scope, 'budget_execution')
    assert old.background_release_id is None
    await register(document_context, 'browser-background-upload', details=metadata(id='budget-context', title='本期项目背景', kind='background', eventTime='2026-11-01'), body='项目B本期采购计划调整，仅作解释材料，不改变预算执行率公式。'.encode())
    await documents.ingest_revision(await documents.claim_next())
    original = await documents.get_document(token, scope, 'budget-context')
    await documents.review_revision(token, scope, 'budget-context', 1, decision='approved', reason='合成背景原文核对', expected_version=original['revisions'][0]['stateVersion'])
    background = await evidence.publish(token, scope, request_id='browser-background-release', kind='background', revision_ids=(DocumentRevisionRef(document_id='budget-context', revision=1),))
    foreign_context = (documents, token, document_context[3], scope, document_context[5], document_context[4])
    await register(foreign_context, 'foreign-context', details=metadata(id='budget-context', title='组织B同名背景', kind='background'))
    foreign = await documents.get_document(token, document_context[3], 'budget-context')
    app = FastAPI()
    settings = ManagementSettings(public_origin='http://127.0.0.1:5205', allow_local_http=True)
    app.include_router(create_management_router(ctx['scopes'].auth, settings))
    app.include_router(create_statistical_policy_router(policies, settings))
    app.include_router(create_business_evidence_router(evidence, settings))
    app.include_router(create_business_documents_router(documents, settings))
    output = Path('/tmp') / f'smart-reporting-background-default-browser-{os.getpid()}'
    output.mkdir()
    browser = await run_management_browser(app, {'token':token, 'database':scope.database, 'companyId':scope.company_id, 'releaseId':background.release_id}, output, script='smoke/management-background-default-postgres-smoke.mjs')
    assert browser['writes'] == 1 and browser['unknownResponseReadback']
    current = await policies.get_default(token, scope, 'budget_execution')
    assert current['version'] == original_default['version']+1 and current['backgroundReleaseId'] == background.release_id
    assert current['policyVersion'] == original_default['policyVersion'] and current['issues'] == []
    assert await policies.get(token, scope, 'monthly-budget') == original_policy
    restored = await ReportBasisService(ctx['scopes']).load_report_basis('run-basis', scope, user_id='7', thread_id='thread-basis')
    assert restored == old
    await ctx['provider'].register_run('run-background-new', scope, user_id='7', thread_id='thread-background-new', entrypoint='cli')
    new = await basis_service.register_report_basis('run-background-new', scope, user_id='7', thread_id='thread-background-new', request_summary=summary, build_identity=build)
    assert new.background_release_id == background.release_id
    for key in ('policy_version', 'metric_versions', 'source_versions', 'catalog_refs', 'evidence_release_id'):
        assert getattr(new,key) == getattr(old,key)
    assert await documents.get_document(token, document_context[3], 'budget-context') == foreign
    async with ctx['repository'].transaction() as connection:
        actions = list((await connection.execute(select(audit_events.c.action).where(audit_events.c.action.in_(['report_policy_default_set','statistical_policy_published','statistical_policy_draft_saved'])))).scalars())
    assert actions.count('report_policy_default_set') == 2
    assert actions.count('statistical_policy_published') == actions.count('statistical_policy_draft_saved') == 1
    (output/'database-evidence.json').write_text(json.dumps({'oldBasis':old.model_dump(mode='json'), 'restoredBasis':restored.model_dump(mode='json'), 'newBasis':new.model_dump(mode='json'), 'originalDefault':original_default,'currentDefault':current,'originalPolicy':original_policy,'currentPolicy':await policies.get(token,scope,'monthly-budget'),'auditActions':actions,'foreignBefore':foreign,'foreignAfter':await documents.get_document(token,document_context[3],'budget-context'),'fixtureScope':'真实管理HTTP/隔离PG/原件与Agno PgVector，合成固定向量；仅登记计算依据，未生成报告或取业务数据，非模型/StarRocks/中文召回/业务签认'},ensure_ascii=False,indent=2))
