"""单实例管理入口无需组织登记、选择或参数。"""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
from smart_reporting.management.metrics_api import create_metrics_router
from smart_reporting.management.settings import ManagementSettings
from smart_reporting.reporting.tests.test_semantic_models import metric_payload


@pytest.mark.anyio
async def test_metric_endpoints_use_instance_configuration_without_organization_parameters():
    auth = SimpleNamespace(authenticate=AsyncMock(return_value=object()))
    service = SimpleNamespace(scopes=SimpleNamespace(auth=auth), list=AsyncMock(return_value={"items": [], "nextCursor": None}),
        save_draft=AsyncMock(return_value={"version": 1}))
    app = FastAPI()
    app.include_router(create_metrics_router(service, ManagementSettings(public_origin="https://reports.example")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://reports.example") as client:
        client.cookies.set(SESSION_COOKIE, "fixture-session")
        response = await client.get("/management/api/v1/metrics")
        assert response.status_code == 200
        await client.get("/management/api/v1/metrics?scopeDatabase=foreign&companyId=foreign")
        assert service.list.await_args_list[0].args[1] == service.list.await_args_list[1].args[1]
        definition = {key: value for key, value in metric_payload().items() if key not in {"scopeId", "revision"}}
        response = await client.put("/management/api/v1/metrics/budget/draft", json={"expectedVersion": 0, "definition": definition},
            headers={"origin": "https://reports.example", "x-csrf-token": csrf_token("fixture-session")})
        assert response.status_code == 200
        assert service.save_draft.await_args.args[1] == service.list.await_args.args[1]


@pytest.mark.parametrize("module_name", ["metrics_api", "statistical_policy_api", "business_documents_api", "business_evidence_api", "catalog_api", "import_api", "report_issue_reviews_api", "data_sources.api"])
def test_management_write_contracts_do_not_expose_organization_fields(module_name):
    module = importlib.import_module("smart_reporting.management." + module_name)
    for value in vars(module).values():
        if isinstance(value, type) and issubclass(value, BaseModel) and value.__module__ == module.__name__:
            properties = value.model_json_schema(by_alias=True).get("properties", {})
            assert not {"scopeDatabase", "companyId"}.intersection(properties), value.__name__


def test_organization_management_routes_are_removed():
    auth = SimpleNamespace(repository=object())
    router = create_management_router(auth, ManagementSettings())
    app = FastAPI()
    app.include_router(router)
    assert not any("/scopes" in path for path in app.openapi()["paths"])
    assert not any(getattr(route, "path", None) == "/management/organizations" for route in router.routes)


def test_catalog_version_options_do_not_require_organization_query_parameters():
    from smart_reporting.management.version_options import create_version_options_router
    auth = SimpleNamespace(repository=object())
    app = FastAPI()
    app.include_router(create_version_options_router(SimpleNamespace(auth=auth)))
    parameters = app.openapi()["paths"]["/management/api/v1/sources/{source_id}/catalog/versions"]["get"]["parameters"]
    assert not {"scopeDatabase", "companyId"}.intersection(item["name"] for item in parameters)
