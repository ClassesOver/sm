from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from .contract import (
    AgentQueryRequest,
    AgentQueryResponse,
    ModelTermsRequest,
    ModelTermsResponse,
    ReportingAgent,
)
from .models import ReportingError

MAX_METADATA_RESPONSE_BYTES = 4 * 1024 * 1024


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

    async def query_agents(self, source_ids: tuple[str, ...]) -> AgentQueryResponse:
        request = AgentQueryRequest(sourceIds=source_ids)
        payload = await self._post("/api/reporting/v1/agents/query", request)
        return self._validate(AgentQueryResponse, payload, "report_metadata_agents_invalid")

    async def query_model(
        self,
        *,
        agent_id: str,
        source_ids: tuple[str, ...],
        expected_revision: str,
    ) -> ModelTermsResponse:
        request = ModelTermsRequest(agentId=agent_id, sourceIds=source_ids)
        for attempt in range(2):
            payload = await self._post("/api/reporting/v1/model-terms/query", request)
            response = self._validate(ModelTermsResponse, payload, "report_metadata_model_invalid")
            if response.revision == expected_revision:
                return response
            if attempt == 0:
                agents = await self.query_agents(source_ids)
                selected = next(
                    (item for item in agents.agents if item.enabled and item.code == agent_id), None
                )
                if selected is None:
                    break
                expected_revision = selected.model_revision
                continue
        raise ReportingError(
            "report_metadata_revision_changed", "报表元数据 revision 在获取期间发生变化。"
        )

    async def _post(self, path: str, request: Any) -> Any:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        owns_client = self.client_factory is None
        client = (
            httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds)
            if owns_client
            else self._provided_client()
        )
        try:
            response = await client.post(
                path,
                headers=headers,
                json=request.model_dump(mode="json", by_alias=True),
            )
        except httpx.TimeoutException as error:
            raise ReportingError("report_metadata_timeout", "报表元数据服务请求超时。") from error
        except httpx.HTTPError as error:
            raise ReportingError("report_metadata_unavailable", "报表元数据服务不可用。") from error
        finally:
            if owns_client:
                await client.aclose()
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

    @staticmethod
    def _validate(model: type[Any], payload: Any, code: str) -> Any:
        try:
            return model.model_validate(payload)
        except Exception as error:
            raise ReportingError(code, "报表元数据响应不符合 v1 契约。") from error

    def _provided_client(self) -> httpx.AsyncClient:
        assert self.client_factory is not None
        return self.client_factory()


def select_reporting_agent(
    response: AgentQueryResponse,
    requested_agent_id: str | None,
) -> ReportingAgent | tuple[ReportingAgent, ...] | None:
    enabled = tuple(item for item in response.agents if item.enabled)
    if requested_agent_id is not None:
        selected = next((item for item in enabled if item.code == requested_agent_id), None)
        if selected is None:
            raise ReportingError("report_agent_invalid", "所选报表 Agent 不存在或未启用。")
        return selected
    if len(enabled) == 1:
        return enabled[0]
    if len(enabled) > 1:
        return enabled
    return None
