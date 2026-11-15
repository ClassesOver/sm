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


@pytest.mark.asyncio
async def test_admin_chat_model_uses_native_agno_and_isolated_credentials(providers):
    from agno.agent import Agent
    from agno.models.openai import OpenAIChat
    from smart_reporting.reporting.agent_events import run_owned_agent_with_events
    from smart_reporting.office.settings import OfficeSettings
    from smart_reporting.office.provider_http import ProviderHTTP

    service, admin, user, other = providers
    service.office.providers = service
    original = OpenAIChat(id="deployment-default", api_key="deployment-key")
    assert (await OfficeSettings(service.office).model(user, original)).id == "deployment-default"
    await service.save(admin, "chatModel", config())
    seen = []

    def respond(request):
        seen.append(request)
        assert request.headers["authorization"] == "Bearer secret-provider-key"
        assert json.loads(request.content)["model"] == "vision-model"
        return httpx.Response(
            200,
            json={
                "id": "chat-1",
                "object": "chat.completion",
                "created": 1,
                "model": "vision-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ready"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    service.runtime.http = ProviderHTTP(transport=httpx.MockTransport(respond))
    model = await OfficeSettings(service.office).model(user, original)
    assert isinstance(model, OpenAIChat) and original.id == "deployment-default"
    result = await run_owned_agent_with_events(Agent(model=model), "hello")
    assert result.content == "ready" and model.async_client.is_closed()
    assert (await OfficeSettings(service.office).model(other, original)).id == "deployment-default"
    await service.save(
        admin, "chatModel", {**config(), "enabled": False, "apiKey": None, "expectedVersion": 1}
    )
    with pytest.raises(OfficeError):
        await OfficeSettings(service.office).model(user, original)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "gemini", "qwen", "doubao", "glm", "xai", "custom"])
async def test_generation_protocols_validate_images_and_never_forward_keys_to_assets(
    providers, provider
):
    import base64
    from smart_reporting.office.provider_http import ProviderHTTP
    from smart_reporting.office.provider_catalog import catalog_for

    service, admin, user, _ = providers
    meta = next(item for item in catalog_for("imageGeneration") if item["id"] == provider)
    body = {
        "enabled": True,
        "provider": provider,
        "model": meta["model"] or "image-model",
        "baseUrl": meta["baseUrl"] or "https://example.com/v1",
        "apiKey": "image-private-key",
        "expectedVersion": 0,
    }
    encoded = image_data().split(",", 1)[1]
    seen = []

    def respond(request):
        seen.append(request)
        if request.url.host == "assets.example.com":
            assert (
                "authorization" not in request.headers and "x-goog-api-key" not in request.headers
            )
            return httpx.Response(
                200, content=base64.b64decode(encoded), headers={"content-type": "image/png"}
            )
        payload = json.loads(request.content)
        if provider == "gemini":
            assert payload["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {"inlineData": {"mimeType": "image/png", "data": encoded}}
                                ]
                            }
                        }
                    ]
                },
            )
        if provider == "qwen":
            assert payload["input"]["messages"][0]["content"][0]["text"] == "white square"
            return httpx.Response(
                200,
                json={
                    "output": {
                        "choices": [
                            {
                                "message": {
                                    "content": [{"image": "https://assets.example.com/image.png"}]
                                }
                            }
                        ]
                    }
                },
            )
        assert payload["n"] == 1 and payload["prompt"] == "white square"
        if provider == "xai":
            assert "size" not in payload
        return httpx.Response(200, json={"data": [{"url": "https://assets.example.com/image.png"}]})

    service.runtime.http = ProviderHTTP(transport=httpx.MockTransport(respond))
    await service.save(admin, "imageGeneration", body)
    content, mime, extension = await service.generate(user, "white square")
    assert content == base64.b64decode(encoded) and mime == "image/png" and extension == "png"
    await service.save(
        admin, "imageGeneration", {**body, "enabled": False, "apiKey": None, "expectedVersion": 1}
    )
    with pytest.raises(OfficeError):
        await service.generate(user, "white square")


