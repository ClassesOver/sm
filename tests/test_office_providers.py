import json

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.management.data_sources.secrets import CredentialVault
from smart_reporting.office.repository import Identity, OfficeError, OfficeRepository


@pytest_asyncio.fixture
async def providers():
    from smart_reporting.office.provider_settings import OfficeProviders

    engine = create_async_engine("sqlite+aiosqlite://")
    office = OfficeRepository(engine)
    await office.create_schema()
    admin, user, other = (
        Identity("db", "1", "10"),
        Identity("db", "1", "20"),
        Identity("db", "2", "10"),
    )
    await office.bootstrap(admin, "Admin")
    await office.provision(admin, user.user, "User")
    await office.bootstrap(other, "Other")
    vault = CredentialVault("test:" + CredentialVault.generate_key())
    service = OfficeProviders(office, vault)
    yield service, admin, user, other
    await engine.dispose()


def config(**overrides):
    return dict(
        enabled=True,
        provider="openai",
        model="vision-model",
        baseUrl="https://api.openai.com/v1",
        apiKey="secret-provider-key",
        expectedVersion=0,
        **overrides,
    )


@pytest.mark.asyncio
async def test_encrypted_capability_settings_admin_isolation_and_cas(providers):
    from smart_reporting.office.schema import provider_settings

    service, admin, user, other = providers
    data = await service.save(admin, "imageAnalysis", config())
    assert data["hasKey"] and data["version"] == 1
    assert "secret-provider-key" not in json.dumps(data) and "apiKey" not in data
    async with service.office.transaction(admin) as conn:
        stored = (await conn.execute(select(provider_settings.c.document))).scalar_one()
    assert "secret-provider-key" not in json.dumps(stored)
    assert not (await service.catalog(other))["settings"]["imageAnalysis"]["hasKey"]
    with pytest.raises(OfficeError) as denied:
        await service.catalog(user)
    assert denied.value.status == 403
    with pytest.raises(OfficeError) as stale:
        await service.save(admin, "imageAnalysis", config())
    assert stale.value.status == 409
    change = config()
    change.update(
        provider="gemini",
        model="gemini-test",
        baseUrl="https://generativelanguage.googleapis.com/v1beta",
        apiKey=None,
        expectedVersion=1,
    )
    with pytest.raises(OfficeError, match="密钥"):
        await service.save(admin, "imageAnalysis", change)
    change.update(enabled=False)
    assert not (await service.save(admin, "imageAnalysis", change))["hasKey"]


@pytest.mark.asyncio
async def test_media_and_search_protocols_are_bounded_and_do_not_leak_errors(providers):
    from smart_reporting.office.provider_runtime import ProviderRuntime
    from smart_reporting.office.provider_http import ProviderHTTP

    service, admin, user, _ = providers
    seen = []

    def respond(request):
        seen.append(request)
        if request.url.host == "api.tavily.com":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"title": "A", "url": "https://example.com/a", "content": "Evidence"},
                        {"url": "javascript:alert(1)"},
                    ],
                    "answer": "Answer",
                },
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": "A white pixel"}}]})

    http = ProviderHTTP(transport=httpx.MockTransport(respond))
    service.runtime = ProviderRuntime(http)
    await service.save(admin, "imageAnalysis", config())
    image = image_data()
    result = await service.analyze(user, [image], "Describe")
    assert result["text"] == "A white pixel"
    assert json.loads(seen[0].content)["messages"][0]["content"][1]["type"] == "image_url"
    search = dict(
        enabled=True,
        provider="tavily",
        model="",
        baseUrl="https://api.tavily.com",
        apiKey="search-key",
        expectedVersion=0,
    )
    await service.save(admin, "webSearch", search)
    result = await service.search(user, "question", 3)
    assert result["results"] == [
        {"title": "A", "url": "https://example.com/a", "snippet": "Evidence"}
    ]
    assert result["method"] == "tavily"
    with pytest.raises(OfficeError):
        await service.analyze(user, ["file:///etc/passwd"], "Read")
    service.runtime = ProviderRuntime(
        ProviderHTTP(
            transport=httpx.MockTransport(lambda r: httpx.Response(401, text="secret-provider-key"))
        )
    )
    with pytest.raises(OfficeError) as error:
        await service.analyze(user, [image], "Describe")
    assert "secret-provider-key" not in str(error.value)


