"""撤销前核对登记引用；历史依据不从当前默认反推。"""

import httpx
import pytest
from fastapi import FastAPI

from smart_reporting.management.api import SESSION_COOKIE
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


async def test_document_impact_tracks_rules_background_and_frozen_reports(
    basis_context, document_context
):
    from smart_reporting.reporting.business_knowledge.retrieval import DocumentRevisionRef
    from smart_reporting.tests.test_business_document_ingestion import metadata, register
    from smart_reporting.tests.test_report_evidence_retrieval import registered_basis

    ctx = basis_context
    service, token, scope, other = document_context[:4]
    policies = ctx["policy_service"]
    await register(
        document_context, "background-impact", details=metadata(id="context", kind="background")
    )
    await service.ingest_revision(await service.claim_next())
    detail = await service.get_document(token, scope, "context")
    await service.review_revision(
        token,
        scope,
        "context",
        1,
        decision="approved",
        reason="合成背景核对",
        expected_version=detail["revisions"][0]["stateVersion"],
    )
    background = await policies.evidence.publish(
        token,
        scope,
        request_id="impact-background-release",
        kind="background",
        revision_ids=(DocumentRevisionRef(document_id="context", revision=1),),
    )
    await policies.set_default(
        token,
        scope,
        "budget_execution",
        policy_version={"policyId": "monthly-budget", "revision": 1},
        background_release_id=background.release_id,
        expected_version=1,
    )
    bases, original_basis = await registered_basis(ctx)
    foreign = (service, token, other, scope, document_context[5], document_context[4])
    await register(foreign, details=metadata(title="另一组织同名原件"))

    async def pages(document_id, revision):
        items, after = [], None
        while True:
            result = await service.read_revision_impact(
                token, scope, document_id, revision, limit=1, after=after
            )
            assert result["documentRevision"] == {"documentId": document_id, "revision": revision}
            items.extend(result["items"])
            after = result["nextCursor"]
            if after is None:
                return items

    rules = await pages("budget-rules", 1)
    assert {(row["kind"], row["referenceId"]) for row in rules} == {
        ("evidence_release", ctx["release_id"]),
        ("policy", "monthly-budget"),
        ("default", "budget_execution"),
        ("report", "run-basis"),
    }
    assert next(row for row in rules if row["kind"] == "report")["basisId"] == original_basis.id
    assert {(row["kind"], row["referenceId"]) for row in await pages("context", 1)} == {
        ("evidence_release", background.release_id),
        ("default", "budget_execution"),
        ("report", "run-basis"),
    }
    await policies.set_default(
        token,
        scope,
        "budget_execution",
        policy_version={"policyId": "monthly-budget", "revision": 1},
        background_release_id=None,
        expected_version=2,
    )
    assert {row["kind"] for row in await pages("context", 1)} == {"evidence_release", "report"}
    await register(document_context, "rules-new-revision", expected_version=1)
    assert await pages("budget-rules", 2) == []
    assert (await service.read_revision_impact(token, other, "budget-rules", 1))["items"] == []
    before = await pages("budget-rules", 1)
    detail = await service.get_document(token, scope, "budget-rules")
    first = next(r for r in detail["revisions"] if r["revision"] == 1)
    await service.review_revision(
        token,
        scope,
        "budget-rules",
        1,
        decision="revoked",
        reason="合成撤销验收",
        expected_version=first["stateVersion"],
    )
    assert await pages("budget-rules", 1) == before
    assert (
        await bases.load_report_basis("run-basis", scope, user_id="7", thread_id="thread-basis")
        == original_basis
    )


async def test_document_impact_http_checks_session_scope_revision_and_paging(document_context):
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.tests.test_business_document_ingestion import register

    service, token, scope, *_ = document_context
    await register(document_context)
    app = FastAPI()
    app.include_router(
        create_business_documents_router(
            service, ManagementSettings(public_origin="https://reports.example")
        )
    )
    path = "/management/api/v1/business-documents/budget-rules/revisions/1/impact"
    params = {"scopeDatabase": scope.database, "companyId": scope.company_id}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://reports.example"
    ) as client:
        assert (await client.get(path, params=params)).status_code == 401
        client.cookies.set(SESSION_COOKIE, token, path="/management")
        result = await client.get(path, params=params)
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store"
        assert result.json() == {
            "documentRevision": {"documentId": "budget-rules", "revision": 1},
            "items": [],
            "nextCursor": None,
        }
        assert (await client.get(path, params={**params, "companyId": "b"})).status_code == 404
        assert (await client.get(path.replace("/1/", "/99/"), params=params)).status_code == 404
        for patch in ({"limit": 0}, {"limit": 101}, {"after": "x" * 401}):
            assert (await client.get(path, params={**params, **patch})).status_code == 422
