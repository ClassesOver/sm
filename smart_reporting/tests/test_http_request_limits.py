from __future__ import annotations

import pytest
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from smart_reporting import http_request_limits
from smart_reporting.http_request_limits import (
    RequestBodyLimitError,
    agentos_run_request_limit,
    is_agentos_run_create,
    read_limited_body,
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
