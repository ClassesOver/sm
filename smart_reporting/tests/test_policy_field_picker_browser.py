"""真实已发布字段目录选择；保存与发布仍为独立操作。"""

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


async def test_browser_policy_field_selection_preserves_rules_published_and_basis(
    basis_context,
):
    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.business_evidence_api import create_business_evidence_router
    from smart_reporting.management.data_sources.api import create_source_router
    from smart_reporting.management.metrics import MetricService
    from smart_reporting.management.metrics_api import create_metrics_router
    from smart_reporting.management.report_bases import ReportBasisService
    from smart_reporting.management.repository import audit_events
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.management.statistical_policy_api import create_statistical_policy_router
    from smart_reporting.tests.report_issue_browser_flow import run_management_browser
    from smart_reporting.tests.test_report_evidence_retrieval import registered_basis

    ctx = basis_context
    policies, token, scope = ctx["policy_service"], ctx["token"], ctx["scope"]
    _, basis = await registered_basis(ctx)
    metrics = MetricService(ctx["scopes"])
    before = await metrics.get(token, scope, "budget")
    original = await policies.get(token, scope, "monthly-budget")
    definition = {
        key: value
        for key, value in original["draft"]["document"].items()
        if key not in ("scopeId", "revision")
    }
    definition.update(
        filters=[
            {"fieldRef": "warehouse.test.budget.project_id", "operator": "eq", "values": ["A"]}
        ],
        joins=[
            {
                "leftKeys": ["warehouse.test.budget.project_id"],
                "rightKeys": ["warehouse.test.budget.project_id"],
                "cardinality": "many_to_one",
                "outputGrain": ["project"],
            }
        ],
        readinessPolicy={
            "expectedPeriods": [{"start": "2026-01-01", "end": "2027-01-01"}],
            "expectedGroups": [[{"dimensionId": "project", "value": "A"}]],
            "watermarkField": "warehouse.test.budget.period",
            "maximumDelaySeconds": 3600,
            "emptyObservation": "unknown",
        },
    )
    await policies.save_draft(token, scope, definition, expected_version=1)
    policy_before = await policies.get(token, scope, "monthly-budget")
    default = await policies.get_default(token, scope, "budget_execution")
    app = FastAPI()
    settings = ManagementSettings(public_origin="http://127.0.0.1:5210", allow_local_http=True)
    app.include_router(create_management_router(ctx["scopes"].auth, settings))
    app.include_router(create_metrics_router(metrics, settings))
    app.include_router(create_statistical_policy_router(policies, settings))
    app.include_router(create_source_router(ctx["scopes"], ctx["vault"]))
    app.include_router(create_business_evidence_router(policies.evidence, settings))
    output = Path("/tmp") / f"smart-reporting-policy-field-picker-browser-{os.getpid()}"
    output.mkdir()
    browser = await run_management_browser(
        app,
        {"token": token, "database": scope.database, "companyId": scope.company_id},
        output,
        script="smoke/management-policy-field-picker-postgres-smoke.mjs",
    )
    assert (
        browser["writes"] == 1
        and browser["unknownResponseReadback"]
        and browser["fourFieldsSelected"]
    )
    current = await policies.get(token, scope, "monthly-budget")
    assert (
        current["draft"]["version"] == 3
        and current["draft"]["document"]["name"] == "目录选择后的口径"
    )
    assert current["published"] == original["published"]
    document = current["draft"]["document"]
    assert document["filters"] == definition["filters"] and document["joins"] == definition["joins"]
    assert document["readinessPolicy"] == {
        **definition["readinessPolicy"],
        "watermarkField": "warehouse.test.budget.period",
    }
    assert await metrics.get(token, scope, "budget") == before
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
    assert audits.count("statistical_policy_draft_saved") == 3  # 初始化、准备规则与明确保存。
    assert (
        audits.count("statistical_policy_published")
        == audits.count("report_policy_default_set")
        == 1
    )
    (output / "database-evidence.json").write_text(
        json.dumps(
            {
                "before": before,
                "policyBefore": policy_before,
                "metricAfter": await metrics.get(token, scope, "budget"),
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
