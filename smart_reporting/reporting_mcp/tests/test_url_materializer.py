import asyncio
import socket
import threading
from typing import Any

import httpcore
import httpx
import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting_mcp.contracts import ReportingUrlAttachment
from smart_reporting.reporting_mcp.url_materializer import (
    UrlMaterializer,
    _PinnedNetworkBackend,
)


class _Workspace:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, bytes]] = []
        self.deletes: list[tuple[str, str, bool]] = []

    def upload(self, thread_id: str, path: str, content: bytes) -> None:
        self.uploads.append((thread_id, path, content))

    def delete_file(self, thread_id: str, path: str, recursive: bool = False) -> None:
        self.deletes.append((thread_id, path, recursive))


class _NetworkStream:
    def __init__(self, address: str) -> None:
        self.address = address

    def get_extra_info(self, name: str):
        return (self.address, 443) if name == "server_addr" else None


async def _public_dns(*_args):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


@pytest.mark.anyio
async def test_pinned_network_backend_connects_only_to_approved_address() -> None:
    calls: list[tuple[str, int]] = []
    stream = object()

    class Backend:
        async def connect_tcp(self, host: str, port: int, **_kwargs: Any):
            calls.append((host, port))
            return stream

        async def connect_unix_socket(self, *_args: Any, **_kwargs: Any):
            raise AssertionError("URL 下载不得使用 Unix socket")

        async def sleep(self, _seconds: float) -> None:
            return None

    backend = _PinnedNetworkBackend(
        "example.com",
        frozenset({"93.184.216.34"}),
        backend=Backend(),  # type: ignore[arg-type]
    )

    connected = await backend.connect_tcp("example.com", 443)

    assert connected is stream
    assert calls == [("93.184.216.34", 443)]
    with pytest.raises(httpcore.ConnectError):
        await backend.connect_tcp("other.example.com", 443)


@pytest.mark.anyio
async def test_url_materializer_uses_dns_pinned_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pinned: list[tuple[str, frozenset[str]]] = []

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/csv"},
            content=b"a\n1\n",
            extensions={"network_stream": _NetworkStream("93.184.216.34")},
        )

    def transport(hostname: str, addresses: frozenset[str]) -> httpx.AsyncBaseTransport:
        pinned.append((hostname, addresses))
        return httpx.MockTransport(handler)

    monkeypatch.setattr(
        "smart_reporting.reporting_mcp.url_materializer._PinnedAsyncHTTPTransport",
        transport,
    )
    materializer = UrlMaterializer(_Workspace(), resolver=_public_dns)

    await materializer.materialize(
        thread_id="thread-1",
        operation_id="operation-1",
        index=0,
        url="https://example.com/file.csv",
        filename="input.csv",
        expected_sha256=None,
    )

    assert pinned == [("example.com", frozenset({"93.184.216.34"}))]


@pytest.mark.anyio
async def test_url_materializer_enforces_total_download_deadline() -> None:
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0.05)
            yield b"a\n1\n"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/csv"},
            stream=SlowStream(),
            extensions={"network_stream": _NetworkStream("93.184.216.34")},
        )

    materializer = UrlMaterializer(
        _Workspace(),
        timeout_seconds=0.01,
        resolver=_public_dns,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ReportingError) as error:
        await materializer.materialize(
            thread_id="thread-1",
            operation_id="operation-1",
            index=0,
            url="https://example.com/file.csv",
            filename="input.csv",
            expected_sha256=None,
        )

    assert error.value.code == "report_attachment_download_timeout"


@pytest.mark.anyio
async def test_url_materializer_waits_for_blocking_upload_before_cancel_cleanup() -> None:
    started = threading.Event()
    release = threading.Event()
    events: list[str] = []

    class Workspace(_Workspace):
        def upload(self, thread_id: str, path: str, content: bytes) -> None:
            started.set()
            release.wait(timeout=1)
            events.append("upload")
            super().upload(thread_id, path, content)

        def delete_file(self, thread_id: str, path: str, recursive: bool = False) -> None:
            events.append("delete")
            super().delete_file(thread_id, path, recursive)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/csv"},
            content=b"a\n1\n",
            extensions={"network_stream": _NetworkStream("93.184.216.34")},
        )

    workspace = Workspace()
    materializer = UrlMaterializer(
        workspace,
        resolver=_public_dns,
        transport=httpx.MockTransport(handler),
    )
    task = asyncio.create_task(
        materializer.materialize_all(
            thread_id="thread-1",
            operation_id="operation-1",
            attachments=(
                ReportingUrlAttachment.model_validate({"url": "https://example.com/input.csv"}),
            ),
        )
    )
    await asyncio.to_thread(started.wait, 1)

    task.cancel()
    await asyncio.sleep(0.02)
    assert workspace.deletes == []
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert events == ["upload", "delete"]


def test_url_materializer_rejects_non_https() -> None:
    with pytest.raises(ReportingError) as error:
        UrlMaterializer._validate_url("http://example.com/file.csv")
    assert error.value.code == "report_attachment_url_invalid"


