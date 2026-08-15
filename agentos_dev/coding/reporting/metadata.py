from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel
from sqlglot import exp, parse

from .contract import (
    MetadataAgentResponse,
    MetadataModelResponse,
    ModelTable,
    ModelTerm,
    ModelTermsResponse,
    ReportingAgent,
    SourceRef,
    parse_ddl,
    schema_hash,
)
from .data_source.models import DataSourceConfig
from .models import ReportingError

MAX_METADATA_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_METADATA_ATTEMPTS = 3
METADATA_RETRY_STATUS_CODES = frozenset({502, 503, 504})
METADATA_RETRY_DELAYS = (0.2, 0.5)


class ReportingMetadataClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout_seconds: float = 10.0,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory

    async def query_agent(self) -> ReportingAgent:
        payload = await self._post("/get_agent_json", {})
        response = self._validate(MetadataAgentResponse, payload, "report_metadata_agents_invalid")
        if len(response.agent_list) != 1:
            raise ReportingError(
                "report_metadata_agents_invalid", "Reporting metadata 必须唯一配置一个 Agent。"
            )
        item = response.agent_list[0]
        return ReportingAgent(
            code=str(item.id),
            name=item.name,
            description=item.desc,
        )

    async def query_model(
        self,
        *,
        agent_id: str,
        sources: tuple[DataSourceConfig, ...],
    ) -> ModelTermsResponse:
        if not re.fullmatch(r"[1-9][0-9]*", agent_id):
            raise ReportingError("report_agent_invalid", "报表 Agent code 必须是正整数。")
        payload = await self._post("/get_model_ddl_term_json", {"agent_id": int(agent_id)})
        response = self._validate(MetadataModelResponse, payload, "report_metadata_model_invalid")
        try:
            return _adapt_model_response(response, sources)
        except ReportingError:
            raise
        except Exception as error:
            raise ReportingError(
                "report_metadata_model_invalid", "报表元数据响应不符合 DDL/term 契约。"
            ) from error

    async def _post(self, path: str, request: BaseModel | dict[str, Any]) -> Any:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        owns_client = self.client_factory is None
        client = (
            httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds)
            if owns_client
            else self._provided_client()
        )
        body = (
            request.model_dump(mode="json", by_alias=True)
            if isinstance(request, BaseModel)
            else request
        )
        try:
            for attempt in range(1, MAX_METADATA_ATTEMPTS + 1):
                try:
                    response = await client.post(path, headers=headers, json=body)
                except httpx.TimeoutException as error:
                    if attempt < MAX_METADATA_ATTEMPTS:
                        await asyncio.sleep(METADATA_RETRY_DELAYS[attempt - 1])
                        continue
                    raise ReportingError(
                        "report_metadata_timeout", "报表元数据服务请求超时。"
                    ) from error
                except httpx.NetworkError as error:
                    if attempt < MAX_METADATA_ATTEMPTS:
                        await asyncio.sleep(METADATA_RETRY_DELAYS[attempt - 1])
                        continue
                    raise ReportingError(
                        "report_metadata_unavailable", "报表元数据服务不可用。"
                    ) from error
                except httpx.HTTPError as error:
                    raise ReportingError(
                        "report_metadata_unavailable", "报表元数据服务不可用。"
                    ) from error

                if response.status_code in METADATA_RETRY_STATUS_CODES:
                    if attempt < MAX_METADATA_ATTEMPTS:
                        await asyncio.sleep(METADATA_RETRY_DELAYS[attempt - 1])
                        continue
                    raise ReportingError("report_metadata_unavailable", "报表元数据服务不可用。")
                if response.status_code in {401, 403}:
                    raise ReportingError("report_metadata_auth_failed", "报表元数据服务鉴权失败。")
                if response.status_code >= 500:
                    raise ReportingError("report_metadata_unavailable", "报表元数据服务不可用。")
                if response.status_code < 200 or response.status_code >= 300:
                    raise ReportingError("report_metadata_rejected", "报表元数据服务拒绝了请求。")
                if len(response.content) > MAX_METADATA_RESPONSE_BYTES:
                    raise ReportingError("report_metadata_response_too_large", "报表元数据响应过大。")
                try:
                    return response.json()
                except ValueError as error:
                    raise ReportingError(
                        "report_metadata_invalid_json", "报表元数据响应不是合法 JSON。"
                    ) from error
            raise ReportingError("report_metadata_unavailable", "报表元数据服务不可用。")
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _validate(model: type[Any], payload: Any, code: str) -> Any:
        try:
            return model.model_validate(payload)
        except Exception as error:
            raise ReportingError(code, "报表元数据响应不符合接口契约。") from error

    def _provided_client(self) -> httpx.AsyncClient:
        assert self.client_factory is not None
        return self.client_factory()


