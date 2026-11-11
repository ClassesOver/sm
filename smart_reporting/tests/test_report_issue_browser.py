"""正式关闭的真实隔离PG验证；不重算裁定不冒充新报告交付。"""

import pytest
from sqlalchemy import select

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

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_browser_signoff_and_no_recalculation_close_use_same_postgres(approval_context, tmp_path):
    import json
    import os
    from pathlib import Path

    from fastapi import FastAPI

    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.report_issue_business_approvals import read_approval
    from smart_reporting.management.report_issue_resolutions import read_resolution
    from smart_reporting.management.repository import audit_events
    from smart_reporting.management.settings import ManagementSettings

    case = approval_context
    app = FastAPI()
    settings = ManagementSettings(public_origin='http://127.0.0.1:5193', allow_local_http=True)
    app.include_router(create_management_router(case.ctx['scopes'].auth, settings, report_runtime=case.runtime))
    app.include_router(create_business_documents_router(case.runtime.business_evidence_service.documents, settings))
    from smart_reporting.tests.report_issue_browser_flow import run_management_browser

    out = Path('/tmp') / f'smart-reporting-issue-pg-browser-{os.getpid()}'
    out.mkdir()
    evidence = await run_management_browser(app, {
        'token': case.ctx['token'], 'database': case.ctx['scope'].database, 'companyId': case.ctx['scope'].company_id,
        'issueId': 'issue-C02', 'sourceTitle': '合成独立预期对账',
    }, out)
    assert evidence['signingPosts'] == evidence['closingPosts'] == 1
    assert evidence['closureReads'] == 2
    assert evidence['seriousOrCritical'] == [] and not evidence['overflow']
    item = (await case.service.report_list(**case.binding))['items'][0]
    assert item['review']['status'] == 'resolved' and item['version'] == 3
    assert item['resolutionRequestId'] == evidence['closureRequestId']
    closure = await read_resolution(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', evidence['closureRequestId'])
    approval = await read_approval(case.service, case.ctx['token'], case.ctx['scope'], 'issue-C02', evidence['approvalRequestId'])
    assert closure.evidence.approval_receipt_id == approval.receipt_id
    assert closure.request.mode == 'not_recalculated' and not closure.evidence.delivery_ready
    assert closure.request.regression_receipt_ids == (case.regression.receipt_id,)
    async with case.ctx['repository'].transaction() as connection:
        events = (await connection.execute(select(audit_events.c.action).where(
            audit_events.c.action.in_(['report_issue_resolved', 'report_issue_expectations_approved'])))).scalars().all()
    assert sorted(events) == ['report_issue_expectations_approved', 'report_issue_resolved']
    (out / 'database-evidence.json').write_text(json.dumps({'issue': item,
        'closure': closure.model_dump(mode='json', by_alias=True), 'approvalReceiptId': approval.receipt_id,
        'auditActions': sorted(events)}, ensure_ascii=False, indent=2))
