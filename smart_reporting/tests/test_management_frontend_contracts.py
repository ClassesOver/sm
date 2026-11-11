from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from smart_reporting.management.api import csrf_token
from smart_reporting.management.data_sources.api import create_source_router
from smart_reporting.management.repository import source_credentials, source_drafts
from smart_reporting.tests.management_fixtures import publish_dependencies
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_management_release_dependencies import (
    release_context as release_context,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_editor_preserves_credentials_and_checks_release(release_context, monkeypatch):
    service, scopes, repo, token, scope = release_context
    monkeypatch.setenv("AGENT_MANAGEMENT_PUBLIC_ORIGIN", "https://reports.test")
    app = FastAPI()
    app.include_router(create_source_router(scopes, service.vault))
    query = {"scopeDatabase": scope.database, "companyId": scope.company_id}
    headers = {"origin": "https://reports.test", "x-csrf-token": csrf_token(token)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://reports.test"
    ) as c:
        c.cookies.set("report_management_session", token, path="/management")
        url = "/management/api/v1/sources/operations"
        detail = await c.get(url, params=query)
        assert detail.status_code == 200, detail.text
        assert detail.json()["published"] is None
        check = await c.get(url + "/release-check", params={**query, "expectedVersion": 1})
        assert check.status_code == 200 and check.json()["canPublish"] is False
        async with repo.engine.connect() as db:
            before = (await db.execute(select(source_drafts))).mappings().one()
            count = await db.scalar(select(func.count()).select_from(source_credentials))
        body = {
            **query,
            "expectedVersion": 1,
            "name": "新名称",
            "database": "warehouse",
            "reportingProfileVersionId": "base:1",
            "metadataVersionId": "operations:1",
        }
        saved = await c.put(url + "/draft", json=body, headers=headers)
        assert saved.status_code == 200, saved.text
        async with repo.engine.connect() as db:
            after = (await db.execute(select(source_drafts))).mappings().one()
            assert after["credential_ref"] == before["credential_ref"]
            assert after["credential_revision"] == before["credential_revision"]
            assert await db.scalar(select(func.count()).select_from(source_credentials)) == count
        assert (
            await c.put(
                url + "/draft", json={**body, "expectedVersion": 2, "dsn": None}, headers=headers
            )
        ).status_code == 422
        assert (
            await c.put(
                url + "/draft",
                json={**body, "expectedVersion": 2, "database": "other"},
                headers=headers,
            )
        ).status_code == 422
        assert (await c.put(url + "/draft", json=body, headers=headers)).status_code == 409
        await publish_dependencies(scopes, token, scope, draft_version=2)
        check = await c.get(url + "/release-check", params={**query, "expectedVersion": 2})
        assert check.status_code == 200 and check.json()["canPublish"] is True, check.text
        assert "test-secret" not in check.text
        pub = await c.post(url + "/publish", json={**query, "expectedVersion": 2}, headers=headers)
        assert pub.status_code == 200, pub.text
        detail = (await c.get(url, params=query)).json()
        assert detail["hasUnpublishedChanges"] is False
        assert detail["published"]["revision"] == 1
        filtered = await c.get("/management/api/v1/sources", params={**query, "q": "不存在"})
        assert filtered.json()["items"] == []
        filtered = await c.get(
            "/management/api/v1/sources", params={**query, "publicationState": "changed"}
        )
        assert filtered.json()["items"] == []


async def test_version_options_are_scoped_and_precheck_does_not_authorize_future_publish(
    release_context, monkeypatch
):
    from smart_reporting.management.data_sources.models import SourceDraftInput
    from smart_reporting.management.models import ManagementScope
    from smart_reporting.management.version_options import create_version_options_router

    service, scopes, repo, token, scope = release_context
    monkeypatch.setenv("AGENT_MANAGEMENT_PUBLIC_ORIGIN", "https://reports.test")
    await publish_dependencies(scopes, token, scope)
    foreign = ManagementScope(scope.database, "foreign")
    await scopes.register(token, foreign, "其他机构")
    app = FastAPI()
    app.include_router(create_version_options_router(scopes))
    app.include_router(create_source_router(scopes, service.vault))
    headers = {"origin": "https://reports.test", "x-csrf-token": csrf_token(token)}
    query = {"scopeDatabase": scope.database, "companyId": scope.company_id}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://reports.test"
    ) as c:
        c.cookies.set("report_management_session", token, path="/management")
        for path in ["/profiles/versions", "/sources/operations/catalog/versions"]:
            response = await c.get("/management/api/v1" + path, params=query)
            assert response.status_code == 200, response.text
            assert len(response.json()["items"]) == 1
            if "catalog" in path:
                assert response.json()["items"][0]["publishedAt"] is None
                assert response.json()["items"][0]["syncedAt"]
            assert (
                await c.get("/management/api/v1" + path, params={**query, "after": "not-a-cursor"})
            ).status_code == 422
        response = await c.get(
            "/management/api/v1/profiles/versions", params={**query, "companyId": "foreign"}
        )
        assert response.json()["items"] == []
        assert (
            await c.get(
                "/management/api/v1/sources/operations", params={**query, "companyId": "foreign"}
            )
        ).status_code == 404
        check = await c.get(
            "/management/api/v1/sources/operations/release-check",
            params={**query, "expectedVersion": 1},
        )
        assert check.json()["canPublish"] is True
        await service.save_draft(
            token,
            scope,
            "operations",
            SourceDraftInput.model_validate({"name": "并发更新", "database": "warehouse"}),
            1,
        )
        published = await c.post(
            "/management/api/v1/sources/operations/publish",
            json={**query, "expectedVersion": 1},
            headers=headers,
        )
        assert published.status_code == 409
        assert (await service.detail(token, scope, "operations"))["published"] is None


