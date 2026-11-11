"""正式关闭的真实隔离PG验证；不重算裁定不冒充新报告交付。"""

import pytest
from sqlalchemy import func, select

from smart_reporting.tests.test_report_issue_approval_checks import (
    approval_context as approval_context,
)
from smart_reporting.tests.test_report_issue_approval_checks import (
    auth_context as auth_context,
)
from smart_reporting.tests.test_report_issue_approval_checks import (
    basis_context as basis_context,
)
from smart_reporting.tests.test_report_issue_approval_checks import (
    document_context as document_context,
)
from smart_reporting.tests.test_report_issue_approval_checks import (
    index_context as index_context,
)
from smart_reporting.tests.test_report_issue_approval_checks import (
    issue_context as issue_context,
)
from smart_reporting.tests.test_report_issue_approval_checks import (
    regression_context as regression_context,
)
from smart_reporting.tests.test_report_issue_approval_checks import (
    signed,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_explicit_no_recalculation_closes_atomically_and_reads_original_result(approval_context, monkeypatch):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_issue_resolutions import read_resolution, resolve_issue
    from smart_reporting.management.repository import audit_events

    case = approval_context
    selected = await signed(case)
    request = {**selected, 'requestId': 'close-without-new-report', 'mode': 'not_recalculated',
        'decisionReason': '独立对账及正式规则已核对，明确结束此次纠错。',
        'notRecalculatedReason': '本例只修复后续规则；历史报告作为原始记录保留，本次不要求重发。',
        'originalReportUnchanged': True}
    result = await resolve_issue(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', request, runtime=case.runtime)
    assert result.issue_closed and result.resolved_issue_version == 3
    assert result.request.mode == 'not_recalculated' and not result.evidence.delivery_ready
    assert result.evidence.business_approval_ready
    item = (await case.service.report_list(**case.binding))['items'][0]
    assert item['review']['status'] == 'resolved' and item['version'] == 3
    assert item['review']['notRecalculatedReason'] == request['notRecalculatedReason']
    assert item['review']['newReportRevision'] is None
    assert await read_resolution(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', request['requestId']) == result

    async def no_io(*args, **kwargs):
        pytest.fail('已提交请求只能读回历史，不能再次读取原件或裁定')
    monkeypatch.setattr(case.runtime.business_evidence_service.documents, 'read_original', no_io)
    assert await resolve_issue(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', request, runtime=case.runtime) == result
    with pytest.raises(ManagementError) as changed:
        await resolve_issue(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02',
            {**request, 'decisionReason': '同ID篡改裁定'}, runtime=case.runtime)
    assert changed.value.status == 409
    async with case.ctx['repository'].transaction() as connection:
        assert await connection.scalar(select(func.count()).select_from(audit_events)
            .where(audit_events.c.action == 'report_issue_resolved')) == 1


async def test_resolution_requires_delivery_or_explicit_disposition_and_current_signoff(approval_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_issue_resolutions import read_resolution, resolve_issue

    case = approval_context
    selected = await signed(case)
    request = {**selected, 'requestId': 'close-incomplete', 'mode': 'recalculated',
        'decisionReason': '不能把独立回归冒充新报告交付。', 'originalReportUnchanged': True}
    with pytest.raises(ManagementError) as missing:
        await resolve_issue(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', request, runtime=case.runtime)
    assert missing.value.status == 409
    assert await read_resolution(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', request['requestId']) is None
    for override in ({'mode': 'not_recalculated'}, {'mode': 'not_recalculated', 'notRecalculatedReason': '   '},
                     {'mode': 'not_recalculated', 'notRecalculatedReason': '保留原报告', 'originalReportUnchanged': False}):
        with pytest.raises(ManagementError) as invalid:
            await resolve_issue(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02',
                {**request, **override}, runtime=case.runtime)
        assert invalid.value.status == 422
    invalid = {**request, 'mode': 'not_recalculated', 'notRecalculatedReason': '明确不重发', 'businessApprovalRequestId': 'unknown'}
    with pytest.raises(ManagementError) as unsigned:
        await resolve_issue(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', invalid, runtime=case.runtime)
    assert unsigned.value.status == 409
    assert (await case.service.report_list(**case.binding))['items'][0]['review']['status'] == 'accepted'


async def test_resolution_http_contract_and_audit_failure_roll_back_all_state(approval_context, monkeypatch):
    import httpx
    from fastapi import FastAPI

    from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
    from smart_reporting.management.report_issue_resolutions import read_resolution
    from smart_reporting.management.settings import ManagementSettings

    case = approval_context
    selected = await signed(case)
    app = FastAPI()
    app.include_router(create_management_router(case.ctx['scopes'].auth,
        ManagementSettings(public_origin='https://reports.example'), report_runtime=case.runtime))
    path = '/management/api/v1/report-issue-reviews/issue-C02/resolutions'
    params = {'scopeDatabase': case.ctx['scope'].database, 'companyId': case.ctx['scope'].company_id}
    request = {**selected, 'requestId': 'http-close', 'mode': 'not_recalculated', 'decisionReason': '正式核对后裁定。',
        'notRecalculatedReason': '明确保留原报告，只应用后续规则。', 'originalReportUnchanged': True}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        assert (await client.post(path, json={**params, **request})).status_code == 401
        client.cookies.set(SESSION_COOKIE, case.ctx['token'], path='/management')
        assert (await client.post(path, json={**params, **request})).status_code == 403
        headers = {'origin': 'https://reports.example', 'x-csrf-token': csrf_token(case.ctx['token'])}
        assert (await client.post(path, headers=headers, json={**params, **request, 'companyId': 'foreign'})).status_code in (403, 404)
        assert (await client.post(path, headers=headers, json={**params, **request, 'unchecked': True})).status_code == 422
        from smart_reporting.management.scopes import ScopeService
        audit = ScopeService.audit
        async def fail_audit(self, connection, actor, action, details):
            if action == 'report_issue_resolved':
                raise RuntimeError('isolated audit fault')
            return await audit(self, connection, actor, action, details)
        monkeypatch.setattr(ScopeService, 'audit', fail_audit)
        with pytest.raises(RuntimeError, match='isolated audit fault'):
            await client.post(path, headers=headers, json={**params, **request})
        assert await read_resolution(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', request['requestId']) is None
        assert (await case.service.report_list(**case.binding))['items'][0]['review']['status'] == 'accepted'
        monkeypatch.setattr(ScopeService, 'audit', audit)
        result = await client.post(path, headers=headers, json={**params, **request})
        assert result.status_code == 200, result.text
        body = result.json()
        assert body['issueClosed'] and body['historicalResult'] and body['requestHash']
        assert (await client.get(path + '/http-close', params=params)).json() == body
        assert (await client.get(path + '/absent', params=params)).status_code == 404
        assert (await client.get(path + '/http-close', params={**params, 'companyId': 'foreign'})).status_code in (403, 404)


async def test_resolution_lost_commit_response_recovers_one_immutable_result(approval_context, monkeypatch):
    from contextlib import asynccontextmanager

    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError

    from smart_reporting.management.report_issue_resolutions import read_resolution, resolve_issue
    from smart_reporting.management.repository import audit_events, report_basis_receipts
    from smart_reporting.reporting.semantics.issue_resolution import resolution_receipt_id

    case = approval_context
    selected = await signed(case)
    request = {**selected, 'requestId': 'lost-resolution', 'mode': 'not_recalculated', 'decisionReason': '核对后明确裁定。',
        'notRecalculatedReason': '历史报告保留，此次不重发。', 'originalReportUnchanged': True}
    receipt_id = resolution_receipt_id(case.binding['basis_id'], 'issue-C02', request['requestId'])
    transaction = case.service.scopes.write_transaction

    @asynccontextmanager
    async def lost_response(actor):
        async with transaction(actor) as connection:
            yield connection
            exists = await connection.scalar(select(report_basis_receipts.c.receipt_id).where(report_basis_receipts.c.receipt_id == receipt_id))
        if exists:
            raise ConnectionError('resolution response lost after commit')

    with monkeypatch.context() as fault:
        fault.setattr(case.service.scopes, 'write_transaction', lost_response)
        with pytest.raises(ConnectionError, match='resolution response lost after commit'):
            await resolve_issue(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', request, runtime=case.runtime)
    saved = await read_resolution(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', request['requestId'])
    assert saved.issue_closed and saved.resolved_issue_version == 3
    assert await resolve_issue(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', request, runtime=case.runtime) == saved
    async with case.ctx['repository'].transaction() as connection:
        assert await connection.scalar(select(func.count()).select_from(audit_events).where(audit_events.c.action == 'report_issue_resolved')) == 1
    with pytest.raises(IntegrityError):
        async with case.ctx['repository'].engine.begin() as connection:
            await connection.execute(update(report_basis_receipts).where(report_basis_receipts.c.receipt_id == receipt_id).values(content_hash='0' * 64))
    import os
    import tempfile
    from pathlib import Path
    out = Path(tempfile.gettempdir()) / f'smart-reporting-issue-resolution-{os.getpid()}'
    out.mkdir(exist_ok=True)
    (out / 'resolution.json').write_text(saved.model_dump_json(by_alias=True, indent=2) + '\n')


async def test_resolution_rejects_source_revocation_after_check(approval_context, monkeypatch):
    from smart_reporting.management import report_issue_resolutions as module
    from smart_reporting.management.models import ManagementError

    case = approval_context
    selected = await signed(case)
    request = {**selected, 'requestId': 'revoked-before-commit', 'mode': 'not_recalculated', 'decisionReason': '必须核验当前状态。',
        'notRecalculatedReason': '保留旧报告。', 'originalReportUnchanged': True}
    check = module.check_resolution_evidence
    async def revoke_after_check(*args, **kwargs):
        result = await check(*args, **kwargs)
        documents = case.runtime.business_evidence_service.documents
        detail = await documents.get_document(case.ctx['token'], case.ctx['scope'], case.document)
        await documents.review_revision(case.ctx['token'], case.ctx['scope'], case.document, 1, decision='revoked',
            reason='关闭写入前撤销，必须拒绝旧检查。', expected_version=detail['revisions'][0]['stateVersion'])
        return result
    monkeypatch.setattr(module, 'check_resolution_evidence', revoke_after_check)
    with pytest.raises(ManagementError) as changed:
        await module.resolve_issue(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', request, runtime=case.runtime)
    assert changed.value.status == 409
    assert await module.read_resolution(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', request['requestId']) is None
    assert (await case.service.report_list(**case.binding))['items'][0]['review']['status'] == 'accepted'


async def test_concurrent_resolution_registers_one_close_and_one_audit(approval_context):
    import asyncio

    from smart_reporting.management.report_issue_resolutions import resolve_issue
    from smart_reporting.management.repository import audit_events

    case = approval_context
    selected = await signed(case)
    request = {**selected, 'requestId': 'concurrent-close', 'mode': 'not_recalculated', 'decisionReason': '并发显式关闭保持唯一。',
        'notRecalculatedReason': '只修后续规则，不重发历史。', 'originalReportUnchanged': True}
    results = await asyncio.gather(*(resolve_issue(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', request,
        runtime=case.runtime) for _ in range(2)))
    assert results[0] == results[1] and results[0].resolved_issue_version == 3
    async with case.ctx['repository'].transaction() as connection:
        assert await connection.scalar(select(func.count()).select_from(audit_events).where(audit_events.c.action == 'report_issue_resolved')) == 1


async def test_closed_issue_exposes_its_exact_resolution_request_for_authorized_reopening(approval_context):
    from smart_reporting.management.report_issue_resolutions import read_resolution, resolve_issue

    case = approval_context
    selected = await signed(case)
    payload = {**selected, 'requestId': 'reopen-closed-detail', 'mode': 'not_recalculated', 'decisionReason': '明确关闭后仍须找回处理证据。',
        'notRecalculatedReason': '历史报告保留，不重发。', 'originalReportUnchanged': True}
    closed = await resolve_issue(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', payload, runtime=case.runtime)
    report_item = (await case.service.report_list(**case.binding))['items'][0]
    admin_item = (await case.service.admin_list(case.ctx['token'], case.ctx['scope'], issue_id='issue-C02'))['items'][0]
    assert admin_item['resolutionRequestId'] == report_item['resolutionRequestId'] == payload['requestId']
    assert await read_resolution(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', admin_item['resolutionRequestId']) == closed
