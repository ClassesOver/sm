from __future__ import annotations

import pytest
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from smart_reporting.http import request_limits as http_request_limits
from smart_reporting.http.request_limits import (
    RequestBodyLimitError,
    agentos_run_request_limit,
    install_streaming_body_limit,
    is_agentos_run_create,
    read_limited_body,
    request_body_limit_error,
    validate_agentos_run_multipart,
)


def _multipart(*files: tuple[str, bytes], boundary: str = "boundary") -> tuple[str, bytes]:
    parts: list[bytes] = []
    for filename, content in files:
        parts.extend(
            (
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
                ).encode(),
                b"Content-Type: text/plain\r\n\r\n",
                content,
                b"\r\n",
            )
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/agents/smart-reporting/runs", http_request_limits.MAX_AGENT_RUN_REQUEST_BYTES),
        ("/teams/report-team/runs", http_request_limits.MAX_AGENT_RUN_REQUEST_BYTES),
        ("/workflows/report-workflow/runs", http_request_limits.MAX_AGENT_RUN_REQUEST_BYTES),
        (
            "/agents/smart-reporting/runs/run-1/continue",
            http_request_limits.MAX_AGENT_RUN_CONTINUE_REQUEST_BYTES,
        ),
        ("/workspace/upload", None),
    ],
)
def test_agentos_run_request_limit_covers_creation_and_continuation(
    path: str, expected: int | None
) -> None:
    assert agentos_run_request_limit(path, "POST") == expected
    assert agentos_run_request_limit(path, "GET") is None


def test_agentos_run_request_limit_preserves_larger_run_limits() -> None:
    assert agentos_run_request_limit("/agents/smart-reporting/runs", "POST") == (
        http_request_limits.MAX_AGENT_RUN_REQUEST_BYTES
    )
    assert agentos_run_request_limit("/agents/smart-reporting/runs/run-1/continue", "POST") == (
        http_request_limits.MAX_AGENT_RUN_CONTINUE_REQUEST_BYTES
    )


def test_agentos_run_multipart_limits_file_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_request_limits, "MAX_AGENT_RUN_FILES", 2)
    content_type, body = _multipart(("a.txt", b"a"), ("b.txt", b"b"), ("c.txt", b"c"))

    with pytest.raises(RequestBodyLimitError) as raised:
        validate_agentos_run_multipart(content_type, body)

    assert raised.value.code == "too_many_files"


def test_agentos_run_multipart_limits_individual_file_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http_request_limits, "MAX_AGENT_RUN_FILE_BYTES", 4)
    content_type, body = _multipart(("large.txt", b"12345"))

    with pytest.raises(RequestBodyLimitError) as raised:
        validate_agentos_run_multipart(content_type, body)

    assert raised.value.code == "file_too_large"


def _streaming_request(
    messages: list[dict[str, object]], *, content_length: int | None = None
) -> tuple[Request, list[dict[str, object]]]:
    received: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        message = messages[len(received)]
        received.append(message)
        return message

    headers = []
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/workspace/upload",
            "raw_path": b"/workspace/upload",
            "query_string": b"",
            "headers": headers,
            "client": ("test", 123),
            "server": ("test", 80),
        },
        receive,
    )
    return request, received


@pytest.mark.anyio
async def test_streaming_body_limit_preserves_chunks_without_caching_body() -> None:
    messages: list[dict[str, object]] = [
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"def", "more_body": False},
    ]
    request, received = _streaming_request(messages)

    install_streaming_body_limit(request, 6)
    body = b"".join([chunk async for chunk in request.stream()])

    assert body == b"abcdef"
    assert received == messages
    assert not hasattr(request, "_body")


@pytest.mark.anyio
async def test_streaming_body_limit_stops_when_chunks_exceed_limit() -> None:
    messages: list[dict[str, object]] = [
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"def", "more_body": True},
        {"type": "http.request", "body": b"unused", "more_body": False},
    ]
    request, received = _streaming_request(messages)
    install_streaming_body_limit(request, 5)

    with pytest.raises(RequestBodyLimitError) as raised:
        _ = [chunk async for chunk in request.stream()]

    assert raised.value.code == "request_too_large"
    assert received == messages[:2]
    assert not hasattr(request, "_body")


