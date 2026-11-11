"""从精确原件修订找回任务，不暴露内部租约、路径或请求摘要。"""

import httpx
import pytest
from fastapi import FastAPI

from smart_reporting.management.api import SESSION_COOKIE
from smart_reporting.tests.test_business_document_ingestion import (
    document_context as document_context,
)
from smart_reporting.tests.test_business_document_ingestion import metadata, register
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_revision_jobs_are_exact_scoped_and_expose_only_public_receipts(document_context):
    service, token, scope, other, *_ = document_context
    first = await register(document_context)
    second = await register(document_context, "second", expected_version=1)
    foreign = (service, token, other, scope, document_context[5], document_context[4])
    other_job = await register(foreign, details=metadata(title="另一组织同名原件"))
    result = await service.list_revision_jobs(token, scope, "budget-rules", 1)
    assert result == {
        "items": [
            (await service.get_job(token, scope, first.job_id)).model_dump(
                mode="json", by_alias=True
            )
        ],
        "nextCursor": None,
    }
    assert (await service.list_revision_jobs(token, scope, "budget-rules", 2))["items"][0][
        "jobId"
    ] == second.job_id
    assert (await service.list_revision_jobs(token, other, "budget-rules", 1))["items"][0][
        "jobId"
    ] == other_job.job_id
    assert set(result["items"][0]) == {
        "jobId",
        "documentId",
        "revision",
        "attempt",
        "status",
        "issueCodes",
    }


async def test_revision_jobs_http_requires_session_scope_and_real_revision(document_context):
    from smart_reporting.management.business_documents_api import create_business_documents_router
    from smart_reporting.management.settings import ManagementSettings

    service, token, scope, *_ = document_context
    receipt = await register(document_context)
    app = FastAPI()
    app.include_router(
        create_business_documents_router(
            service, ManagementSettings(public_origin="https://reports.example")
        )
    )
    path = "/management/api/v1/business-documents/budget-rules/revisions/1/ingestion-jobs"
    params = {"scopeDatabase": scope.database, "companyId": scope.company_id}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://reports.example"
    ) as client:
        assert (await client.get(path, params=params)).status_code == 401
        client.cookies.set(SESSION_COOKIE, token, path="/management")
        result = await client.get(path, params=params)
        assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
        assert result.json()["items"][0]["jobId"] == receipt.job_id
        assert (await client.get(path, params={**params, "companyId": "b"})).status_code == 404
        assert (await client.get(path.replace("/1/", "/99/"), params=params)).status_code == 404
        for patch in ({"limit": 0}, {"after": "x" * 129}):
            assert (await client.get(path, params={**params, **patch})).status_code == 422
