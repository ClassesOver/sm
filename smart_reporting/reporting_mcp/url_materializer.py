from __future__ import annotations

import asyncio
import hashlib
import io
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import urlparse

import httpcore
import httpx
import polars as pl

from ..reporting.models import ReportingError
from ..workspace import MAX_UPLOAD_BYTES
from .contracts import ReportingUrlAttachment

MAX_MCP_ATTACHMENT_BYTES = min(MAX_UPLOAD_BYTES, 50 * 1024 * 1024)
MAX_MCP_ATTACHMENTS_TOTAL_BYTES = 200 * 1024 * 1024
_DOWNLOAD_CONCURRENCY = 2
# 255 字节文件名上限，预留 "{index}-" 前缀。
_MAX_FILENAME_BYTES = 240
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
            raise httpcore.ConnectError("附件下载连接目标与已校验域名不一致")
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
        raise httpcore.ConnectError("附件下载没有可用的已校验地址")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[tuple[Any, ...]] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("附件下载不允许 Unix socket")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self, hostname: str, addresses: frozenset[str]) -> None:
        super().__init__(trust_env=False)
        # httpcore 的 network_backend 是其公开连接扩展点；连接池继续负责 TLS、SNI、
        # HTTP 解析和证书验证，避免在 Reporting 内重复实现 HTTP 客户端。
        self._pool = httpcore.AsyncConnectionPool(
            max_connections=1,
            max_keepalive_connections=0,
            network_backend=_PinnedNetworkBackend(hostname, addresses),
        )


class WorkspaceWriter(Protocol):
    def upload(self, thread: str, path: str, content: bytes) -> Any: ...

    def delete_file(self, thread: str, path: str, recursive: bool = False) -> Any: ...


