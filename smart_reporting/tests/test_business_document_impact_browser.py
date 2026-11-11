"""真实管理HTTP/浏览器撤销与登记依据核对，不生成报告或查询业务库。"""

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
    return "asyncio"


async def test_browser_revocation_impact_unknown_recovery_and_frozen_basis(
    basis_context, document_context
):
    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.business_evidence_api import create_business_evidence_router
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import audit_events
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.tests.report_issue_browser_flow import run_management_browser
    from smart_reporting.tests.test_business_document_ingestion import metadata, register
    from smart_reporting.tests.test_report_evidence_retrieval import registered_basis, search

    ctx = basis_context
    documents, token, scope, other = document_context[:4]
    policies = ctx["policy_service"]
    bases, original_basis = await registered_basis(ctx)
    before = await documents.get_document(token, scope, "budget-rules")
    impact = await documents.read_revision_impact(token, scope, "budget-rules", 1)
    assert {row["kind"] for row in impact["items"]} == {
        "evidence_release",
        "policy",
        "default",
        "report",
    }
    default_before = await policies.get_default(token, scope, "budget_execution")
    foreign_context = (documents, token, other, scope, document_context[5], document_context[4])
    await register(foreign_context, details=metadata(title="另一组织同名原件"))
    foreign = await documents.get_document(token, other, "budget-rules")
    app = FastAPI()
    settings = ManagementSettings(public_origin="http://127.0.0.1:5206", allow_local_http=True)
    app.include_router(create_management_router(documents.scopes.auth, settings))
    app.include_router(create_business_documents_router(documents, settings))
    app.include_router(create_business_evidence_router(policies.evidence, settings))
    output = Path("/tmp") / f"smart-reporting-document-impact-browser-{os.getpid()}"
    output.mkdir()
    browser = await run_management_browser(
        app,
        {
            "token": token,
            "database": scope.database,
            "companyId": scope.company_id,
            "basisId": original_basis.id,
        },
        output,
        script="smoke/management-document-impact-postgres-smoke.mjs",
    )
    assert browser["writes"] == 1 and browser["unknownResponseReadback"]
    current = await documents.get_document(token, scope, "budget-rules")
    assert current["revisions"][0]["reviewStatus"] == "revoked"
    assert current["revisions"][0]["originalHash"] == before["revisions"][0]["originalHash"]
    assert await documents.read_revision_impact(token, scope, "budget-rules", 1) == impact
    restored = await ReportBasisService(ctx["scopes"]).load_report_basis(
        "run-basis", scope, user_id="7", thread_id="thread-basis"
    )
    assert restored == original_basis
    with pytest.raises(ManagementError) as error:
        await documents.read_original(token, scope, "budget-rules", 1)
    assert error.value.status == 403
    result = await search(policies.evidence, bases, ctx)
    assert not result.search or not result.search.hits
    default_after = await policies.get_default(token, scope, "budget_execution")
    assert default_after["version"] == default_before["version"]
    assert (
        default_after["policyVersion"] == default_before["policyVersion"]
        and default_after["issues"]
    )
    assert await documents.get_document(token, other, "budget-rules") == foreign
    async with ctx["repository"].transaction() as connection:
        audits = list(
            (
                await connection.execute(
                    select(audit_events.c.action).where(
                        audit_events.c.action == "business_document_reviewed"
                    )
                )
            ).scalars()
        )
    assert len(audits) == 2  # 初始批准一次，浏览器撤销一次。
    (output / "database-evidence.json").write_text(
        json.dumps(
            {
                "before": before,
                "current": current,
                "impactBefore": impact,
                "impactAfter": await documents.read_revision_impact(
                    token, scope, "budget-rules", 1
                ),
                "oldBasis": original_basis.model_dump(mode="json"),
                "restoredBasis": restored.model_dump(mode="json"),
                "defaultBefore": default_before,
                "defaultAfter": default_after,
                "retrievalAfter": result.model_dump(mode="json"),
                "foreignBefore": foreign,
                "foreignAfter": await documents.get_document(token, other, "budget-rules"),
                "auditActions": audits,
                "fixtureScope": "真实隔离PG/管理HTTP/Agno固定合成向量；合成原件撤销，无业务SQL、真实模型、StarRocks、报告生成或业务负责人确认",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
