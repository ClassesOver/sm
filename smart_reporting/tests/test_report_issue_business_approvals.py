"""业务预期显式签认的隔离PG验收；合成管理员操作不冒充真实业务签认。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from smart_reporting.tests.test_report_issue_regressions import auth_context as auth_context
from smart_reporting.tests.test_report_issue_regressions import basis_context as basis_context
from smart_reporting.tests.test_report_issue_regressions import document_context as document_context
from smart_reporting.tests.test_report_issue_regressions import index_context as index_context
from smart_reporting.tests.test_report_issue_regressions import issue_context as issue_context
from smart_reporting.tests.test_report_issue_regressions import (
    regression_context as regression_context,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def approval_context(regression_context):
    from smart_reporting.management.report_issue_regressions import verify_regression
    from smart_reporting.reporting.business_knowledge.retrieval import DocumentRevisionRef
    from smart_reporting.tests.test_business_document_ingestion import metadata

    ctx, service, binding, payload, runtime, calculation = regression_context
    regression = await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime)
    evidence = runtime.business_evidence_service
    documents = evidence.documents
    original = '合成独立对账：项目A预算100元，项目B预算200元，预算合计300元。'
    registered = await documents.register_document(ctx['token'], ctx['scope'], original.encode(), filename='expected.txt',
        metadata=metadata(id='independent-budget-check', title='合成独立预期对账'), request_id='expected-source', expected_version=0)
    await documents.ingest_revision(await documents.claim_next())
    detail = await documents.get_document(ctx['token'], ctx['scope'], registered.document_id)
    await documents.review_revision(ctx['token'], ctx['scope'], registered.document_id, 1, decision='approved',
        reason='合成签认夹具原件', expected_version=detail['revisions'][0]['stateVersion'])
    await evidence.publish(ctx['token'], ctx['scope'], request_id='independent-check-release', kind='rule_evidence',
        revision_ids=(DocumentRevisionRef(document_id=registered.document_id, revision=1),))
    detail = await documents.get_document(ctx['token'], ctx['scope'], registered.document_id)
    fragment = detail['revisions'][0]['parseReceipt']['fragments'][0]
    request = {'requestId': 'explicit-budget-signoff', 'expectedIssueVersion': 2,
        'decision': 'approve_expected_values', 'regressionReceiptIds': [regression.receipt_id],
        'approvalReason': '人工核对独立原始预算100+200=300，与所选回归全部分组预期一致；不批准整份报告。',
        'sources': [{'regressionReceiptId': regression.receipt_id, 'documentId': registered.document_id,
            'revision': 1, 'locator': fragment['locator'], 'quote': original}]}
    return SimpleNamespace(ctx=ctx, service=service, binding=binding, runtime=runtime,
        regression=regression, request=request, document=registered.document_id, calculation=calculation)


async def test_explicit_approval_binds_exact_regression_sources_and_authenticated_actor(approval_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_issue_business_approvals import (
        approve_expectations,
        read_approval,
    )
    from smart_reporting.management.repository import audit_events

    case = approval_context
    ctx, service = case.ctx, case.service
    result = await approve_expectations(service, ctx['token'], ctx['scope'], 'issue-C02', case.request, runtime=case.runtime)
    assert result.business_approval == 'explicitly_approved'
    assert result.approval_scope == 'regression_expected_values'
    actor = await ctx['scopes'].actor(ctx['token'], ctx['scope'])
    assert result.approved_by_account_id == actor.account_id and result.approved_by_username == actor.username
    assert result.regressions[0].receipt_id == case.regression.receipt_id
    assert result.sources[0].document_id == case.document and result.sources[0].sha256
    assert await read_approval(service, ctx['token'], ctx['scope'], 'issue-C02', case.request['requestId']) == result
    assert await approve_expectations(service, ctx['token'], ctx['scope'], 'issue-C02', case.request, runtime=case.runtime) == result
    with pytest.raises(ManagementError) as conflict:
        await approve_expectations(service, ctx['token'], ctx['scope'], 'issue-C02',
            {**case.request, 'approvalReason': '同ID改写签认声明'}, runtime=case.runtime)
    assert conflict.value.status == 409
    assert case.regression.business_approval == 'not_performed'
    assert (await service.report_list(**case.binding))['items'][0]['review']['status'] == 'accepted'
    async with ctx['repository'].transaction() as connection:
        assert await connection.scalar(select(func.count()).select_from(audit_events)
            .where(audit_events.c.action == 'report_issue_expectations_approved')) == 1


async def test_approval_rejects_forged_quote_uncovered_receipt_and_missing_original(approval_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_issue_business_approvals import (
        approve_expectations,
        read_approval,
    )

    case = approval_context
    for source in ({**case.request['sources'][0], 'quote': '伪造的预算310元'},
                   {**case.request['sources'][0], 'locator': {'kind': 'text_lines', 'lineStart': 999, 'lineEnd': 999}},
                   {**case.request['sources'][0], 'regressionReceiptId': 'other-regression'}):
        with pytest.raises(ManagementError) as invalid:
            await approve_expectations(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02',
                {**case.request, 'sources': [source]}, runtime=case.runtime)
        assert invalid.value.status in (409, 422)
    documents = case.runtime.business_evidence_service.documents
    # 实际删除本例隔离原件，不使用模拟“文件不存在”的替身。
    async with case.ctx['repository'].transaction() as connection:
        from smart_reporting.management.repository import business_document_revisions
        resource = await connection.scalar(select(business_document_revisions.c.original_resource_id).where(
            business_document_revisions.c.document_id == case.document))
    await documents.originals.discard(case.ctx['scope_id'], resource)
    with pytest.raises(ManagementError) as missing:
        await approve_expectations(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', case.request, runtime=case.runtime)
    assert missing.value.status == 409
    assert await read_approval(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', case.request['requestId']) is None


async def test_approval_http_requires_session_csrf_and_exact_readback(approval_context):
    import json
    import os
    import tempfile
    from pathlib import Path

    import httpx
    from fastapi import FastAPI

    from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
    from smart_reporting.management.business_documents import _digest
    from smart_reporting.management.report_issue_regressions import verify_regression
    from smart_reporting.management.settings import ManagementSettings

    case = approval_context
    app = FastAPI()
    app.include_router(create_management_router(case.ctx['scopes'].auth,
        ManagementSettings(public_origin='https://reports.example'), report_runtime=case.runtime))
    path = '/management/api/v1/report-issue-reviews/issue-C02/business-approvals'
    params = {'scopeDatabase': case.ctx['scope'].database, 'companyId': case.ctx['scope'].company_id}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        assert (await client.post(path, json={**params, **case.request})).status_code == 401
        client.cookies.set(SESSION_COOKIE, case.ctx['token'], path='/management')
        assert (await client.get(path + '/' + case.request['requestId'], params=params)).status_code == 404
        assert (await client.post(path, json={**params, **case.request})).status_code == 403
        headers = {'origin': 'https://reports.example', 'x-csrf-token': csrf_token(case.ctx['token'])}
        assert (await client.post(path, headers=headers, json={**params, **case.request,
            'approvedByAccountId': 'forged-admin'})).status_code == 422
        wrong_request = {**case.regression.request.model_dump(mode='json', by_alias=True),
            'requestId': 'wrong-expectation', 'assertions': [{**case.regression.request.assertions[0].model_dump(mode='json', by_alias=True),
                'expectedValue': '310'}]}
        wrong = await verify_regression(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', wrong_request, runtime=case.runtime)
        assert wrong.status == 'failed'
        denied = await client.post(path, headers=headers, json={**params, **case.request,
            'requestId': 'must-not-approve-failed', 'regressionReceiptIds': [wrong.receipt_id],
            'sources': [{**case.request['sources'][0], 'regressionReceiptId': wrong.receipt_id}]})
        assert denied.status_code == 409 and denied.json()['code'] == 'management_issue_approval_regression_unavailable'
        result = await client.post(path, headers=headers, json={**params, **case.request})
        assert result.status_code == 200, result.text
        assert result.headers['cache-control'] == 'no-store'
        assert result.json()['requestHash'] == _digest(case.request)
        assert result.json()['currentEvidenceStatus'] == 'not_checked'
        assert 'quote' not in result.json()['request']['sources'][0]
        recovered = await client.get(path + '/' + case.request['requestId'], params=params)
        assert recovered.status_code == 200 and recovered.json() == result.json()
        assert (await client.get(path + '/' + case.request['requestId'],
            params={**params, 'companyId': case.ctx['other_scope'].company_id})).status_code == 404
        documents = case.runtime.business_evidence_service.documents
        detail = await documents.get_document(case.ctx['token'], case.ctx['scope'], case.document)
        await documents.review_revision(case.ctx['token'], case.ctx['scope'], case.document, 1,
            decision='revoked', reason='签认后撤销来源，历史响应不能返回原文摘录。',
            expected_version=detail['revisions'][0]['stateVersion'])
        historical = await client.get(path + '/' + case.request['requestId'], params=params)
        assert historical.json() == result.json()
        assert case.request['sources'][0]['quote'] not in historical.text
        assert (await client.post(path, headers=headers, json={**params, **case.request})).json() == result.json()
        assert (await client.post(path, headers=headers, json={**params, **case.request,
            'requestId': 'new-signoff-after-revocation'})).status_code == 409
        out = Path(tempfile.gettempdir()) / f'smart-reporting-issue-business-approval-http-{os.getpid()}'
        out.mkdir(exist_ok=True)
        for name, response in [('approved', result), ('recovered', recovered), ('after-revocation', historical), ('failed-regression-denied', denied)]:
            (out / (name + '.json')).write_text(json.dumps({'statusCode': response.status_code,
                'cacheControl': response.headers.get('cache-control'), 'body': response.json()}, ensure_ascii=False, indent=2) + '\n')


@pytest.mark.parametrize('change', ['issue', 'source', 'csv'])
async def test_approval_rechecks_changes_during_source_io(approval_context, monkeypatch, change):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_issue_business_approvals import (
        approve_expectations,
        read_approval,
    )
    from smart_reporting.tests.test_report_issue_reviews import accepted_fix

    case = approval_context
    documents = case.runtime.business_evidence_service.documents
    read = documents.read_original

    async def changed(token, scope, document_id, revision):
        content = await read(token, scope, document_id, revision)
        if change == 'issue':
            await case.service.decide(token, scope, 'issue-C02',
                {**accepted_fix(), 'expectedVersion': 2, 'decisionReason': 'IO期间更新问题，旧签认应冲突。'})
        elif change == 'source':
            detail = await documents.get_document(token, scope, document_id)
            await documents.review_revision(token, scope, document_id, revision, decision='revoked',
                reason='IO期间撤销原件', expected_version=detail['revisions'][0]['stateVersion'])
        else:
            workspace = case.runtime.datasets.service.registry.resolve(case.runtime.test_workflow_scope)
            (workspace.root / case.calculation.datasets[0].file.path).unlink()
        return content

    monkeypatch.setattr(documents, 'read_original', changed)
    with pytest.raises(ManagementError) as conflict:
        await approve_expectations(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', case.request, runtime=case.runtime)
    assert conflict.value.status == 409
    assert await read_approval(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', case.request['requestId']) is None


async def test_approval_audit_rollback_and_commit_response_loss_are_exactly_readable(approval_context, monkeypatch):
    import json
    import os
    import tempfile
    from contextlib import asynccontextmanager
    from pathlib import Path

    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError

    from smart_reporting.management.report_issue_business_approvals import (
        approve_expectations,
        read_approval,
    )
    from smart_reporting.management.repository import audit_events, report_basis_receipts
    from smart_reporting.reporting.semantics.issue_approval import approval_receipt_id

    case = approval_context
    ctx, service = case.ctx, case.service
    receipt_id = approval_receipt_id(case.binding['basis_id'], 'issue-C02', case.request['requestId'])
    audit = ctx['scopes'].audit

    async def fail_audit(connection, actor, action, details):
        if action == 'report_issue_expectations_approved':
            raise RuntimeError('approval audit failed')
        return await audit(connection, actor, action, details)

    with monkeypatch.context() as fault:
        fault.setattr(ctx['scopes'], 'audit', fail_audit)
        with pytest.raises(RuntimeError, match='approval audit failed'):
            await approve_expectations(service, ctx['token'], ctx['scope'], 'issue-C02', case.request, runtime=case.runtime)
    assert await read_approval(service, ctx['token'], ctx['scope'], 'issue-C02', case.request['requestId']) is None
    transaction = ctx['scopes'].write_transaction

    @asynccontextmanager
    async def lost_response(actor):
        async with transaction(actor) as connection:
            yield connection
            exists = await connection.scalar(select(report_basis_receipts.c.receipt_id)
                .where(report_basis_receipts.c.receipt_id == receipt_id))
        if exists:
            raise ConnectionError('approval response lost after commit')

    with monkeypatch.context() as fault:
        fault.setattr(ctx['scopes'], 'write_transaction', lost_response)
        with pytest.raises(ConnectionError, match='approval response lost after commit'):
            await approve_expectations(service, ctx['token'], ctx['scope'], 'issue-C02', case.request, runtime=case.runtime)
    saved = await read_approval(service, ctx['token'], ctx['scope'], 'issue-C02', case.request['requestId'])
    assert saved.receipt_id == receipt_id and saved.request.request_id == case.request['requestId']
    async with ctx['repository'].transaction() as connection:
        assert await connection.scalar(select(func.count()).select_from(audit_events)
            .where(audit_events.c.action == 'report_issue_expectations_approved')) == 1
    with pytest.raises(IntegrityError):
        async with ctx['repository'].engine.begin() as connection:
            await connection.execute(update(report_basis_receipts).where(report_basis_receipts.c.receipt_id == receipt_id)
                .values(content_hash='0' * 64))
    assert await read_approval(service, ctx['token'], ctx['scope'], 'issue-C02', case.request['requestId']) == saved
    assert (await service.report_list(**case.binding))['items'][0]['review']['status'] == 'accepted'
    out = Path(tempfile.gettempdir()) / f'smart-reporting-issue-business-approval-{os.getpid()}'
    out.mkdir(exist_ok=True)
    (out / 'approval.json').write_text(saved.model_dump_json(by_alias=True, indent=2) + '\n')
    (out / 'regression.json').write_text(case.regression.model_dump_json(by_alias=True, indent=2) + '\n')
    (out / 'request.json').write_text(json.dumps(case.request, ensure_ascii=False, indent=2) + '\n')
    (out / 'original.txt').write_bytes(await case.runtime.business_evidence_service.documents.read_original(
        ctx['token'], ctx['scope'], case.document, 1))


async def test_concurrent_approval_records_one_immutable_signoff(approval_context):
    import asyncio

    from smart_reporting.management.report_issue_business_approvals import approve_expectations
    from smart_reporting.management.repository import audit_events

    case = approval_context
    results = await asyncio.gather(*(approve_expectations(case.service, case.ctx['token'], case.ctx['scope'],
        'issue-C02', case.request, runtime=case.runtime) for _ in range(2)))
    assert results[0] == results[1]
    async with case.ctx['repository'].transaction() as connection:
        assert await connection.scalar(select(func.count()).select_from(audit_events)
            .where(audit_events.c.action == 'report_issue_expectations_approved')) == 1


async def test_approval_source_options_include_original_rules_and_paginate_with_org_isolation(approval_context):
    import httpx
    from fastapi import FastAPI

    from smart_reporting.management.api import SESSION_COOKIE, create_management_router
    from smart_reporting.management.settings import ManagementSettings

    case = approval_context
    app = FastAPI()
    app.include_router(create_management_router(case.ctx['scopes'].auth,
        ManagementSettings(public_origin='https://reports.example'), report_runtime=case.runtime))
    path = '/management/api/v1/report-issue-reviews/issue-C02/approval-source-options'
    params = {'scopeDatabase': case.ctx['scope'].database, 'companyId': case.ctx['scope'].company_id, 'limit': 1}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        assert (await client.get(path, params=params)).status_code == 401
        client.cookies.set(SESSION_COOKIE, case.ctx['token'], path='/management')
        first = await client.get(path, params=params)
        assert first.status_code == 200, first.text
        assert first.headers['cache-control'] == 'no-store'
        assert first.json()['items'][0]['documentId'] == 'budget-rules'
        assert first.json()['items'][0]['available'] is True
        assert first.json()['nextCursor']
        second = await client.get(path, params={**params, 'after': first.json()['nextCursor']})
        assert second.json()['items'][0]['documentId'] == case.document and second.json()['nextCursor'] is None
        searched = await client.get(path, params={**params, 'q': '独立预期'})
        assert searched.json()['items'][0]['documentId'] == case.document
        assert (await client.get(path, params={**params, 'companyId': case.ctx['other_scope'].company_id})).status_code == 404
        assert (await client.get(path, params={**params, 'after': 'bad'})).status_code == 422
