"""历史预期签认进入关闭准备时，必须重新核验当前精确来源和回归。"""

import pytest

from smart_reporting.tests.test_report_issue_business_approvals import (
    approval_context as approval_context,
)
from smart_reporting.tests.test_report_issue_business_approvals import auth_context as auth_context
from smart_reporting.tests.test_report_issue_business_approvals import (
    basis_context as basis_context,
)
from smart_reporting.tests.test_report_issue_business_approvals import (
    document_context as document_context,
)
from smart_reporting.tests.test_report_issue_business_approvals import (
    index_context as index_context,
)
from smart_reporting.tests.test_report_issue_business_approvals import (
    issue_context as issue_context,
)
from smart_reporting.tests.test_report_issue_business_approvals import (
    regression_context as regression_context,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def signed(case):
    from smart_reporting.management.report_issue_business_approvals import approve_expectations

    await approve_expectations(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', case.request, runtime=case.runtime)
    return {'expectedIssueVersion': 2, 'regressionReceiptIds': [case.regression.receipt_id],
        'businessApprovalRequestId': case.request['requestId']}


async def check(case, payload):
    from smart_reporting.management.report_issue_resolution_evidence import (
        check_resolution_evidence,
    )

    return await check_resolution_evidence(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', payload, runtime=case.runtime)


async def test_resolution_uses_only_explicitly_selected_current_signoff(approval_context):
    case = approval_context
    payload = await signed(case)
    unsigned = await check(case, {key: value for key, value in payload.items() if key != 'businessApprovalRequestId'})
    assert unsigned['businessApproval'] == 'not_performed' and unsigned['businessApprovalReady'] is False
    result = await check(case, payload)
    assert result['businessApproval'] == 'explicitly_approved' and result['businessApprovalReady'] is True
    assert result['businessApprovalCheck']['status'] == 'verified'
    assert result['businessApprovalCheck']['requestId'] == case.request['requestId']
    assert case.document in {item['documentId'] for item in result['originalChecks']}
    assert result['regressionEvidenceReady'] and result['originalEvidenceReady']
    assert result['deliveryReady'] is False and result['issueClosed'] is False
    assert (await case.service.report_list(**case.binding))['items'][0]['review']['status'] == 'accepted'
    assert case.request['sources'][0]['quote'] not in str(result)
    import json
    import os
    import tempfile
    from pathlib import Path

    directory = Path(tempfile.gettempdir()) / f'smart-reporting-current-approval-{os.getpid()}'
    directory.mkdir(exist_ok=True)
    (directory / 'unsigned.json').write_text(json.dumps(unsigned, ensure_ascii=False, indent=2) + '\n')
    (directory / 'selected.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


@pytest.mark.parametrize('fault', ['original_missing', 'source_revoked', 'csv_missing', 'unknown', 'issue_updated'])
async def test_resolution_invalidates_unavailable_or_stale_signoff(approval_context, fault):
    from smart_reporting.management.report_issue_business_approvals import read_approval
    from smart_reporting.tests.test_report_issue_reviews import accepted_fix

    case = approval_context
    payload = await signed(case)
    documents = case.runtime.business_evidence_service.documents
    if fault == 'original_missing':
        from sqlalchemy import select

        from smart_reporting.management.repository import business_document_revisions
        async with case.ctx['repository'].transaction() as connection:
            resource = await connection.scalar(select(business_document_revisions.c.original_resource_id).where(
                business_document_revisions.c.document_id == case.document))
        await documents.originals.discard(case.ctx['scope_id'], resource)
    elif fault == 'source_revoked':
        detail = await documents.get_document(case.ctx['token'], case.ctx['scope'], case.document)
        await documents.review_revision(case.ctx['token'], case.ctx['scope'], case.document, 1,
            decision='revoked', reason='当前核验前撤销独立原件', expected_version=detail['revisions'][0]['stateVersion'])
    elif fault == 'csv_missing':
        await case.runtime.datasets.service.adelete_file(case.calculation.workspace.workspace_key, case.calculation.datasets[0].file.path)
    elif fault == 'unknown':
        payload['businessApprovalRequestId'] = 'not-registered'
    else:
        await case.service.decide(case.ctx['token'], case.ctx['scope'], 'issue-C02',
            {**accepted_fix(), 'expectedVersion': 2, 'decisionReason': '更新问题后原签认不自动承接。'})
        payload['expectedIssueVersion'] = 3
    result = await check(case, payload)
    assert result['businessApprovalReady'] is False and result['issueClosed'] is False
    assert result['businessApprovalCheck']['status'] != 'verified'
    assert result['businessApprovalCheck']['issues']
    assert await read_approval(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', case.request['requestId']) is not None
    import json
    import os
    import tempfile
    from pathlib import Path

    directory = Path(tempfile.gettempdir()) / f'smart-reporting-current-approval-{os.getpid()}'
    directory.mkdir(exist_ok=True)
    (directory / (fault + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


async def test_current_signoff_check_rejects_review_update_during_io(approval_context, monkeypatch):
    from smart_reporting.management.models import ManagementError

    case = approval_context
    payload = await signed(case)
    documents = case.runtime.business_evidence_service.documents
    read = documents.read_original

    async def revoke(token, scope, document_id, revision):
        content = await read(token, scope, document_id, revision)
        if document_id == case.document:
            detail = await documents.get_document(token, scope, document_id)
            await documents.review_revision(token, scope, document_id, revision, decision='revoked',
                reason='读取期间撤销，不能返回旧签认可用。', expected_version=detail['revisions'][0]['stateVersion'])
        return content

    monkeypatch.setattr(documents, 'read_original', revoke)
    with pytest.raises(ManagementError) as conflict:
        await check(case, payload)
    assert conflict.value.status == 409


async def test_resolution_signoff_http_preserves_auth_scope_and_does_not_infer_selection(approval_context):
    import httpx
    from fastapi import FastAPI

    from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
    from smart_reporting.management.settings import ManagementSettings

    case = approval_context
    selected = await signed(case)
    app = FastAPI()
    app.include_router(create_management_router(case.ctx['scopes'].auth,
        ManagementSettings(public_origin='https://reports.example'), report_runtime=case.runtime))
    path = '/management/api/v1/report-issue-reviews/issue-C02/resolution-evidence-check'
    body = {**selected, 'scopeDatabase': case.ctx['scope'].database, 'companyId': case.ctx['scope'].company_id}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        assert (await client.post(path, json=body)).status_code == 401
        client.cookies.set(SESSION_COOKIE, case.ctx['token'], path='/management')
        assert (await client.post(path, json=body)).status_code == 403
        headers = {'origin': 'https://reports.example', 'x-csrf-token': csrf_token(case.ctx['token'])}
        assert (await client.post(path, headers=headers,
            json={**body, 'companyId': case.ctx['other_scope'].company_id})).status_code == 404
        result = await client.post(path, headers=headers, json=body)
        assert result.status_code == 200, result.text
        assert result.headers['cache-control'] == 'no-store' and result.json()['businessApprovalReady'] is True
        assert result.json()['issueClosed'] is False
        unsigned = await client.post(path, headers=headers,
            json={key: value for key, value in body.items() if key != 'businessApprovalRequestId'})
        assert unsigned.status_code == 200 and unsigned.json()['businessApproval'] == 'not_performed'
        invalid = await client.post(path, headers=headers, json={**body, 'businessApprovalReady': True})
        assert invalid.status_code == 422


async def test_signoff_cannot_cover_another_equal_valued_regression(approval_context):
    from smart_reporting.management.report_issue_regressions import verify_regression

    case = approval_context
    payload = await signed(case)
    other = await verify_regression(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02',
        {**case.regression.request.model_dump(mode='json', by_alias=True), 'requestId': 'other-equal-value'}, runtime=case.runtime)
    result = await check(case, {**payload, 'regressionReceiptIds': [other.receipt_id]})
    assert result['regressionEvidenceReady'] is True
    assert result['businessApprovalReady'] is False
    assert result['businessApprovalCheck']['issues'][0]['code'] == 'management_issue_approval_stale'
