from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from agentos_dev.coding.reporting.contract import (
    AgentQueryResponse,
    ModelColumn,
    ModelTable,
    schema_hash,
)
from agentos_dev.coding.reporting.metadata import (
    MAX_METADATA_RESPONSE_BYTES,
    ReportingMetadataClient,
    select_reporting_agent,
)
from agentos_dev.coding.reporting.models import ReportingError

SOURCE_IDS = ("operations",)


def _agent_payload(*, revision: str = "model-r1", code: str = "operations-agent") -> dict[str, Any]:
    return {
        "code": code,
        "name": "运营分析",
        "description": "运营模型",
        "enabled": True,
        "modelRevision": revision,
    }


def _model_payload(*, revision: str = "model-r1") -> dict[str, Any]:
    tables = (
        ModelTable(
            sourceId="operations",
            database="reporting",
            name="income",
            columns=(ModelColumn(name="month", dataType="DATE", nullable=False),),
        ),
    )
    return {
        "revision": revision,
        "schemaHash": schema_hash(tables),
        "sourceRefs": [{"sourceId": "operations"}],
        "tables": [table.model_dump(mode="json", by_alias=True) for table in tables],
        "terms": [],
    }


def _service(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[ReportingMetadataClient, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://metadata.internal"
    )
    return (
        ReportingMetadataClient("https://metadata.internal", client_factory=lambda: client),
        client,
    )


@pytest.mark.anyio
async def test_两阶段请求都发送契约版本和严格字段():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/agents/query"):
            return httpx.Response(200, json={"revision": "agents-r1", "agents": [_agent_payload()]})
        return httpx.Response(200, json=_model_payload())

    service, client = _service(handler)
    try:
        agents = await service.query_agents(SOURCE_IDS)
        await service.query_model(
            agent_id=agents.agents[0].code,
            source_ids=SOURCE_IDS,
            expected_revision=agents.agents[0].model_revision,
        )
    finally:
        await client.aclose()

    assert [request.url.path for request in requests] == [
        "/api/reporting/v1/agents/query",
        "/api/reporting/v1/model-terms/query",
    ]
    assert requests[0].read().decode() == '{"contractVersion":"1","sourceIds":["operations"]}'
    assert requests[1].read().decode() == (
        '{"contractVersion":"1","agentId":"operations-agent","sourceIds":["operations"]}'
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("response_factory", "expected_code"),
    [
        (lambda request: httpx.Response(401, request=request), "report_metadata_auth_failed"),
        (lambda request: httpx.Response(403, request=request), "report_metadata_auth_failed"),
        (lambda request: httpx.Response(503, request=request), "report_metadata_unavailable"),
        (
            lambda request: httpx.Response(200, content=b"not-json", request=request),
            "report_metadata_invalid_json",
        ),
        (
            lambda request: httpx.Response(
                200,
                content=b" " * (MAX_METADATA_RESPONSE_BYTES + 1),
                request=request,
            ),
            "report_metadata_response_too_large",
        ),
    ],
)
async def test_metadata失败返回稳定错误且不降级为零agent(response_factory, expected_code):
    async def handler(request: httpx.Request) -> httpx.Response:
        return response_factory(request)

    service, client = _service(handler)
    try:
        with pytest.raises(ReportingError) as captured:
            await service.query_agents(SOURCE_IDS)
    finally:
        await client.aclose()

    assert captured.value.code == expected_code


@pytest.mark.anyio
async def test_metadata超时返回稳定错误():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    service, client = _service(handler)
    try:
        with pytest.raises(ReportingError) as captured:
            await service.query_agents(SOURCE_IDS)
    finally:
        await client.aclose()

    assert captured.value.code == "report_metadata_timeout"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {"revision": "agents-r1", "agents": [], "unexpected": True},
        {
            "revision": "agents-r1",
            "agents": [_agent_payload(code=f"agent-{index}") for index in range(101)],
        },
        {
            "revision": "agents-r1",
            "agents": [_agent_payload() | {"description": "x" * 2_001}],
        },
    ],
)
async def test_agent响应超出结构或数量限制时拒绝(payload):
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    service, client = _service(handler)
    try:
        with pytest.raises(ReportingError) as captured:
            await service.query_agents(SOURCE_IDS)
    finally:
        await client.aclose()

    assert captured.value.code == "report_metadata_agents_invalid"


@pytest.mark.anyio
async def test_revision漂移后完整重取且刷新结果一致才成功():
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/agents/query"):
            return httpx.Response(
                200,
                json={"revision": "agents-r2", "agents": [_agent_payload(revision="model-r2")]},
            )
        revision = "model-r1-stale" if paths.count(request.url.path) == 1 else "model-r2"
        return httpx.Response(200, json=_model_payload(revision=revision))

    service, client = _service(handler)
    try:
        response = await service.query_model(
            agent_id="operations-agent",
            source_ids=SOURCE_IDS,
            expected_revision="model-r1",
        )
    finally:
        await client.aclose()

    assert response.revision == "model-r2"
    assert paths == [
        "/api/reporting/v1/model-terms/query",
        "/api/reporting/v1/agents/query",
        "/api/reporting/v1/model-terms/query",
    ]


@pytest.mark.anyio
async def test_revision完整重取后仍不一致则返回稳定错误():
    model_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal model_calls
        if request.url.path.endswith("/agents/query"):
            return httpx.Response(
                200,
                json={"revision": "agents-r2", "agents": [_agent_payload(revision="model-r2")]},
            )
        model_calls += 1
        return httpx.Response(200, json=_model_payload(revision=f"model-stale-{model_calls}"))

    service, client = _service(handler)
    try:
        with pytest.raises(ReportingError) as captured:
            await service.query_model(
                agent_id="operations-agent",
                source_ids=SOURCE_IDS,
                expected_revision="model-r1",
            )
    finally:
        await client.aclose()

    assert captured.value.code == "report_metadata_revision_changed"
    assert model_calls == 2


@pytest.mark.anyio
async def test_revision漂移后agent消失则失败关闭且不再请求模型():
    model_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal model_calls
        if request.url.path.endswith("/agents/query"):
            return httpx.Response(200, json={"revision": "agents-r2", "agents": []})
        model_calls += 1
        return httpx.Response(200, json=_model_payload(revision="model-stale"))

    service, client = _service(handler)
    try:
        with pytest.raises(ReportingError) as captured:
            await service.query_model(
                agent_id="operations-agent",
                source_ids=SOURCE_IDS,
                expected_revision="model-r1",
            )
    finally:
        await client.aclose()

    assert captured.value.code == "report_metadata_revision_changed"
    assert model_calls == 1


def test_显式agent选择只接受已启用且存在的code():
    response = AgentQueryResponse.model_validate(
        {
            "revision": "agents-r1",
            "agents": [
                _agent_payload(code="enabled"),
                _agent_payload(code="disabled") | {"enabled": False},
            ],
        }
    )

    assert select_reporting_agent(response, "enabled").code == "enabled"  # type: ignore[union-attr]
    for requested in ("disabled", "missing"):
        with pytest.raises(ReportingError) as captured:
            select_reporting_agent(response, requested)
        assert captured.value.code == "report_agent_invalid"
