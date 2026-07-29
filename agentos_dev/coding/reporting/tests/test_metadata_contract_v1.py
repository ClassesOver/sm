from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from agentos_dev.coding.reporting.contract import AgentQueryResponse, SourceSchemaSnapshot
from agentos_dev.coding.reporting.data_source.models import DataSourceConfig
from agentos_dev.coding.reporting.metadata import (
    MAX_METADATA_RESPONSE_BYTES,
    ReportingMetadataClient,
    select_reporting_agent,
)
from agentos_dev.coding.reporting.models import ReportingError

SOURCE_IDS = ("operations",)


def _source() -> DataSourceConfig:
    return cast(
        DataSourceConfig,
        SimpleNamespace(
            id="operations",
            database="reporting",
            tables=("reporting.income",),
        ),
    )


def _agent_payload(*, agent_id: int = 1) -> dict[str, Any]:
    return {"id": agent_id, "name": "运营分析", "desc": "运营模型"}


def _model_payload(*, amount_type: str = "DECIMAL(18, 2)") -> dict[str, Any]:
    return {
        "ddl": [
            {
                "id": 10,
                "modelName": "income",
                "modelDesc": "收入模型",
                "ddl": (
                    f"CREATE TABLE reporting.income (month DATE NOT NULL, amount {amount_type})"
                ),
            }
        ],
        "term": [{"id": 20, "key": "actual_income", "value": "实际收入"}],
    }


def _service(
    handler: Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]],
) -> tuple[ReportingMetadataClient, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://metadata.internal"
    )
    return (
        ReportingMetadataClient("https://metadata.internal", client_factory=lambda: client),
        client,
    )


@pytest.mark.anyio
async def test_两阶段请求使用既定路由和严格字段():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/get_agent_json":
            return httpx.Response(200, json={"agent": [_agent_payload()]})
        return httpx.Response(200, json=_model_payload())

    service, client = _service(handler)
    try:
        agents = await service.query_agents(SOURCE_IDS)
        model = await service.query_model(
            agent_id=agents.agents[0].code,
            sources=(_source(),),
        )
    finally:
        await client.aclose()

    assert [request.url.path for request in requests] == [
        "/get_agent_json",
        "/get_model_ddl_term_json",
    ]
    assert json.loads(requests[0].read()) == {}
    assert json.loads(requests[1].read()) == {"agent_id": 1}
    assert model.tables[0].name == "income"
    assert model.ddl_models[0].model_name == "income"
    assert model.terms[0].name == "actual_income"


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
        {"agent": [], "unexpected": True},
        {"agent": [_agent_payload(agent_id=index + 1) for index in range(101)]},
        {"agent": [_agent_payload() | {"desc": "x" * 2_001}]},
        {"agent": [_agent_payload(), _agent_payload()]},
    ],
)
async def test_agent响应超出结构数量或唯一性限制时拒绝(payload):
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
async def test_model_revision由规范化响应确定性计算():
    current_payload = _model_payload()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=current_payload)

    service, client = _service(handler)
    try:
        first = await service.query_model(agent_id="1", sources=(_source(),))
        second = await service.query_model(agent_id="1", sources=(_source(),))
        current_payload = _model_payload(amount_type="DECIMAL(20, 2)")
        changed = await service.query_model(agent_id="1", sources=(_source(),))
    finally:
        await client.aclose()

    assert first.revision == second.revision
    assert changed.revision != first.revision
    assert changed.schema_hash != first.schema_hash


@pytest.mark.anyio
async def test_model说明或term变化也会改变revision():
    current_payload = _model_payload()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=current_payload)

    service, client = _service(handler)
    try:
        original = await service.query_model(agent_id="1", sources=(_source(),))
        current_payload = _model_payload()
        current_payload["ddl"][0]["modelDesc"] = "另一模型说明"
        description_changed = await service.query_model(agent_id="1", sources=(_source(),))
        current_payload = _model_payload()
        current_payload["term"][0]["value"] = "另一术语定义"
        term_changed = await service.query_model(agent_id="1", sources=(_source(),))
    finally:
        await client.aclose()

    assert original.revision != description_changed.revision
    assert original.revision != term_changed.revision


@pytest.mark.anyio
async def test_原始ddl逐字保留且可从workflow快照状态恢复():
    raw_ddl = (
        "CREATE TABLE reporting.income ("
        "month DATE NULL COMMENT '月份', amount DECIMAL(18, 2) NOT NULL"
        ") COMMENT='收入表'"
    )
    payload = _model_payload()
    payload["ddl"][0]["ddl"] = raw_ddl

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    service, client = _service(handler)
    try:
        model = await service.query_model(agent_id="1", sources=(_source(),))
    finally:
        await client.aclose()

    snapshot = SourceSchemaSnapshot(
        source="metadata_api",
        revision=model.revision,
        schemaHash=model.schema_hash,
        ddlModels=model.ddl_models,
        tables=model.tables,
        terms=model.terms,
    )
    restored = SourceSchemaSnapshot.model_validate(snapshot.model_dump(mode="json", by_alias=True))
    assert restored.ddl_models[0].ddl == raw_ddl
    assert restored.tables[0].description == "收入表"
    assert restored.tables[0].columns[0].description == "月份"
    assert restored.tables[0].columns[0].nullable is True
    assert restored.tables[0].columns[1].nullable is False


