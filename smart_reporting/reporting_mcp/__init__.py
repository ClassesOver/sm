"""旧四工具 Reporting MCP 适配层。

生产应用已使用 Agno 原生 Workflow 三工具
``run_reporting_workflow`` / ``continue_run`` / ``cancel_run``。这里保留的四工具只供旧协议
兼容和隔离测试使用，不得重新接入 ``smart_reporting.app`` 的公开 MCP 工具表面。
"""

from .adapter import ReportingMcpAdapter
from .contracts import (
    ReportingOperationResult,
    ReportingReportRequest,
    ReportingReviewInput,
    ReportingStartInput,
)
from .tools import create_reporting_mcp_tools

__all__ = [
    "ReportingMcpAdapter",
    "ReportingOperationResult",
    "ReportingReportRequest",
    "ReportingReviewInput",
    "ReportingStartInput",
    "create_reporting_mcp_tools",
]