@pytest.mark.anyio
async def test_url_materializer_rejects_private_address() -> None:
    async def private_dns(*_args):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    materializer = UrlMaterializer(_Workspace(), resolver=private_dns)
    with pytest.raises(ReportingError) as error:
        await materializer.materialize(
            thread_id="thread-1",
            operation_id="operation-1",
            index=0,
            url="https://example.com/file.csv",
            filename=None,
            expected_sha256=None,
        )
    assert error.value.code == "report_attachment_url_forbidden"


@pytest.mark.anyio
async def test_url_materializer_streams_csv_with_pinned_peer() -> None:
    workspace = _Workspace()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "example.com"
        return httpx.Response(
            200,
            headers={"content-type": "text/csv", "content-length": "8"},
            content=b"a,b\n1,2\n",
            extensions={"network_stream": _NetworkStream("93.184.216.34")},
        )

    materializer = UrlMaterializer(
        workspace,
        resolver=_public_dns,
        transport=httpx.MockTransport(handler),
    )
    result = await materializer.materialize(
        thread_id="thread-1",
        operation_id="operation-1",
        index=0,
        url="https://example.com/file.csv",
        filename="input.csv",
        expected_sha256=None,
    )

    assert result["mediaType"] == "text/csv"
    assert workspace.uploads == [
        ("thread-1", "reporting-inputs/operation-1/0-input.csv", b"a,b\n1,2\n")
    ]


@pytest.mark.anyio
async def test_url_materializer_rejects_content_length_before_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = _Workspace()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/csv", "content-length": "9"},
            content=b"a,b\n1,2\n",
            extensions={"network_stream": _NetworkStream("93.184.216.34")},
        )

    monkeypatch.setattr(
        "smart_reporting.reporting_mcp.url_materializer.MAX_MCP_ATTACHMENT_BYTES", 8
    )
    materializer = UrlMaterializer(
        workspace,
        resolver=_public_dns,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ReportingError) as error:
        await materializer.materialize(
            thread_id="thread-1",
            operation_id="operation-1",
            index=0,
            url="https://example.com/file.csv",
            filename="input.csv",
            expected_sha256=None,
        )

    assert error.value.code == "report_attachment_too_large"
    assert workspace.uploads == []


@pytest.mark.anyio
async def test_url_materializer_rejects_dns_peer_change() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/csv"},
            content=b"a\n1\n",
            extensions={"network_stream": _NetworkStream("1.1.1.1")},
        )

    materializer = UrlMaterializer(
        _Workspace(),
        resolver=_public_dns,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ReportingError) as error:
        await materializer.materialize(
            thread_id="thread-1",
            operation_id="operation-1",
            index=0,
            url="https://example.com/file.csv",
            filename="input.csv",
            expected_sha256=None,
        )
    assert error.value.code == "report_attachment_url_changed"


@pytest.mark.anyio
async def test_url_materializer_checks_peer_before_http_status() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            headers={"content-type": "text/csv"},
            content=b"not found",
            extensions={"network_stream": _NetworkStream("127.0.0.1")},
        )

    materializer = UrlMaterializer(
        _Workspace(),
        resolver=_public_dns,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ReportingError) as error:
        await materializer.materialize(
            thread_id="thread-1",
            operation_id="operation-1",
            index=0,
            url="https://example.com/file.csv",
            filename="input.csv",
            expected_sha256=None,
        )

    assert error.value.code == "report_attachment_url_changed"


@pytest.mark.anyio
async def test_url_materializer_cleans_operation_after_batch_failure() -> None:
    workspace = _Workspace()

    async def handler(request: httpx.Request) -> httpx.Response:
        media_type = "text/csv" if request.url.path.endswith("ok.csv") else "application/json"
        return httpx.Response(
            200,
            headers={"content-type": media_type},
            content=b"a\n1\n",
            extensions={"network_stream": _NetworkStream("93.184.216.34")},
        )

    materializer = UrlMaterializer(
        workspace,
        resolver=_public_dns,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ReportingError) as error:
        await materializer.materialize_all(
            thread_id="thread-1",
            operation_id="operation-1",
            attachments=(
                ReportingUrlAttachment.model_validate({"url": "https://example.com/ok.csv"}),
                ReportingUrlAttachment.model_validate({"url": "https://example.com/fail.csv"}),
            ),
        )

    assert error.value.code == "report_attachment_type_unsupported"
    assert workspace.deletes == [("thread-1", "reporting-inputs/operation-1", True)]


@pytest.mark.anyio
async def test_url_materializer_reports_operation_cleanup_failure() -> None:
    class Workspace(_Workspace):
        def delete_file(self, thread_id: str, path: str, recursive: bool = False) -> None:
            raise RuntimeError("workspace delete failed")

    materializer = UrlMaterializer(Workspace())

    with pytest.raises(ReportingError) as error:
        await materializer.cleanup_operation("thread-1", "operation-1")

    assert error.value.code == "report_attachment_cleanup_failed"