@pytest.mark.anyio
async def test_真实数量形态接收六项ddl和四项term():
    table_names = (
        "dwd_income_budget_view",
        "dwd_expenditure_budget_view",
        "dwd_project_budget_view",
        "dwd_hdc_income_summary_view",
        "dwd_hdc_cost_table_view",
        "dm_hdc_gongzuoliang_view",
    )
    payload = {
        "ddl": [
            {
                "id": index,
                "modelName": name,
                "modelDesc": f"模型 {index}",
                "ddl": f"CREATE TABLE {name} (data_date DATE NULL)",
            }
            for index, name in enumerate(table_names, start=1)
        ],
        "term": [
            {"id": index, "key": f"术语 {index}", "value": f"定义 {index}"} for index in range(1, 5)
        ],
    }
    source = cast(
        DataSourceConfig,
        SimpleNamespace(
            id="rj",
            database="rj",
            tables=tuple(f"rj.{name}" for name in table_names),
        ),
    )
    service, client = _service(lambda _request: httpx.Response(200, json=payload))
    try:
        model = await service.query_model(agent_id="1", sources=(source,))
    finally:
        await client.aclose()

    assert len(model.ddl_models) == len(model.tables) == 6
    assert len(model.terms) == 4
    assert [item.kind for item in model.terms] == ["definition"] * 4


@pytest.mark.anyio
async def test_model只允许绑定到配置白名单内的唯一数据源():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_model_payload())

    service, client = _service(handler)
    disallowed = cast(
        DataSourceConfig,
        SimpleNamespace(
            id="operations",
            database="reporting",
            tables=("reporting.cost",),
        ),
    )
    try:
        with pytest.raises(ReportingError) as captured:
            await service.query_model(agent_id="1", sources=(disallowed,))
    finally:
        await client.aclose()

    assert captured.value.code == "report_schema_not_allowed"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda payload: payload["ddl"].append(dict(payload["ddl"][0])),
            "report_metadata_model_invalid",
        ),
        (
            lambda payload: payload["term"].append(dict(payload["term"][0])),
            "report_metadata_model_invalid",
        ),
        (
            lambda payload: payload["ddl"][0].update(ddl="SELECT 1"),
            "report_ddl_invalid",
        ),
        (
            lambda payload: payload["ddl"][0].update(ddl="CREATE TABLE broken ("),
            "report_ddl_invalid",
        ),
    ],
)
async def test_model重复或非法ddl整体拒绝(mutation, expected_code):
    payload = _model_payload()
    mutation(payload)
    service, client = _service(lambda _request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ReportingError) as captured:
            await service.query_model(agent_id="1", sources=(_source(),))
    finally:
        await client.aclose()
    assert captured.value.code == expected_code


@pytest.mark.anyio
@pytest.mark.parametrize("agent_id", ("", "0", "-1", "1.0", "agent"))
async def test_model请求只接受正整数agent_code(agent_id: str):
    service, client = _service(lambda _request: httpx.Response(500))
    try:
        with pytest.raises(ReportingError) as captured:
            await service.query_model(agent_id=agent_id, sources=(_source(),))
    finally:
        await client.aclose()
    assert captured.value.code == "report_agent_invalid"


@pytest.mark.anyio
async def test_未限定同名表匹配多个数据源时拒绝():
    payload = _model_payload()
    payload["ddl"][0]["ddl"] = "CREATE TABLE income (month DATE NOT NULL)"
    duplicate = cast(
        DataSourceConfig,
        SimpleNamespace(id="other", database="other", tables=("other.income",)),
    )
    service, client = _service(lambda _request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ReportingError) as captured:
            await service.query_model(agent_id="1", sources=(_source(), duplicate))
    finally:
        await client.aclose()
    assert captured.value.code == "report_schema_source_ambiguous"


@pytest.mark.anyio
async def test_单项ddl按utf8字节限制为一mib():
    payload = _model_payload()
    payload["ddl"][0]["ddl"] = "表" * 400_000
    service, client = _service(lambda _request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ReportingError) as captured:
            await service.query_model(agent_id="1", sources=(_source(),))
    finally:
        await client.aclose()
    assert captured.value.code == "report_metadata_model_invalid"


def test_显式agent选择只接受已启用且存在的数字code():
    response = AgentQueryResponse.model_validate(
        {
            "agents": [
                {"code": "1", "name": "启用", "description": "", "enabled": True},
                {"code": "2", "name": "停用", "description": "", "enabled": False},
            ]
        }
    )

    assert select_reporting_agent(response, "1").code == "1"  # type: ignore[union-attr]
    for requested in ("2", "3", "invalid"):
        with pytest.raises(ReportingError) as captured:
            select_reporting_agent(response, requested)
        assert captured.value.code == "report_agent_invalid"
