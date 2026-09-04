"""Reporting Agent 的 AgentOS MCP 适配层。"""

from .adapter import ReportingMcpAdapter
from .contracts import (
    ReportingGetInput,
    ReportingOperationResult,
    ReportingReportRequest,
    ReportingReviewInput,
    ReportingStartInput,
)
from .tools import create_reporting_mcp_tools

__all__ = [
    "ReportingGetInput",
    "ReportingMcpAdapter",
    "ReportingOperationResult",
    "ReportingReportRequest",
    "ReportingReviewInput",
    "ReportingStartInput",
    "create_reporting_mcp_tools",
]