def _adapt_model_response(
    response: MetadataModelResponse,
    sources: tuple[DataSourceConfig, ...],
) -> ModelTermsResponse:
    ddl_ids = [item.id for item in response.ddl]
    term_ids = [item.id for item in response.term]
    term_keys = [item.key for item in response.term]
    if (
        len(ddl_ids) != len(set(ddl_ids))
        or len(term_ids) != len(set(term_ids))
        or len(term_keys) != len(set(term_keys))
    ):
        raise ReportingError("report_metadata_model_invalid", "DDL id 或术语 id/key 重复。")

    tables: list[ModelTable] = []
    seen_tables: set[tuple[str, str, str]] = set()
    for raw in response.ddl:
        source = _bind_ddl_source(raw.ddl, sources)
        parsed = parse_ddl(raw.ddl, source_id=source.id, default_database=source.database)
        if len(parsed) != 1:
            raise ReportingError("report_metadata_model_invalid", "每个 DDL 模型必须只包含一张表。")
        table = parsed[0]
        key = (table.source_id.lower(), table.database.lower(), table.name.lower())
        if key in seen_tables:
            raise ReportingError("report_metadata_model_invalid", "DDL 包含重复数据表。")
        seen_tables.add(key)
        tables.append(table)

    terms = tuple(
        ModelTerm(
            code=str(item.id),
            name=item.key,
            description=item.value,
            kind="definition",
        )
        for item in response.term
    )
    revision_payload = {
        "ddl": [item.model_dump(mode="json", by_alias=True) for item in response.ddl],
        "term": [item.model_dump(mode="json", by_alias=True) for item in response.term],
        "measureSemantics": [
            item.model_dump(mode="json", by_alias=True) for item in response.measure_semantics
        ],
    }
    revision = hashlib.sha256(
        json.dumps(
            revision_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    source_ids = {table.source_id for table in tables}
    return ModelTermsResponse(
        revision=revision,
        schemaHash=schema_hash(tables),
        sourceRefs=tuple(
            SourceRef(sourceId=source.id) for source in sources if source.id in source_ids
        ),
        ddlModels=response.ddl,
        tables=tuple(tables),
        terms=terms,
        measureSemantics=response.measure_semantics,
    )


def _bind_ddl_source(ddl: str, sources: tuple[DataSourceConfig, ...]) -> DataSourceConfig:
    try:
        statements = parse(ddl, read="mysql")
    except Exception as error:
        raise ReportingError("report_ddl_invalid", "DDL 语法无效。") from error
    if len(statements) != 1 or not isinstance(statements[0], exp.Create):
        raise ReportingError("report_ddl_invalid", "每个模型只接受一条 CREATE TABLE DDL。")
    schema = statements[0].this
    if not isinstance(schema, exp.Schema) or not isinstance(schema.this, exp.Table):
        raise ReportingError("report_ddl_invalid", "DDL 必须包含明确的表和字段。")
    table = schema.this
    if table.catalog:
        raise ReportingError("report_schema_not_allowed", "DDL 不允许使用 catalog 限定名。")
    database = str(table.db or "").lower()
    matches = []
    for source in sources:
        if not database or database == source.database.lower():
            matches.append(source)
    if len(matches) != 1:
        code = "report_schema_source_ambiguous" if len(matches) > 1 else "report_schema_not_allowed"
        raise ReportingError(code, "DDL 数据表无法唯一绑定到已配置数据源数据库。")
    return matches[0]

