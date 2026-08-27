"""Reporting Workflow runtime composition root."""

from .analysis import RuntimeAnalysisMixin
from .base import (
    REPORT_WORKFLOW_INPUT_STATE_KEY,
    REPORT_WORKFLOW_RESULT_STATE_KEY,
    _ReportWorkflowRuntimeBase,
)
from .datasets import RuntimeDatasetsMixin
from .planning import RuntimePlanningMixin
from .publication import RuntimePublicationMixin
from .sections import RuntimeSectionsMixin


class ReportWorkflowRuntime(
    RuntimePlanningMixin,
    RuntimeDatasetsMixin,
    RuntimeAnalysisMixin,
    RuntimeSectionsMixin,
    RuntimePublicationMixin,
    _ReportWorkflowRuntimeBase,
):
    """v1 报表运行时；数据库连接只存在于服务端 adapter 内。"""


__all__ = [
    "REPORT_WORKFLOW_INPUT_STATE_KEY",
    "REPORT_WORKFLOW_RESULT_STATE_KEY",
    "ReportWorkflowRuntime",
]