@pytest.mark.asyncio
async def test_outbound_rejects_private_dns_redirects_and_oversized_responses():
    from smart_reporting.office.provider_http import ProviderHTTP

    private = [(2, 1, 6, "", ("127.0.0.1", 443))]

    async def resolve(*args):
        return private

    with pytest.raises(OfficeError):
        await ProviderHTTP(resolver=resolve).request("GET", "https://example.com")
    for response in [
        httpx.Response(302, headers={"location": "https://127.0.0.1"}),
        httpx.Response(200, content=b"x" * 100),
    ]:
        http = ProviderHTTP(transport=httpx.MockTransport(lambda r: response))
        with pytest.raises(OfficeError):
            await http.request("GET", "https://example.com", max_bytes=10)


@pytest.mark.asyncio
async def test_admin_provider_routes_csrf_and_key_redaction(providers):
    from fastapi import FastAPI
    from smart_reporting.office.api import create_office_router, csrf_token

    service, admin, user, other = providers
    app = FastAPI()
    app.include_router(
        create_office_router(
            service.office, public_origin="http://test", source_vault=service.vault
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get("/office/api/admin/providers")).status_code == 401
        raw = await service.office.create_session(user)
        client.cookies.set("genoffice_session", raw)
        assert (await client.get("/office/api/admin/providers")).status_code == 403
        raw = await service.office.create_session(admin)
        client.cookies.set("genoffice_session", raw)
        headers = {"origin": "http://test", "x-csrf-token": csrf_token(raw)}
        url = "/office/api/admin/providers/imageAnalysis"
        assert (await client.put(url, json=config())).status_code == 403
        response = await client.put(url, json=config(), headers=headers)
        assert response.status_code == 200 and response.json()["hasKey"]
        assert "secret-provider-key" not in (await client.get("/office/api/admin/providers")).text
        assert (await client.put(url, json=config(), headers=headers)).status_code == 409
        # API validation errors must not echo the rejected API key input.
        bad = config()
        bad["apiKey"] = "private-key\n"
        response = await client.put(url, json=bad, headers=headers)
        assert response.status_code == 422 and "private-key" not in response.text


@pytest.mark.asyncio
async def test_runtime_rechecks_configuration_after_request_and_tools_reauthorize(
    providers, monkeypatch
):
    from agno.agent import Agent
    from smart_reporting.office import provider_tools
    from smart_reporting.office.provider_runtime import ProviderRuntime
    from smart_reporting.office.provider_http import ProviderHTTP
    from types import SimpleNamespace

    service, admin, user, _ = providers
    config_search = dict(
        enabled=True,
        provider="tavily",
        model="",
        baseUrl="https://api.tavily.com",
        apiKey="key",
        expectedVersion=0,
    )
    await service.save(admin, "webSearch", config_search)
    session = SimpleNamespace(
        capabilities={
            "office": {
                "database": "db",
                "company": "1",
                "user": "20",
                "version": None,
                "session": None,
            }
        }
    )
    calls = []

    class Documents:
        office = service.office

        async def authorize(self, current):
            calls.append(current)

    documents = Documents()
    documents.office.providers = service
    monkeypatch.setattr(provider_tools, "current", lambda: (session, documents.authorize))
    agent = Agent()
    await provider_tools.attach_provider_tools(agent)
    assert [tool.__name__ for tool in agent.tools] == ["web_search"]

    async def respond(request):
        changed = {**config_search, "enabled": False, "apiKey": None, "expectedVersion": 1}
        await service.save(admin, "webSearch", changed)
        return httpx.Response(200, json={"results": [{"url": "https://example.com", "title": "A"}]})

    service.runtime = ProviderRuntime(ProviderHTTP(transport=httpx.MockTransport(respond)))
    with pytest.raises(OfficeError):
        await agent.tools[0]("query")
    assert len(calls) >= 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider",
    ["serper", "serply", "searchapi", "tavily", "parallel", "exa", "firecrawl", "keenable"],
)
async def test_every_search_adapter_preserves_evidence_and_uses_the_selected_provider(provider):
    from smart_reporting.office.provider_runtime import ProviderRuntime
    from smart_reporting.office.provider_http import ProviderHTTP
    from smart_reporting.office.provider_catalog import SEARCH

    item = {
        "url": "https://example.com",
        "link": "https://example.com",
        "title": "Title",
        "snippet": "Text",
        "description": "Text",
        "content": "Text",
        "text": "Text",
        "excerpts": ["Text"],
    }
    payload = {
        "organic": [item],
        "organic_results": [item],
        "results": [item],
        "data": {"web": [item]},
    }

    def respond(request):
        assert request.url.host == httpx.URL(SEARCH[provider]["baseUrl"]).host
        assert "key" not in request.url.params
        if provider == "searchapi":
            assert request.headers["authorization"] == "Bearer secret"
        return httpx.Response(200, json=payload)

    result = await ProviderRuntime(ProviderHTTP(transport=httpx.MockTransport(respond))).search(
        {"provider": provider, "baseUrl": SEARCH[provider]["baseUrl"]}, "secret", "query", 1
    )
    assert result["method"] == provider and result["results"] == [
        {"title": "Title", "url": "https://example.com", "snippet": "Text"}
    ]


