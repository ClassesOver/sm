"""连接与目录独立发布；旧业务Profile输入不可进入新数据源契约。"""

import pytest
from pydantic import ValidationError

from smart_reporting.tests.test_report_basis_persistence import (
    auth_context as auth_context,
)
from smart_reporting.tests.test_report_basis_persistence import basis_context as basis_context
from smart_reporting.tests.test_report_basis_persistence import (
    document_context as document_context,
)
from smart_reporting.tests.test_report_basis_persistence import (
    index_context as index_context,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_old_profile_field_is_rejected_even_when_null():
    from smart_reporting.management.data_sources.models import SourceDraftInput
    for value in (None, "base:1"):
        with pytest.raises(ValidationError):
            SourceDraftInput.model_validate({"name": "连接", "database": "test",
                "reportingProfileVersionId": value})


async def test_new_connection_and_catalog_publish_without_any_profile_dependency(basis_context):
    from sqlalchemy import select

    from smart_reporting.management.catalog import CatalogService
    from smart_reporting.management.data_sources.models import SourceDraftInput
    from smart_reporting.management.data_sources.service import SourceService
    from smart_reporting.management.repository import catalog_versions, source_versions
    service = SourceService(basis_context["scopes"], basis_context["vault"])
    created = await service.create_draft(basis_context["token"], basis_context["scope"], "new-source",
        SourceDraftInput(name="独立连接", database="test",
            dsn="starrocks://reporter:synthetic-only@localhost:9030/test", metadataVersionId="new-source:1"))
    assert "profile_version_id" not in created
    assert "reportingProfileVersionId" not in created
    async with basis_context["repository"].transaction() as connection:
        from smart_reporting.tests.management_fixtures import business_metadata, physical_catalog
        catalog = {"tables": CatalogService._payload(physical_catalog("new-source", "test")),
            "metadata": business_metadata("new-source", "test").model_dump(mode="json", by_alias=True)}
        await connection.execute(catalog_versions.insert().values(
            scope_id=basis_context["scope_id"], source_id="new-source", revision=1, status="published",
            catalog=catalog, content_hash=CatalogService._hash(catalog), synced_at=basis_context["scopes"].auth.clock()))
    check = await service.release_check(basis_context["token"], basis_context["scope"], "new-source", 1)
    assert check["canPublish"] and not check["issues"], check["issues"]
    published = await service.publish(basis_context["token"], basis_context["scope"], "new-source", 1)
    assert published["revision"] == 1 and "reportingProfileVersionId" not in published
    detail = await service.detail(basis_context["token"], basis_context["scope"], "new-source")
    assert "reportingProfileVersionId" not in detail["published"]
    async with basis_context["repository"].engine.connect() as connection:
        row = (await connection.execute(select(source_versions).where(
            source_versions.c.source_id == "new-source"))).mappings().one()
    assert row["profile_version_id"] is None
    assert row["content_hash"] == SourceService._config_hash({"name": "独立连接", "type": "starrocks",
        "database": "test", "metadataVersionId": "new-source:1"}, 1, row["execution_parameters"])


async def test_archived_profile_binding_cannot_be_silently_converted_on_save(basis_context):
    from sqlalchemy import select, update

    from smart_reporting.management.data_sources.models import SourceDraftInput
    from smart_reporting.management.data_sources.service import SourceService
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.repository import source_drafts, source_versions

    ctx = basis_context
    service = SourceService(ctx["scopes"], ctx["vault"])
    await service.create_draft(ctx["token"], ctx["scope"], "archived",
        SourceDraftInput(name="历史连接", database="test",
            dsn="starrocks://reporter:synthetic-only@localhost:9030/test"))
    async with ctx["repository"].transaction() as connection:
        await connection.execute(update(source_drafts).where(source_drafts.c.source_id == "archived")
            .values(profile_version_id="base:1"))
    with pytest.raises(ManagementError) as error:
        await service.save_draft(ctx["token"], ctx["scope"], "archived",
            SourceDraftInput(name="试图转换", database="test"), 1)
    assert error.value.code == "management_source_contract_retired" and error.value.status == 409
    async with ctx["repository"].engine.connect() as connection:
        row = (await connection.execute(select(source_drafts).where(
            source_drafts.c.source_id == "archived"))).mappings().one()
        assert row["version"] == 1 and row["profile_version_id"] == "base:1"
        assert row["name"] == "历史连接"
        assert not (await connection.execute(select(source_versions).where(
            source_versions.c.source_id == "archived"))).all()


async def test_source_file_rejects_old_profile_binding_and_omits_it_from_public_config():
    from smart_reporting.reporting.data_source.starrocks import parse_starrocks_source
    raw = {"id": "operations", "type": "starrocks", "dsnEnv": "TEST_DSN"}
    environ = {"TEST_DSN": "starrocks://reporter:synthetic-only@localhost:9030/test"}
    for value in (None, "base"):
        with pytest.raises(ValueError):
            parse_starrocks_source({**raw, "reportingProfile": value}, environ)
    parsed = parse_starrocks_source(raw, environ)
    assert not hasattr(parsed, "reporting_profile")
    assert "reportingProfile" not in parsed.public_dict()


async def test_retired_freeze_and_restore_refuse_before_any_configuration_io(basis_context):
    from sqlalchemy import event

    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.runtime import ManagedConfigurationProvider
    ctx = basis_context
    provider = ManagedConfigurationProvider(ctx["scopes"], ctx["vault"])
    statements = []
    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    engine = ctx["repository"].engine.sync_engine
    event.listen(engine, "before_cursor_execute", observe)
    try:
        for operation in (
            lambda: provider.freeze("run-basis", ctx["scope"]),
            lambda: provider.load_pinned(ctx["scope"], {"runId": "run-basis", "sources": []}),
        ):
            with pytest.raises(ManagementError) as error:
                await operation()
            assert error.value.code == "report_contract_retired" and error.value.status == 409
        assert not statements
    finally:
        event.remove(engine, "before_cursor_execute", observe)


async def test_old_profile_http_routes_are_authenticated_retired_tombstones(basis_context, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import event

    from smart_reporting.management.api import SESSION_COOKIE, csrf_token
    from smart_reporting.management.profile_api import create_profile_router
    from smart_reporting.management.version_options import create_version_options_router
    ctx = basis_context
    monkeypatch.setenv('AGENT_MANAGEMENT_PUBLIC_ORIGIN', 'https://reports.test')
    app = FastAPI()
    app.include_router(create_profile_router(ctx['scopes']))
    app.include_router(create_version_options_router(ctx['scopes']))
    statements = []
    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    engine = ctx['repository'].engine.sync_engine
    event.listen(engine, 'before_cursor_execute', observe)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.test') as client:
            assert (await client.get('/management/api/v1/profiles/versions')).status_code == 401
            client.cookies.set(SESSION_COOKIE, ctx['token'], path='/management')
            headers = {'origin': 'https://reports.test', 'x-csrf-token': csrf_token(ctx['token'])}
            for method, path in [('GET', '/profiles/versions'), ('POST', '/profiles/preview'),
                ('PUT', '/profiles/base/draft'), ('POST', '/profiles/base/publish'),
                ('GET', '/profiles/base'), ('GET', '/profiles/base/versions/1')]:
                response = await client.request(method, '/management/api/v1'+path, headers=headers,
                    json={'profile': {'profileId': 'base', 'revision': 'r1'}})
                assert response.status_code == 410, (path, response.text)
                assert response.json()['code'] == 'management_profile_retired'
            assert not any('management_profile_' in statement for statement in statements)
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