@pytest.mark.asyncio
async def test_generated_nonimage_or_oversized_data_is_rejected(providers):
    from smart_reporting.office.provider_http import ProviderHTTP

    service, admin, user, _ = providers
    await service.save(admin, "imageGeneration", config())
    service.runtime.http = ProviderHTTP(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"data": [{"b64_json": "bm90IGFuIGltYWdl"}]})
        )
    )
    with pytest.raises(OfficeError):
        await service.generate(user, "white square")


@pytest.mark.asyncio
async def test_user_image_generation_api_is_authenticated_and_csrf_protected(providers):
    from fastapi import FastAPI
    from smart_reporting.office.api import create_office_router, csrf_token
    from smart_reporting.office.provider_http import ProviderHTTP

    service, admin, user, _ = providers
    await service.save(admin, "imageGeneration", config())
    app = FastAPI()
    app.include_router(
        create_office_router(
            service.office, public_origin="http://test", source_vault=service.vault
        )
    )
    encoded = image_data().split(",", 1)[1]
    service.office.providers.runtime.http = ProviderHTTP(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"data": [{"b64_json": encoded}]})
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        url = "/office/api/media/images"
        assert (await client.post(url, json={"prompt": "white square"})).status_code == 401
        token = await service.office.create_session(user)
        client.cookies.set("genoffice_session", token)
        assert (await client.post(url, json={"prompt": "white square"})).status_code == 403
        response = await client.post(
            url,
            json={"prompt": "white square"},
            headers={"origin": "http://test", "x-csrf-token": csrf_token(token)},
        )
        assert response.status_code == 200 and response.json()["previewDataUrl"] == image_data()
        assert "secret-provider-key" not in response.text


@pytest.mark.asyncio
async def test_model_transport_pins_scope_redacts_errors_and_rechecks_revocation():
    from smart_reporting.office.provider_models import OfficeModelTransport

    calls = []
    active = True

    async def guard():
        if not active:
            raise OfficeError("revoked", "配置已撤销。")

    def respond(request):
        calls.append(request)
        return httpx.Response(401, text="private-provider-key response body")

    transport = OfficeModelTransport(
        "https://api.openai.com/v1", guard, transport=httpx.MockTransport(respond)
    )
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        response = await client.post("https://api.openai.com/v1/chat/completions")
        assert response.status_code == 401 and "private-provider-key" not in response.text
        with pytest.raises(OfficeError):
            await client.post("https://other.example.com/v1/chat/completions")
        active = False
        with pytest.raises(OfficeError):
            await client.post("https://api.openai.com/v1/chat/completions")
    assert len(calls) == 1

    async def allow():
        pass

    async def private(*args):
        return [(2, 1, 6, "", ("127.0.0.1", 443))]

    async with httpx.AsyncClient(
        transport=OfficeModelTransport("https://private.example", allow, resolver=private)
    ) as client:
        with pytest.raises(Exception):
            await client.post("https://private.example/chat/completions")


@pytest.mark.asyncio
async def test_agno_streaming_model_policy_and_response_limits():
    from smart_reporting.office.provider_models import OfficeModelTransport

    events = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"text":"hello"}\n\n'
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            events.append("close")

    async def guard():
        events.append("guard")

    transport = OfficeModelTransport(
        "https://api.example.com",
        guard,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, stream=Stream(), headers={"content-type": "text/event-stream"}
            )
        ),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        async with client.stream("POST", "https://api.example.com/chat/completions") as response:
            chunks = [chunk async for chunk in response.aiter_bytes()]
    assert b"hello" in b"".join(chunks) and events.count("guard") == 3 and "close" in events

    class Huge(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * (16 * 1024 * 1024 + 1)

    transport = OfficeModelTransport(
        "https://api.example.com",
        guard,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Huge())),
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(OfficeError):
            await client.post("https://api.example.com/chat/completions")


