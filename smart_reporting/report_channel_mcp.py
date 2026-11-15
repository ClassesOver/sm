"""Opt-in MCP adapter for a private report-channel host."""

import re
from urllib.parse import urlsplit

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.tools.base import ToolResult
from httpx import ASGITransport, AsyncClient
from mcp.types import ResourceLink

from .report_channel_invitation import parse_channel_invitation


def create_report_channel_mcp(channel_app, *, origin: str) -> FastMCP:
    """Use the channel API's authenticator and authorization for every tool call."""
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("invalid_report_service_origin")
    server = FastMCP(
        "report-channel",
        instructions=(
            "When the user asks to join a shared report, pass the complete share link to "
            "join_report_channel. Use the returned channel for the conversation and Word tasks. "
            "Open editorUrl through the client's supported browser action if available, "
            "or present it as a link for the user. Fetching the URL as text does not open the editor. "
            "The browser requires a report editor session. If access is denied, ask the user to "
            "open the report through the host's normal sign-in and report access flow. "
            "After delegating a Word task, use "
            "report_word_task_status to check progress and present reviewUrl to the editor. "
            "The editor reviews, accepts and saves the candidate. Never ask for credentials in chat."
        ),
        tasks=False,
        strict_input_validation=True,
    )

    async def call(method: str, path: str, **kwargs):
        authorization = get_http_request().headers.get("authorization")
        if not authorization:
            raise ToolError("connector_authentication_required")
        async with AsyncClient(transport=ASGITransport(app=channel_app), base_url=origin,
                               headers={"Authorization": authorization}) as client:
            response = await client.request(method, path, **kwargs)
        if not response.is_success:
            raise ToolError(f"report_channel_request_failed_{response.status_code}")
        return response.json()

    def channel_path(channel: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", channel):
            raise ToolError("invalid_report_channel")
        return f"/reports/v1/channels/{channel}"

    @server.tool
    async def join_report_channel(share_link: str) -> ToolResult:
        """Join the shared report chat. Open editorUrl in an authorized report editor session."""
        try:
            reference = parse_channel_invitation(share_link, origin=origin)
        except ValueError:
            raise ToolError("invalid_report_channel_invitation") from None
        joined = await call("POST", "/reports/v1/channels/invitations/exchange", json={"reference": reference})
        if "editorPath" not in joined:
            raise ToolError("report_editor_unavailable")
        url = origin.rstrip("/") + joined["editorPath"]
        return ToolResult(
            content=[ResourceLink(type="resource_link", uri=url, name="报告编辑器")],
            structured_content={"channel": joined["channel"], "editorUrl": url},
        )

    @server.tool
    async def delegate_report_word_task(channel: str, request_id: str, instruction: str) -> ToolResult:
        """Ask the report assistant to generate a candidate within the authorized Word selection."""
        result = await call("POST", channel_path(channel) + "/word-tasks",
                            json={"request_id": request_id, "instruction": instruction})
        url = origin.rstrip("/") + result["reviewPath"]
        return ToolResult(
            content=[ResourceLink(type="resource_link", uri=url, name="审阅 Word 候选")],
            structured_content={**result, "reviewUrl": url},
        )

    @server.tool
    async def report_word_task_status(channel: str, task_id: str) -> dict:
        """Check candidate generation progress without reading candidate contents."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
            raise ToolError("invalid_report_word_task")
        return await call("GET", channel_path(channel) + f"/word-tasks/{task_id}")

    @server.tool
    async def read_report_channel(channel: str, after: int = 0) -> list[dict]:
        """Read messages after the supplied sequence cursor."""
        return await call("GET", channel_path(channel) + "/messages", params={"after": after})

    @server.tool
    async def post_report_channel_message(channel: str, message_id: str, text: str) -> list[dict]:
        """Send a message to the shared report chat."""
        return await call("POST", channel_path(channel) + "/messages",
                          json={"message_id": message_id, "text": text})

    return server
