"""Reporting Worker 工具的稳定装配入口。"""

__all__ = ["ReportWorkspaceTaskToolkit", "build_report_worker_tools"]


def __getattr__(name: str):
    if name == "build_report_worker_tools":
        from .factory import build_report_worker_tools

        return build_report_worker_tools
    if name == "ReportWorkspaceTaskToolkit":
        from .toolkit import ReportWorkspaceTaskToolkit

        return ReportWorkspaceTaskToolkit
    raise AttributeError(name)
