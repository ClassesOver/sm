from typing import get_type_hints

import pytest
from agno.agent import Agent
from agno.os import AgentOS
from agno.os.config import MCPServerConfig
from agno.os.mcp import build_mcp_server
from fastmcp import FastMCP
from pydantic import ValidationError

from smart_reporting.reporting_mcp.contracts import (
    ReportingOperationResult,
    ReportingReportRequest,
    ReportingStartInput,
)
from smart_reporting.reporting_mcp.tools import create_reporting_mcp_tools


def test_start_contract_accepts_url_attachments() -> None:
    value = ReportingStartInput.model_validate(
        {
            "clientRequestId": "req-1",
            "threadId": "thread-1",
            "reportRequest": {
                "reportGoal": "分析",
                "period": {"start": "2026-01-01", "end": "2026-01-31"},
            },
            "attachments": [{"url": "https://example.com/a.csv", "filename": "a.csv"}],
        }
    )
    assert str(value.attachments[0].url).startswith("https://")


def test_start_contract_rejects_client_identity_fields() -> None:
    with pytest.raises(ValidationError):
        ReportingStartInput.model_validate(
            {
                "clientRequestId": "req-1",
                "threadId": "thread-1",
                "reportRequest": {},
                "userId": "spoofed",
            }
        )


def test_start_contract_rejects_direct_file_inputs() -> None:
    with pytest.raises(ValidationError):
        ReportingStartInput.model_validate(
            {
                "clientRequestId": "req-1",
                "threadId": "thread-1",
                "reportRequest": {
                    "reportGoal": "分析",
                    "period": {"start": "2026-01-01", "end": "2026-01-31"},
                    "fileInputs": [
                        {
                            "path": "绕过.csv",
                            "filename": "绕过.csv",
                            "size": 1,
                            "sha256": "0" * 64,
                        }
                    ],
                },
            }
        )


def test_mcp_tools_publish_strong_contracts_without_identity_arguments() -> None:
    tools = create_reporting_mcp_tools(object())  # type: ignore[arg-type]
    by_name = {tool.__name__: tool for tool in tools}

    assert set(by_name) == {
        "reporting_start",
        "reporting_get",
        "reporting_review",
        "reporting_cancel",
    }
    start_hints = get_type_hints(by_name["reporting_start"])
    review_hints = get_type_hints(by_name["reporting_review"])
    assert "user_id" not in start_hints
    assert start_hints["reportRequest"] is ReportingReportRequest
    assert start_hints["return"] is ReportingOperationResult
    assert "approve" in str(review_hints["action"])
    assert "reject" in str(review_hints["action"])


def test_completed_operation_contract_includes_html_preview() -> None:
    result = ReportingOperationResult.model_validate(
        {
            "ok": True,
            "operationId": "operation-1",
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
    )

    assert result.report is not None
    assert str(result.report.html.preview_url) == "https://reports.example.com/report.html"


@pytest.mark.anyio
async def test_fastmcp_tool_list_contains_closed_input_and_output_schema() -> None:
    server = FastMCP("reporting-test")
    for function in create_reporting_mcp_tools(object()):  # type: ignore[arg-type]
        server.add_tool(function)

    tools = {tool.name: tool for tool in await server.list_tools()}
    start_schema = tools["reporting_start"].parameters
    review_schema = tools["reporting_review"].parameters
    output_schema = tools["reporting_start"].output_schema

    assert start_schema["additionalProperties"] is False
    assert "fileInputs" not in start_schema["properties"]["reportRequest"]["properties"]
    assert review_schema["properties"]["action"]["enum"] == ["approve", "reject"]
    assert output_schema is not None
    assert output_schema["additionalProperties"] is False
    report_schema = output_schema["properties"]["report"]["anyOf"][0]
    assert "html" in report_schema["properties"]


@pytest.mark.anyio
async def test_agentos_embedded_mcp_exposes_only_reporting_tools() -> None:
    functions = create_reporting_mcp_tools(object())  # type: ignore[arg-type]
    agent_os = AgentOS(
        name="reporting-test",
        agents=[Agent(id="reporting-test-agent")],
        teams=[],
        workflows=[],
        mcp_server=MCPServerConfig(tools=functions, enable_builtin_tools=False),
        telemetry=False,
    )

    tools = await build_mcp_server(agent_os).list_tools()

    assert {tool.name for tool in tools} == {
        "reporting_start",
        "reporting_get",
        "reporting_review",
        "reporting_cancel",
    }