class UrlMaterializer:
    """将受控 HTTPS URL 下载到 thread workspace，并返回稳定文件身份。"""

    def __init__(
        self,
        workspace: WorkspaceWriter,
        *,
        timeout_seconds: float = 20.0,
        resolver: Callable[..., Awaitable[list[Any]]] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.workspace = workspace
        self._timeout_seconds = timeout_seconds
        self.timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))
        self._resolver = resolver or self._resolve
        self._transport = transport

    async def materialize_all(
        self,
        *,
        thread_id: str,
        operation_id: str,
        attachments: tuple[ReportingUrlAttachment, ...],
    ) -> tuple[dict[str, object], ...]:
        results: list[dict[str, object] | None] = [None] * len(attachments)
        limiter = asyncio.Semaphore(_DOWNLOAD_CONCURRENCY)

        async def materialize_one(index: int, item: ReportingUrlAttachment) -> None:
            async with limiter:
                results[index] = await self.materialize(
                    thread_id=thread_id,
                    operation_id=operation_id,
                    index=index,
                    url=str(item.url),
                    filename=item.filename,
                    expected_sha256=item.sha256,
                )

        try:
            async with asyncio.TaskGroup() as group:
                for index, item in enumerate(attachments):
                    group.create_task(materialize_one(index, item))
            completed = tuple(item for item in results if item is not None)
            if len(completed) != len(attachments):
                raise ReportingError(
                    "report_attachment_download_failed", "报表附件下载结果不完整。"
                )
            sizes = [item.get("size") for item in completed]
            if any(not isinstance(size, int) for size in sizes):
                raise ReportingError("report_attachment_download_failed", "报表附件下载结果无效。")
            if (
                sum(size for size in sizes if isinstance(size, int))
                > MAX_MCP_ATTACHMENTS_TOTAL_BYTES
            ):
                raise ReportingError(
                    "report_attachment_total_too_large", "报表附件总大小超过允许限制。"
                )
            return completed
        except BaseException as error:
            await self.cleanup_operation(thread_id, operation_id)
            if isinstance(error, asyncio.CancelledError):
                raise
            failure = self._first_reporting_error(error)
            if failure is not None:
                raise failure
            raise ReportingError(
                "report_attachment_download_failed", "报表附件批量下载失败。"
            ) from error

    async def materialize(
        self,
        *,
        thread_id: str,
        operation_id: str,
        index: int,
        url: str,
        filename: str | None,
        expected_sha256: str | None,
    ) -> dict[str, object]:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await self._materialize_within_deadline(
                    thread_id=thread_id,
                    operation_id=operation_id,
                    index=index,
                    url=url,
                    filename=filename,
                    expected_sha256=expected_sha256,
                )
        except TimeoutError as error:
            raise ReportingError(
                "report_attachment_download_timeout", "报表附件下载超时。"
            ) from error

    async def _materialize_within_deadline(
        self,
        *,
        thread_id: str,
        operation_id: str,
        index: int,
        url: str,
        filename: str | None,
        expected_sha256: str | None,
    ) -> dict[str, object]:
        parsed = self._validate_url(url)
        assert parsed.hostname is not None
        port = parsed.port or 443
        try:
            addresses = await self._resolver(parsed.hostname, port)
        except OSError as error:
            raise ReportingError(
                "report_attachment_url_unreachable", "报表附件 URL 无法解析。"
            ) from error
        public_addresses = self._public_addresses(addresses)
        transport = self._transport or _PinnedAsyncHTTPTransport(parsed.hostname, public_addresses)
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client:
                async with client.stream("GET", url) as response:
                    self._validate_peer(response, public_addresses)
                    response.raise_for_status()
                    media_type = self._validate_media_type(response)
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            announced_size = int(content_length)
                        except ValueError as error:
                            raise ReportingError(
                                "report_attachment_response_invalid",
                                "报表附件响应的 Content-Length 无效。",
                            ) from error
                        if announced_size < 0 or announced_size > MAX_MCP_ATTACHMENT_BYTES:
                            raise ReportingError(
                                "report_attachment_too_large", "报表附件超过允许大小。"
                            )
                    buffer = bytearray()
                    async for chunk in response.aiter_bytes():
                        buffer.extend(chunk)
                        if len(buffer) > MAX_MCP_ATTACHMENT_BYTES:
                            raise ReportingError(
                                "report_attachment_too_large", "报表附件超过允许大小。"
                            )
        except httpx.HTTPError as error:
            raise ReportingError(
                "report_attachment_download_failed", "报表附件下载失败。"
            ) from error
        content = bytes(buffer)
        self._validate_csv(content)
        digest = hashlib.sha256(content).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256.lower():
            raise ReportingError("report_attachment_hash_mismatch", "报表附件 hash 校验失败。")
        safe_name = self._safe_filename(
            filename or PurePosixPath(parsed.path).name or f"attachment-{index}.csv"
        )
        path = f"reporting-inputs/{operation_id}/{index}-{safe_name}"
        await self._upload_before_propagating_cancel(thread_id, path, content)
        return {
            "path": path,
            "filename": safe_name,
            "size": len(content),
            "sha256": digest,
            "mediaType": media_type,
        }

    async def _upload_before_propagating_cancel(
        self, thread_id: str, path: str, content: bytes
    ) -> None:
        upload = asyncio.create_task(
            asyncio.to_thread(self.workspace.upload, thread_id, path, content)
        )
        try:
            await asyncio.shield(upload)
        except BaseException:
            # to_thread 已开始后无法被协程取消。必须等它真正结束，外层才能删除整个
            # operation 目录；否则线程可能在清理之后重新写回一个未登记附件。
            await asyncio.gather(upload, return_exceptions=True)
            raise

    @staticmethod
    def _safe_filename(value: str) -> str:
        name = PurePosixPath(value).name.replace("\x00", "")
        if (
            not name
            or name in {".", ".."}
            or "\\" in name
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
        ):
            raise ReportingError("report_attachment_filename_invalid", "报表附件文件名无效。")
        if PurePosixPath(name).suffix.lower() != ".csv":
            raise ReportingError(
                "report_attachment_type_unsupported", "Reporting URL 附件仅支持 CSV。"
            )
        # 文件系统限制的是字节数；落盘名还带有 "{index}-" 前缀，按 UTF-8 字节截断。
        stem = name[: -len(".csv")]
        while len(f"{stem}.csv".encode()) > _MAX_FILENAME_BYTES:
            stem = stem[:-1]
        return f"{stem}.csv"

    @staticmethod
    def _validate_url(value: str):
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname:
            raise ReportingError(
                "report_attachment_url_invalid", "报表附件 URL 必须是无凭据的 HTTPS 地址。"
            )
        if parsed.fragment:
            raise ReportingError(
                "report_attachment_url_invalid", "报表附件 URL 不得包含 fragment。"
            )
        return parsed

    @staticmethod
    async def _resolve(host: str, port: int) -> list[Any]:
        return await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)

    @staticmethod
    def _public_addresses(addresses: list[Any]) -> frozenset[str]:
        resolved: set[str] = set()
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address[4][0])
            except (IndexError, TypeError, ValueError) as error:
                raise ReportingError(
                    "report_attachment_url_unreachable", "报表附件 URL 解析结果无效。"
                ) from error
            if not ip.is_global or not _embedded_ipv4_is_global(ip):
                raise ReportingError(
                    "report_attachment_url_forbidden", "报表附件 URL 指向受限地址。"
                )
            resolved.add(ip.compressed)
        if not resolved:
            raise ReportingError("report_attachment_url_unreachable", "报表附件 URL 无法解析。")
        return frozenset(resolved)

    @staticmethod
    def _validate_peer(response: httpx.Response, resolved: frozenset[str]) -> None:
        stream = response.extensions.get("network_stream")
        peer = (
            stream.get_extra_info("server_addr")
            if stream is not None and hasattr(stream, "get_extra_info")
            else None
        )
        if not isinstance(peer, (list, tuple)) or not peer:
            raise ReportingError(
                "report_attachment_peer_unavailable",
                "无法确认报表附件的实际连接地址。",
            )
        try:
            connected = ipaddress.ip_address(peer[0]).compressed
        except (IndexError, TypeError, ValueError) as error:
            raise ReportingError(
                "report_attachment_peer_unavailable",
                "无法确认报表附件的实际连接地址。",
            ) from error
        if connected not in resolved:
            raise ReportingError(
                "report_attachment_url_changed",
                "报表附件 URL 的解析地址在连接前发生变化。",
            )

    @staticmethod
    def _validate_media_type(response: httpx.Response) -> str:
        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media_type not in {
            "text/csv",
            "application/csv",
            "application/vnd.ms-excel",
            "application/octet-stream",
        }:
            raise ReportingError(
                "report_attachment_type_unsupported", "Reporting URL 附件仅支持 CSV。"
            )
        return "text/csv"

    @staticmethod
    def _validate_csv(content: bytes) -> None:
        if not content:
            raise ReportingError("report_attachment_csv_invalid", "CSV 附件不能为空。")
        try:
            frame = pl.read_csv(io.BytesIO(content), n_rows=1)
        except (UnicodeDecodeError, pl.exceptions.PolarsError) as error:
            raise ReportingError("report_attachment_csv_invalid", "CSV 附件格式无效。") from error
        if not frame.columns:
            raise ReportingError("report_attachment_csv_invalid", "CSV 附件缺少表头。")

    async def cleanup_operation(self, thread_id: str, operation_id: str) -> None:
        delete = getattr(self.workspace, "delete_file", None)
        if not callable(delete):
            return
        try:
            await asyncio.to_thread(
                delete,
                thread_id,
                f"reporting-inputs/{operation_id}",
                True,
            )
        except Exception as error:
            raise ReportingError(
                "report_attachment_cleanup_failed",
                "报表附件目录清理失败。",
            ) from error

    @classmethod
    def _first_reporting_error(cls, error: BaseException) -> ReportingError | None:
        if isinstance(error, ReportingError):
            return error
        if isinstance(error, BaseExceptionGroup):
            for nested in error.exceptions:
                failure = cls._first_reporting_error(nested)
                if failure is not None:
                    return failure
        return None
