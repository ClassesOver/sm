"""真实双管理员并发口径草稿；合并只改变明确选定字段。"""

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


async def test_browser_explicit_policy_conflict_merge_preserves_published_default_and_basis(
    basis_context,
):
    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.business_evidence_api import create_business_evidence_router
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import audit_events
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.management.statistical_policy_api import create_statistical_policy_router
    from smart_reporting.tests.report_issue_browser_flow import run_management_browser
    from smart_reporting.tests.test_report_evidence_retrieval import registered_basis

    ctx = basis_context
    policies, token, scope = ctx["policy_service"], ctx["token"], ctx["scope"]
    _, basis = await registered_basis(ctx)
    before = await policies.get(token, scope, "monthly-budget")
    default = await policies.get_default(token, scope, "budget_execution")
    app = FastAPI()
    settings = ManagementSettings(public_origin="http://127.0.0.1:5207", allow_local_http=True)
    app.include_router(create_management_router(ctx["scopes"].auth, settings))
    app.include_router(create_statistical_policy_router(policies, settings))
    app.include_router(create_business_evidence_router(policies.evidence, settings))
    output = Path("/tmp") / f"smart-reporting-policy-conflict-browser-{os.getpid()}"
    output.mkdir()
    browser = await run_management_browser(
        app,
        {"token": token, "database": scope.database, "companyId": scope.company_id},
        output,
        script="smoke/management-policy-conflict-postgres-smoke.mjs",
    )
    assert browser["conflicts"] == browser["writes"] == 1 and browser["unknownResponseReadback"]
    current = await policies.get(token, scope, "monthly-budget")
    assert current["draft"]["version"] == 3
    assert current["draft"]["document"]["name"] == "本地保留的口径名称"
    assert current["draft"]["document"]["decisionNotes"] == "另一管理员补充的决策说明"
    assert current["published"] == before["published"]
    assert await policies.get_default(token, scope, "budget_execution") == default
    restored = await ReportBasisService(ctx["scopes"]).load_report_basis(
        "run-basis", scope, user_id="7", thread_id="thread-basis"
    )
    assert restored == basis
    async with ctx["repository"].transaction() as connection:
        audits = list(
            (
                await connection.execute(
                    select(audit_events.c.action).where(
                        audit_events.c.action.in_(
                            [
                                "statistical_policy_draft_saved",
                                "statistical_policy_published",
                                "report_policy_default_set",
                            ]
                        )
                    )
                )
            ).scalars()
        )
    assert audits.count("statistical_policy_draft_saved") == 3  # 初始化、并发管理员、明确合并。
    assert (
        audits.count("statistical_policy_published")
        == audits.count("report_policy_default_set")
        == 1
    )
    (output / "database-evidence.json").write_text(
        json.dumps(
            {
                "before": before,
                "current": current,
                "defaultBefore": default,
                "defaultAfter": await policies.get_default(token, scope, "budget_execution"),
                "oldBasis": basis.model_dump(mode="json"),
                "restoredBasis": restored.model_dump(mode="json"),
                "auditActions": audits,
                "fixtureScope": "真实隔离PG/管理HTTP并发CAS；合成业务定义，无业务SQL/模型/StarRocks/报告生成或业务负责人确认",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