def test_streaming_body_limit_rejects_oversized_content_length_before_reading() -> None:
    request, received = _streaming_request([], content_length=6)

    with pytest.raises(RequestBodyLimitError) as raised:
        install_streaming_body_limit(request, 5)

    assert raised.value.code == "request_too_large"
    assert received == []


@pytest.mark.anyio
async def test_streaming_body_limit_middleware_returns_413_for_chunked_body() -> None:
    application = FastAPI()

    @application.middleware("http")
    async def enforce_limit(request: Request, call_next):
        streaming_limit = install_streaming_body_limit(request, accepted_size)
        try:
            response = await call_next(request)
        except (RequestBodyLimitError, BaseExceptionGroup) as error:
            limit_error = request_body_limit_error(error)
            if limit_error is None:
                raise
            return JSONResponse({"error": limit_error.code}, status_code=limit_error.status_code)
        if streaming_limit.error is not None:
            return JSONResponse(
                {"error": streaming_limit.error.code},
                status_code=streaming_limit.error.status_code,
            )
        return response

    @application.post("/workspace/upload")
    async def upload(file: UploadFile = File(...)):
        return {"body": (await file.read()).decode()}

    def multipart(content: bytes) -> bytes:
        return b"".join(
            (
                b"--boundary\r\n",
                b'Content-Disposition: form-data; name="file"; filename="a.txt"\r\n',
                b"Content-Type: text/plain\r\n\r\n",
                content,
                b"\r\n--boundary--\r\n",
            )
        )

    accepted_body = multipart(b"abcdef")
    rejected_body = multipart(b"abcdefg")
    accepted_size = len(accepted_body)

    async def accepted_chunks():
        yield accepted_body[:20]
        yield accepted_body[20:]

    async def rejected_chunks():
        yield rejected_body[:20]
        yield rejected_body[20:]

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        headers = {"content-type": "multipart/form-data; boundary=boundary"}
        accepted = await client.post(
            "/workspace/upload", content=accepted_chunks(), headers=headers
        )
        rejected = await client.post(
            "/workspace/upload", content=rejected_chunks(), headers=headers
        )

    assert accepted.status_code == 200
    assert accepted.json() == {"body": "abcdef"}
    assert rejected.status_code == 413
    assert rejected.json() == {"error": "request_too_large"}


@pytest.mark.anyio
async def test_agentos_run_middleware_preserves_multipart_for_downstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http_request_limits, "MAX_AGENT_RUN_REQUEST_BYTES", 1024)
    application = FastAPI()

    @application.middleware("http")
    async def enforce_limit(request: Request, call_next):
        limit = agentos_run_request_limit(request.url.path, request.method)
        body = await read_limited_body(request, limit) if limit else b""
        if body is None:
            return JSONResponse({"error": "request_too_large"}, status_code=413)
        if body and is_agentos_run_create(request.url.path, request.method):
            try:
                validate_agentos_run_multipart(request.headers.get("content-type", ""), body)
            except RequestBodyLimitError as error:
                return JSONResponse({"error": error.code}, status_code=error.status_code)
        return await call_next(request)

    @application.post("/agents/smart-reporting/runs")
    async def run(files: list[UploadFile] = File(...)):
        return {"sizes": [len(await item.read()) for item in files]}

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        accepted = await client.post(
            "/agents/smart-reporting/runs",
            files=[("files", ("ok.txt", b"content", "text/plain"))],
        )
        rejected = await client.post(
            "/agents/smart-reporting/runs",
            content=b"x" * 1025,
            headers={"content-type": "application/octet-stream"},
        )

    assert accepted.status_code == 200
    assert accepted.json() == {"sizes": [7]}
    assert rejected.status_code == 413
    assert rejected.json() == {"error": "request_too_large"}