def image_data():
    from PIL import Image
    from io import BytesIO
    import base64

    output = BytesIO()
    Image.new("RGB", (2, 2), "white").save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


@pytest.mark.asyncio
async def test_gemini_video_routing_ephemeral_test_and_clear_key(providers):
    from smart_reporting.office.provider_runtime import ProviderRuntime
    from smart_reporting.office.provider_http import ProviderHTTP
    import base64

    service, admin, user, _ = providers
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "A clip"}]}}]}
        )

    service.runtime = ProviderRuntime(ProviderHTTP(transport=httpx.MockTransport(respond)))
    video = (
        "data:video/mp4;base64,"
        + base64.b64encode(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 20).decode()
    )
    draft = {
        "enabled": True,
        "provider": "gemini",
        "model": "gemini-test",
        "baseUrl": "https://generativelanguage.googleapis.com/v1beta",
        "apiKey": "gemini-key",
        "expectedVersion": 0,
    }
    assert (await service.test(admin, "videoAnalysis", draft, [video]))["ok"]
    assert (await service.catalog(admin))["settings"]["videoAnalysis"]["version"] == 0
    await service.save(admin, "videoAnalysis", draft)
    assert (await service.analyze(user, [video], "Describe"))["provider"] == "gemini"
    payload = json.loads(seen[-1].content)
    assert payload["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "video/mp4"
    assert seen[-1].headers["x-goog-api-key"] == "gemini-key"
    assert "gemini-key" not in str(seen[-1].url)
    await service.save(
        admin, "videoAnalysis", {**draft, "enabled": False, "apiKey": "", "expectedVersion": 1}
    )
    with pytest.raises(OfficeError):
        await service.analyze(user, [video], "Describe")
    assert not (await service.catalog(admin))["settings"]["videoAnalysis"]["hasKey"]


@pytest.mark.asyncio
async def test_changing_endpoint_cannot_forward_retained_secret_and_vault_required(providers):
    from smart_reporting.office.provider_settings import OfficeProviders

    service, admin, _, _ = providers
    await service.save(admin, "imageAnalysis", config())
    changed = config()
    changed.update(baseUrl="https://other.example/v1", apiKey=None, expectedVersion=1)
    with pytest.raises(OfficeError, match="密钥"):
        await service.save(admin, "imageAnalysis", changed)
    unavailable = OfficeProviders(service.office, None)
    with pytest.raises(OfficeError) as missing:
        await unavailable.save(admin, "imageAnalysis", {**config(), "expectedVersion": 1})
    assert missing.value.status == 503


@pytest.mark.asyncio
async def test_search_connection_test_does_not_report_empty_or_malformed_response_as_success(
    providers,
):
    from smart_reporting.office.provider_runtime import ProviderRuntime
    from smart_reporting.office.provider_http import ProviderHTTP

    service, admin, _, _ = providers
    service.runtime = ProviderRuntime(
        ProviderHTTP(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"message": "quota exhausted"})
            )
        )
    )
    draft = {
        "enabled": True,
        "provider": "tavily",
        "model": "",
        "baseUrl": "https://api.tavily.com",
        "apiKey": "key",
        "expectedVersion": 0,
    }
    with pytest.raises(OfficeError):
        await service.test(admin, "webSearch", draft)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider",
    ["serper", "serply", "searchapi", "tavily", "parallel", "exa", "firecrawl", "keenable"],
)
async def test_runtime_rejects_malformed_success_but_allows_valid_empty_results(provider):
    from smart_reporting.office.provider_runtime import ProviderRuntime
    from smart_reporting.office.provider_http import ProviderHTTP
    from smart_reporting.office.provider_catalog import SEARCH

    runtime = ProviderRuntime(
        ProviderHTTP(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"message": "quota exhausted"})
            )
        )
    )
    value = {"provider": provider, "baseUrl": SEARCH[provider]["baseUrl"]}
    with pytest.raises(OfficeError):
        await runtime.search(value, "secret", "query", 1)
    empty = {"organic": [], "organic_results": [], "results": [], "data": {"web": []}}
    runtime = ProviderRuntime(
        ProviderHTTP(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=empty)))
    )
    assert (await runtime.search(value, "secret", "query", 1))["results"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("excerpts", [None, "not-an-array"])
async def test_parallel_uses_pinned_source_payload_and_handles_bad_excerpts(excerpts):
    from smart_reporting.office.provider_runtime import ProviderRuntime
    from smart_reporting.office.provider_http import ProviderHTTP

    def respond(request):
        assert json.loads(request.content) == {"search_queries": ["query"], "mode": "fast"}
        assert "parallel-beta" not in request.headers
        return httpx.Response(
            200,
            json={"results": [{"url": "https://example.com", "title": "A", "excerpts": excerpts}]},
        )

    result = await ProviderRuntime(ProviderHTTP(transport=httpx.MockTransport(respond))).search(
        {"provider": "parallel", "baseUrl": "https://api.parallel.ai"}, "secret", "query", 1
    )
    assert result["results"][0]["snippet"] == ""


@pytest.mark.asyncio
async def test_serply_requests_requested_result_count():
    from smart_reporting.office.provider_runtime import ProviderRuntime
    from smart_reporting.office.provider_http import ProviderHTTP

    def respond(request):
        assert request.url.params["num"] == "20"
        return httpx.Response(200, json={"results": []})

    await ProviderRuntime(ProviderHTTP(transport=httpx.MockTransport(respond))).search(
        {"provider": "serply", "baseUrl": "https://api.serply.io"}, "secret", "query", 20
    )


@pytest.mark.asyncio
async def test_nonvideo_iso_container_is_not_misrouted_as_video():
    import base64
    from smart_reporting.office.provider_runtime import ProviderRuntime

    image = (
        "data:image/avif;base64,"
        + base64.b64encode(b"\x00\x00\x00\x18ftypavif" + b"\x00" * 20).decode()
    )
    with pytest.raises(OfficeError):
        await ProviderRuntime().load_media([image])
