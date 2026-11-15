"""Bounded HTTPS calls using the application's existing DNS-pinned transport."""

import asyncio

import httpx

from ..reporting.models import ReportingError
from .pinned_http import PinnedAsyncHTTPTransport, public_addresses, resolve, validate_https_url
from .repository import OfficeError


class ProviderHTTP:
    def __init__(self, *, transport=None, resolver=None):
        # Injectable transport is for protocol tests; production always resolves and pins.
        self.transport, self.resolver = transport, resolver or resolve

    async def request(
        self, method, url, *, headers=None, json=None, params=None, max_bytes=2 * 1024 * 1024
    ):
        try:
            async with asyncio.timeout(60):
                parsed = validate_https_url(url)
                if parsed.port not in (None, 443):
                    raise OfficeError("office_provider_url_invalid", "仅支持 HTTPS 443 端口。", 422)
                transport = self.transport
                if transport is None:
                    addresses = public_addresses(
                        await self.resolver(parsed.hostname, 443)
                    )
                    transport = PinnedAsyncHTTPTransport(parsed.hostname, addresses)
                async with httpx.AsyncClient(
                    transport=transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(45, connect=10),
                ) as client:
                    async with client.stream(
                        method, url, headers=headers, json=json, params=params
                    ) as response:
                        if not 200 <= response.status_code < 300:
                            raise OfficeError(
                                "office_provider_rejected",
                                f"提供商请求失败（HTTP {response.status_code}），请检查配置和配额。",
                                502,
                            )
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > max_bytes:
                                raise OfficeError(
                                    "office_provider_response_too_large",
                                    "提供商响应或媒体文件超过大小限制。",
                                    422,
                                )
                            body.extend(chunk)
                        return bytes(body), response.headers.get("content-type", "")
        except OfficeError:
            raise
        except (httpx.HTTPError, OSError, TimeoutError, ReportingError, ValueError):
            # Never surface URLs, signed query strings, keys or provider response bodies.
            raise OfficeError(
                "office_provider_connection_failed",
                "无法安全连接提供商或媒体地址，请检查 HTTPS 公网地址及网络。",
                502,
            ) from None
