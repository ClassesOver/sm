"""Reporting 工具的稳定装配入口。"""

__all__ = ["ReportingToolkit", "build_reporting_tools"]


def __getattr__(name: str):
    if name == "build_reporting_tools":
        from .factory import build_reporting_tools

        return build_reporting_tools
    if name == "ReportingToolkit":
        from .toolkit import ReportingToolkit

        return ReportingToolkit
    raise AttributeError(name)
