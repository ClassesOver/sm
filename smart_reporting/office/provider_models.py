"""Native Agno models over the existing public-address-pinned HTTPS transport."""

import asyncio
import re
from urllib.parse import urlsplit

import httpx
from agno.models.openai import OpenAIChat
from agno.models.openai.responses import OpenAIResponses

from .pinned_http import PinnedAsyncHTTPTransport, public_addresses, resolve, validate_https_url
from .repository import OfficeError


class _BoundStream(httpx.AsyncByteStream):
    def __init__(self, response, transport, guard):
        self.response, self.transport, self.guard = response, transport, guard
        self.checked = self.closed = False

    async def __aiter__(self):
        size = 0
        try:
            async with asyncio.timeout(120):
                async for chunk in self.response.aiter_bytes():
                    size += len(chunk)
                    if size > 16 * 1024 * 1024:
                        raise OfficeError(
                            "office_model_response_too_large", "模型响应超过大小限制。", 502
                        )
                    yield chunk
                await self.check_completion()
        finally:
            await self.aclose()

    async def check_completion(self):
        if not self.checked:
            self.checked = True
            await self.guard()

    async def aclose(self):
        if self.closed:
            return
        self.closed = True
        try:
            # OpenAI's SSE iterator stops at [DONE] without draining EOF.
            await self.check_completion()
        finally:
            try:
                await self.response.aclose()
            finally:
                await self.transport.aclose()


class OfficeModelTransport(httpx.AsyncBaseTransport):
    def __init__(self, base_url, guard, *, transport=None, resolver=None):
        self.origin = urlsplit(base_url).hostname
        self.guard, self.transport = guard, transport
        self.resolver = resolver or resolve

    async def handle_async_request(self, request):
        await self.guard()
        parsed = validate_https_url(str(request.url))
        if parsed.hostname != self.origin or parsed.port not in (None, 443):
            raise OfficeError("office_model_endpoint_invalid", "模型请求目标与配置不一致。", 403)
        transport = self.transport
        if transport is None:
            async with asyncio.timeout(10):
                addresses = public_addresses(
                    await self.resolver(parsed.hostname, 443)
                )
            transport = PinnedAsyncHTTPTransport(parsed.hostname, addresses)
        response = None
        try:
            response = await transport.handle_async_request(request)
            await self.guard()
            if not 200 <= response.status_code < 300:
                status = response.status_code
                await response.aclose()
                await transport.aclose()
                # SDK errors may be logged. Never pass through vendor bodies containing credentials.
                return httpx.Response(
                    status,
                    json={
                        "error": {
                            "message": "Model provider rejected the request.",
                            "type": "provider_error",
                        }
                    },
                )
            headers = [
                (k, v)
                for k, v in response.headers.multi_items()
                if k.lower() not in {"content-encoding", "content-length"}
            ]
            return httpx.Response(
                response.status_code,
                headers=headers,
                stream=_BoundStream(response, transport, self.guard),
                extensions=response.extensions,
            )
        except BaseException:
            try:
                if response is not None:
                    await response.aclose()
            finally:
                await transport.aclose()
            raise


def native_chat_model(value, key, guard, *, transport=None):
    client = httpx.AsyncClient(
        transport=OfficeModelTransport(value["baseUrl"], guard, transport=transport),
        timeout=httpx.Timeout(120, connect=10),
        trust_env=False,
        follow_redirects=False,
    )
    model_type = (
        OpenAIResponses
        if value["provider"] == "openai" and re.match(r"^gpt-(?:5\.[4-9]|[6-9])", value["model"])
        else OpenAIChat
    )
    return model_type(
        id=value["model"],
        api_key=key,
        base_url=value["baseUrl"],
        http_client=client,
        timeout=120,
        max_retries=0,
    )
