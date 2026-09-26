"""AgentOS 原生 run 请求的传输层资源边界。"""

from __future__ import annotations

from typing import Any, cast

from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header

MAX_AGENT_RUN_REQUEST_BYTES = 32 * 1024 * 1024
MAX_AGENT_RUN_CONTINUE_REQUEST_BYTES = 2 * 1024 * 1024
MAX_AGENT_RUN_FILE_BYTES = 24 * 1024 * 1024
MAX_AGENT_RUN_FILES = 8
# 编辑器 Markdown 上限 10 MiB，JSON 编码与其余字段留出余量。
MAX_REPORT_EDITOR_WRITE_REQUEST_BYTES = 12 * 1024 * 1024
_AGENTOS_COMPONENT_PATHS = frozenset({"agents", "teams", "workflows"})


class RequestBodyLimitError(ValueError):
    def __init__(self, code: str, *, status_code: int = 413):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class StreamingBodyLimit:
    def __init__(self) -> None:
        self.error: RequestBodyLimitError | None = None


def request_body_limit_error(error: BaseException) -> RequestBodyLimitError | None:
    if isinstance(error, RequestBodyLimitError):
        return error
    if not isinstance(error, BaseExceptionGroup):
        return None
    matched, remaining = error.split(RequestBodyLimitError)
    if matched is None or remaining is not None:
        return None
    for nested in matched.exceptions:
        limit_error = request_body_limit_error(nested)
        if limit_error is not None:
            return limit_error
    return None


def _run_path_parts(path: str, method: str) -> list[str] | None:
    if method.upper() != "POST":
        return None
    parts = [part for part in str(path or "").split("/") if part]
    if len(parts) < 3 or parts[0] not in _AGENTOS_COMPONENT_PATHS or parts[2] != "runs":
        return None
    return parts


def is_agentos_run_create(path: str, method: str) -> bool:
    parts = _run_path_parts(path, method)
    return parts is not None and len(parts) == 3


def agentos_run_request_limit(path: str, method: str) -> int | None:
    parts = _run_path_parts(path, method)
    if parts is None:
        return None
    if len(parts) == 3:
        return MAX_AGENT_RUN_REQUEST_BYTES
    if len(parts) == 5 and parts[4] == "continue":
        return MAX_AGENT_RUN_CONTINUE_REQUEST_BYTES
    return None


def report_editor_write_request_limit(path: str, method: str) -> int | None:
    """编辑器写接口先解析 JSON 再核验会话，必须在读取请求体前限定大小。"""

    if method.upper() in {"PUT", "POST"} and path.startswith("/reports/v1/editor/"):
        return MAX_REPORT_EDITOR_WRITE_REQUEST_BYTES
    return None


async def read_limited_body(request: Any, limit: int) -> bytes | None:
    content_length = request.headers.get("content-length")
    try:
        if content_length is not None and int(content_length) > limit:
            return None
    except ValueError:
        pass
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    body = b"".join(chunks)
    request._body = body
    return body


def install_streaming_body_limit(request: Any, limit: int) -> StreamingBodyLimit:
    """在 ASGI receive 边界累计请求体大小，同时保持消息流原样交给下游。"""

    content_length = request.headers.get("content-length")
    try:
        declared_bytes = int(content_length) if content_length is not None else None
    except ValueError:
        declared_bytes = None
    if declared_bytes is not None and declared_bytes > limit:
        raise RequestBodyLimitError("request_too_large")

    receive = request._receive
    received_bytes = 0
    state = StreamingBodyLimit()

    async def limited_receive() -> Any:
        nonlocal received_bytes
        message = await receive()
        if message["type"] != "http.request":
            return message
        received_bytes += len(message.get("body", b""))
        if received_bytes > limit:
            state.error = RequestBodyLimitError("request_too_large")
            raise state.error
        return message

    # Workspace 上传可接近 200 MiB。这里必须只包装 receive 并原样转发每个
    # ASGI 消息，不能调用 Request.body()/stream() 或设置 _body；否则中间件会
    # 在 Starlette multipart 临时文件之外再长期持有一份完整请求体。
    request._receive = limited_receive
    return state


def validate_agentos_run_multipart(content_type: str, body: bytes) -> None:
    """增量统计 multipart 文件元数据，不复制或保存文件正文。"""

    media_type, parameters = parse_options_header(content_type)
    if media_type != b"multipart/form-data":
        return
    boundary = parameters.get(b"boundary")
    if not boundary:
        raise RequestBodyLimitError("invalid_multipart", status_code=400)

    current_header_name = bytearray()
    current_header_value = bytearray()
    content_disposition = bytearray()
    current_is_file = False
    current_file_bytes = 0
    file_count = 0

    def on_part_begin() -> None:
        nonlocal current_is_file, current_file_bytes
        current_is_file = False
        current_file_bytes = 0
        content_disposition.clear()

    def on_header_field(data: bytes, start: int, end: int) -> None:
        current_header_name.extend(data[start:end])

    def on_header_value(data: bytes, start: int, end: int) -> None:
        current_header_value.extend(data[start:end])

    def on_header_end() -> None:
        if bytes(current_header_name).lower() == b"content-disposition":
            content_disposition.extend(current_header_value)
        current_header_name.clear()
        current_header_value.clear()

    def on_headers_finished() -> None:
        nonlocal current_is_file, file_count
        _disposition, options = parse_options_header(bytes(content_disposition))
        current_is_file = b"filename" in options
        if not current_is_file:
            return
        file_count += 1
        if file_count > MAX_AGENT_RUN_FILES:
            raise RequestBodyLimitError("too_many_files")

    def on_part_data(_data: bytes, start: int, end: int) -> None:
        nonlocal current_file_bytes
        if not current_is_file:
            return
        current_file_bytes += end - start
        if current_file_bytes > MAX_AGENT_RUN_FILE_BYTES:
            raise RequestBodyLimitError("file_too_large")

    callbacks: dict[str, Any] = {
        "on_part_begin": on_part_begin,
        "on_part_data": on_part_data,
        "on_part_end": lambda: None,
        "on_header_field": on_header_field,
        "on_header_value": on_header_value,
        "on_header_end": on_header_end,
        "on_headers_finished": on_headers_finished,
        "on_end": lambda: None,
    }
    try:
        parser = MultipartParser(boundary, cast(Any, callbacks))
        parser.write(body)
        parser.finalize()
    except RequestBodyLimitError:
        raise
    except (MultipartParseError, ValueError) as error:
        raise RequestBodyLimitError("invalid_multipart", status_code=400) from error