async def test_search_is_literal_and_status_uses_hash_not_draft_version(release_context):
    from smart_reporting.management.data_sources.models import SourceDraftInput
    from smart_reporting.management.repository import source_versions

    service, scopes, repo, token, scope = release_context
    await publish_dependencies(scopes, token, scope)
    original = await service.publish(token, scope, "operations", 1)
    payload = SourceDraftInput.model_validate(
        {
            "name": "收入100%_!",
            "database": "warehouse",
            "reportingProfileVersionId": "base:1",
            "metadataVersionId": "operations:1",
        }
    )
    await service.save_draft(token, scope, "operations", payload, 1)
    await service.create_draft(
        token,
        scope,
        "other",
        SourceDraftInput.model_validate(
            {
                "name": "收入100XYZ",
                "database": "warehouse",
                "dsn": "starrocks://r:test@localhost:9030/warehouse",
            }
        ),
    )
    for query in ["%", "_", "!", "OPERATIONS"]:
        result = await service.list(token, scope, q=query)
        assert [row["source_id"] for row in result["items"]] == ["operations"]
    assert len((await service.list(token, scope, publication_state="changed"))["items"]) == 1
    published = await service.publish(token, scope, "operations", 2)
    assert published["revision"] == 2
    await service.save_draft(token, scope, "operations", payload, 2)
    assert (await service.list(token, scope, publication_state="changed"))["items"] == []
    async with repo.engine.connect() as db:
        historical = (
            (
                await db.execute(
                    select(source_versions).where(
                        source_versions.c.source_id == "operations", source_versions.c.revision == 1
                    )
                )
            )
            .mappings()
            .one()
        )
        assert historical["content_hash"] == original["contentHash"]
        assert historical["name"] == original["name"]
        assert (
            await db.scalar(
                select(func.count())
                .select_from(source_credentials)
                .where(source_credentials.c.source_id == "operations")
            )
            == 1
        )


async def test_published_version_cursor_is_stable_and_strict(release_context):
    from smart_reporting.management.profiles import ProfileService
    from smart_reporting.management.version_options import create_version_options_router

    service, scopes, repo, token, scope = release_context
    profiles = ProfileService(scopes)
    for identifier in ["alpha", "base", "zeta"]:
        draft = await profiles.save_draft(
            token, scope, {"profileId": identifier, "revision": "r1", "dimensions": []}, 0
        )
        await profiles.publish(token, scope, identifier, draft["version"])
    app = FastAPI()
    app.include_router(create_version_options_router(scopes))
    query = {"scopeDatabase": scope.database, "companyId": scope.company_id, "limit": 1}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://reports.test"
    ) as client:
        client.cookies.set("report_management_session", token, path="/management")
        refs = []
        cursor = None
        for _ in range(3):
            response = await client.get(
                "/management/api/v1/profiles/versions",
                params={**query, **({"after": cursor} if cursor else {})},
            )
            assert response.status_code == 200, response.text
            refs.extend(row["ref"] for row in response.json()["items"])
            cursor = response.json()["nextCursor"]
            if len(refs) == 1:
                malformed = await client.get(
                    "/management/api/v1/profiles/versions", params={**query, "after": cursor + "$"}
                )
                assert malformed.status_code == 422
        assert refs == ["alpha:1", "base:1", "zeta:1"]
        assert cursor is None