@pytest.mark.asyncio
async def test_source_openai_models_use_native_responses_and_test_drafts_do_not_save(providers):
    from agno.models.openai.responses import OpenAIResponses
    from smart_reporting.office.provider_models import native_chat_model
    from smart_reporting.office.provider_http import ProviderHTTP

    service, admin, _, _ = providers

    async def guard():
        pass

    model = native_chat_model(
        {"provider": "openai", "model": "gpt-6.1-terra", "baseUrl": "https://api.openai.com/v1"},
        "secret",
        guard,
    )
    assert isinstance(model, OpenAIResponses)
    await model.http_client.aclose()

    def respond(request):
        return httpx.Response(
            200,
            json={
                "id": "chat-1",
                "object": "chat.completion",
                "created": 1,
                "model": "test",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    service.runtime.http = ProviderHTTP(transport=httpx.MockTransport(respond))
    assert (await service.test(admin, "chatModel", config()))["ok"]
    assert (await service.catalog(admin))["settings"]["chatModel"]["version"] == 0


@pytest.mark.asyncio
async def test_actual_openai_sdk_done_marker_rechecks_policy_and_closes_stream():
    from openai import AsyncOpenAI
    from smart_reporting.office.provider_models import OfficeModelTransport

    events = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"x","choices":[{"index":0,"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
            events.append("revoked")
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            events.append("close")

    async def guard():
        events.append("guard")
        if "revoked" in events:
            raise OfficeError("revoked", "revoked")

    transport = OfficeModelTransport(
        "https://model.example/v1",
        guard,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, stream=Stream(), headers={"content-type": "text/event-stream"}
            )
        ),
    )
    async with AsyncOpenAI(
        api_key="secret",
        base_url="https://model.example/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=transport),
    ) as client:
        with pytest.raises(OfficeError, match="revoked"):
            stream = await client.chat.completions.create(
                model="x", messages=[{"role": "user", "content": "hello"}], stream=True
            )
            async for _ in stream:
                pass
    assert "close" in events


@pytest.mark.asyncio
async def test_image_generation_matches_native_size_and_source_deadline(providers):
    import base64
    from smart_reporting.office.provider_images import validate_image
    from smart_reporting.office.provider_http import ProviderHTTP

    service, admin, user, _ = providers
    content = base64.b64decode(image_data().split(",", 1)[1]) + b"x" * (6 * 1024 * 1024)
    with pytest.raises(OfficeError) as oversized:
        validate_image(content)
    assert oversized.value.code == "office_image_size_invalid"
    await service.save(admin, "imageGeneration", config())

    def respond(request):
        assert request.extensions["timeout"]["read"] == 600
        return httpx.Response(200, json={"data": [{"b64_json": image_data().split(",", 1)[1]}]})

    service.runtime.http = ProviderHTTP(transport=httpx.MockTransport(respond))
    await service.generate(user, "white square")


@pytest.mark.asyncio
@pytest.mark.parametrize("feature", ["knowledge", "search"])
@pytest.mark.parametrize("mode", ["configured", "unconfigured", "provider_disabled", "deployment_disabled"])
async def test_company_model_runs_without_deployment_fallback(providers, monkeypatch, feature, mode):
    from types import SimpleNamespace
    from smart_reporting.office.knowledge import OfficeKnowledge
    from smart_reporting.office.search import OfficeSearch
    from smart_reporting.reporting import agent_events

    service, actor, _, _ = providers
    office = service.office
    office.providers = service
    if mode != "unconfigured":
        data = config()
        data["enabled"] = mode != "provider_disabled"
        await service.save(actor, "chatModel", data)
    space = (await office.spaces(actor))[0]["id"]
    files = []
    for name in ("one", "two"):
        entry = await office.register_file(actor, space, None, name + ".docx", "docx", name, 1,
            {"database": actor.database, "companyId": actor.company})
        await office.favorite(actor, entry["id"], True)
        await office.record_search_text(actor, space, entry["id"], 1, "quarter renewal")
        files.append(entry)

    class Documents:
        async def contents(self, identity, file_id):
            return await office.file(identity, file_id), b"quarter renewal"

    used = []
    async def run(agent, prompt, **kwargs):
        used.append(agent.model)
        assert agent.model.id == "vision-model"
        agent.model.get_async_client()  # Exercise the same owned SDK lifecycle as a real run.
        if feature == "search":
            return SimpleNamespace(content={"order": [2, 1]})
        reader = next(tool for tool in agent.tools if tool.__name__ == "read_knowledge_file")
        evidence = await reader(files[0]["id"])
        return SimpleNamespace(content={"answer": "quarter renewal", "citations": [evidence["citationId"]]})

    monkeypatch.setattr(agent_events, "run_agent_with_events", run)
    kwargs = {"enabled": False} if mode == "deployment_disabled" else {}
    if feature == "knowledge":
        knowledge = OfficeKnowledge(office, Documents(), parser=lambda content, fmt: {
            "text": content.decode(), "limitations": []}, **kwargs)
        if mode == "configured":
            answer = await knowledge.ask(actor, space, "renewal?")
            assert answer["answer"] == "quarter renewal"
            assert answer["citations"][0]["fileId"] == files[0]["id"]
        else:
            with pytest.raises(OfficeError) as error:
                await knowledge.ask(actor, space, "renewal?")
            assert error.value.code == ("office_provider_disabled" if mode == "provider_disabled"
                                        else "office_knowledge_unavailable")
    else:
        search = OfficeSearch(office, Documents(), **kwargs)
        order = await search.rerank(actor, space, "renewal", {f["id"]: 1 for f in files})
        assert order == ([f["id"] for f in reversed(files)] if mode == "configured" else [])
    assert len(used) == (1 if mode == "configured" else 0)
    if used:
        assert used[0].http_client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['configured', 'disabled', 'unconfigured'])
async def test_native_pptx_filename_obeys_company_model_selection(providers, monkeypatch, mode):
    from types import SimpleNamespace
    from agno.models.openai import OpenAIChat
    from smart_reporting.office import settings as settings_module
    from smart_reporting.report_editor.native_slides_read_ai import AgnoNativeSlidesReadPlanner
    from smart_reporting.reporting import agent_events

    service, actor, _, _ = providers
    service.office.providers = service
    if mode != 'unconfigured':
        data = config()
        data['enabled'] = mode != 'disabled'
        await service.save(actor, 'chatModel', data)
    async def context():
        return settings_module.OfficeSettings(service.office), actor
    monkeypatch.setattr(settings_module, 'native_settings', context)
    calls = []
    async def run(agent, prompt, **kwargs):
        calls.append(agent.model)
        assert agent.model.id == ('vision-model' if mode == 'configured' else 'deployment-model')
        assert agent.tools == []
        assert prompt == 'Quarterly revenue'
        assert any('Simplified Chinese' in instruction for instruction in agent.instructions)
        agent.model.get_async_client()
        return SimpleNamespace(content='季度收入\nignored second line')
    monkeypatch.setattr(agent_events, 'run_agent_with_events', run)
    planner = AgnoNativeSlidesReadPlanner(OpenAIChat(id='deployment-model', api_key='test'))
    if mode == 'disabled':
        with pytest.raises(OfficeError) as error:
            await planner.suggest_filename('Quarterly revenue', name_locale='zh-CN', session_id='name', user_id=actor.user)
        assert error.value.code == 'office_provider_disabled'
        assert calls == []
    else:
        assert await planner.suggest_filename('Quarterly revenue', name_locale='zh-CN', session_id='name', user_id=actor.user) == {'answer': '季度收入'}
        assert calls[0] is not planner.model and calls[0].async_client.is_closed()
