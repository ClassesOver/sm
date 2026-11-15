"""出站 HTTPS 的 SSRF 边界：只连接预先解析并校验为公网的地址，保留原始 Host/SNI。

由已退役的报告附件下载器（reporting_mcp.url_materializer）中抽出，供 Office 提供商调用使用。
校验失败统一抛出 ValueError，由调用方转换为不含 URL、密钥或响应正文的业务错误。
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from typing import Any
from urllib.parse import ParseResult, urlparse

import httpcore
import httpx

_NAT64_NETWORKS = (
    ipaddress.IPv6Network("64:ff9b::/96"),
    ipaddress.IPv6Network("64:ff9b:1::/48"),
)
_IPV4_COMPATIBLE_NETWORK = ipaddress.IPv6Network("::/96")


def _embedded_ipv4_is_global(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """NAT64 与 IPv4 兼容地址被 ipaddress 视为公网，但实际会路由到内嵌的 IPv4。"""

    if not isinstance(ip, ipaddress.IPv6Address):
        return True
    if any(ip in network for network in (*_NAT64_NETWORKS, _IPV4_COMPATIBLE_NETWORK)):
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF).is_global
    return True


def validate_https_url(value: str) -> ParseResult:
    """只接受无凭据、无 fragment 的 HTTPS 地址。"""

    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname:
        raise ValueError("outbound_url_invalid")
    if parsed.fragment:
        raise ValueError("outbound_url_invalid")
    return parsed


async def resolve(host: str, port: int) -> list[Any]:
    return await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)


def public_addresses(addresses: list[Any]) -> frozenset[str]:
    """解析结果必须全部是公网地址；任一受限地址都拒绝整个请求。"""

    resolved: set[str] = set()
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address[4][0])
        except (IndexError, TypeError, ValueError) as error:
            raise ValueError("outbound_url_unreachable") from error
        if not ip.is_global or not _embedded_ipv4_is_global(ip):
            raise ValueError("outbound_url_forbidden")
        resolved.add(ip.compressed)
    if not resolved:
        raise ValueError("outbound_url_unreachable")
    return frozenset(resolved)


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """保留原始 HTTPS Host/SNI，但只允许 TCP 连接到预先校验过的公网地址。"""

    def __init__(
        self,
        hostname: str,
        addresses: frozenset[str],
        *,
        backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._hostname = hostname.rstrip(".").lower()
        self._addresses = tuple(sorted(addresses))
        self._backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[tuple[Any, ...]] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if host.rstrip(".").lower() != self._hostname:
            raise httpcore.ConnectError("出站连接目标与已校验域名不一致")
        last_error: Exception | None = None
        for address in self._addresses:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as error:
                last_error = error
        if last_error is not None:
            raise last_error
        raise httpcore.ConnectError("出站连接没有可用的已校验地址")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[tuple[Any, ...]] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("出站连接不允许 Unix socket")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self, hostname: str, addresses: frozenset[str]) -> None:
        super().__init__(trust_env=False)
        # httpcore 的 network_backend 是公开连接扩展点；连接池继续负责 TLS、SNI、
        # HTTP 解析和证书验证，不重复实现 HTTP 客户端。
        self._pool = httpcore.AsyncConnectionPool(
            max_connections=1,
            max_keepalive_connections=0,
            network_backend=_PinnedNetworkBackend(hostname, addresses),
        )


__all__ = ["PinnedAsyncHTTPTransport", "public_addresses", "resolve", "validate_https_url"]
