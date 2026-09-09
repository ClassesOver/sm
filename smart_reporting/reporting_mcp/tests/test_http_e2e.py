from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import socket
import time
from typing import Any

import pytest
import uvicorn
from agno.agent import Agent
from agno.os import AgentOS
from agno.os.config import MCPServerConfig
from fastmcp import Client

from smart_reporting.reporting_mcp.adapter import ReportingMcpAdapter
from smart_reporting.reporting_mcp.identity import CapabilityTokenVerifier
from smart_reporting.reporting_mcp.tools import create_reporting_mcp_tools


def _segment(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _capability(secret: str, *, thread_id: str) -> str:
    now = int(time.time())
    header = _segment({"alg": "HS256", "typ": "WORKSPACE-CAP"})
    claims = _segment(
        {
            "aud": "agentos-workspace",
            "iat": now,
            "exp": now + 300,
            "database": "odoo",
            "user": 7,
            "company": 11,
            "odoo_session": "a" * 64,
            "thread": thread_id,
        }
    )
    payload = f"{header}.{claims}"
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return f"{payload}.{signature}"


class _Controller:
    def __init__(self) -> None:
        self.scopes: list[tuple[str, str, str, str]] = []

    def _record_scope(self, values: dict[str, Any]) -> None:
        self.scopes.append(
            (
                values["thread_id"],
                values["user_id"],
                values["database"],
                values["company_id"],
            )
        )

    async def start_external_background(self, _payload: Any, **values: Any) -> dict[str, Any]:
        values.pop("prepare")
        values.pop("prepared_input_cleanup")
        values.pop("request_fingerprint")
        self._record_scope(values)
        return {"ok": True, "status": "running"}

    async def get_external(self, **values: Any) -> dict[str, Any]:
        values.pop("external_run_id")
        self._record_scope(values)
        return {
            "ok": True,
            "status": "completed",
            "report": {
                "reportId": "report-1",
                "revision": 1,
                "pdf": {
                    "downloadUrl": "https://reports.example.com/report.pdf",
                    "expiresAt": "2026-10-09T00:00:00Z",
                    "size": 12,
                    "sha256": "a" * 64,
                },
                "word": {
                    "downloadUrl": "https://reports.example.com/report.docx",
                    "expiresAt": "2026-10-09T00:00:00Z",
                    "size": 14,
                    "sha256": "b" * 64,
                },
                "html": {
                    "previewUrl": "https://reports.example.com/report.html",
                    "expiresAt": "2026-10-09T00:00:00Z",
                },
            },
        }

    async def external_context(self, **values: Any) -> object:
        values.pop("external_run_id")
        self._record_scope(values)
        return object()

    async def reject(self, feedback: str, _context: object) -> dict[str, Any]:
        assert feedback == "需要补充说明"
        return {"ok": True, "status": "running"}

    async def cancel_external(self, **values: Any) -> dict[str, Any]:
        values.pop("external_run_id")
        self._record_scope(values)
        return {"ok": True, "status": "cancelled"}


async def _start_http_server(app: Any) -> tuple[uvicorn.Server, asyncio.Task[None], int]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.setblocking(False)
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", access_log=False, lifespan="on")
    )
    task = asyncio.create_task(server.serve(sockets=[listener]))
    for _ in range(100):
        if server.started:
            return server, task, port
        if task.done():
            await task
        await asyncio.sleep(0.01)
    server.should_exit = True
    await task
    raise RuntimeError("MCP HTTP 测试服务启动超时")


@pytest.mark.anyio
async def test_reporting_tools_work_over_authenticated_streamable_http() -> None:
    secret = "s" * 32
    thread_id = "thread-1"
    controller = _Controller()
    adapter = ReportingMcpAdapter(controller, object())  # type: ignore[arg-type]
    agent_os = AgentOS(
        name="reporting-http-test",
        agents=[Agent(id="reporting-http-test-agent")],
        teams=[],
        workflows=[],
        mcp_server=MCPServerConfig(
            tools=create_reporting_mcp_tools(adapter),
            enable_builtin_tools=False,
        ),
        mcp_auth=CapabilityTokenVerifier(secret),
        telemetry=False,
    )
    logger_names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    logger_states = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
            logging.getLogger(name).disabled,
        )
        for name in logger_names
    }
    server, server_task, port = await _start_http_server(agent_os.get_app())
    try:
        async with Client(
            f"http://127.0.0.1:{port}/mcp",
            auth=_capability(secret, thread_id=thread_id),
        ) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools} == {
                "reporting_start",
                "reporting_get",
                "reporting_review",
                "reporting_cancel",
            }

            started = await client.call_tool(
                "reporting_start",
                {
                    "clientRequestId": "request-1",
                    "threadId": thread_id,
                    "reportRequest": {
                        "reportGoal": "分析月度运营",
                        "period": {"start": "2026-01-01", "end": "2026-01-31"},
                    },
                },
            )
            assert started.structured_content is not None
            operation_id = started.structured_content["operationId"]
            assert started.structured_content["status"] == "running"

            completed = await client.call_tool(
                "reporting_get",
                {"operationId": operation_id, "threadId": thread_id},
            )
            assert completed.structured_content is not None
            assert completed.structured_content["report"]["html"]["previewUrl"] == (
                "https://reports.example.com/report.html"
            )

            reviewed = await client.call_tool(
                "reporting_review",
                {
                    "operationId": operation_id,
                    "threadId": thread_id,
                    "action": "reject",
                    "feedback": "需要补充说明",
                },
            )
            assert reviewed.structured_content is not None
            assert reviewed.structured_content["status"] == "running"

            cancelled = await client.call_tool(
                "reporting_cancel",
                {"operationId": operation_id, "threadId": thread_id},
            )
            assert cancelled.structured_content is not None
            assert cancelled.structured_content["status"] == "cancelled"
    finally:
        server.should_exit = True
        await server_task
        for name, (handlers, level, propagate, disabled) in logger_states.items():
            logger = logging.getLogger(name)
            logger.handlers[:] = handlers
            logger.setLevel(level)
            logger.propagate = propagate
            logger.disabled = disabled

    assert controller.scopes == [(thread_id, "7", "odoo", "11")] * 4
